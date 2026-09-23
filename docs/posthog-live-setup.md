# Connecting GTMOS to a real PostHog

**Status: NOT verified against a live PostHog project.** No PostHog account exists for this project and
no request has ever been made to `posthog.com`, `us.i.posthog.com` or `us.posthog.com` from this
codebase. The parser, the identity resolution, the PQL rule and the webhook pipeline are implemented and
exercised locally against PostHog's documented payload shapes — see
[`docs/research/posthog.md`](research/posthog.md), which is where every factual claim below comes from.
The last section says exactly which parts are unproven.

> **Read this before you build anything.** **Group analytics — the feature that makes an event an
> *account* fact rather than a user fact — is a paid add-on.** It is not on the no-card Free plan. You
> enable it from the billing page, which requires a card on file. Within the first 1,000,000
> events/month the bill is **$0**, but the add-on's meter then counts **all identified events in the
> project**, not only the ones carrying `$groups`. Without it you cannot answer "how many people from
> this company are active", which is the only question GTMOS asks PostHog. Budget the friction, not the
> dollars. (`docs/research/posthog.md` §3.5, §9.)
>
> A second, weaker caveat, flagged so you meet it now rather than after wiring: the **HTTP Webhook**
> destination template is `free: false` in PostHog's source while the Slack template is `free: true`,
> and "Data pipelines" is listed among the features absent from the free tier. No prose doc states the
> gating. **UNCONFIRMED** — §4 gives you a path that works either way.

---

## 1. Choose an environment

| Option | Cost | Good for | Caveats |
|---|---|---|---|
| **PostHog Cloud US** ← recommended | Free plan: 1,000,000 events/month, 1 project, 1-year retention | Exactly this | Group analytics is a paid add-on on top (see above). Ingest host `us.i.posthog.com`, read host `us.posthog.com` — they are different hosts |
| PostHog Cloud EU | Same allowances | EU data residency | `eu.i.posthog.com` / `eu.posthog.com`. Otherwise identical |
| Self-hosted (docker-compose) | Free, MIT | Nothing in this integration | **Not viable. Do not do this.** |

**Why self-hosting is not recommended here**, stated plainly because it is the first thing an engineer
reaches for:

1. **The two features this integration needs are the two PostHog names as absent from self-hosted.** The
   open-source disclaimer lists **Group analytics** and **Data pipelines** in the "what you lose" list.
   Group analytics is how an event carries an account key; data pipelines is how an event leaves PostHog
   for GTMOS. A local instance can ingest and chart events and cannot do either of those, so it cannot
   exercise the integration's actual surface.
2. **The box.** "4 vCPU, 16GB RAM, and more than 30GB storage", running ClickHouse, Kafka, Zookeeper,
   Redis, Postgres and MinIO. That is not a sidecar next to an existing dev stack.
3. **It is officially unsupported.** No tagged releases, no CVE process, no commercial support:
   "every change, including security fixes, ships continuously from `master`".

PostHog's own decision flowchart terminates anyone under 1M events/month at "You'll probably be better
off with PostHog Cloud."

**If you want to develop with no PostHog account at all**, skip to §7.1: GTMOS's endpoint takes the
documented PostHog payload shape from any sender, so `curl` and the n8n template reproduce the contract
faithfully. That is what the golden flow does (`make golden-flow`).

## 2. Create the project and find the two keys

Sign up at `us.posthog.com`, which creates an organization and a project. Then **Settings → Project →
Project ID** and **Project API key**.

PostHog has two keys that do different jobs and are constantly confused for each other:

| Key | Prefix | Where you find it | Can write events? | Can read data? | Is it a secret? |
|---|---|---|---|---|---|
| **Project API key** (project token) | `phc_` | Settings → Project → Project API key | Yes — it is the only thing `/i/v0/e/` accepts | **No** | **No.** Public endpoints return nothing sensitive; it ships in browsers |
| **Personal API key** | `phx_` | Settings → User → Personal API keys → Create | No | Yes, `Authorization: Bearer …` | **Yes.** Org-wide blast radius unless you scope it |

