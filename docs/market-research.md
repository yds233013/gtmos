# GTM Engineer Market Research

Access date for all sources: 2026-09-21.

## 1. Method and sources

**Method.** I pulled live GTM-engineering postings from the public job-board APIs (Ashby `api.ashbyhq.com/posting-api/job-board/{org}`, Greenhouse `boards-api.greenhouse.io/v1/boards/{org}/jobs`) and read the full descriptions. Several postings that came up in web search (Basis AI, OnBoard, Instawork, Lighthouse, Beacon Software, Backblaze, Team8) turned out to be closed or 404, so they are **excluded**. I checked vendor facts against the official docs wherever I could fetch them. Anything I could not confirm from a primary source is marked **[unverified]**.

### Job postings used (all open and fetched 2026-09-21)

| # | Company | Role | URL | Posted |
|---|---|---|---|---|
| 1 | Clay | GTM Engineer - Systems and Infrastructure (NYC) | https://jobs.ashbyhq.com/claylabs/f90028b7-6c35-4392-824c-105967ccd406 | 2026-06-09 |
| 2 | Mercor | GTM Engineer (SF; first GTM Engineer hire, $175K-$250K base) | https://jobs.ashbyhq.com/mercor/746c6df1-cc93-46ed-8f68-b8b8515398f4 | 2026-08-07 |
| 3 | Sierra | GTM Engineer (SF) | https://jobs.ashbyhq.com/sierra/1c991675-099f-49dd-9b9b-bd3c9111e65c | 2026-01-29 |
| 4 | Baseten | GTM Engineer (NYC) | https://jobs.ashbyhq.com/baseten/5cd2f489-b9ee-428b-b252-94e83d55f107 | 2026-08-25 |
| 5 | Attio | Forward Deployed GTM Engineer (NYC / SF) | https://jobs.ashbyhq.com/attio/cef00929-63ab-4927-8a3c-1ea1d4224606 | 2026-05-29 |
| 6 | Ramp | GTM Business Systems Engineer - Post Sales (NYC) | https://jobs.ashbyhq.com/ramp/696bc715-794c-4a0c-967d-d7f8b637b392 | 2026-09-03 |
| 7 | Cursor board | GTM Applications Engineer (SF). The posting text refers to "SpaceXAI's go-to-market org", which is quoted as published. | https://jobs.ashbyhq.com/cursor/9d7c8f36-eeb7-4e9f-acbe-d959f6280e46 | 2026-09-09 |

Adjacent roles I saw but did not analyse in depth: Anthropic "Staff Software Engineer, GTM Systems" and "DevOps / AgentOps Engineer, GTM Systems" (Greenhouse), OpenAI "Software Engineer, GTM Growth Engineering" (Ashby), Brex "Engineering Manager, GTM Engineering", Notion "Forward Deployed Engineer, GTM", Decagon "GTM Analytics Engineer".

### Secondary / market-sizing sources (third-party, treat figures as indicative)
- Clay, "GTM Engineering: What It Is and How to Hire in 2026": https://www.clay.com/blog/gtm-engineering
- SyncGTM, "GTM Engineer Jobs in 2026": https://syncgtm.com/blog/gtm-engineer-jobs. It claims Clay appears in more postings than any other tool, followed by HubSpot (52%), Outreach (49%) and Salesforce (45%), and that there were "3,000+ open roles in January 2026". **[unverified; third-party analysis]**
- GTME Pulse, "How to Become a GTM Engineer": https://gtmepulse.com/careers/how-to-become-gtm-engineer/. It cites Clay adoption at 84% and daily CRM use at 92%. **[unverified]**

### Vendor documentation (primary)
- HubSpot: https://developers.hubspot.com/docs/guides/api/crm/objects/contacts, .../associations/associations-v4, .../properties, .../understanding-the-crm, https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines, https://developers.hubspot.com/docs/guides/apps/authentication/validating-requests, https://developers.hubspot.com/docs/api-reference/legacy/webhooks/guide, https://knowledge.hubspot.com/records/use-lifecycle-stages
- PostHog: https://posthog.com/docs/api/capture, https://posthog.com/docs/cdp/destinations/webhook
- n8n: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook.md, .../n8n-nodes-base.crypto.md, https://docs.n8n.io/build/manage-workflows/export-and-import.md
- Apollo: https://docs.apollo.io/reference/people-enrichment, .../bulk-people-enrichment, .../organization-enrichment
- Hightouch: https://hightouch.com/docs/getting-started/concepts, https://hightouch.com/docs/syncs/types-and-modes
- Census (now Fivetran Activations; `docs.getcensus.com` redirects to `fivetran.com/docs/activations`): https://fivetran.com/docs/activations/syncs
- Clay: https://www.clay.com/faq/do-unsuccessful-searches-consume-data-credits-what-about-actions, https://www.clay.com/guides/waterfall-enrichment, https://university.clay.com/docs/claygent-builder
- Gmail sender guidelines: https://support.google.com/a/answer/81126
- Apple MPP effect on opens: https://postmarkapp.com/support/article/1257-open-tracking-and-apple-mail
- Salesforce Lead/convertLead reference pages returned 403 to automated fetch. The Salesforce notes below are from established platform knowledge **[not re-verified this session]**.

