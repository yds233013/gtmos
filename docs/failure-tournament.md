# Failure tournament

Every integration boundary in GTMOS was deliberately broken and the result pinned by a test. The
question was not "does the happy path work" — the rest of the suite covers that — but "when PostHog
sends the same event twice, when n8n replays a signed request an hour late, when HubSpot rate-limits a
batch halfway through, when two enrichment providers contradict each other, and when a worker dies
mid-run, what exactly happens?"

The tests are in:

* `apps/api/tests/integration/test_failure_tournament.py` — the full pipeline, against Postgres.
* `apps/api/tests/unit/test_failure_modes.py` — the boundaries that need no database: the enrichment
  waterfall's fallbacks, the merge policy's treatment of stale data, the matcher's refusal to treat
  free mail as a company, and the **real** HubSpot HTTP client's retry bound proven over a mock
  transport (the only way to prove it without a portal).

Every test name is the claim it defends, so a failure reads as "this claim stopped being true".

## The five invariants

| # | Invariant | Holds? | Asserted by name in |
|---|---|---|---|
| 1 | No duplicate revenue action (no double outreach, no double CRM write, no double signal) | **Yes** | `test_invariant_1_no_duplicate_revenue_action_a_redelivered_product_event_creates_one_signal`, `test_invariant_1_no_duplicate_revenue_action_a_replay_after_a_worker_crash_does_not_repeat_finished_steps` |
| 2 | No silent corruption | **Yes** | `test_invariant_2_no_silent_corruption_an_out_of_order_event_cannot_rewind_the_account_timeline`, `test_invariant_2_no_silent_corruption_a_failed_row_does_not_advance_its_external_record_hash` |
| 3 | No unbounded retry | **Yes** | `test_invariant_3_no_unbounded_retry_a_crm_that_always_rate_limits_is_abandoned_after_the_bounded_rounds`, `test_invariant_3_no_unbounded_retry_the_hubspot_client_stops_at_its_retry_bound` (unit, parametrized over 429/500/502/503) |
| 4 | No unsupported field overwrite | **Yes, qualified** | `test_invariant_4_no_unsupported_field_overwrite_an_inbound_crm_change_never_writes_a_gtmos_field`, `test_a_manual_lock_outranks_every_provider_however_confident` (unit) |
| 5 | No lost audit trail | **Yes** | `test_invariant_5_no_lost_audit_trail_a_sync_that_fails_still_writes_its_audit_event`, `test_invariant_5_no_lost_audit_trail_a_failed_delivery_is_stored_with_everything_needed_to_replay_it` |

Invariant 4 is marked *qualified* for an honest reason, not a technical one: nothing inbound can
overwrite a `gtmos_*` field because **nothing inbound is applied at all**. That is a strong guarantee
bought with a missing feature. See GAP-3.

## Scenario table

Correctness column: **Yes** = the behaviour is what it should be; **Acceptable** = imperfect but
defensible, with the reason given; **Gap** = a real shortcoming, numbered and described below.

### Product events (PostHog)

