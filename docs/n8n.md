# n8n Templates

`integrations/n8n/` contains four n8n workflow templates that connect GTMOS to the outside world. They are optional. GTMOS runs fully without n8n, and every endpoint they call can also be called directly.

| File | Trigger | What it does |
|---|---|---|
| `01-signal-to-gtmos.json` | Webhook `POST /webhook/gtmos-signal-intake` | Normalizes an external alert (such as a funding-news feed) into a GTMOS signal, signs it, and posts it to `/api/v1/webhooks/n8n`. |
| `02-product-event-to-gtmos.json` | Webhook `POST /webhook/gtmos-posthog` | Relays PostHog destination events, filtered to GTM-relevant ones, to `/api/v1/webhooks/posthog`. |
| `03-qualified-accounts-to-hubspot.json` | Schedule, hourly | Asks GTMOS for the reverse-ETL diff and runs the HubSpot sync only if something changed. |
| `04-crm-update-to-rescore.json` | Webhook `POST /webhook/gtmos-hubspot-change` | Rescores an account in GTMOS when a fit-relevant HubSpot company property changes. |

All four are imported inactive (`"active": false`).

## Environment variables

The templates read configuration through `$env`, so no secrets are stored in the workflow JSON.

| Variable | Used by | Value |
|---|---|---|
| `GTMOS_BASE_URL` | all | GTMOS API base URL, for example `http://api:8000` inside docker compose or `http://host.docker.internal:8010` for an API running on the host. |
| `GTMOS_WEBHOOK_SECRET` | 01, 02 | Must equal the API's `WEBHOOK_SECRET`. 01 uses it as the HMAC key; 02 sends it as `X-GTMOS-Webhook-Token`. |
| `GTMOS_ADMIN_TOKEN` | 03 | Must equal the API's `ADMIN_API_TOKEN`. Needed only when live HubSpot writes are enabled. |

Current n8n releases also restrict what Code nodes and expressions can reach. The templates need two n8n settings:

| n8n setting | Why |
|---|---|
| `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` | n8n 2.x blocks `$env` access in expressions and Code nodes unless this is set to `false`. All templates read `$env.GTMOS_*`. |
| `NODE_FUNCTION_ALLOW_BUILTIN=crypto` | Template 01's signing node calls `require('crypto')`. Code nodes may load built-in modules only when they are allow-listed. |

The `n8n` service in `docker-compose.yml` sets all of these (mapped from `WEBHOOK_SECRET`, `ADMIN_API_TOKEN` and `HUBSPOT_ACCESS_TOKEN` in `.env`, exposed to n8n as `GTMOS_WEBHOOK_SECRET`, `GTMOS_ADMIN_TOKEN` and `HUBSPOT_TOKEN`).

## Running n8n locally

```bash
make n8n        # = docker compose --profile n8n up -d n8n
open http://localhost:5678
```

The service runs `n8nio/n8n:latest` on port 5678 with a named volume (`n8ndata`) for its own state. It is in the compose `n8n` profile, so `make up` does not start it. On the compose network it reaches the API as `http://api:8000`. Start the GTMOS stack (`make up`) first.

### Importing the templates

**UI:** in n8n, open *Workflows → Import from File* and pick a JSON file from `integrations/n8n/`. Repeat for each template.

**CLI:** import all four at once:

```bash
docker compose --profile n8n run --rm -v "$PWD/integrations/n8n:/templates:ro" \
  --entrypoint n8n n8n import:workflow --separate --input=/templates
```

After importing, open each workflow, check the webhook URLs n8n shows (test vs production), and activate the ones you need.

## How each template works

### 01: External buying signal → GTMOS (signed)

1. **Signal webhook** (Webhook node, `POST gtmos-signal-intake`, responds immediately). Receives an alert from any source.
2. **Map to GTMOS signal** (Code). Maps the alert to the GTMOS `SignalIn` contract: `account_domain` ← `domain`, `signal_type` ← `type` (default `funding_round`), `title`, `explanation` ← `summary`, `source` = `n8n:<feed>`, `source_ref` ← `id`/`url`/`title`, `source_url`, `confidence` (default 0.85). `source_ref` must be stable for the real-world event, because GTMOS dedupes signals on `(type, account domain, source_ref)`. The same funding round arriving from two feeds with the same reference becomes one signal.
3. **Sign request (HMAC-SHA256)** (Code). Serializes the body once, then computes `X-GTMOS-Timestamp` (unix seconds) and `X-GTMOS-Signature = "sha256=" + hex(HMAC-SHA256(secret, ts + "." + body))`.
4. **POST to GTMOS** (HTTP Request). Sends the *exact serialized string* as a raw JSON body with both headers to `/api/v1/webhooks/n8n`. Re-serializing the object here would change the bytes and break the signature. GTMOS rejects signatures that do not match and timestamps more than 5 minutes off.

GTMOS then dedupes, stores the signal, rescores the account, and fires `signal.created` workflows (for example funding → research → draft into the approval queue). An unknown domain or signal type makes the webhook event `failed` (HTTP 202), visible and replayable on the Operations page.

### 02: PostHog product event → GTMOS

1. **PostHog destination webhook** (Webhook, `POST gtmos-posthog`). Point a PostHog webhook destination here.
2. **Keep GTM-relevant events** (Filter). Passes only `workspace_created`, `signed_up`, `teammate_invited`, `integration_connected`, `trace_volume_threshold` and `pricing_page_viewed`, so product noise never reaches GTMOS.
3. **Forward to GTMOS** (HTTP Request). Posts the event body to `/api/v1/webhooks/posthog` with `X-GTMOS-Webhook-Token` and `Idempotency-Key` set to the PostHog event `uuid`, so a re-delivery is recognized as a duplicate.

