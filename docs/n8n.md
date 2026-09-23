# n8n workflows

`integrations/n8n/` holds six n8n workflows that connect GTMOS to the outside world. They are optional —
GTMOS runs fully without n8n, and every endpoint they call can be called directly — but they are the
low-code surface a RevOps operator can change without a deploy.

Verified against **n8n 2.40.5** (`n8nio/n8n:2.40.5`, container `gtmos-n8n-1`) talking to the GTMOS API on
the host at `http://host.docker.internal:8010`. See [research/n8n.md](research/n8n.md) for the underlying
n8n reference this was built from.

| File | Id | Trigger | What it does |
|---|---|---|---|
| `01-signal-to-gtmos.json` | `jV6yvWXpC6IaLuFl` | Webhook `POST /webhook/gtmos-signal-intake` | Normalises an external alert into a GTMOS signal, HMAC-signs it, posts to `/api/v1/webhooks/n8n`. |
| `02-product-event-to-gtmos.json` | `VZMR72EYXwur2acN` | Webhook `POST /webhook/gtmos-posthog` | Relays PostHog destination events, filtered to GTM-relevant ones, to `/api/v1/webhooks/posthog`. |
| `03-qualified-accounts-to-hubspot.json` | `V9xOZgZVTpaEDMPD` | Schedule, hourly (+ Execute Workflow Trigger) | Previews the reverse-ETL diff, runs the sync only when something changed, writes a signed run record back to GTMOS. |
| `04-crm-update-to-rescore.json` | `ddeUXj02dyHboALn` | Webhook `POST /webhook/gtmos-hubspot-change` | Rescores an account when a fit-relevant HubSpot property changes. **Needs a HubSpot token; not runnable in this environment.** |
| `05-crm-webhook-to-gtmos.json` | `GTMOScrmDedupe01` | Webhook `POST /webhook/gtmos-crm-events` | Normalises a HubSpot-shaped event **array** and forwards it to `/api/v1/webhooks/hubspot`; redeliveries are deduplicated. |
| `06-error-handler.json` | `GTMOSerrHandler1` | Error Trigger | Receives failures from the other workflows and records a structured operational record in GTMOS. Notifies nothing external. |

Every file carries an explicit top-level `"id"`. That is deliberate: `n8n import:workflow` **upserts on
id**, so re-importing updates the same workflow instead of creating a duplicate every time. Workflows
01–05 set `settings.errorWorkflow: "GTMOSerrHandler1"`.

---

## Environment

The workflows read configuration through `$env`, so no secrets live in the workflow JSON.

| Variable | Used by | Value |
|---|---|---|
| `GTMOS_BASE_URL` | all | `http://host.docker.internal:8010` (API on the host) or `http://api:8000` (all-in-compose). |
| `GTMOS_WEBHOOK_SECRET` | 01, 02, 03, 06 | Must equal the API's `WEBHOOK_SECRET`. HMAC key for 01/03/06; sent as `X-GTMOS-Webhook-Token` by 02. |
| `GTMOS_ADMIN_TOKEN` | 03 | Must equal the API's `ADMIN_API_TOKEN`. Gates the reverse-ETL run endpoint when live CRM writes are on. |
| `HUBSPOT_TOKEN` | 04 | HubSpot private-app token. Unset here, which is why 04 cannot run. |
| `HUBSPOT_WEBHOOK_CLIENT_SECRET` | 05 (optional) | If present, 05 signs its delivery with HubSpot's v3 scheme. Unset here, so GTMOS records `signature: not_configured`. |

Two n8n settings are required and are already in `docker-compose.yml`:

| Setting | Why |
|---|---|
| `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` | n8n 2.x blocks `$env` in expressions and Code nodes by default. Every workflow reads `$env.GTMOS_*`. |
| `NODE_FUNCTION_ALLOW_BUILTIN=crypto` | The signing Code nodes in 01, 03, 05 and 06 call `require('crypto')`. |

---

## Import, publish, run

