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
    AssociationRequest,
    CrmAdapter,
    DemoHubSpotAdapter,
    RealHubSpotAdapter,
    UpsertRecord,
    company_properties,
    contact_properties,
    deal_properties,
)
from gtmos.models import (
    Account,
    AccountContactRole,
    Contact,
    ExternalRecord,
    Integration,
    IntegrationSync,
    Opportunity,
    Signal,
)
from gtmos.services import governance
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
        prev = ext.get(a.id)
        # Field ownership: GTMOS owns gtmos_* properties. Name and domain are set only when the record is
        # created, so a rep's edits in the CRM are never overwritten by a later reverse-ETL push.
        owned = {k: v for k, v in computed.items() if v is not None}
        if full_record:
            props = company_properties(a, computed)
        elif prev is None:
            props = {k: v for k, v in {"domain": a.domain, "name": a.name, **owned}.items() if v is not None}
        else:
            props = owned
        h = payload_hash(owned) if not full_record else payload_hash(props)
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
    # Checked before the adapter is built, so a paused workspace never opens a connection, and the
    # caller gets an operator-readable reason rather than a mysteriously empty sync.
    governance.require(db, workspace_id, "crm_writes_enabled")
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
    ensure = getattr(adapter, "ensure_properties_once", None)
    if callable(ensure) and plan.changes:
        ensure()  # live adapter: create gtmos_* custom properties (incl. the unique id property) first
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


# --------------------------------------------------------------------------------------------------
# Contacts, deals and associations
# --------------------------------------------------------------------------------------------------
#
# Phase 2 shipped company sync only: contacts and deals were mapped but never scheduled, so the CRM
# side of the demo was a list of companies with nothing attached. A company record with no contacts and
# no deals is not a CRM — associations are what make it one, and they are also the part most
# integrations get wrong (see ASSOCIATION_TYPES in integrations/hubspot.py for the primary-vs-general
# trap).


def _external(db: Session, object_type: str, internal_ids: list[uuid.UUID]) -> dict[uuid.UUID, ExternalRecord]:
    if not internal_ids:
        return {}
    return {
        e.internal_id: e
        for e in db.scalars(
            select(ExternalRecord).where(
                ExternalRecord.provider == "hubspot",
                ExternalRecord.object_type == object_type,
                ExternalRecord.internal_id.in_(internal_ids),
            )
        )
    }


def _record_sync(
    db: Session,
    workspace_id: uuid.UUID,
    object_type: str,
    internal_id: uuid.UUID,
    external_id: str | None,
    props: dict[str, Any],
    is_simulated: bool,
    now: datetime,
) -> None:
    ext = _external(db, object_type, [internal_id]).get(internal_id)
    if ext is None:
        ext = ExternalRecord(
            workspace_id=workspace_id,
            provider="hubspot",
            object_type=object_type,
            internal_id=internal_id,
            is_simulated=is_simulated,
        )
        db.add(ext)
    ext.external_id = external_id or ext.external_id
    ext.last_payload = props
    ext.last_payload_hash = payload_hash(props)
    ext.last_synced_at = now
    ext.is_simulated = is_simulated


