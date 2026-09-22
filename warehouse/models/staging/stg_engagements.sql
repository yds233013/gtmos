with source as (

    select * from {{ source('gtmos_app', 'engagements') }}

)

select
    id                  as engagement_id,
    workspace_id,
    account_id,
    contact_id,
    event_name,
    distinct_id,
    occurred_at,
    occurred_at::date   as occurred_date,
    source              as engagement_source,
    data_origin,
    dedupe_key
from source
