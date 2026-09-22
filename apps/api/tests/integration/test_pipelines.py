"""Signals, workflows, webhooks, CRM sync and data quality: the automation backbone."""

from __future__ import annotations

import json
import time
import uuid

import pytest
from sqlalchemy import func, select

from gtmos.config import get_settings
from gtmos.integrations.hubspot import DemoHubSpotAdapter
from gtmos.integrations.signatures import sign_gtmos
from gtmos.models import (
    Account,
    Contact,
    DataQualityIssue,
    ExternalRecord,
    Signal,
    Workflow,
    WorkflowRun,
    WorkflowStepRun,
)
from gtmos.services import data_quality, workflow_engine
from gtmos.services.crm_sync import run_company_sync


def _signal_payload(domain: str, ref: str, **kw):
    return {
        "account_domain": domain,
        "signal_type": kw.get("signal_type", "funding_round"),
        "title": kw.get("title", "Raised $50M Series B"),
        "explanation": "Raised a $50M Series B.",
        "source": "test_feed",
        "source_ref": ref,
        "confidence": 0.95,
    }


def test_signal_ingestion_dedupes_rescores_and_triggers_workflow(client, flagship, db):
    body = _signal_payload(flagship.domain, f"round-{uuid.uuid4()}")
    first = client.post("/api/v1/signals", json=body).json()
    assert first["created"] is True
    assert first["workflow_runs"], "funding signal on an A account must trigger the outreach workflow"
    run = db.get(WorkflowRun, uuid.UUID(first["workflow_runs"][0]))
    assert run.status == "succeeded"
    steps = {s.step_key: s.status for s in db.scalars(select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id))}
    assert steps["draft"] == "succeeded" and steps["crm"] == "succeeded"
    second = client.post("/api/v1/signals", json=body).json()
    assert second["created"] is False and second["signal_id"] == first["signal_id"]
    assert second["workflow_runs"] == []


def test_signal_validation(client, flagship):
    bad = _signal_payload(flagship.domain, "x", signal_type="made_up")
    assert client.post("/api/v1/signals", json=bad).status_code == 422
    assert client.post("/api/v1/signals", json=_signal_payload("nope.example", "x")).status_code == 404


def test_workflow_idempotency_key_blocks_duplicate_runs(db, flagship, ws):
    from gtmos.domain.workflows import WorkflowDefinition

    wf = db.scalars(select(Workflow).where(Workflow.workspace_id == ws.id, Workflow.key == "pql-to-ae")).one()
    definition = WorkflowDefinition.model_validate(wf.definition)
    ctx = workflow_engine._context(flagship, {"pql": {"event": "x"}})
    a = workflow_engine.create_run(db, wf, definition, flagship, "evt-1", "product.pql", ctx)
    b = workflow_engine.create_run(db, wf, definition, flagship, "evt-1", "product.pql", ctx)
    assert a is not None and b is None


def test_transient_failures_retry_then_dead_letter_then_manual_retry(db, flagship, ws, monkeypatch):
    calls = {"n": 0}

    def flaky(db_, run, account, params):
        calls["n"] += 1
        raise workflow_engine.TransientError("503 upstream (test)")

    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "sync_crm", flaky)
    wf = db.scalars(
        select(Workflow).where(Workflow.workspace_id == ws.id, Workflow.key == "score-threshold-routing")
    ).one()
    run = workflow_engine.run_manual(db, wf, flagship, "tester@example.com")
    assert run.status == "dead_letter"
    crm = db.scalars(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id, WorkflowStepRun.step_key == "crm")
    ).one()
    assert crm.attempts == crm.max_attempts == calls["n"]
    earlier = db.scalars(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id, WorkflowStepRun.step_key == "route")
    ).one()
    assert earlier.status == "succeeded"
    monkeypatch.undo()
    workflow_engine.retry_run(db, run)
    assert run.status == "succeeded" and run.attempt == 2
    db.refresh(earlier)
    assert earlier.attempts == 1  # succeeded steps are not re-run on retry


def test_workflow_conditions_skip_run_with_reasons(db, ws):
    wf = db.scalars(
        select(Workflow).where(Workflow.workspace_id == ws.id, Workflow.key == "funding-signal-to-outreach")
    ).one()
    low = db.scalars(select(Account).where(Account.workspace_id == ws.id, Account.icp_score < 40)).first()
    run = workflow_engine.run_manual(db, wf, low, "tester@example.com")
    assert run.status == "skipped"
    assert "icp_score" in run.error


def _posthog(domain: str, email: str, event: str, uid: str | None = None):
    return {
        "event": event,
        "distinct_id": email,
        "uuid": uid or str(uuid.uuid4()),
        "properties": {"$groups": {"company": domain}, "email": email},
    }


