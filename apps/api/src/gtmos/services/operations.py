"""Operational health: workflow runs, syncs, webhooks, providers, routing latency."""

from __future__ import annotations

import statistics
import uuid
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from gtmos.config import Settings, get_settings
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


# Integration status ----------------------------------------------------------------------------------
#
# Four green "Connected" badges would be a lie. GTMOS talks to four tools at four genuinely different
# levels of proof, and the difference between "this ran" and "this compiles" is the whole point of this
# view. Two orthogonal axes are reported for every boundary:
#
#   mode          — what the running configuration does *right now*
#   verification  — how much of it has ever actually happened, and against what
#
# Both are derived from rows that exist (integrations, integration_syncs, webhook_events,
# enrichment_runs) plus which environment variables are set. Nothing here is asserted by hand, and no
# secret value is read — only whether one is present.

MODES: dict[str, str] = {
    "not_configured": "No credentials and no traffic. The boundary exists in code only.",
    "demo": "Running against GTMOS's simulated adapter. No external system is called.",
    "test": "GTMOS's side of the boundary has been exercised with locally generated traffic. "
    "No account with the real service exists.",
    "live": "Connected to a real running instance of the tool.",
}

VERIFICATION_LEVELS: dict[str, str] = {
    "unverified": "Implemented against the documented contract and never run.",
    "simulated": "Verified through the simulated adapter only. The live adapter has never run against "
    "the real service.",
    "verified_locally": "Verified by local execution against GTMOS's own endpoint using the documented "
    "payload shape. Nothing has ever been received from the real service.",
    "verified_by_execution": "Verified by execution against a real running instance of the tool.",
}

_FAILED_EVENT_STATUSES = ("failed", "dead_letter", "rejected")
_FAILED_SYNC_STATUSES = ("failed",)
_OK_SYNC_STATUSES = ("succeeded", "partial")


class Boundary(NamedTuple):
    """One integration boundary and the tables that carry evidence about it."""

    provider: str
    display_name: str
    category: str
    direction: str
    summary: str
    moves: tuple[str, ...]
    webhook_source: str | None
    sync_provider: str | None
    enrichment_prefixes: tuple[str, ...]
    endpoints: tuple[str, ...]
    docs: tuple[tuple[str, str], ...]


# Ordered as the data flows in docs/phase3-architecture.md: observe → enrich → orchestrate → operate.
BOUNDARIES: tuple[Boundary, ...] = (
    Boundary(
        provider="posthog",
        display_name="PostHog",
        category="product_analytics",
        direction="inbound",
        summary="Observes the product. GTMOS turns its events into account-level signals and the "
        "product-qualified rule.",
        moves=(
            "PostHog → GTMOS: product events carrying $groups.company, over a destination webhook",
            "GTMOS → PostHog: nothing. GTMOS never writes back.",
        ),
        webhook_source="posthog",
        sync_provider=None,
        enrichment_prefixes=(),
        endpoints=("POST /api/v1/webhooks/posthog", "POST /api/v1/events"),
        docs=(("Research: PostHog", "docs/research/posthog.md"), ("Integrations", "docs/integrations.md")),
    ),
    Boundary(
        provider="clay",
        display_name="Clay",
        category="enrichment",
        direction="inbound",
        summary="Buys commodity enrichment. GTMOS keeps the merge policy: a Clay value enters through "
        "the same provenance and conflict rules as any other provider.",
        moves=(
            "Clay → GTMOS: enriched account and contact rows with per-cell provider, confidence and "
            "observed_at, signed with X-Clay-Signature",
            "GTMOS → Clay: read-only Public API calls (/me, credits). Clay's API cannot write table rows.",
        ),
        webhook_source="clay",
        sync_provider="clay",
        enrichment_prefixes=("clay",),
        endpoints=("POST /api/v1/webhooks/clay", "GET /api/v1/integrations/clay/contract"),
        docs=(("Live setup + honest status", "docs/clay-live-setup.md"), ("Research: Clay", "docs/research/clay.md")),
    ),
    Boundary(
        provider="n8n",
        display_name="n8n",
        category="workflow_automation",
        direction="bidirectional",
        summary="Moves bytes between systems. Anything that decides revenue stays in GTMOS; anything "
        "that is plumbing lives on the n8n canvas.",
        moves=(
            "n8n → GTMOS: normalised signals and relayed product events, HMAC-signed",
            "GTMOS → n8n: nothing pushed. n8n pulls the reverse-ETL diff on a schedule and calls back.",
        ),
        webhook_source="n8n",
        sync_provider=None,
        enrichment_prefixes=(),
        endpoints=("POST /api/v1/webhooks/n8n",),
        docs=(("n8n templates", "docs/n8n.md"), ("Research: n8n", "docs/research/n8n.md")),
    ),
    Boundary(
        provider="hubspot",
        display_name="HubSpot",
        category="crm",
        direction="bidirectional",
        summary="Where the revenue team works. GTMOS writes only its own gtmos_* fields and never "
        "applies an inbound CRM change as truth.",
        moves=(
            "GTMOS → HubSpot: gtmos_* computed properties on companies, contacts and deals, batch-upserted "
            "on a unique key",
            "HubSpot → GTMOS: property-change webhooks. Logged and acknowledged, never auto-applied.",
        ),
        webhook_source="hubspot",
        sync_provider="hubspot",
        enrichment_prefixes=(),
        endpoints=(
            "POST /api/v1/webhooks/hubspot",
            "POST /api/v1/integrations/hubspot/reverse-etl/run",
            "GET /api/v1/integrations/hubspot/mapping",
        ),
        docs=(("Research: HubSpot", "docs/research/hubspot.md"), ("Integrations", "docs/integrations.md")),
    ),
)

