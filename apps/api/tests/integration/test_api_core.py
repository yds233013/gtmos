"""API-level integration tests over the seeded demo universe."""

from __future__ import annotations

from sqlalchemy import func, select

from gtmos.models import Account, AuditEvent, MessageDraft, ResearchEvidence, ResearchReport


def test_health_and_workspace(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    r = client.get("/api/v1/workspace").json()
    assert r["mode"] == "demo"
    assert r["llm_mode"] == "demo"  # no key in tests → deterministic generators
    assert r["counts"]["accounts"] >= 150
    assert r["flagship_account_id"]


def test_request_id_and_security_headers(client):
    r = client.get("/api/v1/workspace", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_account_list_filters_and_sorting(client):
    r = client.get("/api/v1/accounts", params={"grade": ["A", "B"], "sort": "score", "page_size": 20}).json()
    assert all(a["score_grade"] in ("A", "B") for a in r["items"])
    scores = [a["icp_score"] for a in r["items"]]
    assert scores == sorted(scores, reverse=True)
    q = client.get("/api/v1/accounts", params={"q": "kestrel"}).json()
    assert q["items"][0]["name"] == "Kestrel Analytics"
    assert client.get("/api/v1/accounts", params={"sort": "bogus"}).status_code == 422


def test_flagship_detail_is_coherent(client, flagship):
    d = client.get(f"/api/v1/accounts/{flagship.id}").json()
    assert d["account"]["name"] == "Kestrel Analytics"
    assert d["score"]["grade"] == "A"
    total = sum(d["score"][k] for k in ("fit", "intent", "timing", "technical", "engagement"))
    assert abs(total - d["score"]["total"]) <= 1
    assert {c["category"] for c in d["score"]["components"]} >= {"fit", "intent", "timing", "technical", "engagement"}
    assert all(c["explanation"] for c in d["score"]["components"])
    types = {s["signal_type"] for s in d["signals"]}
    assert {"funding_round", "ai_product_launch", "ai_hiring_surge", "executive_hire"} <= types
    roles = {r["role"]: r["contact"]["name"] for r in d["committee"] if r["rank"] == 1}
    assert roles["champion"] == "Priya Raman"
    assert roles["technical_evaluator"] == "Tomás Alvarez"
    assert d["opportunities"][0]["name"].startswith("Kestrel Analytics")
    assert d["research"] is not None and d["research"]["evidence"]
    assert d["next_action"]["label"]


def test_unknown_account_404_and_bad_id_422(client):
    assert client.get("/api/v1/accounts/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.get("/api/v1/accounts/not-a-uuid").status_code == 422


def test_rescore_is_deterministic(client, flagship):
    a = client.post(f"/api/v1/accounts/{flagship.id}/rescore").json()
    b = client.post(f"/api/v1/accounts/{flagship.id}/rescore").json()
    assert a["after"] == b["after"] == b["before"]


def test_enrichment_fills_missing_fields_with_provenance(client, db, ws):
    target = db.scalars(select(Account).where(Account.workspace_id == ws.id, Account.employee_count.is_(None),
                                              Account.domain.is_not(None), Account.merged_into_id.is_(None),
                                              ~Account.domain.like("www.%"))).first()
    assert target is not None
    r = client.post(f"/api/v1/accounts/{target.id}/enrich").json()
    assert r["run"]["is_simulated"] is True
    outcomes = {a["outcome"] for a in r["attempts"]}
    assert outcomes & {"hit", "miss", "error", "low_confidence"}
    detail = client.get(f"/api/v1/accounts/{target.id}").json()
    if "employee_count" in r["run"]["fields_changed"]:
        assert detail["account"]["employee_count"] is not None
        assert detail["provenance"]["employee_count"]["source"].startswith("demo_")


def test_routing_preview_does_not_apply(client, flagship, db):
    before = flagship.owner_id
    r = client.post(f"/api/v1/accounts/{flagship.id}/route", json={"apply": False}).json()
    assert r["simulated"] is True and r["explanation"]
    db.refresh(flagship)
    assert flagship.owner_id == before


def test_committee_override_persists_through_recompute(client, flagship):
    d = client.get(f"/api/v1/accounts/{flagship.id}").json()
    tomas = next(c for c in d["contacts"] if c["full_name"] == "Tomás Alvarez")
    assert client.put(f"/api/v1/accounts/{flagship.id}/committee/champion", json={"contact_id": tomas["id"]}).status_code == 200
    client.post(f"/api/v1/accounts/{flagship.id}/committee/recompute")
    d2 = client.get(f"/api/v1/accounts/{flagship.id}").json()
    champ = next(r for r in d2["committee"] if r["role"] == "champion" and r["rank"] == 1)
    assert champ["contact"]["name"] == "Tomás Alvarez" and champ["is_manual_override"]
    client.delete(f"/api/v1/accounts/{flagship.id}/committee/champion")
    d3 = client.get(f"/api/v1/accounts/{flagship.id}").json()
    champ = next(r for r in d3["committee"] if r["role"] == "champion" and r["rank"] == 1)
    assert champ["contact"]["name"] == "Priya Raman"


def test_research_claims_all_cite_existing_evidence(client, flagship, db):
    r = client.post(f"/api/v1/accounts/{flagship.id}/research", json={"use_llm": True}).json()
    assert r["generator"] == "demo-deterministic"
    refs = {e["ref"] for e in r["evidence"]}
    claims = [c for k, v in r["sections"].items() if k != "_meta" for c in v]
    assert claims and all(c["evidence"] and set(c["evidence"]) <= refs for c in claims)
    report = db.get(ResearchReport, r["id"])
    assert report.status == "draft"  # never auto-promoted to truth
    n = db.scalar(select(func.count()).select_from(ResearchEvidence).where(ResearchEvidence.report_id == report.id))
    assert n == len(refs)


def test_outreach_multithreads_to_buyer_on_open_opportunity(client, flagship):
    r = client.post(f"/api/v1/accounts/{flagship.id}/drafts", json={"channels": ["email"]}).json()
    email = r["drafts"][0]
    assert email["status"] == "draft"
    assert "Priya" in email["body"]  # references the engaged champion
    assert not email["body"].startswith("Hi Priya")
    assert all(g["passed"] for g in email["guardrails"] if g["blocking"])


def test_draft_approval_state_machine_and_guardrail_block(client, flagship, db):
    email = client.post(f"/api/v1/accounts/{flagship.id}/drafts", json={"channels": ["email"]}).json()["drafts"][0]
    did = email["id"]
    assert client.post(f"/api/v1/drafts/{did}/transition", json={"target": "ready"}).status_code == 409
    assert client.post(f"/api/v1/drafts/{did}/transition", json={"target": "review"}).json()["status"] == "review"
    # An edit that fabricates a metric is blocked from approval.
    edited = client.put(f"/api/v1/drafts/{did}", json={"subject": "x", "body": "We cut incidents by 73%. Chat?"}).json()
    assert any(g["check"] == "numbers_grounded" and not g["passed"] for g in edited["guardrails"])
    blocked = client.post(f"/api/v1/drafts/{did}/transition", json={"target": "approved"})
    assert blocked.status_code == 409 and "guardrail" in blocked.json()["error"].lower()
    client.put(f"/api/v1/drafts/{did}", json={"subject": email["subject"], "body": email["body"]})
    ok = client.post(f"/api/v1/drafts/{did}/transition", json={"target": "approved"}).json()
    assert ok["status"] == "approved" and ok["approved_by"]
    assert client.post(f"/api/v1/drafts/{did}/transition", json={"target": "ready"}).json()["status"] == "ready"
    actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == db.get(MessageDraft, did).id)))
    assert {"message.review", "message.approved", "message.ready", "message.edited"} <= actions


def test_stage_transition_rules_enforced(client, db, ws):
    a = db.scalars(select(Account).where(Account.workspace_id == ws.id, Account.funnel_stage == "prospect",
                                         Account.merged_into_id.is_(None))).first()
    assert client.post(f"/api/v1/accounts/{a.id}/stage", json={"stage": "won"}).status_code == 409
    r = client.post(f"/api/v1/accounts/{a.id}/stage", json={"stage": "engaged"}).json()
    assert r["funnel_stage"] == "engaged" and r["lifecycle_stage"] == "marketingqualifiedlead"
    assert client.post(f"/api/v1/accounts/{a.id}/stage", json={"stage": "contacted"}).status_code == 409


def test_icp_preview_and_validation(client):
    icp = client.get("/api/v1/icp").json()["definition"]
    icp["weights"] = {"fit": 50, "intent": 20, "timing": 10, "technical": 10, "engagement": 10}
    p = client.post("/api/v1/icp/preview", json=icp).json()
    assert p["accounts_scored"] >= 150 and p["grade_distribution"]
    icp["weights"]["fit"] = 70  # no longer sums to 100
    assert client.post("/api/v1/icp/preview", json=icp).status_code == 422
