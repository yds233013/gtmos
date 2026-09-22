"""Personalized outreach drafts and the human approval workflow."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from gtmos.domain.personalization import (
    DraftContent,
    PersonalizationInput,
    check_message_transition,
    generate_messages,
    run_guardrails,
)
from gtmos.domain.research import ANGLES, sanitize_external
from gtmos.models import (
    Account,
    AccountContactRole,
    Activity,
    Contact,
    MessageDraft,
    Opportunity,
    ResearchEvidence,
    Signal,
)
from gtmos.services.common import Conflict, NotFound, audit, utcnow
from gtmos.services.research_service import generate_research, latest_report

SENDER = "Jordan Lee, Sentinel AI"


def _short(title: str) -> str:
    return title[0].lower() + title[1:] if title else title


def _anchor(db: Session, account: Account, angle: str, evidence: list[ResearchEvidence]) -> dict | None:  # type: ignore[type-arg]
    sig_type = ANGLES.get(angle, (None, None, None))[1]
    q = select(Signal).where(Signal.account_id == account.id).order_by(Signal.observed_at.desc())
    if sig_type:
        q = q.where(Signal.signal_type == sig_type)
    s = db.scalars(q).first()
    if s is None:
        return None
    ref = next((e.ref for e in evidence if e.source_record_id == s.id), None)
    ev = s.evidence or {}
    # Signal text comes from external feeds and lands in an email a prospect reads, which is the
    # highest-consequence place untrusted text can end up. Sanitised at the same boundary as research.
    return {
        "id": str(s.id),
        "title": sanitize_external(s.title),
        "short": sanitize_external(ev.get("short") or _short(s.title)),
        "subject_hook": sanitize_external(ev.get("hook")) or account.name,
        "confidence": s.confidence,
        "observed_at": s.observed_at,
        "ref": ref,
    }


def pick_recipient(db: Session, account: Account) -> Contact | None:
    """Champion first for new outreach; once an opportunity is open, multi-thread to the buyer."""
    has_open_opp = db.scalars(
        select(Opportunity.id).where(
            Opportunity.account_id == account.id, Opportunity.stage.not_in(["closed_won", "closed_lost"])
        )
    ).first()
    order = (
        ["economic_buyer", "executive_sponsor", "champion", "technical_evaluator"]
        if has_open_opp
        else ["champion", "economic_buyer", "technical_evaluator", "executive_sponsor"]
    )
    for role in order:
        r = db.scalars(
            select(AccountContactRole).where(
                AccountContactRole.account_id == account.id,
                AccountContactRole.role == role,
                AccountContactRole.rank == 1,
            )
        ).first()
        if r:
            c = db.get(Contact, r.contact_id)
            if c and not c.do_not_contact and c.email_status != "invalid":
                return c
    return None


def _engaged_champion(db: Session, account: Account, recipient: Contact) -> Contact | None:
    """The champion, if someone other than the recipient has already met with us (grounds a warm intro)."""
    r = db.scalars(
        select(AccountContactRole).where(
            AccountContactRole.account_id == account.id,
            AccountContactRole.role == "champion",
            AccountContactRole.rank == 1,
        )
    ).first()
    if r is None or r.contact_id == recipient.id:
        return None
    met = db.scalars(
        select(Activity.id).where(Activity.contact_id == r.contact_id, Activity.type == "meeting_held")
    ).first()
    return db.get(Contact, r.contact_id) if met else None


def draft_outreach(
    db: Session,
    account: Account,
    contact: Contact,
    *,
    channels: list[str] | None = None,
    actor: str = "system",
    initial_status: str = "draft",
    workflow_run_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
) -> list[MessageDraft]:
    channels = channels or ["email", "linkedin", "call_prep"]
    report = latest_report(db, account.id) or generate_research(db, account, actor=actor)
    evidence = list(
        db.scalars(
            select(ResearchEvidence).where(ResearchEvidence.report_id == report.id).order_by(ResearchEvidence.ref)
        )
    )
    angle = (report.sections or {}).get("_meta", {}).get("angle", "icp_fit")
    ev_dicts = [
        {"ref": e.ref, "label": e.label, "detail": e.detail, "kind": e.kind, "source": e.source} for e in evidence
    ]
    role = db.scalars(
        select(AccountContactRole.role)
        .where(AccountContactRole.account_id == account.id, AccountContactRole.contact_id == contact.id)
        .order_by(AccountContactRole.rank)
    ).first()
    champion = _engaged_champion(db, account, contact)
    inp = PersonalizationInput(
        account={"name": account.name},
        contact={
            "first_name": contact.first_name,
            "name": contact.full_name,
            "title": contact.title,
            "email_status": contact.email_status,
            "do_not_contact": contact.do_not_contact,
            "role": role,
            "thread_with": champion.first_name if champion else None,
        },
        angle=angle,
        anchor_signal=_anchor(db, account, angle, evidence),
        evidence=ev_dicts,
        sender_name=SENDER,
        now=utcnow(),
    )
    drafts: list[MessageDraft] = []
    for d in generate_messages(inp):
        if d.channel not in channels:
            continue
        row = MessageDraft(
            workspace_id=account.workspace_id,
            account_id=account.id,
            contact_id=contact.id,
            campaign_id=campaign_id,
            research_report_id=report.id,
            channel=d.channel,
            subject=d.subject,
            body=d.body,
            angle=d.angle,
            reasoning_chain=d.chain,
            evidence=d.evidence,
            guardrails=d.guardrails_json(),
            status=initial_status,
            generator="demo-deterministic",
            workflow_run_id=workflow_run_id,
        )
        db.add(row)
        drafts.append(row)
    db.flush()
    audit(
        db,
        account.workspace_id,
        "outreach.drafted",
        "account",
        account.id,
        after={
            "drafts": [str(d.id) for d in drafts],
            "contact_id": str(contact.id),
            "angle": angle,
            "status": initial_status,
        },
        reason="Drafts require human approval; GTMOS never sends messages.",
        actor_type="workflow" if workflow_run_id else ("user" if actor != "system" else "system"),
        actor=actor,
    )
    return drafts


def _blocked(d: MessageDraft) -> bool:
    return any(g.get("blocking") and not g.get("passed") for g in (d.guardrails or []))


def transition(db: Session, draft: MessageDraft, target: str, actor: str, reason: str | None = None) -> MessageDraft:
    ok, why = check_message_transition(draft.status, target, _blocked(draft))
    if not ok:
        raise Conflict(why)
    before = draft.status
    draft.status = target
    if target == "review":
        draft.reviewed_by = None
    if target == "approved":
        draft.approved_by = actor
        draft.approved_at = utcnow()
    if target == "rejected":
        draft.rejection_reason = reason
    if target == "draft":
        draft.approved_by = None
        draft.approved_at = None
    audit(
        db,
        draft.workspace_id,
        f"message.{target}",
        "message_draft",
        draft.id,
        before={"status": before},
        after={"status": target},
        reason=reason,
        actor=actor,
    )
    return draft


def edit_draft(db: Session, draft: MessageDraft, subject: str | None, body: str, actor: str) -> MessageDraft:
    if draft.status in ("ready",):
        raise Conflict("Move the message back to draft before editing.")
    account = db.get(Account, draft.account_id)
    contact = db.get(Contact, draft.contact_id) if draft.contact_id else None
    if account is None:
        raise NotFound("account missing")
    chain = draft.reasoning_chain or {}
    sig = chain.get("signal")
    inp = PersonalizationInput(
        account={"name": account.name},
        contact={
            "first_name": contact.first_name if contact else None,
            "email_status": contact.email_status if contact else "unknown",
            "do_not_contact": contact.do_not_contact if contact else False,
        },
        angle=draft.angle,
        anchor_signal=None
        if not sig
        else {"title": sig["text"], "confidence": sig["confidence"], "observed_at": utcnow()},
        evidence=list(draft.evidence or []),
        sender_name=SENDER,
        now=utcnow(),
    )
    content = DraftContent(draft.channel, subject, body, draft.angle, chain, list(draft.evidence or []))
    # Edits are checked against the draft's own evidence plus the full research pack.
    if draft.research_report_id:
        inp.evidence = [
            {"ref": e.ref, "label": e.label, "detail": e.detail}
            for e in db.scalars(select(ResearchEvidence).where(ResearchEvidence.report_id == draft.research_report_id))
        ]
    content.guardrails = run_guardrails(content, inp)
    before = {"subject": draft.subject, "body": draft.body, "status": draft.status}
    draft.subject = subject
    draft.body = body
    draft.guardrails = content.guardrails_json()
    draft.version += 1
    if draft.status == "approved":
        draft.status = "review"
        draft.approved_by = None
        draft.approved_at = None
    audit(
        db,
        draft.workspace_id,
        "message.edited",
        "message_draft",
        draft.id,
        before=before,
        after={"subject": subject, "body": body, "status": draft.status, "version": draft.version},
        actor=actor,
    )
    return draft
