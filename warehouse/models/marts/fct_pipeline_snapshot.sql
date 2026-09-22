{{
    config(
        materialized = 'table',
        indexes = [{'columns': ['opportunity_id'], 'unique': True}]
    )
}}

-- One row per opportunity with the account, campaign and owner attributes a pipeline review needs,
-- so the deal table can be filtered by segment or owner without re-joining the operational schema.

with opportunities as (

    select
        opportunity_id,
        workspace_id,
        account_id,
        owner_id,
        campaign_id,
        opportunity_name,
        deal_stage,
        lead_source,
        lost_reason,
        amount_usd,
        opened_at,
        closed_at,
        expected_close_date,
        is_won,
        is_lost,
        is_open
    from {{ ref('stg_opportunities') }}

),

accounts as (

    select
        account_id,
        account_name,
        domain,
        industry,
        segment,
        region,
        score_grade,
        icp_score
    from {{ ref('stg_accounts') }}

),

campaigns as (

    select campaign_id, campaign_key, campaign_name, channel from {{ ref('stg_campaigns') }}

),

owners as (

    select user_id, user_name, team from {{ ref('stg_users') }}

),

first_contact as (

    select
        entity_id as account_id,
        min(changed_at) as first_contacted_at
    from {{ ref('stg_stage_transitions') }}
    where pipeline = 'funnel'
      and entity_type = 'account'
      and to_stage = 'contacted'
    group by 1

)

select
    o.opportunity_id,
    o.workspace_id,
    o.account_id,
    a.account_name,
    a.domain,
    a.industry,
    a.segment,
    a.region,
    a.score_grade,
    a.icp_score,
    o.opportunity_name,
    o.deal_stage,
    o.lead_source,
    o.lost_reason,
    o.campaign_id,
    c.campaign_key,
    c.campaign_name,
    c.channel                       as campaign_channel,
    o.owner_id,
    u.user_name                     as owner_name,
    u.team                          as owner_team,
    o.amount_usd,
    o.opened_at,
    o.closed_at,
    o.expected_close_date,
    fc.first_contacted_at,
    o.is_won,
    o.is_lost,
    o.is_open,
    o.campaign_id is not null       as is_campaign_sourced,
    case when o.is_open then o.amount_usd else 0 end::numeric(18, 2) as open_pipeline_usd,
    case when o.is_won then o.amount_usd else 0 end::numeric(18, 2)  as won_revenue_usd,
    -- Age is measured to close for finished deals and to now() for live ones, so an open deal's age
    -- keeps growing while a closed deal's stops at the close date.
    (extract(epoch from (coalesce(o.closed_at, current_timestamp) - o.opened_at)) / 86400)::int as age_days,
    case
        when fc.first_contacted_at is null then null
        else (extract(epoch from (o.opened_at - fc.first_contacted_at)) / 86400)::int
    end as days_from_first_contact_to_open
from opportunities o
left join accounts a        on a.account_id = o.account_id
left join campaigns c       on c.campaign_id = o.campaign_id
left join owners u          on u.user_id = o.owner_id
left join first_contact fc  on fc.account_id = o.account_id