```bash
# 1. start n8n (GTMOS API must already be running on :8010)
docker compose --profile n8n up -d n8n

# 2. import everything from the read-only /workflows mount (upserts on the id in each file)
docker exec gtmos-n8n-1 sh -lc 'n8n import:workflow --separate --input=/workflows'

# 3. publish. Import ALWAYS deactivates, and publish:workflow has no --all
for id in jV6yvWXpC6IaLuFl VZMR72EYXwur2acN V9xOZgZVTpaEDMPD \
          ddeUXj02dyHboALn GTMOScrmDedupe01 GTMOSerrHandler1; do
  docker exec gtmos-n8n-1 sh -lc "n8n publish:workflow --id=$id"
done

# 4. RESTART — CLI publishes write to the database and a running n8n does not notice
docker restart gtmos-n8n-1
until [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:5678/healthz)" = 200 ]; do sleep 1; done
sleep 8   # healthz goes green a few seconds before webhook routes are registered

docker exec gtmos-n8n-1 sh -lc 'n8n list:workflow'                # ids
docker exec gtmos-n8n-1 sh -lc 'n8n list:workflow --active=true'  # published only
```

`n8n update:workflow --id=<id> --active=true` still works but is deprecated in 2.x; `publish:workflow`
is the current command.

### Production webhook URLs

| Workflow | URL |
|---|---|
| 01 | `http://localhost:5678/webhook/gtmos-signal-intake` |
| 02 | `http://localhost:5678/webhook/gtmos-posthog` |
| 04 | `http://localhost:5678/webhook/gtmos-hubspot-change` |
| 05 | `http://localhost:5678/webhook/gtmos-crm-events` |

`/webhook/...` is live only once the workflow is published. `/webhook-test/...` is a different endpoint
that only exists for 120 seconds after you press *Listen for test event* in the editor. Both failure
modes return 404 and look identical from curl.

### Running the scheduled workflow on demand

Workflow 03 carries an **Execute Workflow Trigger** next to its Schedule Trigger, because the Server CLI
refuses to execute a workflow whose only trigger is a schedule (`Missing node to start execution`):

```bash
docker exec gtmos-n8n-1 sh -lc \
  'N8N_RUNNERS_BROKER_PORT=5699 N8N_PORT=5688 n8n execute --id=V9xOZgZVTpaEDMPD'
```

The two port overrides are required: `n8n execute` starts its own task broker, which collides with the
running server's on 5679.

---

## What each workflow does

### 03 — High-intent accounts → CRM (Workflow B)

```
Every hour ─┐
            ├─> Preview reverse-ETL diff ─> Anything changed? ─true─> Run reverse-ETL sync ─ok──┐
Run now  ───┘                                       │                          └─err─> Sync call failed (Stop And Error)
                                                    └─false─> Nothing to sync ─────────┐
                                                                                        ├─> Build run record
                                                    Sign (HMAC) ─> Log outcome to GTMOS ┘
                                                          └─> Any records failed? ─true─> Fail the run (Stop And Error)
                                                                                  └─false─> Clean run
```

1. `GET /api/v1/integrations/hubspot/reverse-etl/preview?limit=25` — read-only, returns `would_create` /
   `would_update` / `unchanged`.
2. Only when `would_create + would_update > 0` does it `POST /api/v1/integrations/hubspot/reverse-etl/run`
   with `Authorization: Bearer $GTMOS_ADMIN_TOKEN`. An idle hour writes no sync-log row and no CRM audit
   noise.
3. Either way it builds a structured run record (preview counts + the `integration_syncs` row), signs it
   and posts it to `/api/v1/webhooks/n8n`, so the outcome is durable and queryable in GTMOS rather than
   only in n8n's execution list.
4. A sync that reports `records_failed > 0` ends in **Stop And Error**, which hands the run to workflow 06.

The record uses `signals: []`. `/api/v1/webhooks/n8n` stores the whole body verbatim and hands
`payload.signals` to the signal processor, so an empty list records the run as a processed webhook event
without inventing GTM data. `event_id` is the sync-row id (or `noop:<minute>`), so GTMOS dedupes it.

