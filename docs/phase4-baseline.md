# Phase 4 baseline

The state of the repository at the start of the release-readiness phase. Recorded so that every change
Phase 4 makes is a diff against something written down, rather than against memory.

Phase 4 adds **no features**. Its subject is presentation, credibility, documentation, demo quality
and public-release safety.

## Repository

| | |
|---|---|
| Branch | `main` |
| HEAD at start | `3f3e5e4` — *Recapture three screenshots against the cleaned dataset, fix four captions* |
| Commits | 68 |
| Working tree | clean |
| Remote | **none configured** |
| Author identity | Uniform across all 68 commits — no mixed identities to reconcile |

## Mechanically verified counts

Every number below was produced by running the thing that counts it, on the date of this document.
None is quoted from an earlier document. The commands are given so they can be re-run.

| Measure | Value | How it was counted |
|---|---:|---|
| Backend unit tests | **210** | `pytest --collect-only -q tests/unit` |
| Backend integration tests | **255** | `pytest --collect-only -q tests/integration` |
| Frontend component tests | **14** | `npx vitest run` |
| End-to-end tests | **25** | `npx playwright test --list` |
| dbt **models** | **19** | `target/manifest.json`, `resource_type == "model"` |
| dbt **tests** | **113** | `target/manifest.json`, `resource_type == "test"` |
| API operations | **90** | `openapi.json`, counting HTTP methods |
| API paths | **86** | `openapi.json`, counting path entries |
| Database tables | **40** | `information_schema`, excluding `alembic_version` |
| n8n workflow definitions | **6** | files in `integrations/n8n/` |
| Next.js pages | **21** | `page.tsx` files under `apps/web/src/app` |
| Seeded accounts | **2,006** | `select count(*) from accounts` |

**The distinction that caused a real error in Phase 3 and must not recur:** `dbt build` reports
`TOTAL=132`, which is 19 models **plus** 113 tests. It is not a test count. The same class of mistake
is available for API *paths* (86) versus *operations* (90), and for Playwright *files* versus *cases*.
Any public claim must say which of these it means.

## Verified gate results carried into Phase 4

All green at `3f3e5e4`:

- `make lint` — ruff + eslint clean
- `make typecheck` — mypy strict + tsc clean
- backend suite — 465 passed, 1 skipped (the skip is deliberate and states its reason)
- `npx vitest run` — 14 passed
- `make e2e` — 25 passed
- `make warehouse` — `PASS=132 ERROR=0` (19 models + 113 tests)
- `make golden-flow` and `VIA_N8N=1` — 20/20 on both transports
- migrations apply from empty on a scratch database; `alembic check` reports no model drift
- `docker compose build api web` — both images build; the API image serves live data

## Security posture at baseline

- **No secret has ever been committed.** All 742 blobs across all of history were scanned for
  `sk-ant-*`, `pat-na*`/`pat-eu*`, `xox[baprs]-*`, `AKIA*`, `gh[pousr]_*`, `phc_*` and PEM private-key
  headers. Zero matches.
- The two locally generated development secrets that live in `.env` were searched for **by value**
  across all of history. Zero matches — `.env` has never been committed and is git-ignored.
- `.env.example` contains no live values; every credential line is commented out.
- Every email address found anywhere in history is a synthetic fixture on a reserved `.example`
  domain or an obvious placeholder, with one exception: the author's own address, which appears in
  commit metadata and is inherent to a public git history rather than a leak.
- One machine-specific path (`/Users/<user>/gtmos`) appeared in a document and is generalised in this
  phase.

## Scope

Phase 4 changes application code only where it fixes a bug, improves demo comprehension, improves
public-demo safety, improves visual presentation, fixes documentation drift, or fixes a release issue.
Everything else it touches is presentation and documentation.
