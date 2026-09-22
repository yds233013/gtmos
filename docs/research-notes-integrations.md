# Integration Research Notes (adapter reference)

Accessed 2026-09-21. Items marked **[unverified]** were not confirmed against a primary doc this session. Check them before relying on them.

---

## HubSpot

Sources:
- https://developers.hubspot.com/docs/guides/api/crm/understanding-the-crm
- https://developers.hubspot.com/docs/guides/api/crm/objects/contacts
- https://developers.hubspot.com/docs/api-reference/crm-companies-v3/batch/post-crm-v3-objects-companies-batch-upsert
- https://developers.hubspot.com/docs/guides/api/crm/associations/associations-v4
- https://developers.hubspot.com/docs/guides/api/crm/properties
- https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines
- https://developers.hubspot.com/docs/guides/apps/authentication/validating-requests
- https://developers.hubspot.com/docs/api-reference/legacy/webhooks/guide
- https://developers.hubspot.com/docs/guides/apps/private-apps/overview
- Company upsert/domain caveat: https://community.hubspot.com/t/companies-batch-upsert-api-endpoint/127307

**API versioning note.** The current HubSpot docs show **date-versioned** paths (for example `/crm/objects/2026-09/...`, `/crm/associations/2026-09/...`) alongside the long-standing `/crm/v3/...` and `/crm/v4/...` paths. Build the adapter with a configurable base path. The v3/v4 paths below are the widely deployed ones.

### Auth
- Private app (now labelled a "legacy app"; still supported): `Authorization: Bearer <token>`.
- Rotation: "Rotate and expire now", or "rotate and expire later" (the old token expires in 7 days). Admins get a reminder if a token has not been rotated in 180+ days.
- Private apps support webhooks, but subscriptions are configured only in the app settings UI, not via API.
- Scopes, for example `crm.objects.companies.read` / `crm.objects.companies.write`, and `crm.objects.contacts.*`, `crm.objects.deals.*`, `crm.schemas.*` for properties.

### Object type IDs
| Object | ID | Object | ID |
|---|---|---|---|
| contacts | 0-1 | tasks | 0-27 |
| companies | 0-2 | notes | 0-46 |
| deals | 0-3 | meetings | 0-47 |
| tickets | 0-5 | calls | 0-48 |
| | | emails | 0-49 |

- `hs_object_id` is the record ID. **Treat it as a string.**
- Alternate IDs: contact `email`. Company `domain` is the documented "primary unique identifier" for dedupe, **but it is not a unique-enforced property.**

### CRUD (companies shown; contacts, deals, notes and tasks follow the same pattern under `/crm/v3/objects/{objectType}`)
```
POST   /crm/v3/objects/companies                      {properties:{...}, associations:[{to:{id}, types:[{associationCategory, associationTypeId}]}]}
GET    /crm/v3/objects/companies/{id}?properties=a,b&associations=contacts&idProperty=<uniqueProp>
PATCH  /crm/v3/objects/companies/{id}                 {properties:{...}}
DELETE /crm/v3/objects/companies/{id}
POST   /crm/v3/objects/companies/batch/read           {properties:[...], idProperty?:"x", inputs:[{id}]}   (batch read does NOT return associations)
POST   /crm/v3/objects/companies/batch/create|update|archive
POST   /crm/v3/objects/companies/batch/upsert
POST   /crm/v3/objects/{objectType}/search            [search limits: separate, see usage docs]
```
Company create needs at least `name` or `domain`. Extra domains go in `hs_additional_domains` (semicolon-separated).

### Batch upsert
```
POST /crm/v3/objects/{contacts|companies|deals|...}/batch/upsert
{
  "inputs": [
    { "id": "<value of idProperty>", "idProperty": "email" | "<custom_unique_prop>",
      "properties": { "phone": "+1..." } }
  ]
}
```
- Maximum **100 inputs per batch**.
- Contacts: `idProperty: "email"` is allowed, but **partial upserts are not supported with email**. Use a custom unique property if you need partial upserts.
- Companies: `domain` and `name` **cannot** be used as `idProperty`. They fail with `Unable to perform update/upsert by non-unique 0-2 property domain` (community-confirmed). **Create a custom unique property** (for example `gtmos_account_id`) and upsert on that.
- Response: `status`, `results[]` (each with `id`, `properties`, `new: bool` **[unverified field name]**), `errors[]` on 207.