n8n never touches HubSpot. GTMOS owns the CRM boundary — field mapping, `gtmos_*` ownership,
simulated-vs-live mode, batching, change detection — so this workflow schedules GTMOS's job rather than
re-implementing it.

### 05 — CRM webhook → GTMOS with deduplication (Workflow C)

```
HubSpot events webhook ─> Normalise HubSpot batch ─> Prepare signed delivery ─> Forward batch to GTMOS
                                                                                    ├─ok─> Report dedupe outcome
                                                                                    └─err─> Ingestion failed (Stop And Error)
```

Accepts a JSON **array** of HubSpot change events (`eventId`, `subscriptionType`, `objectId`,
`propertyName`, `propertyValue`, `occurredAt`, `attemptNumber`). It keeps the batch a batch: GTMOS's
idempotency key for an array payload is `hubspot:batch:<sorted member eventIds>`, so fanning the array
out into n8n items would destroy exactly the dedupe this workflow exists to demonstrate.

`attemptNumber` is forwarded unchanged on purpose. It is the field HubSpot increments on every retry, and
GTMOS strips it (`RETRY_VOLATILE_KEYS` in `webhook_service.py`) before hashing — passing it through is
what makes the dedupe test honest rather than staged. Events without an `eventId` are dropped rather than
allowed to push the whole batch onto the body-hash fallback.

`responseMode: lastNode` means the caller gets GTMOS's verdict back, so `curl` shows `duplicate: true`
directly.

**Signature.** GTMOS verifies inbound CRM webhooks with HubSpot's v3 scheme,
`base64(HMAC-SHA256(client_secret, METHOD + uri + rawBody + timestamp_ms))`. If
`HUBSPOT_WEBHOOK_CLIENT_SECRET` is present in the n8n environment the workflow computes it; it is not set
here, so GTMOS reports `signature_status: not_configured` and accepts the delivery (development only —
with `ENV=production` GTMOS refuses unsigned webhooks). The body string is built once in the Code node and
sent verbatim as a raw body, because re-serialising it downstream would change the bytes and break the MAC.

### 06 — Error handler (Workflow D)

```
On workflow error ─> Build operational record ─> Sign (HMAC) ─> Record failure in GTMOS ─> Mirror to execution log
```

Attached as `settings.errorWorkflow` on 01–05. It flattens both Error Trigger payload shapes (`execution{}`
for a mid-run node failure, `trigger{}` for a failure in the trigger itself) into one record:

```json
{
  "signals": [],
  "event_id": "n8n-error:<workflowId>:<executionId>:<lastNode>",
  "record_type": "n8n_workflow_error",
  "recorded_by": "n8n:06-error-handler",
  "workflow_id": "...", "workflow_name": "...",
  "execution_id": "19", "execution_url": "http://localhost:5678/workflow/.../executions/19",
  "execution_mode": "webhook", "retry_of": null, "last_node_executed": "Ingestion failed",
  "error_name": "NodeOperationError", "error_message": "...", "error_stack": "..."
}
```

It **notifies nothing external** — no email, no Slack, no third-party call. A failure is data, not an
alert; GTMOS owns alerting. Three durable places record it:

1. the GTMOS webhook event (`GET /api/v1/webhooks/events?source=n8n`), keyed on `event_id` so a redelivery
   of the same failure collapses instead of piling up;
2. `$execution.customData` (`gtmos_failed_workflow`, `gtmos_failed_execution`, `gtmos_failed_node`), which
   n8n's execution list can be filtered by;
3. a `GTMOS_N8N_ERROR <json>` line in the execution's log output, as a last resort for when GTMOS itself
   is the thing that was down.

06 deliberately does **not** set an `errorWorkflow` of its own, and its HTTP node uses
`onError: continueRegularOutput`, so a failure while recording a failure cannot recurse.

### 01, 02, 04

