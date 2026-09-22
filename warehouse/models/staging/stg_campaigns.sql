with source as (

    select * from {{ source('gtmos_app', 'campaigns') }}

)

select
    id                          as campaign_id,
    workspace_id,
    owner_id,
    key                         as campaign_key,
    name                        as campaign_name,
    status                      as campaign_status,
    channel,
    nullif(persona, '')         as persona,
    nullif(trigger_signal, '')  as trigger_signal,
    hypothesis,
    value_prop,
    start_date,
    end_date,
    data_origin,
    created_at,
    updated_at
from source
