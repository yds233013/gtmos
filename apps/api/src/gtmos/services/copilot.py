"""GTM Copilot: natural-language questions over a *closed* set of approved analyses.

    question → intent + parameters → approved semantic query → deterministic metrics → explanation

No LLM ever writes or runs SQL. The planner maps a question onto one of the analyses in `INTENTS`
(each backed by functions in services/analytics.py and friends) and extracts only whitelisted
parameters (period, dimension). The answer is rendered from the computed numbers, and the response
includes the plan and the metric calls so every sentence can be traced.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from gtmos.services import analytics, experiments_service, stack_inspector
from gtmos.services.attribution_service import run as run_attribution


@dataclass
class Plan:
    intent: str
    confidence: float
    params: dict[str, Any] = field(default_factory=dict)
    steps: list[str] = field(default_factory=list)


INTENTS: dict[str, dict[str, Any]] = {
    "pipeline_change": {
        "label": "Explain a change in pipeline",
        "patterns": [r"pipeline", r"\b(fall|fell|drop|dropp|declin|down|decreas|change|chang|up|grow)"],
        "examples": ["Why did pipeline fall?", "What changed in pipeline this month?"],
    },
    "segment_conversion": {
        "label": "Compare conversion across a dimension",
        "patterns": [
            r"(segment|industry|industries|region|persona|campaign|grade|tier|source)",
            r"(convert|conversion|meeting|rate|best|highest|lowest|worst)",
        ],
        "examples": ["Which segment has the highest meeting conversion?", "Which campaign converts best to meetings?"],
    },
    "signal_correlation": {
        "label": "Signals associated with opportunities",
        "patterns": [r"signal", r"(correlat|predict|associat|opportunit|work|matter)"],
        "examples": ["Which signals correlate with opportunities?"],
    },
    "stuck": {
        "label": "Where accounts get stuck",
        "patterns": [r"(stuck|stall|leak|bottleneck|drop.?off)"],
        "examples": ["Where are accounts getting stuck?", "Where is pipeline leaking?"],
    },
    "investigate": {
        "label": "What to investigate",
        "patterns": [r"(investigate|priorit|focus|fix|should .*team|health)"],
        "examples": ["What should the GTM team investigate?"],
    },
    "experiment": {
        "label": "Experiment results",
        "patterns": [r"(experiment|a/b|test|variant|personaliz|funding.trigger)"],
        "examples": ["Did funding-trigger personalization work?"],
    },
    "attribution": {
        "label": "Pipeline attribution",
        "patterns": [r"(attribut|sourc|credit|which campaign.*(pipeline|revenue))"],
        "examples": ["Which campaigns sourced the most pipeline?"],
    },
    "velocity": {
        "label": "Sales velocity",
        "patterns": [r"(velocity|cycle|how long|win rate|deal size)"],
        "examples": ["What is our win rate and sales cycle?"],
    },
}

DIMENSION_WORDS = {
    "segment": "segment",
    "tier": "segment",
    "size": "segment",
    "industr": "industry",
    "region": "region",
    "geo": "region",
    "persona": "persona",
    "department": "persona",
    "campaign": "campaign",
    "grade": "score_grade",
    "score": "score_grade",
    "source": "source",
}
METRIC_WORDS = {
    "meeting": "meeting_rate",
    "opportunit": "opportunity_rate",
    "pipeline": "opportunity_rate",
    "engag": "engagement_rate",
    "repl": "engagement_rate",
}


def _period(q: str, default: int) -> int:
    m = re.search(r"(last|past)\s+(\d{1,3})\s*(day|week|month)", q)
    if m:
        n, unit = int(m.group(2)), m.group(3)
        return min(n * {"day": 1, "week": 7, "month": 30}[unit], 365)
    if "this month" in q or "last month" in q or "month" in q:
        return 30
    if "quarter" in q:
        return 90
    if "week" in q:
        return 7
    return default


def plan(question: str) -> Plan:
    q = question.lower().strip()
    best, best_score = "investigate", 0.0
    for key, spec in INTENTS.items():
        hits = sum(1 for p in spec["patterns"] if re.search(p, q))
        score = hits / len(spec["patterns"])
        if score > best_score:
            best, best_score = key, score
    params: dict[str, Any] = {}
    if best == "segment_conversion":
        params["dimension"] = next((d for w, d in DIMENSION_WORDS.items() if w in q), "segment")
        params["metric"] = next((m for w, m in METRIC_WORDS.items() if w in q), "meeting_rate")
        params["days"] = _period(q, 180)
    elif best == "pipeline_change":
        params["days"] = _period(q, 28)
    elif best in ("signal_correlation", "attribution", "velocity"):
        params["days"] = _period(q, 180)
    if best_score == 0:
        return Plan("unsupported", 0.0, params)
    return Plan(best, round(best_score, 2), params)


def _money(x: float) -> str:
    return f"${x / 1e6:.2f}M" if abs(x) >= 1e6 else f"${x / 1e3:,.0f}k"


def _pct(x: float) -> str:
    return f"{x:.1%}"


def answer(db: Session, ws: uuid.UUID, question: str) -> dict[str, Any]:
    p = plan(question)
    queries: list[dict[str, Any]] = []
    lines: list[str] = []
    data: dict[str, Any] = {}

    if p.intent == "pipeline_change":
        days = p.params["days"]
        cmp = analytics.period_comparison(db, ws, days)
        stuck = analytics.stuck_accounts(db, ws)
        queries += [
            {"metric": "period_comparison", "params": {"days": days}},
            {"metric": "stuck_accounts", "params": {}},
        ]
        cur, prev = cmp["current"], cmp["previous"]
        delta = cur["pipeline"] - prev["pipeline"]
        direction = "fell" if delta < 0 else "rose"
        lines.append(
            f"Pipeline created {direction} from {_money(prev['pipeline'])} ({prev['opportunities']} opps) "
            f"to {_money(cur['pipeline'])} ({cur['opportunities']} opps) in the last {days} days vs the "
            f"prior {days}."
        )
        movers = [r for r in cmp["by_source"] if r["delta_pipeline"] != 0]
        neg = [r for r in movers if r["delta_pipeline"] < 0][:3]
        pos = sorted((r for r in movers if r["delta_pipeline"] > 0), key=lambda r: -r["delta_pipeline"])[:2]
        if neg:
            lines.append(
                "Biggest decreases by source: "
                + "; ".join(
                    f"{r['key']} {_money(r['delta_pipeline'])} ({r['previous_count']}→{r['current_count']} opps)"
                    for r in neg
                )
                + "."
            )
        if pos:
            lines.append(
                "Offsetting increases: " + "; ".join(f"{r['key']} +{_money(r['delta_pipeline'])}" for r in pos) + "."
            )
        lines.append(
            f"Leading indicators: meetings {prev['meetings']}→{cur['meetings']}, emails sent "
            f"{prev['emails_sent']}→{cur['emails_sent']}."
        )
        if stuck["unowned_by_stage"]:
            n = sum(stuck["unowned_by_stage"].values())
            lines.append(
                f"{n} stalled accounts have no owner "
                f"({', '.join(f'{k}: {v}' for k, v in stuck['unowned_by_stage'].items())}). Check routing "
                "coverage."
            )
        data = {"comparison": cmp, "stuck_summary": {k: stuck[k] for k in ("by_stage", "unowned_by_stage", "total")}}

    elif p.intent == "segment_conversion":
        dim, metric, days = p.params["dimension"], p.params["metric"], p.params["days"]
        b = analytics.breakdown(db, ws, dim, days)
        queries.append({"metric": "breakdown", "params": {"dimension": dim, "days": days}})
        rows = [r for r in b["rows"] if not r["low_sample"]]
        small = [r["key"] for r in b["rows"] if r["low_sample"]]
        rows.sort(key=lambda r: -r[metric])
        label = metric.replace("_", " ")
        if rows:
            top, bottom = rows[0], rows[-1]
            lines.append(
                f"By {dim.replace('_', ' ')}, **{top['key']}** has the highest {label}: "
                f"{_pct(top[metric])} ({top['meetings']} meetings from {top['contacted']} contacted accounts, "
                f"last {days} days)."
            )
            if len(rows) > 1:
                lines.append(f"Lowest: {bottom['key']} at {_pct(bottom[metric])} ({bottom['contacted']} contacted).")
            lines.append("Ranking: " + ", ".join(f"{r['key']} {_pct(r[metric])}" for r in rows[:6]) + ".")
        else:
            lines.append("No group has enough contacted accounts (≥30) to compare reliably.")
        if small:
            lines.append(f"Excluded for small samples (<30 accounts): {', '.join(small[:6])}.")
        data = {"breakdown": b}

    elif p.intent == "signal_correlation":
        sc = analytics.signal_correlation(db, ws, p.params["days"])
        queries.append({"metric": "signal_correlation", "params": {"days": p.params["days"]}})
        rows = [r for r in sc["rows"] if not r["low_sample"] and r["lift"]]
        lines.append(
            f"Baseline: {_pct(sc['baseline_opportunity_rate'])} of {sc['contacted_accounts']} contacted "
            "accounts produced an opportunity."
        )
        for r in rows[:4]:
            lines.append(
                f"- **{r['label']}**: {_pct(r['opportunity_rate'])} opportunity rate across {r['accounts']} "
                f"accounts vs {_pct(r['rate_without_signal'])} without it (lift {r['lift']}×)."
            )
        lines.append(sc["caveat"])
        data = {"signal_correlation": sc}

    elif p.intent == "stuck":
        f = analytics.funnel(db, ws, 90)
        st = analytics.stuck_accounts(db, ws)
        queries += [{"metric": "funnel", "params": {"days": 90}}, {"metric": "stuck_accounts", "params": {}}]
        steps = [s for s in f["stages"] if s["conversion_from_previous"] is not None and s["stage"] != "contacted"]
        worst = min(steps, key=lambda s: s["conversion_from_previous"]) if steps else None
        if worst:
            lines.append(
                f"The weakest funnel step (90 days) is entering **{worst['stage']}**: "
                f"{_pct(worst['conversion_from_previous'])} conversion from the previous stage."
            )
        if st["by_stage"]:
            lines.append(
                "Accounts past their stage SLA: "
                + ", ".join(f"{k}: {v}" for k, v in st["by_stage"].items())
                + f" ({st['total']} total)."
            )
        if st["unowned_by_stage"]:
            lines.append(
                f"Of those, {sum(st['unowned_by_stage'].values())} have no owner: a routing gap, not a "
                "messaging problem."
            )
        data = {"funnel": f, "stuck": st}

    elif p.intent == "experiment":
        exps = experiments_service.list_experiments(db, ws)
        queries.append({"metric": "experiments", "params": {}})
        for e in exps:
            from gtmos.models import Experiment

            full = experiments_service.results(db, db.get(Experiment, uuid.UUID(e["id"])))  # type: ignore[arg-type]
            lines.append(
                f"**{full['name']}** ({full['status']}, {e['units']} {full['unit']}s): {full['verdict_explanation']}"
            )
        data = {"experiments": exps}

    elif p.intent == "attribution":
        a = run_attribution(db, ws, p.params["days"])
        queries.append({"metric": "attribution", "params": {"days": p.params["days"]}})
        rows = a["rows"][:5]
        lines.append(
            f"{a['opportunities']} opportunities ({_money(a['total_pipeline'])}) in {a['window_days']} days; "
            f"{a['unattributed_opportunities']} have no recorded touches."
        )
        for r in rows:
            lines.append(
                f"- {r['key']}: first-touch {_money(r['first_touch'])}, last-touch {_money(r['last_touch'])}, "
                f"linear {_money(r['linear'])}"
            )
        lines.append("Models disagree by design. Treat the spread as uncertainty, not a ranking.")
        data = {"attribution": a}

    elif p.intent == "velocity":
        v = analytics.velocity(db, ws, p.params["days"])
        queries.append({"metric": "velocity", "params": {"days": p.params["days"]}})
        lines.append(
            f"Win rate {_pct(v['win_rate'])} on {v['closed_deals']} closed deals; average won deal "
            f"{_money(v['avg_won_deal'])}; median cycle {v['median_cycle_days']} days."
        )
        if v["pipeline_velocity_per_day"]:
            lines.append(f"Pipeline velocity ≈ {_money(v['pipeline_velocity_per_day'])}/day ({v['formula']}).")
        if v["low_sample"]:
            lines.append("Fewer than 20 closed deals: treat these as directional.")
        data = {"velocity": v}

    elif p.intent == "unsupported":
        lines.append("I can only answer questions that map to an approved GTM analysis, and this one doesn't. "
                     "Try one of these:")
        lines.extend(f"- {q}" for q in suggested_questions()[:6])
    else:  # investigate
        rep = stack_inspector.inspect(db, ws)
        queries.append({"metric": "stack_inspector", "params": {}})
        bad = [s for s in rep["sections"] if s["status"] != "healthy"]
        if bad:
            lines.append(
                "Systems needing attention: "
                + "; ".join(f"{s['title']} ({s['status']}): {s['headline']}" for s in bad[:4])
                + "."
            )
        lines.append("Top recommendations:")
        for r in rep["recommendations"][:5]:
            lines.append(f"{r['rank']}. **{r['title']}**: {r['why']}")
        data = {"stack_inspector": {"sections": rep["sections"], "recommendations": rep["recommendations"][:5]}}

    p.steps = [
        f"Classified intent: {INTENTS.get(p.intent, {}).get('label', p.intent)} (confidence {p.confidence})",
        *[f"Ran approved metric `{q['metric']}` with {q['params'] or 'default parameters'}" for q in queries],
        "Rendered the answer from computed values only",
    ]
    return {
        "question": question,
        "intent": p.intent,
        "confidence": p.confidence,
        "params": p.params,
        "plan": p.steps,
        "queries": queries,
        "answer": "\n".join(lines),
        "data": data,
        "generator": "deterministic",
        "guardrails": [
            "No free-form SQL: only whitelisted analytics functions are callable.",
            "Numbers in the answer are computed, never generated.",
            "Small samples are flagged and excluded from rankings.",
        ],
        "suggested": [ex for spec in INTENTS.values() for ex in spec["examples"]][:8],
    }


def suggested_questions() -> list[str]:
    return [ex for spec in INTENTS.values() for ex in spec["examples"]]
