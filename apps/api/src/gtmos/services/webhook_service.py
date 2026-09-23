"""Webhook ingestion: verify → store raw → dedupe → process → record outcome (with replay support)."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gtmos.config import get_settings
from gtmos.integrations.signatures import verify_gtmos, verify_hubspot, verify_token
from gtmos.models import WebhookEvent
from gtmos.services.common import correlation_id, utcnow

MAX_ATTEMPTS = 3
Processor = Callable[[Session, dict[str, Any] | list[Any]], dict[str, Any]]


@dataclass
class VerifyResult:
    status: str  # valid | invalid | not_configured
    detail: str


def verify_request(
    source: str, headers: dict[str, str], body: bytes, method: str = "POST", uri: str = ""
) -> VerifyResult:
    s = get_settings()
    h = {k.lower(): v for k, v in headers.items()}
    if source == "hubspot":
        secret = s.hubspot_webhook_client_secret
        if secret is None:
            return VerifyResult("not_configured", "HUBSPOT_WEBHOOK_CLIENT_SECRET not set")
        ok, why = verify_hubspot(
            secret.get_secret_value(),
            method,
            uri,
            body,
            signature_v3=h.get("x-hubspot-signature-v3"),
            timestamp_ms=h.get("x-hubspot-request-timestamp"),
            signature_v1_or_v2=h.get("x-hubspot-signature"),
            signature_version=h.get("x-hubspot-signature-version"),
        )
        return VerifyResult("valid" if ok else "invalid", why)
    if s.webhook_secret is None:
        return VerifyResult("not_configured", "WEBHOOK_SECRET not set (accepted in development only)")
    secret_value = s.webhook_secret.get_secret_value()
    if "x-gtmos-signature" in h:
        ok, why = verify_gtmos(secret_value, h.get("x-gtmos-timestamp"), h.get("x-gtmos-signature"), body)
    else:
        ok, why = verify_token(secret_value, h.get("x-gtmos-webhook-token"))
    return VerifyResult("valid" if ok else "invalid", why)


EVENT_ID_KEYS = ("uuid", "event_id", "eventId", "id")
# Fields a sender changes between retries of the *same* event. They must not reach the body hash, or a
# redelivery would look like a new event. HubSpot increments `attemptNumber` on every retry.
RETRY_VOLATILE_KEYS = frozenset({"attemptNumber", "attempt_number", "attempt", "retryCount", "deliveryId"})


def _event_id(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    for key in EVENT_ID_KEYS:
        # `is not None` rather than truthiness: HubSpot event ids are integers and 0 is a valid one.
        value = item.get(key)
        if value is not None and str(value) != "":
            return str(value)
    return None


def _stable_body(payload: Any) -> bytes:
    """Canonical JSON with per-retry fields stripped, so the hash identifies the event, not the attempt."""

    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k not in RETRY_VOLATILE_KEYS}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    return json.dumps(strip(payload), sort_keys=True, separators=(",", ":"), default=str).encode()


def idempotency_key_for(source: str, payload: Any, headers: dict[str, str], body: bytes) -> str:
    """A key that is identical across redeliveries of the same event and distinct across different ones.

    HubSpot posts a JSON *array* of events and bumps `attemptNumber` on each retry, so keying on the raw
    body would make every retry look new and defeat deduplication entirely. Batches are keyed by their
    member event ids; only a payload with no usable id at all falls back to a hash, and that hash is
    taken over a canonical form with the retry counters removed.
    """
    h = {k.lower(): v for k, v in headers.items()}
    if explicit := h.get("idempotency-key") or h.get("x-idempotency-key"):
        return explicit[:200]
    if (single := _event_id(payload)) is not None:
        return f"{source}:{single}"[:200]
    if isinstance(payload, list) and payload:
        ids = [_event_id(item) for item in payload]
        if all(i is not None for i in ids):
            # Order is not guaranteed across redeliveries of a batch, so sort before joining. Long
            # batches collapse to a hash of their ids to stay inside the column width.
            joined = ",".join(sorted(str(i) for i in ids))
            digest = f"{source}:batch:{joined}"
            if len(digest) > 200:
                digest = f"{source}:batch:sha256:{hashlib.sha256(joined.encode()).hexdigest()}"
            return digest
    if payload is not None:
        return f"{source}:sha256:{hashlib.sha256(_stable_body(payload)).hexdigest()}"
    return f"{source}:sha256:{hashlib.sha256(body).hexdigest()}"


@dataclass
class ReceiveResult:
    event: WebhookEvent
    duplicate: bool
    http_status: int


def receive(
    db: Session,
    workspace_id: uuid.UUID,
    source: str,
    event_type: str,
    headers: dict[str, str],
    body: bytes,
    processor: Processor,
    *,
    method: str = "POST",
    uri: str = "",
) -> ReceiveResult:
    verification = verify_request(source, headers, body, method, uri)
    if verification.status == "not_configured" and get_settings().env == "production":
        verification = VerifyResult("invalid", "webhook secret must be configured in production")
    try:
        payload: Any = json.loads(body or b"{}")
    except json.JSONDecodeError:
        payload = None
    now = utcnow()
    key = idempotency_key_for(source, payload, headers, body)

    existing = db.scalars(
        select(WebhookEvent).where(WebhookEvent.source == source, WebhookEvent.idempotency_key == key)
    ).first()
    if existing is not None and existing.status == "failed" and verification.status != "invalid":
        # The sender is retrying an event we failed to process: process it again instead of acking a failure.
        existing.attempts += 1
        existing.duplicate_count += 1
        _process(db, existing, payload, processor)
        return ReceiveResult(existing, False, 200 if existing.status == "processed" else 202)
    if existing is not None and verification.status == "invalid":
        # An unsigned or badly signed delivery is rejected whatever we have seen before. Without this,
        # knowing (or guessing) an event id would be enough to get a 200 out of the endpoint and to
        # inflate another event's duplicate counter. The stored event is left untouched: a forged
        # delivery must not be able to change the status of an event that was legitimately processed.
        return ReceiveResult(existing, False, 401)
    if existing is not None and existing.status != "rejected":
        existing.duplicate_count += 1
        db.flush()
        return ReceiveResult(existing, True, 200)
    if existing is not None:
        # A rejected (unauthenticated or malformed) delivery never counts as "seen": otherwise anyone could
        # pre-empt a legitimate event by sending an unsigned copy first. Re-evaluate this delivery in place.
        existing.attempts += 1
        existing.signature_status = verification.status
        existing.payload = payload if isinstance(payload, dict) else {"_items": payload}
        existing.correlation_id = correlation_id()
        existing.received_at = now
        existing.error = None
        existing.status = "received"
        ev = existing
        return _finish(db, ev, verification, payload, processor)

    ev = WebhookEvent(
        workspace_id=workspace_id,
        source=source,
        event_type=event_type,
        idempotency_key=key,
        signature_status=verification.status,
        payload=payload if isinstance(payload, dict) else {"_items": payload},
        status="received",
        correlation_id=correlation_id(),
        received_at=now,
    )
    db.add(ev)
    db.flush()
    return _finish(db, ev, verification, payload, processor)


def _finish(
    db: Session, ev: WebhookEvent, verification: VerifyResult, payload: Any, processor: Processor
) -> ReceiveResult:
    if verification.status == "invalid":
        ev.status = "rejected"
        ev.error = f"signature check failed: {verification.detail}"
        ev.processed_at = utcnow()
        return ReceiveResult(ev, False, 401)
    if payload is None:
        ev.status = "rejected"
        ev.error = "body is not valid JSON"
        return ReceiveResult(ev, False, 400)
    _process(db, ev, payload, processor)
    if ev.status == "processed":
        return ReceiveResult(ev, False, 200)
    # 422 for a body that can never work, 202 for one worth retrying. The distinction is what stops a
    # well-behaved sender from redelivering a malformed payload ten times.
    return ReceiveResult(ev, False, 422 if ev.status == "rejected" else 202)


class PermanentError(Exception):
    """The delivery can never succeed, however many times it is sent.

    A malformed body, a missing required field, an unknown event shape. Distinguished from a transient
    failure because the two deserve opposite answers: a transient failure should be retried, and telling
    a sender to retry a body that is structurally wrong makes it hammer the endpoint until the event
    dead-letters. HubSpot retries ten times over 24 hours on a non-2xx, so that is ten guaranteed-futile
    deliveries per bad payload.
    """


def _process(db: Session, ev: WebhookEvent, payload: Any, processor: Processor) -> None:
    t0 = time.perf_counter()
    try:
        with db.begin_nested():
            ev.result = processor(db, payload)
        ev.status = "processed"
        ev.error = None
    except PermanentError as exc:
        # Rejected, not failed: the sender should stop, and `replay` should not offer to re-run it.
        ev.error = f"{exc.__class__.__name__}: {exc}"[:2000]
        ev.status = "rejected"
    except Exception as exc:
        ev.error = f"{exc.__class__.__name__}: {exc}"[:2000]
        ev.status = "dead_letter" if ev.attempts >= MAX_ATTEMPTS else "failed"
    ev.processed_at = utcnow()
    ev.processing_ms = int((time.perf_counter() - t0) * 1000)
    db.flush()


def replay(db: Session, ev: WebhookEvent, processor: Processor) -> WebhookEvent:
    if ev.status not in ("failed", "dead_letter"):
        raise ValueError("only failed or dead-lettered events can be replayed")
    ev.attempts += 1
    payload: Any = ev.payload.get("_items") if "_items" in ev.payload else ev.payload
    _process(db, ev, payload, processor)
    return ev
