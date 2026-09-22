-- dim_reps grain is (rep_id, period_start_date). A failing row here means
-- int_rep_capacity_periods produced a duplicate change point for a rep.
-- A dbt test passes when this query returns zero rows.

select
    rep_id,
    period_start_date,
    count(*) as n_rows
from {{ ref('dim_reps') }}
group by 1, 2
having count(*) > 1
