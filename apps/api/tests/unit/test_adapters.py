"""Live-adapter contracts, verified with httpx.MockTransport (no network, no credentials)."""

from __future__ import annotations

import json
import time
import uuid

import httpx

from gtmos.domain.enrichment import ProviderError
from gtmos.integrations.enrichment_providers import ApolloOrganizationProvider
from gtmos.integrations.hubspot import BATCH_LIMIT, RealHubSpotAdapter, UpsertRecord, chunks
from gtmos.integrations.signatures import (
    hubspot_v3_signature,
    sign_gtmos,
    verify_gtmos,
    verify_hubspot_v3,
    verify_token,
)


def _records(n: int) -> list[UpsertRecord]:
    return [UpsertRecord(uuid.uuid4(), f"acct-{i}", {"name": f"Co {i}", "gtmos_icp_score": i}) for i in range(n)]


def test_hubspot_batch_upsert_request_shape_and_batching():
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/crm/v3/objects/companies/batch/upsert"
        assert req.headers["Authorization"] == "Bearer test-token"
        body = json.loads(req.content)
        seen.append(body)
        assert len(body["inputs"]) <= BATCH_LIMIT
        results = [
            {"id": str(1000 + i), "new": i % 2 == 0, "properties": {"gtmos_account_id": inp["id"]}}
            for i, inp in enumerate(body["inputs"])
        ]
        return httpx.Response(200, json={"status": "COMPLETE", "results": results})

    client = httpx.Client(base_url="https://api.hubapi.com", transport=httpx.MockTransport(handler))
    adapter = RealHubSpotAdapter("test-token", client=client, sleep=lambda s: None)
    out = adapter.upsert("companies", _records(230))
    assert out.http_calls == 3 and len(seen) == 3  # 100 + 100 + 30
    first = seen[0]["inputs"][0]
    assert first["idProperty"] == "gtmos_account_id"
    assert first["properties"]["gtmos_account_id"] == first["id"]  # unique key also written as a property
    assert {r.status for r in out.results} == {"created", "updated"}
    assert all(r.external_id for r in out.results)


def test_hubspot_retries_429_using_retry_after_then_succeeds():
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "3"}, json={"message": "rate limited"})
        body = json.loads(req.content)
        return httpx.Response(
            200, json={"results": [{"id": "1", "properties": {"gtmos_account_id": body["inputs"][0]["id"]}}]}
        )

    client = httpx.Client(base_url="https://api.hubapi.com", transport=httpx.MockTransport(handler))
    out = RealHubSpotAdapter("t", client=client, sleep=sleeps.append).upsert("companies", _records(1))
    assert calls["n"] == 2 and sleeps == [3.0]
    assert out.results[0].status == "updated"


def test_hubspot_partial_failure_and_non_retryable_errors():
    def partial(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        ok = body["inputs"][0]
        return httpx.Response(
            207,
            json={
                "results": [{"id": "9", "properties": {"gtmos_account_id": ok["id"]}}],
                "errors": [{"message": "Property values were not valid"}],
            },
        )

    client = httpx.Client(base_url="https://api.hubapi.com", transport=httpx.MockTransport(partial))
    out = RealHubSpotAdapter("t", client=client, sleep=lambda s: None).upsert("companies", _records(2))
    assert [r.status for r in out.results] == ["updated", "failed"]
    assert "not valid" in (out.results[1].error or "")

    def bad_request(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "idProperty must be unique"})

    client = httpx.Client(base_url="https://api.hubapi.com", transport=httpx.MockTransport(bad_request))
    out = RealHubSpotAdapter("t", client=client, sleep=lambda s: None).upsert("companies", _records(1))
    assert out.results[0].status == "failed" and out.results[0].retryable is False

    def down(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = httpx.Client(base_url="https://api.hubapi.com", transport=httpx.MockTransport(down))
    out = RealHubSpotAdapter("t", client=client, max_retries=2, sleep=lambda s: None).upsert("companies", _records(1))
    assert out.results[0].retryable is True  # surfaced to the sync job, which retries in later rounds


def test_chunking():
    assert [len(c) for c in chunks(list(range(250)))] == [100, 100, 50]


def test_apollo_adapter_maps_fields_and_errors():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["domain"] == "acme.example"
        assert req.headers["X-Api-Key"] == "k"
        return httpx.Response(
            200,
            json={
                "organization": {
                    "industry": "computer software",
                    "estimated_num_employees": 420,
                    "city": "Austin",
                    "current_technologies": [{"name": "Snowflake"}, {"name": "OpenAI"}],
                }
            },
        )

    p = ApolloOrganizationProvider("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    got = p.lookup("acme.example", ["industry", "employee_count", "technologies", "founded_year"])
    assert got["employee_count"].value == 420
    assert got["technologies"].value == ["Snowflake", "OpenAI"]
    assert "founded_year" not in got  # missing data is a miss, not a fabricated value

    for status in (429, 500):
        p = ApolloOrganizationProvider(
            "k", client=httpx.Client(transport=httpx.MockTransport(lambda r, s=status: httpx.Response(s)))
        )
        try:
            p.lookup("acme.example", ["industry"])
            raise AssertionError("expected ProviderError")
        except ProviderError:
            pass
    p = ApolloOrganizationProvider(
        "k", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    )
    assert p.lookup("acme.example", ["industry"]) == {}


def test_gtmos_signature_roundtrip_and_replay_window():
    body = b'{"a":1}'
    ts = str(int(time.time()))
    sig = sign_gtmos("s", ts, body)
    assert verify_gtmos("s", ts, sig, body) == (True, "valid")
    assert verify_gtmos("s", ts, sig, b'{"a":2}')[0] is False
    assert verify_gtmos("wrong", ts, sig, body)[0] is False
    old = str(int(time.time()) - 600)
    assert "window" in verify_gtmos("s", old, sign_gtmos("s", old, body), body)[1]
    assert verify_gtmos("s", None, None, body) == (False, "missing signature headers")
    assert verify_token("s", "s")[0] and not verify_token("s", "x")[0]


def test_hubspot_v3_signature_verification():
    secret, body, uri = "client-secret", b'[{"eventId":1}]', "https://gtmos.example/api/v1/webhooks/hubspot"
    ts = str(int(time.time() * 1000))
    sig = hubspot_v3_signature(secret, "POST", uri, body, ts)
    assert verify_hubspot_v3(secret, "POST", uri, body, sig, ts) == (True, "valid")
    assert verify_hubspot_v3(secret, "POST", uri, body + b" ", sig, ts)[0] is False
    stale = str(int((time.time() - 600) * 1000))
    assert (
        verify_hubspot_v3(secret, "POST", uri, body, hubspot_v3_signature(secret, "POST", uri, body, stale), stale)[1]
        == "timestamp older than 5 minutes"
    )


def test_hubspot_v3_rejects_future_timestamps():
    secret, body, uri = "s", b"[]", "https://gtmos.example/api/v1/webhooks/hubspot"
    future = str(int((time.time() + 600) * 1000))
    sig = hubspot_v3_signature(secret, "POST", uri, body, future)
    assert verify_hubspot_v3(secret, "POST", uri, body, sig, future) == (False, "timestamp is in the future")
