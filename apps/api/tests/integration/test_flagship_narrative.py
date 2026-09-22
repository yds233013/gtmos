"""The flagship narrative contract.

The demo rests on one account telling a complete, non-contradictory story:

    signal → ICP fit → score → why now → buying committee → research → personalization → human approval
    → routing → CRM state → workflow execution → campaign → engagement → meeting → opportunity
    → pipeline → attribution → experiment → learning

These tests fail if any link in that chain breaks, which is what stops the demo quietly rotting as the seed
or the engines change.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from gtmos.domain.pipeline import check_funnel_transition
from gtmos.domain.signals import SIGNAL_TYPES
from gtmos.models import (
    Activity,
    ExperimentAssignment,
    ExperimentOutcome,
    ExternalRecord,
    MessageDraft,
    Opportunity,
    StageTransition,
)
from gtmos.services.attribution_service import run as run_attribution


def test_signal_fit_and_score_are_coherent(client, flagship):
    d = client.get(f"/api/v1/accounts/{flagship.id}").json()
    assert d["account"]["score_grade"] == "A", "the flagship must be the best-scoring account in the demo"
    score = d["score"]
    assert score["total"] >= 90
    # "Why now" must come from real signals, not from fit alone.
    categories = {SIGNAL_TYPES[s["signal_type"]].category for s in d["signals"] if s["signal_type"] in SIGNAL_TYPES}
    assert {"intent", "timing", "engagement"} <= categories
    assert len(d["signals"]) >= 8
    assert score["intent"] > 0 and score["timing"] > 0 and score["engagement"] > 0
    # Every component carries an explanation a rep could read aloud.
    assert all(c["explanation"] for c in score["components"])


def test_buying_committee_is_complete_and_explained(client, flagship):
    d = client.get(f"/api/v1/accounts/{flagship.id}").json()
    primary = {r["role"]: r for r in d["committee"] if r["rank"] == 1}
    assert {"champion", "economic_buyer", "technical_evaluator", "executive_sponsor", "end_user"} <= set(primary)
    assert primary["champion"]["contact"]["name"] == "Priya Raman"
    assert all(r["rationale"] for r in primary.values())


def test_research_is_cited_and_never_auto_promoted(client, flagship):
    d = client.get(f"/api/v1/accounts/{flagship.id}").json()
    report = d["research"]
    assert report is not None and report["status"] == "draft"
    refs = {e["ref"] for e in report["evidence"]}
    claims = [c for k, v in report["sections"].items() if k != "_meta" for c in v]
    assert len(claims) >= 10
    assert all(c["evidence"] and set(c["evidence"]) <= refs for c in claims)
    for section in ("account_summary", "why_now", "likely_pain", "buying_committee", "recommended_angle"):
        assert report["sections"].get(section), section


def test_outbound_has_draft_lineage_from_approval_to_send(client, db, flagship):
    """A send must be traceable to the approved draft that produced it (evidence → draft → approval → send)."""
    sends = list(
        db.scalars(
            select(Activity).where(
                Activity.account_id == flagship.id,
                Activity.type == "email_sent",
                Activity.message_draft_id.is_not(None),
            )
        )
    )
    assert sends, "no campaign send on the flagship links to the draft that generated it"
    draft = db.get(MessageDraft, sends[0].message_draft_id)
    assert draft is not None
    assert draft.status in ("approved", "ready")
    assert draft.approved_by, "a sent message must record who approved it"
    assert draft.reasoning_chain.get("signal"), "the draft must name the signal it was built from"
    assert all(g["passed"] for g in draft.guardrails if g["blocking"])


def test_journey_is_multi_touch_across_campaigns(client, flagship):
    d = client.get(f"/api/v1/accounts/{flagship.id}").json()
    campaigns = {a["campaign"] for a in d["activities"] if a.get("campaign")}
    assert len(campaigns) >= 3, f"expected a multi-campaign journey, got {campaigns}"
    types = {a["type"] for a in d["activities"]}
    assert {"webinar_attended", "email_sent", "email_replied", "positive_reply", "meeting_held"} <= types


def test_stage_history_is_valid_and_ends_in_an_opportunity(client, db, flagship):
    history = list(
        db.scalars(
            select(StageTransition)
            .where(StageTransition.entity_id == flagship.id, StageTransition.pipeline == "funnel")
            .order_by(StageTransition.changed_at)
        )
    )
    assert [t.to_stage for t in history][-1] == "opportunity"
    for t in history:
        assert check_funnel_transition(t.from_stage, t.to_stage).allowed, f"{t.from_stage}→{t.to_stage}"
    opp = db.scalars(select(Opportunity).where(Opportunity.account_id == flagship.id)).one()
    assert opp.amount_usd > 0 and opp.source_campaign_id is not None


def test_workflow_history_was_really_executed(client, db, flagship):
    d = client.get(f"/api/v1/accounts/{flagship.id}").json()
    runs = [r for r in d["workflow_runs"] if not r["synthetic_history"]]
    assert runs, "the flagship's history must come from real engine executions, not fabricated rows"
    detail = client.get(f"/api/v1/workflow-runs/{runs[0]['id']}").json()
    assert detail["status"] == "succeeded"
    assert detail["steps"] and all(s["status"] in ("succeeded", "skipped") for s in detail["steps"])
    # Real execution means real outputs, not a {"synthetic_history": true} placeholder.
    outputs = [s["output"] for s in detail["steps"] if s["status"] == "succeeded"]
    assert any(o and "synthetic_history" not in o for o in outputs)
    assert detail["trigger_event"].get("backdated") is True


def test_routing_crm_and_next_action_agree(client, db, flagship):
    d = client.get(f"/api/v1/accounts/{flagship.id}")
    j = d.json()
    assert j["account"]["owner"], "an opportunity-stage account must have an owner"
    decisions = j["routing_decisions"]
    assert decisions and decisions[0]["explanation"]
    ext = db.scalars(
        select(ExternalRecord).where(ExternalRecord.internal_id == flagship.id, ExternalRecord.provider == "hubspot")
    ).first()
    assert ext is not None and ext.is_simulated is True
    assert j["next_action"]["key"] == "multithread"  # open opportunity → broaden beyond the champion


def test_experiment_assignment_and_outcomes_close_the_loop(db, flagship):
    assignment = db.scalars(select(ExperimentAssignment).where(ExperimentAssignment.account_id == flagship.id)).first()
    assert assignment is not None, "the flagship must participate in an experiment"
    metrics = {
        o.metric for o in db.scalars(select(ExperimentOutcome).where(ExperimentOutcome.assignment_id == assignment.id))
    }
    assert {"reply", "positive_reply", "meeting", "opportunity"} <= metrics


def test_attribution_sees_the_flagship_as_multi_touch(db, ws, flagship):
    result = run_attribution(db, ws.id, days=180)
    opp = db.scalars(select(Opportunity).where(Opportunity.account_id == flagship.id)).one()
    credits = result["details"].get(str(opp.id))
    assert credits and len(credits) >= 2, "the flagship opportunity should have several touch sources"
    first = run_attribution(db, ws.id, days=180)
    by_model: dict[str, dict[str, float]] = defaultdict(dict)
    for row in first["rows"]:
        by_model["first_touch"][row["key"]] = row["first_touch"]
        by_model["last_touch"][row["key"]] = row["last_touch"]
    # First and last touch must disagree somewhere, otherwise the attribution page teaches nothing.
    assert by_model["first_touch"] != by_model["last_touch"]
    assert first["unattributed_opportunities"] > 0, "a credible dataset has an unattributed tail"
