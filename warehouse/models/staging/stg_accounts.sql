with source as (

    select * from {{ source('gtmos_app', 'accounts') }}

)

select
    id                                  as account_id,
    workspace_id,
    owner_id,
    merged_into_id,
    name                                as account_name,
    nullif(domain, '')                  as domain,
    nullif(industry, '')                as industry,
    nullif(sub_industry, '')            as sub_industry,
    nullif(segment, '')                 as segment,
    nullif(country, '')                 as country,
    nullif(region, '')                  as region,
    nullif(city, '')                    as city,
    nullif(funding_stage, '')           as funding_stage,
    funnel_stage,
    lifecycle_stage,
    source                              as account_source,
    data_origin,
    employee_count,
    employee_growth_12m,
    annual_revenue_usd,
    founded_year,
    total_funding_usd,
    last_funding_at,
    last_funding_amount_usd,
    ai_team_size,
    ai_open_roles,
    icp_score,
    nullif(score_grade, '')             as score_grade,
    intent_score,
    is_customer,
    is_flagship,
    merged_into_id is null              as is_live,
    score_updated_at,
    last_signal_at,
    last_enriched_at,
    created_at,
    updated_at
from source
