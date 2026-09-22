"""Data-quality rules, issue lifecycle and remediation.

Each rule is a query over current CRM state that yields issue candidates with a stable fingerprint.
A scan upserts candidates (new → open, still present → last_seen updated) and auto-resolves open issues
that are no longer detected. Remediations are explicit, audited actions such as merging duplicates,
routing unowned accounts, or suppressing invalid emails. Nothing is changed silently.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from gtmos.domain.matching import is_valid_email, normalize_company_name, normalize_domain
from gtmos.domain.pipeline import FUNNEL_TO_LIFECYCLE, invalid_history_transitions
from gtmos.models import (
    Account,
    AccountContactRole,
    Activity,
    Contact,
    DataQualityIssue,
    Engagement,
    MessageDraft,
    Opportunity,
    Signal,
    StageTransition,
)
from gtmos.services.common import Conflict, NotFound, audit, utcnow

STALE_ENRICHMENT = timedelta(days=180)

RULES: dict[str, dict[str, str]] = {
    "duplicate_contact": {
        "label": "Duplicate contacts",
        "severity": "high",
        "why": "Duplicates split activity history and cause double outreach.",
    },
    "duplicate_account": {
        "label": "Duplicate accounts",
        "severity": "high",
        "why": "Duplicate accounts split pipeline and break routing and attribution.",
    },
    "missing_domain": {
        "label": "Missing domain",
        "severity": "high",
        "why": "Without a domain we cannot enrich, match leads, or upsert to the CRM.",
    },
    "invalid_email": {
        "label": "Invalid emails",
        "severity": "medium",
        "why": "Sending to invalid addresses hurts deliverability and sender reputation.",
    },
    "missing_employee_count": {
        "label": "Missing employee count",
        "severity": "medium",
        "why": "Size drives fit scoring, segmentation and routing.",
    },
    "stale_enrichment": {
        "label": "Stale enrichment",
        "severity": "low",
        "why": "Firmographics older than 180 days drift (headcount, funding, stack).",
    },
    "orphan_contact": {
        "label": "Orphan contacts",
        "severity": "medium",
        "why": "Contacts without an account can't be routed or scored.",
    },
    "lifecycle_conflict": {
        "label": "Conflicting lifecycle states",
        "severity": "medium",
        "why": "Lifecycle and funnel disagree, so reports double count or miss records.",
    },
    "missing_owner": {
        "label": "High-fit accounts without owner",
        "severity": "high",
        "why": "Unowned A/B accounts receive no follow-up: direct pipeline leakage.",
    },
    "invalid_pipeline_transition": {
        "label": "Invalid pipeline transitions",
        "severity": "medium",
        "why": "Stage skips or reversals corrupt conversion and velocity metrics.",
    },
    "bad_external_id": {
        "label": "Bad CRM external IDs",
        "severity": "high",
        "why": "Malformed or duplicated CRM IDs make sync create or overwrite the wrong record.",
    },
}


@dataclass
class Candidate:
    rule_key: str
    entity_type: str
    entity_id: uuid.UUID | None
    title: str
    details: dict[str, Any] = field(default_factory=dict)
    suggested_fix: dict[str, Any] = field(default_factory=dict)
    related_ids: list[str] = field(default_factory=list)
    key: str = ""

    @property
    def fingerprint(self) -> str:
        raw = f"{self.rule_key}|{self.entity_type}|{self.key or self.entity_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:40]


def _live_accounts(db: Session, ws: uuid.UUID) -> list[Account]:
    return list(db.scalars(select(Account).where(Account.workspace_id == ws, Account.merged_into_id.is_(None))))


def _live_contacts(db: Session, ws: uuid.UUID) -> list[Contact]:
    return list(db.scalars(select(Contact).where(Contact.workspace_id == ws, Contact.merged_into_id.is_(None))))


def rule_duplicate_contacts(db: Session, ws: uuid.UUID, now: datetime) -> list[Candidate]:
    """Two passes: same normalized email, then same person (name) on the same account with other emails."""
    contacts = _live_contacts(db, ws)
    by_email: dict[str, list[Contact]] = defaultdict(list)
    by_name: dict[str, list[Contact]] = defaultdict(list)
    for c in contacts:
        if c.email and c.email.strip():
            by_email[f"email:{c.email.strip().lower()}"].append(c)
        if c.account_id and c.first_name and c.last_name:
            by_name[f"name:{c.account_id}:{c.first_name.lower()} {c.last_name.lower()}"].append(c)
    groups: list[tuple[str, list[Contact]]] = [(k, v) for k, v in by_email.items() if len(v) > 1]
    covered = {frozenset(c.id for c in v) for _, v in groups}
    for k, v in by_name.items():
        if len(v) > 1 and frozenset(c.id for c in v) not in covered:
            emails = {(c.email or "").strip().lower() for c in v}
            if len(emails) > 1:
                groups.append((k, v))
    out = []
    for key, cs in groups:
        cs.sort(key=lambda c: (c.email_status != "valid", c.created_at, str(c.id)))
        primary, dupes = cs[0], cs[1:]
        label = key.split(":", 1)[1] if key.startswith("email:") else primary.full_name
        out.append(
            Candidate(
                "duplicate_contact",
                "contact",
                primary.id,
                f"{len(cs)} records for {primary.full_name} ({label})",
                {
                    "match_key": key.split(":", 1)[0],
                    "records": [{"id": str(c.id), "email": c.email, "title": c.title} for c in cs],
                },
                {
                    "action": "merge_contacts",
                    "params": {"primary_id": str(primary.id), "duplicate_ids": [str(d.id) for d in dupes]},
                    "description": f"Merge {len(dupes)} duplicate(s) into the oldest valid record; activities, roles "
                    "and engagements move to the primary.",
                },
                [str(d.id) for d in dupes],
                key,
            )
        )
    return out


def rule_duplicate_accounts(db: Session, ws: uuid.UUID, now: datetime) -> list[Candidate]:
    """Same normalized domain, or same normalized company name (catches domain-less duplicates)."""
    accounts = _live_accounts(db, ws)
    by_domain: dict[str, list[Account]] = defaultdict(list)
    by_name: dict[str, list[Account]] = defaultdict(list)
    for a in accounts:
        if d := normalize_domain(a.domain):
            by_domain[f"domain:{d}"].append(a)
        if n := normalize_company_name(a.name):
            by_name[f"name:{n}"].append(a)
    groups: list[tuple[str, list[Account]]] = [(k, v) for k, v in by_domain.items() if len(v) > 1]
    covered = {frozenset(a.id for a in v) for _, v in groups}
    for k, v in by_name.items():
        if len(v) > 1 and frozenset(a.id for a in v) not in covered:
            domains = {normalize_domain(a.domain) for a in v}
            if len(domains - {None}) <= 1:  # different real domains = different companies with similar names
                groups.append((k, v))
    out = []
    for key, accs in groups:
        accs.sort(key=lambda a: (a.domain is None, -(a.icp_score or 0), a.created_at, str(a.id)))
        primary, dupes = accs[0], accs[1:]
        out.append(
            Candidate(
                "duplicate_account",
                "account",
                primary.id,
                f"{len(accs)} account records for {primary.name}",
                {
                    "match_key": key.split(":", 1)[0],
                    "records": [{"id": str(a.id), "name": a.name, "domain": a.domain} for a in accs],
                },
                {
                    "action": "merge_accounts",
                    "params": {"primary_id": str(primary.id), "duplicate_ids": [str(d.id) for d in dupes]},
                    "description": "Merge into the record with a clean domain; contacts, signals, activities and "
                    "opportunities are re-parented.",
                },
                [str(d.id) for d in dupes],
                key,
            )
        )
    return out


def rule_missing_domain(db: Session, ws: uuid.UUID, now: datetime) -> list[Candidate]:
    return [
        Candidate(
            "missing_domain",
            "account",
            a.id,
            f"{a.name} has no domain",
            {"name": a.name},
            {"action": "manual", "description": "Add the company website; then run enrichment."},
        )
        for a in _live_accounts(db, ws)
        if not normalize_domain(a.domain)
    ]


def rule_invalid_email(db: Session, ws: uuid.UUID, now: datetime) -> list[Candidate]:
    out = []
    for c in _live_contacts(db, ws):
        if c.email and (not is_valid_email(c.email) or c.email_status == "invalid") and not c.do_not_contact:
            out.append(
                Candidate(
                    "invalid_email",
                    "contact",
                    c.id,
                    f"Invalid email for {c.full_name}: {c.email}",
                    {"email": c.email, "email_status": c.email_status},
                    {
                        "action": "suppress_email",
                        "params": {"contact_id": str(c.id)},
                        "description": "Mark the email invalid and exclude the contact from sequences.",
                    },
                )
            )
    return out


def rule_missing_employee_count(db: Session, ws: uuid.UUID, now: datetime) -> list[Candidate]:
    return [
        Candidate(
            "missing_employee_count",
            "account",
            a.id,
            f"{a.name} is missing employee count",
            {"domain": a.domain},
            {
                "action": "enrich_account",
                "params": {"account_id": str(a.id)},
                "description": "Run the enrichment waterfall for this account.",
            },
        )
        for a in _live_accounts(db, ws)
        if a.employee_count is None and a.domain
    ]


def rule_stale_enrichment(db: Session, ws: uuid.UUID, now: datetime) -> list[Candidate]:
    out = []
    for a in _live_accounts(db, ws):
        if (
            a.domain
            and a.score_grade in ("A", "B", "C")
            and (a.last_enriched_at is None or now - a.last_enriched_at > STALE_ENRICHMENT)
        ):
            age = "never" if a.last_enriched_at is None else f"{(now - a.last_enriched_at).days} days ago"
            out.append(
                Candidate(
                    "stale_enrichment",
                    "account",
                    a.id,
                    f"{a.name} last enriched {age}",
                    {"last_enriched_at": a.last_enriched_at.isoformat() if a.last_enriched_at else None},
                    {
                        "action": "enrich_account",
                        "params": {"account_id": str(a.id)},
                        "description": "Refresh firmographics via the waterfall.",
                    },
                )
            )
    return out


def rule_orphan_contacts(db: Session, ws: uuid.UUID, now: datetime) -> list[Candidate]:
    return [
        Candidate(
            "orphan_contact",
            "contact",
            c.id,
            f"{c.full_name} ({c.email}) has no account",
            {"email": c.email},
            {
                "action": "match_contact_to_account",
                "params": {"contact_id": str(c.id)},
                "description": "Match by email domain to an existing account.",
            },
        )
        for c in _live_contacts(db, ws)
        if c.account_id is None
    ]


def rule_lifecycle_conflict(db: Session, ws: uuid.UUID, now: datetime) -> list[Candidate]:
    out = []
    accounts = {a.id: a for a in _live_accounts(db, ws)}
    for a in accounts.values():
        expected = FUNNEL_TO_LIFECYCLE.get(a.funnel_stage)
        if a.lifecycle_stage == "customer" and not a.is_customer:
            out.append(
                Candidate(
                    "lifecycle_conflict",
                    "account",
                    a.id,
                    f"{a.name}: lifecycle 'customer' but not marked as a customer",
                    {
                        "lifecycle_stage": a.lifecycle_stage,
                        "is_customer": a.is_customer,
                        "funnel_stage": a.funnel_stage,
                    },
                    {
                        "action": "align_lifecycle",
                        "params": {"account_id": str(a.id)},
                        "description": f"Set lifecycle to '{expected or 'lead'}' to match the funnel.",
                    },
                    key=f"acct:{a.id}",
                )
            )
        elif a.is_customer and a.funnel_stage not in ("won",) and a.lifecycle_stage != "customer":
            out.append(
                Candidate(
                    "lifecycle_conflict",
                    "account",
                    a.id,
                    f"{a.name}: marked customer but lifecycle is '{a.lifecycle_stage}'",
                    {"lifecycle_stage": a.lifecycle_stage, "is_customer": True},
                    {
                        "action": "align_lifecycle",
                        "params": {"account_id": str(a.id)},
                        "description": "Set lifecycle to 'customer'.",
                    },
                    key=f"acct:{a.id}",
                )
            )
    for c in _live_contacts(db, ws):
        acct = accounts.get(c.account_id) if c.account_id else None
        if acct and c.lifecycle_stage == "customer" and not acct.is_customer:
            out.append(
                Candidate(
                    "lifecycle_conflict",
                    "contact",
                    c.id,
                    f"{c.full_name} is 'customer' but {acct.name} is not a customer",
                    {"contact_lifecycle": c.lifecycle_stage, "account": acct.name},
                    {
                        "action": "align_lifecycle",
                        "params": {"contact_id": str(c.id)},
                        "description": "Align the contact lifecycle with the account.",
                    },
                    key=f"contact:{c.id}",
                )
            )
    return out


def rule_missing_owner(db: Session, ws: uuid.UUID, now: datetime) -> list[Candidate]:
    return [
        Candidate(
            "missing_owner",
            "account",
            a.id,
            f"{a.score_grade}-grade {a.name} has no owner",
            {"score": a.icp_score, "region": a.region, "segment": a.segment},
            {
                "action": "route_account",
                "params": {"account_id": str(a.id)},
                "description": "Run routing. If no rule matches, add a rule for this territory.",
            },
        )
        for a in _live_accounts(db, ws)
        if a.owner_id is None and a.score_grade in ("A", "B") and not a.is_customer
    ]


def rule_invalid_transitions(db: Session, ws: uuid.UUID, now: datetime) -> list[Candidate]:
    rows = db.execute(
        select(StageTransition.entity_id, StageTransition.from_stage, StageTransition.to_stage)
        .where(StageTransition.workspace_id == ws, StageTransition.pipeline == "funnel")
        .order_by(StageTransition.entity_id, StageTransition.changed_at)
    ).all()
    hist: dict[uuid.UUID, list[tuple[str | None, str]]] = defaultdict(list)
    for eid, frm, to in rows:
        hist[eid].append((frm, to))
    names = dict(db.execute(select(Account.id, Account.name).where(Account.id.in_(list(hist)))).tuples().all())
    out = []
    for eid, h in hist.items():
        bad = invalid_history_transitions(h)
        if bad:
            frm, to, why = bad[0]
            out.append(
                Candidate(
                    "invalid_pipeline_transition",
                    "account",
                    eid,
                    f"{names.get(eid, eid)}: {frm} → {to}",
                    {"transitions": [{"from": f, "to": t, "reason": r} for f, t, r in bad]},
                    {
                        "action": "manual",
                        "description": f"{why} Review the stage history and "
                        "backfill the missing stages or correct the record.",
                    },
                )
            )
    return out


def rule_bad_external_ids(db: Session, ws: uuid.UUID, now: datetime) -> list[Candidate]:
    out = []
    by_id: dict[str, list[Account]] = defaultdict(list)
    for a in _live_accounts(db, ws):
        if a.hubspot_company_id is None:
            continue
        if not a.hubspot_company_id.isdigit():
            out.append(
                Candidate(
                    "bad_external_id",
                    "account",
                    a.id,
                    f"{a.name}: malformed HubSpot company id '{a.hubspot_company_id}'",
                    {"hubspot_company_id": a.hubspot_company_id},
                    {
                        "action": "clear_external_id",
                        "params": {"account_id": str(a.id)},
                        "description": "Clear the id; the next sync re-links by the unique gtmos_account_id key.",
                    },
                    key=f"malformed:{a.id}",
                )
            )
        else:
            by_id[a.hubspot_company_id].append(a)
    for hid, accs in by_id.items():
        if len(accs) > 1:
            out.append(
                Candidate(
                    "bad_external_id",
                    "account",
                    accs[0].id,
                    f"HubSpot id {hid} is linked to {len(accs)} accounts",
                    {"accounts": [a.name for a in accs]},
                    {
                        "action": "manual",
                        "description": "Resolve which account owns the CRM record (often a duplicate account).",
                    },
                    [str(a.id) for a in accs[1:]],
                    key=f"dup:{hid}",
                )
            )
    return out


RULE_FUNCS: dict[str, Callable[[Session, uuid.UUID, datetime], list[Candidate]]] = {
    "duplicate_contact": rule_duplicate_contacts,
    "duplicate_account": rule_duplicate_accounts,
    "missing_domain": rule_missing_domain,
    "invalid_email": rule_invalid_email,
    "missing_employee_count": rule_missing_employee_count,
    "stale_enrichment": rule_stale_enrichment,
    "orphan_contact": rule_orphan_contacts,
    "lifecycle_conflict": rule_lifecycle_conflict,
    "missing_owner": rule_missing_owner,
    "invalid_pipeline_transition": rule_invalid_transitions,
    "bad_external_id": rule_bad_external_ids,
}


def scan(db: Session, ws: uuid.UUID, now: datetime | None = None, write_audit: bool = True) -> dict[str, Any]:
    now = now or utcnow()
    candidates = [c for f in RULE_FUNCS.values() for c in f(db, ws, now)]
    existing = {
        i.fingerprint: i for i in db.scalars(select(DataQualityIssue).where(DataQualityIssue.workspace_id == ws))
    }
    seen: set[str] = set()
    created = 0
    for c in candidates:
        fp = c.fingerprint
        if fp in seen:
            continue
        seen.add(fp)
        issue = existing.get(fp)
        if issue is None:
            db.add(
                DataQualityIssue(
                    workspace_id=ws,
                    rule_key=c.rule_key,
                    severity=RULES[c.rule_key]["severity"],
                    entity_type=c.entity_type,
                    entity_id=c.entity_id,
                    related_ids=c.related_ids,
                    title=c.title[:300],
                    details=c.details,
                    suggested_fix=c.suggested_fix,
                    status="open",
                    fingerprint=fp,
                    detected_at=now,
                    last_seen_at=now,
                )
            )
            created += 1
        else:
            issue.last_seen_at = now
            issue.title = c.title[:300]
            issue.details = c.details
            issue.suggested_fix = c.suggested_fix
            issue.related_ids = c.related_ids
            if issue.status == "resolved":
                issue.status = "open"
                issue.resolved_at = None
    auto_resolved = 0
    for fp, issue in existing.items():
        if fp not in seen and issue.status == "open":
            issue.status = "resolved"
            issue.resolved_at = now
            issue.resolved_by = "scan: no longer detected"
            auto_resolved += 1
    db.flush()
    counts = dict(
        db.execute(
            select(DataQualityIssue.rule_key, func.count())
            .where(DataQualityIssue.workspace_id == ws, DataQualityIssue.status == "open")
            .group_by(DataQualityIssue.rule_key)
        )
        .tuples()
        .all()
    )
    if write_audit:
        audit(
            db,
            ws,
            "data_quality.scanned",
            "workspace",
            ws,
            after={"open": sum(counts.values()), "new": created, "auto_resolved": auto_resolved},
            actor_type="system",
            actor="dq_scanner",
        )
    return {
        "open_by_rule": counts,
        "new": created,
        "auto_resolved": auto_resolved,
        "open_total": sum(counts.values()),
        "scanned_at": now.isoformat(),
    }


# --------------------------------------------------------------------------------------------------
# Remediation
# --------------------------------------------------------------------------------------------------


def merge_contacts(db: Session, primary_id: uuid.UUID, duplicate_ids: list[uuid.UUID], actor: str) -> Contact:
    primary = db.get(Contact, primary_id)
    if primary is None or primary.merged_into_id is not None:
        raise NotFound("primary contact not found")
    for did in duplicate_ids:
        dup = db.get(Contact, did)
        if dup is None or dup.id == primary.id or dup.merged_into_id:
            continue
        before = {"email": dup.email, "account_id": dup.account_id}
        for model in (Activity, Engagement, MessageDraft, Signal):
            db.execute(update(model).where(model.contact_id == dup.id).values(contact_id=primary.id))
        existing_roles = {
            r.role for r in db.scalars(select(AccountContactRole).where(AccountContactRole.contact_id == primary.id))
        }
        for r in db.scalars(select(AccountContactRole).where(AccountContactRole.contact_id == dup.id)):
            if r.role in existing_roles:
                db.delete(r)
            else:
                r.contact_id = primary.id
        for f in ("title", "linkedin_url", "seniority", "department", "account_id"):
            if getattr(primary, f) is None and getattr(dup, f) is not None:
                setattr(primary, f, getattr(dup, f))
        dup.merged_into_id = primary.id
        audit(
            db,
            primary.workspace_id,
            "contact.merged",
            "contact",
            dup.id,
            before=before,
            after={"merged_into": str(primary.id)},
            reason="duplicate contact remediation",
            actor=actor,
        )
    db.flush()
    return primary


def merge_accounts(db: Session, primary_id: uuid.UUID, duplicate_ids: list[uuid.UUID], actor: str) -> Account:
    primary = db.get(Account, primary_id)
    if primary is None or primary.merged_into_id is not None:
        raise NotFound("primary account not found")
    for did in duplicate_ids:
        dup = db.get(Account, did)
        if dup is None or dup.id == primary.id or dup.merged_into_id:
            continue
        for model in (Contact, Signal, Activity, Engagement, Opportunity, MessageDraft):
            db.execute(update(model).where(model.account_id == dup.id).values(account_id=primary.id))
        for f in (
            "employee_count",
            "industry",
            "city",
            "country",
            "region",
            "funding_stage",
            "owner_id",
            "hubspot_company_id",
        ):
            if getattr(primary, f) is None and getattr(dup, f) is not None:
                setattr(primary, f, getattr(dup, f))
        if dup.hubspot_company_id == primary.hubspot_company_id:
            dup.hubspot_company_id = None
        dup.merged_into_id = primary.id
        audit(
            db,
            primary.workspace_id,
            "account.merged",
            "account",
            dup.id,
            before={"name": dup.name, "domain": dup.domain},
            after={"merged_into": str(primary.id)},
            reason="duplicate account remediation",
            actor=actor,
        )
    db.flush()
    return primary


def remediate(db: Session, issue: DataQualityIssue, actor: str) -> dict[str, Any]:
    fix = issue.suggested_fix or {}
    action = fix.get("action")
    p = fix.get("params", {})
    result: dict[str, Any] = {"action": action}
    if action == "merge_contacts":
        merge_contacts(db, uuid.UUID(p["primary_id"]), [uuid.UUID(x) for x in p["duplicate_ids"]], actor)
    elif action == "merge_accounts":
        merge_accounts(db, uuid.UUID(p["primary_id"]), [uuid.UUID(x) for x in p["duplicate_ids"]], actor)
    elif action == "suppress_email":
        c = db.get(Contact, uuid.UUID(p["contact_id"]))
        if c:
            before = {"email_status": c.email_status, "do_not_contact": c.do_not_contact}
            c.email_status = "invalid"
            c.do_not_contact = True
            audit(
                db,
                c.workspace_id,
                "contact.email_suppressed",
                "contact",
                c.id,
                before=before,
                after={"email_status": "invalid", "do_not_contact": True},
                actor=actor,
            )
    elif action == "enrich_account":
        from gtmos.services.enrichment_service import enrich_account

        a = db.get(Account, uuid.UUID(p["account_id"]))
        if a:
            run = enrich_account(db, a, trigger="data_quality")
            result["enrichment_run_id"] = str(run.id)
            result["fields_changed"] = run.fields_changed
    elif action == "route_account":
        from gtmos.services.routing_service import route_account

        a = db.get(Account, uuid.UUID(p["account_id"]))
        if a:
            d = route_account(db, a, trigger="data_quality")
            result["routing_outcome"] = d.outcome
            if d.outcome == "unmatched":
                raise Conflict("No routing rule matches this account; add a rule for its territory first.")
    elif action == "align_lifecycle":
        if "account_id" in p:
            a = db.get(Account, uuid.UUID(p["account_id"]))
            if a:
                before = a.lifecycle_stage
                a.lifecycle_stage = "customer" if a.is_customer else (FUNNEL_TO_LIFECYCLE.get(a.funnel_stage) or "lead")
                audit(
                    db,
                    a.workspace_id,
                    "account.lifecycle_aligned",
                    "account",
                    a.id,
                    before={"lifecycle_stage": before},
                    after={"lifecycle_stage": a.lifecycle_stage},
                    actor=actor,
                )
        else:
            c = db.get(Contact, uuid.UUID(p["contact_id"]))
            if c:
                before = c.lifecycle_stage
                c.lifecycle_stage = "salesqualifiedlead"
                audit(
                    db,
                    c.workspace_id,
                    "contact.lifecycle_aligned",
                    "contact",
                    c.id,
                    before={"lifecycle_stage": before},
                    after={"lifecycle_stage": c.lifecycle_stage},
                    actor=actor,
                )
    elif action == "clear_external_id":
        a = db.get(Account, uuid.UUID(p["account_id"]))
        if a:
            before = a.hubspot_company_id
            a.hubspot_company_id = None
            audit(
                db,
                a.workspace_id,
                "account.external_id_cleared",
                "account",
                a.id,
                before={"hubspot_company_id": before},
                after={"hubspot_company_id": None},
                actor=actor,
            )
    elif action == "match_contact_to_account":
        from gtmos.domain.matching import email_domain

        c = db.get(Contact, uuid.UUID(p["contact_id"]))
        d = email_domain(c.email) if c else None
        acct = (
            db.scalars(select(Account).where(Account.workspace_id == issue.workspace_id, Account.domain == d)).first()
            if d
            else None
        )
        if c is None or acct is None:
            raise Conflict("No account matches this contact's email domain.")
        c.account_id = acct.id
        audit(
            db,
            c.workspace_id,
            "contact.matched_to_account",
            "contact",
            c.id,
            after={"account_id": str(acct.id)},
            reason=f"email domain {d}",
            actor=actor,
        )
        result["account"] = acct.name
    else:
        raise Conflict("This issue needs a manual fix; see the suggested remediation.")
    issue.status = "resolved"
    issue.resolved_at = utcnow()
    issue.resolved_by = actor
    db.flush()
    return result