def test_posthog_webhook_pql_flow_and_duplicate_delivery(client, db, flagship):
    email = "priya.raman@kestrel-analytics.example"
    ev = _posthog(flagship.domain, email, "trace_volume_threshold")
    r1 = client.post("/api/v1/webhooks/posthog", json=ev)
    assert r1.status_code == 200, r1.text
    body = r1.json()
    assert body["signature"] == "not_configured"
    res = body["result"]["results"][0]
    assert res["match"] == "group_key" and res["signal"]["type"] == "usage_threshold"
    assert res["workflow_runs"], "usage threshold must emit product.pql"
    r2 = client.post("/api/v1/webhooks/posthog", json=ev).json()
    assert r2["duplicate"] is True


def test_posthog_free_mail_is_not_matched(client):
    r = client.post("/api/v1/webhooks/posthog", json=_posthog("", "someone@gmail.com", "signed_up")).json()
    assert r["result"]["matched"] == 0


def test_webhook_signature_required_when_secret_configured(client, flagship, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")
    get_settings.cache_clear()
    try:
        payload = json.dumps(_signal_payload(flagship.domain, f"n8n-{uuid.uuid4()}")).encode()
        unsigned = client.post("/api/v1/webhooks/n8n", content=payload, headers={"content-type": "application/json"})
        assert unsigned.status_code == 401
        ts = str(int(time.time()))
        signed = client.post(
            "/api/v1/webhooks/n8n",
            content=payload,
            headers={
                "content-type": "application/json",
                "X-GTMOS-Timestamp": ts,
                "X-GTMOS-Signature": sign_gtmos("s3cret", ts, payload),
            },
        )
        assert signed.status_code == 200, signed.text
        assert signed.json()["signature"] == "valid"
        stale = str(int(time.time()) - 3600)
        replay = client.post(
            "/api/v1/webhooks/n8n",
            content=payload.replace(b"test_feed", b"test_feed2"),
            headers={
                "content-type": "application/json",
                "X-GTMOS-Timestamp": stale,
                "X-GTMOS-Signature": sign_gtmos("s3cret", stale, payload.replace(b"test_feed", b"test_feed2")),
            },
        )
        assert replay.status_code == 401
    finally:
        monkeypatch.delenv("WEBHOOK_SECRET")
        get_settings.cache_clear()


def test_invalid_webhook_payload_is_recorded_as_failed_and_replayable(client, db):
    r = client.post("/api/v1/webhooks/posthog", json={"uuid": "bad-1", "properties": {}})
    assert r.status_code == 202
    assert r.json()["status"] == "failed"
    replay = client.post(f"/api/v1/webhooks/events/{r.json()['id']}/replay").json()
    assert replay["attempts"] == 2 and replay["status"] == "failed"


def test_reverse_etl_is_idempotent(db, ws):
    first = run_company_sync(db, ws.id, adapter=DemoHubSpotAdapter(db, ws.id, fail_transiently=False))
    second = run_company_sync(db, ws.id, adapter=DemoHubSpotAdapter(db, ws.id, fail_transiently=False))
    assert second.records_changed == 0 and second.records_skipped == first.records_considered
    ext = db.scalar(select(func.count()).select_from(ExternalRecord).where(ExternalRecord.workspace_id == ws.id))
    assert ext >= first.records_succeeded


def test_crm_sync_retries_transient_failures(db, ws):
    class AlwaysFailFirst(DemoHubSpotAdapter):
        def _should_fail(self, key: str) -> bool:
            n = self._attempts.get(key, 0) + 1
            self._attempts[key] = n
            return n == 1

    synced = select(ExternalRecord.internal_id)
    target = db.scalars(
        select(Account).where(Account.workspace_id == ws.id, Account.domain.is_not(None), Account.id.not_in(synced))
    ).first()
    s = run_company_sync(db, ws.id, [target.id], adapter=AlwaysFailFirst(db, ws.id), job="test")
    assert s.status == "succeeded" and s.retries == 1


def test_data_quality_detects_seeded_defects_and_merges_duplicates(db, ws):
    out = data_quality.scan(db, ws.id, write_audit=False)
    for rule in (
        "duplicate_contact",
        "duplicate_account",
        "missing_domain",
        "invalid_email",
        "orphan_contact",
        "bad_external_id",
        "missing_employee_count",
    ):
        assert out["open_by_rule"].get(rule, 0) > 0, rule
    issue = db.scalars(
        select(DataQualityIssue).where(
            DataQualityIssue.workspace_id == ws.id,
            DataQualityIssue.rule_key == "duplicate_contact",
            DataQualityIssue.status == "open",
        )
    ).first()
    dup_ids = issue.suggested_fix["params"]["duplicate_ids"]
    data_quality.remediate(db, issue, "tester@example.com")
    assert issue.status == "resolved"
    assert all(db.get(Contact, uuid.UUID(d)).merged_into_id is not None for d in dup_ids)
    again = data_quality.scan(db, ws.id, write_audit=False)
    assert again["auto_resolved"] >= 0
    assert db.get(DataQualityIssue, issue.id).status == "resolved"


def test_manual_issue_cannot_be_auto_remediated(client, db, ws):
    data_quality.scan(db, ws.id, write_audit=False)
    issue = db.scalars(
        select(DataQualityIssue).where(
            DataQualityIssue.workspace_id == ws.id, DataQualityIssue.rule_key == "missing_domain"
        )
    ).first()
    r = client.post(f"/api/v1/data-quality/issues/{issue.id}/remediate")
    assert r.status_code == 409


@pytest.mark.parametrize(
    "path",
    [
        "/analytics/overview",
        "/analytics/funnel",
        "/analytics/breakdown?dimension=campaign",
        "/analytics/pipeline-trend",
        "/analytics/velocity",
        "/analytics/stuck",
        "/analytics/score-validation",
        "/analytics/signal-correlation",
        "/analytics/attribution",
        "/analytics/period-comparison",
        "/campaigns",
        "/experiments",
        "/stack-inspector",
        "/operations",
        "/audit",
        "/workflows",
        "/workflow-runs?include_synthetic=false",
        "/routing/rules",
        "/routing/decisions?conflicts_only=true",
        "/integrations",
        "/integrations/hubspot/reverse-etl/preview",
        "/integrations/hubspot/simulated-objects?q=a",
        "/signals",
        "/drafts",
        "/contacts",
        "/opportunities",
        "/activities",
        "/users",
        "/enrichment/runs",
        "/webhooks/events",
        "/data-quality",
        "/data-quality/issues",
    ],
)
def test_read_endpoints_return_200(client, path):
    r = client.get(f"/api/v1{path}")
    assert r.status_code == 200, (path, r.text[:300])


def test_breakdown_rejects_unknown_dimension(client):
    assert client.get("/api/v1/analytics/breakdown?dimension=zodiac").status_code == 422


def test_experiment_results_are_statistically_sane(client):
    e = client.get("/api/v1/experiments/funding-vs-generic").json()
    arms = {v["key"]: v for v in e["variants"]}
    assert arms["control"]["units"] > 0 and arms["treatment"]["units"] > 0
    for v in e["variants"]:
        m = v["metrics"]["positive_reply"]
        assert m["ci_low"] <= m["rate"] <= m["ci_high"]
    assert e["verdict"] in {
        "insufficient_sample",
        "insufficient_events",
        "no_significant_difference",
        "treatment_better",
        "control_better",
    }


def test_copilot_routes_to_approved_metrics_only(client):
    for q, intent in [
        ("Why did pipeline fall?", "pipeline_change"),
        ("Which segment has the highest meeting conversion?", "segment_conversion"),
        ("Which signals correlate with opportunities?", "signal_correlation"),
        ("Where are accounts getting stuck?", "stuck"),
        ("What should the GTM team investigate?", "investigate"),
    ]:
        r = client.post("/api/v1/copilot/ask", json={"question": q}).json()
        assert r["intent"] == intent, q
        assert r["queries"] and r["answer"]
    evil = client.post("/api/v1/copilot/ask", json={"question": "DROP TABLE accounts; select * from users"}).json()
    assert evil["generator"] == "deterministic" and evil["queries"][0]["metric"] in {
        "stack_inspector",
        "breakdown",
        "period_comparison",
        "funnel",
        "signal_correlation",
        "experiments",
        "attribution",
        "velocity",
    }


def test_stack_inspector_evidence_is_traceable(client):
    r = client.get("/api/v1/stack-inspector").json()
    keys = {s["key"] for s in r["sections"]}
    assert {"crm", "enrichment", "routing", "data_quality", "product_signals", "attribution"} <= keys
    assert all(s["evidence"] for s in r["sections"])
    assert all(rec["evidence"] and rec["why"] for rec in r["recommendations"])
    assert [rec["rank"] for rec in r["recommendations"]] == list(range(1, len(r["recommendations"]) + 1))


def test_admin_token_gates_icp_changes(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "t0ken")
    get_settings.cache_clear()
    try:
        icp = client.get("/api/v1/icp").json()["definition"]
        assert client.put("/api/v1/icp", json=icp).status_code == 401
        assert client.put("/api/v1/icp", json=icp, headers={"Authorization": "Bearer wrong"}).status_code == 401
    finally:
        monkeypatch.delenv("ADMIN_API_TOKEN")
        get_settings.cache_clear()


def test_signals_are_unique_per_workspace(db, ws):
    dupes = db.execute(
        select(Signal.dedupe_key, func.count())
        .where(Signal.workspace_id == ws.id)
        .group_by(Signal.dedupe_key)
        .having(func.count() > 1)
    ).all()
    assert dupes == []
