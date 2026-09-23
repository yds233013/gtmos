"""Email deliverability as a constraint on outbound volume.

GTMOS has no mailbox, no SMTP client and no sending integration, and it never will: the approval queue
ends at READY. So nothing here measures a real mail stream. Two different kinds of number live in this
module and they are kept apart deliberately.

*Capacity* is a plan. It is arithmetic over a declared sending setup (how many mailboxes, what per-mailbox
cap, how far into warmup) and a ramp schedule. It says what a team could safely send if they had that
setup. It is not an observation of anything.

*Risk* is computed from observed activity — which in a demo workspace means simulated activity. The
thresholds it is compared against are real: Google's published bulk-sender spam-rate limits, and vendor
rules of thumb for bounces, unsubscribes and list hygiene, each cited at the threshold that uses it. The
rates are conservative in two ways: counted rates get Wilson intervals, so a single complaint in a small
sample never gets called a breach, and the complaint/unsubscribe denominators are accounts rather than
messages, which overstates the per-message rate rather than flattering it.

The number that actually decides a campaign is neither of those on its own: it is days-to-work-the-list
at the safe volume. A 4,000-account list with a four-step sequence is 16,000 sends, which four warmed
mailboxes cannot deliver inside a quarter. That is a planning fact, available before anyone writes copy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from gtmos.domain.experiments import wilson_interval

# Google Workspace publishes a hard cap of 2,000 external recipients per user per day (Gmail sending
# limits). It is a terms-of-service ceiling, not a reputation-safe number, and quoting it as a sending
# plan is the mistake this module exists to prevent: the safe number is an order of magnitude lower.
PROVIDER_DAILY_CAP = 2_000
# No mailbox provider publishes a safe cold-send volume. 30-50 per mailbox per day on a warmed domain is
# vendor and agency consensus (warmup tooling defaults cluster there). Rule of thumb, not a measurement.
REPUTATION_SAFE_DAILY_CAP = 40

DOES_NOT_MODEL: tuple[str, ...] = (
    "GTMOS sends no email. The capacity figures are a plan for a sending setup that does not exist here.",
    "IP reputation. This models domain-level reputation only; shared vs dedicated IP pools, IP warmup and "
    "per-IP throttling by the receiving MTA are out of scope.",
    "Inbox placement. Landing in the inbox rather than Promotions or Junk can only be measured with seed-list "
    "testing (GlockApps, Validity) or Google Postmaster Tools. Nothing here estimates placement.",
    "Authentication. SPF, DKIM, DMARC alignment and one-click unsubscribe headers (RFC 8058) are pass/fail "
    "prerequisites, not rates. Microsoft has required all three for senders above 5,000 messages/day since "
    "2025-05-05; this model assumes they are in place and does not check them.",
    "Per-provider differences. Gmail, Outlook and corporate filters disagree about the same message; these "
    "rates are pooled across every recipient domain.",
    "Content scoring, spam-trap hits, blocklist status and mailbox-level reputation.",
)


# Capacity ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RampSchedule:
    """How fast a new mailbox may grow. Multiplicative, because that is how warmup tooling ramps.

    No provider publishes a warmup curve. The shape vendor guidance describes is: start at a handful of
    sends, grow by roughly 15-20% a day, reach full volume in two to four weeks. These defaults reach 40/day
    on day 14. Treat the curve as policy we chose, not as a number anyone can look up.
    """

    start_per_day: int = 5
    daily_growth: float = 1.18
    steady_state_per_day: int = REPUTATION_SAFE_DAILY_CAP

    def __post_init__(self) -> None:
        if self.start_per_day < 1:
            raise ValueError("ramp must start at 1 or more sends per day")
        if self.daily_growth <= 1.0:
            raise ValueError("ramp growth must be greater than 1.0, or the mailbox never warms up")
        if self.steady_state_per_day < self.start_per_day:
            raise ValueError("steady state cannot be below the ramp's starting volume")

    def allowance(self, warmup_day: int) -> int:
        """Sends this mailbox may make on day `warmup_day` of its life (day 1 = its first sending day)."""
        if warmup_day < 1:
            return 0
        grown = self.start_per_day * self.daily_growth ** (warmup_day - 1)
        return min(self.steady_state_per_day, math.floor(grown))

    @property
    def days_to_full_volume(self) -> int:
        span = self.steady_state_per_day / self.start_per_day
        return max(1, math.ceil(math.log(span) / math.log(self.daily_growth)) + 1)


DEFAULT_RAMP = RampSchedule()


@dataclass(frozen=True)
class SendingCapacity:
    mailboxes: int
    warmup_day: int
    per_mailbox_daily_cap: int
    per_mailbox_allowance: int
    daily_capacity: int
    steady_state_daily_capacity: int
    is_warming: bool
    days_to_full_volume: int
    limiting_factor: str  # no_mailboxes | warmup | configured_cap
    note: str


def sending_capacity(
    mailboxes: int,
    per_mailbox_daily_cap: int = REPUTATION_SAFE_DAILY_CAP,
    warmup_day: int = 1,
    ramp: RampSchedule = DEFAULT_RAMP,
) -> SendingCapacity:
    """Sends available today from `mailboxes` mailboxes that are `warmup_day` days into their ramp.

    Warmup is the whole point of the function. A new mailbox pushed straight to its steady-state volume is
    the classic way to get a domain filtered in week one, so the allowance on day 1 is the ramp's starting
    volume however high the configured cap is.
    """
    if mailboxes < 0:
        raise ValueError("mailboxes cannot be negative")
    if per_mailbox_daily_cap < 1:
        raise ValueError("per-mailbox daily cap must be at least 1")
    if warmup_day < 1:
        raise ValueError("warmup day starts at 1 (the mailbox's first sending day)")

    cap = min(per_mailbox_daily_cap, PROVIDER_DAILY_CAP)
    allowance = min(cap, ramp.allowance(warmup_day))
    is_warming = warmup_day < ramp.days_to_full_volume and allowance < cap
    if mailboxes == 0:
        limiting, note = "no_mailboxes", "No sending mailboxes declared, so the safe volume is zero."
    elif is_warming:
        limiting = "warmup"
        note = (
            f"Day {warmup_day} of warmup: {allowance} sends per mailbox against a configured cap of {cap}. "
            f"Full volume on day {ramp.days_to_full_volume}. Sending the cap today is the single most common "
            "way to burn a new domain."
        )
    else:
        limiting = "configured_cap"
        over_rule_of_thumb = (
            f"That cap is above the ~{REPUTATION_SAFE_DAILY_CAP}/day rule of thumb for cold outbound, which the "
            "provider allows and reputation does not. "
            if cap > REPUTATION_SAFE_DAILY_CAP
            else ""
        )
        note = (
            f"Mailboxes are past warmup, so the configured cap of {cap}/mailbox/day binds. "
            f"{over_rule_of_thumb}More volume means more mailboxes, not a higher cap."
        )
    return SendingCapacity(
        mailboxes=mailboxes,
        warmup_day=warmup_day,
        per_mailbox_daily_cap=cap,
        per_mailbox_allowance=allowance,
        daily_capacity=allowance * mailboxes,
        steady_state_daily_capacity=min(cap, ramp.steady_state_per_day) * mailboxes,
        is_warming=is_warming,
        days_to_full_volume=ramp.days_to_full_volume,
        limiting_factor=limiting,
        note=note,
    )


def days_to_send(
    total_sends: int,
    mailboxes: int,
    per_mailbox_daily_cap: int = REPUTATION_SAFE_DAILY_CAP,
    warmup_day: int = 1,
    ramp: RampSchedule = DEFAULT_RAMP,
    max_days: int = 365,
) -> int | None:
    """Calendar days to deliver `total_sends`, simulating the ramp day by day. None if it takes over a year.

    Simulated rather than divided, because dividing by today's capacity is wrong in both directions during
    warmup: it understates a ramping setup (tomorrow is bigger) and overstates a cold one (day 1 is 5 sends,
    not 40).
    """
    if total_sends <= 0:
        return 0
    if mailboxes <= 0 or per_mailbox_daily_cap < 1:
        return None
    cap = min(per_mailbox_daily_cap, PROVIDER_DAILY_CAP)
    remaining = total_sends
    for offset in range(max_days):
        remaining -= min(cap, ramp.allowance(warmup_day + offset)) * mailboxes
        if remaining <= 0:
            return offset + 1
    return None


@dataclass(frozen=True)
class CampaignFeasibility:
    list_size: int
    steps_per_account: int
    total_sends: int
    daily_capacity_today: int
    steady_state_daily_capacity: int
    days_to_first_touch: int | None
    days_to_work_list: int | None
    deadline_days: int | None
    fits_deadline: bool | None
    mailboxes_needed_for_deadline: int | None
    verdict: str  # feasible | tight | infeasible | no_capacity
    reason: str


def campaign_feasibility(
    list_size: int,
    steps_per_account: int,
    mailboxes: int,
    per_mailbox_daily_cap: int = REPUTATION_SAFE_DAILY_CAP,
    warmup_day: int = 1,
    ramp: RampSchedule = DEFAULT_RAMP,
    deadline_days: int | None = None,
    tight_days: int = 90,
) -> CampaignFeasibility:
    """Capacity against demand: can this list be worked at a safe volume, and by when.

    `list_size` is accounts (or contacts) to touch; `steps_per_account` is the email steps in the sequence.
    Demand is their product, because a four-step sequence to 1,000 accounts is 4,000 sends, not 1,000 — the
    arithmetic error that makes outbound plans miss by a factor of the sequence length.
    """
    if list_size < 0 or steps_per_account < 0:
        raise ValueError("list size and steps per account cannot be negative")
    cap = sending_capacity(mailboxes, per_mailbox_daily_cap, warmup_day, ramp)
    total = list_size * steps_per_account
    first_touch = days_to_send(list_size, mailboxes, per_mailbox_daily_cap, warmup_day, ramp)
    full = days_to_send(total, mailboxes, per_mailbox_daily_cap, warmup_day, ramp)

    needed: int | None = None
    if deadline_days is not None and deadline_days > 0 and total > 0:
        for m in range(1, 501):  # 500 mailboxes is already an absurd answer; past that, say so instead
            d = days_to_send(total, m, per_mailbox_daily_cap, warmup_day, ramp, max_days=deadline_days)
            if d is not None and d <= deadline_days:
                needed = m
                break
    fits = None if deadline_days is None else (full is not None and full <= deadline_days)

    if total == 0:
        verdict, reason = "feasible", "No sends planned."
    elif full is None:
        verdict = "no_capacity" if cap.daily_capacity == 0 else "infeasible"
        reason = (
            f"{total:,} sends cannot be delivered within a year at this capacity"
            f"{' (no mailboxes declared)' if cap.daily_capacity == 0 else ''}. The list, the sequence length or "
            "the mailbox count has to change."
        )
    elif fits is False:
        verdict = "infeasible"
        reason = (
            f"{total:,} sends ({list_size:,} accounts x {steps_per_account} steps) need {full} days at a safe "
            f"volume, against a {deadline_days}-day deadline."
            + (f" {needed} mailboxes would make it." if needed else " No sane mailbox count makes that deadline.")
        )
    elif full > tight_days:
        verdict = "tight"
        reason = (
            f"{total:,} sends need {full} days at a safe volume — over {tight_days} days, so the last account "
            f"hears from us in a different quarter to the first. First touch to the whole list takes "
            f"{first_touch} days."
        )
    else:
        verdict = "feasible"
        reason = (
            f"{total:,} sends need {full} days at a safe volume ({cap.daily_capacity}/day today, "
            f"{cap.steady_state_daily_capacity}/day once warm). First touch to the whole list takes "
            f"{first_touch} days."
        )
    return CampaignFeasibility(
        list_size=list_size,
        steps_per_account=steps_per_account,
        total_sends=total,
        daily_capacity_today=cap.daily_capacity,
        steady_state_daily_capacity=cap.steady_state_daily_capacity,
        days_to_first_touch=first_touch,
        days_to_work_list=full,
        deadline_days=deadline_days,
        fits_deadline=fits,
        mailboxes_needed_for_deadline=needed,
        verdict=verdict,
        reason=reason,
    )


# Risk --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Threshold:
    """A published limit or a stated rule of thumb, with the source it came from.

    `warn` is where a sender should stop adding volume; `severe` is where mailbox providers start acting.
    `weight` is this signal's share of the composite risk score, and is policy, not evidence.
    """

    metric: str
    label: str
    warn: float
    severe: float
    direction: str  # high_is_bad | low_is_bad
    weight: float
    source: str
    why: str


THRESHOLDS: dict[str, Threshold] = {
    "spam_complaint": Threshold(
        "spam_complaint",
        "Spam complaint rate",
        0.001,
        0.003,
        "high_is_bad",
        0.30,
        "Google bulk-sender guidelines (Feb 2024, enforced through 2024-25): keep the Postmaster Tools spam "
        "rate below 0.30% and aim below 0.10%. The only hard numeric threshold a mailbox provider publishes.",
        "Complaints are the one signal Gmail states it acts on. Crossing 0.30% throttles every campaign from "
        "the domain, not just the one that caused it.",
    ),
    "bounce": Threshold(
        "bounce",
        "Hard bounce rate",
        0.02,
        0.05,
        "high_is_bad",
        0.25,
        "No provider publishes a bounce limit. Vendor consensus (ESP and verification-tool guidance) treats "
        "under 2% as healthy and over 5% as a failed list; 5% is also the ceiling GTMOS's own experiment "
        "guardrails use. Rule of thumb, cited as such.",
        "A high bounce rate tells the receiving side the list was never verified, which is the cheapest "
        "possible evidence that the sender is not curating who they contact.",
    ),
    "unsubscribe": Threshold(
        "unsubscribe",
        "Unsubscribe rate",
        0.01,
        0.02,
        "high_is_bad",
        0.12,
        "Rule of thumb for cold outbound: healthy sits well under 1%, and sustained 2%+ means the targeting "
        "is wrong rather than the copy. No provider publishes a number.",
        "An unsubscribe is cheaper than a complaint and permanent all the same: the account is gone from "
        "every future play, not just this one.",
    ),
    "reply": Threshold(
        "reply",
        "Reply rate",
        0.02,
        0.01,
        "low_is_bad",
        0.10,
        "Cold-outbound benchmarks cluster between 1% and 5%. Gmail and Outlook both weight recipient "
        "engagement in filtering, so a very low reply rate is a deliverability input, not only a copy problem.",
        "Volume with no replies is the profile of a sender nobody wants to hear from, and filters learn it "
        "before a human notices.",
    ),
    "invalid_address_share": Threshold(
        "invalid_address_share",
        "Unsendable addresses on the list",
        0.02,
        0.05,
        "high_is_bad",
        0.15,
        "Leading indicator for the bounce rate above: invalid, role (info@, sales@) and free-mail addresses "
        "are where bounces and complaints come from. Same 2%/5% rule of thumb as bounces.",
        "This is the one deliverability number that can be fixed before a send rather than after one.",
    ),
    "unverified_share": Threshold(
        "unverified_share",
        "Unverified addresses on the list",
        0.10,
        0.25,
        "high_is_bad",
        0.08,
        "B2B lists decay at roughly 2% a month as people change jobs, so an address that has never been "
        "verified is a bounce with a delay. Rule of thumb; no published threshold exists.",
        "Unverified is not the same as bad, which is why it carries the smallest weight here — but it is the "
        "part of the risk that is knowable in advance and usually is not checked.",
    ),
}


@dataclass(frozen=True)
class SignalAssessment:
    metric: str
    label: str
    numerator: int
    denominator: int
    denominator_label: str
    rate: float | None
    ci_low: float | None  # None for census metrics: an interval over the whole list would be theatre
    ci_high: float | None
    warn: float
    severe: float
    direction: str
    status: str  # ok | watch | severe | no_data
    proven: bool  # the interval, not just the point estimate, clears the line we are claiming
    severity: float  # 0 at the warn line, 1 at the severe line; the risk score's input
    source: str
    reason: str


def _severity(rate: float, t: Threshold) -> float:
    """0 while healthy, ramping linearly to 1 at the severe line. Point estimate, not interval.

    Deliberately blunt. The interval decides what we are willing to *claim* (see `status`); the score is a
    summary of the central estimate, and pretending it is more precise than a straight line would be false.
    """
    if t.direction == "low_is_bad":
        if rate >= t.warn:
            return 0.0
        return min(1.0, (t.warn - rate) / (t.warn - t.severe)) if t.warn > t.severe else 1.0
    if rate <= t.warn:
        return 0.0
    return min(1.0, (rate - t.warn) / (t.severe - t.warn)) if t.severe > t.warn else 1.0


def assess_signal(
    metric: str, numerator: int, denominator: int, denominator_label: str, is_sample: bool = True
) -> SignalAssessment:
    """One observed rate against its threshold.

    `is_sample=False` marks a census (the state of the list right now, not a draw from a process): the rate
    is exact, so it gets no confidence interval and its status is read off the point estimate.
    """
    t = THRESHOLDS[metric]
    if denominator <= 0:
        return SignalAssessment(
            metric,
            t.label,
            numerator,
            denominator,
            denominator_label,
            None,
            None,
            None,
            t.warn,
            t.severe,
            t.direction,
            "no_data",
            False,
            0.0,
            t.source,
            f"No {denominator_label} in the window, so there is nothing to measure.",
        )
    rate = numerator / denominator
    lo, hi = wilson_interval(numerator, denominator) if is_sample else (rate, rate)
    pct = f"{rate * 100:.2f}%"
    interval = f" (95% CI {lo * 100:.2f}-{hi * 100:.2f}%)" if is_sample else ""
    # A census has no sampling error, so its sentences must not borrow the language of one.
    whole = " for the whole interval" if is_sample else ""
    census = "" if is_sample else " This is a count of the list as it stands, not a sample."

    if t.direction == "low_is_bad":
        if hi < t.severe:
            status, proven = "severe", True
            reason = f"{pct}{interval} is below the {t.severe * 100:.2f}% floor even at the top of the interval."
        elif hi < t.warn:
            status, proven = "watch", True
            reason = f"{pct}{interval} sits below the {t.warn * 100:.2f}% we treat as healthy engagement."
        elif rate < t.warn:
            status, proven = "watch", False
            reason = (
                f"{pct}{interval} is under the {t.warn * 100:.2f}% healthy line, but the interval reaches back over it."
            )
        else:
            status, proven = "ok", lo >= t.warn
            reason = f"{pct}{interval} is at or above the {t.warn * 100:.2f}% healthy line."
    elif lo > t.severe:
        status, proven = "severe", True
        reason = f"{pct}{interval} is above the {t.severe * 100:.2f}% severe line{whole}.{census}"
    elif lo > t.warn:
        status, proven = "watch", True
        reason = (
            f"{pct}{interval} is above the {t.warn * 100:.2f}% healthy line{whole}, though under "
            f"the {t.severe * 100:.2f}% severe line.{census}"
        )
    elif rate > t.warn:
        status, proven = "watch", False
        reason = (
            f"{pct}{interval} is over the {t.warn * 100:.2f}% healthy line, but with {denominator:,} "
            f"{denominator_label} the interval still reaches back under it. Not proven; not ignorable."
        )
    elif hi <= t.warn:
        status, proven = "ok", True
        reason = f"{pct}{interval} stays under the {t.warn * 100:.2f}% healthy line{whole}.{census}"
    else:
        status, proven = "ok", False
        reason = (
            f"{pct}{interval} is under the {t.warn * 100:.2f}% healthy line, but with {denominator:,} "
            f"{denominator_label} the interval still reaches {hi * 100:.2f}% — under the line, not cleared of it."
        )
    return SignalAssessment(
        metric,
        t.label,
        numerator,
        denominator,
        denominator_label,
        round(rate, 6),
        None if not is_sample else round(lo, 6),
        None if not is_sample else round(hi, 6),
        t.warn,
        t.severe,
        t.direction,
        status,
        proven,
        round(_severity(rate, t), 4),
        t.source,
        reason,
    )


@dataclass(frozen=True)
class ObservedSignals:
    """Counts a caller measured. Every field is a count, so the denominators stay visible in the output."""

    sent: int = 0
    bounced: int = 0
    replies: int = 0
    accounts_touched: int = 0
    spam_complaints: int = 0
    unsubscribes: int = 0
    contacts_with_email: int = 0
    unsendable_addresses: int = 0  # invalid, role (info@/sales@) or free-mail
    unverified_addresses: int = 0  # never verified: status unknown or risky


@dataclass(frozen=True)
class RiskAssessment:
    risk_score: int  # 0-100, higher is worse; a weighted summary, not a probability
    verdict: str  # scale | caution | throttle | stop
    headline: str
    reasoning: str
    signals: tuple[SignalAssessment, ...]
    actions: tuple[str, ...]
    throttle_factor: float  # multiplier this verdict applies to planned volume
    coverage: str
    does_not_model: tuple[str, ...]


# What each verdict does to the sending plan. Policy: a risk model that does not change the plan is a chart.
THROTTLE_FACTORS: dict[str, float] = {"scale": 1.0, "caution": 1.0, "throttle": 0.5, "stop": 0.0}

REMEDIES: dict[str, str] = {
    "spam_complaint": "Cut volume and re-check targeting: complaints are the one rate Gmail says it enforces.",
    "bounce": "Verify the list before the next send; hard bounces are unverified addresses arriving late.",
    "unsubscribe": "The targeting is wrong, not the copy. Tighten the ICP filter before re-running the play.",
    "reply": "Low engagement is a filtering input. Send less, to better-fitting accounts, with a real reason.",
    "invalid_address_share": "Drop role, free-mail and known-invalid addresses from the send list.",
    "unverified_share": "Run verification on the unverified share before it becomes the bounce rate.",
}


def assess_risk(observed: ObservedSignals) -> RiskAssessment:
    """Composite deliverability risk from observed rates, with a verdict that changes the sending plan.

    The composite is the weighted mean of per-signal severities over the signals that had data, so a metric
    nobody could measure does not quietly improve the score — it shrinks the evidence base, which the
    `coverage` line states outright.
    """
    signals = (
        assess_signal("spam_complaint", observed.spam_complaints, observed.accounts_touched, "accounts touched"),
        assess_signal("bounce", observed.bounced, observed.sent, "messages sent"),
        assess_signal("unsubscribe", observed.unsubscribes, observed.accounts_touched, "accounts touched"),
        assess_signal("reply", observed.replies, observed.sent, "messages sent"),
        assess_signal(
            "invalid_address_share",
            observed.unsendable_addresses,
            observed.contacts_with_email,
            "contacts with an email",
            is_sample=False,
        ),
        assess_signal(
            "unverified_share",
            observed.unverified_addresses,
            observed.contacts_with_email,
            "contacts with an email",
            is_sample=False,
        ),
    )
    measured = [s for s in signals if s.status != "no_data"]
    weight = sum(THRESHOLDS[s.metric].weight for s in measured)
    score = round(100 * sum(THRESHOLDS[s.metric].weight * s.severity for s in measured) / weight) if weight else 0

    severe = [s for s in measured if s.status == "severe"]
    watch = [s for s in measured if s.status == "watch"]
    proven_watch = [s for s in watch if s.proven and s.metric in ("bounce", "spam_complaint")]
    if any(s.metric in ("bounce", "spam_complaint") for s in severe):
        verdict = "stop"
        headline = "Stop sending until the list is fixed."
    elif severe or proven_watch:
        verdict = "throttle"
        headline = "Halve the volume and fix the list before adding any."
    elif watch:
        verdict = "caution"
        headline = "Safe to keep sending at the current volume, not to scale it."
    else:
        verdict = "scale"
        headline = "Nothing in the observed rates argues against more volume."

    drivers = severe + watch
    reasoning = (
        headline
        + " "
        + (
            "; ".join(f"{s.label.lower()} {s.reason[0].lower() + s.reason[1:]}" for s in drivers[:3])
            if drivers
            else "Every measured rate is inside its threshold."
        )
    )
    actions = tuple(dict.fromkeys(REMEDIES[s.metric] for s in drivers))
    coverage = (
        f"{len(measured)} of {len(signals)} signals had data "
        f"({', '.join(s.metric for s in signals if s.status == 'no_data')} did not)."
        if len(measured) < len(signals)
        else f"All {len(signals)} signals had data."
    )
    return RiskAssessment(
        risk_score=score,
        verdict=verdict,
        headline=headline,
        reasoning=reasoning,
        signals=signals,
        actions=actions,
        throttle_factor=THROTTLE_FACTORS[verdict],
        coverage=coverage,
        does_not_model=DOES_NOT_MODEL,
    )
