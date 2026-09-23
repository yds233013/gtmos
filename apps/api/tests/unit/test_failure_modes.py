"""Failure tournament: the cases that need no database.

Companion to `tests/integration/test_failure_tournament.py`. Everything here is a boundary GTMOS owns
in pure code — the enrichment waterfall's fallback behaviour, the merge policy's treatment of stale
data, the HubSpot HTTP retry bound and the matcher's refusal to treat a free-mail domain as a company.
They live apart from the integration file because they are deterministic and need no fixture universe,
and because a retry bound proven against a mock transport is proven for the *real* adapter, which the
integration suite can never call.

Each test name is the claim it defends. See `docs/failure-tournament.md` for the scenario table.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from gtmos.domain.enrichment import (
    Attempt,
    Disagreement,
    ExistingValue,
    FieldValue,
    ProviderError,
    apply_conflict,
    decide,
    detect_conflict,
    run_waterfall,
)
from gtmos.domain.matching import AccountRef, Lead, match_lead_to_account, match_to_account
from gtmos.integrations.hubspot import AssociationRequest, RealHubSpotAdapter, UpsertRecord

NOW = datetime(2026, 6, 1, tzinfo=UTC)


# --------------------------------------------------------------------------------------------------
# Clay / enrichment: a provider that breaks must cost the run a provider, not the field
# --------------------------------------------------------------------------------------------------


class _FakeProvider:
    """A provider that answers from a dict, or raises. Enough to satisfy the EnrichmentProvider protocol."""

    is_simulated = True

    def __init__(self, key: str, answers: dict[str, FieldValue], *, raises: Exception | None = None) -> None:
        self.key = key
        self.name = key
        self.answers = answers
        self.raises = raises
        self.supported_fields = frozenset(answers) if raises is None else frozenset({"industry", "employee_count"})
        self.cost_per_lookup = 1.0
        self.calls = 0

    def lookup(self, domain: str, fields: list[str]) -> dict[str, FieldValue]:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return {f: v for f, v in self.answers.items() if f in fields}


def test_a_provider_timeout_makes_the_waterfall_fall_through_to_the_next_provider():
    slow = _FakeProvider("slow_vendor", {}, raises=ProviderError("slow_vendor: upstream timeout"))
    backup = _FakeProvider("backup_vendor", {"industry": FieldValue("AI/ML Platforms", 0.9)})

    result = run_waterfall(
        "kestrel.example",
        ["industry"],
        {"industry": ["slow_vendor", "backup_vendor"]},
        {"slow_vendor": slow, "backup_vendor": backup},
        existing={},
        now=NOW,
    )

    decision = result.decisions[0]
    assert decision.action == "set" and decision.value == "AI/ML Platforms"
    assert decision.provider == "backup_vendor", "the field must be answered by the provider behind the broken one"
    # The timeout is not swallowed: it is an attempt with outcome `error`, which is what makes provider
    # health measurable instead of invisible.
    errored = [a for a in result.attempts if a.outcome == "error"]
    assert [a.provider for a in errored] == ["slow_vendor"]
    assert "timeout" in (errored[0].error or "")
    assert slow.calls == 1, "a provider that timed out is not called again inside the same run"


def test_every_provider_timing_out_leaves_the_field_empty_rather_than_guessed_at():
    first = _FakeProvider("a", {}, raises=ProviderError("a: upstream timeout"))
    second = _FakeProvider("b", {}, raises=ProviderError("b: upstream timeout"))

    result = run_waterfall(
        "kestrel.example",
        ["industry"],
        {"industry": ["a", "b"]},
        {"a": first, "b": second},
        existing={},
        now=NOW,
    )

    assert result.decisions[0].action == "no_data" and result.decisions[0].value is None
    assert result.status == "failed"
    assert len([a for a in result.attempts if a.outcome == "error"]) == 2, "both failures stay on the record"


def test_a_provider_timeout_never_erases_a_value_we_already_had():
    """Invariant 2 (no silent corruption), waterfall edition: a broken vendor cannot blank a field."""
    broken = _FakeProvider("a", {}, raises=ProviderError("a: 503"))
    existing = {"industry": ExistingValue("Developer Tools", 0.85, "demo_firmographics", NOW, False)}

    result = run_waterfall(
        "kestrel.example", ["industry"], {"industry": ["a"]}, {"a": broken}, existing=existing, now=NOW
    )

    decision = result.decisions[0]
    assert decision.action == "keep_existing" and decision.value == "Developer Tools"


# --------------------------------------------------------------------------------------------------
# Merge policy: stale data is not trusted just because it got there first
# --------------------------------------------------------------------------------------------------


def test_a_stale_value_is_replaced_by_an_equally_confident_fresh_one_but_a_current_value_is_not():
    """Staleness is the tie-breaker. Without it, the first answer ever written wins forever."""
    candidate = Attempt("employee_count", "demo_webscan", 0, "hit", 400, 0.9)
    stale = ExistingValue(240, 0.9, "demo_firmographics", NOW - timedelta(days=400), False)
    current = ExistingValue(240, 0.9, "demo_firmographics", NOW - timedelta(days=5), False)

    assert decide("employee_count", stale, candidate, NOW).action == "update"
    assert "stale" in decide("employee_count", stale, candidate, NOW).reason
    # The same pair of numbers, only fresher, is kept: freshness is the only thing that differs, so it
    # is the only thing that may decide.
    assert decide("employee_count", current, candidate, NOW).action == "keep_existing"


def test_a_value_with_no_observation_date_counts_as_stale_rather_than_as_trusted():
    """A field with no provenance is of unknown age. Treating that as fresh would trust an import forever."""
    candidate = Attempt("industry", "demo_webscan", 0, "hit", "Developer Tools", 0.7)
    undated = ExistingValue("AI/ML Platforms", 0.7, "unknown", None, False)

    assert decide("industry", undated, candidate, NOW).action == "update"


def test_a_manual_lock_outranks_every_provider_however_confident():
    """Invariant 4 (no unsupported field overwrite): a human's answer is not a confidence score."""
    candidate = Attempt("industry", "demo_webscan", 0, "hit", "Developer Tools", 0.99)
    locked = ExistingValue("AI/ML Platforms", 0.5, "human", NOW - timedelta(days=900), is_manual_lock=True)

    decision = decide("industry", locked, candidate, NOW)

    assert decision.action == "keep_existing" and decision.value == "AI/ML Platforms"


