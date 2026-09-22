-- QA plan invariant: no negative revenue; no negative utilized/committed
-- Action volume. A dbt test passes when this query returns zero rows.

select account_id, month, mrr, 'fact_revenue_monthly' as source_table
from {{ ref('fact_revenue_monthly') }}
where mrr < 0

union all

select account_id, month, committed_actions_monthly, 'fact_committed_vs_utilized_monthly (committed)'
from {{ ref('fact_committed_vs_utilized_monthly') }}
where committed_actions_monthly < 0

union all

select account_id, month, utilized_actions_monthly, 'fact_committed_vs_utilized_monthly (utilized)'
from {{ ref('fact_committed_vs_utilized_monthly') }}
where utilized_actions_monthly < 0
