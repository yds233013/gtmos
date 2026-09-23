# Phase 3 handoff

Everything needed to pick this repository up cold: how to run it, what is genuinely verified, what is
not, what is open, and what to say about it in a room. `docs/phase3-final-report.md` is the narrative;
this is the operational companion.

---

## 1 · Run it

```bash
make setup                 # uv + npm install
make dev-deps              # Postgres on 56432, Redis on 56379, in Docker
make migrate && make seed  # deterministic synthetic dataset
make dev                   # API on :8010, web on :3010
```

`make up` runs the whole stack in Docker instead. `make down` stops it. Both images build clean.

## 2 · The safety posture, and how it is enforced

`.env` pins `LLM_ENABLED=false` and `HUBSPOT_LIVE_WRITES_ENABLED=false`. No email or message has ever
been sent by this system, to anyone; there is no SMTP client and no sequencer. No paid model call was
made building it — the default writer is deterministic, and every command during development ran with
`ANTHROPIC_API_KEY=` explicitly emptied. `.env` is git-ignored and has never been committed.

## 3 · What is actually verified, by boundary

| Boundary | Verified how far | What unblocks the next step |
|---|---|---|
| **n8n** | **By execution.** Six workflows imported and published, five executed against the running API from a pinned `n8nio/n8n:2.40.5` container. Deduplication and the error handler were each proved deliberately. | Nothing. |
| **HubSpot** | Simulated adapter end to end; every sync it performs is labelled SIMULATED. Live adapter **never run against a real portal**. | A developer test account and a private-app token. Twenty minutes and a human login — `docs/hubspot-live-setup.md`. |
| **PostHog** | Contract exercised locally against the documented payload shape. **Nothing has come from PostHog.** | A project, plus the group-analytics add-on and a webhook destination, both of which appear to be paid. |
| **Clay** | Contract exercised locally against the documented Public API and signed-webhook shape. **Nothing requested from clay.com.** | Two secrets and a paid-tier workspace for the HTTP API column. |

The `/integrations` page reports this itself, computed from stored deliveries rather than from
configuration, and the API returns `verified_against_live_clay: false` on its own.

## 4 · Regenerating every number

No headline figure should be typed by hand again. The four generators:

```bash
make backtest        # docs/scoring-backtest.md   — AUC, deciles, grade bands
make docs-numbers    # docs/demo-numbers.md       — routing SLA, experiment, data quality, deliverability
make llm-eval        # docs/llm-eval-report.md    — content evaluation (no database, no network)
make warehouse       # dbt build: 19 models + 113 tests
```

If a number in prose disagrees with a generated file, **the generated file is right.** This rule
exists because a review found four rows of the README's own honesty table contradicted by the running
app, three of them in the flattering direction.

## 5 · The quality gates, and their current state

| Gate | Command | State |
|---|---|---|
| Backend tests | `make test-api` | 465 (210 unit, 255 Postgres integration) |
| Frontend | `make test-web` | 14 |
| End to end | `make e2e` | 25, including `/integrations` |
| Warehouse | `make warehouse` | 19 models, 113 tests |
| Lint | `make lint` | clean |
| Types | `make typecheck` | mypy strict + tsc clean |
| Golden flow | `make golden-flow` and `VIA_N8N=1` | 20/20 on both transports |
| Migrations from empty | `alembic upgrade head` on a scratch DB | clean, and `alembic check` reports no model drift |
| Docker | `docker compose build api web` | both build; the API image serves live data |

**A caveat worth knowing:** the integration suite skips rather than fails when Postgres is unreachable,
so a green run on a machine with no database proves nothing. Anything calling itself CI must assert the
collected count, not just the exit code.

## 6 · What is open, and why

Each of these was found deliberately and left open with a reason, not overlooked.

1. **No reconciliation against the remote CRM record.** Change detection compares the payload hash to
   what GTMOS last *sent*, never to what HubSpot currently *holds*. `external_records.remote_updated_at`
   exists in the schema and is never read or written.
2. **No conditional writes.** No optimistic-concurrency check on the remote `updatedAt`.
3. **The approval queue does not group by contact.** Four pending drafts for the same person, two
   identically titled, is the noise the queue exists to prevent. Needs a suppression window per contact
   per draft type, plus a test for it.