BOUNDARIES_BY_PROVIDER: dict[str, Boundary] = {b.provider: b for b in BOUNDARIES}


def _percentiles(values: list[int]) -> tuple[int | None, int | None]:
    if not values:
        return None, None
    p95 = round(statistics.quantiles(values, n=20)[18]) if len(values) >= 20 else None
    return round(statistics.median(values)), p95


def _real_event() -> Any:
    """Deliveries the engine really received, as opposed to the seeded illustrative history."""
    return WebhookEvent.payload["synthetic_history"].as_string().is_(None)


def _webhook_facts(db: Session, ws: uuid.UUID, source: str, since: datetime) -> dict[str, Any]:
    base = [WebhookEvent.workspace_id == ws, WebhookEvent.source == source]
    win = [*base, WebhookEvent.received_at >= since]
    by_status: dict[str, int] = dict(
        db.execute(select(WebhookEvent.status, func.count()).where(*win).group_by(WebhookEvent.status)).tuples().all()
    )
    by_signature: dict[str, int] = dict(
        db.execute(
            select(WebhookEvent.signature_status, func.count()).where(*win).group_by(WebhookEvent.signature_status)
        )
        .tuples()
        .all()
    )
    latencies = [
        int(r[0])
        for r in db.execute(select(WebhookEvent.processing_ms).where(*win, WebhookEvent.processing_ms.is_not(None)))
    ]
    p50, p95 = _percentiles(latencies)
    failure = db.execute(
        select(WebhookEvent.received_at, WebhookEvent.status, WebhookEvent.error)
        .where(*base, WebhookEvent.status.in_(_FAILED_EVENT_STATUSES))
        .order_by(WebhookEvent.received_at.desc())
        .limit(1)
    ).first()
    total = db.scalar(select(func.count()).select_from(WebhookEvent).where(*base)) or 0
    real = db.scalar(select(func.count()).select_from(WebhookEvent).where(*base, _real_event())) or 0
    return {
        "window_total": sum(by_status.values()),
        "window_processed": by_status.get("processed", 0),
        "window_failed": sum(by_status.get(s, 0) for s in _FAILED_EVENT_STATUSES),
        "by_status": by_status,
        "by_signature": by_signature,
        "duplicates_absorbed": int(
            db.scalar(select(func.coalesce(func.sum(WebhookEvent.duplicate_count), 0)).where(*win)) or 0
        ),
        "retries": int(db.scalar(select(func.coalesce(func.sum(WebhookEvent.attempts - 1), 0)).where(*win)) or 0),
        "p50_processing_ms": p50,
        "p95_processing_ms": p95,
        "last_received_at": db.scalar(select(func.max(WebhookEvent.received_at)).where(*base)),
        "last_processed_at": db.scalar(
            select(func.max(WebhookEvent.received_at)).where(*base, WebhookEvent.status == "processed")
        ),
        "last_failure_at": failure[0] if failure else None,
        "last_failure": (f"{failure[1]}: {failure[2]}" if failure[2] else str(failure[1])) if failure else None,
        "lifetime_total": total,
        "lifetime_real": real,
        "lifetime_synthetic": total - real,
    }


