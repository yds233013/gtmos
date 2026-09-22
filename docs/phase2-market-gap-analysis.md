# Phase 2: Market Gap Analysis

**What this is.** A second research pass, run on 2026-09-22, against a GTMOS that already exists. Phase 1
(`docs/market-research.md`, 2026-09-21) asked "what should I build?". This asks the harder question: *given what
is now built, where would a hiring manager still say no?*

---

## 1. Method and sources

**Method.** I pulled live postings straight from the ATS APIs rather than from job aggregators or SEO articles —
Ashby (`api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true`) and Greenhouse
(`boards-api.greenhouse.io/v1/boards/{org}/jobs[/{id}]`) — so every requirement and salary band below is quoted
from the employer's own published text, not a third party's summary. Vendor behaviour was checked against
official documentation and changelogs. Practitioner claims are attributed to their author. Anything I could not
confirm from a primary source is marked **[unverified]**.

**Access date for every URL: 2026-09-22.**

### Postings analysed (all open on the access date)

| # | Company | Title | Category | Published | Published band (base) | URL |
|---|---|---|---|---|---|---|
| P1 | Clay | GTM Engineer – Systems and Infrastructure | (a) vendor | 2026-06-09 | $140K–$200K | https://jobs.ashbyhq.com/claylabs/f90028b7-6c35-4392-824c-105967ccd406 |
| P2 | Clay | GTM Engineer Manager – Seller Efficiency | (a) vendor | 2026-08-31 | $240K–$265K | https://jobs.ashbyhq.com/claylabs/546b27c1-8808-4808-bd98-5c6cad88d88c |
| P3 | Attio | Forward Deployed GTM Engineer (SF) | (c) forward-deployed | 2026-09-17 | $150K–$200K | https://jobs.ashbyhq.com/attio/26c31052-b667-46ae-b459-049018e55e96 |
| P4 | Attio | Forward Deployed GTM Engineer (NYC) | (c) forward-deployed | 2026-05-29 | $150K–$200K | https://jobs.ashbyhq.com/attio/cef00929-63ab-4927-8a3c-1ea1d4224606 |
| P5 | Sierra | GTM Engineer | (b) in-house | 2026-01-29 | $150K–$230K | https://jobs.ashbyhq.com/sierra/1c991675-099f-49dd-9b9b-bd3c9111e65c |
| P6 | Mercor | GTM Engineer (first GTM Engineer hire) | (b) in-house | 2026-08-07 | $175K–$250K | https://jobs.ashbyhq.com/mercor/746c6df1-cc93-46ed-8f68-b8b8515398f4 |
| P7 | Baseten | GTM Engineer | (b) in-house | 2026-08-25 | $175K–$200K | https://jobs.ashbyhq.com/baseten/5cd2f489-b9ee-428b-b252-94e83d55f107 |
| P8 | Baseten | GTM Systems Manager | (b) in-house | 2026-08-27 | $160K–$200K | https://jobs.ashbyhq.com/baseten/7a999a4e-5e04-4432-a7fe-86ad1151e061 |
| P9 | Ramp | GTM Business Systems Engineer – Post Sales | (b) in-house | 2026-09-03 | $122.2K–$183.4K | https://jobs.ashbyhq.com/ramp/696bc715-794c-4a0c-967d-d7f8b637b392 |
| P10 | Ramp | GTM Business Systems Engineer, Quote-to-Cash | (b) in-house | 2026-09-03 | $122.2K–$183.4K | https://jobs.ashbyhq.com/ramp/6310f1b3-1ae2-476c-b4ce-affe530ede26 |
| P11 | Anthropic | Staff Software Engineer, GTM Systems | (b) in-house | 2026-08-21 | $320K–$405K | https://job-boards.greenhouse.io/anthropic/jobs/5368166008 |
| P12 | Anthropic | Staff Software Engineer, GTM AI Engineering | (b) in-house | 2026-09-18 | $320K–$405K | https://job-boards.greenhouse.io/anthropic/jobs/5390966008 |
| P13 | Anthropic | DevOps / AgentOps Engineer, GTM Systems | (b) in-house | 2026-08-21 | $320K–$405K | https://job-boards.greenhouse.io/anthropic/jobs/5392856008 |
| P14 | Vercel | Software Engineer, GTM | (b) in-house | 2026-09-22 | $170K–$260K (SF) | https://job-boards.greenhouse.io/vercel/jobs/5914474004 |
| P15 | Figma | GTM Systems Architect | (b) in-house | 2026-09-01 | $140K–$245K | https://boards.greenhouse.io/figma/jobs/6167305004 |

Also surveyed but not quoted: Sierra *GTM Operations, Agent Development* ($210K–$255K), Mercor *Revenue
Operations* ($150K–$225K), Anthropic *Data Engineer, GTM*, Webflow *Senior Forward Deployed Engineer*, and
Databricks' ~60 Forward Deployed Engineer listings. Common Room, Unify, Rox, 11x, Gong, Hightouch and
Census/Fivetran expose no public Ashby/Greenhouse board at these org slugs, so I have **no verified postings
from the signal-tooling or AI-SDR vendors** and make no claims about their hiring.

### Practitioner and vendor sources

