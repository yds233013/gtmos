"""GTM analytics: a small semantic layer of named, deterministic metrics computed from the database.

Every number the command center, Stack Inspector or Copilot shows comes from a function in this module.
There are no hardcoded values, and the same functions back the UI and the Copilot, so answers match the
dashboards.
"""

from __future__ import annotations

import statistics
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, distinct, func, select
from sqlalchemy.orm import Session

from gtmos.domain.signals import SIGNAL_TYPES
from gtmos.models import (
    Account,
    Activity,
    Campaign,
    Contact,
    MessageDraft,
    Opportunity,
    Signal,
    StageTransition,
)
from gtmos.models.crm import FUNNEL_STAGES
from gtmos.services.common import utcnow

FUNNEL_ORDER = [s for s in FUNNEL_STAGES if s != "lost"]
OPEN_DEAL = ["discovery", "evaluation", "proposal", "negotiation"]
DIMENSIONS = ("segment", "industry", "region", "score_grade", "campaign", "persona", "source")


def _since(days: int, now: datetime | None = None) -> datetime:
    return (now or utcnow()) - timedelta(days=days)


def _live(ws: uuid.UUID) -> Any:
    return and_(Account.workspace_id == ws, Account.merged_into_id.is_(None))


def overview(db: Session, ws: uuid.UUID, days: int = 90) -> dict[str, Any]:
    since = _since(days)
    total = db.scalar(select(func.count()).select_from(Account).where(_live(ws))) or 0
    graded = dict(
        db.execute(select(Account.score_grade, func.count()).where(_live(ws)).group_by(Account.score_grade))
        .tuples()
        .all()
    )
    high_intent = (
        db.scalar(
            select(func.count())
            .select_from(Account)
            .where(_live(ws), Account.intent_score >= 50, Account.score_grade != "X")
        )
        or 0
    )
    core_complete = (
        db.scalar(
            select(func.count())
            .select_from(Account)
            .where(
                _live(ws),
                Account.domain.is_not(None),
                Account.industry.is_not(None),
                Account.employee_count.is_not(None),
                Account.region.is_not(None),
            )
        )
        or 0
    )
    contacts = (
        db.scalar(
            select(func.count())
            .select_from(Contact)
            .where(Contact.workspace_id == ws, Contact.merged_into_id.is_(None))
        )
        or 0
    )
    valid_contacts = (
        db.scalar(
            select(func.count())
            .select_from(Contact)
            .where(Contact.workspace_id == ws, Contact.merged_into_id.is_(None), Contact.email_status == "valid")
        )
        or 0
    )
    acts = dict(
        db.execute(
            select(Activity.type, func.count())
            .where(Activity.workspace_id == ws, Activity.occurred_at >= since)
            .group_by(Activity.type)
        )
        .tuples()
        .all()
    )
    drafts = dict(
        db.execute(
            select(MessageDraft.status, func.count())
            .where(MessageDraft.workspace_id == ws)
            .group_by(MessageDraft.status)
        )
        .tuples()
        .all()
    )
    qualified = (
        db.scalar(
            select(func.count(distinct(StageTransition.entity_id))).where(
                StageTransition.workspace_id == ws,
                StageTransition.to_stage == "qualified",
                StageTransition.changed_at >= since,
            )
        )
        or 0
    )
    opp_created = db.execute(
        select(func.count(), func.coalesce(func.sum(Opportunity.amount_usd), 0)).where(
            Opportunity.workspace_id == ws, Opportunity.opened_at >= since
        )
    ).one()
    won = db.execute(
        select(func.count(), func.coalesce(func.sum(Opportunity.amount_usd), 0)).where(
            Opportunity.workspace_id == ws, Opportunity.stage == "closed_won", Opportunity.closed_at >= since
        )
    ).one()
    open_pipe = db.execute(
        select(func.count(), func.coalesce(func.sum(Opportunity.amount_usd), 0)).where(
            Opportunity.workspace_id == ws, Opportunity.stage.in_(OPEN_DEAL)
        )
    ).one()
    sent = acts.get("email_sent", 0)
    return {
        "window_days": days,
        "accounts_sourced": total,
        "icp_accounts": graded.get("A", 0) + graded.get("B", 0),
        "grade_distribution": {k or "unscored": v for k, v in graded.items()},
        "high_intent_accounts": high_intent,
        "enrichment_coverage": round(core_complete / total, 4) if total else 0,
        "contacts": contacts,
        "contacts_verified": valid_contacts,
        "contact_coverage": round(valid_contacts / contacts, 4) if contacts else 0,
        "messages_drafted": sum(drafts.values()),
        "messages_in_review": drafts.get("review", 0),
        "messages_approved": drafts.get("approved", 0) + drafts.get("ready", 0),
        "emails_sent": sent,
        "emails_delivered": acts.get("email_delivered", 0),
        "emails_opened": acts.get("email_opened", 0),
        "replies": acts.get("email_replied", 0),
        "positive_replies": acts.get("positive_reply", 0),
        "reply_rate": round(acts.get("email_replied", 0) / sent, 4) if sent else 0,
        "meetings": acts.get("meeting_held", 0),
        "qualified_accounts": qualified,
        "opportunities_created": opp_created[0],
        "pipeline_created": float(opp_created[1]),
        "won_deals": won[0],
        "won_revenue": float(won[1]),
        "open_opportunities": open_pipe[0],
        "open_pipeline": float(open_pipe[1]),
        "open_rate_caveat": "Opens are shown for completeness only: Apple Mail Privacy Protection and "
        "image proxies make open tracking unreliable, so no GTMOS decision uses them.",
    }


