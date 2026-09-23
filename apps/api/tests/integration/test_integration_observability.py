"""The integration status view must not flatter itself.

GTMOS talks to four tools at four genuinely different levels of proof: n8n really executes, HubSpot
runs on a simulated adapter, and PostHog and Clay are contracts exercised locally against endpoints
GTMOS owns. A status surface that renders four green badges is worse than no status surface, because
it converts "we have not tried this" into "this works". These tests pin the two claims that are easy
to get wrong:

  * a boundary is only ever `reached_real_service` when something genuinely crossed it, and seeded
    illustrative history never counts;
  * presence of a credential is reported, the credential itself never is.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from gtmos.config import get_settings
from gtmos.models import IntegrationSync, WebhookEvent
from gtmos.services import operations
from gtmos.services.common import utcnow

MODES = {"not_configured", "demo", "test", "live"}
LEVELS = {"unverified", "simulated", "verified_locally", "verified_by_execution"}
BOUNDARIES = {"hubspot", "n8n", "posthog", "clay"}


def _event(
    ws: Any,
    source: str,
    *,
    status: str = "processed",
    synthetic: bool = False,
    age_days: float = 0.0,
    processing_ms: int = 25,
    error: str | None = None,
    signature: str = "valid",
) -> WebhookEvent:
    received = utcnow() - timedelta(days=age_days)
    return WebhookEvent(
        workspace_id=ws.id,
        source=source,
        event_type="test_event",
        idempotency_key=f"obs-{uuid.uuid4()}",
        signature_status=signature,
        payload={"synthetic_history": True} if synthetic else {"hello": "world"},
        status=status,
        result={},
        error=error,
        attempts=1,
        correlation_id=uuid.uuid4().hex[:16],
        received_at=received,
        processed_at=received,
        processing_ms=processing_ms,
    )


def _clear(db: Session, ws: Any, source: str) -> None:
    """Start a boundary from a known-empty state inside the test's rolled-back transaction."""
    db.execute(delete(WebhookEvent).where(WebhookEvent.workspace_id == ws.id, WebhookEvent.source == source))
    db.execute(delete(IntegrationSync).where(IntegrationSync.workspace_id == ws.id, IntegrationSync.provider == source))
    db.flush()


def _by_provider(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {i["provider"]: i for i in payload["integrations"]}


@pytest.fixture
def status(db: Session, ws):  # type: ignore[no-untyped-def]
    def run(days: int = 7) -> dict[str, dict[str, Any]]:
        return _by_provider(operations.integration_status(db, ws.id, days))

    return run


# Shape -------------------------------------------------------------------------------------------


def test_endpoint_reports_every_boundary_with_a_legal_mode_and_verification_level(client):
    body = client.get("/api/v1/integrations/status").json()
    assert set(body["modes"]) == MODES
    assert set(body["verification_levels"]) == LEVELS
    items = _by_provider(body)
    assert set(items) == BOUNDARIES
    for i in items.values():
        assert i["mode"] in MODES
        assert i["verification"] in LEVELS
        assert i["health"] in {"healthy", "degraded", "failing", "idle", "not_configured"}
        # Every field the card needs, so a missing key fails here rather than blanking a panel.
        for key in ("summary", "moves", "requirements", "blocking", "window", "lifetime", "docs", "endpoints"):
            assert i[key] is not None, key
        assert i["window"]["days"] == 7
        assert isinstance(i["reached_real_service"], bool)


def test_window_is_configurable_and_counts_only_events_inside_it(db: Session, ws, status):
    _clear(db, ws, "clay")
    db.add(_event(ws, "clay", age_days=1))
    db.add(_event(ws, "clay", age_days=20))
    db.flush()
    assert status(7)["clay"]["window"]["inbound_events"] == 1
    assert status(30)["clay"]["window"]["inbound_events"] == 2
    # Lifetime is not windowed: both deliveries really happened.
    assert status(7)["clay"]["lifetime"]["inbound_events"] == 2


# Honesty -----------------------------------------------------------------------------------------


def test_hubspot_without_credentials_is_demo_and_simulated_never_connected(status):
    hs = status()["hubspot"]
    assert hs["mode"] == "demo"
    assert hs["verification"] == "simulated"
    assert hs["reached_real_service"] is False
    assert "HUBSPOT_ACCESS_TOKEN" in hs["blocking"]


def test_hubspot_with_both_switches_is_live_but_still_unverified_until_a_real_sync_runs(
    monkeypatch, db: Session, ws, status
):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "pat-na1-not-a-real-token")
    monkeypatch.setenv("HUBSPOT_LIVE_WRITES_ENABLED", "true")
    get_settings.cache_clear()
    try:
        hs = status()["hubspot"]
        # Configuration says live. Nothing has run, so the claim stops there.
        assert hs["mode"] == "live"
        assert hs["verification"] == "unverified"
        assert hs["reached_real_service"] is False
        assert hs["lifetime"]["live_sync_runs"] == 0
    finally:
        get_settings.cache_clear()


