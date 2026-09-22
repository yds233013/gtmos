"""Buying-signal catalog and time decay.

A signal is an observed, timestamped fact that changes *when* or *whether* an account is likely to buy.
Each type has a scoring category, a default strength, and a half-life: a funding round is relevant for
months, a pricing-page visit for about two weeks.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SignalTypeSpec:
    key: str
    name: str
    category: str  # intent | timing | engagement
    default_strength: float
    half_life_days: float
    description: str
    # Negative signals subtract points instead of adding them. A taxonomy where every observation is
    # encouraging is a taxonomy that cannot tell you to stop, and "stop working this account" is the
    # cheapest recommendation a GTM system can make.
    is_negative: bool = False
    # What a rep should do about it, since a negative signal is an instruction, not a data point.
    action: str = ""


SIGNAL_TYPES: dict[str, SignalTypeSpec] = {
    s.key: s
    for s in (
        SignalTypeSpec(
            "funding_round",
            "Funding round",
            "timing",
            0.9,
            90,
            "New priced equity round. Budget is being allocated and new initiatives start.",
        ),
        SignalTypeSpec(
            "executive_hire",
            "Executive hire",
            "timing",
            0.75,
            120,
            "New technical executive (CTO, VP Eng, Head of AI). New leaders re-evaluate tooling.",
        ),
        SignalTypeSpec(
            "expansion",
            "Expansion",
            "timing",
            0.5,
            120,
            "New office, region or business line; operating complexity rises.",
        ),
        SignalTypeSpec(
            "ai_hiring_surge",
            "AI/ML hiring surge",
            "intent",
            0.85,
            45,
            "Material increase in open AI/ML roles; the AI org is scaling.",
        ),
        SignalTypeSpec(
            "job_posting",
            "Relevant job posting",
            "intent",
            0.65,
            30,
            "A posting that names the problem we solve (LLM evaluation, AI reliability, agent ops).",
        ),
        SignalTypeSpec(
            "ai_product_launch",
            "AI product launch",
            "intent",
            0.8,
            60,
            "Shipped an LLM feature or agent to customers; production reliability now matters.",
        ),
        SignalTypeSpec(
            "tech_adoption",
            "Technology adoption",
            "intent",
            0.6,
            90,
            "Adopted an LLM framework, model provider or vector database.",
        ),
        SignalTypeSpec(
            "pricing_page_visit",
            "Pricing page activity",
            "intent",
            0.7,
            14,
            "Repeated visits to our pricing page from the account's network or known users.",
        ),
        SignalTypeSpec(
            "website_visit", "Website engagement", "engagement", 0.3, 14, "Visits to docs, blog or product pages."
        ),
        SignalTypeSpec(
            "product_signup",
            "Product signup",
            "engagement",
            0.6,
            30,
            "Someone at the account created a free workspace.",
        ),
        SignalTypeSpec(
            "teammate_invited",
            "Invited teammates",
            "engagement",
            0.7,
            30,
            "Free workspace invited additional teammates: usage is spreading.",
        ),
        SignalTypeSpec(
            "integration_activated",
            "Integration activated",
            "engagement",
            0.8,
            30,
            "Connected a production model provider or tracing SDK.",
        ),
        SignalTypeSpec(
            "usage_threshold",
            "Usage threshold reached",
            "engagement",
            0.9,
            21,
            "Crossed the free-tier trace volume threshold: a product-qualified account.",
        ),
        # --- Negative and disqualifying signals ---------------------------------------------------
        SignalTypeSpec(
            "competitor_adopted",
            "Competitor adopted",
            "intent",
            0.9,
            180,
            "Public evidence the account deployed a competing platform. Not permanent — renewals come "
            "round — but the near-term window is closed.",
            is_negative=True,
            action="Stop the current sequence. Re-approach near their renewal with a migration angle.",
        ),
        SignalTypeSpec(
            "layoffs",
            "Layoffs announced",
            "timing",
            0.8,
            120,
            "Workforce reduction announced. Budgets freeze, champions leave, and headcount-based fit "
            "figures are now stale.",
            is_negative=True,
            action="Pause outbound and re-enrich. Reaching out with a growth pitch during layoffs damages the brand.",
        ),
        SignalTypeSpec(
            "budget_freeze",
            "Budget freeze",
            "timing",
            0.85,
            90,
            "Hiring or spending freeze reported. New spend needs an exception, which lengthens every cycle.",
            is_negative=True,
            action="Keep the relationship warm; move the forecast date out rather than pushing the deal.",
        ),
        SignalTypeSpec(
            "champion_departed",
            "Champion departed",
            "engagement",
            0.9,
            60,
            "The contact driving the evaluation left the company. The deal's memory left with them.",
            is_negative=True,
            action="Multithread immediately: the replacement has no context and no commitment.",
        ),
        SignalTypeSpec(
            "unsubscribed",
            "Unsubscribed or asked to stop",
            "engagement",
            1.0,
            365,
            "Someone at the account asked not to be contacted. Compliance, not preference.",
            is_negative=True,
            action="Suppress the account from outbound. Inbound and existing threads only.",
        ),
        SignalTypeSpec(
            "ai_project_cancelled",
            "AI initiative cancelled",
            "intent",
            0.8,
            150,
            "The programme our product serves was publicly shelved. The use case, not the budget, is gone.",
            is_negative=True,
            action="Disqualify for this cycle and set a reminder rather than burning sequence capacity.",
        ),
    )
}

NEGATIVE_SIGNAL_TYPES = frozenset(k for k, s in SIGNAL_TYPES.items() if s.is_negative)

CATEGORIES = ("fit", "intent", "timing", "technical", "engagement")


def decay_factor(observed_at: datetime, now: datetime, half_life_days: float) -> float:
    """Exponential decay: 1.0 when fresh, 0.5 after one half-life. Future timestamps are clamped to 1.0."""
    age_days = max((now - observed_at).total_seconds() / 86400.0, 0.0)
    return math.pow(0.5, age_days / half_life_days)


def signal_dedupe_key(signal_type: str, account_key: str, source_ref: str) -> str:
    """Stable key so the same real-world event ingested twice (e.g. from two feeds) becomes one signal."""
    raw = f"{signal_type}|{account_key.lower()}|{source_ref.strip().lower()}"
    return f"{signal_type}:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"
