"""Account research pipeline: gather evidence from the DB → generate (demo or LLM) → validate → persist."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gtmos.config import get_settings
from gtmos.domain.committee import ROLE_LABELS
from gtmos.domain.research import (
    PROMPT_VERSION,
    ResearchInput,
    generate_deterministic,
    input_hash,
    sections_to_json,
    validate_sections,
)
from gtmos.integrations.llm import LLMUnavailable, get_research_writer
from gtmos.models import (
    Account,
    AccountContactRole,
    Activity,
    Contact,
    ResearchEvidence,
    ResearchReport,
    Signal,
    Workspace,
)
from gtmos.services.common import audit, utcnow
from gtmos.services.enrichment_service import provenance_for
from gtmos.services.scoring_service import current_score

ACTIVITY_LABELS = {
    "positive_reply": "Positive reply",
    "email_replied": "Replied",
    "meeting_held": "Meeting held",
    "meeting_booked": "Meeting booked",
    "call": "Call",
}


def build_input(db: Session, account: Account, now: datetime | None = None) -> ResearchInput:
    now = now or utcnow()
    ws = db.get(Workspace, account.workspace_id)
    sc = current_score(db, account.id)
    signals = list(
        db.scalars(
            select(Signal)
            .where(
                Signal.account_id == account.id,
                Signal.observed_at >= now - timedelta(days=180),
                Signal.observed_at <= now,
            )
            .order_by(Signal.observed_at.desc())
            .limit(12)
        )
    )
    roles = db.execute(
        select(AccountContactRole, Contact)
        .join(Contact, Contact.id == AccountContactRole.contact_id)
        .where(AccountContactRole.account_id == account.id, AccountContactRole.rank == 1)
    ).all()
    acts = list(
        db.scalars(
            select(Activity)
            .where(Activity.account_id == account.id, Activity.type.in_(list(ACTIVITY_LABELS)))
            .order_by(Activity.occurred_at.desc())
            .limit(5)
        )
    )
    prov = {
        f: {"source": p.source, "confidence": p.confidence, "observed_at": p.observed_at}
        for f, p in provenance_for(db, account.id).items()
    }
    contacts_by_id = {c.id: c for _, c in roles}
    return ResearchInput(
        account={
            "id": str(account.id),
            "name": account.name,
            "industry": account.industry,
            "employee_count": account.employee_count,
            "city": account.city,
            "funding_stage": account.funding_stage,
            "total_funding_usd": account.total_funding_usd,
            "technologies": list(account.technologies or []),
            "ai_team_size": account.ai_team_size,
            "ai_open_roles": account.ai_open_roles,
        },
        score={"id": str(sc[0].id), "total": sc[0].total, "grade": sc[0].grade, "summary": sc[0].summary} if sc else {},
        signals=[
            {
                "id": str(s.id),
                "signal_type": s.signal_type,
                "title": s.title,
                "explanation": s.explanation,
                "source": s.source,
                "source_url": s.source_url,
                "confidence": s.confidence,
                "strength": s.strength,
                "observed_at": s.observed_at,
                "evidence": s.evidence or {},
            }
            for s in signals
        ],
        committee=[
            {
                "contact_id": str(r.contact_id),
                "name": c.full_name,
                "title": c.title or "",
                "role": r.role,
                "role_label": ROLE_LABELS[r.role],
                "reasons": r.rationale or ["inferred"],
                "confidence": r.confidence,
            }
            for r, c in roles
        ],
        activities=[
            {
                "id": str(a.id),
                "label": f"{ACTIVITY_LABELS.get(a.type, a.type)}: {a.subject or ''}".strip(),
                "detail": (a.summary or a.subject or ACTIVITY_LABELS.get(a.type, a.type))
                + (f" ({contacts_by_id[a.contact_id].full_name})" if a.contact_id in contacts_by_id else ""),
                "occurred_at": a.occurred_at,
                "source": a.source,
            }
            for a in acts
        ],
        provenance=prov,
        seller={"name": ws.seller_name if ws else "Seller", "product": ws.seller_product if ws else ""},
        now=now,
    )


def generate_research(
    db: Session, account: Account, *, actor: str = "system", use_llm: bool = True, now: datetime | None = None
) -> ResearchReport:
    t0 = time.perf_counter()
    inp = build_input(db, account, now)
    out = generate_deterministic(inp)
    generator = "demo-deterministic"
    meta: dict[str, Any] = {"angle": out.angle}
    unsupported = out.unsupported
    sections = out.sections
    writer = get_research_writer(get_settings()) if use_llm else None
    if writer is not None:
        try:
            llm_sections = writer.write(account.name, inp.seller, out.evidence)
            sections, unsupported = validate_sections(llm_sections, {e.ref for e in out.evidence})
            generator = writer.name
        except LLMUnavailable as exc:
            meta["llm_fallback_reason"] = str(exc)
    meta["counts"] = {k: len(v) for k, v in sections.items()}
    report = ResearchReport(
        workspace_id=account.workspace_id,
        account_id=account.id,
        status="draft",
        generator=generator,
        prompt_version=PROMPT_VERSION,
        sections={**sections_to_json(sections), "_meta": meta},
        unsupported_claims=unsupported,
        input_hash=input_hash(inp),
        created_at=utcnow(),
        created_by=actor,
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )
    db.add(report)
    db.flush()
    db.add_all(
        ResearchEvidence(
            report_id=report.id,
            ref=e.ref,
            kind=e.kind,
            label=e.label[:300],
            detail=e.detail,
            source=e.source,
            source_url=e.source_url,
            source_record_type=e.record_type,
            source_record_id=uuid.UUID(e.record_id) if e.record_id else None,
            observed_at=e.observed_at,
            confidence=e.confidence,
        )
        for e in out.evidence
    )
    audit(
        db,
        account.workspace_id,
        "research.generated",
        "account",
        account.id,
        after={
            "report_id": str(report.id),
            "generator": generator,
            "evidence": len(out.evidence),
            "unsupported_claims_removed": len(unsupported),
        },
        reason="Draft research. Not written to CRM until reviewed.",
        actor_type="user" if actor != "system" else "system",
        actor=actor,
    )
    db.flush()
    return report


def latest_report(db: Session, account_id: uuid.UUID) -> ResearchReport | None:
    return db.scalars(
        select(ResearchReport).where(ResearchReport.account_id == account_id).order_by(ResearchReport.created_at.desc())
    ).first()


def review_report(db: Session, report: ResearchReport, status: str, actor: str) -> ResearchReport:
    if status not in ("reviewed", "rejected", "draft"):
        raise ValueError("status must be reviewed, rejected or draft")
    before = report.status
    report.status = status
    report.reviewed_by = actor
    report.reviewed_at = utcnow()
    audit(
        db,
        report.workspace_id,
        "research.reviewed",
        "account",
        report.account_id,
        before={"status": before},
        after={"status": status, "report_id": str(report.id)},
    )
    return report