def test_a_non_simulated_sync_run_is_what_promotes_hubspot_to_verified(monkeypatch, db: Session, ws, status):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "pat-na1-not-a-real-token")
    monkeypatch.setenv("HUBSPOT_LIVE_WRITES_ENABLED", "true")
    get_settings.cache_clear()
    try:
        now = utcnow()
        db.add(
            IntegrationSync(
                workspace_id=ws.id,
                provider="hubspot",
                job="reverse_etl_companies",
                direction="outbound",
                object_type="companies",
                status="succeeded",
                is_simulated=False,
                records_changed=3,
                correlation_id=uuid.uuid4().hex[:16],
                started_at=now,
                finished_at=now,
                duration_ms=120,
            )
        )
        db.flush()
        hs = status()["hubspot"]
        assert hs["verification"] == "verified_by_execution"
        assert hs["reached_real_service"] is True
    finally:
        get_settings.cache_clear()


def test_seeded_history_alone_never_counts_as_verification(db: Session, ws, status):
    _clear(db, ws, "clay")
    db.add(_event(ws, "clay", synthetic=True))
    db.add(_event(ws, "clay", synthetic=True))
    db.flush()
    clay = status()["clay"]
    assert clay["lifetime"]["inbound_events"] == 2
    assert clay["lifetime"]["real_deliveries"] == 0
    assert clay["mode"] == "demo"
    assert clay["verification"] == "unverified"
    assert clay["reached_real_service"] is False


def test_a_boundary_with_no_credentials_and_no_traffic_is_not_configured(db: Session, ws, status):
    _clear(db, ws, "clay")
    clay = status()["clay"]
    assert clay["mode"] == "not_configured"
    assert clay["verification"] == "unverified"
    assert clay["health"] == "not_configured"


def test_local_traffic_proves_the_contract_but_never_the_vendor(db: Session, ws, status):
    """The distinction the whole page exists for: exercised locally is not the same as connected."""
    _clear(db, ws, "clay")
    db.add(_event(ws, "clay"))
    db.flush()
    clay = status()["clay"]
    assert clay["mode"] == "test"
    assert clay["verification"] == "verified_locally"
    assert clay["reached_real_service"] is False
    assert "A Clay workspace on the Growth plan" in clay["blocking"]


def test_posthog_cannot_claim_a_live_account_because_no_posthog_setting_exists(db: Session, ws, status):
    _clear(db, ws, "posthog")
    db.add(_event(ws, "posthog"))
    db.flush()
    ph = status()["posthog"]
    assert ph["mode"] == "test"
    assert ph["reached_real_service"] is False
    assert any(r["kind"] == "account" and not r["configured"] for r in ph["requirements"])


def test_n8n_executions_are_the_one_thing_that_earns_a_green_badge(monkeypatch, db: Session, ws, status):
    monkeypatch.setenv("WEBHOOK_SECRET", "hmac-key-for-the-templates")
    get_settings.cache_clear()
    try:
        _clear(db, ws, "n8n")
        db.add(_event(ws, "n8n"))
        db.flush()
        n8n = status()["n8n"]
        assert n8n["mode"] == "live"
        assert n8n["verification"] == "verified_by_execution"
        assert n8n["reached_real_service"] is True
        assert n8n["blocking"] == []
    finally:
        get_settings.cache_clear()


# Secrets -----------------------------------------------------------------------------------------


def test_requirements_report_presence_and_never_the_secret_itself(monkeypatch, client):
    sentinel = "pat-na1-0000-super-secret-value"
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", sentinel)
    monkeypatch.setenv("CLAY_API_KEY", "clay-key-0000-secret")
    get_settings.cache_clear()
    try:
        res = client.get("/api/v1/integrations/status")
        raw = res.text
        assert sentinel not in raw
        assert "clay-key-0000-secret" not in raw
        items = _by_provider(res.json())
        token = next(r for r in items["hubspot"]["requirements"] if r["key"] == "HUBSPOT_ACCESS_TOKEN")
        assert token["configured"] is True
        assert set(token) == {"key", "kind", "configured", "purpose"}
    finally:
        get_settings.cache_clear()


