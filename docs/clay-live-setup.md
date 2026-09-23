# Connecting a live Clay workspace to GTMOS

**Status: NOT verified against a live Clay workspace.** No Clay account exists for this project and
no request has ever been made to `clay.com` or `api.clay.com` from this codebase. Everything below is
built and tested against Clay's published contract as recorded in
[`docs/research/clay.md`](research/clay.md). The last section says precisely which claims are proven
and which are not. Read it before you repeat any of this to anyone.

---

## 1. What GTMOS expects Clay to be

GTMOS treats Clay as a **per-field resolution service**, not a system of record. Clay resolves
commodity data — headcount, industry, work email, tech stack — across a provider waterfall GTMOS has
no contracts to replicate. GTMOS owns identity, ICP scoring, provenance, trust and everything
downstream. Data flows Clay → GTMOS. It never flows back as authority, which is also the technical
reality: Clay's Public API cannot write rows into Clay tables.

There are two directions, and they are gated very differently:

| Direction | Mechanism | Clay plan required |
| --- | --- | --- |
| Clay → GTMOS (the one that carries data) | HTTP API enrichment column POSTing to GTMOS | **Growth**, $495/mo |
| Clay → GTMOS (run finished, notification only) | Public API signed webhook | Free |
| GTMOS → Clay | Public API `clay-api-key` (`/me`, credits, routines) | Free |

**The important consequence:** the enriched-record push described in §3 needs a Growth plan, because
the in-table HTTP API column is a Growth feature. On Free you can still prove the whole mechanism —
signature verification, dedupe, provenance — by sending the same payload with `curl` (§8), and you
can drive the free Public API path (§7), but Clay itself will not push enriched rows to you.

---

## 2. The Clay table GTMOS expects

Create one table per ICP motion. For the ICP this deployment is tuned to — **AI/ML platform
companies, 250–5000 employees** — build it as follows.

### Source

Clay Search (Companies), filtered to:

- Industry / keywords: AI infrastructure, machine learning platform, MLOps, LLM tooling, vector database
- Headcount: 250–5000
- Geography: whatever your territory model covers (GTMOS stores `country` as ISO-3166 alpha-2 and
  `region` as one of `NA | EMEA | APAC | LATAM`)

On Free this is capped at 50 results per search and 100 results per rolling 30 days, and the table
itself is capped at 200 rows.

### Columns

Column names are matched case-insensitively and punctuation-insensitively, so `Company Domain`,
`company_domain` and `COMPANY DOMAIN` are the same column. Each GTMOS field also accepts a few
aliases. The authoritative list is served by the running API at
`GET /api/v1/integrations/clay/contract` — read it from there rather than trusting this table to stay
current.

**Account columns**

| GTMOS field | Accepted column names | Type GTMOS coerces to |
| --- | --- | --- |
| `domain` | `domain`, `company_domain`, `website`, `company_website`, `url` | bare host (`https://www.Acme.example/x` → `acme.example`) |
| `name` | `name`, `company_name`, `company`, `account_name` | text |
| `description` | `description`, `company_description`, `summary`, `about` | text |
| `industry` | `industry`, `company_industry`, `sector` | text |
| `sub_industry` | `sub_industry`, `subindustry`, `sub_sector`, `niche` | text |
| `employee_count` | `employee_count`, `employees`, `headcount`, `employee_size`, `company_size` | integer (`"1,250"` → `1250`) |
| `employee_growth_12m` | `employee_growth_12m`, `headcount_growth`, `employee_growth`, `growth_12m` | fraction (`"35%"` → `0.35`) |
| `annual_revenue_usd` | `annual_revenue_usd`, `annual_revenue`, `revenue`, `estimated_revenue` | integer (`"$12M"` is **not** parsed — send a number) |
| `founded_year` | `founded_year`, `founded`, `year_founded` | integer |
| `country` | `country`, `company_country`, `country_code` | ISO-3166 alpha-2 only |
| `region` | `region`, `company_region` | `NA` \| `EMEA` \| `APAC` \| `LATAM` |
| `city` | `city`, `company_city`, `hq_city`, `location_city` | text |
| `funding_stage` | `funding_stage`, `latest_funding_stage`, `stage` | text |
| `total_funding_usd` | `total_funding_usd`, `total_funding`, `total_raised`, `funding_total` | integer |
| `technologies` | `technologies`, `tech_stack`, `technology`, `tools` | list (a comma string is split) |
| `ai_team_size` | `ai_team_size`, `ai_headcount`, `ml_team_size` | integer |
| `ai_open_roles` | `ai_open_roles`, `ai_job_openings`, `ai_roles_open`, `open_ai_roles` | integer |
| `linkedin_url` | `linkedin_url`, `company_linkedin`, `linkedin`, `linkedin_company_url` | text |

