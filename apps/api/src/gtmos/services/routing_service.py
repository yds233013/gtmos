"""Applies routing rules from the database and records every decision with its explanation."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
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
            r.sla_hours,
            r.is_fallback,
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
            "id": str(a.id),
            "name": a.name,
            "is_named_account": a.is_named_account,
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
    return route(
        load_rules(db, account.workspace_id),
        routing_context(account),
        load_users(db, account.workspace_id),
        now=utcnow(),
    )


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
        now=decided_at,
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
        sla_due_at=out.sla_due_at,
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


# Touch types that count as "the rep responded". An internal note is not a touch.
FIRST_TOUCH_TYPES = ("email_sent", "call", "linkedin", "meeting_held")

# Speed to lead measures the response to a *new lead event* — a signal fired, a form came in, a
# product threshold was crossed. A territory reshuffle assigns thousands of accounts at once and
# starts no clock: counting those would make the metric a measure of list size rather than of
# responsiveness, and every team would fail it.
LEAD_TRIGGERS = ("signal.created", "inbound", "product.pql", "manual", "workflow")


def sla_report(db: Session, workspace_id: uuid.UUID, days: int = 90) -> dict[str, Any]:
    """Speed to lead: did the first touch happen inside the window routing promised?

    Breach is computed against real activity rather than stored on the decision, so three states stay
    distinguishable: touched in time, touched late, and never touched. A stored boolean would collapse
    the last two, and "nobody has looked at it yet" is the one that costs money.
    """
    from gtmos.models import Activity

    since = utcnow() - timedelta(days=days)
    decisions = list(
        db.scalars(
            select(RoutingDecision)
            .where(
                RoutingDecision.workspace_id == workspace_id,
                RoutingDecision.sla_due_at.is_not(None),
                RoutingDecision.decided_at >= since,
                RoutingDecision.applied.is_(True),
                RoutingDecision.trigger.in_(LEAD_TRIGGERS),
            )
            .order_by(RoutingDecision.decided_at)
        )
    )
    if not decisions:
        return {
            "window_days": days,
            "decisions_with_sla": 0,
            "note": "No lead-event routing decisions carry an SLA in this window.",
            "hit_rate": None,
            "met": 0,
            "late": 0,
            "untouched": 0,
            "pending": 0,
            "median_hours_to_first_touch": None,
            "by_rule": [],
            "worst": [],
        }

    account_ids = {d.account_id for d in decisions}
    touches: dict[uuid.UUID, list[datetime]] = {}
    for account_id, occurred_at in db.execute(
        select(Activity.account_id, Activity.occurred_at).where(
            Activity.account_id.in_(account_ids),
            Activity.type.in_(FIRST_TOUCH_TYPES),
            Activity.account_id.is_not(None),
        )
    ).tuples():
        if account_id is not None:
            touches.setdefault(account_id, []).append(occurred_at)

    names = dict(db.execute(select(Account.id, Account.name).where(Account.id.in_(account_ids))).tuples().all())
    rule_names = dict(
        db.execute(select(RoutingRule.id, RoutingRule.name).where(RoutingRule.workspace_id == workspace_id))
        .tuples()
        .all()
    )

    met = late = untouched = pending = 0
    hours: list[float] = []
    per_rule: dict[str, dict[str, Any]] = {}
    worst: list[dict[str, Any]] = []
    now = utcnow()
    for d in decisions:
        after = sorted(t for t in touches.get(d.account_id, []) if t >= d.decided_at)
        first = after[0] if after else None
        label = rule_names.get(d.rule_id, "No rule") if d.rule_id else "No rule"
        bucket = per_rule.setdefault(label, {"rule": label, "n": 0, "met": 0, "late": 0, "untouched": 0, "pending": 0})
        bucket["n"] += 1
        if first is None:
            if d.sla_due_at is not None and now < d.sla_due_at:
                # Assigned, not yet due. Counting this as a miss would penalise the team for the clock
                # still running.
                pending += 1
                bucket["pending"] += 1
                continue
            untouched += 1
            bucket["untouched"] += 1
            worst.append(
                {
                    "account": names.get(d.account_id),
                    "account_id": str(d.account_id),
                    "state": "untouched",
                    "overdue_hours": round((now - d.sla_due_at).total_seconds() / 3600, 1)
                    if d.sla_due_at and now > d.sla_due_at
                    else 0.0,
                }
            )
            continue
        elapsed = (first - d.decided_at).total_seconds() / 3600
        hours.append(elapsed)
        if d.sla_due_at is not None and first > d.sla_due_at:
            late += 1
            bucket["late"] += 1
            worst.append(
                {
                    "account": names.get(d.account_id),
                    "account_id": str(d.account_id),
                    "state": "late",
                    "overdue_hours": round((first - d.sla_due_at).total_seconds() / 3600, 1),
                }
            )
        else:
            met += 1
            bucket["met"] += 1

    hours.sort()
    median = hours[len(hours) // 2] if hours else None
    worst.sort(key=lambda w: -w["overdue_hours"])
    total = len(decisions)
    # The hit rate is measured over decisions whose clock has actually run out. Including pending ones
    # would make the number drift down purely because a batch was assigned this morning.
    decided = met + late + untouched
    return {
        "window_days": days,
        "decisions_with_sla": total,
        "met": met,
        "late": late,
        "untouched": untouched,
        "pending": pending,
        "hit_rate": round(met / decided, 4) if decided else None,
        "median_hours_to_first_touch": round(median, 1) if median is not None else None,
        "by_rule": sorted(per_rule.values(), key=lambda r: -r["n"]),
        "worst": worst[:20],
        "definition": (
            "First outbound touch (email, call, LinkedIn or meeting) after the routing decision, against "
            "the SLA the winning rule promised. Accounts with no touch at all are counted separately from "
            "late ones: a late touch is a process problem, no touch is a leak."
        ),
    }
