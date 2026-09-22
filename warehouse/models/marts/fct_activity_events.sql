{{
    config(
        materialized = 'incremental',
        unique_key = 'activity_id',
        incremental_strategy = 'merge',
        on_schema_change = 'append_new_columns',
        indexes = [
            {'columns': ['activity_id'], 'unique': True},
            {'columns': ['occurred_at']},
        ]
    )
}}

-- The engagement event stream, one row per activity, built incrementally.
--
-- Incremental semantics: a normal run only reads activities newer than
-- `max(occurred_at) - {{ var('activity_late_arrival_days') }} days` already in the table. The lookback exists because
-- activity is ingested from ESP webhooks and CRM syncs that can deliver hours or days late; without
-- it, a delivery event that arrives after its week has been built would never be picked up. The merge
-- strategy on `activity_id` makes reprocessing that overlap idempotent, and a corrected row (for
-- example a bounce reclassified by the ESP) overwrites the old one instead of duplicating it.
--
-- Anything older than the lookback -- a backfill, a changed definition, a re-seeded demo database --
-- needs `dbt build --select fct_activity_events --full-refresh`, which rebuilds the table from zero.

with activities as (

    select
        activity_id,
        workspace_id,
        account_id,
        contact_id,
        campaign_id,
        user_id,
        activity_type,
        channel,
        activity_status,
        occurred_at,
        occurred_date,
        occurred_week,
        activity_source,
        data_origin
    from {{ ref('stg_activities') }}

    {% if is_incremental() %}
    where occurred_at >= (
        select coalesce(max(occurred_at), '1900-01-01'::timestamptz)
             - interval '{{ var("activity_late_arrival_days") }} days'
        from {{ this }}
    )
    {% endif %}

),

campaigns as (

    select campaign_id, campaign_key, campaign_name from {{ ref('stg_campaigns') }}

),

accounts as (

    select account_id, account_name, segment, region, score_grade from {{ ref('stg_accounts') }}

)

select
    a.activity_id,
    a.workspace_id,
    a.account_id,
    acc.account_name,
    acc.segment,
    acc.region,
    acc.score_grade,
    a.contact_id,
    a.campaign_id,
    c.campaign_key,
    c.campaign_name,
    a.user_id,
    a.activity_type,
    a.channel,
    a.activity_status,
    a.occurred_at,
    a.occurred_date,
    a.occurred_week,
    a.activity_type in ('email_sent', 'email_delivered', 'email_opened', 'email_replied',
                        'email_bounced', 'positive_reply')            as is_email_event,
    a.activity_type = 'email_sent'                                    as is_send,
    a.activity_type in ('email_replied', 'positive_reply')            as is_reply,
    a.activity_type = 'positive_reply'                                as is_positive_reply,
    a.activity_type in ('meeting_booked', 'meeting_held')             as is_meeting,
    -- The touch types the attribution service credits. Opens are excluded on purpose.
    a.activity_type in ('email_sent', 'email_replied', 'meeting_held', 'webinar_attended', 'linkedin')
                                                                      as is_attributable_touch,
    a.activity_source,
    a.data_origin,
    current_timestamp as dbt_loaded_at
from activities a
left join campaigns c   on c.campaign_id = a.campaign_id
left join accounts acc  on acc.account_id = a.account_id