def _sync_facts(db: Session, ws: uuid.UUID, provider: str, since: datetime) -> dict[str, Any]:
    base = [IntegrationSync.workspace_id == ws, IntegrationSync.provider == provider]
    win = [*base, IntegrationSync.started_at >= since]
    runs = list(db.scalars(select(IntegrationSync).where(*win)))
    durations = [r.duration_ms for r in runs if r.duration_ms is not None]
    p50, p95 = _percentiles(durations)
    failure = db.execute(
        select(IntegrationSync.started_at, IntegrationSync.errors)
        .where(*base, IntegrationSync.status.in_(_FAILED_SYNC_STATUSES))
        .order_by(IntegrationSync.started_at.desc())
        .limit(1)
    ).first()
    return {
        "window_runs": len(runs),
        "window_ok": sum(1 for r in runs if r.status in _OK_SYNC_STATUSES),
        "window_failed": sum(1 for r in runs if r.status in _FAILED_SYNC_STATUSES),
        "window_partial": sum(1 for r in runs if r.status == "partial"),
        "records_changed": sum(r.records_changed for r in runs),
        "records_failed": sum(r.records_failed for r in runs),
        "retries": sum(r.retries for r in runs),
        "p50_duration_ms": p50,
        "p95_duration_ms": p95,
        "last_success_at": db.scalar(
            select(func.max(IntegrationSync.finished_at)).where(*base, IntegrationSync.status.in_(_OK_SYNC_STATUSES))
        ),
        "last_failure_at": failure[0] if failure else None,
        "last_failure": _first_error(failure[1]) if failure else None,
        # A single non-simulated run is the only honest evidence that the live adapter ever spoke to a
        # real portal. There are none, and the UI must not claim otherwise.
        "live_runs": db.scalar(
            select(func.count()).select_from(IntegrationSync).where(*base, IntegrationSync.is_simulated.is_(False))
        )
        or 0,
    }


def _enrichment_facts(db: Session, ws: uuid.UUID, prefixes: tuple[str, ...], since: datetime) -> dict[str, Any]:
    if not prefixes:
        return {"attempts": 0, "hits": 0, "errors": 0, "avg_latency_ms": None, "runs": 0, "fields_filled": 0}
    match = [EnrichmentAttempt.provider.like(f"{p}%") for p in prefixes]
    rows = db.execute(
        select(EnrichmentAttempt.outcome, func.count(), func.avg(func.nullif(EnrichmentAttempt.latency_ms, 0)))
        .join(EnrichmentRun, EnrichmentRun.id == EnrichmentAttempt.run_id)
        .where(EnrichmentRun.workspace_id == ws, EnrichmentRun.started_at >= since, or_(*match))
        .group_by(EnrichmentAttempt.outcome)
    ).all()
    latencies = [float(lat) for _, _, lat in rows if lat]
    run_rows = list(
        db.scalars(
            select(EnrichmentRun)
            .join(EnrichmentAttempt, EnrichmentAttempt.run_id == EnrichmentRun.id)
            .where(EnrichmentRun.workspace_id == ws, EnrichmentRun.started_at >= since, or_(*match))
            .distinct()
        )
    )
    return {
        "attempts": sum(int(n) for _, n, _ in rows),
        "hits": sum(int(n) for outcome, n, _ in rows if outcome == "hit"),
        "errors": sum(int(n) for outcome, n, _ in rows if outcome == "error"),
        "avg_latency_ms": round(statistics.mean(latencies)) if latencies else None,
        "runs": len(run_rows),
        "fields_filled": sum(len(r.fields_filled) for r in run_rows),
    }


def _requirement(key: str, kind: str, configured: bool, purpose: str) -> dict[str, Any]:
    """Only ever reports *whether* a secret is present. The value is never read or returned."""
    return {"key": key, "kind": kind, "configured": configured, "purpose": purpose}


