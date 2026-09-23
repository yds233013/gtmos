# GTM Engineer Interview Questions, Answered Using GTMOS

Each answer has three parts: a **thesis** you can say in one breath, the **specifics** (what GTMOS actually does, with file references), and the **trade-offs** (what you would change in production, and what GTMOS does not do). Numbers marked *demo* come from the synthetic seed dataset. Use them to show the mechanics work, never as results.

Paths are relative to `apps/api/src/gtmos/` unless they start with `docs/`.

---

## Core system design

### 1. How would you design lead routing?

**Thesis.** Routing is a deterministic, explainable decision function: rules as data, explicit conflict resolution, ownership respected by default, fair distribution within pools, and a log entry for every decision.

**Specifics.**
- **Named accounts first.** An account flagged `is_named_account` keeps its owner and no territory rule can move it. Strategic accounts are assigned by agreement, and routing that silently reassigns one destroys trust in routing faster than any bug.
- **Rules** are `{field, op, value}` conditions in a small safe language (`domain/rules.py`, no `eval`). Each rule has a priority, a strategy (named user, least-loaded pool, or round robin) and an optional first-touch SLA.
- **Conflict resolution** (`domain/routing.py::_sort_key`): the lowest priority number wins, then the more specific rule (more conditions), then the rule key alphabetically. Losing rules are recorded with their reason, for example "lower priority (30 vs 20)".
- **Ownership.** An active owner is kept unless the winning rule has `overrides_existing_owner`. An inactive owner triggers reassignment. An inactive named assignee falls back to their team's pool.
- **Distribution.** Least-loaded by `load / capacity` where capacity differs; round robin where it does not. Round robin hashes the account id over a sorted pool instead of keeping a shared counter: a counter gives exact balance but needs a lock and sends the same account to a different rep depending on when it ran, while hashing is idempotent across a replay. When a whole pool is at capacity the account is still assigned and a capacity alert is raised, so it never gets dropped.
- **A fallback queue, not a shrug.** One rule is marked `is_fallback` and is evaluated last whatever its priority, so accounts no territory rule claims go to RevOps triage. `unmatched` now means only that no queue is configured — a gap in the rule set, and the explanation says so. *Demo:* the Stack Inspector traces 71 accounts in regions no active rule names, falling through to triage because the seed has no APAC rule.
- **Speed to lead.** Each rule carries an SLA (4h for a high-intent strategic account, 72h for triage) that becomes a due-by timestamp on the decision. The report measures against the first real outbound touch, counts only genuine lead events — a territory reshuffle assigns thousands at once and starts no clock — and separates *late* from *never touched*, because only one of those is a process problem. *Demo:* 655 assignments, 84% met, 98 late, 9 never touched, median 4.1 hours.
- **Logging.** Every decision is a `RoutingDecision` with matched rules, the conditions that passed or failed with their actual values, conflicts, the explanation, and latency from the triggering signal (`services/routing_service.py`). A simulator runs the same function without applying the result.

**Trade-offs.** Least-loaded adapts to uneven capacity but can starve a new rep unpredictably; round robin is fair but ignores load; I support both and pick per rule. Hash-based round robin trades exact balance for idempotency, which I would take in any system that retries. GTMOS still has no working hours or PTO, so an SLA can run overnight, and there is no escalation when one breaches — both are next. For inbound leads I would route to the account owner first (account-based routing) before applying territory rules.

### 2. How does an enrichment waterfall work?

**Thesis.** Ask providers in order, per field, until one returns a confident value. Record every attempt, and only let clearly better data overwrite existing data.

**Specifics** (`domain/enrichment.py::run_waterfall`).
- **Per-field order**, because the best source differs by field: `employee_count: [firmographics, apollo, webscan]`, `technologies: [webscan, apollo]` (`integrations/enrichment_providers.py`).
- **One call per provider per run.** Fields that need the same provider are batched, and the response is cached for later waterfall positions. Vendors charge per lookup.
- **Outcomes** are `hit`, `miss`, `low_confidence` (below 0.6, kept as a fallback), `error` (falls through to the next provider) and `skipped`. Each attempt stores latency and credit cost.
- **Merge policy** (`decide`): manual locks always win. An update needs at least 0.10 more confidence, or a stale existing value (older than 180 days) plus equal confidence. A provider that confirms the existing value raises its confidence.
- **Provenance** (`FieldProvenance`) records source, confidence, time and run for each field, so "where did 850 employees come from?" has a one-click answer.

**Trade-offs.** The three providers are simulated, with realistic coverage (70–82%), error rates (2–5%) and costs (0.5–1.0 credits). The Apollo adapter exists but has not been tested against the live API. In production I would add caching with TTLs, per-provider budgets and rate limits, email verification in the email waterfall, and report coverage per dollar by segment so the order can be tuned from data.

