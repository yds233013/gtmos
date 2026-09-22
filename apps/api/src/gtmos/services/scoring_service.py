"""Loads scoring facts from the database, runs the pure scoring engine, persists explainable results."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from gtmos.domain.icp import ICPDefinition, default_icp
from gtmos.domain.scoring import (
    AccountFacts,
    EngagementFacts,
    ScoreResult,
    SignalFact,
    intent_index,
    score_account,
)
from gtmos.models import Account, Activity, ICPProfile, ICPScore, ScoreComponent, Signal
from gtmos.services.common import audit, utcnow

A_GRADE_THRESHOLD = 80
SIGNAL_LOOKBACK = timedelta(days=365)


def active_icp(db: Session, workspace_id: uuid.UUID) -> tuple[ICPProfile, ICPDefinition]:
    row = db.scalars(
        select(ICPProfile)
        .where(ICPProfile.workspace_id == workspace_id, ICPProfile.is_active.is_(True))
        .order_by(ICPProfile.version.desc())
    ).first()
    if row is None:
        row = ICPProfile(
            workspace_id=workspace_id,
            name=default_icp().name,
            version=1,
            is_active=True,
            definition=default_icp().model_dump(mode="json"),
        )
        db.add(row)
        db.flush()
    return row, ICPDefinition.model_validate(row.definition)


def account_facts(a: Account) -> AccountFacts:
    return AccountFacts(
        name=a.name,
        domain=a.domain,
        industry=a.industry,
        employee_count=a.employee_count,
        region=a.region,
        country=a.country,
        employee_growth_12m=a.employee_growth_12m,
        technologies=tuple(a.technologies or ()),
        ai_team_size=a.ai_team_size,
        is_customer=a.is_customer,
    )


def load_signal_facts(db: Session, account_ids: list[uuid.UUID], now: datetime) -> dict[uuid.UUID, list[SignalFact]]:
    out: dict[uuid.UUID, list[SignalFact]] = defaultdict(list)
    rows = db.execute(
        select(
            Signal.id,
            Signal.account_id,
            Signal.signal_type,
            Signal.observed_at,
            Signal.strength,
            Signal.confidence,
            Signal.title,
        ).where(Signal.account_id.in_(account_ids), Signal.observed_at >= now - SIGNAL_LOOKBACK)
    ).all()
    for r in rows:
        out[r.account_id].append(SignalFact(str(r.id), r.signal_type, r.observed_at, r.strength, r.confidence, r.title))
    return out


def load_engagement_facts(db: Session, account_ids: list[uuid.UUID], now: datetime) -> dict[uuid.UUID, EngagementFacts]:
    since = now - timedelta(days=90)
    rows = db.execute(
        select(Activity.account_id, Activity.type, func.count())
        .where(
            Activity.account_id.in_(account_ids),
            Activity.occurred_at >= since,
            Activity.occurred_at <= now,
            Activity.type.in_(["email_replied", "positive_reply", "meeting_held"]),
        )
        .group_by(Activity.account_id, Activity.type)
    ).all()
    counts: dict[uuid.UUID, dict[str, int]] = defaultdict(dict)
    for acc, typ, n in rows:
        counts[acc][typ] = n
    return {
        acc: EngagementFacts(
            replies_90d=c.get("email_replied", 0),
            positive_replies_90d=c.get("positive_reply", 0),
            meetings_90d=c.get("meeting_held", 0),
        )
        for acc, c in counts.items()
    }


@dataclass
class RescoreOutcome:
    account_id: uuid.UUID
    old_total: int | None
    result: ScoreResult
    score_id: uuid.UUID

    @property
    def crossed_a_grade(self) -> bool:
        return (self.old_total or 0) < A_GRADE_THRESHOLD <= self.result.total


def rescore_accounts(
    db: Session,
    workspace_id: uuid.UUID,
    account_ids: list[uuid.UUID] | None = None,
    *,
    trigger: str = "manual",
    now: datetime | None = None,
    write_audit: bool = True,
) -> list[RescoreOutcome]:
    now = now or utcnow()
    profile, icp = active_icp(db, workspace_id)
    q = select(Account).where(Account.workspace_id == workspace_id, Account.merged_into_id.is_(None))
    if account_ids is not None:
        q = q.where(Account.id.in_(account_ids))
    accounts = list(db.scalars(q))
    if not accounts:
        return []
    ids = [a.id for a in accounts]
    outcomes: list[RescoreOutcome] = []
    for start in range(0, len(ids), 500):
        chunk_ids = ids[start : start + 500]
        chunk = [a for a in accounts if a.id in set(chunk_ids)]
        signals = load_signal_facts(db, chunk_ids, now)
        engagement = load_engagement_facts(db, chunk_ids, now)
        db.execute(
            update(ICPScore)
            .where(ICPScore.account_id.in_(chunk_ids), ICPScore.is_current.is_(True))
            .values(is_current=False)
        )
        score_rows: list[dict[str, Any]] = []
        comp_rows: list[dict[str, Any]] = []
        for a in chunk:
            res = score_account(
                icp, account_facts(a), signals.get(a.id, []), engagement.get(a.id, EngagementFacts()), now
            )
            sid = uuid.uuid4()
            score_rows.append(
                {
                    "id": sid,
                    "workspace_id": workspace_id,
                    "account_id": a.id,
                    "icp_profile_id": profile.id,
                    "icp_version": profile.version,
                    "total": res.total,
                    "grade": res.grade,
                    "fit": res.categories["fit"].points,
                    "intent": res.categories["intent"].points,
                    "timing": res.categories["timing"].points,
                    "technical": res.categories["technical"].points,
                    "engagement": res.categories["engagement"].points,
                    "excluded": res.excluded,
                    "exclusion_reason": res.exclusion_reason,
                    "summary": res.summary,
                    "inputs_hash": res.inputs_hash,
                    "computed_at": now,
                    "trigger": trigger,
                    "is_current": True,
                }
            )
            for c in res.components():
                comp_rows.append(
                    {
                        "id": uuid.uuid4(),
                        "icp_score_id": sid,
                        "category": c.category,
                        "key": c.key,
                        "label": c.label,
                        "points": c.points,
                        "max_points": c.max_points,
                        "explanation": c.explanation,
                        "evidence": c.evidence,
                    }
                )
            old = a.icp_score
            a.icp_score = res.total
            a.score_grade = res.grade
            a.intent_score = intent_index(res)
            a.score_updated_at = now
            outcomes.append(RescoreOutcome(a.id, old, res, sid))
            if write_audit and account_ids is not None and len(account_ids) <= 5 and old != res.total:
                audit(
                    db,
                    workspace_id,
                    "score.recalculated",
                    "account",
                    a.id,
                    before={"icp_score": old},
                    after={"icp_score": res.total, "grade": res.grade},
                    reason=f"trigger={trigger}; ICP v{profile.version}",
                    actor_type="system",
                )
        db.execute(insert(ICPScore), score_rows)
        if comp_rows:
            db.execute(insert(ScoreComponent), comp_rows)
    db.flush()
    if write_audit and (account_ids is None or len(account_ids) > 5):
        audit(
            db,
            workspace_id,
            "score.bulk_recalculated",
            "icp_profile",
            profile.id,
            after={"accounts": len(outcomes), "icp_version": profile.version},
            reason=f"trigger={trigger}",
            actor_type="system",
        )
    return outcomes


def current_score(db: Session, account_id: uuid.UUID) -> tuple[ICPScore, list[ScoreComponent]] | None:
    s = db.scalars(
        select(ICPScore)
        .where(ICPScore.account_id == account_id, ICPScore.is_current.is_(True))
        .order_by(ICPScore.computed_at.desc())
    ).first()
    if s is None:
        return None
    comps = list(db.scalars(select(ScoreComponent).where(ScoreComponent.icp_score_id == s.id)))
    return s, comps


def preview_icp(
    db: Session, workspace_id: uuid.UUID, icp: ICPDefinition, limit: int = 2000, now: datetime | None = None
) -> dict[str, Any]:
    """Score accounts under a draft ICP without saving: grade distribution and biggest movers."""
    now = now or utcnow()
    accounts = list(
        db.scalars(
            select(Account).where(Account.workspace_id == workspace_id, Account.merged_into_id.is_(None)).limit(limit)
        )
    )
    ids = [a.id for a in accounts]
    signals = load_signal_facts(db, ids, now)
    engagement = load_engagement_facts(db, ids, now)
    dist: dict[str, int] = defaultdict(int)
    movers = []
    for a in accounts:
        r = score_account(icp, account_facts(a), signals.get(a.id, []), engagement.get(a.id, EngagementFacts()), now)
        dist[r.grade] += 1
        movers.append((r.total - (a.icp_score or 0), a, r))
    movers = [m for m in movers if m[0] != 0]
    movers.sort(key=lambda m: (-abs(m[0]), m[1].name))
    return {
        "accounts_scored": len(accounts),
        "grade_distribution": dict(sorted(dist.items())),
        "current_distribution": dict(
            sorted(
                db.execute(
                    select(Account.score_grade, func.count())
                    .where(Account.workspace_id == workspace_id, Account.merged_into_id.is_(None))
                    .group_by(Account.score_grade)
                )
                .tuples()
                .all(),
                key=lambda t: str(t[0]),
            )
        ),
        "biggest_movers": [
            {"account_id": str(a.id), "name": a.name, "from": a.icp_score, "to": r.total, "delta": d}
            for d, a, r in movers[:10]
        ],
    }
