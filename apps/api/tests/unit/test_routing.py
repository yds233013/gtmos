from gtmos.domain.rules import Condition
from gtmos.domain.routing import RuleSpec, UserFacts, pick_least_loaded, route

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
    RuleSpec("existing-customer", "Existing customer → AM", 10, (C(field="account.is_customer", op="eq", value=True),),
             "pool_least_loaded", assign_team="Account Management", overrides_existing_owner=True),
    RuleSpec("strategic-high-intent", "High-intent strategic → Senior AE", 20,
             (C(field="account.segment", op="in", value=["strategic", "enterprise"]),
              C(field="account.intent_score", op="gte", value=70)),
             "user", assign_user_id="sae"),
    RuleSpec("enterprise-na", "Enterprise NA → AE", 30,
             (C(field="account.segment", op="in", value=["strategic", "enterprise"]),
              C(field="account.region", op="eq", value="NA")),
             "pool_least_loaded", assign_team="Enterprise NA"),
    RuleSpec("smb", "SMB & mid-market → SDR pool", 50,
             (C(field="account.segment", op="in", value=["smb", "mid_market"]),), "pool_least_loaded",
             assign_team="SDR Pool"),
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
    r3 = RuleSpec("z-specific", "Z", 5, (C(field="account.region", op="eq", value="NA"),
                                         C(field="account.segment", op="eq", value="enterprise")),
                  "user", assign_user_id="sae")
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


def test_unmatched_goes_to_triage():
    out = route(RULES, ctx(segment="enterprise", region="APAC"), USERS)
    assert out.outcome == "unmatched" and out.assigned_user_id is None


def test_pool_at_capacity_still_assigns_with_alert_and_is_deterministic():
    u = [UserFacts("x", "Xavier", "T", True, 1, 1), UserFacts("y", "Yara", "T", True, 1, 1)]
    chosen, why = pick_least_loaded(u, "T")
    assert chosen.id == "x" and "capacity" in why
    assert pick_least_loaded([], "T")[0] is None
