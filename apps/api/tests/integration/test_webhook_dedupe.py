"""Deduplication of real-world webhook deliveries.

HubSpot posts a JSON *array* of events and retries a failed delivery up to ten times over 24 hours,
incrementing `attemptNumber` each time. Those two facts together broke the original idempotency key:
the array had no top-level id so the key fell back to a hash of the body, and the changing attempt
counter made every retry hash differently. The endpoint therefore deduplicated nothing.
"""

from __future__ import annotations

import json
import time
import uuid

from sqlalchemy import select

from gtmos.config import get_settings
from gtmos.integrations.signatures import hubspot_v3_signature
from gtmos.models import WebhookEvent
from gtmos.services.webhook_service import idempotency_key_for


def _hubspot_events(attempt: int, event_ids: list[int]) -> list[dict[str, object]]:
    return [
        {
            "eventId": eid,
            "subscriptionId": 1_000_001,
            "portalId": 12_345_678,
            "occurredAt": 1_767_225_600_000 + eid,
            "subscriptionType": "company.propertyChange",
            "attemptNumber": attempt,
            "objectId": 5_000 + eid,
            "propertyName": "name",
            "propertyValue": "Renamed by a rep",
        }
        for eid in event_ids
    ]


def test_batch_key_is_stable_across_retries_of_the_same_batch():
    first = _hubspot_events(0, [101, 102])
    retry = _hubspot_events(3, [102, 101])  # same events, later attempt, different order
    key = idempotency_key_for("hubspot", first, {}, json.dumps(first).encode())
    assert key == idempotency_key_for("hubspot", retry, {}, json.dumps(retry).encode())
    assert "sha256" not in key, "a batch with usable event ids should not fall back to a body hash"


def test_batch_key_distinguishes_different_events():
    a = _hubspot_events(0, [101, 102])
    b = _hubspot_events(0, [101, 103])
    assert idempotency_key_for("hubspot", a, {}, b"") != idempotency_key_for("hubspot", b, {}, b"")


def test_long_batches_collapse_to_a_hash_that_still_fits_the_column():
    big = _hubspot_events(0, list(range(500)))
    key = idempotency_key_for("hubspot", big, {}, b"")
    assert len(key) <= 200
    assert key == idempotency_key_for("hubspot", _hubspot_events(7, list(range(499, -1, -1))), {}, b"")


def test_payloads_without_ids_hash_the_event_not_the_attempt():
    """The last-resort hash must ignore retry counters, or a redelivery looks like a new event."""
    first = [{"attemptNumber": 0, "propertyName": "name", "propertyValue": "Acme"}]
    retry = [{"attemptNumber": 4, "propertyName": "name", "propertyValue": "Acme"}]
    assert idempotency_key_for("hubspot", first, {}, json.dumps(first).encode()) == idempotency_key_for(
        "hubspot", retry, {}, json.dumps(retry).encode()
    )
    changed = [{"attemptNumber": 0, "propertyName": "name", "propertyValue": "Different"}]
    assert idempotency_key_for("hubspot", first, {}, b"") != idempotency_key_for("hubspot", changed, {}, b"")


def test_an_explicit_idempotency_header_always_wins():
    payload = _hubspot_events(0, [1])
    key = idempotency_key_for("hubspot", payload, {"Idempotency-Key": "from-header"}, b"")
    assert key == "from-header"


def test_hubspot_retry_of_an_array_body_is_recognised_as_a_duplicate(client, db, monkeypatch):
    monkeypatch.setenv("HUBSPOT_WEBHOOK_CLIENT_SECRET", "hs-secret")
    get_settings.cache_clear()
    try:
        eids = [int(uuid.uuid4().int % 10**9), int(uuid.uuid4().int % 10**9)]

        def post(attempt: int):
            body = json.dumps(_hubspot_events(attempt, eids)).encode()
            ts = str(int(time.time() * 1000))
            url = "http://testserver/api/v1/webhooks/hubspot"
            return client.post(
                "/api/v1/webhooks/hubspot",
                content=body,
                headers={
                    "content-type": "application/json",
                    "X-HubSpot-Request-Timestamp": ts,
                    "X-HubSpot-Signature-v3": hubspot_v3_signature("hs-secret", "POST", url, body, ts),
                },
            )

        first = post(0)
        assert first.status_code == 200, first.text
        assert first.json()["duplicate"] is False

        # HubSpot redelivers the same batch as attempt 3 after a timeout on our side.
        second = post(3)
        assert second.status_code == 200, second.text
        assert second.json()["duplicate"] is True, "a HubSpot retry must not be stored as a new event"
        assert second.json()["id"] == first.json()["id"]

        stored = list(db.scalars(select(WebhookEvent).where(WebhookEvent.source == "hubspot")))
        matching = [e for e in stored if e.id == uuid.UUID(first.json()["id"])]
        assert len(matching) == 1
        assert matching[0].duplicate_count == 1
    finally:
        monkeypatch.delenv("HUBSPOT_WEBHOOK_CLIENT_SECRET")
        get_settings.cache_clear()


def test_a_forged_delivery_cannot_touch_an_event_we_already_processed(client, db, monkeypatch):
    """Knowing an event id must not be enough to get a 200, nor to alter the stored event."""
    monkeypatch.setenv("HUBSPOT_WEBHOOK_CLIENT_SECRET", "hs-secret")
    get_settings.cache_clear()
    try:
        eids = [int(uuid.uuid4().int % 10**9)]
        body = json.dumps(_hubspot_events(0, eids)).encode()
        ts = str(int(time.time() * 1000))
        url = "http://testserver/api/v1/webhooks/hubspot"
        good = client.post(
            "/api/v1/webhooks/hubspot",
            content=body,
            headers={
                "content-type": "application/json",
                "X-HubSpot-Request-Timestamp": ts,
                "X-HubSpot-Signature-v3": hubspot_v3_signature("hs-secret", "POST", url, body, ts),
            },
        )
        assert good.status_code == 200, good.text
        event_id = uuid.UUID(good.json()["id"])
        before = db.get(WebhookEvent, event_id)
        assert before is not None
        status_before, duplicates_before = before.status, before.duplicate_count

        forged = client.post("/api/v1/webhooks/hubspot", content=body, headers={"content-type": "application/json"})
        assert forged.status_code == 401, "an unsigned delivery must be rejected even for a known event id"

        db.expire_all()
        after = db.get(WebhookEvent, event_id)
        assert after is not None
        assert after.status == status_before, "a forged delivery must not change a processed event's status"
        assert after.duplicate_count == duplicates_before, "a forged delivery must not count as a duplicate"
    finally:
        monkeypatch.delenv("HUBSPOT_WEBHOOK_CLIENT_SECRET")
        get_settings.cache_clear()