**Which one GTMOS needs, and for what:**

- **Neither, for the integration to work.** GTMOS never calls PostHog. Events arrive at GTMOS; GTMOS
  does not fetch them. There is no `POSTHOG_*` setting in `apps/api/src/gtmos/config.py`, and that is
  deliberate — the ingestion contract should not depend on who is calling it.
- **The project API key** (`phc_`) goes wherever your product emits events, and into any script that
  replays events for testing. It is not a secret, so it can live in an n8n node or a shell profile.
- **A personal API key** (`phx_`) is needed only by **you**, for the verification in §7.2 — reading the
  event back out of PostHog to prove it was actually stored. Create it with the **Query Read** scope and
  nothing else. Max 10 personal keys per user.

> Capture returns `200` for events it silently drops (no event name, empty `distinct_id`) and `200` when
> the project is over quota. Asserting on HTTP status proves the request was well-formed and nothing
> else. That is the entire reason §7.2 exists.

## 3. Create the `company` group type and attach it to events

GTMOS resolves an event to an account from `properties.$groups.company`
(`apps/api/src/gtmos/integrations/posthog.py::normalize`). Two hard requirements:

1. **The group type must literally be named `company`.** `normalize` reads `groups.get("company")`.
   Another name resolves to `None` and the event falls back to email-domain matching. Group types are a
   scarce, schema-level resource: **maximum 5 per project**, and you can delete a type but not an
   individual group.
2. **The group key must be the account's domain as GTMOS stores it**, lower-cased and bare —
   `kestrel-analytics.example`, not `Kestrel Analytics`, not a UUID. `_known_domains` in
   `apps/api/src/gtmos/services/product_events.py` looks the key up against `accounts.domain`, and
   `normalize_domain` strips scheme, `www.`, path, port and case. PostHog's own docs suggest
   `company_id_in_your_db` as the key; **for GTMOS it must be the domain**, or nothing matches.

Create the group once, before any event references it — `$groups` on a normal event does **not** create
a group:

```bash
curl -sL -H "Content-Type: application/json" -d '{
  "api_key": "'"$POSTHOG_PROJECT_API_KEY"'",
  "event": "$groupidentify",
  "distinct_id": "gtmos-groups-setup",
  "properties": {
    "$group_type": "company",
    "$group_key": "kestrel-analytics.example",
    "$group_set": {"name": "Kestrel Analytics", "domain": "kestrel-analytics.example"}
  }
}' https://us.i.posthog.com/i/v0/e/
```

`$group_set` **must be a plain JSON object** — strings, numbers, booleans and arrays make PostHog
discard the whole `$groupidentify`. Always set `name`: the UI falls back to the raw key without it.

Then every product event carries the group:

```bash
curl -sL -H "Content-Type: application/json" -d '{
  "api_key": "'"$POSTHOG_PROJECT_API_KEY"'",
  "event": "integration_connected",
  "distinct_id": "usr_8f21c0",
  "properties": {
    "$groups": {"company": "kestrel-analytics.example"},
    "email": "priya.raman@kestrel-analytics.example"
  }
}' https://us.i.posthog.com/i/v0/e/
```

Three things GTMOS cares about in that body:

- **`$groups.company`** — the account key, confidence 0.98 in `match_to_account`.
- **`properties.email`** (or `$email`) — used to resolve the *contact* inside the account, and as the
  fallback account key at confidence 0.9 when `$groups` is absent. Free-mail domains
  (19 of them, `domain/matching.py::FREE_MAIL_DOMAINS`) never match an account.
- **`distinct_id`** — carried onto the engagement row and counted toward `distinct_users` in the PQL
  rule when no contact resolves. Mint an opaque server-side ID. Do not use an email or a domain: PostHog
  silently rejects a blocklist of placeholder distinct IDs during merges, and merges of already-identified
  profiles are refused outright.

**Event names matter.** Only these become GTMOS signals
(`integrations/posthog.py::EVENT_SIGNAL_MAP` and `PRICING_EVENTS`):

