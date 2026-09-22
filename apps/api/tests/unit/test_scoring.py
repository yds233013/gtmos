from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from gtmos.domain.icp import CategoryWeights, ICPDefinition, default_icp
from gtmos.domain.scoring import (
    AccountFacts,
    EngagementFacts,
    SignalFact,
    grade_for,
    intent_index,
    score_account,
)
from gtmos.domain.signals import decay_factor

NOW = datetime(2026, 9, 1, tzinfo=UTC)
ICP = default_icp()

STRONG = AccountFacts(
    name="Kestrel",
    domain="kestrel.example",
    industry="AI/ML Platforms",
    employee_count=850,
    region="NA",
    country="US",
    employee_growth_12m=0.42,
    technologies=("OpenAI", "LangChain", "Pinecone", "Kubernetes", "Snowflake"),
    ai_team_size=64,
)


def sig(t: str, days: float, strength: float = 0.9, conf: float = 0.9, i: str = "s1") -> SignalFact:
    return SignalFact(i, t, NOW - timedelta(days=days), strength, conf, f"{t} title")


def test_score_is_deterministic_and_hash_stable():
    s = [sig("funding_round", 10), sig("ai_hiring_surge", 5, i="s2")]
    a = score_account(ICP, STRONG, s, EngagementFacts(), NOW)
    b = score_account(ICP, STRONG, list(reversed(s)), EngagementFacts(), NOW)
    assert a.total == b.total
    assert a.inputs_hash == b.inputs_hash
    assert [c.points for c in a.components()] == [c.points for c in b.components()]


def test_categories_sum_to_total_and_respect_budgets():
    s = [
        sig(t, 0, 1.0, 1.0, i=t)
        for t in (
            "funding_round",
            "ai_hiring_surge",
            "ai_product_launch",
            "job_posting",
            "pricing_page_visit",
            "executive_hire",
            "usage_threshold",
        )
    ]
    r = score_account(ICP, STRONG, s, EngagementFacts(meetings_90d=1), NOW)
    assert r.total == round(sum(c.points for c in r.categories.values()))
    for cat in r.categories.values():
        assert cat.points <= cat.max_points
    assert r.categories["intent"].capped  # many strong intent signals exceed the 25-point budget
    assert r.grade == "A"


def test_fit_components_explain_each_point():
    r = score_account(ICP, STRONG, [], EngagementFacts(), NOW)
    fit = {c.key: c for c in r.categories["fit"].components}
    assert fit["industry"].points == fit["industry"].max_points == 15
    assert "core ICP industry" in fit["industry"].explanation
    assert fit["company_size"].points == 12
    assert "sweet spot" in fit["company_size"].explanation
    assert fit["geography"].points == 8


def test_adjacent_industry_gets_half_credit_and_unknown_gets_zero():
    adj = score_account(ICP, AccountFacts(**{**STRONG.__dict__, "industry": "Fintech"}), [], EngagementFacts(), NOW)
    unk = score_account(ICP, AccountFacts(**{**STRONG.__dict__, "industry": None}), [], EngagementFacts(), NOW)
    get = lambda r: next(c for c in r.categories["fit"].components if c.key == "industry")  # noqa: E731
    assert get(adj).points == 7.5
    assert get(unk).points == 0
    assert "Enrichment needed" in get(unk).explanation


def test_signals_decay_with_half_life():
    fresh = score_account(ICP, STRONG, [sig("pricing_page_visit", 0, 0.7, 0.7)], EngagementFacts(), NOW)
    old = score_account(ICP, STRONG, [sig("pricing_page_visit", 14, 0.7, 0.7)], EngagementFacts(), NOW)
    f = next(c for c in fresh.categories["intent"].components if c.key == "signal:pricing_page_visit")
    o = next(c for c in old.categories["intent"].components if c.key == "signal:pricing_page_visit")
    assert o.points == pytest.approx(f.points / 2, abs=0.1)  # 14-day half-life
    assert decay_factor(NOW, NOW, 30) == 1.0
    assert decay_factor(NOW - timedelta(days=30), NOW, 30) == pytest.approx(0.5)


def test_future_signals_are_ignored():
    r = score_account(ICP, STRONG, [sig("funding_round", -5)], EngagementFacts(), NOW)
    assert not any(c.key == "signal:funding_round" for c in r.components())


def test_additional_signals_of_same_type_add_diminishing_credit():
    one = score_account(ICP, STRONG, [sig("job_posting", 1, 0.5, 0.8)], EngagementFacts(), NOW)
    two = score_account(
        ICP, STRONG, [sig("job_posting", 1, 0.5, 0.8), sig("job_posting", 2, 0.5, 0.8, "s2")], EngagementFacts(), NOW
    )
    p1 = one.categories["intent"].points
    p2 = two.categories["intent"].points
    assert p1 < p2 < 2 * p1


def test_exclusions_zero_the_score_with_reason():
    gov = AccountFacts(**{**STRONG.__dict__, "industry": "Government"})
    r = score_account(ICP, gov, [sig("funding_round", 1)], EngagementFacts(), NOW)
    assert r.excluded and r.total == 0 and r.grade == "X"
    assert "excluded" in (r.exclusion_reason or "")
    tiny = AccountFacts(**{**STRONG.__dict__, "employee_count": 10})
    assert score_account(ICP, tiny, [], EngagementFacts(), NOW).excluded


