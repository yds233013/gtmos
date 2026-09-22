# GTM Concepts, and How GTMOS Implements Them

This is a reference for the go-to-market (GTM) concepts GTMOS is built around. Each concept has four parts: what it is, why it matters, how GTMOS does it (with file references), and what a production version would add.

All paths are relative to the repository root. Backend logic lives in `apps/api/src/gtmos/`. It is split into `domain/`, which holds pure, deterministic, unit-tested functions with no I/O, `services/`, which handles database orchestration, and `integrations/`, which holds the vendor boundaries. Numbers labeled **demo** come from the seeded synthetic dataset (`seed/generator.py`) as served by the local API. They show that the mechanics work. They are not business results.

---

## 1. Ideal Customer Profile (ICP)

**What it is.** A structured description of the companies most likely to buy, retain and expand. It covers industry, size, geography, technical profile, buyer personas and hard exclusions.

**Why it matters.** Scoring, routing, messaging and territory design all start from the ICP. A vague ICP ("mid-market tech") produces vague pipeline.

**How GTMOS does it.** `domain/icp.py` defines `ICPDefinition` as a Pydantic model, not free text. It holds core and adjacent industries, a `SizeBand` (hard minimum 25, target range 100–10,000, sweet spot 250–5,000), primary and secondary regions, a `TechnicalProfile` (AI-team thresholds, LLM-stack and platform technologies), `positive_signals` (the point budget for each signal type), exclusions (industries, sanctioned countries, domains) and `CategoryWeights`. Validators enforce that the weights sum to 100, that no industry is both core and excluded, that the size band is ordered, and that every signal type is known. ICPs are versioned in the `icp_profiles` table. Before an ICP change is saved, `services/scoring_service.py::preview_icp` re-scores every account under the draft and shows the new grade distribution and the biggest movers.

**Production would add.** A closed-won backtest to calibrate the weights, separate ICPs per product line or segment, and an approval workflow for ICP changes, since every change re-routes revenue.

---

## 2. Firmographic and technographic data

**What it is.** Firmographics are company facts: industry, headcount, HQ, funding stage, revenue, growth. Technographics describe the technology a company uses (for example LangChain, Pinecone, Snowflake).

**Why it matters.** Firmographics decide fit. Technographics decide technical compatibility, and often reveal the use case: a vector database suggests RAG, which suggests evaluation pain.

**How GTMOS does it.** Fields live on the `Account` model (`models/crm.py`). Every enriched field has a `FieldProvenance` row recording its value, source provider, confidence, observation time, the enrichment run that set it, and an `is_manual_lock` flag. Scoring reads technographics in `domain/scoring.py::_score_technical`. A company running one LLM-stack technology earns 40% of the "LLM stack" budget, two earn 70%, and three or more earn 100%.

**Production would add.** Real providers (Clearbit/Breeze, Apollo, BuiltWith, HG Insights), confidence calibration per provider, and scheduled refreshes, because headcount and stack data drift.

---

## 3. Enrichment waterfalls

**What it is.** Providers are asked in a fixed order, field by field, until one returns a confident value. This is the pattern Clay popularized.

**Why it matters.** No single vendor covers everything, and the best source differs by field (the best employee-count source is rarely the best tech-stack source). A waterfall gives higher coverage at lower cost than buying one expensive vendor.

**How GTMOS does it.** `domain/enrichment.py::run_waterfall` is a pure function:

- **Per-field order.** `integrations/enrichment_providers.py::DEFAULT_WATERFALL` sets it, for example `employee_count: [demo_firmographics, apollo, demo_webscan]` and `technologies: [demo_webscan, apollo]`.
- **Batching.** Each provider is called at most once per run. Fields that share a provider at the same position are batched together, and the response is cached for later positions. Vendors bill per lookup, so this controls cost.
- **Outcomes.** Every attempt is recorded as `hit`, `miss`, `low_confidence` (below 0.6), `error` or `skipped`, with its latency and credit cost (`EnrichmentAttempt` rows).
- **Fallback.** The best low-confidence answer is kept as a fallback in case nothing better arrives.
- **Merge policy** (`decide`). A value never overwrites a manual lock. It replaces an existing value only when its confidence is at least 0.10 higher, or when the existing value is stale (older than 180 days) and the new one is at least as confident. When a provider confirms an existing value, the existing confidence is raised.