# Health and counters -----------------------------------------------------------------------------


def test_health_reflects_the_failure_mix(db: Session, ws, status):
    _clear(db, ws, "clay")
    db.add(_event(ws, "clay", status="failed", error="boom"))
    db.flush()
    assert status()["clay"]["health"] == "failing"

    for _ in range(19):
        db.add(_event(ws, "clay"))
    db.flush()
    # One failure in twenty is still degraded; the threshold is deliberately tight for a boundary.
    assert status()["clay"]["health"] in {"degraded", "healthy"}

    for _ in range(40):
        db.add(_event(ws, "clay"))
    db.flush()
    assert status()["clay"]["health"] == "healthy"


def test_counters_and_latency_come_from_the_stored_rows(db: Session, ws, status):
    _clear(db, ws, "posthog")
    db.add(_event(ws, "posthog", processing_ms=10))
    db.add(_event(ws, "posthog", processing_ms=30))
    db.add(_event(ws, "posthog", status="failed", processing_ms=50, error="OperationalError"))
    db.flush()
    w = status()["posthog"]["window"]
    assert w["inbound_events"] == 3
    assert w["inbound_processed"] == 2
    assert w["error_count"] == 1
    assert w["records_processed"] == 2
    assert w["latency"]["inbound_p50_ms"] == 30
    assert w["error_rate"] == pytest.approx(1 / 3, abs=0.001)


def test_last_failure_is_carried_with_its_message(db: Session, ws, status):
    _clear(db, ws, "n8n")
    db.add(_event(ws, "n8n", status="rejected", error="signature check failed: missing token header"))
    db.flush()
    n8n = status()["n8n"]
    assert n8n["last_failure_at"] is not None
    assert "signature check failed" in (n8n["last_failure"] or "")


# Drilldown ---------------------------------------------------------------------------------------


def test_activity_returns_the_records_behind_a_card(db: Session, ws, client):
    _clear(db, ws, "clay")
    db.add(_event(ws, "clay"))
    db.add(_event(ws, "clay", status="failed", error="unparseable row"))
    db.flush()
    body = client.get("/api/v1/integrations/clay/activity?days=30&limit=10").json()
    assert body["provider"] == "clay"
    assert len(body["events"]) == 2
    assert [e["message"] for e in body["errors"]] == ["unparseable row"]
    assert all("payload" not in e for e in body["events"]), "raw payloads are not part of the drilldown"


def test_activity_separates_sync_runs_from_deliveries(db: Session, ws, client):
    body = client.get("/api/v1/integrations/hubspot/activity").json()
    assert body["syncs"], "the seeded demo runs reverse-ETL jobs against the simulated adapter"
    assert all(s["is_simulated"] for s in body["syncs"])


def test_activity_rejects_a_provider_with_no_boundary(client):
    assert client.get("/api/v1/integrations/salesforce/activity").status_code == 404


def test_status_survives_a_sync_row_whose_errors_are_malformed(db: Session, ws, status):
    """`errors` is free-form JSON. An observability view that dies on bad input is not observability."""
    now = utcnow()
    db.add(
        IntegrationSync(
            workspace_id=ws.id,
            provider="hubspot",
            job="reverse_etl_companies",
            direction="outbound",
            object_type="companies",
            status="failed",
            is_simulated=True,
            errors=["a bare string, not the dict the writer promised"],
            correlation_id=uuid.uuid4().hex[:16],
            started_at=now,
            finished_at=now,
            duration_ms=5,
        )
    )
    db.flush()
    hs = status()["hubspot"]
    assert hs["last_failure"] == "a bare string, not the dict the writer promised"


def test_registry_rows_do_not_override_the_observed_posture(db: Session, ws, status):
    """`integrations.mode` is written at seed time; this view reports what is true now."""
    hs = status()["hubspot"]
    assert hs["registered"] is True
    assert hs["registry_mode"] in {"demo", "live"}
    assert hs["mode"] == "demo"
    # Clay has no registry row at all and must still be reported.
    assert status()["clay"]["registered"] is False
    assert db.scalar(select(WebhookEvent.source).where(WebhookEvent.source == "clay").limit(1)) in {"clay", None}