- Liz Christo (Stage 2 Capital), "Do You Need a GTM Engineer?", 2026-08-15 — https://gtm.stage2.capital/p/do-you-need-a-gtm-engineer
- *The GTM Engineer* (Clay), "How to hire a GTM Engineer", 2025-07-17 — https://thegtme.com/p/how-to-hire-a-gtm-engineer
- Clay GTM Job Board — https://www.clay.com/job-board (interface only; no market figures published on the page)
- Third-party market-size claims (SyncGTM, GTME Pulse, herohunt, cleanlist) are **[unverified]** and are not
  relied on anywhere below.

*(Vendor documentation is cited inline in §4; failure-mode and benchmark sources inline in §5–§6.)*

---

## 2. What a strong GTM Engineer is expected to know today

Three distinct jobs share the title, and they want different things:

- **(a) GTM Engineer at a GTM-tooling vendor** (Clay). Dogfooding is half the job: "Push the limits of Clay and
  extend our platform into new use cases… act as a practitioner evangelist" (P1). The rest is *Salesforce
  engineering* — "objects, flows, validation rules, reports, and dashboards", "CPQ and billing workflows",
  "Design protocols, observability and debugging principles to ensure our systems maintain high uptime" (P1).
  Clay asks for "6-10 years… Technical RevOps, GTM Engineering, site reliability engineering (SRE)" and
  "Python, JavaScript, SQL, SOQL, or TypeScript; we pull our own data on this team" (P1).
- **(b) In-house GTM Engineer at a B2B SaaS company** (Sierra, Mercor, Baseten, Ramp, Anthropic, Vercel,
  Figma). This is the target role, and it splits again into a *pipeline* flavour (Sierra, Mercor, Baseten) and a
  *systems-of-record* flavour (Ramp, Figma, Anthropic GTM Systems). The pipeline flavour is the closest match to
  GTMOS: "Design and build the automated workflows, integrations, and AI-powered systems that turn signal into
  pipeline, across enrichment, scoring, routing, and outbound activation" (P5).
- **(c) Forward-deployed / solutions variant** (Attio, Databricks, Webflow). Lowest experience bar of the set —
  Attio asks only "2+ years as a developer, GTM engineer, or in a technical solutions role" (P3/P4) — but the
  highest bar on *communication under someone else's constraints*: "Lead and execute time-boxed build projects,
  delivering real working product: data models, integrations, sequences, workflows, and SDK apps". Attio's
  process includes a **case-study interview** (P3). For a new graduate, this is the realistic entry point, and a
  portfolio that *is* a case study is directly on target.

**The skill set that recurs across all three.** Python and TypeScript (P1, P5, P6, P12, P14); SQL and schema
design even where the role is not a data role — "we pull our own data on this team" (P1), "Working fluency
with data, including SQL" (P12); REST APIs and webhooks (P3, P7, P9); async patterns, retries and idempotency
— Ramp names "data contracts, idempotency, error handling, reconciliation" in both postings (P9, P10), and
Sierra asks you to "think about what happens at 10x volume, when an API goes down, or when the same account
hits your queue five times in parallel" (P5); production LLM work — "Prompt design, eval loops, error
handling, and the difference between a demo and a system you can trust at scale" (P5); and AI coding tools as
a *daily* instrument (P3, P7, P12, P13).

**The GTM knowledge that recurs.** How leads flow through a CRM "and why data quality degrades over time"
(P5); funnel mechanics "from lead generation and attribution to pipeline management and customer expansion"
(P6); territory design and routing — "TAM mapping, account and contact enrichment, rules of engagement,
attribution, and lead routing" (P6), "book carving, ROE automation, signal detection, and pipeline
intelligence" (P2); and quote-to-cash, in five of fifteen postings.

**Two expectations Phase 1 under-weighted.**

1. **Adoption is a deliverable, not a side effect.** Baseten: "Get insights in front of reps… *A build isn't
   done until the field is using it*" and "Drive adoption, not just deployment… measure success by whether
   people actually use it" (P7, P8). Sierra: "You take accountability from code to deployment *to adoption*"
   (P5). Clay: "Measure what matters: track performance, adoption, and business impact of everything you
   build" (P2).
2. **Governance of AI changes is now its own role.** Anthropic is hiring a dedicated engineer to build a
   release pipeline with "three modes: fully agentic, human-in-the-loop, and AI-assisted", to define "what
   agents are scoped to do… what tools and permissions they hold, how they are sandboxed… and what they are
   not trusted to do unsupervised", to own "kill-switch and rollback mechanics", and to "Produce the audit
   trail and evidence a SOX-scoped platform needs" (P13). Anthropic's GTM AI Engineering role likewise asks
   you to "Design the human oversight for each motion: approval gates, handoffs, and escalation paths that
   keep sellers in control" and to "build eval frameworks that prove those agents are ready for
   customer-facing work" (P12).

---

## 3. The systems they actually build day-to-day

Stripped of adjectives, the postings describe seven recurring systems.

1. **An enrichment pipeline that ends in the CRM** — Sierra publishes the most concrete definition anywhere:
   "the pipelines that take a new signup, demo request, or event attendee list and return a fully enriched,
   scored, Salesforce-upserted record across Clay, ZoomInfo, Cognism, and LLM-powered sources" (P5).
2. **A fit/intent scoring service writing to two databases** — "evaluates every account against our ICP and
   writes results to Postgres *and Salesforce*, including signal design, batching, retry logic" (P5).
3. **Routing, territory and rules of engagement** — book carving and ROE automation (P2, P6); LeanData (P9/P10).
4. **Integrations with explicit failure semantics** — "data contracts, idempotency, error handling,
   reconciliation, and safe lifecycle changes" (P9).