Three simulated providers (firmographics at 1.0 credit with 82% coverage and a 5% error rate, web scan at 0.5 credit with 78% coverage, hiring index at 0.75 credit with 70% coverage) produce real misses, errors and low-confidence answers. `ApolloOrganizationProvider` is a real adapter that registers only when `APOLLO_API_KEY` is set. It **has not been tested against the live API.**

**Production would add.** Email and phone waterfalls with verification (ZeroBounce/NeverBounce), response caching with TTLs, per-provider rate limiting and budgets, asynchronous vendor callbacks, and coverage/cost dashboards per provider per segment.

---

## 4. Buying signals and time decay

**What it is.** A signal is a timestamped fact that changes whether or when an account is likely to buy: a funding round, a new executive, AI hiring, a product launch, pricing-page visits, product usage.

**Why it matters.** Fit tells you who could buy. Signals tell you who might buy now. Signals also go stale: a pricing visit from last week matters much more than one from last quarter.

**How GTMOS does it.** `domain/signals.py::SIGNAL_TYPES` catalogs 13 types. Each has a category (intent, timing or engagement), a typical strength and a half-life, ranging from 14 days (pricing page, website) to 120 days (executive hire, expansion). Decay is exponential: `decay_factor = 0.5 ** (age_days / half_life)`. A signal's value (`domain/scoring.py::signal_value`) is `confidence × min(strength/typical, 1.25) × decay`, capped at 1.0. Repeat signals of the same type add 25% of their value each, so ten website visits do not count as ten signals. Future-dated signals (clock skew, bad feeds) are ignored.

Ingestion (`services/signal_service.py`) follows the steps normalize → dedupe → persist → rescore → trigger workflows. `signal_dedupe_key` hashes `(type, account domain, source_ref)`, and Postgres enforces uniqueness with `UniqueConstraint(workspace_id, dedupe_key)`, so the same event arriving from two feeds becomes one signal. Pricing views become a signal only after 2 or more views in 7 days, keyed to the ISO week (`services/product_events.py`).

*Demo:* Kestrel Analytics' AI hiring surge (14 open roles, observed 6 days ago, confidence 92%, 45-day half-life) earns 88% of its 10-point budget, or 8.83 points.

**Production would add.** Real sources (Crunchbase or news APIs, job-board scrapers, people-movement feeds, G2/Bombora intent), per-source confidence priors, and half-lives fitted from historical conversion data.

---

## 5. Account scoring: fit, intent, timing, technical, engagement

**What it is.** A single number (with a grade) that ranks accounts by likelihood to buy, broken into interpretable categories.

**Why it matters.** Reps prioritize by it and routing keys off it. If reps cannot see why an account scored 87, they ignore the score.

**How GTMOS does it.** `domain/scoring.py::score_account` is a pure function of `(ICP, account facts, signals, engagement, now)`. The category budgets come from the ICP weights and default to Fit 35, Intent 25, Timing 15, Technical 15, Engagement 10.

- **Fit:** industry (core earns full credit, adjacent half), size (sweet spot 100%, target range 65%, above range 40%, below 15%), geography.
- **Intent:** signals in the intent category (hiring, launches, job postings, tech adoption, pricing visits).
- **Timing:** funding, executive hires, expansion, plus 12-month headcount growth.
- **Technical:** AI-team size, LLM stack, platform maturity.
- **Engagement:** replies, positive replies and meetings in the last 90 days, plus product signals.

Every point belongs to a `Component` that carries a human sentence and evidence (field values or signal IDs). Each category is capped at its budget, and the `capped` flag records when that happened. Exclusions (excluded industry, sanctioned country, do-not-target domain, below the hard minimum) produce grade **X** with a stated reason. The grades are A ≥ 80, B ≥ 65, C ≥ 50, otherwise D. Each run stores an `inputs_hash` (SHA-256 of all inputs plus the day), so a score can be reproduced and compared across ICP versions. `intent_index` normalizes intent, timing and engagement to 0–100 as a "why now" number that ignores fit.

