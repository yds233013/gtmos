from datetime import UTC, datetime, timedelta

from gtmos.domain.enrichment import (
    Attempt,
    ExistingValue,
    FieldValue,
    ProviderError,
    decide,
    run_waterfall,
    values_disagree,
)

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


# Provider disagreement ---------------------------------------------------------------------------


def test_trivial_differences_are_not_treated_as_disagreement():
    # Headcount measured a month apart, a legal suffix, a casing difference: all the same fact.
    assert not values_disagree(240, 247)
    assert not values_disagree("AI/ML Platforms", "ai/ml platforms  ")
    assert not values_disagree(None, 500)
    # One provider seeing more of a tech stack than another is coverage, not contradiction.
    assert not values_disagree(["python", "aws"], ["python", "aws", "kubernetes"])


def test_material_differences_are_treated_as_disagreement():
    assert values_disagree(240, 4000)
    assert values_disagree("Fintech", "Developer Tools")
    assert values_disagree(True, False)
    assert values_disagree(["python", "aws"], ["ruby", "gcp"])


def test_a_second_opinion_already_paid_for_is_used_to_flag_a_conflict():
    """A provider call returns every field it supports, so the losing answer is usually free."""
    a = FakeProvider(
        "a",
        {"employee_count": FieldValue(240, 0.9), "industry": FieldValue("Fintech", 0.5)},
        ["employee_count", "industry"],
    )
    b = FakeProvider(
        "b",
        {"employee_count": FieldValue(4000, 0.88), "industry": FieldValue("Developer Tools", 0.9)},
        ["employee_count", "industry"],
    )
    r = run_waterfall(
        "x.example",
        ["employee_count", "industry"],
        {"employee_count": ["a", "b"], "industry": ["a", "b"]},
        {"a": a, "b": b},
        {},
        NOW,
    )
    headcount = next(d for d in r.decisions if d.field == "employee_count")
    # `a` answered confidently at position 0, so the waterfall never asks `b` for headcount — but `b`
    # was called for industry and its response carried a headcount too.
    assert headcount.value == 240
    assert headcount.conflict is not None
    assert [o.value for o in headcount.conflict.others] == [4000]
    assert headcount.conflict.material is True
    assert "4000" in headcount.conflict.explanation


def test_agreement_between_providers_produces_no_conflict():
    a = FakeProvider("a", {"employee_count": FieldValue(240, 0.9)}, ["employee_count"])
    b = FakeProvider("b", {"employee_count": FieldValue(250, 0.9)}, ["employee_count"])
    r = run_waterfall("x.example", ["employee_count"], {"employee_count": ["a", "b"]}, {"a": a, "b": b}, {}, NOW)
    assert r.conflicts == []


def test_a_contested_field_is_never_silently_overwritten():
    """Two confident providers contradicting each other is not grounds to replace a stored value."""
    existing = {"industry": ExistingValue("Fintech", 0.7, "manual_import", NOW - timedelta(days=10))}
    a = FakeProvider(
        "a",
        {"industry": FieldValue("Developer Tools", 0.95)},  # no headcount, so `b` gets called for it
        ["industry", "employee_count"],
    )
    b = FakeProvider(
        "b",
        {"industry": FieldValue("B2B SaaS", 0.9), "employee_count": FieldValue(1, 0.9)},
        ["industry", "employee_count"],
    )
    r = run_waterfall(
        "x.example",
        ["industry", "employee_count"],
        {"industry": ["a", "b"], "employee_count": ["a", "b"]},
        {"a": a, "b": b},
        existing,
        NOW,
    )
    industry = next(d for d in r.decisions if d.field == "industry")
    assert industry.action == "conflict"
    assert industry.value == "Fintech", "the stored value must survive a contested update"
    assert "raised it for review" in industry.reason
    assert industry.field not in r.fields_changed


def test_an_empty_field_still_gets_filled_but_records_the_loser():
    """Having a value beats having none, so `set` stands — the disagreement is recorded, not suppressed."""
    a = FakeProvider(
        "a",
        {"industry": FieldValue("Developer Tools", 0.95)},  # no headcount, so `b` gets called for it
        ["industry", "employee_count"],
    )
    b = FakeProvider(
        "b",
        {"industry": FieldValue("Fintech", 0.9), "employee_count": FieldValue(1, 0.9)},
        ["industry", "employee_count"],
    )
    r = run_waterfall(
        "x.example",
        ["industry", "employee_count"],
        {"industry": ["a", "b"], "employee_count": ["a", "b"]},
        {"a": a, "b": b},
        {},
        NOW,
    )
    industry = next(d for d in r.decisions if d.field == "industry")
    assert industry.action == "set"
    assert industry.value == "Developer Tools"
    assert industry.conflict is not None and industry.conflict.others[0].value == "Fintech"


def test_a_low_confidence_dissent_is_recorded_but_not_material():
    a = FakeProvider(
        "a",
        {"industry": FieldValue("Developer Tools", 0.95)},  # no headcount, so `b` gets called for it
        ["industry", "employee_count"],
    )
    b = FakeProvider(
        "b",
        {"industry": FieldValue("Fintech", 0.2), "employee_count": FieldValue(1, 0.9)},
        ["industry", "employee_count"],
    )
    existing = {"industry": ExistingValue("B2B SaaS", 0.5, "manual_import", NOW - timedelta(days=10))}
    r = run_waterfall(
        "x.example",
        ["industry", "employee_count"],
        {"industry": ["a", "b"], "employee_count": ["a", "b"]},
        {"a": a, "b": b},
        existing,
        NOW,
    )
    industry = next(d for d in r.decisions if d.field == "industry")
    assert industry.conflict is not None and industry.conflict.material is False
    # A guess from a provider that admits it is guessing does not block a confident upgrade.
    assert industry.action == "update"
