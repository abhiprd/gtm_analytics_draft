-- mart_consumption_utilization invariants. Passes when zero rows are returned.

-- 1. total_mrr equals fact_revenue_monthly's mrr for the same segment-month
--    (Commercial and Enterprise), both directions.
select 'total_mrr_differs_from_fact_revenue' as failed_check, coalesce(m.segment, f.segment) as segment,
       cast(coalesce(m.month, f.month) as varchar) as month
from {{ ref('mart_consumption_utilization') }} m
full outer join (
    select segment, month, sum(mrr) as mrr
    from {{ ref('fact_revenue_monthly') }}
    where segment in ('Commercial', 'Enterprise')
    group by 1, 2
) f on f.segment = m.segment and f.month = m.month
where m.segment is null or f.segment is null or abs(m.total_mrr - f.mrr) > 0.01

union all

-- 2. Non-negativity and bounds: 0 <= overage_mrr <= total_mrr, share in [0, 1],
--    overage actions non-negative, over-commit accounts within committed accounts,
--    utilized covers overage.
select 'value_out_of_range', segment, cast(month as varchar)
from {{ ref('mart_consumption_utilization') }}
where overage_mrr < 0 or overage_mrr > total_mrr + 0.01
   or overage_share_of_mrr < 0 or overage_share_of_mrr > 1
   or overage_actions_sum < 0 or committed_actions_sum < 0 or utilized_actions_sum < 0
   or accounts_over_commit_count > accounts_with_commitment_count
   or overage_actions_sum > utilized_actions_sum

union all

-- 3. The overage apportionment holds per account-month: mrr is the
--    greatest(committed, utilized) billing, so overage_mrr cannot exceed the
--    sum of those accounts' mrr.
select 'overage_actions_not_utilized_minus_committed_floor', m.segment, cast(m.month as varchar)
from {{ ref('mart_consumption_utilization') }} m
inner join (
    select segment, month,
           sum(greatest(utilized_actions_monthly - committed_actions_monthly, 0)) as o
    from {{ ref('fact_committed_vs_utilized_monthly') }}
    where committed_actions_monthly > 0
    group by 1, 2
) c on c.segment = m.segment and c.month = m.month
where m.overage_actions_sum <> c.o