### 3. What happens when HubSpot and the warehouse disagree?

**Thesis.** Decide field ownership in advance. For each field, exactly one system is the source of truth. Conflicts are detected and logged, never silently resolved by "last write wins".

**Specifics.**
- GTMOS owns the computed `gtmos_*` properties (score, grade, tier, last signal, next best action). The reverse-ETL job overwrites them on change.
- Rep-owned fields (owner edits, notes, deal stage in the CRM) belong to the CRM.
- The inbound HubSpot webhook (`api/routes/integrations.py::webhook_hubspot`) verifies the v3 signature, stores the event and acknowledges it, but applies nothing ("GTMOS-owned gtmos_* properties are never overwritten"). A rep who manually edits `gtmos_icp_score` is overwritten on the next change, and the edit is visible in the event log.
- For enrichment fields, the provenance and manual-lock model (`FieldProvenance.is_manual_lock`) means a rep's correction beats any provider.
- Change detection compares against `ExternalRecord.last_payload_hash` for what GTMOS last pushed, not the live CRM value. A CRM-side edit to a `gtmos_*` field is therefore not re-pushed until the underlying value changes.

**Trade-offs.** That last point is a real gap. Production needs a **reconciliation job** that reads CRM values, diffs them against the desired state, and reports drift. It also needs an explicit policy per field (warehouse wins, CRM wins, or flag for review). With a real warehouse, dbt tests on the model plus Hightouch's sync logs would cover much of this.

### 4. How do you prevent duplicate CRM records?

**Thesis.** Prevention beats cleanup. Upsert on a stable unique key that you own, dedupe before syncing, and treat the domain as a matching hint rather than an identity.

**Specifics.**
- **Upsert key.** Companies upsert on the custom unique property `gtmos_account_id` (`hasUniqueValue: true`), not `domain` (`integrations/hubspot.py`). HubSpot does not enforce domain uniqueness, so batch upsert will not accept it as an `idProperty`. Domains also collide (subsidiaries, rebrands, shared parent domains).
- **Replays are safe.** Replaying a sync updates rather than creates, and deals follow the same pattern with `gtmos_opportunity_id`. Contacts use `email`, which HubSpot does dedupe.
- **Dedupe before sync.** `services/data_quality.py` finds duplicate contacts (normalized email, then same name on the same account) and duplicate accounts (normalized domain, then normalized name, only when domains do not conflict). It suggests merges into the oldest valid or highest-scored record and moves activities and roles to the survivor with an audit entry. *Demo:* 18 duplicate-contact groups. One is Kestrel's champion, whose duplicate record `" Priya.Raman@KESTREL-ANALYTICS.EXAMPLE"` shows up as a #2 champion candidate.
- **Bad external IDs** are their own data-quality rule, because a malformed ID makes the sync write to the wrong record.

**Trade-offs.** The first sync against a CRM that already has records needs a backfill: match existing companies by domain, write `gtmos_account_id` onto them, then switch to upsert. Skip this and you create a duplicate of every existing company. GTMOS has not implemented the backfill because it has never connected to a live portal.

### 5. How would you score accounts?

**Thesis.** Transparent points before black-box probabilities: a deterministic, versioned rules model where every point has a sentence and evidence, validated against outcomes, and eventually calibrated by a statistical model.

**Specifics** (`domain/scoring.py`).
- **Five categories** with ICP-configurable budgets: Fit 35, Intent 25, Timing 15, Technical 15, Engagement 10. Each is capped at its budget. Grades are A ≥ 72, B ≥ 58, C ≥ 45, then D, with **X** for exclusions (sanctioned country, excluded industry, below 25 employees, do-not-target domain).
- **Signals decay**: `confidence × relative strength × 0.5^(age/half-life)`. Repeat signals of the same type add only 25% each.
- **Pure function** with an `inputs_hash`, so scores are reproducible, diffable across ICP versions, and unit-tested (`tests/unit/test_scoring.py`).
- **Disqualifying signals subtract.** Six of the nineteen types (competitor adopted, layoffs, budget freeze, champion departed, unsubscribed, initiative cancelled) carry a penalty and the action it implies. Penalties apply *after* the category caps, because inside a category a maxed engagement score would absorb a champion's departure entirely — and the point of a negative signal is that it must be able to hurt. Only the strongest instance of a type counts: two reports of one layoff are one layoff.
- *Demo:* Kestrel scores 98/A. Its explanation reads like "14 open AI/ML roles, observed 6 days ago… 45-day half-life → 88% of 10 pts."
- **Bands are set from the distribution, not from round numbers.** The old 80/65/50 put a single account in grade A, because a 100-point score needs an account to max every category at once. The score's 99th percentile is 72, so the bands are 72/58/45 — roughly the top 1% and the next 10%, which is a day's list and a quarter's list.

