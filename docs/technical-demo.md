# Technical demo (10 minutes, for an engineer)

Ten sections, roughly a minute each. Assume the listener is sceptical, knows more about distributed
systems than about revenue operations, and will interrupt. Each section therefore ends with the question
it invites and a one-line answer, so an interruption lands on prepared ground rather than derailing the
run of play.

**Two things to establish before the clock starts**, because everything after them is read differently:

- The data is synthetic — 2,006 fictional accounts on reserved `.example` domains. Nothing here
  describes a real customer.
- Of four integration boundaries, **one is verified by execution** (n8n, in Docker locally). HubSpot
  runs on a simulated adapter whose live half has never touched a real portal. Clay and PostHog are
  contracts exercised against locally generated traffic. Nothing has ever sent an email or a message,
  and no paid model call was made building any of it.

Paths below are relative to the repository root. Line numbers are as committed; if a file has moved
under you, the symbol name is the stable reference.

---

## 1 · Architecture and ownership boundaries

**Show:** `http://localhost:3010/integrations`. Then `docs/phase3-architecture.md` for the diagram.

**Say.** Four external systems, and the interesting decision is which of them owns what. PostHog owns
product behaviour, Clay owns commodity enrichment, n8n owns plumbing, HubSpot owns the operational CRM.
Everything that constitutes a *judgement* — what a signal means, what an account is worth, who works it,
what may be said to them — stays in versioned code here. The test I applied: would a reasonable revenue
leader want to argue with it? If yes it has to be explainable, versioned and diffable, so it cannot live
on a vendor's canvas.

The page has two independent axes, **mode** and **verification**, because collapsing them into one badge
is how integration pages start lying. The headline is **Real services reached: 1 of 4**, computed from
stored deliveries rather than from configuration. There is no "Connected" state anywhere in the product.

**They'll ask:** *"You have a workflow engine and you also run n8n. Why both?"*
Because anything that decides revenue should be reviewable in a diff, and adding a Slack notification
should not need one — n8n moves bytes, GTMOS decides.

---

## 2 · Data model

**Show:** `apps/api/src/gtmos/models/` — six modules (`base`, `core`, `crm`, `intelligence`, `ops`,
`outbound`), 40 tables in Postgres. Then `docs/data-model.md`.

**Say.** Account-shaped, not lead-shaped, because B2B buying is a committee act: contacts hang off
accounts, signals and engagements resolve to an account before they mean anything, and the funnel is a
stage on the account with its own transition history. That history is what the backtest and the funnel
chart both read, so the two cannot disagree.

Three constraints carry most of the weight. `workflow_runs` has
`UniqueConstraint("idempotency_key")` (`models/ops.py:37`). `webhook_events` has
`UniqueConstraint("source", "idempotency_key")` (`models/ops.py:194`). And `external_records`
(`models/ops.py:166`) holds the mapping to CRM ids plus `last_payload_hash` — the change-detection key.

**They'll ask:** *"Multi-tenant?"*
The schema is — every row carries `workspace_id` — but the UI and auth are single-operator, so it is
multi-tenant in shape and not in enforcement, and I would not claim otherwise.

---

## 3 · Workflow idempotency and concurrency

**Show:** `http://localhost:3010/workflows/runs/911aed23-4489-4e2d-a6b5-da0045501f0e` — step timeline,
attempts, then the **Identity & idempotency** block. Then
`apps/api/src/gtmos/services/workflow_engine.py`.

**Say.** The key is `workflow : version : trigger type : event id`
(`domain/workflows.py:67`), checked before insert at `services/workflow_engine.py:302` and backed by a
unique index, so a re-delivered webhook or a double click cannot start a second run.

That is the easy half. The hard half is two workers holding the same run id — an RQ redelivery, the
sweeper racing a live worker, a retry racing the original. Persisted step state alone does not save you:
both workers read the same `pending` rows before either writes, so both call the actions, and every side
effect whose dedupe is a read-then-write happens twice. `_claim`
(`services/workflow_engine.py:372`) takes `SELECT … FOR UPDATE SKIP LOCKED` on the run row, so the loser
is a no-op instead of a duplicate. The lock is held by the transaction rather than by a status flag,
which means a worker that dies releases it and the run stays resumable. That was a real bug, and the
regression test is
`apps/api/tests/integration/test_workflow_hardening.py:78`.

Related: Postgres is truth, Redis is delivery. Runs are rows first and are enqueued **after commit**
(`workflow_engine.py:359`); if the queue is down the run stays `queued` and a sweeper picks it up
(`test_workflow_hardening.py:404`).

