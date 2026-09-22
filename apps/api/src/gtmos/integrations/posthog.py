"""PostHog-compatible product event parsing.

Accepts the shape PostHog uses for captured events and webhook destinations:
    {"event": "...", "distinct_id": "...", "timestamp": "...", "uuid": "...",
     "properties": {"$groups": {"company": "acme.example"}, "email": "...", ...}}
Either a single event, a list, or {"batch": [...]} is accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class PostHogEvent(BaseModel):
    event: str = Field(min_length=1, max_length=120)
    distinct_id: str | None = Field(default=None, max_length=320)
    timestamp: datetime | None = None
    uuid: str | None = Field(default=None, max_length=100)
    properties: dict[str, Any] = Field(default_factory=dict)


@dataclass
class NormalizedEvent:
    event: str
    event_id: str
    distinct_id: str | None
    email: str | None
    company_domain: str | None
    occurred_at: datetime
    properties: dict[str, Any] = field(default_factory=dict)


def parse_payload(payload: Any) -> list[PostHogEvent]:
    if isinstance(payload, dict) and "batch" in payload:
        items = payload["batch"]
    elif isinstance(payload, list):
        items = payload
    else:
        items = [payload]
    return [PostHogEvent.model_validate(i) for i in items]


def normalize(ev: PostHogEvent, received_at: datetime | None = None) -> NormalizedEvent:
    props = ev.properties or {}
    groups = props.get("$groups") or {}
    company = groups.get("company") if isinstance(groups, dict) else None
    email = props.get("email") or props.get("$email")
    if not email and ev.distinct_id and "@" in ev.distinct_id:
        email = ev.distinct_id
    ts = ev.timestamp or received_at or datetime.now(UTC)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    event_id = ev.uuid or f"{ev.event}:{ev.distinct_id}:{ts.isoformat()}"
    clean = {k: v for k, v in props.items() if not k.startswith("$") or k in ("$current_url", "$pathname")}
    return NormalizedEvent(ev.event, event_id, ev.distinct_id, email, company, ts, clean)


# Product events that map directly to GTMOS signals.
EVENT_SIGNAL_MAP = {
    "workspace_created": "product_signup",
    "signed_up": "product_signup",
    "teammate_invited": "teammate_invited",
    "integration_connected": "integration_activated",
    "trace_volume_threshold": "usage_threshold",
}
PRICING_EVENTS = {"pricing_page_viewed"}
PQL_SIGNALS = {"usage_threshold"}