def funnel(db: Session, ws: uuid.UUID, days: int = 90) -> dict[str, Any]:
    """Distinct accounts that *reached* each stage within the window, with step conversion."""
    since = _since(days)
    rows = dict(
        db.execute(
            select(StageTransition.to_stage, func.count(distinct(StageTransition.entity_id)))
            .where(
                StageTransition.workspace_id == ws,
                StageTransition.pipeline == "funnel",
                StageTransition.changed_at >= since,
            )
            .group_by(StageTransition.to_stage)
        )
        .tuples()
        .all()
    )
    stages = []
    prev = None
    for s in FUNNEL_ORDER:
        if s == "prospect":
            n = db.scalar(select(func.count()).select_from(Account).where(_live(ws))) or 0
        else:
            n = rows.get(s, 0)
        stages.append({"stage": s, "accounts": n, "conversion_from_previous": round(n / prev, 4) if prev else None})
        prev = n if n else prev
    return {"window_days": days, "stages": stages, "lost": rows.get("lost", 0)}


def _stage_reached(db: Session, ws: uuid.UUID, since: datetime) -> dict[uuid.UUID, set[str]]:
    reached: dict[uuid.UUID, set[str]] = defaultdict(set)
    for eid, st in db.execute(
        select(StageTransition.entity_id, StageTransition.to_stage).where(
            StageTransition.workspace_id == ws,
            StageTransition.pipeline == "funnel",
            StageTransition.changed_at >= since,
        )
    ):
        reached[eid].add(st)
    return reached


