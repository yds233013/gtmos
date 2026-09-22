"""Backtests the ICP score against what actually happened to the accounts it ranked.

The interesting question for a hand-weighted score is not accuracy but **leakage**: engagement points
are awarded for replies and meetings, and "did the account book a meeting" is the outcome, so the full
score partly predicts itself. This service therefore evaluates several score variants against the same
outcomes, so the difference between them measures how much of the apparent skill is circular:

    structural       fit + technical           known before anyone was contacted — no leakage
    pre_engagement   + timing + intent         external signals; leaks only if a signal was caused by us
    total            + engagement              the score shown in the product; leaks by construction

Population is restricted to accounts that were actually contacted. An uncontacted account cannot book
a meeting, so scoring the whole database would measure who reps chose to work, not who converts.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gtmos.domain.evaluation import Observation, evaluate
from gtmos.models import Account, ICPScore, StageTransition

# Score variants, as (key, label, columns summed, leakage note).
VARIANTS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    (
        "structural",
        "Structural (fit + technical)",
        ("fit", "technical"),
        "No leakage: every input is a firmographic or technographic fact known before first contact.",
    ),
    (
        "pre_engagement",
        "Pre-engagement (fit + technical + timing + intent)",
        ("fit", "technical", "timing", "intent"),
        "Low leakage: signals are external events. A signal GTMOS itself caused (a webinar we ran) is "
        "the exception and is not separated out in V1.",
    ),
    (
        "total",
        "Total score (as shown in the product)",
        # The stored total, not the sum of the category columns: disqualifying-signal penalties are
        # applied after the caps, so the columns deliberately do not add up to it.
        ("total",),
        "Leaks: engagement points are awarded for replies and meetings, which is part of the outcome "
        "being predicted. Its advantage over the other variants is the size of that circularity.",
    ),
)

OUTCOMES: tuple[tuple[str, str, str], ...] = (
    ("meeting", "Booked a meeting", "Account ever reached the 'meeting' stage."),
    ("opportunity", "Became an opportunity", "Account ever reached the 'opportunity' stage."),
)


def _stage_reached(db: Session, ws: uuid.UUID, stage: str) -> set[uuid.UUID]:
    rows = db.scalars(
        select(StageTransition.entity_id).where(
            StageTransition.workspace_id == ws,
            StageTransition.pipeline == "funnel",
            StageTransition.to_stage == stage,
        )
    )
    return set(rows)


def run(db: Session, ws: uuid.UUID) -> dict[str, Any]:
    scores = list(
        db.execute(
            select(
                ICPScore.account_id,
                ICPScore.total,
                ICPScore.grade,
                ICPScore.fit,
                ICPScore.intent,
                ICPScore.timing,
                ICPScore.technical,
                ICPScore.engagement,
                ICPScore.excluded,
            ).where(ICPScore.workspace_id == ws, ICPScore.is_current.is_(True))
        ).all()
    )
    names = dict(db.execute(select(Account.id, Account.name).where(Account.workspace_id == ws)).tuples().all())
    contacted = _stage_reached(db, ws, "contacted")
    reached = {key: _stage_reached(db, ws, key) for key, _, _ in OUTCOMES}

    graded = Counter(s.grade for s in scores)
    excluded = sum(1 for s in scores if s.excluded)

    # Excluded (X) accounts are ranked by the same score but are not recommendations, so they are
    # reported separately rather than mixed into the ranking being evaluated.
    population = [s for s in scores if s.account_id in contacted and not s.excluded]

    everyone = [s for s in scores if not s.excluded]

    def observe(rows: list[Any], cols: tuple[str, ...], won: set[uuid.UUID]) -> list[Observation]:
        return [
            Observation(
                key=names.get(s.account_id, str(s.account_id)),
                score=sum(float(getattr(s, c)) for c in cols),
                outcome=s.account_id in won,
                grade=s.grade,
            )
            for s in rows
        ]

    results: dict[str, Any] = {}
    for outcome_key, outcome_label, outcome_def in OUTCOMES:
        won = reached[outcome_key]
        per_variant = {}
        for key, label, cols, note in VARIANTS:
            ev = evaluate(observe(population, cols, won))
            entry = {"label": label, "leakage": note, **ev.as_dict()}
            entry.pop("by_grade")  # grade is a property of the total score, reported once below
            per_variant[key] = entry
        structural_cols = VARIANTS[0][2]
        results[outcome_key] = {
            "label": outcome_label,
            "definition": outcome_def,
            "by_grade": [b.as_dict() for b in evaluate(observe(population, ("total",), won)).by_grade],
            "variants": per_variant,
            "leakage_delta": _leakage_delta(per_variant),
            "selection_effect": _selection_effect(
                contacted=per_variant["structural"]["auc"],
                everyone=evaluate(observe(everyone, structural_cols, won)).auc,
                contacted_n=len(population),
                everyone_n=len(everyone),
            ),
        }

    return {
        "population": {
            "scored_accounts": len(scores),
            "contacted": len(contacted),
            "evaluated": len(population),
            "excluded_from_ranking": excluded,
            "note": "Only contacted, non-excluded accounts are evaluated. Uncontacted accounts have no "
            "opportunity to convert, so including them would measure rep selection, not score quality.",
        },
        "grade_distribution": [
            {
                "grade": g,
                "accounts": graded.get(g, 0),
                "share": round(graded.get(g, 0) / len(scores), 4) if scores else 0,
            }
            for g in ("A", "B", "C", "D", "X")
        ],
        "outcomes": results,
        "caveats": [
            "This is a heuristic ranking, not a trained model: there is no training set, no holdout and "
            "no learned weights. AUC here measures whether the hand-set weights order accounts usefully.",
            "The dataset is simulated. Every number is reproducible from the seed and says nothing about "
            "real-world conversion.",
            "Scores are evaluated at their current value, not as of the moment of contact. GTMOS keeps score "
            "history but the demo seed does not backdate a score per touch, so the total-score variant is "
            "measured after the outcome it predicts.",
            "Grade thresholds (A≥72, B≥58, C≥45) were set from the score distribution and rep capacity, then "
            "checked against these conversion rates. That check is in-sample: the same accounts set and "
            "validated the bands, so the ladder below is a sanity check, not evidence of predictive power.",
        ],
    }


def _selection_effect(
    contacted: float | None, everyone: float | None, contacted_n: int, everyone_n: int
) -> dict[str, Any]:
    """Both available estimates of the structural score's power are biased, in opposite directions.

    Measured on contacted accounts only, the score is graded on the list it selected: reps never worked
    the low-fit tail, so the score's range is restricted and the AUC is pulled toward 0.5. Measured on
    every account, uncontacted accounts count as failures, which rewards the score for agreeing with the
    targeting decision it drove. The truth is between them and neither is an estimate of causal lift.
    """
    if contacted is None or everyone is None:
        return {"available": False}
    return {
        "available": True,
        "contacted_only_auc": contacted,
        "contacted_only_n": contacted_n,
        "all_accounts_auc": everyone,
        "all_accounts_n": everyone_n,
        "note": (
            "Range restriction (contacted only) biases downward; targeting feedback (all accounts) biases "
            "upward. The only unbiased measurement is a holdout: contact a random sample of accounts "
            "regardless of score and compare conversion across score bands. GTMOS does not run one, "
            "because the demo sends no email."
        ),
    }


def _leakage_delta(per_variant: dict[str, Any]) -> dict[str, Any]:
    """How much AUC the leaking variant gains over the clean one. Large gaps mean the headline number
    is mostly circular."""
    structural = per_variant.get("structural", {}).get("auc")
    total = per_variant.get("total", {}).get("auc")
    if structural is None or total is None:
        return {"available": False}
    return {
        "available": True,
        "structural_auc": structural,
        "total_auc": total,
        "delta": round(total - structural, 4),
        "interpretation": (
            "The total score's advantage over the structural score is contaminated: engagement points "
            "are downstream of the outcome. Read the structural AUC as the score's real prospecting value."
        ),
    }
