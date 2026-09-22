from datetime import UTC, datetime, timedelta

from gtmos.domain.routing import RuleSpec, UserFacts, pick_least_loaded, route
from gtmos.domain.rules import Condition

C = Condition
USERS = [
    UserFacts("ae1", "Avery Enterprise", "Enterprise NA", True, 40, 30),
    UserFacts("ae2", "Blake Enterprise", "Enterprise NA", True, 40, 12),
    UserFacts("sae", "Sam Senior", "Strategic", True, 25, 20),
    UserFacts("sdr1", "Casey SDR", "SDR Pool", True, 150, 149),
    UserFacts("sdr2", "Drew SDR", "SDR Pool", True, 150, 149),
    UserFacts("am1", "Morgan AM", "Account Management", True, 80, 10),
    UserFacts("gone", "Former Rep", "Enterprise NA", False, 40, 0),
]
RULES = [
    RuleSpec(
        "existing-customer",
        "Existing customer → AM",
        10,
        (C(field="account.is_customer", op="eq", value=True),),
        "pool_least_loaded",
        assign_team="Account Management",
        overrides_existing_owner=True,
    ),
    RuleSpec(
        "strategic-high-intent",
        "High-intent strategic → Senior AE",
        20,
        (
            C(field="account.segment", op="in", value=["strategic", "enterprise"]),
            C(field="account.intent_score", op="gte", value=70),
        ),
        "user",
        assign_user_id="sae",
    ),
    RuleSpec(
        "enterprise-na",
        "Enterprise NA → AE",
        30,
        (
            C(field="account.segment", op="in", value=["strategic", "enterprise"]),
            C(field="account.region", op="eq", value="NA"),
        ),
        "pool_least_loaded",
        assign_team="Enterprise NA",
    ),
    RuleSpec(
        "smb",
        "SMB & mid-market → SDR pool",
        50,
        (C(field="account.segment", op="in", value=["smb", "mid_market"]),),
        "pool_least_loaded",
        assign_team="SDR Pool",
    ),
]


def ctx(**kw):
    base = {"segment": "enterprise", "region": "NA", "intent_score": 40, "is_customer": False, "owner_id": None}
    return {"account": {**base, **kw}}


def test_enterprise_na_goes_to_least_loaded_ae():
    out = route(RULES, ctx(), USERS)
    assert out.outcome == "assigned" and out.rule_key == "enterprise-na"
    assert out.assigned_user_id == "ae2"
    assert any("Least-loaded" in e for e in out.explanation)


def test_high_intent_strategic_beats_territory_rule_and_records_conflict():
    out = route(RULES, ctx(intent_score=85), USERS)
    assert out.rule_key == "strategic-high-intent" and out.assigned_user_id == "sae"
    assert len(out.conflicts) == 1
    assert out.conflicts[0]["rule"] == "enterprise-na"
    assert "lower priority" in out.conflicts[0]["lost_because"]


def test_same_priority_tie_broken_by_specificity_then_key():
    r1 = RuleSpec("b-rule", "B", 5, (C(field="account.region", op="eq", value="NA"),), "user", assign_user_id="ae1")
    r2 = RuleSpec("a-rule", "A", 5, (C(field="account.region", op="eq", value="NA"),), "user", assign_user_id="ae2")
    r3 = RuleSpec(
        "z-specific",
        "Z",
        5,
        (C(field="account.region", op="eq", value="NA"), C(field="account.segment", op="eq", value="enterprise")),
        "user",
        assign_user_id="sae",
    )
    out = route([r1, r2], ctx(), USERS)
    assert out.rule_key == "a-rule"
    assert "tie broken by key" in out.conflicts[0]["lost_because"]
    out = route([r1, r2, r3], ctx(), USERS)
    assert out.rule_key == "z-specific"
    assert all("less specific" in c["lost_because"] for c in out.conflicts)


def test_existing_owner_is_kept_unless_rule_overrides():
    out = route(RULES, ctx(owner_id="ae1"), USERS)
    assert out.outcome == "kept_owner" and out.assigned_user_id == "ae1"
    cust = route(RULES, ctx(owner_id="ae1", is_customer=True), USERS)
    assert cust.outcome == "assigned" and cust.assigned_user_id == "am1"


def test_inactive_owner_is_reassigned():
    out = route(RULES, ctx(owner_id="gone"), USERS)
    assert out.outcome == "assigned" and out.assigned_user_id == "ae2"
    assert any("inactive" in e for e in out.explanation)


def test_an_unclaimed_account_with_no_fallback_configured_is_a_rules_gap():
    out = route(RULES, ctx(segment="enterprise", region="APAC"), USERS)
    assert out.outcome == "unmatched" and out.assigned_user_id is None
    assert any("gap in the rules" in e for e in out.explanation)


def test_pool_at_capacity_still_assigns_with_alert_and_is_deterministic():
    u = [UserFacts("x", "Xavier", "T", True, 1, 1), UserFacts("y", "Yara", "T", True, 1, 1)]
    chosen, why = pick_least_loaded(u, "T")
    assert chosen.id == "x" and "capacity" in why
    assert pick_least_loaded([], "T")[0] is None


