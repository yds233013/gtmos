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
    """HMAC-SHA256(secret, method + uri + rawBody + timestamp), base64, no delimiters.

    Two details are where implementations go wrong, both confirmed in `docs/research/hubspot.md`:

    * The **raw request body bytes** are hashed, not a re-serialised object. HubSpot's own Node sample
      uses `JSON.stringify(body)`, which re-orders and re-spaces the JSON and is the single most common
      cause of a mismatch. FastAPI gives us the raw bytes, so we keep them.
    * The URI is used **exactly as received**. An earlier version ran `unquote()` over it, which
      corrupts any request whose path or query carries a percent-encoded character — HubSpot signs what
      it sent, not a decoded form of it.
    """
    source = method.upper().encode() + uri.encode() + body + timestamp.encode()
    return base64.b64encode(hmac.new(client_secret.encode(), source, hashlib.sha256).digest()).decode()


def hubspot_v1_signature(client_secret: str, body: bytes) -> str:
    """SHA-256 of `clientSecret + requestBody`, hex. A plain hash, not an HMAC.

    This is the scheme **private app webhooks** use, which matters more than it looks: a private app is
    what someone sets up in a free developer test account, so a verifier that only understands v3
    rejects every delivery from the most likely test environment.
    """
    return hashlib.sha256(client_secret.encode() + body).hexdigest()


def hubspot_v2_signature(client_secret: str, method: str, uri: str, body: bytes) -> str:
    """SHA-256 of `clientSecret + method + uri + body`, hex. Used by workflow webhook actions.

    The URI must match the original request exactly, including protocol and query-parameter order.
    """
    return hashlib.sha256(client_secret.encode() + method.upper().encode() + uri.encode() + body).hexdigest()


def verify_hubspot(
    client_secret: str,
    method: str,
    uri: str,
    body: bytes,
    *,
    signature_v3: str | None,
    timestamp_ms: str | None,
    signature_v1_or_v2: str | None = None,
    signature_version: str | None = None,
    now: float | None = None,
) -> tuple[bool, str]:
    """Verify a HubSpot webhook, preferring v3 and falling back to v1/v2.

    Which scheme arrives depends on how the integration was registered, and the difference is not
    cosmetic:

    * **v3** (`X-HubSpot-Signature-v3` + `X-HubSpot-Request-Timestamp`) is HMAC-based, replay-protected
      by a 5-minute window, and is what OAuth/public apps receive.
    * **v1** (`X-HubSpot-Signature`) is a plain SHA-256 of `secret + body` with **no timestamp and no
      replay protection**, and it is what **private app** webhooks are documented to send. A private app
      is exactly what a free developer test account uses, so refusing v1 would mean the integration
      cannot be tested in the environment it is most likely to be tested in.

    Because v1 carries no timestamp, replay protection for that path comes from the event-id
    deduplication in `webhook_service`, not from the signature. That is a weaker guarantee and the
    returned detail says which path verified, so the Operations page can show it.
    """
    if signature_v3 and timestamp_ms:
        return _verify_hubspot_v3(client_secret, method, uri, body, signature_v3, timestamp_ms, now)
    if signature_v1_or_v2:
        version = (signature_version or "v1").lower()
        if version == "v2":
            expected = hubspot_v2_signature(client_secret, method, uri, body)
        else:
            expected = hubspot_v1_signature(client_secret, body)
        if hmac.compare_digest(expected, signature_v1_or_v2):
            return True, f"valid ({version}; no replay window — deduped on event id instead)"
        return False, f"signature mismatch ({version})"
    return False, "missing HubSpot signature headers"


def _verify_hubspot_v3(
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
    if ts - now > MAX_SKEW_SECONDS:
        return False, "timestamp is in the future"
    expected = hubspot_v3_signature(client_secret, method, uri, body, timestamp_ms)
    return (True, "valid (v3)") if hmac.compare_digest(expected, signature) else (False, "signature mismatch (v3)")
