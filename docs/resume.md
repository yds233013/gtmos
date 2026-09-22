# Resume bullets (truthful, repository-verifiable)

All numbers below describe the **engineering scope of this repository and its synthetic demo dataset**, not
business outcomes. GTMOS has no real customers or production traffic, so don't imply otherwise.

## Project line

**GTMOS: AI-native GTM operating system** (Python/FastAPI, PostgreSQL, Redis/RQ, Next.js/TypeScript, Docker)
· github.com/<you>/gtmos

## Bullet candidates (pick 3–5)

- Built an end-to-end GTM operating system (FastAPI, PostgreSQL, Redis/RQ, Next.js) that scores, enriches,
  routes and researches **2,000 accounts** and drafts evidence-grounded outreach behind a human approval queue;
  **40-table** schema, **75** REST endpoints, **20** product pages.
- Designed an **explainable account-scoring engine** (fit, intent, timing, technical, engagement) as a pure,
  deterministic function with signal half-life decay, ICP versioning and reproducible input hashes; every point
  is attributed to a rule and its evidence.
- Implemented a **Clay-style enrichment waterfall** with per-field provider ordering, fallback on
  miss/error/low-confidence, single-call-per-provider batching, cost accounting and field-level provenance;
  found and fixed a cross-position caching bug through unit tests.
- Built an **idempotent workflow engine** (trigger → conditions → actions) with persisted step state, retries
  with exponential backoff, dead-letter handling, resumable manual retry and after-commit Redis enqueueing with
  a stale-run sweeper.
- Engineered a **HubSpot integration boundary** (demo + live adapters) using batch upserts on a custom unique
  property (HubSpot doesn't enforce domain uniqueness), 429/5xx retry, payload-hash change detection and a
  reverse-ETL job for computed account properties.
- Secured inbound webhooks (PostHog, n8n, HubSpot v3) with HMAC signatures, replay windows, event-id dedupe and
  replay; closed an **idempotency-key poisoning** vulnerability where an unsigned delivery could block a later
  valid event.
- Grounded LLM research and personalization in numbered evidence packs with **citation validation** and
  deterministic outbound guardrails (ungrounded numbers, unverifiable claims, stale signals); AI output can't be
  approved while a blocking check fails and is never auto-written to the CRM.
- Implemented GTM analytics and experimentation: funnel, velocity, stuck-account detection, 4-model attribution,
  deterministic account-level A/B assignment with Wilson and Newcombe intervals and minimum-sample gating.
- Built a **GTM Stack Inspector** and data-quality engine (11 rules, audited remediation such as contact and
  account merges) that computes system health and ranks automation opportunities with traceable evidence.
- Shipped with **124 backend tests** (unit + Postgres integration), **14 component tests** and a **22-test
  Playwright** suite (desktop + mobile); mypy --strict, ruff, ESLint and tsc clean; one-command Docker
  Compose stack.

## Short version (one line)

Built GTMOS, an AI-native GTM system (FastAPI/Postgres/Next.js) with explainable account scoring, an
enrichment waterfall, idempotent workflows, a HubSpot reverse-ETL boundary, signed webhook ingestion, and
evidence-grounded AI outreach behind human approval; 160 automated tests.

## How to talk about scope honestly

- Say "synthetic dataset of 2,000 accounts" and "demo/simulated integrations", not "processed X leads".
- The HubSpot and Apollo live adapters are **implemented, not validated against live accounts**.
- The n8n templates were **verified to import** into n8n 2.40.5; they were not run against live feeds.
