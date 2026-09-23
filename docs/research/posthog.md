# PostHog — factual reference for the GTMOS integration

Research date: **2026-09-22**. Sources are `posthog.com/docs`, `posthog.com/pricing`,
`posthog.com/handbook` and the `PostHog/posthog` / `PostHog/posthog-js` repositories on GitHub.
Anything not confirmable from those is marked **UNCONFIRMED**.

Practical note: **append `.md` to any `posthog.com` path** to get clean markdown
(`curl -sL https://posthog.com/docs/api/capture.md`). The full LLM index is
<https://posthog.com/llms.txt>.

PostHog does not version its docs or its product — "PostHog doesn't have versions: self-hosted
deployments are officially unsupported, and every change, including security fixes, ships
continuously from `master`"
([self-host disclaimer](https://posthog.com/docs/self-host/open-source/disclaimer.md)). So there
is no version number to record; everything below is "as of 2026-09-22".

---

## 0. Executive summary for this project

| Question | Answer |
|---|---|
| Ingest endpoint | `https://us.i.posthog.com/i/v0/e/` (single), `/batch/` (batch). **Not** `/capture/` any more |
| Auth to write | project API key (`phc_…`) in the JSON body as `api_key` — public, write-only |
| Auth to read | **personal API key** (`phx_…`), `Authorization: Bearer …` |
| Account/company grouping | `$groupidentify` + `$groups` on events; **max 5 group types per project** |
| Group analytics cost | **Paid add-on**, enabled on the billing page. First 1M events/month $0, but enabling it makes **all identified events** in the project billable |
| Event → external URL | CDP **HTTP Webhook** destination. Fully customisable method/URL/body/headers, Hog + Liquid templating, optional Standard Webhooks signing |
| Webhook destination cost | Realtime destinations: first **10,000 trigger events/month free**. But the HTTP Webhook template is `free: false` in source (Slack is `free: true`) → likely requires the paid $0-base plan. **UNCONFIRMED in prose docs** |
| Self-hosting | docker-compose only, "officially unsupported", **4 vCPU / 16 GB RAM / 30 GB+ disk**, and **group analytics and data pipelines are explicitly absent from it** |
| Blocker for a local integration | Yes — self-hosted PostHog cannot do the two things this integration needs. Use Cloud |

---

## 1. Event ingestion

### 1.1 Endpoints

The documented paths are **`/i/v0/e/`** (single event) and **`/batch/`** (batch). The string
`/capture` no longer appears as a path anywhere in the current docs
([capture API](https://posthog.com/docs/api/capture.md)).

> "Make sure to send API requests to the correct domain. These are `https://us.i.posthog.com`
> for US Cloud, `https://eu.i.posthog.com` for EU Cloud, and your self-hosted domain for
> self-hosted instances."

| Target | Ingestion host | Single event | Batch |
|---|---|---|---|
| US Cloud | `https://us.i.posthog.com` | `https://us.i.posthog.com/i/v0/e/` | `https://us.i.posthog.com/batch/` |
| EU Cloud | `https://eu.i.posthog.com` | `https://eu.i.posthog.com/i/v0/e/` | `https://eu.i.posthog.com/batch/` |
| Self-hosted | your domain | `https://<domain>/i/v0/e/` | `https://<domain>/batch/` |

The **read** (private) API lives on a *different* host: `https://us.posthog.com` /
`https://eu.posthog.com` ([API overview](https://posthog.com/docs/api.md)). Mixing the two up
is the first thing to check when a read 404s or a write 401s.

The legacy `/capture/` path still routes and returns `200` in practice, but it is absent from
all current documentation — treat it as **UNCONFIRMED / unsupported** and use `/i/v0/e/`.

### 1.2 Single-event body

`POST`, `Content-Type: application/json`:

```json
{
  "api_key": "<ph_project_api_key>",
  "event": "event name",
  "distinct_id": "user distinct id",
  "properties": { "account_type": "pro" },
  "timestamp": "[optional timestamp in ISO 8601 format]"
}
```

> "Every event request must contain an `api_key`, `distinct_id`, and `event` field with the
> name. Both the `properties` and `timestamp` fields are optional."

`distinct_id` belongs at the **top level**. PostHog also reads `properties.distinct_id` as a
fallback, and "the top level wins if both are set. This applies to every event in this
reference, including `$groupidentify`, `$identify`, and `$create_alias`."

**Events sent via the API are identified by default.** To capture anonymously, set
`properties.$process_person_profile: false`; anonymous events "can be up to 4x cheaper"
([anonymous vs identified](https://posthog.com/docs/data/anonymous-vs-identified-events.md)).
This matters for billing under group analytics — see §3.4.

### 1.3 Batch body

```json
{
  "api_key": "<ph_project_api_key>",
  "historical_migration": false,
  "batch": [
    { "event": "batched_event_name_1",
      "properties": { "distinct_id": "user distinct id", "account_type": "pro" },
      "timestamp": "[optional ISO 8601]" },
    { "event": "batched_event_name_2",
      "properties": { "distinct_id": "user distinct id" } }
  ]
}
```

- "There is no limit on the number of events you can send in a batch, but the entire request
  body must be less than 20MB by default."
- Inside `batch[]`, `distinct_id` goes in `properties`.
- `historical_migration: true` is required for backfills: "This ensures that events are
  processed in order without triggering our spike detection systems."

### 1.4 Response codes

From [API responses](https://posthog.com/docs/api.md#responses):

| Code | Body | Meaning |
|---|---|---|
| `200` | `{"status": "Ok"}` | Payload received, format correct, project token valid. **"It does not imply that events are valid and will be ingested."** |
| `400` | `{"type":"validation_error","code":"invalid_project",...}` or `{"code":"invalid_payload","detail":"Malformed request data"}` | |
| `401` | `{"type":"authentication_error","code":"invalid_api_key",...}` / `"invalid_personal_api_key"` | |
| `503` | — | Marked **(Deprecated)**; self-hosted Postgres instances only |

Two traps:

1. **Events with no name, no `distinct_id`, or an empty `distinct_id` are dropped silently with
   a `200`.** There is no synchronous validation. The only feedback channel is the **ingestion
   warnings** page ([ingestion warnings](https://posthog.com/docs/data/ingestion-warnings.md)).
2. **Over billing quota, capture still returns `200`** and "names the limited resources in the
   `quota_limited` field of the response body."

So an integration test that asserts on HTTP status proves almost nothing. Assert by reading the
event back through the query API (§6).

### 1.5 Size and value limits

| Limit | Value | Source |
|---|---|---|
| POST body | **20 MB** (`DATA_UPLOAD_MAX_MEMORY_SIZE`) | [api.md#tips](https://posthog.com/docs/api.md) |
| Single event after processing | discarded if **> 1 MB** | [ingestion warnings](https://posthog.com/docs/data/ingestion-warnings.md) |
| `distinct_id` | **200 chars** — truncated, event still ingested, warning logged | same |
| `$group_type`, `$group_key` | **400 chars each** | [group analytics](https://posthog.com/docs/product-analytics/group-analytics.md) |
| Person properties, total per person | **512 KB** | [person properties](https://posthog.com/docs/product-analytics/person-properties.md) |
| Per-`(project, distinct_id)` throughput | ~**5,000 events/minute** before overflow rerouting | [ingestion pipeline](https://posthog.com/docs/how-posthog-works/ingestion-pipeline.md) |

That last one is worth reading carefully: over ~5k/min for one distinct ID, events are still
accepted with a `200` "but are processed without strict ordering and **without person profile
updates** for the duration of the spike." A batch backfill keyed to one synthetic distinct ID
will silently stop updating person properties.

---

## 2. Identity

The framing in [identity resolution](https://posthog.com/docs/product-analytics/identity-resolution.md):

> "PostHog doesn't know your users. It knows **entities** tagged with a `distinct_id` and
> properties. It can merge what you tell it to merge. It can't resolve identity for you."

Recommended strategy: "Assign a durable ID the moment you first see a user. This ID never
changes… mint the ID in a stable place – ideally your server."

### 2.1 `$identify` over the API is not the SDK's `identify()`

Explicit callout in [capture API](https://posthog.com/docs/api/capture.md#identify):

> "The `$identify` event works differently from the `identify()` method in the JavaScript SDK.
> This event **updates the person properties**, while the JavaScript `identify()` method
> connects an anonymous user and a distinct ID."

```json
{"api_key":"...","event":"$identify","distinct_id":"user distinct id",
 "properties":{"$set":{"is_cool":"true"}},"timestamp":"2020-08-16T09:03:11.913767"}
```

So server-side `$identify` does **not** merge anything. For a server-first GTM integration,
this is the desirable behaviour — you are just setting person properties.

### 2.2 Anonymous vs identified

A person profile is created only for identified events. The frontend default is
`person_profiles: 'identified_only'`; `'always'` forces profiles. Backend SDKs and the raw API
default to **identified**. `$anon_distinct_id` is the property posthog-js emits on the
identity-change event (`{ distinct_id: new, $anon_distinct_id: previous }`, confirmed in
[posthog-js source](https://github.com/PostHog/posthog-js/blob/main/packages/browser/src/posthog-core.ts));
its contract as a raw-API field is **UNCONFIRMED by prose docs**.

### 2.3 Alias

```json
{"api_key":"...","event":"$create_alias","distinct_id":"123","properties":{"alias":"456"}}
```

> "In this example, `123` is merged into `456` and `456` becomes the main `distinct_id`."

SDK form is `posthog.alias('backend_id', 'frontend_id')` — "This will merge all past and future
events into the same user." `$merge_dangerously` exists for repairing duplicates and carries its
own warning: "Merging users with `$merge_dangerously` is irreversible and has no safeguards!…
we don't recommend you merge users frequently, but rather as a one-off for recovering from
implementation problems."

### 2.4 Re-identification warnings — read before designing IDs

- "We do not allow identifying a user that has already been identified with a different distinct
  ID." ([identify](https://posthog.com/docs/product-analytics/identify.md))
- "When PostHog can't merge two already-identified profiles, it blocks the merge and logs a
  'Refused to merge an already identified user' ingestion warning."
  ([persons](https://posthog.com/docs/data/persons.md))
- A blocklist of distinct IDs is **silently rejected during merges**: `null`, `undefined`,
  `None`, `0`, `anonymous`, `guest`, `distinct_id`, `id`, `email`, `true`, `false`,
  `[object Object]`, `NaN`, empty strings and quoted variants. "person merges will fail
  silently. You'll end up with split identities and no error message."
- After a merge, "events keep their original `distinct_id` – it's never rewritten. The merge
  updates the `person_id` mapping."

**Design implication for GTMOS:** never use an email or a domain as a `distinct_id`, and never
let a null/placeholder leak into one. Mint an opaque server-side ID and carry the domain as a
property.

---

## 3. Groups — the critical piece for B2B GTM

Canonical page: [group analytics](https://posthog.com/docs/product-analytics/group-analytics.md).

### 3.1 Model

**Group types** are categories you define — "company", "project", "workspace". **Groups** are
individual instances within a type, keyed by `$group_key`. An event is linked to a group by the
`$groups` property.

### 3.2 The hard limit: 5 group types per project

Stated three times on the page, verbatim:

- "You can create up to 5 group types per project"
- "Each project can have up to 5 group types"
- Under **Limitations**: "Maximum of 5 group types per project"

Individual groups within a type are unlimited. Deleted group types do not count toward the 5.
For GTMOS this is not binding — one `company` type is enough — but it does mean group types are
a scarce, schema-level resource you should not spend casually, and **you can delete a group type
but not an individual group**.

### 3.3 Creating / updating a group: `$groupidentify`

```bash
curl -L -H "Content-Type: application/json" -d '{
  "api_key": "<ph_project_api_key>",
  "event": "$groupidentify",
  "distinct_id": "groups_setup_id",
  "properties": {
    "$group_type": "company",
    "$group_key": "company_id_in_your_db",
    "$group_set": {
      "name": "Acme Inc",
      "subscription": "premium",
      "date_joined": "[optional ISO 8601]"
    }
  }
}' https://us.i.posthog.com/i/v0/e/
```

Required properties: **`$group_type`**, **`$group_key`**, **`$group_set`**.

- `$group_set` **must be a plain JSON object**: "PostHog discards `$groupidentify` events when
  the `$group_set` property is not a valid JSON object… strings, numbers, booleans, and arrays
  are rejected." ([ingestion warnings](https://posthog.com/docs/data/ingestion-warnings.md))
- "You must include at least one group property for a group to be visible in the People and
  groups tab."
- "The PostHog UI identifies a group using the `name` property. If the `name` property is not
  found, it falls back to the group key." — so always set `name`.
- `distinct_id` is still required on the event but is incidental here.

### 3.4 Attaching a group to a normal event: `$groups`

```json
{
  "api_key": "...",
  "event": "feature_used",
  "distinct_id": "user distinct id",
  "properties": { "$groups": { "company": "company_id_in_your_db" } }
}
```

- "This event will **not** create a new group if a new key being used. To create a group, see
  the group identify event." — you must `$groupidentify` first, or the group will not exist.
- "An event links to a maximum of **one individual group per group type**." Multiple types are
  fine: `{"company": "...", "project": "..."}`.
- "PostHog doesn't store group membership on the person or on the individual group. **The
  connection lives on the event.**"

Three consequences that shape any account-scoring design:

1. **You cannot build a cohort from a group.**
2. "Related people and groups only cover the **last 90 days** of events."
3. Group types are unavailable for **lifecycle insights** and **user paths**.

### 3.5 Group analytics is a paid add-on

From [group analytics → Billing](https://posthog.com/docs/product-analytics/group-analytics.md#billing),
verbatim:

> "Group analytics is a paid add-on. Here's how billing works:
>
> **All identified events count toward billing**
>
> Once you subscribe to group analytics, billing applies to **all identified events** in your
> project, not just events with group properties attached. This is because group analytics
> enables infrastructure that processes all identified events to support group-level analysis.
>
> - Billing starts when you enable group analytics from your billing page, not when you add
>   group analytics code to your application.
> - Usage is based on captured identified events, even if they don't include group properties.
> - Billing stops when you unsubscribe from the billing page."

Pricing ([pricing](https://posthog.com/pricing.md), "Group analytics", *Extends Product
analytics*, unit = event):

| Monthly volume | Price per event |
|---|---|
| First 1,000,000 | **Free** |
| 1,000,001 – 2,000,000 | $0.000071 |
| 2,000,001 – 15,000,000 | $0.00003 |
| 15,000,001 – 50,000,000 | $0.0000189 |
| 50,000,001 – 100,000,000 | $0.0000105 |
| 100,000,001 – 250,000,000 | $0.000004 |
| Above 250,000,000 | $0.0000029 |

**What this means in practice.** Group analytics is not on the no-card **Free** plan; it is an
add-on you switch on from the billing page, which puts you on the **Paid pay-as-you-go plan
($0/mo base)**. Within the first 1M events/month the bill is still **$0**. So the cost of
turning it on for a demo-scale project is zero dollars but is **not zero friction**: it requires
a card on file. Two corroborating gates:

- [B2B mode](https://posthog.com/docs/customer-analytics/b2b-mode.md): "B2B mode is only
  available for organizations with group analytics add-on."
- [self-host disclaimer](https://posthog.com/docs/self-host/open-source/disclaimer.md) lists
  **Group analytics** under what you lose when self-hosting / on the free tier.

Note the interaction with §1.2: because the add-on bills **all identified events**, sending
GTM-irrelevant traffic as identified inflates the meter. Set
`$process_person_profile: false` on anything that does not need a person profile.

### 3.6 Reading groups back

- `GET /api/projects/{project_id}/groups/?group_type_index=<n>` — keyset pagination via
  `cursor`; `previous` is always null.
- `GET /api/projects/{project_id}/groups_types/` — lists the valid types.

([groups_list](https://posthog.com/docs/open-api-spec/groups_list.md))

---

## 4. Person and group properties

| Directive | Behaviour |
|---|---|
| `$set` | "Using `set` replaces any property value that may have been set on a person profile." |
| `$set_once` | "only sets the property if it has never been set before" — checks key existence, not timestamps |
| `$unset` | array of keys, e.g. `"$unset": ["email"]`; SDK helper `unsetPersonProperties()` |
| `$group_set` | the group equivalent, on `$groupidentify`. "Properties on groups behave in the same way as properties on persons." |

They can ride on any event, or on the dedicated `$set` event:

```json
{"api_key":"...","event":"$set","distinct_id":"1234",
 "properties":{"$set":{"name":"Max Hedgehog"},"$set_once":{"initial_url":"/blog"}},
 "timestamp":"2020-08-16 09:03:11.913767"}
```

**They are not stored on the event.** Verbatim:

> "These properties only tell PostHog how to update person data during ingestion — they aren't
> kept on the stored event, so you can't filter, break down, or query events by them."

Query them as `person.properties.your_property` in SQL instead.

**Update ordering — the gotcha.** From
[person properties](https://posthog.com/docs/product-analytics/person-properties.md):

> "Person properties are set in **ingestion order** (the order PostHog receives and processes
> events), not by event timestamps."
>
> "`$set` always reflects the last *ingested* value, not the last *timestamped* value."

`$set_once` is ingestion-ordered too — "the first ingested event claims the key, not necessarily
the earliest event by timestamp." Anything that batches, retries, or backfills (offline mobile
flushes, delayed server flushes, historical imports) can therefore land a stale value last.
Do not treat person properties as a source of truth for a scoring input that must be ordered.

Other facts:

- `last_seen_at` "gets updated once per hour, and the timestamp is always rounded down to the
  nearest hour." Suppress with event property `$update_person_last_seen_at: false`.
- Person record size limit **512 KB**; over-limit updates are rejected with an ingestion warning.
- **Warehouse properties** (Data → Warehouse properties) can sync person/group properties from a
  data-warehouse table keyed by distinct-ID or group-key column. Important constraint: "A sync
  only updates a person who already exists in PostHog. It never creates one."
- No documented `$group_unset`; group property removal via event is **UNCONFIRMED** (the REST
  API does have `groups_delete_property_create`).

---

## 5. API keys

From [API authentication](https://posthog.com/docs/api.md#authentication) and
[personal API keys](https://posthog.com/docs/api/personal-api-keys.md):

| Key type | Prefix | Used for | Can read data? |
|---|---|---|---|
| **Project API key** (project token) | `phc_` | Public POST-only endpoints: `/i/v0/e/`, `/batch/`, `/flags` | **No** — write-only |
| **Personal API key** | `phx_` | Private `GET`/`POST`/`PATCH`/`DELETE`; "tied to your own account" | **Yes** |
| **Project secret API key** (beta) | `phs_` | Server-to-server, project-scoped, not tied to a user | Today only `endpoint:read` |
| **OAuth** | `pha_` access / `phr_` refresh | Apps other PostHog users install | Yes, scoped |

- **The project API key is safe in a client.** Public endpoints "do not require authentication,
  but use your project token to handle the request" and "do not return any sensitive data from
  your PostHog instance."
- **To READ data you need a personal API key** (or OAuth, or a project secret key for the
  Endpoints product).
- **Header format:** `Authorization: Bearer $POSTHOG_PERSONAL_API_KEY`. A `personal_api_key`
  field in the request body also works; "only the value encountered first (in the order above)
  will be used."
- **Scopes** are chosen at key creation and are editable later. The query API requires the
  **Query Read** scope. Scope objects are enumerated in
  [`posthog/scopes.py`](https://github.com/PostHog/posthog/blob/master/posthog/scopes.py)
  (`action`, `activity_log`, `annotation`, `batch_export`, `cohort`, `customer_analytics`,
  `dashboard`, `event_definition`, `experiment`, `export`, `feature_flag`, `group`,
  `hog_function`, `insight`, `integration`, `query`, …), each with `read` / `write`; `*` is full
  access.
- Max **10 personal API keys per user**; deleted with the user. Keys predating Feb 2024 use
  legacy PBKDF2 hashing and carry a **Legacy** tag; "Roll key" upgrades to sha256.
- GitHub secret scanning auto-rolls leaked `phx_`/`phs_` keys and revokes leaked `pha_`/`phr_`.

**For GTMOS:** the project key goes wherever events are emitted (including an n8n workflow — it
is not a secret). The personal API key is a real secret, is org-wide in blast radius unless
scoped, and is what you would need for any read-back verification step.

---

## 6. Reading data out

### 6.1 Query API (HogQL)

`POST /api/projects/:project_id/query/` on the **private** host
([queries API](https://posthog.com/docs/api/queries.md)):

```bash
curl -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \
  https://us.posthog.com/api/projects/:project_id/query/ \
  -d '{"query":{"kind":"HogQLQuery","query":"select properties.$current_url from events limit 100"},
       "name":"get 100 blog urls"}'
```

- Top-level fields: `query` (required, with `kind`), `client_query_id`, `refresh`,
  `filters_override`, `variables_override`, `name`.
- `refresh`: `blocking` (default), `async`, `force_blocking`, `force_async`, `force_cache`,
  `lazy_async`, `async_except_on_cache_miss`.
- `kind`: `HogQLQuery`, `EventsQuery`, `TrendsQuery`, `FunnelsQuery`, `RetentionQuery`,
  `PathsQuery`.
- Default **100 rows**; with an explicit `LIMIT`, **up to 50,000 rows** per query.
- **`OFFSET` pagination is rejected with HTTP 400 for personal API keys.** Use keyset pagination
  on `timestamp`.
- Async: poll `GET /api/projects/:project_id/query/:query_id/`; cancel with `DELETE` on the same
  path.

PostHog is blunt about misuse:

> "The `/query` endpoint is not for exports… Bulk or recurring exports of `events`, `persons`,
> or `query_log` are not supported over `/query`… Connectors built on `/query` are not supported
> and will be rate-limited or rejected."

### 6.2 Events API — effectively deprecated

`GET /api/projects/{project_id}/events/`. The OpenAPI description
([events_list](https://posthog.com/docs/open-api-spec/events_list.md)) says verbatim:

> "This endpoint allows you to list and filter events. It is effectively deprecated and is kept
> only for backwards compatibility. If you ever ask about it you will be advised to not use
> it... If you want to ad-hoc list or aggregate events, use the Query endpoint instead. If you
> want to export all events or many pages of events you should use our CDP/Batch Exports
> products instead."

Params include `after` (default now−24h), `before` (default now+5s), `distinct_id`, `event`,
`format` (`csv`|`json`).

### 6.3 Rate limits

From [rate limiting](https://posthog.com/docs/api.md#rate-limiting). "These limits apply to
**the entire team** (i.e. all users within your PostHog organization)."

| Scope | Limit |
|---|---|
| Analytics endpoints (insights, persons, session recordings) | **240/minute** and **1200/hour** |
| `events/values` | **60/minute**, **300/hour** (`event_name` param required with a personal key) |
| `/query` | **2400/hour** |
| Feature flag local evaluation | **600/minute** |
| All other CRUD endpoints | **480/minute** and **4800/hour** |
| `/invites`, `/invites/bulk` | 50/hour, 200/day, ≤20 per bulk request |
| **Public POST-only endpoints (`/e`, `/i/v0/e`, `/batch`, `/flags`)** | **"no request-level rate limits"** |

Rule of thumb from the docs: "A rule of thumb for whether rate limits apply is if the personal
API key is used for authentication."

**Hourly read budget** (separate from the above): "Queries made with a personal API key draw
from an hourly read budget per project, and every query debits the bytes it read. The budget
refills continuously, and unused budget carries over up to a cap." Exhaustion →
**`429` with code `api_queries_budget_exceeded`** and a `Retry-After` header. Every `/query`
response carries `X-PostHog-Query-Bytes-Read` and `X-PostHog-Query-Budget-Remaining-Bytes`.
Cached results and in-app queries are unaffected. "For the larger budget, subscribe to a paid
plan." The exact byte figures for free vs paid are **UNCONFIRMED** — they are not published.

Higher limits are sold as the **Endpoints** product: materialized endpoints get 1,200 req/min
burst, 12,000 req/hour sustained, 10 concurrent
([endpoints rate limits](https://posthog.com/docs/endpoints/rate-limits.md)).

---

## 7. Getting data OUT to other systems

The product is called **Data pipelines** ([CDP](https://posthog.com/docs/cdp.md)):
sources → transformations → destinations. Two delivery modes plus one-off exports:

| Mode | What it is |
|---|---|
| **Realtime destinations** | Fire per event as it is ingested ([destinations](https://posthog.com/docs/cdp/destinations.md)) |
| **Batch exports** | Scheduled to S3, BigQuery, Snowflake, Redshift, Postgres, Databricks, Azure Blob, GCS ([batch exports](https://posthog.com/docs/cdp/batch-exports.md)) |
| **File download exports** | One-off bulk |

### 7.1 The HTTP Webhook destination — what it can POST

This is the piece that determines whether PostHog → n8n → GTMOS works.
Docs: [webhook destination](https://posthog.com/docs/cdp/destinations/webhook.md).
Setup: Data pipelines → **+ New → Destination** → search "Webhook" → **+ Create** → set
**Webhook URL** → **Create & Enable**. There is a built-in **Testing** panel and a **Log
responses** debug toggle.

> "By default, PostHog sends a `POST` request with a templated JSON body."

Configurable inputs, verbatim from the template source
([`webhook.template.ts`](https://github.com/PostHog/posthog/blob/master/nodejs/src/cdp/templates/_destinations/webhook/webhook.template.ts)):

| Input | Type | Default | Description |
|---|---|---|---|
| `url` | string, **required** | — | "Endpoint URL to send event data to." |
| `method` | choice | `POST` | `POST`, `PUT`, `PATCH`, `GET`, `DELETE` |
| `body` | json | `{ "event": "{event}", "person": "{person}" }` | "JSON payload to send in the request body." |
| `headers` | dictionary | `{ "Content-Type": "application/json" }` | "HTTP headers to send in the request." |
| `signing_secret` | string, secret | — | "Signs each request following the [Standard Webhooks](https://www.standardwebhooks.com) spec." |
| `debug` | boolean | `false` | "Logs the response of http calls for debugging." |

**So: yes, the payload is fully customisable** — arbitrary JSON body, arbitrary headers,
arbitrary method, and optional HMAC signing. That is everything an n8n Webhook node needs,
including a shared-secret header or a Standard Webhooks signature.

**Templating — two layers**
([customizing destinations](https://posthog.com/docs/cdp/destinations/customizing-destinations.md)):

1. **Curly-brace Hog templating** — `{event.event}`, `{event.timestamp}`,
   `{person.properties.first_name}`, `{project.url}`. Works in the URL too:
   `https://api.example.com/v0/track?username={person.name}`.
2. **Liquid templating** — "Destination templates also support Liquid templating", e.g.
   `{% assign conversionValue = conversionValue | plus: 0 %}{{ conversionValue }}` to coerce a
   string to a number.
3. Full source editing in **Hog** ("show source code"), built on
   `fetch(url, {headers, body, method})`. Constraint: "Do not perform more than 5 `fetch` calls:
   The function will error if you do."

**The global template object** available to a destination:

```
event   { uuid, event, distinct_id, properties, timestamp, url }
person? { id, name, url, properties }
groups? { [id]: { id, type, index, url, properties } }
project { id, name, url }
source? { name, url }
```

`groups` being available to destinations is the key fact for account-level GTM: a webhook can
carry the company group key and its properties, not just the person.

**Filtering:** "you can construct a query that filters by event types, properties, or any SQL
statement you can come up with", plus match rules and trigger options in the **Filters** section.
This is where you keep the trigger-event meter small.

**Delivery behaviour** ([destinations](https://posthog.com/docs/cdp/destinations.md)):

- "There is no limit on the number of events to be processed but the system requires that the
  destination responds with healthy status codes (non 5xx) and in a timely fashion."
- "By default, all HTTP calls (`fetch` calls in Hog) are expected to return a 2xx response. If
  we get a non-OK response we will **retry up to 3 times** depending on the error codes."
- 4xx is **not** counted as poor performance. Sustained errors or slowness → the destination is
  quarantined, then auto-disabled, with automatic re-enable attempts.
- Person data on the event is "the latest information… at the time the event is processed".
- Firewall allowlist IPs (from the webhook doc): EU `3.75.65.221`, `18.197.246.42`,
  `3.120.223.253`; US `44.205.89.55`, `52.4.194.122`, `44.208.188.173`.

### 7.2 Is it a paid feature?

Two statements that do not fully agree, so both are recorded:

**Pricing page** ([pricing](https://posthog.com/pricing.md)) lists **Realtime destinations** as
a product with a free allowance on both plans:

| Monthly volume | Price per trigger event |
|---|---|
| First 10,000 | **Free** |
| 10,001 – 50,000 | $0.0005 |
| 50,001 – 100,000 | $0.0003 |
| 100,001 – 1,000,000 | $0.00015 |
| 1,000,001 – 10,000,000 | $0.0001 |
| 10,000,001 – 100,000,000 | $0.00005 |
| Above 100,000,000 | $0.000025 |

Batch exports: unit = row, first **1,000,000/month free**, then $0.000015 → $0.00000125. There
is also a **Data pipelines** add-on row (*Extends Product analytics*, unit = event, first 1M
free, $0.000062 → $0.0000025).

**But the HTTP Webhook template is marked `free: false` in source**, while e.g. the Slack
template is `free: true`
([webhook.template.ts](https://github.com/PostHog/posthog/blob/master/nodejs/src/cdp/templates/_destinations/webhook/webhook.template.ts)
vs [slack.template.ts](https://github.com/PostHog/posthog/blob/master/nodejs/src/cdp/templates/_destinations/slack/slack.template.ts)),
and the [self-host disclaimer](https://posthog.com/docs/self-host/open-source/disclaimer.md)
lists **Data pipelines** among the things absent from the free/self-hosted tier.

**Conclusion, stated at the confidence it deserves:** Slack/Zapier-style `free: true` templates
work on the no-card Free plan. The arbitrary **HTTP Webhook** template almost certainly requires
the paid pay-as-you-go plan ($0/mo base, card on file), inside whose 10,000 free trigger events
the bill is still $0. **The prose docs never state this gating explicitly — the `free: false`
reading is inferred from source and is UNCONFIRMED.** Verify by attempting to create the
destination on a card-less account before designing around it.

### 7.3 The legacy "Actions + webhook" path is gone

No longer documented. `https://posthog.com/docs/webhooks` now serves the "Realtime analytics
data exports" page; `https://posthog.com/docs/integrate/webhooks` now serves the CDP
webhook-destination page; `/docs/api/actions` and `/docs/actions` 404. The only surviving
actions page is [actions](https://posthog.com/docs/data/actions). Treat the old "an Action fires
a webhook to Slack/Teams" flow as fully superseded by CDP destinations + filters.

Also relevant in the other direction: **incoming webhooks as a source**
([incoming webhooks](https://posthog.com/docs/cdp/sources/incoming-webhooks.md)), and
**Workflows** (triggers: event performed / recurring schedule / webhook; dispatches: mail,
Slack, SMS, webhook, or any realtime destination). Whether a Workflow can be triggered on a
group/account entity rather than a person is **UNCONFIRMED**.

---

## 8. Self-hosting

Sources: [self-host](https://posthog.com/docs/self-host.md),
[open-source disclaimer](https://posthog.com/docs/self-host/open-source/disclaimer.md).

### 8.1 Official position

- **Docker Compose is the only supported self-host path, and it is "officially unsupported" as
  a product.** "We offer a free Docker Compose deployment under an MIT license." "New
  deployments of PostHog's paid open source product using Kubernetes are no longer supported."
  (Helm was sunset.)
- **No tagged releases, no CVE process:** "PostHog doesn't have versions: self-hosted
  deployments are officially unsupported, and every change, including security fixes, ships
  continuously from `master`… We recommend running your instance the way we run PostHog Cloud:
  always on the latest image."
- **No support:** "Self-hosted customers cannot receive commercial support from PostHog… we
  cannot answer tickets and cannot help debug. We're unable to support recovery from data loss."

### 8.2 Install

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/posthog/posthog/HEAD/bin/deploy-hobby)"
# upgrade
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/posthog/posthog/HEAD/bin/upgrade-hobby)"
```

There is also a **[BETA] Self Host TUI**:

```bash
curl -OfsSL https://github.com/PostHog/posthog/releases/download/hobby-latest/hobby-installer
chmod +x hobby-installer && ./hobby-installer
# CI mode
./hobby-installer --ci --domain=posthog.yourdomain.com
```

"This is a trial and will change or might be removed based on your feedback."

### 8.3 Resource requirements

Verbatim: "You have deployed a Linux Ubuntu Virtual Machine. You will need something equivalent
to a Hetzner VM with **4 vCPU, 16GB RAM, and more than 30GB storage**." Plus an `A` record for a
custom domain (LetsEncrypt cert is auto-issued). Boot takes ~5–10 minutes.

The stack brings up: posthog web / worker / plugin-server, Caddy, **ClickHouse, Kafka,
Zookeeper, Redis, Postgres, MinIO**.

Scale ceiling: "Everything runs on a single machine, and thus is unlikely to scale past a couple
100ks events without significant effort." The decision flowchart's threshold question is
"Do you expect to ingest more than 300k events, 1k recordings, 300k /flags API calls into the
instance?"

### 8.4 What is missing from self-hosted / free

Verbatim list from the disclaimer, product analytics section: "insight & dashboard
subscriptions, advanced paths, correlation analysis, lifecycle insights, one year event
retention, more than two alerts, **Group analytics**, **Data pipelines**." Also missing: web
analytics path cleaning; session replay downloads; feature flag multi-environment support and
group experiments; most survey customisation; and platform features (priority support,
unlimited projects, white labeling, SSO/SAML, RBAC, audit logs, custom retention).

### 8.5 Is a local instance a practical way to test this integration in 2026?

**No.** Two independent reasons:

1. **The two features this integration depends on — group analytics and data pipelines
   (destinations) — are exactly the two named as absent from self-hosted.** A local PostHog can
   ingest events and run basic product analytics; it cannot do account-level grouping or POST to
   an external webhook. So a local instance cannot exercise the integration's actual surface.
2. **Cost of the box.** 4 vCPU / 16 GB / 30 GB+ running ClickHouse + Kafka + Zookeeper +
   Postgres + Redis + MinIO is not a laptop-friendly sidecar next to an existing dev stack.

PostHog's own guidance agrees: "For most companies we'd recommend PostHog Cloud, which comes
with a very generous free tier", and the flowchart's terminal node for anyone under 1M
events/month is "You'll probably be better off with PostHog Cloud."

**Recommendation:** develop against PostHog Cloud (free tier for ingestion), and for the
outbound leg point the destination at a tunnelled local n8n — or, for fully offline work, stub
the destination by POSTing PostHog's documented payload shape directly at the n8n webhook. The
payload contract in §7.1 is fully specified, so a stub is faithful.

---

## 9. Free tier (PostHog Cloud)

From [pricing](https://posthog.com/pricing.md). Two plans, no per-seat charges:

- **Free** — "No credit card required. Generous monthly usage limits on every product. 1
  project. 1 year data retention. Community support."
- **Paid (pay-as-you-go)** — "$0/mo base price. You get a free tier on every product, then pay
  only for what you use above it. The free tier resets every month. 6 projects. 7 year data
  retention. Email support."

| Product | Free allowance / month | First paid tier |
|---|---|---|
| **Product analytics (events)** | **1,000,000 events** | $0.00005/event |
| Session replay | 5,000 recordings | $0.005 |
| Feature flags & experiments | 1,000,000 requests | $0.0001 |
| Surveys | 1,500 responses | $0.10 |
| Error tracking | 100,000 exceptions | $0.00037 |
| Data warehouse | 1,000,000 rows | $0.000015 |
| **Realtime destinations** | **10,000 trigger events** | $0.0005 |
| **Batch exports** | **1,000,000 rows** | $0.000015 |
| AI observability | 100,000 events | $0.00035 |
| Logs | 10 GB | $0.25/GB |
| PostHog AI | 500 credits | $0.01 |
| Emails | 10,000 | $0.003 |
| *(add-on)* Identified events | 1,000,000 | $0.000198 |
| *(add-on)* **Group analytics** | **1,000,000** | $0.000071 |
| *(add-on)* Data pipelines | 1,000,000 | $0.000062 |
| *(add-on)* Mobile session replay | 2,500 recordings | $0.01 |

Platform packages, flat and on top: Boost $250/mo, Scale $750/mo, Enterprise $2000/mo.

**Is group analytics included on Free? No.** It is an add-on enabled on the billing page (§3.5),
it is named among the features you lose on free/self-hosted, and B2B mode requires it. Once
enabled the first 1M events/month cost $0, but enabling it makes **all identified events** in
the project billable against that meter.

**Are destinations/webhooks included on Free?** Realtime destinations carry a 10,000
trigger-event/month free allowance and appear in the free-plan product list. The specific
**HTTP Webhook** template is `free: false` in source while Slack is `free: true`, and
"Data pipelines" is listed among the features absent from free/self-hosted. Net: Slack-style
free templates yes; **arbitrary HTTP Webhook almost certainly needs the paid $0-base plan —
UNCONFIRMED in prose docs** (§7.2).

Other allowances: Customer Analytics is "currently in beta and free to use". Startups get
$50,000 credits for 12 months (<2 years old, <$5M raised); YC companies get $50,000/year.

---

## 10. Product-led GTM patterns — how PostHog documents PQLs

There is **no `posthog.com/tutorials/` page on PQLs or lead scoring**; the group-analytics
tutorial category holds only
[frontend vs backend group analytics](https://posthog.com/tutorials/frontend-vs-backend-group-analytics).
PostHog documents the pattern in four other places.

### 10.1 The canonical PQL page — a Pocket Guide / agent Skill

[Lead scoring](https://posthog.com/pocket-guides/context-warehouse/lead-scoring) —
"Which leads deserve the sales team's time?"

> "A CRM full of leads doesn't tell sales who to call first; product usage does. This Skill
> scores CRM leads by recent product usage and surfaces the warmest ones sales hasn't yet
> reached: a product-qualified-lead list."

Documented method:

1. Pick a handful of intent events and weight them. Worked example: `created_project` = 5,
   `invited_teammate` = 4, `ran_query` = 2, `viewed_pricing` = 1, over 30 days.
2. Join PostHog persons to HubSpot/Salesforce lead rows on `lower(email)`.
3. Exclude `lifecycle_stage IN ('customer')` and leads contacted in the last 30 days.
4. `ORDER BY score DESC LIMIT 100`, saved as a SQL/HogQL **table insight** named
   "Product-qualified leads (uncontacted)".
5. Then "Offer to help set up an alert or a cohort that flags a lead when its score crosses a
   threshold… (Pushing the score back into the CRM is a separate reverse-ETL step.)"

Its own caveat: "this ranks by product signal only; a real PQL model may blend in firmographics."

Account-level sibling:
[upsell-ready accounts](https://posthog.com/pocket-guides/context-warehouse/upsell-ready-accounts)
— `usage ÷ plan_limit ≥ 0.8 AND plan is not top tier`, joined to Stripe, keyed on
`person.properties.account_id` or the group key, preferring a "consistently over" signal (over
threshold in 2+ of the last 3 months), saved as a materialized view on a refresh schedule.
Index: [context warehouse](https://posthog.com/pocket-guides/context-warehouse).

### 10.2 Glossary definition

[Glossary](https://posthog.com/docs/glossary): "**PQL** — Product Qualified Lead. A PQL is a
user who has expressed interest in your product based on actions which can be attributed to the
product, such as completing a free trial or having experienced the direct value of the product."

### 10.3 The product surface: Customer Analytics (beta, free)

[Customer analytics](https://posthog.com/docs/customer-analytics/start-here.md):

- **B2B mode** renders every dashboard insight against a group type — but "is only available for
  organizations with group analytics add-on".
- **Usage metrics** ([usage metrics](https://posthog.com/docs/customer-analytics/usage-metrics.md))
  — "identify expansion opportunities or churn risk". Documented examples: `api_request` →
  "Identify heavy API users for expansion"; `export_created` → "Find power users". Configurable
  over 7/30/90-day intervals, count-of-events or sum-of-property, and buildable from a warehouse
  table keyed by a **group key column** (warehouse metrics render on group profiles only).
- **Customer profiles** for persons *and* groups — "Group profiles show aggregated activity for
  an organization, company… useful for B2B products where you care about company-level
  activity" — pulling in events, errors, LLM traces and Zendesk tickets.
- **Saved views** on the persons/groups lists; the doc's own example is a "High value customers"
  view filtered on revenue. This is the practical product-qualified-account list UI.
- **Revenue analytics** (Stripe live; Chargebee/Polar/RevenueCat "coming soon") "automatically
  connects revenue data to persons and groups when you use revenue events."

### 10.4 How PostHog itself does it (handbook)

- [RevOps overview](https://posthog.com/handbook/growth/revops/overview): "we built an automated
  workflow that identifies product qualified leads in real-time. When a company hits key
  milestones (like having 5+ active users and using multiple products) and matches our ICP
  they're automatically flagged as a new lead in Salesforce with their usage data."
- [Lead scoring](https://posthog.com/handbook/growth/sales/lead-scoring): the live thresholds —
  "Customers with MRR between $500-1,667, employee count > 50, user count > 7, based in ICP
  country, and has been paying for at least 3 months"; "First signup from a company with 500+
  employees who have ingested at least 1 event and invited at least 1 person"; "Unmanaged
  customers with >$20K ARR who raise a support ticket". **Scores are computed in Salesforce,
  not in PostHog.**
- [ICP fit score](https://posthog.com/handbook/growth/revops/icp-fit-score): the firmographic
  half — org-level properties `icp_fit_status`, `icp_fit_score` (0–100), `icp_fit_version`;
  Harmonic enrichment on work-email domain; weights Traction 35 / Capital 30 / AI-pilled 15 /
  Headcount growth 10 / Software relevance 10. Code:
  [`fit_score.py`](https://github.com/PostHog/posthog/blob/master/products/growth/backend/enrichment/fit_score.py).
- [Product-led lead qualification](https://posthog.com/handbook/growth/sales/product-led-lead-qualification)
  — the richest operational page. Notable signals: destination configuration as a signal ("Data
  flowing out to a competitor (Amplitude, Mixpanel) is a risk signal. Data flowing to a
  warehouse… is a stickiness signal"); missing-product triggers ("B2B without Group Analytics,
  mobile app without Mobile Replay…"); and "In the org event stream, filter for
  `path name contains 'billing'`. Recent billing page views mean they're thinking about cost."
- [Product-led sales](https://posthog.com/handbook/growth/sales/product-led-sales): outreach
  threshold — "If you think they have potential to end up paying more than $20k a year then you
  should reach out."
- [CRM](https://posthog.com/handbook/growth/sales/crm): PostHog's own `user signed up` event
  fires a destination literally named "Salesforce create contact for signups", mapping
  `role_at_organization` ("used in lead scoring"), `is_organization_first_user`, org ID/name,
  distinct ID.

### 10.5 CRM plumbing

Destinations exist for [HubSpot](https://posthog.com/docs/cdp/destinations/hubspot.md) (person
data → Contacts), [Salesforce](https://posthog.com/docs/cdp/destinations/salesforce.md) (event
data, with `Object path` and `Additional properties` JSON, e.g.
`"email": "{person.properties.email}"`), Attio, Close, Intercom, Customer.io, Zapier. Matching
**sources** exist for the join side (HubSpot, Salesforce, Close, Freshsales…).

**There is no destination template specifically for PQLs or lead scores.** The documented
pattern is: compute the score in HogQL or in the CRM, and move it with reverse ETL — which is
precisely the gap a GTMOS-style layer fills.

Dated/third-party: [Variance connector](https://posthog.com/tutorials/variance-connector)
(July 1, 2022) describes Variance "milestones" — "Signed Up, Onboarded, Product Qualified (PQL),
Transacted, Expansion Qualified (EQL)" — syncing to Salesforce/HubSpot. Its `.md` variant 404s;
treat it as stale.

---

## 11. Explicitly UNCONFIRMED

- Whether the HTTP Webhook destination is hard-gated behind a paid plan. Inferred from
  `free: false` in the template source; no prose doc states it.
- The exact byte size of the `/query` hourly read budget on free vs paid plans.
- Whether the legacy `/capture/` path is officially supported. It still returns `200` but is
  absent from every current doc.
- `$anon_distinct_id` as a documented raw-API contract (present in posthog-js source only).
- Any `$group_unset` equivalent for removing a group property via an event.
- Whether Workflows can be triggered on a group/account entity rather than a person.

---

## 12. Implications for PostHog → n8n → GTMOS

1. **The outbound leg is real and well specified.** The HTTP Webhook destination can POST an
   arbitrary JSON body with arbitrary headers to an arbitrary URL, with Hog + Liquid templating
   and optional Standard Webhooks HMAC signing. It exposes `groups` alongside `event` and
   `person`, so an account-level payload is possible. Retries are 3× with auto-quarantine on
   sustained failure — n8n's webhook must return 2xx fast, which argues for
   `responseMode: onReceived` on the n8n side.
2. **Group analytics is the constraint, not the webhook.** 5 group types max, group membership
   lives on the event (so no cohorts from groups, and "related people and groups" only looks
   back 90 days), and it is a billing-page add-on whose meter counts **all identified events**.
   Design so that only GTM-relevant events are identified.
3. **Self-hosting does not help.** The two features needed are the two named as absent from
   self-hosted, on top of a 4 vCPU / 16 GB / 30 GB box. Use Cloud, or stub the destination
   against the documented payload shape.
4. **Money.** Ingestion and reading are genuinely free to 1M events/month on the no-card Free
   plan. Group analytics, and probably the HTTP Webhook destination, require the paid
   pay-as-you-go plan — **$0/mo base, $0 within the free allowances, but a card on file.** No
   real spend is required to build and demonstrate this; a payment method probably is.
5. **Verification must read data back.** Capture returns `200` for dropped events and for
   over-quota projects alike. Any "did it land?" assertion has to go through
   `POST /api/projects/:id/query/` with a personal API key.
