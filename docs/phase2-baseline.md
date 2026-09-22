# Phase 2 baseline

Recorded before any Phase 2 change, so every later claim can be compared against a known-good state.

**Date:** 2026-09-22 · **HEAD at baseline:** `70d6938f6ad3ab28c2376f72e0c37dceb49c5c20`
("Protect CRM-owned fields in reverse ETL, auto-create HubSpot properties, fix n8n template 04 and compose env;
add data model, integrations and n8n docs") · **Working tree:** clean.

## Demo-mode safety (verified first)

| Check | Result |
|---|---|
| `LLM_ENABLED` | unset in shell; pinned `false` in the git-ignored root `.env` |
| `HUBSPOT_LIVE_WRITES_ENABLED` | unset in shell; pinned `false` in `.env` |
| `ANTHROPIC_API_KEY` | present in the developer shell, **stripped** from every process started in Phase 2 (`env -u ANTHROPIC_API_KEY …`) |
| `HUBSPOT_ACCESS_TOKEN`, `APOLLO_API_KEY` | not set |
| `GET /api/v1/workspace` | `mode: demo · llm: demo · hubspot: demo · outbound_send: false` |

All Phase 2 work runs against simulated adapters and the deterministic demo dataset. No billed API calls, no
live writes.

## Quality gates at baseline (all green)

| Gate | Command | Result |
|---|---|---|
| Backend lint | `ruff check src tests` | pass |
| Backend format | `ruff format --check src tests` | pass |
| Backend types | `mypy` (strict, 66 files) | pass |
| Backend unit tests | `pytest tests/unit` | **57 passed** (0.5 s) |
| Backend integration tests | `pytest tests/integration` (Postgres) | **67 passed** (10.7 s) |
| Frontend lint | `eslint src e2e` | pass |
| Frontend types | `tsc --noEmit` | pass |
| Frontend unit/component | `vitest run` | **14 passed** |
| Production build | `next build` | pass (20 routes) |
| E2E desktop + mobile | `playwright test` against the production build | **22 passed** (1.4 min) |
| **Total automated tests** | | **160** |

## Infrastructure

| Check | Result |
|---|---|
| Migrations from an empty database | `alembic upgrade head` applies the single initial revision |
| Model drift | `alembic check` → "No new upgrade operations detected" |
| Seed | `python -m gtmos.seed --reset` completes in ~54 s |
| Docker images | `api` and `web` built in Phase 1; Compose stack verified with the RQ worker executing a run |

## Seed determinism (finding)

Two consecutive `--reset` runs on the same day produced **identical record structure**:

```
accounts 2006 · contacts 11819 · signals 4228 · activities 16960 · opportunities 125
workflow_runs 916 · drafts 18 · open DQ issues 392 · pipeline sum $10,102,000 · flagship score 98
```

but a **different grade distribution**:

```
run 1: A:2  B:73  C:538  D:1344  X:49
run 2: A:1  B:74  C:537  D:1345  X:49
```

Cause: the seed writes signals at offsets relative to the day's anchor, then scores with wall-clock `now`, so
time-decay shifts a few accounts across grade boundaries depending on the hour of the seed run. The data is
reproducible; the *scores* are not bit-identical. Carried into the audit as a demo-consistency defect
(P2-01) because a demo that reports "2 A-grade accounts" should not report 1 an hour later.

## Security

| Check | Result |
|---|---|
| Secret scan over 236 tracked files | no key material, no `.env`/`.pem`/`.key` tracked |
| `npm audit --omit=dev` | 0 vulnerabilities |
| Python dependencies | 57 packages, all from the locked `uv.lock` |

## Baseline inventory

| Item | Count |
|---|---|
| Database tables | 40 |
| API endpoints | 75 |
| Frontend routes | 20 |
| Python source lines | ~15,900 |
| TypeScript source lines | ~11,900 |
| Demo dataset | 2,006 accounts · 11,819 contacts · 4,228 signals · 16,960 activities · 125 opportunities |

## Rule for Phase 2

No currently passing gate may regress. Every change lands with the suite green, and the final report compares
these numbers directly.