**Evaluation** (`make backtest`, [`docs/scoring-evaluation.md`](scoring-evaluation.md)). This is the part I would want to be asked about:

- The score is split into a **structural** variant (fit + technical: firmographics known before anyone was contacted) and the **total** shown in the product, which includes engagement points awarded for replies and meetings — part of the outcome being predicted.
- On the demo data the total scores AUC 0.609 and the structural 0.544 with an interval of 0.494–0.595. **The honest number includes 0.5**: on this dataset the usable, non-leaking part of the score is not distinguishable from random, and the report leads with that rather than the flattering one.
- Both available estimates are biased in opposite directions. Measured on contacted accounts only, the score is graded on the list it selected, so range restriction pulls the AUC down. Measured across every account, the untouched majority counts as failures, which rewards the score for agreeing with the targeting it drove (0.578). The truth is between them.
- **The only unbiased design is a holdout**: contact a random sample regardless of score and compare conversion across bands. GTMOS does not run one, because it sends no email, and the report says that too.
- Grade ordering does hold on the full dataset — meetings A 38.5% > B 18.9% > C 11.8% > D 8.7% — but grade A has 13 contacted accounts and an interval of 17.7–64.5%, so B versus D is the only comparison that survives a confidence interval.

**Trade-offs.** Hand-set weights encode opinions, and I would rather ship opinions I can argue with than a model nobody can interrogate — on a new territory there is nothing to learn from anyway. With ~1,000 clean labelled outcomes and a point-in-time feature store I would fit a model and keep the rules as the explanation layer. The harness is deliberately model-agnostic: it takes (score, outcome) pairs, so the day the score becomes a prediction the same backtest grades it.

### 6. How would you detect buying signals?

**Thesis.** A signal is a timestamped, sourced, confidence-weighted fact tied to an account. Detection is ingestion plus resolution plus deduplication plus decay. The source matters less than that pipeline.

**Specifics.**
- **Catalog.** 13 types (`domain/signals.py`) across first-party (product events, pricing visits), third-party (funding, executive hires, AI hiring surges, job postings that name the problem, tech adoption, launches) and engagement. Each type has a half-life from 14 to 120 days.
- **Pipeline** (`services/signal_service.py`): validate → dedupe on `hash(type, domain, source_ref)` (unique in Postgres) → persist with evidence and source URL → rescore → emit `signal.created` to workflows.
- **Thresholding.** Some signals are thresholds, not events. Pricing views become a signal only at 2 or more in 7 days, and at most one per account-week (`services/product_events.py`).
- **Validation.** `analytics.signal_correlation` compares opportunity rates for accounts with and without each signal. *Demo:* pricing-page activity 14.1% vs 5.8% baseline. The endpoint states the caveat that signal-triggered campaigns also target these accounts.

**Trade-offs.** All third-party signals in the demo are synthetic. In production I would source funding from Crunchbase or news APIs, hiring from job boards, and executive moves from a people feed. I would also learn per-source confidence, because a press release and a scraped rumor should not carry the same weight.

### 7. How would you measure outbound experiments?

**Thesis.** Randomize at the account level, pre-register the primary metric and sample size, measure replies, meetings and pipeline rather than opens, and refuse to declare a winner until the data supports it.

**Specifics** (`domain/experiments.py`).
- **Assignment** is `sha256(salt:account_id) mod 10,000`: deterministic, reproducible, no assignment table needed. Account-level randomization stops two contacts at the same company from getting competing variants.
- **Statistics**: Wilson intervals per arm, a pooled two-proportion z-test, and a Newcombe interval for the difference.
- **Verdicts** refuse a winner below the pre-registered minimum sample, when any arm has fewer than 5 events, or when the difference CI includes zero.
- **Guardrail metrics** (bounce, unsubscribe, spam complaint, negative reply) are evaluated *one-sided, for harm*: a breach requires the treatment's Wilson lower bound to clear the ceiling, or the lower bound of the regression against control to clear the tolerance. An improving guardrail is only ever "ok". They are deliberately **not** gated on the primary metric's minimum sample, because evidence of harm should not have to wait for evidence of benefit.
- **A breach outranks a win.** The recommendation is `ship | do_not_ship | keep_running | no_change`, and a guardrail breach forces `do_not_ship` whatever the primary metric did.
- **Minimum detectable effect** is reported with every result, so a null is readable as "no effect at this sample size" rather than ambiguously. It is derived by inverting the same sample-size function used to plan the test, so the two can never disagree.
- *Demo:* `provocative-subject` (289 vs 311 accounts) lifts reply rate 21.8% → 40.5%, +18.7 pp, p < 0.001 — and the recommendation is **do not ship**, because unsubscribes go 0.35% → 2.25% (interval 1.09–4.57%, entirely above the 1% ceiling) and negative replies 3.1% → 11.3%. This is the example worth walking through: optimising reply rate alone is exactly how a team burns its sending domain.
- The running subject-line test correctly reports `insufficient_sample`. **All effects are simulated by construction** in `seed/generator.py`, so this validates the method, not the message.