def run_contact_and_deal_sync(
    db: Session,
    workspace_id: uuid.UUID,
    account_ids: list[uuid.UUID] | None = None,
    *,
    job: str = "reverse_etl_contacts_deals",
    trigger: str = "manual",
    adapter: CrmAdapter | None = None,
    limit_accounts: int = 200,
) -> IntegrationSync:
    """Push contacts and opportunities for accounts that already exist in the CRM, then associate them.

    Ordering is the whole design. An association can only be created between two records that already
    exist, so this runs strictly after the company sync and skips any account with no company record
    rather than creating one implicitly — a contact that quietly conjures a company is how duplicate
    companies get into a CRM.
    """
    governance.require(db, workspace_id, "crm_writes_enabled")
    adapter = adapter or get_adapter(db, workspace_id)
    started = utcnow()
    t0 = time.perf_counter()

    q = select(Account).where(
        Account.workspace_id == workspace_id,
        Account.merged_into_id.is_(None),
        Account.domain.is_not(None),
    )
    if account_ids is not None:
        q = q.where(Account.id.in_(account_ids))
    else:
        q = q.where(Account.score_grade.in_(["A", "B"]))
    accounts = list(db.scalars(q.limit(limit_accounts)))
    company_ext = _external(db, "companies", [a.id for a in accounts])
    # Only accounts whose company is already in the CRM can carry associations.
    syncable = [a for a in accounts if a.id in company_ext and company_ext[a.id].external_id]

    contacts = (
        list(
            db.scalars(
                select(Contact).where(
                    Contact.account_id.in_([a.id for a in syncable]),
                    Contact.merged_into_id.is_(None),
                    Contact.email.is_not(None),
                )
            )
        )
        if syncable
        else []
    )
    opps = (
        list(db.scalars(select(Opportunity).where(Opportunity.account_id.in_([a.id for a in syncable]))))
        if syncable
        else []
    )
    roles = (
        {
            r.contact_id: r.role
            for r in db.scalars(
                select(AccountContactRole).where(AccountContactRole.contact_id.in_([c.id for c in contacts]))
            )
        }
        if contacts
        else {}
    )

    sync = IntegrationSync(
        workspace_id=workspace_id,
        provider=adapter.provider,
        job=job,
        direction="outbound",
        object_type="contacts_deals",
        status="running",
        is_simulated=adapter.is_simulated,
        records_considered=len(contacts) + len(opps),
        records_changed=0,
        records_skipped=0,
        correlation_id=correlation_id(),
        started_at=started,
        trigger=trigger,
    )
    db.add(sync)
    db.flush()

    now = utcnow()
    errors: list[str] = []
    succeeded = failed = associations_made = 0

    def _upsert_with_retry(object_type: str, records: list[UpsertRecord]) -> tuple[dict[uuid.UUID, str], int, int, int]:
        """Upsert records, retrying only the ones that failed *retryably*.

        Bounded at MAX_RETRY_ROUNDS, matching the company sync. A permanent failure — a 400 on a bad
        property — is never retried, because retrying it only burns rate limit and delays the report.
        """
        outstanding = {r.internal_id: r for r in records}
        external: dict[uuid.UUID, str] = {}
        ok = bad = retried = 0
        problems: list[str] = []
        for round_no in range(1, MAX_RETRY_ROUNDS + 1):
            if not outstanding:
                break
            if round_no > 1:
                retried += len(outstanding)
            outcome = adapter.upsert(object_type, list(outstanding.values()))
            still: dict[uuid.UUID, UpsertRecord] = {}
            for res in outcome.results:
                if res.status != "failed":
                    ok += 1
                    if res.external_id:
                        external[res.internal_id] = res.external_id
                    continue
                if res.retryable and round_no < MAX_RETRY_ROUNDS:
                    still[res.internal_id] = outstanding[res.internal_id]
                    continue
                bad += 1
                if res.error:
                    problems.append(f"{object_type[:-1]} {res.internal_id}: {res.error}")
            outstanding = still
        errors.extend(problems[:25])
        by_id = {r.internal_id: r for r in records}
        for internal_id, external_id in external.items():
            _record_sync(
                db,
                workspace_id,
                object_type,
                internal_id,
                external_id,
                by_id[internal_id].properties,
                adapter.is_simulated,
                now,
            )
        return external, ok, bad, retried

    contact_records = [
        UpsertRecord(c.id, (c.email or "").lower(), contact_properties(c, roles.get(c.id))) for c in contacts
    ]
    contact_external, c_ok, c_bad, c_retried = _upsert_with_retry("contacts", contact_records)
    succeeded += c_ok
    failed += c_bad

    deal_records = [UpsertRecord(o.id, str(o.id), deal_properties(o)) for o in opps]
    deal_external, d_ok, d_bad, d_retried = _upsert_with_retry("deals", deal_records)
    succeeded += d_ok
    failed += d_bad
    sync.retries = c_retried + d_retried

    associate = getattr(adapter, "associate", None)
    if callable(associate):
        contact_pairs = [
            AssociationRequest(from_id=contact_external[c.id], to_id=company_ext[c.account_id].external_id or "")
            for c in contacts
            if c.id in contact_external and c.account_id in company_ext
        ]
        deal_pairs = [
            AssociationRequest(from_id=deal_external[o.id], to_id=company_ext[o.account_id].external_id or "")
            for o in opps
            if o.id in deal_external and o.account_id in company_ext
        ]
        for from_type, pairs in (("contacts", contact_pairs), ("deals", deal_pairs)):
            if not pairs:
                continue
            res = associate(from_type, "companies", pairs)
            for r in res.results:
                if r.status == "failed":
                    failed += 1
                    if r.error:
                        errors.append(f"associate {from_type}: {r.error}")
                else:
                    associations_made += 1

    sync.records_succeeded = succeeded
    sync.records_failed = failed
    sync.records_changed = succeeded
    sync.errors = errors[:50]
    sync.status = "succeeded" if not failed else ("partial" if succeeded else "failed")
    sync.finished_at = utcnow()
    sync.duration_ms = int((time.perf_counter() - t0) * 1000)
    sync.details = {
        "contacts": len(contact_records),
        "deals": len(deal_records),
        "associations": associations_made,
        "accounts_skipped_no_company": len(accounts) - len(syncable),
    }
    audit(
        db,
        workspace_id,
        "integration.synced",
        "integration_sync",
        sync.id,
        after={"job": job, "status": sync.status, "associations": associations_made},
        actor_type="system",
        actor="crm_sync",
    )
    db.flush()
    return sync
