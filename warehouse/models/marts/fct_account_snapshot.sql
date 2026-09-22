{{
    config(
        materialized = 'table',
        indexes = [
            {'columns': ['account_id'], 'unique': True},
            {'columns': ['workspace_id']},
        ]
    )
}}

-- One row per live account: the current state plus the lifetime aggregates the command center reads.
-- Merged duplicates are excluded here, exactly as analytics._live() excludes them in the API.

with accounts as (

    select
        account_id,
        workspace_id,
        owner_id,
        account_name,
        domain,
        industry,
        segment,
        region,
        country,
        funding_stage,
        employee_count,
        annual_revenue_usd,
        funnel_stage,
        lifecycle_stage,
        is_customer,
        account_source,
        icp_score,
        score_grade,
        intent_score,
        score_updated_at,
        created_at
    from {{ ref('stg_accounts') }}
    where is_live

),

owners as (

    select user_id, user_name, team, territory from {{ ref('stg_users') }}

),

funnel_transitions as (

    select
        entity_id as account_id,
        to_stage,
        min(changed_at) as first_reached_at
    from {{ ref('stg_stage_transitions') }}
    where pipeline = 'funnel'
      and entity_type = 'account'
    group by 1, 2

),

funnel_milestones as (

    select
        account_id,
        min(first_reached_at) filter (where to_stage = 'contacted')   as first_contacted_at,
        min(first_reached_at) filter (where to_stage = 'engaged')     as first_engaged_at,
        min(first_reached_at) filter (where to_stage = 'qualified')   as first_qualified_at,
        min(first_reached_at) filter (where to_stage = 'meeting')     as first_meeting_at,
        min(first_reached_at) filter (where to_stage = 'opportunity') as first_opportunity_at,
        min(first_reached_at) filter (where to_stage = 'won')         as first_won_at,
        min(first_reached_at) filter (where to_stage = 'lost')        as first_lost_at,
        max(first_reached_at)                                         as last_stage_change_at
    from funnel_transitions
    group by 1

),

activity_rollup as (

    select
        account_id,
        min(occurred_at) as first_touch_at,
        max(occurred_at) as last_touch_at,
        count(*) filter (where activity_type = 'email_sent')     as emails_sent,
        count(*) filter (where activity_type = 'email_replied')  as replies,
        count(*) filter (where activity_type = 'positive_reply') as positive_replies,
        count(*) filter (where activity_type = 'meeting_held')   as meetings_held
    from {{ ref('stg_activities') }}
    where account_id is not null
    group by 1

),

signal_rollup as (

    select
        account_id,
        count(*)                       as signal_count,
        count(distinct signal_type)    as distinct_signal_types,
        max(observed_at)               as last_signal_at
    from {{ ref('stg_signals') }}
    group by 1

),

opportunity_rollup as (

    select
        account_id,
        count(*)                                                as opportunity_count,
        coalesce(sum(amount_usd), 0)                            as pipeline_usd,
        count(*) filter (where is_won)                          as won_count,
        coalesce(sum(amount_usd) filter (where is_won), 0)      as won_revenue_usd,
        count(*) filter (where is_open)                         as open_opportunity_count,
        coalesce(sum(amount_usd) filter (where is_open), 0)     as open_pipeline_usd,
        min(opened_at)                                          as first_opportunity_opened_at,
        max(coalesce(closed_at, opened_at))                     as last_opportunity_event_at
    from {{ ref('stg_opportunities') }}
    group by 1

),

contact_rollup as (

    select
        account_id,
        count(*)                                as contact_count,
        count(*) filter (where is_email_valid)  as verified_contact_count
    from {{ ref('stg_contacts') }}
    where is_live and account_id is not null
    group by 1

)

select
    a.account_id,
    a.workspace_id,
    a.account_name,
    a.domain,
    a.industry,
    a.segment,
    a.region,
    a.country,
    a.funding_stage,
    a.employee_count,
    a.annual_revenue_usd,
    a.funnel_stage,
    a.lifecycle_stage,
    a.is_customer,
    a.account_source,
    a.icp_score,
    a.score_grade,
    a.intent_score,
    a.score_grade in ('A', 'B')                             as is_icp_account,
    a.intent_score >= 50 and coalesce(a.score_grade, '') <> 'X' as is_high_intent,
    a.score_updated_at,
    a.owner_id,
    o.user_name                                             as owner_name,
    o.team                                                  as owner_team,
    o.territory                                             as owner_territory,
    a.created_at                                            as account_created_at,
    act.first_touch_at,
    act.last_touch_at,
    m.first_contacted_at,
    m.first_engaged_at,
    m.first_qualified_at,
    m.first_meeting_at,
    m.first_opportunity_at,
    m.first_won_at,
    m.first_lost_at,
    m.last_stage_change_at,
    m.first_contacted_at is not null                        as has_been_contacted,
    sig.last_signal_at,
    coalesce(sig.signal_count, 0)                           as signal_count,
    coalesce(sig.distinct_signal_types, 0)                  as distinct_signal_types,
    coalesce(c.contact_count, 0)                            as contact_count,
    coalesce(c.verified_contact_count, 0)                   as verified_contact_count,
    coalesce(act.emails_sent, 0)                            as emails_sent,
    coalesce(act.replies, 0)                                as replies,
    coalesce(act.positive_replies, 0)                       as positive_replies,
    coalesce(act.meetings_held, 0)                          as meetings_held,
    coalesce(opp.opportunity_count, 0)                      as opportunity_count,
    coalesce(opp.pipeline_usd, 0)::numeric(18, 2)           as pipeline_usd,
    coalesce(opp.won_count, 0)                              as won_count,
    coalesce(opp.won_revenue_usd, 0)::numeric(18, 2)        as won_revenue_usd,
    coalesce(opp.open_opportunity_count, 0)                 as open_opportunity_count,
    coalesce(opp.open_pipeline_usd, 0)::numeric(18, 2)      as open_pipeline_usd,
    opp.first_opportunity_opened_at,
    opp.last_opportunity_event_at,
    greatest(
        coalesce(act.last_touch_at, a.created_at),
        coalesce(sig.last_signal_at, a.created_at),
        coalesce(m.last_stage_change_at, a.created_at)
    )                                                       as last_activity_at
from accounts a
left join owners o              on o.user_id = a.owner_id
left join funnel_milestones m   on m.account_id = a.account_id
left join activity_rollup act   on act.account_id = a.account_id
left join signal_rollup sig     on sig.account_id = a.account_id
left join opportunity_rollup opp on opp.account_id = a.account_id
left join contact_rollup c      on c.account_id = a.account_id
