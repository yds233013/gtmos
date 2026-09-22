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
from gtmos.integrations.signatures import verify_gtmos, verify_hubspot_v3, verify_token
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
        ok, why = verify_hubspot_v3(
            secret.get_secret_value(),
            method,
            uri,
            body,
            h.get("x-hubspot-signature-v3"),
            h.get("x-hubspot-request-timestamp"),
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


def idempotency_key_for(source: str, payload: Any, headers: dict[str, str], body: bytes) -> str:
    h = {k.lower(): v for k, v in headers.items()}
    if explicit := h.get("idempotency-key") or h.get("x-idempotency-key"):
        return explicit[:200]
    if isinstance(payload, dict):
        for key in ("uuid", "event_id", "eventId", "id"):
            if payload.get(key):
                return f"{source}:{payload[key]}"[:200]
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


def _finish(db: Session, ev: WebhookEvent, verification: VerifyResult, payload: Any, processor: Processor
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
    return ReceiveResult(ev, False, 200 if ev.status == "processed" else 202)


def _process(db: Session, ev: WebhookEvent, payload: Any, processor: Processor) -> None:
    t0 = time.perf_counter()
    try:
        with db.begin_nested():
            ev.result = processor(db, payload)
        ev.status = "processed"
        ev.error = None
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