Unchanged in behaviour from the original templates; they now carry explicit ids and
`settings.errorWorkflow`. 01 maps an alert to the `SignalIn` contract and signs it; 02 filters PostHog
events and forwards them with `Idempotency-Key: <uuid>`; 04 resolves a HubSpot `objectId` to a domain via
the HubSpot API and then rescores the GTMOS account. See the node comments for detail.

---

## Retries, timeouts and error behaviour

n8n clamps these in the engine (`getRetryParams`): `maxTries` ∈ [2, 5] (default 3) and `waitBetweenTries`
∈ [0, 5000] ms (default 1000). There is **no exponential backoff and no jitter** — the engine sleeps a
fixed interval between attempts. The `timeout` option is milliseconds and is a *response-headers* timeout,
not a total-request budget; unset, it defaults to 300 000 ms, which is not a useful failure mode.

| Workflow · node | `maxTries` | `waitBetweenTries` | `timeout` | `onError` | Why |
|---|---|---|---|---|---|
| 03 · Preview reverse-ETL diff | 3 | 2 000 ms | 15 000 ms | `stopWorkflow` | Read-only and cheap, so retry freely. If the diff cannot be read there is nothing sensible to do next, so stop and let 06 record it. |
| 03 · Run reverse-ETL sync | 2 | 5 000 ms | 120 000 ms | `continueErrorOutput` | Safe to retry (GTMOS diffs and upserts on a stable key), but each attempt walks 850 accounts, so two attempts and the maximum permitted wait. The long timeout covers a real full sync; the error branch goes to Stop And Error so the failure is recorded rather than swallowed. |
| 03 · Log outcome to GTMOS | 3 | 3 000 ms | 15 000 ms | `continueRegularOutput` | Bookkeeping. A failed log must not retroactively fail a sync that succeeded. |
| 05 · Forward batch to GTMOS | 3 | 2 000 ms | 20 000 ms | `continueErrorOutput` | The retry is free of duplicate risk precisely because GTMOS dedupes on member event ids. The error branch raises Stop And Error so the item cannot vanish silently. |
| 06 · Record failure in GTMOS | 3 | 5 000 ms | 15 000 ms | `continueRegularOutput` | If GTMOS is down, wait the longest permitted interval — but never fail, or recording an error becomes an error. Falls through to the execution-log mirror. |

`continueOnFail` is deprecated; these use `onError` (`stopWorkflow` / `continueRegularOutput` /
`continueErrorOutput`). 03 and 05 also set `saveDataErrorExecution: all` and `saveDataSuccessExecution: all`.

---

## What was verified, and how

Executed against the running stack on 2026-09-22/23 (n8n 2.40.5, GTMOS API on :8010, HubSpot in simulated
mode). Reproduce with the commands below.

### 03 — executed, sync path

```bash
docker exec gtmos-n8n-1 sh -lc 'N8N_RUNNERS_BROKER_PORT=5699 N8N_PORT=5688 n8n execute --id=V9xOZgZVTpaEDMPD'
curl -s 'http://127.0.0.1:8010/api/v1/webhooks/events?source=n8n&limit=1'
```

Execution finished `status: success`, `lastNodeExecuted: "Clean run"`, customData
`gtmos_reverse_etl=succeeded`, `gtmos_records_changed=1`. GTMOS-side: preview went `would_update: 1` →
`would_update: 0`; sync row `21bb5583-…` `succeeded`, `records_considered 850`, `records_changed 1`,
`records_succeeded 1`, `records_failed 0`, `records_skipped 849`, `duration_ms 536`; webhook event
`f2f86717-…`, `idempotency_key n8n:n8n-reverse-etl:21bb5583-…`, `signature_status valid`,
`status processed`.

### 03 — executed, no-change path

Re-run with nothing pending: `ran_sync: false`, `sync: null`, preview `would_create 0 / would_update 0 /
unchanged 850`, event key `n8n:n8n-reverse-etl:noop:2026-09-23T03:57`. No sync row was written.

### 05 — executed, deduplication proved

