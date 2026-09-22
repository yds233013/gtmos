{{ config(materialized = 'table') }}

-- Campaign performance by ISO week. Activity metrics are counted in the week the activity happened;
-- opportunity metrics are counted in the week the opportunity was opened and attributed with the
-- opportunity's own `source_campaign_id` (single-touch source attribution). The multi-touch models
-- live in the API's attribution service and are deliberately not duplicated here.
--
-- Opens are carried for completeness but no rate is derived from them: Apple Mail Privacy Protection
-- and image proxies make open tracking unreliable.

with activities as (

    select
        workspace_id,
        campaign_id,
        account_id,
        activity_type,
        occurred_week
    from {{ ref('stg_activities') }}
    where campaign_id is not null

),

campaigns as (

    select
        campaign_id,
        campaign_key,
        campaign_name,
        campaign_status,
        channel,
        persona,
        trigger_signal
    from {{ ref('stg_campaigns') }}

),

opportunities as (

    select
        workspace_id,
        campaign_id,
        amount_usd,
        opened_at,
        is_won
    from {{ ref('stg_opportunities') }}
    where campaign_id is not null

),

activity_weekly as (

    select
        workspace_id,
        campaign_id,
        occurred_week as activity_week,
        count(*) filter (where activity_type = 'email_sent')       as emails_sent,
        count(*) filter (where activity_type = 'email_delivered')  as emails_delivered,
        count(*) filter (where activity_type = 'email_bounced')    as emails_bounced,
        count(*) filter (where activity_type = 'email_opened')     as emails_opened,
        count(*) filter (where activity_type = 'email_replied')    as replies,
        count(*) filter (where activity_type = 'positive_reply')   as positive_replies,
        count(*) filter (where activity_type = 'meeting_booked')   as meetings_booked,
        count(*) filter (where activity_type = 'meeting_held')     as meetings_held,
        count(distinct account_id) filter (where activity_type = 'email_sent') as accounts_emailed
    from activities
    group by 1, 2, 3

),

opportunity_weekly as (

    select
        workspace_id,
        campaign_id,
        date_trunc('week', opened_at)::date          as activity_week,
        count(*)                                     as opportunities_created,
        sum(amount_usd)                              as pipeline_usd,
        count(*) filter (where is_won)               as opportunities_won,
        coalesce(sum(amount_usd) filter (where is_won), 0) as won_revenue_usd
    from opportunities
    group by 1, 2, 3

),

weeks as (

    select workspace_id, campaign_id, activity_week from activity_weekly
    union
    select workspace_id, campaign_id, activity_week from opportunity_weekly

)

select
    {{ surrogate_key(['w.workspace_id', 'w.campaign_id', 'w.activity_week']) }} as outbound_performance_key,
    w.workspace_id,
    w.campaign_id,
    c.campaign_key,
    c.campaign_name,
    c.campaign_status,
    c.channel,
    c.persona,
    c.trigger_signal,
    w.activity_week,
    coalesce(a.emails_sent, 0)          as emails_sent,
    coalesce(a.emails_delivered, 0)     as emails_delivered,
    coalesce(a.emails_bounced, 0)       as emails_bounced,
    coalesce(a.emails_opened, 0)        as emails_opened,
    coalesce(a.replies, 0)              as replies,
    coalesce(a.positive_replies, 0)     as positive_replies,
    coalesce(a.meetings_booked, 0)      as meetings_booked,
    coalesce(a.meetings_held, 0)        as meetings_held,
    coalesce(a.accounts_emailed, 0)     as accounts_emailed,
    coalesce(o.opportunities_created, 0) as opportunities_created,
    coalesce(o.pipeline_usd, 0)::numeric(18, 2)      as pipeline_usd,
    coalesce(o.opportunities_won, 0)    as opportunities_won,
    coalesce(o.won_revenue_usd, 0)::numeric(18, 2)   as won_revenue_usd,
    round(coalesce(a.emails_delivered, 0)::numeric / nullif(a.emails_sent, 0), 4) as delivery_rate,
    round(coalesce(a.replies, 0)::numeric / nullif(a.emails_sent, 0), 4)          as reply_rate,
    round(coalesce(a.positive_replies, 0)::numeric / nullif(a.replies, 0), 4)     as positive_reply_share,
    round(coalesce(a.meetings_held, 0)::numeric / nullif(a.emails_sent, 0), 4)    as meeting_rate
from weeks w
left join activity_weekly a
    on a.workspace_id = w.workspace_id
    and a.campaign_id = w.campaign_id
    and a.activity_week = w.activity_week
left join opportunity_weekly o
    on o.workspace_id = w.workspace_id
    and o.campaign_id = w.campaign_id
    and o.activity_week = w.activity_week
left join campaigns c on c.campaign_id = w.campaign_id
