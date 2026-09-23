"""Deliverability assessment: observed rates from the CRM, capacity from a declared plan.

GTMOS sends nothing, so this service is two halves that must not be confused with each other. The risk
half reads real rows — email activity, experiment guardrail outcomes, unsubscribe signals and the state of
the contact list — and scores them against published limits and stated rules of thumb. In a demo workspace
those rows are simulated, and the payload says so in `basis` rather than in a footnote nobody reads.

The capacity half is arithmetic over a sending setup the caller declares. There is no mailbox behind it.
Its job is to turn "we have 4,000 accounts to work" into "that is N days of sending", which is the number
that decides whether a campaign plan is real, and to refuse to grow while the risk half says otherwise.
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import asdict
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gtmos.domain.deliverability import (
    DEFAULT_RAMP,
    REPUTATION_SAFE_DAILY_CAP,
    THRESHOLDS,
    ObservedSignals,
    assess_risk,
    campaign_feasibility,
    sending_capacity,
)
from gtmos.domain.matching import FREE_MAIL_DOMAINS, email_domain, is_role_address, is_valid_email
from gtmos.models import (
    Account,
    Activity,
    Campaign,
    Contact,
    ExperimentAssignment,
    ExperimentOutcome,
    Sequence,
    SequenceStep,
    Signal,
)
from gtmos.services.common import utcnow

# The sending setup a plan is costed against when the caller does not declare one. Four mailboxes past
# warmup is a normal one-SDR setup; it is a default, not an observation, and the payload labels it so.
DEFAULT_MAILBOXES = 4
DEFAULT_WARMUP_DAY = 90  # well past the ramp: assume mature mailboxes unless told otherwise
DEFAULT_SEQUENCE_STEPS = 4  # used only when no campaign has an email sequence to measure


def _list_quality(db: Session, ws: uuid.UUID) -> tuple[int, int, int]:
    """(contacts with an email, unsendable, unverified) across the live contact list.

    Unsendable is the union of three things that all end as bounces or complaints: an address the CRM has
    already marked invalid or that does not parse, a role inbox (sales@, info@) that no one person owns,
    and a free-mail address, which is not a business contact however valid it is.
    """
    rows = db.execute(
        select(Contact.email, Contact.email_status).where(
            Contact.workspace_id == ws, Contact.merged_into_id.is_(None), Contact.email.is_not(None)
        )
    ).all()
    unsendable = unverified = 0
    for email, status in rows:
        bad_address = status == "invalid" or not is_valid_email(email) or is_role_address(email)
        if bad_address or (email_domain(email) or "") in FREE_MAIL_DOMAINS:
            unsendable += 1
        elif status in ("unknown", "risky"):
            unverified += 1
    return len(rows), unsendable, unverified


def _steps_per_account(db: Session, ws: uuid.UUID) -> tuple[int, str]:
    """Median email steps across the sequences of active campaigns — the real multiplier on list size."""
    counts = list(
        db.scalars(
            select(func.count(SequenceStep.id))
            .select_from(SequenceStep)
            .join(Sequence, Sequence.id == SequenceStep.sequence_id)
            .join(Campaign, Campaign.id == Sequence.campaign_id)
            .where(Campaign.workspace_id == ws, Campaign.status == "active", SequenceStep.channel == "email")
            .group_by(Sequence.id)
        )
    )
    if not counts:
        return DEFAULT_SEQUENCE_STEPS, f"No active email sequence to measure; assuming {DEFAULT_SEQUENCE_STEPS} steps."
    return round(statistics.median(counts)), (
        f"Median email steps across the {len(counts)} sequences on active campaigns."
    )


def observed_signals(db: Session, ws: uuid.UUID, days: int) -> tuple[ObservedSignals, dict[str, str]]:
    """Count everything the risk model needs, and say what each denominator is.

    Complaints and unsubscribes are counted per *account touched*, not per message, because that is the
    grain the data has: the guardrail outcomes are recorded against an experiment assignment, which is an
    account. A per-account rate is larger than the per-message rate a mailbox provider computes, by roughly
    the number of sends per account, so comparing it to Gmail's 0.30% overstates the risk rather than
    hiding it. That is the right direction for a number used to decide whether to send more.
    """
    since = utcnow() - timedelta(days=days)
    acts = dict(
        db.execute(
            select(Activity.type, func.count())
            .where(Activity.workspace_id == ws, Activity.occurred_at >= since, Activity.type.like("email_%"))
            .group_by(Activity.type)
        )
        .tuples()
        .all()
    )
    sent_filter = (Activity.workspace_id == ws, Activity.type == "email_sent", Activity.occurred_at >= since)
    touched = select(Activity.account_id).where(*sent_filter)
    accounts_touched = db.scalar(select(func.count(func.distinct(Activity.account_id))).where(*sent_filter)) or 0
    complaints = (
        db.scalar(
            select(func.count(func.distinct(ExperimentAssignment.account_id)))
            .select_from(ExperimentOutcome)
            .join(ExperimentAssignment, ExperimentAssignment.id == ExperimentOutcome.assignment_id)
            .where(
                ExperimentOutcome.metric == "spam_complaint",
                ExperimentOutcome.occurred_at >= since,
                ExperimentAssignment.account_id.in_(touched),
            )
        )
        or 0
    )
    # An account can also be marked unsubscribed by the signal feed rather than by an experiment outcome.
    # Both mean the same thing, so they are unioned at the account grain instead of added up.
    unsub_accounts = set(
        db.scalars(
            select(func.distinct(ExperimentAssignment.account_id))
            .join(ExperimentOutcome, ExperimentOutcome.assignment_id == ExperimentAssignment.id)
            .where(
                ExperimentOutcome.metric == "unsubscribe",
                ExperimentOutcome.occurred_at >= since,
                ExperimentAssignment.account_id.in_(touched),
            )
        )
    ) | set(
        db.scalars(
            select(func.distinct(Signal.account_id)).where(
                Signal.workspace_id == ws,
                Signal.signal_type == "unsubscribed",
                Signal.observed_at >= since,
                Signal.account_id.in_(touched),
            )
        )
    )
    contacts, unsendable, unverified = _list_quality(db, ws)
    signals = ObservedSignals(
        sent=acts.get("email_sent", 0),
        bounced=acts.get("email_bounced", 0),
        replies=acts.get("email_replied", 0),
        accounts_touched=accounts_touched,
        spam_complaints=complaints,
        unsubscribes=len(unsub_accounts),
        contacts_with_email=contacts,
        unsendable_addresses=unsendable,
        unverified_addresses=unverified,
    )
    sources = {
        "bounce": f"activities.email_bounced over activities.email_sent, last {days} days",
        "reply": f"activities.email_replied over activities.email_sent, last {days} days",
        "spam_complaint": "experiment_outcomes.spam_complaint over accounts with a send in the window",
        "unsubscribe": "experiment_outcomes.unsubscribe and signals.unsubscribed, unioned per account, over "
        "accounts with a send in the window",
        "invalid_address_share": "contacts: invalid or unparseable address, role inbox, or free-mail domain",
        "unverified_share": "contacts whose email_status is still unknown or risky",
    }
    return signals, sources


def assess(
    db: Session,
    ws: uuid.UUID,
    days: int = 90,
    mailboxes: int = DEFAULT_MAILBOXES,
    per_mailbox_daily_cap: int = REPUTATION_SAFE_DAILY_CAP,
    warmup_day: int = DEFAULT_WARMUP_DAY,
) -> dict[str, Any]:
    """Risk from observed activity, capacity from the declared plan, and the gap between them.

    The risk verdict feeds back into the plan: a `throttle` halves the per-mailbox cap before the days-to-
    work-the-list number is computed, and a `stop` takes it to zero. A deliverability model that leaves the
    plan unchanged is decoration.
    """
    signals, sources = observed_signals(db, ws, days)
    risk = assess_risk(signals)

    safe_cap = max(0, int(per_mailbox_daily_cap * risk.throttle_factor))
    capacity = sending_capacity(mailboxes, per_mailbox_daily_cap, warmup_day, DEFAULT_RAMP)
    list_size = (
        db.scalar(
            select(func.count())
            .select_from(Contact)
            .join(Account, Account.id == Contact.account_id)
            .where(
                Contact.workspace_id == ws,
                Contact.merged_into_id.is_(None),
                Contact.do_not_contact.is_(False),
                Contact.email_status == "valid",
                Account.merged_into_id.is_(None),
                Account.score_grade.in_(("A", "B")),
            )
        )
        or 0
    )
    steps, steps_basis = _steps_per_account(db, ws)
    feasibility = (
        campaign_feasibility(list_size, steps, mailboxes, safe_cap, warmup_day, DEFAULT_RAMP)
        if safe_cap
        else campaign_feasibility(list_size, steps, 0, per_mailbox_daily_cap, warmup_day, DEFAULT_RAMP)
    )
    return {
        "window_days": days,
        "generated_at": utcnow(),
        "basis": (
            "GTMOS has no mailbox and sends no email: the capacity figures are a plan for a declared sending "
            "setup, not a measurement of one. The observed rates are computed from this workspace's activity, "
            "which in a demo workspace is simulated data. The thresholds they are compared against are real."
        ),
        "risk": {
            **{k: v for k, v in asdict(risk).items() if k != "signals"},
            "signals": [
                {**asdict(s), "measured_from": sources[s.metric], "why": THRESHOLDS[s.metric].why} for s in risk.signals
            ],
        },
        "plan": {
            **asdict(capacity),
            "is_a_plan_not_a_measurement": True,
            "risk_adjusted_per_mailbox_cap": safe_cap,
            "risk_adjusted_daily_sends": min(safe_cap, capacity.per_mailbox_allowance) * mailboxes,
            "adjustment": (
                f"The '{risk.verdict}' verdict applies a {risk.throttle_factor:.0%} multiplier to the "
                f"{per_mailbox_daily_cap}/mailbox/day plan."
            ),
        },
        "demand": {
            "targetable_contacts": list_size,
            "definition": "Contactable contacts (valid email, not do-not-contact) at live A or B-grade accounts.",
            "steps_per_account": steps,
            "steps_basis": steps_basis,
        },
        "feasibility": asdict(feasibility),
    }