**Trade-offs.** Fixed-horizon tests are slow at outbound volumes; sequential or Bayesian methods allow legitimate early looks. Guardrail ceilings are industry rules of thumb rather than fitted to this business. And a test that wins on replies but breaches a guardrail is only obviously wrong once the guardrail exists — the reason to build them before you need them.

### 8. What is reverse ETL?

**Thesis.** Moving modeled data from where it is computed (the warehouse) into the tools where people work (CRM, sequencer, ads). It is a model with a primary key, a match key, a sync mode, and change detection.

**Specifics** (`services/crm_sync.py`). GTMOS computes account intelligence and pushes `gtmos_icp_score`, `gtmos_intent_score`, `gtmos_score_grade`, `gtmos_account_tier`, `gtmos_last_signal(_at)` and `gtmos_next_best_action` to HubSpot companies. It hashes each payload and skips unchanged records, upserts changes in batches of 100 on `gtmos_account_id`, retries retryable failures for 3 rounds, and logs counts and errors per run. `preview_reverse_etl` is a dry run. All demo syncs are SIMULATED (`DemoHubSpotAdapter`).

**Trade-offs.** Hightouch and Census (now Fivetran Activations) do this generically over a warehouse, with mirror and delete modes, scheduling, many destinations and alerting. At a company with Snowflake and dbt, I would put the scoring output in a dbt model and let Hightouch sync it, rather than maintain a custom syncer. GTMOS shows the contract, not a replacement.

### 9. How would you debug falling pipeline?

**Thesis.** Decompose before you hypothesize. Break the change down by source, then check volume against conversion at each funnel step, then check for system failures, which masquerade as market changes.

**Specifics.**
1. **Decompose by source.** `analytics.period_comparison` splits opportunities created by source campaign, current vs previous period. *Demo, 28 days:* total pipeline actually rose ($1.99M vs $1.22M), but the funding-trigger campaign fell from $391k to $121k after it ended, and PLG fell $180k. Agent-launch outreach (+$804k) masked both.
2. **Volume vs conversion.** Did sends drop, or did reply → meeting → opportunity rates drop? The funnel and breakdown endpoints answer this by segment, region, persona and grade.
3. **Plumbing.** Look for routing gaps (71 accounts in uncovered territories), PQL leakage (41 of 44 PQAs untouched within 3 days), dead-lettered workflows (14), failed syncs, and stale enrichment that drops accounts out of the ICP.
4. **Data artifacts.** Invalid stage transitions and lifecycle conflicts distort funnel metrics.

The Copilot routes "Why did pipeline fall?" to exactly these approved analyses (`services/copilot.py`, the `pipeline_change` intent). No LLM writes SQL.

**Trade-offs.** Seasonality, sales-cycle lag (this month's opportunities come from last quarter's activity), and a small n per campaign all mean week-over-week changes are often noise. I would show confidence bands before anyone reorganizes a team.

### 10. How do you make GTM automation idempotent?

**Thesis.** Put idempotency at every layer. Dedupe inbound events, give every run a natural key, key every side effect, and make external writes upserts. Enforce it with database constraints, not application checks alone.

**Specifics.**
- **Webhooks**: an idempotency key from the header, then the payload ID, then a body hash, enforced by `UniqueConstraint(source, idempotency_key)` (`services/webhook_service.py`). Unsigned deliveries never count as seen, which prevents pre-emption attacks.
- **Signals**: `UniqueConstraint(workspace_id, dedupe_key)`.
- **Workflow runs**: `wf:{key}:v{version}:{trigger}:{event_id}` is unique, and a race loser hits `IntegrityError` and is dropped (`services/workflow_engine.py::create_run`).
- **Side effects**: tasks are keyed `task:{run}:{subject}` and notifications `notify:{run}`. Drafts are reused if the run already created them.
- **CRM writes**: upserts on a unique property, plus payload-hash skipping.
- **Retries** resume at the failed step and never re-run succeeded steps.

**Trade-offs.** Two gaps. First, a webhook whose processing failed is still counted as seen, so the sender's own retry returns "duplicate" and only an operator replay reprocesses it. Second, in-request processing means a slow processor could exceed HubSpot's 5-second acknowledgment window. Production should acknowledge fast, queue the work, and let sender retries of failed events reprocess them.

