"""Clay (clay.com) integration boundary.

Clay is a per-field resolution service; GTMOS is the system of record. Data flows Clay → GTMOS and
never the reverse as authority — which is also the technical reality, since Clay's Public API is
read-only for tables and cannot write rows (`docs/research/clay.md` §5b).

Two directions live here, and they are gated very differently:

* **Inbound (free tier, and the one that carries data).** Clay POSTs to a URL we own and signs the
  exact request body with HMAC-SHA256, sending `sha256=<hex>` in `X-Clay-Signature`. The signing
  secret is returned exactly once when the webhook is registered. There is **no timestamp header**
  in Clay's documented delivery, so the signature alone carries no replay protection — that comes
  from idempotent dedupe in `webhook_service`, the same weaker guarantee HubSpot v1 gets.
* **Outbound (`ClayClient`).** The Public API at `https://api.clay.com/public/v0`, authenticated by
  a single `clay-api-key` header. Everything is asynchronous: a routine run returns a run id, and
  results come back as HTTP 202 with progress counters until the run finishes.

`ClayClient` is **inert without an API key**: every call raises `ClayNotConfigured` rather than
reaching the network, so demo mode (no key in the environment) physically cannot bill a workspace.
It has **not** been exercised against a live Clay workspace — no account exists. It is written
against Clay's published contract and tested with `httpx.MockTransport`. See `docs/clay-live-setup.md`
for exactly which parts that leaves unverified.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from gtmos.config import Settings

CLAY_API_BASE = "https://api.clay.com/public/v0"
SIGNATURE_HEADER = "X-Clay-Signature"
API_KEY_HEADER = "clay-api-key"

# Clay's inline routine run accepts 1–100 items; larger volumes go through the JSONL batch path.
MAX_RUN_ITEMS = 100


def clay_signature(secret: str, body: bytes) -> str:
    """`sha256=<hex HMAC-SHA256(signingSecret, raw body)>`, the format Clay sends."""
    return f"sha256={hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}"


def verify_clay(secret: str, signature: str | None, body: bytes) -> tuple[bool, str]:
    """Verify an inbound Clay delivery against the **raw** request bytes.

    Re-serialising the parsed JSON and hashing that is the classic way to break this: key order and
    whitespace are not preserved, so the digest never matches. FastAPI hands us the original bytes
    and they are what we hash.
    """
    if not signature:
        return False, f"missing {SIGNATURE_HEADER} header"
    candidate = signature.strip()
    expected = clay_signature(secret, body)
    if hmac.compare_digest(expected, candidate):
        return True, "valid (no replay window — deduped on Clay row/run id instead)"
    # Clay documents the `sha256=` prefix, but a hand-rolled test sender often omits it. Accepting the
    # bare hex costs nothing and fails closed either way.
    if hmac.compare_digest(expected.split("=", 1)[1], candidate):
        return True, "valid (bare hex; no replay window — deduped on Clay row/run id instead)"
    return False, "signature mismatch"


class ClayError(Exception):
    """Any failure talking to Clay. Clay returns `{"message": "..."}` with no stable error codes."""


class ClayNotConfigured(ClayError):
    """No CLAY_API_KEY. The outbound client refuses to do anything rather than half-work."""


class ClayAuthError(ClayError):
    pass


class ClayQuotaExceeded(ClayError):
    """HTTP 402 — a plan limit was hit. Clay names the limit in the message and nowhere else."""


class ClayRateLimited(ClayError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# Clay warns that the set of terminal statuses is not closed: "treat unrecognized `status` values as
# an unhandled terminal outcome". So this set is what we *recognise*, not what Clay may send.
KNOWN_TERMINAL_STATUSES = frozenset({"complete", "completed", "failed", "cancelled", "canceled"})


@dataclass(frozen=True)
class RoutineRun:
    run_id: str
    status: str
    running: bool  # the results endpoint answered 202: still in progress
    total: int = 0
    finished: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)

    @property
    def recognized(self) -> bool:
        return self.running or self.status in KNOWN_TERMINAL_STATUSES

    @property
    def succeeded(self) -> bool:
        return self.status in ("complete", "completed")

    @property
    def failed_items(self) -> list[dict[str, Any]]:
        """A completed run can still contain failed items; per-item status is the only way to see it."""
        return [i for i in self.items if str(i.get("status", "")).lower() not in ("success", "complete", "completed")]


class ClayClient:
    """Clay Public API client. Async by design: dispatch, then poll or wait for the signed webhook."""

    def __init__(
        self,
        api_key: str | None,
        *,
        client: httpx.Client | None = None,
        base_url: str = CLAY_API_BASE,
        timeout: float = 15.0,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)
        self._max_retries = max_retries
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> ClayClient:
        key = settings.clay_api_key.get_secret_value() if settings.clay_api_key else None
        return cls(key, **kwargs)

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    @property
    def mode(self) -> str:
        return "live" if self.enabled else "disabled"

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | None:
        if not self._api_key:
            raise ClayNotConfigured("CLAY_API_KEY is not set; the Clay client makes no network calls")
        url = f"{self._base_url}{path}"
        headers = {API_KEY_HEADER: self._api_key, "Accept": "application/json"}
        for attempt in range(self._max_retries):
            try:
                response = self._client.request(method, url, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                raise ClayError(f"clay: {exc.__class__.__name__}") from exc
            if response.status_code == 429:
                retry_after = _retry_after(response)
                if attempt + 1 >= self._max_retries:
                    raise ClayRateLimited(_message(response, "rate limited"), retry_after)
                # Clay does not publish the numeric limit, so honouring Retry-After is the only
                # correct backoff; the header is the ceiling we are told about.
                self._sleep(retry_after if retry_after is not None else 2.0 * (attempt + 1))
                continue
            if response.status_code >= 500:
                if attempt + 1 >= self._max_retries:
                    raise ClayError(_message(response, f"HTTP {response.status_code}"))
                self._sleep(1.0 * (attempt + 1))
                continue
            return _decode(response)
        raise ClayError("clay: retries exhausted")

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/me") or {}

    def credits(self) -> dict[str, Any]:
        """Workspace credit balances. Reading balances does not consume credits."""
        return self._request("GET", "/credits") or {}

    def run_routine(self, routine_id: str, items: list[dict[str, Any]], *, webhook_id: str | None = None) -> str:
        """Dispatch a routine over 1–100 inline items and return its `routine_run_id`.

        Passing `webhook_id` is what turns this into notify-then-pull: Clay POSTs the signed
        completion notification to that registered webhook instead of us polling.
        """
        if not items:
            raise ValueError("a routine run needs at least one item")
        if len(items) > MAX_RUN_ITEMS:
            raise ValueError(f"a routine run accepts at most {MAX_RUN_ITEMS} items; use the batch path")
        body: dict[str, Any] = {"items": items}
        if webhook_id:
            body["webhook_id"] = webhook_id
        data = self._request("POST", f"/routines/{routine_id}/run", json=body) or {}
        run_id = data.get("routine_run_id") or data.get("id")
        if not isinstance(run_id, str) or not run_id:
            raise ClayError("clay: routine run response carried no routine_run_id")
        return run_id

    def run_results(self, run_id: str) -> RoutineRun:
        """202 with progress counters while running; 200 with results when the run is terminal."""
        if not self._api_key:
            raise ClayNotConfigured("CLAY_API_KEY is not set; the Clay client makes no network calls")
        url = f"{self._base_url}/routines/run/{run_id}/results"
        headers = {API_KEY_HEADER: self._api_key, "Accept": "application/json"}
        try:
            response = self._client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise ClayError(f"clay: {exc.__class__.__name__}") from exc
        if response.status_code == 429:
            raise ClayRateLimited(_message(response, "rate limited"), _retry_after(response))
        data = _decode(response) or {}
        status = str(data.get("status") or ("running" if response.status_code == 202 else "unknown"))
        items = data.get("results") or data.get("items") or []
        return RoutineRun(
            run_id=run_id,
            status=status,
            running=response.status_code == 202,
            total=int(data.get("total") or 0),
            finished=int(data.get("finished") or 0),
            items=list(items) if isinstance(items, list) else [],
        )

    def wait_for_results(self, run_id: str, *, poll_interval: float = 2.0, max_polls: int = 30) -> RoutineRun:
        """Poll at a modest interval, as Clay instructs. Prefer a webhook when one is registered."""
        run = self.run_results(run_id)
        for _ in range(max_polls):
            if not run.running:
                return run
            self._sleep(poll_interval)
            run = self.run_results(run_id)
        return run


def _decode(response: httpx.Response) -> dict[str, Any] | None:
    if response.status_code in (401, 403):
        raise ClayAuthError(_message(response, "unauthorized — check the clay-api-key header"))
    if response.status_code == 402:
        raise ClayQuotaExceeded(_message(response, "plan limit exceeded"))
    if response.status_code >= 400:
        raise ClayError(_message(response, f"HTTP {response.status_code}"))
    if not response.content:
        return None
    try:
        body = response.json()
    except ValueError as exc:
        raise ClayError("clay: response body was not JSON") from exc
    return body if isinstance(body, dict) else {"data": body}


def _message(response: httpx.Response, fallback: str) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None
    detail = body.get("message") if isinstance(body, dict) else None
    return f"clay: {detail or fallback} (HTTP {response.status_code})"


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
