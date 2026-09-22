"""Applies routing rules from the database and records every decision with its explanation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gtmos.domain.routing import RoutingOutcome, RuleSpec, UserFacts, route
from gtmos.domain.rules import Condition
from gtmos.models import Account, RoutingDecision, RoutingRule, User
from gtmos.services.common import audit, utcnow


def load_rules(db: Session, workspace_id: uuid.UUID) -> list[RuleSpec]:
    rows = db.scalars(select(RoutingRule).where(RoutingRule.workspace_id == workspace_id))
    return [
        RuleSpec(
            r.key,
            r.name,
            r.priority,
            tuple(Condition.model_validate(c) for c in r.conditions),
            r.assign_strategy,
            str(r.assign_user_id) if r.assign_user_id else None,
            r.assign_team,
            r.overrides_existing_owner,
            r.is_active,
        )
        for r in rows
    ]


def load_users(db: Session, workspace_id: uuid.UUID) -> list[UserFacts]:
    loads = dict(
        db.execute(
            select(Account.owner_id, func.count())
            .where(
                Account.workspace_id == workspace_id,
                Account.owner_id.is_not(None),
                Account.funnel_stage.not_in(["won", "lost"]),
            )
            .group_by(Account.owner_id)
        )
        .tuples()
        .all()
    )
    users = db.scalars(select(User).where(User.workspace_id == workspace_id))
    return [UserFacts(str(u.id), u.name, u.team, u.is_active, u.capacity, loads.get(u.id, 0)) for u in users]


def routing_context(a: Account) -> dict[str, Any]:
    return {
        "account": {
            "segment": a.segment,
            "region": a.region,
            "country": a.country,
            "employee_count": a.employee_count,
            "icp_score": a.icp_score,
            "score_grade": a.score_grade,
            "intent_score": a.intent_score,
            "is_customer": a.is_customer,
            "owner_id": str(a.owner_id) if a.owner_id else None,
            "industry": a.industry,
            "funnel_stage": a.funnel_stage,
        }
    }


def simulate(db: Session, account: Account) -> RoutingOutcome:
    return route(load_rules(db, account.workspace_id), routing_context(account), load_users(db, account.workspace_id))


def route_account(
    db: Session,
    account: Account,
    *,
    trigger: str = "manual",
    apply: bool = True,
    signal_observed_at: datetime | None = None,
    decided_at: datetime | None = None,
    users: list[UserFacts] | None = None,
    rules: list[RuleSpec] | None = None,
    rule_ids: dict[str, uuid.UUID] | None = None,
) -> RoutingDecision:
    decided_at = decided_at or utcnow()
    out = route(
        rules if rules is not None else load_rules(db, account.workspace_id),
        routing_context(account),
        users if users is not None else load_users(db, account.workspace_id),
    )
    rule_id = None
    if out.rule_key and rule_ids is not None:
        rule_id = rule_ids.get(out.rule_key)
    elif out.rule_key:
        rule_id = db.scalars(
            select(RoutingRule.id).where(
                RoutingRule.workspace_id == account.workspace_id, RoutingRule.key == out.rule_key
            )
        ).first()
    prev = account.owner_id
    latency = ((decided_at - signal_observed_at).total_seconds() * 1000) if signal_observed_at else None
    decision = RoutingDecision(
        workspace_id=account.workspace_id,
        account_id=account.id,
        rule_id=rule_id,
        outcome=out.outcome,
        assigned_user_id=uuid.UUID(out.assigned_user_id) if out.assigned_user_id else None,
        previous_owner_id=prev,
        matched_rules=out.matched,
        conflicts=out.conflicts,
        explanation=out.explanation,
        trigger=trigger,
        latency_ms=latency,
        decided_at=decided_at,
        applied=apply,
    )
    db.add(decision)
    if apply and out.assigned_user_id and uuid.UUID(out.assigned_user_id) != prev:
        account.owner_id = uuid.UUID(out.assigned_user_id)
        audit(
            db,
            account.workspace_id,
            "account.owner_changed",
            "account",
            account.id,
            before={"owner_id": prev},
            after={"owner_id": out.assigned_user_id},
            reason=out.explanation[0] if out.explanation else "routing",
            actor_type="system",
            actor="routing_engine",
            occurred_at=decided_at,
        )
    db.flush()
    return decision


def rule_id_map(db: Session, workspace_id: uuid.UUID) -> dict[str, uuid.UUID]:
    return dict(
        db.execute(select(RoutingRule.key, RoutingRule.id).where(RoutingRule.workspace_id == workspace_id))
        .tuples()
        .all()
    )
