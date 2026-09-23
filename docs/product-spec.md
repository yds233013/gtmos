# GTMOS Product Specification (V1)

> GTMOS is an AI-native GTM operating system. It runs the loop **target → enrich → detect signals → score →
> research → identify buyers → personalize → approve → route → sync CRM → track engagement → create
> opportunity → measure pipeline → experiment → learn** on explainable, deterministic infrastructure,
> with AI used only where it adds leverage and never as an unreviewed source of CRM truth.

## 1. Demo persona

| | |
|---|---|
| Seller | **Sentinel AI** (fictional). Observability, evaluation and reliability infrastructure for enterprise AI agents |
| ICP | B2B software/technology companies, 100–10,000 employees, meaningful AI/ML org, shipping LLM apps or agents |
| Buyers | CTO, VP Engineering, Head of AI/ML, ML Platform Lead, Director of AI Infrastructure |
| Flagship account | **Kestrel Analytics** (fictional). Series C, just launched an AI agent, hiring 14 AI roles, new VP of AI, champion already in a free workspace |

All seeded data is synthetic, generated deterministically (fixed RNG seed) on reserved `.example` domains, and
labeled **DEMO** in the API (`data_origin`) and UI.

## 2. Users and jobs to be done

| User | Job | GTMOS answer |
|---|---|---|
| Founder / GTM lead | "Which companies should we target, and why now?" | Ranked accounts with explainable scores and a signal feed |
| SDR / AE | "Who do I contact and what do I say?" | Buying committee, research brief, evidence-grounded drafts |
| RevOps / GTM Engineer | "Is the machine healthy? Where is it leaking?" | Workflows, routing log, data quality, Stack Inspector, Operations |
| Leadership | "What is working?" | Funnel, pipeline, experiments, attribution, Copilot |

## 3. Requirement → feature map

Research gaps G1–G12 come from `docs/market-research.md` §7.

