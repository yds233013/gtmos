"""The metric dictionary: one place that defines every number GTMOS reports.

RevOps arguments are usually definition arguments ("is that reply rate per send or per account?"), so the
definitions live in code next to the semantic layer, are served by the API, and are shown in the UI. Each
entry states the formula, the denominator, and the caveat that stops the number being misread.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    label: str
    category: str  # funnel | outbound | pipeline | data | experiment
    definition: str
    formula: str
    denominator: str
    caveat: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFINITIONS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        "contacted_cohort",
        "Contacted cohort",
        "funnel",
        "Accounts whose first outbound touch happened inside the reporting window. Every funnel conversion "
        "below is measured against this fixed cohort, so later stages can mature after the window closes.",
        "count(distinct account) where first stage transition to 'contacted' is within the window",
        "accounts, not contacts",
        "A cohort funnel understates recent windows: accounts contacted yesterday have not had time to convert.",
    ),
    MetricDefinition(
        "stage_conversion",
        "Stage conversion",
        "funnel",
        "Share of the contacted cohort that ever reached a given stage, including after the window ended.",
        "accounts reaching stage ÷ accounts reaching the previous stage",
        "accounts in the cohort",
        "Stages can be skipped (a warm inbound can book a meeting without an 'engaged' transition), so "
        "step conversion is not strictly sequential.",
    ),
    MetricDefinition(
        "reply_rate",
        "Reply rate",
        "outbound",
        "Replies received per email sent. GTMOS reports the per-send rate because that is what a sequencer "
        "reports; the per-account rate is higher because most accounts receive several sends.",
        "replies ÷ emails sent in the window",
        "emails sent (not contacts, not accounts)",
        "Auto-replies and out-of-office are not separated in the demo dataset.",
    ),
    MetricDefinition(
        "positive_reply_rate",
        "Positive reply rate",
        "outbound",
        "Replies a rep classified as interested, per email sent. This is the primary outbound quality metric "
        "because raw reply rate rewards provocative subject lines that generate negative replies.",
        "positive replies ÷ emails sent in the window",
        "emails sent",
        "Classification is human judgement; in production it needs an agreed rubric and spot audits.",
    ),
    MetricDefinition(
        "open_rate",
        "Open rate",
        "outbound",
        "Tracked opens per delivered email. Shown for completeness only and used in no GTMOS decision.",
        "opens ÷ delivered",
        "delivered emails",
        "Apple Mail Privacy Protection and corporate scanners pre-fetch images, so opens are inflated and "
        "not comparable across audiences. Never optimise on this.",
    ),
    MetricDefinition(
        "meetings_held",
        "Meetings held",
        "funnel",
        "Discovery calls that actually happened, not meetings booked. Bookings that no-show never count.",
        "count of activities of type meeting_held in the window",
        "activities",
        "Booked-to-held ratio is a separate operational metric and is not reported in V1.",
    ),
    MetricDefinition(
        "qualified_accounts",
        "Qualified accounts (SQL equivalent)",
        "funnel",
        "Accounts that reached the 'qualified' stage: a positive reply confirmed the pain and the buying "
        "context. This is GTMOS's sales-qualified lead equivalent, defined at the account level.",
        "count(distinct account) transitioning to 'qualified' in the window",
        "accounts",
        "Qualification is stage-based, not a score threshold: a high score alone never qualifies an account.",
    ),
    MetricDefinition(
        "pipeline_created",
        "Pipeline created",
        "pipeline",
        "Total amount of opportunities opened in the window, counted at creation, not at close.",
        "sum(opportunity amount) where opened_at is in the window",
        "opportunities opened in the window",
        "Amounts are the seller's estimate at creation and are never revised down in the demo dataset.",
    ),
    MetricDefinition(
        "open_pipeline",
        "Open pipeline",
        "pipeline",
        "Amount currently in non-closed deal stages, regardless of when it was created.",
        "sum(amount) where stage not in (closed_won, closed_lost)",
        "open opportunities",
        "Not weighted by stage probability; a weighted forecast is a separate metric.",
    ),
    MetricDefinition(
        "win_rate",
        "Win rate",
        "pipeline",
        "Share of decided opportunities that were won, over opportunities that closed in the window.",
        "closed-won ÷ (closed-won + closed-lost) closed in the window",
        "closed opportunities",
        "Open deals are excluded, so early-stage pipeline does not dilute the number.",
    ),
    MetricDefinition(
        "pipeline_velocity",
        "Pipeline velocity",
        "pipeline",
        "Expected revenue per day implied by the current funnel.",
        "open opportunities × win rate × average won deal ÷ median sales cycle (days)",
        "open opportunities",
        "Combines four noisy inputs; useful for direction, not for forecasting. Unreliable below ~20 closed "
        "deals, which GTMOS flags.",
    ),
    MetricDefinition(
        "enrichment_coverage",
        "Enrichment coverage",
        "data",
        "Share of accounts where every core field needed for scoring and routing is present "
        "(domain, industry, employee count, region, AI team size).",
        "accounts with all core fields ÷ all accounts",
        "non-merged accounts",
        "Coverage says nothing about accuracy; provenance confidence and staleness are tracked separately.",
    ),
    MetricDefinition(
        "intent_index",
        "Intent index",
        "funnel",
        "The 'why now' half of the score, normalised to 0–100: intent, timing and engagement points as a "
        "share of their combined budget, independent of fit.",
        "(intent + timing + engagement points) ÷ their maximum × 100",
        "score categories",
        "A high intent index on a poor-fit account is still not a target; read it alongside the grade.",
    ),
    MetricDefinition(
        "time_to_first_touch",
        "Time to first touch",
        "funnel",
        "Hours between a qualifying signal being observed and the first outbound touch on that account. The "
        "operational SLA for signal-based selling.",
        "median(first touch after signal − signal observed_at)",
        "signals that triggered a play",
        "Demo history is simulated batch processing, so the distribution reflects the seed, not live latency.",
    ),
    MetricDefinition(
        "attributed_share",
        "Attributed share",
        "pipeline",
        "Share of opportunity value that has at least one recorded touch inside the lookback window.",
        "1 − (unattributed pipeline ÷ total pipeline)",
        "opportunities in the window",
        "Anything GTMOS never saw (referrals, events, dark social) is unattributed by definition, not by "
        "failure. A 100% attributed number means your tracking is lying.",
    ),
    MetricDefinition(
        "guardrail_metric",
        "Guardrail metric",
        "experiment",
        "A metric an experiment must not damage, even if the primary metric improves: bounces, unsubscribes "
        "and negative replies.",
        "count of guardrail events ÷ emails sent per variant",
        "emails sent per variant",
        "Guardrails are evaluated for harm, not for lift: a variant that wins on replies but doubles "
        "unsubscribes should not ship.",
    ),
)

BY_KEY: dict[str, MetricDefinition] = {m.key: m for m in DEFINITIONS}


def as_list() -> list[dict[str, Any]]:
    return [m.as_dict() for m in DEFINITIONS]
