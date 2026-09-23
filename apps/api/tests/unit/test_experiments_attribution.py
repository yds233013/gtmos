import math
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from gtmos.domain.attribution import OpportunityFacts, Touch, attribute, weights_for
from gtmos.domain.experiments import (
    GUARDRAILS,
    Z95,
    assign_variant,
    compare,
    evaluate_guardrail,
    minimum_detectable_effect,
    newcombe_diff_interval,
    practical_threshold_for,
    recommend,
    required_sample_size,
    two_proportion_z,
    wilson_interval,
)


def test_assignment_is_deterministic_and_balanced():
    variants = [("control", 0.5), ("treatment", 0.5)]
    a = [assign_variant("salt-1", f"acct-{i}", variants)[0] for i in range(4000)]
    b = [assign_variant("salt-1", f"acct-{i}", variants)[0] for i in range(4000)]
    assert a == b
    share = Counter(a)["treatment"] / 4000
    assert 0.46 < share < 0.54
    # different salt reshuffles units
    c = [assign_variant("salt-2", f"acct-{i}", variants)[0] for i in range(4000)]
    assert a != c


def test_weighted_assignment():
    got = Counter(assign_variant("s", str(i), [("a", 0.2), ("b", 0.8)])[0] for i in range(5000))
    assert 0.17 < got["a"] / 5000 < 0.23
    with pytest.raises(ValueError):
        assign_variant("s", "x", [])


def test_wilson_and_z_known_values():
    lo, hi = wilson_interval(10, 100)
    assert lo == pytest.approx(0.0552, abs=1e-3) and hi == pytest.approx(0.1744, abs=1e-3)
    z, p = two_proportion_z(40, 400, 64, 400)
    assert z == pytest.approx(2.54, abs=0.02)
    assert p == pytest.approx(0.011, abs=0.002)
    lo, hi = newcombe_diff_interval(40, 400, 64, 400)
    assert lo > 0 and hi > lo
    assert wilson_interval(0, 0) == (0.0, 0.0)
    assert wilson_interval(0, 50)[0] == 0.0  # regression: float residue made ci_low > rate
    assert wilson_interval(50, 50)[1] == 1.0


def test_verdicts_are_conservative():
    assert compare(("c", 5, 50), ("t", 12, 50), min_sample=200).verdict == "insufficient_sample"
    assert compare(("c", 40, 400), ("t", 44, 400), min_sample=200).verdict == "no_significant_difference"
    r = compare(("c", 40, 400), ("t", 64, 400), min_sample=200)
    assert r.verdict == "treatment_better" and r.absolute_lift == pytest.approx(0.06)
    assert r.relative_lift == pytest.approx(0.6)
    assert compare(("c", 2, 300), ("t", 3, 300), min_sample=200).verdict == "insufficient_events"
    assert compare(("c", 64, 400), ("t", 40, 400), min_sample=200).verdict == "control_better"
    assert required_sample_size(0.1, 0.05) > 400


def test_mde_matches_the_textbook_formula_and_inverts_the_sample_size():
    # Hand-computed: mde = (z_0.975 + z_0.80) * sqrt(2 * p * (1 - p) / n)
    #              = (1.95996 + 0.84160) * sqrt(2 * 0.2 * 0.8 / 1000) = 2.80156 * 0.0178885 = 0.05012
    closed_form = (Z95 + 0.8416) * math.sqrt(2 * 0.2 * 0.8 / 1000)
    assert closed_form == pytest.approx(0.0501, abs=1e-4)
    mde = minimum_detectable_effect(0.2, 1000)
    # Ours is the slightly larger, more conservative number: the pooled+unpooled sample-size formula it
    # inverts carries the treatment arm's own variance, which the textbook approximation drops.
    assert mde == pytest.approx(closed_form, abs=0.005) and mde > closed_form
    assert required_sample_size(0.2, mde) == 1000  # exact inverse, so the two numbers can never disagree
    assert required_sample_size(0.2, mde * 0.98) > 1000
    assert minimum_detectable_effect(0.2, 4000) < minimum_detectable_effect(0.2, 1000)
    assert minimum_detectable_effect(0.2, 0) is None and minimum_detectable_effect(0.0, 500) is None
    assert minimum_detectable_effect(0.2, 4) is None  # n = 4 cannot detect even a jump to certainty


def test_a_null_result_reports_what_it_could_have_detected():
    r = compare(("c", 40, 400), ("t", 44, 400), min_sample=200, practical_threshold=0.02)
    assert r.verdict == "no_significant_difference"
    assert r.mde_abs is not None and r.mde_abs > 0.05  # 400 per arm cannot see a 2 pp move at 10% baseline
    assert "underpowered, not evidence of no effect" in r.practical_note
    assert not r.practically_significant


def test_practical_significance_gates_a_statistically_real_but_tiny_lift():
    small = compare(("c", 2000, 20_000), ("t", 2120, 20_000), min_sample=200, practical_threshold=0.02)
    assert small.verdict == "treatment_better" and small.p_value < 0.05
    assert small.absolute_lift == pytest.approx(0.006)
    assert not small.practically_significant
    assert recommend("reply", small, []).action == "no_change"

    # 6 pp on 400 per arm clears the bar on the point estimate but not across the whole interval.
    borderline = compare(("c", 40, 400), ("t", 64, 400), min_sample=200, practical_threshold=0.02)
    assert borderline.practically_significant and not borderline.practical_interval_clears
    assert "Worth shipping, not worth promising" in borderline.practical_note
    assert recommend("reply", borderline, []).action == "ship"

    big = compare(("c", 400, 4000), ("t", 600, 4000), min_sample=200, practical_threshold=0.02)
    assert big.practically_significant and big.practical_interval_clears
    assert recommend("reply", big, []).action == "ship"


