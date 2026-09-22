"""Workflows, routing, analytics, experiments, campaigns, data quality, inspector, operations, audit, copilot."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gtmos.api.deps import actor, db_session, parse_uuid, row, workspace
from gtmos.domain import metrics
from gtmos.domain.routing import route as route_rules
from gtmos.domain.workflows import ACTIONS
from gtmos.models import (
    Account,
    Activity,
    AuditEvent,
    Campaign,
    DataQualityIssue,
    Experiment,
    Opportunity,
    RoutingDecision,
    RoutingRule,
    User,
    Workflow,
    WorkflowRun,
    WorkflowStepRun,
    Workspace,
)
from gtmos.services import (
    analytics,
    attribution_service,
    copilot,
    data_quality,
    experiments_service,
    operations,
    stack_inspector,
)
from gtmos.services.common import audit, utcnow
from gtmos.services.routing_service import load_rules, load_users
from gtmos.services.workflow_engine import retry_run

router = APIRouter(tags=["operations"])


# Workflows -------------------------------------------------------------------------------------------


@router.get("/workflows")
def workflows(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> list[dict[str, Any]]:
    since = utcnow() - timedelta(days=30)
    stats: dict[Any, dict[str, int]] = {}
    for wid, status, n in db.execute(
        select(WorkflowRun.workflow_id, WorkflowRun.status, func.count())
        .where(WorkflowRun.workspace_id == ws.id, WorkflowRun.created_at >= since)
        .group_by(WorkflowRun.workflow_id, WorkflowRun.status)
    ):
        stats.setdefault(wid, {})[status] = n
    last = dict(
        db.execute(
            select(WorkflowRun.workflow_id, func.max(WorkflowRun.created_at))
            .where(WorkflowRun.workspace_id == ws.id)
            .group_by(WorkflowRun.workflow_id)
        )
        .tuples()
        .all()
    )
    return [
        {**row(w, exclude=("workspace_id",)), "runs_30d": stats.get(w.id, {}), "last_run_at": last.get(w.id)}
        for w in db.scalars(select(Workflow).where(Workflow.workspace_id == ws.id).order_by(Workflow.name))
    ]


@router.get("/workflows/actions")
def workflow_actions() -> dict[str, str]:
    return ACTIONS


class WorkflowPatch(BaseModel):
    is_enabled: bool


@router.patch("/workflows/{key}")
def patch_workflow(
    key: str,
    body: WorkflowPatch,
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
    who: str = Depends(actor),
) -> dict[str, Any]:
    wf = db.scalars(select(Workflow).where(Workflow.workspace_id == ws.id, Workflow.key == key)).first()
    if wf is None:
        raise HTTPException(404, "workflow not found")
    before = wf.is_enabled
    wf.is_enabled = body.is_enabled
    audit(
        db,
        ws.id,
        "workflow.toggled",
        "workflow",
        wf.id,
        before={"is_enabled": before},
        after={"is_enabled": wf.is_enabled},
        actor=who,
    )
    db.commit()
    return row(wf, exclude=("workspace_id",))


@router.get("/workflow-runs")
def workflow_runs(
    status: list[str] | None = Query(None),
    workflow: str | None = None,
    include_synthetic: bool = True,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
) -> dict[str, Any]:
    cond = [WorkflowRun.workspace_id == ws.id]
    if status:
        cond.append(WorkflowRun.status.in_(status))
    if workflow:
        cond.append(Workflow.key == workflow)
    if not include_synthetic:
        cond.append(WorkflowRun.trigger_event["synthetic_history"].as_string().is_(None))
    rows = db.execute(
        select(WorkflowRun, Workflow.name, Workflow.key, Account.name)
        .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
        .outerjoin(Account, Account.id == WorkflowRun.account_id)
        .where(*cond)
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    ).all()
    counts = dict(
        db.execute(
            select(WorkflowRun.status, func.count())
            .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
            .where(*cond)
            .group_by(WorkflowRun.status)
        )
        .tuples()
        .all()
    )
    return {
        "items": [
            {
                **row(r, exclude=("workspace_id",)),
                "workflow": wn,
                "workflow_key": wk,
                "account_name": an,
                "synthetic_history": bool((r.trigger_event or {}).get("synthetic_history")),
            }
            for r, wn, wk, an in rows
        ],
        "counts": counts,
    }


@router.get("/workflow-runs/{run_id}")
def workflow_run(run_id: str, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    r = db.get(WorkflowRun, parse_uuid(run_id))
    if r is None or r.workspace_id != ws.id:
        raise HTTPException(404, "run not found")
    wf = db.get(Workflow, r.workflow_id)
    acct = db.get(Account, r.account_id) if r.account_id else None
    steps = list(
        db.scalars(select(WorkflowStepRun).where(WorkflowStepRun.run_id == r.id).order_by(WorkflowStepRun.position))
    )
    return {
        **row(r, exclude=("workspace_id",)),
        "workflow": row(wf, exclude=("workspace_id",)) if wf else None,
        "account": {"id": str(acct.id), "name": acct.name} if acct else None,
        "steps": [row(s, exclude=("run_id",)) for s in steps],
        "synthetic_history": bool((r.trigger_event or {}).get("synthetic_history")),
    }


@router.post("/workflow-runs/{run_id}/retry")
def workflow_retry(
    run_id: str, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    r = db.get(WorkflowRun, parse_uuid(run_id))
    if r is None or r.workspace_id != ws.id:
        raise HTTPException(404, "run not found")
    if (r.trigger_event or {}).get("synthetic_history"):
        raise HTTPException(409, "Synthetic history runs are illustrative and cannot be retried.")
    retry_run(db, r)
    db.commit()
    return {"id": str(r.id), "status": r.status, "attempt": r.attempt, "error": r.error}


# Routing ---------------------------------------------------------------------------------------------


@router.get("/routing/rules")
def routing_rules(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> list[dict[str, Any]]:
    users = dict(db.execute(select(User.id, User.name).where(User.workspace_id == ws.id)).tuples().all())
    since = utcnow() - timedelta(days=90)
    hits = dict(
        db.execute(
            select(RoutingDecision.rule_id, func.count())
            .where(RoutingDecision.workspace_id == ws.id, RoutingDecision.decided_at >= since)
            .group_by(RoutingDecision.rule_id)
        )
        .tuples()
        .all()
    )
    return [
        {
            **row(r, exclude=("workspace_id",)),
            "assign_user": users.get(r.assign_user_id) if r.assign_user_id else None,
            "decisions_90d": hits.get(r.id, 0),
        }
        for r in db.scalars(
            select(RoutingRule).where(RoutingRule.workspace_id == ws.id).order_by(RoutingRule.priority, RoutingRule.key)
        )
    ]


@router.get("/routing/decisions")
def routing_decisions(
    outcome: str | None = None,
    conflicts_only: bool = False,
    limit: int = Query(100, le=500),
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
) -> dict[str, Any]:
    cond = [RoutingDecision.workspace_id == ws.id]
    if outcome:
        cond.append(RoutingDecision.outcome == outcome)
    if conflicts_only:
        cond.append(func.jsonb_array_length(RoutingDecision.conflicts) > 0)
    users = dict(db.execute(select(User.id, User.name).where(User.workspace_id == ws.id)).tuples().all())
    rows = db.execute(
        select(RoutingDecision, Account.name, Account.region, Account.segment, RoutingRule.name)
        .join(Account, Account.id == RoutingDecision.account_id)
        .outerjoin(RoutingRule, RoutingRule.id == RoutingDecision.rule_id)
        .where(*cond)
        .order_by(RoutingDecision.decided_at.desc())
        .limit(limit)
    ).all()
    counts = dict(
        db.execute(
            select(RoutingDecision.outcome, func.count())
            .where(RoutingDecision.workspace_id == ws.id)
            .group_by(RoutingDecision.outcome)
        )
        .tuples()
        .all()
    )
    counts["conflicts"] = (
        db.scalar(
            select(func.count())
            .select_from(RoutingDecision)
            .where(RoutingDecision.workspace_id == ws.id, func.jsonb_array_length(RoutingDecision.conflicts) > 0)
        )
        or 0
    )
    return {
        "items": [
            {
                **row(d, exclude=("workspace_id",)),
                "account_name": an,
                "region": rg,
                "segment": sg,
                "rule_name": rn,
                "assigned_to": users.get(d.assigned_user_id) if d.assigned_user_id else None,
            }
            for d, an, rg, sg, rn in rows
        ],
        "counts": counts,
    }


class RoutingSim(BaseModel):
    segment: Literal["strategic", "enterprise", "mid_market", "smb"] | None = None
    region: Literal["NA", "EMEA", "APAC", "LATAM"] | None = None
    icp_score: int = Field(default=70, ge=0, le=100)
    intent_score: int = Field(default=40, ge=0, le=100)
    is_customer: bool = False
    owner_id: str | None = None


@router.post("/routing/simulate")
def routing_simulate(
    body: RoutingSim, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    users = load_users(db, ws.id)
    names = {u.id: u.name for u in users}
    out = route_rules(load_rules(db, ws.id), {"account": body.model_dump()}, users)
    return {
        "outcome": out.outcome,
        "rule": out.rule_key,
        "assigned_to": names.get(out.assigned_user_id) if out.assigned_user_id else None,
        "explanation": out.explanation,
        "conflicts": out.conflicts,
        "matched": out.matched,
    }


# Analytics -------------------------------------------------------------------------------------------


@router.get("/analytics/overview")
def overview(
    days: int = Query(90, ge=7, le=365), db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    return analytics.overview(db, ws.id, days)


@router.get("/analytics/metrics")
def metric_definitions() -> dict[str, Any]:
    """The metric dictionary: how every reported number is defined, and how it can be misread."""
    return {"metrics": metrics.as_list()}


@router.get("/analytics/funnel")
def funnel(
    days: int = Query(90, ge=7, le=365), db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    return analytics.funnel(db, ws.id, days)


@router.get("/analytics/breakdown")
def breakdown(
    dimension: str = "segment",
    days: int = Query(180, ge=7, le=365),
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
) -> dict[str, Any]:
    try:
        return analytics.breakdown(db, ws.id, dimension, days)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/analytics/pipeline-trend")
def pipeline_trend(
    weeks: int = Query(16, ge=4, le=52), db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    return analytics.pipeline_trend(db, ws.id, weeks)


@router.get("/analytics/period-comparison")
def period_comparison(
    days: int = Query(28, ge=7, le=180), db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    return analytics.period_comparison(db, ws.id, days)


@router.get("/analytics/velocity")
def velocity(
    days: int = Query(180, ge=30, le=365), db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    return analytics.velocity(db, ws.id, days)


@router.get("/analytics/stuck")
def stuck(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    return analytics.stuck_accounts(db, ws.id)


@router.get("/analytics/score-validation")
def score_validation(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    return analytics.score_validation(db, ws.id)


@router.get("/analytics/signal-correlation")
def signal_correlation(
    days: int = Query(180, ge=30, le=365), db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    return analytics.signal_correlation(db, ws.id, days)


@router.get("/analytics/attribution")
def attribution(
    days: int = Query(180, ge=30, le=365), db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    return attribution_service.run(db, ws.id, days)


# Campaigns & experiments -----------------------------------------------------------------------------


@router.get("/campaigns")
def campaigns(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> list[dict[str, Any]]:
    acts = db.execute(
        select(Activity.campaign_id, Activity.type, func.count(), func.count(func.distinct(Activity.account_id)))
        .where(Activity.workspace_id == ws.id, Activity.campaign_id.is_not(None))
        .group_by(Activity.campaign_id, Activity.type)
    ).all()
    stats: dict[Any, dict[str, int]] = {}
    for cid, typ, n, accts in acts:
        s = stats.setdefault(cid, {})
        s[typ] = n
        if typ in ("email_sent", "webinar_attended"):
            s["accounts_touched"] = max(s.get("accounts_touched", 0), accts)
    opps = db.execute(
        select(
            Opportunity.source_campaign_id,
            func.count(),
            func.coalesce(func.sum(Opportunity.amount_usd), 0),
            func.count().filter(Opportunity.stage == "closed_won"),
            func.coalesce(func.sum(Opportunity.amount_usd).filter(Opportunity.stage == "closed_won"), 0),
        )
        .where(Opportunity.workspace_id == ws.id)
        .group_by(Opportunity.source_campaign_id)
    ).all()
    ostats = {
        cid: {"opportunities": n, "pipeline": float(p), "won": w, "won_revenue": float(wr)} for cid, n, p, w, wr in opps
    }
    out = []
    for c in db.scalars(select(Campaign).where(Campaign.workspace_id == ws.id).order_by(Campaign.start_date.desc())):
        s = stats.get(c.id, {})
        o = ostats.get(c.id, {"opportunities": 0, "pipeline": 0.0, "won": 0, "won_revenue": 0.0})
        sent = s.get("email_sent", 0)
        out.append(
            {
                **row(c, exclude=("workspace_id",)),
                "metrics": {
                    "accounts_touched": s.get("accounts_touched", 0),
                    "sent": sent,
                    "delivered": s.get("email_delivered", 0),
                    "opened": s.get("email_opened", 0),
                    "bounced": s.get("email_bounced", 0),
                    "replied": s.get("email_replied", 0),
                    "positive_replies": s.get("positive_reply", 0),
                    "meetings": s.get("meeting_held", 0),
                    "attended": s.get("webinar_attended", 0),
                    **o,
                    "reply_rate": round(s.get("email_replied", 0) / sent, 4) if sent else None,
                    "positive_reply_rate": round(s.get("positive_reply", 0) / sent, 4) if sent else None,
                },
            }
        )
    return out


@router.get("/experiments")
def experiments(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> list[dict[str, Any]]:
    return experiments_service.list_experiments(db, ws.id)


@router.get("/experiments/{key}")
def experiment(key: str, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    e = db.scalars(select(Experiment).where(Experiment.workspace_id == ws.id, Experiment.key == key)).first()
    if e is None:
        raise HTTPException(404, "experiment not found")
    return experiments_service.results(db, e)


# Data quality ----------------------------------------------------------------------------------------


@router.get("/data-quality")
def dq_summary(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    counts = db.execute(
        select(DataQualityIssue.rule_key, DataQualityIssue.status, func.count())
        .where(DataQualityIssue.workspace_id == ws.id)
        .group_by(DataQualityIssue.rule_key, DataQualityIssue.status)
    ).all()
    by_rule: dict[str, dict[str, int]] = {}
    for rk, st, n in counts:
        by_rule.setdefault(rk, {})[st] = n
    last = db.scalar(select(func.max(DataQualityIssue.last_seen_at)).where(DataQualityIssue.workspace_id == ws.id))
    rules = [
        {
            "key": k,
            **v,
            "open": by_rule.get(k, {}).get("open", 0),
            "resolved": by_rule.get(k, {}).get("resolved", 0),
            "ignored": by_rule.get(k, {}).get("ignored", 0),
        }
        for k, v in data_quality.RULES.items()
    ]
    return {
        "rules": rules,
        "open_total": sum(r["open"] for r in rules),
        "resolved_total": sum(r["resolved"] for r in rules),
        "last_scan_at": last,
    }


@router.get("/data-quality/issues")
def dq_issues(
    rule: str | None = None,
    status: str = "open",
    limit: int = Query(200, le=1000),
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
) -> dict[str, Any]:
    cond = [DataQualityIssue.workspace_id == ws.id, DataQualityIssue.status == status]
    if rule:
        cond.append(DataQualityIssue.rule_key == rule)
    sev = {"high": 0, "medium": 1, "low": 2}
    items = list(
        db.scalars(select(DataQualityIssue).where(*cond).order_by(DataQualityIssue.detected_at.desc()).limit(limit))
    )
    items.sort(key=lambda i: (sev.get(i.severity, 3), i.rule_key))
    return {"items": [row(i, exclude=("workspace_id",)) for i in items]}


@router.post("/data-quality/scan")
def dq_scan(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    out = data_quality.scan(db, ws.id)
    db.commit()
    return out


def _issue(db: Session, ws: Workspace, issue_id: str) -> DataQualityIssue:
    i = db.get(DataQualityIssue, parse_uuid(issue_id))
    if i is None or i.workspace_id != ws.id:
        raise HTTPException(404, "issue not found")
    return i


@router.post("/data-quality/issues/{issue_id}/remediate")
def dq_remediate(
    issue_id: str, db: Session = Depends(db_session), ws: Workspace = Depends(workspace), who: str = Depends(actor)
) -> dict[str, Any]:
    i = _issue(db, ws, issue_id)
    if i.status != "open":
        raise HTTPException(409, f"issue is {i.status}")
    result = data_quality.remediate(db, i, who)
    db.commit()
    return {"issue": row(i, exclude=("workspace_id",)), "result": result}


@router.post("/data-quality/issues/{issue_id}/ignore")
def dq_ignore(
    issue_id: str, db: Session = Depends(db_session), ws: Workspace = Depends(workspace), who: str = Depends(actor)
) -> dict[str, Any]:
    i = _issue(db, ws, issue_id)
    i.status = "ignored"
    i.resolved_by = who
    i.resolved_at = utcnow()
    audit(db, ws.id, "data_quality.issue_ignored", "data_quality_issue", i.id, after={"rule": i.rule_key}, actor=who)
    db.commit()
    return row(i, exclude=("workspace_id",))


# Inspector, operations, audit, copilot ----------------------------------------------------------------


@router.get("/stack-inspector")
def inspector(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    return stack_inspector.inspect(db, ws.id)


@router.get("/operations")
def ops_summary(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    return operations.summary(db, ws.id)


@router.get("/audit")
def audit_log(
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    actor_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
) -> dict[str, Any]:
    cond = [AuditEvent.workspace_id == ws.id]
    if entity_type:
        cond.append(AuditEvent.entity_type == entity_type)
    if entity_id:
        cond.append(AuditEvent.entity_id == parse_uuid(entity_id))
    if action:
        cond.append(AuditEvent.action.like(f"{action}%"))
    if actor_type:
        cond.append(AuditEvent.actor_type == actor_type)
    items = list(db.scalars(select(AuditEvent).where(*cond).order_by(AuditEvent.occurred_at.desc()).limit(limit)))
    actions = dict(
        db.execute(
            select(AuditEvent.action, func.count()).where(AuditEvent.workspace_id == ws.id).group_by(AuditEvent.action)
        )
        .tuples()
        .all()
    )
    return {"items": [row(e, exclude=("workspace_id",)) for e in items], "actions": actions}


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@router.post("/copilot/ask")
def copilot_ask(body: Ask, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    return copilot.answer(db, ws.id, body.question)


@router.get("/copilot/suggestions")
def copilot_suggestions() -> list[str]:
    return copilot.suggested_questions()
