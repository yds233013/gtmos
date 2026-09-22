with source as (

    select * from {{ source('gtmos_app', 'experiment_outcomes') }}

)

select
    id                  as outcome_id,
    assignment_id,
    source_activity_id,
    metric,
    value               as metric_value,
    occurred_at,
    note
from source