```bash
# delivery 1
curl -s -X POST http://localhost:5678/webhook/gtmos-crm-events -H 'Content-Type: application/json' \
  --data-binary '[{"eventId":4399101201,"subscriptionType":"company.propertyChange","objectId":8812001,"propertyName":"numberofemployees","propertyValue":"340","occurredAt":1790135000000,"attemptNumber":0},
                  {"eventId":4399101202,"subscriptionType":"company.propertyChange","objectId":8812001,"propertyName":"industry","propertyValue":"COMPUTER_SOFTWARE","occurredAt":1790135000500,"attemptNumber":0}]'
# delivery 2 — same eventIds, attemptNumber 2
# delivery 3 — same eventIds, attemptNumber 3, array order reversed
curl -s 'http://127.0.0.1:8010/api/v1/webhooks/events?source=hubspot&limit=1'
```

| Delivery | `attemptNumber` | HTTP | GTMOS event id | `status` | `duplicate` | `duplicate_count` after |
|---|---|---|---|---|---|---|
| 1 | 0 | 200 | `aaa9f9a1-…` | `processed` | `false` | 0 |
| 2 | 2 | 200 | `aaa9f9a1-…` (same) | `duplicate` | `true` | **1** |
| 3 | 3, order reversed | 200 | `aaa9f9a1-…` (same) | `duplicate` | `true` | **2** |
| control: different `eventId` | 0 | 200 | `21955957-…` (new) | `processed` | `false` | 0 |

One stored event, `idempotency_key hubspot:batch:4399101201,4399101202`, `attempts: 1`, `received: 2`.
Re-verified after the deliberate-break test with a second batch (`4400500001,4400500002`): 0 → 1.

### 06 — executed, and proved to fire

Workflow 05's Code node was temporarily pointed at `/api/v1/webhooks/DELIBERATELY-BROKEN`, re-imported,
published and the container restarted. Firing the production webhook returned
`{"message":"Error in workflow"}` HTTP 500, and:

* n8n execution 19 (`GTMOScrmDedupe01`, mode `webhook`) → `error`;
* n8n execution 20 (`GTMOSerrHandler1`, **mode `error`**) → `success`;
* GTMOS webhook event `c738e991-…`, `idempotency_key n8n:n8n-error:GTMOScrmDedupe01:19:Ingestion failed`,
  `signature_status valid`, `status processed`, carrying `error_name: NodeOperationError`,
  `last_node_executed: "Ingestion failed"`, `execution_mode: "webhook"` and the full 404 detail including
  the broken URL.

05 was then restored from the repo file, re-imported, published, restarted and re-verified.

### 01 and 02 — re-executed after the changes

01: `POST /webhook/gtmos-signal-intake` → 200; GTMOS created signal
`n8n-verify-20260922-a` and moved the account score. 02: `POST /webhook/gtmos-posthog` → 200; GTMOS event
`n8n-verify-ph-20260922-a`, `signature_status valid`, `status processed`, `matched: 1`, signal
`integration_activated` created.

### 04 — NOT executed

`04-crm-update-to-rescore.json` calls `api.hubapi.com` directly and there is no HubSpot token in this
environment. It imports and publishes cleanly and its webhook is registered, but any delivery fails at the
*Get company from HubSpot* node. It is the one workflow here whose runtime behaviour is unverified. If you
route CRM events through n8n, prefer **05**, which stays inside the GTMOS boundary.

---

## Gotchas hit while building this

1. **CLI publish needs a container restart.** `n8n publish:workflow` writes straight to the database; a
   running n8n never notices. The command says so itself. Forgetting it means `/webhook/...` keeps 404ing
   with no other symptom.
2. **`healthz` is green before webhooks are registered.** For several seconds after a restart the editor
   answers 200 on `/healthz` while `POST /webhook/<path>` still returns `Cannot POST /webhook/<path>`.
   That 404 is indistinguishable from "not published". Sleep ~8 s after health before firing a test.
3. **An error workflow must itself be published.** n8n's docs say "If a workflow uses the Error Trigger
   node, you don't have to publish the workflow." In 2.40.5 that was not true here: with
   `GTMOSerrHandler1` unpublished, a failing workflow produced **no** error execution and no record.
   Publishing it and repeating the identical failure produced both. Publish 06.
