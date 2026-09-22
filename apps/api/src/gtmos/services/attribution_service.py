"""Builds touches from activities and runs every attribution model side by side."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gtmos.domain.attribution import MODELS, OpportunityFacts, Touch, attribute
from gtmos.models import Activity, Campaign, Opportunity
from gtmos.services.common import utcnow

# Activities that count as marketing/sales touches. Opens are excluded (unreliable).
TOUCH_TYPES = ("email_sent", "email_replied", "meeting_held", "webinar_attended", "linkedin")


def run(db: Session, ws: uuid.UUID, days: int = 180) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    opps = list(db.scalars(select(Opportunity).where(Opportunity.workspace_id == ws, Opportunity.opened_at >= since)))
    facts = [OpportunityFacts(str(o.id), float(o.amount_usd or 0), o.opened_at, o.stage == "closed_won") for o in opps]
    acct_opps: dict[uuid.UUID, list[str]] = defaultdict(list)
    for o in opps:
        acct_opps[o.account_id].append(str(o.id))
    names = dict(db.execute(select(Campaign.id, Campaign.name).where(Campaign.workspace_id == ws)).tuples().all())
    touches_by_acct: dict[uuid.UUID, list[Touch]] = defaultdict(list)
    seen: set[tuple[uuid.UUID, uuid.UUID | None, str]] = set()
    for a in db.execute(
        select(
            Activity.id,
            Activity.account_id,
            Activity.campaign_id,
            Activity.channel,
            Activity.occurred_at,
            Activity.type,
        )
        .where(Activity.account_id.in_(list(acct_opps)), Activity.type.in_(TOUCH_TYPES))
        .order_by(Activity.occurred_at)
    ):
        # Collapse repeated sends of one campaign on one day into a single touch.
        day_key = (a.account_id, a.campaign_id, f"{a.type}:{a.occurred_at.date()}")
        if day_key in seen:
            continue
        seen.add(day_key)
        label = names.get(a.campaign_id) if a.campaign_id else f"Direct: {a.channel or a.type}"
        touches_by_acct[a.account_id].append(Touch(label or "Unknown", a.occurred_at, str(a.id)))
    touches_by_opp = {oid: touches_by_acct[acc] for acc, oids in acct_opps.items() for oid in oids}
    results = {m: attribute(m, facts, touches_by_opp) for m in MODELS}
    keys = sorted({k for r in results.values() for k in r.pipeline_by_key})
    table = [
        {
            "key": k,
            **{m: results[m].pipeline_by_key.get(k, 0.0) for m in MODELS},
            **{f"{m}_won": results[m].won_by_key.get(k, 0.0) for m in MODELS},
        }
        for k in keys
    ]
    table.sort(key=lambda r: -r["linear"])
    first = results["first_touch"]
    total = first.total_pipeline
    return {
        "window_days": days,
        "models": list(MODELS),
        "opportunities": len(opps),
        "total_pipeline": total,
        "unattributed_opportunities": first.unattributed_opportunities,
        "unattributed_pipeline": first.unattributed_pipeline,
        "attributed_share": round(1 - first.unattributed_pipeline / total, 4) if total else None,
        "rows": table,
        "limitations": [
            "Touches are GTMOS-recorded activities only; offline, partner, word-of-mouth and ad touches are invisible.",
            "Account-level: every contact's touches at the account count toward the account's opportunities.",
            "180-day lookback before opportunity creation; later touches are influence, not sourcing.",
            "Email opens are excluded; they are unreliable signals of attention.",
            "No model is causal. Use the experiments page for causal claims.",
        ],
    }
