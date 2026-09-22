with source as (

    select * from {{ source('gtmos_app', 'activities') }}

)

select
    id                          as activity_id,
    workspace_id,
    account_id,
    contact_id,
    campaign_id,
    user_id,
    sequence_step_id,
    message_draft_id,
    type                        as activity_type,
    nullif(channel, '')         as channel,
    nullif(status, '')          as activity_status,
    nullif(subject, '')         as subject,
    occurred_at,
    occurred_at::date           as occurred_date,
    date_trunc('week', occurred_at)::date as occurred_week,
    source                      as activity_source,
    data_origin,
    dedupe_key
from source