| PostHog event | GTMOS signal type |
|---|---|
| `workspace_created`, `signed_up` | `product_signup` |
| `teammate_invited` | `teammate_invited` |
| `integration_connected` | `integration_activated` |
| `trace_volume_threshold` | `usage_threshold` |
| `pricing_page_viewed` | `pricing_page_visit`, but only at ≥ 2 views in 7 days, and at most one per account-week |

Anything else is stored as an `Engagement` row and counts toward the PQL window, but creates no signal
and moves no score. That is intentional: treating every event as a signal drowns the score in noise.

## 4. Configure the outbound path to GTMOS

Two options. Pick **B** unless you have a reason not to.

### Option A — PostHog destination straight to GTMOS

**Data pipelines → + New → Destination → search "Webhook" → + Create.**

| Field | Value |
|---|---|
| **URL** | `https://<your-host>/api/v1/webhooks/posthog` |
| **Method** | `POST` |
| **Headers** | `Content-Type: application/json`, `X-GTMOS-Webhook-Token: <WEBHOOK_SECRET>` |
| **Body** | the JSON in §5 |
| **Filters** | restrict to the six event names in §3. This is also what keeps the trigger-event meter small |

Then **Create & Enable**. There is a built-in **Testing** panel and a **Log responses** debug toggle;
use both.

The endpoint must be publicly reachable. For local development:

```bash
ngrok http 8010
# destination URL becomes https://<subdomain>.ngrok-free.app/api/v1/webhooks/posthog
```

PostHog's outbound IPs, if you allowlist instead: US `44.205.89.55`, `52.4.194.122`, `44.208.188.173`;
EU `3.75.65.221`, `18.197.246.42`, `3.120.223.253`.

**The honest caveat.** The HTTP Webhook destination template is marked `free: false` in PostHog's source
while the Slack template is `free: true`, and the self-host disclaimer lists "Data pipelines" among the
things absent from the free tier. No prose documentation states this gating anywhere, so it is recorded
as **UNCONFIRMED**. If you are on the no-card Free plan, **try to create the destination before you
design around it** — that one click settles the question. On the paid pay-as-you-go plan ($0/mo base,
card on file) realtime destinations carry a 10,000 trigger-event/month free allowance, so the bill is
still $0 at demo scale.

