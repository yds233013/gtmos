"""Persists buying-committee inference while preserving manual overrides."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from gtmos.domain.committee import ROLE_LABELS, ContactFacts, infer_committee
from gtmos.models import Account, AccountContactRole, Activity, Contact, Engagement
from gtmos.services.common import Conflict, NotFound, audit


def _contact_facts(db: Session, account_id: uuid.UUID | None, contacts: list[Contact]) -> list[ContactFacts]:
    ids = [c.id for c in contacts]
    acts = db.execute(
        select(Activity.contact_id, Activity.type, func.count())
        .where(Activity.contact_id.in_(ids), Activity.type.in_(["email_replied", "positive_reply", "meeting_held"]))
        .group_by(Activity.contact_id, Activity.type)
    ).all()
    replied: set[uuid.UUID] = set()
    meetings: dict[uuid.UUID, int] = defaultdict(int)
    for cid, typ, n in acts:
        if typ in ("email_replied", "positive_reply"):
            replied.add(cid)
        else:
            meetings[cid] += n
    product_users = set(
        db.scalars(
            select(Engagement.contact_id)
            .where(
                Engagement.contact_id.in_(ids),
                Engagement.source.in_(["posthog", "demo_seed"]),
                Engagement.event_name.in_(
                    ["workspace_created", "trace_logged", "teammate_invited", "integration_connected"]
                ),
            )
            .distinct()
        )
    )
    return [
        ContactFacts(
            str(c.id),
            c.full_name,
            c.title,
            c.seniority,
            c.department,
            c.email_status,
            c.id in replied,
            meetings.get(c.id, 0),
            c.id in product_users,
            c.do_not_contact,
        )
        for c in contacts
    ]


def recompute_committee(db: Session, account: Account) -> list[AccountContactRole]:
    contacts = list(
        db.scalars(select(Contact).where(Contact.account_id == account.id, Contact.merged_into_id.is_(None)))
    )
    manual = list(
        db.scalars(
            select(AccountContactRole).where(
                AccountContactRole.account_id == account.id, AccountContactRole.is_manual_override.is_(True)
            )
        )
    )
    overrides = {m.role: str(m.contact_id) for m in manual}
    result = infer_committee(_contact_facts(db, account.id, contacts), overrides)
    db.execute(
        delete(AccountContactRole).where(
            AccountContactRole.account_id == account.id, AccountContactRole.is_manual_override.is_(False)
        )
    )
    rows: list[AccountContactRole] = []
    for a in result.assignments:
        if a.is_manual_override:
            continue
        rows.append(
            AccountContactRole(
                account_id=account.id,
                contact_id=uuid.UUID(a.contact_id),
                role=a.role,
                rank=a.rank,
                score=a.score,
                confidence=a.confidence,
                rationale=a.reasons,
            )
        )
    db.add_all(rows)
    db.flush()
    return manual + rows


def override_role(db: Session, account: Account, role: str, contact_id: uuid.UUID, actor: str) -> AccountContactRole:
    if role not in ROLE_LABELS:
        raise Conflict(f"unknown role '{role}'")
    contact = db.get(Contact, contact_id)
    if contact is None or contact.account_id != account.id:
        raise NotFound("contact not found on this account")
    prev = db.scalars(
        select(AccountContactRole).where(
            AccountContactRole.account_id == account.id, AccountContactRole.role == role, AccountContactRole.rank == 1
        )
    ).first()
    before = {"contact_id": str(prev.contact_id)} if prev else None
    db.execute(
        delete(AccountContactRole).where(
            AccountContactRole.account_id == account.id,
            AccountContactRole.role == role,
            AccountContactRole.is_manual_override.is_(True),
        )
    )
    row = AccountContactRole(
        account_id=account.id,
        contact_id=contact_id,
        role=role,
        rank=1,
        score=100,
        confidence=1.0,
        rationale=[f"Manually assigned by {actor}"],
        is_manual_override=True,
        overridden_by=actor,
    )
    db.add(row)
    db.flush()
    audit(
        db,
        account.workspace_id,
        "committee.role_overridden",
        "account",
        account.id,
        before=before,
        after={"role": role, "contact_id": str(contact_id)},
        reason="manual override",
    )
    recompute_committee(db, account)
    return row


def clear_override(db: Session, account: Account, role: str) -> None:
    db.execute(
        delete(AccountContactRole).where(
            AccountContactRole.account_id == account.id,
            AccountContactRole.role == role,
            AccountContactRole.is_manual_override.is_(True),
        )
    )
    audit(db, account.workspace_id, "committee.override_cleared", "account", account.id, after={"role": role})
    recompute_committee(db, account)


def recompute_committees_bulk(db: Session, accounts: list[Account]) -> int:
    """Batch version for backfills/seeding: a few queries per 500 accounts instead of several per account."""
    from sqlalchemy import insert

    written = 0
    for i in range(0, len(accounts), 500):
        chunk = accounts[i : i + 500]
        ids = [a.id for a in chunk]
        contacts = list(
            db.scalars(select(Contact).where(Contact.account_id.in_(ids), Contact.merged_into_id.is_(None)))
        )
        facts = {f.id: f for f in _contact_facts(db, None, contacts)}
        by_acct: dict[uuid.UUID, list[ContactFacts]] = defaultdict(list)
        for c in contacts:
            if c.account_id:
                by_acct[c.account_id].append(facts[str(c.id)])
        manual: dict[uuid.UUID, dict[str, str]] = defaultdict(dict)
        for m in db.scalars(
            select(AccountContactRole).where(
                AccountContactRole.account_id.in_(ids), AccountContactRole.is_manual_override.is_(True)
            )
        ):
            manual[m.account_id][m.role] = str(m.contact_id)
        db.execute(
            delete(AccountContactRole).where(
                AccountContactRole.account_id.in_(ids), AccountContactRole.is_manual_override.is_(False)
            )
        )
        rows = []
        for a in chunk:
            result = infer_committee(by_acct.get(a.id, []), manual.get(a.id))
            for r in result.assignments:
                if not r.is_manual_override:
                    rows.append(
                        {
                            "id": uuid.uuid4(),
                            "account_id": a.id,
                            "contact_id": uuid.UUID(r.contact_id),
                            "role": r.role,
                            "rank": r.rank,
                            "score": r.score,
                            "confidence": r.confidence,
                            "rationale": r.reasons,
                            "is_manual_override": False,
                        }
                    )
        if rows:
            db.execute(insert(AccountContactRole), rows)
            written += len(rows)
    return written
