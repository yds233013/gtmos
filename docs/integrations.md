# GTMOS Integrations

GTMOS runs end to end with no external credentials. Each integration boundary has a demo implementation that behaves like the real one (same contract, same failure modes, clearly labeled), and where it makes sense a live implementation that a configuration switch enables. This document states which is which, what the code actually does at each boundary, and what has and has not been tested.

## Status at a glance

| Boundary | Status | Default behavior | Live behavior | Tested against the real service? |
|---|---|---|---|---|
| HubSpot outbound (reverse ETL) | **DEMO** by default, **OPTIONAL** live | `DemoHubSpotAdapter` writes to `simulated_crm_objects`; every sync is `is_simulated=true` and labeled SIMULATED | `RealHubSpotAdapter` calls CRM v3 batch upsert | **No.** Request shape, batching, 429 retry and partial failures are unit-tested with `httpx.MockTransport` only. |
| HubSpot inbound webhooks | **LIVE** endpoint (signature verification implemented) | Events stored and acknowledged | Same; changes are logged, not applied | Signature code is tested against computed vectors, not against real HubSpot deliveries. |
| PostHog product events | **LIVE** endpoint | Accepts PostHog-shaped events from any sender | Same | Payload shape follows PostHog docs; not tested with a real PostHog destination. |
| n8n | **OPTIONAL** | Templates in `integrations/n8n/` | Signed webhooks into GTMOS | Templates import cleanly into n8n; see [n8n.md](n8n.md). |
| Enrichment | **DEMO** (3 simulated providers) plus **OPTIONAL** Apollo | Simulated providers answer from the deterministic universe | Apollo organization enrichment added to the waterfall | **No.** The Apollo adapter has not been run against the live API. |
| LLM research | **DEMO** by default, **OPTIONAL** live | Deterministic generator that restates evidence | Anthropic Claude through the official SDK, structured output | Not part of the automated test suite. |
| Background jobs | **LIVE** (local infrastructure) | Inline execution | Redis + RQ worker with a Postgres sweeper | Yes, in docker compose. |
| Outbound email / sequencing | **Deliberately none** | Drafts stop at READY | n/a | n/a |

"LIVE endpoint" means the GTMOS side is real code that accepts real traffic. It does not mean a third-party account has been connected.

## Environment variables

All configuration comes from the environment (`apps/api/src/gtmos/config.py`, template in `.env.example`). Secrets are `SecretStr` and never logged or returned by the API.

| Variable | Default | Purpose |
|---|---|---|
| `ENV` | `development` | `production` makes missing webhook secrets and admin token hard failures. |
| `DATABASE_URL` | `postgresql+psycopg://gtmos:gtmos@localhost:56432/gtmos` | Postgres connection. |
| `REDIS_URL` | unset | Redis for the RQ worker. |
| `QUEUE_BACKEND` | `inline` | `inline` runs workflow runs in-process; `redis` enqueues them after commit. |
| `CORS_ORIGINS` | `localhost:3010` / `127.0.0.1:3010` | Allowed web origins (JSON list). |
| `LOG_LEVEL` | `INFO` | Log level. |
| `SEED_ACCOUNTS` | `2000` | Size of the deterministic demo universe; the simulated providers answer from the same universe. |
| `ADMIN_API_TOKEN` | unset | When set, admin endpoints and live CRM sync runs require `Authorization: Bearer <token>`. Required in production. |
| `WEBHOOK_SECRET` | unset | HMAC secret for n8n/generic webhooks and the shared token for PostHog. Required in production. |
| `ANTHROPIC_API_KEY` | unset | Anthropic API key. |
| `LLM_ENABLED` | `false` | Must also be `true` for live LLM calls. A key alone never triggers billed calls. |
| `LLM_MODEL` | `claude-opus-5` | Model used for research generation. |
| `HUBSPOT_ACCESS_TOKEN` | unset | HubSpot private-app token. |
| `HUBSPOT_LIVE_WRITES_ENABLED` | `false` | Must also be `true` before anything is written to HubSpot. |
| `HUBSPOT_WEBHOOK_CLIENT_SECRET` | unset | App client secret used to verify `X-HubSpot-Signature-v3`. |
| `APOLLO_API_KEY` | unset | Registers the Apollo enrichment adapter. |
| `OUTBOUND_SEND_ENABLED` | `false` | Documents the boundary only. No code sends email. |
| `API_INTERNAL_URL` | `http://127.0.0.1:8010` | Web app → API URL (frontend). |

