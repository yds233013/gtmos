"""The inspector's causal chains: one account set traced from root cause to consequence.

A chain is only worth showing if the same accounts survive every link. These tests re-query the database
for the accounts a chain ends on and check they really do satisfy each step, because the failure mode
worth guarding against is not a crash — it is three true numbers arranged to imply a story.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from gtmos.models import Account, RoutingDecision, RoutingRule
from gtmos.seed.profiles import segment_for
from gtmos.services import stack_inspector
from gtmos.services.common import utcnow
from gtmos.services.stack_inspector import UNCLAIMED_OUTCOMES

CONFIDENCE_LEVELS = {"high", "medium", "low"}


def _chains(db, ws):
    return stack_inspector.causal_chains(db, ws.id, utcnow())


def _by_key(chains, key):
    return next((c for c in chains if c["key"] == key), None)


def test_chains_are_present_in_the_inspector_payload(client):
    payload = client.get("/api/v1/stack-inspector").json()
    assert payload["causal_chains"], "the inspector should surface at least one chain"
    # The existing contract is untouched: chains are an addition, not a replacement.
    assert {s["key"] for s in payload["sections"]} >= {"crm", "enrichment", "routing", "data_quality"}
    assert [r["rank"] for r in payload["recommendations"]] == list(range(1, len(payload["recommendations"]) + 1))


def test_every_link_narrows_the_set_it_inherited(db, ws):
    for chain in _chains(db, ws):
        counts = [link["count"] for link in chain["links"]]
        assert counts == sorted(counts, reverse=True), f"{chain['key']} widens at some link: {counts}"
        assert counts[-1] == chain["traced_accounts"]
        assert [link["step"] for link in chain["links"]] == list(range(1, len(counts) + 1))


def test_a_chain_the_data_cannot_carry_to_the_end_is_not_shown(db, ws):
    for chain in _chains(db, ws):
        assert chain["traced_accounts"] > 0
        assert chain["consequence"]["accounts"] == chain["traced_accounts"]


def test_the_size_chain_ends_on_accounts_that_actually_failed_every_step(db, ws):
    chain = _by_key(_chains(db, ws), "size_gap_blocks_routing")
    assert chain is not None
    ids = [uuid.UUID(a["id"]) for a in chain["accounts"]]
    assert ids
    for account in db.scalars(select(Account).where(Account.id.in_(ids))):
        assert account.employee_count is None
        assert account.segment is None
        # The terminal state is "no territory owner": either nobody owns it, or the only thing that
        # claimed it was the fallback queue, which exists to catch what the rules missed.
        claimed_by_a_rule = db.scalar(
            select(func.count())
            .select_from(RoutingDecision)
            .where(
                RoutingDecision.account_id == account.id,
                RoutingDecision.outcome.notin_(UNCLAIMED_OUTCOMES),
            )
        )
        assert account.owner_id is None or not claimed_by_a_rule
        unclaimed = db.scalar(
            select(func.count())
            .select_from(RoutingDecision)
            .where(RoutingDecision.account_id == account.id, RoutingDecision.outcome.in_(UNCLAIMED_OUTCOMES))
        )
        assert unclaimed, f"{account.name} is in the routing link but a rule did claim it"


def test_the_size_chain_reports_the_true_intersection_not_the_bigger_number(db, ws):
    chain = _by_key(_chains(db, ws), "size_gap_blocks_routing")
    assert chain is not None
    all_unmatched = db.scalar(
        select(func.count(func.distinct(RoutingDecision.account_id))).where(
            RoutingDecision.workspace_id == ws.id, RoutingDecision.outcome.in_(UNCLAIMED_OUTCOMES)
        )
    )
    routing_link = next(link for link in chain["links"] if "routing" in link["label"].lower())
    assert routing_link["count"] <= all_unmatched
    # The claim the audit item warned about: the chain must say how much of the bigger number it explains.
    assert str(routing_link["count"]) in chain["confidence"]["limits"]


def test_the_routing_mechanism_is_shown_not_asserted(db, ws):
    chain = _by_key(_chains(db, ws), "size_gap_blocks_routing")
    assert chain is not None
    rules = list(db.scalars(select(RoutingRule).where(RoutingRule.workspace_id == ws.id, RoutingRule.is_active)))
    segment_rules = [r for r in rules if any(c.get("field") == "account.segment" for c in r.conditions)]
    evidence = next(link["evidence"] for link in chain["links"] if "routing" in link["label"].lower())
    assert (
        evidence["segment_conditioned_rules"]
        == f"{len(segment_rules)} of {len(rules)} active rules test account.segment"
    )


def test_the_territory_chain_names_only_regions_no_active_rule_covers(db, ws):
    chain = _by_key(_chains(db, ws), "territory_gap_strands_accounts")
    if chain is None:
        return  # every region has a rule in this dataset; the chain is correctly absent
    covered = set(chain["links"][0]["evidence"]["covered_regions"])
    stranded = db.scalars(select(Account).where(Account.id.in_([uuid.UUID(a["id"]) for a in chain["accounts"]])))
    for account in stranded:
        assert account.region not in covered
        assert account.segment is not None, "a segment-less account belongs to the size chain, not this one"
        claimed = db.scalar(
            select(func.count())
            .select_from(RoutingDecision)
            .where(
                RoutingDecision.account_id == account.id,
                RoutingDecision.outcome.notin_(UNCLAIMED_OUTCOMES),
            )
        )
        assert account.owner_id is None or not claimed, "a territory rule did claim this account"


def test_the_conflict_chain_counts_only_disagreements_that_change_the_derived_value(db, ws):
    chain = _by_key(_chains(db, ws), "provider_conflict_decides_owner")
    if chain is None:
        return  # no material provider conflict in this dataset
    flip_link = chain["links"][1]
    assert (
        flip_link["count"] == flip_link["evidence"]["segment_band_flips"] + flip_link["evidence"]["industry_tier_flips"]
    )
    for account in db.scalars(select(Account).where(Account.id.in_([uuid.UUID(a["id"]) for a in chain["accounts"]]))):
        # Whatever else is true of it, the account still holds the value the sources disagreed about.
        assert account.employee_count is None or segment_for(account.employee_count) == account.segment


def test_every_chain_carries_a_fix_and_an_honest_confidence_statement(db, ws):
    for chain in _chains(db, ws):
        assert len(chain["links"]) >= 3, f"{chain['key']} is a finding, not a chain"
        assert all(link["sentence"] and link["query"] for link in chain["links"])
        assert chain["consequence"]["sentence"] and chain["consequence"]["metrics"]
        assert chain["fix"]["how"] and chain["fix"]["expected_effect"]
        confidence = chain["confidence"]
        assert confidence["level"] in CONFIDENCE_LEVELS
        assert confidence["statement"] and confidence["limits"]


def test_a_chain_resting_on_correlation_says_so_in_the_payload(db, ws):
    for chain in _chains(db, ws):
        basis = chain["confidence"]["basis"]
        assert "mechanism" in basis or "correlation" in basis
        if "correlation" in basis:
            # The UI reads `limits`; a correlational chain that leaves it vague would imply proof.
            assert len(chain["confidence"]["limits"]) > 40
