# Phase 3 tool research: the four tools against what GTMOS already does

`docs/phase3-architecture.md` states the boundary — buy the commodity, orchestrate the plumbing, own
the judgement. This document is the evidence for it. A buy/orchestrate/build decision is only as good
as the knowledge behind it, and the knowledge that matters is rarely "what does the marketing page
say the tool does". It is three other things: what the tool genuinely does, where it stops, and which
paid tier the useful part sits behind. Those three answers decide the architecture far more often than
any elegance argument does. PostHog's group analytics being a billing-page add-on, Clay's HTTP API
column being a $495/month feature, and HubSpot refusing to deduplicate API-created companies on
`domain` each changed a design decision in this repository — and none of them appears in a feature
list.

This is the engineering-facing counterpart to `docs/gtm-tool-guide.md`, which explains what these
tools *are* to somebody who has not worked in revenue operations. Nothing here re-explains a CRM. It
is the comparison the other documents deliberately do not make.

**Sourcing rule.** Every vendor claim below is traceable to the per-tool research in
`docs/research/{hubspot,n8n,posthog,clay}.md`, all of which were compiled against current public
documentation on 2026-09-22, or to a source cited inline. Where the vendor's own documentation is
ambiguous or silent, the cell says **Unverified** rather than guessing. **No live vendor service has
been called from this repository.** n8n is the only integration verified by execution; HubSpot runs
against a simulated adapter; Clay and PostHog are contracts exercised locally against recorded payload
shapes.

---

## 1. The capability matrix

Twenty-one GTM capabilities against five systems. The verdicts are **native** (the tool does this as a
first-class feature), **paid tier** (it does it, behind a specific subscription), **partial** (it does
part of it, and the qualifier says which part), and **no**.

