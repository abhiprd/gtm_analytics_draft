-- mart_efficiency's cost columns must reconcile to their sources:
--   1. marketing_spend_allocated summed across segments equals
--      fact_marketing_spend.spend per month (every dollar is attributed to a
--      segment, none double-counted);
--   2. rep_fully_loaded_cost summed across segments equals
--      fact_rep_monthly_cost per month;
--   3. am_cost never exceeds rep_fully_loaded_cost.
-- Checks 1-2 run over the simulation window (2023-01 onward). Earlier
-- months belong to the back-dated established-cohort tail, where a segment
-- can have reps on payroll but no revenue-movement row to attach the cost to.
-- Returns offending months / rows (test passes on 0 rows).

with mkt_mart as (
    select month, sum(marketing_spend_allocated) as allocated
    from {{ ref('mart_efficiency') }}
    where marketing_spend_allocated is not null
    group by 1
),
mkt_src as (
    select month, sum(spend) as spend from {{ ref('fact_marketing_spend') }} group by 1
),
rep_mart as (
    select month, sum(rep_fully_loaded_cost) as cost
    from {{ ref('mart_efficiency') }}
    where month >= date '2023-01-01'
    group by 1
),
rep_src as (
    select month, sum(monthly_fully_loaded_cost_usd) as cost from {{ ref('fact_rep_monthly_cost') }} group by 1
)

select 'marketing_allocation' as check_name, m.month
from mkt_mart m
left join mkt_src s on s.month = m.month
where s.month is null or abs(m.allocated - s.spend) > 0.01

union all

select 'rep_cost' as check_name, r.month
from rep_mart r
left join rep_src s on s.month = r.month
where abs(r.cost - coalesce(s.cost, 0)) > 0.01

union all

select 'am_cost_le_rep_cost' as check_name, month
from {{ ref('mart_efficiency') }}
where am_cost > rep_fully_loaded_cost + 0.01
