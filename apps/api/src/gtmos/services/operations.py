"""Operational health: workflow runs, syncs, webhooks, providers, routing latency."""

from __future__ import annotations

import statistics
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gtmos.config import get_settings
from gtmos.models import (
    EnrichmentAttempt,
    EnrichmentRun,
    Integration,
    IntegrationSync,
    RoutingDecision,
    WebhookEvent,
    Workflow,
    WorkflowRun,
    WorkflowStepRun,
)
from gtmos.services.common import utcnow


def workflow_health(db: Session, ws: uuid.UUID, days: int = 7) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    counts = dict(
        db.execute(
            select(WorkflowRun.status, func.count())
            .where(WorkflowRun.workspace_id == ws, WorkflowRun.created_at >= since)
            .group_by(WorkflowRun.status)
        )
        .tuples()
        .all()
    )
    executed = sum(v for k, v in counts.items() if k != "skipped")
    failed = counts.get("failed", 0) + counts.get("dead_letter", 0)
    durations = [
        (f - s).total_seconds() * 1000
        for s, f in db.execute(
            select(WorkflowRun.started_at, WorkflowRun.finished_at).where(
                WorkflowRun.workspace_id == ws,
                WorkflowRun.created_at >= since,
                WorkflowRun.status == "succeeded",
                WorkflowRun.started_at.is_not(None),
                WorkflowRun.finished_at.is_not(None),
            )
        )
    ]
    retried_steps = (
        db.scalar(
            select(func.count())
            .select_from(WorkflowStepRun)
            .join(WorkflowRun, WorkflowRun.id == WorkflowStepRun.run_id)
            .where(WorkflowRun.workspace_id == ws, WorkflowRun.created_at >= since, WorkflowStepRun.attempts > 1)
        )
        or 0
    )
    attention = db.execute(
        select(
            WorkflowRun.id,
            Workflow.name,
            WorkflowRun.status,
            WorkflowRun.error,
            WorkflowRun.created_at,
            WorkflowRun.account_id,
            WorkflowRun.correlation_id,
            WorkflowRun.trigger_event,
        )
        .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
        .where(WorkflowRun.workspace_id == ws, WorkflowRun.status.in_(["failed", "dead_letter"]))
        .order_by(WorkflowRun.created_at.desc())
        .limit(20)
    ).all()
    return {
        "window_days": days,
        "by_status": counts,
        "executed": executed,
        "failure_rate": round(failed / executed, 4) if executed else 0.0,
        "median_duration_ms": round(statistics.median(durations)) if durations else None,
        "retried_steps": retried_steps,
        "dead_letter_total": db.scalar(
            select(func.count())
            .select_from(WorkflowRun)
            .where(WorkflowRun.workspace_id == ws, WorkflowRun.status == "dead_letter")
        ),
        "needs_attention": [
            {
                "run_id": str(r[0]),
                "workflow": r[1],
                "status": r[2],
                "error": r[3],
                "created_at": r[4],
                "account_id": str(r[5]) if r[5] else None,
                "correlation_id": r[6],
                "synthetic_history": bool((r[7] or {}).get("synthetic_history")),
            }
            for r in attention
        ],
    }


def _first_error(errors: Any) -> str | None:
    if not errors:
        return None
    first = errors[0]
    if isinstance(first, dict):
        value = first.get("error")
        return str(value) if value is not None else None
    return str(first)


def sync_health(db: Session, ws: uuid.UUID, days: int = 7) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    runs = list(
        db.scalars(
            select(IntegrationSync)
            .where(IntegrationSync.workspace_id == ws, IntegrationSync.started_at >= since)
            .order_by(IntegrationSync.started_at.desc())
        )
    )
    last_ok = db.scalar(
        select(func.max(IntegrationSync.finished_at)).where(
            IntegrationSync.workspace_id == ws, IntegrationSync.status.in_(["succeeded", "partial"])
        )
    )
    failed = [r for r in runs if r.status == "failed"]
    records = sum(r.records_changed for r in runs)
    rec_failed = sum(r.records_failed for r in runs)
    return {
        "window_days": days,
        "runs": len(runs),
        "failed_runs": len(failed),
        "partial_runs": sum(1 for r in runs if r.status == "partial"),
        "records_changed": records,
        "records_failed": rec_failed,
        "record_failure_rate": round(rec_failed / records, 4) if records else 0.0,
        "retries": sum(r.retries for r in runs),
        "last_success_at": last_ok,
        "hours_since_success": round((utcnow() - last_ok).total_seconds() / 3600, 1) if last_ok else None,
        "all_simulated": all(r.is_simulated for r in runs) if runs else True,
        "recent": [
            {
                "id": str(r.id),
                "job": r.job,
                "status": r.status,
                "started_at": r.started_at,
                "duration_ms": r.duration_ms,
                "changed": r.records_changed,
                "failed": r.records_failed,
                "skipped": r.records_skipped,
                "retries": r.retries,
                "is_simulated": r.is_simulated,
                "trigger": r.trigger,
                "correlation_id": r.correlation_id,
                # Defensive: a sync writing a bare string here used to take the whole Operations page
                # down with an AttributeError. An observability surface that dies on malformed input is
                # the opposite of observability.
                "error": _first_error(r.errors),
            }
            for r in runs[:15]
        ],
    }


