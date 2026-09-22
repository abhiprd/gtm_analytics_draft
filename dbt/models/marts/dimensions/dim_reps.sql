-- Grain: one row per rep_id per capacity-period (quota/status change
-- point) -- deliberately NOT collapsed to one row per rep with a static
-- current quota/status, per the dbt-conventions skill: point-in-time
-- capacity queries ("what was rep X's quota and active/departed status as
-- of month M") need this historized. Join on rep_id and filter
-- period_start_date <= as_of < coalesce(period_end_date, infinity) for a
-- point-in-time lookup, or is_current_period = true for "as of now."

with capacity_periods as (
    select * from {{ ref('int_rep_capacity_periods') }}
),

reps as (
    select * from {{ ref('stg_users') }}
)

select
    cp.rep_id,
    r.rep_type,
    r.segment,
    r.hire_date,
    r.book_size,
    cp.period_start_date,
    cp.period_end_date,
    cp.is_current_period,
    cp.quota_amount,
    cp.status as rep_status
from capacity_periods cp
inner join reps r on r.rep_id = cp.rep_id
