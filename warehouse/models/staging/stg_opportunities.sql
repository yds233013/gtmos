with source as (

    select * from {{ source('gtmos_app', 'opportunities') }}

)

select
    id                          as opportunity_id,
    workspace_id,
    account_id,
    owner_id,
    primary_contact_id,
    source_campaign_id          as campaign_id,
    name                        as opportunity_name,
    stage                       as deal_stage,
    nullif(lead_source, '')     as lead_source,
    nullif(lost_reason, '')     as lost_reason,
    amount_usd::numeric(18, 2)  as amount_usd,
    opened_at,
    closed_at,
    expected_close_date,
    stage = 'closed_won'        as is_won,
    stage = 'closed_lost'       as is_lost,
    stage in ('discovery', 'evaluation', 'proposal', 'negotiation') as is_open,
    data_origin,
    created_at,
    updated_at
from source
