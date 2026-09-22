with source as (

    select * from {{ source('gtmos_app', 'experiment_assignments') }}

)

select
    id              as assignment_id,
    experiment_id,
    variant_id,
    unit_id,
    account_id,
    bucket,
    assigned_at,
    exposed_at,
    exposed_at is not null as is_exposed
from source
