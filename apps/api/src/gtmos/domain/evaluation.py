"""Offline evaluation for a ranking score.

The ICP score is a hand-weighted heuristic, not a trained model, so the honest question is not
"how accurate is it" but "does working the list top-down beat working it at random, and by how much".
These are the standard answers to that question and they are pure functions of (score, outcome)
pairs so they can be unit-tested against hand-computed cases.

Everything here treats a higher score as a stronger prediction of a binary outcome. Nothing here
knows what the score means; leakage is the caller's problem and is discussed in
`docs/scoring-evaluation.md`.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

from gtmos.domain.experiments import wilson_interval

# Below this many positives a bucket's conversion rate is noise; the report says so rather than
# quietly rendering "100%" off two accounts.
MIN_BUCKET = 30


@dataclass(frozen=True)
class Observation:
    """One scored unit and what happened to it."""

    key: str
    score: float
    outcome: bool
    grade: str = ""


@dataclass
class Bucket:
    label: str
    n: int
    positives: int
    rate: float
    ci_low: float
    ci_high: float
    lift: float  # rate ÷ base rate; 1.0 = no better than random
    small_sample: bool
    score_min: float | None = None
    score_max: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "n": self.n,
            "positives": self.positives,
            "rate": round(self.rate, 4),
            "ci_low": round(self.ci_low, 4),
            "ci_high": round(self.ci_high, 4),
            "lift": round(self.lift, 3),
            "small_sample": self.small_sample,
            "score_min": self.score_min,
            "score_max": self.score_max,
        }


@dataclass
class Evaluation:
    n: int
    positives: int
    base_rate: float
    auc: float | None
    auc_ci: tuple[float, float] | None
    buckets: list[Bucket] = field(default_factory=list)
    by_grade: list[Bucket] = field(default_factory=list)
    precision_at_k: list[dict[str, Any]] = field(default_factory=list)
    monotonic: bool = False
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "positives": self.positives,
            "base_rate": round(self.base_rate, 4),
            "auc": round(self.auc, 4) if self.auc is not None else None,
            "auc_ci": [round(x, 4) for x in self.auc_ci] if self.auc_ci else None,
            "buckets": [b.as_dict() for b in self.buckets],
            "by_grade": [b.as_dict() for b in self.by_grade],
            "precision_at_k": self.precision_at_k,
            "monotonic": self.monotonic,
            "warnings": list(self.warnings),
        }


def roc_auc(obs: list[Observation]) -> float | None:
    """Probability a random positive outscores a random negative, ties counted as half.

    Computed as the rank-sum (Mann-Whitney U) form so it is exact and needs no threshold sweep.
    Returns None when one class is empty, where AUC is undefined rather than 0.5.
    """
    pos = [o.score for o in obs if o.outcome]
    neg = [o.score for o in obs if not o.outcome]
    if not pos or not neg:
        return None
    ranks = _midranks([o.score for o in obs])
    rank_sum = sum(r for r, o in zip(ranks, obs, strict=True) if o.outcome)
    n1, n0 = len(pos), len(neg)
    u = rank_sum - n1 * (n1 + 1) / 2
    return u / (n1 * n0)


def _midranks(values: list[float]) -> list[float]:
    """Ranks from 1, with tied values sharing the average of the ranks they span."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        mid = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = mid
        i = j + 1
    return ranks


def auc_interval(obs: list[Observation], auc: float) -> tuple[float, float]:
    """Hanley–McNeil 95% interval. Distribution-free, conservative, and enough to say whether a
    reported AUC is distinguishable from 0.5 at this sample size."""
    n1 = sum(1 for o in obs if o.outcome)
    n0 = len(obs) - n1
    if n1 == 0 or n0 == 0:
        return (0.0, 1.0)
    q1 = auc / (2 - auc)
    q2 = 2 * auc**2 / (1 + auc)
    var = (auc * (1 - auc) + (n1 - 1) * (q1 - auc**2) + (n0 - 1) * (q2 - auc**2)) / (n1 * n0)
    se = math.sqrt(max(var, 0.0))
    return (max(0.0, auc - 1.96 * se), min(1.0, auc + 1.96 * se))