### 11. What should be deterministic vs LLM-powered?

**Thesis.** Anything that routes money, changes ownership or gets reported must be deterministic and testable. LLMs handle language: summarizing evidence, drafting wording and parsing questions, always as reviewable drafts tied to evidence.

**Specifics** (`docs/product-spec.md` §4).
- **Deterministic:** scoring, routing, workflow conditions, experiment assignment and statistics, attribution, data quality, analytics, and Copilot queries.
- **LLM-assisted:** research narrative (`integrations/llm.py`, opt-in via `LLM_ENABLED`) and message wording.
- **Controls on the LLM path:** it uses structured output with required citations, passes through the same `validate_sections` as the deterministic generator, and falls back to deterministic output if the provider fails or refuses.
- **Copilot:** maps a question onto a closed set of intents with whitelisted parameters, and the answer is rendered from computed numbers.

**Trade-offs.** Rules are brittle at the edges. Title regexes miss "Head of Intelligence Engineering", for example. A good middle ground is an LLM **classifier** whose output feeds a deterministic rule, logged with confidence and a human override, rather than an LLM that makes the decision.

### 12. How would this architecture change at 10x scale?

**Thesis.** The domain layer stays and the plumbing changes: batch becomes streaming, the app database gives way to a warehouse, inline execution moves to durable queues, and one process becomes several workers with rate limits.

**Specifics.**
- **Data.** 20k accounts and 120k contacts fit in Postgres today. At 10x, events and activities belong in a warehouse (Snowflake or BigQuery), with dbt models for scores and metrics and Hightouch for activation.
- **Execution.** Rescoring already chunks by 500 (`services/scoring_service.py`). At scale it should be incremental, rescoring only accounts with new signals, plus a nightly full pass for decay.
- **Workflows** move to Temporal or a similar durable orchestrator, with per-action concurrency limits.
- **Webhooks** get acknowledged at the edge, put on a queue (SQS or Kafka) and processed by workers.
- **CRM sync** needs a token-bucket limiter shared across workers, keyed to HubSpot's 100–190 requests per 10 seconds per app, plus daily-limit budgeting.
- **Multi-tenant auth** means SSO/RBAC instead of the single operator identity (`api/deps.py`).

**Trade-offs.** Most of the pure functions (`domain/*.py`) are unchanged by any of this. That is why they are pure: scale changes where they run, not what they compute.

---

## Integrations and reliability

### 13. How do you secure webhooks?

**Thesis.** Authenticate every delivery, with a signature over the raw body plus a timestamp. Compare in constant time, bound the replay window, and fail closed in production.

**Specifics** (`integrations/signatures.py`).
- **GTMOS scheme:** `HMAC-SHA256(secret, "{timestamp}.{raw_body}")`, rejected if the timestamp is outside ±5 minutes.
- **HubSpot v3:** base64 HMAC over `method + uri + body + timestamp`, with a 5-minute window.
- **Shared-token header** for PostHog, which cannot compute HMACs.
- **Constant-time comparison** with `hmac.compare_digest` everywhere.
- **Fail closed:** a missing secret is rejected in production (`webhook_service.receive`).
- **Size limit:** bodies over 1 MB return 413.
- **Rejected events** are stored (for forensics) but never count as seen.

**Trade-offs.** The HubSpot verifier checks only "too old", not future timestamps. It also signs `str(request.url)`, which behind a TLS-terminating proxy may not match the URL HubSpot signed, so production needs proxy-aware URL reconstruction. Tokens are weaker than HMACs because they can be replayed if leaked, so I would put PostHog behind an allowlist or a relay that signs.

### 14. How do you handle API rate limits?

**Thesis.** Batch to reduce calls, back off on 429s using the server's hints, separate retryable from permanent errors, and budget centrally when many workers share one quota.

**Specifics.**
- **Batching.** Batches of up to 100 (`integrations/hubspot.py::BATCH_LIMIT`).
- **`RealHubSpotAdapter._post`** retries 429 and 5xx up to 4 times, honors `Retry-After`, and otherwise uses exponential backoff capped at 30s.
- **Error classes.** Results come back as retryable or permanent. The sync retries only retryable records, for up to 3 rounds (`services/crm_sync.py`).
- **Reduced load.** Payload hashing removes unchanged records before any call.
- **The demo adapter** injects deterministic simulated 429s (about 3% of records on first attempt), so the retry path is exercised in every demo sync.
- **Enrichment** calls each provider once per run.

