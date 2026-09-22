"""Multi-model pipeline attribution.

Given each opportunity's touches (campaign/channel interactions before it was created), distribute
its amount across touches under several models. Comparing the models side by side is the point:
first-touch rewards top-of-funnel campaigns, last-touch rewards whatever closed the meeting, linear
spreads credit. None of them is "the truth". Opportunities with no recorded touches are reported
as unattributed rather than silently credited to "direct".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

MODELS = ("first_touch", "last_touch", "linear", "u_shaped")
DEFAULT_LOOKBACK = timedelta(days=180)


@dataclass(frozen=True)
class Touch:
    key: str  # what receives credit: a campaign key, or channel when no campaign
    occurred_at: datetime
    touch_id: str


@dataclass(frozen=True)
class OpportunityFacts:
    id: str
    amount: float
    opened_at: datetime
    won: bool


@dataclass
class AttributionResult:
    model: str
    pipeline_by_key: dict[str, float]
    won_by_key: dict[str, float]
    opportunities_by_key: dict[str, float]
    unattributed_pipeline: float
    unattributed_opportunities: int
    total_pipeline: float
    details: dict[str, list[tuple[str, float]]] = field(default_factory=dict)


def weights_for(model: str, n: int) -> list[float]:
    if n <= 0:
        return []
    if model == "first_touch":
        return [1.0] + [0.0] * (n - 1)
    if model == "last_touch":
        return [0.0] * (n - 1) + [1.0]
    if model == "linear":
        return [1.0 / n] * n
    if model == "u_shaped":
        if n == 1:
            return [1.0]
        if n == 2:
            return [0.5, 0.5]
        middle = 0.2 / (n - 2)
        return [0.4] + [middle] * (n - 2) + [0.4]
    raise ValueError(f"unknown attribution model '{model}'")


def eligible_touches(touches: list[Touch], opened_at: datetime,
                     lookback: timedelta = DEFAULT_LOOKBACK) -> list[Touch]:
    window_start = opened_at - lookback
    return sorted((t for t in touches if window_start <= t.occurred_at <= opened_at),
                  key=lambda t: (t.occurred_at, t.touch_id))


def attribute(model: str, opps: list[OpportunityFacts], touches_by_opp: dict[str, list[Touch]],
              lookback: timedelta = DEFAULT_LOOKBACK) -> AttributionResult:
    pipeline: dict[str, float] = defaultdict(float)
    won: dict[str, float] = defaultdict(float)
    counts: dict[str, float] = defaultdict(float)
    details: dict[str, list[tuple[str, float]]] = {}
    unattr_amt, unattr_n, total = 0.0, 0, 0.0
    for o in sorted(opps, key=lambda x: x.id):
        total += o.amount
        ts = eligible_touches(touches_by_opp.get(o.id, []), o.opened_at, lookback)
        if not ts:
            unattr_amt += o.amount
            unattr_n += 1
            continue
        w = weights_for(model, len(ts))
        credit: dict[str, float] = defaultdict(float)
        for t, wt in zip(ts, w, strict=True):
            if wt > 0:
                credit[t.key] += wt
        details[o.id] = sorted(credit.items())
        for k, share in credit.items():
            pipeline[k] += o.amount * share
            counts[k] += share
            if o.won:
                won[k] += o.amount * share
    return AttributionResult(
        model,
        {k: round(v, 2) for k, v in pipeline.items()},
        {k: round(v, 2) for k, v in won.items()},
        {k: round(v, 3) for k, v in counts.items()},
        round(unattr_amt, 2),
        unattr_n,
        round(total, 2),
        details,
    )