def test_engagement_prefers_meetings_over_replies():
    m = score_account(ICP, STRONG, [], EngagementFacts(meetings_90d=1), NOW)
    r = score_account(ICP, STRONG, [], EngagementFacts(replies_90d=3), NOW)
    assert m.categories["engagement"].points > r.categories["engagement"].points > 0


def test_weights_rescale_category_budgets():
    icp = ICP.model_copy(update={"weights": CategoryWeights(fit=50, intent=20, timing=10, technical=10, engagement=10)})
    r = score_account(icp, STRONG, [], EngagementFacts(), NOW)
    assert r.categories["fit"].max_points == 50
    assert r.categories["fit"].points == 50


def test_invalid_icp_definitions_are_rejected():
    with pytest.raises(ValidationError):
        CategoryWeights(fit=50, intent=50, timing=10, technical=0, engagement=0)
    with pytest.raises(ValidationError):
        ICPDefinition(positive_signals={"made_up": 3})
    with pytest.raises(ValidationError):
        ICPDefinition(core_industries=["Fintech"], excluded_industries=["Fintech"])


def test_grades_and_intent_index():
    assert [grade_for(x) for x in (95, 72, 71, 58, 45, 44)] == ["A", "A", "B", "B", "C", "D"]
    quiet = score_account(ICP, STRONG, [], EngagementFacts(), NOW)
    hot = score_account(
        ICP, STRONG, [sig("ai_hiring_surge", 1), sig("funding_round", 1, i="s2")], EngagementFacts(meetings_90d=1), NOW
    )
    assert intent_index(hot) > intent_index(quiet)
    assert "Scores" in hot.summary


# Negative signals --------------------------------------------------------------------------------


def test_a_disqualifying_signal_lowers_the_score():
    """Every signal adding points is a taxonomy that can never say 'stop working this account'."""
    clean = score_account(ICP, STRONG, [sig("ai_hiring_surge", 5)], EngagementFacts(), NOW)
    churned = score_account(
        ICP,
        STRONG,
        [sig("ai_hiring_surge", 5), sig("competitor_adopted", 5, i="neg")],
        EngagementFacts(),
        NOW,
    )
    assert churned.total < clean.total
    penalty = next(c for c in churned.components() if c.key == "signal:competitor_adopted")
    assert penalty.points < 0
    assert penalty.category == "negative"


def test_a_penalty_is_not_absorbed_by_a_category_cap():
    """Inside its own category the penalty would vanish against the cap, which defeats the point."""
    maxed = [sig("product_signup", 1, i="a"), sig("teammate_invited", 1, i="b"), sig("usage_threshold", 1, i="c")]
    engaged = EngagementFacts(replies_90d=4, positive_replies_90d=2, meetings_90d=2)
    before = score_account(ICP, STRONG, maxed, engaged, NOW)
    assert before.categories["engagement"].capped or before.category_points("engagement") == pytest.approx(
        before.categories["engagement"].max_points
    )
    after = score_account(ICP, STRONG, [*maxed, sig("champion_departed", 1, i="neg")], engaged, NOW)
    assert after.total < before.total


def test_a_penalty_carries_the_action_it_implies():
    r = score_account(ICP, STRONG, [sig("unsubscribed", 2, i="neg")], EngagementFacts(), NOW)
    c = next(c for c in r.components() if c.key == "signal:unsubscribed")
    assert "Suppress the account from outbound" in c.explanation
    assert c.evidence and c.evidence[0]["signal_id"] == "neg"


def test_a_penalty_decays_like_any_other_signal():
    fresh = score_account(ICP, STRONG, [sig("layoffs", 1, i="n")], EngagementFacts(), NOW)
    old = score_account(ICP, STRONG, [sig("layoffs", 400, i="n")], EngagementFacts(), NOW)
    assert old.total > fresh.total, "a two-year-old layoff should weigh less than last week's"


def test_repeated_bad_news_is_counted_once():
    """Two reports of the same layoff are one layoff; stacking punishes press coverage, not risk."""
    once = score_account(ICP, STRONG, [sig("layoffs", 3, i="n1")], EngagementFacts(), NOW)
    twice = score_account(ICP, STRONG, [sig("layoffs", 3, i="n1"), sig("layoffs", 4, i="n2")], EngagementFacts(), NOW)
    assert once.total == twice.total


def test_the_score_never_goes_below_zero():
    weak = AccountFacts(
        name="Tiny",
        domain="tiny.example",
        industry="Retail",
        employee_count=30,
        region="LATAM",
        country="BR",
        employee_growth_12m=0.0,
    )
    negatives = [
        sig("unsubscribed", 1, i="n1"),
        sig("competitor_adopted", 1, i="n2"),
        sig("ai_project_cancelled", 1, i="n3"),
        sig("layoffs", 1, i="n4"),
    ]
    assert score_account(ICP, weak, negatives, EngagementFacts(), NOW).total == 0


def test_a_negative_signal_cannot_be_configured_as_a_reward():
    with pytest.raises(ValidationError):
        ICPDefinition(positive_signals={"layoffs": 5})
    with pytest.raises(ValidationError):
        ICPDefinition(negative_signals={"funding_round": 5})
