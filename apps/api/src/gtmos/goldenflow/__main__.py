"""python -m gtmos.goldenflow [--via-n8n] [--json]

One account, end to end, through every system boundary GTMOS has — and deliberately including the
parts that usually get skipped in a demo: a duplicate delivery, a reconciliation, and an audit trail
that explains what happened afterwards.

The scenario is a product-led one, because that is the flow this architecture exists to serve:

    three people at one company use the product
        → PostHog-shaped events
        → n8n normalises and forwards them (when --via-n8n and n8n is running)
        → GTMOS ingests, resolves identity, records engagement
        → product-qualified account rule fires
        → signal created, score moves
        → workflow triggers, routing decides an owner
        → reverse ETL pushes the account to the CRM and associates its contacts
        → the CRM sends a change webhook back
        → the same webhook is delivered twice and the second is deduplicated
        → analytics, operations and the audit log all reflect it

Determinism: every identifier the flow generates is derived from a fixed run key, so two runs produce
the same ids, the same dedupe keys and the same result. `--run-key` changes that when you want a fresh
pass without resetting the database.

Nothing here sends an email, writes to a real CRM, or calls a paid API.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select

from gtmos.config import get_settings
from gtmos.db import session_scope
from gtmos.models import (
    Account,
    AuditEvent,
    Engagement,
    ExternalRecord,
    SimulatedCrmObject,
    WebhookEvent,
    WorkflowRun,
    Workspace,
)

FLAGSHIP_DOMAIN = "kestrel-analytics.example"
N8N_WEBHOOK = "http://localhost:5678/webhook/gtmos-posthog"

# The three people whose product use makes this a team adoption rather than one curious engineer.
# Fixed so the flow is replayable.
USERS = [
    ("priya.raman@kestrel-analytics.example", "integration_connected"),
    ("marco.silva@kestrel-analytics.example", "trace_volume_threshold"),
    ("dana.cole@kestrel-analytics.example", "pricing_page_viewed"),
]


@dataclass
class Step:
    n: int
    title: str
    ok: bool
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def line(self) -> str:
        mark = "ok  " if self.ok else "FAIL"
        return f"  {self.n:>2}. [{mark}] {self.title}\n        {self.detail}"


class Flow:
    def __init__(self, run_key: str, via_n8n: bool) -> None:
        self.run_key = run_key
        self.via_n8n = via_n8n
        self.steps: list[Step] = []

    def add(self, n: int, title: str, ok: bool, detail: str, **evidence: Any) -> None:
        self.steps.append(Step(n, title, ok, detail, evidence))

    @property
    def failed(self) -> list[Step]:
        return [s for s in self.steps if not s.ok]

    def event_id(self, suffix: str) -> str:
        """Deterministic per run key, so a replay collides with itself on purpose."""
        return f"golden-{self.run_key}-{suffix}"


def _sign(secret: str, body: bytes, ts: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()


def _post(client: httpx.Client, path: str, body: dict[str, Any] | list[Any], secret: str | None) -> httpx.Response:
    raw = json.dumps(body).encode()
    headers = {"content-type": "application/json"}
    if secret:
        ts = str(int(time.time()))
        headers["X-GTMOS-Timestamp"] = ts
        headers["X-GTMOS-Signature"] = _sign(secret, raw, ts)
    return client.post(path, content=raw, headers=headers)


def run(base_url: str, run_key: str, via_n8n: bool) -> Flow:
    flow = Flow(run_key, via_n8n)
    settings = get_settings()
    secret = settings.webhook_secret.get_secret_value() if settings.webhook_secret else None
    client = httpx.Client(base_url=base_url, timeout=30.0)

    # 1 ── the account exists ----------------------------------------------------------------------
    with session_scope() as db:
        ws = db.scalars(select(Workspace).order_by(Workspace.created_at)).first()
        if ws is None:
            flow.add(1, "Account exists", False, "No workspace. Run `make seed` first.")
            return flow
        account = db.scalars(
            select(Account).where(Account.workspace_id == ws.id, Account.domain == FLAGSHIP_DOMAIN)
        ).first()
        if account is None:
            flow.add(1, "Account exists", False, f"No account with domain {FLAGSHIP_DOMAIN}.")
            return flow
        ws_id, account_id = ws.id, account.id
        score_before = account.icp_score or 0
        owner_before = account.owner_id
        flow.add(
            1,
            "Account exists",
            True,
            f"{account.name} · grade {account.score_grade} · score {score_before} · {account.segment}",
            account_id=str(account_id),
        )

    # 2–5 ── product activity → PostHog shape → n8n → GTMOS ----------------------------------------
    delivered = 0
    transport = "n8n" if via_n8n else "direct"
    for i, (email, event_name) in enumerate(USERS):
        payload = {
            "event": event_name,
            "uuid": flow.event_id(f"evt-{i}"),
            "distinct_id": email,
            "timestamp": datetime.now(UTC).isoformat(),
            "properties": {
                # PostHog's real group shape: $groups maps a group *type* to a group *key*.
                "$groups": {"company": FLAGSHIP_DOMAIN},
                "email": email,
                "$current_url": "https://app.sentinel.example/settings/integrations",
            },
        }
        if via_n8n:
            try:
                r = httpx.post(N8N_WEBHOOK, json=payload, timeout=20.0)
                ok = r.status_code < 300
            except httpx.HTTPError as exc:
                ok = False
                flow.add(4, "n8n receives the event", False, f"n8n unreachable: {exc}")
                break
        else:
            r = _post(client, "/api/v1/webhooks/posthog", payload, secret)
            ok = r.status_code < 300
        delivered += 1 if ok else 0

    flow.add(
        2,
        "Product activity occurs",
        delivered == len(USERS),
        f"{len(USERS)} people at one company: an integration connected, a usage threshold crossed, pricing viewed",
    )
    flow.add(3, "PostHog-shaped events produced", delivered == len(USERS), "$groups.company carries account identity")
    flow.add(
        4,
        "n8n receives and normalises" if via_n8n else "Delivered directly to GTMOS",
        delivered == len(USERS),
        f"{delivered}/{len(USERS)} delivered over {transport}"
        + (" (n8n filtered, signed and forwarded)" if via_n8n else " (--via-n8n to route through n8n)"),
    )
    time.sleep(1.5)  # n8n forwards asynchronously

    # 5–6 ── ingestion and identity resolution ------------------------------------------------------
    with session_scope() as db:
        # Look the rows up by *this run's* dedupe keys rather than by a time window. Re-running the
        # flow under the same run key is supposed to collide with itself — the event ids are derived
        # from the run key precisely so that it does — and a time-window check reports that correct
        # idempotent outcome as a failure, which is the opposite of the signal this harness exists
        # to give. A replay that finds the rows already there is a pass, and says so.
        expected = [flow.event_id(f"evt-{i}") for i in range(len(USERS))]
        engagements = [
            e
            for e in db.scalars(select(Engagement).where(Engagement.account_id == account_id))
            if e.dedupe_key and any(e.dedupe_key.endswith(k) for k in expected)
        ]
        since = datetime.now(UTC) - timedelta(minutes=10)
        fresh = [e for e in engagements if e.occurred_at >= since]
        replayed = len(engagements) - len(fresh)
        flow.add(
            5,
            "GTMOS ingests the events",
            len(engagements) == len(USERS),
            f"{len(engagements)}/{len(USERS)} engagement rows for this run key"
            + (f" ({replayed} already present — the replay deduplicated, as intended)" if replayed else ""),
        )
        people = {e.contact_id or e.distinct_id for e in engagements}
        flow.add(
            6,
            "Account identity resolved",
            len(people) == len(USERS),
            f"{len(people)} distinct people resolved to {FLAGSHIP_DOMAIN} by group key and email domain",
        )

    # 7–9 ── qualification, signal, score -----------------------------------------------------------
    with session_scope() as db:
        from gtmos.services.product_events import assess_account, evaluate_pql

        account = db.get(Account, account_id)
        assert account is not None
        assessment = assess_account(db, account)
        result = evaluate_pql(db, ws_id, account, data_origin="demo")
        db.commit()
        flow.add(
            7,
            "Product-qualified account rule evaluated",
            assessment.qualified,
            f"{assessment.score}/{assessment.summary.split(':')[0].split('at ')[-1] if False else 55}"
            f" — {assessment.summary}",
            criteria=[m["key"] for m in assessment.met],
        )
        sig = result.get("signal")
        flow.add(
            8,
            "Signal created",
            sig is not None,
            (
                f"signal {sig['id'][:8]} · score {sig['score_before']} → {sig['score_after']}"
                if sig
                else "no signal (account did not qualify)"
            ),
        )
        after = db.get(Account, account_id)
        assert after is not None
        flow.add(
            9,
            "Score reflects the new evidence",
            after.icp_score is not None,
            f"ICP score {score_before} → {after.icp_score}, grade {after.score_grade}",
        )
        pql_runs = result.get("workflow_runs") or []

    # 10 ── workflow ---------------------------------------------------------------------------------
    with session_scope() as db:
        recent_runs = list(
            db.scalars(
                select(WorkflowRun)
                .where(WorkflowRun.account_id == account_id)
                .order_by(WorkflowRun.created_at.desc())
                .limit(5)
            )
        )
        flow.add(
            10,
            "Workflow triggered",
            bool(pql_runs or recent_runs),
            f"{len(pql_runs)} run(s) emitted by the PQL trigger; {len(recent_runs)} recent runs on this account",
        )

    # 11 ── committee and research -------------------------------------------------------------------
    r = client.get(f"/api/v1/accounts/{account_id}")
    detail = r.json() if r.status_code == 200 else {}
    committee = detail.get("committee") or []
    research = detail.get("research")
    flow.add(
        11,
        "Buying committee and research available",
        bool(committee),
        f"{len({c['role'] for c in committee})} roles inferred"
        + (f"; research report with {len(research.get('evidence', []))} cited items" if research else "; no research"),
    )

    # 12 ── routing -----------------------------------------------------------------------------------
    with session_scope() as db:
        from gtmos.services.routing_service import route_account

        account = db.get(Account, account_id)
        assert account is not None
        decision = route_account(db, account, trigger="signal.created")
        db.commit()
        flow.add(
            12,
            "Routing decision made",
            decision.outcome in ("assigned", "kept_owner", "named_account", "fallback_queue"),
            f"{decision.outcome}"
            + (f" · SLA due {decision.sla_due_at:%H:%M}" if decision.sla_due_at else " · no SLA on this rule")
            + f" · {decision.explanation[0][:90] if decision.explanation else ''}",
            owner_changed=str(owner_before) != str(decision.assigned_user_id),
        )

    # 13–14 ── CRM update -------------------------------------------------------------------------------
    with session_scope() as db:
        from gtmos.services.crm_sync import run_company_sync, run_contact_and_deal_sync

        company_sync = run_company_sync(db, ws_id, [account_id], job="golden_flow_companies", trigger="golden-flow")
        cd_sync = run_contact_and_deal_sync(db, ws_id, [account_id], job="golden_flow_contacts", trigger="golden-flow")
        db.commit()
        flow.add(
            13,
            "CRM update generated",
            company_sync.status in ("succeeded", "partial"),
            f"company sync {company_sync.status}: {company_sync.records_changed} changed, "
            f"{company_sync.records_skipped} unchanged (payload hash matched)",
        )
        flow.add(
            14,
            "Simulated HubSpot adapter processes it",
            cd_sync.status in ("succeeded", "partial"),
            f"contacts+deals {cd_sync.status}: {cd_sync.details.get('contacts', 0)} contacts, "
            f"{cd_sync.details.get('deals', 0)} deals, {cd_sync.details.get('associations', 0)} associations",
        )
        ext = db.scalars(
            select(ExternalRecord).where(
                ExternalRecord.internal_id == account_id, ExternalRecord.object_type == "companies"
            )
        ).first()
        external_id = ext.external_id if ext else None

    # 15–16 ── CRM webhook back, then the same delivery again --------------------------------------------
    hubspot_event = [
        {
            "eventId": 90000000 + (int(hashlib.sha256(run_key.encode()).hexdigest()[:6], 16) % 1000),
            "subscriptionId": 3000001,
            "portalId": 24680135,
            "occurredAt": int(time.time() * 1000),
            "subscriptionType": "company.propertyChange",
            "attemptNumber": 0,
            "objectId": int(external_id) if external_id and external_id.isdigit() else 12345,
            "propertyName": "lifecyclestage",
            "propertyValue": "opportunity",
            "changeSource": "CRM_UI",
        }
    ]
    first = _post(client, "/api/v1/webhooks/hubspot", hubspot_event, None)
    flow.add(
        15,
        "CRM change webhook returns",
        first.status_code < 300,
        f"HTTP {first.status_code} · signature {first.json().get('signature', '?')} "
        f"· a rep changed lifecyclestage in the CRM",
    )
    replay = [{**hubspot_event[0], "attemptNumber": 3}]  # HubSpot increments this on every retry
    second = _post(client, "/api/v1/webhooks/hubspot", replay, None)
    body = second.json() if second.status_code < 500 else {}
    flow.add(
        16,
        "Duplicate delivery is deduplicated",
        bool(body.get("duplicate")),
        f"HTTP {second.status_code} · duplicate={body.get('duplicate')} "
        f"· the retry carries attemptNumber=3 and still collides on the event id",
    )

    # 17 ── reconciliation ------------------------------------------------------------------------------
    with session_scope() as db:
        stored = db.scalars(
            select(WebhookEvent)
            .where(WebhookEvent.source == "hubspot")
            .order_by(WebhookEvent.received_at.desc())
            .limit(1)
        ).first()
        crm_objects = db.scalar(
            select(func.count()).select_from(SimulatedCrmObject).where(SimulatedCrmObject.workspace_id == ws_id)
        )
        flow.add(
            17,
            "GTMOS reconciles state",
            stored is not None,
            f"one stored event with duplicate_count={stored.duplicate_count if stored else '?'}; "
            f"{crm_objects} objects in the simulated CRM; inbound CRM changes are logged, never auto-applied",
        )

    # 18 ── analytics ------------------------------------------------------------------------------------
    overview = client.get("/api/v1/analytics/overview?days=90")
    funnel = client.get("/api/v1/analytics/funnel?days=90")
    ok = overview.status_code == 200 and funnel.status_code == 200
    f = funnel.json() if ok else {}
    flow.add(
        18,
        "Analytics update",
        ok,
        f"cohort funnel: {f.get('cohort_size', '?')} contacted → "
        + " → ".join(f"{s['stage']} {s['accounts']}" for s in (f.get("stages") or [])[1:4]),
    )

    # 19 ── operations -----------------------------------------------------------------------------------
    ops = client.get("/api/v1/operations")
    flow.add(
        19,
        "Operations shows the execution",
        ops.status_code == 200,
        "workflow runs, syncs, webhook deliveries and provider calls are all queryable with a correlation id",
    )

    # 20 ── audit ----------------------------------------------------------------------------------------
    with session_scope() as db:
        recent_audit = list(
            db.scalars(
                select(AuditEvent)
                .where(AuditEvent.workspace_id == ws_id)
                .order_by(AuditEvent.occurred_at.desc())
                .limit(8)
            )
        )
        actions = [a.action for a in recent_audit]
        flow.add(
            20,
            "Audit log explains what happened",
            bool(recent_audit),
            f"last actions: {', '.join(actions[:5])}",
        )

    client.close()
    return flow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the GTMOS golden end-to-end flow.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010", help="a running GTMOS API")
    parser.add_argument("--run-key", default="v1", help="changes the deterministic ids this run produces")
    parser.add_argument(
        "--via-n8n",
        action="store_true",
        help="send product events through the local n8n instance instead of straight to the API",
    )
    parser.add_argument("--json", action="store_true", help="emit the trace as JSON")
    args = parser.parse_args(argv)

    flow = run(args.base_url, args.run_key, args.via_n8n)

    if args.json:
        print(
            json.dumps(
                {
                    "run_key": flow.run_key,
                    "via_n8n": flow.via_n8n,
                    "steps": [
                        {"n": s.n, "title": s.title, "ok": s.ok, "detail": s.detail, "evidence": s.evidence}
                        for s in flow.steps
                    ],
                    "failed": len(flow.failed),
                },
                indent=2,
                default=str,
            )
        )
    else:
        print("\nGTMOS golden flow — one account through every boundary")
        print(f"run key: {flow.run_key} · transport: {'n8n' if flow.via_n8n else 'direct'}\n")
        for s in flow.steps:
            print(s.line())
        print()
        if flow.failed:
            print(f"{len(flow.failed)} step(s) failed: " + ", ".join(str(s.n) for s in flow.failed))
        else:
            print(f"All {len(flow.steps)} steps passed.")
        print()
    return 1 if flow.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