The n8n templates use their own variables (`GTMOS_BASE_URL`, `GTMOS_WEBHOOK_SECRET`, `GTMOS_ADMIN_TOKEN`), documented in [n8n.md](n8n.md).

---

## HubSpot

### Object mapping

| GTMOS | HubSpot object | Upsert key (`idProperty`) |
|---|---|---|
| Account | `companies` | `gtmos_account_id` (custom, `hasUniqueValue: true`) |
| Contact | `contacts` | `email` |
| Opportunity | `deals` | `gtmos_opportunity_id` (custom, `hasUniqueValue: true`) |

`GET /api/v1/integrations/hubspot/mapping` returns this mapping and the custom property definitions. Only **companies** are pushed today (reverse ETL and the `sync_crm` workflow action). Contact and deal property mappers (`contact_properties`, `deal_properties`, including a deal-stage map to HubSpot's default pipeline) exist but are not yet wired to a sync job.

**Why not upsert companies on `domain`?** HubSpot documents `domain` as the company's primary identifier for dedupe, but does not enforce uniqueness on it, so batch upsert rejects it as an `idProperty` ("Unable to perform update/upsert by non-unique 0-2 property domain"). GTMOS creates its own unique property, `gtmos_account_id`, holding the GTMOS account UUID, and keys every write on it. Replaying a sync therefore cannot create a duplicate company.

Custom company properties written by GTMOS: `gtmos_account_id`, `gtmos_icp_score`, `gtmos_intent_score`, `gtmos_score_grade`, `gtmos_account_tier`, `gtmos_last_signal`, `gtmos_last_signal_at`, `gtmos_next_best_action`, `gtmos_industry`. Contacts: `gtmos_contact_id`, `gtmos_buying_role`. Deals: `gtmos_opportunity_id`.

### Two adapters, one protocol

Both implement `CrmAdapter.upsert(object_type, records) -> BatchOutcome` (`integrations/hubspot.py`). `crm_sync.get_adapter` picks the live adapter **only** when `HUBSPOT_ACCESS_TOKEN` is set **and** `HUBSPOT_LIVE_WRITES_ENABLED=true`. In every other case, including a token with the flag off, the demo adapter is used.

**`DemoHubSpotAdapter` (default).** Upserts into `simulated_crm_objects` keyed on the same unique value the real adapter would use. It assigns deterministic fake HubSpot ids and merges properties on update like HubSpot does. It deterministically fails about 3% of records on their first attempt with a simulated `429 Too Many Requests`, so the retry path runs in every demo sync. Syncs are recorded with `is_simulated=true`, and the UI and API label the remote side SIMULATED (`GET /api/v1/integrations/hubspot/simulated-objects`).

**`RealHubSpotAdapter` (optional).**
- `POST https://api.hubapi.com/crm/v3/objects/{type}/batch/upsert` with `Authorization: Bearer <private app token>` and `{"inputs": [{"idProperty": ..., "id": ..., "properties": {...}}]}`.
- Records are chunked to at most **100 inputs per batch** (the HubSpot limit).
- HTTP `429` and `5xx` are retried up to 4 attempts. Integer `Retry-After` values are honored; otherwise it backs off exponentially (1s, 2s, 4s, …, capped at 30s).
- `200` and `207` responses are matched back to input records by the id property. Records missing from `results` are marked failed with the batch's `errors[].message`. Non-retryable HTTP errors fail the whole batch without retry.
- `ensure_properties()` creates the custom properties via `POST /crm/v3/properties/{type}` and treats `409` as "already exists". It needs `crm.schemas.*` write scopes. The sync job calls it automatically (`ensure_properties_once`) before the first live company sync in each process; you can also run it by hand to check scopes first (see [Going live safely](#going-live-safely)).
- On success, the returned HubSpot id is written to `accounts.hubspot_company_id` and `external_records.external_id`.

**This adapter has not been run against a live HubSpot portal.** No credentials were available. Its behavior is covered by unit tests with a mocked HTTP client, based on the documented API shape in `docs/research-notes-integrations.md`. One detail in that shape, the `new` flag on upsert results used to tell created from updated, is marked unverified there.

### Reverse ETL: diff, upsert, retry

`services/crm_sync.py` implements the contract that tools like Hightouch and Census implement on top of a warehouse model:

1. **Model.** For each candidate account (not merged, has a domain, grade A/B/C unless specific ids are given) build the desired properties: `name`, `domain` and the `gtmos_*` computed fields (score, grade, intent, tier, most recent signal, next best action).
2. **Diff.** Hash the canonical JSON payload (sha256, sorted keys) and compare it with `external_records.last_payload_hash`. Matching records are skipped and counted as `records_skipped`. For the rest, `last_payload` gives the list of changed fields. Note what this does and does not detect: the hash is compared against **what GTMOS last sent**, not against the record's current state in HubSpot. If someone edits a `gtmos_*` property in the CRM, the computed payload is unchanged, the record is skipped, and the drift persists until the computed value itself changes. A reconciliation job that reads remote state back is the fix and is not implemented in V1.
3. **Upsert.** Send changed records through the adapter in batches of at most 100 on the stable key.
4. **Retry.** Records that failed with a retryable error are retried as a smaller set, up to 3 rounds. Non-retryable failures are recorded immediately.
5. **Record.** Successful records update `external_records` (hash, payload, external id, timestamp). The run is written to `integration_syncs` with considered, changed, succeeded, failed and skipped counts, retries, the first 50 errors and a correlation id. `integrations.status` becomes `healthy` or `degraded`, and an `integration.synced` audit event is written.

`GET /api/v1/integrations/hubspot/reverse-etl/preview` returns the plan without writing: `would_create`, `would_update`, `unchanged`, per-field change counts, a sample, and `destination_mode` (`simulated` or `live`). `POST /api/v1/integrations/hubspot/reverse-etl/run` executes it. When live writes are enabled and `ADMIN_API_TOKEN` is set, it requires the admin bearer token.

```mermaid
sequenceDiagram
    autonumber
    participant T as Trigger (UI / n8n schedule / workflow)
    participant S as crm_sync
    participant DB as Postgres
    participant A as CrmAdapter (demo or real)
    participant H as HubSpot / simulated_crm_objects

    T->>S: run_company_sync(account_ids?)
    S->>DB: select candidate accounts + external_records + last signals
    S->>S: build payload, sha256 hash, compare last_payload_hash
    S->>DB: insert integration_syncs (status=running, skipped=N unchanged)
    loop up to 3 rounds while retryable failures remain
        S->>A: upsert("companies", changed records)
        loop chunks of at most 100
            A->>H: POST /crm/v3/objects/companies/batch/upsert (idProperty=gtmos_account_id)
            alt 429 or 5xx
                H-->>A: error (+ Retry-After)
                A->>A: sleep, retry (max 4 HTTP attempts)
            else 200 / 207
                H-->>A: results[] + errors[]
            end
        end
        A-->>S: per-record created / updated / failed(retryable?)
        S->>DB: upsert external_records (hash, payload, external_id)
    end
    S->>DB: finalize integration_syncs counts, integrations health, audit_events
    S-->>T: sync row (status succeeded / partial / failed)
```

### Inbound HubSpot webhooks

`POST /api/v1/webhooks/hubspot` accepts HubSpot CRM change events.

- **Signature v3:** `X-HubSpot-Signature-v3 = base64(HMAC-SHA256(client_secret, METHOD + decoded URI + body + X-HubSpot-Request-Timestamp))`, compared in constant time. Timestamps older than 5 minutes, or more than 5 minutes in the future, are rejected. The secret is `HUBSPOT_WEBHOOK_CLIENT_SECRET`. Without it the status is `not_configured`, which is accepted in development and rejected in production.
- The URI used is the URL the API sees (`request.url`). Behind a TLS-terminating proxy, run uvicorn with proxy headers so the scheme and host match what HubSpot signed. Otherwise every signature fails.
- Events go through the standard webhook pipeline (stored raw, deduplicated, see [Webhook pipeline](#webhook-pipeline)) and are **acknowledged and logged, not applied**. The processor returns `{"received": n, "applied": 0}`. Replay is not offered for HubSpot events.

### Sync conflict policy

GTMOS and the CRM each own a set of fields, and neither silently overwrites the other's:

- **GTMOS owns the `gtmos_*` properties.** They are computed (scores, tier, last signal, next best action) and recomputed from GTMOS state on every sync. A rep's edit to a `gtmos_*` field in HubSpot will be overwritten by the next changed push. That is intended, because those fields are outputs, not inputs.
- **The CRM owns rep-edited fields** such as owner, lifecycle notes and deal details. The default reverse-ETL payload does not include owner, lifecycle stage or firmographics. `full_record=True` adds industry (as `gtmos_industry`), employee count, city, country and lifecycle stage, and is meant for an initial backfill.
- **Inbound HubSpot changes are logged, not auto-applied.** They are stored in `webhook_events` for review. Applying a CRM-side change to GTMOS (for example, a rep correcting employee count) is meant to be a deliberate manual field edit that writes `field_provenance` with `source=crm`/`manual` and optionally a manual lock, which the enrichment merge policy already respects. **Not implemented in V1:** no endpoint writes `field_provenance`, so today an inbound change is recorded and read, never applied. The n8n template `04-crm-update-to-rescore` shows the narrow automated case: a fit-relevant change triggers a rescore, never a field write.
- **Known gap:** the default payload includes `name` and `domain` alongside the `gtmos_*` fields, so they are also sent whenever any GTMOS field changes. If a rep renames a company in HubSpot, the next changed push will write the GTMOS name back. Sending `name` and `domain` only when creating a company would close this gap.

---

## PostHog

**Status: LIVE endpoint, not tested against a real PostHog destination.**

Endpoints: `POST /api/v1/webhooks/posthog` (for PostHog webhook destinations or a relay such as n8n template 02) and `POST /api/v1/events` (direct capture, same pipeline).

**Auth.** PostHog destinations can add static headers but cannot compute an HMAC, so this endpoint accepts `X-GTMOS-Webhook-Token: <WEBHOOK_SECRET>` (constant-time compare). A sender that can sign may instead send the GTMOS HMAC headers described under n8n. The HMAC takes precedence when `X-GTMOS-Signature` is present.

**Event shape** (`integrations/posthog.py`). A single event, a list, or `{"batch": [...]}`:

```json
{
  "event": "trace_volume_threshold",
  "distinct_id": "maya@kestrel-analytics.example",
  "timestamp": "2026-09-21T14:03:11Z",
  "uuid": "0192c3a4-...",
  "properties": { "$groups": { "company": "kestrel-analytics.example" }, "email": "maya@kestrel-analytics.example" }
}
```

**Account matching** (`domain/matching.py`):
1. `properties.$groups.company`, normalized as a domain, matched against known account domains (method `group_key`, confidence 0.98).
2. Otherwise the email domain from `properties.email`, `properties.$email`, or a `distinct_id` that contains `@` (method `email_domain`, confidence 0.9). Subdomains fall back to their parent (`eu.acme.example` → `acme.example`, confidence 0.8).
3. **Free-mail domains never match** (gmail.com, outlook.com, icloud.com, proton.me, and the rest of the blocklist). A personal address is not a company.

Every event is stored as an `engagements` row (`dedupe_key = posthog:{uuid}`), matched or not. A duplicate event id is reported and skipped before any signal is derived. `$`-prefixed properties are dropped except `$current_url` and `$pathname`.

**Event → signal.** `workspace_created` / `signed_up` → `product_signup`; `teammate_invited` → `teammate_invited`; `integration_connected` → `integration_activated`; `trace_volume_threshold` → `usage_threshold`. Signals from product events get `confidence=0.95` and `source=posthog`.

**Pricing aggregation.** A single `pricing_page_viewed` is not a signal. When an account has at least 2 pricing views in the trailing 7 days, a `pricing_page_visit` signal is created with `source_ref = pricing:{ISO year}-W{week}`, so the signal dedupe key allows at most one pricing signal per account per ISO week.

**PQL.** A newly created `usage_threshold` signal emits a `product.pql` workflow event in addition to the normal `signal.created`. The default `pql-to-ae` workflow (conditions: segment in strategic/enterprise/mid_market) rescores, routes to an AE, creates a follow-up task, advances the funnel stage to `engaged`, records an in-app owner notification, and syncs to the CRM.

```mermaid
sequenceDiagram
    autonumber
    participant P as PostHog destination / n8n relay
    participant W as /webhooks/posthog
    participant WS as webhook_service
    participant PE as product_events
    participant SG as signal_service
    participant WF as workflow_engine

    P->>W: POST event(s), X-GTMOS-Webhook-Token, Idempotency-Key
    W->>WS: verify token, derive idempotency key
    alt duplicate delivery
        WS-->>P: 200 {status: duplicate}
    else new
        WS->>WS: store webhook_events (received)
        WS->>PE: ingest_events
        PE->>PE: match $groups.company, else email domain (free-mail blocked)
        PE->>PE: insert engagements (dedupe posthog:{uuid})
        alt trace_volume_threshold
            PE->>SG: ingest_signal(usage_threshold)
            SG->>SG: dedupe, persist, rescore account
            SG->>WF: emit signal.created
            PE->>WF: emit product.pql
            WF->>WF: pql-to-ae run: rescore, route, task, lifecycle, notify, sync_crm
        else pricing_page_viewed and 2 or more in 7 days
            PE->>SG: ingest_signal(pricing_page_visit, one per account-week)
        end
        WS-->>P: 200 {status: processed, result}
    end
```

---

## n8n

**Status: OPTIONAL.** Four templates in `integrations/n8n/` handle transport and scheduling around GTMOS. Scoring, dedupe, idempotency and state stay in GTMOS. See [n8n.md](n8n.md) for node-by-node details.

**Signing scheme** (`integrations/signatures.py`), used by `POST /api/v1/webhooks/n8n` and available on any GTMOS webhook:

```
X-GTMOS-Timestamp: <unix seconds>
X-GTMOS-Signature: sha256=<hex HMAC-SHA256(WEBHOOK_SECRET, "${timestamp}.${raw_body}")>
```

The signature covers the exact raw bytes, is compared in constant time, and is rejected if the timestamp is more than 5 minutes from server time in either direction, which limits replay. `/webhooks/n8n` accepts one signal, a list, or `{"signals": [...]}` (up to 100 per request) in the `SignalIn` shape: `account_domain`, `signal_type`, `title`, `explanation`, `source`, `source_ref` (stable id of the real-world event), optional `source_url`, `observed_at`, `confidence`, `strength` and `evidence`.

---

## Enrichment providers

**Status: DEMO (three simulated providers) plus OPTIONAL Apollo, untested live.**

| Key | Name | Fields | Coverage | Error rate | Cost |
|---|---|---|---|---|---|
| `demo_firmographics` | Firmographics DB (simulated) | industry, employees, geo, founded, funding, revenue, growth | 82% | 5% | 1.0 |
| `demo_webscan` | Website & technographics scanner (simulated) | technologies, noisy employee estimate (conf 0.55), industry, geo | 78% | 2% | 0.5 |
| `demo_hiring` | Job-postings index (simulated) | AI open roles, AI team size, growth | 70% | 3% | 0.75 |
| `apollo` | Apollo organization enrichment | industry, employees, geo, founded, revenue, technologies, funding | real | real | 1.0 |

The simulated providers answer from the same deterministic company universe the seed data was generated from (`seed/profiles.py`). Coverage gaps, value noise, confidence and simulated upstream timeouts are derived from a hash of provider + domain, so they are reproducible and waterfall behavior (fallback, low confidence, errors) happens without any paid API. Latency is reported, not slept. Their display names include "(simulated)" everywhere they are shown, and runs are `is_simulated=true`.

The waterfall (`DEFAULT_WATERFALL`) tries providers per field in order, caching one call per provider per run. Answers below 0.6 confidence are held as fallbacks. The merge policy never overwrites a manual lock and replaces an existing value only with a clearly better one (+0.1 confidence, or the existing value is more than 180 days old). Every attempt, including misses, is stored in `enrichment_attempts`, and the winning value's provenance in `field_provenance`.

`ApolloOrganizationProvider` calls `GET https://api.apollo.io/api/v1/organizations/enrich?domain=…` with an `X-Api-Key` header and is registered only when `APOLLO_API_KEY` is set. Without it, Apollo's waterfall positions record `skipped: provider not configured`. Its field mapping and error handling are unit-tested with a mocked transport. **It has not been exercised against the live Apollo API.** Treat the field mapping and the fixed 0.8 confidence as assumptions to verify.

---

## LLM (research generation)

**Status: DEMO by default, OPTIONAL live.**

Live generation is used only when **both** `ANTHROPIC_API_KEY` is set **and** `LLM_ENABLED=true` (`Settings.llm_mode`). A key in the environment alone never triggers billed calls. Otherwise the deterministic generator writes the brief by restating evidence.

When live, `AnthropicResearchWriter` (`integrations/llm.py`) uses the official `anthropic` Python SDK with structured output (`messages.parse` with a Pydantic `ResearchOut` schema). Each claim carries `evidence` refs (`E1`, `E2`, …) and a `hypothesis` flag. The system prompt forbids facts that are not in the numbered evidence. Whatever the model returns then goes through **the same citation validation as the deterministic generator**: a claim whose refs do not resolve to evidence in the report is stripped and recorded in `research_reports.unsupported_claims`. Provider errors, connection failures, refusals and missing structured output raise `LLMUnavailable`. The service then falls back to the deterministic generator and records the reason. The generator name is stored (`anthropic:<model>` or `demo-deterministic`). Reports are always drafts, and research is never written to the CRM as fact.

Only account research uses the LLM. Outreach drafts are built from templates plus the evidence-grounded reasoning chain.

---

## Background jobs: Redis / RQ

**Status: LIVE (local infrastructure).**

With `QUEUE_BACKEND=inline` (the default for local development and tests), workflow runs execute in the request. With `QUEUE_BACKEND=redis` and `REDIS_URL` (the docker compose default):

- `dispatch()` does not enqueue immediately. It appends the run id to `session.info`, and a SQLAlchemy `after_commit` listener enqueues it on the `gtmos-workflows` RQ queue (`job_id=run-{id}`). The worker never sees a run whose row has not been committed, and a rolled-back transaction enqueues nothing.
- If Redis is down at enqueue time, the error is logged and the run stays `queued` in Postgres. A sweeper thread in the worker (`python -m gtmos.worker`) re-enqueues runs that have been `queued` for more than 2 minutes, every 60 seconds. Postgres is the source of truth; Redis is only delivery.
- `execute_run` is resumable and idempotent. It skips completed steps, retries `TransientError` with backoff up to each step's `max_attempts`, and moves exhausted runs to `dead_letter` for manual retry from the Operations page.

```mermaid
sequenceDiagram
    autonumber
    participant Src as n8n / API / PostHog
    participant SG as signal_service
    participant SC as scoring_service
    participant WF as workflow_engine
    participant Q as Redis (RQ)
    participant WK as worker
    participant CRM as crm_sync → HubSpot adapter

    Src->>SG: signal (domain, type, source_ref)
    SG->>SG: dedupe_key check, insert signals, audit
    SG->>SC: rescore_accounts([account])
    SC-->>SG: new icp_scores row, cached score on accounts
    SG->>WF: emit_event("signal.created"), plus "score.threshold_crossed" if it became A-grade
    WF->>WF: filters, conditions, insert workflow_runs (unique idempotency_key) + step rows
    Note over WF,Q: run id queued in session.info
    WF-->>Src: response after commit
    WF->>Q: after_commit: enqueue run-{id}
    Q->>WK: execute_run_job
    WK->>WK: enrich → rescore → committee → research
    WK->>WK: draft_outreach → message_drafts (status=review)
    WK->>WK: route_account
    WK->>CRM: sync_crm (single account)
    CRM-->>WK: integration_syncs row (retryable failure → TransientError → step retry)
    WK->>WK: run succeeded / dead_letter, audit
```

The diagram shows the `funding-signal-to-outreach` workflow. Its conditions require `icp_score >= 75` and a non-customer account.

---

## Webhook pipeline

All inbound webhooks (`posthog`, `n8n`, `hubspot`) share `services/webhook_service.py`: **verify → store raw → dedupe → process → record outcome**.

- Verification returns `valid`, `invalid` or `not_configured`. `not_configured` is accepted in development and becomes `invalid` when `ENV=production`.
- The idempotency key comes from the `Idempotency-Key` header, else the payload `uuid`/`event_id`/`eventId`/`id`, else `sha256(body)`. `UNIQUE (source, idempotency_key)` holds under concurrency. Duplicates return `200` with the original result and increment `duplicate_count`.
- Rejected deliveries (bad signature, invalid JSON) do not block a later valid delivery with the same key.
- Processing runs in a savepoint. Failures are stored as `failed`, or as `dead_letter` after 3 attempts, and return `202`. `POST /api/v1/webhooks/events/{id}/replay` reprocesses failed PostHog and n8n events.
- Bodies over 1 MB are rejected with `413`.

---

## Outbound email

**Status: deliberately none.** GTMOS does not send email, LinkedIn messages or any other external message. Message drafts move `draft → review → approved → ready`, and **READY is the hand-off**: an approved message is ready for a rep to send from their own sequencing tool or inbox. The `notify_owner` workflow action records an in-app notification (`activities.type = notification`, "no external message sent"). `OUTBOUND_SEND_ENABLED` exists only to document the boundary; nothing reads it to send. This is intentional: deliverability, consent and sending reputation belong to a dedicated sending platform, and an automated system that can write evidence-grounded copy should not also be able to send it without a human.

---

## Going live safely

Suggested order for connecting a real HubSpot portal. Use a sandbox or developer test portal first.

1. **Set the security boundary.** Set `ENV=production` (or at least set the secrets), a strong `ADMIN_API_TOKEN` and `WEBHOOK_SECRET`. In production, unsigned webhooks and admin calls without a token are refused.
2. **Create a private app** with `crm.objects.companies.read/write`, `crm.objects.contacts.read/write`, `crm.objects.deals.read/write` and `crm.schemas.companies.write` (plus contacts/deals schemas). Set `HUBSPOT_ACCESS_TOKEN`. **Leave `HUBSPOT_LIVE_WRITES_ENABLED=false`.** The demo adapter is still used at this point.
3. **Create the custom properties.** Run `RealHubSpotAdapter(token).ensure_properties()` once from a Python shell in the API environment and check the result in HubSpot → Properties. `gtmos_account_id` must exist with *unique values* enabled before any upsert. HubSpot allows at most 10 unique properties per object. If the call fails (usually missing schema scopes), create the properties manually.
4. **Preview.** `GET /api/v1/integrations/hubspot/reverse-etl/preview`. Check `would_create`, the changed-field counts and the sample payloads. Existing HubSpot companies will **not** be matched by domain. The first live run creates new companies keyed on `gtmos_account_id`. Before that run, deduplicate by backfilling `gtmos_account_id` on existing HubSpot companies (export, match on domain, import).
5. **Enable writes on a small scope.** Set `HUBSPOT_LIVE_WRITES_ENABLED=true`, restart, and trigger a sync for a few accounts. A manual run of a workflow that contains `sync_crm` on a single account from the account page is the smallest scope. `/reverse-etl/run` pushes every changed A/B/C account. Check `integration_syncs` (`is_simulated=false`), `external_records.external_id` and the records in HubSpot.
6. **Understand the trigger surface.** With live writes on, the `sync_crm` workflow step writes to HubSpot whenever a qualifying signal triggers a workflow, with no admin token involved. The admin token gates only the manual `/reverse-etl/run` endpoint. Disable the relevant workflows first if you want manual-only syncs.
7. **Inbound webhooks.** Set `HUBSPOT_WEBHOOK_CLIENT_SECRET` from a public app, subscribe to company property changes, point the subscription at `/api/v1/webhooks/hubspot`, and confirm deliveries show `signature: valid` in `GET /api/v1/webhooks/events?source=hubspot`. Run behind HTTPS with proxy headers enabled.
8. **Monitor.** Watch the Operations page for `partial`/`failed` syncs, `integrations.status = degraded` and dead-lettered runs. Every run has a correlation id that links its sync, audit events and webhook deliveries.
9. **Roll back** by setting `HUBSPOT_LIVE_WRITES_ENABLED=false`. The next sync uses the demo adapter again, and nothing else changes.

The same pattern applies to the LLM (`ANTHROPIC_API_KEY` then `LLM_ENABLED=true`, with generated reports reviewed before they are trusted) and to Apollo (set `APOLLO_API_KEY`, enrich a handful of accounts, and inspect `enrichment_attempts` before relying on it).

## Known issues found while documenting

- *(Fixed after review)* Property groups are now mapped explicitly (`companyinformation`, `contactinformation`, `dealinformation`), and `ensure_properties()` runs once per process before the first live company sync.
- *(Fixed after review)* Reverse ETL updates carry only `gtmos_*` properties; `name` and `domain` are sent only when a record is created, so rep edits in HubSpot are never overwritten.
- Contact and deal sync are mapped (`contact_properties`, `deal_properties`) but not yet scheduled: only companies are pushed by the reverse-ETL job.
- `Retry-After` is honored only when it is an integer string (`isdigit()`). Fractional or HTTP-date values fall back to exponential backoff.
