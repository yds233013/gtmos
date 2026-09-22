from datetime import UTC, datetime, timedelta

from gtmos.domain.personalization import (
    DraftContent,
    PersonalizationInput,
    check_message_transition,
    generate_messages,
    run_guardrails,
)
from gtmos.domain.research import Claim, ResearchInput, generate_deterministic, validate_sections

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def research_input(signals=None):
    return ResearchInput(
        account={
            "id": "a1",
            "name": "Kestrel Analytics",
            "industry": "AI/ML Platforms",
            "employee_count": 850,
            "city": "San Francisco",
            "funding_stage": "Series C",
            "total_funding_usd": 180_000_000,
            "technologies": ["OpenAI", "LangChain", "LangSmith"],
            "ai_team_size": 64,
            "ai_open_roles": 14,
        },
        score={"id": "s1", "total": 93, "grade": "A", "summary": "Scores 93/100."},
        signals=signals
        if signals is not None
        else [
            {
                "id": "sig1",
                "signal_type": "funding_round",
                "title": "Raised $120M Series C",
                "explanation": "Kestrel raised a $120M Series C.",
                "source": "demo_news_feed",
                "confidence": 0.95,
                "strength": 0.9,
                "observed_at": NOW - timedelta(days=12),
                "source_url": None,
                "evidence": {},
            },
            {
                "id": "sig2",
                "signal_type": "ai_product_launch",
                "title": "Launched Kestrel Copilot agent",
                "explanation": "Launched an AI agent for analysts.",
                "source": "demo_news_feed",
                "confidence": 0.9,
                "strength": 0.85,
                "observed_at": NOW - timedelta(days=20),
                "source_url": None,
                "evidence": {"object": "the Kestrel Copilot agent"},
            },
        ],
        committee=[
            {
                "contact_id": "c3",
                "name": "Priya Raman",
                "title": "Head of AI Platform",
                "role_label": "Champion",
                "reasons": ["Head of AI feels the pain"],
                "confidence": 0.9,
            }
        ],
        activities=[],
        provenance={},
        seller={"name": "Sentinel AI"},
        now=NOW,
    )


def test_every_research_claim_is_cited_with_valid_refs():
    out = generate_deterministic(research_input())
    refs = {e.ref for e in out.evidence}
    claims = [c for sec in out.sections.values() for c in sec]
    assert claims
    assert all(c.evidence and set(c.evidence) <= refs for c in claims)
    assert out.unsupported == []
    assert out.angle == "launch_reliability"
    assert all(c.hypothesis for c in out.sections["likely_pain"])
    assert any("LangSmith" in c.text for c in out.sections["potential_objections"])


def test_no_signals_means_timing_not_established():
    out = generate_deterministic(research_input(signals=[]))
    assert "Timing is not established" in out.sections["why_now"][0].text
    assert out.angle == "icp_fit"


def test_validation_strips_uncited_and_unknown_refs():
    clean, bad = validate_sections(
        {"why_now": [Claim("ok", ["E1"]), Claim("uncited", []), Claim("ghost", ["E99"])]}, {"E1"}
    )
    assert [c.text for c in clean["why_now"]] == ["ok"]
    assert {b["text"] for b in bad} == {"uncited", "ghost"}


def p_input(**kw):
    out = generate_deterministic(research_input())
    ev = [{"ref": e.ref, "label": e.label, "detail": e.detail} for e in out.evidence]
    sig_ref = next(e.ref for e in out.evidence if e.record_id == "sig2")
    base = {
        "account": {"name": "Kestrel Analytics"},
        "contact": {"first_name": "Priya", "name": "Priya Raman", "title": "Head of AI Platform", "email_status": "valid"},
        "angle": "launch_reliability",
        "anchor_signal": {
            "id": "sig2",
            "title": "Launched Kestrel Copilot agent",
            "short": "launched Kestrel Copilot",
            "confidence": 0.9,
            "observed_at": NOW - timedelta(days=20),
            "ref": sig_ref,
            "subject_hook": "Kestrel Copilot",
        },
        "evidence": ev,
        "sender_name": "Jordan, Sentinel AI",
        "now": NOW,
    }
    base.update(kw)
    return PersonalizationInput(**base)


def test_generated_messages_pass_guardrails_and_cite_evidence():
    drafts = generate_messages(p_input())
    assert [d.channel for d in drafts] == ["email", "linkedin", "call_prep"]
    email = drafts[0]
    assert not email.blocked, email.guardrails_json()
    assert "Kestrel Analytics" in email.body
    assert email.chain["signal"]["ref"] and email.evidence
    assert len(drafts[1].body) <= 300


def test_guardrails_block_fabricated_numbers_and_superlatives():
    inp = p_input()
    bad = DraftContent(
        "email", "s", "Hi Priya, we cut incidents by 73% and are best-in-class. Chat?", "launch_reliability", {}, []
    )
    res = {g.check: g for g in run_guardrails(bad, inp)}
    assert not res["numbers_grounded"].passed and "73%" in res["numbers_grounded"].detail
    assert not res["no_unverifiable_claims"].passed
    bad.guardrails = list(res.values())
    assert bad.blocked


def test_stale_signal_and_unreachable_contact_block():
    inp = p_input(
        anchor_signal={
            "id": "x",
            "title": "Old news",
            "short": "did a thing",
            "confidence": 0.9,
            "observed_at": NOW - timedelta(days=400),
            "ref": None,
        },
        contact={"first_name": "P", "do_not_contact": True},
    )
    d = generate_messages(inp)[0]
    res = {g.check: g for g in d.guardrails}
    assert not res["signal_verified"].passed
    assert not res["contact_reachable"].passed
    assert d.blocked


def test_message_state_machine():
    assert check_message_transition("draft", "review", False)[0]
    assert check_message_transition("review", "approved", False)[0]
    assert not check_message_transition("review", "approved", True)[0]
    assert not check_message_transition("draft", "ready", False)[0]
    assert check_message_transition("approved", "ready", False)[0]
    assert check_message_transition("rejected", "draft", False)[0]
