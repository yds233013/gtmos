"""Buying-committee inference.

For each contact we compute a fit score per role from title keywords, seniority, department and
engagement, keeping the human-readable reasons. Each role is then held by its best candidate; one
person can hold at most one role unless they're the only viable candidate. Manual overrides are
applied last and always win.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ROLE_LABELS = {
    "champion": "Champion",
    "technical_evaluator": "Technical evaluator",
    "economic_buyer": "Economic buyer",
    "executive_sponsor": "Executive sponsor",
    "end_user": "End user",
}

# (pattern, points, reason). Patterns are matched against the lower-cased title.
ROLE_TITLE_RULES: dict[str, list[tuple[str, float, str]]] = {
    "executive_sponsor": [
        (r"\b(cto|chief technology officer)\b", 60, "CTO owns technical strategy and signs off on platforms"),
        (r"\b(ceo|chief executive|founder|co-founder)\b", 45, "Company leader; sponsors strategic bets"),
        (r"\b(chief ai officer|caio|chief data officer)\b", 55, "C-level owner of AI/data strategy"),
        (r"\bsvp\b", 35, "Senior executive"),
    ],
    "economic_buyer": [
        (r"\bvp\b.*\b(engineering|eng|platform|infrastructure)\b", 60, "VP Engineering controls the tooling budget"),
        (r"\bvp\b.*\b(ai|ml|machine learning|data)\b", 60, "VP of AI/ML controls AI infrastructure spend"),
        (r"\b(cto|chief technology officer)\b", 40, "CTO can approve spend directly"),
        (r"\bhead of (engineering|platform)\b", 40, "Engineering head often owns budget at mid-size companies"),
    ],
    "champion": [
        (
            r"\bhead of (ai|ml|machine learning|applied ai|ai platform|genai)\b",
            60,
            "Head of AI/ML feels agent reliability pain most directly",
        ),
        (
            r"\bdirector\b.*\b(ai|ml|machine learning|ai infrastructure|ml platform)\b",
            55,
            "AI/ML director drives tooling decisions for their org",
        ),
        (r"\b(ml|ai) platform (lead|manager)\b", 45, "Platform lead owns the internal AI stack"),
        (r"\bvp\b.*\b(ai|ml)\b", 30, "Senior AI leader who can champion internally"),
    ],
    "technical_evaluator": [
        (
            r"\b(staff|principal|senior staff)\b.*\b(ml|ai|machine learning|platform)\b",
            60,
            "Staff-level engineer runs technical evaluations",
        ),
        (r"\b(ml|ai) platform (lead|engineer)\b", 50, "Owns the platform the product would integrate with"),
        (r"\b(ml|machine learning|ai) (infrastructure|infra)\b", 45, "AI infrastructure owner"),
        (r"\barchitect\b", 40, "Architect evaluates integration fit"),
        (r"\b(engineering manager)\b.*\b(ml|ai)\b", 35, "Manages the team that would adopt the tool"),
    ],
    "end_user": [
        (r"\b(ml|machine learning|ai|llm) engineer\b", 50, "Hands-on AI/ML engineer; daily user"),
        (r"\b(applied scientist|research engineer|data scientist)\b", 40, "Builds and evaluates models"),
        (r"\b(software engineer|backend engineer)\b", 20, "Engineer who may instrument agents"),
    ],
}

SENIORITY_BONUS = {
    "executive_sponsor": {"c_suite": 20, "vp": 5},
    "economic_buyer": {"vp": 20, "c_suite": 10, "director": 5},
    "champion": {"director": 15, "vp": 5, "manager": 10},
    "technical_evaluator": {"ic": 10, "manager": 10},
    "end_user": {"ic": 15},
}
DEPARTMENT_BONUS = {"ai_ml": 10, "engineering": 5, "data": 5}
MIN_ROLE_SCORE = 35.0


@dataclass(frozen=True)
class ContactFacts:
    id: str
    name: str
    title: str | None
    seniority: str | None
    department: str | None
    email_status: str = "unknown"
    replied: bool = False
    meetings: int = 0
    product_user: bool = False
    do_not_contact: bool = False


@dataclass
class RoleCandidate:
    contact_id: str
    role: str
    score: float
    reasons: list[str]


@dataclass
class RoleAssignment:
    role: str
    contact_id: str
    rank: int
    score: float
    confidence: float
    reasons: list[str]
    is_manual_override: bool = False


@dataclass
class CommitteeResult:
    assignments: list[RoleAssignment]
    unfilled_roles: list[str]
    candidates: dict[str, list[RoleCandidate]] = field(default_factory=dict)

    def holder(self, role: str) -> RoleAssignment | None:
        for a in self.assignments:
            if a.role == role and a.rank == 1:
                return a
        return None


def score_roles(c: ContactFacts) -> list[RoleCandidate]:
    title = (c.title or "").lower()
    out: list[RoleCandidate] = []
    for role, rules in ROLE_TITLE_RULES.items():
        best_pts, best_reason = 0.0, ""
        for pattern, pts, reason in rules:
            if re.search(pattern, title) and pts > best_pts:
                best_pts, best_reason = pts, reason
        if best_pts == 0:
            continue
        score = best_pts
        reasons = [f"Title “{c.title}”: {best_reason}"]
        sb = SENIORITY_BONUS.get(role, {}).get(c.seniority or "", 0)
        if sb:
            score += sb
            reasons.append(f"Seniority {c.seniority} (+{sb})")
        db = DEPARTMENT_BONUS.get(c.department or "", 0)
        if db:
            score += db
            reasons.append(f"Department {c.department} (+{db})")
        if role in ("champion", "technical_evaluator", "end_user") and c.product_user:
            score += 15
            reasons.append("Active user of the free product (+15)")
        if c.meetings:
            score += 12
            reasons.append(f"Attended {c.meetings} meeting(s) (+12)")
        elif c.replied:
            score += 8
            reasons.append("Replied to outreach (+8)")
        if c.email_status == "invalid":
            score -= 15
            reasons.append("Email invalid (−15): reachability risk")
        if c.do_not_contact:
            score -= 40
            reasons.append("Marked do-not-contact (−40)")
        out.append(RoleCandidate(c.id, role, round(score, 1), reasons))
    return out


def _confidence(score: float, runner_up: float | None) -> float:
    base = min(score / 100.0, 1.0)
    if runner_up is not None:
        margin = (score - runner_up) / max(score, 1.0)
        base *= 0.75 + 0.25 * min(max(margin * 3, 0.0), 1.0)
    return round(max(min(base, 0.99), 0.05), 2)


def infer_committee(
    contacts: list[ContactFacts],
    overrides: dict[str, str] | None = None,
) -> CommitteeResult:
    """`overrides` maps role -> contact_id set manually by a rep. Returns ranked assignments per role."""
    overrides = overrides or {}
    by_role: dict[str, list[RoleCandidate]] = {r: [] for r in ROLE_LABELS}
    for c in sorted(contacts, key=lambda x: x.id):
        for cand in score_roles(c):
            if cand.score >= MIN_ROLE_SCORE:
                by_role[cand.role].append(cand)
    for cands in by_role.values():
        cands.sort(key=lambda x: (-x.score, x.contact_id))

    # Fill the most constrained roles first so one strong executive doesn't absorb every role.
    fill_order = ["executive_sponsor", "economic_buyer", "champion", "technical_evaluator", "end_user"]
    taken: set[str] = set(overrides.values())
    primary: dict[str, RoleCandidate] = {}
    for role in fill_order:
        if role in overrides:
            continue
        cands = by_role[role]
        pick = next((c for c in cands if c.contact_id not in taken), None)
        if pick is None and cands:
            pick = cands[0]  # allow double duty only when nobody else qualifies
            pick = RoleCandidate(
                pick.contact_id,
                pick.role,
                pick.score,
                [*pick.reasons, "Also holds another role: no other qualified candidate"],
            )
        if pick:
            primary[role] = pick
            taken.add(pick.contact_id)

    assignments: list[RoleAssignment] = []
    unfilled: list[str] = []
    for role in ROLE_LABELS:
        cands = by_role[role]
        if role in overrides:
            cid = overrides[role]
            auto = next((c for c in cands if c.contact_id == cid), None)
            reasons = ["Manually assigned by a rep; overrides inferred ranking", *(auto.reasons if auto else [])]
            assignments.append(RoleAssignment(role, cid, 1, auto.score if auto else 0.0, 1.0, reasons, True))
            others = [c for c in cands if c.contact_id != cid]
        elif role in primary:
            p = primary[role]
            runner = next((c.score for c in cands if c.contact_id != p.contact_id), None)
            assignments.append(RoleAssignment(role, p.contact_id, 1, p.score, _confidence(p.score, runner), p.reasons))
            others = [c for c in cands if c.contact_id != p.contact_id]
        else:
            unfilled.append(role)
            continue
        for i, c in enumerate(others[:2], start=2):
            assignments.append(
                RoleAssignment(role, c.contact_id, i, c.score, _confidence(c.score, None) * 0.8, c.reasons)
            )
    return CommitteeResult(assignments, unfilled, by_role)
