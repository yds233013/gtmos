"""Evidence-grounded personalization and outbound guardrails.

Messages are built from a reasoning chain rather than a blank prompt:
    verified signal → pain hypothesis → value proposition → proof → CTA
Guardrails run on *every* draft, deterministic or LLM-written, and blocking failures prevent approval.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

# Seller-approved statements about the product. Personalization may only use these as "proof", so
# messages can't invent customer results, logos or metrics.
SELLER_PROOF_LIBRARY: dict[str, str] = {
    "eval_gates": "Sentinel runs regression evals on every prompt, model or agent change before it ships.",
    "agent_tracing": "Sentinel traces each agent step and tool call, so failures are debuggable in minutes.",
    "online_monitoring": "Sentinel scores live traffic for hallucination and policy violations and alerts "
                         "on drift.",
    "team_standards": "Sentinel gives every AI team the same evaluation datasets, metrics and release "
                      "checklist.",
    "free_to_prod": "Free workspaces can be upgraded in place: traces, datasets and evals carry over.",
}

ANGLE_PLAYBOOK: dict[str, dict[str, str]] = {
    "launch_reliability": {
        "pain": "once an agent is customer-facing, regressions surface as support tickets",
        "value": "eval_gates",
        "question": "How are you catching regressions in the agent before customers do?",
    },
    "scaling_ai_org": {
        "pain": "as AI teams grow, every squad ends up with its own eval scripts and release bar",
        "value": "team_standards",
        "question": "Is there a shared bar for what ‘good enough to ship’ means across your AI teams?",
    },
    "plg_expansion": {
        "pain": "free-tier setups hit limits right when usage becomes production-critical",
        "value": "free_to_prod",
        "question": "Would a production rollout plan for the workspace your team already uses help?",
    },
    "new_leader": {
        "pain": "new technical leaders usually need a reliability baseline for AI systems early on",
        "value": "online_monitoring",
        "question": "Would a 90-day AI reliability baseline be useful as you settle in?",
    },
    "funding_growth": {
        "pain": "a bigger roadmap means more agents in production with the same reliability tooling",
        "value": "agent_tracing",
        "question": "Is agent reliability on the roadmap the new round is funding?",
    },
    "icp_fit": {
        "pain": "teams shipping LLM features often lack visibility into multi-step agent failures",
        "value": "agent_tracing",
        "question": "How do you debug a failed agent run today?",
    },
}

CTA_OPTIONS = {
    "email": "Worth a 20-minute conversation next week?",
    "linkedin": "Open to comparing notes?",
}

BANNED_PATTERNS: list[tuple[str, str]] = [
    (r"\bguarantee[sd]?\b", "Guarantees are unverifiable claims"),
    (r"\b\d+\s?x\b", "Multiplier claims (e.g. 10x) are not in the proof library"),
    (r"#1|number one|best[- ]in[- ]class|industry[- ]leading", "Superlatives are unverifiable"),
    (r"\bI (noticed|know|saw) you(?:'re| are) struggling\b", "Presumes pain we have not verified"),
    (r"\bcustomers? like\b", "Customer references must come from the approved library"),
    (r"\bas (?:we|you) discussed\b", "Implies a prior conversation"),
]
MAX_EMAIL_WORDS = 130
MAX_LINKEDIN_CHARS = 300
SIGNAL_MAX_AGE = timedelta(days=120)
SIGNAL_MIN_CONFIDENCE = 0.7


@dataclass
class GuardrailResult:
    check: str
    passed: bool
    blocking: bool
    detail: str


@dataclass
class DraftContent:
    channel: str
    subject: str | None
    body: str
    angle: str
    chain: dict[str, Any]
    evidence: list[dict[str, Any]]
    guardrails: list[GuardrailResult] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(g.blocking and not g.passed for g in self.guardrails)

    def guardrails_json(self) -> list[dict[str, Any]]:
        return [asdict(g) for g in self.guardrails]


@dataclass
class PersonalizationInput:
    account: dict[str, Any]
    contact: dict[str, Any]
    angle: str
    anchor_signal: dict[str, Any] | None  # {id, title, short, explanation, confidence, observed_at, ref}
    evidence: list[dict[str, Any]]  # the research evidence pack (ref, label, detail, ...)
    sender_name: str
    now: datetime


_NUM_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?[MBK]?")


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "").replace("$", "") for m in _NUM_RE.finditer(text)}


def run_guardrails(content: DraftContent, inp: PersonalizationInput) -> list[GuardrailResult]:
    body = content.body
    full = f"{content.subject or ''}\n{body}"
    results: list[GuardrailResult] = []

    grounded_text = " ".join(f"{e.get('label', '')} {e.get('detail', '')}" for e in inp.evidence)
    grounded_text += " " + " ".join(SELLER_PROOF_LIBRARY.values()) + " " + " ".join(CTA_OPTIONS.values())
    grounded_text += " 90-day 90 days 1 business day"
    ungrounded = sorted(_numbers(full) - _numbers(grounded_text))
    results.append(GuardrailResult(
        "numbers_grounded", not ungrounded, True,
        "Every number appears in cited evidence." if not ungrounded
        else f"Numbers not found in evidence: {', '.join(ungrounded)}"))

    hits = [why for pat, why in BANNED_PATTERNS if re.search(pat, full, flags=re.IGNORECASE)]
    results.append(GuardrailResult("no_unverifiable_claims", not hits, True,
                                   "No banned claim patterns." if not hits else "; ".join(hits)))

    sig = inp.anchor_signal
    if sig is None:
        results.append(GuardrailResult("signal_verified", True, False,
                                       "No signal anchor; message relies on ICP fit only (weaker)."))
    else:
        fresh = inp.now - sig["observed_at"] <= SIGNAL_MAX_AGE
        confident = sig["confidence"] >= SIGNAL_MIN_CONFIDENCE
        results.append(GuardrailResult(
            "signal_verified", fresh and confident, True,
            f"Anchor signal '{sig['title']}' confidence {sig['confidence']:.0%}, "
            f"{(inp.now - sig['observed_at']).days} days old"
            + ("" if fresh and confident else ": too old or not confident enough to reference")))

    if content.channel == "email":
        words = len(body.split())
        results.append(GuardrailResult("length", words <= MAX_EMAIL_WORDS, False,
                                       f"{words} words (limit {MAX_EMAIL_WORDS})."))
    elif content.channel == "linkedin":
        results.append(GuardrailResult("length", len(body) <= MAX_LINKEDIN_CHARS, True,
                                       f"{len(body)} characters (limit {MAX_LINKEDIN_CHARS})."))

    if content.channel in ("email", "linkedin"):
        has_q = "?" in body
        results.append(GuardrailResult("has_cta", has_q, False,
                                       "Ends with a clear question/CTA." if has_q else "No CTA found."))
        name = inp.account.get("name", "")
        results.append(GuardrailResult("personalized", bool(name) and name in full, False,
                                       "References the account by name." if name in full
                                       else "Does not reference the account."))

    c = inp.contact
    reachable = not c.get("do_not_contact") and c.get("email_status") != "invalid"
    results.append(GuardrailResult(
        "contact_reachable", reachable, True,
        "Contact is reachable." if reachable else "Contact is do-not-contact or has an invalid email."))
    return results


def build_chain(inp: PersonalizationInput) -> dict[str, Any]:
    play = ANGLE_PLAYBOOK.get(inp.angle, ANGLE_PLAYBOOK["icp_fit"])
    sig = inp.anchor_signal
    return {
        "signal": {"text": sig["title"], "ref": sig.get("ref"), "confidence": sig["confidence"]} if sig else None,
        "pain_hypothesis": play["pain"],
        "value_proposition": SELLER_PROOF_LIBRARY[play["value"]],
        "proof_source": f"seller_proof_library:{play['value']}",
        "question": play["question"],
        "cta": CTA_OPTIONS["email"],
    }


def generate_messages(inp: PersonalizationInput) -> list[DraftContent]:
    """Deterministic drafts for email, LinkedIn and call prep. Guardrails are attached to each."""
    chain = build_chain(inp)
    first = inp.contact.get("first_name") or "there"
    company = inp.account["name"]
    sig = inp.anchor_signal
    used_refs = [sig["ref"]] if sig and sig.get("ref") else []
    evidence_used = [e for e in inp.evidence if e.get("ref") in used_refs]

    opener = (f"Saw that {company} {sig['short']}." if sig
              else f"I've been following how {company} is building with LLMs.")
    email_body = (
        f"Hi {first},\n\n"
        f"{opener} In our experience, {chain['pain_hypothesis']}.\n\n"
        f"{chain['value_proposition']}\n\n"
        f"{chain['question']} {CTA_OPTIONS['email']}\n\n"
        f"{inp.sender_name}"
    )
    subject = f"{company} + agent reliability" if not sig else f"{sig.get('subject_hook', company)}: reliability"
    email = DraftContent("email", subject, email_body, inp.angle, chain, evidence_used)

    li_body = f"Hi {first}, {opener[0].lower() + opener[1:]} {chain['question']} {CTA_OPTIONS['linkedin']}"
    linkedin = DraftContent("linkedin", None, li_body, inp.angle, {**chain, "cta": CTA_OPTIONS["linkedin"]},
                            evidence_used)

    ev_lines = "\n".join(f"- [{e['ref']}] {e['label']}" for e in inp.evidence[:8])
    prep = (
        f"CALL PREP: {inp.contact.get('name')} ({inp.contact.get('title')}) at {company}\n\n"
        f"Opener: {opener}\n"
        f"Hypothesis to test: {chain['pain_hypothesis']}.\n"
        f"Discovery questions:\n"
        f"- {chain['question']}\n"
        f"- Who owns AI evaluation and incident response today?\n"
        f"- What happened the last time an LLM feature regressed in production?\n"
        f"Value to connect: {chain['value_proposition']}\n\n"
        f"Evidence on file:\n{ev_lines}"
    )
    call = DraftContent("call_prep", None, prep, inp.angle, chain, inp.evidence[:8])

    for d in (email, linkedin, call):
        d.guardrails = run_guardrails(d, inp)
    return [email, linkedin, call]


# Approval state machine ----------------------------------------------------------------------------

MESSAGE_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"review", "rejected"},
    "review": {"approved", "rejected", "draft"},
    "approved": {"ready", "draft"},
    "ready": {"draft"},
    "rejected": {"draft"},
}


def check_message_transition(current: str, target: str, blocked: bool) -> tuple[bool, str]:
    if target not in MESSAGE_TRANSITIONS.get(current, set()):
        return False, f"Cannot move a message from {current} to {target}."
    if target in ("approved", "ready") and blocked:
        return False, "Blocking guardrail failures must be fixed before approval."
    return True, f"{current} → {target}"
