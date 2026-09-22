"""Runs the enrichment waterfall for an account and persists attempts, provenance and changes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gtmos.config import get_settings
from gtmos.domain.enrichment import EnrichmentProvider, ExistingValue, run_waterfall
from gtmos.integrations.enrichment_providers import DEFAULT_WATERFALL, ENRICHABLE_FIELDS, build_providers
from gtmos.models import Account, EnrichmentAttempt, EnrichmentRun, FieldProvenance
from gtmos.seed.profiles import segment_for
from gtmos.services.common import audit, jsonable, utcnow


def provenance_for(db: Session, entity_id: uuid.UUID) -> dict[str, FieldProvenance]:
    rows = db.scalars(select(FieldProvenance).where(FieldProvenance.entity_id == entity_id))
    return {r.field: r for r in rows}


def enrich_account(
    db: Session,
    account: Account,
    *,
    fields: list[str] | None = None,
    trigger: str = "manual",
    providers: dict[str, EnrichmentProvider] | None = None,
    now: datetime | None = None,
) -> EnrichmentRun:
    now = now or utcnow()
    fields = fields or ENRICHABLE_FIELDS
    providers = providers if providers is not None else build_providers(get_settings())
    prov = provenance_for(db, account.id)
    existing: dict[str, ExistingValue] = {}
    for f in fields:
        val = getattr(account, f, None)
        if val in (None, "", []):
            continue
        p = prov.get(f)
        existing[f] = ExistingValue(
            val,
            p.confidence if p else 0.5,
            p.source if p else "unknown",
            p.observed_at if p else None,
            p.is_manual_lock if p else False,
        )

    started = utcnow()
    result = run_waterfall(account.domain or "", fields, DEFAULT_WATERFALL, providers, existing, now)
    run = EnrichmentRun(
        workspace_id=account.workspace_id,
        entity_type="account",
        entity_id=account.id,
        status=result.status,
        started_at=started,
        finished_at=utcnow(),
        fields_requested=fields,
        fields_filled=result.fields_filled,
        fields_changed=result.fields_changed,
        total_cost_credits=result.cost_credits,
        trigger=trigger,
        is_simulated=all(getattr(providers.get(p), "is_simulated", True) for p in result.providers_called),
    )
    if not account.domain:
        run.status = "failed"
    db.add(run)
    db.flush()
    db.add_all(
        EnrichmentAttempt(
            run_id=run.id,
            field=a.field,
            provider=a.provider,
            position=a.position,
            outcome=a.outcome,
            value=jsonable(a.value),
            confidence=a.confidence,
            latency_ms=a.latency_ms,
            cost_credits=a.cost_credits,
            error=a.error,
        )
        for a in result.attempts
    )

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for d in result.decisions:
        if d.action not in ("set", "update"):
            if d.action == "keep_existing" and d.field in prov and d.confidence:
                prov[d.field].confidence = max(prov[d.field].confidence, d.confidence)
            continue
        before[d.field] = jsonable(getattr(account, d.field, None))
        setattr(account, d.field, d.value)
        after[d.field] = jsonable(d.value)
        p = prov.get(d.field)
        if p is None:
            p = FieldProvenance(
                workspace_id=account.workspace_id, entity_type="account", entity_id=account.id, field=d.field
            )
            db.add(p)
        p.value = jsonable(d.value)
        p.source = d.provider or "unknown"
        p.confidence = d.confidence or 0.0
        p.observed_at = now
        p.enrichment_run_id = run.id
    if "employee_count" in after:
        account.segment = segment_for(account.employee_count)
    account.last_enriched_at = now
    if after:
        audit(
            db,
            account.workspace_id,
            "account.enriched",
            "account",
            account.id,
            before=before,
            after=after,
            reason=f"waterfall run {run.id} ({trigger}); cost {result.cost_credits} credits",
            actor_type="system",
        )
    db.flush()
    return run