**They'll ask:** *"Why not a status column instead of a row lock?"*
Because a crashed worker leaves `running` set forever, and then you need a lease and a reaper; the
transaction already gives you that for free.

---

## 4 · CRM reconciliation and field ownership

**Show:** `apps/api/src/gtmos/services/crm_sync.py:119` — `plan_company_sync`. Then
`http://localhost:3010/operations`, the **Reverse ETL · HubSpot companies** panel.

**Say.** Field ownership is enforced in the planner, not documented in a wiki. On update the payload is
`gtmos_*` properties and nothing else; `name` and `domain` go only on create. A reverse-ETL push
therefore cannot clobber a rep's correction, because the fields a rep edits are never in the payload.
Inbound CRM changes are logged and never auto-applied — that is what breaks the sync loop where GTMOS
writes a field, HubSpot fires a change webhook, GTMOS applies it, and writes again.

Change detection is a hash of the owned properties (`payload_hash`, `crm_sync.py:96`) compared with
`external_records.last_payload_hash`. On the Operations page right now: 850 companies considered, 850
unchanged, nothing written.

Now the honest gap, and I would rather say it than have you find it. That hash compares against **what
GTMOS last sent**, never against what HubSpot currently holds. `remote_updated_at` exists on the model
(`models/ops.py:187`) and is never read or written. So a `gtmos_*` field edited inside the CRM is
invisible to us: we think we are in sync, and we are in sync with our own last write. Closing it needs a
read-back plus a conditional write on the remote `updatedAt`, and it is the second item on the next-steps
list for exactly that reason.

Also: upsert is on a custom unique property `gtmos_account_id`, not on `domain`, because HubSpot does not
enforce uniqueness on `domain` and API-created companies are not deduplicated on it.

**They'll ask:** *"How do you know the live adapter works, then?"*
I don't. It is implemented against the documented v3 batch API and unit-tested against mocked HTTP, and
every sync the product performs is labelled SIMULATED — it has never run against a portal.

---

## 5 · Webhooks, signatures and dedupe

**Show:** `apps/api/src/gtmos/services/webhook_service.py:91` — `idempotency_key_for`. Then
`http://localhost:3010/integrations/n8n` for per-delivery signature status.

**Say.** Ingestion is verify → store raw → dedupe → process → record outcome, with replay from the stored
payload.

The interesting failure is HubSpot. It posts a JSON **array** of events and increments `attemptNumber` on
every retry — so the naive idempotency key, a hash of the raw body, hashes differently on every retry and
deduplication never fires at all. It had that bug. The fix keys a batch on the **sorted set of member
`eventId` values** (`webhook_service.py:109`); order is not guaranteed across redeliveries either, hence
the sort. Only a payload with no usable id anywhere falls back to a hash, and that hash is taken over a
canonical form with the retry counters stripped (`RETRY_VOLATILE_KEYS`, `webhook_service.py:64`).

Signatures: HubSpot v1, v2 and v3 are all accepted, v3 preferred
(`integrations/signatures.py:87`). Private apps sign with **v1** — a plain SHA-256 of
`clientSecret + body`, no timestamp, therefore no replay window — and a private app is exactly what a
free developer test account uses, so implementing only v3 would have rejected every delivery from the
most likely test environment. v1's weaker guarantee is labelled per delivery rather than hidden. The v3
verifier hashes the URI **as sent**; an earlier version unquoted it first, and there is now a test that
signs the decoded form and asserts it does *not* verify.

One more: a rejected delivery must not write the idempotency key, or a forged request poisons it and the
genuine signed delivery that follows is swallowed as a duplicate
(`apps/api/tests/integration/test_webhook_dedupe.py:117`).

**They'll ask:** *"What stops a replay of a valid signed body?"*
A timestamp window on the schemes that carry one; v1 has none, which is stated in the verifier's detail
string and shown on the Operations page rather than glossed over.

---

## 6 · Routing and SLA measurement

**Show:** `http://localhost:3010/routing` — the rules table, then the **Speed to first touch** panel,
then expand a Kestrel decision to read the recorded conflict. Code: `apps/api/src/gtmos/domain/routing.py:127`.

**Say.** Rules are data, evaluated in a fixed order: lowest priority number wins, ties broken by
specificity (more conditions), then by rule key alphabetically (`_sort_key`, `routing.py:79`). Every
decision persists which rules matched, which lost and why — the Kestrel row reads *"Also matched
'Enterprise NA → Enterprise AE pool'; lost: lower priority (30 vs 20)"*. Round robin keys the seat off
the account id (`pick_round_robin`, `routing.py:106`) so a replay lands on the same rep. Named accounts
cannot be moved by any rule, and anything no rule claims goes to a fallback triage queue rather than to
nobody — currently 200 accounts, 14.5%, and zero unowned.

