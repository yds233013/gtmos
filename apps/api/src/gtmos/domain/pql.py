"""Product-qualified accounts: when does product usage mean a human should get involved?

A single product event is almost never a buying signal. One person signing up for a free tier is
noise; the same company putting three people in the product, connecting it to their production model
provider and crossing a volume threshold in the same fortnight is a different thing entirely — that is
a team that has adopted the product without talking to anyone, and the cost of not calling them is
that they either churn quietly or buy the smallest possible plan.

So qualification is evaluated at the **account** level over a window, not per event, and it is a
*composite* rule. Three design decisions worth defending:

* **Breadth before depth.** Multiple distinct users matter more than one user doing a lot, because a
  single enthusiastic engineer is a champion and a team is a budget. `distinct_users` is the first
  criterion for that reason.
* **Depth of integration is the strongest single predictor.** Connecting a production provider or
  sending real traffic is an act with switching costs behind it; a pricing-page view is an intention.
  The weights reflect that ordering.
* **Qualification fires once.** An account that keeps using the product should not generate a fresh
  PQL alert every day — the signal is "this account crossed the line", and crossing it twice is not
  news. Deduplication happens on the signal's `source_ref`, which encodes the account and the window.

Nothing here is learned from outcomes. These are hand-set weights and a hand-set threshold, exactly
like the ICP score, and `docs/scoring-evaluation.md` applies to them just as much: the honest claim is
that this encodes a defensible opinion about product-led qualification, not that it is calibrated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

# The window over which product behaviour is read. Two weeks is short enough that the behaviour is
# current and long enough to catch a team that evaluates over a sprint.
PQL_WINDOW = timedelta(days=14)

# Points per criterion, and the bar. Set so that no single criterion qualifies an account on its own:
# the highest is 30 against a threshold of 55, which forces at least two independent kinds of evidence.
PQL_THRESHOLD = 55


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    points: int
    why: str


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "multiple_users",
        "Three or more distinct users",
        25,
        "A team, not an individual. One engineer exploring is a champion; three is a budget holder's problem to solve.",
    ),
    Criterion(
        "second_user",
        "A second user joined",
        10,
        "The weaker version of the same signal, worth something on its own because it means the first "
        "user told a colleague.",
    ),
    Criterion(
        "integration_connected",
        "Connected a production integration",
        30,
        "The strongest single act: wiring the product to a model provider or tracing SDK has switching "
        "costs behind it, so it is a decision rather than an intention.",
    ),
    Criterion(
        "usage_threshold",
        "Crossed the usage threshold",
        25,
        "Real traffic through the product. Distinguishes evaluation from adoption.",
    ),
    Criterion(
        "pricing_intent",
        "Viewed pricing",
        10,
        "Commercial intent, but cheap to fake and easy to misread — a rep checking a competitor looks "
        "identical. Deliberately the smallest weight.",
    ),
)

BY_KEY = {c.key: c for c in CRITERIA}


@dataclass
class PQLAssessment:
    account_id: str
    score: int
    qualified: bool
    met: list[dict[str, Any]] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)
    distinct_users: int = 0
    window_days: int = PQL_WINDOW.days
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "score": self.score,
            "threshold": PQL_THRESHOLD,
            "qualified": self.qualified,
            "distinct_users": self.distinct_users,
            "window_days": self.window_days,
            "met": self.met,
            "missing": self.missing,
            "summary": self.summary,
        }


def assess(
    account_id: str,
    *,
    distinct_users: int,
    event_counts: dict[str, int],
    now: datetime | None = None,
) -> PQLAssessment:
    """Score an account's recent product behaviour against the criteria.

    `event_counts` is the number of times each product event occurred in the window, keyed by the
    GTMOS event name. Counts rather than booleans because the caller already has them, and because a
    future version may want to weight repetition — today it does not, deliberately: a team that
    connected four integrations is not four times as qualified as one that connected one.
    """
    met: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    def record(key: str, satisfied: bool, evidence: str) -> int:
        c = BY_KEY[key]
        entry = {"key": c.key, "label": c.label, "points": c.points, "why": c.why, "evidence": evidence}
        if satisfied:
            met.append(entry)
            return c.points
        missing.append(entry)
        return 0

    score = 0
    score += record(
        "multiple_users",
        distinct_users >= 3,
        f"{distinct_users} distinct users active in the window",
    )
    # Only credited when the stronger criterion did not fire, so a team of five is not paid twice for
    # the same fact.
    score += record(
        "second_user",
        2 <= distinct_users < 3,
        f"{distinct_users} distinct users active in the window",
    )
    score += record(
        "integration_connected",
        event_counts.get("integration_connected", 0) > 0,
        f"{event_counts.get('integration_connected', 0)} integration_connected events",
    )
    score += record(
        "usage_threshold",
        event_counts.get("usage_threshold", 0) > 0 or event_counts.get("trace_volume_threshold", 0) > 0,
        f"{event_counts.get('usage_threshold', 0) + event_counts.get('trace_volume_threshold', 0)} threshold events",
    )
    score += record(
        "pricing_intent",
        event_counts.get("pricing_page_viewed", 0) > 0,
        f"{event_counts.get('pricing_page_viewed', 0)} pricing page views",
    )

    qualified = score >= PQL_THRESHOLD
    if qualified:
        reasons = ", ".join(m["label"].lower() for m in met)
        summary = f"Product-qualified at {score}/{PQL_THRESHOLD}: {reasons}."
    else:
        needed = PQL_THRESHOLD - score
        nearest = min(missing, key=lambda m: abs(m["points"] - needed), default=None)
        summary = f"Not yet product-qualified ({score}/{PQL_THRESHOLD})." + (
            f" Closest missing criterion: {nearest['label'].lower()}." if nearest else ""
        )

    return PQLAssessment(
        account_id=account_id,
        score=score,
        qualified=qualified,
        met=met,
        missing=missing,
        distinct_users=distinct_users,
        summary=summary,
    )


def window_ref(account_id: str, when: datetime) -> str:
    """A stable dedupe key: one qualification per account per ISO week.

    Without this, an account that stays qualified emits a fresh signal on every product event, which
    turns a meaningful alert into a background hum a rep learns to ignore.
    """
    year, week, _ = when.isocalendar()
    return f"pql:{account_id}:{year}-W{week:02d}"