| Scenario | What GTMOS actually does | Correct? | Test |
|---|---|---|---|
| Duplicate event (same `uuid`) | The transport dedupes on `posthog:<uuid>`. The test defeats that on purpose with a distinct `Idempotency-Key`, so the delivery is processed a second time — and the engagement dedupe key inside `ingest_events` still yields one engagement, zero new signals, zero workflow runs. Two independent layers, both asserted. | Yes | `test_invariant_1_..._a_redelivered_product_event_creates_one_signal` |
| Out-of-order events (a later timestamp arriving first) | The older event is stored at its own `occurred_at`, but `account.last_signal_at` does not move backwards: `create_signal` only advances the high-water mark. History stays right; derived state does not regress. | Yes | `test_invariant_2_..._an_out_of_order_event_cannot_rewind_the_account_timeline` |
| Unknown account domain | No account is created. The engagement is stored unattached (`account_id` NULL) and the response carries `match: "none"` with a reason naming the domain that failed to resolve. Recorded *and* surfaced, rather than dropped. | Yes | `test_a_product_event_from_an_unknown_domain_is_recorded_and_surfaced_without_inventing_an_account` |
| Free-mail domain | Never matched. `match_to_account` drops the domain before the account lookup and says so in the reason; the lead matcher drops it as a company key entirely. No `gmail.com` account is created. | Yes | `test_a_free_mail_signup_is_never_matched_to_a_company_account`, unit `test_a_free_mail_address_is_never_matched_to_a_company` (4 providers), `test_a_free_mail_lead_with_no_company_name_is_an_unmatched_lead_not_a_guess` |
| Malformed event (missing field, wrong types, 5 000-character event name) | Nothing is written — the processor runs inside a savepoint that rolls back — and the error says `invalid PostHog payload: N validation error(s)`, and the HTTP status is **422** with the delivery stored as `rejected`. | **Gap 1, fixed** | `test_a_malformed_product_event_is_recorded_as_failed_with_a_useful_error_and_writes_nothing` (4 shapes), plus `test_a_malformed_product_event_is_answered_with_a_4xx` |
| Enormous body (1.1 MB) | Refused with 413 in the route, before the JSON parser and before any row is stored. | Yes | `test_an_oversized_delivery_is_refused_before_it_is_parsed_or_stored` |

### Transport (n8n and the shared signature path)

| Scenario | What GTMOS actually does | Correct? | Test |
|---|---|---|---|
| Bad signature | 401. No signal is created. The attempt is still stored as `rejected` with `signature check failed: …`, so a forged delivery is visible rather than invisible. | Yes | `test_a_request_with_a_bad_signature_is_rejected_with_401_and_changes_no_state` |
| Signed request replayed outside the window | 401, with `timestamp outside 5-minute window (possible replay)` on the stored record. A control test posts the same body signed *now* and gets 200, so the rejection is provably about the clock and not the payload. | Yes | `test_a_signed_request_replayed_outside_the_timestamp_window_is_rejected`, `test_a_request_signed_inside_the_window_is_accepted_so_the_rejection_above_is_about_the_clock` |
| Valid signature, unparseable body | 400. The event is stored with `signature_status: valid`, `status: rejected`, `error: body is not valid JSON` and a correlation id — the audit trail is complete. It is **not** replayable: `replay()` accepts only `failed`/`dead_letter`, so the endpoint answers 409. | Acceptable (see note) | `test_a_validly_signed_but_unparseable_body_is_stored_with_its_reason_and_refused_for_replay` |
| Valid signature, body that fails *processing* | 202, stored as `failed` with the cause. Replaying it after the cause is removed (here: the missing account appears) succeeds and bumps `attempts` to 2. This is the replayable half of the pair above. | Yes | `test_a_signed_request_whose_processor_fails_is_replayable_and_succeeds_on_the_second_attempt` |
| The same signal on two different deliveries | Both deliveries are genuinely processed (the bodies differ, so the transport key differs), and `source_ref` collapses them to one `Signal`; the second response reports `created: false` with the same signal id. | Yes | `test_the_same_signal_arriving_on_two_different_deliveries_is_stored_once` |
| One bad item in a signal batch | The whole batch rolls back to its savepoint: no half-applied batch, and the full payload is kept for replay. The error names the validation problem but not the index. | **Gap 4** | `test_one_bad_item_in_a_signal_batch_rolls_back_the_whole_batch_and_keeps_it_replayable` |

> **Why "unparseable body is not replayable" is acceptable.** A body that is not JSON will not become
> JSON on a second attempt, so a replay could only fail again. The cost is that "signed but corrupt"
> deliveries do not appear in the replay queue an operator works from — they appear in the event list
> as `rejected`, which is the right place for them. This is a deliberate line, not an oversight, and
> the test says so in its name.

### HubSpot — outbound (reverse ETL)