*Demo:* Kestrel scores 98/A (fit 35/35, intent 25/25 capped, timing 13/15, technical 15/15, engagement 10/10). `services/analytics.py::score_validation` checks whether grades predict outcomes. Among contacted accounts, B-grade meeting rate is 18.9%, C is 15.5% and D is 6.2%. The note in the code admits a bias: engagement points come partly from outcomes.

**Production would add.** A holdout backtest against closed-won deals, a logistic or GBM model to set the weights (with the rules kept as the explanation layer), and score-change alerts.

---

## 6. Buying committee

**What it is.** The set of people involved in a B2B purchase: champion, technical evaluator, economic buyer, executive sponsor, end users.

**Why it matters.** Single-threaded deals die when the champion leaves or loses internal arguments. Multi-threading to the economic buyer is one of the most common coaching points in enterprise sales.

**How GTMOS does it.** `domain/committee.py::infer_committee` scores every contact for every role. It uses title regexes (each with a written reason), seniority and department bonuses, +15 for product usage, +12 for a meeting attended (or +8 for a reply), −15 for an invalid email and −40 for do-not-contact. The minimum role score is 35. Roles are filled most-constrained first (sponsor, then buyer, then champion, evaluator, end user), so one strong executive does not take every role. A person can hold two roles only when no one else qualifies. Manual overrides from reps always win and survive recomputes (`services/committee_service.py`).

*Demo:* At Kestrel the champion is Priya Raman (Head of AI Platform, score 112, confidence 0.93), the economic buyer is Elena Park (VP of AI), the sponsor is Dana Whitfield (CTO), the evaluator is Tomás Alvarez and the end user is Aisha Okafor. A duplicate Priya Raman record (mixed-case email with a leading space) shows up as the #2 champion candidate. This is the data-quality problem the dedupe rules exist to catch.