**Trade-offs.** The retry logic is per-process, and the real adapter is untested against live HubSpot. Production needs a shared limiter (a Redis token bucket), reading of the `X-HubSpot-RateLimit-*` headers to slow down before hitting 429, and daily quota tracking.

### 15. How do you do lead-to-account matching?

**Thesis.** Use the strongest identifier first, never match on free-mail domains, record confidence, and keep unmatched records rather than dropping them.

**Specifics** (`domain/matching.py::match_to_account`).
- **Priority:** explicit company group key (PostHog `$groups.company`, 0.98), then exact email domain (0.9), then a parent domain for subdomains (0.8).
- **Free mail:** 19 free-mail domains are blocked ("gmail.com is not a company").
- **Normalization** strips protocol, `www.`, path, port and case.
- **Unmatched events** are stored as `Engagement` rows without an account, and the Stack Inspector counts them.

**Trade-offs.** No fuzzy name matching, no reverse-IP, and no precision/recall fixture set yet. The market research lists those as the next steps (`docs/market-research.md` §7, G4). I would also add a review queue for matches below 0.8.

### 16. How do you handle a CRM migration (for example Salesforce to HubSpot)?

**Thesis.** Treat it as a data project with an identity map at the center: freeze the schema, map objects and fields, carry stable external IDs, dry-run and reconcile, then cut over with a rollback plan.

**Specifics, and how GTMOS helps.** `ExternalRecord` is already an identity map (internal ID, then provider, object type and external ID, plus last payload hash). The same pattern carries Salesforce IDs as a custom property on HubSpot records, which makes reloads idempotent. Object mapping requires thought: Salesforce Leads have no HubSpot equivalent (a person is always a Contact, and qualification lives in `lifecyclestage`, see `docs/market-research.md`). The dry-run preview pattern (`preview_reverse_etl`) and the data-quality rules (duplicates, bad external IDs, lifecycle conflicts) are what I would run before and after each load.

**Trade-offs.** GTMOS has not done a migration. The hard parts are organizational: rebuilding reports, retraining reps, and deciding which history (activities, emails) is worth moving.

### 17. What is a data contract, and where would you use one?

**Thesis.** A data contract is an explicit, versioned agreement on a feed's schema and semantics, enforced at the boundary so bad data fails loudly instead of corrupting scores quietly.

**Specifics.** GTMOS enforces contracts at every entry point with Pydantic:
- `PostHogEvent`: event name length, typed timestamp.
- `SignalIn`: known signal type, confidence and strength within [0, 1] (`services/signal_service.py` raises `InvalidSignal`).
- `ICPDefinition`: weights sum to 100.
- `WorkflowDefinition`: known actions, unique step keys.

Future-dated signals are ignored rather than trusted. Invalid webhook payloads become `failed` events with the validation error attached, not partial writes.

**Trade-offs.** These are code-level contracts, not shared, published contracts with owners. In production I would publish schemas (JSON Schema or protobuf), version them, add dbt tests on warehouse models, and alert the producing team when a contract breaks.

---

## AI quality and safety

### 18. How do you prevent AI hallucinations in research and outreach?

**Thesis.** Constrain the input, require citations, validate the output mechanically, and keep a human in the loop. Never rely on a prompt alone.

**Specifics.**
1. **Closed evidence.** The model sees only the numbered evidence pack E1…En built from records GTMOS holds (`domain/research.py::build_evidence_pack`).
2. **Structured output** with a required `evidence` list per claim, and `hypothesis=true` for inferences (`integrations/llm.py::ResearchOut`).
3. **Validation.** `validate_sections` removes claims with no valid citation and lists them as unsupported, whichever generator wrote them.
4. **Outreach guardrails** (`domain/personalization.py::run_guardrails`) block on any number not present in the evidence, banned claim patterns ("guarantee", "10x", "customers like"), stale or low-confidence anchor signals, and unreachable contacts. Proof can come only from an approved library.
5. **Approval.** Blocking failures prevent approval, and edits are re-checked (`services/outreach_service.py::edit_draft`).

**Trade-offs.** Citation checking proves a claim *cites* evidence, not that the evidence *supports* it. The next layer is an entailment check (a second model or an NLI classifier) on each claim–evidence pair, sampled against human review. The numbers guardrail is also lexical: "$120M" matches "120M" in the evidence, but a paraphrase such as "over a hundred million" would pass. There are small implementation gaps too. When one contact holds two committee roles, the evidence pack lists them twice.

### 19. How would you measure AI personalization quality?

**Thesis.** Measure at three levels: offline quality (does the draft meet the rubric?), human acceptance (do reps approve it unedited?), and business outcome (does it beat a control in a randomized test?).