4. **Import always deactivates.** `import:workflow` deactivates every workflow it touches — including ones
   already published — so publish after *every* import. `--activeState=fromJson` only works in
   multi-main/queue mode.
5. **Import upserts on the JSON `id`, and creates a duplicate without one.** All six files now carry an
   explicit top-level `id`.
6. **`n8n execute` cannot start a Schedule Trigger** (`Missing node to start execution`) and collides with
   the running server's task broker on port 5679. Hence the Execute Workflow Trigger in 03 and the
   `N8N_RUNNERS_BROKER_PORT=5699 N8N_PORT=5688` overrides.
7. **A CLI execution is a manual execution**, so it does *not* fire the error workflow. Proving 06 required
   a real production trigger — a published webhook.
8. **Retry settings are clamped**, silently: `maxTries: 10` becomes 5, `waitBetweenTries: 30000` becomes
   5 000 ms. Do not write values you think are being honoured.
9. **Do not re-serialise a signed body.** The signing Code nodes emit the exact body string and the HTTP
   nodes send it with `contentType: raw`. `JSON.stringify` on the object again downstream reorders nothing
   but re-spaces enough to break the MAC.
10. **`WEBHOOK_URL` is deprecated** from 2.35.0 in favour of `N8N_WEBHOOK_URL`, and `N8N_RUNNERS_ENABLED`
    is deprecated from 2.0. Both still show up in n8n's own startup deprecation banner.
11. **Executions prune after 14 days** (`EXECUTIONS_DATA_MAX_AGE=336` hours) — which is a reason the error
    handler writes to GTMOS rather than relying on n8n's execution list as the record of record.

---

## What belongs in n8n and what belongs in GTMOS

The dividing line is **state and judgment**.

**n8n does glue, transport and scheduling:** receiving webhooks from tools GTMOS has no native connector
for and reshaping them into a GTMOS contract; filtering noisy streams before they reach GTMOS; schedules
("every hour, check the diff"); fan-out; anything a RevOps operator should be able to change without a
deploy.

**GTMOS does everything that must be correct, repeatable or explainable:** scoring, signal decay, routing
and buying-committee logic; idempotency and dedupe (signal dedupe keys, webhook idempotency keys, workflow
-run keys enforced by unique constraints); state — which records were pushed with which payload hash
(`external_records`); retries with persisted step state and dead-lettering; audit, with an actor, a
before/after snapshot and a correlation id on every change.

Workflow 05 is the clearest illustration. n8n could implement its own dedupe with static data, and it
would be wrong the first time two deliveries raced or n8n was redeployed. Instead the batch is forwarded
untouched and GTMOS's `webhook_events.idempotency_key` unique constraint does the work.

If logic sits in an n8n Code node it is untested, unversioned alongside the product and invisible to the
audit log. That is fine for mapping a feed's field names and signing a request; it is not fine for
deciding whether an account is qualified. The Code nodes here do mapping, signing and shaping only.

---

## Security notes

- Treat n8n webhook URLs as public endpoints. Anyone who knows one can post to it. For production, put
  header or basic auth on the Webhook nodes, or restrict them at the network edge.
- 01, 03 and 06 sign with HMAC over `timestamp + "." + body`, so GTMOS verifies both origin and that the
  request was not replayed outside its 5-minute window. 02 uses the shared-token header because PostHog
  cannot compute HMACs; replay protection there comes from the idempotency key. 05 can produce a HubSpot
  v3 signature when the client secret is available, and sends none rather than a forged one when it is not.
- `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` exposes *every* environment variable to anyone who can edit a
  workflow in that instance. Run n8n with only the variables it needs and limit editor access.
- `GTMOS_ADMIN_TOKEN` lets workflow 03 trigger CRM writes. Scope the n8n instance accordingly.
- With `ENV=production` GTMOS refuses unsigned webhooks. In development, missing secrets are accepted and
  recorded as `signature: not_configured` — which is what 05 currently shows.
