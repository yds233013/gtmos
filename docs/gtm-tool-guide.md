# The modern GTM stack, explained through this repository

Written for someone who can read code but has not worked in revenue operations. Every section ties the
tool to a specific place in GTMOS, so you can open the file and see what the integration actually does.

The shortest useful framing: a modern GTM team runs on four kinds of system.

| Kind | Question it answers | In this stack |
|---|---|---|
| Product analytics | What are users doing? | PostHog |
| Enrichment | Who is this company, really? | Clay |
| Orchestration | How do these systems talk? | n8n |
| CRM | Where does the revenue team work? | HubSpot |

And then the part nobody sells you: the judgement layer that decides what any of it *means*. That is
what GTMOS is, and it is the part a GTM engineer is hired to build.

---

## HubSpot

### What is it?
A CRM: the system of record for companies, contacts and deals, and the application where salespeople
spend their day. It also bundles marketing email, sequences, forms, workflows and reporting.

### Why do GTM teams use it?
Because reps need one place that answers "who am I talking to, what did we say, what happens next".
Everything else in the stack exists to make that record better. HubSpot specifically tends to win at
companies under a few hundred people because it is dramatically easier to administer than Salesforce.

### What problem does it solve?
Shared memory. Without a CRM, the state of a deal lives in one person's inbox and leaves when they do.

### Where does GTMOS integrate with it?
- `apps/api/src/gtmos/integrations/hubspot.py` — two adapters behind one interface. `DemoHubSpotAdapter`
  writes to a simulated store in Postgres; `RealHubSpotAdapter` calls the live API. Only the demo one
  has ever run.
- `apps/api/src/gtmos/services/crm_sync.py` — `run_company_sync` and `run_contact_and_deal_sync`.
- `POST /api/v1/webhooks/hubspot` — inbound change events.
- `docs/crm-sync-design.md` — the full design, including three failure scenarios.

### What data flows?
**Out of GTMOS:** company records keyed on a custom unique property `gtmos_account_id`, carrying only
computed fields — `gtmos_icp_score`, `gtmos_intent_score`, `gtmos_account_tier`, `gtmos_last_signal`,
`gtmos_next_best_action`, `gtmos_last_scored_at` — plus name and domain **on create only**. Then
contacts (keyed on email), deals (keyed on `gtmos_opportunity_id`), and the associations between them.

**Into GTMOS:** property-change webhooks, which are **logged and never auto-applied**.

### What should GTMOS *not* replace?
The CRM itself. Do not rebuild pipeline management, tasks, sequences, permissions or mobile. The moment
your custom system becomes where reps work, you own a CRM and you will lose.

### Common failure modes
1. **Sync loops.** GTMOS writes a field → HubSpot fires a change webhook → GTMOS applies it → writes
   again. GTMOS breaks the cycle by never auto-applying inbound changes.
2. **Overwriting rep edits.** A reverse-ETL job that pushes a full record wipes whatever a human fixed.
   GTMOS sends only `gtmos_*` fields on update.
3. **Duplicate companies.** `domain` is **not** unique in HubSpot — the docs say records created via API
   are not deduplicated on it. Upserting on domain creates duplicates. GTMOS uses a custom unique
   property instead.
4. **Broken webhook signatures.** The most common cause is hashing a re-serialised body instead of the
   raw bytes; HubSpot's own Node sample does this.
5. **Assuming the returned id is the one you asked for.** Merged records resolve to the surviving id.

### What would an interviewer ask?
*"How do you prevent a sync loop?"* — one-way ownership per field, inbound changes logged not applied,
and a payload hash so an unchanged record is not rewritten.

*"Why not upsert on domain?"* — HubSpot does not enforce uniqueness on it. Use a custom unique property,
and know that you get at most ten of them per object and cannot add the constraint retroactively.

---

## Clay

### What is it?
A spreadsheet-shaped enrichment and orchestration tool. Each row is a company or person; each column is
a data source, an enrichment provider, a formula, or an AI agent. Its signature feature is the
**waterfall**: try provider A; if it has no answer, try B; then C — paying only for the one that
answers.

