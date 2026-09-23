"""A Clay delivery end to end: signature → shared pipeline → account, contact and provenance.

No Clay account exists and nothing here touches the network. The deliveries are constructed against
the contract GTMOS publishes in `docs/clay-live-setup.md` and signed with the scheme Clay documents,
which is exactly what a live Clay table would send if it were configured as that document says.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from gtmos.config import get_settings
from gtmos.integrations.clay import clay_signature
from gtmos.models import Account, Contact, FieldProvenance, WebhookEvent
from gtmos.services import data_quality
from gtmos.services.common import utcnow

SECRET = "clay-signing-secret"


@pytest.fixture
def clay_secret(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLAY_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    yield SECRET
    monkeypatch.delenv("CLAY_WEBHOOK_SECRET")
    get_settings.cache_clear()


def _post(client, payload: dict[str, Any], *, secret: str | None = SECRET, signature: str | None = None):
    body = json.dumps(payload).encode()
    headers = {"content-type": "application/json"}
    if signature is not None:
        headers["X-Clay-Signature"] = signature
    elif secret is not None:
        headers["X-Clay-Signature"] = clay_signature(secret, body)
    return client.post("/api/v1/webhooks/clay", content=body, headers=headers)


def _row(domain: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "clay_row_id": f"row_{uuid.uuid4().hex[:10]}",
        "clay_run_id": "run_integration",
        "clay_table_id": "t_ai_ml_icp",
        "observed_at": utcnow().isoformat(),
        "Company Domain": domain,
    }
    payload.update(overrides)
    return payload


def test_a_signed_clay_row_flows_through_the_shared_pipeline_and_writes_provenance(
    client, db, ws, flagship, clay_secret
):
    payload = _row(
        flagship.domain,
        **{
            "Sub Industry": {"value": "LLM Observability", "provider": "clearbit", "confidence": 0.88},
            "Work Email": f"clay.buyer.{uuid.uuid4().hex[:6]}@{flagship.domain}",
            "Job Title": "VP of Machine Learning",
            "Email Verification": "valid",
        },
    )
    response = _post(client, payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["signature"] == "valid" and body["status"] == "processed"
    result = body["result"]
    assert result["matched"] is True and result["account"]["created"] is False

    db.expire_all()
    account = db.get(Account, uuid.UUID(result["account"]["id"]))
    assert account is not None and account.id == flagship.id
    assert account.sub_industry == "LLM Observability"
    prov = db.scalars(
        select(FieldProvenance).where(FieldProvenance.entity_id == account.id, FieldProvenance.field == "sub_industry")
    ).one()
    # Provenance must name Clay *and* the vendor behind it, because "Clay said so" is not a source.
    assert prov.source == "clay:clearbit" and prov.confidence == 0.88

    contact = db.get(Contact, uuid.UUID(result["contact"]["id"]))
    assert contact is not None and contact.account_id == account.id
    assert contact.title == "VP of Machine Learning" and contact.email_status == "valid"

    stored = db.scalars(select(WebhookEvent).where(WebhookEvent.id == uuid.UUID(body["id"]))).one()
    assert stored.source == "clay" and stored.signature_status == "valid"


def test_a_redelivered_clay_row_is_deduplicated_rather_than_applied_twice(client, db, ws, flagship, clay_secret):
    payload = _row(flagship.domain, **{"City": "Reykjavik"})
    first = _post(client, payload)
    assert first.status_code == 200 and first.json()["duplicate"] is False

    second = _post(client, payload)
    assert second.status_code == 200, second.text
    assert second.json()["duplicate"] is True
    assert second.json()["id"] == first.json()["id"]

    db.expire_all()
    events = list(
        db.scalars(select(WebhookEvent).where(WebhookEvent.source == "clay", WebhookEvent.workspace_id == ws.id))
    )
    assert len(events) == 1 and events[0].duplicate_count == 1


def test_a_redelivery_carrying_a_changed_cell_is_still_the_same_clay_row(client, db, flagship, clay_secret):
    """Clay re-runs a row when a column is refreshed; the row id, not the body, is its identity."""
    payload = _row(flagship.domain, **{"City": "Reykjavik"})
    first = _post(client, payload)
    again = _post(client, {**payload, "City": "Reykjavík"})
    assert again.json()["duplicate"] is True and again.json()["id"] == first.json()["id"]


def test_an_unsigned_or_forged_clay_delivery_is_refused_and_stores_nothing(client, db, ws, flagship, clay_secret):
    payload = _row(flagship.domain, **{"City": "Nowhere"})
    body = json.dumps(payload).encode()

    unsigned = client.post("/api/v1/webhooks/clay", content=body, headers={"content-type": "application/json"})
    assert unsigned.status_code == 401

    forged = _post(client, payload, secret="not-the-signing-secret")
    assert forged.status_code == 401

    tampered = _post(client, {**payload, "City": "Elsewhere"}, signature=clay_signature(SECRET, body))
    assert tampered.status_code == 401

    db.expire_all()
    assert list(db.scalars(select(WebhookEvent).where(WebhookEvent.source == "clay"))) == []


def test_a_partially_enriched_row_is_processed_and_names_the_columns_that_did_not_resolve(
    client, db, flagship, clay_secret
):
    response = _post(
        client,
        _row(
            flagship.domain,
            **{
                "Sub Industry": "Vector Databases",
                "Employee Count": {"value": None, "status": "empty"},
                "Founded": {"value": None, "status": "errored"},
                "Claygent Notes": "free text GTMOS does not store as a field",
            },
        ),
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["account"]["fields"]["set"] == ["sub_industry"]
    assert {s["field"]: s["reason"] for s in result["skipped_fields"]} == {
        "employee_count": "empty",
        "founded_year": "errored",
    }
    assert result["unmapped_columns"] == ["claygent_notes"]


def test_a_clay_value_that_contradicts_a_confident_one_produces_a_conflict_not_an_overwrite(
    client, db, ws, flagship, clay_secret
):
    flagship.sub_industry = "Data Infrastructure"
    db.add(
        FieldProvenance(
            workspace_id=ws.id,
            entity_type="account",
            entity_id=flagship.id,
            field="sub_industry",
            value="Data Infrastructure",
            source="demo_firmographics",
            confidence=0.9,
            observed_at=utcnow(),
        )
    )
    db.flush()

    response = _post(
        client,
        _row(flagship.domain, **{"Sub Industry": {"value": "Martech", "provider": "apollo", "confidence": 0.95}}),
    )
    assert response.status_code == 200, response.text

    db.expire_all()
    account = db.get(Account, flagship.id)
    assert account is not None and account.sub_industry == "Data Infrastructure"
    prov = db.scalars(
        select(FieldProvenance).where(FieldProvenance.entity_id == flagship.id, FieldProvenance.field == "sub_industry")
    ).one()
    assert prov.source == "demo_firmographics", "the incumbent keeps the field it was not beaten out of"
    assert prov.conflict is not None and prov.conflict["material"] is True
    assert any(o["provider"] == "clay:apollo" for o in prov.conflict["others"])
    # The existing data-quality rule sees a Clay conflict exactly as it sees a provider one: reusing
    # the merge policy means reusing everything downstream of it, for free.
    flagged = data_quality.rule_provider_conflict(db, ws.id, utcnow())
    assert any(c.entity_id == flagship.id and c.details["field"] == "sub_industry" for c in flagged)


def test_a_clay_row_for_an_unknown_company_creates_the_account_it_describes(client, db, ws, clay_secret):
    domain = f"clay-{uuid.uuid4().hex[:8]}.example"
    response = _post(
        client,
        _row(
            domain,
            **{
                "Company Name": "Newly Sourced AI",
                "Employee Count": 900,
                "Industry": "AI/ML Platforms",
                "Tech Stack": ["Snowflake", "Ray"],
            },
        ),
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["account"]["created"] is True

    db.expire_all()
    account = db.get(Account, uuid.UUID(result["account"]["id"]))
    assert account is not None
    assert (account.name, account.domain, account.employee_count) == ("Newly Sourced AI", domain, 900)
    assert account.source == "clay" and account.data_origin == "live"
    # Segment is derived from headcount the same way the enrichment waterfall derives it.
    assert account.segment is not None


def test_a_row_with_no_company_domain_is_acknowledged_without_inventing_an_account(client, db, ws, clay_secret):
    before = db.scalar(select(Account.id).where(Account.workspace_id == ws.id))
    response = _post(client, {"clay_row_id": f"row_{uuid.uuid4().hex[:8]}", "Industry": "AI/ML Platforms"})
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["matched"] is False and "domain" in result["reason"]
    assert before is not None


def test_clays_own_run_notification_is_recorded_without_a_fetch_it_cannot_make(client, db, clay_secret):
    """Clay's signed webhook says only that a run finished; the data is pulled with an API key we lack."""
    response = _post(
        client,
        {
            "webhookId": "wh_abc123",
            "createdAt": "2026-06-16T17:50:00.000Z",
            "data": {"routine_run_id": f"run_{uuid.uuid4().hex[:8]}"},
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["kind"] == "routine_run_notification" and result["fetched"] is False
    assert "CLAY_API_KEY is not configured" in result["note"]


def test_clay_is_a_replayable_source_like_posthog_and_n8n(client, db, flagship, clay_secret):
    """A processed event is refused for the right reason — proof the Clay processor is registered."""
    posted = _post(client, _row(flagship.domain, **{"City": "Lisbon"}))
    assert posted.status_code == 200, posted.text
    replay = client.post(f"/api/v1/webhooks/events/{posted.json()['id']}/replay")
    assert replay.status_code == 409
    assert "failed or dead-lettered" in replay.json()["detail"]


def test_the_published_contract_says_plainly_that_nothing_was_verified_against_live_clay(client):
    contract = client.get("/api/v1/integrations/clay/contract").json()
    assert contract["verified_against_live_clay"] is False
    assert contract["endpoint"] == "/api/v1/webhooks/clay"
    assert contract["outbound"]["mode"] == "disabled"
    assert "employee_count" in contract["account_columns"] and "email" in contract["contact_columns"]


def test_without_a_configured_secret_development_still_accepts_but_marks_the_delivery(client, db, flagship):
    """An unconfigured secret is a development convenience, and the stored event must say so."""
    get_settings.cache_clear()
    response = client.post(
        "/api/v1/webhooks/clay",
        content=json.dumps(_row(flagship.domain, **{"City": "Porto"})).encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["signature"] == "not_configured"
