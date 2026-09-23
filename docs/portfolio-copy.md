# Portfolio copy

Ready to paste. All data is synthetic; nothing has ever been sent.

---

## TITLE

GTMOS — AI-Native GTM Infrastructure

## SUBTITLE

A control plane for the judgement layer: what a signal means, what an account is worth, who works
it, and whether any of it worked.

## SHORT DESCRIPTION

GTMOS connects product signals, enrichment, CRM state and custom decision logic into one pipeline —
signal, score, route, execute, sync, measure. The deterministic core (scoring, routing, workflow
conditions, experiment statistics, attribution) is pure functions under test; generation only ever
writes prose over an evidence pack the system already holds. Its evaluation layer reports the
unflattering number first: the leakage-free scoring AUC is 0.537, with an interval that includes 0.5.

## TECH STACK

Python · FastAPI · PostgreSQL · Redis/RQ · SQLAlchemy/Alembic · Next.js · TypeScript · dbt · Docker ·
n8n · Playwright · pytest

## KEY SYSTEMS

- **Explainable scoring** — a 100-point score over a versioned ICP, every point traced to a named
  rule and its evidence, with per-signal half-life decay and six signal types that subtract.
- **Idempotent workflow engine** — runs as rows, claimed with `FOR UPDATE SKIP LOCKED`, bounded
  backoff, dead letters, resumable replay; proved by a two-connection race test.
- **CRM reverse ETL** — batch upsert on a custom unique property, because HubSpot does not
  deduplicate API-created companies on `domain`; updates carry `gtmos_*` fields and nothing else.
- **Signed webhook ingestion** — HMAC verification, replay windows, and dedupe keyed on sorted
  member event ids so a CRM retry with a bumped `attemptNumber` stores one event.
- **Experimentation with guardrails** — deterministic account-level assignment, Wilson intervals, a
  minimum detectable effect, and harm metrics that veto a variant which won its primary metric.
- **Evidence-grounded generation** — validated citations, blocked ungrounded numbers, and a
  sentence-level sanitiser at the enrichment trust boundary that leaves a visible scar.

## ARCHITECTURE SUMMARY

Postgres is the source of truth and Redis is delivery: workflow runs are written as rows and
enqueued only after commit, with a sweeper for anything stuck. Around that sit four boundaries with
different jobs — product analytics observes, enrichment buys commodity data, an orchestrator moves
bytes between systems, and the CRM is where reps work — while GTMOS owns only the decisions, because
anything a revenue leader would want to argue with has to be explainable, versioned and diffable.
Each boundary is labelled with how far it has really been verified: n8n runs in Docker and its
workflows genuinely fire; HubSpot runs on a simulated adapter; Clay and PostHog are contracts
exercised locally. There is no "Connected" badge anywhere, because three of the four have never been.

## WHAT I LEARNED

- The pipeline is a week; the policy is the work. Two enrichment providers disagreeing, a field a
  rep edited, a message that won on replies and lost on unsubscribes — none of those is a plumbing
  question, and none of the four vendor tools has an answer for them.
- The risk is the inherited assumption, not the code. Three load-bearing vendor facts contradicted
  the obvious guess, and each would have broken on first contact with a real portal.
- A trust boundary is a property of where data comes from, not of which field it lands in. Adding an
  integration silently reclassified fields that had been safe, and opened a prompt-injection hole.
- Measuring honestly is harder than building, and more useful. Separating the leakage-free part of a
  score from the circular part turned a flattering result into a truthful one, and the truthful one
  says the model does not work yet.