def test_guardrails_are_read_for_harm_not_for_lift():
    # Treatment unsubscribes are 2.4% against a 1% ceiling and the whole interval sits above it.
    breach = evaluate_guardrail("unsubscribe", ("c", 1, 293), ("t", 7, 293))
    assert breach.status == "breach" and breach.ceiling == GUARDRAILS["unsubscribe"].ceiling
    # A guardrail that moves the "good" way is never a win, only ever an "ok".
    improved = evaluate_guardrail("unsubscribe", ("c", 7, 293), ("t", 1, 293))
    assert improved.status == "ok" and improved.absolute_lift < 0
    # Under the ceiling but with an interval that still reaches it: not cleared, and it says so.
    unclear = evaluate_guardrail("bounce", ("c", 30, 293), ("t", 10, 293))
    assert unclear.status == "ok" and not unclear.conclusive
    assert "Control is over the ceiling too" in unclear.reason  # a bad list, not a bad variant
    assert evaluate_guardrail("bounce", ("c", 20, 5000), ("t", 20, 5000)).conclusive
    # Over the ceiling on the point estimate but not confirmed by the interval.
    assert evaluate_guardrail("spam_complaint", ("c", 0, 293), ("t", 1, 293)).status == "watch"
    assert evaluate_guardrail("bounce", ("c", 0, 100), ("t", 0, 0)).status == "no_data"


def test_a_primary_metric_win_does_not_ship_over_a_breached_guardrail():
    primary = compare(
        ("c", 68, 293), ("t", 93, 293), min_sample=250, practical_threshold=practical_threshold_for("reply")
    )
    assert primary.verdict == "treatment_better" and primary.practically_significant

    clean = recommend("reply", primary, [evaluate_guardrail("bounce", ("c", 10, 293), ("t", 5, 293))])
    assert clean.action == "ship"

    breached = recommend(
        "reply",
        primary,
        [
            evaluate_guardrail("bounce", ("c", 10, 293), ("t", 5, 293)),
            evaluate_guardrail("unsubscribe", ("c", 1, 293), ("t", 7, 293)),
            evaluate_guardrail("spam_complaint", ("c", 0, 293), ("t", 1, 293)),
        ],
    )
    assert breached.action == "do_not_ship"
    assert breached.blocking_guardrails == ["unsubscribe"]
    assert breached.watch_guardrails == ["spam_complaint"]
    assert "despite the win" in breached.headline
    assert "+8.5 pp on reply" in breached.reasoning  # the win is stated, not hidden, and then refused


def test_a_breach_outranks_an_undecided_primary_metric():
    early = compare(("c", 5, 60), ("t", 12, 60), min_sample=250)
    assert early.verdict == "insufficient_sample"
    assert recommend("reply", early, []).action == "keep_running"
    r = recommend("reply", early, [evaluate_guardrail("unsubscribe", ("c", 0, 60), ("t", 9, 60))])
    assert r.action == "do_not_ship" and r.blocking_guardrails == ["unsubscribe"]
    assert recommend("reply", compare(("c", 64, 400), ("t", 40, 400), min_sample=200), []).action == "do_not_ship"


NOW = datetime(2026, 9, 1, tzinfo=UTC)


def test_attribution_models_distribute_credit_differently():
    opp = OpportunityFacts("o1", 100_000, NOW, won=True)
    touches = {
        "o1": [
            Touch("webinar", NOW - timedelta(days=60), "t1"),
            Touch("funding-outbound", NOW - timedelta(days=20), "t2"),
            Touch("pql", NOW - timedelta(days=2), "t3"),
            Touch("too-old", NOW - timedelta(days=400), "t0"),
            Touch("after-open", NOW + timedelta(days=1), "t4"),
        ]
    }
    ft = attribute("first_touch", [opp], touches)
    lt = attribute("last_touch", [opp], touches)
    lin = attribute("linear", [opp], touches)
    u = attribute("u_shaped", [opp], touches)
    assert ft.pipeline_by_key == {"webinar": 100_000}
    assert lt.pipeline_by_key == {"pql": 100_000}
    assert lin.pipeline_by_key["funding-outbound"] == pytest.approx(33_333.33, abs=0.01)
    assert u.pipeline_by_key["webinar"] == 40_000 and u.pipeline_by_key["funding-outbound"] == 20_000
    for r in (ft, lt, lin, u):
        assert sum(r.pipeline_by_key.values()) == pytest.approx(100_000, abs=0.05)
        assert r.won_by_key == r.pipeline_by_key


def test_unattributed_opportunities_are_reported_not_hidden():
    r = attribute("linear", [OpportunityFacts("o1", 50_000, NOW, False)], {})
    assert r.unattributed_opportunities == 1 and r.unattributed_pipeline == 50_000
    assert r.pipeline_by_key == {}
    assert weights_for("u_shaped", 1) == [1.0]
    with pytest.raises(ValueError):
        weights_for("magic", 2)
