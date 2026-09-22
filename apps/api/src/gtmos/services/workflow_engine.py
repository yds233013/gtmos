"""Workflow engine: TRIGGER → CONDITIONS → ACTIONS with persisted, idempotent, retryable runs.

Guarantees
* Idempotency: one run per (workflow version, trigger event), enforced by a unique key in Postgres.
  A re-delivered webhook or a double click cannot run a workflow twice.
* Resumability: every step's state is persisted. Retrying a failed run skips steps that already
  succeeded and resumes at the failed step.
* Retries: steps raising TransientError are retried up to `max_attempts`; exhausting retries moves the
  run to `dead_letter`, which the Operations page surfaces for manual retry.
* Side effects inside actions are themselves idempotent (tasks are keyed by run+step, CRM writes are
  upserts on a unique key, drafts are created once per run).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gtmos.config import get_settings
from gtmos.domain.pipeline import check_funnel_transition
from gtmos.domain.rules import evaluate_all
from gtmos.domain.workflows import WorkflowDefinition, backoff_seconds, idempotency_key
from gtmos.models import Account, Activity, MessageDraft, Workflow, WorkflowRun, WorkflowStepRun
from gtmos.services.common import audit, correlation_id, utcnow

log = logging.getLogger(__name__)


class TransientError(Exception):
    """Retryable failure (rate limit, timeout, upstream 5xx)."""


class StepSkipped(Exception):
    """The step had nothing to do (e.g. no eligible contact); not a failure."""


ActionFn = Callable[[Session, WorkflowRun, Account, dict[str, Any]], dict[str, Any]]


# --------------------------------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------------------------------


def _enrich(db: Session, run: WorkflowRun, a: Account, params: dict[str, Any]) -> dict[str, Any]:
    from gtmos.services.enrichment_service import enrich_account

    r = enrich_account(db, a, trigger=f"workflow:{run.id}")
    if r.status == "failed" and not a.domain:
        raise StepSkipped("account has no domain to enrich on")
    return {
        "enrichment_run_id": str(r.id),
        "status": r.status,
        "fields_changed": r.fields_changed,
        "cost_credits": r.total_cost_credits,
        "simulated": r.is_simulated,
    }


def _rescore(db: Session, run: WorkflowRun, a: Account, params: dict[str, Any]) -> dict[str, Any]:
    from gtmos.services.scoring_service import rescore_accounts

    before = a.icp_score
    rescore_accounts(db, a.workspace_id, [a.id], trigger=f"workflow:{run.id}")
    return {"score_before": before, "score_after": a.icp_score, "grade": a.score_grade}


def _committee(db: Session, run: WorkflowRun, a: Account, params: dict[str, Any]) -> dict[str, Any]:
    from gtmos.services.committee_service import recompute_committee

    roles = [r for r in recompute_committee(db, a) if r.rank == 1]
    return {"roles_filled": sorted(r.role for r in roles)}


def _research(db: Session, run: WorkflowRun, a: Account, params: dict[str, Any]) -> dict[str, Any]:
    from gtmos.services.research_service import generate_research

    r = generate_research(db, a, actor="workflow")
    return {"report_id": str(r.id), "generator": r.generator, "unsupported_claims_removed": len(r.unsupported_claims)}


def _draft(db: Session, run: WorkflowRun, a: Account, params: dict[str, Any]) -> dict[str, Any]:
    from gtmos.services.outreach_service import draft_outreach, pick_recipient

    existing = list(db.scalars(select(MessageDraft).where(MessageDraft.workflow_run_id == run.id)))
    if existing:
        return {"draft_ids": [str(d.id) for d in existing], "reused": True}
    contact = pick_recipient(db, a)
    if contact is None:
        raise StepSkipped("no reachable champion/buyer on the account")
    drafts = draft_outreach(
        db,
        a,
        contact,
        channels=[params.get("channel", "email"), "call_prep"],
        actor="workflow",
        initial_status="review",
        workflow_run_id=run.id,
    )
    return {"draft_ids": [str(d.id) for d in drafts], "contact": contact.full_name, "status": "review (approval queue)"}


def _route(db: Session, run: WorkflowRun, a: Account, params: dict[str, Any]) -> dict[str, Any]:
    from gtmos.models import User
    from gtmos.services.routing_service import route_account

    observed = run.trigger_event.get("signal", {}).get("observed_at")
    d = route_account(
        db, a, trigger=f"workflow:{run.id}", signal_observed_at=datetime.fromisoformat(observed) if observed else None
    )
    owner = db.get(User, d.assigned_user_id) if d.assigned_user_id else None
    return {
        "decision_id": str(d.id),
        "outcome": d.outcome,
        "owner": owner.name if owner else None,
        "conflicts": len(d.conflicts),
    }


def _task(db: Session, run: WorkflowRun, a: Account, params: dict[str, Any]) -> dict[str, Any]:
    key = f"task:{run.id}:{params.get('subject', 'follow-up')}"[:200]
    existing = db.scalars(select(Activity).where(Activity.dedupe_key == key)).first()
    if existing:
        return {"task_id": str(existing.id), "reused": True}
    t = Activity(
        workspace_id=a.workspace_id,
        account_id=a.id,
        user_id=a.owner_id,
        type="task",
        channel=None,
        occurred_at=utcnow(),
        subject=params.get("subject", "Follow up"),
        status="open",
        summary=f"Created by workflow run {run.id}",
        source="gtmos_workflow",
        data_origin=run.data_origin,
        dedupe_key=key,
    )
    db.add(t)
    db.flush()
    return {"task_id": str(t.id), "owner_id": str(a.owner_id) if a.owner_id else None}


def _lifecycle(db: Session, run: WorkflowRun, a: Account, params: dict[str, Any]) -> dict[str, Any]:
    from gtmos.services.crm_service import change_funnel_stage

    target = params.get("stage", "engaged")
    chk = check_funnel_transition(a.funnel_stage, target)
    if not chk.allowed:
        raise StepSkipped(f"lifecycle unchanged: {chk.reason}")
    before = a.funnel_stage
    change_funnel_stage(db, a, target, actor="workflow", reason=f"workflow run {run.id}")
    return {"from": before, "to": target, "lifecycle": a.lifecycle_stage}


def _notify(db: Session, run: WorkflowRun, a: Account, params: dict[str, Any]) -> dict[str, Any]:
    key = f"notify:{run.id}"
    if db.scalars(select(Activity).where(Activity.dedupe_key == key)).first() is None:
        db.add(
            Activity(
                workspace_id=a.workspace_id,
                account_id=a.id,
                user_id=a.owner_id,
                type="notification",
                occurred_at=utcnow(),
                subject="Owner notified (internal only; no external message sent)",
                source="gtmos_workflow",
                data_origin=run.data_origin,
                dedupe_key=key,
            )
        )
    return {"notified_user_id": str(a.owner_id) if a.owner_id else None, "channel": "in-app (recorded)"}


def _sync(db: Session, run: WorkflowRun, a: Account, params: dict[str, Any]) -> dict[str, Any]:
    from gtmos.services.crm_sync import run_company_sync

    s = run_company_sync(db, a.workspace_id, [a.id], job="workflow_crm_upsert", trigger=f"workflow:{run.id}")
    if s.status == "failed" and any(e.get("retryable") for e in s.errors):
        raise TransientError(f"CRM upsert failed: {s.errors[0].get('error')}")
    if s.status == "failed":
        raise RuntimeError(f"CRM upsert failed permanently: {s.errors[0].get('error') if s.errors else ''}")
    return {
        "sync_id": str(s.id),
        "status": s.status,
        "simulated": s.is_simulated,
        "skipped_unchanged": s.records_skipped,
    }


ACTION_HANDLERS: dict[str, ActionFn] = {
    "enrich_account": _enrich,
    "recalculate_score": _rescore,
    "identify_buying_committee": _committee,
    "generate_research": _research,
    "draft_outreach": _draft,
    "route_account": _route,
    "create_task": _task,
    "update_lifecycle": _lifecycle,
    "notify_owner": _notify,
    "sync_crm": _sync,
}


# --------------------------------------------------------------------------------------------------
# Triggering
# --------------------------------------------------------------------------------------------------


def _context(account: Account, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        "account": {
            "id": str(account.id),
            "name": account.name,
            "icp_score": account.icp_score,
            "score_grade": account.score_grade,
            "intent_score": account.intent_score,
            "segment": account.segment,
            "region": account.region,
            "is_customer": account.is_customer,
            "funnel_stage": account.funnel_stage,
            "owner_id": str(account.owner_id) if account.owner_id else None,
        },
    }


def emit_event(
    db: Session,
    workspace_id: uuid.UUID,
    trigger_type: str,
    event_id: str,
    account: Account,
    payload: dict[str, Any],
    *,
    execute: bool = True,
    data_origin: str = "live",
) -> list[WorkflowRun]:
    workflows = list(
        db.scalars(
            select(Workflow).where(
                Workflow.workspace_id == workspace_id,
                Workflow.trigger_type == trigger_type,
                Workflow.is_enabled.is_(True),
            )
        )
    )
    ctx = _context(account, payload)
    runs: list[WorkflowRun] = []
    for wf in workflows:
        definition = WorkflowDefinition.model_validate(wf.definition)
        ok, _ = evaluate_all(definition.trigger.filters, ctx)
        if not ok:
            continue
        run = create_run(db, wf, definition, account, event_id, trigger_type, ctx, data_origin)
        if run is not None:
            runs.append(run)
    if execute:
        for run in runs:
            if run.status == "queued":
                dispatch(db, run)
    return runs


def create_run(
    db: Session,
    wf: Workflow,
    definition: WorkflowDefinition,
    account: Account,
    event_id: str,
    trigger_type: str,
    ctx: dict[str, Any],
    data_origin: str = "live",
    created_at: datetime | None = None,
) -> WorkflowRun | None:
    key = idempotency_key(wf.key, wf.version, trigger_type, event_id)
    if db.scalars(select(WorkflowRun.id).where(WorkflowRun.idempotency_key == key)).first():
        return None
    passed, results = evaluate_all(definition.conditions, ctx)
    run = WorkflowRun(
        workspace_id=wf.workspace_id,
        workflow_id=wf.id,
        workflow_version=wf.version,
        account_id=account.id,
        trigger_event={k: v for k, v in ctx.items() if k != "account"} | {"type": trigger_type, "event_id": event_id},
        idempotency_key=key,
        correlation_id=correlation_id(),
        status="queued" if passed else "skipped",
        condition_results=results,
        created_at=created_at or utcnow(),
        data_origin=data_origin,
    )
    if not passed:
        run.finished_at = run.created_at
        run.error = "Conditions not met: " + "; ".join(r["condition"] for r in results if not r["passed"])
    try:
        with db.begin_nested():
            db.add(run)
            db.flush()
    except IntegrityError:
        return None  # concurrent duplicate delivery lost the race: idempotency held
    for i, step in enumerate(definition.steps):
        db.add(
            WorkflowStepRun(
                run_id=run.id,
                step_key=step.key,
                position=i,
                action=step.action,
                status="pending" if passed else "skipped",
                max_attempts=step.max_attempts,
                input=step.params,
            )
        )
    db.flush()
    return run


# --------------------------------------------------------------------------------------------------
# Dispatch & execution
# --------------------------------------------------------------------------------------------------


def dispatch(db: Session, run: WorkflowRun) -> None:
    settings = get_settings()
    if settings.queue_backend == "redis" and settings.redis_url:
        pending: list[str] = db.info.setdefault("gtmos_pending_runs", [])
        pending.append(str(run.id))  # enqueued after the transaction commits (see listener below)
        return
    execute_run(db, run.id)


@event.listens_for(Session, "after_commit")
def _enqueue_after_commit(session: Session) -> None:
    pending = session.info.pop("gtmos_pending_runs", None)
    if not pending:
        return
    from gtmos.worker import enqueue_run

    for run_id in pending:
        try:
            enqueue_run(run_id)
        except Exception:  # queue down: run stays 'queued' and is picked up by the sweeper
            log.exception("failed to enqueue workflow run %s", run_id)


def execute_run(db: Session, run_id: uuid.UUID, *, sleep: Callable[[float], None] | None = None) -> WorkflowRun:
    run = db.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    if run.status in ("succeeded", "skipped"):
        return run
    wf = db.get(Workflow, run.workflow_id)
    account = db.get(Account, run.account_id) if run.account_id else None
    if wf is None or account is None:
        run.status = "failed"
        run.error = "workflow or account no longer exists"
        return run
    steps = list(
        db.scalars(select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id).order_by(WorkflowStepRun.position))
    )
    definition = {s.key: s for s in WorkflowDefinition.model_validate(wf.definition).steps}
    run.status = "running"
    run.started_at = run.started_at or utcnow()
    db.flush()

    final_status = "succeeded"
    for step in steps:
        if step.status in ("succeeded", "skipped"):
            continue
        spec = definition.get(step.step_key)
        handler = ACTION_HANDLERS.get(step.action)
        step.started_at = utcnow()
        t0 = time.perf_counter()
        logs = list(step.logs or [])
        while True:
            step.attempts += 1
            try:
                with db.begin_nested():
                    if handler is None:
                        raise RuntimeError(f"no handler for action '{step.action}'")
                    step.output = handler(db, run, account, dict(step.input or {}))
                step.status = "succeeded"
                step.error = None
                logs.append({"at": utcnow().isoformat(), "level": "info", "msg": f"attempt {step.attempts}: succeeded"})
                break
            except StepSkipped as exc:
                step.status = "skipped"
                step.output = {"reason": str(exc)}
                logs.append({"at": utcnow().isoformat(), "level": "info", "msg": f"skipped: {exc}"})
                break
            except TransientError as exc:
                logs.append(
                    {
                        "at": utcnow().isoformat(),
                        "level": "warn",
                        "msg": f"attempt {step.attempts}: transient error: {exc}",
                    }
                )
                if step.attempts >= step.max_attempts:
                    step.status = "failed"
                    step.error = f"retries exhausted: {exc}"
                    break
                wait = backoff_seconds(step.attempts)
                logs.append({"at": utcnow().isoformat(), "level": "info", "msg": f"retrying in {wait:.0f}s"})
                if sleep:
                    sleep(min(wait, 2.0))
            except Exception as exc:  # permanent failure; captured, never crashes the worker
                log.exception("workflow step failed run=%s step=%s", run.id, step.step_key)
                step.status = "failed"
                step.error = f"{exc.__class__.__name__}: {exc}"
                logs.append({"at": utcnow().isoformat(), "level": "error", "msg": step.error})
                break
        step.logs = logs
        step.finished_at = utcnow()
        step.duration_ms = int((time.perf_counter() - t0) * 1000)
        db.flush()
        if step.status == "failed":
            if spec and spec.continue_on_failure:
                final_status = "failed"
                continue
            exhausted = (step.error or "").startswith("retries exhausted")
            final_status = "dead_letter" if exhausted else "failed"
            for later in steps:
                if later.position > step.position and later.status == "pending":
                    later.status = "skipped"
                    later.output = {"reason": f"upstream step '{step.step_key}' failed"}
            run.error = f"step '{step.step_key}': {step.error}"
            break

    run.status = final_status
    run.finished_at = utcnow()
    if final_status == "succeeded":
        run.error = None
    audit(
        db,
        run.workspace_id,
        f"workflow.run_{final_status}",
        "workflow_run",
        run.id,
        after={"workflow": wf.key, "account_id": str(account.id), "status": final_status},
        reason=run.error,
        actor_type="workflow",
        actor=wf.key,
    )
    db.flush()
    return run


def retry_run(db: Session, run: WorkflowRun) -> WorkflowRun:
    if run.status not in ("failed", "dead_letter"):
        raise ValueError(f"only failed or dead-lettered runs can be retried (status={run.status})")
    for step in db.scalars(select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)):
        if step.status in ("failed",) or (
            step.status == "skipped" and (step.output or {}).get("reason", "").startswith("upstream")
        ):
            step.status = "pending"
            step.attempts = 0
            step.error = None
    run.attempt += 1
    run.status = "queued"
    run.error = None
    audit(db, run.workspace_id, "workflow.run_retried", "workflow_run", run.id, after={"attempt": run.attempt})
    db.flush()
    dispatch(db, run)
    return run


def run_manual(db: Session, wf: Workflow, account: Account, actor: str) -> WorkflowRun | None:
    event_id = f"manual:{account.id}:{utcnow().isoformat()}"
    definition = WorkflowDefinition.model_validate(wf.definition)
    ctx = _context(account, {"manual": {"actor": actor}})
    run = create_run(db, wf, definition, account, event_id, "manual", ctx)
    if run and run.status == "queued":
        dispatch(db, run)
    return run
