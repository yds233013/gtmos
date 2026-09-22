with source as (

    select * from {{ source('gtmos_app', 'message_drafts') }}

)

select
    id                      as message_draft_id,
    workspace_id,
    account_id,
    contact_id,
    campaign_id,
    research_report_id,
    workflow_run_id,
    channel,
    status                  as draft_status,
    angle,
    generator,
    version,
    nullif(subject, '')     as subject,
    nullif(reviewed_by, '') as reviewed_by,
    nullif(approved_by, '') as approved_by,
    nullif(rejection_reason, '') as rejection_reason,
    approved_at,
    created_at,
    updated_at
from source
