# Clay (clay.com) — what is actually possible without a paid plan

Research date: 2026-09-22. All claims below are sourced to clay.com, university.clay.com
(Clay's help centre) or developers.clay.com (Clay's developer docs). Anything not confirmable
from those is marked **UNCONFIRMED**.

---

## What can be verified without payment

A free Clay account **can** build and verify a real two-way integration with a self-hosted
system — but only through Clay's **Public API**, not through the in-product integration
columns. Clay states plainly that "the developer platform is available across all Clay plans,
including free and trial plans"
([Clay Agent Plugin docs](https://university.clay.com/docs/clay-api-cli)), so a free account can
mint an API key, call `https://api.clay.com/public/v0/...`, run enrichment routines, read table
rows, and register a **signed outbound webhook** that Clay POSTs to an arbitrary URL when a run
finishes ([Webhooks](https://developers.clay.com/public-api/webhooks)). That is a genuine
round trip: our system → Clay → our HTTP endpoint → our system.

What a free account **cannot** do is the thing most people mean by "Clay integration": the
in-table **HTTP API enrichment column** and **webhook automation** are both listed under the
Growth plan's "Everything in Launch, plus… Integrate with any HTTP API / Automate any signal via
webhook" ([clay.com/pricing](https://www.clay.com/pricing)) — $495/mo. Structured table queries
(joins, ranges, paging past 100 rows) are Enterprise-only
([Tables](https://developers.clay.com/tables)).

The free ceiling is also low enough to matter: **100 Data Credits and 500 Actions per month,
200 rows per table, and 100 search results per rolling 30 days**
([pricing](https://www.clay.com/pricing),
[Searches](https://developers.clay.com/searches)). That is enough to prove an integration
works end to end; it is not enough to demo volume.

**Bottom line for the portfolio project:** the integration boundary can be genuinely built and
genuinely exercised against live Clay on $0 via the Public API. Claim that, and nothing more.

---

## 1. What Clay is

Clay is a GTM (go-to-market) data platform built around **tables**. A table looks like a
spreadsheet — rows are records (a company, a person, a deal), columns are fields — but the
column model is the whole difference: in Clay a column is not a stored value or a formula over
other cells, it is **an action that runs per row**. A column can call a data provider, call an
AI agent, call an arbitrary HTTP endpoint, or run a formula. Clay's own docs describe the HTTP
API column as processing "data row by row"
([HTTP API](https://university.clay.com/docs/http-api-integration-overview)).

The vocabulary:

| Concept | What it is |
| --- | --- |
| **Source** | How rows get into a table: CSV upload, CRM/warehouse import, Clay's own Search over its GTM database, or a **webhook** URL Clay generates for you ([Webhooks in Clay](https://university.clay.com/docs/webhook-integration-guide)) |
| **Enrichment** | A column that calls a provider or Clay-managed function to fill a value for that row |
| **Formula** | A local computation over other columns. Free — formulas and filters consume neither Actions nor Data Credits ([Actions & Data Credits](https://university.clay.com/docs/actions-data-credits)) |
| **Claygent** | An AI research agent packaged as a column (see §7) |
| **Waterfall** | An ordered fallback chain across providers (below) |
| **Routine** | The API-side name for runnable Clay logic: Clay-managed functions, custom functions, and Workflows ([Routines](https://developers.clay.com/routines/api)) |

### The waterfall

This is Clay's central product idea and the strongest argument for buying rather than building.
A waterfall column lets you "utilize multiple data providers in a predetermined sequence, so you
don't duplicate tasks or spend extra credits"
([Waterfalls](https://university.clay.com/docs/building-a-data-waterfall)). You add a column,
pick the waterfall data type (work email, phone, etc.), then add, reorder, toggle and delete
provider steps. Execution stops at the first provider that returns a valid value, so you pay for
the hit, not for the attempts.

The problem it solves: no single contact-data vendor has good coverage. Any one provider finds
maybe half your list. Ordering cheap-broad providers first and expensive-specialist providers
last means the expensive vendor only ever runs on the records everyone else missed. Clay's
[work email waterfall](https://university.clay.com/docs/work-email-waterfall) cascades across a
large set of email providers this way.

Crucially for a receiving system, the waterfall can **"optionally, choose to output the name of
the successful provider"** ([Waterfalls](https://university.clay.com/docs/building-a-data-waterfall)).
See §9.

---

## 2. The credit model

Clay changed its pricing model in 2026 and now bills on **two separate meters**
([pricing FAQ](https://www.clay.com/pricing)):

- **Actions** — "the orchestration you do on Clay — enriching data, running a table, calling an
  AI model, sending data to a third-party system, or exporting data out of Clay." Start at
  "less than $0.01 each."
- **Data Credits** — "used when you purchase data from Clay's marketplace." Start at **$0.05
  each**.

What consumes **Actions** ([Actions & Data Credits](https://university.clay.com/docs/actions-data-credits)):
each enrichment from any provider, AI uses, signals, CRM exports and syncs, data warehouse
exports, **HTTP API calls**, ads audience exports, and sending emails. Using your own API keys
still consumes an Action.

What consumes **Data Credits**: buying data or AI from Clay's marketplace. Clay says a fully
enriched record "typically costs 6–20 Data Credits," varying by data type — emails cheap, phone
numbers expensive.

What is **free** (neither meter): sourcing/search result lists, CRM imports, data warehouse
imports, **Clay formulas and filters**, Send Table Data between Clay tables, and Lookup Single
Row in Other Table.

Two billing rules that matter for integration design:

1. **No result, no charge.** "If an enrichment returns no result, you're not charged Data
   Credits or Actions" ([pricing FAQ](https://www.clay.com/pricing)).
2. **Bring your own key and you skip Data Credits entirely**, paying only the Action — "If you
   bring your own API keys for third-party data, you skip Data Credit costs entirely and only
   use Actions for the platform work Clay handles behind the scenes"
   ([pricing FAQ](https://www.clay.com/pricing)). This is the cheapest way to run Clay as pure
   orchestration.

**Per-row cost is therefore not a single number.** One row that runs a three-step waterfall and
hits on step two costs one Action plus that provider's Data Credits. There is no flat per-row
price.

**Free plan allowance: 100 Data Credits/mo and 500 Actions/mo**
([pricing](https://www.clay.com/pricing)). It renews monthly. It does **not** roll over — the
comparison table marks "Rollover credits" as *Not included* for Free; rollover (up to 2x monthly
credits) begins on Launch and Growth, and Actions never roll over on any plan because they
"reset each billing cycle."

---

## 3. Pricing tiers as of 2026-09-22

Clay's current self-serve ladder is **Free / Launch / Growth / Enterprise**. The older
**Starter ($149), Explorer ($349) and Pro ($800)** names no longer appear on clay.com/pricing;
they are legacy plans. Clay's developer docs note only that "legacy plans also have access for a
limited time" ([Agent Plugin docs](https://university.clay.com/docs/clay-api-cli)). *Legacy plan
pricing and grandfathering terms: **UNCONFIRMED** from an official Clay page — do not quote
Starter/Explorer/Pro figures.*

From [clay.com/pricing](https://www.clay.com/pricing):

| | **Free** | **Launch** | **Growth** | **Enterprise** |
| --- | --- | --- | --- | --- |
| Price | $0 | from **$185/mo** ($167/mo annual) | from **$495/mo** ($446/mo annual) | Custom, annual commitment |
| Data Credits | 100/mo | 2,500/mo | 6,000/mo | 100,000+/mo |
| Actions | 500/mo | 15,000/mo | 40,000/mo | 200,000+/mo |
| Rows per table | 200 | 50,000 | *not stated* | Unlimited bulk enrichment |
| Seats | Unlimited | Unlimited | Unlimited | Unlimited |
| Table version history | Not included | 1 month | 6 months | 6 months |
| Source sync frequency | — | 1 day | 15 min | 15 min |
| Credit rollover | Not included | up to 1 month's credits | up to 1 month's credits | 15% of annual |
| Credit top-ups | Not included | at 30% premium | at 30% premium | custom price |

### Feature gating — the part that decides everything

| Capability | Free | Launch | Growth | Enterprise |
| --- | --- | --- | --- | --- |
| Multi-provider waterfalls | ✅ | ✅ | ✅ | ✅ |
| Claygent enrichment | ✅ | ✅ | ✅ | ✅ |
| Clay Sequencer (email) | ✅ | ✅ | ✅ | ✅ |
| **Public API / CLI / agent plugin** | **✅** | ✅ | ✅ | ✅ |
| Phone number enrichment | ❌ | ✅ | ✅ | ✅ |
| Job change & signal tracking | ❌ | ✅ | ✅ | ✅ |
| **HTTP API integration column** | ❌ | ❌ | **✅** | ✅ |
| **Webhook automation** | ❌ | ❌ | **✅** | ✅ |
| CRM auto-sync & enrichment | ❌ | ❌ | ✅ | ✅ |
| Data warehouse sync | ❌ | ❌ | ✅ | ✅ |
| **Tables API (structured queries)** | ❌ | ❌ | ❌ | **✅** |
| SSO / RBAC | ❌ | ❌ | ❌ | ✅ |

Sources: the plan comparison table and FAQ on [clay.com/pricing](https://www.clay.com/pricing)
(Growth = "Everything in Launch, plus… Integrate with any HTTP API / Automate any signal via
webhook"; Enterprise = "everything in Growth, plus… Clay API access, data warehouse syncs, SSO,
RBAC"), cross-read against
[Agent Plugin docs](https://university.clay.com/docs/clay-api-cli) and
[Tables](https://developers.clay.com/tables).

> **Important contradiction, stated honestly.** The pricing FAQ lists "Clay API access" as an
> Enterprise inclusion. Clay's developer documentation says the opposite for the Public API as a
> whole: "The developer platform is available across all Clay plans, including free and trial
> plans" ([Agent Plugin docs](https://university.clay.com/docs/clay-api-cli)). The reconciliation
> that fits both is in the same doc's FAQ: *"Basic row reads work on any plan. Structured queries
> — joins, ranges, and paging past 100 rows — need API table sync, an Enterprise feature."* So
> "Clay API access" on the pricing page most likely means the **Tables/warehouse-grade** API
> surface, while routines, searches and webhooks are open to everyone. **This should be verified
> against a live free workspace before the project claims it**, because two official Clay pages
> disagree on the wording.

---

## 4. Getting data OUT of Clay

There are three distinct exits, gated differently.

### (a) HTTP API enrichment column — Growth ($495/mo)

Clay's own integration column: "send or retrieve data from any tool or database using an API
endpoint, even when Clay doesn't offer a native integration"
([HTTP API](https://university.clay.com/docs/http-api-integration-overview)). It supports
**GET, POST, PUT and DELETE**, and you configure the endpoint URL, query string params, a JSON
body, header fields for auth, response field paths to map back into columns, and rate-limiting
controls. It runs **per row**.

**Payload shape: you define it.** There is no standard Clay envelope. The body is a JSON
template you hand-write, referencing columns with a leading slash — `"name": "/Column Name"` for
strings, `/Column Number` unquoted for numbers. There is an option to "remove empty fields from
request." This is good news for a receiving system (you control the contract exactly) and bad
news for anyone hoping to document "the Clay payload" — there isn't one.

**Can a free account POST to an arbitrary external URL this way? No.** The column is a Growth
feature per the pricing comparison table.

### (b) Public API webhooks — available on Free

Clay will POST to an arbitrary URL you register when a **routine run** finishes
([Webhooks](https://developers.clay.com/public-api/webhooks)). Register with
`clay webhooks create https://example.com/hooks/clay`; the response returns a `signingSecret`
**exactly once**. Pass `webhook_id` when starting a run.

The delivery payload is small and fixed — it is a notification, not the data:

```json
{
  "webhookId": "wh_abc123",
  "createdAt": "2026-06-16T17:50:00.000Z",
  "data": { "routine_run_id": "run_abc123" }
}
```

For test events `data` is `{}`. Clay signs the exact request body with the signing secret and
sends `sha256=<hex>` in the **`X-Clay-Signature`** header (HMAC-SHA256). Verify, then fetch
results from `GET /public/v0/routines/run/{id}/results`. This is a notify-then-pull pattern, so
the receiving system needs both an inbound endpoint and an outbound API client.

### (c) Native integrations and exports

Clay ships native connectors (CRMs, sequencers, Slack, ad platforms, Zapier —
[Send Clay data to Zapier](https://university.clay.com/docs/clay-to-zapier)). CRM auto-sync and
warehouse sync are Growth+; ads audience push is Growth+. All exports consume Actions.

---

## 5. Getting data INTO Clay

### (a) Webhook as a source

Every Clay table can be given a generated inbound URL: in a workbook, `+ Add` → search
"Webhooks" → `Monitor webhook`. Clay returns a unique URL and an optional cURL command. POST
JSON to it and a row appears. You can optionally secure it with an auth token in the request
headers — "Make sure to copy the token immediately, as you can only access authentication tokens
once" ([Webhooks in Clay](https://university.clay.com/docs/webhook-integration-guide)).

**Limit: "Webhook sources are limited to 50,000 submissions, and this limit persists even after
deleting rows."** Past that you create a new table. Enterprise gets an auto-delete (passthrough)
mode for unlimited submissions.

*Plan gating of the inbound webhook source specifically:* **UNCONFIRMED**. The pricing page gates
"Automate any signal via webhook" to Growth, but the webhook docs never state a plan requirement
for using a webhook as a table source, and the free tier's 200-row table cap would bind long
before the 50,000-submission cap. Assume it may be gated; verify in a live free workspace.

### (b) The Public API — read-only for tables

You **cannot** write rows through the API. Clay is unambiguous: *"Can I build or write to Clay
tables via CLI or API? No… Tables in the Public API is read-only — you can query and read rows,
but not create tables, add fields, or write records. There are no current plans to support table
building from the API or CLI"* ([Agent Plugin docs](https://university.clay.com/docs/clay-api-cli)).

So the inbound path for row data is the webhook source or a CSV/CRM import — not the API. The
API's write-equivalent is **running a routine with your own inputs** (§6), which returns results
to you rather than persisting rows in a table.

---

## 6. Clay's public API

Yes — Clay has a documented public REST API at **developers.clay.com**, and it is more real than
its reputation suggests.

- **Base URL:** `https://api.clay.com/public/v0`
- **Auth:** a single header, **`clay-api-key: <key>`**. Keys are created in
  *Settings → Account → API keys (beta)*, or via `clay api-keys create`. The key is shown once.
  Keys are "tied to a Clay user and workspace access"
  ([Authentication](https://developers.clay.com/public-api/authentication)).
- **Beta:** the API-keys surface is labelled **(beta)** in the Clay UI; **Workflows** via
  CLI/plugin are explicitly **Beta**, and Clay recommends Clay-managed or custom functions "for
  production use." The workflow-run query endpoints are marked beta too.
- **No OAuth, no scopes, no rotation documented.** One static workspace-scoped key.

Endpoint groups ([llms.txt index](https://developers.clay.com/llms.txt)):

| Group | Notable endpoints |
| --- | --- |
| Me | `GET /me` — authenticated user and workspace |
| Credits | `GET` workspace credit balances — "Reading balances does not consume credits" |
| Routines | `POST /routines/{routine_id}/run` (1–100 items), `GET /routines/run/{id}/results`, batch run over a presigned-uploaded JSONL |
| Searches | query-mode search over Clay's GTM database (filters-mode is deprecated) |
| Tables | `POST /tables/query` — **Enterprise** |
| Workflows runs | query runs (beta) |

**Async by design.** `POST /routines/{id}/run` returns a `routine_run_id`; the results endpoint
returns **HTTP 202** with `{status, total, finished}` progress counters while running, and
**HTTP 200** with `status: "complete"` when done
([Routines API](https://developers.clay.com/routines/api)). Clay tells you to poll "at a modest
interval" — or register a webhook and skip polling.

**Rate limits** ([Rate limits](https://developers.clay.com/public-api/rate-limits)): a
per-workspace request rate limit; `429` with a `Retry-After` header in seconds, and
`X-RateLimit-Limit` / `-Remaining` / `-Reset` "when available." **The numeric limit is not
published** — UNCONFIRMED. The CLI signals rate limiting with exit code `4`.

**Errors** ([Errors](https://developers.clay.com/public-api/errors)): non-2xx returns
`{"message": "..."}` only — *"Error response bodies do not currently include stable error
codes."* Use the HTTP status as the machine-readable category. Clay also warns: on a terminal
200, "treat unrecognized `status` values as an unhandled terminal outcome — do not assume the set
of statuses is closed." That is a real instruction for a defensive client.

**Search quotas by plan** ([Searches](https://developers.clay.com/searches)) — note these are
tighter than the general credit allowance:

| Plan | Results/request | Results/search | Results/period |
| --- | --- | --- | --- |
| Free | 50 | 50 | 100 per rolling 30 days |
| Trial | 50 | 50 | 10,000 for the trial |
| Paid | 500 | up to period limit | 1,000,000 per 30 days |
| Enterprise | 500 | up to period limit | 10,000,000 per 30 days |

Exceeding a limit returns **HTTP 402** naming the limit hit.

**No extra cost for the API:** *"API and CLI calls consume the same credits and actions as the
equivalent work done in-product. There is no additional cost"*
([Agent Plugin docs](https://university.clay.com/docs/clay-api-cli)).

**Platform note:** the CLI runs on macOS and Linux; Windows requires WSL.

---

## 7. Claygent and AI columns

Claygent is Clay's AI research agent exposed as a column — give it a prompt and a target (a
domain, a person) and it does web research and returns a structured answer. It is available on
**all plans including Free** ([pricing](https://www.clay.com/pricing) FAQ: Free "includes…
Claygent enrichment"). There is a
[Claygent Builder](https://university.clay.com/docs/claygent-builder).

Cost: a run is **one Action plus Data Credits that vary by model**
([Actions & Data Credits](https://university.clay.com/docs/actions-data-credits)). Clay now runs
two AI pricing modes ([pricing FAQ](https://www.clay.com/pricing)):

- **Fixed-price** — "80% of models in Clay continue to cost a flat number of Data Credits per
  task, including all of Clay's native models."
- **Variable** — token-intensive frontier models are billed on actual tokens "with no markup."
  These show an estimate with a tilde (`~`), and "75% of runs cost less than the estimate."

Bring your own AI key and you pay the provider directly, consuming an Action but no Data Credit —
though Clay notes its own keys run "2x faster" due to negotiated rate limits.

**Relevance to an integration boundary: low, and that is the point.** Claygent output is
free-text or loosely-structured JSON produced by a model. It is a fine thing to *receive*, but
it should cross the boundary as an attributed, timestamped, low-trust field — never as
authoritative structured data. An integration contract should treat Claygent columns as
`source: claygent`, confidence unknown.

---

## 8. What Clay is genuinely good at vs. what a custom system should own

The honest architectural read.

**Buy from Clay — commodity:**

- **Provider breadth.** This is the entire argument. Clay describes a marketplace of **150+ data
  partners** in its pricing FAQ and **200+ vendors/providers** in its product nav and developer
  docs (the two numbers appear on different Clay pages; the discrepancy is Clay's, not a
  transcription error). No self-hosted system can replicate commercial contracts with that many
  vendors, and the value is not any one vendor — it is the *aggregate coverage*.
- **Waterfall fallback logic with per-hit billing.** Rebuilding this means rebuilding sequential
  provider orchestration, per-provider cost accounting, and stop-on-success semantics, and then
  still buying every contract.
- **Vendor churn absorption.** Providers change APIs, pricing and coverage constantly. Clay
  eats that maintenance.
- **Volume discounts.** Clay claims it negotiates volume pricing and passes it on — a solo
  developer cannot get list price, let alone volume price, from a dozen vendors.

**Build in the custom system — proprietary:**

- **ICP definition and scoring.** Your fit logic is the differentiated asset. It should not live
  in a vendor's column.
- **Identity resolution and the canonical record.** Which company record is the truth, how
  duplicates merge, what the stable internal ID is.
- **Provenance, trust and freshness policy.** Deciding that a Clay-sourced email from provider X
  beats a CRM-typed one from 2023 is business logic your system must own (see §9).
- **Orchestration triggers and state.** When to re-enrich, what has already been spent, what is
  stale.
- **Everything downstream of the data.** Routing, sequencing decisions, reporting.

The clean boundary: **Clay is a per-field resolution service; the custom system is the system of
record.** Data flows Clay → your store, never the reverse as authority. That framing also
happens to match the technical reality that the API cannot write rows into Clay tables (§5b).

---

## 9. Provider / source metadata and provenance

Mixed, and worth being precise about because provenance is the thing a receiving system most
wants.

**What is confirmed available:**

- **Which provider won a waterfall.** Waterfall columns can "optionally, choose to output the
  name of the successful provider and hide the provider columns for a cleaner table view"
  ([Waterfalls](https://university.clay.com/docs/building-a-data-waterfall)). This is opt-in
  configuration, not automatic — if nobody ticks the box, the provider name is not in the output.
  Additionally, each provider step in a waterfall is itself a column, so the per-provider results
  are visible in the table even when a summary column is used.
- **Per-cell status.** The Tables API returns each cell with a status so an integration "can
  distinguish successful, empty, pending, and errored cells"
  ([Tables](https://developers.clay.com/tables)). The response shape is
  `{"status": "success", "value": "clay.com", "fields": null}` alongside a `fields` map giving
  each field's `id`, `name` and `type`. This is genuinely useful — a partially-enriched row is
  distinguishable from an empty one.
- **Per-item status in routine runs.** "Check each item's `status`: a completed run can contain
  failed items" ([Routines API](https://developers.clay.com/routines/api)).
- **Run-level credit and action consumption** is visible in the Workflows Runs view
  ([Agent Plugin docs](https://university.clay.com/docs/clay-api-cli)).
- **Webhook delivery timestamp** — `createdAt` on the webhook envelope.

**What is NOT confirmed:**

- **Confidence scores.** No official Clay doc reviewed exposes a numeric confidence or match
  score as a standard output field. Individual providers may return their own confidence inside
  their response payload, but there is no uniform Clay-level confidence. **UNCONFIRMED — could
  not verify from official docs.**
- **Per-cell enrichment timestamps.** No documented per-field "enriched at" timestamp in the
  Tables API response shape. Table *version history* exists (1 or 6 months by plan) but that is
  snapshotting table configuration, not field-level provenance.
  **UNCONFIRMED — could not verify from official docs.**
- **A standard provenance envelope on outbound data.** Because the HTTP API column body is
  hand-written by the user (§4a), any provenance in an outbound payload is provenance *you chose
  to include*. Clay does not attach one.

**Design consequence:** a receiving system must **construct** provenance at the boundary —
stamp `received_at` itself, carry `source: clay`, and carry the provider name only if the Clay
table was explicitly configured to emit it. Do not design a schema that assumes Clay supplies
confidence or field-level timestamps.

---

## 10. Known limitations

**Everything is asynchronous.** The routines API returns 202-with-progress until complete
([Routines API](https://developers.clay.com/routines/api)). In-product enrichment is likewise a
background run per row. There is no synchronous "enrich this and block" call. Any integration
must be built around polling or webhook callbacks, and any UI must tolerate pending cells.

**Latency is not published.** Clay documents no SLA or expected enrichment latency for routine
runs or table enrichments. **UNCONFIRMED — could not verify from official docs.**

**Partial enrichment is normal and must be handled.** A completed run can contain failed items;
cells carry `success | empty | pending | errored` status. "Empty" and "errored" are different
things and a good client distinguishes them — an empty result is also, helpfully, not billed.

**Errors are thin.** `{"message": "..."}` with no stable error codes
([Errors](https://developers.clay.com/public-api/errors)). Status-code-driven handling only.
Clay explicitly warns that the set of terminal `status` values is not closed.

**Rate limits are undocumented numerically.** You get `429` + `Retry-After` and must discover the
ceiling empirically.

**Hard caps to design around:**

- Webhook source: **50,000 submissions**, persisting after row deletion.
- Free table size: **200 rows**; Launch: 50,000 rows.
- Routine run: **1–100 items** per inline call; larger volumes go through the JSONL batch path.
- Tables query: `limit` max **100** per page, cursor-paged; paging past 100 rows needs the
  Enterprise API table sync.
- HTTP API as a source: pagination up to **50,000 rows**.
- Free search: **100 results per rolling 30 days**.

**Scan consistency caveat.** For table queries, "scans return rows in least-recently-updated-first
order and reflect writes that land while you paginate" ([llms.txt](https://developers.clay.com/llms.txt)
description of the tables query endpoint) — a scan is not a snapshot. Workflow-run queries are read
from "an eventually-consistent replica."

**Operational gaps Clay itself names:** credit budgets are "not available on the developer
platform yet"; there is no list-tables endpoint, so you must know table ids in advance (find them
in the URL after `/tables/`); Workflows are Beta.

**Cost opacity.** Because per-record cost is 6–20 Data Credits "depending on the data types you
enrich," and variable AI models are priced on tokens after the fact, forecasting spend requires
measurement rather than arithmetic. This is a widely-repeated complaint in third-party pricing
commentary; the underlying variability is confirmed by Clay's own FAQ.

---

## Honest integration posture

**What this project should claim:**

> The Clay integration boundary is implemented against Clay's documented Public API
> (`https://api.clay.com/public/v0`, `clay-api-key` header) and its signed-webhook callback
> contract (HMAC-SHA256 in `X-Clay-Signature`). The async run→poll/callback→fetch lifecycle,
> per-item status handling, 402/429 backoff, and provenance stamping at the boundary are built
> and unit-tested against recorded payload shapes taken from Clay's published documentation.

Then, depending on what actually gets run, exactly one of:

- **If a free workspace was created and calls were made:** *"Verified end to end against a live
  free-tier Clay workspace: routine run dispatched, signed webhook received and signature
  verified, results fetched. Not exercised at volume — the free tier allows 100 Data Credits,
  500 Actions and 200 rows per table per month."*
- **If no workspace was created:** *"The integration boundary is built and tested against
  recorded payload shapes; it has not been verified against a live Clay workspace."*

**What this project must NOT claim:**

- ❌ "Full two-way Clay integration" — the API cannot write rows to Clay tables, by Clay's own
  documentation. Inbound row creation requires the webhook source in the UI.
- ❌ Anything involving the **HTTP API enrichment column** or **webhook automation** being used —
  those are Growth-tier ($495/mo).
- ❌ Anything involving the **Tables structured-query API** — Enterprise-only.
- ❌ Any enrichment-quality, coverage or match-rate numbers. 100 Data Credits buys roughly 5–16
  fully enriched records at Clay's stated 6–20 credits each. That is a smoke test, not a
  benchmark, and no coverage claim can honestly be made from it.
- ❌ Any latency or throughput figure — Clay publishes neither.

**Cheapest honest path to a live-verified claim: $0.** Create a free workspace, mint an API key
under *Settings → Account → API keys (beta)*, call `GET /me` and `GET` credit balances (which
"does not consume credits"), run one Clay-managed function on a handful of records, register a
webhook, and verify the signature on the callback. That exercises every mechanism in the boundary
— auth, async dispatch, callback, signature verification, result fetch, error handling — for a
few Actions. If even that is not done, say so plainly; a documented, well-designed, untested
boundary is a defensible engineering artifact, whereas an overclaimed integration is not.

**One item to re-verify before publishing:** clay.com/pricing lists "Clay API access" as an
Enterprise feature while developers' docs say the developer platform covers all plans including
free. §3 explains why both are probably true of different surfaces, but the project should
confirm against a live free workspace rather than rely on the reconciliation.

---

## Sources

- https://www.clay.com/pricing
- https://developers.clay.com/ (index, quickstart, llms.txt)
- https://developers.clay.com/public-api/authentication
- https://developers.clay.com/public-api/rate-limits
- https://developers.clay.com/public-api/errors
- https://developers.clay.com/public-api/webhooks
- https://developers.clay.com/routines/api
- https://developers.clay.com/routines/clay-managed-functions
- https://developers.clay.com/searches
- https://developers.clay.com/tables
- https://developers.clay.com/concepts/execution-model
- https://university.clay.com/docs/clay-api-cli
- https://university.clay.com/docs/http-api-integration-overview
- https://university.clay.com/docs/webhook-integration-guide
- https://university.clay.com/docs/building-a-data-waterfall
- https://university.clay.com/docs/work-email-waterfall
- https://university.clay.com/docs/actions-data-credits
- https://university.clay.com/docs/claygent-builder
- https://university.clay.com/docs/clay-to-zapier
- https://github.com/clay-run/agent-plugins