PostHog signs with the [Standard Webhooks](https://www.standardwebhooks.com) spec when you set a
`signing_secret`. **GTMOS does not verify that scheme.** It verifies its own HMAC
(`X-GTMOS-Signature` over `{timestamp}.{body}`) or a shared token
(`X-GTMOS-Webhook-Token`), and PostHog can only produce the former by hand-writing the Hog source. Use
the token header, and know that a token authenticates the sender but does not protect against replay —
GTMOS relies on the idempotency key for that (`services/webhook_service.py`).

### Option B — via the existing n8n workflow (recommended)

`integrations/n8n/02-product-event-to-gtmos.json` already implements this hop. Point the PostHog
destination at n8n instead:

| Field | Value |
|---|---|
| **URL** | `https://<your-n8n-host>/webhook/gtmos-posthog` |
| **Method** | `POST` |
| **Headers** | `Content-Type: application/json` |
| **Body** | the JSON in §5 |

The workflow is three nodes:

1. **PostHog destination webhook** — `POST gtmos-posthog`, `responseMode: onReceived`. It answers
   immediately, which matters: PostHog retries a non-2xx **up to 3 times** and quarantines then
   auto-disables a destination that is sustainedly slow or failing.
2. **Keep GTM-relevant events** — a Filter passing only `workspace_created`, `signed_up`,
   `teammate_invited`, `integration_connected`, `trace_volume_threshold`, `pricing_page_viewed`.
3. **Forward to GTMOS** — `POST {{$env.GTMOS_BASE_URL}}/api/v1/webhooks/posthog` with
   `X-GTMOS-Webhook-Token: {{$env.GTMOS_WEBHOOK_SECRET}}` and `Idempotency-Key: {{$json.body.uuid}}`.

Why B is better: you get server-side filtering you can change without a deploy, the GTMOS URL stays
private, and if the HTTP Webhook template does turn out to be plan-gated, the n8n leg is the half you
can keep and test on its own. The cost: one more hop that can be down, and `/webhook-test/` only fires
while the n8n editor is open — `/webhook/` is the real path, and this catches everybody once.

The filter reads `$json.body.event`, so it expects **one event per request**. A `{"batch": [...]}`
payload is dropped by the filter; send batches straight to GTMOS, which does parse them.

See [`docs/n8n.md`](n8n.md) for import instructions and the two n8n settings the templates need
(`N8N_BLOCK_ENV_ACCESS_IN_NODE=false`, `NODE_FUNCTION_ALLOW_BUILTIN=crypto`).

## 5. The exact payload GTMOS parses

`POST /api/v1/webhooks/posthog`, `Content-Type: application/json`. Parsed by
`integrations/posthog.py::parse_payload` and `::normalize`.

```json
{
  "event": "integration_connected",
  "uuid": "0192f3a1-6b4c-7c2e-9a1f-0b2c3d4e5f60",
  "distinct_id": "usr_8f21c0",
  "timestamp": "2026-09-22T12:00:00Z",
  "properties": {
    "$groups": {"company": "kestrel-analytics.example"},
    "email": "priya.raman@kestrel-analytics.example",
    "$current_url": "https://app.sentinel.example/settings/integrations",
    "integration": "snowflake"
  }
}
```

Three shapes are accepted: a single object, a JSON array of them, or `{"batch": [...]}`.

| Field | Required | What GTMOS does with it |
|---|---|---|
| `event` | **yes** | 1–120 chars. Looked up in `EVENT_SIGNAL_MAP` / `PRICING_EVENTS` |
| `uuid` | no, but send it | Becomes the event id, the webhook idempotency key (`posthog:<uuid>`) and the engagement `dedupe_key`. Without it the id is synthesised as `{event}:{distinct_id}:{timestamp}`, which is stable only if the timestamp is |
| `distinct_id` | no | ≤ 320 chars. Stored on the engagement; counted in `distinct_users` when no contact resolves; used as an email fallback if it contains `@` |
| `timestamp` | no | ISO 8601. A naive timestamp is read as UTC. Absent → receipt time |
| `properties.$groups.company` | no, but it is the point | The account key. Must be the account domain |
| `properties.email` / `$email` | no | Contact resolution, and the fallback account key |
| everything else in `properties` | no | Stored on the engagement, **except** keys beginning `$` — only `$current_url` and `$pathname` survive |

Headers GTMOS reads: `X-GTMOS-Webhook-Token` (or `X-GTMOS-Signature` + `X-GTMOS-Timestamp`),
`Idempotency-Key` / `X-Idempotency-Key`. Bodies over **1 MB** are rejected with `413` — well under
PostHog's own 20 MB request ceiling, so a large `/batch/` relay will hit the GTMOS limit first.

Responses: `200` processed, `200` with `"duplicate": true` on a redelivery, `202` if the payload was
stored but processing failed (visible and replayable on the Operations page), `400` non-JSON body,
`401` bad signature or token, `413` oversized.

## 6. Environment variables

GTMOS side, in `.env` at the repo root (git-ignored). Restart the API after changing it.

| Variable | Where | Why |
|---|---|---|
| `WEBHOOK_SECRET` | GTMOS API | The value PostHog or n8n sends as `X-GTMOS-Webhook-Token`. Also the HMAC key for `X-GTMOS-Signature`. Unset in development → events are accepted and recorded `signature: not_configured` |
| `ENV=production` | GTMOS API | Makes a missing secret a **rejection** instead of a warning. Set this before you expose the endpoint |

n8n side (Option B), set in the container environment, not in node parameters:

| Variable | Why |
|---|---|
| `GTMOS_BASE_URL` | e.g. `http://host.docker.internal:8010` for an API on the host, `http://api:8000` inside compose |
| `GTMOS_WEBHOOK_SECRET` | Must equal the API's `WEBHOOK_SECRET` |

Your shell, for the verification steps only. **None of these is read by GTMOS**:

| Variable | Why |
|---|---|
| `POSTHOG_PROJECT_API_KEY` | `phc_…`, to emit test events at `https://us.i.posthog.com/i/v0/e/` |
| `POSTHOG_PERSONAL_API_KEY` | `phx_…`, Query Read scope, to read events back from `https://us.posthog.com` |
| `POSTHOG_PROJECT_ID` | The numeric project id in the read-API path |

## 7. Verify

### 7.1 Prove the GTMOS half, with no PostHog account

This works today and is the half that is actually tested. Post the documented shape directly:

```bash
curl -s -X POST localhost:8010/api/v1/webhooks/posthog \
  -H 'Content-Type: application/json' \
  -H "X-GTMOS-Webhook-Token: $WEBHOOK_SECRET" \
  -d '{
    "event": "integration_connected",
    "uuid": "verify-ph-001",
    "distinct_id": "priya.raman@kestrel-analytics.example",
    "timestamp": "2026-09-22T12:00:00Z",
    "properties": {
      "$groups": {"company": "kestrel-analytics.example"},
      "email": "priya.raman@kestrel-analytics.example",
      "integration": "snowflake"
    }
  }' | jq
```

Then read back what GTMOS did with it — this is the assertion that matters:

```bash
curl -s "localhost:8010/api/v1/webhooks/events?source=posthog&limit=1" \
  | jq '.items[0] | {status, signature_status, idempotency_key,
                     matched: .result.matched,
                     signals_created: .result.signals_created,
                     match_reason: .result.results[0].match_reason}'
```

A working delivery looks like this. The `status`, `signature_status`, `matched`, `signals_created` and
`match_reason` values are taken from a real `integration_connected` delivery recorded in the local
stack; the idempotency key is what this body produces (no `Idempotency-Key` header, so the event `uuid`
is prefixed with the source):

```json
{
  "status": "processed",
  "signature_status": "valid",
  "idempotency_key": "posthog:verify-ph-001",
  "matched": 1,
  "signals_created": 1,
  "match_reason": "Company group key 'kestrel-analytics.example' matches a known account."
}
```

Send **the identical body a second time**. The response carries `"duplicate": true`, no second
engagement row is written, and `duplicate_count` increments on the stored event. Then confirm the signal
and the score:

```bash
curl -s "localhost:8010/api/v1/signals?type=integration_activated&days=1&limit=3" \
  | jq '.items[] | {account_name, signal_type, source, confidence, title}'

curl -s "localhost:8010/api/v1/accounts/<account-id>" | jq '.account | {icp_score, score_grade}'
```

Finally, the whole chain in one command, including the PQL rule firing and the CRM hop:

```bash
make golden-flow             # 20 steps, direct to the API
make golden-flow VIA_N8N=1   # same, but the three product events go through the n8n container
```

`VIA_N8N=1` posts to `http://localhost:5678/webhook/gtmos-posthog`, which is the exact URL a PostHog
destination would target. That is as close to a live PostHog as this project gets.

### 7.2 Prove the PostHog half, once you have a project

Capture returns `200` for dropped and over-quota events alike, so the only real assertion is a read-back
through the query API, on the **private** host:

```bash
curl -s -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \
  "https://us.posthog.com/api/projects/$POSTHOG_PROJECT_ID/query/" \
  -d '{"query":{"kind":"HogQLQuery","query":"select event, distinct_id, properties.$groups, timestamp from events where timestamp > now() - interval 1 hour order by timestamp desc limit 10"}}' | jq
```

And that the group itself exists:

```bash
curl -s -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \
  "https://us.posthog.com/api/projects/$POSTHOG_PROJECT_ID/groups_types/" | jq
curl -s -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \
  "https://us.posthog.com/api/projects/$POSTHOG_PROJECT_ID/groups/?group_type_index=0" | jq
```

If the event is not there, check **Data management → Ingestion warnings** — it is the only feedback
channel for silently dropped events.

### 7.3 Prove the destination fired

In PostHog: **Data pipelines → your destination → Logs**, with the **Log responses** toggle on. You are
looking for a 2xx from GTMOS. A 4xx is not counted against the destination's health; sustained 5xx or
slowness quarantines and then auto-disables it.

## 8. What to expect to go wrong

Ranked by how often it should actually happen:

1. **Nothing matches an account.** Almost always the group key. It must be the bare lower-cased domain
   that is in `accounts.domain`, and the group type must be named `company`. Check
   `result.results[0].match_reason` on the stored webhook event — it says which rule fired or why none did.
2. **Wrong host.** `us.i.posthog.com` writes, `us.posthog.com` reads. A read that 404s or a write that
   401s is this, roughly every time.
3. **Events accepted and never stored.** A `200` from capture means the request parsed. Empty
   `distinct_id`, no event name, over quota (`quota_limited` in the body) and >1 MB post-processing all
   drop silently. Read them back.
4. **The destination will not create.** The `free: false` question in §4. Try it early.
5. **`$groupidentify` discarded** because `$group_set` was not a plain object.
6. **Person properties land out of order.** They are applied in *ingestion* order, not timestamp order,
   so a retry or backfill can write a stale value last. GTMOS does not read person properties for this
   reason, but anything you build on them inherits the problem.
7. **Rate limits on the read side only.** `/query` is 2400/hour and draws on a per-project hourly *byte*
   budget (`429` with `api_queries_budget_exceeded`). The capture endpoints have no request-level rate
   limit, but one `distinct_id` over ~5,000 events/minute is rerouted and stops updating person profiles.

## What is still not implemented

Being explicit, because a setup guide that implies completeness is worse than none:

- **None of §2, §3, §4 or §7.2 has been run.** No PostHog project exists. Those sections are transcribed
  from PostHog's current documentation via `docs/research/posthog.md`, not from a screen anyone looked
  at. Specifically unproven: that the HTTP Webhook destination can be created on a given plan; that its
  templated body produces exactly the bytes in §5; that a `company` group type survives the UI the way
  §3 describes; that the query API returns what §7.2 expects.
- **What *is* proven** is everything downstream of the HTTP request: payload parsing of all three
  shapes, group-key and email-domain matching, free-mail rejection, subdomain fallback, engagement
  dedupe on `posthog:<event_id>`, the pricing-view threshold, the PQL rule, signal creation and
  rescoring, and webhook idempotency — unit and integration tested, and executed end to end by
  `make golden-flow`, including `VIA_N8N=1` through the real n8n container.
- **PostHog's Standard Webhooks signature is not verified.** GTMOS accepts its own HMAC or a shared
  token. A token can be replayed if it leaks; only the idempotency key limits the damage. Putting the
  endpoint behind an allowlist, or behind n8n signing with the GTMOS HMAC, is the fix and is not done.
- **Webhook processing is inline, not queued.** GTMOS parses, matches, scores and may run workflows
  inside the request. PostHog expects a timely non-5xx and retries 3 times before quarantining. Under
  load this is the first thing that breaks; acknowledge at the edge and process on a queue.
- **One delivery is one row.** A `{"batch": [...]}` payload is parsed into many events but stored as a
  single `webhook_events` row, so a partial failure fails the whole delivery.
- **`$groupidentify` is not consumed.** GTMOS reads `$groups` off ordinary events and ignores group
  *properties* entirely. Group property changes in PostHog do not reach the account record; enrichment
  is Clay's job here (`docs/clay-live-setup.md`).
- **Nothing is read back from PostHog.** There is no query-API client, no reconciliation, and no check
  that the events GTMOS holds match the events PostHog holds. Given that capture returns `200` for
  dropped events, that is the most valuable missing piece.
- **No `$identify` or `$create_alias` handling.** Identity merges inside PostHog are invisible to GTMOS;
  an account's `distinct_users` count can therefore double-count one person who was merged after the fact.
