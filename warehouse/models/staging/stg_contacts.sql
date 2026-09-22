with source as (

    select * from {{ source('gtmos_app', 'contacts') }}

)

select
    id                                          as contact_id,
    workspace_id,
    account_id,
    owner_id,
    merged_into_id,
    nullif(trim(coalesce(first_name, '') || ' ' || coalesce(last_name, '')), '') as full_name,
    nullif(first_name, '')                      as first_name,
    nullif(last_name, '')                       as last_name,
    lower(nullif(email, ''))                    as email,
    email_status,
    email_status = 'valid'                      as is_email_valid,
    nullif(title, '')                           as title,
    nullif(seniority, '')                       as seniority,
    nullif(department, '')                      as department,
    nullif(persona, '')                         as persona,
    nullif(country, '')                         as country,
    lifecycle_stage,
    source                                      as contact_source,
    data_origin,
    do_not_contact,
    merged_into_id is null                      as is_live,
    last_enriched_at,
    created_at,
    updated_at
from source
