"""Adversarial tests for the workflow engine: duplicate triggers, concurrency, crashes, bad definitions."""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from typing import Any

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from gtmos.domain.rules import Condition
from gtmos.domain.workflows import WorkflowDefinition, idempotency_key
from gtmos.models import Account, Activity, AuditEvent, Workflow, WorkflowRun, WorkflowStepRun
from gtmos.services import workflow_engine
from gtmos.services.common import utcnow

ACTOR = "hardening@example.com"


def _workflow(db: Session, ws: Any, key: str) -> Workflow:
    return db.scalars(select(Workflow).where(Workflow.workspace_id == ws.id, Workflow.key == key)).one()


def _queued_run(db: Session, wf: Workflow, account: Account, event_id: str | None = None) -> WorkflowRun:
    definition = WorkflowDefinition.model_validate(wf.definition)
    ctx = workflow_engine._context(account, {"manual": {"actor": ACTOR}})
    run = workflow_engine.create_run(
        db, wf, definition, account, event_id or f"hardening:{uuid.uuid4()}", "manual", ctx
    )
    assert run is not None
    return run


def _steps(db: Session, run: WorkflowRun) -> dict[str, WorkflowStepRun]:
    rows = db.scalars(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id).order_by(WorkflowStepRun.position)
    )
    return {s.step_key: s for s in rows}


def _tasks_for(db: Session, run: WorkflowRun) -> int:
    return db.scalar(select(func.count()).select_from(Activity).where(Activity.dedupe_key.like(f"task:{run.id}:%")))


def _counting(counter: Counter[str], name: str, out: dict[str, Any] | None = None) -> workflow_engine.ActionFn:
    def handler(db: Session, run: WorkflowRun, account: Account, params: dict[str, Any]) -> dict[str, Any]:
        counter[name] += 1
        return out or {"handled": name}

    return handler


def test_the_same_trigger_event_delivered_twice_produces_one_run_and_one_set_of_side_effects(db, ws, flagship):
    event_id = f"pql-{uuid.uuid4()}"
    payload = {"pql": {"event": "trace_volume_threshold"}}
    first = workflow_engine.emit_event(db, ws.id, "product.pql", event_id, flagship, payload)
    assert first, "a PQL on the flagship account must trigger at least one workflow"
    run = first[0]
    assert run.idempotency_key == idempotency_key("pql-to-ae", run.workflow_version, "product.pql", event_id)
    assert run.status == "succeeded"
    tasks_after_first = _tasks_for(db, run)
    assert tasks_after_first == 1

    second = workflow_engine.emit_event(db, ws.id, "product.pql", event_id, flagship, payload)

    assert second == [], "the re-delivered event must not create a second run"
    runs = db.scalar(
        select(func.count()).select_from(WorkflowRun).where(WorkflowRun.idempotency_key == run.idempotency_key)
    )
    assert runs == 1
    assert _tasks_for(db, run) == tasks_after_first


