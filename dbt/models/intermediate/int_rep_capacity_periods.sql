-- Grain: one row per rep_id per capacity-period-start-date, where a period
-- boundary is any date on which either quota or status changed. Quota and
-- status are two independently time-varying attributes on the same rep, so
-- this unions their change points and forward-fills each attribute across
-- the merged timeline -- this is the join/business-logic step that lets
-- dim_reps answer point-in-time capacity questions instead of collapsing
-- quota/status into static current-value columns.

with quota as (
    select rep_id, effective_date, quota_amount
    from {{ ref('stg_quota_history') }}
),

status as (
    select rep_id, effective_date, status
    from {{ ref('stg_rep_status_history') }}
),

change_points as (
    select rep_id, effective_date from quota
    union
    select rep_id, effective_date from status
),

joined as (
    select
        cp.rep_id,
        cp.effective_date,
        q.quota_amount,
        s.status
    from change_points cp
    left join quota  q on q.rep_id = cp.rep_id and q.effective_date = cp.effective_date
    left join status s on s.rep_id = cp.rep_id and s.effective_date = cp.effective_date
),

filled as (
    select
        rep_id,
        effective_date,
        last_value(quota_amount ignore nulls) over (
            partition by rep_id order by effective_date
            rows between unbounded preceding and current row
        ) as quota_amount,
        last_value(status ignore nulls) over (
            partition by rep_id order by effective_date
            rows between unbounded preceding and current row
        ) as status
    from joined
)

select
    rep_id,
    effective_date as period_start_date,
    lead(effective_date) over (
        partition by rep_id order by effective_date
    ) - interval 1 day as period_end_date,
    quota_amount,
    status,
    lead(effective_date) over (
        partition by rep_id order by effective_date
    ) is null as is_current_period
from filled
