"""Analytics semantics: cohort denominators and published metric definitions."""

from __future__ import annotations

from sqlalchemy import select

from gtmos.services import analytics


def test_funnel_is_cohort_based_with_a_fixed_denominator(client):
    f = client.get("/api/v1/analytics/funnel?days=90").json()
    stages = {s["stage"]: s for s in f["stages"]}
    # The mixed-denominator bug: "prospect" (all accounts, all time) used to head the funnel.
    assert "prospect" not in stages
    assert f["cohort_size"] > 0
    assert stages["contacted"]["accounts"] == f["cohort_size"]
    assert stages["contacted"]["conversion_from_cohort"] == 1.0
    # Every later stage is a subset of the cohort, so counts never increase down the funnel.
    counts = [s["accounts"] for s in f["stages"]]
    assert counts == sorted(counts, reverse=True)
    for s in f["stages"]:
        assert s["conversion_from_cohort"] is None or 0.0 <= s["conversion_from_cohort"] <= 1.0
    assert f["universe"]["accounts"] >= f["cohort_size"]
    assert "first outbound touch" in f["cohort_definition"]


def test_funnel_cohort_shrinks_with_a_shorter_window(client):
    wide = client.get("/api/v1/analytics/funnel?days=180").json()
    narrow = client.get("/api/v1/analytics/funnel?days=14").json()
    assert narrow["cohort_size"] <= wide["cohort_size"]


def test_every_reported_metric_is_defined(client):
    metrics = client.get("/api/v1/analytics/metrics").json()["metrics"]
    keys = [m["key"] for m in metrics]
    assert len(keys) == len(set(keys))
    for m in metrics:
        assert m["definition"] and m["formula"] and m["denominator"], m["key"]
        assert m["category"] in {"funnel", "outbound", "pipeline", "data", "experiment"}
    by_key = {m["key"]: m for m in metrics}
    # The numbers most likely to be misread must carry an explicit caveat.
    for key in ("open_rate", "pipeline_velocity", "attributed_share", "reply_rate", "contacted_cohort"):
        assert by_key[key]["caveat"], key
    assert "Apple Mail Privacy Protection" in by_key["open_rate"]["caveat"]


def test_overview_reply_rate_matches_its_published_denominator(client, db, ws):
    o = client.get("/api/v1/analytics/overview?days=90").json()
    expected = round(o["replies"] / o["emails_sent"], 4) if o["emails_sent"] else 0
    assert o["reply_rate"] == expected  # replies ÷ sends, as the dictionary states
    mix = analytics.activity_mix(db, ws.id, days=90)
    assert mix.get("email_sent", 0) == o["emails_sent"]


def test_scores_are_a_pure_function_of_the_seed_anchor(db, ws):
    """Re-scoring the seeded dataset must not move a single score.

    The seed places every signal at an offset from the workspace anchor, but scoring used to run at
    wall-clock time, so decay was measured over an interval that depended on how long the seed had been
    running. Two resets on the same afternoon produced different grade distributions as borderline
    accounts tipped across a band, which makes "deterministic demo data" untrue in the one way a
    reviewer would notice: the headline numbers changed between runs.
    """
    from gtmos.models import ICPScore
    from gtmos.services.scoring_service import rescore_accounts

    assert ws.demo_anchor_at is not None

    def fingerprint() -> list[tuple[str, int, str]]:
        rows = db.execute(
            select(ICPScore.account_id, ICPScore.total, ICPScore.grade).where(
                ICPScore.workspace_id == ws.id, ICPScore.is_current.is_(True)
            )
        ).all()
        return sorted((str(a), t, g) for a, t, g in rows)

    before = fingerprint()
    assert before, "the fixture should have scored accounts"
    rescore_accounts(db, ws.id, trigger="determinism-check", now=ws.demo_anchor_at, write_audit=False)
    db.flush()
    assert fingerprint() == before
