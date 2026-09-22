"""Webhook authentication.

* GTMOS signature (n8n, generic senders, internal tools):
      X-GTMOS-Timestamp: <unix seconds>
      X-GTMOS-Signature: sha256=<hex HMAC-SHA256(secret, f"{timestamp}.{raw_body}")>
  Signed timestamps prevent replay outside a 5-minute window.
* Shared-token header (PostHog destinations, which can add static headers but not compute HMACs):
      X-GTMOS-Webhook-Token: <secret>
* HubSpot v3 (inbound CRM webhooks):
      X-HubSpot-Signature-v3 = base64(HMAC-SHA256(client_secret, method + uri + body + timestamp))
      X-HubSpot-Request-Timestamp (ms), rejected if older than 5 minutes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from urllib.parse import unquote

MAX_SKEW_SECONDS = 300


def sign_gtmos(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


def verify_gtmos(
    secret: str, timestamp: str | None, signature: str | None, body: bytes, now: float | None = None
) -> tuple[bool, str]:
    if not timestamp or not signature:
        return False, "missing signature headers"
    try:
        ts = int(timestamp)
    except ValueError:
        return False, "invalid timestamp"
    now = time.time() if now is None else now
    if abs(now - ts) > MAX_SKEW_SECONDS:
        return False, "timestamp outside 5-minute window (possible replay)"
    expected = sign_gtmos(secret, timestamp, body)
    if not hmac.compare_digest(expected, signature.strip()):
        return False, "signature mismatch"
    return True, "valid"


def verify_token(secret: str, token: str | None) -> tuple[bool, str]:
    if not token:
        return False, "missing token header"
    return (True, "valid") if hmac.compare_digest(secret, token) else (False, "token mismatch")


def hubspot_v3_signature(client_secret: str, method: str, uri: str, body: bytes, timestamp: str) -> str:
    source = method.upper().encode() + unquote(uri).encode() + body + timestamp.encode()
    return base64.b64encode(hmac.new(client_secret.encode(), source, hashlib.sha256).digest()).decode()


def verify_hubspot_v3(
    client_secret: str,
    method: str,
    uri: str,
    body: bytes,
    signature: str | None,
    timestamp_ms: str | None,
    now: float | None = None,
) -> tuple[bool, str]:
    if not signature or not timestamp_ms:
        return False, "missing HubSpot signature headers"
    try:
        ts = int(timestamp_ms) / 1000.0
    except ValueError:
        return False, "invalid timestamp"
    now = time.time() if now is None else now
    if now - ts > MAX_SKEW_SECONDS:
        return False, "timestamp older than 5 minutes"
    expected = hubspot_v3_signature(client_secret, method, uri, body, timestamp_ms)
    return (True, "valid") if hmac.compare_digest(expected, signature) else (False, "signature mismatch")
