-- mart_workflow_chain_health invariants. Passes when zero rows are returned.

-- 1. Mart sums equal the fact's sums per month (all segments).
select 'sums_differ_from_fact' as failed_check, cast(m.month as varchar) as month
from (
    select month,
           sum(upstream_actions_sum) as up, sum(downstream_actions_sum) as dn,
           sum(ingestion_without_completion_actions_sum) as iwc, sum(accounts_with_chain) as n
    from {{ ref('mart_workflow_chain_health') }}
    group by month
) m
full outer join (
    select month, sum(upstream_actions) as up, sum(downstream_actions) as dn,
           sum(ingestion_without_completion_actions) as iwc, count(*) as n
    from {{ ref('fact_workflow_chain_events') }}
    group by month
) f on f.month = m.month
where m.month is null or f.month is null
   or m.up <> f.up or m.dn <> f.dn or m.iwc <> f.iwc or m.n <> f.n

union all

-- 2. Counts partition the segment-month; sustained is a subset of partial;
--    rate in [0, 1]; downstream never exceeds upstream.
select 'count_or_rate_invariant', cast(month as varchar)
from {{ ref('mart_workflow_chain_health') }}
where partial_chain_account_count + full_chain_account_count <> accounts_with_chain
   or sustained_partial_account_count > partial_chain_account_count
   or ingestion_without_completion_rate < 0 or ingestion_without_completion_rate > 1
   or downstream_actions_sum > upstream_actions_sum

union all

-- 3. The usage fact joins 1:1 (no account-month lost to the join).
select 'account_months_lost_in_join', cast(w.month as varchar)
from {{ ref('fact_workflow_chain_events') }} w
left join {{ ref('fact_usage_monthly') }} u on u.account_id = w.account_id and u.month = w.month
where u.account_id is null