def webhook_health(db: Session, ws: uuid.UUID, days: int = 7) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(
            WebhookEvent.source,
            WebhookEvent.status,
            func.count(),
            func.coalesce(func.sum(WebhookEvent.duplicate_count), 0),
        )
        .where(WebhookEvent.workspace_id == ws, WebhookEvent.received_at >= since)
        .group_by(WebhookEvent.source, WebhookEvent.status)
    ).all()
    by_source: dict[str, dict[str, int]] = {}
    dupes = 0
    for src, status, n, d in rows:
        by_source.setdefault(src, {})[status] = n
        dupes += int(d)
    total = sum(sum(v.values()) for v in by_source.values())
    bad = sum(v.get("failed", 0) + v.get("dead_letter", 0) for v in by_source.values())
    times = [
        r[0]
        for r in db.execute(
            select(WebhookEvent.processing_ms).where(
                WebhookEvent.workspace_id == ws,
                WebhookEvent.received_at >= since,
                WebhookEvent.processing_ms.is_not(None),
            )
        )
    ]
    last = dict(
        db.execute(
            select(WebhookEvent.source, func.max(WebhookEvent.received_at))
            .where(WebhookEvent.workspace_id == ws)
            .group_by(WebhookEvent.source)
        )
        .tuples()
        .all()
    )
    attention = list(
        db.scalars(
            select(WebhookEvent)
            .where(WebhookEvent.workspace_id == ws, WebhookEvent.status.in_(["failed", "dead_letter", "rejected"]))
            .order_by(WebhookEvent.received_at.desc())
            .limit(15)
        )
    )
    return {
        "window_days": days,
        "total": total,
        "by_source": by_source,
        "duplicates_absorbed": dupes,
        "failure_rate": round(bad / total, 4) if total else 0.0,
        "p50_processing_ms": round(statistics.median(times)) if times else None,
        "p95_processing_ms": round(statistics.quantiles(times, n=20)[18]) if len(times) >= 20 else None,
        "last_received": last,
        "needs_attention": [
            {
                "id": str(e.id),
                "source": e.source,
                "status": e.status,
                "error": e.error,
                "received_at": e.received_at,
                "attempts": e.attempts,
                "correlation_id": e.correlation_id,
                "synthetic_history": bool((e.payload or {}).get("synthetic_history")),
            }
            for e in attention
        ],
    }


def provider_health(db: Session, ws: uuid.UUID, days: int = 30) -> list[dict[str, Any]]:
    since = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(
            EnrichmentAttempt.provider,
            EnrichmentAttempt.outcome,
            func.count(),
            func.coalesce(func.sum(EnrichmentAttempt.cost_credits), 0),
            func.avg(func.nullif(EnrichmentAttempt.latency_ms, 0)),
        )
        .join(EnrichmentRun, EnrichmentRun.id == EnrichmentAttempt.run_id)
        .where(EnrichmentRun.workspace_id == ws, EnrichmentRun.started_at >= since)
        .group_by(EnrichmentAttempt.provider, EnrichmentAttempt.outcome)
    ).all()
    agg: dict[str, dict[str, Any]] = {}
    for prov, outcome, n, cost, lat in rows:
        a = agg.setdefault(
            prov,
            {
                "provider": prov,
                "attempts": 0,
                "hit": 0,
                "miss": 0,
                "low_confidence": 0,
                "error": 0,
                "skipped": 0,
                "cost_credits": 0.0,
                "latency": [],
            },
        )
        a["attempts"] += n
        a[outcome] = a.get(outcome, 0) + n
        a["cost_credits"] += float(cost)
        if lat:
            a["latency"].append(float(lat))
    names = dict(
        db.execute(select(Integration.provider, Integration.display_name).where(Integration.workspace_id == ws))
        .tuples()
        .all()
    )
    out = []
    for a in agg.values():
        tried = a["attempts"] - a.get("skipped", 0)
        lat = a.pop("latency")
        out.append(
            {
                **a,
                "name": names.get(a["provider"], a["provider"]),
                "hit_rate": round(a["hit"] / tried, 4) if tried else None,
                "error_rate": round(a["error"] / tried, 4) if tried else None,
                "avg_latency_ms": round(statistics.mean(lat)) if lat else None,
                "cost_credits": round(a["cost_credits"], 2),
                "status": "degraded" if tried and a["error"] / tried > 0.1 else "healthy",
            }
        )
    return sorted(out, key=lambda r: r["provider"])


def routing_latency(db: Session, ws: uuid.UUID, days: int = 90) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    lat = [
        r[0]
        for r in db.execute(
            select(RoutingDecision.latency_ms).where(
                RoutingDecision.workspace_id == ws,
                RoutingDecision.decided_at >= since,
                RoutingDecision.latency_ms.is_not(None),
                RoutingDecision.latency_ms >= 0,
            )
        )
    ]
    return {
        "decisions_with_signal": len(lat),
        "median_signal_to_owner_hours": round(statistics.median(lat) / 3_600_000, 1) if lat else None,
        "p90_signal_to_owner_hours": round(statistics.quantiles(lat, n=10)[8] / 3_600_000, 1)
        if len(lat) >= 10
        else None,
        "note": "Signal observed → owner assigned. In demo data the delay reflects simulated historical "
        "processing (batch routing), not live system latency.",
    }


def summary(db: Session, ws: uuid.UUID) -> dict[str, Any]:
    s = get_settings()
    return {
        "workflows": workflow_health(db, ws),
        "syncs": sync_health(db, ws),
        "webhooks": webhook_health(db, ws),
        "providers": provider_health(db, ws),
        "routing": routing_latency(db, ws),
        "queue": {"backend": s.queue_backend, "redis_configured": bool(s.redis_url)},
        "llm": {"mode": s.llm_mode, "model": s.llm_model if s.llm_mode == "live" else None},
    }
