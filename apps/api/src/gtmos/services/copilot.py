"""GTM Copilot: natural-language questions over a *closed* set of approved analyses.

    question → intent + parameters → approved semantic query → deterministic metrics → explanation

No LLM ever writes or runs SQL. The planner maps a question onto one of the analyses in `INTENTS`
(each backed by functions in services/analytics.py and friends) and extracts only whitelisted
parameters (period, dimension). The answer is rendered from the computed numbers, and the response
includes the plan and the metric calls so every sentence can be traced.

Anything the closed set cannot serve is refused *by name* rather than approximated: see `REFUSALS`
and `UNSUPPORTED_METRICS` below.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from gtmos.models import Account
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

# Refusals -----------------------------------------------------------------------------------------
# The closed INTENTS set is the actual safety boundary: there is no free-form SQL to inject into and
# only the analytics functions above can run. These two tables exist so a request the Copilot cannot
# serve is refused explicitly instead of falling through to the fuzzy matcher, which otherwise latches
# onto a single shared word ("churn *rate*" → meeting rate, "disable every *work*flow" → signal
# correlation) and answers a question GTMOS never asked. Verbs are listed in their imperative form
# only, so "how many emails were sent" still routes to an analysis while "send the sequence" does not.

CAPABILITIES = (
    "pipeline created and what moved it; funnel conversion and where accounts stall; conversion by "
    "segment, industry, region, persona or campaign; which signals lift opportunity rate; experiment "
    "results; campaign attribution; win rate and sales cycle"
)

REFUSALS: dict[str, tuple[str, str]] = {
    # Destructive verbs are refused when they are *commands*, not whenever they appear: "how many emails
    # did we send last month" is a reporting question and must be answered, while "send the sequence to
    # everyone" must not. So the bare verbs only fire at the start of the request, after an explicit
    # "can you …", or against a global object ("delete all contacts").
    "write_action": (
        r"\b(drop\s+table|truncate|delete\s+from|insert\s+into|alter\s+table|grant\s+all"
        r"|update\s+\w+\s+set|;\s*(select|delete|drop|update|insert|truncate|alter))\b"
        r"|^\s*(?:please\s+|now\s+|just\s+)?(delete|remove|purge|wipe|disable|deactivate|unsubscribe"
        r"|reset|archive|send|enroll|launch|revoke|reassign|merge|overwrite)\b"
        r"|\b(?:can|could|would|will|please)\s+(?:you\s+)?(?:please\s+)?(delete|remove|purge|wipe|disable"
        r"|deactivate|unsubscribe|reset|archive|send|enroll|launch|revoke|reassign|merge|overwrite)\b"
        r"|\b(delete|remove|purge|wipe|disable|deactivate|unsubscribe|revoke|archive)\s+"
        r"(all|every|everyone|everything|each)\b",
        "I am read-only. I report on what already happened and never change data, send outreach, or turn anything off.",
    ),
    "secrets": (
        r"\b(password|passwd|api[ _-]?key|secret|access\s+token|credential|bearer|private\s+key"
        r"|ssh\s+key|environment\s+variables?|env\s+vars?|connection\s+string|ssn|social\s+security"
        r"|salary|salaries)\b"
        r"|\b(phone|mobile|email)\s+(numbers?|addresses?)\b|\beveryone'?s\s+(email|phone|contact)",
        "I do not have access to credentials, configuration or personal contact details, and I would "
        "not return them if I did.",
    ),
    "prompt_injection": (
        r"\b(ignore|disregard|forget)\s+(your|the|all|any|previous|prior|earlier|above)"
        r"|\bsystem\s+prompt\b|\b(admin|developer|god|debug)\s+mode\b|\bjailbreak\b|\byou\s+are\s+now\b"
        r"|\bact\s+as\b|\bfor\s+testing\s+purposes\b|\bbypass\b|\boverride\s+your\b"
        r"|\braw\s+(accounts|contacts|data|database|table|sql)\b|\bdump\b",
        "My instructions are not negotiable and there is no privileged mode to switch into: every "
        "answer comes from the same approved analyses.",
    ),
    "fabrication": (
        r"\b(invent|fabricate|hallucinate|make\s+up|made\s+up|guess|pretend|just\s+say)\b",
        "Every number I return is computed by an approved metric. I will not invent, estimate or "
        "round one into existence.",
    ),
}

# Business metrics GTMOS has no concept of. Matching one is decisive: better to name the gap than to
# answer with the nearest metric that happens to share a word.
UNSUPPORTED_METRICS: dict[str, tuple[str, str]] = {
    "revenue, ARR or bookings": (
        r"\b(revenue|arr|mrr|acv|tcv|bookings|billings|invoices?)\b",
        "pipeline created (opportunity amount), campaign attribution and win rate",
    ),
    "churn, retention or renewals": (
        r"\b(churn|retention|renewals?|nrr|grr|downgrades?)\b",
        "funnel conversion, where accounts stall, and opportunity rate by segment",
    ),
    "customer, user or seat counts": (
        r"\bhow\s+many\s+(customers|logos|users|seats|subscribers)\b"
        r"|\b(customer|logo|seat|user)\s+(count|base)\b",
        "account, contact, meeting and opportunity counts",
    ),
    "NPS, CSAT or support volume": (
        r"\b(nps|c-?sat|net\s+promoter|customer\s+satisfaction|support\s+tickets?)\b",
        "engagement and meeting rates by segment or campaign",
    ),
    "CAC, LTV, quota or forecast": (
        r"\b(cac|ltv|cltv|payback|burn\s+rate|runway|quota|forecast)\b",
        "pipeline created, win rate, average won deal and median cycle length",
    ),
    "headcount or compensation": (
        r"\b(headcount|compensation|commissions?|payroll)\b",
        "account and contact coverage, including unowned accounts",
    ),
}

OUT_OF_SCOPE_LABELS = {
    "refused": "Refused: outside the Copilot's remit",
    "unsupported_metric": "Refused: metric GTMOS does not track",
    "unknown_entity": "Refused: unknown account",
    "unsupported": "No approved analysis matches",
}

# A company the question scopes to: quoted, a domain, or two or more capitalised words after a
# preposition. One capitalised word is deliberately ignored — "for Enterprise accounts" is a segment.
SCOPED_NAME = re.compile(r"\b(?:for|at|about|on|with|of)\s+((?:[A-Z][\w&.'-]+)(?:\s+[A-Z][\w&.'-]+)+)")
# Double quotes only: a straight apostrophe would turn "what's the team's focus" into a company name.
QUOTED_NAME = re.compile(r"[\"“]([A-Za-z][\w&.' -]{2,60})[\"”]")
DOMAIN_NAME = re.compile(r"\b([a-z0-9][a-z0-9-]{2,}\.(?:com|io|ai|co|net|org))\b", re.I)


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
    if not q:
        return Plan("unsupported", 0.0, {})
    category = next((k for k, (pattern, _) in REFUSALS.items() if re.search(pattern, q)), None)
    metric = next((label for label, (pattern, _) in UNSUPPORTED_METRICS.items() if re.search(pattern, q)), None)
    if category or metric:
        # Confidence describes the classification, not a fallback answer: we are certain this is out
        # of scope, so the UI must not present it as a weak match to a real metric.
        out: dict[str, Any] = {"category": category or "unknown_metric"}
        if metric:
            out["metric"] = metric
        return Plan("refused" if category else "unsupported_metric", 1.0, out)

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


def _refusal_lines(params: dict[str, Any]) -> list[str]:
    """Say what was refused and what can be asked instead. A refusal that lists no alternative is a dead end."""
    lines = []
    reason = REFUSALS.get(str(params.get("category", "")))
    if reason:
        lines.append(reason[1])
    label = params.get("metric")
    if label:
        lines.append(
            f"GTMOS does not model {label}, so I have no number to give you and will not estimate one. "
            f"It measures {UNSUPPORTED_METRICS[label][1]}."
        )
    lines.append(f"What I can answer: {CAPABILITIES}.")
    lines.append("Try one of these:")
    lines.extend(f"- {q}" for q in suggested_questions()[:6])
    return lines


def _named_entity(db: Session, ws: uuid.UUID, question: str) -> tuple[str, str] | None:
    """Resolve a company the question scopes to, as ("known" | "unknown", name), or None if none is named."""
    m = SCOPED_NAME.search(question) or QUOTED_NAME.search(question) or DOMAIN_NAME.search(question)
    if not m:
        return None
    name = m.group(1).strip(" .,'\"")
    like = f"%{re.sub(r'[%_]', '', name)}%"
    hit = db.scalars(
        select(Account.id)
        .where(
            Account.workspace_id == ws,
            or_(
                Account.name.ilike(like),
                Account.domain.ilike(like),
                Account.industry.ilike(name),
                Account.region.ilike(name),
                Account.segment.ilike(name),
            ),
        )
        .limit(1)
    ).first()
    return ("known" if hit else "unknown", name)


def answer(db: Session, ws: uuid.UUID, question: str) -> dict[str, Any]:
    p = plan(question)
    queries: list[dict[str, Any]] = []
    lines: list[str] = []
    data: dict[str, Any] = {}

    # An analysis is workspace-wide. If the question scopes it to a company we have never heard of,
    # the honest move is to say so rather than to return workspace numbers under that company's name.
    entity = None if p.intent in {"refused", "unsupported_metric"} else _named_entity(db, ws, question)
    if entity and entity[0] == "unknown":
        p = Plan("unknown_entity", 1.0, {"entity": entity[1]})

    if p.intent in {"refused", "unsupported_metric"}:
        lines.extend(_refusal_lines(p.params))
        data = {"refusal": p.params}

    elif p.intent == "unknown_entity":
        lines.append(
            f"I can't find “{p.params['entity']}” as an account, segment, industry or region in this "
            "workspace, so there is nothing to report on it."
        )
        lines.append(f"What I can answer (workspace-wide): {CAPABILITIES}.")
        lines.append("Try one of these:")
        lines.extend(f"- {q}" for q in suggested_questions()[:6])
        data = {"unknown_entity": p.params["entity"]}

    elif p.intent == "pipeline_change":
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
        lines.append(
            "I can only answer questions that map to an approved GTM analysis, and this one doesn't. Try one of these:"
        )
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

    if entity and entity[0] == "known" and queries:
        lines.append(f"Note: approved analyses run workspace-wide, so these numbers are not scoped to {entity[1]}.")

    label = INTENTS.get(p.intent, {}).get("label") or OUT_OF_SCOPE_LABELS.get(p.intent, p.intent)
    p.steps = [
        f"Classified intent: {label} (confidence {p.confidence})",
        *[f"Ran approved metric `{q['metric']}` with {q['params'] or 'default parameters'}" for q in queries],
        "Rendered the answer from computed values only"
        if queries
        else "No metric ran: the request is outside the approved set",
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
            "Read-only: requests to change data, reveal secrets or report a metric GTMOS does not "
            "model are refused, not approximated.",
        ],
        "suggested": [ex for spec in INTENTS.values() for ex in spec["examples"]][:8],
    }


def suggested_questions() -> list[str]:
    return [ex for spec in INTENTS.values() for ex in spec["examples"]]