### Custom properties
```
POST /crm/v3/properties/{objectType}
{ "groupName": "companyinformation", "name": "gtmos_account_id", "label": "GTMOS Account ID",
  "type": "string", "fieldType": "text", "hasUniqueValue": true }
```
- type/fieldType pairs: `bool`: booleancheckbox | calculation_equation. `enumeration`: booleancheckbox, checkbox, radio, select, calculation_equation. `date`: date. `datetime`: date. `string`: text, textarea, html, phonenumber, file, calculation_equation. `number`: number, calculation_equation.
- Maximum **10 unique-value properties per object type**.
- Once defined, a unique property works as `?idProperty=gtmos_account_id` on GET/PATCH.
- Property groups: `POST /crm/v3/properties/{objectType}/groups` `{name,label}` **[unverified; not shown on the fetched page]**.

### Associations v4
```
PUT  /crm/v4/objects/{fromType}/{fromId}/associations/default/{toType}/{toId}           (default/unlabeled)
PUT  /crm/v4/objects/{fromType}/{fromId}/associations/{toType}/{toId}
     body: [{ "associationCategory": "HUBSPOT_DEFINED"|"USER_DEFINED", "associationTypeId": 279 }]
POST /crm/v4/associations/{fromType}/{toType}/batch/create            {inputs:[{from:{id}, to:{id}, types:[...]}]}
POST /crm/v4/associations/{fromType}/{toType}/batch/associate/default {inputs:[{from:{id}, to:{id}}]}
POST /crm/v4/associations/{fromType}/{toType}/batch/read
POST /crm/v4/associations/{fromType}/{toType}/batch/archive
POST /crm/v4/associations/{fromType}/{toType}/batch/labels/archive
GET  /crm/v4/associations/{fromType}/{toType}/labels
```
(The current docs render these as `/crm/objects/2026-09/...` and `/crm/associations/2026-09/...`.)
v3 single-object shorthand: `PUT /crm/v3/objects/companies/{id}/associations/{toObjectType}/{toObjectId}/{associationTypeId}`.

Default HUBSPOT_DEFINED type IDs. The first five were verified this session. The rest come from HubSpot's standard table **[unverified this session]**:
| from to | id |
|---|---|
| contact to company (primary) | 1 |
| contact to company | 279 |
| deal to company (primary) | 5 |
| deal to company | 341 |
| note to contact | 202 |
| company to contact | 280 |
| deal to contact | 3 |
| contact to deal | 4 |
| company to deal | 342 |
| note to company | 190 |
| note to deal | 214 |
| task to contact | 204 |
| task to company | 192 |
| task to deal | 216 |

Engagements (notes, tasks) are objects: `POST /crm/v3/objects/notes` with `hs_timestamp` and `hs_note_body`, and `POST /crm/v3/objects/tasks` with `hs_timestamp`, `hs_task_subject`, `hs_task_body`, `hs_task_status`, `hs_task_priority`, `hubspot_owner_id`. Associate them inline via `associations[]` **[property names unverified this session]**.

### Lifecycle stage
- Contact/company property `lifecyclestage`. Defaults: `subscriber`, `lead`, `marketingqualifiedlead`, `salesqualifiedlead`, `opportunity`, `customer`, `evangelist`, `other`.
- It only moves **forward**. To move backward, PATCH it to `""` first, then set the new value.
- Fetch actual options with `GET /crm/v3/properties/0-1/lifecyclestage`.

### Rate limits
| Tier | Private app burst | Daily (per account) |
|---|---|---|
| Free/Starter | 100 / 10 s per app | 250,000 |
| Professional | 190 / 10 s per app | 625,000 |
| Enterprise | 190 / 10 s per app | 1,000,000 |
| + API limit increase add-on | 250 / 10 s | +1,000,000 per add-on (max 2 add-ons) |