def _resolve_posture(provider: str, s: Settings, wh: dict[str, Any], sync: dict[str, Any]) -> dict[str, Any]:
    """Mode, verification level and what is still missing, per boundary."""
    exercised = wh["lifetime_real"] > 0
    seen_anything = wh["lifetime_total"] > 0

    def local_mode(account_configured: bool) -> str:
        if account_configured and exercised:
            return "live"
        if exercised:
            return "test"
        return "demo" if seen_anything else "not_configured"

    if provider == "hubspot":
        token, flag = bool(s.hubspot_access_token), s.hubspot_live_writes_enabled
        reached = sync["live_runs"] > 0
        live = token and flag
        reqs = [
            _requirement(
                "HUBSPOT_ACCESS_TOKEN",
                "env",
                token,
                "Private-app token with crm.objects.companies/contacts/deals write scopes.",
            ),
            _requirement(
                "HUBSPOT_LIVE_WRITES_ENABLED",
                "env",
                flag,
                "Second switch. A token on its own never writes to a portal.",
            ),
            _requirement(
                "HUBSPOT_WEBHOOK_CLIENT_SECRET",
                "env",
                bool(s.hubspot_webhook_client_secret),
                "Verifies the signature on inbound property-change events.",
            ),
            _requirement(
                "A HubSpot portal (developer test or production)", "account", token, "Nothing to write to without one."
            ),
        ]
        return {
            "mode": "live" if live else "demo",
            "verification": "verified_by_execution" if reached else ("unverified" if live else "simulated"),
            "reached_real_service": reached,
            "requirements": reqs,
            "blocking": [] if reached else [r["key"] for r in reqs if not r["configured"]],
            "note": "The simulated adapter is exercised end to end and every sync it performs is labelled "
            "SIMULATED. The live adapter is implemented against the documented v3 batch-upsert API and "
            "has never run against a real portal.",
        }

    if provider == "n8n":
        secret = bool(s.webhook_secret)
        reqs = [
            _requirement("WEBHOOK_SECRET", "env", secret, "HMAC key the n8n templates sign their payloads with."),
            _requirement(
                "A running n8n instance posting to /api/v1/webhooks/n8n",
                "service",
                exercised,
                "Proven by deliveries this API actually received and processed.",
            ),
        ]
        return {
            "mode": "live" if (secret and exercised) else local_mode(False),
            "verification": "verified_by_execution" if exercised else "unverified",
            "reached_real_service": exercised,
            "requirements": reqs,
            "blocking": [r["key"] for r in reqs if not r["configured"]],
            "note": "n8n runs locally in Docker on the pinned image n8nio/n8n:2.40.5. Its workflows fire "
            "against this API for real, and the deliveries below are those executions.",
        }

    if provider == "posthog":
        # Derived, not asserted: there is no posthog_* setting on Settings at all, so this deployment has
        # no way to be pointed at a PostHog project. If one is ever added, this flips on its own.
        account = any(f.startswith("posthog") for f in Settings.model_fields)
        reqs = [
            _requirement(
                "WEBHOOK_SECRET", "env", bool(s.webhook_secret), "Shared token / HMAC on inbound product events."
            ),
            _requirement(
                "A PostHog project with group analytics and a webhook destination",
                "account",
                account,
                "Group analytics and the outbound HTTP destination are paid add-ons. No PostHog account "
                "exists for this project.",
            ),
        ]
        return {
            "mode": local_mode(account),
            "verification": "verified_locally" if exercised else "unverified",
            "reached_real_service": account and exercised,
            "requirements": reqs,
            "blocking": [r["key"] for r in reqs if not r["configured"]],
            "note": "The inbound path is real code and is exercised: events in PostHog's documented shape "
            "are accepted, deduplicated, normalised and turned into signals. Not one of them came from "
            "PostHog itself.",
        }

    # clay
    account = bool(s.clay_webhook_secret or s.clay_api_key)
    reqs = [
        _requirement(
            "CLAY_WEBHOOK_SECRET",
            "env",
            bool(s.clay_webhook_secret),
            "Clay's signingSecret, shown once when the webhook is registered. Without it inbound rows are "
            "accepted unsigned.",
        ),
        _requirement("CLAY_API_KEY", "env", bool(s.clay_api_key), "Workspace key for the read-only Public API."),
        _requirement(
            "A Clay workspace on the Growth plan",
            "account",
            account,
            "The in-table HTTP API column that pushes enriched rows is a Growth feature. No Clay account "
            "exists for this project.",
        ),
    ]
    return {
        "mode": local_mode(account),
        "verification": "verified_locally" if exercised else "unverified",
        "reached_real_service": account and exercised,
        "requirements": reqs,
        "blocking": [r["key"] for r in reqs if not r["configured"]],
        "note": "The boundary is built against Clay's documented Public API and signed-webhook contract "
        "and tested locally against that contract. Nothing has ever been requested from clay.com.",
    }


