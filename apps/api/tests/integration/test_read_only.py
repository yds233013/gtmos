"""The `READ_ONLY` flag, for a publicly reachable demo instance.

Of 36 mutating routes in this API, four are genuinely gated by `require_admin` and two more by a gate
that is a no-op unless live writes are already enabled. The remaining 24 have no gate to be a no-op of.
That is fine on a laptop and not fine on a public URL, so the flag refuses every write at the edge.

These tests exist because the allow-list is the part that rots: it is three literal strings, and the
day one of those routes is renamed the demo quietly loses its only interactive surfaces with nothing
failing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gtmos.main import READ_ONLY_POST_ALLOWLIST, create_app


@pytest.fixture
def read_only_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from gtmos.config import get_settings

    monkeypatch.setenv("READ_ONLY", "true")
    get_settings.cache_clear()
    client = TestClient(create_app())
    yield client
    get_settings.cache_clear()


def test_every_allow_listed_path_still_exists(client) -> None:
    """A renamed route must break this test rather than silently disable the demo's best surfaces."""
    paths = set(client.get("/openapi.json").json()["paths"])
    missing = READ_ONLY_POST_ALLOWLIST - paths
    assert not missing, f"read-only allow-list references routes that no longer exist: {sorted(missing)}"


def test_allow_listed_paths_accept_post(client) -> None:
    """Allow-listing a path that is not a POST would be a silent no-op."""
    spec = client.get("/openapi.json").json()["paths"]
    for path in sorted(READ_ONLY_POST_ALLOWLIST):
        assert "post" in spec[path], f"{path} is allow-listed for read-only POSTs but has no POST handler"


def test_reads_are_unaffected(read_only_client: TestClient) -> None:
    assert read_only_client.get("/health/ready").status_code == 200
    assert read_only_client.get("/api/v1/accounts?limit=1").status_code == 200


def test_a_write_is_refused_with_an_explanation(read_only_client: TestClient, flagship) -> None:
    r = read_only_client.post(f"/api/v1/accounts/{flagship.id}/rescore")
    assert r.status_code == 403
    body = r.json()["error"]
    # The message has to tell a visitor what to do instead, or it reads as a broken demo.
    assert "read-only demo" in body
    assert "make up" in body


def test_the_webhook_paths_are_refused_too(read_only_client: TestClient) -> None:
    """Covered by the method check without being named, which is the reason this is a middleware."""
    r = read_only_client.post("/api/v1/webhooks/posthog", json={"event": "x", "distinct_id": "y"})
    assert r.status_code == 403


def test_an_allow_listed_post_still_works(read_only_client: TestClient) -> None:
    r = read_only_client.post("/api/v1/routing/simulate", json={"segment": "enterprise", "region": "NA"})
    assert r.status_code != 403, "the routing simulator writes nothing and must survive read-only mode"


def test_the_flag_is_off_by_default(client, flagship) -> None:
    """Local development and every other test must be untouched by this."""
    assert client.post(f"/api/v1/accounts/{flagship.id}/rescore").status_code == 200
