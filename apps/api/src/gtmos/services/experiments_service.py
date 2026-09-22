"""Experiment results from assignments and outcomes."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gtmos.domain.experiments import compare, variant_stats
from gtmos.models import Campaign, Experiment, ExperimentAssignment, ExperimentOutcome, ExperimentVariant

METRICS = ("reply", "positive_reply", "meeting", "opportunity")


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
                "pipeline": pipeline.get(v.id, 0.0),
            }
        )
    comparisons: dict[str, Any] = {}
    control = next((v for v in variants if v.is_control), None)
    for v in variants:
        if control is None or v.id == control.id:
            continue
        comparisons[v.key] = {}
        for m in METRICS:
            r = compare(
                (control.key, counts.get((control.id, m), 0), n_by_variant.get(control.id, 0)),
                (v.key, counts.get((v.id, m), 0), n_by_variant.get(v.id, 0)),
                exp.min_sample_per_variant,
            )
            comparisons[v.key][m] = {k: val for k, val in asdict(r).items() if k not in ("control", "treatment")}
    primary = comparisons.get(next(iter(comparisons), ""), {}).get(exp.primary_metric)
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
        "verdict": primary["verdict"] if primary else "no_data",
        "verdict_explanation": primary["explanation"] if primary else "No comparison available.",
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
            | {"units": sum(v["units"] for v in r["variants"])}
        )
    return out
