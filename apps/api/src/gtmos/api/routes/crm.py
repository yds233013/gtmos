"""Contacts, opportunities, activities, users, signals, ICP, research review and message drafts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from gtmos.api.deps import Page, actor, db_session, parse_uuid, require_admin, row, workspace
from gtmos.domain.icp import ICPDefinition
from gtmos.domain.signals import SIGNAL_TYPES
from gtmos.models import (
    Account,
    AccountContactRole,
    Activity,
    Campaign,
    Contact,
    ICPProfile,
    MessageDraft,
    Opportunity,
    ResearchReport,
    Signal,
    User,
    Workspace,
)
from gtmos.services import crm_service, outreach_service
from gtmos.services.common import audit, utcnow
from gtmos.services.research_service import review_report
from gtmos.services.scoring_service import active_icp, preview_icp, rescore_accounts
from gtmos.services.signal_service import ingest_signal

router = APIRouter(tags=["crm"])


@router.get("/users")
def users(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> list[dict[str, Any]]:
    from gtmos.services.analytics import owner_load

    return owner_load(db, ws.id)


@router.get("/contacts")
def contacts(
    q: str | None = Query(None, max_length=100),
    account_id: str | None = None,
    email_status: str | None = None,
    role: str | None = None,
    page: Page = Depends(),
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
) -> dict[str, Any]:
    cond = [Contact.workspace_id == ws.id, Contact.merged_into_id.is_(None)]
    if q:
        like = f"%{q.lower()}%"
        cond.append(
            or_(
                func.lower(Contact.email).like(like),
                func.lower(Contact.last_name).like(like),
                func.lower(Contact.first_name).like(like),
                func.lower(Contact.title).like(like),
            )
        )
    if account_id:
        cond.append(Contact.account_id == parse_uuid(account_id))
    if email_status:
        cond.append(Contact.email_status == email_status)
    if role:
        cond.append(
            Contact.id.in_(
                select(AccountContactRole.contact_id).where(
                    AccountContactRole.role == role, AccountContactRole.rank == 1
                )
            )
        )
    total = db.scalar(select(func.count()).select_from(Contact).where(*cond)) or 0
    rows = db.execute(
        select(Contact, Account.name)
        .outerjoin(Account, Account.id == Contact.account_id)
        .where(*cond)
        .order_by(Contact.last_name, Contact.id)
        .offset(page.offset)
        .limit(page.page_size)
    ).all()
    ids = [c.id for c, _ in rows]
    roles: dict[Any, list[str]] = {}
    for cid, r in db.execute(
        select(AccountContactRole.contact_id, AccountContactRole.role).where(
            AccountContactRole.contact_id.in_(ids), AccountContactRole.rank == 1
        )
    ):
        roles.setdefault(cid, []).append(r)
    return {
        "items": [
            {
                **row(c, exclude=("workspace_id",)),
                "full_name": c.full_name,
                "account_name": n,
                "roles": roles.get(c.id, []),
            }
            for c, n in rows
        ],
        "total": total,
        "page": page.page,
        "page_size": page.page_size,
    }


@router.get("/opportunities")
def opportunities(
    stage: list[str] | None = Query(None),
    owner_id: str | None = None,
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
) -> dict[str, Any]:
    cond = [Opportunity.workspace_id == ws.id]
    if stage:
        cond.append(Opportunity.stage.in_(stage))
    if owner_id:
        cond.append(Opportunity.owner_id == parse_uuid(owner_id))
    rows = db.execute(
        select(Opportunity, Account.name, Account.score_grade, User.name, Campaign.name)
        .join(Account, Account.id == Opportunity.account_id)
        .outerjoin(User, User.id == Opportunity.owner_id)
        .outerjoin(Campaign, Campaign.id == Opportunity.source_campaign_id)
        .where(*cond)
        .order_by(Opportunity.opened_at.desc())
        .limit(500)
    ).all()
    return {
        "items": [
            {**row(o, exclude=("workspace_id",)), "account_name": an, "account_grade": g, "owner": un, "campaign": cn}
            for o, an, g, un, cn in rows
        ]
    }


class DealStageBody(BaseModel):
    stage: str = Field(max_length=40)
    lost_reason: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=500)


@router.post("/opportunities/{opp_id}/stage")
def opportunity_stage(
    opp_id: str,
    body: DealStageBody,
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
    who: str = Depends(actor),
) -> dict[str, Any]:
    o = db.get(Opportunity, parse_uuid(opp_id))
    if o is None or o.workspace_id != ws.id:
        raise HTTPException(404, "opportunity not found")
    crm_service.change_deal_stage(db, o, body.stage, actor=who, reason=body.reason, lost_reason=body.lost_reason)
    db.commit()
    return row(o, exclude=("workspace_id",))


@router.get("/activities")
def activities(
    type: list[str] | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
) -> dict[str, Any]:
    cond = [
        Activity.workspace_id == ws.id,
        Activity.occurred_at >= utcnow() - timedelta(days=days),
        Activity.occurred_at <= utcnow(),
    ]
    if type:
        cond.append(Activity.type.in_(type))
    rows = db.execute(
        select(Activity, Account.name, Contact.first_name, Contact.last_name, Campaign.name)
        .outerjoin(Account, Account.id == Activity.account_id)
        .outerjoin(Contact, Contact.id == Activity.contact_id)
        .outerjoin(Campaign, Campaign.id == Activity.campaign_id)
        .where(*cond)
        .order_by(Activity.occurred_at.desc())
        .limit(limit)
    ).all()
    return {
        "items": [
            {
                **row(a, exclude=("workspace_id", "dedupe_key")),
                "account_name": an,
                "contact_name": " ".join(x for x in (f, ln) if x) or None,
                "campaign": cn,
            }
            for a, an, f, ln, cn in rows
        ]
    }


# Signals ---------------------------------------------------------------------------------------------


@router.get("/signal-types")
def signal_types() -> list[dict[str, Any]]:
    return [
        {
            "key": s.key,
            "name": s.name,
            "category": s.category,
            "default_strength": s.default_strength,
            "half_life_days": s.half_life_days,
            "description": s.description,
        }
        for s in SIGNAL_TYPES.values()
    ]


@router.get("/signals")
def signals(
    type: list[str] | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    min_confidence: float = Query(0, ge=0, le=1),
    grade: list[str] | None = Query(None),
    source: str | None = None,
    page: Page = Depends(),
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
) -> dict[str, Any]:
    cond = [
        Signal.workspace_id == ws.id,
        Signal.observed_at >= utcnow() - timedelta(days=days),
        Signal.confidence >= min_confidence,
    ]
    if type:
        cond.append(Signal.signal_type.in_(type))
    if source:
        cond.append(Signal.source == source)
    if grade:
        cond.append(Account.score_grade.in_(grade))
    total = (
        db.scalar(select(func.count()).select_from(Signal).join(Account, Account.id == Signal.account_id).where(*cond))
        or 0
    )
    rows = db.execute(
        select(Signal, Account.name, Account.icp_score, Account.score_grade, Account.domain)
        .join(Account, Account.id == Signal.account_id)
        .where(*cond)
        .order_by(Signal.observed_at.desc(), Signal.id)
        .offset(page.offset)
        .limit(page.page_size)
    ).all()
    by_type = dict(
        db.execute(
            select(Signal.signal_type, func.count())
            .join(Account, Account.id == Signal.account_id)
            .where(*cond)
            .group_by(Signal.signal_type)
        )
        .tuples()
        .all()
    )
    return {
        "items": [
            {
                **row(s, exclude=("workspace_id", "dedupe_key")),
                "account_name": n,
                "account_score": sc,
                "account_grade": g,
                "account_domain": d,
                "category": SIGNAL_TYPES[s.signal_type].category if s.signal_type in SIGNAL_TYPES else None,
            }
            for s, n, sc, g, d in rows
        ],
        "total": total,
        "by_type": by_type,
        "page": page.page,
        "page_size": page.page_size,
    }


class SignalIn(BaseModel):
    account_domain: str = Field(min_length=3, max_length=255)
    signal_type: str
    title: str = Field(min_length=3, max_length=300)
    explanation: str = Field(min_length=3, max_length=2000)
    source: str = Field(default="manual", max_length=80)
    source_ref: str = Field(min_length=1, max_length=300, description="Stable id of the real-world event")
    source_url: str | None = Field(default=None, max_length=1000)
    observed_at: datetime | None = None
    confidence: float = Field(default=0.8, ge=0, le=1)
    strength: float | None = Field(default=None, ge=0, le=1)
    evidence: dict[str, Any] = Field(default_factory=dict)


def ingest_signal_payload(db: Session, ws: Workspace, body: SignalIn) -> dict[str, Any]:
    from gtmos.domain.matching import normalize_domain

    domain = normalize_domain(body.account_domain)
    a = db.scalars(
        select(Account).where(Account.workspace_id == ws.id, Account.domain == domain, Account.merged_into_id.is_(None))
    ).first()
    if a is None:
        raise HTTPException(404, f"no account with domain '{domain}'")
    if body.signal_type not in SIGNAL_TYPES:
        raise HTTPException(422, f"unknown signal type '{body.signal_type}'")
    observed = body.observed_at or utcnow()
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    res = ingest_signal(
        db,
        a,
        signal_type=body.signal_type,
        observed_at=observed,
        source=body.source,
        title=body.title,
        explanation=body.explanation,
        source_ref=body.source_ref,
        confidence=body.confidence,
        strength=body.strength,
        evidence=body.evidence,
        source_url=body.source_url,
        data_origin="live",
    )
    return {
        "signal_id": str(res.signal.id),
        "created": res.created,
        "account_id": str(a.id),
        "score_before": res.score_before,
        "score_after": res.score_after,
        "workflow_runs": res.workflow_runs,
    }


@router.post("/signals")
def create_signal(
    body: SignalIn, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    out = ingest_signal_payload(db, ws, body)
    db.commit()
    return out


# ICP -------------------------------------------------------------------------------------------------


@router.get("/icp")
def get_icp(db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    profile, icp = active_icp(db, ws.id)
    versions = db.execute(
        select(ICPProfile.version, ICPProfile.created_at, ICPProfile.created_by, ICPProfile.is_active)
        .where(ICPProfile.workspace_id == ws.id)
        .order_by(ICPProfile.version.desc())
    ).all()
    return {
        "id": str(profile.id),
        "version": profile.version,
        "definition": icp.model_dump(mode="json"),
        "versions": [{"version": v, "created_at": c, "created_by": b, "is_active": act} for v, c, b, act in versions],
        "signal_types": signal_types(),
    }


@router.post("/icp/preview")
def icp_preview(
    definition: ICPDefinition, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    return preview_icp(db, ws.id, definition)


@router.put("/icp", dependencies=[Depends(require_admin)])
def save_icp(
    definition: ICPDefinition,
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
    who: str = Depends(actor),
) -> dict[str, Any]:
    profile, _old = active_icp(db, ws.id)
    profile.is_active = False
    new = ICPProfile(
        workspace_id=ws.id,
        name=definition.name,
        version=profile.version + 1,
        is_active=True,
        definition=definition.model_dump(mode="json"),
        created_by=who,
    )
    db.add(new)
    db.flush()
    audit(
        db,
        ws.id,
        "icp.updated",
        "icp_profile",
        new.id,
        before={"version": profile.version},
        after={"version": new.version},
        actor=who,
    )
    outcomes = rescore_accounts(db, ws.id, trigger=f"icp:v{new.version}")
    db.commit()
    return {"version": new.version, "rescored": len(outcomes)}


# Research & drafts -----------------------------------------------------------------------------------


class ReviewBody(BaseModel):
    status: Literal["reviewed", "rejected", "draft"]


@router.post("/research/{report_id}/review")
def research_review(
    report_id: str,
    body: ReviewBody,
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
    who: str = Depends(actor),
) -> dict[str, Any]:
    r = db.get(ResearchReport, parse_uuid(report_id))
    if r is None or r.workspace_id != ws.id:
        raise HTTPException(404, "report not found")
    review_report(db, r, body.status, who)
    db.commit()
    return {"id": str(r.id), "status": r.status}


@router.get("/drafts")
def drafts(
    status: list[str] | None = Query(None), db: Session = Depends(db_session), ws: Workspace = Depends(workspace)
) -> dict[str, Any]:
    cond = [MessageDraft.workspace_id == ws.id]
    if status:
        cond.append(MessageDraft.status.in_(status))
    rows = db.execute(
        select(MessageDraft, Account.name, Account.icp_score, Contact.first_name, Contact.last_name, Contact.title)
        .join(Account, Account.id == MessageDraft.account_id)
        .outerjoin(Contact, Contact.id == MessageDraft.contact_id)
        .where(*cond)
        .order_by(MessageDraft.created_at.desc())
        .limit(200)
    ).all()
    counts = dict(
        db.execute(
            select(MessageDraft.status, func.count())
            .where(MessageDraft.workspace_id == ws.id)
            .group_by(MessageDraft.status)
        )
        .tuples()
        .all()
    )
    return {
        "items": [
            {
                **row(d, exclude=("workspace_id",)),
                "account_name": an,
                "account_score": sc,
                "contact_name": " ".join(x for x in (f, ln) if x) or None,
                "contact_title": t,
            }
            for d, an, sc, f, ln, t in rows
        ],
        "counts": counts,
    }


def _draft(db: Session, ws: Workspace, draft_id: str) -> MessageDraft:
    d = db.get(MessageDraft, parse_uuid(draft_id))
    if d is None or d.workspace_id != ws.id:
        raise HTTPException(404, "draft not found")
    return d


@router.get("/drafts/{draft_id}")
def draft_detail(draft_id: str, db: Session = Depends(db_session), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    d = _draft(db, ws, draft_id)
    acct = db.get(Account, d.account_id)
    contact = db.get(Contact, d.contact_id) if d.contact_id else None
    return {**row(d, exclude=("workspace_id",)), "account_name": acct.name if acct else None,
            "account_score": acct.icp_score if acct else None,
            "contact_name": contact.full_name if contact else None, "contact_title": contact.title if contact else None}


class TransitionBody(BaseModel):
    target: Literal["draft", "review", "approved", "ready", "rejected"]
    reason: str | None = Field(default=None, max_length=1000)


@router.post("/drafts/{draft_id}/transition")
def draft_transition(
    draft_id: str,
    body: TransitionBody,
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
    who: str = Depends(actor),
) -> dict[str, Any]:
    d = _draft(db, ws, draft_id)
    outreach_service.transition(db, d, body.target, who, body.reason)
    db.commit()
    return row(d, exclude=("workspace_id",))


class EditBody(BaseModel):
    subject: str | None = Field(default=None, max_length=500)
    body: str = Field(min_length=1, max_length=5000)


@router.put("/drafts/{draft_id}")
def draft_edit(
    draft_id: str,
    body: EditBody,
    db: Session = Depends(db_session),
    ws: Workspace = Depends(workspace),
    who: str = Depends(actor),
) -> dict[str, Any]:
    d = _draft(db, ws, draft_id)
    outreach_service.edit_draft(db, d, body.subject, body.body, who)
    db.commit()
    return row(d, exclude=("workspace_id",))
