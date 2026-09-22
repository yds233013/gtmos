"""CRM state changes with validation, history and audit."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from gtmos.domain.pipeline import DEAL_ORDER, check_funnel_transition, lifecycle_for_funnel
from gtmos.models import Account, Opportunity, StageTransition
from gtmos.services.common import Conflict, audit, utcnow


def change_funnel_stage(
    db: Session,
    account: Account,
    target: str,
    *,
    actor: str,
    reason: str | None = None,
    recycle: bool = False,
    at: datetime | None = None,
) -> StageTransition:
    chk = check_funnel_transition(account.funnel_stage, target, recycle=recycle)
    if not chk.allowed:
        raise Conflict(chk.reason)
    at = at or utcnow()
    before = {"funnel_stage": account.funnel_stage, "lifecycle_stage": account.lifecycle_stage}
    t = StageTransition(
        workspace_id=account.workspace_id,
        entity_type="account",
        entity_id=account.id,
        pipeline="funnel",
        from_stage=account.funnel_stage,
        to_stage=target,
        changed_at=at,
        changed_by=actor,
        reason=reason,
    )
    account.funnel_stage = target
    new_lc = lifecycle_for_funnel(target, account.lifecycle_stage)
    if new_lc:
        account.lifecycle_stage = new_lc
    if target == "won":
        account.is_customer = True
    db.add(t)
    audit(
        db,
        account.workspace_id,
        "account.stage_changed",
        "account",
        account.id,
        before=before,
        after={"funnel_stage": target, "lifecycle_stage": account.lifecycle_stage},
        reason=reason or chk.reason,
        actor=actor,
        actor_type="user" if "@" in actor else "system",
        occurred_at=at,
    )
    db.flush()
    return t


def change_deal_stage(
    db: Session, opp: Opportunity, target: str, *, actor: str, reason: str | None = None, lost_reason: str | None = None
) -> Opportunity:
    if target not in DEAL_ORDER:
        raise Conflict(f"unknown deal stage '{target}'")
    if opp.stage in ("closed_won", "closed_lost"):
        raise Conflict("closed opportunities cannot change stage")
    if target == "closed_lost" and not lost_reason:
        raise Conflict("a lost reason is required to close an opportunity as lost")
    before = opp.stage
    now = utcnow()
    db.add(
        StageTransition(
            workspace_id=opp.workspace_id,
            entity_type="opportunity",
            entity_id=opp.id,
            pipeline="deal",
            from_stage=before,
            to_stage=target,
            changed_at=now,
            changed_by=actor,
            reason=reason,
        )
    )
    opp.stage = target
    if target in ("closed_won", "closed_lost"):
        opp.closed_at = now
        opp.lost_reason = lost_reason
        account = db.get(Account, opp.account_id)
        if account and account.funnel_stage == "opportunity":
            open_others = db.scalars(
                select(Opportunity.id).where(
                    Opportunity.account_id == account.id,
                    Opportunity.id != opp.id,
                    Opportunity.stage.not_in(["closed_won", "closed_lost"]),
                )
            ).first()
            if target == "closed_won":
                change_funnel_stage(db, account, "won", actor=actor, reason=f"Opportunity {opp.name} won")
            elif open_others is None:
                change_funnel_stage(db, account, "lost", actor=actor, reason=f"Opportunity lost: {lost_reason}")
    audit(
        db,
        opp.workspace_id,
        "opportunity.stage_changed",
        "opportunity",
        opp.id,
        before={"stage": before},
        after={"stage": target, "lost_reason": lost_reason},
        reason=reason,
        actor=actor,
    )
    db.flush()
    return opp


def create_opportunity(
    db: Session,
    account: Account,
    *,
    name: str,
    amount: float,
    actor: str,
    primary_contact_id: uuid.UUID | None = None,
    source_campaign_id: uuid.UUID | None = None,
) -> Opportunity:
    if amount < 0:
        raise Conflict("amount must be non-negative")
    now = utcnow()
    opp = Opportunity(
        workspace_id=account.workspace_id,
        account_id=account.id,
        name=name,
        stage="discovery",
        amount_usd=amount,
        opened_at=now,
        owner_id=account.owner_id,
        primary_contact_id=primary_contact_id,
        source_campaign_id=source_campaign_id,
        lead_source="outbound" if source_campaign_id else "inbound",
        data_origin="live",
    )
    db.add(opp)
    db.flush()
    if check_funnel_transition(account.funnel_stage, "opportunity").allowed:
        change_funnel_stage(db, account, "opportunity", actor=actor, reason=f"Opportunity '{name}' created")
    audit(
        db,
        account.workspace_id,
        "opportunity.created",
        "opportunity",
        opp.id,
        after={"name": name, "amount": amount},
        actor=actor,
    )
    return opp
