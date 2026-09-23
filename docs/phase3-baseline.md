# Phase 3 baseline

Recorded before any Phase 3 change, so every later claim can be diffed against a known state.

## Repository

| | |
|---|---|
| Root | `~/gtmos` |
| Branch | `main` |
| HEAD | `cc209e9c2e2f61bdecc4a83bb4931e875d2da3db` (`cc209e9`, "Record the final commit hash in the Phase 2 report") |
| Working tree | Clean — nothing staged, nothing untracked |
| Remotes | **None configured.** The repository is local only. |
| Commits since the Phase 1 baseline `70d6938` | 22 |

## Quality gates at baseline

All verified by running them, not assumed:

| Gate | Result |
|---|---|
| Backend unit (pytest) | **132 passed** |
| Backend integration (pytest + Postgres) | **185 passed** |
| Backend total | **317 passed** |
| `ruff check src tests` | All checks passed |
| `mypy --strict src/gtmos` | Success, no issues in 78 source files |
| Frontend component (Vitest) | 14 passed |
| End-to-end (Playwright, desktop + Pixel 7) | 22 passed |
| dbt (`make warehouse`) | PASS=132, 0 errors |
| Content evaluation (`make llm-eval`) | 7 of 7 cases |
| `alembic check` | No drift |
| **Total automated checks** | **492** |

## Architecture as inherited

- **`apps/api`** — FastAPI + SQLAlchemy 2 + Alembic over PostgreSQL, 40 tables, 84 REST endpoints.
  Pure domain logic in `domain/`, orchestration in `services/`, external boundaries in `integrations/`.
- **`apps/web`** — Next.js 16 App Router, 19 pages, server components calling the API directly and
  browser requests proxied through a rewrite.
- **`warehouse/`** — dbt project, 19 models and 113 tests, parity-checked against the API's semantic
  layer.
- **Redis + RQ worker** for workflow execution, with an after-commit enqueue and a sweeper.

## Integration boundaries as inherited

| Boundary | File | State at baseline |
|---|---|---|
| HubSpot | `integrations/hubspot.py` | `DemoHubSpotAdapter` (simulated store) and `RealHubSpotAdapter` (implemented against documented APIs, **never run against a real portal**) |
| PostHog | `integrations/posthog.py` | Inbound webhook receiver with token auth; product events → signals |
| Enrichment providers | `integrations/enrichment_providers.py` | Three simulated providers + an optional real Apollo adapter (never exercised) |
| LLM | `integrations/llm.py` | Anthropic research writer, gated behind `LLM_ENABLED` (false) |
| Signatures | `integrations/signatures.py` | GTMOS HMAC scheme + HubSpot v3 verification |
| n8n | `integrations/n8n/` (4 workflow JSON files) | Templates **verified to import** into n8n 2.40.5; never executed |
| Clay | — | **No boundary exists.** New in Phase 3. |

Inbound webhook endpoints already present: `/webhooks/posthog`, `/webhooks/n8n`, `/webhooks/hubspot`,
plus `/events`, `/webhooks/events` and a replay endpoint.

`docker-compose.yml` already defines an `n8n` service behind a `n8n` profile, pinned to
`n8nio/n8n:latest` (Phase 3 should pin a real version).

## Credentials available

Checked by presence only; **no value was printed, and none will be used without authorisation**:

| Variable | Present |
|---|---|
| `ANTHROPIC_API_KEY` | **Set** — deliberately unused. Every command in Phase 3 runs with it blanked. |
| `HUBSPOT_ACCESS_TOKEN` | Not set |
| `HUBSPOT_WEBHOOK_CLIENT_SECRET` | Not set |
| `APOLLO_API_KEY` | Not set |
| `POSTHOG_API_KEY` / `POSTHOG_PROJECT_API_KEY` | Not set |
| `CLAY_API_KEY` | Not set |
| `N8N_API_KEY` | Not set |
| `WEBHOOK_SECRET`, `ADMIN_API_TOKEN` | Not set |

**Consequence for Phase 3 planning.** No credential exists for any of the four target tools. Only n8n
can be stood up locally without an account, so it is the one integration that can be verified
end-to-end by execution. HubSpot, PostHog and Clay all require the user to create an account and
authenticate, so the work for those is: build the boundary, test it against recorded payload shapes and
a local fake, and write exact setup instructions — while being explicit in the README about what is
verified and what is not.

`.env` at baseline pins demo mode and contains no secrets:

```
ENV=development
LLM_ENABLED=false
HUBSPOT_LIVE_WRITES_ENABLED=false
```

## Phase 3 preservation rule

Every gate above must still pass at the end of Phase 3, and no Phase 2 behaviour may regress. Where a
Phase 3 change alters a Phase 2 number (as the seed inevitably will), the change is recorded in the
final report rather than quietly absorbed.
