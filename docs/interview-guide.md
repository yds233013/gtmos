# Presenting GTMOS in a GTM Engineer Interview

This guide covers how to talk about GTMOS: what to say in 30 seconds, 2 minutes and 10 minutes, which decisions to defend, how to handle pushback, and what never to overclaim. Pair it with `docs/demo-script.md` (the click path), `docs/interview-questions.md` (deep answers) and `docs/gtm-concepts.md` (the concepts).

---

## 1. The 30-second pitch

> "GTMOS is the system a GTM engineer builds so sales knows who to call, why now and what to say, and so RevOps can see whether the machine is working. It takes an account from enrichment through signals, an explainable score, the buying committee, evidence-cited research and guard-railed outreach drafts, then routing and a CRM upsert. Everything that moves money (scoring, routing, experiments, attribution) is deterministic and unit-tested. AI is used only for language, only over cited evidence, and a human approves every draft. It's a portfolio project on synthetic data with simulated integrations, built the way I'd build it for production."

Say the last sentence every time. It costs nothing and buys trust.

---

## 2. The 2-minute walkthrough

Use this when there is no screen share, or as the opening of a longer demo.

1. **The problem (15 s).** GTM stacks leak in the gaps between tools: a funding signal nobody acts on, a product-qualified account routed to nobody, a score reps don't trust, duplicate CRM records.
2. **The loop (30 s).** Target → enrich (a per-field waterfall with provenance) → detect signals (19 types, time-decayed) → score (Fit/Intent/Timing/Technical/Engagement, where every point has a sentence) → buying committee → research (claims must cite evidence E1…En) → personalized draft (signal → pain → value → proof → CTA, with guardrails) → approval → route → reverse ETL to HubSpot.
3. **The infrastructure (40 s).**
   - Workflows are trigger → conditions → actions with an idempotency key per event, persisted step runs, retries with backoff, and a dead letter queue.
   - Webhooks are HMAC-verified and deduplicated.
   - The CRM upsert keys on a custom unique property, not domain.
   - Experiments randomize at the account level and refuse to declare winners early.
4. **The stack around it (15 s).** PostHog observes the product, Clay buys commodity enrichment, n8n glues systems together, HubSpot is where the revenue team works, and GTMOS owns the judgement. "Buy the commodity, orchestrate the plumbing, own the judgement" (`docs/phase3-architecture.md`).
5. **Self-audit (10 s).** A Stack Inspector computes the health of the GTM system itself (sync failures, routing gaps, PQL leakage, data quality), and every number cites its query. A Copilot answers questions by mapping them to approved analyses, never generated SQL.
6. **Honesty (10 s).** Synthetic data. n8n is verified by execution; the Clay, HubSpot and PostHog adapters are built against documented contracts and have never seen a live account.

---

## 3. The 10-minute demo path

Follow `docs/demo-script.md`. Run `make reset` beforehand so the data matches the script. Below is what each beat should *prove*, which is what the interviewer is actually evaluating.

| Beat | What to show | What it proves |
|---|---|---|
| Kestrel Analytics | 98/A, owner Sam Okoro, stage Opportunity | A flagship account that exercises every feature |
| Why the score | Fit 35/35, Intent 25/25 (capped), Timing 13/15, Technical 15/15, Engagement 10/10. Read one line aloud: "14 open AI/ML roles, observed 6 days ago… 45-day half-life → 88% of 10 pts" | Explainable, reproducible scoring (`domain/scoring.py`, input hash) |
| Signals | $120M Series C (12 days), Kestrel Copilot launch, new VP of AI, LLM-eval job posting, the free workspace reaching the usage threshold | Signal taxonomy, decay, first- and third-party data |
| Buying committee | Priya Raman champion, Elena Park economic buyer, Dana Whitfield sponsor; overrides survive recompute | Rules with reasons, human override wins |
| Research | Evidence chips on every sentence; pains tagged **Hypothesis** | Grounding and citation validation (`validate_sections`) |
| Outreach draft | The email goes to **Elena**, referencing Priya: "I've been working with Priya on agent reliability…" | Multi-threading, because an open opportunity changes the recipient order (`pick_recipient`) |
| Approval queue | Edit in "we cut incidents by 73%" and Approve is blocked (`numbers_grounded`) | Guardrails are enforced, not advisory |
| Workflow run detail | Step timeline, attempts, idempotency key, a dead-letter run | Durable, idempotent, retryable automation |
| Routing simulator | Senior AE rule beats the territory rule ("lower priority (30 vs 20)"); APAC → no rule matched | Conflict resolution, and the system finding its own gap |
| Experiment | Positive replies +11.6 pp (CI +3.1 to +19.9, p = 0.008); meetings and opportunities **not significant** | Statistical discipline |
| Data quality | Merge a duplicate-contact group (audited) | Fingerprinted issues, explicit remediation |
| Stack Inspector | Eight systems, ranked recommendations with evidence | Operating the GTM system, not just building it |
| Copilot | "Why did pipeline fall?" → *How this was computed* | Closed-intent analytics, no LLM SQL |
| Operations | Failure rates, dead letters, SIMULATED syncs, provider health, correlation IDs | Observability |

