with source as (

    select * from {{ source('gtmos_app', 'signals') }}

)

select
    id                  as signal_id,
    workspace_id,
    account_id,
    contact_id,
    signal_type,
    title               as signal_title,
    source              as signal_source,
    source_url,
    confidence,
    strength,
    observed_at,
    observed_at::date   as observed_date,
    ingested_at,
    data_origin,
    dedupe_key
from source
