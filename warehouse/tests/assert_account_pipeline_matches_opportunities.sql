-- Business rule: the account rollup and the opportunity grain must agree. If fct_account_snapshot
-- and fct_pipeline_snapshot disagree on a single account's pipeline, the command center and the deal
-- table are showing different numbers for the same question.
--
-- Accounts merged into another record are excluded from the snapshot by design, so their deals are
-- excluded from the comparison too.

with account_level as (

    select account_id, opportunity_count, pipeline_usd, won_revenue_usd
    from {{ ref('fct_account_snapshot') }}

),

opportunity_level as (

    select
        p.account_id,
        count(*) as opportunity_count,
        sum(p.amount_usd) as pipeline_usd,
        sum(p.won_revenue_usd) as won_revenue_usd
    from {{ ref('fct_pipeline_snapshot') }} p
    join account_level a on a.account_id = p.account_id
    group by 1

)

select
    a.account_id,
    a.opportunity_count as snapshot_opportunities,
    o.opportunity_count as deal_opportunities,
    a.pipeline_usd      as snapshot_pipeline,
    o.pipeline_usd      as deal_pipeline
from account_level a
join opportunity_level o on o.account_id = a.account_id
where a.opportunity_count <> o.opportunity_count
   or a.pipeline_usd <> o.pipeline_usd
   or a.won_revenue_usd <> o.won_revenue_usd
