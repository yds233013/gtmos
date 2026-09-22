with source as (

    select * from {{ source('gtmos_app', 'stage_transitions') }}

)

select
    id                  as stage_transition_id,
    workspace_id,
    entity_type,
    entity_id,
    pipeline,
    from_stage,
    to_stage,
    changed_at,
    changed_at::date    as changed_date,
    changed_by,
    reason
from source