- Public OAuth apps: 110 / 10 s per installing account (Search API excluded; the add-on does not apply).
- Search API has its own, lower limits **[commonly cited as 5 req/s per account; unverified this session]**.
- Headers: `X-HubSpot-RateLimit-Daily`, `X-HubSpot-RateLimit-Daily-Remaining`, `X-HubSpot-RateLimit-Max`, `X-HubSpot-RateLimit-Remaining`, `X-HubSpot-RateLimit-Interval-Milliseconds`.
- A 429 body carries `policyName` of `DAILY` or `SECONDLY`. Marketplace guidance keeps errors under 5% of daily requests.
- Maximum 20 private apps per account (third-party source) **[unverified]**.

### Webhooks (v3 / "legacy" app webhooks)
- POST of a JSON **array**, under 100 events per request. Concurrency limit is 10 requests.
- Respond within **5 s**. Otherwise, or on connection failure or 4xx/5xx, HubSpot retries **up to 10 times over 24 h**.
- Payload example (from docs):
```json
[{ "objectId": 1246965, "propertyName": "lifecyclestage", "propertyValue": "subscriber",
   "changeSource": "ACADEMY", "eventId": 3816279340, "subscriptionId": 25, "portalId": 33,
   "appId": 1160452, "occurredAt": 1462216307945, "subscriptionType": "contact.propertyChange",
   "attemptNumber": 0 }]
```
  The docs example labels the type field `eventType`. Real deliveries commonly use `subscriptionType`, so accept both. Subscription types look like `contact.creation`, `contact.propertyChange`, `company.creation`, `deal.propertyChange`, `*.deletion`, `*.associationChange`, `*.merge`.
- Idempotency key: `eventId` (plus `subscriptionId` / `portalId`). The same event can be redelivered: `attemptNumber` increments.
- There is also a new **v4 webhooks journal API (beta)**. It is poll-based, with `journalEvents[]` carrying `action` values CREATE/UPDATE/DELETE/MERGE/RESTORE/ASSOCIATION_ADDED/... It is not compatible with v3. Limits: Journal 100 rps, Subscriptions 50 rps, Snapshots 10 rps.

### Request signature validation
| Version | Header | Source string | Algo |
|---|---|---|---|
| v1 | `X-HubSpot-Signature` (and `X-HubSpot-Signature-Version: v1`) | `clientSecret + body` | SHA-256 hex digest (not HMAC) |
| v2 | `X-HubSpot-Signature` (`...-Version: v2`) | `clientSecret + method + fullURI + body` | SHA-256 hex, UTF-8 |
| v3 | `X-HubSpot-Signature-v3` + `X-HubSpot-Request-Timestamp` | `method + uri + body + timestamp` | **HMAC-SHA256(key=clientSecret), base64** |

v3 details:
- Reject if `now - timestamp > 5 min` (the timestamp is in ms).
- `uri` is the full URL, including protocol and host, **with these percent-encodings decoded**: `%3A : %2F / %3F ? %40 @ %21 ! %24 $ %27 ' %28 ( %29 ) %2A * %2C , %3B ;`. Query-string delimiters stay as-is.
- Compare with constant-time equality.
- For private apps, use the app's client secret **[confirm where the private-app secret is shown in the UI]**.

```python
src = f"{method}{decoded_uri}{raw_body}{timestamp}".encode("utf-8")
sig = base64.b64encode(hmac.new(secret.encode(), src, hashlib.sha256).digest()).decode()
ok = hmac.compare_digest(sig, request.headers["X-HubSpot-Signature-v3"]) and abs(now_ms - int(ts)) < 300_000
```

---

## PostHog

Sources: https://posthog.com/docs/api/capture, https://posthog.com/docs/cdp/destinations/webhook

- Hosts (ingestion): US `https://us.i.posthog.com`, EU `https://eu.i.posthog.com`, or self-hosted domain.
- Single event: `POST /i/v0/e/`. The legacy `/capture/` path is still accepted **[unverified this session; widely used by SDKs historically]**. Batch: `POST /batch/`.
- Auth is the project token in the body (`api_key`). This is **not** the personal API key.
- Single event body:
```json
{ "api_key": "<ph_project_token>", "event": "signed_up", "distinct_id": "user_123",
  "properties": { "plan": "pro", "$groups": { "company": "acme.com" } },
  "timestamp": "2026-09-21T10:00:00Z" }
```
  `distinct_id` has a max of 200 chars. `timestamp` is optional ISO 8601. `uuid` is optional for dedupe **[unverified this session]**.
