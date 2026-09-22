# Final review

Four reviewer perspectives applied to the finished V1. Findings marked **fixed** were addressed during the
build (most with regression tests); the rest are open, with rationale.

## Reviewer 1: GTM Engineer

*Does this demonstrate genuine understanding of modern GTM systems?*

**Strengths**
- Covers the real GTM engineering surface area, not just a dashboard: ICP definition, an enrichment waterfall
  with provenance and merge policy, signal decay, explainable scoring, buying-committee inference,
  lead-to-account matching (free-mail blocklist, `$groups.company`), territory routing with conflict
  resolution, forward-only lifecycle, CRM mapping, reverse ETL, PQL routing, experiments and attribution.
- Makes GTM judgment calls a practitioner would recognize: upserting HubSpot companies on a custom unique
  property instead of `domain`; treating email opens as untrustworthy; account-level randomization; refusing to
  declare experiment winners on secondary metrics; multi-threading to the economic buyer once an opportunity is
  open; routing gaps surfacing as "stuck after reply".
- The Stack Inspector frames the GTM *system* as something to operate, which is what distinguishes a GTM
  Engineer from a tool admin.

**Findings**
- Scoring's predictive power in the demo data is modest (meeting rate B ≈ C). **Open, by design**: the page
  says so and explains the right next step (a holdout backtest). Faking a clean monotonic curve would be
  dishonest.
- Signal sources are simulated feeds; there's no real funding/news/job-board ingestion. **Open**: the ingestion
  contract (`POST /signals`, n8n template 01) is where a real feed plugs in.
- No sequencer integration (Outreach/Salesloft/Apollo sequences). **Open, intentional**: READY is the
  hand-off, and sending is out of scope for safety.

## Reviewer 2: Staff Software Engineer

*Is the architecture coherent? Are core systems tested? Are integrations safe? Is important logic
deterministic?*

**Strengths**
- Clear layering: pure `domain/` (no DB, no clock) → `services/` (transactions, audit) → `integrations/`
  (protocols with demo and live implementations) → thin routes.
- Idempotency is structural: unique keys on signals, workflow runs, webhook events and external records;
  savepoint-guarded run creation; payload hashing; side effects keyed by run id.
- Tests exercise behavior rather than lines: 57 unit, 67 Postgres integration (each in a rolled-back
  transaction), 14 component, 22 E2E against the production build. mypy --strict, ruff, ESLint and tsc are clean.
- Migrations apply from scratch and `alembic check` reports no drift.

**Bugs found and fixed during the build**
| Bug | How it was found | Fix |
|---|---|---|
| Waterfall reused a provider's cached response that lacked fields requested at later positions | unit test | first call requests every supported field for the run |
| Unsigned (rejected) webhook delivery blocked a later valid signed delivery: idempotency-key poisoning | integration test | rejected events never count as seen; re-evaluated in place |
| Wilson interval lower bound returned 5.5e-17 for zero successes (CI above the rate) | integration test | exact edges clamped; regression test |
| Evidence refs like `[E12]` failed the numbers guardrail, so call-prep drafts could never be approved | agent review | refs stripped before numeric extraction; regression test |
| `include_synthetic=false` and JSON text filters returned 500 (JSON variant lacks `.astext`) | browser QA | portable `.as_string()` |
| `GROUP BY 1` rejected by SQLAlchemy in pipeline analytics | smoke test | labeled expressions |
| Apollo adapter read `response.elapsed` before the body was read | mocked-HTTP test | monotonic clock timing |
| Seed hung forever above 1,820 accounts (name space exhausted) | seed run | qualifiers added after repeated collisions |
| Seeded failure history attached failures to non-existent steps and mismatched conditions | agent review | real condition evaluation; failures on actual steps |
| An API key present in the shell would have made seeds call the live LLM | manual review | live LLM requires `LLM_ENABLED=true` in addition to a key |
| A webhook that failed processing was acked as a duplicate when the sender retried | doc review | failed events are reprocessed on redelivery; integration test |
| A contact holding two committee roles appeared twice in the evidence pack | doc review | evidence keyed by record; unit test |
| HubSpot v3 verifier accepted far-future timestamps | doc review | rejected beyond the 5-minute skew; unit test |
| Reverse ETL re-sent `name`/`domain`, which could overwrite rep edits in HubSpot | doc review | updates carry only `gtmos_*` fields; integration test |
| HubSpot property group built as `companieinformation`; custom properties never auto-created | doc review | explicit group map; `ensure_properties_once` before first live sync |
| n8n template 04 read a domain HubSpot events don't carry; compose lacked n8n 2.x env settings | doc review | HubSpot lookup by objectId; env vars added; re-imported into n8n 2.40.5 |

**Open findings**
- Single-operator auth. Acceptable for a demo, documented; production needs OIDC + RBAC + row-level scoping.
- Some request paths issue many small queries (account detail ≈ 20). Fine at this scale; would need
  consolidation or caching at 10×.
- RQ is a pragmatic queue. Exactly-once isn't claimed: steps are idempotent, so at-least-once delivery is safe.
- `RealHubSpotAdapter` and `ApolloOrganizationProvider` are contract-tested with mocked HTTP but not against
  live accounts.

## Reviewer 3: Startup founder

*Can I understand the business value within 60 seconds?*

**Strengths**
- The Overview states the purpose in one sentence and shows the funnel, pipeline and "Act now" accounts
  immediately. The Guided Demo panel gives a five-step path.
- The flagship account tells a coherent story end to end: funding + new VP of AI + agent launch + PLG usage →
  A-grade score with reasons → cited research → a multi-threaded draft → approval → routing → CRM.
- The experiment page answers "did personalization work?" honestly, which builds trust.

**Findings**
- Density is high for a first-time viewer. **Mitigated**: the demo script and guided panel point to the five
  pages that matter; the DEMO banner keeps the framing clear.
- Dollar figures are synthetic. **Mitigated**: labeled everywhere; nothing claims real revenue.

## Reviewer 4: Recruiter

*Can I understand why this candidate is relevant to a GTM Engineer position?*

- The README maps directly to GTM Engineer job requirements researched in `docs/market-research.md`: CRM
  integration (HubSpot), enrichment waterfalls (Clay-style), signal-based selling, routing, reverse ETL,
  workflow automation (n8n), product analytics (PostHog), AI research and personalization with guardrails, and
  data quality.
- Resume bullets are scoped to verifiable repository facts (`docs/resume.md`) with explicit guidance on what
  not to claim.
- **Suggestion (open):** record a 3-minute walkthrough video of the demo script for the portfolio link. It
  needs a human voice.

## Verdict

V1 meets the P0 and P1 bar from the brief and most P2 items (Copilot, reverse ETL, advanced committee,
workflow visualization). The highest-value next steps are in the handoff: a live HubSpot sandbox run, a real
signal feed, a scoring backtest, OIDC auth, and an offline eval set for the LLM path.
