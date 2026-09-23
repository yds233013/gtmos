"""Accounts: list, flagship detail view, and account-level actions."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from gtmos.api.deps import Page, actor, db_session, parse_uuid, row, workspace
from gtmos.domain.committee import ROLE_LABELS
from gtmos.models import (
    Account,
    AccountContactRole,
    Activity,
    AuditEvent,
    Campaign,
    Contact,
    EnrichmentAttempt,
    EnrichmentRun,
    Experiment,
    ExperimentAssignment,
    ExperimentOutcome,
    ExperimentVariant,
    ExternalRecord,
    ICPScore,
    MessageDraft,
    Opportunity,
    ResearchEvidence,
    RoutingDecision,
    Signal,
    StageTransition,
    User,
    Workflow,
    WorkflowRun,
    Workspace,
)
from gtmos.services import committee_service, crm_service, outreach_service, routing_service
from gtmos.services.common import NotFound, utcnow
from gtmos.services.enrichment_service import enrich_account, provenance_for
from gtmos.services.next_action import next_best_action
from gtmos.services.research_service import generate_research, latest_report
from gtmos.services.scoring_service import active_icp, current_score, rescore_accounts
from gtmos.services.workflow_engine import run_manual

router = APIRouter(prefix="/accounts", tags=["accounts"])

SORTS: dict[str, Any] = {
    "score": Account.icp_score.desc().nulls_last(),
    "intent": Account.intent_score.desc().nulls_last(),
    "recent_signal": Account.last_signal_at.desc().nulls_last(),
    "name": Account.name.asc(),
    "employees": Account.employee_count.desc().nulls_last(),
}


def get_account(db: Session, ws: Workspace, account_id: str) -> Account:
    a = db.get(Account, parse_uuid(account_id))
    if a is None or a.workspace_id != ws.id:
        raise HTTPException(404, "account not found")
    return a


def _users(db: Session, ws: Workspace) -> dict[uuid.UUID, str]:
    return dict(db.execute(select(User.id, User.name).where(User.workspace_id == ws.id)).tuples().all())


@router.get("")
def list_accounts(
    q: str | None = Query(None, max_length=100),
    grade: list[str] | None = Query(None),
    segment: list[str] | None = Query(None),
    region: list[str] | None = Query(None),
    stage: list[str] | None = Query(None),
    industry: str | None = Query(None, max_length=120),
    owner_id: str | None = None,
    unowned: bool = False,
    signal_days: int | None = Query(None, ge=1, le=365),
    customers: Literal["include", "exclude", "only"] = "include",
    sort: Literal["score", "intent", "recent_signal", "name", "employees"] = "score",
    page: Page = Depends(),
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
) -> dict[str, Any]:
    cond = [Account.workspace_id == ws.id, Account.merged_into_id.is_(None)]
    if q:
        like = f"%{q.lower()}%"
        cond.append(or_(func.lower(Account.name).like(like), func.lower(Account.domain).like(like)))
    if grade:
        cond.append(Account.score_grade.in_(grade))
    if segment:
        cond.append(Account.segment.in_(segment))
    if region:
        cond.append(Account.region.in_(region))
    if stage:
        cond.append(Account.funnel_stage.in_(stage))
    if industry:
        cond.append(Account.industry == industry)
    if owner_id:
        cond.append(Account.owner_id == parse_uuid(owner_id))
    if unowned:
        cond.append(Account.owner_id.is_(None))
    if signal_days:
        cond.append(Account.last_signal_at >= utcnow() - timedelta(days=signal_days))
    if customers == "exclude":
        cond.append(Account.is_customer.is_(False))
    elif customers == "only":
        cond.append(Account.is_customer.is_(True))
    total = db.scalar(select(func.count()).select_from(Account).where(*cond)) or 0
    accounts = list(
        db.scalars(
            select(Account).where(*cond).order_by(SORTS[sort], Account.id).offset(page.offset).limit(page.page_size)
        )
    )
    ids = [a.id for a in accounts]
    recent = {
        r[0]: (r[1], r[2])
        for r in db.execute(
            select(Signal.account_id, Signal.title, Signal.signal_type)
            .where(Signal.account_id.in_(ids))
            .distinct(Signal.account_id)
            .order_by(Signal.account_id, Signal.observed_at.desc())
        )
    }
    scores = {
        s.account_id: s
        for s in db.scalars(select(ICPScore).where(ICPScore.account_id.in_(ids), ICPScore.is_current.is_(True)))
    }
    users = _users(db, ws)
    items = []
    for a in accounts:
        s = scores.get(a.id)
        items.append(
            {
                "id": str(a.id),
                "name": a.name,
                "domain": a.domain,
                "industry": a.industry,
                "employee_count": a.employee_count,
                "segment": a.segment,
                "region": a.region,
                "country": a.country,
                "icp_score": a.icp_score,
                "score_grade": a.score_grade,
                "intent_score": a.intent_score,
                "categories": {
                    "fit": s.fit,
                    "intent": s.intent,
                    "timing": s.timing,
                    "technical": s.technical,
                    "engagement": s.engagement,
                }
                if s
                else None,
                "funnel_stage": a.funnel_stage,
                "is_customer": a.is_customer,
                "owner": users.get(a.owner_id) if a.owner_id else None,
                "last_signal": {"title": recent[a.id][0], "type": recent[a.id][1]} if a.id in recent else None,
                "last_signal_at": a.last_signal_at,
                "data_origin": a.data_origin,
                "is_flagship": a.is_flagship,
            }
        )
    _, icp = active_icp(db, ws.id)
    return {
        "items": items,
        "total": total,
        "page": page.page,
        "page_size": page.page_size,
        "category_max": icp.weights.as_dict(),
    }


@router.get("/facets")
def facets(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    base = [Account.workspace_id == ws.id, Account.merged_into_id.is_(None)]

    def f(col: Any) -> list[dict[str, Any]]:
        return [
            {"value": v, "count": n}
            for v, n in db.execute(
                select(col, func.count()).where(*base).group_by(col).order_by(func.count().desc())
            ).all()
            if v
        ]

    return {
        "grade": f(Account.score_grade),
        "segment": f(Account.segment),
        "region": f(Account.region),
        "stage": f(Account.funnel_stage),
        "industry": f(Account.industry),
    }


def experiment_participation(db: Session, account_id: uuid.UUID) -> list[dict[str, Any]]:
    """Which experiments this account is in, which arm, and what it did.

    Without this the account page is where the loop visibly breaks: an account is enrolled in a test,
    the experiments page reports a lift, and nothing on the account says it took part.
    """
    rows = db.execute(
        select(ExperimentAssignment, Experiment, ExperimentVariant)
        .join(Experiment, Experiment.id == ExperimentAssignment.experiment_id)
        .join(ExperimentVariant, ExperimentVariant.id == ExperimentAssignment.variant_id)
        .where(ExperimentAssignment.account_id == account_id)
        .order_by(ExperimentAssignment.assigned_at.desc())
    ).all()
    if not rows:
        return []
    outcomes: dict[uuid.UUID, list[str]] = {}
    for assignment_id, metric in db.execute(
        select(ExperimentOutcome.assignment_id, ExperimentOutcome.metric).where(
            ExperimentOutcome.assignment_id.in_([a.id for a, _, _ in rows])
        )
    ).tuples():
        outcomes.setdefault(assignment_id, []).append(metric)
    return [
        {
            "experiment_key": exp.key,
            "experiment": exp.name,
            "status": exp.status,
            "variant": var.name,
            "variant_key": var.key,
            "is_control": var.is_control,
            "assigned_at": assignment.assigned_at,
            "exposed_at": assignment.exposed_at,
            "outcomes": sorted(outcomes.get(assignment.id, [])),
        }
        for assignment, exp, var in rows
    ]


@router.get("/{account_id}")
def account_detail(
    account_id: str, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    a = get_account(db, ws, account_id)
    users = _users(db, ws)
    sc = current_score(db, a.id)
    prov = provenance_for(db, a.id)
    contacts = list(db.scalars(select(Contact).where(Contact.account_id == a.id).order_by(Contact.last_name)))
    roles = list(
        db.scalars(
            select(AccountContactRole)
            .where(AccountContactRole.account_id == a.id)
            .order_by(AccountContactRole.role, AccountContactRole.rank)
        )
    )
    contact_map = {c.id: c for c in contacts}
    signals = list(db.scalars(select(Signal).where(Signal.account_id == a.id).order_by(Signal.observed_at.desc())))
    campaigns = dict(
        db.execute(select(Campaign.id, Campaign.name).where(Campaign.workspace_id == ws.id)).tuples().all()
    )
    acts = list(
        db.scalars(
            select(Activity)
            .where(Activity.account_id == a.id, Activity.type != "email_delivered")
            .order_by(Activity.occurred_at.desc())
            .limit(150)
        )
    )
    opps = list(
        db.scalars(select(Opportunity).where(Opportunity.account_id == a.id).order_by(Opportunity.opened_at.desc()))
    )
    report = latest_report(db, a.id)
    evidence = (
        list(
            db.scalars(
                select(ResearchEvidence).where(ResearchEvidence.report_id == report.id).order_by(ResearchEvidence.ref)
            )
        )
        if report
        else []
    )
    drafts = list(
        db.scalars(
            select(MessageDraft)
            .where(MessageDraft.account_id == a.id)
            .order_by(MessageDraft.created_at.desc())
            .limit(20)
        )
    )
    wf_names = dict(db.execute(select(Workflow.id, Workflow.name).where(Workflow.workspace_id == ws.id)).tuples().all())
    runs = list(
        db.scalars(
            select(WorkflowRun).where(WorkflowRun.account_id == a.id).order_by(WorkflowRun.created_at.desc()).limit(20)
        )
    )
    decisions = list(
        db.scalars(
            select(RoutingDecision)
            .where(RoutingDecision.account_id == a.id)
            .order_by(RoutingDecision.decided_at.desc())
            .limit(10)
        )
    )
    enrich_runs = list(
        db.scalars(
            select(EnrichmentRun)
            .where(EnrichmentRun.entity_id == a.id)
            .order_by(EnrichmentRun.started_at.desc())
            .limit(5)
        )
    )
    attempts = (
        list(
            db.scalars(
                select(EnrichmentAttempt)
                .where(EnrichmentAttempt.run_id == enrich_runs[0].id)
                .order_by(EnrichmentAttempt.field, EnrichmentAttempt.position)
            )
        )
        if enrich_runs
        else []
    )
    history = db.execute(
        select(ICPScore.total, ICPScore.computed_at, ICPScore.trigger)
        .where(ICPScore.account_id == a.id)
        .order_by(ICPScore.computed_at.desc())
        .limit(20)
    ).all()
    transitions = list(
        db.scalars(
            select(StageTransition).where(StageTransition.entity_id == a.id).order_by(StageTransition.changed_at)
        )
    )
    audit_rows = list(
        db.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == a.id).order_by(AuditEvent.occurred_at.desc()).limit(30)
        )
    )
    ext = db.scalars(select(ExternalRecord).where(ExternalRecord.internal_id == a.id)).first()
    nba = next_best_action(db, a)

    def contact_view(c: Contact) -> dict[str, Any]:
        return {
            **row(c, exclude=("workspace_id",)),
            "full_name": c.full_name,
            "roles": [r.role for r in roles if r.contact_id == c.id and r.rank == 1],
        }

    return {
        "account": {**row(a), "owner": users.get(a.owner_id) if a.owner_id else None},
        "provenance": {
            f: {
                "source": p.source,
                "confidence": p.confidence,
                "observed_at": p.observed_at,
                "enrichment_run_id": str(p.enrichment_run_id) if p.enrichment_run_id else None,
                "is_manual_lock": p.is_manual_lock,
                "conflict": p.conflict,
            }
            for f, p in prov.items()
        },
        "score": None
        if not sc
        else {
            **row(sc[0], exclude=("workspace_id",)),
            "components": [row(c, exclude=("icp_score_id",)) for c in sorted(sc[1], key=lambda c: -c.max_points)],
        },
        "score_history": [{"total": t, "computed_at": at, "trigger": tr} for t, at, tr in reversed(history)],
        "signals": [row(s, exclude=("workspace_id", "dedupe_key")) for s in signals],
        "contacts": [contact_view(c) for c in contacts if c.merged_into_id is None],
        "committee": [
            {
                **row(r, exclude=("account_id",)),
                "role_label": ROLE_LABELS[r.role],
                "contact": {
                    "id": str(r.contact_id),
                    "name": contact_map[r.contact_id].full_name,
                    "title": contact_map[r.contact_id].title,
                    "email": contact_map[r.contact_id].email,
                    "email_status": contact_map[r.contact_id].email_status,
                }
                if r.contact_id in contact_map
                else None,
            }
            for r in roles
        ],
        "research": None
        if not report
        else {**row(report, exclude=("workspace_id",)), "evidence": [row(e, exclude=("report_id",)) for e in evidence]},
        "drafts": [row(d, exclude=("workspace_id",)) for d in drafts],
        "activities": [
            {
                **row(x, exclude=("workspace_id", "dedupe_key")),
                "campaign": campaigns.get(x.campaign_id) if x.campaign_id else None,
                "contact_name": contact_map[x.contact_id].full_name if x.contact_id in contact_map else None,
            }
            for x in acts
        ],
        "opportunities": [
            {
                **row(o, exclude=("workspace_id",)),
                "owner": users.get(o.owner_id) if o.owner_id else None,
                "campaign": campaigns.get(o.source_campaign_id) if o.source_campaign_id else None,
            }
            for o in opps
        ],
        "workflow_runs": [
            {
                **row(r, exclude=("workspace_id", "trigger_event")),
                "workflow": wf_names.get(r.workflow_id),
                "synthetic_history": bool((r.trigger_event or {}).get("synthetic_history")),
                "trigger": (r.trigger_event or {}).get("type"),
            }
            for r in runs
        ],
        "routing_decisions": [
            {
                **row(d, exclude=("workspace_id",)),
                "assigned_to": users.get(d.assigned_user_id) if d.assigned_user_id else None,
            }
            for d in decisions
        ],
        "experiments": experiment_participation(db, a.id),
        "enrichment": {
            "runs": [row(r, exclude=("workspace_id",)) for r in enrich_runs],
            "latest_attempts": [row(x, exclude=("run_id",)) for x in attempts],
        },
        "stage_history": [row(t, exclude=("workspace_id",)) for t in transitions],
        "audit": [row(e, exclude=("workspace_id",)) for e in audit_rows],
        "crm_sync": None
        if not ext
        else {
            "external_id": ext.external_id,
            "last_synced_at": ext.last_synced_at,
            "is_simulated": ext.is_simulated,
            "last_payload": ext.last_payload,
        },
        "next_action": {"key": nba.key, "label": nba.label, "reason": nba.reason, "priority": nba.priority},
    }


@router.post("/{account_id}/rescore")
def rescore(account_id: str, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    a = get_account(db, ws, account_id)
    before = a.icp_score
    out = rescore_accounts(db, ws.id, [a.id], trigger="manual")
    db.commit()
    return {"before": before, "after": a.icp_score, "grade": a.score_grade, "summary": out[0].result.summary}


@router.post("/{account_id}/enrich")
def enrich(account_id: str, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    a = get_account(db, ws, account_id)
    run = enrich_account(db, a, trigger="manual")
    before = a.icp_score
    if run.fields_changed:
        rescore_accounts(db, ws.id, [a.id], trigger="enrichment")
    attempts = list(
        db.scalars(
            select(EnrichmentAttempt)
            .where(EnrichmentAttempt.run_id == run.id)
            .order_by(EnrichmentAttempt.field, EnrichmentAttempt.position)
        )
    )
    db.commit()
    return {
        "run": row(run, exclude=("workspace_id",)),
        "attempts": [row(x, exclude=("run_id",)) for x in attempts],
        "score_before": before,
        "score_after": a.icp_score,
    }


class RouteBody(BaseModel):
    apply: bool = True


@router.post("/{account_id}/route")
def route(
    account_id: str, body: RouteBody, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    a = get_account(db, ws, account_id)
    if not body.apply:
        out = routing_service.simulate(db, a)
        users = _users(db, ws)
        return {
            "simulated": True,
            "outcome": out.outcome,
            "rule": out.rule_key,
            "assigned_to": users.get(uuid.UUID(out.assigned_user_id)) if out.assigned_user_id else None,
            "explanation": out.explanation,
            "conflicts": out.conflicts,
            "matched": out.matched,
        }
    d = routing_service.route_account(db, a, trigger="manual")
    db.commit()
    users = _users(db, ws)
    return {
        "simulated": False,
        **row(d, exclude=("workspace_id",)),
        "assigned_to": users.get(d.assigned_user_id) if d.assigned_user_id else None,
    }


class StageBody(BaseModel):
    stage: str = Field(max_length=40)
    reason: str | None = Field(default=None, max_length=500)
    recycle: bool = False


@router.post("/{account_id}/stage")
def change_stage(
    account_id: str,
    body: StageBody,
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
    who: str = Depends(actor),
) -> dict[str, Any]:
    a = get_account(db, ws, account_id)
    t = crm_service.change_funnel_stage(db, a, body.stage, actor=who, reason=body.reason, recycle=body.recycle)
    db.commit()
    return {
        "funnel_stage": a.funnel_stage,
        "lifecycle_stage": a.lifecycle_stage,
        "transition": row(t, exclude=("workspace_id",)),
    }


@router.post("/{account_id}/committee/recompute")
def committee_recompute(
    account_id: str, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    a = get_account(db, ws, account_id)
    roles = committee_service.recompute_committee(db, a)
    db.commit()
    return {"roles": [row(r, exclude=("account_id",)) for r in roles]}


class OverrideBody(BaseModel):
    contact_id: str


@router.put("/{account_id}/committee/{role}")
def committee_override(
    account_id: str,
    role: str,
    body: OverrideBody,
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
    who: str = Depends(actor),
) -> dict[str, Any]:
    a = get_account(db, ws, account_id)
    r = committee_service.override_role(db, a, role, parse_uuid(body.contact_id), who)
    db.commit()
    return row(r, exclude=("account_id",))


@router.delete("/{account_id}/committee/{role}")
def committee_clear(
    account_id: str, role: str, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, str]:
    a = get_account(db, ws, account_id)
    committee_service.clear_override(db, a, role)
    db.commit()
    return {"status": "cleared"}


class ResearchBody(BaseModel):
    # Defaults to False, not True. This field decides whether a request can cause a billed model
    # call, and a permissive default on such a field is the kind of thing that only looks harmless
    # until the endpoint is reachable from the internet with a key configured. The UI asks for it
    # explicitly; a direct caller has to as well.
    use_llm: bool = False


@router.post("/{account_id}/research")
def research(
    account_id: str,
    body: ResearchBody,
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
    who: str = Depends(actor),
) -> dict[str, Any]:
    a = get_account(db, ws, account_id)
    report = generate_research(db, a, actor=who, use_llm=body.use_llm)
    evidence = list(
        db.scalars(
            select(ResearchEvidence).where(ResearchEvidence.report_id == report.id).order_by(ResearchEvidence.ref)
        )
    )
    db.commit()
    return {**row(report, exclude=("workspace_id",)), "evidence": [row(e, exclude=("report_id",)) for e in evidence]}


class DraftBody(BaseModel):
    contact_id: str | None = None
    channels: list[Literal["email", "linkedin", "call_prep"]] = Field(default=["email", "linkedin", "call_prep"])


@router.post("/{account_id}/drafts")
def create_drafts(
    account_id: str,
    body: DraftBody,
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
    who: str = Depends(actor),
) -> dict[str, Any]:
    a = get_account(db, ws, account_id)
    contact = (
        db.get(Contact, parse_uuid(body.contact_id)) if body.contact_id else outreach_service.pick_recipient(db, a)
    )
    if contact is None or contact.account_id != a.id:
        raise HTTPException(409, "No reachable contact on this account. Identify the buying committee first.")
    drafts = outreach_service.draft_outreach(db, a, contact, channels=list(body.channels), actor=who)
    db.commit()
    return {"drafts": [row(d, exclude=("workspace_id",)) for d in drafts]}


class OpportunityBody(BaseModel):
    name: str = Field(min_length=3, max_length=300)
    amount: float = Field(ge=0, le=100_000_000)
    primary_contact_id: str | None = None


@router.post("/{account_id}/opportunities")
def create_opportunity(
    account_id: str,
    body: OpportunityBody,
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
    who: str = Depends(actor),
) -> dict[str, Any]:
    a = get_account(db, ws, account_id)
    o = crm_service.create_opportunity(
        db,
        a,
        name=body.name,
        amount=body.amount,
        actor=who,
        primary_contact_id=parse_uuid(body.primary_contact_id) if body.primary_contact_id else None,
    )
    db.commit()
    return row(o, exclude=("workspace_id",))


@router.post("/{account_id}/workflows/{workflow_key}/run")
def run_workflow(
    account_id: str,
    workflow_key: str,
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
    who: str = Depends(actor),
) -> dict[str, Any]:
    a = get_account(db, ws, account_id)
    wf = db.scalars(select(Workflow).where(Workflow.workspace_id == ws.id, Workflow.key == workflow_key)).first()
    if wf is None:
        raise NotFound("workflow not found")
    run = run_manual(db, wf, a, who)
    db.commit()
    if run is None:
        raise HTTPException(409, "duplicate run suppressed by idempotency key")
    return {"run_id": str(run.id), "status": run.status, "error": run.error}