def test_two_workers_executing_the_same_run_do_not_duplicate_step_work(engine: Engine, monkeypatch):
    from gtmos.services.common import get_workspace

    started = threading.Barrier(2, timeout=30)
    calls = Counter[str]()
    lock = threading.Lock()

    def slow_task(db: Session, run: WorkflowRun, account: Account, params: dict[str, Any]) -> dict[str, Any]:
        with lock:
            calls[params["subject"]] += 1
        # Every invocation writes its own row, so a second worker shows up as an extra row rather than as
        # an integrity error from the handler's own read-then-write dedupe.
        db.add(
            Activity(
                workspace_id=account.workspace_id,
                account_id=account.id,
                type="task",
                occurred_at=utcnow(),
                subject=params["subject"],
                source="gtmos_workflow",
                dedupe_key=f"hardening:{run.id}:{uuid.uuid4()}",
            )
        )
        db.flush()
        threading.Event().wait(0.15)  # widen the window so both workers are inside the run at once
        return {"subject": params["subject"]}

    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "create_task", slow_task)

    with Session(engine) as setup:
        ws = get_workspace(setup)
        account = setup.scalars(
            select(Account).where(Account.workspace_id == ws.id, Account.is_flagship.is_(True))
        ).one()
        wf = Workflow(
            workspace_id=ws.id,
            key=f"hardening-concurrency-{uuid.uuid4().hex[:8]}",
            name="Hardening: concurrent execution",
            trigger_type="manual",
            definition={
                "trigger": {"type": "manual", "filters": []},
                "conditions": [],
                "steps": [
                    {"key": "one", "action": "create_task", "params": {"subject": "one"}},
                    {"key": "two", "action": "create_task", "params": {"subject": "two"}},
                    {"key": "three", "action": "create_task", "params": {"subject": "three"}},
                ],
            },
        )
        setup.add(wf)
        setup.flush()
        run = _queued_run(setup, wf, account)
        run_id, workflow_id = run.id, wf.id
        setup.commit()

    outcomes: dict[int, Any] = {}

    def worker(index: int) -> None:
        try:
            with Session(engine) as s:
                started.wait()
                outcomes[index] = workflow_engine.execute_run(s, run_id).status
                s.commit()
        except BaseException as exc:  # a worker error is reported as a test failure below
            outcomes[index] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in (0, 1)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert not any(t.is_alive() for t in threads), "a worker deadlocked on the run"
        assert not any(isinstance(v, BaseException) for v in outcomes.values()), outcomes

        with Session(engine) as check:
            run = check.get(WorkflowRun, run_id)
            assert run is not None and run.status == "succeeded"
            assert calls == Counter({"one": 1, "two": 1, "three": 1}), (
                f"each step must run exactly once across both workers, got {dict(calls)}"
            )
            rows = check.scalar(
                select(func.count()).select_from(Activity).where(Activity.dedupe_key.like(f"hardening:{run_id}:%"))
            )
            assert rows == 3
            assert [s.attempts for s in _steps(check, run).values()] == [1, 1, 1]
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(delete(Activity).where(Activity.dedupe_key.like(f"hardening:{run_id}:%")))
            cleanup.execute(delete(AuditEvent).where(AuditEvent.entity_id == run_id))
            cleanup.execute(delete(Workflow).where(Workflow.id == workflow_id))
            cleanup.commit()


def test_a_worker_that_dies_mid_run_resumes_at_the_first_incomplete_step(db, ws, flagship, monkeypatch):
    calls = Counter[str]()
    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "route_account", _counting(calls, "route"))
    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "sync_crm", _counting(calls, "crm"))

    def killed(db_: Session, run: WorkflowRun, account: Account, params: dict[str, Any]) -> dict[str, Any]:
        calls["task"] += 1
        raise SystemExit("worker killed between steps (test)")

    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "create_task", killed)
    run = _queued_run(db, _workflow(db, ws, "score-threshold-routing"), flagship)

    with pytest.raises(SystemExit):
        workflow_engine.execute_run(db, run.id)

    steps = _steps(db, run)
    assert steps["route"].status == "succeeded"
    assert steps["task"].status == "pending", "the step that died must not be recorded as finished"
    assert run.status == "running", "a killed worker leaves the run non-terminal; nothing marks it done"

    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "create_task", _counting(calls, "task_ok"))
    resumed = workflow_engine.execute_run(db, run.id)

    assert resumed.status == "succeeded"
    assert calls["route"] == 1, "a step that already succeeded must not run again on resume"
    assert calls["task_ok"] == 1 and calls["crm"] == 1
    steps = _steps(db, run)
    assert steps["route"].attempts == 1
    assert all(s.status == "succeeded" for s in steps.values())


def test_replaying_a_succeeded_run_does_nothing(db, ws, flagship, monkeypatch):
    calls = Counter[str]()
    for action in ("route_account", "sync_crm"):
        monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, action, _counting(calls, action))
    wf = _workflow(db, ws, "score-threshold-routing")
    run = workflow_engine.run_manual(db, wf, flagship, ACTOR)
    assert run is not None and run.status == "succeeded"
    tasks, before = _tasks_for(db, run), dict(calls)
    finished_at = run.finished_at

    replayed = workflow_engine.execute_run(db, run.id)

    assert replayed.status == "succeeded" and replayed.finished_at == finished_at
    assert dict(calls) == before, "replaying a succeeded run must not call any action again"
    assert _tasks_for(db, run) == tasks
    assert all(s.attempts == 1 for s in _steps(db, run).values())