| Scenario | What GTMOS actually does | Correct? | Test |
|---|---|---|---|
| 429 on every row | Three rounds (`crm_sync.MAX_RETRY_ROUNDS`), then stop. The sync is `failed`, `retries` counts the re-attempted rows, and each error carries `retryable: true` **and** `note: "gave up after 3 attempts"` — reported, not retried forever. | Yes | `test_invariant_3_..._a_crm_that_always_rate_limits_is_abandoned_after_the_bounded_rounds` |
| 500 on every row | Identical bound and identical reporting; a 5xx is classified retryable exactly like a 429. | Yes | `test_a_server_error_is_bounded_by_the_same_rounds_as_a_rate_limit` |
| 400 (permanent) | One attempt, no retry, `retryable: false`. Retrying a bad property only burns rate limit and delays the report. | Yes | `test_a_permanent_error_is_not_retried_even_once` |
| HTTP-level retry inside the real adapter | `RealHubSpotAdapter._post` attempts exactly `max_retries` times, sleeps between attempts with doubling backoff and never after the last one, and honours a `Retry-After` header over its own guess. Proven over `httpx.MockTransport` for 429/500/502/503. | Yes | unit `test_invariant_3_..._the_hubspot_client_stops_at_its_retry_bound`, `test_a_retry_after_header_is_honoured_rather_than_the_clients_own_backoff` |
| **Partial** batch success | Round one carries both rows; round two carries **only** the row that failed. The row that already landed is never re-sent — no double CRM write. | Yes | `test_a_partial_batch_keeps_its_successes_and_retries_only_the_rows_that_failed` |
| External record hash on a failed row | Not advanced. The failed row keeps its previous `last_payload_hash` and `last_payload`, so the next run still sees it as changed. If the hash advanced, change detection would skip the record forever and the sync would report success over a permanently stale CRM record. | Yes | `test_invariant_2_..._a_failed_row_does_not_advance_its_external_record_hash` |
| Unknown association pair | No network call at all; every pair comes back `failed` with `no association type for companies→tickets` and `retryable: false`. | Yes | unit `test_an_unknown_association_pair_fails_every_row_with_a_reason_instead_of_reaching_the_network` |
| Audit trail on a failed sync | The `integration.synced` audit event is written whether the sync succeeded, partially succeeded or failed, with the counts, the actor (`hubspot_adapter`) and the correlation id. | Yes | `test_invariant_5_..._a_sync_that_fails_still_writes_its_audit_event` |

### HubSpot — inbound webhooks

| Scenario | What GTMOS actually does | Correct? | Test |
|---|---|---|---|
| Delivered twice / batch redelivered with a different `attemptNumber` and a different member order | One stored event. The idempotency key is built from the sorted member event ids, so the attempt counter and the ordering are both irrelevant; `duplicate_count` becomes 1 and `attempts` stays 1. | Yes | `test_a_hubspot_batch_redelivered_with_a_different_attempt_number_is_still_one_event` (and the pre-existing `test_webhook_dedupe.py`) |
| Inbound change to a `gtmos_*` property | Received, verified, stored verbatim and acknowledged 200 — and **applied: 0**. The account's `icp_score`, `score_grade`, `intent_score` and `name` are untouched. | Yes, qualified | `test_invariant_4_..._an_inbound_crm_change_never_writes_a_gtmos_field` |
| Webhooks arriving out of order | Neither one is applied, so the later state cannot be clobbered by the earlier one. Both deliveries survive as separate records. This is the honest answer: the question cannot arise today. | **Gap 3** | `test_out_of_order_hubspot_webhooks_cannot_clobber_state_because_inbound_changes_are_not_applied` |

### Clay and enrichment

