{{ config(materialized = 'table') }}

-- Association between a buying signal and an opportunity, one row per signal type.
--
-- Mirrors analytics.signal_correlation() in the API: the population is accounts with a `contacted`
-- funnel transition inside the analysis window; a signal counts if it was observed inside the window
-- plus a 90-day head start (a signal that fired before the touch is exactly the interesting case).
-- Both the with-signal and without-signal counts are exposed so a two-account "3x lift" is visibly
-- a two-account lift. This is association, not causation: signal-triggered campaigns target these
-- same accounts, so part of every lift here is the campaign.

{% set window_days = var('signal_analysis_days') %}
{% set signal_head_start_days = var('signal_lookback_extra_days') %}

with window_bounds as (

    select
        current_timestamp - interval '{{ window_days }} days' as window_start,
        current_timestamp - interval '{{ window_days + signal_head_start_days }} days' as signal_window_start

),

contacted_accounts as (

    select distinct t.workspace_id, t.entity_id as account_id
    from {{ ref('stg_stage_transitions') }} t
    cross join window_bounds b
    where t.pipeline = 'funnel'
      and t.entity_type = 'account'
      and t.to_stage = 'contacted'
      and t.changed_at >= b.window_start

),

accounts_with_opportunity as (

    select distinct o.account_id
    from {{ ref('stg_opportunities') }} o
    cross join window_bounds b
    where o.opened_at >= b.window_start

),

population as (

    select
        c.workspace_id,
        c.account_id,
        o.account_id is not null as has_opportunity
    from contacted_accounts c
    left join accounts_with_opportunity o on o.account_id = c.account_id

),

population_totals as (

    select
        workspace_id,
        count(*)                                as contacted_accounts,
        count(*) filter (where has_opportunity) as accounts_with_opportunity
    from population
    group by 1

),

signal_accounts as (

    select distinct
        p.workspace_id,
        s.signal_type,
        p.account_id,
        p.has_opportunity
    from {{ ref('stg_signals') }} s
    join population p on p.account_id = s.account_id
    cross join window_bounds b
    where s.observed_at >= b.signal_window_start

),

by_signal as (

    select
        workspace_id,
        signal_type,
        count(*)                                as accounts_with_signal,
        count(*) filter (where has_opportunity) as with_signal_and_opportunity
    from signal_accounts
    group by 1, 2

)

select
    {{ surrogate_key(['s.workspace_id', 's.signal_type']) }} as signal_effect_key,
    s.workspace_id,
    s.signal_type,
    {{ window_days }}                                       as window_days,
    t.contacted_accounts,
    t.accounts_with_opportunity,
    s.accounts_with_signal,
    s.with_signal_and_opportunity,
    t.contacted_accounts - s.accounts_with_signal            as accounts_without_signal,
    t.accounts_with_opportunity - s.with_signal_and_opportunity as without_signal_and_opportunity,
    round(t.accounts_with_opportunity::numeric / nullif(t.contacted_accounts, 0), 4) as baseline_opportunity_rate,
    round(s.with_signal_and_opportunity::numeric / nullif(s.accounts_with_signal, 0), 4) as opportunity_rate_with_signal,
    round(
        (t.accounts_with_opportunity - s.with_signal_and_opportunity)::numeric
        / nullif(t.contacted_accounts - s.accounts_with_signal, 0),
        4
    ) as opportunity_rate_without_signal,
    round(
        (s.with_signal_and_opportunity::numeric / nullif(s.accounts_with_signal, 0))
        / nullif(
            (t.accounts_with_opportunity - s.with_signal_and_opportunity)::numeric
            / nullif(t.contacted_accounts - s.accounts_with_signal, 0),
            0
        ),
        2
    ) as lift,
    s.accounts_with_signal < 30 as is_low_sample
from by_signal s
join population_totals t on t.workspace_id = s.workspace_id