**Contact columns** — prefix with `contact_`, `person_`, `lead_` or `prospect_` in a flat payload if
a name would otherwise collide with an account column (`linkedin_url`, `country`).

| GTMOS field | Accepted column names | Notes |
| --- | --- | --- |
| `email` | `email`, `work_email`, `business_email`, `email_address` | lowercased; an unparseable address is skipped |
| `email_status` | `email_status`, `email_verification`, `email_validity`, `email_verification_status` | `valid` \| `invalid` \| `risky` \| `unknown` |
| `first_name` / `last_name` | `first_name`/`firstname`/`given_name`, `last_name`/`lastname`/`family_name`/`surname` | text |
| `title` | `title`, `job_title`, `position` | text |
| `seniority` | `seniority`, `seniority_level` | `c_suite` \| `vp` \| `director` \| `manager` \| `ic` |
| `department` | `department`, `function`, `team` | text |
| `linkedin_url` | `contact_linkedin_url`, `person_linkedin`, `linkedin_profile` | text |
| `country` | `contact_country`, `person_country` | ISO-3166 alpha-2 |

A column GTMOS does not recognise is **not an error**: it is reported back in
`result.unmapped_columns` on the webhook response and in the stored webhook event, so a typo in a
Clay column name is visible instead of silent. Claygent free-text columns fall in this bucket
deliberately — model prose is not structured data and GTMOS will not store it as a field.

---

## 3. The recommended enrichment waterfall for this ICP

Order matters because Clay bills per hit, not per attempt: execution stops at the first provider that
returns a valid value, so cheap-and-broad goes first and expensive-and-specialist goes last, running
only on the records everyone else missed.

| GTMOS field | Waterfall order | Why this order |
| --- | --- | --- |
| `employee_count`, `industry`, `country`, `city` | Clay's own company database → one general firmographics provider → website scan | Firmographics are the cheapest thing Clay sells and the most widely covered; a second opinion here is rarely worth an Action |
| `technologies` | A tech-detection provider (BuiltWith-class) → website scan → Claygent as last resort | Detection beats inference; Claygent output lands as low-trust text and is ignored unless mapped to `technologies` explicitly |
| `total_funding_usd`, `funding_stage` | A funding-data provider → Clay's company database | Funding data is a specialist feed and stale copies are common |
| `ai_team_size`, `ai_open_roles` | A jobs/hiring-signal provider → Claygent over the careers page | This is the ICP-defining pair for an AI/ML platform buyer and the hardest to buy; expect low coverage |
| Contact `email` | Clay's work-email waterfall, 4–6 providers deep | This is the single strongest argument for Clay: no one vendor finds more than about half a list |
| Contact `email_status` | A verification provider immediately after the email waterfall | GTMOS routes on `email_status`; an unverified address is worse than none |

Two configuration choices that matter more than the ordering:

1. **Turn on "output the name of the successful provider"** on every waterfall column. It is opt-in
   and off by default. Without it GTMOS can only record `source: clay`, which tells a rep nothing
   about whether to trust the value. With it, GTMOS records `clay:<provider>` (§5).
2. **Bring your own API keys** where you already have vendor contracts. You then pay only the Action
   and skip Data Credits entirely.

Free-plan ceiling to design around: 100 Data Credits and 500 Actions per month, and Clay's own figure
of 6–20 Data Credits for a fully enriched record. That is roughly 5–16 complete records a month. It
is enough for a smoke test and nothing else — do not draw a coverage or match-rate conclusion from it.

---

## 4. The exact payload GTMOS parses

**Clay has no standard outbound envelope.** The HTTP API column's body is a JSON template you
hand-write, referencing columns with a leading slash. So this contract is GTMOS's, and this document
is what the column is configured against.