| Scenario | What GTMOS actually does | Correct? | Test |
|---|---|---|---|
| Two providers conflict with a stored value | The incumbent value stays. Clay's 0.95 would beat a stored 0.80 on confidence alone, but a second Clay provider contradicting both makes the disagreement material, so the decision becomes `conflict`: the field is reported under `conflicted`, the provenance row records every losing value and who said it, and `data_quality.rule_provider_conflict` raises it for a human. Never a silent overwrite. | Yes | `test_two_providers_contradicting_a_stored_value_keep_it_and_record_the_conflict`, unit `test_two_providers_that_disagree_materially_keep_the_stored_value_and_raise_a_conflict` |
| Partial enrichment | The cells that resolved are applied; `errored`, `pending` and uncoercible cells are skipped **by name and with a reason** (`errored`, `pending`, `expected a number`) and the fields they would have written are left exactly as they were. | Yes | `test_a_partially_resolved_clay_row_applies_what_arrived_and_leaves_the_rest_untouched` |
| Provider timeout | The waterfall falls through to the next provider for that field, the timeout is recorded as an `error` attempt (so provider health is measurable), and the dead provider is not called again in the same run. If *every* provider times out the field is `no_data` — left empty rather than guessed — and an existing value is kept, never blanked. | Yes | unit `test_a_provider_timeout_makes_the_waterfall_fall_through_to_the_next_provider`, `test_every_provider_timing_out_leaves_the_field_empty_rather_than_guessed_at`, `test_a_provider_timeout_never_erases_a_value_we_already_had` |
| Stale enrichment | Flagged, not trusted. Two mechanisms: `data_quality.rule_stale_enrichment` raises an issue naming the age and suggesting the fix, and the merge policy lets an equally confident fresh value replace a value older than 180 days (while refusing to replace a current one). A value with no observation date counts as stale rather than as trusted. | Yes | `test_a_stale_enrichment_is_flagged_for_review_rather_than_silently_trusted`, unit `test_a_stale_value_is_replaced_by_an_equally_confident_fresh_one_but_a_current_value_is_not`, `test_a_value_with_no_observation_date_counts_as_stale_rather_than_as_trusted` |
| Manual lock vs a very confident provider | The lock wins at any confidence. A human's answer is not a confidence score. | Yes | unit `test_a_manual_lock_outranks_every_provider_however_confident` |

### Workflow engine and the worker

| Scenario | What GTMOS actually does | Correct? | Test |
|---|---|---|---|
| Worker crash mid-run, then replay | The run is left `running` with the dead step still `pending` — nothing falsely marks it done. On resume, the steps that already succeeded are skipped: the routing step is not re-run, and the task the rep can see stays a single row with the same id. Only the step that died runs again. | Yes | `test_invariant_1_..._a_replay_after_a_worker_crash_does_not_repeat_finished_steps` |
| Two workers on one run | The second worker's `SELECT … FOR UPDATE SKIP LOCKED` claim returns nothing, so it returns the run untouched and executes no action. The test holds a real row lock on one connection and runs the second worker on another, then asserts zero handler calls. | Yes | `test_a_second_worker_handed_a_run_another_worker_holds_is_a_no_op` (and the thread-race version in `test_workflow_hardening.py`) |

## Gaps

### GAP-1 — a permanently invalid payload was answered 202, not 4xx · **fixed**

**What it was.** `_process` caught *every* processor exception and classified it as a processing
failure: `status = "failed"` (or `dead_letter` once `attempts >= MAX_ATTEMPTS`), and `_finish` mapped
anything that was not `processed` to HTTP 202. A payload that failed schema validation therefore got
the same answer as a payload that hit a transient database error: "accepted, we will retry". A sender
with retry logic would re-send a body that can never succeed — three times, until it dead-lettered —
and an operator looking at the replay queue saw deliveries that were not worth replaying. Nothing was
ever written, so it was a reporting bug rather than a correctness bug, but it was the one place in the
tournament where the observed behaviour was worse than the specified behaviour.

