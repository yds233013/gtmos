with source as (

    select * from {{ source('gtmos_app', 'users') }}

)

select
    id                  as user_id,
    workspace_id,
    name                as user_name,
    email               as user_email,
    role                as user_role,
    nullif(team, '')    as team,
    nullif(territory, '') as territory,
    nullif(title, '')   as title,
    is_active,
    capacity,
    created_at,
    updated_at
from source