The measurement is the part I would push on if I were you. Speed to lead is computed from real activity,
not from a stored breach flag, so three states stay distinguishable: met, **late**, and **never touched**
(`services/routing_service.py`, `sla_report`). A boolean collapses the last two, and "nobody has looked
at it" is the one that costs money. Right now: 79% met, 474 of 602 whose clock has run out, **106 late,
22 never touched**, median 4.4 hours. Only genuine lead events start a clock — `signal.created`,
inbound, `product.pql`, manual, workflow (`LEAD_TRIGGERS`, `routing_service.py:167`) — because a
territory reshuffle assigns thousands of accounts at once and would turn the metric into a measure of
list size.

**They'll ask:** *"Can an operator change a rule?"*
No, and that is the sharpest unanswered question in the project: the architecture argues n8n exists so
operators can work without a deploy, and then a territory change still needs one.

---

## 7 · Experimentation

**Show:** `http://localhost:3010/experiments/provocative-subject`. Code:
`apps/api/src/gtmos/domain/experiments.py`.

**Say.** Assignment is `sha256(salt + account_id) mod 10000` split by variant weight
(`bucket_for`/`assign_variant`, `experiments.py:105`) — deterministic, at the **account** level because
that is the unit a buying decision happens at, and nobody picks who gets what. Minimum sample is fixed
before launch; until every arm reaches it the verdict stays "insufficient" however large the observed
lift, which is the single most common way A/B tests lie.

Statistics: Wilson intervals on rates, a two-proportion z-test, a Newcombe interval on the difference
(`compare`, `experiments.py:243`). Every null reports a **minimum detectable effect**
(`experiments.py:221`) so a flat result reads as "no effect" or "underpowered" rather than ambiguously.

The reason to open this page: the treatment wins the primary metric decisively — reply rate 20.7% → 37.0%,
**+16.3 pp, p < 0.001** — and the recommendation is **do not ship**. Guardrails are evaluated one-sided
for harm and are never traded against the primary metric (`evaluate_guardrail`, `experiments.py:351`;
`recommend`, `experiments.py:427`). Unsubscribes go 0.00% → 2.90% against a 1% ceiling, with the whole
95% interval above it, and negative replies 2.63% → 10.14%. A team that ships this wins the quarter and
burns the sending domain for someone else's campaign next quarter.

**They'll ask:** *"You seeded this outcome, though."*
Yes — the point is not the result, it is that the engine produces `do_not_ship` on a significant win
without a human overriding it.

---

## 8 · AI boundaries and evidence grounding

**Show:** `http://localhost:3010/approvals` — a Kestrel draft, its reasoning chain, evidence refs and
guardrail list. Code: `apps/api/src/gtmos/domain/research.py:109` and
`apps/api/src/gtmos/domain/personalization.py:125`.

**Say.** A model never decides anything. It writes prose over an evidence pack the system already holds
(`build_evidence_pack`, `research.py:127`), claims must cite numbered evidence, uncited claims are
stripped, and output is validated like any other generator's. The default writer is deterministic; the
live path needs both an API key and a flag, and neither was used at any point. Drafts go DRAFT → REVIEW →
APPROVED → READY, and READY means handed to a sequencer — there is no send path in this codebase.

Prompt injection. Enrichment and signal text is scraped from the outside world and ends up in a brief a
rep may paste into an email. The evaluation harness caught the generator copying an attacker-supplied
instruction into a research report *with a citation*. `sanitize_external` (`research.py:109`) drops
offending sentences and leaves a visible marker, because silently altering evidence is its own kind of
dishonesty. The general lesson is the part worth stealing: **a trust boundary is a property of where data
came from, not of which field it lands in.** Phase 2 sanitised signal titles on the reasonable assumption
that firmographics were our own facts; adding Clay made that assumption false and silently reclassified
`industry`, `city` and `technologies` as attacker-influenceable.

Second open failure: guardrails run when a draft is **generated**, and approval only re-reads the stored
verdict (`_blocked` → `transition`, `services/outreach_service.py:194`). A signal retracted while the
draft sat in the queue leaves a message citing evidence that no longer resolves, and a human approves it
believing the green ticks. Editing re-runs them; approving does not. It is a GTM problem more than a
software one, and it is open.

**They'll ask:** *"Why not just re-run the guardrails on approve?"*
Because the interesting half is deciding what a stale-evidence failure should *do* — block, warn, or
silently regenerate — and I would rather ship the question than guess the answer.