def _health(mode: str, activity: int, successes: int, errors: int) -> str:
    if mode == "not_configured":
        return "not_configured"
    if not activity:
        return "idle"
    if not successes:
        return "failing"
    return "degraded" if errors / activity > 0.1 else "healthy"


def integration_status(db: Session, ws: uuid.UUID, days: int = 7) -> dict[str, Any]:
    """Per-integration health, mode and verification level for the four tools GTMOS integrates with."""
    s = get_settings()
    since = utcnow() - timedelta(days=days)
    registered = {i.provider: i for i in db.scalars(select(Integration).where(Integration.workspace_id == ws))}
    items: list[dict[str, Any]] = []
    for b in BOUNDARIES:
        wh = _webhook_facts(db, ws, b.webhook_source, since) if b.webhook_source else {}
        sync = _sync_facts(db, ws, b.sync_provider, since) if b.sync_provider else {}
        enr = _enrichment_facts(db, ws, b.enrichment_prefixes, since)
        posture = _resolve_posture(
            b.provider,
            s,
            wh or {"lifetime_real": 0, "lifetime_total": 0},
            sync or {"live_runs": 0},
        )
        row_ = registered.get(b.provider)
        activity = int(wh.get("window_total", 0)) + int(sync.get("window_runs", 0)) + int(enr["attempts"])
        successes = int(wh.get("window_processed", 0)) + int(sync.get("window_ok", 0)) + int(enr["hits"])
        errors = int(wh.get("window_failed", 0)) + int(sync.get("window_failed", 0)) + int(enr["errors"])
        retries = int(wh.get("retries", 0)) + int(sync.get("retries", 0))
        records = int(wh.get("window_processed", 0)) + int(sync.get("records_changed", 0)) + int(enr["fields_filled"])
        last_failure_at = max(
            [t for t in (wh.get("last_failure_at"), sync.get("last_failure_at")) if t is not None],
            default=None,
        )
        last_failure = (
            sync.get("last_failure")
            if last_failure_at is not None and last_failure_at == sync.get("last_failure_at")
            else wh.get("last_failure")
        )
        items.append(
            {
                "provider": b.provider,
                "display_name": b.display_name,
                "category": b.category,
                "direction": b.direction,
                "summary": b.summary,
                "moves": list(b.moves),
                "endpoints": list(b.endpoints),
                "docs": [{"label": label, "path": path} for label, path in b.docs],
                "registered": row_ is not None,
                "registry_mode": row_.mode if row_ else None,
                "mode": posture["mode"],
                "mode_description": MODES[posture["mode"]],
                "verification": posture["verification"],
                "verification_description": VERIFICATION_LEVELS[posture["verification"]],
                "verification_note": posture["note"],
                "reached_real_service": posture["reached_real_service"],
                "requirements": posture["requirements"],
                "blocking": posture["blocking"],
                "health": _health(posture["mode"], activity, successes, errors),
                "last_inbound_event_at": wh.get("last_received_at"),
                "last_success_at": sync.get("last_success_at") or wh.get("last_processed_at"),
                "last_failure_at": last_failure_at,
                "last_failure": last_failure,
                "window": {
                    "days": days,
                    "inbound_events": int(wh.get("window_total", 0)),
                    "inbound_processed": int(wh.get("window_processed", 0)),
                    "inbound_by_status": wh.get("by_status", {}),
                    "signature_status": wh.get("by_signature", {}),
                    "duplicates_absorbed": int(wh.get("duplicates_absorbed", 0)),
                    "syncs": int(sync.get("window_runs", 0)),
                    "sync_failures": int(sync.get("window_failed", 0)),
                    "sync_partial": int(sync.get("window_partial", 0)),
                    "enrichment_attempts": int(enr["attempts"]),
                    "error_count": errors,
                    "retry_count": retries,
                    "error_rate": round(errors / activity, 4) if activity else None,
                    "records_processed": records,
                    "records_failed": int(sync.get("records_failed", 0)),
                    "latency": {
                        "inbound_p50_ms": wh.get("p50_processing_ms"),
                        "inbound_p95_ms": wh.get("p95_processing_ms"),
                        "sync_p50_ms": sync.get("p50_duration_ms"),
                        "enrichment_avg_ms": enr["avg_latency_ms"],
                    },
                },
                "lifetime": {
                    "inbound_events": int(wh.get("lifetime_total", 0)),
                    "real_deliveries": int(wh.get("lifetime_real", 0)),
                    "synthetic_history": int(wh.get("lifetime_synthetic", 0)),
                    "live_sync_runs": int(sync.get("live_runs", 0)),
                },
            }
        )
    return {
        "window_days": days,
        "generated_at": utcnow(),
        "modes": MODES,
        "verification_levels": VERIFICATION_LEVELS,
        "integrations": items,
    }


