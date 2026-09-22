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

Also surveyed but not quoted: Sierra *GTM Operations, Agent Development* (£135K–£185K / $210K–$255K), Mercor
*Revenue Operations* ($150K–$225K), Anthropic *Data Engineer, GTM* and *Technical Program Manager, GTM Systems*,
Webflow *Senior Forward Deployed Engineer*, Databricks' ~60 Forward Deployed Engineer listings. Common Room,
Unify, Rox, 11x, Gong, Hightouch and Census/Fivetran do not expose a public Ashby/Greenhouse board at these
org slugs, so I have **no verified postings from the signal-tooling or AI-SDR vendors** and make no claims
about their hiring.

### Practitioner and vendor sources

- Liz Christo (Stage 2 Capital), "Do You Need a GTM Engineer?", 2026-08-15 — https://gtm.stage2.capital/p/do-you-need-a-gtm-engineer
- *The GTM Engineer* (Clay), "How to hire a GTM Engineer", 2025-07-17 — https://thegtme.com/p/how-to-hire-a-gtm-engineer
- Clay GTM Job Board — https://www.clay.com/job-board (interface only; no market figures published on the page)
- Third-party market-size claims (SyncGTM, GTME Pulse, herohunt, cleanlist) are **[unverified]** and are not
  relied on anywhere below.

*(Vendor documentation sources are cited inline in §4.)*

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
design, called out explicitly even where the role is not a data role — "we pull our own data on this team"
(P1), "Strong proficiency in SQL and Python" (P6), "Working fluency with data, including SQL" (P12); REST APIs
and webhooks (P3, P7, P9); async patterns, retries and idempotency — Ramp names "data contracts, idempotency,
error handling, reconciliation" in both postings (P9, P10), Sierra asks you to "think about what happens at 10x
volume, when an API goes down, or when the same account hits your queue five times in parallel" (P5);
production LLM work, where Sierra wants "Prompt design, eval loops, error handling, and the difference between
a demo and a system you can trust at scale" (P5); and AI coding tools as a *daily* instrument, not a novelty
(P3, P7, P12, P13).

**The GTM knowledge that recurs.** How leads flow through a CRM "and why data quality degrades over time" (P5);
funnel mechanics "from lead generation and attribution to pipeline management and customer expansion" (P6);
territory design, rules of engagement and routing — Mercor names "TAM mapping, account and contact enrichment,
rules of engagement, attribution, and lead routing" (P6) and Clay names "book carving, ROE automation, signal
detection, and pipeline intelligence" (P2); and quote-to-cash, which appears in five of fifteen postings
(P1, P2 implicitly, P8, P9, P10).

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

1. **An enrichment pipeline that ends in the CRM.** Sierra's is the most concrete definition published
   anywhere: "the pipelines that take a new signup, demo request, or event attendee list and return a fully
   enriched, scored, Salesforce-upserted record across Clay, ZoomInfo, Cognism, and LLM-powered sources" (P5).
2. **A fit/intent scoring service with a home in two databases.** "Build and improve the fit scoring pipeline
   that evaluates every account against our ICP and writes results to Postgres *and Salesforce*, including
   signal design, batching, retry logic" (P5).
3. **Routing, territory and rules of engagement.** Book carving and ROE automation (P2); "rules of engagement,
   attribution, and lead routing — giving decentralized GTM teams a shared view" (P6); LeanData named at Ramp
   (P9, P10).
4. **Integrations with explicit failure semantics.** "Own data contracts, idempotency, error handling,
   reconciliation, and safe lifecycle changes for quotes, contracts, and subscriptions" (P9); "Integrate
   third-party APIs to sync events and information across disparate systems" (P7).
5. **A warehouse/analytics layer that GTM leaders read.** "Develop data architecture using Postgres, Fivetran
   pipelines, and reverse ETL. Keep data jobs healthy and in sync with the tools that consume them; *track
   downstream impact when schemas and apps change*" (P5); "Snowflake, BigQuery, dbt, Airflow, Looker, Hex"
   (P6); Vercel wants "dbt models… testing and documentation standards… semantic models" and comfort with
   "reconciliation, versioning, clear lineage" (P14).
6. **Agents with oversight and evals.** "Build and operate autonomous agents that run go-to-market motions end
   to end… Develop evaluation frameworks for agent behavior, and run them in development *and in production*…
   Instrument model and tool calls in production, and build the observability and measurement that ties agent
   actions to pipeline and revenue" (P12). Also: "Ship an MCP server that gives sellers and their agents
   governed access to a core revenue system" (P12).
7. **The delivery pipeline for all of the above.** PR review, CI/CD, automated UAT, on-call (P9, P11, P13);
   Figma drives "User Acceptance Testing (UAT) for Salesforce enhancements, releases, and system changes"
   (P15).

---

## 4. What the tools actually do now

<!--TOOLS-->

---

## 5. Failure modes practitioners complain about

<!--FAILURES-->

---

## 6. Metrics that matter, with definitions

<!--METRICS-->

---

## 7. Gap table

<!--GAPTABLE-->

---

## 8. "Do NOT build" list

<!--DONOTBUILD-->

---

## 9. What would make a hiring manager say yes in 60 seconds

<!--60SEC-->
