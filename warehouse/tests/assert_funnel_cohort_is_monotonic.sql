-- Business rule: a cohort funnel can only narrow. Because the cohort is fixed and a stage is counted
-- whenever it was reached, the account set at each stage is a subset of the stage above it, so
-- accounts_reached must never increase as stage_rank grows.
--
-- This catches the classic funnel bug of mixing denominators -- counting "all accounts" at the top
-- and "accounts that hit a stage inside the window" below it, which can produce a step conversion
-- above 100%.

select
    cohort_week,
    stage,
    stage_rank,
    accounts_reached,
    previous_stage_accounts
from {{ ref('fct_funnel_cohort') }}
where previous_stage_accounts is not null
  and accounts_reached > previous_stage_accounts
