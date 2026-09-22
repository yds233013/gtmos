"""Explainable, deterministic account scoring.

score_account() is a pure function of (ICP definition, account facts, signals, engagement, now).
The same inputs always produce the same score, components, and explanations, which is what lets us
unit-test it, diff it between ICP versions, and trust it enough to route revenue on.

Score = Fit + Intent + Timing + Technical + Engagement (category budgets come from ICP weights and
sum to 100). Every point is attributed to a named component with a sentence explaining it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from gtmos.domain.icp import ICPDefinition
from gtmos.domain.signals import SIGNAL_TYPES, decay_factor

GRADE_THRESHOLDS = (("A", 80), ("B", 65), ("C", 50))
ADDITIONAL_SIGNAL_WEIGHT = 0.25  # each extra signal of the same type adds 25% of its value

# Fixed internal shares of each category budget. Changing ICP weights rescales these proportionally.
FIT_SHARES = {"industry": 15 / 35, "company_size": 12 / 35, "geography": 8 / 35}
TECH_SHARES = {"ai_team": 6 / 15, "llm_stack": 6 / 15, "platform": 3 / 15}
TIMING_GROWTH_SHARE = 3 / 15
ENGAGEMENT_SALES_SHARE = 5 / 10


@dataclass(frozen=True)
class AccountFacts:
    name: str
    domain: str | None
    industry: str | None
    employee_count: int | None
    region: str | None
    country: str | None
    employee_growth_12m: float | None
    technologies: tuple[str, ...] = ()
    ai_team_size: int | None = None
    is_customer: bool = False


@dataclass(frozen=True)
class SignalFact:
    id: str
    signal_type: str
    observed_at: datetime
    strength: float
    confidence: float
    title: str


@dataclass(frozen=True)
class EngagementFacts:
    replies_90d: int = 0
    positive_replies_90d: int = 0
    meetings_90d: int = 0


@dataclass
class Component:
    category: str
    key: str
    label: str
    points: float
    max_points: float
    explanation: str
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CategoryScore:
    category: str
    points: float
    max_points: float
    capped: bool
    components: list[Component]


@dataclass
class ScoreResult:
    total: int
    grade: str
    excluded: bool
    exclusion_reason: str | None
    categories: dict[str, CategoryScore]
    summary: str
    inputs_hash: str

    def category_points(self, category: str) -> float:
        return self.categories[category].points

    def components(self) -> list[Component]:
        return [c for cat in self.categories.values() for c in cat.components]


def grade_for(total: int) -> str:
    for grade, threshold in GRADE_THRESHOLDS:
        if total >= threshold:
            return grade
    return "D"


def _r(x: float) -> float:
    """Component precision. Categories are rounded to one decimal after summing, so display drift is <0.1."""
    return round(x + 0.0, 2)


def _fmt_int(n: int) -> str:
    return f"{n:,}"


# --------------------------------------------------------------------------------------------------
# Category scorers
# --------------------------------------------------------------------------------------------------


def _score_fit(icp: ICPDefinition, a: AccountFacts, budget: float) -> list[Component]:
    comps: list[Component] = []

    mx = budget * FIT_SHARES["industry"]
    if a.industry in icp.core_industries:
        pts, why = mx, f"{a.industry} is a core ICP industry."
    elif a.industry in icp.adjacent_industries:
        pts, why = mx * 0.5, f"{a.industry} is an adjacent industry (half credit)."
    elif a.industry is None:
        pts, why = 0.0, "Industry unknown. Enrichment needed before this can score."
    else:
        pts, why = 0.0, f"{a.industry} is outside the target industries."
    comps.append(
        Component("fit", "industry", "Industry", _r(pts), _r(mx), why, [{"field": "industry", "value": a.industry}])
    )

    mx = budget * FIT_SHARES["company_size"]
    s = icp.size
    n = a.employee_count
    if n is None:
        pts, why = 0.0, "Employee count unknown. Enrichment needed."
    elif s.sweet_spot_min <= n <= s.sweet_spot_max:
        pts = mx
        why = (
            f"{_fmt_int(n)} employees is inside the sweet spot "
            f"({_fmt_int(s.sweet_spot_min)}–{_fmt_int(s.sweet_spot_max)})."
        )
    elif s.min_employees <= n <= s.max_employees:
        pts = mx * 0.65
        why = (
            f"{_fmt_int(n)} employees is within the target range "
            f"({_fmt_int(s.min_employees)}–{_fmt_int(s.max_employees)}) but outside the sweet spot."
        )
    elif n > s.max_employees:
        pts, why = mx * 0.4, f"{_fmt_int(n)} employees is above the target range (long sales cycle risk)."
    else:
        pts, why = mx * 0.15, f"{_fmt_int(n)} employees is below the target range."
    comps.append(
        Component(
            "fit", "company_size", "Company size", _r(pts), _r(mx), why, [{"field": "employee_count", "value": n}]
        )
    )

    mx = budget * FIT_SHARES["geography"]
    if a.region in icp.primary_regions:
        pts, why = mx, f"Headquartered in a primary region ({a.region})."
    elif a.region in icp.secondary_regions:
        pts, why = mx * 0.5, f"Headquartered in a secondary region ({a.region})."
    elif a.region is None:
        pts, why = 0.0, "Region unknown."
    else:
        pts, why = 0.0, f"Region {a.region} is not currently served."
    comps.append(
        Component(
            "fit",
            "geography",
            "Geography",
            _r(pts),
            _r(mx),
            why,
            [{"field": "region", "value": a.region}, {"field": "country", "value": a.country}],
        )
    )
    return comps


def _score_technical(icp: ICPDefinition, a: AccountFacts, budget: float) -> list[Component]:
    t = icp.technical
    comps: list[Component] = []

    mx = budget * TECH_SHARES["ai_team"]
    size = a.ai_team_size
    if size is None:
        pts, why = 0.0, "AI/ML team size unknown."
    elif size >= t.ai_team_strong:
        pts, why = mx, f"AI/ML org of ~{size} engineers (≥{t.ai_team_strong}): mature buyer."
    elif size >= t.ai_team_min:
        pts, why = mx * 0.6, f"AI/ML org of ~{size} engineers: meaningful but still growing."
    elif size > 0:
        pts, why = mx * 0.25, f"Small AI/ML team (~{size}); may not feel reliability pain yet."
    else:
        pts, why = 0.0, "No dedicated AI/ML team detected."
    comps.append(
        Component(
            "technical", "ai_team", "AI/ML team", _r(pts), _r(mx), why, [{"field": "ai_team_size", "value": size}]
        )
    )

    techs = set(a.technologies)
    llm = sorted(techs & set(t.llm_stack))
    mx = budget * TECH_SHARES["llm_stack"]
    ratio = {0: 0.0, 1: 0.4, 2: 0.7}.get(len(llm), 1.0)
    why = (
        f"Runs {len(llm)} LLM-stack technologies: {', '.join(llm)}."
        if llm
        else "No LLM application stack detected in technographics."
    )
    comps.append(
        Component(
            "technical",
            "llm_stack",
            "LLM stack",
            _r(mx * ratio),
            _r(mx),
            why,
            [{"field": "technologies", "value": llm}],
        )
    )

    plat = sorted(techs & set(t.platform_stack))
    mx = budget * TECH_SHARES["platform"]
    ratio = {0: 0.0, 1: 0.5}.get(len(plat), 1.0)
    why = f"Production platform maturity: {', '.join(plat)}." if plat else "No production data/infra platform detected."
    comps.append(
        Component(
            "technical",
            "platform",
            "Platform maturity",
            _r(mx * ratio),
            _r(mx),
            why,
            [{"field": "technologies", "value": plat}],
        )
    )
    return comps


def signal_value(s: SignalFact, typical_strength: float, half_life_days: float, now: datetime) -> float:
    """0..1 value of one signal: confidence × relative strength × time decay.

    Strength is judged relative to what is typical for the signal type (a $120M round vs. a $5M one),
    so a fresh, confident, typical signal earns ~its full budget and decays from there.
    """
    relative = min(s.strength / typical_strength, 1.25) if typical_strength > 0 else 1.0
    return min(1.0, s.confidence * relative * decay_factor(s.observed_at, now, half_life_days))


def _age_phrase(observed_at: datetime, now: datetime) -> str:
    days = int(max((now - observed_at).total_seconds(), 0) // 86400)
    if days == 0:
        return "today"
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"


def _signal_components(icp: ICPDefinition, category: str, signals: list[SignalFact], now: datetime) -> list[Component]:
    comps: list[Component] = []
    by_type: dict[str, list[SignalFact]] = {}
    for s in signals:
        spec = SIGNAL_TYPES.get(s.signal_type)
        if spec and spec.category == category and s.signal_type in icp.positive_signals:
            by_type.setdefault(s.signal_type, []).append(s)

    for sig_type, max_pts in icp.positive_signals.items():
        spec = SIGNAL_TYPES[sig_type]
        if spec.category != category or max_pts <= 0:
            continue
        found = by_type.get(sig_type, [])
        if not found:
            continue
        valued = sorted(
            ((signal_value(s, spec.default_strength, spec.half_life_days, now), s) for s in found),
            key=lambda p: (-p[0], p[1].id),
        )
        best_val, best = valued[0]
        extra = sum(v for v, _ in valued[1:]) * ADDITIONAL_SIGNAL_WEIGHT
        raw = min(1.0, best_val + extra)
        pts = max_pts * raw
        more = f" (+{len(valued) - 1} more)" if len(valued) > 1 else ""
        why = (
            f"{best.title}, observed {_age_phrase(best.observed_at, now)}{more}. "
            f"Confidence {best.confidence:.0%}, strength {best.strength:.2f} (typical "
            f"{spec.default_strength:.2f}), {spec.half_life_days:g}-day half-life → {raw:.0%} of "
            f"{max_pts:g} pts."
        )
        comps.append(
            Component(
                category,
                f"signal:{sig_type}",
                spec.name,
                _r(pts),
                _r(max_pts),
                why,
                [
                    {
                        "signal_id": s.id,
                        "title": s.title,
                        "observed_at": s.observed_at.isoformat(),
                        "value": round(v, 3),
                    }
                    for v, s in valued[:5]
                ],
            )
        )
    return comps


def _score_timing(
    icp: ICPDefinition, a: AccountFacts, signals: list[SignalFact], now: datetime, budget: float
) -> list[Component]:
    comps = _signal_components(icp, "timing", signals, now)
    mx = budget * TIMING_GROWTH_SHARE
    g = a.employee_growth_12m
    if g is None:
        pts, why = 0.0, "Headcount growth unknown."
    elif g >= 0.30:
        pts, why = mx, f"Headcount grew {g:.0%} in 12 months: rapid scaling."
    elif g >= 0.15:
        pts, why = mx * 0.6, f"Headcount grew {g:.0%} in 12 months."
    elif g >= icp.min_growth_rate:
        pts, why = mx * 0.25, f"Modest headcount growth ({g:.0%})."
    else:
        pts, why = 0.0, f"Flat or shrinking headcount ({g:.0%})."
    comps.append(
        Component(
            "timing",
            "headcount_growth",
            "Headcount growth",
            _r(pts),
            _r(mx),
            why,
            [{"field": "employee_growth_12m", "value": g}],
        )
    )
    return comps


def _score_engagement(
    icp: ICPDefinition, signals: list[SignalFact], e: EngagementFacts, now: datetime, budget: float
) -> list[Component]:
    mx = budget * ENGAGEMENT_SALES_SHARE
    if e.meetings_90d > 0:
        ratio, why = 1.0, f"{e.meetings_90d} meeting(s) in the last 90 days."
    elif e.positive_replies_90d > 0:
        ratio, why = 0.8, f"{e.positive_replies_90d} positive repl(ies) in the last 90 days."
    elif e.replies_90d > 0:
        ratio, why = 0.5, f"{e.replies_90d} repl(ies) in the last 90 days (not yet positive)."
    else:
        ratio, why = 0.0, "No two-way sales engagement in the last 90 days."
    comps = [Component("engagement", "sales_engagement", "Sales engagement", _r(mx * ratio), _r(mx), why, [asdict(e)])]
    comps.extend(_signal_components(icp, "engagement", signals, now))
    return comps


# --------------------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------------------


def _exclusion(icp: ICPDefinition, a: AccountFacts) -> str | None:
    if a.industry and a.industry in icp.excluded_industries:
        return f"Industry '{a.industry}' is excluded by the ICP."
    if a.country and a.country in icp.excluded_countries:
        return f"Country '{a.country}' is excluded (compliance)."
    if a.domain and a.domain.lower() in {d.lower() for d in icp.excluded_domains}:
        return f"Domain '{a.domain}' is on the do-not-target list."
    if a.employee_count is not None and a.employee_count < icp.size.hard_min_employees:
        return f"{a.employee_count} employees is below the hard minimum of {icp.size.hard_min_employees}."
    return None


def compute_inputs_hash(
    icp: ICPDefinition, a: AccountFacts, signals: list[SignalFact], e: EngagementFacts, now: datetime
) -> str:
    payload = {
        "icp": icp.model_dump(mode="json"),
        "account": asdict(a),
        "signals": sorted(
            [{**asdict(s), "observed_at": s.observed_at.isoformat()} for s in signals],
            key=lambda d: d["id"],
        ),
        "engagement": asdict(e),
        "day": now.date().isoformat(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _summary(result_cats: dict[str, CategoryScore], total: int) -> str:
    comps = [c for cat in result_cats.values() for c in cat.components if c.points > 0]
    comps.sort(key=lambda c: (-c.points / max(c.max_points, 0.01) * c.points, c.key))
    top = [c.label.lower() for c in comps[:3]]
    gaps = [cat.category for cat in result_cats.values() if cat.max_points > 0 and cat.points / cat.max_points < 0.35]
    parts = [f"Scores {total}/100"]
    if top:
        parts.append("driven by " + ", ".join(top))
    text = "; ".join(parts) + "."
    if gaps:
        text += " Weak on " + ", ".join(gaps) + "."
    return text


def score_account(
    icp: ICPDefinition,
    account: AccountFacts,
    signals: list[SignalFact],
    engagement: EngagementFacts,
    now: datetime,
) -> ScoreResult:
    weights = icp.weights.as_dict()
    inputs_hash = compute_inputs_hash(icp, account, signals, engagement, now)
    # Future-dated signals (clock skew, bad feed) are ignored rather than trusted.
    live_signals = [s for s in signals if s.observed_at <= now]

    raw: dict[str, list[Component]] = {
        "fit": _score_fit(icp, account, weights["fit"]),
        "intent": _signal_components(icp, "intent", live_signals, now),
        "timing": _score_timing(icp, account, live_signals, now, weights["timing"]),
        "technical": _score_technical(icp, account, weights["technical"]),
        "engagement": _score_engagement(icp, live_signals, engagement, now, weights["engagement"]),
    }
    categories: dict[str, CategoryScore] = {}
    for cat, comps in raw.items():
        budget = weights[cat]
        subtotal = sum(c.points for c in comps)
        categories[cat] = CategoryScore(
            category=cat,
            points=round(min(subtotal, budget), 1),
            max_points=round(budget, 1),
            capped=subtotal > budget + 1e-9,
            components=comps,
        )

    reason = _exclusion(icp, account)
    if reason:
        return ScoreResult(0, "X", True, reason, categories, f"Excluded: {reason}", inputs_hash)

    total = round(sum(c.points for c in categories.values()))
    total = max(0, min(100, total))
    return ScoreResult(total, grade_for(total), False, None, categories, _summary(categories, total), inputs_hash)


def intent_index(result: ScoreResult) -> int:
    """0–100 normalization of intent + timing + engagement: 'why now', independent of fit."""
    keys = ("intent", "timing", "engagement")
    got = sum(result.categories[k].points for k in keys)
    mx = sum(result.categories[k].max_points for k in keys)
    return round(100 * got / mx) if mx else 0
