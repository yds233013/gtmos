"""The generator behind `make docs-numbers` and `docs/demo-numbers.md`.

These figures were typed by hand into the README until a review found four of them had drifted far
enough that the README claimed the system was *better* than the running app showed. The generator is
the fix; these tests are what stop the generator becoming the next silent failure — a report that
renders "—" everywhere because a service changed its keys is worse than no report, because it looks
like it ran.
"""

from __future__ import annotations

from typing import Any

from gtmos.demonumbers.__main__ import collect, render


def test_collect_reads_every_section_from_the_services(db, ws) -> None:
    report = collect(db, ws.id)

    assert set(report) >= {"routing_sla", "data_quality", "experiment", "deliverability", "window_days"}
    assert report["window_days"] == 90
    assert report["data_quality"]["rule_count"] > 0


def test_render_uses_the_service_key_names_and_not_invented_ones(db, ws) -> None:
    """The failure this pins: the first version of the generator guessed at key names.

    Every number rendered as 0 or "—" and the markdown still looked plausible, because a table of
    zeroes is a table. Asserting on the *rendered* text is the only check that catches a shape
    mismatch, since a missing key reads as a default rather than raising.
    """
    text = render(collect(db, ws.id))

    assert "Do not edit by hand" in text
    for heading in ("## Routing SLA", "## Experiment", "## Data quality", "## Deliverability"):
        assert heading in text

    # A renderer reading the wrong keys produces "0" and "None" rather than failing.
    assert "None/100" not in text, "deliverability risk score did not resolve"
    assert "**0** lead-event assignments" not in text, "routing SLA total did not resolve"

    # The dataset is synthetic and the file has to keep saying so.
    assert "synthetic" in text.lower()


def test_sla_reports_late_untouched_and_pending_separately(db, ws) -> None:
    """Collapsing the three is the classic way a speed-to-lead metric flatters itself."""
    text = render(collect(db, ws.id))

    assert "Touched late" in text
    assert "Never touched at all" in text
    assert "Still pending" in text


def test_render_survives_a_service_returning_nothing(db, ws) -> None:
    """A missing experiment must degrade to a sentence, not crash the whole file."""
    report: dict[str, Any] = collect(db, ws.id)
    report["experiment"] = None

    text = render(report)
    assert "_Not present in this dataset._" in text
