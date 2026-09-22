"""Deterministic next-best-action for an account.

Rules are ordered by urgency and each returns the reason it fired, so the recommendation is explainable
and can be written to the CRM (reverse ETL) without an LLM in the loop. Facts are loaded in bulk so
the reverse-ETL job costs a handful of queries regardless of account count.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gtmos.models import Account, AccountContactRole, Activity, Contact, MessageDraft, Opportunity
from gtmos.services.common import utcnow


@dataclass
class NextAction:
    key: str
    label: str
    reason: str
    priority: int  # 1 = most urgent


@dataclass
class ActionFacts:
    pending_drafts: dict[uuid.UUID, int] = field(default_factory=dict)
    open_opp: dict[uuid.UUID, str] = field(default_factory=dict)
    last_touch: dict[uuid.UUID, datetime] = field(default_factory=dict)
    has_econ_buyer: set[uuid.UUID] = field(default_factory=set)
    champion: dict[uuid.UUID, str] = field(default_factory=dict)


def load_action_facts(db: Session, account_ids: list[uuid.UUID], now: datetime) -> ActionFacts:
    f = ActionFacts()
    if not account_ids:
        return f
    f.pending_drafts = dict(
        db.execute(
            select(MessageDraft.account_id, func.count())
            .where(MessageDraft.account_id.in_(account_ids), MessageDraft.status == "review")
            .group_by(MessageDraft.account_id)
        )
        .tuples()
        .all()
    )
    for acc, name in db.execute(
        select(Opportunity.account_id, Opportunity.name)
        .where(Opportunity.account_id.in_(account_ids), Opportunity.stage.not_in(["closed_won", "closed_lost"]))
        .order_by(Opportunity.opened_at)
    ).tuples():
        f.open_opp[acc] = name
    f.last_touch = dict(
        db.execute(
            select(Activity.account_id, func.max(Activity.occurred_at))
            .where(
                Activity.account_id.in_(account_ids),
                Activity.occurred_at <= now,
                Activity.type.not_in(["task", "notification"]),
            )
            .group_by(Activity.account_id)
        )
        .tuples()
        .all()
    )
    roles = db.execute(
        select(AccountContactRole.account_id, AccountContactRole.role, Contact.first_name, Contact.last_name)
        .join(Contact, Contact.id == AccountContactRole.contact_id)
        .where(
            AccountContactRole.account_id.in_(account_ids),
            AccountContactRole.rank == 1,
            AccountContactRole.role.in_(["economic_buyer", "champion"]),
        )
    ).all()
    for acc, role, first, last in roles:
        if role == "economic_buyer":
            f.has_econ_buyer.add(acc)
        else:
            f.champion[acc] = " ".join(x for x in (first, last) if x)
    return f


def decide(a: Account, f: ActionFacts, now: datetime) -> NextAction:
    if a.is_customer:
        return NextAction(
            "expansion_review",
            "Review expansion potential with the account manager",
            "Existing customer: expansion motion, not new-logo outreach.",
            4,
        )
    if a.score_grade == "X":
        return NextAction("do_not_target", "Do not target", "Excluded by ICP rules.", 9)
    if a.owner_id is None and a.score_grade in ("A", "B"):
        return NextAction(
            "route", "Assign an owner", f"{a.score_grade}-grade account has no owner; routing did not match a rule.", 1
        )
    if pending := f.pending_drafts.get(a.id):
        return NextAction(
            "approve_outreach", f"Review {pending} outreach draft(s)", "Drafts are waiting in the approval queue.", 1
        )
    if opp := f.open_opp.get(a.id):
        last = f.last_touch.get(a.id)
        if last is None or now - last > timedelta(days=14):
            return NextAction(
                "reengage_opportunity",
                "Re-engage the open opportunity",
                f"'{opp}' has had no activity for 14+ days.",
                2,
            )
        if a.id in f.has_econ_buyer:
            return NextAction(
                "multithread",
                "Multi-thread to the economic buyer",
                "Open opportunity; broaden beyond the champion before the evaluation.",
                2,
            )
        return NextAction("advance_opportunity", "Advance the opportunity", f"'{opp}' is active.", 3)
    if a.employee_count is None or not a.industry:
        return NextAction(
            "enrich",
            "Enrich missing firmographics",
            "Missing employee count or industry makes the fit score unreliable.",
            3,
        )
    if (a.icp_score or 0) >= 75 and (a.intent_score or 0) >= 45:
        who = f.champion.get(a.id)
        return NextAction(
            "outreach",
            f"Start signal-based outreach to {who or 'the champion'}",
            f"High fit ({a.icp_score}) with active intent ({a.intent_score}).",
            2,
        )
    if (a.icp_score or 0) >= 65:
        return NextAction(
            "nurture", "Add to ICP nurture and monitor signals", "Good fit but no strong buying signal yet.", 5
        )
    return NextAction("monitor", "Monitor", "Low fit or intent; no action recommended.", 8)


def next_best_action(db: Session, a: Account, now: datetime | None = None) -> NextAction:
    now = now or utcnow()
    return decide(a, load_action_facts(db, [a.id], now), now)


def next_best_actions(db: Session, accounts: list[Account], now: datetime | None = None) -> dict[uuid.UUID, NextAction]:
    now = now or utcnow()
    out: dict[uuid.UUID, NextAction] = {}
    for i in range(0, len(accounts), 1000):
        chunk = accounts[i : i + 1000]
        facts = load_action_facts(db, [a.id for a in chunk], now)
        out.update({a.id: decide(a, facts, now) for a in chunk})
    return out