Every field may be sent in either of two forms:

- **bare** — `"industry": "AI/ML Platforms"`
- **wrapped** — `{"value": ..., "provider": ..., "confidence": ..., "observed_at": ..., "status": ..., "others": [...]}`

Use the wrapped form wherever the Clay column can supply provenance. `status` is how a cell says it
did not resolve: `empty`, `pending` or `errored` are all skipped without failing the row. `others`
carries the waterfall steps that lost, if you chose to emit them.

### The body to paste into the Clay HTTP API column

```json
{
  "clay_row_id": "/Row ID",
  "clay_run_id": "/Run ID",
  "clay_table_id": "t_ai_ml_icp",
  "observed_at": "/Enriched At",
  "account": {
    "domain": "/Company Domain",
    "name": "/Company Name",
    "industry": { "value": "/Industry", "provider": "/Industry Provider", "confidence": 0.85 },
    "employee_count": { "value": "/Employee Count", "provider": "/Headcount Provider" },
    "employee_growth_12m": "/Headcount Growth",
    "total_funding_usd": "/Total Funding",
    "funding_stage": "/Funding Stage",
    "technologies": "/Tech Stack",
    "ai_open_roles": "/AI Job Openings",
    "country": "/Country Code",
    "city": "/City",
    "linkedin_url": "/Company LinkedIn"
  },
  "contact": {
    "email": { "value": "/Work Email", "provider": "/Email Provider" },
    "email_status": "/Email Verification",
    "first_name": "/First Name",
    "last_name": "/Last Name",
    "title": "/Job Title",
    "seniority": "/Seniority",
    "department": "/Department"
  }
}
```

Tick **"remove empty fields from request"** in the column config. GTMOS handles absent and null
fields identically, so this only saves bytes — but it also keeps the stored webhook payload readable.

A **flat** payload works too (all columns at the top level, no `account`/`contact` nesting), which is
the shape an HTTP API column produces most naturally. Prefix contact columns with `contact_` when the
name would otherwise collide with an account column.

### What GTMOS answers

`200` with the processing result, or `202` if the row was accepted but processing failed and will be
retried on redelivery:

```json
{
  "id": "1f0c…", "status": "processed", "duplicate": false, "signature": "valid",
  "result": {
    "kind": "enriched_record", "matched": true,
    "clay_row_id": "row_abc", "clay_run_id": "run_xyz",
    "account": { "id": "…", "domain": "acme.example", "created": false,
                 "fields": {"set": ["industry"], "updated": [], "kept": [], "conflicted": ["employee_count"]},
                 "conflicts": [ … ] },
    "contact": { "id": "…", "created": true, "fields": { … }, "conflicts": [] },
    "skipped_fields": [{"entity": "account", "field": "city", "reason": "empty"}],
    "unmapped_columns": ["claygent_notes"]
  }
}
```

`401` means the signature did not verify; nothing was stored. `400` means the body was not JSON.
`413` means the body exceeded 1 MB.

---

## 5. What GTMOS does with the row

1. **Identity.** The account is resolved by normalised domain, falling back to the domain of the work
   email. A row with no usable domain is acknowledged and dropped — guessing an identity creates
   duplicate accounts, which cost far more than a dropped row. An unknown domain creates a new account
   with `source=clay`.
2. **Merge.** Every field goes through the same merge policy provider enrichment uses
   (`domain/enrichment.py`). A Clay value **never** overwrites a manually locked field. A value that
   materially disagrees with an existing **confident** value (≥ 0.6) produces a `conflict`: the
   existing value is kept and the disagreement is raised for review, rather than the marginally more
   self-assured source winning silently. The same value, casing differences, and headcounts within
   15% of each other are not disagreements.
3. **Provenance.** Every written field gets a `field_provenance` row recording the value, the source,
   the confidence and when it was observed. The source is `clay` — narrowed to `clay:<provider>` only
   when the waterfall column was configured to emit its winner. **Clay publishes no uniform confidence
   score and no per-cell enrichment timestamp**, so when a column supplies neither, GTMOS records its
   own policy confidence of `0.7` and stamps `observed_at` from the payload envelope or its own
   receipt time. That number is GTMOS's, not Clay's, and is documented as such in `clay_service.py`.