**The fix, as shipped.** `webhook_service` now defines `PermanentError`. `_process` sets
`status = "rejected"` for it — never `failed`, never retried — and `_finish` returns **422**.
`_posthog_processor` and `_signal_processor` in `api/routes/integrations.py` raise it where they
previously raised `ValueError`. The distinction the endpoint now makes is between "try again" and
"this will never work", which it could not make before.

**What the fix cost, and it is worth recording.** Three existing tests had pinned the buggy behaviour
by asserting 202, and had to be updated. A suite can encode a bug as a guarantee, and the only thing
that catches that is deciding what *should* happen before reading what does.

**Pinned by.** `test_a_malformed_product_event_is_answered_with_a_4xx` asserts 422 and that the stored
delivery is `rejected`; the companion case asserts that a *transient* failure still answers 202, so the
two paths cannot be collapsed again.

### GAP-2 — `rejected` deliveries are outside the replay path

`webhook_service.replay` (line 229) accepts only `failed` and `dead_letter`. Deliveries rejected for a
bad signature or an unparseable body are stored in full but cannot be replayed, so an operator who
fixes a sender's signing key has to ask the sender to re-send rather than replaying what GTMOS already
holds. This is defensible for an unparseable body (see the note above) and defensible-but-inconvenient
for a signature that has since been corrected. Not fixed; recorded so that it is a decision rather
than an accident. Pinned by
`test_a_validly_signed_but_unparseable_body_is_stored_with_its_reason_and_refused_for_replay`.

### GAP-3 — inbound CRM changes are recorded but never applied

`apps/api/src/gtmos/api/routes/integrations.py`, `webhook_hubspot` (the inline `process`): every
inbound HubSpot property change is stored and acknowledged with `applied: 0`. Two consequences, and
they point in opposite directions:

* It is why invariant 4 holds absolutely — no inbound write can touch a `gtmos_*` field, because there
  are no inbound writes.
* It is also why webhook ordering is currently a non-question, and a legitimate rep edit in HubSpot
  never reaches GTMOS.

If inbound apply is ever built, `occurredAt` has to become a write guard (last-writer-wins by event
time, not by arrival time), `gtmos_*` properties have to stay on a deny list, and the test
`test_out_of_order_hubspot_webhooks_cannot_clobber_state_because_inbound_changes_are_not_applied` has
to be replaced rather than amended — its name would become a lie. `hubspot` is also absent from the
replay processor map (`integrations.py` line 371), which is consistent with there being nothing to
replay.

### GAP-4 — a bad item fails its whole signal batch, and the error does not say which item

`_signal_processor` in `apps/api/src/gtmos/api/routes/integrations.py` validates items in a loop and
raises on the first failure; the savepoint in `_process` then rolls back the items that had already
been written. All-or-nothing is the safe direction — there is no half-applied batch and the delivery
stays replayable in full — but the error reads `invalid signal: <message>` with no index, so an
operator replaying a 50-item batch has to find the offender by hand. A one-line fix (include the
index and the item's `source_ref` in the message) would remove the sharp edge without changing the
semantics. Pinned by
`test_one_bad_item_in_a_signal_batch_rolls_back_the_whole_batch_and_keeps_it_replayable`.

## Running it

The shared `gtmos_test` database deadlocks under concurrent runs, because the two-worker test needs
real committed rows on two connections. Run the tournament against a database of its own:

```bash
docker exec gtmos-db-1 psql -U gtmos -d postgres -c "CREATE DATABASE gtmos_fail OWNER gtmos;"
cd apps/api && ANTHROPIC_API_KEY= LLM_ENABLED=false HUBSPOT_LIVE_WRITES_ENABLED=false ENV=development \
  TEST_DATABASE_URL="postgresql+psycopg://gtmos:gtmos@localhost:56432/gtmos_fail" \
  uv run pytest tests/integration/test_failure_tournament.py tests/unit/test_failure_modes.py -q
```

No test in either file makes a network call or reads `ANTHROPIC_API_KEY`. The only HTTP client that
appears is `httpx.MockTransport`.