| # | Requirement | GTMOS feature | Acceptance criteria |
|---|---|---|---|
| 1 | ICP definition | **ICP Builder** (Settings → ICP): industries, size bands, regions, technographics, AI adoption, signals, exclusions, weights | Definition validated by Pydantic (weights sum to 100, no core/excluded overlap, known signal types); versioned; re-scoring all accounts is one action |
| 2 | Account scoring (G6) | **Explainable scoring engine**: Fit/Intent/Timing/Technical/Engagement, every point attributed to a component with a sentence and evidence | Pure function; same inputs → same output (input hash stored); signal time-decay by half-life; exclusions produce grade X; unit-tested |
| 3 | Enrichment (G3) | **Waterfall engine** + `EnrichmentProvider` protocol; 3 simulated providers, optional Apollo adapter | Per-field provider order; misses/errors/low-confidence fall back; one call per provider per run; cost credits; field provenance UI; manual locks never overwritten |
| 4 | Signals (G6) | **Signal engine + feed**: 19 signal types across intent, timing and engagement (funding, AI hiring, exec hire, launches, tech adoption, pricing visits, PLG events…), six of which subtract | Each signal has type, source, observed_at, confidence, strength, explanation, evidence; dedupe key; feeds scoring and workflows |
| 5 | Lead-to-account matching (G4) | Domain normalization, free-mail blocklist, contact email → account | Unit-tested; unmatched events recorded, not dropped |
| 6 | Buying committee | **Committee inference**: champion, technical evaluator, economic buyer, executive sponsor, end user | Title/seniority/department/engagement rules with reasons; manual overrides persist through recompute |
| 7 | AI research (G8) | **Research agent**: evidence pack → generator (deterministic demo or Claude) → citation validation | Every claim cites evidence IDs; uncited claims are stripped and listed; reports are drafts until reviewed; never written to CRM as fact |
| 8 | Personalization (G8) | **Message studio**: signal → pain → value → evidence → CTA for email, LinkedIn, call prep | Guardrails (unsupported numbers, unverifiable claims, length, CTA, do-not-contact); DRAFT→REVIEW→APPROVED→READY state machine; no send capability |
| 9 | Mini CRM | Accounts, Contacts, Opportunities, Activities; flagship **Account page** | Funnel stages Prospect→…→Won/Lost with transition validation and history |
| 10 | Routing (G5) | **Routing engine**: priority rules on segment, region, tier, intent, customer status, ownership | Deterministic; conflict resolution (priority → specificity → key); least-loaded pool assignment with capacity; every decision explained and logged |
| 11 | Workflows | **Workflow engine**: trigger → conditions → actions, persisted runs and step runs | Idempotency key per trigger; retries with attempt counts; failed → dead letter; step logs; inline or Redis/RQ execution |
| 12 | CRM sync (G1) | **HubSpot adapter boundary**: `DemoHubSpotAdapter` (simulated store) and `RealHubSpotAdapter` | Upsert on a unique custom property (`gtmos_account_id`), not `domain`; batches ≤100; 429/5xx retry; payload hashing skips unchanged records; all demo syncs labeled SIMULATED |
| 13 | Webhooks (G2) | Signed ingestion endpoints (PostHog, n8n, Clay, generic, and a HubSpot verifier that prefers v3 and falls back to the v1 scheme private apps actually send) | HMAC verification; raw event store; dedupe on event id; failure + dead-letter state; replay |
| 14 | n8n (G9) | Importable workflow templates + `docs/n8n.md` | Templates call GTMOS with signature headers; honest about what was and wasn't run against a live n8n |
| 15 | Product signals | PostHog-compatible ingestion: signup, invite, integration, usage threshold, pricing views | Event → account (via `$groups.company` or email domain) → signal → score → PQL workflow |
| 16 | Reverse ETL (G7) | **Reverse ETL job**: computed properties (`gtmos_icp_score`, `gtmos_intent_score`, `gtmos_account_tier`, `gtmos_last_signal`, `gtmos_next_best_action`) → CRM | Diff by payload hash; dry-run preview; sync log with counts |
| 17 | Outbound model (G10) | Campaigns → sequences → steps; outcome events | sent/delivered/opened(caveated)/replied/positive/meeting/opportunity/won; opens excluded from decisions (Apple MPP) |
| 18 | Analytics (G11) | **Command center**: funnel, stage conversion, pipeline, velocity, breakdowns | Every number computed from the database; DEMO badge |
| 19 | Experiments (G10) | Deterministic hash assignment at the **account** level; lift, Wilson CIs, two-proportion z-test | Won't declare a winner below minimum sample or when CI crosses zero |
| 20 | Attribution (G11) | First touch, last touch, linear, side-by-side | Shows how credited pipeline changes by model; unattributed share reported |
| 21 | Data quality | 12 rules (duplicates, invalid emails, missing fields, stale enrichment, orphans, lifecycle conflicts, missing owners, invalid transitions, bad external IDs, provider disagreement) | Fingerprinted issues; suggested remediation; merge/assign actions audited |
| 22 | Stack Inspector | Health of CRM sync, enrichment, routing, DQ, product-signal sync, attribution, workflows + ranked automation opportunities | Every metric and recommendation traceable to a query; no hardcoded percentages |
| 23 | Copilot | Question → intent → approved semantic query → deterministic metrics → explanation | No LLM-generated SQL; plan and queries shown; works without API key |
| 24 | Observability | **Operations** page: workflow runs, syncs, webhooks, failures, retries, latency, provider health | Correlation IDs on requests, runs, syncs and audit events |
| 25 | Audit | Audit log of state changes with actor, before/after, reason | Written by every mutating service |
| 26 | Production hygiene (G12) | Typed Python (mypy strict), ruff, pytest, TS strict, ESLint, Vitest, Playwright smoke, Docker Compose | `make check` runs everything |

## 4. What is deterministic vs. AI

| Deterministic (rules, testable) | AI-assisted (optional, reviewed) |
|---|---|
| Scoring, routing, workflow conditions, experiment assignment and statistics, attribution, data quality, analytics, Copilot queries | Research narrative wording, message wording, Copilot explanation phrasing |

AI output is always a draft attached to its evidence. Humans approve before anything leaves the system, and
no LLM output is ever executed as a query or written to CRM fields.

## 5. Explicit non-goals for V1

- Sending email or LinkedIn messages (the READY state is the hand-off point to a sequencer)
- Full SSO/RBAC (the demo uses a single operator identity; the admin-token boundary gates live integrations)
- Drag-and-drop workflow editor (definitions are JSON with a read-only visual view)
- Scraping third-party sites