4. **A draft's cited evidence is never re-validated at approval time.** The guardrails run when a
   draft is generated, not when a human approves it, so a signal retracted while the draft sat in the
   queue leaves a message citing evidence that no longer resolves. Found by accident when cleaning up
   test data — see finding 4 in `docs/phase3-product-review.md`. This is the most interesting open
   item in the list, because it is a GTM problem rather than a software one.
5. **No inbound rate limiting.** Deliberate: in production this belongs at the edge, and a naive
   in-process limiter gives false confidence across workers.
6. **The admin gate is a no-op in demo mode**, along with roughly thirty ungated mutating routes.
   Defensible for an openable demo; written up as Finding 4 in `docs/security-review.md` rather than
   covered by a scoping sentence.
7. **The audit actor is caller-asserted** (`X-GTMOS-Actor`), so the trail is a change log with a name on
   it. Finding 5, same document.
8. **Routing rules and workflow definitions are not editable in the product.** The ICP is the only thing
   an operator can change. The architecture argues the n8n split exists so operators can work without a
   deploy — and then the operator cannot change a territory or an SLA without one. This is the sharpest
   unanswered question in the project.
9. **No supply-chain scanning.**
10. **Every evaluation runs on synthetic data.** The matcher's held-out set is 116 cases, which cannot
   distinguish 0.96 precision from 0.90, and `docs/matcher-evaluation.md` says so in its own headline.

## 7 · Two things only you can decide

**Commit identity.** Every commit is authored `yds2330 <yashshah2311@berkeley.edu>`. If the repository
is going to be linked from a résumé pointing at a different account, the contribution graph there will
be empty. Rewriting history was explicitly out of scope, so nothing was changed — but `git config
user.name` / `user.email` should be set before the next commit either way.

**Provenance disclosure.** The history is dense and recent, and the README says nothing about how the
work was done. A reader who checks `git log` will notice. Adding a note about method was out of scope
under the no-attribution rule, so this is flagged rather than written: decide whether the README should
address it, because the project's own standard is that a reader should not discover something the
document could have said.

## 8 · What to say about it

The three surfaces that make the argument, in order: `/integrations` ("1 of 4 real services reached"),
`/experiments/provocative-subject` (a winning variant rejected, with the reasoning),
`docs/scoring-evaluation.md` (AUC 0.537, interval including 0.5).

The four questions worth rehearsing, because they are the ones a good interviewer will find:

- *"Why not upsert HubSpot companies on domain?"* — it is not a unique-enforced property, API-created
  companies are not deduplicated on it, you get ten unique properties per object, and the constraint
  cannot be added retroactively.
- *"Your enrichment providers disagree because you wrote them that way. What does this prove?"* — the
  merge policy, the provenance model and the refusal to resolve a material conflict on confidence alone.
  Not the coverage numbers, which are simulated and say so.
- *"Your score's AUC includes 0.5. Why ship it?"* — because an explainable score you can argue with
  beats a black box you cannot, and because the honest next step is a randomised holdout, which is
  named as the only unbiased design in the evaluation doc.
- *"You changed the simulation to make the score look better."* — yes, and `docs/scoring-evaluation.md`
  says so, names the function, and states the general lesson: you can make a model look good by changing
  the world it is measured against. Volunteer this one. It is the most credible thing in the repository.

## 9 · Document map

Start: `README.md` → `docs/phase3-final-report.md` → `docs/phase3-architecture.md`.
Tools: `docs/gtm-tool-guide.md` (what these tools are) and `docs/phase3-tool-research.md` (how they
compare to what GTMOS does, with thirteen cells marked Unverified rather than guessed).
Honesty: `docs/scoring-evaluation.md`, `docs/matcher-evaluation.md`, `docs/llm-evaluation.md`,
`docs/failure-tournament.md`, `docs/security-review.md`, `docs/phase3-product-review.md`,
`docs/demo-numbers.md`.
Going live: `docs/hubspot-live-setup.md`, `docs/posthog-live-setup.md`, `docs/clay-live-setup.md`.
