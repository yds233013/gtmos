from datetime import UTC, datetime, timedelta

from gtmos.domain.enrichment import Attempt, ExistingValue, FieldValue, ProviderError, decide, run_waterfall

NOW = datetime(2026, 9, 1, tzinfo=UTC)


class FakeProvider:
    is_simulated = True

    def __init__(self, key, data, fields, cost=1.0, fail=False):
        self.key = key
        self.name = key
        self.data = data
        self.supported_fields = frozenset(fields)
        self.cost_per_lookup = cost
        self.fail = fail
        self.calls = 0

    def lookup(self, domain, fields):
        self.calls += 1
        if self.fail:
            raise ProviderError("timeout")
        return {f: self.data[f] for f in fields if f in self.data}


WATERFALL = {"employee_count": ["a", "b", "c"], "industry": ["a", "b"], "technologies": ["c", "b"]}


def test_waterfall_falls_back_on_miss_error_and_low_confidence():
    a = FakeProvider("a", {"industry": FieldValue("AI/ML Platforms", 0.9)}, ["employee_count", "industry"], fail=True)
    b = FakeProvider("b", {"employee_count": FieldValue(800, 0.4)}, ["employee_count", "industry", "technologies"])
    c = FakeProvider(
        "c",
        {"employee_count": FieldValue(850, 0.85), "technologies": FieldValue(["OpenAI"], 0.8)},
        ["employee_count", "technologies"],
    )
    res = run_waterfall(
        "k.example", ["employee_count", "industry", "technologies"], WATERFALL, {"a": a, "b": b, "c": c}, {}, NOW
    )
    outcomes = [(x.field, x.provider, x.outcome) for x in res.attempts]
    assert ("employee_count", "a", "error") in outcomes
    assert ("employee_count", "b", "low_confidence") in outcomes
    assert ("employee_count", "c", "hit") in outcomes
    assert ("industry", "b", "miss") in outcomes
    dec = {d.field: d for d in res.decisions}
    assert dec["employee_count"].value == 850 and dec["employee_count"].provider == "c"
    assert dec["technologies"].action == "set"
    assert dec["industry"].action == "no_data"
    assert res.status == "partial"
    # each provider called at most once per run and charged once
    assert (a.calls, b.calls, c.calls) == (1, 1, 1)
    assert res.cost_credits == 3.0


def test_low_confidence_value_used_only_as_last_resort():
    b = FakeProvider("b", {"employee_count": FieldValue(800, 0.4)}, ["employee_count"])
    res = run_waterfall("k.example", ["employee_count"], {"employee_count": ["b"]}, {"b": b}, {}, NOW)
    assert res.decisions[0].value == 800 and res.decisions[0].action == "set"


def test_stops_after_first_confident_hit():
    a = FakeProvider("a", {"employee_count": FieldValue(900, 0.9)}, ["employee_count"])
    b = FakeProvider("b", {"employee_count": FieldValue(800, 0.99)}, ["employee_count"])
    res = run_waterfall("k.example", ["employee_count"], {"employee_count": ["a", "b"]}, {"a": a, "b": b}, {}, NOW)
    assert b.calls == 0 and res.decisions[0].value == 900


def test_unconfigured_provider_is_skipped_not_fatal():
    res = run_waterfall("k.example", ["industry"], {"industry": ["missing"]}, {}, {}, NOW)
    assert res.attempts[0].outcome == "skipped"
    assert res.decisions[0].action == "no_data"


def test_merge_policy_respects_manual_locks_and_confidence():
    cand = Attempt("employee_count", "p", 0, "hit", 1000, 0.95)
    locked = ExistingValue(850, 0.5, "manual", NOW, is_manual_lock=True)
    assert decide("employee_count", locked, cand, NOW).action == "keep_existing"
    weak = ExistingValue(850, 0.6, "seed", NOW)
    assert decide("employee_count", weak, cand, NOW).action == "update"
    strong = ExistingValue(850, 0.9, "seed", NOW)
    assert decide("employee_count", strong, cand, NOW).action == "keep_existing"
    stale = ExistingValue(850, 0.9, "seed", NOW - timedelta(days=400))
    assert decide("employee_count", stale, Attempt("employee_count", "p", 0, "hit", 1000, 0.9), NOW).action == "update"
    same = ExistingValue(1000, 0.7, "seed", NOW)
    assert decide("employee_count", same, cand, NOW).action == "keep_existing"