5. **A warehouse layer GTM leaders read** — Postgres + Fivetran + reverse ETL, and "track downstream impact
   when schemas and apps change" (P5); dbt/Airflow/Looker/Hex (P6); "dbt models… semantic models… versioning,
   clear lineage" (P14).
6. **Agents with oversight, evals and revenue attribution** — "Develop evaluation frameworks for agent
   behavior, and run them in development *and in production*… Instrument model and tool calls in production,
   and build the observability and measurement that ties agent actions to pipeline and revenue"; plus "Ship an
   MCP server that gives sellers and their agents governed access to a core revenue system" (P12).
7. **The delivery pipeline for all of it** — PR review, CI/CD, automated UAT, on-call (P9, P11, P13, P15).

---

## 4. What the tools actually do now

Only changes that affect GTMOS's design are listed. Everything here was read from the vendor's own docs on
2026-09-22.

- **HubSpot** (https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines). The developer
  platform is now **versioned** — the current standards apply to apps "on the latest versions of the developer
  platform (**2025.2 and 2026.03**)", which is new since Phase 1 and means an integration now has a platform
  version to pin, not just an API version. Published limits for privately distributed apps: burst **100 per
  10 s** (Free/Starter) or **190 per 10 s** (Pro/Enterprise); daily **250,000 / 625,000 / 1,000,000** by tier;
  at most two purchasable limit increases; up to **1,000 webhook subscriptions** per app. Batch read supports
  the `idProperty` parameter for custom unique properties, and "cannot retrieve associations"
  (https://developers.hubspot.com/docs/guides/api/crm/objects/companies) — the latter is a real trap for any
  sync that assumes one batch read returns the full graph. **Lifecycle semantics are unchanged and validate
  GTMOS's model**: the default lifecycle property "can only be moved forward by HubSpot tools" and you "must
  clear the value manually or via a workflow before using these tools to set an earlier value"
  (https://knowledge.hubspot.com/records/use-lifecycle-stages, last updated 2026-07-17). **New since Phase 1:**
  calculated date-entered / date-exited and time-in-stage properties per lifecycle stage — which makes
  stage-duration analysis a CRM-native feature rather than something GTMOS must own alone.
- **Clay** (https://university.clay.com/docs/actions-data-credits). Two currencies: **Actions** (one per record
  per enrichment) and **Data Credits** (**0.5 to 10+ per record depending on data type**), with a typical
  fully-enriched record costing **6–20 credits**. Refunds occur only "if a provider refunds us due to invalid
  data". This is the precise economic argument for GTMOS's per-field waterfall with cost accounting, and it is
  worth citing in the README rather than describing the waterfall generically.
- **Hightouch AI Decisioning** (https://hightouch.com/docs/ai-decisioning/overview) is the category entrant
  GTMOS must position against. It is a warehouse-native **agent loop** — inputs (audience, goals, messages,
  **guardrails**) → decide message/channel/timing → deliver → measure → "update future decisions based on what
  worked" — using "reinforcement learning to balance exploration (testing new options) with optimization", where
  "Agents operate entirely within the inputs and rules you define". The market has moved from *A/B tests a human
  reads* to *a constrained agent allocating traffic continuously*. GTMOS's honest-statistics stance is still
  defensible, but the framing must become "explicit, auditable experiments **versus** a learned policy".
- **PostHog data pipelines / CDP** (https://posthog.com/docs/cdp). Sources, **transformations that "add, edit,
  or drop event properties during ingestion, before anything is stored"**, and destinations delivered in real
  time or by scheduled batch on the same stream that powers analytics. Schema enforcement belongs at ingest —
  the same argument as the data-quality gap in §7.

Not verified this session, and therefore not relied on anywhere above: Clay's HTTP API/webhook surface and its
signals products, HubSpot Breeze, Apollo's sequence API, Census/Fivetran Activations sync behaviours, and n8n's
AI-node and queue-mode specifics. Phase 1's notes on those (`docs/market-research.md` §1) stand unrevised and
should be treated as **[unverified for 2026]**.

---

## 5. Failure modes practitioners complain about

The evidence here is bimodal, and that itself matters: deliverability, webhook semantics, CRM dedupe mechanics
and SDR economics are backed by primary documents, while speed-to-lead, reply rates and win rates circulate as
a network of vendor blogs citing each other. Several widely-quoted "2026 benchmarks" are 2007–2011 studies with
the date stripped off. I have marked the difference.

- **Duplicate records are hard for structural reasons, not laziness.** Salesforce match keys narrow candidates
  to "the 100 most likely duplicates" before the matching equation runs; a rule "only runs on edited records
  when the edited fields are included in the associated matching rule"; and **records saved simultaneously are
  not compared to each other** — exactly the race that bulk imports and concurrent API writes hit
  (https://help.salesforce.com/s/articleView?id=sales.duplicate_rules_overview.htm). HubSpot's own KB documents
  the canonical cross-system bug: Salesforce allows multiple contacts with one email, HubSpot does not, so
  "Salesforce returns all records that match (in no particular order), and HubSpot syncs with the first record
  returned" (https://knowledge.hubspot.com/salesforce/duplicate-salesforce-leads-or-contacts-syncing-to-hubspot).
- **Enrichment credit burn is a documented cost model, not a rumour.** Clay bills Actions plus Data Credits at
  **0.5–10+ credits per data type**, and a fully-enriched record typically runs **6–20 credits**; refunds happen
  only "if a provider refunds us due to invalid data" (https://university.clay.com/docs/actions-data-credits).
  The universal fix practitioners converge on is to gate the waterfall behind a free ICP formula so credits are
  never spent on records that could have been disqualified for nothing.
- **Bad lead-to-account matching produces no visible failure.** It produces "a compounding set of downstream
  errors": leads round-robin to a rep who has never spoken to the account, duplicates are created because the
  company field says "ACME Corporation" rather than "Acme Corp", and account-level attribution silently
  under-counts (https://www.leandata.com/blog/how-to-fix-5-common-breakdowns-in-account-based-motions/).
- **Speed-to-lead: use the real citation.** The famous "21× more likely to qualify within 5 minutes versus 30"
  and "+391% in minute one" come from Oldroyd/InsideSales (2007), reissued via HBR (2011) — not from a 2026
  study. Every "2026 speed-to-lead benchmark" I found was vendor-authored **[unverified]**.
- **Deliverability is the best-documented risk in GTM.** Google requires spam rates in Postmaster Tools below
  **0.30%**, recommends below **0.10%**, and since June 2024 a sender above 0.3% is **ineligible for mitigation**
  until it stays below 0.3% for seven consecutive days (https://support.google.com/mail/answer/81126,
  https://support.google.com/mail/answer/14229414). Microsoft began enforcing SPF + DKIM + DMARC (`p=none`
  minimum, aligned) for senders of **≥5,000/day** to Outlook.com, Hotmail and Live on **5 May 2025**;
  non-compliant mail goes to Junk and may be rejected with `550 5.7.515`. Microsoft publishes **no** numeric
  complaint threshold — the 0.3% figure is Gmail's and is frequently misattributed. Independently, Validity's
  2025 benchmark (seed-list panel) puts global inbox placement at **83.5%**, spam **6.7%**, missing **9.8%**.
- **"AI slop" personalisation.** The circulating decline (reply rates 8.5% → 5.0% → 3.43%) is a citation loop
  with no primary dataset — **[unverified]**. The defensible evidence is Gong Labs' own corpora: across 28M+
  cold emails the average rep sends **344 emails per meeting booked**, "10%+ reply rate is the gold standard",
  and pitching in a cold email cuts reply rates by up to **57%**; across 30,000+ emails at 250+ companies,
  **company-specific** topics roughly **triple** reply rates with director-and-above buyers
  (https://www.gong.io/blog/does-cold-email-even-work-any-more-heres-what-the-data-says). The thing AI SDRs
  fake is precisely the thing that works, and the named governance failure is bots running for weeks with
  nobody reviewing targeting, copy or domain reputation.
- **Webhooks are at-least-once, unordered, sometimes doubled.** Stripe documents that endpoints "might
  occasionally receive the same event more than once"; that in some cases *two separate Event objects* are
  generated (so dedupe must key on object ID **+** event type, because the event IDs differ); and that Stripe
  "doesn't guarantee the delivery of events in the order that they're generated", explicitly warning against
  using `created` for ordering (https://docs.stripe.com/webhooks). The correct primitive is an atomic claim
  (`INSERT … ON CONFLICT DO NOTHING`), never check-then-act.
- **Sync loops between CRM and warehouse.** No vendor documents this, which is itself the finding: CRM →
  warehouse → reverse ETL → CRM echoes, because the write bumps `SystemModstamp`, CDC reads the echo as a real
  change, and flows fire again. Mitigations: write only compute-only fields the CRM never edits, use a
  dedicated integration user excluded from the extract, gate writes on a real value change.
- **Lifecycle drift and attribution disputes.** Marketing defines MQL on behavioural signals, sales inherits a
  definition it never agreed to, and stages get updated manually — therefore not at all. (Practitioners assert
  roughly a third of contacts sit in the wrong stage within six months; that is an assertion **[unverified]**.)
  Attribution is likewise a data-in problem, not a model problem: much of the journey happens where no pixel
  reaches, and finance rejects marketing-tool-only reports with no audit trail. The 2025–26 replacement stack
  is self-reported attribution plus incrementality tests, not better multi-touch models.
- **Adoption and decay.** Salesforce's State of Sales (n = 5,500, fielded 2024) reports reps spending roughly
  **70% of their time on non-selling tasks**, **67%** not expecting to hit quota and **84%** having missed it
  the prior year (https://www.salesforce.com/news/stories/sales-ai-statistics-2024/). CRM contact data decays
  at the industry convention of **~2.1%/month (≈22.5%/year)** — a MarketingSherpa figure nobody links to the
  original study, so treat it as convention, not measurement **[unverified]**.

---

## 6. Metrics that matter, with definitions

| Metric | Definition | Benchmark / source |
|---|---|---|
| **Pipeline coverage** | Open qualified pipeline ÷ remaining quota for the period | Convention is 3×–5×; the honest framing is that the target is the **inverse of your win rate**, so with 2025 win rates near 20% the real floor is 4–5× [vendor-authored, treat as convention] |
| **Sales velocity** | `(Qualified opps × Avg deal size × Win rate) ÷ Cycle length` = revenue per day | Formula is uncontested (https://www.salesforce.com/blog/sales/sales-velocity/). GTMOS already computes this in `analytics.velocity()` |
| **MQL / SQL / SQO** | MQL = behavioural threshold + ICP fit, marketing-owned. **SQL** = interest became intent, confirmed by a human conversation **and accepted by sales**. **SQO** = an SQL that cleared a standardised qualification gate in formal discovery and is now a **forecastable** opportunity | No standards body owns these; each company defines them and RevOps owns the gates — which is the root cause of lifecycle drift. SQO is the first forecastable object; SQL is not |
| **PQL** | A user who has experienced the product and hit predefined activation behaviours | Claimed PQL→customer conversion ~25–30% vs MQL 5–10% **[unverified]**. Note: OpenView's product benchmarks stop at **2022** and the firm wound down in 2024, so there is **no current primary PLG dataset** |
| **Reply → meeting → opportunity** | Positive-reply rate, meeting-booked rate and opportunity rate on sent volume | Gong (28M emails): **344 cold emails per meeting** for the average rep; **10%+ reply rate is "the gold standard"**. Bridge Group 2025 (n = **351** companies, independent): median SDR Stage-0 quota **10 meetings/month, down 40% since 2018**; **$3.78M pipeline sourced per SDR per year**; **60% of SDRs at quota, the lowest on record** (https://www.bridgegroupinc.com/research/2025-sdr-models-metrics-report-the-bridge-group) |
| **Cost per opportunity** | Fully-loaded outbound cost ÷ opportunities created | No credible published benchmark. Derive it: Bridge Group puts SDR OTE at **$80K** against $3.78M sourced pipeline, which makes a defensible internal ratio |
| **Enrichment coverage %** | Share of active records whose scoring fields were validated against a verified external source (not self-reported form input) | Practitioner targets converge on **>80%** coverage, **>80–85%** field completeness on scoring fields, duplicate rate **<3–5%**, email validity **93%+** [vendor-authored]. Worth stealing: track **new duplicates created per week** — a flow metric, not a stock metric |
| **Time-to-first-touch** | Lead creation (form submit or signal fire) → first human outreach attempt. Distinguish **routing latency** (assignment) from **response latency** (rep touch): most SLA misses are the second, most tooling fixes the first | Common SLA targets <5 min high-intent inbound, <15 min as the practical standard; the only durable evidence is the 2007 Oldroyd result |
| **Deliverability** | Spam complaint rate, hard-bounce rate, inbox placement | Gmail: **<0.30% required, <0.10% best practice** (official). Microsoft: auth requirements only, **no published numeric threshold**. Bounce **<2%** healthy, **<1%** excellent. Inbox placement **83.5%** globally (Validity 2025) |
| **Win rate / cycle length** | Closed-won ÷ closed; and days from opportunity creation to close | Roughly **19–21%** win rate and a median B2B SaaS cycle near **84 days**, segmenting 14–30 days SMB to 90–180+ enterprise — all vendor-authored **[unverified]**. Corroborated only indirectly by Bridge Group and Salesforce quota data |

---

## 7. Gap table

Priorities are **hiring value per unit of work**, not product value. P0 = a hiring manager will notice its
absence; P1 = it converts a good answer into a memorable one; P2 = only if time is free.

| Capability | What the market expects | What GTMOS has today | Gap / recommendation |
|---|---|---|---|
| **ICP & segmentation** | Versioned ICP, fit scoring against it, plus **TAM mapping** (P6) and **book carving / territory design** (P2, P6) | Validated, versioned `ICPDefinition` with size bands, regions, technographics, exclusions and weights that must sum to 100 (`domain/icp.py`); preview of grade changes before save; 2,006 accounts scored | **P1 – add TAM/segment coverage.** No notion of addressable market, segment tiers (SMB/MM/ENT) or territory books. *Hiring value:* "how big is the addressable set and how is it carved?" is the first question a GTM leader asks, and two postings name it by title. |
| **Enrichment** | Multi-provider waterfall, validation before accept, **credit/cost accounting**, provenance, caching (P5, P7) | Per-field provider order with fallback on miss/error/low-confidence, one call per provider per run, cost credits, field provenance, manual locks never overwritten (`domain/enrichment.py`) | **Met.** No change. This is already ahead of what most candidates show. |
| **Lead-to-account matching** | Domain normalisation, free-mail exclusion, **fuzzy company-name fallback**, a confidence score, and evidence the matcher is actually accurate; Salesforce's Lead object has no FK to Account, so L2A is fuzzy matching by construction | `domain/matching.py` normalises domains and company names, blocks 20 free-mail domains, prefers an explicit `$groups.company` key (0.98) over email domain (0.90) over parent-domain fallback (0.80), returns a reason, and records unmatched events rather than dropping them | **P1 – finish what Phase 1 specified.** `normalize_company_name()` exists but `match_to_account()` never uses it, so there is **no fuzzy-name fallback**, and Phase 1's G4 requirement to report **precision and recall on a labelled fixture set** was never built. Add a ~200-row labelled fixture (including hard negatives: subsidiaries, agency domains, shared parent domains) and publish precision/recall. *Hiring value:* almost nobody quantifies their matcher; a precision/recall table is an instantly credible artifact. |
| **Signals** | First-party product events, third-party intent/hiring/funding, resolved to an account, decayed, activated within minutes (P2 "signal detection", P5 "turn signal into pipeline") | 13 typed signals across intent/timing/engagement with source, confidence, strength, evidence, dedupe key and half-life decay (`domain/signals.py`); PostHog ingestion → account match → signal → rescore | **Met, with one gap: P1 – signal → action latency is not measured.** Add a per-signal "time from `observed_at` to first action" metric. *Hiring value:* it is the number that proves the loop is closed. |
| **Scoring** | Fit + intent, explainable, written to Postgres *and* the CRM, with "signal design, batching, retry logic" (P5), and score→outcome validation | Pure `score_account()`, 100 points across five categories, every point attributed to a named component with a sentence, input hash for reproducibility, grade X for exclusions (`domain/scoring.py`); `analytics.score_validation()` exists | **P1 – close the learning loop.** Scores are validated descriptively but never fed back: no periodic recalibration, no comparison of predicted vs realised conversion by grade over time. *Hiring value:* answers "how do you know your score is any good?" |
| **Routing** | Rules of engagement, territory, round-robin with capacity, **SLA timers and escalation**, explainable decisions (P2, P6, P9) | Deterministic conflict resolution (priority → specificity → key), ownership respect, inactive-owner reassignment, least-loaded pools with capacity, decision log (`domain/routing.py`) | **P0 – speed-to-lead SLA is missing entirely.** `operations.routing_latency()` measures how long the *engine* took, not time-to-first-touch. Phase 1 specified "SLA timers" (G5) and they were not built. Add an SLA clock per routed account, breach detection, escalation and an SLA-attainment metric. *Hiring value:* speed-to-lead is the single most-quoted routing metric in RevOps and the gap is visible from the Routing page. |
| **CRM sync / reverse ETL** | Idempotent upsert on a stable key, batch limits, retries, change detection, reconciliation, **data contracts** (P9, P10) | Upsert on custom unique `gtmos_account_id`, batches ≤100, 429/5xx retry, payload-hash change detection, dry-run preview, sync log, documented conflict policy (`services/crm_sync.py`, `docs/integrations.md`) | **P1 – reconciliation is absent.** Change detection is not reconciliation: nothing re-reads the CRM and reports drift between what GTMOS believes it pushed and what is actually there. Ramp names "reconciliation" in both postings. Add a periodic diff job with a drift report. |
| **Lifecycle & funnel definitions** | MQL/SQL/SQO definitions owned in code, handoff rules, drift detection (P5 "why data quality degrades over time") | Forward-only funnel and lifecycle with validated transitions, stage history, `FUNNEL_TO_LIFECYCLE` conflict map, invalid-transition DQ rule (`domain/pipeline.py`) | **P1 – no SQL→SQO distinction and no written definitions doc.** GTMOS has `qualified` but no separate sales-*accepted* / sales-*qualified-opportunity* gate with acceptance and rejection reasons. Add SQO with a rejection-reason taxonomy. *Hiring value:* every RevOps interview asks where the MQL→SQL→SQO handoff sits and who rejects. |
| **Outbound + deliverability** | Sequencer integration, and demonstrated awareness of sending risk; Clay's own hiring guide lists "**ignoring risks like deliverability or targeting fatigue**" as a red flag | Campaigns → sequences → steps with full outcome events; opens explicitly untrusted (Apple MPP); `READY` is the hand-off; **no sending, by design** (`docs/integrations.md` §Outbound email) | **P0 – model deliverability without sending.** Not sending is defensible and should stay. But there is no suppression list, no bounce/complaint model, no per-domain sending budget, no consent register beyond a guardrail flag and no contact-fatigue cap. Add these as *pre-send constraints* on the approval queue, with the real thresholds encoded: Gmail's 0.30% spam-rate ceiling and 0.10% target, Microsoft's SPF+DKIM+DMARC requirement for ≥5,000/day enforced since 2025-05-05, RFC 8058 one-click unsubscribe. *Hiring value:* it converts "I didn't build sending" from an omission into a deliberate, informed boundary. |
| **Experimentation** | "Experimentation frameworks" (P6); rapid prototyping then "measure their business impact, and scale successful experiments" (P6) | Account-level hash assignment, Wilson intervals, two-proportion z-test, Newcombe CI, pre-registered minimum sample, refuses premature winners (`domain/experiments.py`) | **Met, and a differentiator.** **P1:** add guardrail metrics (unsubscribes, complaints) so a "winner" that burns the domain cannot win — Hightouch AI Decisioning makes guardrails a first-class input, and GTMOS currently has none. **P2:** add a paragraph positioning explicit, auditable experiments against a learned allocation policy (§4). |
| **Attribution** | Pipeline/conversion/attribution visibility for GTM leaders (P6); the ability to defend the number | Four models side by side, 180-day lookback, unattributed share reported rather than dumped into "direct", opens excluded (`domain/attribution.py`) | **Met.** **P2:** add a self-reported-attribution field and an incrementality holdout, and say plainly that models are not causal. |
| **Data quality** | "Design for data quality — build validation, governance, and structure the rest of the GTM stack can rely on" (P1); dedupe; "Own the quality, documentation, and governance of GTM data" (P6) | 11 rules with stable fingerprints, auto-resolve, audited remediation (merge/route/suppress) (`services/data_quality.py`) | **P1 – validate on ingest, not only in batch.** Today DQ is a scan. Add write-time validation (a data contract at the webhook and enrichment boundary) so bad records are rejected or quarantined rather than detected later, plus **new duplicates created per week** as a flow metric alongside the current stock counts, and a documented survivorship rule per field for merges. *Hiring value:* it is the difference between a monitor and a control. |
| **Observability** | Run logs, dead-letter queues, replay, correlation IDs, on-call; Anthropic measures "lead time, failure rate" on the pipeline itself (P13) | Correlation IDs, audit log with before/after, Operations page (workflow failure rate, retries, DLQ backlog, sync and webhook health, provider hit/error rates), Stack Inspector (`services/operations.py`, `stack_inspector.py`) | **P1 – no SLOs, no alerting, no structured log/trace export.** Everything is a dashboard a human must visit. Define 3–4 explicit SLOs with error budgets (e.g. "PQL routed within 1 business day", "webhook processed < 60 s p95") and surface breach state. |
| **AI usage & safety** | "Prompt design, **eval loops**, error handling, and the difference between a demo and a system you can trust at scale" (P5); "Develop evaluation frameworks for agent behavior, and run them in development **and in production**"; "Instrument model and tool calls in production… that ties agent actions to pipeline and revenue" (P12) | Evidence-pack grounding, numbered citations E1..En, uncited claims stripped, blocking guardrails before approval, DRAFT→REVIEW→APPROVED→READY, `PROMPT_VERSION` recorded (`domain/research.py`, `domain/personalization.py`, `services/research_service.py`) | **P0 – there is no eval harness.** GTMOS validates each output at runtime but has no golden set, no scored rubric, no regression run on prompt change, no unsupported-claim rate tracked over time, and no measurement of whether approved drafts outperform. This is the single most-repeated production-LLM requirement in the postings, and GTMOS is ~80% of the way there already. *Hiring value:* highest ratio of credibility gained to work required. |
| **Warehouse / dbt** | Named in six postings: Postgres + Fivetran + reverse ETL (P5); "Snowflake, BigQuery, dbt, Airflow, Looker, Hex" (P6); "dbt models… testing and documentation standards… semantic models… reconciliation, versioning, clear lineage" (P14); BigQuery/Databricks + Sigma/Hex (P7) | Nothing. Zero `.sql` files and no dbt project in the repo; `services/analytics.py` computes every metric in Python via SQLAlchemy | **P0 – the largest single hole.** GTMOS's own README concedes this ("in a larger company GTMOS's analytics would read from a warehouse (dbt models)"). Add a small dbt project over the existing Postgres: staging models, a funnel/pipeline mart, dbt tests (unique, not_null, accepted_values, relationships), `dbt docs` lineage, and make at least the funnel and velocity metrics read from the mart. *Hiring value:* it is the most commonly named tool GTMOS cannot show, and "I don't know dbt" ends a lot of screens. |
| **Security & permissions** | "what tools and permissions they hold, how they are sandboxed… and what they are not trusted to do unsupervised"; "kill-switch and rollback mechanics"; "the audit trail and evidence a SOX-scoped platform needs" (P13); "financial correctness and auditability" (P11) | Single demo operator; `ADMIN_API_TOKEN` gates destructive and live-write endpoints and is mandatory in production; HMAC on webhooks; full audit log with actor/before/after/reason (`api/deps.py`, `services/common.py`) | **P0 – add roles and a kill switch.** Three roles (rep / RevOps / admin) enforced on mutating endpoints, plus a global "pause all automation" kill switch with a reason and audit entry, and per-workflow enable/disable. The multi-tenant schema already exists, so this is mostly enforcement. *Hiring value:* it directly answers the highest-paid GTM-engineering posting in the set (P13). |
| **Delivery pipeline / change management** | PR review, CI/CD, automated UAT, on-call (P9, P11, P13); UAT for releases (P15); lanes for agentic vs human-in-the-loop changes (P13) | `make check` (lint, mypy strict, 160 tests, production build, Playwright); a GitHub workflow directory exists | **P1 – make the governance visible.** Add a documented change-management story for *GTM config* (ICP versions, routing rules, workflow definitions): propose → preview impact → approve → apply → rollback, with the diff audited. GTMOS already previews ICP grade changes; generalise it. *Hiring value:* nobody else's portfolio has this, and three postings are about it. |
| **Adoption & enablement** | "A build isn't done until the field is using it" (P7); "measure success by whether people actually use it" (P8); "accountability from code to deployment to adoption" (P5) | Nothing. No usage instrumentation of GTMOS itself | **P1 – instrument GTMOS's own usage.** Track approvals per operator, time-to-approve, recommendations acted on vs ignored, and show it on the Stack Inspector. *Hiring value:* it is a stated success criterion in three postings and essentially no portfolio addresses it. |
| **Agent interfaces (MCP)** | "Ship an MCP server that gives sellers and their agents governed access to a core revenue system"; "MCP development" under minimum qualifications (P12) | None | **P1 – expose the Copilot's approved metric functions as an MCP server.** The hard part (a closed set of approved, deterministic analyses) is already built in `services/copilot.py`; MCP is a thin, governed wrapper with the same allow-list. *Hiring value:* small work, and it is named in the job spec of the highest-paid role analysed. |
| **Quote-to-cash / lead-to-cash** | Named in five postings: CPQ and billing workflows (P1), quote-to-cash as a whole role (P10), "lead-to-cash transactions" (P11), deal ops/CPQ exposure (P8) | Opportunities with deal stages, amounts and stage history; nothing after "won" | **P2 – do not build the CPQ.** Instead write one page in `docs/` describing the hand-off contract to billing (what a won opportunity must contain, idempotency of the hand-off, what finance reconciles). *Hiring value:* shows awareness without months of work. |
| **Forecasting & coverage metrics** | Pipeline visibility for leaders (P6); "pipeline intelligence" (P2) | `analytics.velocity()` gives win rate, average deal size, cycle length and a velocity figure; no quota or coverage model | **P1 – add pipeline coverage.** Needs only a quota/target per period; see §6 for the definition. *Hiring value:* it is the first number on every board slide and its absence is conspicuous. |

---

## 8. "Do NOT build" list

Each of these is something the market talks about that would, in this portfolio, add noise instead of signal.

1. **An email/LinkedIn sender.** Keep `READY` as the hand-off. Sending adds consent, reputation and abuse
   surface for zero hiring signal — and Clay's own hiring guide lists ignoring deliverability risk as a red
   flag, which a *modelled* deliverability layer (§7) answers better than an actual SMTP client would.
2. **A drag-and-drop workflow builder.** Weeks of frontend work to demonstrate a UI skill nobody in these
   postings asks for. Definition-as-data with a read-only visual view already proves the engineering point.
3. **A second CRM adapter (Salesforce).** Salesforce dominates the postings, so the temptation is strong —
   but an *untested second* adapter is worse than one well-understood adapter plus a written comparison. The
   `CrmAdapter` protocol already makes the point that the boundary is pluggable. Write the comparison instead.
4. **An LLM-to-SQL feature.** It is the most common "AI in GTM" demo and the most commonly regretted one.
   GTMOS's refusal to let an LLM write SQL is a *stronger* answer than a text-to-SQL box, and it should stay
   framed that way.
5. **A full CPQ / billing engine.** Real quote-to-cash is months of work, almost always owned by another team.
   One page describing the hand-off contract gets most of the credit (§7).
6. **More seeded scale.** 200,000 synthetic accounts proves nothing a reviewer can verify and slows the demo.
   If scale needs proving, benchmark one path (scoring throughput, reverse-ETL batch) and publish the numbers.
7. **Integrations with signal vendors (Common Room, Unify, Koala, Pocus) or AI-SDR products (11x, Artisan,
   Regie).** I could not verify a single job posting at any of them, and the GTMOS signal model already
   generalises over the category. Thin, untested API clients dilute the "everything here actually runs" claim
   that is currently the project's strongest asset.
8. **A second LLM provider, a model router, or more chat surface** (summary widgets, "ask anything" boxes).
   No posting asks for any of it; the postings reward evals, oversight and measured impact instead.
9. **Rewriting the demo dataset to look like a real company.** Synthetic-and-labelled is a credibility
   *asset*; a demo that implies real customers is a liability.

---

## 9. The credibility bar, and what makes a hiring manager say yes in 60 seconds

### Credible vs. student project

Drawn from the postings and from Clay's own hiring guide (https://thegtme.com/p/how-to-hire-a-gtm-engineer,
2025-07-17), whose named red flags are tunnel vision, shiny-object syndrome, over-engineering, **"ignoring
risks like deliverability or targeting fatigue"**, and "lack of commercial awareness".

| Reads as credible | Reads as a student project |
|---|---|
| Failure paths are first-class: retries, dead letters, replay, idempotency keys you can point at | Only the happy path is demonstrated |
| Numbers are traceable to a query or a rule | Hardcoded percentages and invented "results" |
| Limits are stated up front (what is simulated, what is untested) | Claims of production use that cannot be checked |
| A negative or inconclusive result is shown and respected | Every experiment "won" |
| Deliberate scope boundaries with a stated reason (no sending, no CPQ) | Missing pieces with no explanation |
| Risk is modelled even where it isn't exercised — deliverability, consent, fatigue, blast radius | Outbound automation with no mention of deliverability |
| Tests that caught real bugs, named | A test count with no story |
| The tools the market names are actually present (SQL, dbt, warehouse) | Everything reimplemented in one language, warehouse absent |
| Documentation a stranger could operate from | A README that only explains how to run it |

The single most-cited red flag is commercial disconnection: "focusing purely on technical implementation
without connecting to business outcomes". GTMOS's weakest link today is that its engines are excellent and its
*business framing* — coverage, SLA attainment, cost per opportunity, adoption — is thin. Several §7 P0/P1 items
exist mainly to close that.

### The 60-second demo

Liz Christo quotes a practitioner's test for when a company needs this role: hire when "your GTM stack produces
a number nobody in the room can explain" (https://gtm.stage2.capital/p/do-you-need-a-gtm-engineer, 2026-08-15).
GTMOS's whole thesis is the inverse of that sentence, and the 60-second pitch should say so explicitly. The
reviewer should be able to verify, without reading code:

1. **One screen where a number decomposes into its causes.** The account page's "Why this score" is the
   strongest artifact in the project. Lead with it, not with the overview dashboard.
2. **One failure handled well, shown live.** Kill a step, watch it retry, dead-letter, then resume at the
   failed step with the same idempotency key and correlation ID. Systems people trust failure demos more than
   success demos.
3. **One AI output that gets blocked.** The fabricated-metric guardrail. Then — once §7's P0 lands — the eval
   run that proves the guardrail holds across a golden set, with an unsupported-claim rate trended over time.
4. **One honest negative result.** The experiment where positive replies moved significantly but meetings and
   opportunities did not, and the page says so. Refusing to declare a winner is the fastest way to signal
   commercial judgement, which is the red flag Clay's hiring guide names most often.
5. **A README that states its limits in the first screen.** The DEMO banner, the "untested against a live
   portal" admissions and the Limitations section already do this. Do not soften them; they are why the rest
   is believable.

The five P0s, in the order a reviewer is likely to notice them: **a dbt project** (named in six of fifteen
postings and absent entirely), **an eval suite for the AI path**, **roles plus a kill switch**, a
**speed-to-lead SLA with escalation**, and a **deliverability constraint model** that justifies not sending.
