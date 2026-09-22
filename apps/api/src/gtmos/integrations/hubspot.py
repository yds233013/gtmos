"""HubSpot integration boundary.

GTMOS → HubSpot object mapping
    Account      → Company  (upsert on custom unique property `gtmos_account_id`)
    Contact      → Contact  (upsert on `email`)
    Opportunity  → Deal     (upsert on custom unique property `gtmos_opportunity_id`)

Why not upsert companies on `domain`? HubSpot does not enforce `domain` uniqueness, so batch upsert
rejects it as an idProperty. We create our own unique property (hasUniqueValue=true) and key on it,
which also makes every write idempotent: replaying a sync can't create duplicates.

Two adapters implement the same protocol:
  * DemoHubSpotAdapter: writes to the `simulated_crm_objects` table. Every sync it performs is
    recorded with is_simulated=True and labeled SIMULATED in the UI. It injects deterministic transient
    failures (simulated 429s) so retry handling is exercised.
  * RealHubSpotAdapter: calls the HubSpot CRM v3 batch upsert API with a private-app token. Only used
    when HUBSPOT_ACCESS_TOKEN is set *and* HUBSPOT_LIVE_WRITES_ENABLED=true. Not exercised against a
    live portal in this repository (no credentials were available).
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from gtmos.models import SimulatedCrmObject

log = logging.getLogger(__name__)

BATCH_LIMIT = 100  # HubSpot batch endpoints accept at most 100 inputs

ID_PROPERTY = {"companies": "gtmos_account_id", "contacts": "email", "deals": "gtmos_opportunity_id"}

# Custom properties GTMOS needs in the portal (created by RealHubSpotAdapter.ensure_properties()).
CUSTOM_PROPERTIES: dict[str, list[dict[str, Any]]] = {
    "companies": [
        {
            "name": "gtmos_account_id",
            "label": "GTMOS Account ID",
            "type": "string",
            "fieldType": "text",
            "hasUniqueValue": True,
        },
        {"name": "gtmos_icp_score", "label": "GTMOS ICP Score", "type": "number", "fieldType": "number"},
        {"name": "gtmos_intent_score", "label": "GTMOS Intent Score", "type": "number", "fieldType": "number"},
        {"name": "gtmos_score_grade", "label": "GTMOS Score Grade", "type": "string", "fieldType": "text"},
        {"name": "gtmos_account_tier", "label": "GTMOS Account Tier", "type": "string", "fieldType": "text"},
        {"name": "gtmos_last_signal", "label": "GTMOS Last Signal", "type": "string", "fieldType": "text"},
        {"name": "gtmos_last_signal_at", "label": "GTMOS Last Signal At", "type": "datetime", "fieldType": "date"},
        {
            "name": "gtmos_next_best_action",
            "label": "GTMOS Next Best Action",
            "type": "string",
            "fieldType": "textarea",
        },
        {"name": "gtmos_industry", "label": "GTMOS Industry", "type": "string", "fieldType": "text"},
    ],
    "contacts": [
        {"name": "gtmos_contact_id", "label": "GTMOS Contact ID", "type": "string", "fieldType": "text"},
        {"name": "gtmos_buying_role", "label": "GTMOS Buying Role", "type": "string", "fieldType": "text"},
    ],
    "deals": [
        {
            "name": "gtmos_opportunity_id",
            "label": "GTMOS Opportunity ID",
            "type": "string",
            "fieldType": "text",
            "hasUniqueValue": True,
        },
    ],
}

PROPERTY_GROUPS = {"companies": "companyinformation", "contacts": "contactinformation", "deals": "dealinformation"}

DEAL_STAGE_MAP = {
    "discovery": "appointmentscheduled",
    "evaluation": "qualifiedtobuy",
    "proposal": "presentationscheduled",
    "negotiation": "contractsent",
    "closed_won": "closedwon",
    "closed_lost": "closedlost",
}


@dataclass
class UpsertRecord:
    internal_id: uuid.UUID
    id_value: str
    properties: dict[str, Any]


@dataclass
class UpsertResult:
    internal_id: uuid.UUID
    status: str  # created | updated | failed
    external_id: str | None = None
    error: str | None = None
    retryable: bool = False


@dataclass
class BatchOutcome:
    results: list[UpsertResult] = field(default_factory=list)
    http_calls: int = 0


class CrmAdapter(Protocol):
    provider: str
    is_simulated: bool

    def upsert(self, object_type: str, records: list[UpsertRecord]) -> BatchOutcome: ...


def chunks[T](items: list[T], size: int = BATCH_LIMIT) -> list[list[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


# --------------------------------------------------------------------------------------------------
# Demo adapter
# --------------------------------------------------------------------------------------------------


def _fake_hubspot_id(object_type: str, key: str) -> str:
    return str(int(hashlib.sha256(f"{object_type}:{key}".encode()).hexdigest()[:10], 16) % 10**11)


class DemoHubSpotAdapter:
    provider = "hubspot"
    is_simulated = True
    TRANSIENT_FAILURE_RATE = 0.03

    def __init__(self, db: Session, workspace_id: uuid.UUID, fail_transiently: bool = True) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.fail_transiently = fail_transiently
        self._attempts: dict[str, int] = {}

    def _should_fail(self, key: str) -> bool:
        attempt = self._attempts.get(key, 0) + 1
        self._attempts[key] = attempt
        if not self.fail_transiently or attempt > 1:
            return False
        h = int(hashlib.sha256(f"fail:{key}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        return h < self.TRANSIENT_FAILURE_RATE

    def upsert(self, object_type: str, records: list[UpsertRecord]) -> BatchOutcome:
        out = BatchOutcome()
        now = datetime.now(UTC)
        for batch in chunks(records):
            out.http_calls += 1
            keys = [r.id_value for r in batch]
            existing = {
                o.unique_key: o
                for o in self.db.scalars(
                    select(SimulatedCrmObject).where(
                        SimulatedCrmObject.workspace_id == self.workspace_id,
                        SimulatedCrmObject.object_type == object_type,
                        SimulatedCrmObject.unique_key.in_(keys),
                    )
                )
            }
            for r in batch:
                if self._should_fail(f"{object_type}:{r.id_value}"):
                    out.results.append(
                        UpsertResult(r.internal_id, "failed", error="429 Too Many Requests (simulated)", retryable=True)
                    )
                    continue
                obj = existing.get(r.id_value)
                if obj is None:
                    obj = SimulatedCrmObject(
                        workspace_id=self.workspace_id,
                        object_type=object_type,
                        external_id=_fake_hubspot_id(object_type, r.id_value),
                        unique_key=r.id_value,
                        properties=dict(r.properties),
                        created_at=now,
                        updated_at=now,
                    )
                    self.db.add(obj)
                    existing[r.id_value] = obj
                    out.results.append(UpsertResult(r.internal_id, "created", obj.external_id))
                else:
                    obj.properties = {**obj.properties, **r.properties}
                    obj.updated_at = now
                    out.results.append(UpsertResult(r.internal_id, "updated", obj.external_id))
        self.db.flush()
        return out


# --------------------------------------------------------------------------------------------------
# Real adapter
# --------------------------------------------------------------------------------------------------


class RealHubSpotAdapter:
    provider = "hubspot"
    is_simulated = False
    BASE_URL = "https://api.hubapi.com"

    def __init__(
        self,
        token: str,
        client: httpx.Client | None = None,
        max_retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or httpx.Client(base_url=self.BASE_URL, timeout=30.0)
        self._headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self._max_retries = max_retries
        self._sleep = sleep

    def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        delay = 1.0
        for attempt in range(1, self._max_retries + 1):
            resp = self._client.post(path, json=payload, headers=self._headers)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self._max_retries:
                    return resp
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                log.warning("hubspot %s -> %s; retrying in %.1fs", path, resp.status_code, wait)
                self._sleep(wait)
                delay = min(delay * 2, 30)
                continue
            return resp
        raise AssertionError("unreachable")

    _properties_ensured = False

    def ensure_properties_once(self) -> None:
        if not RealHubSpotAdapter._properties_ensured:
            self.ensure_properties()
            RealHubSpotAdapter._properties_ensured = True

    def ensure_properties(self) -> list[str]:
        """Create GTMOS custom properties if missing. Returns names created. Requires schema scopes."""
        created: list[str] = []
        for obj, props in CUSTOM_PROPERTIES.items():
            for p in props:
                resp = self._post(f"/crm/v3/properties/{obj}", {**p, "groupName": PROPERTY_GROUPS[obj]})
                if resp.status_code in (200, 201):
                    created.append(f"{obj}.{p['name']}")
                elif resp.status_code != 409:  # 409 = already exists
                    log.warning("could not create %s.%s: %s", obj, p["name"], resp.text[:200])
        return created

    def upsert(self, object_type: str, records: list[UpsertRecord]) -> BatchOutcome:
        id_prop = ID_PROPERTY[object_type]
        out = BatchOutcome()
        for batch in chunks(records):
            payload = {
                "inputs": [
                    {"idProperty": id_prop, "id": r.id_value, "properties": {**r.properties, id_prop: r.id_value}}
                    for r in batch
                ]
            }
            resp = self._post(f"/crm/v3/objects/{object_type}/batch/upsert", payload)
            out.http_calls += 1
            if resp.status_code in (200, 207):
                body = resp.json()
                by_key = {
                    str((res.get("properties") or {}).get(id_prop, "")).lower(): res for res in body.get("results", [])
                }
                for r in batch:
                    res = by_key.get(r.id_value.lower())
                    if res:
                        out.results.append(
                            UpsertResult(r.internal_id, "created" if res.get("new") else "updated", str(res.get("id")))
                        )
                    else:
                        errs = "; ".join(e.get("message", "") for e in body.get("errors", []))[:500]
                        out.results.append(UpsertResult(r.internal_id, "failed", error=errs or "not in batch response"))
            else:
                retryable = resp.status_code == 429 or resp.status_code >= 500
                msg = f"HTTP {resp.status_code}: {resp.text[:300]}"
                out.results.extend(UpsertResult(r.internal_id, "failed", error=msg, retryable=retryable) for r in batch)
        return out


# --------------------------------------------------------------------------------------------------
# Mapping
# --------------------------------------------------------------------------------------------------


def company_properties(a: Any, computed: dict[str, Any]) -> dict[str, Any]:
    props = {
        "name": a.name,
        "domain": a.domain,
        "gtmos_industry": a.industry,
        "numberofemployees": a.employee_count,
        "city": a.city,
        "country": a.country,
        "lifecyclestage": a.lifecycle_stage,
        **computed,
    }
    return {k: v for k, v in props.items() if v is not None}


def contact_properties(c: Any, role: str | None) -> dict[str, Any]:
    props = {
        "email": (c.email or "").lower(),
        "firstname": c.first_name,
        "lastname": c.last_name,
        "jobtitle": c.title,
        "lifecyclestage": c.lifecycle_stage,
        "gtmos_contact_id": str(c.id),
        "gtmos_buying_role": role,
    }
    return {k: v for k, v in props.items() if v is not None}


def deal_properties(o: Any) -> dict[str, Any]:
    props = {
        "dealname": o.name,
        "amount": o.amount_usd,
        "dealstage": DEAL_STAGE_MAP.get(o.stage, o.stage),
        "pipeline": "default",
        "closedate": o.expected_close_date.isoformat() if o.expected_close_date else None,
    }
    return {k: v for k, v in props.items() if v is not None}