**Production would add.** Org-chart data, email and calendar signal (who is cc'd), LinkedIn relationship mapping, and learned role models trained on closed-won committees.

---

## 7. Account research with evidence grounding

**What it is.** A brief on an account covering what it does, why now, likely pain, the committee, objections and a recommended angle.

**Why it matters.** Good research raises reply rates and discovery quality. An LLM writing research without constraints will hallucinate funding amounts, customers and executives, and one invented fact in an email destroys credibility.

**How GTMOS does it.** `domain/research.py` runs evidence pack → claims with citations → validation:

1. `build_evidence_pack` numbers everything GTMOS actually holds as E1…En: firmographics with provenance, technographics, signals, committee members, recent activities and the score.
2. A generator writes claims. The generator is either `generate_deterministic`, which only restates and combines evidence, or `integrations/llm.py::AnthropicResearchWriter`, which uses structured output with a system prompt that says "use ONLY the numbered evidence". Each claim must cite refs, and inferences are marked `hypothesis=true`.
3. `validate_sections` removes claims that cite nothing or cite refs that do not exist, and lists them as `unsupported`. LLM output goes through exactly the same validator.

Reports are stored as drafts with `prompt_version` and an input hash, and they are never written to CRM fields as fact. The LLM path is opt-in (`LLM_ENABLED=true` plus a key), and it falls back to the deterministic generator if the provider fails.

**Production would add.** Retrieval over the web and first-party documents (each result becomes evidence with a URL), claim-level entailment checks (does E3 actually support the sentence, not just get cited?), an offline eval set, and capture of rep edits as training signal.

---

## 8. Personalization (signal → pain → value → proof → CTA) and guardrails

**What it is.** Outreach built from a reasoning chain: a verified trigger, a hypothesis about the pain it creates, the relevant value proposition, approved proof, and a low-friction call to action.

**Why it matters.** "I saw you raised a Series C" is not personalization. Personalization means connecting the trigger to a problem the product solves. The reasoning chain also makes messages reviewable.

**How GTMOS does it.** `domain/personalization.py`:

- **Angles.** `ANGLE_PLAYBOOK` maps an angle (for example `launch_reliability`) to a pain, a value proposition and a discovery question. The angle is chosen from the account's signals by `domain/research.py::choose_angle`.
- **Proof.** Proof can come only from `SELLER_PROOF_LIBRARY`, a set of approved product statements, so messages cannot invent customer logos or metrics.
- **Multi-threading.** Once an opportunity is open, `services/outreach_service.py::pick_recipient` targets the economic buyer first. If the champion has already met with the team, the opener references them ("I've been working with Priya…").
- **Guardrails.** `run_guardrails` checks every draft, whether deterministic, LLM-written or rep-edited. The blocking checks are `numbers_grounded` (every number must appear in the evidence), `no_unverifiable_claims` (banned patterns: "guarantee", "10x", "best-in-class", "customers like", "as we discussed"), `signal_verified` (anchor signal at most 120 days old with confidence of at least 0.7), `contact_reachable` (not do-not-contact, email not invalid) and LinkedIn length. The warning-only checks are email length (130 words), CTA present and account named.
- **Approval.** The state machine runs DRAFT → REVIEW → APPROVED → READY. Blocking failures prevent approval, and editing an approved draft sends it back to review. GTMOS never sends anything.

**Production would add.** A sequencer hand-off (Outreach, Salesloft, Apollo) at READY, capture of rep edits, LLM wording variants measured through experiments, and deliverability preflight (SPF/DKIM/DMARC, one-click unsubscribe).

---

## 9. Lead-to-account matching

**What it is.** Resolving an inbound person or event (a form fill, a product signup) to the right company record.

**Why it matters.** Without it, a VP at a target account who signs up for the free tier is routed as an anonymous lead to an SDR queue while the named AE never hears about it.

**How GTMOS does it.** `domain/matching.py::match_to_account` checks sources in priority order:

1. An explicit company group key (PostHog `$groups.company`), confidence 0.98.
2. An exact email-domain match, confidence 0.9.
3. A subdomain of a known account (`eu.kestrel.example` → `kestrel.example`), confidence 0.8.

Free-mail domains (gmail.com and 18 others) never match. `normalize_domain` strips protocol, `www.`, path, port and case. Unmatched events are stored as `Engagement` rows with no account rather than dropped.

**Production would add.** Fuzzy company-name matching, IP-to-company resolution (reverse IP), enrichment-provider firmographic IDs, a labeled fixture set with reported precision and recall, and a manual review queue for low-confidence matches (the LeanData pattern).

---

## 10. Lead routing: territory, pools, conflicts, ownership

**What it is.** Assigning an account or lead to the right owner quickly, using territory, segment and intent rules plus a fair distribution method.

**Why it matters.** Speed-to-lead and correct ownership are direct revenue levers. Routing disputes also destroy trust between sales and RevOps.

**How GTMOS does it.** `domain/routing.py::route`:

- **Rules as data.** Rules are `{field, op, value}` conditions (`domain/rules.py`, with no `eval()`). Each has a priority and a strategy: `user` or `pool_least_loaded`.
- **Conflict resolution.** The lowest priority number wins. On a tie, the more specific rule (more conditions) wins. On a further tie, the alphabetical rule key wins. Every losing rule is recorded with the reason it lost.
- **Ownership.** An active existing owner is kept unless the winning rule has `overrides_existing_owner`. An inactive owner triggers reassignment.
- **Distribution.** GTMOS uses least-loaded assignment (open accounts ÷ capacity, ties broken by name then id), not strict round-robin. When everyone is at capacity, it still assigns and raises a capacity alert.
- **Fallbacks.** If a named user is inactive, the account falls back to that user's team pool. If nothing matches, it goes to a RevOps triage queue.

Every decision is saved as a `RoutingDecision` with matched rules, conflicts, the explanation and latency from the signal (`services/routing_service.py`).

*Demo:* Kestrel matched both "High-intent strategic → Senior AE" (priority 20) and "Enterprise NA → Enterprise AE pool" (priority 30). The first won on priority and the conflict is logged. The Stack Inspector finds 107 unmatched decisions in 90 days (APAC 71, LATAM 30) because the seed has no APAC rule. That territory gap is deliberate.

**Production would add.** Working hours and PTO, SLA timers with escalation, true round-robin with a last-assigned timestamp, account-based routing for leads (route to the account owner), and a rule-change dry run over historical data.

---

## 11. Lifecycle stages vs funnel stages

**What it is.** Lifecycle stage is a CRM-wide classification of a record's relationship with you (HubSpot: subscriber → lead → MQL → SQL → opportunity → customer → evangelist). Funnel or deal stages track progress through a specific motion or deal.

**Why it matters.** Mixing them up breaks reporting. HubSpot lifecycle is forward-only by default, and conversion metrics depend on clean stage history.

**How GTMOS does it.** `domain/pipeline.py`:

- **Funnel.** Stages run prospect → contacted → engaged → qualified → meeting → opportunity → won/lost. Skipping forward is allowed. Moving backward is not, except into `lost`. `won` and `lost` are terminal unless the account is explicitly recycled to `prospect`, and `won` requires an open opportunity.
- **Lifecycle.** Lifecycle is forward-only. `FUNNEL_TO_LIFECYCLE` derives the lifecycle a funnel stage implies (engaged → MQL, qualified → SQL). Losing does not change lifecycle.
- **Audit.** `invalid_history_transitions` feeds the data-quality rule that flags bad history. Every change is written to `StageTransition`.

**Production would add.** Per-motion pipelines (new logo, expansion, PLG), stage entry and exit criteria enforced in the CRM, and time-in-stage SLAs.

---

## 12. CRM data model and upsert keys

**What it is.** HubSpot's core objects are **Companies**, **Contacts** and **Deals**, linked by associations. Salesforce has Lead, Account, Contact and Opportunity.

**Why it matters.** Duplicates in the CRM split activity history, cause double outreach and corrupt attribution. The choice of match key decides whether an integration creates duplicates.

**How GTMOS does it.** `integrations/hubspot.py` maps Account → Company, Contact → Contact and Opportunity → Deal, with deal stages mapped to HubSpot's defaults. Companies upsert on a custom unique property `gtmos_account_id` (`hasUniqueValue: true`), not on `domain`. **HubSpot does not enforce domain uniqueness, so domain cannot be a batch-upsert `idProperty`.** Domains are also not identities: subsidiaries share them and companies rebrand. Using a unique property that GTMOS owns makes every write idempotent, because replaying a sync updates records instead of creating new ones. Contacts upsert on `email` and deals on `gtmos_opportunity_id`. `ensure_properties` creates the custom properties and treats a 409 response as "already exists".

**Production would add.** Associations v4 writes, Salesforce support (external ID fields and Lead conversion), an initial backfill that matches existing CRM records by domain before assigning `gtmos_account_id`, and field-level ownership rules.

---

## 13. Reverse ETL

**What it is.** Pushing modeled data (scores, tiers, product usage) from the system that computes it (usually a warehouse) into operational tools (CRM, sequencer, ads), so reps see it where they work.

**Why it matters.** A score that lives only in a dashboard changes nothing. Hightouch and Census (now Fivetran Activations) productized this: a model with a primary key, a match key, a sync mode, and change detection (CDC) so only diffs are sent.

**How GTMOS does it.** `services/crm_sync.py::run_company_sync` follows the same contract:

1. Build the desired properties per account (`gtmos_icp_score`, `gtmos_intent_score`, `gtmos_score_grade`, `gtmos_account_tier`, `gtmos_last_signal(_at)`, `gtmos_next_best_action`).
2. Hash the payload and skip records whose hash matches `ExternalRecord.last_payload_hash`. This is the change detection.
3. Upsert changed records in batches of up to 100 on the unique key.
4. Retry retryable failures for up to 3 rounds with backoff.
5. Write an `IntegrationSync` log with counts, errors and a simulated flag.

`preview_reverse_etl` is a dry run that shows would-create, would-update and unchanged counts plus per-field change counts. By default, only A/B/C accounts sync. **Every demo sync goes to `DemoHubSpotAdapter`, which writes to a `simulated_crm_objects` table, injects deterministic simulated 429s, and is labeled SIMULATED.**

**GTMOS vs Hightouch/Census.** GTMOS computes and syncs in one application, with Postgres as its store. Hightouch and Census sit on a warehouse and sync SQL models to hundreds of destinations, with mirror and delete modes, scheduling and alerting. At a company that already has Snowflake and dbt, the right design is usually for the scores to become a dbt model with Hightouch syncing it. GTMOS would then own only the logic.

**Production would add.** Mirror and archive semantics, a scheduler, per-field conflict policy, and periodic reconciliation reports that compare CRM values with the desired state.

---

## 14. Webhooks and idempotency

**What it is.** A webhook is an HTTP callback from another system (HubSpot, PostHog, n8n). An idempotent operation produces the same result however many times it runs.

**Why it matters.** Webhook senders deliver at least once. HubSpot retries on timeouts, and networks duplicate requests. Without idempotency you get duplicate signals, duplicate workflow runs and duplicate tasks.

**How GTMOS does it.** `services/webhook_service.py::receive` runs verify → store raw → dedupe → process → record outcome:

- **Verification** (`integrations/signatures.py`):
  - The GTMOS HMAC scheme signs `timestamp.body` with SHA-256 and rejects timestamps outside a 5-minute window, which blocks replays.
  - A shared-token header covers PostHog, which cannot compute HMACs.
  - The HubSpot v3 verifier checks base64 HMAC over `method + uri + body + timestamp`.
  - All comparisons use `hmac.compare_digest`. An unconfigured secret is rejected in production.
- **Idempotency key.** Taken from `Idempotency-Key` or `X-Idempotency-Key` if present, otherwise from the payload `uuid`/`event_id`/`id`, otherwise from a SHA-256 of the body. It is enforced by `UniqueConstraint(source, idempotency_key)`. Duplicates return 200 and increment `duplicate_count`.
- **Rejected deliveries.** A rejected (unsigned) delivery is never counted as "seen". Otherwise an attacker could send an unsigned copy first and block the real event.
- **Failure handling.** Failed processing moves the event to `failed`, and after 3 attempts to `dead_letter`. Operators can replay failed events.

Downstream, idempotency is layered: signals have dedupe keys, workflow runs have unique keys, tasks and notifications are keyed by run+step, and CRM writes are upserts.

**Production would add.** Acknowledge immediately and process on a queue (GTMOS currently processes inline within the request), handle proxy-aware URL reconstruction for HubSpot signatures, reject future timestamps, and set retention policies for raw payloads.

---

## 15. Workflow automation: trigger, condition, action, retries, dead letter

**What it is.** "When X happens, if Y is true, do Z", run by durable infrastructure rather than people remembering.

**Why it matters.** Most GTM leakage is operational: a signal nobody acted on, a product-qualified account (PQA) nobody routed. Automation that fails silently is worse than none.

**How GTMOS does it.**

- **Definitions** (`domain/workflows.py`). Workflows are validated data. They have a trigger (`signal.created`, `score.threshold_crossed`, `product.pql`, `account.created`, `manual`) with filters, conditions, and steps drawn from 10 actions (enrich, rescore, committee, research, draft outreach, route, task, lifecycle, sync CRM, notify).
- **Idempotency** (`services/workflow_engine.py`). `idempotency_key = wf:{key}:v{version}:{trigger}:{event_id}` is enforced by a unique constraint. A concurrent duplicate that loses the race hits `IntegrityError` and is discarded.
- **Persistence.** Each step is its own `WorkflowStepRun` with attempts, logs and output.
- **Retries.** `TransientError` triggers retries up to `max_attempts` with 2s/8s/32s backoff (the in-process sleep is capped at 2s for demos). Exhausting retries sends the run to **dead_letter**. Other exceptions fail the step permanently. `StepSkipped` is a success-like no-op.
- **Resume.** `retry_run` resumes at the failed step and skips steps that already succeeded.
- **Execution.** Runs execute inline, or on Redis/RQ after the transaction commits (`worker.py`). A sweeper re-enqueues runs stuck in `queued`, so Postgres stays the source of truth.

*Demo:* The Operations page shows 14 dead-lettered runs (for example "retries exhausted: 503 Service Unavailable from sync_crm (simulated)"). This run history is seeded (`synthetic_history: true`).

**Production would add.** A durable orchestrator (Temporal, or Inngest-style step functions), per-action rate limits, alerting on dead-letter growth, a visual editor, and workflow versioning with migration of in-flight runs.

---

## 16. Outbound metrics, and why opens are unreliable

**What it is.** The outbound funnel: sent → delivered → (opened) → replied → positive reply → meeting → opportunity → won.

**Why it matters.** Teams optimize whatever they measure. Since iOS 15 (2021), **Apple Mail Privacy Protection** pre-fetches remote images, including tracking pixels, through Apple proxies when mail arrives, so emails register as "opened" whether or not anyone read them. Corporate image proxies and security scanners inflate opens further. An open rate is mostly a measure of recipients' mail clients.

**How GTMOS does it.**

- **Outcome model.** The outbound model (`models/outbound.py`) stores all the events, but `email_opened` carries the caveat `"open tracking unreliable (Apple MPP)"`.
- **Analytics.** `services/analytics.py::overview` returns an `open_rate_caveat`.
- **Experiments.** Metrics are reply, positive reply, meeting and opportunity (`services/experiments_service.py::METRICS`).
- **Attribution.** Opens are excluded from touches (`services/attribution_service.py::TOUCH_TYPES`).

*Demo (90 days):* 4,103 sent, 1,685 opens (shown but not used), 217 replies, 134 positive, 87 meetings, 57 opportunities.

**Production would add.** Deliverability monitoring (bounce and spam rates against Gmail's 0.3% threshold, domain warm-up), reply classification, and meeting-booked integration from the calendar tool.

---

## 17. Experimentation

**What it is.** Randomized comparison of GTM treatments (messaging, channel, cadence) with honest statistics.

**Why it matters.** Outbound samples are small and noisy. Most "winning" subject lines are noise that someone declared a winner too early.

**How GTMOS does it.** `domain/experiments.py`:

- **Account-level randomization.** `bucket_for = sha256(salt:unit_id) mod 10,000`, split by variant weight. The same account always lands in the same variant, and no assignment table is needed to reproduce it. Randomizing at the account level means two people at one company never get competing messages, and it avoids contamination when they talk to each other.
- **Wilson score intervals** per variant. These behave better than the normal "Wald" interval at small n and rates near 0.
- **Two-proportion z-test** (pooled standard error), plus a **Newcombe interval** for the difference in rates.
- **Verdict.** `insufficient_sample` below the pre-registered minimum per arm, `insufficient_events` when an arm has fewer than 5 successes or failures (the normal approximation breaks down), `no_significant_difference` when p ≥ 0.05 or the difference CI includes 0, otherwise a winner. `required_sample_size` gives n for 80% power.

**Why not declare winners early.** Repeatedly checking a p-value and stopping at the first p < 0.05 ("peeking") inflates the false-positive rate well above 5%. Pre-registering the sample size and primary metric prevents that.

*Demo:* In "funding-vs-generic" (136 control, 155 treatment accounts, minimum 120 per arm), positive replies were 10.3% vs 21.9%: +11.6 pp, 95% CI +3.1 to +19.9 pp, p = 0.008. Meetings were 8.1% vs 12.9% (p = 0.18, CI crosses zero). Opportunities were 5.9% vs 5.8% (p = 0.98). The honest reading is that the treatment wins on the primary metric but has not been shown to create more pipeline. **The lift is built into the simulator** (`REPLY_MULTIPLIER` in `seed/generator.py`), so this result tests the statistics pipeline, not the messaging. The running "subject-question" test (32 vs 47 accounts, minimum 250) correctly returns `insufficient_sample`.

**Production would add.** Sequential testing or Bayesian beta-binomial for legitimate early stopping, CUPED-style variance reduction, holdout groups for incrementality, and guardrail metrics (unsubscribes, spam complaints).

---

## 18. Attribution

**What it is.** Distributing credit for pipeline across the touches that preceded it.

| Model | Rule | Bias |
|---|---|---|
| First touch | 100% to the first touch | Over-credits top-of-funnel (webinars, content, paid) |
| Last touch | 100% to the last touch before the opportunity | Over-credits bottom-of-funnel (SDR follow-ups, demo requests) |
| Linear | Equal split | Treats a newsletter open and a discovery call as equal |
| U-shaped | 40% first, 40% last, 20% spread across the middle | Arbitrary weights, under-credits nurture |

**Why it matters.** Budget follows attribution, and every model is biased. None of them is causal.

**How GTMOS does it.**

- **Models.** `domain/attribution.py` implements all four, using a 180-day lookback before the opportunity opened.
- **Unattributed pipeline.** Opportunities with no touches are reported as unattributed rather than credited to "direct".
- **Touches.** `services/attribution_service.py` builds touches at the account level, excludes opens, collapses same-day repeats, and lists its limitations in the API response.

*Demo:* The webinar "Evaluating LLM agents in production" gets $269k under first touch and $0 under last touch, which shows exactly how model choice drives the argument.

**Production would add.** Ad and offline touches, W-shaped or data-driven models, self-reported attribution ("how did you hear about us"), and incrementality tests through holdouts. For causal claims, GTMOS directs users to the experiments page.

---

## 19. Data quality

**What it is.** Keeping records accurate, complete, unique and consistent.

**Why it matters.** Everything downstream (routing, scoring, attribution, CRM sync) inherits bad data. Duplicates cause double outreach, and a missing domain makes enrichment and upsert impossible.

**How GTMOS does it.** `services/data_quality.py` defines 11 rules:

- duplicate contacts (normalized email, then same name on the same account)
- duplicate accounts (normalized domain, then normalized company name)
- missing domain
- invalid email
- missing employee count
- stale enrichment (older than 180 days)
- orphan contacts
- lifecycle/funnel conflicts
- high-fit accounts without an owner
- invalid pipeline transitions
- bad CRM external IDs

Each issue has a stable fingerprint. Re-scans update `last_seen`, and issues that are no longer detected auto-resolve. Remediations (merge contacts or accounts, route, suppress) are explicit, audited actions, so nothing changes silently.

*Demo:* 18 duplicate-contact groups, 6 duplicate-account groups, 81 invalid emails, 210 accounts with stale enrichment.

**Production would add.** Checks on ingest rather than only in batch, data contracts on upstream feeds, survivorship rules per field, and a CRM-side dedupe tool (Dedupely, or Salesforce duplicate rules).

---

## 20. Observability

**What it is.** Being able to answer "what happened, to which record, and why" for every automated action.

**Why it matters.** GTM automation touches revenue. When a rep asks why an account was reassigned, or why a sync failed, the answer has to be a lookup, not an investigation.

**How GTMOS does it.**

- **Correlation IDs** on requests, workflow runs, syncs and webhook events (`services/common.py`).
- **Audit log** (`AuditEvent`) with actor, before/after and reason, written by every mutating service.
- **Operations page** (`services/operations.py`): workflow failure rate and median duration, retried steps, dead-letter backlog, sync health, webhook failure rate, provider hit and error rates, routing latency.
- **Stack Inspector** (`services/stack_inspector.py`): a health report on the GTM system. Every status and recommendation cites the numbers it used.

**Production would add.** Structured logs shipped to Datadog or OTel traces, metrics with alerting and on-call runbooks, and SLOs (for example, "PQL routed within 1 business day").

---

## 21. PLG and product-qualified leads/accounts

**What it is.** Product-led growth means users adopt a free tier first. A PQL/PQA is a user or account whose product usage indicates buying intent, such as inviting teammates, connecting integrations or hitting usage limits.

**Why it matters.** Product usage is the strongest first-party signal available, but only if sales hears about it quickly and at the account level.

**How GTMOS does it.** `integrations/posthog.py` parses PostHog-shaped events (single, list or `{"batch": …}`). `services/product_events.py::ingest_events` runs event → account match (`$groups.company` beats email domain) → `Engagement` row (deduplicated on the PostHog `uuid`) → signal (`product_signup`, `teammate_invited`, `integration_activated`, `usage_threshold`; pricing views after 2 or more in 7 days) → rescore → the `product.pql` trigger when `usage_threshold` fires. The seeded "Product-qualified account → AE" workflow then rescores, routes, creates a "reach out within 1 business day" task, advances the lifecycle, notifies the owner and syncs to the CRM.

*Demo:* The Stack Inspector reports that 41 of 44 accounts that crossed the usage threshold in 60 days had no sales touch within 3 days. That is the leakage this workflow exists to close.

**Production would add.** Real PostHog/Segment destinations, user-to-account aggregation across workspaces, PQL definitions tuned by conversion analysis, and in-app plus sales-assist plays.
