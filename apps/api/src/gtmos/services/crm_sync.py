"""CRM sync and reverse ETL.

Reverse ETL here means: GTMOS is the system that *computes* account intelligence (score, intent, tier,
last signal, next best action). The CRM is where reps *work*. The job:
  1. builds the desired CRM properties for each account (the "model"),
  2. hashes the payload and skips records whose hash matches what we last pushed (change detection),
  3. upserts changed records in batches of ≤100 on a stable unique key (idempotent),
  4. retries transient failures with backoff, and records per-run counts and errors (sync log).
That is the same contract Hightouch/Census implement on top of a warehouse model.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gtmos.config import get_settings
from gtmos.integrations.hubspot import (
    CrmAdapter,
    DemoHubSpotAdapter,
    RealHubSpotAdapter,
    UpsertRecord,
    company_properties,
)
from gtmos.models import Account, ExternalRecord, Integration, IntegrationSync, Signal
from gtmos.services.common import audit, correlation_id, jsonable, utcnow
from gtmos.services.next_action import next_best_action, next_best_actions

MAX_RETRY_ROUNDS = 3
SEGMENT_TIER = {
    "strategic": "Tier 1: Strategic",
    "enterprise": "Tier 2: Enterprise",
    "mid_market": "Tier 3: Mid-Market",
    "smb": "Tier 4: SMB",
}


def get_adapter(db: Session, workspace_id: uuid.UUID) -> CrmAdapter:
    s = get_settings()
    if s.hubspot_access_token and s.hubspot_live_writes_enabled:
        return RealHubSpotAdapter(s.hubspot_access_token.get_secret_value())
    return DemoHubSpotAdapter(db, workspace_id)


def last_signals(db: Session, account_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, datetime]]:
    out: dict[uuid.UUID, tuple[str, datetime]] = {}
    for i in range(0, len(account_ids), 1000):
        rows = db.execute(
            select(Signal.account_id, Signal.title, Signal.observed_at)
            .where(Signal.account_id.in_(account_ids[i : i + 1000]))
            .distinct(Signal.account_id)
            .order_by(Signal.account_id, Signal.observed_at.desc())
        ).all()
        out.update({r[0]: (r[1], r[2]) for r in rows})
    return out


def _computed(a: Account, last: tuple[str, datetime] | None, nba_label: str) -> dict[str, Any]:
    return {
        "gtmos_account_id": str(a.id),
        "gtmos_icp_score": a.icp_score,
        "gtmos_intent_score": a.intent_score,
        "gtmos_score_grade": a.score_grade,
        "gtmos_account_tier": SEGMENT_TIER.get(a.segment or "", "Unknown"),
        "gtmos_last_signal": last[0] if last else None,
        "gtmos_last_signal_at": last[1].isoformat() if last else None,
        "gtmos_next_best_action": nba_label,
    }


def computed_properties(db: Session, a: Account, now: datetime | None = None) -> dict[str, Any]:
    return _computed(a, last_signals(db, [a.id]).get(a.id), next_best_action(db, a, now).label)


def payload_hash(props: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(props, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class PlannedChange:
    account: Account
    properties: dict[str, Any]
    hash: str
    changed_fields: list[str]
    is_new: bool


@dataclass
class SyncPlan:
    changes: list[PlannedChange] = field(default_factory=list)
    unchanged: int = 0

    @property
    def considered(self) -> int:
        return len(self.changes) + self.unchanged


def plan_company_sync(db: Session, workspace_id: uuid.UUID, accounts: list[Account], full_record: bool) -> SyncPlan:
    ext = {
        e.internal_id: e
        for e in db.scalars(
            select(ExternalRecord).where(
                ExternalRecord.provider == "hubspot",
                ExternalRecord.object_type == "companies",
                ExternalRecord.internal_id.in_([a.id for a in accounts]),
            )
        )
    }
    plan = SyncPlan()
    lasts = last_signals(db, [a.id for a in accounts])
    actions = next_best_actions(db, accounts)
    for a in accounts:
        computed = _computed(a, lasts.get(a.id), actions[a.id].label)
        props = (
            company_properties(a, computed)
            if full_record
            else {k: v for k, v in {"domain": a.domain, "name": a.name, **computed}.items() if v is not None}
        )
        h = payload_hash(props)
        prev = ext.get(a.id)
        if prev and prev.last_payload_hash == h:
            plan.unchanged += 1
            continue
        old = prev.last_payload if prev else {}
        changed = sorted(k for k in props if old.get(k) != props[k])
        plan.changes.append(PlannedChange(a, props, h, changed, prev is None))
    return plan


def run_company_sync(
    db: Session,
    workspace_id: uuid.UUID,
    account_ids: list[uuid.UUID] | None = None,
    *,
    job: str = "reverse_etl_companies",
    trigger: str = "manual",
    full_record: bool = False,
    adapter: CrmAdapter | None = None,
    sleep: Any = None,
) -> IntegrationSync:
    adapter = adapter or get_adapter(db, workspace_id)
    started = utcnow()
    t0 = time.perf_counter()
    q = select(Account).where(
        Account.workspace_id == workspace_id, Account.merged_into_id.is_(None), Account.domain.is_not(None)
    )
    if account_ids is not None:
        q = q.where(Account.id.in_(account_ids))
    else:
        q = q.where(Account.score_grade.in_(["A", "B", "C"]))  # only sync accounts reps should see
    accounts = list(db.scalars(q))
    plan = plan_company_sync(db, workspace_id, accounts, full_record)
    sync = IntegrationSync(
        workspace_id=workspace_id,
        provider=adapter.provider,
        job=job,
        direction="outbound",
        object_type="companies",
        status="running",
        is_simulated=adapter.is_simulated,
        records_considered=plan.considered,
        records_changed=len(plan.changes),
        records_skipped=plan.unchanged,
        correlation_id=correlation_id(),
        started_at=started,
        trigger=trigger,
    )
    db.add(sync)
    db.flush()

    pending = {c.account.id: c for c in plan.changes}
    ext_map = (
        {
            e.internal_id: e
            for e in db.scalars(
                select(ExternalRecord).where(
                    ExternalRecord.provider == "hubspot",
                    ExternalRecord.object_type == "companies",
                    ExternalRecord.internal_id.in_(list(pending)),
                )
            )
        }
        if pending
        else {}
    )
    errors: list[dict[str, Any]] = []
    rounds = 0
    succeeded = 0
    while pending and rounds < MAX_RETRY_ROUNDS:
        rounds += 1
        if rounds > 1:
            sync.retries += len(pending)
            if sleep:
                sleep(min(2 ** (rounds - 1), 8))
        records = [UpsertRecord(c.account.id, str(c.account.id), c.properties) for c in pending.values()]
        outcome = adapter.upsert("companies", records)
        for r in outcome.results:
            change = pending[r.internal_id]
            if r.status in ("created", "updated"):
                ext = ext_map.get(r.internal_id)
                if ext is None:
                    ext = ExternalRecord(
                        workspace_id=workspace_id,
                        provider="hubspot",
                        object_type="companies",
                        internal_id=r.internal_id,
                    )
                    db.add(ext)
                    ext_map[r.internal_id] = ext
                ext.external_id = r.external_id
                ext.last_payload_hash = change.hash
                ext.last_payload = jsonable(change.properties)
                ext.last_synced_at = utcnow()
                ext.is_simulated = adapter.is_simulated
                if not adapter.is_simulated:
                    change.account.hubspot_company_id = r.external_id
                succeeded += 1
                del pending[r.internal_id]
            elif not r.retryable:
                errors.append({"account_id": str(r.internal_id), "error": r.error, "retryable": False})
                del pending[r.internal_id]
            elif rounds == MAX_RETRY_ROUNDS:
                errors.append(
                    {
                        "account_id": str(r.internal_id),
                        "error": r.error,
                        "retryable": True,
                        "note": f"gave up after {rounds} attempts",
                    }
                )
        db.flush()

    sync.records_succeeded = succeeded
    sync.records_failed = len(errors)
    sync.errors = errors[:50]
    sync.status = "succeeded" if not errors else ("partial" if succeeded else "failed")
    sync.finished_at = utcnow()
    sync.duration_ms = int((time.perf_counter() - t0) * 1000)
    integ = db.scalars(
        select(Integration).where(Integration.workspace_id == workspace_id, Integration.provider == "hubspot")
    ).first()
    if integ:
        if sync.status != "failed":
            integ.last_success_at = sync.finished_at
        if errors:
            integ.last_error_at = sync.finished_at
            integ.last_error = str(errors[0].get("error"))
        integ.status = "healthy" if sync.status == "succeeded" else "degraded"
    audit(
        db,
        workspace_id,
        "integration.synced",
        "integration_sync",
        sync.id,
        after={
            "job": job,
            "status": sync.status,
            "changed": sync.records_changed,
            "succeeded": succeeded,
            "failed": len(errors),
            "simulated": adapter.is_simulated,
        },
        reason=f"trigger={trigger}",
        actor_type="integration",
        actor="hubspot_adapter",
    )
    db.flush()
    return sync


def preview_reverse_etl(db: Session, workspace_id: uuid.UUID, limit: int = 50) -> dict[str, Any]:
    accounts = list(
        db.scalars(
            select(Account).where(
                Account.workspace_id == workspace_id,
                Account.merged_into_id.is_(None),
                Account.domain.is_not(None),
                Account.score_grade.in_(["A", "B", "C"]),
            )
        )
    )
    plan = plan_company_sync(db, workspace_id, accounts, full_record=False)
    last = db.scalars(
        select(IntegrationSync)
        .where(IntegrationSync.workspace_id == workspace_id, IntegrationSync.job == "reverse_etl_companies")
        .order_by(IntegrationSync.started_at.desc())
    ).first()
    field_counts: dict[str, int] = {}
    for c in plan.changes:
        for f in c.changed_fields:
            field_counts[f] = field_counts.get(f, 0) + 1
    return {
        "considered": plan.considered,
        "would_create": sum(1 for c in plan.changes if c.is_new),
        "would_update": sum(1 for c in plan.changes if not c.is_new),
        "unchanged": plan.unchanged,
        "changed_field_counts": dict(sorted(field_counts.items(), key=lambda kv: -kv[1])),
        "sample": [
            {
                "account_id": str(c.account.id),
                "name": c.account.name,
                "is_new": c.is_new,
                "changed_fields": c.changed_fields,
                "properties": c.properties,
            }
            for c in plan.changes[:limit]
        ],
        "last_run": {
            "id": str(last.id),
            "status": last.status,
            "finished_at": last.finished_at,
            "is_simulated": last.is_simulated,
        }
        if last
        else None,
        "destination_mode": "simulated"
        if not (get_settings().hubspot_access_token and get_settings().hubspot_live_writes_enabled)
        else "live",
    }


def simulated_crm_counts(db: Session, workspace_id: uuid.UUID) -> dict[str, int]:
    from gtmos.models import SimulatedCrmObject

    return dict(
        db.execute(
            select(SimulatedCrmObject.object_type, func.count())
            .where(SimulatedCrmObject.workspace_id == workspace_id)
            .group_by(SimulatedCrmObject.object_type)
        )
        .tuples()
        .all()
    )