- Batch body (total under 20 MB, no event-count limit):
```json
{ "api_key": "<token>", "historical_migration": false,
  "batch": [ { "event": "e", "properties": { "distinct_id": "u1" }, "timestamp": "..." } ] }
```
- Group analytics (company level). Attach `properties.$groups = {"<group_type>": "<group_key>"}` to events. Set group properties with:
```json
{ "event": "$groupidentify", "distinct_id": "groups_setup_id",
  "properties": { "$group_type": "company", "$group_key": "acme.com",
                  "$group_set": { "name": "Acme", "plan": "enterprise" } } }
```
- Person properties: `{"event":"$identify","distinct_id":"u1","properties":{"$set":{...}}}`. `$set_once` is also supported **[unverified this session]**. Alias: `$create_alias` with `properties.alias`. Anonymous (no person profile): `properties.$process_person_profile=false`.
- Responses: returns **200 even for invalid events** (missing event name or distinct_id). Such events are silently dropped, so validate client-side. No rate limit is documented on the capture page.
- Webhook destination (CDP): POSTs templated JSON to your URL, with filters, test and response logging. Egress IPs for allowlisting: US `44.205.89.55`, `52.4.194.122`, `44.208.188.173`. EU `3.75.65.221`, `18.197.246.42`, `3.120.223.253`. The default body template and variables (`event`, `person`, `groups`) exist but were not quoted on the fetched page **[unverified exact template]**. No signature header is documented. Put a shared-secret header in the destination's configurable headers.

---

## n8n

Sources:
- https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook.md
- https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.crypto.md
- https://docs.n8n.io/build/manage-workflows/export-and-import.md
- Sample JSON: https://api.n8n.io/api/templates/workflows/1750

### Webhook node (`n8n-nodes-base.webhook`)
- Methods: DELETE, GET, HEAD, PATCH, POST, PUT.
- Test URL: live only while "Listen for Test Event" is active. Production URL: registered when the workflow is published/active. Conventional paths are `/webhook-test/<path>` and `/webhook/<path>` **[path prefixes not stated on the fetched page; standard n8n behavior]**.
- Path params: `/:var1/path/:var2`.
- Auth: None, Basic auth, **Header auth** (a credential with a header name and value), JWT auth. **No native HMAC verification.** To verify one, enable the **Raw Body** option, recompute the signature with the **Crypto** node (Hmac, SHA256/SHA384/SHA512/MD5/SHA3-*, encoding HEX or BASE64), compare in an IF node, and reply with Respond to Webhook (401).
- Respond modes: Immediately ("Workflow got started"), When Last Node Finishes, Using 'Respond to Webhook' node (`responseMode: "responseNode"`), Streaming.
- Options: IP(s) allowlist, CORS, custom response code and headers. Max payload is 16 MB (env-configurable).

### Workflow JSON
Minimum shape (verified from the template API):
```json
{
  "name": "GTMOS inbound lead",
  "nodes": [
    { "id": "uuid", "name": "Webhook", "type": "n8n-nodes-base.webhook", "typeVersion": 1,
      "position": [375, 115], "webhookId": "uuid",
      "parameters": { "path": "gtmos-lead", "httpMethod": "POST", "responseMode": "responseNode", "options": {} },
      "credentials": { "httpHeaderAuth": { "id": "1", "name": "GTMOS header" } } },
    { "id": "uuid2", "name": "Respond to Webhook", "type": "n8n-nodes-base.respondToWebhook",
      "typeVersion": 1, "position": [600, 115], "parameters": {} }
  ],
  "connections": {
    "Webhook": { "main": [ [ { "node": "Respond to Webhook", "type": "main", "index": 0 } ] ] }
  },
  "settings": { "executionOrder": "v1" },
  "active": false
}
```
- `connections` is keyed by **source node name**. `main[outputIndex]` is an array of targets `{node, type, index}`, where `index` is the target input.
- `nodes[].credentials` references credentials by id and name only. Secrets are never exported, but names may be sensitive.
- Other top-level keys seen in full exports: `pinData`, `meta`, `versionId`, `tags`, `id` **[unverified which are required on import]**.
- `httpHeaderAuth` credential type name and `httpMethod` param name **[unverified this session]**.
- The new `n8n-cli package` bundles workflows into `.n8np`. Server CLI export/import is slated for deprecation.
- The Error Trigger node (`n8n-nodes-base.errorTrigger`) runs the error workflow.