def breakdown(db: Session, ws: uuid.UUID, dimension: str, days: int = 180) -> dict[str, Any]:
    """Conversion by a dimension, for accounts contacted in the window."""
    if dimension not in DIMENSIONS:
        raise ValueError(f"dimension must be one of {', '.join(DIMENSIONS)}")
    since = _since(days)
    reached = _stage_reached(db, ws, since)
    contacted = {eid for eid, s in reached.items() if "contacted" in s}
    keys: dict[uuid.UUID, str] = {}
    if dimension == "campaign":
        rows = db.execute(
            select(Activity.account_id, Campaign.name)
            .join(Campaign, Campaign.id == Activity.campaign_id)
            .where(Activity.workspace_id == ws, Activity.type == "email_sent", Activity.occurred_at >= since)
            .distinct(Activity.account_id)
            .order_by(Activity.account_id, Activity.occurred_at)
        ).all()
        keys = {r[0]: r[1] for r in rows}
    elif dimension == "persona":
        rows = db.execute(
            select(Activity.account_id, Contact.department)
            .join(Contact, Contact.id == Activity.contact_id)
            .where(Activity.workspace_id == ws, Activity.type == "email_sent", Activity.occurred_at >= since)
            .distinct(Activity.account_id)
            .order_by(Activity.account_id, Activity.occurred_at)
        ).all()
        keys = {r[0]: (r[1] or "unknown") for r in rows}
    else:
        col = getattr(Account, dimension)
        keys = {
            r[0]: (r[1] or "unknown")
            for r in db.execute(select(Account.id, col).where(Account.id.in_(list(contacted))))
        }
    opp_amount: dict[uuid.UUID, float] = defaultdict(float)
    for acc, amt in db.execute(
        select(Opportunity.account_id, Opportunity.amount_usd).where(
            Opportunity.workspace_id == ws, Opportunity.opened_at >= since
        )
    ):
        opp_amount[acc] += float(amt or 0)
    agg: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for eid in contacted:
        k = keys.get(eid)
        if k is None:
            continue
        s = reached[eid]
        g = agg[k]
        g["contacted"] += 1
        g["engaged"] += 1 if s & {"engaged", "qualified", "meeting", "opportunity", "won"} else 0
        g["meetings"] += 1 if s & {"meeting", "opportunity", "won"} else 0
        g["opportunities"] += 1 if eid in opp_amount else 0
        g["pipeline"] += opp_amount.get(eid, 0.0)
        g["won"] += 1 if "won" in s else 0
    out = []
    for k, g in agg.items():
        n = g["contacted"]
        out.append(
            {
                "key": k,
                "contacted": int(n),
                "engaged": int(g["engaged"]),
                "meetings": int(g["meetings"]),
                "opportunities": int(g["opportunities"]),
                "pipeline": round(g["pipeline"], 2),
                "won": int(g["won"]),
                "engagement_rate": round(g["engaged"] / n, 4),
                "meeting_rate": round(g["meetings"] / n, 4),
                "opportunity_rate": round(g["opportunities"] / n, 4),
                "low_sample": n < 30,
            }
        )
    out.sort(key=lambda r: -r["contacted"])
    return {"dimension": dimension, "window_days": days, "rows": out}


def pipeline_trend(db: Session, ws: uuid.UUID, weeks: int = 16) -> dict[str, Any]:
    now = utcnow()
    start = (now - timedelta(weeks=weeks)).replace(hour=0, minute=0, second=0, microsecond=0)
    start -= timedelta(days=start.weekday())
    wk_open = func.date_trunc("week", Opportunity.opened_at).label("wk")
    created = db.execute(
        select(wk_open, func.count(), func.coalesce(func.sum(Opportunity.amount_usd), 0))
        .where(Opportunity.workspace_id == ws, Opportunity.opened_at >= start)
        .group_by(wk_open)
    ).all()
    wk_close = func.date_trunc("week", Opportunity.closed_at).label("wk")
    won = db.execute(
        select(wk_close, func.coalesce(func.sum(Opportunity.amount_usd), 0))
        .where(Opportunity.workspace_id == ws, Opportunity.stage == "closed_won", Opportunity.closed_at >= start)
        .group_by(wk_close)
    ).all()
    wk_act = func.date_trunc("week", Activity.occurred_at).label("wk")
    meetings = db.execute(
        select(wk_act, func.count())
        .where(Activity.workspace_id == ws, Activity.type == "meeting_held", Activity.occurred_at >= start)
        .group_by(wk_act)
    ).all()
    series: dict[str, dict[str, float]] = {}
    for i in range(weeks + 1):
        wk = (start + timedelta(weeks=i)).date().isoformat()
        series[wk] = {"opportunities": 0, "pipeline": 0.0, "won": 0.0, "meetings": 0}
    for wk, n, amt in created:
        series.setdefault(wk.date().isoformat(), {"opportunities": 0, "pipeline": 0.0, "won": 0.0, "meetings": 0})
        series[wk.date().isoformat()].update(opportunities=n, pipeline=float(amt))
    for wk, amt in won:
        if wk.date().isoformat() in series:
            series[wk.date().isoformat()]["won"] = float(amt)
    for wk, n in meetings:
        if wk.date().isoformat() in series:
            series[wk.date().isoformat()]["meetings"] = n
    return {"weeks": [{"week": k, **v} for k, v in sorted(series.items())], "note": "The current week is partial."}


