"""GTM experiment assignment and statistics.

Assignment is a pure hash of (experiment salt, unit id): the same account always lands in the same
variant, across processes and re-runs, with no assignment table required to reproduce it. We randomize at
the account level by default so two contacts at one company don't receive competing messages.

Statistics are deliberately conservative: Wilson intervals per variant, a two-proportion z-test, a
Newcombe interval for the difference, and a verdict that refuses to declare a winner when the sample
is below the pre-registered minimum or there are too few events for the normal approximation.

Two things separate a verdict from a decision, and both live here.

*Guardrails* are metrics we evaluate for harm, never for lift. Bounces, unsubscribes, spam complaints and
negative replies are not competing success metrics to be traded off against replies; they are limits. A
variant that wins the primary metric while pushing a guardrail past its ceiling is not a winner, it is a
variant that borrowed reply rate from the sending domain. So guardrails are tested one-sided, against an
absolute policy ceiling and against a tolerated regression from control, and any confirmed breach blocks
the recommendation whatever the primary metric did.

*Practical significance* is the second gap. A p-value answers "is this difference real?", not "is it worth
the operational cost of changing the play?". We report the minimum detectable effect for the sample we
actually have, so a null result can be read as "no meaningful effect" rather than "underpowered", and we
compare the lift against a pre-set threshold in percentage points before recommending a change.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

BUCKETS = 10_000

# Success metrics move in the direction we want; guardrails are the ones we only ever check for damage.
SUCCESS_METRICS = ("reply", "positive_reply", "meeting", "opportunity")


@dataclass(frozen=True)
class Guardrail:
    """A limit, not a metric to optimise.

    `ceiling` is an absolute rate we refuse to operate above whatever the lift; `max_regression` is how much
    worse than control we will tolerate even while staying under the ceiling. Both are policy, set before the
    test, not derived from the data.
    """

    metric: str
    label: str
    ceiling: float
    max_regression: float
    rationale: str


GUARDRAILS: dict[str, Guardrail] = {
    "bounce": Guardrail(
        "bounce",
        "Hard bounce rate",
        0.05,
        0.015,
        "Sustained hard bounces above ~5% tell mailbox providers the list is unverified and the sending "
        "domain starts getting filtered. It is a list-quality signal, so a variant should not move it at all.",
    ),
    "unsubscribe": Guardrail(
        "unsubscribe",
        "Unsubscribe rate",
        0.01,
        0.004,
        "An unsubscribe is a permanent loss of a targetable account. Healthy cold outbound sits well under "
        "1%; a variant that buys replies by annoying the other 99% is spending an asset we cannot rebuy.",
    ),
    "spam_complaint": Guardrail(
        "spam_complaint",
        "Spam complaint rate",
        0.003,
        0.001,
        "Gmail and Yahoo bulk-sender rules put the hard limit at 0.3% and the target at 0.1%. Crossing it "
        "throttles every campaign from the domain, not just this one.",
    ),
    "negative_reply": Guardrail(
        "negative_reply",
        "Negative reply rate",
        0.08,
        0.025,
        "Explicitly hostile or 'do not contact us' replies. They burn the account for future plays and are "
        "the part of a raised reply rate that looks like success in a dashboard and like damage in a CRM.",
    ),
}
GUARDRAIL_METRICS = tuple(GUARDRAILS)

# The lift below which changing the play costs more than it earns: retraining reps, rewriting sequences,
# re-approving copy. Policy, in absolute percentage points, chosen before the test and deliberately blunt.
PRACTICAL_THRESHOLD: dict[str, float] = {
    "reply": 0.02,
    "positive_reply": 0.015,
    "meeting": 0.01,
    "opportunity": 0.005,
}
DEFAULT_PRACTICAL_THRESHOLD = 0.02


def practical_threshold_for(metric: str) -> float:
    return PRACTICAL_THRESHOLD.get(metric, DEFAULT_PRACTICAL_THRESHOLD)


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
    mde_abs: float | None  # smallest lift this sample could have detected at 80% power
    mde_relative: float | None
    practical_threshold: float
    practically_significant: bool  # the observed lift clears the threshold
    practical_interval_clears: bool  # the whole difference interval clears it, which is the stronger claim
    practical_note: str


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


def minimum_detectable_effect(p_base: float, n_per_variant: int, power_z: float = 0.8416) -> float | None:
    """The smallest absolute lift `n_per_variant` units per arm could have caught at 95%/80% power.

    Inverted from `required_sample_size` by bisection rather than a second closed form, so the two numbers
    can never disagree. It assumes equal arms, one look at the data and the control rate as the baseline —
    all three are true of how these tests are run here. Read it as "a real lift smaller than this would
    probably have been missed", which is what turns a null result into evidence instead of a shrug.
    """
    if n_per_variant <= 0 or not 0 < p_base < 1:
        return None
    lo, hi = 1e-6, 1.0 - p_base
    if required_sample_size(p_base, hi, power_z=power_z) > n_per_variant:
        return None  # even a lift to certainty would not be readable at this n
    for _ in range(60):
        mid = (lo + hi) / 2
        if required_sample_size(p_base, mid, power_z=power_z) > n_per_variant:
            lo = mid
        else:
            hi = mid
    return hi


def compare(
    control: tuple[str, int, int],
    treatment: tuple[str, int, int],
    min_sample: int,
    alpha: float = 0.05,
    min_events: int = 5,
    practical_threshold: float = DEFAULT_PRACTICAL_THRESHOLD,
) -> ComparisonResult:
    """control/treatment: (key, successes, n)."""
    c = variant_stats(control[0], control[1], control[2])
    t = variant_stats(treatment[0], treatment[1], treatment[2])
    abs_lift = t.rate - c.rate
    rel = (abs_lift / c.rate) if c.rate > 0 else None
    lo, hi = newcombe_diff_interval(c.successes, c.n, t.successes, t.n)
    z, p = two_proportion_z(c.successes, c.n, t.successes, t.n)
    req = required_sample_size(c.rate, max(abs(abs_lift), 0.01)) if c.rate > 0 else None
    mde = minimum_detectable_effect(c.rate, min(c.n, t.n))
    mde_rel = (mde / c.rate) if mde is not None and c.rate > 0 else None
    clears_point = abs_lift >= practical_threshold
    clears_interval = lo >= practical_threshold

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

    bar = f"{practical_threshold * 100:.1f} pp"
    if mde is None:
        note = f"Sample too small to detect any lift at 80% power. The practical bar for shipping is {bar}."
    elif verdict == "no_significant_difference":
        note = (
            f"This test could only have detected a lift of about {mde * 100:.1f} pp or more, so a true effect "
            f"smaller than that would likely have been missed. Read it as 'no effect worth the switch' only "
            f"because {mde * 100:.1f} pp is already near the {bar} we would act on."
            if mde <= practical_threshold * 1.5
            else f"This test could only have detected about {mde * 100:.1f} pp, well above the {bar} bar we "
            f"would act on — the null result is underpowered, not evidence of no effect."
        )
    elif clears_interval:
        note = f"The whole difference interval clears the {bar} bar, so the lift is worth the switching cost."
    elif clears_point:
        note = (
            f"The observed lift clears the {bar} bar but the interval still allows a smaller one "
            f"({lo * 100:+.1f} pp at the low end). Worth shipping, not worth promising."
        )
    else:
        note = f"Any lift here is below the {bar} we treat as worth the operational cost of changing the play."
    return ComparisonResult(
        c,
        t,
        abs_lift,
        rel,
        lo,
        hi,
        z,
        p,
        verdict,
        why,
        req,
        mde,
        mde_rel,
        practical_threshold,
        clears_point,
        clears_interval,
        note,
    )


@dataclass
class GuardrailResult:
    metric: str
    label: str
    control: VariantStats
    treatment: VariantStats
    ceiling: float
    max_regression: float
    absolute_lift: float  # treatment minus control: positive means MORE harm, never "better"
    diff_ci_low: float
    diff_ci_high: float
    status: str  # ok | watch | breach | no_data
    conclusive: bool  # we could rule a ceiling breach out, rather than merely failing to see one
    reason: str
    rationale: str  # why this limit exists at all, carried through so the UI never shows a bare number


def evaluate_guardrail(metric: str, control: tuple[str, int, int], treatment: tuple[str, int, int]) -> GuardrailResult:
    """One-sided harm test for a guardrail. control/treatment: (key, events, n).

    Deliberately not gated on the experiment's minimum sample: that minimum is powered for the primary
    metric, and evidence of harm should not have to wait for it. The Wilson lower bound does the honest
    work instead — with few units it simply never clears the ceiling, which is the correct answer.
    """
    g = GUARDRAILS[metric]
    c = variant_stats(control[0], control[1], control[2])
    t = variant_stats(treatment[0], treatment[1], treatment[2])
    lift = t.rate - c.rate
    lo, hi = newcombe_diff_interval(c.successes, c.n, t.successes, t.n)
    conclusive = t.n > 0 and t.ci_high <= g.ceiling

    if t.n == 0:
        status, reason = "no_data", "No units exposed to this variant yet."
    elif t.ci_low > g.ceiling:
        status = "breach"
        reason = (
            f"{t.rate * 100:.2f}% is above the {g.ceiling * 100:.2f}% ceiling and the whole 95% interval "
            f"({t.ci_low * 100:.2f}–{t.ci_high * 100:.2f}%) sits above it."
        )
    elif lo > g.max_regression:
        status = "breach"
        reason = (
            f"{lift * 100:+.2f} pp worse than control, and the 95% interval starts at {lo * 100:+.2f} pp — "
            f"past the {g.max_regression * 100:.2f} pp regression we tolerate."
        )
    elif t.rate > g.ceiling:
        status = "watch"
        reason = (
            f"{t.rate * 100:.2f}% is over the {g.ceiling * 100:.2f}% ceiling, but the interval "
            f"({t.ci_low * 100:.2f}–{t.ci_high * 100:.2f}%) still reaches back under it. Not proven; not ignorable."
        )
    elif lift > g.max_regression:
        status = "watch"
        reason = (
            f"{lift * 100:+.2f} pp worse than control, over the {g.max_regression * 100:.2f} pp we tolerate, "
            f"but the difference interval ({lo * 100:+.2f} to {hi * 100:+.2f} pp) includes smaller regressions."
        )
    elif conclusive:
        status, reason = (
            "ok",
            f"{t.rate * 100:.2f}%, and the 95% interval stays under the {g.ceiling * 100:.2f}% ceiling.",
        )
    else:
        status = "ok"
        reason = (
            f"{t.rate * 100:.2f}% is under the {g.ceiling * 100:.2f}% ceiling, but with {t.n} units the "
            f"interval still reaches {t.ci_high * 100:.2f}% — under the limit, not yet cleared of it."
        )
    if c.rate > g.ceiling and status != "breach":
        # Control over its own ceiling is a standing problem with the play, not something this variant caused.
        reason += (
            f" Control is over the ceiling too ({c.rate * 100:.2f}%), so this is a programme issue, not a variant one."
        )
    return GuardrailResult(
        metric, g.label, c, t, g.ceiling, g.max_regression, lift, lo, hi, status, conclusive, reason, g.rationale
    )


@dataclass
class Recommendation:
    action: str  # ship | do_not_ship | keep_running | no_change
    headline: str
    reasoning: str
    blocking_guardrails: list[str] = field(default_factory=list)
    watch_guardrails: list[str] = field(default_factory=list)


CAUSAL_CAVEAT = (
    "Randomisation licenses a causal read of the gap between these two arms, on this audience, in this "
    "window — and nothing wider."
)


def recommend(metric: str, primary: ComparisonResult, guardrails: list[GuardrailResult]) -> Recommendation:
    """Turn a statistical verdict plus guardrails into a ship decision.

    The ordering is the whole point: a breached guardrail outranks any win on the primary metric, because
    the guardrail is a constraint and the primary metric is an objective. Optimising the objective by
    violating the constraint is not a win, it is an unpriced transfer from next quarter.
    """
    breaches = [g for g in guardrails if g.status == "breach"]
    watches = [g for g in guardrails if g.status == "watch"]
    blocking = [g.metric for g in breaches]
    watching = [g.metric for g in watches]
    lift_txt = f"{primary.absolute_lift * 100:+.1f} pp on {metric.replace('_', ' ')}"
    watch_txt = (
        " Also watch " + ", ".join(f"{g.label.lower()} ({g.treatment.rate * 100:.2f}%)" for g in watches) + "."
        if watches
        else ""
    )

    if breaches:
        worst = breaches[0]
        won = primary.verdict == "treatment_better"
        return Recommendation(
            "do_not_ship",
            "Do not ship — guardrail breached" + (" despite the win" if won else ""),
            (
                f"{worst.label} is {worst.treatment.rate * 100:.2f}% on the treatment against "
                f"{worst.control.rate * 100:.2f}% on control. {worst.reason} {worst.rationale} "
                + (
                    f"The treatment did win the primary metric ({lift_txt}), and that is exactly the trade we "
                    "are refusing: the lift is real and it is being paid for out of the sending domain."
                    if won
                    else f"The primary metric shows {lift_txt}, which does not buy back the breach."
                )
                + watch_txt
            ),
            blocking,
            watching,
        )
    if primary.verdict in ("insufficient_sample", "insufficient_events"):
        return Recommendation(
            "keep_running",
            "Keep running — no decision yet",
            f"{primary.explanation} No guardrail has been breached, so the test can continue. "
            f"{primary.practical_note}{watch_txt}",
            blocking,
            watching,
        )
    if primary.verdict == "control_better":
        return Recommendation(
            "do_not_ship",
            "Do not ship — control wins",
            f"{primary.explanation} {CAUSAL_CAVEAT}{watch_txt}",
            blocking,
            watching,
        )
    if primary.verdict == "no_significant_difference":
        return Recommendation(
            "no_change",
            "No change — no effect we could act on",
            f"{primary.explanation} {primary.practical_note} Keeping the current play costs nothing; "
            f"switching would.{watch_txt}",
            blocking,
            watching,
        )
    if not primary.practically_significant:
        return Recommendation(
            "no_change",
            "No change — real but too small to be worth it",
            f"{primary.explanation} {primary.practical_note} A statistically real lift below the bar is a "
            f"result, not a reason to rewrite the play.{watch_txt}",
            blocking,
            watching,
        )
    return Recommendation(
        "ship",
        "Ship the treatment",
        f"{primary.explanation} {primary.practical_note} Every guardrail is inside its limit. "
        f"{CAUSAL_CAVEAT}{watch_txt}",
        blocking,
        watching,
    )
