"""Workspace info, integrations, CRM sync / reverse ETL, enrichment runs and inbound webhooks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gtmos.api.deps import db_session, parse_uuid, require_admin_for_live_writes, row, workspace
from gtmos.config import get_settings
from gtmos.integrations.clay import API_KEY_HEADER, CLAY_API_BASE, SIGNATURE_HEADER, ClayClient
from gtmos.integrations.hubspot import CUSTOM_PROPERTIES, ID_PROPERTY
from gtmos.integrations.posthog import normalize, parse_payload
from gtmos.models import (
    Account,
    Contact,
    EnrichmentRun,
    Integration,
    Opportunity,
    Signal,
    SimulatedCrmObject,
    WebhookEvent,
    Workspace,
)
from gtmos.services import clay_service, crm_sync, webhook_service
from gtmos.services.product_events import ingest_events
from gtmos.services.webhook_service import PermanentError

router = APIRouter(tags=["integrations"])


@router.get("/workspace")
def workspace_info(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    s = get_settings()

    def count(model: Any) -> int:
        return db.scalar(select(func.count()).select_from(model).where(model.workspace_id == ws.id)) or 0

    return {
        **row(ws),
        "llm_mode": s.llm_mode,
        "hubspot_mode": "live" if s.hubspot_access_token and s.hubspot_live_writes_enabled else "demo",
        "outbound_send_enabled": False,
        "counts": {
            "accounts": count(Account),
            "contacts": count(Contact),
            "signals": count(Signal),
            "opportunities": count(Opportunity),
        },
        "flagship_account_id": str(
            db.scalar(select(Account.id).where(Account.workspace_id == ws.id, Account.is_flagship.is_(True))) or ""
        ),
    }


def _current_mode(provider: str, stored: str) -> str:
    """Modes reflect the running configuration, not what was true when the row was seeded."""
    s = get_settings()
    live = {
        "hubspot": bool(s.hubspot_access_token and s.hubspot_live_writes_enabled),
        "anthropic": s.llm_mode == "live",
        "apollo": bool(s.apollo_api_key),
    }
    if provider in live:
        if live[provider]:
            return "live"
        return "disabled" if provider == "apollo" else "demo"
    return stored


@router.get("/integrations")
def integrations(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> list[dict[str, Any]]:
    return [
        {**row(i, exclude=("workspace_id",)), "mode": _current_mode(i.provider, i.mode)}
        for i in db.scalars(
            select(Integration)
            .where(Integration.workspace_id == ws.id)
            .order_by(Integration.category, Integration.provider)
        )
    ]


@router.get("/integrations/hubspot/mapping")
def hubspot_mapping() -> dict[str, Any]:
    return {
        "id_properties": ID_PROPERTY,
        "custom_properties": CUSTOM_PROPERTIES,
        "objects": {"Account": "companies", "Contact": "contacts", "Opportunity": "deals"},
    }


@router.get("/integrations/hubspot/reverse-etl/preview")
def reverse_etl_preview(
    limit: int = Query(25, ge=1, le=200), db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    return crm_sync.preview_reverse_etl(db, ws.id, limit)


@router.post("/integrations/hubspot/reverse-etl/run", dependencies=[Depends(require_admin_for_live_writes)])
def reverse_etl_run(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    sync = crm_sync.run_company_sync(db, ws.id, job="reverse_etl_companies", trigger="manual")
    db.commit()
    return row(sync, exclude=("workspace_id",))


@router.post("/integrations/hubspot/reverse-etl/contacts-deals", dependencies=[Depends(require_admin_for_live_writes)])
def reverse_etl_contacts_deals(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    """Push contacts and deals for accounts already in the CRM, then associate them to their company.

    Deliberately a separate call from the company sync: an association needs both records to exist, so
    companies must land first. Running this against an account with no company record skips it rather
    than creating one, because a contact that conjures a company is how duplicate companies appear.
    """
    sync = crm_sync.run_contact_and_deal_sync(db, ws.id, job="reverse_etl_contacts_deals", trigger="manual")
    db.commit()
    return row(sync, exclude=("workspace_id",))


@router.get("/integrations/hubspot/simulated-objects")
def simulated_objects(
    object_type: str = "companies",
    q: str | None = Query(None, max_length=100),
    limit: int = Query(50, le=200),
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
) -> dict[str, Any]:
    cond = [SimulatedCrmObject.workspace_id == ws.id, SimulatedCrmObject.object_type == object_type]
    if q:
        cond.append(func.lower(SimulatedCrmObject.properties["name"].as_string()).like(f"%{q.lower()}%"))
    items = list(
        db.scalars(select(SimulatedCrmObject).where(*cond).order_by(SimulatedCrmObject.updated_at.desc()).limit(limit))
    )
    return {
        "simulated": True,
        "counts": crm_sync.simulated_crm_counts(db, ws.id),
        "items": [row(o, exclude=("workspace_id",)) for o in items],
        "note": "SIMULATED. This is the demo adapter's local store, not a HubSpot portal.",
    }


@router.get("/enrichment/runs")
def enrichment_runs(
    limit: int = Query(50, le=200), db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    rows = db.execute(
        select(EnrichmentRun, Account.name)
        .join(Account, Account.id == EnrichmentRun.entity_id)
        .where(EnrichmentRun.workspace_id == ws.id)
        .order_by(EnrichmentRun.started_at.desc())
        .limit(limit)
    ).all()
    return {"items": [{**row(r, exclude=("workspace_id",)), "account_name": n} for r, n in rows]}


# Webhooks --------------------------------------------------------------------------------------------


def _posthog_processor(ws: Workspace) -> webhook_service.Processor:
    def process(db: Session, payload: Any) -> dict[str, Any]:
        try:
            events = [normalize(e) for e in parse_payload(payload)]
        except ValidationError as exc:
            raise PermanentError(f"invalid PostHog payload: {exc.error_count()} validation error(s)") from exc
        results = ingest_events(db, ws.id, events)
        return {
            "events": len(results),
            "matched": sum(1 for r in results if r["account_id"]),
            "signals_created": sum(1 for r in results if r["signal"] and r["signal"]["created"]),
            "workflow_runs": [w for r in results for w in r["workflow_runs"]],
            "results": results[:50],
        }

    return process


def _signal_processor(ws: Workspace) -> webhook_service.Processor:
    from gtmos.api.routes.crm import SignalIn, ingest_signal_payload

    def process(db: Session, payload: Any) -> dict[str, Any]:
        items = payload if isinstance(payload, list) else payload.get("signals", [payload])
        out = []
        for item in items[:100]:
            try:
                body = SignalIn.model_validate(item)
            except ValidationError as exc:
                raise PermanentError(f"invalid signal: {exc.errors()[0]['msg']}") from exc
            out.append(ingest_signal_payload(db, ws, body))
        return {"signals": out}

    return process


async def _receive(
    request: Request,
    response: Response,
    db: Session,
    ws: Workspace,
    source: str,
    event_type: str,
    processor: webhook_service.Processor,
) -> dict[str, Any]:
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(413, "payload too large")
    res = webhook_service.receive(
        db,
        ws.id,
        source,
        event_type,
        dict(request.headers),
        body,
        processor,
        method=request.method,
        uri=str(request.url),
    )
    db.commit()
    response.status_code = res.http_status
    ev = res.event
    return {
        "id": str(ev.id),
        "status": "duplicate" if res.duplicate else ev.status,
        "duplicate": res.duplicate,
        "signature": ev.signature_status,
        "error": ev.error,
        "result": ev.result,
        "correlation_id": ev.correlation_id,
    }


@router.post("/webhooks/posthog")
async def webhook_posthog(
    request: Request, response: Response, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    return await _receive(request, response, db, ws, "posthog", "product_event", _posthog_processor(ws))


@router.post("/events")
async def product_events(
    request: Request, response: Response, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    """Direct PostHog-shaped event capture (same pipeline as the webhook)."""
    return await _receive(request, response, db, ws, "posthog", "product_event", _posthog_processor(ws))


@router.post("/webhooks/n8n")
async def webhook_n8n(
    request: Request, response: Response, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    return await _receive(request, response, db, ws, "n8n", "signal", _signal_processor(ws))


@router.post("/webhooks/hubspot")
async def webhook_hubspot(
    request: Request, response: Response, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    """HubSpot CRM change events (v3 signature). Recorded and acknowledged; property changes are not applied
    back automatically. Conflicts with GTMOS-owned fields are logged for review (see docs/integrations.md)."""

    def process(db: Session, payload: Any) -> dict[str, Any]:
        events = payload if isinstance(payload, list) else [payload]
        return {
            "received": len(events),
            "applied": 0,
            "note": "Inbound CRM changes are logged; GTMOS-owned gtmos_* properties are never overwritten.",
        }

    return await _receive(request, response, db, ws, "hubspot", "crm_change", process)


@router.post("/webhooks/clay")
async def webhook_clay(
    request: Request, response: Response, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    """An enriched record pushed from a Clay table, signed with HMAC-SHA256 in `X-Clay-Signature`.

    The payload contract is GTMOS's, not Clay's: Clay's HTTP API column body is a JSON template the
    operator writes, so there is no standard Clay envelope to parse. `docs/clay-live-setup.md` is what
    a Clay table is configured against. Ingestion runs through the same pipeline as every other source.
    """
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(413, "payload too large")
    try:
        res = clay_service.receive(db, ws, dict(request.headers), body, method=request.method, uri=str(request.url))
    except clay_service.ClaySignatureError as exc:
        # Nothing is stored: unlike the sources whose scheme `webhook_service` verifies itself, an
        # unverified Clay delivery is turned away at the door rather than persisted as a rejected event.
        raise HTTPException(401, f"Clay signature check failed: {exc}") from exc
    db.commit()
    response.status_code = res.http_status
    ev = res.event
    return {
        "id": str(ev.id),
        "status": "duplicate" if res.duplicate else ev.status,
        "duplicate": res.duplicate,
        "signature": ev.signature_status,
        "error": ev.error,
        "result": ev.result,
        "correlation_id": ev.correlation_id,
    }


@router.get("/integrations/clay/contract")
def clay_contract() -> dict[str, Any]:
    """The columns GTMOS parses out of a Clay row, and the state of the outbound client.

    Published as an endpoint because the Clay table is configured by hand against this list: a column
    name that is not here is silently ignored, and reading it from the running API beats trusting a doc.
    """
    s = get_settings()
    client = ClayClient.from_settings(s)
    return {
        "endpoint": "/api/v1/webhooks/clay",
        "signature_header": SIGNATURE_HEADER,
        "signature_scheme": "sha256=<hex HMAC-SHA256(signing_secret, raw_body)>",
        "webhook_secret_configured": s.clay_webhook_secret is not None,
        "idempotency": "clay_row_id (+ clay_run_id when present); redeliveries are deduplicated",
        "account_columns": {f: list(spec.aliases) for f, spec in clay_service.ACCOUNT_FIELDS.items()},
        "contact_columns": {f: list(spec.aliases) for f, spec in clay_service.CONTACT_FIELDS.items()},
        "cell_envelope": ["value", "provider", "confidence", "observed_at", "status", "others"],
        "unresolved_cell_statuses": sorted(clay_service.UNRESOLVED_CELL_STATUSES),
        "default_confidence": clay_service.CLAY_DEFAULT_CONFIDENCE,
        "outbound": {
            "base_url": CLAY_API_BASE,
            "auth_header": API_KEY_HEADER,
            "mode": client.mode,
            "note": "Inert without CLAY_API_KEY: no network call is made and none is made in demo mode.",
        },
        "verified_against_live_clay": False,
    }


@router.get("/webhooks/events")
def webhook_events(
    source: str | None = None,
    status: str | None = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
) -> dict[str, Any]:
    cond = [WebhookEvent.workspace_id == ws.id]
    if source:
        cond.append(WebhookEvent.source == source)
    if status:
        cond.append(WebhookEvent.status == status)
    items = list(db.scalars(select(WebhookEvent).where(*cond).order_by(WebhookEvent.received_at.desc()).limit(limit)))
    return {"items": [row(e, exclude=("workspace_id",)) for e in items]}


class ReplayBody(BaseModel):
    pass


@router.post("/webhooks/events/{event_id}/replay")
def webhook_replay(
    event_id: str, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    ev = db.get(WebhookEvent, parse_uuid(event_id))
    if ev is None or ev.workspace_id != ws.id:
        raise HTTPException(404, "event not found")
    if ev.payload.get("synthetic_history"):
        raise HTTPException(409, "Synthetic history events are illustrative and cannot be replayed.")
    processor = {
        "posthog": _posthog_processor(ws),
        "n8n": _signal_processor(ws),
        "clay": clay_service.processor(ws),
    }.get(ev.source)
    if processor is None:
        raise HTTPException(409, f"replay not supported for source '{ev.source}'")
    try:
        webhook_service.replay(db, ev, processor)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return row(ev, exclude=("workspace_id",))