def period_comparison(db: Session, ws: uuid.UUID, days: int = 28) -> dict[str, Any]:
    """Current vs previous period for pipeline creation, decomposed by source campaign."""
    now = utcnow()
    cur_start, prev_start = now - timedelta(days=days), now - timedelta(days=2 * days)

    def by_campaign(a: datetime, b: datetime) -> dict[str, tuple[int, float]]:
        src = func.coalesce(Campaign.name, Opportunity.lead_source, "unattributed").label("src")
        rows = db.execute(
            select(src, func.count(), func.coalesce(func.sum(Opportunity.amount_usd), 0))
            .select_from(Opportunity)
            .outerjoin(Campaign, Campaign.id == Opportunity.source_campaign_id)
            .where(Opportunity.workspace_id == ws, Opportunity.opened_at >= a, Opportunity.opened_at < b)
            .group_by(src)
        ).all()
        return {r[0]: (r[1], float(r[2])) for r in rows}

    cur, prev = by_campaign(cur_start, now), by_campaign(prev_start, cur_start)
    keys = sorted(set(cur) | set(prev))
    rows = [
        {
            "key": k,
            "current_count": cur.get(k, (0, 0))[0],
            "previous_count": prev.get(k, (0, 0))[0],
            "current_pipeline": cur.get(k, (0, 0.0))[1],
            "previous_pipeline": prev.get(k, (0, 0.0))[1],
            "delta_pipeline": cur.get(k, (0, 0.0))[1] - prev.get(k, (0, 0.0))[1],
        }
        for k in keys
    ]
    rows.sort(key=lambda r: r["delta_pipeline"])

    def meetings(a: datetime, b: datetime) -> int:
        return (
            db.scalar(
                select(func.count())
                .select_from(Activity)
                .where(
                    Activity.workspace_id == ws,
                    Activity.type == "meeting_held",
                    Activity.occurred_at >= a,
                    Activity.occurred_at < b,
                )
            )
            or 0
        )

    def sends(a: datetime, b: datetime) -> int:
        return (
            db.scalar(
                select(func.count())
                .select_from(Activity)
                .where(
                    Activity.workspace_id == ws,
                    Activity.type == "email_sent",
                    Activity.occurred_at >= a,
                    Activity.occurred_at < b,
                )
            )
            or 0
        )

    return {
        "days": days,
        "current": {
            "opportunities": sum(v[0] for v in cur.values()),
            "pipeline": sum(v[1] for v in cur.values()),
            "meetings": meetings(cur_start, now),
            "emails_sent": sends(cur_start, now),
        },
        "previous": {
            "opportunities": sum(v[0] for v in prev.values()),
            "pipeline": sum(v[1] for v in prev.values()),
            "meetings": meetings(prev_start, cur_start),
            "emails_sent": sends(prev_start, cur_start),
        },
        "by_source": rows,
    }


