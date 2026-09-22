{{ config(materialized = 'table') }}

-- Cohort funnel, one row per (cohort week x funnel stage).
--
-- Cohort semantics mirror analytics.funnel() in the API: an account belongs to the week of its FIRST
-- `contacted` funnel transition, and a stage is counted whenever the account reached it, including
-- after the cohort week. The denominator therefore stays fixed at the cohort size instead of drifting
-- with the reporting window, which is what makes the conversion rates comparable across weeks.

with funnel_stages as (

    select stage, stage_rank from (
        values
            ('contacted', 1),
            ('engaged', 2),
            ('qualified', 3),
            ('meeting', 4),
            ('opportunity', 5),
            ('won', 6)
    ) as s (stage, stage_rank)

),

transitions as (

    select
        workspace_id,
        entity_id as account_id,
        to_stage,
        changed_at
    from {{ ref('stg_stage_transitions') }}
    where pipeline = 'funnel'
      and entity_type = 'account'

),

cohort_members as (

    select
        workspace_id,
        account_id,
        date_trunc('week', min(changed_at))::date as cohort_week
    from transitions
    where to_stage = 'contacted'
    group by 1, 2

),

cohort_size as (

    select
        workspace_id,
        cohort_week,
        count(*) as cohort_accounts
    from cohort_members
    group by 1, 2

),

reached as (

    select
        c.workspace_id,
        c.cohort_week,
        t.to_stage as stage,
        count(distinct t.account_id) as accounts_reached
    from cohort_members c
    join transitions t on t.account_id = c.account_id
    group by 1, 2, 3

),

grid as (

    select
        cs.workspace_id,
        cs.cohort_week,
        cs.cohort_accounts,
        s.stage,
        s.stage_rank,
        coalesce(r.accounts_reached, 0) as accounts_reached
    from cohort_size cs
    cross join funnel_stages s
    left join reached r
        on r.workspace_id = cs.workspace_id
        and r.cohort_week = cs.cohort_week
        and r.stage = s.stage

),

lost as (

    select
        workspace_id,
        cohort_week,
        accounts_reached as accounts_lost
    from reached
    where stage = 'lost'

),

with_previous as (

    select
        g.workspace_id,
        g.cohort_week,
        g.cohort_accounts,
        g.stage,
        g.stage_rank,
        g.accounts_reached,
        lag(g.accounts_reached) over (
            partition by g.workspace_id, g.cohort_week order by g.stage_rank
        ) as previous_stage_accounts
    from grid g

)

select
    {{ surrogate_key(['w.workspace_id', 'w.cohort_week', 'w.stage']) }} as funnel_cohort_key,
    w.workspace_id,
    w.cohort_week,
    w.stage,
    w.stage_rank,
    w.cohort_accounts,
    w.accounts_reached,
    w.previous_stage_accounts,
    coalesce(l.accounts_lost, 0) as cohort_accounts_lost,
    round(w.accounts_reached::numeric / nullif(w.cohort_accounts, 0), 4) as conversion_from_cohort,
    round(w.accounts_reached::numeric / nullif(w.previous_stage_accounts, 0), 4) as conversion_from_previous
from with_previous w
left join lost l
    on l.workspace_id = w.workspace_id
    and l.cohort_week = w.cohort_week