---

## 9 · Observability

**Show:** `http://localhost:3010/operations` — failure rates, dead letters, webhook health by source,
provider hit/error rates, routing latency. Code: `apps/api/src/gtmos/services/governance.py:118`.

**Say.** Every mutation writes an audit row with actor, before/after, reason and a correlation id, and
the correlation id ties a workflow run to the CRM syncs, drafts and audit events it produced — one id
across the whole causal fan-out. Right now: 10.7% workflow failure rate over 75 executed runs, 19
dead-lettered, 1.38% sync record failures, 60 re-deliveries absorbed without reprocessing. Older runs
are labelled **HISTORY (synthetic)** and their retry buttons are disabled; anything unlabelled was
executed by the engine.

Runtime kill switches for automation, outbound and CRM writes are read from the database on every action
(`governance.require`, `governance.py:118`) rather than from config, so a pause takes effect immediately
instead of after a deploy. A blocked request returns **423 Locked**, not 403 — the caller is not
unauthorised, the capability is switched off — and queued work stays queued (`main.py:88`).

**They'll ask:** *"Is that audit log admissible?"*
No. The actor is caller-asserted via a header, so it is a change log with a name on it rather than a
true audit trail, and it is written up as a finding rather than covered by a scoping sentence.

---

## 10 · Evaluation honesty

**Show:** `http://localhost:3010/scoring`, the **Does the score work?** panel. Then
`docs/scoring-evaluation.md`. Code: `apps/api/src/gtmos/domain/evaluation.py:220`.

**Say.** The score is a hand-weighted heuristic, not a model: no training set, no loss function, no
holdout. That is the right first move on a new ICP with no labels, and the bill for it is that a
heuristic nobody evaluates is just an opinion with a number attached. So it gets graded.

The evaluation splits the score into nested variants, which is the whole exercise. **Structural** (fit +
technical, all known before first contact) scores **AUC 0.537, 95% interval 0.485–0.589**. The interval
includes 0.5: on this data it is **not distinguishable from random**, and the product prints that warning
itself. The total score reads 0.593 — and +0.056 of that is circularity, because engagement points are
awarded for replies and meetings, which is the outcome. Read the first row.

Two biases pull in opposite directions and neither is fixable by arithmetic: range restriction from only
contacting above a propensity floor biases it down, targeting feedback across all accounts biases it up
(0.553). The only unbiased design is a randomised holdout — contact a sample regardless of score — and
GTMOS does not run one, because the demo sends nothing.

The harness at `evaluation.py:220` takes `(score, outcome)` pairs and is model-agnostic on purpose: the
day the score becomes a learned prediction, the same backtest grades it. And every headline number is
regenerated by `make backtest` and `make docs-numbers`, because a review once found four rows of the
README contradicted by the running app, three of them in the flattering direction.

**They'll ask:** *"So why ship a score that doesn't beat chance?"*
Because an explainable score a revenue leader can argue with beats a black box nobody can interrogate,
and because the honest next step is named, costed and not pretended to be done.

---

## Things to volunteer before you are asked

Offering these unprompted is worth more than any of the ten sections above.

1. **The simulation was changed to make the score look better.** When disqualifying signals were added
   the backtest got *worse*, because the negative signals were generated after the journeys and were
   pure noise. The fix was in the seed, not the score — accounts with a departed champion now genuinely
   engage less. It is defensible and it is the failure mode of every simulated evaluation: you can make
   a model look good by changing the world it is measured against. The function is named in
   `docs/scoring-evaluation.md`.
2. **Three of four integrations have never met the vendor.** Say it before the interviewer reads the
   badge.
3. **The matcher's held-out set is 116 cases**, which cannot distinguish 0.96 precision from 0.90, and
   the evaluation doc says so in its own headline.
4. **Roughly thirty mutating routes are ungated** in demo mode, written up as a security finding rather
   than hidden behind "it's a demo".

## Recovery

- **A page shows different numbers.** Read what is on screen. The dataset is a rolling window and moves
  on reseed; every figure quoted here came off the running app on the day it was written, and the
  generated files (`docs/demo-numbers.md`, `docs/scoring-backtest.md`) are authoritative over any prose.
- **The run URL 404s.** Run ids are per-seed; take the newest **EXECUTED** run from `/workflows`.
- **You are asked for something not built.** Prefer "not built, here is why and what it would cost" over
  a hedge. The next-steps list is in `docs/phase3-final-report.md` §4 and the open items in
  `docs/phase3-handoff.md` §6.