4. **Partial rows are normal.** Unresolved cells are listed in `skipped_fields` with a reason and the
   rest of the row is applied.
5. **Idempotency.** Deliveries are deduplicated on `clay_row_id` (plus `clay_run_id` when present),
   through the same webhook pipeline PostHog, n8n and HubSpot use. A redelivery returns
   `"duplicate": true` and the original event id. Clay sends no timestamp with its signature, so this
   dedupe — not the signature — is what provides replay protection.

---

## 6. Configuring the connection

### On the GTMOS side

```bash
# .env
CLAY_WEBHOOK_SECRET=<the signingSecret Clay shows exactly once>
WEBHOOK_SECRET=<any strong random string>   # set this too in production; see the note below
CLAY_API_KEY=<optional; only needed for the outbound direction in §7>
```

Restart the API. Verify with:

```bash
curl -s localhost:8010/api/v1/integrations/clay/contract | jq '.webhook_secret_configured, .outbound.mode'
```

> **Production note.** `webhook_service`'s verifier is keyed by source and does not know Clay's
> scheme, so `clay_service` verifies the Clay HMAC at the boundary and passes the verified outcome
> into the pipeline as the internal shared-token attestation. That attestation needs `WEBHOOK_SECRET`
> to be set. In development both may be omitted and the delivery is recorded with
> `signature: "not_configured"`; in production a missing `CLAY_WEBHOOK_SECRET` rejects every delivery.

### On the Clay side

1. Open the table → `+ Add` → **HTTP API** column (Growth plan).
2. Method `POST`, URL `https://<your-host>/api/v1/webhooks/clay`.
3. Body: the JSON from §4.
4. Headers: `Content-Type: application/json`.
5. **Signature.** Clay signs Public API webhooks automatically, but an HTTP API *column* does not sign
   for you — it sends only the headers you configure. If your Clay plan cannot compute an HMAC in a
   column, the honest options are (a) put the column behind a Clay-managed function or a small proxy
   that signs, or (b) register a Public API webhook (§7) and let GTMOS pull the results. Do not
   disable verification in production to work around this.
6. Set the column to run on new rows, and rate-limit it to something your API can absorb.

---

## 7. The outbound direction (Public API, free plan)

GTMOS ships a client for Clay's Public API in `apps/api/src/gtmos/integrations/clay.py`. It is
**inert without `CLAY_API_KEY`**: every method raises `ClayNotConfigured` before any socket is opened,
so demo mode cannot bill a workspace. Nothing in GTMOS calls it automatically.

```python
from gtmos.config import get_settings
from gtmos.integrations.clay import ClayClient

client = ClayClient.from_settings(get_settings())
client.me()                                        # GET /public/v0/me
client.credits()                                   # reading balances consumes nothing
run_id = client.run_routine("routine_1", [{"domain": "acme.example"}], webhook_id="wh_abc123")
run = client.wait_for_results(run_id)              # 202 + progress until terminal
run.failed_items                                   # a complete run can still contain failed items
```

Behaviour it implements from Clay's documented contract: `clay-api-key` header, 15-second timeout,
429 backoff honouring `Retry-After` (Clay does not publish the numeric limit), 402 raised as a
distinct `ClayQuotaExceeded` because a plan limit is not something to retry, thin `{"message": ...}`
error bodies surfaced as-is because Clay has no stable error codes, and unrecognised terminal
statuses flagged rather than assumed successful — Clay explicitly warns that the status set is not
closed.

To register the free-plan signed webhook:

```bash
clay webhooks create https://<your-host>/api/v1/webhooks/clay   # returns signingSecret ONCE
```

Put that `signingSecret` in `CLAY_WEBHOOK_SECRET`. Clay will then POST
`{"webhookId": "...", "createdAt": "...", "data": {"routine_run_id": "..."}}` when a run finishes.
GTMOS recognises this as a **notification, not a record**: it stores it, deduplicates on the run id,
and says so in the result. Fetching the actual results requires `CLAY_API_KEY`.

---

## 8. Validation procedure

This proves the inbound path without a Clay account, using the same signature Clay would compute.

