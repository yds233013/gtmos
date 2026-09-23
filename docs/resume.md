# Resume bullets (truthful, repository-verifiable)

All numbers below describe the **engineering scope of this repository and its synthetic demo dataset**, not
business outcomes. GTMOS has no real customers or production traffic, so don't imply otherwise.

## Project line

**GTMOS: AI-native GTM operating system** (Python/FastAPI, PostgreSQL, Redis/RQ, Next.js/TypeScript, Docker)
· github.com/<you>/gtmos

## Bullet candidates (pick 3–5)

- Built an end-to-end GTM operating system (FastAPI, PostgreSQL, Redis/RQ, Next.js) that scores, enriches,
  routes and researches **2,000 accounts** and drafts evidence-grounded outreach behind a human approval queue;
  **40-table** domain schema, **90** API operations across 86 paths, **21** page routes.
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
- Secured inbound webhooks (PostHog, n8n, Clay, HubSpot v1/v2/v3) with HMAC signatures, replay windows, event-id dedupe and
  replay; closed an **idempotency-key poisoning** vulnerability where an unsigned delivery could block a later
  valid event.
- Grounded LLM research and personalization in numbered evidence packs with **citation validation** and
  deterministic outbound guardrails (ungrounded numbers, unverifiable claims, stale signals); AI output can't be
  approved while a blocking check fails and is never auto-written to the CRM.
- Implemented GTM analytics and experimentation: cohort funnel with a published metric dictionary, velocity,
  stuck-account detection, 4-model attribution with an unattributed tail, and deterministic account-level A/B
  assignment with Wilson and Newcombe intervals, minimum-sample gating, **minimum detectable effect**, and
  **guardrail metrics** (bounce, unsubscribe, spam, negative reply) evaluated one-sided for harm — a breach
  blocks a variant that won the primary metric.
- Built an **offline backtest for the scoring model** (AUC with Hanley–McNeil intervals, conversion by decile
  and grade, precision@K) that separates the leakage-free part of the score from the part contaminated by
  engagement, reports both biased estimates of the selection effect, and states that the only unbiased design
  is a randomised holdout.
- Added **disqualifying signals** (competitor adopted, layoffs, budget freeze, champion departed, unsubscribed)
  that subtract after category caps, and made the enrichment waterfall **surface provider disagreement**
  instead of resolving it on confidence — the rejected value is stored, shown and raised as a data-quality
  issue rather than silently overwriting a stored one.
- Deepened routing with **named accounts, a fallback queue, hash-based round robin that survives a replay, and
  per-rule first-touch SLAs**, plus a speed-to-lead report that counts only genuine lead events and keeps
  "late" separate from "never touched".
- Shipped **runtime kill switches** (automation, outbound, CRM writes) enforced at the action rather than the
  edge, read from the database on every call, returning `423` with the operator's reason and leaving queued
  work resumable.
- Wrote an **evaluation harness for generated content** (citation validity, number grounding, banned claims,
  prompt-injection resistance, determinism) which found untrusted feed text being copied verbatim into
  research reports, and fixed it with sentence-level sanitisation at the trust boundary.
- Ran **six n8n workflows** against a pinned local n8n 2.40.5 container and the live API — signed forwarding,
  scheduled reverse-ETL, an error-handler workflow made to fail on purpose, and one built specifically to prove
  that three deliveries of the same HubSpot event array (incrementing `attemptNumber`, reordered members)
  produce exactly one stored event.
- Audited the **HubSpot adapter against current documentation** and corrected three things that would have
  failed on first contact with a real portal: private apps sign webhooks with **v1** (plain SHA-256, no
  timestamp and therefore no replay window) rather than v3, the URI must be hashed as sent rather than
  percent-decoded, and association type ids 1/2/5/6 are the **primary** variants — writing only the general
  279/341 produces records that look associated in the UI and behave as orphans in a report.
- Defined a **product-qualified account rule** from PostHog-shaped events: composite and account-level over a
  14-day window, weighted toward acts with switching costs, thresholded so no single criterion qualifies an
  account alone, and fired once per account per week so a rep does not learn to ignore it.
- Built an **integrations observability surface** that separates *mode* from *verification* and refuses a
  "Connected" state — every figure is derived from stored deliveries and sync runs, three of four boundaries
  carry an explicit "real service never reached" badge, and credential requirements report presence, never value.
- Ran a **failure tournament** over five invariants (no duplicate revenue action, no silent corruption, no
  unbounded retry, no unsupported field overwrite, no lost audit trail), which found permanently-invalid
  payloads being retried forever and led to a permanent/retryable split returning `422` instead of `202`.
- Found and fixed a **prompt-injection vulnerability opened by the project's own new enrichment integration**:
  a poisoned `industry` value produced a research brief repeating the injected instruction with a citation.
  The lesson generalises — a trust boundary is a property of where data comes from, not of which field it
  lands in, so adding an integration silently reclassifies fields that were previously safe.
- Modelled the operational database into **analytics marts with dbt** (19 models, 113 tests) and verified the
  marts against the API's semantic layer so the two cannot silently drift.
- Built a **GTM Stack Inspector** and data-quality engine (12 rules, audited remediation such as contact and
  account merges) that computes system health and ranks automation opportunities with traceable evidence.
- Shipped with **465 backend tests** (210 unit + 255 Postgres integration), **14 component tests** and a
  **25-test Playwright** suite (desktop + mobile); mypy --strict, ruff, ESLint and tsc clean; one-command
  Docker Compose stack.

## Short version (one line)

Built GTMOS, an AI-native GTM system (FastAPI/Postgres/Next.js) with explainable account scoring measured by
an offline backtest, an enrichment waterfall that surfaces provider disagreement, idempotent workflows, a
HubSpot reverse-ETL boundary, signed webhook ingestion, experiment guardrails that can reject a winning
variant, and evidence-grounded AI outreach behind human approval; 504 automated tests.

## How to talk about scope honestly

- Say "synthetic dataset of 2,000 accounts" and "demo/simulated integrations", not "processed X leads".
- The HubSpot and Apollo live adapters are **implemented, not validated against live accounts**.
- The n8n workflows **genuinely execute** against a local n8n 2.40.5 container and the running API — that is
  the one integration verified by execution. PostHog and Clay are contracts exercised locally against the
  documented payload shapes; neither vendor service has ever been called.
- The scoring backtest measures a **heuristic on simulated data**. Say "built the evaluation harness and it
  showed the non-leaking part of the score is not distinguishable from random on this dataset" — that is the
  honest and more impressive statement, because it demonstrates the measurement rather than a result.
- The content-evaluation harness grades the **deterministic generator**; no LLM was run, so make no claim
  about any model's behaviour.