---

## Apollo

Sources: https://docs.apollo.io/reference/people-enrichment, https://docs.apollo.io/reference/bulk-people-enrichment, https://docs.apollo.io/reference/organization-enrichment

- Base URL `https://api.apollo.io/api/v1`. Header `x-api-key: <key>`.
- People match: `POST /people/match`. Params: `first_name`, `last_name` | `name`, `email` | `hashed_email` (MD5/SHA-256), `organization_name` | `domain`, `id`, `linkedin_url`, `reveal_personal_emails`, `reveal_phone_number`, `run_waterfall_email`, `run_waterfall_phone`, `webhook_url`, `poll_only`.
  - Phone reveal or waterfall is **async**: it needs `webhook_url` or `poll_only=true` (not both).
- Bulk: `POST /people/bulk_match` with body `{ "details": [ {...}, ... ] }`, **max 10 per request**.
- Org enrich: `GET /organizations/enrich?domain=apollo.io` (no `www.`/`@`). Optional `linkedin_url`, `website`, `name`. Costs 1 credit per org.
- Credits: 1 credit for demographics/email, plus 8 if a mobile phone is returned. Nothing is charged when nothing credit-consuming is found. Waterfall vendor costs vary.
- Response `match_confidence`: `high` | `medium` | `low` | `none`.
- Rate limits are plan-dependent. The docs show a default of 600/hour for `/people/match`. Query the rate-limit endpoint for actual limits **[path unverified]**.

---

## Clay (no public REST API relied on)

Sources: https://www.clay.com/faq/do-unsuccessful-searches-consume-data-credits-what-about-actions, https://www.clay.com/guides/waterfall-enrichment, https://university.clay.com/docs/claygent-builder

- Waterfall: providers run in order, and each record stops at the first confident result. Data Credits are charged only for the provider that returns data. If nothing is found, no credits or actions are consumed.
- Claygent is Clay's AI web-research agent, with optional web search, reusable "Skills" (instructions, quality bar, output format) and attachable docs. Claygent Builder is used to build, test and deploy these agents.
- Integration pattern: Clay tables take input via webhook source and push out through HTTP API actions or native CRM integrations **[specific Clay webhook limits unverified]**.

---

## Reverse ETL: Hightouch and Census (Fivetran Activations)

Sources: https://hightouch.com/docs/getting-started/concepts, https://hightouch.com/docs/syncs/types-and-modes, https://fivetran.com/docs/activations/syncs

### Hightouch
- Source (warehouse/DB), then **Model** (SQL, table, dbt or BI). "Every model requires a unique primary key to identify each row and track changes between syncs." Then **Sync**: type, mode, field mapping, record matching and schedule (interval, cron, or trigger from dbt Cloud/Airflow).
- Modes: Insert, Update, Upsert, Add, Remove (lists), Archive, All/Mirror ("overwrites all existing records in your destination"), Snapshot and Diff (file destinations).
- Record matching maps the model column to the destination identifier (for example, HubSpot company custom unique property or contact email).
- CDC: compares against the previous run and sends only new, changed and removed rows. Delete behavior is configured separately from mode.

### Census, now Fivetran Activations (`docs.getcensus.com` 301s to `fivetran.com/docs/activations`)
- Behaviors: Update or Create (upsert), Update Only, Create Only, Mirror (add, update and remove), Append (immutable log, usually no key), Delete (by ID list).
- All except Append require a **sync key** that matches source to destination.

### GTMOS adapter implications
- The model needs a primary key, and the sync maps it to a match key (`idProperty`).
- Compute a diff hash per row per run and send only changed rows.
- Mirror mode needs explicit delete semantics (archive in the CRM, never hard delete by default).
