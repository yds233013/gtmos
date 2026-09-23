# `apps/web` — the GTMOS interface

A Next.js 16 App Router application. Every data page renders on the server per request: `src/lib/api.ts`
is `server-only` and calls `await connection()`, which opts the page out of prerendering, so there is no
static half to put on a CDN and no client-side data-fetching layer to keep in sync. The browser's
`/api/v1/*` calls are rewritten to the FastAPI service server-side (`next.config.ts`), which is why the
API's CORS allow-list protects nothing on its own and the `READ_ONLY` flag is the gate that matters.

Run it from the repository root rather than here — `make dev` starts the database, applies migrations,
seeds the demo dataset and runs both processes. See the root [README](../../README.md).

```
src/app          routes; every data page is server-rendered per request
src/components   UI primitives, charts, and the per-surface panels
src/lib          the server-only API client, formatters and types
e2e              Playwright specs, run against a production build
```

Tests: `npm run test` (Vitest, component and helper level) and `npx playwright test` (end to end, needs
the stack running). Both are wired into the root `Makefile` as `make test-web` and `make e2e`.