**If there is a terminal instead of a browser**, run the golden flow. It is the same story in 20 lines:

```bash
make golden-flow             # one account through every boundary, direct to the API
make golden-flow VIA_N8N=1   # the three product events routed through the real n8n container
```

Three people at one company produce PostHog-shaped events → GTMOS resolves them to an account by `$groups.company` → the PQL rule fires → a signal moves the score → a workflow runs → routing picks an owner → reverse ETL pushes the company and associates its contacts → the CRM sends a change webhook back → **the same delivery is sent twice and the second is deduplicated** → analytics, operations and the audit log all reflect it (`apps/api/src/gtmos/goldenflow/__main__.py`). Every id is derived from a fixed run key, so it is replayable.

Two beats are worth calling out while it runs. Step 16 posts the identical HubSpot event with `attemptNumber: 3` and fails the run unless the response says `duplicate: true` — that is a real bug this project found and fixed, and the assertion exists so it cannot come back. And `VIA_N8N=1` posts to `http://localhost:5678/webhook/gtmos-posthog`, which is the exact URL a PostHog destination would target, so the n8n leg is exercised rather than described.

**Two things to know before you present.**
- In the current demo data, total 28-day pipeline actually *rose* ($1.99M vs $1.22M), while the funding-trigger campaign fell from $391k to $121k after it ended. If you ask the Copilot "why did pipeline fall?", say the decomposition shows it: "total is up, but the funding campaign fell, and a new campaign masked it." That is a better story than a simple drop.
- Workflow run history and dead letters are **seeded** (`synthetic_history: true`, with retry disabled for those runs). Only the run you trigger live during the demo is a real execution.

---

## 4. Architectural decisions to highlight, and how to defend them

**Pure domain layer, thin services.** Every decision (score, route, waterfall merge, committee, guardrails, statistics, attribution) is a pure function in `domain/*.py` with no I/O, which makes it unit-testable (82 test functions across `apps/api/tests/`). *Defense:* "When a rep asks why an account moved, I can replay the exact inputs. When we change the ICP, I can diff scores before shipping."

**Deterministic where money moves, LLM only for language.** *Defense:* "An LLM that routes accounts or sets a CRM field can't be unit-tested, can't be audited, and changes with the model version. I use the LLM where it's strong, drafting over evidence, and a validator throws out anything it can't cite."

**Upsert on `gtmos_account_id`, not domain.** *Defense:* "HubSpot doesn't enforce domain uniqueness, so batch upsert can't use it as an idProperty. Domains also aren't identities: subsidiaries and rebrands break them. A key I own makes every write idempotent."

**Idempotency enforced by database constraints.** Workflow runs, webhooks, signals and activities all have unique keys, and a race loser gets an `IntegrityError` and is dropped. *Defense:* "Application checks alone race. The constraint is the guarantee."

**Postgres as source of truth, Redis only for delivery.** Runs are written in the transaction and enqueued after commit, and a sweeper recovers anything stranded (`worker.py`). *Defense:* "If Redis dies, nothing is lost. Work is just delayed."

**Human approval before anything leaves.** DRAFT → REVIEW → APPROVED → READY. There is no send capability. *Defense:* "Sender reputation and brand are not things to automate away. READY is the hand-off to a sequencer."

**Account-level experiment randomization.** *Defense:* "Two people at one company comparing notes is contamination. The account is the unit of purchase, so it's the unit of randomization."

**Buy the commodity, orchestrate the plumbing, own the judgement.** The single most important decision in Phase 3, and the one to lead with if the interviewer is senior. GTMOS buys PostHog (capture at volume), Clay (the provider network, not the waterfall), n8n (a canvas RevOps can edit) and HubSpot (where reps work), and builds only what someone would want to argue with: the ICP, the score and its explanation, signal decay, identity resolution, the PQL rule, routing policy, workflow semantics, guardrails and the kill switches. *Defense:* "The test is whether a reasonable GTM leader would want to argue with it. If yes, it has to be explainable, versioned and diffable, so it belongs in code I own — not in a vendor's black box or on a workflow canvas. The GTMOS engine runs GTM semantics; n8n moves bytes. A scoring change should be reviewable in a diff; a Slack notification shouldn't need one." Have `docs/phase3-architecture.md` open — the diagram colour-codes bought versus built.