## 2. Common GTM Engineer responsibilities

These are consolidated across postings 1-7. The numbers in brackets say which postings mention each one.

1. **Enrichment infrastructure, end to end.** Take a new signup, demo request or event list and return "a fully enriched, scored, Salesforce-upserted record across Clay, ZoomInfo, Cognism, and LLM-powered sources" (Sierra) [2,3,4]. Account and contact enrichment, TAM mapping [2].
2. **Scoring and routing.** Fit scoring against the ICP, written to Postgres and the CRM, "including signal design, batching, retry logic" [3]. Lead routing and rules of engagement [2,3].
3. **AI agents for GTM work.** Lead research, account research, call summarization, RFP responses, outbound personalization, and Slack-accessible agents [2,3,4].
4. **CRM as a system of record.** Build objects, flows, validation rules and dashboards [1,6]. Own CRM-level changes [4]. Design data models [5].
5. **Integrations.** Connect the CRM to adjacent systems "through APIs, webhooks, and automation layers" [1]. Sync events across disparate systems [4]. Own "data contracts, idempotency, error handling, reconciliation" (Ramp) [6].
6. **Data pipelines and reverse ETL.** Postgres, Fivetran and reverse ETL; "track downstream impact when schemas and apps change" [3]. Warehouse to CRM [2,4,5].
7. **Reliability and observability.** "Ship production code with PR review, observability, and proper error handling and debug production incidents (... enrichment failures, LLM timeouts)" [3]. "Design protocols, observability and debugging principles to ensure our systems maintain high uptime" [1]. On-call and CI/CD [6].
8. **Reporting and experimentation.** Dashboards, "experimentation frameworks", and visibility into pipeline, conversion and attribution [2]. Scores and alerts that reps act on [4].
9. **Stack audit and prioritisation.** "Audit the stack and generate your own backlog" [4]. Stack consolidation [4].
10. **Documentation and governance.** Named explicitly in [1,2,4]. Data quality and validation [1,2].
11. **Internal apps.** Full-stack TypeScript/Next.js apps for account intelligence, forecasting and pricing [7]. Custom GTM apps and agents on Vercel [4].

## 3. Expected technical skills

| Skill | Evidence |
|---|---|
| Python | Sierra, Mercor, Clay, Ramp |
| TypeScript / JavaScript | Sierra, Clay, Attio (JS), Cursor (TS/Next.js), Baseten (Vercel) |
| SQL, schema design, warehouses | Mercor (Snowflake/BigQuery/dbt/Airflow/Looker/Hex), Sierra, Clay, Cursor, Baseten (BigQuery/Databricks, Sigma/Hex) |
| REST APIs and webhooks | Clay, Baseten, Attio, Ramp |
| Async patterns, retries, idempotency | Sierra ("async patterns", "retry logic"), Ramp ("idempotency ... reconciliation") |
| Production LLM work: prompt design, eval loops, error handling | Sierra ("the difference between a demo and a system you can trust at scale"), Mercor, Baseten |
| AI coding tools (Claude Code, Cursor, Codex) | Baseten, Attio, Cursor |
| Agent frameworks (Vercel AI SDK, Claude Agent SDK, Mastra) | Baseten (nice to have) |
| Salesforce development (Apex, LWC, SOQL, flows) | Ramp (7+ yrs), Clay, Baseten |
| Low-code orchestration (n8n, Zapier, Make, Workato) | Baseten, Attio, Ramp (Workato/Clay as iPaaS) |
| ETL, reverse ETL, CDPs (Segment, RudderStack, Polytomic) | Attio, Sierra |
| Observability, debugging from logs, CI/CD, unit tests | Sierra, Clay, Ramp |

The build-vs-buy judgement comes up again and again: "You know when to reach for Clay and when to build something custom in Claude Code" (Baseten). "Know when low-code gets you 80% of the way there and when it becomes the bottleneck" (Baseten).

## 4. Expected GTM / RevOps skills