def _bucket(label: str, rows: list[Observation], base_rate: float) -> Bucket:
    n = len(rows)
    positives = sum(1 for o in rows if o.outcome)
    rate = positives / n if n else 0.0
    low, high = wilson_interval(positives, n) if n else (0.0, 0.0)
    scores = [o.score for o in rows]
    return Bucket(
        label=label,
        n=n,
        positives=positives,
        rate=rate,
        ci_low=low,
        ci_high=high,
        lift=rate / base_rate if base_rate > 0 else 0.0,
        small_sample=n < MIN_BUCKET,
        score_min=min(scores) if scores else None,
        score_max=max(scores) if scores else None,
    )


def score_buckets(obs: list[Observation], bins: int = 5) -> list[Bucket]:
    """Equal-count bins from the highest scores down, so bucket 1 is "the top fifth of the list".

    Equal-count beats equal-width here: the score distribution is heavily skewed toward low scores,
    and a rep works a list by position, not by score value.
    """
    if not obs:
        return []
    base = sum(1 for o in obs if o.outcome) / len(obs)
    ordered = sorted(obs, key=lambda o: -o.score)
    size = len(ordered) / bins
    out: list[Bucket] = []
    for i in range(bins):
        chunk = ordered[round(i * size) : round((i + 1) * size)]
        if not chunk:
            continue
        out.append(_bucket(f"Top {round((i + 1) / bins * 100)}%" if i == 0 else f"Bin {i + 1}", chunk, base))
    return out


def grade_buckets(obs: list[Observation], order: tuple[str, ...] = ("A", "B", "C", "D", "X")) -> list[Bucket]:
    if not obs:
        return []
    base = sum(1 for o in obs if o.outcome) / len(obs)
    out = []
    for g in order:
        rows = [o for o in obs if o.grade == g]
        if rows:
            out.append(_bucket(g, rows, base))
    return out


def precision_at_k(obs: list[Observation], ks: tuple[int, ...] = (50, 100, 250, 500)) -> list[dict[str, Any]]:
    """What a rep actually experiences: work the top K accounts, how many convert, versus random.

    `random_expected` is the base rate × K, which is the list you would get by shuffling.
    """
    if not obs:
        return []
    base = sum(1 for o in obs if o.outcome) / len(obs)
    ordered = sorted(obs, key=lambda o: -o.score)
    rows = []
    for k in ks:
        if k > len(ordered):
            continue
        top = ordered[:k]
        hits = sum(1 for o in top if o.outcome)
        rows.append(
            {
                "k": k,
                "hits": hits,
                "precision": round(hits / k, 4),
                "random_expected": round(base * k, 1),
                "lift": round((hits / k) / base, 3) if base > 0 else 0.0,
                "recall": round(hits / sum(1 for o in obs if o.outcome), 4) if any(o.outcome for o in obs) else 0.0,
            }
        )
    return rows


def evaluate(obs: list[Observation], bins: int = 5, ks: tuple[int, ...] = (50, 100, 250, 500)) -> Evaluation:
    n = len(obs)
    positives = sum(1 for o in obs if o.outcome)
    base = positives / n if n else 0.0
    auc = roc_auc(obs)
    buckets = score_buckets(obs, bins)
    rates = [b.rate for b in buckets]
    warnings: list[str] = []
    if positives < 50:
        warnings.append(f"Only {positives} positive outcomes: every rate below has a wide interval.")
    if auc is not None and auc_interval(obs, auc)[0] <= 0.5:
        warnings.append("The AUC interval includes 0.5, so this ranking is not distinguishable from random.")
    if any(b.small_sample for b in buckets + grade_buckets(obs)):
        warnings.append(f"Buckets with fewer than {MIN_BUCKET} accounts are marked as small samples.")
    return Evaluation(
        n=n,
        positives=positives,
        base_rate=base,
        auc=auc,
        auc_ci=auc_interval(obs, auc) if auc is not None else None,
        buckets=buckets,
        by_grade=grade_buckets(obs),
        precision_at_k=precision_at_k(obs, ks),
        monotonic=all(a >= b for a, b in itertools.pairwise(rates)),
        warnings=warnings,
    )
