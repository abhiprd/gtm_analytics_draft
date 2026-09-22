-- CLAUDE.md non-negotiable invariant: every parent metric must be the
-- actual mathematical result of its children, never an approximation.
-- This asserts int_revenue_movements' bridge actually reconstructs the
-- segment's real ending MRR from fact_revenue_monthly, for every
-- segment/month, within floating-point tolerance. A dbt test passes when
-- this query returns zero rows.

with bridge as (

    select
        movement_segment as segment,
        month,
        sum(case when movement_type = 'starting'      then movement_amount else 0 end)
        + sum(case when movement_type = 'new_logo_mrr'  then movement_amount else 0 end)
        + sum(case when movement_type = 'expansion'     then movement_amount else 0 end)
        - sum(case when movement_type = 'contraction'   then movement_amount else 0 end)
        - sum(case when movement_type = 'churn'         then movement_amount else 0 end)
        + sum(case when movement_type = 'migration_in'  then movement_amount else 0 end)
        - sum(case when movement_type = 'migration_out' then movement_amount else 0 end)
            as computed_ending_mrr
    from {{ ref('int_revenue_movements') }}
    group by 1, 2

),

actual as (

    select segment, month, sum(mrr) as actual_ending_mrr
    from {{ ref('fact_revenue_monthly') }}
    group by 1, 2

)

select
    b.segment,
    b.month,
    b.computed_ending_mrr,
    a.actual_ending_mrr,
    abs(b.computed_ending_mrr - a.actual_ending_mrr) as diff
from bridge b
inner join actual a on a.segment = b.segment and a.month = b.month
where abs(b.computed_ending_mrr - a.actual_ending_mrr) > 0.5