- How leads flow through a CRM, and "why data quality degrades over time" (Sierra).
- Funnel mechanics from lead generation and attribution through pipeline management and expansion (Mercor).
- Territory design, rules of engagement, and lead routing (Mercor). LeanData named at Ramp.
- Lifecycle stages, MQL/SQL definitions, and handoffs between marketing, sales and CS (implied across all postings).
- Quote-to-cash, CPQ and billing handoffs (Clay, Ramp).
- ICP definition, fit scoring and signal design (Sierra).
- Commercial judgement and measuring business impact ("measure their business impact, and scale successful experiments", Mercor).
- Translating fuzzy stakeholder requests into specs (Cursor, Ramp: "architecture diagrams, data model diagrams, process flows, and sequence diagrams").

## 5. Common tools, by category

Tools named in the postings are listed first. Tools added from secondary sources or general market knowledge are marked with *.

- **CRM:** Salesforce (Clay, Sierra, Baseten, Ramp, Cursor), HubSpot (Sierra), Attio (Mercor, Attio).
- **Enrichment / data:** Clay (Clay, Mercor, Sierra, Baseten, Ramp), ZoomInfo, Cognism (Sierra), Apollo*, LLM/web research such as Claygent*.
- **Sequencing / engagement:** Outreach (Sierra), Customer.io (Mercor), Salesloft*, Apollo sequences*, Instantly/Smartlead*.
- **Workflow automation:** n8n, Zapier, Make (Baseten, Attio), Workato (Ramp, Baseten), Gumloop (Baseten).
- **Product analytics / CDP:** Segment, RudderStack (Attio), PostHog*, Amplitude*.
- **Warehouse / ETL / reverse ETL:** Postgres, Fivetran, reverse ETL (Sierra), Snowflake, BigQuery, dbt, Airflow (Mercor), Databricks (Baseten, Cursor), Polytomic (Attio), Hightouch*, Census (now Fivetran Activations)*.
- **BI:** Looker, Hex (Mercor), Sigma, Hex (Baseten).
- **Revenue intelligence and ops:** Gong, LeanData, CPQ (Ramp).
- **AI:** frontier LLM APIs (Mercor, Sierra), Claude Code, Cursor, Codex (Baseten, Attio), Vercel AI SDK, Claude Agent SDK, Mastra (Baseten), Notion Agents (Baseten).
- **Hosting / infra:** Vercel (Baseten, Cursor), Datadog (Cursor).

## 6. Common architectural patterns

1. **Enrichment waterfall.** Query providers in sequence and stop at the first confident result, with a validation step (for example, email verification) before accepting it. Clay bills Data Credits only when a provider returns data: "Each record stops at the first confident result... If the entire waterfall returns no results, no Data Credits or Actions will be consumed" (Clay FAQ / waterfall guide). Apollo exposes its own `run_waterfall_email` / `run_waterfall_phone` flags. These are asynchronous and deliver by webhook or polling.
2. **Signal-based selling.** Ingest first-party signals (product events from PostHog or Segment, form fills, pricing-page visits), second-party signals (community, events) and third-party signals (intent data, hiring, funding, tech installs). Resolve each signal to an account, score it with decay, and activate through a CRM task or sequence. This is Sierra's "turn signal into pipeline".
3. **Lead-to-account (L2A) matching.** Match an inbound lead to an existing account by normalised email domain (after stripping free-mail domains), then fall back to fuzzy company-name matching and, where available, enrichment-provided firmographic IDs. Record the match confidence. In HubSpot, company `domain` is the de-duplication key but it is **not** enforced as unique, so it cannot be an upsert `idProperty` (see the integration notes).
4. **Routing.** Rules evaluated in order: existing owner (account-based), then territory (geo, segment, industry), then round robin within a pool. Tie-breakers include capacity/cap, working hours, and last-assigned time. SLA timers escalate when a lead is not touched. Named vendor: LeanData.
5. **Reverse ETL.** The warehouse is the source of truth. A SQL model has a primary key, and a sync has a mode (upsert, update, insert, mirror/all, archive) plus field mappings and a destination match key. Change data capture (CDC) sends only diffs (Hightouch). Census is now Fivetran Activations, with behaviors Update or Create, Update Only, Create Only, Mirror, Append, Delete.
6. **Webhook ingestion with idempotency.** Verify the signature (HubSpot v3 is HMAC-SHA256 with a 5-minute timestamp window), acknowledge fast (HubSpot retries if there is no response within 5 s, up to 10 times over 24 h), persist raw events keyed by the provider event ID, de-duplicate, and process asynchronously. Ramp names "data contracts, idempotency, error handling, reconciliation".
7. **Human-in-the-loop AI.** The LLM drafts research, scores or emails, a human approves or edits, and edits feed evals. Sierra stresses "eval loops, error handling"; Baseten stresses durable workflows and sandboxed execution.
8. **Observability and reconciliation.** Run logs, dead-letter queues, replay, and periodic reconciliation between warehouse and CRM (Clay, Sierra, Ramp).