def velocity(db: Session, ws: uuid.UUID, days: int = 180) -> dict[str, Any]:
    since = _since(days)
    closed = db.execute(
        select(Opportunity.stage, Opportunity.amount_usd, Opportunity.opened_at, Opportunity.closed_at).where(
            Opportunity.workspace_id == ws,
            Opportunity.closed_at >= since,
            Opportunity.stage.in_(["closed_won", "closed_lost"]),
        )
    ).all()
    won = [r for r in closed if r.stage == "closed_won"]
    win_rate = len(won) / len(closed) if closed else 0.0
    avg_deal = statistics.mean(float(r.amount_usd) for r in won) if won else 0.0
    cycle = statistics.median((r.closed_at - r.opened_at).days for r in won) if won else None
    open_n = (
        db.scalar(
            select(func.count())
            .select_from(Opportunity)
            .where(Opportunity.workspace_id == ws, Opportunity.stage.in_(OPEN_DEAL))
        )
        or 0
    )
    vel = (open_n * win_rate * avg_deal / cycle) if cycle else None
    # Stage-to-stage durations from the transition log
    trans = db.execute(
        select(StageTransition.entity_id, StageTransition.to_stage, StageTransition.changed_at)
        .where(
            StageTransition.workspace_id == ws,
            StageTransition.pipeline == "funnel",
            StageTransition.changed_at >= since,
        )
        .order_by(StageTransition.entity_id, StageTransition.changed_at)
    ).all()
    first_at: dict[uuid.UUID, dict[str, datetime]] = defaultdict(dict)
    for eid, st, at in trans:
        first_at[eid].setdefault(st, at)
    pairs = [
        ("contacted", "engaged"),
        ("engaged", "qualified"),
        ("qualified", "meeting"),
        ("meeting", "opportunity"),
        ("opportunity", "won"),
    ]
    durations = []
    for a, b in pairs:
        ds = [(v[b] - v[a]).total_seconds() / 86400 for v in first_at.values() if a in v and b in v and v[b] >= v[a]]
        durations.append(
            {"from": a, "to": b, "accounts": len(ds), "median_days": round(statistics.median(ds), 1) if ds else None}
        )
    return {
        "window_days": days,
        "closed_deals": len(closed),
        "win_rate": round(win_rate, 4),
        "avg_won_deal": round(avg_deal, 2),
        "median_cycle_days": cycle,
        "open_opportunities": open_n,
        "pipeline_velocity_per_day": round(vel, 2) if vel else None,
        "formula": "open opportunities × win rate × average won deal ÷ median sales cycle (days)",
        "stage_durations": durations,
        "low_sample": len(closed) < 20,
    }


STUCK_RULES = {
    "contacted": (21, "No reply 21+ days after first touch"),
    "engaged": (14, "Replied but not qualified for 14+ days"),
    "qualified": (10, "Qualified but no meeting for 10+ days"),
    "meeting": (14, "Meeting held but no opportunity for 14+ days"),
    "opportunity": (30, "Opportunity open 30+ days in stage"),
}


def stuck_accounts(db: Session, ws: uuid.UUID, limit: int = 50) -> dict[str, Any]:
    now = utcnow()
    last = (
        db.execute(
            select(StageTransition.entity_id, func.max(StageTransition.changed_at))
            .where(StageTransition.workspace_id == ws, StageTransition.pipeline == "funnel")
            .group_by(StageTransition.entity_id)
        )
        .tuples()
        .all()
    )
    last_at = dict(last)
    accounts = db.scalars(select(Account).where(_live(ws), Account.funnel_stage.in_(list(STUCK_RULES))))
    by_stage: dict[str, int] = defaultdict(int)
    unowned: dict[str, int] = defaultdict(int)
    rows = []
    for a in accounts:
        since = last_at.get(a.id)
        if since is None:
            continue
        days, why = STUCK_RULES[a.funnel_stage]
        age = (now - since).days
        if age < days:
            continue
        by_stage[a.funnel_stage] += 1
        if a.owner_id is None:
            unowned[a.funnel_stage] += 1
        rows.append(
            {
                "account_id": str(a.id),
                "name": a.name,
                "stage": a.funnel_stage,
                "days_in_stage": age,
                "rule": why,
                "owner_id": str(a.owner_id) if a.owner_id else None,
                "region": a.region,
                "icp_score": a.icp_score,
            }
        )
    rows.sort(key=lambda r: (-(r["icp_score"] or 0), -r["days_in_stage"]))
    from gtmos.models import User

    names = {str(k): v for k, v in db.execute(select(User.id, User.name).where(User.workspace_id == ws)).tuples()}
    for r in rows:
        r["owner"] = names.get(r["owner_id"]) if r["owner_id"] else None
    return {"by_stage": dict(by_stage), "unowned_by_stage": dict(unowned), "accounts": rows[:limit], "total": len(rows)}


