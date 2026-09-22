"""Account research: evidence pack → claims with citations → validation.

The research brief is only as good as its evidence. We first assemble an evidence pack of records GTMOS
actually holds (firmographics with provenance, signals, technographics, contacts, activities) and number
it E1..En. Any generator, deterministic or LLM, must cite those refs on every claim. validate_sections()
strips claims that cite nothing or cite refs that don't exist, and reports them as unsupported.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

SECTION_ORDER = (
    "account_summary",
    "why_now",
    "relevant_signals",
    "likely_pain",
    "technical_context",
    "buying_committee",
    "potential_objections",
    "recommended_angle",
)
SECTION_TITLES = {
    "account_summary": "Account summary",
    "why_now": "Why now",
    "relevant_signals": "Relevant signals",
    "likely_pain": "Likely pain",
    "technical_context": "Technical context",
    "buying_committee": "Buying committee",
    "potential_objections": "Potential objections",
    "recommended_angle": "Recommended angle",
}
PROMPT_VERSION = "research-v3"

# Technologies that suggest an incumbent in the seller's category (used for objection hypotheses).
ADJACENT_INCUMBENTS = ("LangSmith", "Arize", "Datadog LLM Observability", "Weights & Biases")


@dataclass
class Evidence:
    ref: str
    kind: str
    label: str
    detail: str
    source: str
    confidence: float
    source_url: str | None = None
    record_type: str | None = None
    record_id: str | None = None
    observed_at: datetime | None = None


@dataclass
class Claim:
    text: str
    evidence: list[str]
    hypothesis: bool = False


@dataclass
class ResearchInput:
    account: dict[str, Any]
    score: dict[str, Any]
    signals: list[dict[str, Any]]
    committee: list[dict[str, Any]]
    activities: list[dict[str, Any]]
    provenance: dict[str, dict[str, Any]]
    seller: dict[str, Any]
    now: datetime


@dataclass
class ResearchOutput:
    sections: dict[str, list[Claim]]
    evidence: list[Evidence]
    unsupported: list[dict[str, Any]] = field(default_factory=list)
    angle: str = ""


def input_hash(inp: ResearchInput) -> str:
    return hashlib.sha256(json.dumps(asdict(inp), sort_keys=True, default=str).encode()).hexdigest()


def _days_ago(ts: datetime | None, now: datetime) -> str:
    if ts is None:
        return "date unknown"
    d = max(int((now - ts).total_seconds() // 86400), 0)
    return "today" if d == 0 else ("yesterday" if d == 1 else f"{d} days ago")


def build_evidence_pack(inp: ResearchInput) -> tuple[list[Evidence], dict[str, str]]:
    """Returns the evidence list and an index from semantic key (e.g. 'signal:<id>') to ref."""
    ev: list[Evidence] = []
    index: dict[str, str] = {}

    def add(key: str, **kw: Any) -> str:
        if key in index:  # e.g. one contact holding two committee roles is one piece of evidence
            return index[key]
        ref = f"E{len(ev) + 1}"
        ev.append(Evidence(ref=ref, **kw))
        index[key] = ref
        return ref

    a = inp.account
    prov = inp.provenance
    for fld, label in (
        ("industry", "Industry"),
        ("employee_count", "Employees"),
        ("city", "Headquarters"),
        ("funding_stage", "Funding stage"),
        ("total_funding_usd", "Total funding"),
        ("ai_team_size", "AI/ML team size"),
        ("ai_open_roles", "Open AI/ML roles"),
    ):
        val = a.get(fld)
        if val in (None, "", []):
            continue
        p = prov.get(fld, {})
        shown = f"${val:,.0f}" if fld == "total_funding_usd" else (f"{val:,}" if isinstance(val, int) else val)
        add(
            f"field:{fld}",
            kind="firmographic",
            label=f"{label}: {shown}",
            detail=f"{label} = {shown} (source: {p.get('source', 'crm')}).",
            source=p.get("source", "crm"),
            confidence=float(p.get("confidence", 0.8)),
            record_type="account",
            record_id=a.get("id"),
            observed_at=p.get("observed_at"),
        )
    techs = a.get("technologies") or []
    if techs:
        p = prov.get("technologies", {})
        add(
            "field:technologies",
            kind="technographic",
            label="Tech stack: " + ", ".join(techs),
            detail="Detected technologies: " + ", ".join(techs) + ".",
            source=p.get("source", "crm"),
            confidence=float(p.get("confidence", 0.75)),
            record_type="account",
            record_id=a.get("id"),
            observed_at=p.get("observed_at"),
        )
    for s in inp.signals:
        add(
            f"signal:{s['id']}",
            kind="signal",
            label=s["title"],
            detail=s["explanation"],
            source=s["source"],
            confidence=float(s["confidence"]),
            source_url=s.get("source_url"),
            record_type="signal",
            record_id=s["id"],
            observed_at=s["observed_at"],
        )
    for m in inp.committee:
        add(
            f"contact:{m['contact_id']}",
            kind="contact",
            label=f"{m['name']}, {m['title']}",
            detail=f"{m['name']} ({m['title']}), inferred {m['role_label'].lower()}: {m['reasons'][0]}",
            source="gtmos_committee_inference",
            confidence=float(m["confidence"]),
            record_type="contact",
            record_id=m["contact_id"],
        )
    for act in inp.activities[:5]:
        add(
            f"activity:{act['id']}",
            kind="activity",
            label=act["label"],
            detail=act["detail"],
            source=act.get("source", "crm"),
            confidence=1.0,
            record_type="activity",
            record_id=act["id"],
            observed_at=act.get("occurred_at"),
        )
    sc = inp.score
    if sc:
        add(
            "score",
            kind="score",
            label=f"ICP score {sc['total']}/100 (grade {sc['grade']})",
            detail=sc.get("summary", ""),
            source="gtmos_scoring",
            confidence=1.0,
            record_type="icp_score",
            record_id=sc.get("id"),
        )
    return ev, index


PAIN_BY_SIGNAL = {
    "ai_product_launch": (
        "Having shipped {title_obj} to customers, reliability is now customer-facing: "
        "regressions, hallucinations and tool-call failures show up as support tickets "
        "unless evaluation and monitoring gate each release."
    ),
    "ai_hiring_surge": (
        "A fast-growing AI org multiplies prompts, models and agents in production; "
        "shared evaluation standards and release gates tend to lag headcount."
    ),
    "job_posting": (
        "They are hiring for this problem directly ({title_obj}), which suggests evaluation / "
        "reliability is an acknowledged gap rather than a solved one."
    ),
    "tech_adoption": (
        "Adopting {title_obj} points to RAG/agent architectures, where retrieval quality and "
        "multi-step failures are hard to observe with traditional APM."
    ),
    "funding_round": (
        "New capital usually comes with aggressive AI roadmap commitments, raising the cost "
        "of shipping unreliable agents."
    ),
    "executive_hire": (
        "A newly hired technical leader typically audits the AI tooling stack and sets "
        "reliability standards in their first 90 days."
    ),
    "usage_threshold": (
        "Their team is already sending production-scale traces to our free tier; they are "
        "hitting limits of an unmanaged setup."
    ),
    "pricing_page_visit": "Repeated pricing-page visits suggest an active evaluation or budget conversation.",
}

ANGLES = {
    "launch_reliability": (
        "Launch reliability",
        "ai_product_launch",
        "Lead with protecting the newly launched AI product: evaluation gates on every "
        "release and tracing for agent failures, framed around their launch.",
    ),
    "scaling_ai_org": (
        "Scaling the AI org",
        "ai_hiring_surge",
        "Lead with standardizing evaluation and observability as the AI team scales, so "
        "new hires ship safely without bespoke tooling.",
    ),
    "plg_expansion": (
        "Product-led expansion",
        "usage_threshold",
        "Lead with what their team is already doing in the free workspace and offer a production rollout plan.",
    ),
    "new_leader": (
        "New leader agenda",
        "executive_hire",
        "Offer the new leader a 90-day AI reliability baseline: what to measure and how.",
    ),
    "funding_growth": (
        "Post-funding roadmap",
        "funding_round",
        "Tie reliability to the roadmap the new round is funding.",
    ),
}
ANGLE_PRIORITY = ["launch_reliability", "plg_expansion", "scaling_ai_org", "new_leader", "funding_growth"]


def choose_angle(signal_types: set[str]) -> str:
    for key in ANGLE_PRIORITY:
        if ANGLES[key][1] in signal_types:
            return key
    return "icp_fit"


def generate_deterministic(inp: ResearchInput) -> ResearchOutput:
    """The demo generator. It only restates and combines evidence, so every sentence is traceable."""
    ev, idx = build_evidence_pack(inp)
    a = inp.account
    S: dict[str, list[Claim]] = {k: [] for k in SECTION_ORDER}

    def refs(*keys: str) -> list[str]:
        return [idx[k] for k in keys if k in idx]

    # ACCOUNT SUMMARY
    parts = [f"{a['name']} is"]
    if a.get("industry"):
        parts.append(f"a {a['industry']} company")
    if a.get("employee_count"):
        parts.append(f"with ~{a['employee_count']:,} employees")
    if a.get("city"):
        parts.append(f"headquartered in {a['city']}")
    S["account_summary"].append(
        Claim(" ".join(parts) + ".", refs("field:industry", "field:employee_count", "field:city"))
    )
    if a.get("funding_stage"):
        txt = f"Funding stage: {a['funding_stage']}"
        if a.get("total_funding_usd"):
            txt += f", ${a['total_funding_usd'] / 1e6:,.0f}M raised to date"
        S["account_summary"].append(Claim(txt + ".", refs("field:funding_stage", "field:total_funding_usd")))
    if inp.score:
        S["account_summary"].append(
            Claim(
                f"ICP score {inp.score['total']}/100 (grade {inp.score['grade']}). {inp.score.get('summary', '')}",
                refs("score"),
            )
        )

    # SIGNALS ranked by strength × confidence, newest first on ties
    sigs = sorted(inp.signals, key=lambda s: (s["strength"] * s["confidence"], s["observed_at"], s["id"]), reverse=True)
    recent = sorted(inp.signals, key=lambda s: s["observed_at"], reverse=True)
    for s in recent[:6]:
        S["relevant_signals"].append(
            Claim(
                f"{s['title']} ({_days_ago(s['observed_at'], inp.now)}, confidence {s['confidence']:.0%}).",
                refs(f"signal:{s['id']}"),
            )
        )
    for s in sigs[:3]:
        S["why_now"].append(Claim(f"{s['title']}: {s['explanation']}", refs(f"signal:{s['id']}")))
    if not inp.signals:
        S["why_now"].append(
            Claim(
                "No recent buying signals; this is a fit-only account. Timing is not established.",
                refs("score"),
                hypothesis=True,
            )
        )

    # LIKELY PAIN (hypotheses, each motivated by cited evidence)
    seen_types: set[str] = set()
    for s in sigs:
        t = s["signal_type"]
        if t in PAIN_BY_SIGNAL and t not in seen_types:
            seen_types.add(t)
            title_obj = s.get("evidence", {}).get("object") or s["title"]
            S["likely_pain"].append(
                Claim(PAIN_BY_SIGNAL[t].format(title_obj=title_obj), refs(f"signal:{s['id']}"), hypothesis=True)
            )
        if len(S["likely_pain"]) >= 3:
            break

    # TECHNICAL CONTEXT
    if techs := a.get("technologies"):
        S["technical_context"].append(Claim("Detected stack: " + ", ".join(techs) + ".", refs("field:technologies")))
    if a.get("ai_team_size"):
        txt = f"AI/ML team of roughly {a['ai_team_size']} engineers"
        if a.get("ai_open_roles"):
            txt += f", with {a['ai_open_roles']} open AI/ML roles"
        S["technical_context"].append(Claim(txt + ".", refs("field:ai_team_size", "field:ai_open_roles")))

    # BUYING COMMITTEE
    for m in inp.committee:
        S["buying_committee"].append(
            Claim(
                f"{m['name']} ({m['title']}), likely {m['role_label'].lower()}: {m['reasons'][0]}.",
                refs(f"contact:{m['contact_id']}"),
            )
        )
    if not inp.committee:
        S["buying_committee"].append(
            Claim(
                "No qualified contacts on file; source ML/AI leaders before outreach.", refs("score"), hypothesis=True
            )
        )

    # OBJECTIONS (hypotheses)
    incumbents = [t for t in (a.get("technologies") or []) if t in ADJACENT_INCUMBENTS]
    if incumbents:
        S["potential_objections"].append(
            Claim(
                f"Already uses {', '.join(incumbents)}; expect 'we have tracing already'. Position evaluation "
                "gates and agent reliability as complementary.",
                refs("field:technologies"),
                hypothesis=True,
            )
        )
    if (a.get("employee_count") or 0) >= 2000:
        S["potential_objections"].append(
            Claim(
                "Large organization: expect security review and procurement; lead with SOC 2 and data residency.",
                refs("field:employee_count"),
                hypothesis=True,
            )
        )
    if (a.get("ai_team_size") or 0) >= 40:
        S["potential_objections"].append(
            Claim(
                "A large AI team may prefer to build internally; quantify maintenance cost of in-house evals.",
                refs("field:ai_team_size"),
                hypothesis=True,
            )
        )
    if not S["potential_objections"]:
        S["potential_objections"].append(
            Claim("Priority/timing: no forcing event cited; anchor on a signal.", refs("score"), hypothesis=True)
        )

    # ANGLE
    angle = choose_angle({s["signal_type"] for s in inp.signals})
    if angle in ANGLES:
        name, sig_type, text = ANGLES[angle]
        anchor = next((s for s in recent if s["signal_type"] == sig_type), None)
        S["recommended_angle"].append(
            Claim(f"{name}: {text}", refs(f"signal:{anchor['id']}") if anchor else refs("score"))
        )
    else:
        S["recommended_angle"].append(
            Claim(
                "ICP fit: lead with peer patterns for AI teams of their size; no timing trigger available.",
                refs("score"),
                hypothesis=True,
            )
        )

    sections, unsupported = validate_sections(S, {e.ref for e in ev})
    return ResearchOutput(sections, ev, unsupported, angle)


def validate_sections(
    sections: dict[str, list[Claim]], valid_refs: set[str]
) -> tuple[dict[str, list[Claim]], list[dict[str, Any]]]:
    """Drop any claim without at least one valid citation. Unknown refs are removed from claims."""
    clean: dict[str, list[Claim]] = {}
    unsupported: list[dict[str, Any]] = []
    for sec in SECTION_ORDER:
        kept: list[Claim] = []
        for c in sections.get(sec, []):
            good = [r for r in c.evidence if r in valid_refs]
            bad = [r for r in c.evidence if r not in valid_refs]
            if not good:
                unsupported.append(
                    {
                        "section": sec,
                        "text": c.text,
                        "reason": "no valid evidence cited" if not bad else f"unknown refs {bad}",
                    }
                )
                continue
            kept.append(Claim(c.text, good, c.hypothesis))
        clean[sec] = kept
    return clean, unsupported


def sections_to_json(sections: dict[str, list[Claim]]) -> dict[str, Any]:
    return {k: [asdict(c) for c in v] for k, v in sections.items()}