def test_a_permanent_step_failure_fails_the_run_and_skips_everything_downstream(db, ws, flagship, monkeypatch):
    calls = Counter[str]()

    def broken(db_: Session, run: WorkflowRun, account: Account, params: dict[str, Any]) -> dict[str, Any]:
        calls["route"] += 1
        raise ValueError("routing table is corrupt (test)")

    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "route_account", broken)
    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "sync_crm", _counting(calls, "crm"))
    run = _queued_run(db, _workflow(db, ws, "score-threshold-routing"), flagship)

    workflow_engine.execute_run(db, run.id)

    assert run.status == "failed"
    assert run.error == "step 'route': ValueError: routing table is corrupt (test)"
    steps = _steps(db, run)
    assert steps["route"].status == "failed" and steps["route"].attempts == 1
    assert calls["route"] == 1, "a non-transient error must not be retried"
    for key in ("task", "crm"):
        assert steps[key].status == "skipped", f"{key} must be skipped, never silently succeeded"
        assert steps[key].output["reason"] == "upstream step 'route' failed"
        assert steps[key].attempts == 0
    assert calls["crm"] == 0
    assert _tasks_for(db, run) == 0


def test_transient_errors_retry_with_backoff_then_dead_letter_and_survive_a_manual_retry(db, ws, flagship, monkeypatch):
    calls = Counter[str]()
    waits: list[float] = []

    def flaky(db_: Session, run: WorkflowRun, account: Account, params: dict[str, Any]) -> dict[str, Any]:
        calls["crm"] += 1
        raise workflow_engine.TransientError("503 from CRM (test)")

    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "sync_crm", flaky)
    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "route_account", _counting(calls, "route"))
    run = _queued_run(db, _workflow(db, ws, "score-threshold-routing"), flagship)

    workflow_engine.execute_run(db, run.id, sleep=waits.append)

    crm = _steps(db, run)["crm"]
    assert run.status == "dead_letter"
    assert calls["crm"] == crm.attempts == crm.max_attempts == 3
    assert waits == [2.0, 8.0], "backoff must grow between attempts and not sleep after the last one"
    assert crm.error.startswith("retries exhausted")
    assert sum(1 for entry in crm.logs if entry["level"] == "warn") == 3
    task_id = _steps(db, run)["task"].output["task_id"]
    assert _tasks_for(db, run) == 1

    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "sync_crm", _counting(calls, "crm_ok"))
    workflow_engine.retry_run(db, run)

    assert run.status == "succeeded" and run.attempt == 2 and run.error is None
    steps = _steps(db, run)
    assert steps["route"].attempts == 1 and calls["route"] == 1, "succeeded steps keep their state across a retry"
    assert steps["task"].output["task_id"] == task_id and _tasks_for(db, run) == 1
    assert steps["crm"].attempts == 1 and steps["crm"].status == "succeeded"


def test_retrying_a_run_that_is_not_failed_is_rejected(db, ws, flagship, monkeypatch):
    for action in ("route_account", "sync_crm"):
        monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, action, _counting(Counter[str](), action))
    run = workflow_engine.run_manual(db, _workflow(db, ws, "score-threshold-routing"), flagship, ACTOR)
    assert run is not None and run.status == "succeeded"
    with pytest.raises(ValueError, match="only failed or dead-lettered runs"):
        workflow_engine.retry_run(db, run)


def test_a_step_whose_action_has_no_handler_fails_the_run_with_a_useful_error(db, ws, flagship, monkeypatch):
    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "route_account", _counting(Counter[str](), "route"))
    run = _queued_run(db, _workflow(db, ws, "score-threshold-routing"), flagship)
    steps = _steps(db, run)
    steps["task"].action = "teleport_account"  # the definition validator cannot catch a row edited later
    db.flush()

    workflow_engine.execute_run(db, run.id)

    assert run.status == "failed"
    assert "no handler for action 'teleport_account'" in run.error
    steps = _steps(db, run)
    assert steps["route"].status == "succeeded"
    assert steps["task"].status == "failed"
    assert steps["crm"].status == "skipped"


