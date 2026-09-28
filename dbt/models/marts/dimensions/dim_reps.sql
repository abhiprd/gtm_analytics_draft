-- Grain: one row per rep_id per capacity-period (quota/status change
-- point) -- deliberately NOT collapsed to one row per rep with a static
-- current quota/status, per the dbt-conventions skill: point-in-time
-- capacity queries ("what was rep X's quota and active/departed status as
-- of month M") need this historized. Join on rep_id and filter
-- period_start_date <= as_of < coalesce(period_end_date, infinity) for a
-- point-in-time lookup, or is_current_period = true for "as of now."
--
-- territory is a new-business coverage/routing concept scoped to
-- account-owning reps (rep_type ISR/AE) -- it is null for every SE and
-- AM-Commercial/AM-Enterprise rep by design, not a data gap.

with capacity_periods as (
    select * from {{ ref('int_rep_capacity_periods') }}
),

reps as (
    select * from {{ ref('stg_users') }}
),

territories as (
    select * from {{ ref('stg_rep_territory') }}
)

select
    cp.rep_id,
    r.rep_type,
    r.segment,
    r.hire_date,
    r.book_size,
    t.territory,
    cp.period_start_date,
    cp.period_end_date,
    cp.is_current_period,
    cp.quota_amount,
    cp.status as rep_status
from capacity_periods cp
inner join reps r on r.rep_id = cp.rep_id
left join territories t on t.rep_id = cp.rep_id
