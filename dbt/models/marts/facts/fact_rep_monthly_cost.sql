-- Grain: one row per rep_id per calendar month in which the rep was employed
-- for at least one day (hire_date through departure). Derived from static
-- per-rep compensation (stg_users) accrued against the rep's employment span
-- (hire_date; the 'departed' row in stg_rep_status_history) -- not a
-- generated event table, so it is fully recomputed on every build.
--
-- Metric-tree lineage: "Rep fully-loaded cost, incl. ramp" (S&M cost, under
-- Magic number) and "AM cost by segment (comp, ramp status, book size)" (AM
-- efficiency). Cost accrues from the hire date, not from first production, so
-- a ramping rep costs the same as a ramped one while producing less.
--
-- Accrual rule: a rep is employed on every day from hire_date up to (not
-- including) the departure effective_date; a month's cost is the annual figure
-- / 12 x (employed days / days in month). Reps still employed at the end of
-- the horizon accrue through the last modelled month.
--
-- Ramp: the QA plan defines a two-quarter ramp starting at the hire date. The
-- ramping_* columns isolate the days (and cost) that fall inside that
-- six-month window, so ramp cost is separable from steady-state cost.

with reps as (

    select
        rep_id,
        rep_type,
        segment,
        hire_date,
        annual_ote_usd,
        fully_loaded_annual_cost_usd
    from {{ ref('stg_users') }}

),

departures as (

    select
        rep_id,
        min(effective_date) as departure_date
    from {{ ref('stg_rep_status_history') }}
    where status = 'departed'
    group by 1

),

months as (

    select distinct month_start_date as month
    from {{ ref('dim_date') }}
    where month_start_date <= date_trunc('month', cast('{{ var("analysis_as_of_date") }}' as date))

),

employment as (

    select
        r.rep_id,
        r.rep_type,
        r.segment,
        r.hire_date,
        r.annual_ote_usd,
        r.fully_loaded_annual_cost_usd,
        m.month,
        cast(m.month + interval 1 month as date)                       as month_end_exclusive,
        greatest(r.hire_date, m.month)                                  as span_start,
        least(coalesce(d.departure_date, date '9999-12-31'),
              cast(m.month + interval 1 month as date))                 as span_end,
        cast(r.hire_date + interval 6 month as date)                    as ramp_end_exclusive
    from reps r
    cross join months m
    left join departures d on d.rep_id = r.rep_id

),

accrued as (

    select
        rep_id,
        rep_type,
        segment,
        month,
        annual_ote_usd,
        fully_loaded_annual_cost_usd,
        datediff('day', month, month_end_exclusive)                     as days_in_month,
        greatest(datediff('day', span_start, span_end), 0)              as active_days,
        greatest(datediff('day', span_start, least(span_end, ramp_end_exclusive)), 0) as ramping_days
    from employment

)

select
    rep_id,
    month,
    rep_type,
    segment,
    days_in_month,
    active_days,
    ramping_days,
    active_days > 0 and ramping_days > 0                                as is_ramping,
    annual_ote_usd::double / 12 * active_days / days_in_month           as monthly_ote_usd,
    fully_loaded_annual_cost_usd::double / 12 * active_days / days_in_month as monthly_fully_loaded_cost_usd,
    fully_loaded_annual_cost_usd::double / 12 * ramping_days / days_in_month as monthly_ramping_cost_usd
from accrued
where active_days > 0