def test_two_providers_that_disagree_materially_keep_the_stored_value_and_raise_a_conflict():
    """Never a silent overwrite: the marginally more self-assured vendor does not get to win alone."""
    existing = ExistingValue(240, 0.8, "demo_firmographics", NOW - timedelta(days=10), False)
    candidate = Attempt("employee_count", "clay:clearbit", 0, "hit", 1800, 0.95)
    decision = decide("employee_count", existing, candidate, NOW)
    assert decision.action == "update", "without the second opinion, confidence alone would overwrite"

    observations = [
        Disagreement("clay:clearbit", 1800, 0.95),
        Disagreement("demo_firmographics", 240, 0.8),
    ]
    decision = apply_conflict(decision, detect_conflict(decision, observations), existing)

    assert decision.action == "conflict"
    assert decision.value == 240, "the stored value stays put until a human resolves the disagreement"
    assert decision.conflict is not None and decision.conflict.material
    assert any(o.value == 240 for o in decision.conflict.others), "the losing value must remain visible"


# --------------------------------------------------------------------------------------------------
# Matching: gmail.com is not a company
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("domain", ["gmail.com", "outlook.com", "proton.me", "qq.com"])
def test_a_free_mail_address_is_never_matched_to_a_company(domain: str):
    known = {"kestrel.example", domain}  # even if someone managed to create such an account

    result = match_to_account(known, email=f"buyer@{domain}")

    assert result.account_key is None and result.method == "none"
    assert "free-mail" in result.reason


def test_a_free_mail_lead_with_no_company_name_is_an_unmatched_lead_not_a_guess():
    accounts = [AccountRef(key="kestrel", name="Kestrel Analytics", domain="kestrel.example")]

    match = match_lead_to_account(Lead(email="buyer@gmail.com"), accounts)

    assert match.account_key is None and match.method == "none"
    assert "free-mail" in match.reason


# --------------------------------------------------------------------------------------------------
# HubSpot transport: the retry loop is bounded, and the bound is provable without a portal
# --------------------------------------------------------------------------------------------------


class _Portal:
    """A RealHubSpotAdapter over a mock transport that always answers with one status code."""

    def __init__(self, status: int, *, max_retries: int = 4, headers: dict[str, str] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.waits: list[float] = []
        client = httpx.Client(
            transport=httpx.MockTransport(self._respond(status, headers or {})), base_url="https://api.hubapi.test"
        )
        self.adapter = RealHubSpotAdapter("token", client=client, max_retries=max_retries, sleep=self.waits.append)

    def _respond(self, status: int, headers: dict[str, str]):  # type: ignore[no-untyped-def]
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(status, json={"message": "slow down"}, headers=headers)

        return handler

    def upsert_one(self):  # type: ignore[no-untyped-def]
        return self.adapter.upsert("companies", [UpsertRecord(uuid.uuid4(), "acme", {"name": "Acme"})])


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_invariant_3_no_unbounded_retry_the_hubspot_client_stops_at_its_retry_bound(status: int):
    portal = _Portal(status, max_retries=4)

    outcome = portal.upsert_one()

    assert len(portal.requests) == 4, f"a permanent {status} must be attempted max_retries times, not forever"
    assert portal.waits == [1.0, 2.0, 4.0], "backoff doubles, and there is no sleep after the final attempt"
    # And the give-up is *reported*, not swallowed: the caller learns the rows are retryable and why.
    assert [r.status for r in outcome.results] == ["failed"]
    assert outcome.results[0].retryable is True
    assert f"HTTP {status}" in (outcome.results[0].error or "")


def test_a_retry_after_header_is_honoured_rather_than_the_clients_own_backoff():
    portal = _Portal(429, max_retries=3, headers={"Retry-After": "7"})

    portal.upsert_one()

    assert len(portal.requests) == 3
    assert portal.waits == [7.0, 7.0], "HubSpot's own advice outranks our guess at how long to wait"


def test_a_400_is_not_retried_at_all_because_retrying_it_only_burns_rate_limit():
    portal = _Portal(400, max_retries=4)

    outcome = portal.upsert_one()

    assert len(portal.requests) == 1 and portal.waits == []
    assert outcome.results[0].retryable is False, "a permanent error must never be marked retryable"


def test_an_unknown_association_pair_fails_every_row_with_a_reason_instead_of_reaching_the_network():
    portal = _Portal(200)

    outcome = portal.adapter.associate("companies", "tickets", [AssociationRequest("1", "2")])

    assert portal.requests == [], "an association type GTMOS has no id for must not reach the network"
    assert [r.status for r in outcome.results] == ["failed"]
    assert "no association type for companies→tickets" in (outcome.results[0].error or "")
    assert outcome.results[0].retryable is False, "a mapping GTMOS does not have will not appear on a retry"
