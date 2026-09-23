"""The Clay boundary, proven without a Clay account.

No Clay workspace exists and no network call is made anywhere in this file. Inbound behaviour is
proven against the documented signature scheme and the payload contract GTMOS publishes in
`docs/clay-live-setup.md`; the outbound client is proven against Clay's documented Public API with
`httpx.MockTransport`, the same way the HubSpot and Apollo adapters are.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from gtmos.integrations.clay import (
    API_KEY_HEADER,
    CLAY_API_BASE,
    ClayClient,
    ClayNotConfigured,
    ClayQuotaExceeded,
    ClayRateLimited,
    clay_signature,
    verify_clay,
)
from gtmos.models import Account, Contact, FieldProvenance
from gtmos.services import clay_service
from gtmos.services.clay_service import CLAY_DEFAULT_CONFIDENCE, ClayRow, parse_row

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


# Signature verification ------------------------------------------------------------------------------


def test_a_correctly_signed_clay_delivery_verifies():
    body = b'{"clay_row_id":"row_1","domain":"acme.example"}'
    ok, why = verify_clay("signing-secret", clay_signature("signing-secret", body), body)
    assert ok is True
    # Clay sends no timestamp header, so the detail must say the signature carries no replay window —
    # the Operations page shows this, and pretending otherwise would overstate the guarantee.
    assert "replay" in why


def test_a_tampered_body_fails_verification():
    body = b'{"employee_count":400}'
    signature = clay_signature("signing-secret", body)
    assert verify_clay("signing-secret", signature, b'{"employee_count":40000}')[0] is False
    assert verify_clay("wrong-secret", signature, body) == (False, "signature mismatch")


def test_a_missing_signature_header_fails_verification():
    assert verify_clay("s", None, b"{}") == (False, "missing X-Clay-Signature header")
    assert verify_clay("s", "", b"{}")[0] is False


def test_a_bare_hex_signature_is_accepted_but_a_wrong_one_is_not():
    """Clay documents the `sha256=` prefix; hand-rolled test senders routinely omit it."""
    body = b"{}"
    prefixed = clay_signature("s", body)
    assert verify_clay("s", prefixed.split("=", 1)[1], body)[0] is True
    assert verify_clay("s", "deadbeef", body)[0] is False


# Field mapping ---------------------------------------------------------------------------------------


def _flat_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "clay_row_id": "row_abc",
        "clay_run_id": "run_xyz",
        "clay_table_id": "t_1",
        "observed_at": "2026-09-22T11:00:00Z",
        "Company Domain": "https://www.Acme-AI.example/careers",
        "Company Name": "Acme AI, Inc.",
        "Industry": "AI/ML Platforms",
        "Employee Count": "1,250",
        "Total Funding": "$120000000",
        "Tech Stack": "Snowflake, OpenAI, dbt",
        "Headcount Growth": "35%",
        "Country": "us",
        "Work Email": "Dana.Reyes@Acme-AI.example",
        "Job Title": "VP of Machine Learning",
        "Seniority": "VP",
    }
    row.update(overrides)
    return row


def _by_field(cells: list[Any]) -> dict[str, Any]:
    return {c.field: c for c in cells}


def test_clay_column_names_map_onto_gtmos_fields_and_are_coerced():
    row = parse_row(_flat_row())
    account = _by_field(row.account)
    assert account["domain"].value == "acme-ai.example"  # url, www and path stripped
    assert account["employee_count"].value == 1250  # thousands separator
    assert account["total_funding_usd"].value == 120_000_000  # currency symbol
    assert account["technologies"].value == ["Snowflake", "OpenAI", "dbt"]  # comma string → list
    assert account["employee_growth_12m"].value == pytest.approx(0.35)  # percent → fraction
    assert account["country"].value == "US"
    contact = _by_field(row.contact)
    assert contact["email"].value == "dana.reyes@acme-ai.example"  # lowercased
    assert contact["title"].value == "VP of Machine Learning"
    assert contact["seniority"].value == "vp"
    assert (row.row_id, row.run_id, row.table_id) == ("row_abc", "run_xyz", "t_1")


def test_the_nested_account_contact_shape_parses_the_same_way():
    row = parse_row(
        {
            "clay_row_id": "row_1",
            "account": {"domain": "acme.example", "Employee Count": 300},
            "contact": {"email": "a@acme.example", "First Name": "Ada"},
        }
    )
    assert _by_field(row.account)["employee_count"].value == 300
    assert _by_field(row.contact)["first_name"].value == "Ada"


def test_columns_gtmos_does_not_know_are_reported_rather_than_dropped_silently():
    row = parse_row(_flat_row(**{"Claygent Summary": "a paragraph of AI prose", "Weird Column": 1}))
    assert row.unmapped == ["claygent_summary", "weird_column"]
    # Envelope keys are not columns and must not be reported as mistakes.
    assert "clay_row_id" not in row.unmapped and "observed_at" not in row.unmapped


def test_a_value_that_cannot_be_coerced_is_skipped_with_a_reason_not_guessed_at():
    row = parse_row(_flat_row(**{"Employee Count": "about a thousand", "Country": "United States"}))
    reasons = {s["field"]: s["reason"] for s in row.skipped}
    assert reasons["employee_count"] == "expected a number"
    assert "alpha-2" in reasons["country"]
    assert "employee_count" not in _by_field(row.account)


def test_the_waterfall_provider_is_carried_into_the_source_only_when_clay_emits_it():
    row = parse_row(
        {
            "clay_row_id": "r",
            "domain": "acme.example",
            "industry": {"value": "AI/ML Platforms", "provider": "clearbit", "confidence": 0.9},
            "city": "Austin",
        }
    )
    cells = _by_field(row.account)
    assert cells["industry"].source == "clay:clearbit"
    assert cells["industry"].confidence == 0.9
    # Naming a provider is opt-in configuration in Clay. Without it we say `clay` and nothing more.
    assert cells["city"].source == "clay" and cells["city"].confidence is None


def test_a_cell_timestamp_falls_back_to_the_envelope_rather_than_being_invented():
    row = parse_row(
        {
            "clay_row_id": "r",
            "observed_at": "2026-09-01T00:00:00Z",
            "industry": {"value": "Fintech", "observed_at": "2026-08-01T00:00:00Z"},
            "city": "Austin",
        }
    )
    cells = _by_field(row.account)
    assert cells["industry"].observed_at == datetime(2026, 8, 1, tzinfo=UTC)
    assert cells["city"].observed_at == datetime(2026, 9, 1, tzinfo=UTC)


# Partial enrichment ----------------------------------------------------------------------------------


def test_unresolved_cells_are_skipped_and_the_rest_of_the_row_still_parses():
    """A completed Clay run can contain failed items; five empty columns must not cost us three good ones."""
    row = parse_row(
        {
            "clay_row_id": "row_partial",
            "domain": "acme.example",
            "industry": "AI/ML Platforms",
            "employee_count": {"value": None, "status": "empty"},
            "city": {"value": None, "status": "pending"},
            "founded_year": {"value": None, "status": "errored"},
            "total_funding_usd": "",
        }
    )
    assert _by_field(row.account)["industry"].value == "AI/ML Platforms"
    assert {s["field"]: s["reason"] for s in row.skipped} == {
        "employee_count": "empty",
        "city": "pending",
        "founded_year": "errored",
        "total_funding_usd": "empty",
    }


def test_an_errored_cell_that_still_carries_a_value_is_not_trusted():
    row = parse_row({"clay_row_id": "r", "employee_count": {"value": 9999, "status": "errored"}})
    assert row.account == []
    assert row.skipped == [{"entity": "account", "field": "employee_count", "reason": "errored"}]


def test_clays_own_run_notification_is_recognised_as_a_notification_not_a_record():
    row = parse_row(
        {"webhookId": "wh_abc123", "createdAt": "2026-06-16T17:50:00.000Z", "data": {"routine_run_id": "run_abc123"}}
    )
    assert row.is_notification is True
    assert row.routine_run_id == "run_abc123"


def test_a_non_object_body_is_rejected_before_anything_is_written():
    with pytest.raises(ValueError):
        parse_row([{"domain": "acme.example"}])


# Idempotency -----------------------------------------------------------------------------------------


def test_the_idempotency_key_is_the_clay_row_and_run_identifier():
    key = clay_service.idempotency_key(parse_row(_flat_row()))
    assert key == "clay:run_xyz:row_abc"
    assert key == clay_service.idempotency_key(parse_row(_flat_row(**{"Employee Count": 1251})))
    assert clay_service.idempotency_key(parse_row(_flat_row(clay_run_id="run_2"))) != key


def test_a_run_notification_is_keyed_on_the_routine_run():
    row = parse_row({"webhookId": "wh_1", "data": {"routine_run_id": "run_abc123"}})
    assert clay_service.idempotency_key(row) == "clay:run:run_abc123"


def test_a_row_with_no_clay_identifier_gets_no_key_and_falls_back_to_the_pipeline_hash():
    assert clay_service.idempotency_key(parse_row({"domain": "acme.example"})) is None


# Merge policy: provenance, locks and conflicts --------------------------------------------------------


class _Session:
    """Just enough Session for `_merge`: it reads provenance, adds rows and flushes. No database."""

    def __init__(self, provenance: list[FieldProvenance] | None = None) -> None:
        self.rows: list[Any] = list(provenance or [])

    def scalars(self, _statement: Any) -> list[Any]:
        return [r for r in self.rows if isinstance(r, FieldProvenance)]

    def add(self, obj: Any) -> None:
        self.rows.append(obj)

    def flush(self) -> None:
        pass

    def provenance(self) -> dict[str, FieldProvenance]:
        return {r.field: r for r in self.rows if isinstance(r, FieldProvenance)}


def _provenance(field: str, value: Any, *, source: str, confidence: float, lock: bool = False) -> FieldProvenance:
    return FieldProvenance(
        workspace_id=uuid.uuid4(),
        entity_type="account",
        entity_id=uuid.uuid4(),
        field=field,
        value=value,
        source=source,
        confidence=confidence,
        observed_at=NOW - timedelta(days=5),
        is_manual_lock=lock,
    )


def _merge(account: Account, payload: dict[str, Any], provenance: list[FieldProvenance] | None = None):
    db = _Session(provenance)
    row = parse_row({"clay_row_id": "r", **payload})
    result = clay_service._merge(db, uuid.uuid4(), account, "account", row.account, NOW)
    return result, db.provenance()


def test_clay_filling_an_empty_field_records_clay_as_the_source_and_when_it_was_observed():
    account = Account(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name="Acme", domain="acme.example")
    result, prov = _merge(
        account,
        {"observed_at": "2026-09-20T00:00:00Z", "industry": {"value": "AI/ML Platforms", "provider": "clearbit"}},
    )
    assert account.industry == "AI/ML Platforms"
    assert result["outcome"]["set"] == ["industry"]
    assert prov["industry"].source == "clay:clearbit"
    assert prov["industry"].observed_at == datetime(2026, 9, 20, tzinfo=UTC)
    # Clay publishes no confidence, so the one recorded is GTMOS's stated policy, not a Clay number.
    assert prov["industry"].confidence == CLAY_DEFAULT_CONFIDENCE


def test_clay_never_overwrites_a_manually_locked_field():
    account = Account(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name="Acme", industry="Data Infrastructure")
    lock = _provenance("industry", "Data Infrastructure", source="manual", confidence=1.0, lock=True)
    result, prov = _merge(account, {"industry": {"value": "Martech", "confidence": 0.99}}, [lock])
    assert account.industry == "Data Infrastructure"
    assert result["outcome"]["kept"] == ["industry"]
    assert prov["industry"].source == "manual"


def test_a_material_disagreement_with_a_confident_value_raises_a_conflict_instead_of_overwriting():
    account = Account(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name="Acme", industry="Data Infrastructure")
    incumbent = _provenance("industry", "Data Infrastructure", source="demo_firmographics", confidence=0.7)
    result, prov = _merge(account, {"industry": {"value": "Martech", "confidence": 0.9}}, [incumbent])
    assert account.industry == "Data Infrastructure", "a contested value must not win on confidence alone"
    assert result["outcome"]["conflicted"] == ["industry"]
    conflict = prov["industry"].conflict
    assert conflict["material"] is True
    assert {o["provider"] for o in conflict["others"]} == {"demo_firmographics"}
    # `chosen_value` is the answer the merge would have taken before materiality overruled it, exactly
    # as provider enrichment records it. The value actually held is the account's, and it did not move.
    assert conflict["chosen_value"] == "Martech"


def test_clay_wins_outright_when_the_value_it_contradicts_was_never_confident():
    account = Account(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name="Acme", industry="Martech")
    weak = _provenance("industry", "Martech", source="crm", confidence=0.4)
    result, prov = _merge(account, {"industry": {"value": "AI/ML Platforms", "confidence": 0.9}}, [weak])
    assert account.industry == "AI/ML Platforms"
    assert result["outcome"]["updated"] == ["industry"]
    assert prov["industry"].source == "clay"
    # The value that lost is still recorded: an overwritten field must not look unanimous afterwards.
    assert prov["industry"].conflict["others"][0]["value"] == "Martech"


def test_a_waterfall_step_that_lost_inside_clay_is_carried_through_as_a_disagreement():
    account = Account(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name="Acme")
    _, prov = _merge(
        account,
        {
            "employee_count": {
                "value": 1200,
                "provider": "clearbit",
                "confidence": 0.9,
                "others": [{"provider": "apollo", "value": 300, "confidence": 0.8}],
            }
        },
    )
    assert account.employee_count == 1200
    conflict = prov["employee_count"].conflict
    assert conflict["material"] is True and conflict["others"][0]["provider"] == "clay:apollo"


def test_clay_confirming_an_existing_value_raises_nothing_and_keeps_the_original_source():
    account = Account(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name="Acme", employee_count=1200)
    incumbent = _provenance("employee_count", 1200, source="demo_firmographics", confidence=0.7)
    result, prov = _merge(account, {"employee_count": 1200}, [incumbent])
    assert result["outcome"]["kept"] == ["employee_count"]
    assert prov["employee_count"].conflict is None
    assert prov["employee_count"].source == "demo_firmographics"


def test_a_headcount_within_measurement_noise_is_not_treated_as_a_disagreement():
    account = Account(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name="Acme", employee_count=1200)
    incumbent = _provenance("employee_count", 1200, source="demo_firmographics", confidence=0.5)
    _, prov = _merge(account, {"employee_count": {"value": 1280, "confidence": 0.9}}, [incumbent])
    assert account.employee_count == 1280
    assert prov["employee_count"].conflict is None


def test_a_partial_row_writes_the_fields_that_resolved_and_leaves_the_rest_alone():
    account = Account(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name="Acme", city="Austin")
    result, prov = _merge(
        account,
        {"industry": "AI/ML Platforms", "employee_count": {"value": None, "status": "errored"}, "city": ""},
    )
    assert account.industry == "AI/ML Platforms" and account.city == "Austin"
    assert result["outcome"]["set"] == ["industry"]
    assert set(prov) == {"industry"}


def test_a_contact_row_merges_through_the_same_policy():
    contact = Contact(id=uuid.uuid4(), workspace_id=uuid.uuid4(), email="dana@acme.example", title="Engineer")
    db = _Session([])
    row = parse_row({"clay_row_id": "r", "contact": {"title": "VP of ML", "Email Verification": "valid"}})
    clay_service._merge(db, uuid.uuid4(), contact, "contact", row.contact, NOW)
    prov = db.provenance()
    # A title nobody ever attributed is a weak incumbent, so Clay replaces it — and the replaced value
    # is kept as a disagreement rather than disappearing.
    assert contact.title == "VP of ML"
    assert prov["title"].entity_type == "contact" and prov["title"].source == "clay"
    assert prov["title"].conflict["others"][0]["value"] == "Engineer"
    assert contact.email_status == "valid"


# Outbound client -------------------------------------------------------------------------------------


def _client(handler, **kwargs: Any) -> ClayClient:
    transport = httpx.MockTransport(handler)
    return ClayClient("k", client=httpx.Client(transport=transport), sleep=lambda s: None, **kwargs)


def test_the_clay_client_is_inert_without_an_api_key():
    """Demo mode sets no key, so the client cannot reach Clay even if something tries to call it."""
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, json={})

    client = ClayClient(None, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.enabled is False and client.mode == "disabled"
    for call in (client.me, client.credits, lambda: client.run_results("run_1")):
        with pytest.raises(ClayNotConfigured):
            call()
    with pytest.raises(ClayNotConfigured):
        client.run_routine("routine_1", [{"domain": "acme.example"}])
    assert calls == [], "an unconfigured client must not make a request at all"


def test_the_clay_client_sends_the_documented_header_and_paths():
    seen: list[tuple[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers[API_KEY_HEADER] == "k"
        assert str(req.url).startswith(CLAY_API_BASE)
        seen.append((req.method, req.url.path))
        if req.url.path.endswith("/me"):
            return httpx.Response(200, json={"user": {"email": "a@b.example"}, "workspace": {"id": "ws_1"}})
        return httpx.Response(200, json={"data_credits": 100, "actions": 500})

    client = _client(handler)
    assert client.me()["workspace"]["id"] == "ws_1"
    assert client.credits()["data_credits"] == 100
    assert seen == [("GET", "/public/v0/me"), ("GET", "/public/v0/credits")]


def test_dispatching_a_routine_posts_the_items_and_returns_the_run_id():
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/public/v0/routines/routine_1/run"
        captured.update(json.loads(req.content))
        return httpx.Response(200, json={"routine_run_id": "run_abc123"})

    run_id = _client(handler).run_routine("routine_1", [{"domain": "acme.example"}], webhook_id="wh_abc123")
    assert run_id == "run_abc123"
    # Passing the webhook id is what makes this notify-then-pull rather than a polling loop.
    assert captured == {"items": [{"domain": "acme.example"}], "webhook_id": "wh_abc123"}


def test_a_routine_run_refuses_more_items_than_clay_accepts_inline():
    with pytest.raises(ValueError):
        _client(lambda r: httpx.Response(200, json={})).run_routine("r", [{"i": i} for i in range(101)])
    with pytest.raises(ValueError):
        _client(lambda r: httpx.Response(200, json={})).run_routine("r", [])


def test_results_report_progress_while_running_and_items_when_complete():
    responses = [
        httpx.Response(202, json={"status": "running", "total": 10, "finished": 4}),
        httpx.Response(
            200,
            json={
                "status": "complete",
                "total": 2,
                "finished": 2,
                "results": [{"status": "success", "value": "acme.example"}, {"status": "failed"}],
            },
        ),
    ]
    client = _client(lambda req: responses.pop(0))
    run = client.wait_for_results("run_abc123", poll_interval=0)
    assert run.running is False and run.succeeded is True
    # A completed run can contain failed items; only per-item status shows it.
    assert len(run.failed_items) == 1


def test_an_unrecognized_terminal_status_is_flagged_rather_than_assumed_successful():
    """Clay warns that the set of terminal statuses is not closed."""
    run = _client(lambda req: httpx.Response(200, json={"status": "quarantined"})).run_results("run_1")
    assert run.recognized is False and run.succeeded is False


def test_rate_limiting_backs_off_on_retry_after_and_then_gives_up_with_the_header_intact():
    sleeps: list[float] = []
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, json={"message": "rate limited"})
        return httpx.Response(200, json={"workspace": {"id": "ws_1"}})

    client = ClayClient("k", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append)
    assert client.me()["workspace"]["id"] == "ws_1"
    assert sleeps == [7.0]

    always = ClayClient(
        "k",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "11"}))
        ),
        sleep=lambda s: None,
        max_retries=2,
    )
    with pytest.raises(ClayRateLimited) as caught:
        always.me()
    assert caught.value.retry_after == 11.0


def test_a_plan_limit_is_a_distinct_failure_from_a_rate_limit():
    """Clay answers 402 naming the limit hit, and there is nothing to retry."""
    handler = lambda req: httpx.Response(402, json={"message": "search result limit reached"})  # noqa: E731
    with pytest.raises(ClayQuotaExceeded, match="search result limit"):
        _client(handler).me()


def test_a_server_error_is_retried_and_the_thin_clay_error_body_is_surfaced():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={"message": "upstream unavailable"})

    from gtmos.integrations.clay import ClayError

    with pytest.raises(ClayError, match="upstream unavailable"):
        _client(handler, max_retries=3).me()
    assert calls["n"] == 3


def test_from_settings_builds_a_disabled_client_in_demo_mode():
    from gtmos.config import Settings

    assert ClayClient.from_settings(Settings(clay_api_key=None)).enabled is False
    assert ClayClient.from_settings(Settings(clay_api_key="k")).enabled is True


def test_the_published_contract_lists_every_column_the_parser_understands():
    """The Clay table is configured by hand against this list, so it must not drift from the parser."""
    row: ClayRow = parse_row({"clay_row_id": "r", **dict.fromkeys(clay_service.ACCOUNT_FIELDS, "x")})
    assert row.unmapped == []