def test_a_workflow_definition_that_stops_validating_fails_the_run_instead_of_crashing_the_worker(
    db, ws, flagship, monkeypatch
):
    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "route_account", _counting(Counter[str](), "route"))
    wf = _workflow(db, ws, "score-threshold-routing")
    run = _queued_run(db, wf, flagship)
    wf.definition = {
        **wf.definition,
        "conditions": [{"field": "account.icp_score", "op": "approximately", "value": 80}],
    }
    db.flush()

    executed = workflow_engine.execute_run(db, run.id)

    assert executed.status == "failed"
    assert "invalid workflow definition" in (run.error or "")
    assert run.finished_at is not None
    assert all(s.status == "skipped" for s in _steps(db, run).values())
    assert _tasks_for(db, run) == 0


def test_one_unparseable_workflow_does_not_block_the_others_from_seeing_the_event(db, ws, flagship, monkeypatch):
    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "sync_crm", _counting(Counter[str](), "crm"))
    broken = _workflow(db, ws, "score-threshold-routing")
    broken.definition = {**broken.definition, "steps": [{"key": "route", "action": "summon_a_wizard"}]}
    db.flush()

    runs = workflow_engine.emit_event(
        db, ws.id, "score.threshold_crossed", f"cross-{uuid.uuid4()}", flagship, {"event": {"threshold": 80}}
    )

    assert all(run.workflow_id != broken.id for run in runs)
    assert all(run.status in ("succeeded", "skipped") for run in runs)


def test_a_condition_on_a_missing_field_skips_the_run_with_a_reason(db, ws, flagship):
    wf = _workflow(db, ws, "funding-signal-to-outreach")
    definition = WorkflowDefinition.model_validate(wf.definition)
    definition.conditions.append(Condition(field="signal.arr_impact", op="gte", value=10))
    ctx = workflow_engine._context(flagship, {"manual": {"actor": ACTOR}})

    run = workflow_engine.create_run(db, wf, definition, flagship, f"missing-{uuid.uuid4()}", "manual", ctx)

    assert run is not None and run.status == "skipped"
    assert "signal.arr_impact" in (run.error or "")
    assert all(s.status == "skipped" for s in _steps(db, run).values())
    assert workflow_engine.execute_run(db, run.id).status == "skipped"


def test_a_step_failing_inside_its_savepoint_keeps_the_work_of_earlier_steps(db, ws, flagship, monkeypatch):
    def writes_then_succeeds(
        db_: Session, run: WorkflowRun, account: Account, params: dict[str, Any]
    ) -> dict[str, Any]:
        db_.add(
            Activity(
                workspace_id=account.workspace_id,
                account_id=account.id,
                type="note",
                occurred_at=utcnow(),
                subject="committed by the first step",
                source="gtmos_workflow",
                dedupe_key=f"savepoint-ok:{run.id}",
            )
        )
        db_.flush()
        return {"wrote": "note"}

    def writes_then_fails(db_: Session, run: WorkflowRun, account: Account, params: dict[str, Any]) -> dict[str, Any]:
        db_.add(
            Activity(
                workspace_id=account.workspace_id,
                account_id=account.id,
                type="note",
                occurred_at=utcnow(),
                subject="written by the failing step",
                source="gtmos_workflow",
                dedupe_key=f"savepoint-rolled-back:{run.id}",
            )
        )
        db_.flush()
        raise RuntimeError("blew up after writing (test)")

    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "route_account", writes_then_succeeds)
    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "create_task", writes_then_fails)
    run = _queued_run(db, _workflow(db, ws, "score-threshold-routing"), flagship)

    workflow_engine.execute_run(db, run.id)

    assert run.status == "failed"
    kept = db.scalars(select(Activity).where(Activity.dedupe_key == f"savepoint-ok:{run.id}")).one_or_none()
    rolled_back = db.scalars(
        select(Activity).where(Activity.dedupe_key == f"savepoint-rolled-back:{run.id}")
    ).one_or_none()
    assert kept is not None, "an earlier step's committed work must survive a later step's failure"
    assert rolled_back is None, "the failing step's own writes must roll back to its savepoint"
    assert _steps(db, run)["route"].status == "succeeded"
