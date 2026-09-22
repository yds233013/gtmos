"""Enrichment waterfall: ask providers in order, per field, until a confident value is found.

This is the Clay-style pattern. Each field has its own provider order, since the best source for
employee count is rarely the best source for tech stack. Every call is recorded, including misses,
low-confidence answers, errors and the fallbacks they caused, so coverage and cost can be audited.
A provider is called at most once per run: fields that share a provider at the same waterfall
position are batched into one request, as real vendor APIs charge per lookup.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol


class ProviderError(Exception):
    """A provider failed (timeout, 5xx, rate limit). The waterfall falls back to the next provider."""


@dataclass(frozen=True)
class FieldValue:
    value: Any
    confidence: float


class EnrichmentProvider(Protocol):
    key: str
    name: str
    supported_fields: frozenset[str]
    cost_per_lookup: float  # credits
    is_simulated: bool

    def lookup(self, domain: str, fields: list[str]) -> dict[str, FieldValue]:
        """Return values for the requested fields it knows. Missing keys mean 'no data'."""
        ...


@dataclass
class Attempt:
    field: str
    provider: str
    position: int
    outcome: str  # hit | miss | low_confidence | error | skipped
    value: Any = None
    confidence: float | None = None
    latency_ms: int = 0
    cost_credits: float = 0.0
    error: str | None = None


@dataclass
class ExistingValue:
    value: Any
    confidence: float
    source: str
    observed_at: datetime | None
    is_manual_lock: bool = False


@dataclass(frozen=True)
class Disagreement:
    """A provider answer that lost, kept so the losing value is visible rather than discarded."""

    provider: str
    value: Any
    confidence: float | None


@dataclass
class FieldConflict:
    field: str
    chosen_value: Any
    chosen_provider: str | None
    others: list[Disagreement]
    material: bool
    explanation: str


@dataclass
class FieldDecision:
    field: str
    # set | update | keep_existing | no_data | conflict
    # `conflict` means providers disagreed materially about a field that already had a value, so the
    # existing value was kept and the disagreement raised for a human instead of being resolved by
    # confidence alone.
    action: str
    value: Any
    confidence: float | None
    provider: str | None
    reason: str
    conflict: FieldConflict | None = None


@dataclass
class WaterfallResult:
    attempts: list[Attempt]
    decisions: list[FieldDecision]
    cost_credits: float
    providers_called: list[str] = field(default_factory=list)

    @property
    def fields_filled(self) -> list[str]:
        return [d.field for d in self.decisions if d.action in ("set", "update", "keep_existing")]

    @property
    def fields_changed(self) -> list[str]:
        return [d.field for d in self.decisions if d.action in ("set", "update")]

    @property
    def conflicts(self) -> list[FieldConflict]:
        return [d.conflict for d in self.decisions if d.conflict is not None]

    @property
    def status(self) -> str:
        if not self.decisions:
            return "succeeded"
        missing = [d for d in self.decisions if d.action == "no_data"]
        if not missing:
            return "succeeded"
        return "failed" if len(missing) == len(self.decisions) else "partial"


DEFAULT_MIN_CONFIDENCE = 0.6
STALE_AFTER = timedelta(days=180)
UPGRADE_MARGIN = 0.1


def decide(field_name: str, existing: ExistingValue | None, candidate: Attempt | None, now: datetime) -> FieldDecision:
    """Merge policy: never overwrite manual locks; only replace data with clearly better data."""
    if candidate is None or candidate.value is None:
        if existing is not None and existing.value is not None:
            return FieldDecision(
                field_name,
                "keep_existing",
                existing.value,
                existing.confidence,
                existing.source,
                "No provider returned a value; kept existing.",
            )
        return FieldDecision(field_name, "no_data", None, None, None, "No provider returned a value.")

    conf = candidate.confidence or 0.0
    if existing is None or existing.value is None:
        return FieldDecision(
            field_name,
            "set",
            candidate.value,
            conf,
            candidate.provider,
            f"Filled empty field from {candidate.provider} ({conf:.2f}).",
        )
    if existing.is_manual_lock:
        return FieldDecision(
            field_name,
            "keep_existing",
            existing.value,
            existing.confidence,
            existing.source,
            "Field is manually locked; provider value ignored.",
        )
    if existing.value == candidate.value:
        return FieldDecision(
            field_name,
            "keep_existing",
            existing.value,
            max(existing.confidence, conf),
            existing.source,
            "Provider confirmed the existing value.",
        )
    stale = existing.observed_at is None or now - existing.observed_at > STALE_AFTER
    if conf >= existing.confidence + UPGRADE_MARGIN:
        return FieldDecision(
            field_name,
            "update",
            candidate.value,
            conf,
            candidate.provider,
            f"Higher confidence ({conf:.2f} vs {existing.confidence:.2f}).",
        )
    if stale and conf >= existing.confidence:
        return FieldDecision(
            field_name,
            "update",
            candidate.value,
            conf,
            candidate.provider,
            "Existing value is stale (>180 days) and provider is at least as confident.",
        )
    return FieldDecision(
        field_name,
        "keep_existing",
        existing.value,
        existing.confidence,
        existing.source,
        f"Provider value {candidate.value!r} not confident enough to replace existing.",
    )


# Two numbers this close are the same fact measured differently (a headcount of 240 vs 247), not a
# disagreement worth a human's time.
NUMERIC_TOLERANCE = 0.15


def values_disagree(a: Any, b: Any) -> bool:
    """Is the difference between two provider answers worth surfacing?

    Providers disagree constantly in trivial ways — casing, legal suffixes, a headcount taken a month
    apart. Flagging those would train everyone to ignore the flag, so only differences a human would
    act on count.
    """
    if a is None or b is None:
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        return a is not b
    if isinstance(a, int | float) and isinstance(b, int | float):
        largest = max(abs(float(a)), abs(float(b)))
        if largest == 0:
            return False
        return abs(float(a) - float(b)) / largest > NUMERIC_TOLERANCE
    if isinstance(a, list | tuple | set) and isinstance(b, list | tuple | set):
        # Tech stacks are coverage, not contradiction: one provider seeing more tools than another is
        # normal. Only a genuine contradiction — each sees something the other denies — counts.
        sa, sb = {str(x).strip().casefold() for x in a}, {str(x).strip().casefold() for x in b}
        return bool(sa - sb) and bool(sb - sa)
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().casefold() != b.strip().casefold()
    return bool(a != b)


# A disagreement this large is not measurement error; it is two sources answering different questions
# (one legal entity versus a whole group). It changes the segment, so it changes routing and scoring.
MATERIAL_NUMERIC_GAP = 0.5


def _large_numeric_gap(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return False
    if not isinstance(a, int | float) or not isinstance(b, int | float):
        return False
    largest = max(abs(float(a)), abs(float(b)))
    return largest > 0 and abs(float(a) - float(b)) / largest > MATERIAL_NUMERIC_GAP


def detect_conflict(
    decision: FieldDecision, observations: list[Disagreement], min_confidence: float = DEFAULT_MIN_CONFIDENCE
) -> FieldConflict | None:
    """Compare the chosen answer with every other answer the run already paid for.

    This costs nothing extra, which is the point. A waterfall stops asking as soon as one provider
    answers confidently, so it looks like there is no second opinion to be had — but a provider call
    returns every field that provider supports, and GTMOS caches the whole response for the run. When
    a later position calls another provider for *some other* field, that response usually carries an
    unsolicited second opinion on fields already resolved. Those observations are otherwise discarded.
    """
    chosen = decision.value
    others = [o for o in observations if o.provider != decision.provider and values_disagree(chosen, o.value)]
    if not others:
        return None
    # Materiality is about consequence, not only about how sure the dissenter sounds. A confident
    # contradiction counts; so does a numeric gap large enough to move an account between segments,
    # even from a source that admits it is estimating.
    material = any(
        (o.confidence is not None and o.confidence >= min_confidence) or _large_numeric_gap(chosen, o.value)
        for o in others
    )
    listed = ", ".join(f"{o.provider} says {o.value!r}" for o in others)
    return FieldConflict(
        field=decision.field,
        chosen_value=chosen,
        chosen_provider=decision.provider,
        others=others,
        material=material,
        explanation=f"Kept {chosen!r} from {decision.provider}; {listed}.",
    )


def apply_conflict(
    decision: FieldDecision, conflict: FieldConflict | None, existing: ExistingValue | None
) -> FieldDecision:
    """Attach a conflict, and refuse to overwrite an existing value on a contested answer.

    Confidence is a provider's opinion of itself. When two confident providers contradict each other
    about a field that already holds a value, the honest move is to keep what is there and ask a
    human, not to let the marginally more self-assured provider win silently.
    """
    if conflict is None:
        return decision
    decision.conflict = conflict
    if decision.action == "update" and conflict.material and existing is not None:
        decision.action = "conflict"
        decision.value = existing.value
        decision.confidence = existing.confidence
        decision.provider = existing.source
        decision.reason = (
            f"Providers disagree materially ({conflict.explanation}) — kept the existing value and "
            "raised it for review rather than overwriting on confidence alone."
        )
    return decision


def run_waterfall(
    domain: str,
    fields: list[str],
    waterfall: dict[str, list[str]],
    providers: dict[str, EnrichmentProvider],
    existing: dict[str, ExistingValue],
    now: datetime,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    clock: Any = time.perf_counter,
) -> WaterfallResult:
    attempts: list[Attempt] = []
    resolved: dict[str, Attempt] = {}
    fallback: dict[str, Attempt] = {}  # best low-confidence answer, used only if nothing better
    responses: dict[str, dict[str, FieldValue] | ProviderError] = {}
    latencies: dict[str, int] = {}
    cost = 0.0
    called: list[str] = []

    depth = max((len(waterfall.get(f, [])) for f in fields), default=0)
    for position in range(depth):
        # Group still-unresolved fields by the provider at this position.
        batch: dict[str, list[str]] = {}
        for f in fields:
            order = waterfall.get(f, [])
            if f in resolved or position >= len(order):
                continue
            batch.setdefault(order[position], []).append(f)

        for provider_key, wanted in batch.items():
            provider = providers.get(provider_key)
            if provider is None:
                attempts.extend(
                    Attempt(f, provider_key, position, "skipped", error="provider not configured") for f in wanted
                )
                continue
            supported = [f for f in wanted if f in provider.supported_fields]
            attempts.extend(
                Attempt(f, provider_key, position, "skipped", error="field not supported")
                for f in wanted
                if f not in provider.supported_fields
            )
            if not supported:
                continue
            first_call = provider_key not in responses
            if first_call:
                start = clock()
                # Ask for everything this provider can supply for the run, not just this position's
                # fields: the cached response then also serves later waterfall positions.
                request = [f for f in fields if f in provider.supported_fields]
                try:
                    responses[provider_key] = provider.lookup(domain, request)
                except ProviderError as exc:
                    responses[provider_key] = exc
                measured = int((clock() - start) * 1000)
                # Simulated providers report the latency they would have had instead of sleeping.
                reported = getattr(provider, "last_latency_ms", None)
                latencies[provider_key] = reported if isinstance(reported, int) and reported else measured
                cost += provider.cost_per_lookup
                called.append(provider_key)
            resp = responses[provider_key]
            call_cost = provider.cost_per_lookup if first_call else 0.0
            for i, f in enumerate(supported):
                charge = call_cost if i == 0 else 0.0
                lat = latencies.get(provider_key, 0) if i == 0 else 0
                if isinstance(resp, ProviderError):
                    attempts.append(
                        Attempt(
                            f, provider_key, position, "error", latency_ms=lat, cost_credits=charge, error=str(resp)
                        )
                    )
                    continue
                fv = resp.get(f)
                if fv is None or fv.value is None or fv.value == "" or fv.value == []:
                    attempts.append(Attempt(f, provider_key, position, "miss", latency_ms=lat, cost_credits=charge))
                    continue
                if fv.confidence < min_confidence:
                    att = Attempt(f, provider_key, position, "low_confidence", fv.value, fv.confidence, lat, charge)
                    attempts.append(att)
                    if f not in fallback or (fallback[f].confidence or 0) < fv.confidence:
                        fallback[f] = att
                    continue
                att = Attempt(f, provider_key, position, "hit", fv.value, fv.confidence, lat, charge)
                attempts.append(att)
                resolved[f] = att

    # Every answer the run paid for, including the ones no attempt was ever recorded against: a
    # provider called at position 2 for one field also answered the fields resolved at position 0.
    observed: dict[str, list[Disagreement]] = {}
    for provider_key, resp in responses.items():
        if isinstance(resp, ProviderError):
            continue
        for f, fv in resp.items():
            if f in fields and fv.value not in (None, "", []):
                observed.setdefault(f, []).append(Disagreement(provider_key, fv.value, fv.confidence))

    decisions = []
    for f in fields:
        decision = decide(f, existing.get(f), resolved.get(f) or fallback.get(f), now)
        if decision.action != "no_data":
            conflict = detect_conflict(decision, observed.get(f, []), min_confidence)
            decision = apply_conflict(decision, conflict, existing.get(f))
        decisions.append(decision)
    return WaterfallResult(attempts, decisions, round(cost, 4), called)
