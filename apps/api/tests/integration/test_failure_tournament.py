"""The failure tournament: break every integration on purpose and pin what GTMOS does about it.

The question this file answers is not "does the happy path work" — the rest of the suite covers that —
but "when PostHog sends the same event twice, when n8n replays a signed request an hour late, when
HubSpot rate-limits a batch halfway through, when two enrichment providers contradict each other and
when a worker dies mid-run, what exactly happens?" Every test asserts the *specific* safe behaviour.
"nothing raised" is not an assertion, because an integration that silently drops a revenue signal
raises nothing either.

Five invariants are asserted by name, each in a test called `test_invariant_N_...`:

1. No duplicate revenue action  — no double outreach, no double CRM write, no double signal.
2. No silent corruption         — a late or contested value never rewrites good state unannounced.
3. No unbounded retry           — every retry loop has a bound and reports when it hits it.
4. No unsupported field overwrite — inbound data never writes a field GTMOS owns, or a human locked.
5. No lost audit trail          — every failure leaves a stored, inspectable, attributable record.

`docs/failure-tournament.md` is the scenario table this file implements, including the places where
the behaviour is imperfect but defensible, and the four numbered gaps (GAP-1 to GAP-4) where it is
not. GAP-1 was the only one that was a bug rather than a scoped-out feature, and it has been fixed:
a permanently invalid payload now answers 422 with the delivery stored as `rejected`, instead of 202
with a retry queued behind it. GAP-2 to GAP-4 remain open and scoped, and each says why.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from gtmos.config import get_settings
from gtmos.domain.signals import signal_dedupe_key
from gtmos.domain.workflows import WorkflowDefinition
from gtmos.integrations.clay import clay_signature
from gtmos.integrations.hubspot import BatchOutcome, UpsertRecord, UpsertResult
from gtmos.integrations.signatures import hubspot_v3_signature, sign_gtmos
from gtmos.models import (
    Account,
    Activity,
    AuditEvent,
    Engagement,
    ExternalRecord,
    FieldProvenance,
    Signal,
    WebhookEvent,
    Workflow,
    WorkflowRun,
    WorkflowStepRun,
)
from gtmos.services import crm_sync, data_quality, workflow_engine
from gtmos.services.common import utcnow

GTMOS_SECRET = "tournament-webhook-secret"
HUBSPOT_SECRET = "tournament-hubspot-secret"
CLAY_SECRET = "tournament-clay-secret"


# --------------------------------------------------------------------------------------------------
# Fixtures and helpers
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def gtmos_secret(monkeypatch):  # type: ignore[no-untyped-def]
    """A configured WEBHOOK_SECRET, so the signature path is exercised rather than the dev bypass."""
    monkeypatch.setenv("WEBHOOK_SECRET", GTMOS_SECRET)
    get_settings.cache_clear()
    yield GTMOS_SECRET
    monkeypatch.delenv("WEBHOOK_SECRET")
    get_settings.cache_clear()


@pytest.fixture
def hubspot_secret(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("HUBSPOT_WEBHOOK_CLIENT_SECRET", HUBSPOT_SECRET)
    get_settings.cache_clear()
    yield HUBSPOT_SECRET
    monkeypatch.delenv("HUBSPOT_WEBHOOK_CLIENT_SECRET")
    get_settings.cache_clear()


@pytest.fixture
def clay_secret(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLAY_WEBHOOK_SECRET", CLAY_SECRET)
    get_settings.cache_clear()
    yield CLAY_SECRET
    monkeypatch.delenv("CLAY_WEBHOOK_SECRET")
    get_settings.cache_clear()


def _event(
    name: str, domain: str, *, at: datetime | None = None, event_uuid: str | None = None, email: str | None = None
) -> dict[str, Any]:
    """A PostHog-shaped capture payload for one product event."""
    occurred = at or utcnow()
    return {
        "event": name,
        "distinct_id": email or f"user.{uuid.uuid4().hex[:8]}@{domain}",
        "timestamp": occurred.isoformat(),
        "uuid": event_uuid or str(uuid.uuid4()),
        "properties": {"$groups": {"company": domain}, "email": email} if email else {"$groups": {"company": domain}},
    }


def _post_event(client, payload: dict[str, Any], *, idempotency: str | None = None):  # type: ignore[no-untyped-def]
    headers = {"content-type": "application/json"}
    if idempotency:
        # Forces a second *delivery* of the same event past the transport-level dedupe, so the test
        # measures the domain layer's own protection rather than the webhook table's.
        headers["Idempotency-Key"] = idempotency
    return client.post("/api/v1/webhooks/posthog", content=json.dumps(payload).encode(), headers=headers)


def _signed(secret: str, body: bytes, *, skew_seconds: int = 0) -> dict[str, str]:
    ts = str(int(time.time()) + skew_seconds)
    return {
        "content-type": "application/json",
        "X-GTMOS-Timestamp": ts,
        "X-GTMOS-Signature": sign_gtmos(secret, ts, body),
    }


def _n8n_signal(domain: str, **overrides: Any) -> dict[str, Any]:
    payload = {
        "account_domain": domain,
        "signal_type": "job_posting",
        "title": "Hiring an ML platform lead",
        "explanation": "A job posting picked up by an n8n scraper node.",
        "source": "n8n",
        "source_ref": f"n8n-{uuid.uuid4().hex[:12]}",
    }
    payload.update(overrides)
    return payload


def _hubspot_batch(attempt: int, event_ids: list[int], *, property_name: str = "name") -> list[dict[str, Any]]:
    return [
        {
            "eventId": eid,
            "subscriptionId": 2_000_001,
            "portalId": 12_345_678,
            "occurredAt": 1_767_225_600_000 + eid,
            "subscriptionType": "company.propertyChange",
            "attemptNumber": attempt,
            "objectId": 7_000 + eid,
            "propertyName": property_name,
            "propertyValue": f"value-{eid}",
        }
        for eid in event_ids
    ]


def _post_hubspot(client, secret: str, body: bytes):  # type: ignore[no-untyped-def]
    ts = str(int(time.time() * 1000))
    url = "http://testserver/api/v1/webhooks/hubspot"
    return client.post(
        "/api/v1/webhooks/hubspot",
        content=body,
        headers={
            "content-type": "application/json",
            "X-HubSpot-Request-Timestamp": ts,
            "X-HubSpot-Signature-v3": hubspot_v3_signature(secret, "POST", url, body, ts),
        },
    )


def _post_clay(client, payload: dict[str, Any], *, secret: str = CLAY_SECRET):  # type: ignore[no-untyped-def]
    body = json.dumps(payload).encode()
    return client.post(
        "/api/v1/webhooks/clay",
        content=body,
        headers={"content-type": "application/json", "X-Clay-Signature": clay_signature(secret, body)},
    )


def _engagements(db: Session, dedupe_key: str) -> int:
    return db.scalar(select(func.count()).select_from(Engagement).where(Engagement.dedupe_key == dedupe_key)) or 0


# --------------------------------------------------------------------------------------------------
# Product events (PostHog)
# --------------------------------------------------------------------------------------------------


def test_invariant_1_no_duplicate_revenue_action_a_redelivered_product_event_creates_one_signal(
    client, db, ws, flagship
):
    """The same PostHog event delivered twice must produce one engagement, one signal, one play.

    Two layers have to hold for this, and the test defeats the first on purpose: the `Idempotency-Key`
    header makes the second delivery a *new* webhook event, so the only thing standing between the
    account and a duplicate signal is the engagement dedupe key inside `ingest_events`.
    """
    payload = _event("workspace_created", flagship.domain)
    dedupe = f"posthog:{payload['uuid']}"

    first = _post_event(client, payload, idempotency=f"delivery-a-{uuid.uuid4().hex[:8]}")
    assert first.status_code == 200, first.text
    assert first.json()["result"]["events"] == 1
    signals_after_first = first.json()["result"]["signals_created"]
    runs_after_first = first.json()["result"]["workflow_runs"]

    second = _post_event(client, payload, idempotency=f"delivery-b-{uuid.uuid4().hex[:8]}")

    assert second.status_code == 200, second.text
    assert second.json()["duplicate"] is False, "the transport was deliberately bypassed for this test"
    result = second.json()["result"]
    assert result["results"][0]["duplicate"] is True, "the event itself must be recognised as already seen"
    assert result["signals_created"] == 0, "a redelivered event must not create a second signal"
    assert result["workflow_runs"] == [], "and must not start a second play"
    assert signals_after_first >= 0 and runs_after_first is not None

    db.expire_all()
    assert _engagements(db, dedupe) == 1, "one real-world event is one engagement, however often it arrives"


def test_invariant_2_no_silent_corruption_an_out_of_order_event_cannot_rewind_the_account_timeline(
    client, db, ws, flagship
):
    """A late-arriving older event is recorded at its own timestamp but never rewinds derived state."""
    recent = utcnow() - timedelta(hours=1)
    older = utcnow() - timedelta(days=9)

    newer_first = _post_event(client, _event("integration_connected", flagship.domain, at=recent))
    assert newer_first.status_code == 200, newer_first.text
    db.expire_all()
    account = db.get(Account, flagship.id)
    assert account is not None
    high_water_mark = account.last_signal_at
    assert high_water_mark is not None and high_water_mark >= recent - timedelta(seconds=5)

    late = _post_event(client, _event("teammate_invited", flagship.domain, at=older))
    assert late.status_code == 200, late.text

    db.expire_all()
    account = db.get(Account, flagship.id)
    assert account is not None
    assert account.last_signal_at == high_water_mark, "an older event must not rewind `last_signal_at`"
    # The late event is not discarded either: it is stored with its real timestamp, so the history is
    # right even though the derived high-water mark did not move.
    stored = db.scalars(
        select(Engagement)
        .where(Engagement.account_id == flagship.id, Engagement.event_name == "teammate_invited")
        .order_by(Engagement.occurred_at.asc())
    ).all()
    assert any(abs((e.occurred_at - older).total_seconds()) < 5 for e in stored)


def test_a_product_event_from_an_unknown_domain_is_recorded_and_surfaced_without_inventing_an_account(client, db, ws):
    """The costly failure here is not the dropped event, it is the junk account a guess would create."""
    unknown = f"never-heard-of-{uuid.uuid4().hex[:8]}.example"

    payload = _event("workspace_created", unknown)

    response = _post_event(client, payload)

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["matched"] == 0
    entry = result["results"][0]
    assert entry["match"] == "none" and entry["account_id"] is None
    assert unknown in entry["match_reason"], "the response must name the domain that could not be resolved"

    db.expire_all()
    assert db.scalars(select(Account).where(Account.domain == unknown)).first() is None, (
        "an unresolvable product event must never conjure an account"
    )
    # Dropped silently would mean no row at all. The engagement is stored unattached, which is what
    # makes an unmatched-traffic report possible at all.
    orphan = db.scalars(select(Engagement).where(Engagement.dedupe_key == f"posthog:{payload['uuid']}")).one()
    assert orphan.account_id is None and orphan.distinct_id == payload["distinct_id"]
    assert orphan.source == "posthog", "an unmatched product event is kept, attributable to where it came from"


def test_a_free_mail_signup_is_never_matched_to_a_company_account(client, db, ws):
    payload = _event("workspace_created", "gmail.com", email="someone.personal@gmail.com")
    payload["properties"].pop("$groups")

    response = _post_event(client, payload)

    assert response.status_code == 200, response.text
    entry = response.json()["result"]["results"][0]
    assert entry["account_id"] is None
    assert "free-mail" in entry["match_reason"]
    db.expire_all()
    assert db.scalars(select(Account).where(Account.domain == "gmail.com")).first() is None


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ({"distinct_id": "nobody@kestrel.example"}, "no event name at all"),
        ({"event": "", "distinct_id": "x"}, "an empty event name"),
        ({"event": 17, "properties": "not-an-object"}, "wrong types throughout"),
        ({"event": "x" * 5000, "distinct_id": "y"}, "an event name far past the column width"),
    ],
)
def test_a_malformed_product_event_is_recorded_as_failed_with_a_useful_error_and_writes_nothing(
    client, db, ws, payload: dict[str, Any], why: str
):
    """Nothing is written, the reason is legible, and the sender is told to stop rather than retry.

    A schema violation can never succeed, so answering 202 ("accepted, will retry") makes a well-behaved
    sender redeliver a body that is structurally wrong — HubSpot retries ten times over 24 hours. The
    processor raises `PermanentError`, which maps to `rejected` and 422.
    """
    before = db.scalar(select(func.count()).select_from(Engagement)) or 0

    response = _post_event(client, payload)

    assert response.status_code == 422, f"{why}: {response.text}"
    body = response.json()
    assert body["status"] == "rejected"
    assert "invalid PostHog payload" in (body["error"] or ""), "the error must say what was wrong, not just fail"
    db.expire_all()
    assert (db.scalar(select(func.count()).select_from(Engagement)) or 0) == before, (
        "a payload that did not validate must leave no engagement behind"
    )
    stored = db.scalars(select(WebhookEvent).where(WebhookEvent.id == uuid.UUID(body["id"]))).one()
    assert stored.status == "rejected" and stored.error


def test_a_malformed_product_event_is_answered_with_a_4xx(client, db, ws):
    response = _post_event(client, {"event": "", "distinct_id": "x"})
    assert 400 <= response.status_code < 500


def test_an_oversized_delivery_is_refused_before_it_is_parsed_or_stored(client, db, ws):
    """The body cap is checked in the route, so an enormous payload never reaches the JSON parser."""
    before = db.scalar(select(func.count()).select_from(WebhookEvent)) or 0

    response = client.post(
        "/api/v1/webhooks/posthog",
        content=b'{"event": "workspace_created", "properties": {"note": "' + b"x" * 1_100_000 + b'"}}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    db.expire_all()
    assert (db.scalar(select(func.count()).select_from(WebhookEvent)) or 0) == before


# --------------------------------------------------------------------------------------------------
# Transport: n8n and the shared signature path
# --------------------------------------------------------------------------------------------------


def test_a_request_with_a_bad_signature_is_rejected_with_401_and_changes_no_state(
    client, db, ws, flagship, gtmos_secret
):
    payload = _n8n_signal(flagship.domain)
    body = json.dumps(payload).encode()
    headers = _signed("the-wrong-secret", body)

    response = client.post("/api/v1/webhooks/n8n", content=body, headers=headers)

    assert response.status_code == 401
    assert response.json()["signature"] == "invalid"
    db.expire_all()
    key = signal_dedupe_key("job_posting", flagship.domain, payload["source_ref"])
    assert db.scalars(select(Signal).where(Signal.dedupe_key == key)).first() is None, (
        "a forged delivery must not create a signal"
    )
    # Invariant 5: rejected is not the same as unrecorded. The attempt is stored with its reason.
    stored = db.scalars(select(WebhookEvent).where(WebhookEvent.id == uuid.UUID(response.json()["id"]))).one()
    assert stored.status == "rejected"
    assert "signature check failed" in (stored.error or "")


def test_a_signed_request_replayed_outside_the_timestamp_window_is_rejected(client, db, ws, flagship, gtmos_secret):
    """A valid signature captured an hour ago is still a valid signature; the window is what stops it."""
    payload = _n8n_signal(flagship.domain)
    body = json.dumps(payload).encode()
    headers = _signed(gtmos_secret, body, skew_seconds=-3600)

    response = client.post("/api/v1/webhooks/n8n", content=body, headers=headers)

    assert response.status_code == 401
    stored = db.scalars(select(WebhookEvent).where(WebhookEvent.id == uuid.UUID(response.json()["id"]))).one()
    assert "5-minute window" in (stored.error or ""), "the rejection must name the replay window"
    key = signal_dedupe_key("job_posting", flagship.domain, payload["source_ref"])
    assert db.scalars(select(Signal).where(Signal.dedupe_key == key)).first() is None


def test_a_request_signed_inside_the_window_is_accepted_so_the_rejection_above_is_about_the_clock(
    client, db, ws, flagship, gtmos_secret
):
    """The control for the replay test: same body, same secret, current timestamp."""
    body = json.dumps(_n8n_signal(flagship.domain)).encode()

    response = client.post("/api/v1/webhooks/n8n", content=body, headers=_signed(gtmos_secret, body))

    assert response.status_code == 200, response.text
    assert response.json()["signature"] == "valid"


def test_a_validly_signed_but_unparseable_body_is_stored_with_its_reason_and_refused_for_replay(
    client, db, ws, gtmos_secret
):
    """Documented behaviour, not the expected one: the event is `rejected` (400), so it is not replayable.

    A body that is not JSON cannot become JSON on a second attempt, so refusing the replay is defensible
    — but it does mean "signed, unparseable" is not in the replay queue an operator works from. The
    record is kept in full, which is what invariant 5 requires.
    """
    body = b'{"account_domain": "kestrel.example", "signal_type":'  # truncated mid-object

    response = client.post("/api/v1/webhooks/n8n", content=body, headers=_signed(gtmos_secret, body))

    assert response.status_code == 400
    event_id = uuid.UUID(response.json()["id"])
    stored = db.scalars(select(WebhookEvent).where(WebhookEvent.id == event_id)).one()
    assert stored.signature_status == "valid", "the signature verified; only the body did not parse"
    assert stored.status == "rejected" and stored.error == "body is not valid JSON"
    assert stored.correlation_id, "a stored failure with no correlation id is an unusable audit record"

    replay = client.post(f"/api/v1/webhooks/events/{event_id}/replay")
    assert replay.status_code == 409, "a rejected event is not replayable; the test pins that, not an ideal"
    assert "only failed or dead-lettered" in replay.json()["detail"]


def test_a_signed_request_whose_processor_fails_is_replayable_and_succeeds_on_the_second_attempt(
    client, db, ws, flagship, gtmos_secret
):
    """The counterpart: a *processing* failure keeps the payload and can be replayed once the cause is gone."""
    payload = _n8n_signal(f"missing-{uuid.uuid4().hex[:8]}.example")
    body = json.dumps(payload).encode()

    response = client.post("/api/v1/webhooks/n8n", content=body, headers=_signed(gtmos_secret, body))

    assert response.status_code == 202, response.text
    event_id = uuid.UUID(response.json()["id"])
    stored = db.scalars(select(WebhookEvent).where(WebhookEvent.id == event_id)).one()
    assert stored.status == "failed" and "no account with domain" in (stored.error or "")

    # The account appears (a rep created it, or a sync landed). The stored delivery now works.
    db.add(
        Account(
            workspace_id=ws.id,
            name="Late Arrival",
            domain=payload["account_domain"],
            source="test",
            data_origin="live",
        )
    )
    db.flush()

    replay = client.post(f"/api/v1/webhooks/events/{event_id}/replay")

    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "processed"
    assert replay.json()["attempts"] == 2, "a replay is an attempt, and the count is the audit trail"


def test_the_same_signal_arriving_on_two_different_deliveries_is_stored_once(client, db, ws, flagship, gtmos_secret):
    """Invariant 1 again, on the n8n path: the real-world event is the identity, not the HTTP request.

    The two bodies differ (a re-scrape produced a longer title), so the transport-level idempotency key
    differs too and both deliveries are processed. `source_ref` is what makes them one signal.
    """
    payload = _n8n_signal(flagship.domain)
    first_body = json.dumps(payload).encode()
    second_body = json.dumps({**payload, "title": "Hiring an ML platform lead (re-scraped)"}).encode()

    first = client.post("/api/v1/webhooks/n8n", content=first_body, headers=_signed(gtmos_secret, first_body))
    second = client.post("/api/v1/webhooks/n8n", content=second_body, headers=_signed(gtmos_secret, second_body))

    assert first.status_code == 200 and second.status_code == 200, second.text
    assert second.json()["duplicate"] is False, "the deliveries are genuinely different requests"
    assert first.json()["result"]["signals"][0]["created"] is True
    assert second.json()["result"]["signals"][0]["created"] is False, "the second must not create a signal"
    assert second.json()["result"]["signals"][0]["signal_id"] == first.json()["result"]["signals"][0]["signal_id"]

    db.expire_all()
    key = signal_dedupe_key("job_posting", flagship.domain, payload["source_ref"])
    assert db.scalar(select(func.count()).select_from(Signal).where(Signal.dedupe_key == key)) == 1


def test_one_bad_item_in_a_signal_batch_rolls_back_the_whole_batch(client, db, ws, flagship, gtmos_secret):
    """All-or-nothing, on purpose — but the error does not say *which* item, which is a real rough edge.

    The processor runs inside a savepoint, so the good signals in the batch roll back with the bad one.
    That is the safe direction: no half-applied batch. Because the failure is a schema violation the
    delivery is *rejected*, not queued for retry — replaying it unchanged could never succeed, and
    offering an operator a replay button that cannot work is worse than not offering one. The body is
    still stored so the offending item can be found, which is why the error message matters: it names
    the validation problem but not the index, so a 50-item batch has to be searched by hand.
    """
    good = _n8n_signal(flagship.domain)
    bad = _n8n_signal(flagship.domain, title="x")  # below the 3-character floor
    body = json.dumps([good, bad]).encode()

    response = client.post("/api/v1/webhooks/n8n", content=body, headers=_signed(gtmos_secret, body))

    assert response.status_code == 422, response.text
    assert response.json()["status"] == "rejected"
    assert "invalid signal" in response.json()["error"]
    db.expire_all()
    key = signal_dedupe_key("job_posting", flagship.domain, good["source_ref"])
    assert db.scalars(select(Signal).where(Signal.dedupe_key == key)).first() is None, (
        "no signal from a batch that did not fully validate may survive"
    )
    event_id = uuid.UUID(response.json()["id"])
    assert db.get(WebhookEvent, event_id).payload["_items"][0]["source_ref"] == good["source_ref"], (
        "the whole batch is retained so the offending item can be found, even though it is not replayable"
    )


# --------------------------------------------------------------------------------------------------
# HubSpot: outbound batches
# --------------------------------------------------------------------------------------------------


class _ScriptedCrm:
    """A CRM adapter whose answer per record is scripted, so retry behaviour is observable exactly.

    `plan` maps an internal id to the list of outcomes it returns on successive rounds; the last entry
    repeats. An id with no entry always succeeds.
    """

    provider = "hubspot"
    is_simulated = True

    def __init__(self, plan: dict[uuid.UUID, list[str]]) -> None:
        self.plan = plan
        self.rounds: list[list[uuid.UUID]] = []

    def upsert(self, object_type: str, records: list[UpsertRecord]) -> BatchOutcome:
        round_no = len(self.rounds)
        self.rounds.append([r.internal_id for r in records])
        out = BatchOutcome(http_calls=1)
        for r in records:
            script = self.plan.get(r.internal_id)
            outcome = "ok" if not script else script[min(round_no, len(script) - 1)]
            if outcome == "ok":
                out.results.append(UpsertResult(r.internal_id, "updated", f"hs-{r.internal_id.hex[:10]}"))
            else:
                out.results.append(
                    UpsertResult(
                        r.internal_id,
                        "failed",
                        error=f"{outcome} Too Many Requests" if outcome == "429" else f"HTTP {outcome}",
                        retryable=outcome in ("429", "500", "503"),
                    )
                )
        return out


def _syncable(db: Session, ws: Any, count: int) -> list[Account]:
    """Accounts the company sync will consider, nudged so change detection does not skip them."""
    accounts = list(
        db.scalars(
            select(Account)
            .where(Account.workspace_id == ws.id, Account.merged_into_id.is_(None), Account.domain.is_not(None))
            .order_by(Account.created_at)
            .limit(count)
        )
    )
    assert len(accounts) == count
    for a in accounts:
        a.intent_score = (a.intent_score or 0) + 7  # changes the computed payload, so nothing is "unchanged"
    db.flush()
    return accounts


def test_invariant_3_no_unbounded_retry_a_crm_that_always_rate_limits_is_abandoned_after_the_bounded_rounds(db, ws):
    accounts = _syncable(db, ws, 2)
    adapter = _ScriptedCrm({a.id: ["429"] for a in accounts})

    sync = crm_sync.run_company_sync(db, ws.id, [a.id for a in accounts], adapter=adapter)

    assert len(adapter.rounds) == crm_sync.MAX_RETRY_ROUNDS == 3, "the retry loop must stop at its bound"
    assert sync.status == "failed" and sync.records_succeeded == 0
    assert sync.retries == 4, "two records retried in each of the two rounds after the first"
    # Reported, not retried forever: the give-up is on the record with the attempt count on it.
    assert len(sync.errors) == 2
    assert all(e["retryable"] is True and "gave up after 3 attempts" in e["note"] for e in sync.errors)


def test_a_server_error_is_bounded_by_the_same_rounds_as_a_rate_limit(db, ws):
    accounts = _syncable(db, ws, 1)
    adapter = _ScriptedCrm({accounts[0].id: ["500"]})

    sync = crm_sync.run_company_sync(db, ws.id, [a.id for a in accounts], adapter=adapter)

    assert len(adapter.rounds) == 3 and sync.status == "failed"
    assert sync.errors[0]["error"].startswith("HTTP 500")


def test_a_permanent_error_is_not_retried_even_once(db, ws):
    """A 400 on a bad property will be a 400 next time; retrying it only delays the report."""
    accounts = _syncable(db, ws, 1)
    adapter = _ScriptedCrm({accounts[0].id: ["400"]})

    sync = crm_sync.run_company_sync(db, ws.id, [a.id for a in accounts], adapter=adapter)

    assert len(adapter.rounds) == 1, "a non-retryable failure must end the loop immediately"
    assert sync.errors[0]["retryable"] is False


def test_a_partial_batch_keeps_its_successes_and_retries_only_the_rows_that_failed(db, ws):
    first, second = _syncable(db, ws, 2)
    adapter = _ScriptedCrm({second.id: ["429", "ok"]})

    sync = crm_sync.run_company_sync(db, ws.id, [first.id, second.id], adapter=adapter)

    assert [sorted(map(str, r)) for r in adapter.rounds] == [
        sorted([str(first.id), str(second.id)]),
        [str(second.id)],
    ], "the second round must carry only the row that failed, never the one that already landed"
    assert sync.status == "succeeded" and sync.records_succeeded == 2 and sync.errors == []


def test_invariant_2_no_silent_corruption_a_failed_row_does_not_advance_its_external_record_hash(db, ws):
    """Change detection must not claim a row is in sync when its write never landed.

    If the hash advanced on failure, the next run would see "unchanged" and skip the record — the row
    would be permanently stale in the CRM and the sync would report success forever.
    """
    good, doomed = _syncable(db, ws, 2)
    stale_marker = "hash-from-the-last-successful-push"
    existing = db.scalars(
        select(ExternalRecord).where(
            ExternalRecord.provider == "hubspot",
            ExternalRecord.object_type == "companies",
            ExternalRecord.internal_id == doomed.id,
        )
    ).first()
    if existing is None:
        existing = ExternalRecord(
            workspace_id=ws.id,
            provider="hubspot",
            object_type="companies",
            internal_id=doomed.id,
            external_id="hs-existing",
        )
        db.add(existing)
    existing.last_payload_hash = stale_marker
    existing.last_payload = {"gtmos_icp_score": -1}
    db.flush()

    sync = crm_sync.run_company_sync(db, ws.id, [good.id, doomed.id], adapter=_ScriptedCrm({doomed.id: ["429"]}))

    assert sync.status == "partial" and sync.records_succeeded == 1 and sync.records_failed == 1
    db.flush()
    db.refresh(existing)
    assert existing.last_payload_hash == stale_marker, "a row that never landed must still look out of date"
    assert existing.last_payload == {"gtmos_icp_score": -1}, "and must not be credited with the payload it refused"
    landed = db.scalars(
        select(ExternalRecord).where(
            ExternalRecord.provider == "hubspot",
            ExternalRecord.object_type == "companies",
            ExternalRecord.internal_id == good.id,
        )
    ).one()
    assert landed.last_payload_hash != stale_marker and landed.last_synced_at is not None


def test_invariant_5_no_lost_audit_trail_a_sync_that_fails_still_writes_its_audit_event(db, ws):
    accounts = _syncable(db, ws, 1)

    sync = crm_sync.run_company_sync(db, ws.id, [accounts[0].id], adapter=_ScriptedCrm({accounts[0].id: ["429"]}))

    assert sync.status == "failed"
    audit = db.scalars(
        select(AuditEvent).where(AuditEvent.entity_type == "integration_sync", AuditEvent.entity_id == sync.id)
    ).one()
    assert audit.action == "integration.synced"
    assert audit.after["status"] == "failed" and audit.after["failed"] == 1
    assert audit.actor_type == "integration" and audit.actor == "hubspot_adapter"
    assert sync.correlation_id, "a sync with no correlation id cannot be traced to the request that caused it"


# --------------------------------------------------------------------------------------------------
# HubSpot: inbound webhooks
# --------------------------------------------------------------------------------------------------


def test_a_hubspot_batch_redelivered_with_a_different_attempt_number_is_still_one_event(client, db, ws, hubspot_secret):
    """HubSpot retries a batch up to ten times and bumps `attemptNumber` each time."""
    eids = [int(uuid.uuid4().int % 10**9), int(uuid.uuid4().int % 10**9)]

    first = _post_hubspot(client, hubspot_secret, json.dumps(_hubspot_batch(0, eids)).encode())
    assert first.status_code == 200 and first.json()["duplicate"] is False

    # Same events, later attempt, and HubSpot does not promise batch order either.
    second = _post_hubspot(client, hubspot_secret, json.dumps(_hubspot_batch(6, list(reversed(eids)))).encode())

    assert second.status_code == 200, second.text
    assert second.json()["duplicate"] is True and second.json()["id"] == first.json()["id"]
    db.expire_all()
    events = db.scalars(select(WebhookEvent).where(WebhookEvent.id == uuid.UUID(first.json()["id"]))).one()
    assert events.duplicate_count == 1 and events.attempts == 1


def test_invariant_4_no_unsupported_field_overwrite_an_inbound_crm_change_never_writes_a_gtmos_field(
    client, db, ws, flagship, hubspot_secret
):
    """A rep (or a HubSpot workflow) editing `gtmos_icp_score` in the portal must not reach the model.

    GTMOS computes those properties; the CRM is a display surface for them. The webhook is acknowledged
    and recorded — the change is not lost — but nothing is applied.
    """
    before = (flagship.icp_score, flagship.score_grade, flagship.intent_score, flagship.name)
    body = json.dumps(
        [
            {
                "eventId": int(uuid.uuid4().int % 10**9),
                "subscriptionType": "company.propertyChange",
                "attemptNumber": 0,
                "objectId": 9_001,
                "propertyName": "gtmos_icp_score",
                "propertyValue": "1",
            }
        ]
    ).encode()

    response = _post_hubspot(client, hubspot_secret, body)

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["received"] == 1 and result["applied"] == 0
    assert "never overwritten" in result["note"]
    db.expire_all()
    account = db.get(Account, flagship.id)
    assert account is not None
    assert (account.icp_score, account.score_grade, account.intent_score, account.name) == before
    stored = db.scalars(select(WebhookEvent).where(WebhookEvent.id == uuid.UUID(response.json()["id"]))).one()
    assert stored.status == "processed", "refusing to apply a change is not the same as failing to receive it"
    assert stored.payload["_items"][0]["propertyName"] == "gtmos_icp_score", "the attempt is kept verbatim"


def test_out_of_order_hubspot_webhooks_cannot_clobber_state_because_inbound_changes_are_not_applied(
    client, db, ws, flagship, hubspot_secret
):
    """The honest answer to "does a stale webhook overwrite a newer one": the question cannot arise.

    GTMOS records inbound CRM property changes and applies none of them, so ordering is irrelevant to
    correctness today. That is a real limitation — it also means a legitimate rep edit is not ingested
    — and it is the reason this test asserts what the system does rather than what a bidirectional
    sync would have to do. If inbound apply is ever built, `occurredAt` must become a write guard and
    this test must be replaced by a last-writer-wins one.
    """
    newer = _hubspot_batch(0, [int(uuid.uuid4().int % 10**9)])
    newer[0]["occurredAt"] = 1_800_000_000_000
    newer[0]["propertyValue"] = "Renamed Second"
    older = _hubspot_batch(0, [int(uuid.uuid4().int % 10**9)])
    older[0]["occurredAt"] = 1_700_000_000_000
    older[0]["propertyValue"] = "Renamed First"
    name_before = flagship.name

    assert _post_hubspot(client, hubspot_secret, json.dumps(newer).encode()).status_code == 200
    late = _post_hubspot(client, hubspot_secret, json.dumps(older).encode())

    assert late.status_code == 200, late.text
    assert late.json()["result"]["applied"] == 0
    db.expire_all()
    account = db.get(Account, flagship.id)
    assert account is not None and account.name == name_before
    # Both deliveries survive independently, so an operator can still see the order they arrived in.
    stored = db.scalars(
        select(WebhookEvent).where(WebhookEvent.source == "hubspot", WebhookEvent.workspace_id == ws.id)
    ).all()
    assert len({e.id for e in stored}) >= 2


# --------------------------------------------------------------------------------------------------
# Clay / enrichment
# --------------------------------------------------------------------------------------------------


def _clay_account(db: Session, ws: Any, **fields: Any) -> Account:
    account = Account(
        workspace_id=ws.id,
        name="Tournament Target",
        domain=f"tournament-{uuid.uuid4().hex[:8]}.example",
        source="test",
        data_origin="live",
        **fields,
    )
    db.add(account)
    db.flush()
    return account


def _provenance(db: Session, ws: Any, account: Account, field: str, value: Any, confidence: float) -> FieldProvenance:
    row = FieldProvenance(
        workspace_id=ws.id,
        entity_type="account",
        entity_id=account.id,
        field=field,
        value=value,
        source="demo_firmographics",
        confidence=confidence,
        observed_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def test_two_providers_contradicting_a_stored_value_keep_it_and_record_the_conflict(client, db, ws, clay_secret):
    """Clay is confident enough to win on confidence alone — and is refused anyway, because it has company.

    The setup matters: at 0.95 against a stored 0.80 the merge policy would normally update the field.
    What stops it is the second Clay provider contradicting *both* of them. Two sources that disagree
    materially do not get to resolve a field between themselves; the incumbent stays and a human is asked.
    """
    account = _clay_account(db, ws, industry="AI/ML Platforms", employee_count=240)
    _provenance(db, ws, account, "industry", "AI/ML Platforms", 0.8)

    response = _post_clay(
        client,
        {
            "clay_row_id": f"row_{uuid.uuid4().hex[:10]}",
            "clay_run_id": "run_tournament",
            "Company Domain": account.domain,
            "Industry": {
                "value": "Fintech",
                "provider": "clearbit",
                "confidence": 0.95,
                "others": [{"provider": "apollo", "value": "Logistics", "confidence": 0.9}],
            },
        },
    )

    assert response.status_code == 200, response.text
    fields = response.json()["result"]["account"]["fields"]
    assert fields["conflicted"] == ["industry"], "a contested field is neither written nor quietly dropped"
    assert "industry" not in fields["updated"] and "industry" not in fields["set"]
    reported = response.json()["result"]["account"]["conflicts"]
    assert [c["field"] for c in reported] == ["industry"], "the response itself must carry the disagreement"

    db.expire_all()
    account = db.get(Account, account.id)
    assert account is not None and account.industry == "AI/ML Platforms", "the stored value survives the dispute"
    row = db.scalars(
        select(FieldProvenance).where(FieldProvenance.entity_id == account.id, FieldProvenance.field == "industry")
    ).one()
    assert row.conflict is not None and row.conflict["material"] is True
    said = {o["provider"]: o["value"] for o in row.conflict["others"]}
    assert said.get("clay:apollo") == "Logistics", "the losing third opinion must remain visible"
    assert "demo_firmographics" in said or row.conflict["chosen_value"] == "AI/ML Platforms"
    flagged = data_quality.rule_provider_conflict(db, ws.id, utcnow())
    assert any(c.entity_id == account.id and c.details["field"] == "industry" for c in flagged), (
        "a material conflict must reach the data-quality queue, not only a provenance row"
    )


def test_a_partially_resolved_clay_row_applies_what_arrived_and_leaves_the_rest_untouched(client, db, ws, clay_secret):
    """A completed Clay run with failed cells is a partial success, not a failed delivery."""
    account = _clay_account(db, ws, city="Reykjavik", employee_count=240)

    response = _post_clay(
        client,
        {
            "clay_row_id": f"row_{uuid.uuid4().hex[:10]}",
            "Company Domain": account.domain,
            "Sub Industry": {"value": "LLM Observability", "provider": "clearbit", "confidence": 0.88},
            "Employee Count": {"value": None, "status": "errored"},
            "City": {"value": "Lisbon", "status": "pending"},
            "Total Funding": {"value": "not a number"},
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["account"]["fields"]["set"] == ["sub_industry"]
    reasons = {s["field"]: s["reason"] for s in result["skipped_fields"]}
    assert reasons["employee_count"] == "errored"
    assert reasons["city"] == "pending"
    assert reasons["total_funding_usd"] == "expected a number", "a value we cannot coerce is named, never guessed"

    db.expire_all()
    account = db.get(Account, account.id)
    assert account is not None
    assert account.sub_industry == "LLM Observability"
    assert account.city == "Reykjavik" and account.employee_count == 240, "unresolved cells touch nothing"


def test_a_stale_enrichment_is_flagged_for_review_rather_than_silently_trusted(db, ws):
    account = _clay_account(db, ws, score_grade="A", icp_score=88)
    account.last_enriched_at = utcnow() - timedelta(days=400)
    db.flush()

    candidates = data_quality.rule_stale_enrichment(db, ws.id, utcnow())

    stale = [c for c in candidates if c.entity_id == account.id]
    assert stale, "an account last enriched over a year ago must surface as a data-quality issue"
    assert "400 days ago" in stale[0].title, "the issue must say how stale, so a human can judge it"
    assert stale[0].suggested_fix["action"] == "enrich_account", "flagged with a fix, not just a complaint"


# --------------------------------------------------------------------------------------------------
# Workflow engine and the worker
# --------------------------------------------------------------------------------------------------


def _counting(counter: Counter[str], name: str) -> workflow_engine.ActionFn:
    def handler(db: Session, run: WorkflowRun, account: Account, params: dict[str, Any]) -> dict[str, Any]:
        counter[name] += 1
        return {"handled": name}

    return handler


def _tasks_for(db: Session, run: WorkflowRun) -> int:
    return (
        db.scalar(select(func.count()).select_from(Activity).where(Activity.dedupe_key.like(f"task:{run.id}:%"))) or 0
    )


def _steps(db: Session, run: WorkflowRun) -> dict[str, WorkflowStepRun]:
    rows = db.scalars(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id).order_by(WorkflowStepRun.position)
    )
    return {s.step_key: s for s in rows}


def test_invariant_1_no_duplicate_revenue_action_a_replay_after_a_worker_crash_does_not_repeat_finished_steps(
    db, ws, flagship, monkeypatch
):
    """The crash is the interesting part: the run is left `running` with no terminal status.

    A resumed run must re-enter at the step that died. Anything else means the account is routed twice
    or the rep gets two tasks for the same signal, which is the most expensive class of bug here
    because it is invisible in the logs and visible to the customer.
    """
    calls = Counter[str]()
    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "route_account", _counting(calls, "route"))

    def killed(db_: Session, run: WorkflowRun, account: Account, params: dict[str, Any]) -> dict[str, Any]:
        calls["crm"] += 1
        raise SystemExit("the worker process was killed here (test)")

    # `create_task` is left as the real handler on purpose: it is the step with a side effect a rep can
    # see, so "did it run twice" is answered by counting rows rather than by counting calls.
    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "sync_crm", killed)
    wf = db.scalars(
        select(Workflow).where(Workflow.workspace_id == ws.id, Workflow.key == "score-threshold-routing")
    ).one()
    definition = WorkflowDefinition.model_validate(wf.definition)
    ctx = workflow_engine._context(flagship, {"manual": {"actor": "tournament@example.com"}})
    run = workflow_engine.create_run(db, wf, definition, flagship, f"crash-{uuid.uuid4()}", "manual", ctx)
    assert run is not None

    with pytest.raises(SystemExit):
        workflow_engine.execute_run(db, run.id)

    steps = _steps(db, run)
    assert steps["route"].status == "succeeded" and steps["task"].status == "succeeded"
    assert steps["crm"].status == "pending", "the step that died must not be recorded as finished"
    assert run.status == "running", "a killed worker leaves the run non-terminal; nothing marks it done"
    task_id = steps["task"].output["task_id"]
    assert _tasks_for(db, run) == 1

    monkeypatch.setitem(workflow_engine.ACTION_HANDLERS, "sync_crm", _counting(calls, "crm_recovered"))
    resumed = workflow_engine.execute_run(db, run.id)

    assert resumed.status == "succeeded"
    assert calls["route"] == 1, "a step that already succeeded must not run a second time"
    assert calls["crm"] == 1 and calls["crm_recovered"] == 1, "the step that died runs once more, not twice"
    assert _steps(db, run)["route"].attempts == 1
    assert _tasks_for(db, run) == 1, "the rep must not get a second task for the same signal"
    assert _steps(db, run)["task"].output["task_id"] == task_id, "and it must be the same task, not a replacement"


def test_a_second_worker_handed_a_run_another_worker_holds_is_a_no_op(engine: Engine):
    """`FOR UPDATE SKIP LOCKED` makes the loser of a race do nothing, rather than duplicate every step.

    Persisted step state alone is not enough: both workers read the same `pending` rows before either
    writes. This needs two real connections, so it commits and cleans up after itself rather than using
    the rolled-back `db` fixture.
    """
    from gtmos.services.common import get_workspace

    calls = Counter[str]()

    def counted(db_: Session, run: WorkflowRun, account: Account, params: dict[str, Any]) -> dict[str, Any]:
        calls["task"] += 1
        return {"ok": True}

    with Session(engine) as setup:
        ws = get_workspace(setup)
        account = setup.scalars(
            select(Account).where(Account.workspace_id == ws.id, Account.is_flagship.is_(True))
        ).one()
        wf = Workflow(
            workspace_id=ws.id,
            key=f"tournament-lock-{uuid.uuid4().hex[:8]}",
            name="Failure tournament: contended run",
            trigger_type="manual",
            definition={
                "trigger": {"type": "manual", "filters": []},
                "conditions": [],
                "steps": [{"key": "one", "action": "create_task", "params": {"subject": "one"}}],
            },
        )
        setup.add(wf)
        setup.flush()
        definition = WorkflowDefinition.model_validate(wf.definition)
        ctx = workflow_engine._context(account, {"manual": {"actor": "tournament@example.com"}})
        run = workflow_engine.create_run(setup, wf, definition, account, f"lock-{uuid.uuid4()}", "manual", ctx)
        assert run is not None
        run_id, workflow_id = run.id, wf.id
        setup.commit()

    holder = Session(engine)
    try:
        original = workflow_engine.ACTION_HANDLERS["create_task"]
        workflow_engine.ACTION_HANDLERS["create_task"] = counted
        # Worker A takes the row lock and keeps its transaction open, exactly as it would while running.
        assert workflow_engine._claim(holder, run_id) is not None

        loser_finished = threading.Event()
        outcome: dict[str, Any] = {}

        def worker_b() -> None:
            try:
                with Session(engine) as s:
                    outcome["status"] = workflow_engine.execute_run(s, run_id).status
                    s.commit()
            except BaseException as exc:  # reported as a failure below rather than lost in a thread
                outcome["error"] = exc
            finally:
                loser_finished.set()

        thread = threading.Thread(target=worker_b)
        thread.start()
        assert loser_finished.wait(timeout=30), "the second worker blocked instead of skipping the locked row"
        thread.join(timeout=30)

        assert "error" not in outcome, outcome
        assert outcome["status"] == "queued", "the loser must return the run untouched, not execute it"
        assert calls["task"] == 0, "no action may run in a worker that did not win the claim"
    finally:
        workflow_engine.ACTION_HANDLERS["create_task"] = original
        holder.rollback()
        holder.close()
        with Session(engine) as cleanup:
            cleanup.execute(delete(WorkflowStepRun).where(WorkflowStepRun.run_id == run_id))
            cleanup.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))
            cleanup.execute(delete(AuditEvent).where(AuditEvent.entity_id == run_id))
            cleanup.execute(delete(Workflow).where(Workflow.id == workflow_id))
            cleanup.commit()


def test_invariant_5_no_lost_audit_trail_a_failed_delivery_is_stored_with_everything_needed_to_replay_it(
    client, db, ws, gtmos_secret
):
    """Whatever else fails, the delivery, its reason, its correlation id and its payload survive."""
    payload = _n8n_signal(f"nowhere-{uuid.uuid4().hex[:8]}.example")
    body = json.dumps(payload).encode()

    response = client.post("/api/v1/webhooks/n8n", content=body, headers=_signed(gtmos_secret, body))

    assert response.status_code == 202
    stored = db.scalars(select(WebhookEvent).where(WebhookEvent.id == uuid.UUID(response.json()["id"]))).one()
    assert stored.status == "failed"
    assert stored.error and stored.correlation_id and stored.received_at
    assert stored.signature_status == "valid", "who sent it is part of the record"
    assert stored.payload["source_ref"] == payload["source_ref"], "the payload is kept verbatim so replay is possible"
    assert stored.processing_ms is not None

    listed = client.get("/api/v1/webhooks/events", params={"source": "n8n", "status": "failed"})
    assert listed.status_code == 200
    assert str(stored.id) in [item["id"] for item in listed.json()["items"]], (
        "a failure an operator cannot find in the UI is a lost audit trail"
    )
