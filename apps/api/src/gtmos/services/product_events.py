"""Product-led signals: product event → account match → engagement → signal → score → PQL workflow."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gtmos.domain.matching import match_to_account, normalize_domain, normalize_email
from gtmos.integrations.posthog import (
    EVENT_SIGNAL_MAP,
    PQL_SIGNALS,
    PRICING_EVENTS,
    NormalizedEvent,
)
from gtmos.models import Account, Contact, Engagement
from gtmos.services.signal_service import ingest_signal

PRICING_WINDOW = timedelta(days=7)
PRICING_THRESHOLD = 2

SIGNAL_TITLES = {
    "product_signup": "Created a free Sentinel workspace",
    "teammate_invited": "Invited teammates to the free workspace",
    "integration_activated": "Connected a production integration",
    "usage_threshold": "Crossed the free-tier trace volume threshold",
}


def _known_domains(db: Session, workspace_id: uuid.UUID, candidates: set[str]) -> dict[str, Account]:
    if not candidates:
        return {}
    # Include parent domains so subdomain emails (eu.acme.example) can match acme.example.
    expanded = set(candidates)
    for d in candidates:
        parts = d.split(".")
        expanded.update(".".join(parts[i:]) for i in range(1, len(parts) - 1))
    rows = db.scalars(
        select(Account).where(
            Account.workspace_id == workspace_id, Account.domain.in_(expanded), Account.merged_into_id.is_(None)
        )
    )
    return {a.domain: a for a in rows if a.domain}


def ingest_events(
    db: Session,
    workspace_id: uuid.UUID,
    events: list[NormalizedEvent],
    *,
    data_origin: str = "live",
    run_workflows: bool = True,
) -> list[dict[str, Any]]:
    candidates: set[str] = set()
    for e in events:
        if g := normalize_domain(e.company_domain):
            candidates.add(g)
        if (em := normalize_email(e.email)) and "@" in em:
            candidates.add(em.split("@", 1)[1])
    accounts = _known_domains(db, workspace_id, candidates)
    results: list[dict[str, Any]] = []
    for e in events:
        m = match_to_account(set(accounts), email=e.email, group_domain=e.company_domain)
        out: dict[str, Any] = {
            "event_id": e.event_id,
            "event": e.event,
            "match": m.method,
            "match_reason": m.reason,
            "account_id": None,
            "signal": None,
            "workflow_runs": [],
        }
        dedupe = f"posthog:{e.event_id}"[:200]
        if db.scalars(select(Engagement.id).where(Engagement.dedupe_key == dedupe)).first():
            out["duplicate"] = True
            results.append(out)
            continue
        account = accounts.get(m.account_key) if m.account_key else None
        contact = None
        if account and (em := normalize_email(e.email)):
            contact = db.scalars(
                select(Contact).where(Contact.account_id == account.id, func.lower(Contact.email) == em)
            ).first()
        db.add(
            Engagement(
                workspace_id=workspace_id,
                account_id=account.id if account else None,
                contact_id=contact.id if contact else None,
                event_name=e.event,
                distinct_id=e.distinct_id,
                occurred_at=e.occurred_at,
                properties=e.properties,
                source="posthog",
                data_origin=data_origin,
                dedupe_key=dedupe,
            )
        )
        db.flush()
        if account is None:
            results.append(out)
            continue
        out["account_id"] = str(account.id)
        sig_type = EVENT_SIGNAL_MAP.get(e.event)
        source_ref = e.event_id
        title = SIGNAL_TITLES.get(sig_type or "", "")
        if e.event in PRICING_EVENTS:
            n = (
                db.scalar(
                    select(func.count())
                    .select_from(Engagement)
                    .where(
                        Engagement.account_id == account.id,
                        Engagement.event_name.in_(PRICING_EVENTS),
                        Engagement.occurred_at >= e.occurred_at - PRICING_WINDOW,
                        Engagement.occurred_at <= e.occurred_at,
                    )
                )
                or 0
            )
            if n >= PRICING_THRESHOLD:
                sig_type = "pricing_page_visit"
                week = e.occurred_at.isocalendar()
                source_ref = f"pricing:{week.year}-W{week.week}"  # one pricing signal per account-week
                title = f"Viewed pricing {n} times in 7 days"
        if sig_type:
            who = contact.full_name if contact else (e.email or e.distinct_id or "an unknown user")
            res = ingest_signal(
                db,
                account,
                run_workflows=run_workflows,
                signal_type=sig_type,
                observed_at=e.occurred_at,
                source="posthog",
                title=title,
                source_ref=source_ref,
                confidence=0.95,
                explanation=f"{title} (product event '{e.event}' by {who}).",
                evidence={
                    "event": e.event,
                    "event_id": e.event_id,
                    "distinct_id": e.distinct_id,
                    "properties": {k: v for k, v in e.properties.items() if k != "email"},
                },
                contact_id=contact.id if contact else None,
                data_origin=data_origin,
            )
            out["signal"] = {
                "id": str(res.signal.id),
                "type": sig_type,
                "created": res.created,
                "score_before": res.score_before,
                "score_after": res.score_after,
            }
            out["workflow_runs"] = res.workflow_runs or []
            if res.created and sig_type in PQL_SIGNALS and run_workflows:
                from gtmos.services.workflow_engine import emit_event

                runs = emit_event(
                    db,
                    workspace_id,
                    "product.pql",
                    str(res.signal.id),
                    account,
                    {"pql": {"event": e.event, "signal_id": str(res.signal.id)}},
                    data_origin=data_origin,
                )
                out["workflow_runs"] += [str(r.id) for r in runs]
        results.append(out)
    return results


def recent_product_activity(db: Session, account_id: uuid.UUID, since: datetime) -> dict[str, int]:
    rows = db.execute(
        select(Engagement.event_name, func.count())
        .where(Engagement.account_id == account_id, Engagement.occurred_at >= since)
        .group_by(Engagement.event_name)
    )
    return dict(rows.tuples().all())