### Why do GTM teams use it?
Because the alternative is contracting with a dozen data vendors individually and writing the fallback
logic yourself. Clay's real product is the *provider network*, not the spreadsheet.

### What problem does it solve?
Coverage and cost. No single vendor knows every company. A waterfall over many vendors gets materially
better coverage than the best single one, for less than buying them all.

### Where does GTMOS integrate with it?
- `apps/api/src/gtmos/integrations/clay.py` — the API client.
- `apps/api/src/gtmos/services/clay_service.py` — ingestion and mapping.
- `POST /api/v1/webhooks/clay` — signed inbound enriched rows.
- `docs/clay-live-setup.md` — exact setup instructions, **and an explicit statement that this has not
  been run against a live Clay workspace.**

### What data flows?
**Into GTMOS:** an enriched account or contact row with, per field, the value, the provider that
supplied it, a confidence where available, and a timestamp. The provenance is the important part.

**Out of GTMOS (designed, not built):** the target list to enrich.

### What should GTMOS *not* replace?
The provider network. GTMOS implements a waterfall over three *simulated* providers to prove it
understands the mechanics — batching, per-field provider order, fallback on miss or low confidence, cost
accounting. That is the right place to stop. Buying Clay is cheaper than becoming a data broker.

### What GTMOS *does* keep
The merge policy. Clay reports what a provider said; it does not decide whether that should overwrite
what you already believe. GTMOS refuses to overwrite a manual lock, refuses to resolve a material
disagreement on confidence alone, and raises a data-quality issue instead.

### Common failure modes
1. **Silent overwrites.** Enrichment replaces a correct human-entered value with a confident wrong one.
2. **Credit burn.** A waterfall configured to try every provider on every row costs a fortune.
3. **Stale data treated as fresh.** A headcount from eighteen months ago is not a fact about today.
4. **Partial enrichment handled as failure.** Most rows come back with some fields filled.

### What would an interviewer ask?
*"Why use Clay instead of building enrichment yourself?"* — the value is the vendor network, not the
code. You can write a waterfall in an afternoon; you cannot negotiate forty data contracts in one.

*"What do you keep in-house?"* — the merge policy, provenance, and the decision about what a conflict
means. That is where the business logic is.

---

## n8n

### What is it?
An open-source workflow automation tool — a visual canvas of nodes (triggers, HTTP requests, code,
conditionals) that runs on a schedule or a webhook. Think Zapier, but self-hostable and far more
capable.

### Why do GTM teams use it?
Because most GTM work is moving data between systems that do not know about each other, and a RevOps
person needs to change that wiring without waiting for an engineering sprint.

### What problem does it solve?
The integration long tail. Every company has thirty small automations that are individually not worth
an engineer's week.

### Where does GTMOS integrate with it?
- `integrations/n8n/*.json` — version-controlled workflow definitions.
- `docker-compose.yml` — the `n8n` service, pinned to **2.40.5**.
- `docs/n8n.md` — how to import, publish and run them.

**This is the one integration verified by execution.** It runs locally in Docker, reaches the GTMOS API
at `host.docker.internal:8010`, signs requests with the shared HMAC secret, and the workflows genuinely
fire.

### What data flows?
Product events inbound, CRM change events inbound, scheduled reverse-ETL triggers outbound, and
failures into an error workflow.

### What should GTMOS *not* replace?
The general-purpose canvas. GTMOS's own workflow engine runs *GTM semantics* — score, qualify,
research, route — with idempotency keys, persisted step state, row-locked execution and dead letters.
n8n runs *plumbing*. The rule: anything that decides revenue lives in GTMOS and is reviewable in a
diff; anything that moves bytes between systems lives in n8n and can be changed without a deploy.

