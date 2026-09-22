"""The scoring backtest must stay honest as the score, thresholds and seed change.

These assert the properties that make the published evaluation trustworthy — the population is the
contacted cohort, leakage is reported rather than hidden, and grade bands stay usable — not the
specific AUC, which is allowed to move.
"""

from __future__ import annotations

from gtmos.domain.scoring import GRADE_THRESHOLDS


def test_evaluation_population_is_the_contacted_cohort(client):
    r = client.get("/api/v1/analytics/scoring-evaluation").json()
    pop = r["population"]
    assert pop["evaluated"] > 0
    # Only contacted accounts can convert, and grade X accounts are not recommendations.
    assert pop["evaluated"] <= pop["contacted"] <= pop["scored_accounts"]
    assert pop["evaluated"] <= pop["scored_accounts"] - pop["excluded_from_ranking"]


def test_every_variant_reports_an_interval_and_its_leakage(client):
    r = client.get("/api/v1/analytics/scoring-evaluation").json()
    for outcome in r["outcomes"].values():
        variants = outcome["variants"]
        assert set(variants) == {"structural", "pre_engagement", "total"}
        for v in variants.values():
            low, high = v["auc_ci"]
            assert low <= v["auc"] <= high, "a reported AUC must sit inside its own interval"
            assert v["leakage"], "every variant must state whether it leaks the outcome"
        # The product's headline score includes engagement, which is downstream of the outcome, so the
        # report must publish the gap rather than the flattering number alone.
        assert outcome["leakage_delta"]["available"] is True
        assert outcome["leakage_delta"]["delta"] == round(variants["total"]["auc"] - variants["structural"]["auc"], 4)


def test_both_biased_estimates_of_the_selection_effect_are_published(client):
    r = client.get("/api/v1/analytics/scoring-evaluation").json()
    sel = r["outcomes"]["meeting"]["selection_effect"]
    assert sel["available"] is True
    assert sel["contacted_only_n"] < sel["all_accounts_n"]
    assert "holdout" in sel["note"], "the report must name the only unbiased design"


def test_small_buckets_are_flagged_and_never_silently_reported(client):
    r = client.get("/api/v1/analytics/scoring-evaluation").json()
    for outcome in r["outcomes"].values():
        for b in outcome["by_grade"]:
            assert (b["n"] < 30) == b["small_sample"]
            assert b["ci_low"] <= b["rate"] <= b["ci_high"]


def test_grade_bands_are_actionable_sizes(client):
    """Grade A exists to be worked today. One account in two thousand is not a list."""
    r = client.get("/api/v1/analytics/scoring-evaluation").json()
    dist = {g["grade"]: g for g in r["grade_distribution"]}
    assert 0.002 <= dist["A"]["share"] <= 0.05, f"grade A holds {dist['A']['accounts']} accounts"
    assert dist["B"]["accounts"] > dist["A"]["accounts"]
    assert dist["C"]["accounts"] > dist["B"]["accounts"]
    # Thresholds are ordered and match what the docs publish.
    assert [t for _, t in GRADE_THRESHOLDS] == sorted((t for _, t in GRADE_THRESHOLDS), reverse=True)


def test_meeting_rate_rises_with_grade(client):
    """The bands must at least order conversion correctly, or they are decoration."""
    by_grade = {
        b["label"]: b
        for b in client.get("/api/v1/analytics/scoring-evaluation").json()["outcomes"]["meeting"]["by_grade"]
    }
    rates = [by_grade[g]["rate"] for g in ("A", "B", "C", "D") if g in by_grade]
    assert rates == sorted(rates, reverse=True), f"grade → meeting rate is not monotonic: {rates}"


def test_the_report_refuses_to_overclaim(client):
    r = client.get("/api/v1/analytics/scoring-evaluation").json()
    blob = " ".join(r["caveats"]).lower()
    assert "heuristic" in blob and "not a trained model" in blob
    assert "simulated" in blob