Account matching (`$groups.company`, then email domain, never free-mail), pricing aggregation and PQL detection all happen in GTMOS (see [integrations.md](integrations.md#posthog)). The filter reads `$json.body.event`, so it expects one event per request. `{"batch": [...]}` payloads are dropped by the filter; send those directly to GTMOS instead.

PostHog can also post straight to `/api/v1/webhooks/posthog` with the token header. The n8n hop is useful when you want to filter, fan out to other tools, or keep the GTMOS URL private.

### 03: Hourly A-grade accounts → HubSpot (via GTMOS reverse ETL)

1. **Every hour** (Schedule Trigger).
2. **Preview reverse-ETL diff** (HTTP GET `/api/v1/integrations/hubspot/reverse-etl/preview?limit=5`). Read-only. Returns `would_create`, `would_update` and `unchanged`.
3. **Anything changed?** (If `would_create + would_update > 0`). The false branch ends the run, so an idle hour makes no sync and writes no sync log row.
4. **Run reverse-ETL sync** (HTTP POST `/api/v1/integrations/hubspot/reverse-etl/run`, `Authorization: Bearer $GTMOS_ADMIN_TOKEN`). GTMOS does the diffing, batching, upserts on `gtmos_account_id` and retries, and returns the `integration_syncs` row.
5. **Alert on failed records** (If `records_failed > 0`). The true branch has no node yet. Connect Slack, email or a ticketing node here.

n8n owns only the schedule and the alert. Whether a record changed, how it is keyed and what retry is safe are GTMOS decisions. Without HubSpot credentials the sync goes to the demo adapter and is labeled SIMULATED.

### 04: HubSpot company change → GTMOS rescore

1. **HubSpot change webhook** (Webhook, `POST gtmos-hubspot-change`). Receives HubSpot's batched change events.
2. **Only fit-relevant properties** (Code). Keeps events whose `propertyName` is `numberofemployees`, `industry`, `country` or `domain`. GTMOS's own `gtmos_*` writes are never on that list, so a GTMOS sync cannot trigger a rescore loop.
3. **Find GTMOS account** (HTTP GET `/api/v1/accounts?q=<domain>&page_size=1`).
4. **Rescore** (HTTP POST `/api/v1/accounts/{id}/rescore`).

**How the lookup works:** HubSpot change events carry `objectId`, `propertyName` and `propertyValue`, not the company's domain. So the Code node emits the changed company ids, a HubSpot `GET /crm/v3/objects/companies/{objectId}?properties=domain,gtmos_account_id` (private-app token in `HUBSPOT_TOKEN`) fetches the domain, and GTMOS is then searched by domain. This template does not verify HubSpot's signature itself. For audited inbound changes, point the HubSpot subscription at GTMOS's `/api/v1/webhooks/hubspot`, which verifies `X-HubSpot-Signature-v3` and logs every event, and use this workflow only for the rescore reaction.

## What belongs in n8n and what belongs in GTMOS

The dividing line is **state and judgment**.

**n8n does glue, transport and scheduling:**
- receiving webhooks from tools GTMOS has no native connector for (news feeds, form tools, Slack commands) and reshaping them into a GTMOS contract;
- filtering noisy streams before they reach GTMOS;
- schedules ("every hour, check the diff");
- fan-out and notifications (post the failed-sync alert to Slack, open a ticket);
- anything a RevOps operator should be able to change without a deploy.

**GTMOS does everything that must be correct, repeatable or explainable:**
- scoring, signal decay, routing and buying-committee logic, which are versioned, tested and explained per component;
- idempotency and dedupe (signal dedupe keys, webhook idempotency keys, workflow-run keys enforced by unique constraints);
- state: which records were pushed and with which payload hash (`external_records`), and which runs already succeeded;
- retries with persisted step state and dead-lettering;
- audit: every change carries an actor, a before/after snapshot and a correlation id.

If logic sits in an n8n Code node, it is untested, unversioned alongside the product and invisible to the audit log. That is acceptable for mapping a feed's field names and not acceptable for deciding whether an account is qualified. The templates keep their Code nodes to field mapping and signing.

## Security notes

- Treat n8n webhook URLs as public endpoints. Anyone who knows them can post. For production, put authentication on the Webhook nodes (header auth or basic auth) or restrict them at the network edge.
- Template 01 signs with HMAC over timestamp and body, so GTMOS can verify both that the request came from the n8n instance and that it was not replayed outside the 5-minute window. Template 02 uses the shared-token header because PostHog cannot compute HMACs. That authenticates the sender but does not protect against replay, and GTMOS relies on the idempotency key for that.
- Keep `GTMOS_WEBHOOK_SECRET` and `GTMOS_ADMIN_TOKEN` in the n8n environment, not in node parameters. Setting `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` exposes *every* environment variable to anyone who can edit workflows in that n8n instance, so run it with only the variables it needs and limit editor access.
- `GTMOS_ADMIN_TOKEN` lets template 03 trigger live CRM writes. Scope the n8n instance accordingly.
- With `ENV=production`, GTMOS refuses unsigned webhooks. In development, missing secrets are accepted and recorded as `signature: not_configured`.

## What was verified

Templates were imported with `n8n import:workflow` into n8n 2.40.5 (`n8nio/n8n:latest`, CLI import with `--separate` of all four files: "Successfully imported 4 workflows"). That confirms the JSON is valid for n8n and that every node type and version resolves. It does **not** confirm runtime behavior: the workflows have not been executed end to end against a running GTMOS instance, and nothing has been tested against real PostHog or HubSpot deliveries. The two n8n settings above were confirmed by reading the n8n 2.40.5 source, not by running the Code nodes. Before relying on template 01, send one test alert and confirm the event shows `signature: valid` in `GET /api/v1/webhooks/events?source=n8n`.