### Supporting concepts (checked facts)
- **HubSpot lifecycle stages** (internal values): `subscriber`, `lead`, `marketingqualifiedlead`, `salesqualifiedlead`, `opportunity`, `customer`, `evangelist`, `other`. Automatic updates only move forward; you must clear the value to move backward.
- **Attribution models:** first-touch, last-touch, linear, U-shaped (position-based), W-shaped, time-decay, and data-driven. These are standard industry definitions **[not tied to a single primary source here]**.
- **Deliverability:** Gmail requires all senders to have SPF or DKIM, valid PTR, TLS, and a spam rate under 0.3%. Bulk senders (5,000+/day to Gmail) need SPF **and** DKIM, DMARC with From-domain alignment, and one-click unsubscribe (`List-Unsubscribe` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click`, RFC 8058).
- **Open tracking is unreliable.** Apple Mail Privacy Protection (iOS 15 / macOS Monterey, 2021) prefetches remote content, including tracking pixels, through Apple proxies when the mail arrives, which inflates opens (Postmark). Outbound experiments should use replies, positive replies, meetings booked and pipeline created as their metrics, not opens.
- **Experiment measurement for outbound:** randomise at the account level (not the contact level) to avoid contamination. Fix sample size and duration up front, compare reply and meeting rates with a two-proportion test or Bayesian beta-binomial, and keep a holdout for attribution **[methodology; standard practice, not a single cited source]**.
- **Salesforce core objects [not re-verified this session]:** Lead (an unqualified person plus company in a single record), Account (company), Contact (person linked to an Account), Opportunity (deal on an Account). Lead conversion (`Database.convertLead` / `LeadConvert`) creates or merges an Account and Contact and optionally an Opportunity. It requires a converted status and sets `IsConverted` and `ConvertedAccountId` / `ConvertedContactId` / `ConvertedOpportunityId`. HubSpot has no Lead-to-Contact split in the same way: a person is always a Contact, and qualification lives in `lifecyclestage` / `hs_lead_status` (HubSpot also added a separate Leads object in 2024 **[unverified detail]**).

## 7. Gaps this project must demonstrate

These are mapped to what hiring managers ask for. Each bullet should become a spec feature with a measurable acceptance test.

- **G1 Idempotent CRM upsert adapter:** batch upsert to HubSpot using a custom unique `idProperty` (not `domain`), capped at 100 per batch, with 429 handling driven by `X-HubSpot-RateLimit-*` headers, and a dry-run diff mode.
- **G2 Signed webhook ingestion:** HubSpot v3 signature verification (HMAC-SHA256, base64, 5-minute replay window), raw event store, dedupe on event ID, async worker, dead-letter queue and replay.
- **G3 Enrichment waterfall:** pluggable providers (Apollo plus mocks), per-field stop conditions, validation, cost/credit accounting per record, caching, and provenance for every field.
- **G4 Lead-to-account matching:** domain normalisation, a free-mail blocklist, fuzzy name fallback, a confidence score, and a test fixture set with precision/recall reported.
- **G5 Routing engine:** declarative rules (owner, territory, then round robin), tie-breakers, capacity limits, SLA timers, and an explainable "why routed" log.
- **G6 Signal ingestion and scoring:** PostHog events with `$groups` for company-level signals, fit plus intent scores with decay, threshold-triggered actions, and score explanations.
- **G7 Warehouse as source of truth and reverse ETL:** a SQL model with a primary key, sync modes (upsert/update/mirror), field mapping config, CDC diffing and reconciliation reports.
- **G8 Human-in-the-loop AI research and drafting:** a Claygent-style account research agent with citations, an approval queue, captured edits, and an offline eval harness (golden set, rubric, regression checks).
- **G9 Workflow-tool interoperability:** exportable n8n workflow JSON that calls GTMOS endpoints with header auth, showing the "low-code vs custom" judgement.
- **G10 Outbound experiment framework:** account-level randomisation, reply/meeting metrics (open rates explicitly excluded because of MPP), significance reporting, and deliverability preflight (SPF/DKIM/DMARC checks).
- **G11 Lifecycle and funnel reporting:** lifecycle-stage transitions (forward-only semantics), conversion and velocity by stage, and a simple attribution model comparison.
- **G12 Production hygiene:** typed code, tests, CI, structured logs and metrics, runbooks, architecture and sequence diagrams, and data contracts. Named in the Sierra, Clay and Ramp postings.
