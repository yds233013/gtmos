"""Funnel stage and lifecycle semantics.

Funnel stages move forward. Skipping ahead is allowed (a warm inbound lead can book a meeting on day
one), but moving backward is not, except into `lost`, and `won`/`lost` are terminal unless the account
is explicitly recycled back to `prospect`. Lifecycle stage (HubSpot semantics) is forward-only.
"""

from __future__ import annotations

from dataclasses import dataclass

from gtmos.models.crm import DEAL_STAGES, FUNNEL_STAGES, LIFECYCLE_STAGES

FUNNEL_ORDER = {s: i for i, s in enumerate(FUNNEL_STAGES)}
LIFECYCLE_ORDER = {s: i for i, s in enumerate(LIFECYCLE_STAGES)}
DEAL_ORDER = {s: i for i, s in enumerate(DEAL_STAGES)}

# Lifecycle implied by funnel stage. Used to detect conflicts and to update lifecycle on transitions.
FUNNEL_TO_LIFECYCLE = {
    "prospect": "lead",
    "contacted": "lead",
    "engaged": "marketingqualifiedlead",
    "qualified": "salesqualifiedlead",
    "meeting": "salesqualifiedlead",
    "opportunity": "opportunity",
    "won": "customer",
    "lost": None,  # losing does not change lifecycle
}


@dataclass(frozen=True)
class TransitionCheck:
    allowed: bool
    reason: str


def check_funnel_transition(from_stage: str | None, to_stage: str, *, recycle: bool = False) -> TransitionCheck:
    if to_stage not in FUNNEL_ORDER:
        return TransitionCheck(False, f"Unknown funnel stage '{to_stage}'.")
    if from_stage is None:
        return TransitionCheck(True, "Initial stage.")
    if from_stage not in FUNNEL_ORDER:
        return TransitionCheck(False, f"Unknown current stage '{from_stage}'.")
    if from_stage == to_stage:
        return TransitionCheck(False, "Account is already in this stage.")
    if from_stage in ("won", "lost"):
        if recycle and to_stage == "prospect":
            return TransitionCheck(True, f"Recycled from {from_stage} to prospect.")
        return TransitionCheck(False, f"'{from_stage}' is terminal; recycle to prospect first.")
    if to_stage == "lost":
        return TransitionCheck(True, "Closed as lost.")
    if to_stage == "won" and from_stage != "opportunity":
        return TransitionCheck(False, "Only accounts with an open opportunity can be marked won.")
    if FUNNEL_ORDER[to_stage] < FUNNEL_ORDER[from_stage]:
        return TransitionCheck(False, f"Backward move {from_stage} → {to_stage} is not allowed.")
    return TransitionCheck(True, f"Forward move {from_stage} → {to_stage}.")


def check_lifecycle_transition(from_stage: str | None, to_stage: str) -> TransitionCheck:
    if to_stage not in LIFECYCLE_ORDER:
        return TransitionCheck(False, f"Unknown lifecycle stage '{to_stage}'.")
    if from_stage is None or from_stage == "other":
        return TransitionCheck(True, "Initial lifecycle stage.")
    if from_stage not in LIFECYCLE_ORDER:
        return TransitionCheck(False, f"Unknown current lifecycle stage '{from_stage}'.")
    if LIFECYCLE_ORDER[to_stage] < LIFECYCLE_ORDER[from_stage]:
        return TransitionCheck(False, f"Lifecycle is forward-only ({from_stage} → {to_stage} rejected).")
    return TransitionCheck(True, f"Lifecycle {from_stage} → {to_stage}.")


def lifecycle_for_funnel(stage: str, current_lifecycle: str | None) -> str | None:
    """The lifecycle an account should have after entering `stage`, or None to leave it unchanged."""
    target = FUNNEL_TO_LIFECYCLE.get(stage)
    if target is None:
        return None
    if current_lifecycle in LIFECYCLE_ORDER and LIFECYCLE_ORDER[current_lifecycle] >= LIFECYCLE_ORDER[target]:
        return None
    return target


def invalid_history_transitions(history: list[tuple[str | None, str]]) -> list[tuple[str | None, str, str]]:
    """Scan an ordered stage history for transitions our rules would reject (used by data quality)."""
    bad: list[tuple[str | None, str, str]] = []
    for frm, to in history:
        chk = check_funnel_transition(frm, to, recycle=True)
        if not chk.allowed:
            bad.append((frm, to, chk.reason))
    return bad