**Specifics.**
- **Offline.** Guardrail pass rates are already stored per draft (`MessageDraft.guardrails`). A golden set of accounts with rubric-scored reference drafts would catch regressions when a prompt changes. `PROMPT_VERSION = "research-v3"` is recorded for exactly that reason.
- **Human.** Approval rate, edit distance between draft and approved version (`MessageDraft.version` increments on edit, and the audit log stores before and after), and rejection reasons.
- **Outcome.** The experiment framework compares positive replies and meetings, randomized at the account level. The funding-trigger test is the template.

**Trade-offs.** GTMOS stores the raw material but has no eval harness yet. Outcome metrics lag and are noisy at outbound volumes, so offline evals are needed to iterate quickly, and experiments are needed to confirm results.

---

## Business and organizational

### 20. How would you route PLG signups and PQLs?

**Thesis.** Resolve the user to the account, use account-level usage to decide whether sales should get involved, and route to the existing account owner before anything else. Speed matters.

**Specifics.** A PostHog event is matched to an account (`$groups.company` before email domain), stored as an engagement, and becomes a signal. `usage_threshold` emits `product.pql` (`services/product_events.py`). The "Product-qualified account → AE" workflow rescores, routes (the existing owner is kept), creates a "reach out within 1 business day" task, advances the lifecycle to engaged, notifies the owner and syncs to the CRM (`domain/workflows.py::DEFAULT_WORKFLOWS`). Conditions restrict it to strategic, enterprise and mid-market segments, and SMB stays self-serve. *Demo:* 41 of 44 PQAs had no sales touch within 3 days, which is the gap this workflow closes.

**Trade-offs.** The PQL definition should come from conversion data (which usage behaviors predict paid conversion), not intuition. Too aggressive, and sales interrupts happy self-serve users.

### 21. First-touch vs last-touch: how do you settle attribution debates?

**Thesis.** You do not settle them with a model. Show every model side by side so the disagreement is visible, report unattributed pipeline honestly, and use experiments or holdouts for causal questions.

**Specifics.** `domain/attribution.py` runs first, last, linear and U-shaped (40/20/40) models over a 180-day lookback. `services/attribution_service.py` lists its own limitations: account-level touches only, no offline or ad touches, opens excluded, not causal. *Demo:* the webinar gets $269k first-touch and $0 last-touch. Marketing and sales can both be "right" about the same deal.

**Trade-offs.** The demo shows 0% unattributed, which is an artifact of synthetic data. Real CRMs have large gaps. Self-reported attribution and incrementality tests (holding out a region or segment from a campaign) answer the question the models cannot.

### 22. How do you get buy-in from sales for new GTM tooling?

**Thesis.** Put it in their existing workflow, make every output explainable, give them override power, and prove value on a small scope before expanding.

**Specifics, with GTMOS design choices that serve buy-in.**
- **In the CRM.** Scores and next best actions arrive in HubSpot fields reps already see (reverse ETL), not in a new tool.
- **Explainable.** Every score point, routing decision and research claim explains itself.
- **Overridable.** Manual committee overrides always win, manual field locks beat enrichment, and existing ownership is respected by default.
- **Drafts, not sends.** Nothing is sent without approval, so reps keep control of their voice and reputation.
- **Proof.** Pilot with one team, measure against a control, and share the result along with its confidence interval.

**Trade-offs.** Too many "helpful" alerts and tasks become noise. I would cap automated tasks per rep per day and review which ones get completed.

### 23. What would you build first at a new company?

**Thesis.** Measurement and plumbing before AI: clean account data (dedupe and domains), an agreed ICP and score that reps trust, routing that never drops a lead, and pipeline reporting that ties back to source.

**Specifics.** In GTMOS terms, the order is data quality → scoring → routing → reverse ETL → signals and workflows → research and personalization → experiments. The Stack Inspector encodes this prioritization: it ranks recommendations by the number of high-value accounts affected (*demo:* acting on fresh signals affects 42 A/B accounts, PQL routing 41, and the enrichment backlog 296).

**Trade-offs.** Some teams need a quick visible win to earn trust. A signal-to-draft workflow for the top 50 accounts can be that win while the plumbing work continues.

### 24. What does "next best action" mean, and how would you compute it?

**Thesis.** It is the single most valuable thing a rep should do on an account now, computed from state by ordered rules so it can be explained and trusted.

**Specifics.** `services/next_action.py::decide` checks conditions in priority order:
1. Customer → expansion review.
2. Excluded → do not target.
3. Unowned A/B account → route.
4. Pending drafts → approve.
5. Open opportunity with no activity for 14+ days → re-engage. Open opportunity with an economic buyer identified → multi-thread.
6. Missing firmographics → enrich.
7. High fit plus intent → signal-based outreach to the named champion.
8. Otherwise nurture or monitor.