def integration_activity(db: Session, ws: uuid.UUID, provider: str, days: int = 30, limit: int = 25) -> dict[str, Any]:
    """The rows behind an integration card: recent inbound deliveries, recent syncs, recent errors."""
    b = BOUNDARIES_BY_PROVIDER[provider]
    since = utcnow() - timedelta(days=days)
    events: list[dict[str, Any]] = []
    if b.webhook_source:
        events = [
            {
                "id": str(e.id),
                "source": e.source,
                "event_type": e.event_type,
                "status": e.status,
                "signature_status": e.signature_status,
                "error": e.error,
                "attempts": e.attempts,
                "duplicate_count": e.duplicate_count,
                "processing_ms": e.processing_ms,
                "received_at": e.received_at,
                "correlation_id": e.correlation_id,
                "synthetic_history": bool((e.payload or {}).get("synthetic_history")),
                "result_summary": {
                    k: v for k, v in (e.result or {}).items() if isinstance(v, int | str | bool | float)
                },
            }
            for e in db.scalars(
                select(WebhookEvent)
                .where(WebhookEvent.workspace_id == ws, WebhookEvent.source == b.webhook_source)
                .order_by(WebhookEvent.received_at.desc())
                .limit(limit)
            )
        ]
    syncs: list[dict[str, Any]] = []
    if b.sync_provider:
        syncs = [
            {
                "id": str(r.id),
                "job": r.job,
                "direction": r.direction,
                "object_type": r.object_type,
                "status": r.status,
                "is_simulated": r.is_simulated,
                "records_changed": r.records_changed,
                "records_failed": r.records_failed,
                "records_skipped": r.records_skipped,
                "retries": r.retries,
                "duration_ms": r.duration_ms,
                "started_at": r.started_at,
                "trigger": r.trigger,
                "correlation_id": r.correlation_id,
                "error": _first_error(r.errors),
            }
            for r in db.scalars(
                select(IntegrationSync)
                .where(IntegrationSync.workspace_id == ws, IntegrationSync.provider == b.sync_provider)
                .order_by(IntegrationSync.started_at.desc())
                .limit(limit)
            )
        ]
    errors = sorted(
        [
            {
                "kind": "webhook",
                "at": e["received_at"],
                "label": f"{e['event_type']} delivery",
                "status": e["status"],
                "message": e["error"],
                "correlation_id": e["correlation_id"],
            }
            for e in events
            if e["status"] in _FAILED_EVENT_STATUSES
        ]
        + [
            {
                "kind": "sync",
                "at": r["started_at"],
                "label": r["job"],
                "status": r["status"],
                "message": r["error"],
                "correlation_id": r["correlation_id"],
            }
            for r in syncs
            if r["status"] in _FAILED_SYNC_STATUSES or r["error"]
        ],
        key=lambda r: r["at"],
        reverse=True,
    )
    return {
        "provider": b.provider,
        "display_name": b.display_name,
        "window_days": days,
        "since": since,
        "events": events,
        "syncs": syncs,
        "errors": errors[:limit],
    }
