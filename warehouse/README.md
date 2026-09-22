# GTMOS warehouse

A dbt project that models the GTMOS operational database into analytics marts.

The API already has a semantic layer in Python (`apps/api/src/gtmos/services/analytics.py`). This
project expresses the same definitions in SQL, where a BI tool, a notebook or a reverse-ETL job can
reach them without going through the application. The two are checked against each other: see
[Parity with the API](#parity-with-the-api).

The architecture argument — why an operational database *and* a warehouse — is in
[`docs/warehouse.md`](../docs/warehouse.md).

## Running it

Prerequisites: Postgres running and seeded (`make dev-deps && make migrate && make seed`). dbt is a
dev dependency of the API project, so no separate install is needed.

```bash
make warehouse         # dbt build: runs every model, then every test
make warehouse-docs    # dbt docs generate
```

Or directly:

```bash
cd apps/api
uv run dbt build   --project-dir ../../warehouse --profiles-dir ../../warehouse
uv run dbt test    --project-dir ../../warehouse --profiles-dir ../../warehouse
uv run dbt build   --project-dir ../../warehouse --profiles-dir ../../warehouse --select fct_funnel_cohort+
```

`profiles.yml` lives in the project directory and defaults to the compose Postgres on host port
56432. Every field is overridable:

| Variable | Default |
| --- | --- |
| `GTMOS_WAREHOUSE_HOST` | `localhost` |
| `GTMOS_WAREHOUSE_PORT` | `56432` |
| `GTMOS_WAREHOUSE_USER` | `gtmos` |
| `GTMOS_WAREHOUSE_PASSWORD` | `gtmos` |
| `GTMOS_WAREHOUSE_DB` | `gtmos` |
| `GTMOS_WAREHOUSE_SCHEMA` | `analytics` |

Marts land in `analytics`; staging views land in `analytics_staging` (dbt's standard custom-schema
behaviour). Nothing is ever written to `public`, which the application owns.

## Layout

```
warehouse/
├── dbt_project.yml          project config and vars
├── profiles.yml             connection, env-var driven
├── macros/surrogate_key.sql local stand-in for dbt_utils (no package dependencies)
├── models/
│   ├── staging/             views, 1:1 with source tables, renaming and typing only
│   └── marts/               tables, the business logic
├── tests/                   singular tests encoding GTM business rules
└── analyses/                api_parity_check.sql, compiled but never materialised
```

## Staging

Views over `public`, one per source table, with no business logic: rename to a consistent
`<entity>_id` key convention, `nullif('')` empty strings that the ORM writes for unset enums,
pre-cast timestamps to `date` and ISO `week`, and derive obvious booleans (`is_won`, `is_live`,
`is_email_valid`) so no mart has to repeat a string comparison.

`stg_accounts`, `stg_users`, `stg_contacts`, `stg_campaigns`, `stg_activities`, `stg_signals`,
`stg_opportunities`, `stg_stage_transitions`, `stg_message_drafts`, `stg_icp_scores`,
`stg_engagements`, `stg_experiment_assignments`, `stg_experiment_outcomes`.

Two conventions worth naming:

- **Merged records are kept, not filtered.** Deduplication sets `merged_into_id`; staging exposes
  `is_live` and the marts do the filtering. A staging view that silently dropped rows would break
  the relationship tests that point at it.
- **`account_funnel_stage` and `deal_stage` are different things.** An account moves through
  prospect → contacted → … → won/lost; a deal moves through discovery → … → closed_won/closed_lost.
  They are never mixed in a single column.

## Marts

| Model | Grain | What it answers |
| --- | --- | --- |
| `fct_account_snapshot` | account | Who is in the funnel, at what score, owned by whom, with how much pipeline |
| `fct_funnel_cohort` | cohort week × stage | How far each weekly contacted cohort progressed |
| `fct_outbound_performance` | campaign × week | Sends → delivered → replies → meetings → pipeline |
| `fct_pipeline_snapshot` | opportunity | Deal table with account, campaign and owner attributes |
| `dim_signal_effect` | signal type | Opportunity rate with vs without each buying signal |
| `fct_activity_events` | activity | The event stream, built incrementally |

### `fct_account_snapshot`

Current state (score, grade, segment, owner, funnel stage) plus lifetime rollups (first touch, first
contact, last signal, activity counts, opportunity and pipeline totals). Named *snapshot* rather
than *daily* because it holds one row per account as of the last build, not one row per account-day;
a daily history would need a dbt snapshot or a scheduled insert, which the demo does not run.

Merged duplicates are excluded, matching `analytics._live()` in the API.

The `first_*_at` milestone columns are what make the cohort funnel a single `count(*) filter (...)`
over this table rather than a re-derivation from the transition log.

### `fct_funnel_cohort`

The cohort definition is the whole point. An account belongs to the week of its **first** `contacted`
transition, and a stage is counted **whenever** the account reached it, including weeks later. The
denominator is therefore fixed at the cohort size.

The alternative — "all accounts" at the top and "accounts that hit a stage during the window" below
— mixes denominators and can produce a step conversion above 100%. `assert_funnel_cohort_is_monotonic`
exists to catch exactly that.

`prospect` is excluded because it precedes the cohort entry point; `lost` is carried as the
`cohort_accounts_lost` column rather than a stage row, since it is terminal and sits outside the
ordered funnel.

**Grain caveat.** This table is grained by *week*, so it cannot reproduce the API's arbitrary
`?days=90` window: filtering `cohort_week >= current_date - 90` clips the oldest partial week and
filtering on `date_trunc('week', ...)` over-includes it. Against the demo data those two boundaries
give 488 and 537 contacted accounts respectively, where the API reports 521 — all three are correct
for the window they describe. Exact-window parity is checked against `fct_account_snapshot`, whose
`first_contacted_at` keeps full timestamp precision, which is what `analyses/api_parity_check.sql`
uses. Use this table for trend and cohort-maturity questions, and the snapshot for "last N days".

### `fct_outbound_performance`

Activity metrics sit in the week the activity happened; opportunity metrics sit in the week the
opportunity opened, attributed by the opportunity's own `source_campaign_id` — single-touch source
attribution. The multi-touch models (first touch, last touch, linear, U-shaped) stay in the API's
attribution service; duplicating them here would give the organisation two attribution answers.

Opens are stored but no rate is derived from them. Apple Mail Privacy Protection and image proxies
pre-fetch images, so an open count measures the proxy, not the reader.

### `fct_pipeline_snapshot`

One row per opportunity with account, campaign and owner attributes denormalised on, plus `age_days`
(to close for finished deals, to now for open ones) and `days_from_first_contact_to_open`.

`first_contacted_at` is null for deals on accounts outbound never touched. That is not a data
quality problem — it is the inbound, partner and referral population, and it is exactly the set the
attribution service reports as unattributed.

### `dim_signal_effect`

Per signal type: accounts that carried the signal, their opportunity rate, the rate for accounts
without it, and the lift between them. Raw counts sit next to every rate and `is_low_sample` flags
anything under 30 accounts, so a two-account "4× lift" reads as a two-account lift.

Association, not causation. Signal-triggered campaigns target the same accounts, so part of every
lift here is the campaign rather than the signal. Controlled experiments are the API's job.

### `fct_activity_events` — the incremental model

Materialised `incremental` with `unique_key = 'activity_id'` and `incremental_strategy = 'merge'`.

A normal run reads only:

```sql
where occurred_at >= (select max(occurred_at) from {{ this }})
                     - interval '3 days'   -- var: activity_late_arrival_days
```

Three things this encodes:

1. **The high-water mark is `occurred_at`, not a load timestamp.** Activity is what the model is
   about, so the watermark is the event time.
2. **The lookback handles late-arriving data.** ESP webhooks and CRM syncs deliver hours or days
   late. Filtering strictly on `> max(occurred_at)` would silently drop a delivery event that
   arrived after its week was built, and the gap would never be noticed because the row count would
   still grow every run. The lookback window is the honest cost of that: re-reading three days of
   events on every build.
3. **`merge` makes the overlap idempotent.** The same activity re-read on the next run overwrites
   itself instead of duplicating, and a correction (a bounce the ESP reclassifies) lands as an
   update. `dbt_loaded_at` records when each row was last written, so reprocessing is visible.

The lookback cannot fix everything. Backfills, definition changes, and a re-seeded demo database all
need a full rebuild:

```bash
make seed   # or make reset
cd apps/api && uv run dbt build --project-dir ../../warehouse --profiles-dir ../../warehouse \
  --select fct_activity_events --full-refresh
```

In production this is the model that would run on a schedule (hourly, say) while the table models
rebuild nightly.

## Tests

`make warehouse` runs 113 data tests across 19 models; all pass against the seeded demo database.

Generic tests: `unique` and `not_null` on every key, `accepted_values` on funnel stages, deal stages,
ICP grades, segments, email statuses, activity types and experiment metrics, and `relationships`
from each mart back to the staging model it was built from.

Four singular tests encode GTM business rules that hold in this data (each was checked with SQL
before being written — a test that does not hold is not a rule):

| Test | Rule |
| --- | --- |
| `assert_campaign_opportunity_has_prior_contact` | A campaign-sourced opportunity sits on an account that was contacted first, and the contact precedes the opportunity. |
| `assert_funnel_cohort_is_monotonic` | Cohort funnel counts never increase as you go down the funnel. |
| `assert_outbound_delivery_within_sends` | Within a campaign-week, delivered + bounced never exceeds sent, replies never exceed sends, positive replies never exceed replies. |
| `assert_account_pipeline_matches_opportunities` | The account rollup and the opportunity grain agree on every account's opportunity count, pipeline and won revenue. |

The first one is deliberately scoped. "No opportunity exists for an account that was never contacted"
is *false* here: 16 opportunities worth $1,188,000 sit on accounts outbound never touched, all of
them with `lead_source` in (inbound, partner, referral) and no source campaign. Asserting the
stronger rule would have failed the build on correct behaviour, so the test asserts the rule that
actually holds — a *campaign-sourced* deal must have a prior touch — and leaves the inbound
population alone. Those same 16 deals show up in the parity table below as the API's unattributed
pipeline, which is the check that they are understood rather than ignored.

## Parity with the API

`analyses/api_parity_check.sql` recomputes the API's metrics from the marts. Compile it and run the
result against the warehouse:

```bash
cd apps/api
uv run dbt compile --project-dir ../../warehouse --profiles-dir ../../warehouse --select api_parity_check
psql "postgresql://gtmos:gtmos@localhost:56432/gtmos" \
  -f ../../warehouse/target/compiled/gtmos_warehouse/analyses/api_parity_check.sql
```

Measured against the running API on the seeded demo dataset:

**`GET /api/v1/analytics/funnel?days=90`** — every stage matches exactly.

| Stage | API | Warehouse |
| --- | --- | --- |
| cohort size (contacted) | 521 | 521 |
| engaged | 143 | 143 |
| qualified | 93 | 93 |
| meeting | 48 | 48 |
| opportunity | 26 | 26 |
| won | 4 | 4 |
| lost | 20 | 20 |

**`GET /api/v1/analytics/overview?days=90`** — ten of eleven compared metrics match exactly.
(Scores are recomputed by the running app, so absolute grade counts move between runs; what matters
is that both sides move together, which is why the parity check is a query and not a fixture.)

| Metric | API | Warehouse |
| --- | --- | --- |
| accounts_sourced | 2,006 | 2,006 |
| icp_accounts (grade A/B) | 232 | 232 |
| high_intent_accounts | 27 | 27 |
| contacts_verified | 10,241 | 10,241 |
| open_opportunities | 44 | 44 |
| open_pipeline | $3,364,000 | $3,364,000 |
| opportunities_created (90d) | 54 | 54 |
| pipeline_created (90d) | $4,438,000 | $4,438,000 |
| won_deals (90d) | 15 | 15 |
| won_revenue (90d) | $1,176,000 | $1,176,000 |
| **contacts** | **11,819** | **11,805** |

**`GET /api/v1/analytics/attribution?days=180`** — matches on volume and on the unattributed split.

| Metric | API | Warehouse |
| --- | --- | --- |
| opportunities | 76 | 76 |
| total_pipeline | $6,592,000 | $6,592,000 |
| unattributed_opportunities | 16 | 16 |
| unattributed_pipeline | $1,188,000 | $1,188,000 |

Per-campaign, `fct_outbound_performance.pipeline_usd` reproduces the API's **last-touch** column
exactly (ICP generic $2,557,000; PLG $992,000; Series B–D $873,000; AI agent launch $806,000; EMEA
$176,000). It does not reproduce first-touch, linear or U-shaped, and it should not: the warehouse
model credits the deal's recorded source campaign, which in this dataset is the last campaign that
touched the account.

**`GET /api/v1/analytics/signal-correlation?days=180`** — `dim_signal_effect` reproduces it exactly,
including the baseline rate and the lift, for every signal type.

| Signal type | Accounts (API / WH) | With opportunity | Rate | Lift |
| --- | --- | --- | --- | --- |
| funding_round | 413 / 413 | 23 / 23 | 0.0557 | 1.23 |
| tech_adoption | 349 / 349 | 22 / 22 | 0.0630 | 1.46 |
| job_posting | 318 / 318 | 20 / 20 | 0.0629 | 1.43 |
| ai_hiring_surge | 302 / 302 | 16 / 16 | 0.0530 | 1.11 |
| ai_product_launch | 291 / 291 | 17 / 17 | 0.0584 | 1.27 |

Contacted population 1,227 and baseline opportunity rate 0.0489 on both sides.

### Known differences

1. **contacts: 11,819 (API) vs 11,805 (warehouse), a gap of 14.** Real and explained. 14 live
   contacts have no `account_id`. The API counts contacts directly; the warehouse number is a sum of
   a per-account rollup, and an account-grain table cannot hold an account-less contact. The
   verified-contact numbers agree because all 14 are unverified. Fixing it properly means a contact
   grain mart, not a fudge in the rollup — noted rather than papered over.
2. **Window boundaries drift.** The API's `days=90` and the analysis's `interval '90 days'` are both
   relative to the moment they run. A cohort boundary that falls between the two calls moves an
   account in or out. Run the parity check close in time to the API call.
3. **`conversion_from_previous` rounds differently.** The API carries the last non-zero stage count
   forward when a stage is empty; `fct_funnel_cohort` uses a plain `lag()` and returns null instead.
   At the weekly grain, empty intermediate stages are common, so the plain lag is the more honest
   answer; the counts themselves are identical either way.
4. **The warehouse has no equivalent of the multi-touch attribution models.** That logic lives in
   `apps/api/src/gtmos/domain/attribution.py` and is intentionally not duplicated.
