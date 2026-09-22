"""GTM experiment assignment and statistics.

Assignment is a pure hash of (experiment salt, unit id): the same account always lands in the same
variant, across processes and re-runs, with no assignment table required to reproduce it. We randomize at
the account level by default so two contacts at one company don't receive competing messages.

Statistics are deliberately conservative: Wilson intervals per variant, a two-proportion z-test, a
Newcombe interval for the difference, and a verdict that refuses to declare a winner when the sample
is below the pre-registered minimum or there are too few events for the normal approximation.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

BUCKETS = 10_000


def bucket_for(salt: str, unit_id: str) -> int:
    digest = hashlib.sha256(f"{salt}:{unit_id}".encode()).hexdigest()
    return int(digest[:15], 16) % BUCKETS


def assign_variant(salt: str, unit_id: str, variants: list[tuple[str, float]]) -> tuple[str, int]:
    """variants: [(key, weight)] in a fixed order. Returns (variant_key, bucket)."""
    if not variants:
        raise ValueError("experiment has no variants")
    total = sum(w for _, w in variants)
    if total <= 0:
        raise ValueError("variant weights must be positive")
    b = bucket_for(salt, unit_id)
    point = b / BUCKETS * total
    acc = 0.0
    for key, w in variants:
        acc += w
        if point < acc:
            return key, b
    return variants[-1][0], b


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


Z95 = 1.959963984540054


def wilson_interval(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = 0.0 if successes == 0 else max(0.0, centre - half)  # exact edges: avoid float residue like 5e-17
    hi = 1.0 if successes == n else min(1.0, centre + half)
    return (lo, hi)


def two_proportion_z(s1: int, n1: int, s2: int, n2: int) -> tuple[float, float]:
    """Returns (z, two-sided p-value) for H0: p1 == p2 using the pooled standard error."""
    if n1 == 0 or n2 == 0:
        return (0.0, 1.0)
    p_pool = (s1 + s2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return (0.0, 1.0)
    z = (s2 / n2 - s1 / n1) / se
    return (z, 2 * (1 - _norm_cdf(abs(z))))


def newcombe_diff_interval(s1: int, n1: int, s2: int, n2: int) -> tuple[float, float]:
    """95% CI for p2 - p1 (treatment minus control) via Newcombe's hybrid score method."""
    if n1 == 0 or n2 == 0:
        return (0.0, 0.0)
    p1, p2 = s1 / n1, s2 / n2
    l1, u1 = wilson_interval(s1, n1)
    l2, u2 = wilson_interval(s2, n2)
    d = p2 - p1
    lower = d - math.sqrt((p2 - l2) ** 2 + (u1 - p1) ** 2)
    upper = d + math.sqrt((u2 - p2) ** 2 + (p1 - l1) ** 2)
    return (lower, upper)


@dataclass
class VariantStats:
    key: str
    n: int
    successes: int
    rate: float
    ci_low: float
    ci_high: float


@dataclass
class ComparisonResult:
    control: VariantStats
    treatment: VariantStats
    absolute_lift: float
    relative_lift: float | None
    diff_ci_low: float
    diff_ci_high: float
    z: float
    p_value: float
    verdict: (
        str  # insufficient_sample | insufficient_events | no_significant_difference | treatment_better | control_better
    )
    explanation: str
    required_n_per_variant: int | None


def variant_stats(key: str, successes: int, n: int) -> VariantStats:
    lo, hi = wilson_interval(successes, n)
    return VariantStats(key, n, successes, successes / n if n else 0.0, lo, hi)


def required_sample_size(p_base: float, mde_abs: float, power_z: float = 0.8416, alpha_z: float = Z95) -> int:
    """Per-variant n to detect an absolute lift `mde_abs` at 95% confidence, 80% power."""
    if p_base <= 0 or mde_abs <= 0:
        return 0
    p2 = min(p_base + mde_abs, 0.999)
    p_bar = (p_base + p2) / 2
    num = (
        alpha_z * math.sqrt(2 * p_bar * (1 - p_bar)) + power_z * math.sqrt(p_base * (1 - p_base) + p2 * (1 - p2))
    ) ** 2
    return math.ceil(num / (mde_abs**2))


def compare(
    control: tuple[str, int, int],
    treatment: tuple[str, int, int],
    min_sample: int,
    alpha: float = 0.05,
    min_events: int = 5,
) -> ComparisonResult:
    """control/treatment: (key, successes, n)."""
    c = variant_stats(control[0], control[1], control[2])
    t = variant_stats(treatment[0], treatment[1], treatment[2])
    abs_lift = t.rate - c.rate
    rel = (abs_lift / c.rate) if c.rate > 0 else None
    lo, hi = newcombe_diff_interval(c.successes, c.n, t.successes, t.n)
    z, p = two_proportion_z(c.successes, c.n, t.successes, t.n)
    req = required_sample_size(c.rate, max(abs(abs_lift), 0.01)) if c.rate > 0 else None

    if min(c.n, t.n) < min_sample:
        verdict = "insufficient_sample"
        why = (
            f"Only {min(c.n, t.n)} units in the smaller arm; the pre-registered minimum is {min_sample}. "
            "No winner is declared."
        )
    elif min(c.successes, t.successes, c.n - c.successes, t.n - t.successes) < min_events:
        verdict = "insufficient_events"
        why = f"Fewer than {min_events} events in an arm; the normal approximation is unreliable."
    elif p >= alpha or lo <= 0 <= hi:
        verdict = "no_significant_difference"
        why = (
            f"p = {p:.3f}; the 95% CI for the difference ({lo * 100:+.1f} to {hi * 100:+.1f} pp) includes zero. "
            "We cannot reject H0."
        )
    elif abs_lift > 0:
        verdict = "treatment_better"
        why = (
            f"Treatment beats control by {abs_lift * 100:+.1f} pp (95% CI {lo * 100:+.1f} to {hi * 100:+.1f} pp, "
            f"p = {p:.3f}). Reject H0."
        )
    else:
        verdict = "control_better"
        why = (
            f"Control beats treatment by {-abs_lift * 100:.1f} pp (95% CI {lo * 100:+.1f} to {hi * 100:+.1f} pp, "
            f"p = {p:.3f})."
        )
    return ComparisonResult(c, t, abs_lift, rel, lo, hi, z, p, verdict, why, req)
