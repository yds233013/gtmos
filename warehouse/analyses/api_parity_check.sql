-- Parity harness: the warehouse numbers next to the API's semantic layer.
--
-- Compile with `dbt compile --select api_parity_check` and run the compiled SQL against the
-- warehouse, then diff it against:
--   GET /api/v1/analytics/funnel?days=90
--   GET /api/v1/analytics/overview?days=90
--   GET /api/v1/analytics/attribution?days=180
--
-- This is an analysis, not a model: it is never materialised. The windows are relative to
-- current_timestamp, so run it close in time to the API call or the cohort boundary will drift.

with funnel_cohort as (

    select *
    from {{ ref('fct_account_snapshot') }}
    where first_contacted_at >= current_timestamp - interval '90 days'

),

funnel as (

    select 'funnel_90d' as check_name, metric, value
    from (
        select
            count(*)::numeric                                           as cohort_size,
            count(*) filter (where first_engaged_at is not null)::numeric     as engaged,
            count(*) filter (where first_qualified_at is not null)::numeric   as qualified,
            count(*) filter (where first_meeting_at is not null)::numeric     as meeting,
            count(*) filter (where first_opportunity_at is not null)::numeric as opportunity,
            count(*) filter (where first_won_at is not null)::numeric         as won,
            count(*) filter (where first_lost_at is not null)::numeric        as lost
        from funnel_cohort
    ) f,
    lateral (values
        ('cohort_size', f.cohort_size),
        ('engaged', f.engaged),
        ('qualified', f.qualified),
        ('meeting', f.meeting),
        ('opportunity', f.opportunity),
        ('won', f.won),
        ('lost', f.lost)
    ) as v (metric, value)

),

overview as (

    select 'overview_90d' as check_name, metric, value
    from (
        select
            count(*)::numeric                                   as accounts_sourced,
            count(*) filter (where is_icp_account)::numeric     as icp_accounts,
            count(*) filter (where is_high_intent)::numeric     as high_intent_accounts,
            sum(verified_contact_count)::numeric                as contacts_verified,
            sum(open_opportunity_count)::numeric                as open_opportunities,
            sum(open_pipeline_usd)::numeric                     as open_pipeline
        from {{ ref('fct_account_snapshot') }}
    ) a,
    lateral (values
        ('accounts_sourced', a.accounts_sourced),
        ('icp_accounts', a.icp_accounts),
        ('high_intent_accounts', a.high_intent_accounts),
        ('contacts_verified', a.contacts_verified),
        ('open_opportunities', a.open_opportunities),
        ('open_pipeline', a.open_pipeline)
    ) as v (metric, value)

),

overview_pipeline as (

    select 'overview_90d' as check_name, metric, value
    from (
        select
            count(*) filter (where opened_at >= current_timestamp - interval '90 days')::numeric        as opportunities_created,
            sum(amount_usd) filter (where opened_at >= current_timestamp - interval '90 days')          as pipeline_created,
            count(*) filter (where is_won and closed_at >= current_timestamp - interval '90 days')::numeric as won_deals,
            sum(amount_usd) filter (where is_won and closed_at >= current_timestamp - interval '90 days')    as won_revenue
        from {{ ref('fct_pipeline_snapshot') }}
    ) p,
    lateral (values
        ('opportunities_created', p.opportunities_created),
        ('pipeline_created', p.pipeline_created),
        ('won_deals', p.won_deals),
        ('won_revenue', p.won_revenue)
    ) as v (metric, value)

),

attribution as (

    select 'attribution_180d' as check_name, metric, value
    from (
        select
            count(*)::numeric                                           as opportunities,
            sum(amount_usd)                                             as total_pipeline,
            count(*) filter (where first_contacted_at is null)::numeric as unattributed_opportunities,
            coalesce(sum(amount_usd) filter (where first_contacted_at is null), 0) as unattributed_pipeline
        from {{ ref('fct_pipeline_snapshot') }}
        where opened_at >= current_timestamp - interval '180 days'
    ) o,
    lateral (values
        ('opportunities', o.opportunities),
        ('total_pipeline', o.total_pipeline),
        ('unattributed_opportunities', o.unattributed_opportunities),
        ('unattributed_pipeline', o.unattributed_pipeline)
    ) as v (metric, value)

)

select * from funnel
union all select * from overview
union all select * from overview_pipeline
union all select * from attribution
