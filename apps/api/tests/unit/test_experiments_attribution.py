from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from gtmos.domain.attribution import OpportunityFacts, Touch, attribute, weights_for
from gtmos.domain.experiments import (
    assign_variant,
    compare,
    newcombe_diff_interval,
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


def test_verdicts_are_conservative():
    assert compare(("c", 5, 50), ("t", 12, 50), min_sample=200).verdict == "insufficient_sample"
    assert compare(("c", 40, 400), ("t", 44, 400), min_sample=200).verdict == "no_significant_difference"
    r = compare(("c", 40, 400), ("t", 64, 400), min_sample=200)
    assert r.verdict == "treatment_better" and r.absolute_lift == pytest.approx(0.06)
    assert r.relative_lift == pytest.approx(0.6)
    assert compare(("c", 2, 300), ("t", 3, 300), min_sample=200).verdict == "insufficient_events"
    assert compare(("c", 64, 400), ("t", 40, 400), min_sample=200).verdict == "control_better"
    assert required_sample_size(0.1, 0.05) > 400


NOW = datetime(2026, 9, 1, tzinfo=UTC)


def test_attribution_models_distribute_credit_differently():
    opp = OpportunityFacts("o1", 100_000, NOW, won=True)
    touches = {"o1": [Touch("webinar", NOW - timedelta(days=60), "t1"),
                      Touch("funding-outbound", NOW - timedelta(days=20), "t2"),
                      Touch("pql", NOW - timedelta(days=2), "t3"),
                      Touch("too-old", NOW - timedelta(days=400), "t0"),
                      Touch("after-open", NOW + timedelta(days=1), "t4")]}
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