| Capability | HubSpot | n8n | PostHog | Clay | GTMOS |
|---|---|---|---|---|---|
| **Event capture at volume** | **partial (Unverified)** — HubSpot has web tracking and custom behavioural events, but their tiering and query surface were outside this research pass; nothing in GTMOS depends on them | **no** — moves events, stores only execution history, pruned at 14 days by default | **native** — `/i/v0/e/` and `/batch/`, 1M events/month free, 20 MB body cap | **no** — Clay models rows, not events | **partial, by design** — accepts PostHog-shaped payloads and turns them into engagement rows (`services/product_events.py:51`); no event store, no funnels over raw events |
| **Group / account-level analytics** | **native** — companies are a first-class object, but product usage has to be pushed in | **no** | **paid add-on** — `$groups`, max 5 group types per project, membership lives on the event | **no** | **native** — the account is the primary entity; the group key is read at `integrations/posthog.py:47` and everything downstream is account-shaped |
| **Person identity resolution** | **partial** — contacts dedupe on `email`; companies created via API do **not** dedupe on `domain` | **no** | **partial, and it says so** — "It can't resolve identity for you"; `$identify` / `$create_alias` / `$merge_dangerously`, already-identified merges refused | **partial** — provider-level matching inside a waterfall; no cross-system identity graph | **native** — domain and email normalisation, validation and role-address detection in `domain/matching.py:133`–`:185`, with free-mail domains rejected before any account match (`:244`) |
| **Lead-to-account matching** | **partial** — associations are manual or workflow-driven; domain dedup is a UI/import-time behaviour only | **no** | **no** — `$groups` links to a group, it does not create or resolve one | **partial** — can enrich a person's company; the join back to *your* account table is yours | **native and explainable** — `domain/matching.py:356`, fuzzy-name threshold 0.87 (`:266`), free-mail blocklist (`:24`), role addresses (`:50`), and rejected candidates carry the reason they lost (`:294`) |
| **Enrichment waterfall + provider network** | **partial (Unverified)** — HubSpot sells a firmographic enrichment add-on, but its coverage, tiering and whether it exposes anything resembling a provider waterfall were outside this research pass | **no** — can call vendor APIs; you write the fallback, the cost accounting and the stop-on-success | **no** | **native, and this is the product** — ordered provider steps, stop at the first valid value, 150+/200+ partners (Clay's own two figures disagree), no charge on an empty result | **partial, deliberately** — three simulated providers plus an unrun Apollo adapter; per-field order at `integrations/enrichment_providers.py:218`, waterfall at `domain/enrichment.py:303`. Mechanics only |
| **Provider conflict / merge policy** | **no** — last write wins per property; there is no conflict object | **no** | **no** — `$set` reflects the last *ingested* value, not the last *timestamped* one | **no** — Clay reports what a provider said; it does not adjudicate | **native** — `domain/enrichment.py:130` refuses to overwrite a manual lock, applies a 180-day staleness rule and a 0.1 upgrade margin; `:246` raises a data-quality issue rather than resolving a material disagreement on confidence |
| **Field-level provenance** | **partial** — per-record property history exists; there is no provider / confidence / freshness model | **no** | **no** | **partial** — the winning provider's name is an opt-in output and per-cell status is `success \| empty \| pending \| errored`; **no uniform confidence and no per-cell enrichment timestamp are documented** | **native** — `FieldProvenance` (`models/intelligence.py:142`) carries provider, confidence and timestamp, stamped at the boundary because Clay supplies none (`services/clay_service.py:60`) |
| **Explainable scoring** | **paid tier** — lead scoring is Marketing Hub and Sales Hub Professional/Enterprise; AI-built scores and score-performance reports are Enterprise. Whether the UI shows per-record criterion contributions is **Unverified** | **no** — you *can* compute a score on a canvas; you should not | **partial** — HogQL can compute one, and PostHog's own handbook computes ICP fit in code and the lead score **in Salesforce, not in PostHog** | **partial** — a formula or Claygent column emits a number; it is not versioned, diffable or testable | **native** — `domain/scoring.py:425` returns per-component contributions with reasons, over a versioned ICP object (`domain/icp.py`), with an inputs hash at `:390` |
| **Signal decay** | **no** — a property holds its value until something overwrites it | **no** | **partial** — you can window a query to 30 or 90 days; there is no decay primitive | **no** | **native** — per-type half-lives in `domain/signals.py:17`, exponential decay at `:205`, applied to every signal component at `domain/scoring.py:255` |
| **Product-qualified rule** | **paid tier** — a workflow can encode a threshold, and workflows are Professional/Enterprise | **partial** — encodable on a canvas, not unit-testable there | **partial, documented as a pattern not a feature** — a HogQL table insight in the "Lead scoring" pocket guide and Customer Analytics usage metrics; **there is no PQL destination template** | **no** | **native** — composite, account-level, 14-day window, threshold 55 so no single criterion qualifies alone (`domain/pql.py:39`, `:50`, `:114`), fired once per account per week (`services/product_events.py:220`) |
| **Routing with SLA** | **paid tier** — workflow-based owner assignment and rotation need Professional+; SLA is reporting rather than a routing primitive (**Unverified:** exact SLA feature tiering) | **partial** — a round-robin is twenty minutes of canvas; there is no territory model and no load state you can reason about | **no** | **no** | **native** — `domain/routing.py:127` with priority-ordered rules, least-loaded and round-robin pools (`:91`, `:106`), an explanation of why each losing rule lost (`:83`), and SLA attainment at `services/routing_service.py:170` |
| **Buying-committee inference** | **no** — contacts carry job titles; nothing infers a committee | **no** | **no** | **partial** — can find people by title through a provider; the role model is yours | **native** — `domain/committee.py:172` over title rules (`:23`), seniority and department weights (`:68`, `:75`), a minimum role score of 35 (`:76`), and a confidence derived from the gap to the runner-up (`:164`) |
| **Evidence-grounded copy + guardrails** | **partial (Unverified)** — HubSpot ships AI content assistants; whether any of them bind a claim to evidence or expose a blocking guardrail was not verified here | **partial** — an LLM node will generate text; the guardrails are whatever you write around it | **no** | **partial** — Claygent returns free text or loose JSON; Clay's own framing is that it should cross a boundary as a low-trust attributed field | **native** — evidence pack at `domain/research.py:127`, every claim carries an `[E#]` reference (`domain/personalization.py:117`), guardrails at `:125`, and a blocking failure makes approval impossible (`:288`) |
| **Approval queue** | **partial** — marketing email approvals exist (**Unverified:** tier) | **partial** — a Wait node and a form can fake one; there is no state machine | **no** | **no** | **native** — a five-state machine (`domain/personalization.py:279`) enforced on every transition (`services/outreach_service.py:198`). Nothing is ever sent, because there is no sender |
| **Workflow orchestration with idempotency / DLQ** | **paid tier** — Workflows are Professional/Enterprise across every hub; no operator-visible dead-letter queue is documented (**Unverified**) | **native for plumbing** — retries with `maxTries` clamped to [2,5] and `waitBetweenTries` to [0,5000] ms, **fixed delay, no backoff, no jitter**; an Error Trigger workflow is the failure channel; idempotency is yours to build | **partial** — destinations retry up to 3 times then quarantine and auto-disable; no replay | **partial** — async run → 202-with-progress → results, with per-item status; no dead letter | **native** — idempotency key at `domain/workflows.py:67` checked at `services/workflow_engine.py:302` with a unique-constraint race guard at `:326`, exponential backoff at `domain/workflows.py:73`, a `dead_letter` terminal status (`:508`) and operator retry (`:535`); inbound dedupe and replay at `services/webhook_service.py:91`, `:246` |
| **Reverse ETL with field ownership** | **no** — it is the destination. Whichever sync tool writes into it, the field-ownership rule is the writer's to enforce | **partial** — it carries the payload; it does not know which fields you own | **partial** — CDP destinations push person or event data to HubSpot, Salesforce, Attio and others; no field-ownership concept | **partial** — CRM auto-sync is Growth+; the overwrite policy is a column setting, not a contract | **native** — `services/crm_sync.py:119` builds update payloads containing only `gtmos_*`, name and domain on create only, and `payload_hash` (`:96`) suppresses no-op writes |
| **CRM system of record** | **native — this is the product** | **no** | **no** | **no, structurally** — the Public API cannot write rows into Clay tables | **deliberately no** — GTMOS holds its own account graph but never becomes where reps work; inbound CRM changes are logged, never auto-applied |
| **Attribution** | **paid tier** — Free and Starter get only the last-ad-interaction report; other report types need Marketing Hub Professional; **deal-create and revenue attribution are Marketing Hub Enterprise** | **no** | **partial** — revenue analytics connects revenue events to persons and groups, and web analytics has channel attribution; no multi-touch opportunity model | **no** | **native** — four models (`domain/attribution.py:16`) over a 180-day lookback (`:17`), computed at `:73` |
| **Experimentation** | **paid tier** — A/B testing of marketing assets (**Unverified:** exact tier per hub) | **no** | **native** — feature flags and experiments, 1,000,000 requests/month free | **no** | **native for outbound** — deterministic bucketing (`domain/experiments.py:105`), Wilson and Newcombe intervals (`:134`, `:158`), guardrail metrics that can veto a winner (`:54`, `:351`), a sample-size calculator (`:209`) and a causal caveat attached to every recommendation (`:421`) |
| **Kill switches** | **partial** — unpublish a workflow or pause a sequence, one object at a time | **partial** — `n8n unpublish:workflow --all` exists, but a CLI change needs a restart to take effect | **partial** — disable a destination; a feature flag can gate your own code | **partial** — pause a table or a run; credit budgets are "not available on the developer platform yet" | **native** — three workspace switches (`services/governance.py:32`) plus `pause_all` (`:152`), checked before the action runs (`:118`) and raising a `Halted` with an operator-readable reason (`:51`) |
| **Audit trail** | **partial** — per-record property history on all tiers; account-level audit logs are an Enterprise platform feature (**Unverified:** exact wording) | **partial** — execution history (pruned at 14 days), `/api/v1/audit`; log streaming is a paid self-hosted feature | **partial** — an activity log exists; audit logs are named among the platform features absent from free and self-hosted | **partial** — table version history is *not included* on Free, 1 month on Launch, 6 months above; that is configuration snapshotting, not field-level audit | **native** — `AuditEvent` (`models/ops.py:216`), written by every state transition, switch flip and remediation |

### Three rows worth reading twice

**Group analytics.** This is the row that decides whether a B2B product-led motion is possible at all,
and it is the row where the free tier fails. Without it PostHog can tell you what a *user* did; B2B
revenue is account-shaped, so a tool that only knows users is not usable for it. It is a billing-page
add-on, the meter counts **all identified events** in the project once enabled, and self-hosting does
not rescue you — group analytics and data pipelines are precisely the two features PostHog names as
absent from self-hosted.

**Provider conflict.** Four tools, four "no". Clay will tell you that provider B says the headcount is
900 while your record says 400. None of the four will tell you which to believe, and the honest answer
is usually "neither, ask a human" — which is why `domain/enrichment.py:246` raises an issue instead of
picking. This is the clearest example in the matrix of a gap that looks small and is actually where
the business logic lives.

**Idempotency.** n8n retries; PostHog retries three times; Clay gives you per-item status; HubSpot
resends a failed webhook up to ten times over 24 hours and explicitly guarantees neither ordering nor
uniqueness. Every one of those makes duplicate delivery *more* likely, and not one of them makes the
receiving system idempotent. That is always the receiver's job, and it is the least glamorous thing in
this repository.

---

## 2. Where GTMOS overlaps, and what should happen to each overlap

Naming these honestly is the point of the exercise. A portfolio project that claims everything it
built is differentiated is making a claim an interviewer can falsify in one question.

**The enrichment waterfall — keep as a mechanics demo, delete the providers in production.**
`domain/enrichment.py:303` and the three simulated providers in
`integrations/enrichment_providers.py` reimplement, badly and at toy scale, the thing Clay exists to
sell. The waterfall *mechanism* — ordered provider steps, stop on first hit, per-provider cost
accounting — is about a hundred lines and anyone can write it in an afternoon. What cannot be written
in an afternoon is 150 vendor contracts. The right production shape is: the providers go, Clay becomes
one input, and the merge policy stays. The policy is the part with an opinion in it.

**The demo CRM store — a test double, would delete the day a portal exists.** `DemoHubSpotAdapter`
(`integrations/hubspot.py:166`) writes companies, contacts, deals and associations into Postgres. It
exists so the sync path can be exercised without credentials, and it is the reason this repository can
honestly say the reverse ETL works. It is not a CRM and nothing in it is differentiated.

**Pipeline analytics — would largely delete in production, with two exceptions.**
`services/analytics.py` is 672 lines recomputing funnel, velocity, breakdowns and period comparison —
all of which HubSpot reporting does at Professional and above, over data that is already in HubSpot.
Two pieces would survive: `domain/metrics.py:28`, the metric dictionary that stops a definition and a
number drifting apart, and `services/scoring_eval.py`, which no CRM does at all (see §3).

**Attribution — a mechanics demo, and a buy if you are already paying.** `domain/attribution.py` is a
textbook 111-line implementation of four touch models. If the portal is Marketing Hub Enterprise, this
is redundant and should go. If it is not, HubSpot gives you the last-ad-interaction report and nothing
else, and the 111 lines earn their place. It is a tier-dependent decision, not a principled one, and
saying so is more useful than defending the code.

**Experiment statistics — the maths is a reimplementation, the policy is not.**
`domain/experiments.py` is 507 lines of bucketing, Wilson intervals, Newcombe difference intervals and
sample-size calculation. PostHog ships all of that. What PostHog does not ship is a guardrail that can
veto a statistically winning variant (`:351`) and a causal caveat welded to every recommendation
(`:421`). Production shape: assignment and statistics move to PostHog, the guardrail policy stays.
Two systems disagreeing about which variant a contact is in is a far worse failure than not owning the
arithmetic.

**The workflow engine — genuinely differentiated, with one exception.** `phase3-architecture.md`
already argues this and the argument holds: GTM semantics belong in version control with tests, and
plumbing belongs on a canvas an operator can change without a deploy. The exception is the `_notify`
step (`services/workflow_engine.py:171`), which is plumbing that ended up inside the engine because it
was convenient. In production that is an n8n hop.

**Product-event ingestion — keep, but keep it bounded.** `services/product_events.py` stores
engagement rows because the PQL rule needs account-level counts over a 14-day window, and asking
PostHog for that on every score would be both slow and rate-limited. That is a defensible reason to
hold derived data. It stops being defensible the moment GTMOS grows funnels, retention curves or
session analysis over those rows. It has not, and it should not.

**Deliverability — differentiated, but not against these four.** `domain/deliverability.py` models
sending capacity, ramp and risk without sending anything. None of HubSpot, n8n, PostHog or Clay does
this — but sequencer vendors do, and the honest framing is that this is a constraint model for a
capability GTMOS deliberately lacks, not a competitive feature. Its most useful twenty lines are
`DOES_NOT_MODEL` at `:38`, which enumerates what it refuses to claim.

---

## 3. Where GTMOS does something none of the four does

Each of these is small. None is hard technology. What is uncommon is that they exist at all, and that
each one is a pure function or a query with a test behind it.

**Causal chains across silos** — `services/stack_inspector.py:208`. Each tool reports its own findings
in its own silo: Clay knows which fields are empty, HubSpot knows which companies have no owner,
PostHog knows which accounts are quiet. `causal_chains` traces one set of accounts from a root cause,
through the mechanism that propagates it, to the business consequence, **intersecting the account id
sets at every link**. "36 accounts missing employee count" and "90 unmatched routing decisions" sound
like the same finding and are usually not the same accounts; the intersection is the honest number and
it is almost always smaller than either. No tool in the four can compute it, because no tool in the
four holds both sides.

**A leakage-aware backtest of the score** — `services/scoring_eval.py`. The score awards engagement
points for replies and meetings, and "did this account book a meeting" is the outcome, so the score
partly predicts itself. The service evaluates three variants against the same outcomes — `structural`
(fit and technical, known before anyone was contacted), `pre_engagement` (plus timing and intent) and
`total` — so the gap between them *measures* the circularity instead of hiding it. No vendor grades
its own score this way, and it would be strange if one did.

**A conflict that refuses to resolve itself** — `domain/enrichment.py:246`. Covered in §1, repeated
here because it is the cleanest example of judgement that a data vendor structurally cannot supply.

**Prompt-injection sanitisation on the enrichment boundary** — `domain/research.py:109`. Signal text
and enrichment values are scraped from the outside world and end up in a brief a rep may paste into an
email. `sanitize_external()` truncates to 400 characters and replaces text matching an instruction
pattern with an explicit withheld marker. It was added after the evaluation harness caught the
generator copying an injected instruction verbatim. None of the four treats enrichment output as
untrusted input to a generator, and Clay's own docs — which warn that Claygent output is
loosely-structured model text — imply that somebody should.

**A metric dictionary in code** — `domain/metrics.py:28`. Every reported number has one definition,
stating the formula, the denominator and the caveat that stops it being misread; the API serves it and
the UI shows it. RevOps arguments are usually definition arguments, and the fix is not a better
dashboard.

**Natural language over a closed set** — `services/copilot.py:37`. Questions map onto one of a fixed
list of approved analyses with whitelisted parameters; no model writes or runs SQL; anything outside
the set is refused *by name* (`:119`, `:160`) rather than approximated. The interesting property is
the refusal list, not the answers.

**A guardrail that can overrule a winner** — `domain/experiments.py:54`, `:351`. A variant can win on
reply rate and still be blocked because a guardrail metric moved the wrong way, and every
recommendation carries `CAUSAL_CAVEAT` (`:421`) stating what the comparison does not establish.

---

## 4. The pricing and gating reality

This is the section that decides what can actually be built for nothing, and it is the section where
vendor knowledge is either real or is not.

| Gate | What it blocks | Cost to clear it |
|---|---|---|
| **PostHog group analytics add-on** | Account-level product analytics, and B2B mode with it. Enabled from the billing page, so **not** on the no-card Free plan. Once enabled the meter counts **all identified events** in the project, not only those carrying group properties | $0 within the first 1M events/month — but a card on file |
| **PostHog HTTP Webhook destination** | PostHog pushing an arbitrary JSON body to an arbitrary URL, i.e. the PostHog → n8n leg. Realtime destinations carry 10,000 free trigger events/month, but the HTTP Webhook template is `free: false` in source while Slack is `free: true`, and "Data pipelines" is named among the features absent from free and self-hosted | Same paid pay-as-you-go plan, $0 base. **Unverified:** no prose doc states the gating; it is inferred from template source |
| **PostHog self-hosting as an escape route** | Nothing — it makes things worse. Group analytics and data pipelines are the two features explicitly named as absent from self-hosted, on top of a 4 vCPU / 16 GB / 30 GB box running ClickHouse, Kafka, Zookeeper, Redis, Postgres and MinIO | Not worth clearing |
| **Clay HTTP API enrichment column** | Clay pushing an enriched row to your endpoint from inside a table — the thing most people mean by "a Clay integration". Listed under Growth's "Integrate with any HTTP API / Automate any signal via webhook" | **$495/mo** (Growth), $446/mo annual |
| **Clay Public API** | Nothing on Free — and this is the useful discovery. Clay's developer docs state the platform is "available across all Clay plans, including free and trial plans", while clay.com/pricing lists "Clay API access" as an Enterprise inclusion. The reconciliation, from Clay's own FAQ: basic row reads work on any plan; structured queries — joins, ranges, paging past 100 rows — need Enterprise. Two official Clay pages disagree on the wording, so this warrants confirmation against a live free workspace | $0, with a ceiling of 100 Data Credits, 500 Actions, 200 rows per table and 100 search results per rolling 30 days |
| **Clay Public API beta status** | Production reliance. API keys are labelled **(beta)** in the Clay UI, Workflows via CLI or plugin are explicitly Beta with Clay recommending managed or custom functions "for production use", and the workflow-run query endpoints are beta too. There is also no OAuth, no scopes and no documented rotation — one static workspace-scoped key | Not clearable; design around it |
| **Clay Tables structured-query API** | Joins, ranges and paging past 100 rows | Enterprise, custom annual |
| **HubSpot standard sandboxes** | A production mirror to test destructive changes against. Requires Marketing, Sales, Service, Data, Content, Smart CRM or Revenue Hub **Enterprise**. Legacy standard sandboxes were sunset on 2026-04-30 | Enterprise. The free substitute is up to **10 developer test accounts** per standard account, each a 90-day trial of many Enterprise features, expiring after 90 days without an API call |
| **HubSpot Workflows** | Encoding any qualification threshold or owner rotation in HubSpot itself. Supported products, verbatim: "Marketing Hub Professional, Enterprise; Sales Hub Professional, Enterprise; Service Hub Professional, Enterprise; Data Hub Professional, Enterprise; Smart CRM Professional, Enterprise; Revenue Hub Professional, Enterprise" | Professional |
| **HubSpot lead scoring** | Scoring in the CRM. Marketing Hub and Sales Hub Professional/Enterprise; AI-built scores and lead-score performance reports are Enterprise | Professional, Enterprise for the reporting |
| **HubSpot revenue attribution** | Deal-create and revenue attribution reports. Free and Starter get the last-ad-interaction report only | Marketing Hub Enterprise |
| **HubSpot private apps** | Nothing — free on all tiers, super-admin only, max 20 per account, non-expiring bearer token. Note the daily rate limit is **shared across every private app in the account**; only the burst limit is per app | $0 |
| **n8n self-hosted** | Nothing. Community edition is free under the Sustainable Use License and "includes almost the complete feature set of n8n". Gated to Business/Enterprise: custom variables, environments, external secrets, external binary storage, log streaming, multi-main mode, projects, SSO, sharing, and Git version control | $0 |
| **n8n registered Community edition** | Folders, debug-in-editor, and **custom execution data**. That last one matters: `$execution.customData` is the cheapest way to make an execution findable by account domain instead of by timestamp | $0 — an email address |
| **n8n public API** | Programmatic workflow management. "The n8n API isn't available during the free trial", and off Enterprise an API key has **full access to all the account's resources**. Whether a self-hosted Community instance with no licence can mint one in 2.40.5 is **Unverified** | Not needed — the Server CLI requires no licence and no key |

**The net.** The architecture in `docs/phase3-architecture.md` costs **$0 in cash** to stand up, needs
**a payment method on PostHog** to be account-shaped, and would cost **$495/month on Clay** only for
the in-table push. The free Public API notify-then-pull path exercises every mechanism in the Clay
boundary — auth, async dispatch, signed callback, signature verification, result fetch, error handling
— for a handful of Actions. That is a smoke test, not a benchmark, and no coverage or match-rate claim
can honestly be made from 100 Data Credits, which buys roughly five to sixteen fully enriched records.

---

## 5. Facts commonly gotten wrong

Each of these is something a confident write-up usually gets backwards, with the correct version and
where it is documented.

**HubSpot `domain` is not a unique property.** The common belief is that companies dedupe on domain,
so upserting on it is safe. HubSpot's own deduplication page says the opposite in the same breath:
domain is used to deduplicate on create, *but* "companies created through API will not be deduplicated
by the Company domain name property". Domain dedup is a UI and import-time behaviour. Nothing stops
`POST /crm/v3/objects/companies` creating a second company with the same domain. The correct approach
is a custom property with `hasUniqueValue: true` — of which you get **ten per object type**, and which
**cannot be added retroactively** ("Only net new properties can be set to contain a unique value").
GTMOS keys companies on `gtmos_account_id` (`integrations/hubspot.py:42`) for exactly this reason.
`hs_additional_domains` lets a company carry several domains; it is not a uniqueness mechanism.
Source: `knowledge.hubspot.com/records/deduplication-of-records`.

**Private apps sign webhooks with v1, not v3.** Signature v3 is the one everybody implements: HMAC-
SHA256 over `requestMethod + requestUri + requestBody + timestamp`, Base64-encoded, with a five-minute
replay window on `X-HubSpot-Request-Timestamp`. Private app webhooks do not use it. HubSpot's private
app documentation says the header is `X-HubSpot-Signature` carrying "a SHA-256 hash that's built using
your private app's client secret" — that is **v1**: a plain SHA-256 (not an HMAC) of
`clientSecret + requestBody`, hex-encoded, with no timestamp and therefore no replay protection, which
is why deduplication has to carry that weight instead. GTMOS implements both and records which one
verified each delivery (`integrations/signatures.py:53`, `:69`, `:87`). Whether private-app deliveries
*also* carry v3 headers is **Unverified** — the v3 changelog scoped it to "outgoing HubSpot requests to
OAuth Apps" — so the verifier prefers v3 and falls back.

**The related trap:** hash the **raw request bytes**, not a re-serialised body. HubSpot's own Node
sample uses `JSON.stringify(body)`, which only matches if your parser round-trips key order, whitespace
and unicode escapes byte-for-byte. This is the single most common cause of signature mismatches and
the docs do not flag it.

**Association type IDs 1/2/5/6 are the *primary* variants.** The widespread assumption is that `1` is
"contact to company" and you use it to link two records. It is not. `1` is contact → **primary**
company and `2` is company → **primary** contact; the general, non-primary types are `279` and `280`.
The same holds for deals: `5` and `6` are the primary variants, `341` and `342` are general. Using `1`
when you meant "just associate them" silently sets the primary company — which is the field territory
assignment and a great deal of reporting keys off. Contact↔deal (`3`/`4`) is symmetric and has no
primary variant. GTMOS writes the primary IDs **deliberately**, because in this data model an account
*is* the contact's company, and says so in a comment above `ASSOCIATION_TYPES`
(`integrations/hubspot.py:93`) rather than leaving a bare integer in a payload. Source: the association
type ID table at `developers.hubspot.com/docs/api-reference/latest/crm/associations/associate-records/guide`.

**n8n: `N8N_WEBHOOK_URL` replaced the deprecated `WEBHOOK_URL`.** `WEBHOOK_URL` is deprecated from n8n
2.35.0. It still works and is an alias, but n8n logs a deprecation warning at startup. It sets the base
URL for **both** the test and the production webhook. The companion error is `N8N_RUNNERS_ENABLED`:
people set it to silence a warning, but it is deprecated from 2.0 and is itself the thing being
deprecated — task runners are on by default, and setting it does nothing useful.

**n8n: `/webhook-test/` and `/webhook/` are different URLs with identical failure modes.** The test URL
is registered only when you press *Listen for test event* and stays live for **120 seconds**. The
production URL 404s until the workflow is **published** — and `import:workflow` always imports
deactivated, with `--activeState=fromJson` only supported in multi-main or queue mode. Worse, a CLI
`publish:workflow` writes straight to the database, so a running n8n does not notice until you restart
it. From curl, "not published" and "test window expired" look the same. Any runbook has to say which
prefix it means; the six workflow files in `integrations/n8n/` are imported, published and restarted as
a unit for this reason.

**PostHog `$groups` links, it does not create.** Attaching `properties.$groups = {"company": "acme"}`
to a normal event associates that event with an existing group. It will **not** create the group — that
requires a `$groupidentify` event first, with `$group_type`, `$group_key` and a `$group_set` that is a
plain JSON object (strings, numbers, booleans and arrays are discarded outright). Three consequences
follow from PostHog storing group membership **on the event** rather than on the person or the group:
you cannot build a cohort from a group, "related people and groups" only covers the last 90 days, and
group types are unavailable for lifecycle insights and user paths. There is a hard cap of **5 group
types per project**, and you can delete a group type but not an individual group. GTMOS reads
`properties.$groups.company` at `integrations/posthog.py:47` and treats that key as the account key.

**The PostHog corollary nobody tests for:** capture returns `200` for events it silently drops — no
event name, missing or empty `distinct_id` — and also returns `200` when the project is over quota,
naming the limited resources in a `quota_limited` field. An integration test that asserts on HTTP status
proves almost nothing; verification means reading the event back through the query API with a personal
API key.

**Clay tables are read-only through the API.** Verbatim from Clay's own documentation: "Tables in the
Public API is read-only — you can query and read rows, but not create tables, add fields, or write
records. There are no current plans to support table building from the API or CLI." So a "full two-way
Clay integration" is not something anyone can build, at any price. Row creation goes through the
webhook *source* configured in the UI, or a CSV or CRM import. The API's write-equivalent is running a
routine with your own inputs, which returns results to you rather than persisting rows.

**The Clay corollary:** the webhook callback is a *notification*, not the data —
`{"webhookId": …, "createdAt": …, "data": {"routine_run_id": …}}`, signed as `sha256=<hex>` in
`X-Clay-Signature`, with the signing secret returned exactly once at registration. It is a
notify-then-pull pattern, so a receiving system needs both an inbound endpoint and an outbound client.
GTMOS has both (`integrations/clay.py:46`, `:51`, `:186`, `:205`). Clay also warns that the set of
terminal `status` values is not closed and that unrecognised values must be treated as unhandled
terminal outcomes, which is why `KNOWN_TERMINAL_STATUSES` is explicit at `integrations/clay.py:95`
rather than assumed.

---

## 6. What GTMOS would change with paid access to all four

Prioritised by how much each change would improve the honesty of the claims, not by effort.

1. **Put a card on PostHog and enable group analytics.** This is the one change that converts the
   account-level story from replayed payloads into observed behaviour. `$groupidentify` the account on
   create, let the HTTP Webhook destination carry `groups` alongside `event` and `person`, and mark
   only GTM-relevant events as identified — because the add-on meters *all* identified events, not
   just the ones with group properties. At demo volume the bill stays $0.
2. **Create a HubSpot developer test account, then a real portal.** Create `gtmos_account_id` as a
   `hasUniqueValue` property **first**, since it cannot be added retroactively. Then exercise the three
   things the documentation cannot settle: whether private-app webhook deliveries carry v3 headers or
   only v1, what the 207 partial-success body actually looks like with a deliberately invalid row, and
   whether `objectWriteTraceId` behaves on `batch/create` as documented.
3. **Delete the three simulated enrichment providers.** Let Clay be one provider among the merge
   policy's inputs — with no special authority for having been bought. The waterfall code goes; the
   policy in `domain/enrichment.py:130` and `:246` stays, and the data-quality issue path finally gets
   exercised against real vendor disagreement rather than synthetic disagreement.
4. **Buy Clay Growth only when there is a list worth enriching.** The $495/month in-table HTTP API
   column is the only way Clay pushes an enriched row to an endpoint, but the free Public API
   notify-then-pull path already exercises every mechanism in the boundary. Spending $495 to prove an
   integration that the free tier can prove is the exact mistake this document exists to avoid.
5. **Move experiment assignment and statistics to PostHog.** Keep the guardrail policy and the causal
   caveat in GTMOS, delete the Wilson and Newcombe implementations. Two systems disagreeing about which
   variant a contact is in is a worse failure than not owning the arithmetic.
6. **Register the n8n Community edition.** It is free and it unlocks `$execution.customData`, which
   makes an execution findable by account domain instead of by timestamp. Also raise
   `EXECUTIONS_DATA_MAX_AGE` above the 14-day default before any run worth keeping is pruned.
7. **If the portal reaches Marketing Hub Enterprise, delete `domain/attribution.py` and most of
   `services/analytics.py`** and read HubSpot's numbers instead. Keep `domain/metrics.py` and
   `services/scoring_eval.py` — the metric dictionary and the leakage-aware backtest are the two things
   HubSpot reporting does not replace.

The ordering is the argument. Three of the seven items delete GTMOS code, and the two that cost money
are fourth and last. That is what "buy the commodity, orchestrate the plumbing, own the judgement"
looks like when it is applied to the thing you built rather than to the thing you are evaluating.
