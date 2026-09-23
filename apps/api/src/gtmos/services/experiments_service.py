"""Experiment results from assignments and outcomes.

Success metrics and guardrails come out of the same `experiment_outcomes` table but are never mixed in the
response: success metrics get a two-sided comparison and a verdict, guardrails get a one-sided harm check
against their policy ceiling. The recommendation is computed here, from the primary comparison plus every
guardrail, so no caller can accidentally read a p-value as a decision.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gtmos.domain.experiments import (
    GUARDRAIL_METRICS,
    GUARDRAILS,
    SUCCESS_METRICS,
    ComparisonResult,
    GuardrailResult,
    compare,
    evaluate_guardrail,
    practical_threshold_for,
    recommend,
    variant_stats,
)
from gtmos.models import Campaign, Experiment, ExperimentAssignment, ExperimentOutcome, ExperimentVariant

METRICS = SUCCESS_METRICS


def results(db: Session, exp: Experiment) -> dict[str, Any]:
    variants = list(
        db.scalars(
            select(ExperimentVariant)
            .where(ExperimentVariant.experiment_id == exp.id)
            .order_by(ExperimentVariant.is_control.desc(), ExperimentVariant.key)
        )
    )
    n_by_variant = dict(
        db.execute(
            select(ExperimentAssignment.variant_id, func.count())
            .where(ExperimentAssignment.experiment_id == exp.id)
            .group_by(ExperimentAssignment.variant_id)
        )
        .tuples()
        .all()
    )
    outcome_rows = db.execute(
        select(
            ExperimentAssignment.variant_id,
            ExperimentOutcome.metric,
            func.count(),
            func.coalesce(func.sum(ExperimentOutcome.value), 0),
        )
        .join(ExperimentOutcome, ExperimentOutcome.assignment_id == ExperimentAssignment.id)
        .where(ExperimentAssignment.experiment_id == exp.id)
        .group_by(ExperimentAssignment.variant_id, ExperimentOutcome.metric)
    ).all()
    counts: dict[tuple[uuid.UUID, str], int] = {}
    pipeline: dict[uuid.UUID, float] = {}
    for vid, metric, n, total in outcome_rows:
        counts[(vid, metric)] = n
        if metric == "opportunity":
            pipeline[vid] = float(total)
    per_variant = []
    for v in variants:
        n = n_by_variant.get(v.id, 0)
        metrics = {m: asdict(variant_stats(v.key, counts.get((v.id, m), 0), n)) for m in METRICS}
        per_variant.append(
            {
                "key": v.key,
                "name": v.name,
                "description": v.description,
                "is_control": v.is_control,
                "units": n,
                "metrics": metrics,
                "guardrails": {g: asdict(variant_stats(v.key, counts.get((v.id, g), 0), n)) for g in GUARDRAIL_METRICS},
                "pipeline": pipeline.get(v.id, 0.0),
            }
        )
    comparisons: dict[str, Any] = {}
    guardrails: dict[str, Any] = {}
    control = next((v for v in variants if v.is_control), None)
    primary_result: ComparisonResult | None = None
    primary_checks: list[GuardrailResult] = []
    for v in variants:
        if control is None or v.id == control.id:
            continue
        comparisons[v.key] = {}
        for m in METRICS:
            r = compare(
                (control.key, counts.get((control.id, m), 0), n_by_variant.get(control.id, 0)),
                (v.key, counts.get((v.id, m), 0), n_by_variant.get(v.id, 0)),
                exp.min_sample_per_variant,
                practical_threshold=practical_threshold_for(m),
            )
            comparisons[v.key][m] = {k: val for k, val in asdict(r).items() if k not in ("control", "treatment")}
            if m == exp.primary_metric and primary_result is None:
                primary_result = r
        checks = [
            evaluate_guardrail(
                g,
                (control.key, counts.get((control.id, g), 0), n_by_variant.get(control.id, 0)),
                (v.key, counts.get((v.id, g), 0), n_by_variant.get(v.id, 0)),
            )
            for g in GUARDRAIL_METRICS
        ]
        guardrails[v.key] = {c.metric: asdict(c) for c in checks}
        if not primary_checks:  # the first treatment arm is the one the headline recommendation is about
            primary_checks = checks
    primary = comparisons.get(next(iter(comparisons), ""), {}).get(exp.primary_metric)
    rec = (
        recommend(exp.primary_metric, primary_result, primary_checks)
        if primary_result is not None
        else None  # single-variant experiment: nothing to compare against
    )
    campaign = db.get(Campaign, exp.campaign_id) if exp.campaign_id else None
    return {
        "id": str(exp.id),
        "key": exp.key,
        "name": exp.name,
        "hypothesis": exp.hypothesis,
        "null_hypothesis": exp.null_hypothesis,
        "primary_metric": exp.primary_metric,
        "unit": exp.unit,
        "status": exp.status,
        "min_sample_per_variant": exp.min_sample_per_variant,
        "assignment": f"sha256('{exp.salt}:' + {exp.unit}_id) mod 10000, split by variant weight",
        "started_at": exp.started_at,
        "ended_at": exp.ended_at,
        "campaign": campaign.name if campaign else None,
        "data_origin": exp.data_origin,
        "variants": per_variant,
        "comparisons": comparisons,
        "guardrails": guardrails,
        "guardrail_policy": {
            g: {"ceiling": GUARDRAILS[g].ceiling, "max_regression": GUARDRAILS[g].max_regression}
            for g in GUARDRAIL_METRICS
        },
        "verdict": primary["verdict"] if primary else "no_data",
        "verdict_explanation": primary["explanation"] if primary else "No comparison available.",
        "recommendation": asdict(rec) if rec else None,
    }


def list_experiments(db: Session, ws: uuid.UUID) -> list[dict[str, Any]]:
    out = []
    for e in db.scalars(select(Experiment).where(Experiment.workspace_id == ws).order_by(Experiment.started_at.desc())):
        r = results(db, e)
        out.append(
            {
                k: r[k]
                for k in (
                    "id",
                    "key",
                    "name",
                    "status",
                    "primary_metric",
                    "verdict",
                    "campaign",
                    "started_at",
                    "ended_at",
                    "unit",
                    "data_origin",
                )
            }
            | {
                "units": sum(v["units"] for v in r["variants"]),
                "action": (r["recommendation"] or {}).get("action"),
                "guardrail_breaches": sorted(
                    {
                        m
                        for by_metric in r["guardrails"].values()
                        for m, g in by_metric.items()
                        if g["status"] == "breach"
                    }
                ),
            }
        )
    return out