---

## 5. Likely pushback and how to answer it

**"Isn't this just a CRM?"**
"No. The CRM is where reps work, and GTMOS pushes into it. GTMOS is the logic layer a CRM doesn't have: enrichment waterfalls with provenance, signal decay, explainable scoring, evidence-grounded research, idempotent workflow execution, and self-auditing. It has a mini CRM model only so the loop is demonstrable end to end. In a real deployment, HubSpot or Salesforce stays the system of record for rep-owned data."

**"Why build instead of buying Clay or using HubSpot workflows?"**
"In most companies you should buy a lot of this, and the architecture says so explicitly. Clay's value is the provider network, not the waterfall — I can write a waterfall in an afternoon, I can't negotiate forty data contracts in one. What I keep is the merge policy: manual locks win, a material disagreement is a conflict rather than an overwrite, and every field carries provenance. Same shape everywhere: I buy the commodity, orchestrate the plumbing in n8n, and own the judgement. I built the mechanics of the bought pieces once, over simulated providers, so I can configure the real ones correctly and debug them when they break."

**"The data is fake. So what?"**
"Right, and it's labeled DEMO everywhere. The point isn't the numbers, it's the mechanics: the same functions would run on real data. The synthetic data isn't random noise either. It's generated from a latent propensity model, so there are real patterns to find (higher grades convert better, an APAC routing gap, PQL leakage). One caveat I always state: the experiment lift was built into the simulator, so it shows the statistics work, not that the message works."

**"Did you test the integrations?"**
Do not answer this with one word. There are four integrations at three different levels of proof, and knowing which is which is the answer:

| Integration | Level | What that means |
|---|---|---|
| **n8n** | **Verified by execution** | Runs in Docker pinned to 2.40.5, reaches the API at `host.docker.internal:8010`, and `make golden-flow VIA_N8N=1` routes real product events through it |
| **PostHog** | Contract implemented, **shape replayed locally** | Parsing, `$groups` matching, dedupe, the PQL rule and rescoring are tested and run end to end. No PostHog project exists; the destination config in `docs/posthog-live-setup.md` §4 has never been created |
| **HubSpot** | Adapter built, **never run live** | `DemoHubSpotAdapter` is exercised on every sync including simulated 429 retries. `RealHubSpotAdapter` follows the documented batch-upsert API and has no portal behind it. First step is `ensure_properties` and a 10-record batch (`docs/hubspot-live-setup.md`) |
| **Clay** | Contract tested, **no account exists** | Signature verification, column mapping, partial rows, idempotency and 402/429 backoff tested under `httpx.MockTransport`. No request has ever been made to `clay.com` |

Then name the open question in each: whether PostHog's HTTP Webhook destination is plan-gated (`free: false` in source, unstated in the docs), whether HubSpot private-app webhooks exist in a developer test account, and whether Clay emits per-cell confidence at all. Each live-setup doc ends with a section listing exactly this.

**"Doesn't PostHog give you all of that for free?"**
"No, and the pricing is the part people discover after they've built. Group analytics — attributing an event to a company rather than a user, which is the entire point for B2B — is a paid add-on enabled from the billing page. The first million events a month cost $0, but it needs a card, and once it's on, the meter counts *all* identified events in the project, not just the ones carrying `$groups`. Self-hosting doesn't rescue you either: group analytics and data pipelines are the two features PostHog names as absent from self-hosted, so a local instance can't do either thing the integration needs. It's in `docs/research/posthog.md` with the verbatim quotes."

**"How do you know the score is any good?"**
"The score-validation view shows meeting rate by grade among contacted accounts: B 18.9%, C 15.5%, D 6.2% in the demo. It's biased, because engagement is part of the score, and the UI says so. The honest next step is a holdout backtest on closed-won deals, then fitting the weights."

**"What would you do differently?"**
Pick two: acknowledge webhooks fast and process them on a queue, since processing is currently inline, and add a CRM reconciliation job so drift in `gtmos_*` fields is detected. Both are real gaps, and naming them yourself reads as seniority.

---

## 6. What NOT to overclaim