The result syncs to `gtmos_next_best_action`. *Demo:* Kestrel's is "Multi-thread to the economic buyer".

**Trade-offs.** Ordered rules cannot trade off several good options against each other. With outcome data you could rank actions by expected value, but keep the reason string.

### 25. Two enrichment providers disagree. What do you do?

**Thesis.** Do not resolve it silently. Confidence is a provider's opinion of itself, and letting the marginally more self-assured source overwrite a stored value is how a CRM fills up with confident nonsense.

**Specifics** (`domain/enrichment.py`).
- **The second opinion is usually free.** A waterfall stops asking as soon as one provider answers confidently, so it looks like there is no second opinion — but a provider call returns every field it supports and GTMOS caches the whole response for the run. When a later position calls another provider for some *other* field, that response normally carries an unsolicited answer on fields already resolved. Those were being discarded; now they are compared.
- **Only differences worth acting on count.** Casing, legal suffixes, numbers within 15%, and one provider seeing more of a tech stack than another are not disagreement. A flag that fires on noise is a flag nobody reads.
- **Materiality follows consequence, not confidence.** A dissent counts if the dissenting provider is confident (≥ 0.6) *or* the numbers differ by more than 50% — a gap that size moves an account between segments, and therefore changes scoring and routing, whatever the source thinks of itself.
- **A contested field keeps its value.** When two sources materially contradict each other about a field that already holds a value, the decision becomes `conflict`: the stored value stays and a data-quality issue is raised with a suggested fix. An empty field is still filled — a value beats no value — but the rejected answer is recorded alongside it and shown under the field on the account page.
- *Demo:* 18 material conflicts. The Stack Inspector traces 8 of them to accounts where the rejected value would have changed the segment band or the ICP industry tier — meaning the owner and the grade were decided by a coin flip nobody saw.

**Trade-offs.** This costs an extra field on `field_provenance` and a rule that can be noisy if the materiality thresholds are wrong. The alternative — survivorship rules per field producing a golden record — is the production answer, and needs a stated precedence order per field rather than a generic confidence comparison.

### 26. How do you stop an automated GTM system that is doing damage?

**Thesis.** With a button an operator can press, not a config change and a deploy. The person who notices a bad sequence sending is rarely the person who can ship.

**Specifics** (`services/governance.py`).
- **Three switches, not one**, because the reasons differ: automation (a rule is misbehaving), outbound (a message or list is wrong), CRM writes (sync is corrupting records). `pause_all` is the single stop button for when the reason is not yet known.
- **Read from the database on every action.** A cached flag would mean a pause takes effect whenever the cache happens to expire, which is the one property a kill switch cannot have.
- **Pausing is not cancelling.** A run queued before the pause stays queued and resumes where it stopped; nothing is failed or discarded.
- **Blocked requests return `423 Locked`** with the operator's reason, so whoever hits it learns why. A `403` would imply they lack permission, which is not the case.
- **Enforced where the action happens**, not at the edge: before a run row is created, before a draft can be approved, before the CRM adapter opens a connection. A UI-only switch is theatre.
- Every change is audited with who, why and when, because that is the first question after an incident.

**Trade-offs.** Three switches is a judgement call — more would be finer-grained but slower to reason about under pressure. There is no scheduled or automatic trip (for example, pause outbound when the bounce rate crosses a threshold), which is the obvious next step and the one that would make the deliverability model actionable rather than advisory.

### 27. How do you tell a real causal chain from three unrelated numbers?

**Thesis.** Intersect the account sets. "35 accounts missing employee count" and "90 unmatched routing decisions" are both true and can share almost no accounts; quoting them next to each other implies a chain the data does not support.

**Specifics** (`services/stack_inspector.py`).
- Every link **intersects** the running set, so a step can never count an account the previous step did not contain, and the reported number at each link is the survivors.
- A chain with **no survivors is not shown at all**. Rendering it with zeros would read as "this happens, rarely" when the honest answer is "this does not happen here".
- The mechanism is **shown, not asserted**: the size chain reports that 5 of 6 active rules test `account.segment`, and that the only segment-less accounts ever assigned were matched by the one rule that does not — so the dependency is visible rather than claimed.
- Each chain states **what it does not prove**, and the size chain reports how much of the bigger number it explains rather than implying all of it.
- Three candidate chains were **dropped** because the data did not support them: invalid email → bounce (0 of 30 bounces hit currently-invalid contacts), bounce → re-send, and duplicate account → attribution error.

**Trade-offs.** Intersection is conservative: a real mechanism that operates through a different path shows as a weak chain. And several of these are still correlational — a region's unowned rate correlating with having no rule is not proof — so each chain carries an explicit confidence basis of "mechanism" or "correlation".