### Common failure modes
1. **Business logic sprawling onto the canvas**, where it cannot be unit-tested or code-reviewed.
2. **No retry configuration**, so a transient 502 silently drops a lead.
3. **No error workflow**, so failures are only visible if someone opens the executions tab.
4. **Credentials in the canvas** rather than in n8n's credential store.
5. **Test vs production webhook URLs.** `/webhook-test/` only fires while the editor is open; `/webhook/`
   is the real one. This catches everybody once.

### What would an interviewer ask?
*"You have a workflow engine — why also run n8n?"* — they solve different problems. Scoring logic
belongs in version control with tests; a Slack notification does not need a pull request. Putting
revenue logic on a canvas is how you get a system nobody can reason about.

---

## PostHog

### What is it?
Open-source product analytics: event capture, session replay, feature flags, experiments, and — most
importantly for B2B — **group analytics**, which lets events be attributed to a company rather than
only a user.

### Why do GTM teams use it?
Because in product-led businesses the strongest buying signal is usage, and it arrives before anyone
fills in a form. A team that connected an integration and pushed real traffic is further along than one
that downloaded a whitepaper.

### What problem does it solve?
It closes the gap between what people *say* in a form and what they *do* in the product.

### Where does GTMOS integrate with it?
- `apps/api/src/gtmos/integrations/posthog.py` — payload parsing and normalisation.
- `apps/api/src/gtmos/services/product_events.py` — ingestion, identity resolution, engagement records.
- `apps/api/src/gtmos/domain/pql.py` — the product-qualified account rule.
- `POST /api/v1/webhooks/posthog`.

### What data flows?
Events with `$groups.company` carrying the account key, `distinct_id` and an email property for person
resolution, and the event name. GTMOS turns those into engagement rows, then into signals, then into a
score change.

### The concept worth understanding: a PQL
A **product-qualified lead** (or account) is one whose product usage says they are ready for a
conversation. The mistake is defining it as a single event. GTMOS uses a composite rule over a 14-day
window at the account level:

| Criterion | Points | Why |
|---|---:|---|
| Three or more distinct users | 25 | A team, not an individual. One engineer is a champion; three is a budget. |
| A second user joined | 10 | The weaker version of the same signal. |
| Connected a production integration | 30 | Switching costs behind it — a decision, not an intention. |
| Crossed the usage threshold | 25 | Real traffic. Adoption rather than evaluation. |
| Viewed pricing | 10 | Commercial intent, but cheap to fake. Deliberately the smallest weight. |

Threshold 55, so **no single criterion qualifies an account alone**. It fires once per account per week,
because an alert that repeats daily is one a rep learns to ignore.

### What should GTMOS *not* replace?
Event storage, session replay, funnels over raw events. PostHog is very good at this and it is a
commodity.

### Common failure modes
1. **User-level thinking in a B2B business.** Without group analytics you cannot answer "how many people
   from this company are active", which is the whole question.
2. **Unmatched accounts.** Free-mail signups (`gmail.com`) must never be matched to a company.
3. **Capture returns 200 for dropped events.** A successful POST does not mean the event was stored;
   verification means reading it back.
4. **Treating every event as a signal**, which drowns the score in noise.

### What would an interviewer ask?
*"How would you identify a PQL?"* — at the account level, composite, time-windowed, weighted toward
acts with switching costs, and fired once. Then: *"how would you know if it worked?"* — the honest
answer is that you need outcomes and a holdout, which is what `docs/scoring-evaluation.md` is about.

---

## Putting it together

The flow this stack is built for, and what each hop contributes:

```
product usage        → PostHog observes it          (bought: capture at volume)
                     → n8n forwards it              (bought: plumbing, editable by ops)
                     → GTMOS decides what it means  (built: PQL rule, scoring, routing)
                     → HubSpot receives the answer  (bought: where reps work)
                     → HubSpot reports what changed (bought: the rep's edits)
                     → GTMOS reconciles and measures(built: attribution, evaluation, audit)
```

Enrichment sits alongside it: Clay answers "who is this company" and GTMOS decides whether to believe
it.

If you remember one thing: **buy the commodity, orchestrate the plumbing, own the judgement.** Everything
in `docs/phase3-architecture.md` follows from that sentence.