- **No live integrations were tested.** HubSpot sync uses `DemoHubSpotAdapter` (a `simulated_crm_objects` table) unless `HUBSPOT_ACCESS_TOKEN` and `HUBSPOT_LIVE_WRITES_ENABLED=true` are both set. `RealHubSpotAdapter`, `ApolloOrganizationProvider` and the Clay client are **untested against live APIs**. Enrichment providers are simulated. No HubSpot portal, Clay workspace or PostHog project exists. The one thing you may claim as executed is n8n: the container runs, the templates fire, and `make golden-flow VIA_N8N=1` goes through it. Say "verified by execution" only about that.
- **The LLM path is opt-in.** The demo runs the deterministic generator (`generator: demo-deterministic`). Don't say "Claude writes the research" unless you ran it live with `LLM_ENABLED=true`.
- **No customers, users or results.** Never say "increased reply rates by X%". Say "the framework detected a simulated +11.6 pp lift and correctly refused to call meetings significant."
- **All data is synthetic.** It uses `.example` domains, fictional companies (Sentinel AI, Kestrel Analytics) and a fixed RNG seed.
- **Workflow history is seeded.** Dead letters and retries in the history are synthetic. Live-triggered runs are real executions.
- **Single-operator auth.** There is no SSO or RBAC. An admin token gates live writes and destructive endpoints.
- **Nothing is sent.** There is no email or LinkedIn sending capability, by design.

---

## 7. Study checklist

Be able to explain each item without notes, and point to where GTMOS implements it.

**GTM fundamentals**
- [ ] ICP vs persona. Firmographic vs technographic data. Why exclusions matter (`domain/icp.py`)
- [ ] Lifecycle stage vs funnel/deal stage. HubSpot lifecycle is forward-only (`domain/pipeline.py`)
- [ ] MQL, SQL, PQL/PQA definitions and how they are misused
- [ ] Buying committee roles and why multi-threading matters (`domain/committee.py`)
- [ ] Sales velocity = opportunities × win rate × deal size ÷ cycle length
- [ ] Speed-to-lead and SLA design

**Data and integrations**
- [ ] Enrichment waterfall mechanics, merge policy and provenance (`domain/enrichment.py`)
- [ ] Lead-to-account matching: free-mail, subdomains, confidence (`domain/matching.py`)
- [ ] HubSpot objects, associations, batch upsert, `idProperty`, rate limits (`docs/research-notes-integrations.md`)
- [ ] Why not upsert on domain
- [ ] Salesforce Lead/Account/Contact/Opportunity and lead conversion
- [ ] Reverse ETL: model, primary key, match key, sync modes, CDC. Hightouch vs Census/Fivetran Activations
- [ ] Webhook signatures (HMAC, timestamp windows, constant-time compare), at-least-once delivery, idempotency keys
- [ ] Why a body hash is the wrong idempotency key for HubSpot: a JSON array plus `attemptNumber` on every retry (`services/webhook_service.py`)
- [ ] Data contracts and reconciliation
- [ ] PostHog: `$groupidentify` vs `$groups`, why the group key must be the account domain here, and why capture returning `200` proves nothing (`docs/research/posthog.md`, `docs/posthog-live-setup.md`)
- [ ] What group analytics costs and why self-hosting PostHog does not work for this
- [ ] The PQL rule: 14-day window, account level, threshold 55, no single criterion qualifies alone (`domain/pql.py`)
- [ ] The four breaks that make a CRM sync loop impossible, and which one is missing (reconciliation)

**Tool ownership**
- [ ] Buy the commodity, orchestrate the plumbing, own the judgement (`docs/phase3-architecture.md`)
- [ ] What each of PostHog, Clay, n8n and HubSpot owns, and the one thing GTMOS refuses to delegate to each
- [ ] Why n8n *and* a workflow engine: semantics in a diff, plumbing on a canvas
- [ ] The verification-level table in §5, from memory

**Automation**
- [ ] Trigger/condition/action, retries with exponential backoff, transient vs permanent errors, dead letter, replay (`services/workflow_engine.py`)
- [ ] Routing: territory, round-robin vs least-loaded, capacity, conflict resolution, ownership (`domain/routing.py`)

**Measurement**
- [ ] Why open rates are unreliable (Apple Mail Privacy Protection, image proxies)
- [ ] Wilson interval, two-proportion z-test, p-values, confidence intervals, power and minimum sample size (`domain/experiments.py`)
- [ ] Peeking and why early winners are usually noise. Account-level randomization
- [ ] Attribution models (first, last, linear, U-shaped, W-shaped, data-driven) and their biases. Incrementality and holdouts (`domain/attribution.py`)
- [ ] Correlation vs causation in signal analysis

**AI in GTM**
- [ ] Evidence grounding, citation validation, and hallucination guardrails (`domain/research.py`, `domain/personalization.py`)
- [ ] Deterministic vs LLM responsibilities, and why
- [ ] Evaluating AI output: golden sets, approval and edit rates, outcome experiments

**Tools you should be able to discuss:** HubSpot, Salesforce, Clay, Apollo, ZoomInfo, Hightouch, Census, Segment, PostHog, n8n/Zapier/Make, Outreach/Salesloft, LeanData, Gong, dbt, Snowflake.
