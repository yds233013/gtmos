"""The kill switch has to actually stop things.

A pause button that only changes a flag is worse than none: it tells an operator the bleeding has
stopped when it has not. Each switch is therefore tested by attempting the thing it is supposed to
prevent.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from gtmos.models import Account, AuditEvent, MessageDraft, Workflow, WorkflowRun
from gtmos.services import governance, workflow_engine
from gtmos.services.common import Conflict, utcnow
from gtmos.services.crm_sync import run_company_sync
from gtmos.services.outreach_service import transition


def test_the_default_state_is_everything_running(client):
    g = client.get("/api/v1/governance").json()
    assert all(s["enabled"] for s in g["switches"])
    assert g["any_paused"] is False and g["all_paused"] is False
    # Each switch says what it stops and when to reach for it, because an operator picking one during
    # an incident should not have to read the source.
    assert all(s["stops"] and s["use_when"] for s in g["switches"])


def test_pausing_automation_stops_workflows_from_firing(client, db, ws, flagship):
    before = db.scalar(select(func.count()).select_from(WorkflowRun).where(WorkflowRun.workspace_id == ws.id)) or 0
    governance.set_switch(db, ws, "automation_enabled", False, "ops@example.com", "runaway rule")
    db.flush()

    runs = workflow_engine.emit_event(
        db, ws.id, "signal.created", f"gov-{uuid.uuid4()}", flagship, {"signal": {"signal_type": "funding_round"}}
    )
    assert runs == [], "a paused workspace must not create workflow runs"
    after = db.scalar(select(func.count()).select_from(WorkflowRun).where(WorkflowRun.workspace_id == ws.id)) or 0
    assert after == before, "no run row should exist to drain when automation resumes"

    governance.resume_all(db, ws, "ops@example.com")
    db.flush()


def test_a_run_queued_before_the_pause_is_left_queued_not_failed(client, db, ws):
    """Pausing is not cancelling: resuming should pick up where it stopped."""
    wf = db.scalars(select(Workflow).where(Workflow.workspace_id == ws.id)).first()
    assert wf is not None
    run = WorkflowRun(
        workspace_id=ws.id,
        workflow_id=wf.id,
        workflow_version=wf.version,
        status="queued",
        idempotency_key=f"gov-{uuid.uuid4()}",
        trigger_event={"test": True},
        correlation_id=str(uuid.uuid4()),
        created_at=utcnow(),
    )
    db.add(run)
    db.flush()

    governance.set_switch(db, ws, "automation_enabled", False, "ops@example.com", "pause")
    db.flush()
    out = workflow_engine.execute_run(db, run.id)
    assert out.status == "queued", "a paused run must not be failed or marked skipped"
    assert out.error is None

    governance.resume_all(db, ws, "ops@example.com")
    db.flush()


def test_pausing_outbound_blocks_approval_but_not_fixing_the_message(client, db, ws):
    draft = db.scalars(select(MessageDraft).where(MessageDraft.workspace_id == ws.id)).first()
    assert draft is not None
    governance.set_switch(db, ws, "outbound_enabled", False, "ops@example.com", "bad list")
    db.flush()

    draft.status = "review"
    with pytest.raises(governance.Halted) as exc:
        transition(db, draft, "approved", "rep@example.com")
    assert "Outbound is paused" in str(exc.value)
    assert "bad list" in str(exc.value), "the operator's reason should reach whoever is blocked"

    # Rejecting must still work: pausing outbound should not stop the team fixing what caused it.
    transition(db, draft, "rejected", "rep@example.com", "needs a rewrite")
    assert draft.status == "rejected"

    governance.resume_all(db, ws, "ops@example.com")
    db.flush()


def test_pausing_crm_writes_stops_a_sync_before_it_opens_a_connection(client, db, ws):
    governance.set_switch(db, ws, "crm_writes_enabled", False, "ops@example.com", "sync corrupting records")
    db.flush()
    with pytest.raises(governance.Halted):
        run_company_sync(db, ws.id, job="reverse_etl_companies", trigger="test")
    governance.resume_all(db, ws, "ops@example.com")
    db.flush()


def test_the_api_refuses_a_blocked_action_with_423_rather_than_a_server_error(client, db, ws):
    draft = db.scalars(select(MessageDraft).where(MessageDraft.workspace_id == ws.id)).first()
    assert draft is not None
    draft.status = "review"
    db.commit()
    governance.set_switch(db, ws, "outbound_enabled", False, "ops@example.com", "paused for a fix")
    db.commit()
    try:
        r = client.post(f"/api/v1/drafts/{draft.id}/transition", json={"target": "approved"})
        assert r.status_code == 423, r.text
        assert "paused" in r.json()["error"].lower()
    finally:
        governance.resume_all(db, ws, "ops@example.com")
        db.commit()


def test_pause_all_records_who_and_why_and_resume_clears_it(client, db, ws):
    state = governance.pause_all(db, ws, "incident@example.com", "sequence sending to the wrong list")
    db.flush()
    assert state.all_paused
    assert state.paused_by == "incident@example.com"
    assert state.paused_reason == "sequence sending to the wrong list"
    assert state.paused_at is not None

    events = list(
        db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == ws.id, AuditEvent.action == "governance.paused"))
    )
    assert events, "a pause must be auditable: the first question afterwards is when and who"

    resumed = governance.resume_all(db, ws, "incident@example.com")
    db.flush()
    assert resumed.automation_enabled and resumed.outbound_enabled and resumed.crm_writes_enabled
    assert resumed.paused_at is None and resumed.paused_by is None and resumed.paused_reason is None


def test_switch_changes_are_admin_gated_when_a_token_is_configured(client, monkeypatch):
    from gtmos.config import get_settings

    monkeypatch.setenv("ADMIN_API_TOKEN", "t0ken")
    get_settings.cache_clear()
    try:
        assert client.post("/api/v1/governance/pause", json={"reason": "testing"}).status_code == 401
        ok = client.post(
            "/api/v1/governance/pause",
            json={"reason": "testing"},
            headers={"Authorization": "Bearer t0ken"},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["all_paused"] is True
        client.post("/api/v1/governance/resume", headers={"Authorization": "Bearer t0ken"})
    finally:
        monkeypatch.delenv("ADMIN_API_TOKEN")
        get_settings.cache_clear()


def test_the_switch_is_read_from_the_database_every_time(db, ws):
    """A cached flag would make a pause take effect whenever the cache happened to expire."""
    assert governance.is_enabled(db, ws.id, "automation_enabled") is True
    ws.automation_enabled = False
    db.flush()
    assert governance.is_enabled(db, ws.id, "automation_enabled") is False
    ws.automation_enabled = True
    db.flush()


def test_an_unknown_switch_is_rejected(db, ws):
    with pytest.raises(ValueError):
        governance.set_switch(db, ws, "send_everything", False, "ops@example.com")


def test_accounts_are_untouched_by_a_pause(db, ws):
    """The switch stops actions, not data. Pausing must not mutate the records themselves."""
    before = db.scalar(select(func.count()).select_from(Account).where(Account.workspace_id == ws.id))
    governance.pause_all(db, ws, "ops@example.com", "drill")
    db.flush()
    assert db.scalar(select(func.count()).select_from(Account).where(Account.workspace_id == ws.id)) == before
    governance.resume_all(db, ws, "ops@example.com")
    db.flush()


def test_conflict_and_halted_are_different_failures(db, ws):
    """A blocked-by-policy action is not the same as an invalid one, and the API must not conflate them."""
    assert not issubclass(governance.Halted, Conflict)
