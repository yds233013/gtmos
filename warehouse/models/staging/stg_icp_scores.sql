with source as (

    select * from {{ source('gtmos_app', 'icp_scores') }}

)

select
    id                  as icp_score_id,
    workspace_id,
    account_id,
    icp_profile_id,
    icp_version,
    total               as score_total,
    grade               as score_grade,
    fit                 as fit_points,
    intent              as intent_points,
    timing              as timing_points,
    technical           as technical_points,
    engagement          as engagement_points,
    excluded            as is_excluded,
    exclusion_reason,
    summary             as score_summary,
    inputs_hash,
    trigger             as score_trigger,
    is_current,
    computed_at
from source