# Named accounts, fallback queue, round robin and SLAs ----------------------------------------------

FALLBACK = RuleSpec(
    "triage",
    "Unrouted → RevOps triage",
    999,
    (),
    "pool_least_loaded",
    assign_team="Account Management",
    is_fallback=True,
    sla_hours=24,
)


def test_an_unclaimed_account_lands_in_the_fallback_queue():
    """Nobody owning an account is a decision someone should have to defend, not a default."""
    out = route([*RULES, FALLBACK], ctx(segment="enterprise", region="APAC"), USERS)
    assert out.outcome == "fallback_queue"
    assert out.assigned_user_id == "am1"
    assert any("fallback queue" in e for e in out.explanation)


def test_the_fallback_queue_only_runs_when_no_other_rule_matched():
    out = route([*RULES, FALLBACK], ctx(), USERS)
    assert out.rule_key == "enterprise-na"
    # Priority 999 is irrelevant: a fallback is excluded from matching, not merely ranked last.
    greedy = RuleSpec("greedy", "Greedy fallback", 1, (), "user", assign_user_id="sae", is_fallback=True)
    out = route([*RULES, greedy], ctx(), USERS)
    assert out.rule_key == "enterprise-na"


def test_a_named_account_is_never_reassigned_by_a_territory_rule():
    out = route([*RULES, FALLBACK], ctx(is_named_account=True, owner_id="ae1", is_customer=True), USERS)
    assert out.outcome == "named_account"
    assert out.assigned_user_id == "ae1"
    # Even a rule that overrides ownership loses to a named account.
    assert out.rule_key is None
    assert any("named account" in e for e in out.explanation)


def test_a_named_account_whose_owner_left_falls_back_to_the_rules():
    out = route([*RULES, FALLBACK], ctx(is_named_account=True, owner_id="gone"), USERS)
    assert out.outcome == "assigned" and out.assigned_user_id == "ae2"


def test_round_robin_is_even_and_stable_for_the_same_account():
    pool = [UserFacts(f"u{i}", f"Rep {i}", "SDR Pool", True, 100, i * 7) for i in range(4)]
    rule = RuleSpec("rr", "Round robin", 10, (), "round_robin", assign_team="SDR Pool")
    counts: dict[str, int] = {}
    for i in range(400):
        out = route([rule], {"account": {"id": f"acct-{i}", "segment": "smb"}}, pool)
        counts[out.assigned_user_id] = counts.get(out.assigned_user_id, 0) + 1
    assert set(counts) == {"u0", "u1", "u2", "u3"}
    # Even within a reasonable band; hashing does not promise exact balance, only no systematic bias.
    assert max(counts.values()) - min(counts.values()) < 60, counts
    # Load is deliberately ignored: that is what pool_least_loaded is for.
    again = route([rule], {"account": {"id": "acct-7", "segment": "smb"}}, pool)
    assert (
        again.assigned_user_id == route([rule], {"account": {"id": "acct-7", "segment": "smb"}}, pool).assigned_user_id
    )


def test_round_robin_is_idempotent_across_a_replay():
    """A re-run after a crash must reach the same rep, or a replay silently changes ownership."""
    pool = [UserFacts(f"u{i}", f"Rep {i}", "SDR Pool", True, 100, 0) for i in range(5)]
    rule = RuleSpec("rr", "Round robin", 10, (), "round_robin", assign_team="SDR Pool")
    first = route([rule], {"account": {"id": "stable-id"}}, pool).assigned_user_id
    # Load has moved on since; the decision must not.
    moved = [UserFacts(u.id, u.name, u.team, u.is_active, u.capacity, 42) for u in pool]
    assert route([rule], {"account": {"id": "stable-id"}}, moved).assigned_user_id == first


def test_an_sla_produces_a_due_by_time_on_the_decision():
    rule = RuleSpec("fast", "Inbound", 10, (), "user", assign_user_id="ae1", sla_hours=2)
    now = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)
    out = route([rule], ctx(), USERS, now=now)
    assert out.sla_hours == 2
    assert out.sla_due_at == now + timedelta(hours=2)
    assert any("due within 2h" in e for e in out.explanation)


def test_a_rule_without_an_sla_promises_nothing():
    out = route(RULES, ctx(), USERS, now=datetime(2026, 9, 22, 9, 0, tzinfo=UTC))
    assert out.sla_due_at is None and out.sla_hours is None


def test_a_matched_rule_with_an_empty_team_blames_the_rule_not_the_account():
    empty = RuleSpec("ghost", "Ghost team", 1, (), "pool_least_loaded", assign_team="Nobody Here")
    out = route([empty], ctx(), USERS)
    assert out.outcome == "unmatched" and out.rule_key == "ghost"
    assert any("no one to assign to" in e for e in out.explanation)