def score_validation(db: Session, ws: uuid.UUID, days: int = 180) -> dict[str, Any]:
    """Does the score predict outcomes? Conversion by grade among contacted accounts."""
    b = breakdown(db, ws, "score_grade", days)
    order = {"A": 0, "B": 1, "C": 2, "D": 3, "X": 4, "unknown": 5}
    rows = sorted(b["rows"], key=lambda r: order.get(r["key"], 9))
    return {
        "window_days": days,
        "rows": rows,
        "note": "Grades are current scores. Past outcomes also feed engagement points, so this view "
        "slightly overstates predictive power; a holdout backtest would remove that bias.",
    }


def signal_correlation(db: Session, ws: uuid.UUID, days: int = 180) -> dict[str, Any]:
    """Opportunity rate for contacted accounts with vs without each signal type (association, not causation)."""
    since = _since(days)
    reached = _stage_reached(db, ws, since)
    contacted = {eid for eid, s in reached.items() if "contacted" in s}
    with_opp = {
        r[0]
        for r in db.execute(
            select(Opportunity.account_id).where(Opportunity.workspace_id == ws, Opportunity.opened_at >= since)
        )
    } & contacted
    base = len(with_opp) / len(contacted) if contacted else 0.0
    sig_accounts: dict[str, set[uuid.UUID]] = defaultdict(set)
    for acc, st in db.execute(
        select(Signal.account_id, Signal.signal_type).where(
            Signal.workspace_id == ws, Signal.observed_at >= since - timedelta(days=90)
        )
    ):
        if acc in contacted:
            sig_accounts[st].add(acc)
    rows = []
    for st, accs in sig_accounts.items():
        n = len(accs)
        opp = len(accs & with_opp)
        without = contacted - accs
        rate_without = len(without & with_opp) / len(without) if without else 0.0
        rate = opp / n if n else 0.0
        rows.append(
            {
                "signal_type": st,
                "label": SIGNAL_TYPES[st].name if st in SIGNAL_TYPES else st,
                "accounts": n,
                "with_opportunity": opp,
                "opportunity_rate": round(rate, 4),
                "rate_without_signal": round(rate_without, 4),
                "lift": round(rate / rate_without, 2) if rate_without else None,
                "low_sample": n < 30,
            }
        )
    rows.sort(key=lambda r: -(r["lift"] or 0))
    return {
        "window_days": days,
        "baseline_opportunity_rate": round(base, 4),
        "contacted_accounts": len(contacted),
        "rows": rows,
        "caveat": "Correlation only. Signal-triggered campaigns also target these accounts, "
        "so part of the lift is the campaign, not the signal.",
    }


def owner_load(db: Session, ws: uuid.UUID) -> list[dict[str, Any]]:
    from gtmos.models import User

    rows = db.execute(
        select(
            User.id,
            User.name,
            User.team,
            User.capacity,
            User.is_active,
            func.count(Account.id).filter(Account.funnel_stage.not_in(["won", "lost"])),
        )
        .outerjoin(Account, and_(Account.owner_id == User.id, Account.merged_into_id.is_(None)))
        .where(User.workspace_id == ws)
        .group_by(User.id)
        .order_by(User.team, User.name)
    ).all()
    return [
        {
            "user_id": str(r[0]),
            "name": r[1],
            "team": r[2],
            "capacity": r[3],
            "is_active": r[4],
            "open_accounts": r[5],
            "utilization": round(r[5] / r[3], 3) if r[3] else None,
        }
        for r in rows
    ]


def activity_mix(db: Session, ws: uuid.UUID, days: int = 30) -> dict[str, int]:
    since = _since(days)
    return dict(
        db.execute(
            select(Activity.type, func.count())
            .where(Activity.workspace_id == ws, Activity.occurred_at >= since)
            .group_by(Activity.type)
        )
        .tuples()
        .all()
    )


_ = case  # re-exported for callers building ad-hoc CASE expressions