```bash
export CLAY_WEBHOOK_SECRET='clay-signing-secret'   # must match the API's environment

BODY='{"clay_row_id":"row_demo_1","clay_run_id":"run_demo_1","clay_table_id":"t_ai_ml_icp",
"observed_at":"2026-09-22T11:00:00Z",
"account":{"domain":"acme-ai.example","name":"Acme AI","industry":{"value":"AI/ML Platforms","provider":"clearbit","confidence":0.88},
"employee_count":{"value":1250,"provider":"apollo"},"technologies":"Snowflake, Ray, dbt",
"city":{"value":null,"status":"empty"}},
"contact":{"email":"dana.reyes@acme-ai.example","title":"VP of Machine Learning","email_status":"valid"}}'

SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$CLAY_WEBHOOK_SECRET" -r | cut -d' ' -f1)"

curl -sS -X POST http://localhost:8010/api/v1/webhooks/clay \
  -H 'Content-Type: application/json' \
  -H "X-Clay-Signature: $SIG" \
  --data-raw "$BODY" | jq
```

Expected, in order:

1. **`signature` is `"valid"` and `status` is `"processed"`.**
2. `result.account.created` is `true` on the first run (the domain is new) and the account carries
   `industry`, `employee_count` and `technologies`.
3. `result.skipped_fields` contains `{"entity":"account","field":"city","reason":"empty"}` — a partial
   row succeeded.
4. **Re-run the exact same command.** The response must come back with `"duplicate": true` and the
   same `id`. That is the idempotency guarantee.
5. **Break the signature** (`-H "X-Clay-Signature: sha256=deadbeef"`). The response must be `401` and
   no new webhook event may appear.
6. Confirm provenance landed:

```bash
curl -s "localhost:8010/api/v1/webhooks/events?source=clay" | jq '.items[0] | {status, signature_status, duplicate_count}'
```

The account's fields should now show `clay:clearbit` and `clay:apollo` as their sources on the
account page, with `city` untouched.

---

## 9. What is proven, and what is not

**Proven, in this repository, with no Clay account:**

- Signature verification against Clay's documented `X-Clay-Signature` HMAC-SHA256 scheme: valid,
  tampered body, wrong secret and missing header all behave correctly (`tests/unit/test_clay.py`).
- Column mapping, type coercion, alias handling and unmapped-column reporting.
- Partial enrichment: `empty` / `pending` / `errored` cells are skipped and the rest of the row lands.
- Provenance recording, manual-lock protection, and conflict-versus-overwrite behaviour, reusing the
  same merge policy as provider enrichment — including that a Clay conflict reaches the existing
  data-quality rule unchanged.
- Idempotency on `clay_row_id` / `clay_run_id`, end to end through the shared webhook pipeline
  (`tests/integration/test_clay_ingestion.py`).
- The outbound client's request shape, auth header, 429/402/5xx handling and 202-then-200 polling,
  under `httpx.MockTransport`.

**NOT proven, and requiring a live Clay workspace:**

- That a real Clay HTTP API column can be configured to send a signed request at all (§6 step 5). This
  is the biggest open question in this document.
- That Clay's actual signature covers exactly the bytes we assume, in exactly the `sha256=<hex>`
  format. The format is documented; it has not been observed.
- That the column names in §2 correspond to anything in a real Clay table — those are GTMOS's names,
  and a real table's columns must be mapped onto them by hand.
- That `provider`, `confidence` and `observed_at` can be emitted from a Clay column in the wrapped
  shape §4 describes. The waterfall provider name is documented as available; confidence and per-cell
  timestamps are **not documented at all** and may simply not exist.
- Any latency, throughput, coverage or match-rate figure. Clay publishes none, and the free tier's
  ~5–16 fully enriched records per month could not establish one anyway.
- Whether the inbound webhook *source* (Clay receiving data) is plan-gated. Clay's docs and pricing
  page disagree; see `docs/research/clay.md` §5a.
- Whether "Clay API access" on the pricing page gates the routines/searches API or only the
  Enterprise Tables API. Two official Clay pages contradict each other on this.

The honest claim this work supports is: *the Clay integration boundary is implemented against Clay's
documented Public API and signed-webhook contract, with the async lifecycle, per-item status handling,
402/429 backoff and provenance stamping built and tested against payload shapes taken from Clay's
published documentation. It has not been verified against a live Clay workspace.* Nothing more.
