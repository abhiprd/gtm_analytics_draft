-- Grain: one row per segment per month. Segment is the account's segment
-- in that month (fact_usage_monthly.segment, point-in-time, so an account
-- that migrates is counted in its then-current segment).
--
-- Exposes the metric tree's "Workflow chain under-utilization" inputs
-- (Durability branch: upstream triggers vs. downstream completion) from
-- fact_workflow_chain_events as sums and account counts. Restates no
-- metric formula.
--
-- Join: fact_workflow_chain_events and fact_usage_monthly are both exactly
-- one row per (account_id, month) with identical key sets (142,942 each),
-- so the inner join is 1:1 and drops nothing; tests/test_phase2_wave10_marts.py
-- asserts it.
--
-- ingestion_without_completion_rate = 1 - downstream / upstream, Actions-
-- weighted (a sum ratio, not an average of account rates).
--
-- A partial-chain account-month has full_chain_completion_rate strictly
-- below var('workflow_chain_completion_threshold') (default 0.70, the same
-- value analytics/playbook_triggers.py uses for its
-- ingestion_without_completion rule); every other account-month is a
-- full-chain account-month, so
-- partial_chain_account_count + full_chain_account_count = accounts_with_chain.
-- sustained_partial_account_count counts account-months that are partial
-- in this month AND in the calendar-prior month for the same account (the
-- playbook rule's two-consecutive-month idea); an account's first month, or
-- a month after a gap, cannot be sustained.

with account_months as (

    select
        u.segment,
        w.account_id,
        w.month,
        w.upstream_actions,
        w.downstream_actions,
        w.ingestion_without_completion_actions,
        w.full_chain_completion_rate < {{ var('workflow_chain_completion_threshold') }} as is_partial_chain
    from {{ ref('fact_workflow_chain_events') }} w
    inner join {{ ref('fact_usage_monthly') }} u
        on u.account_id = w.account_id
        and u.month = w.month

),

with_prior_month as (

    select
        cur.segment,
        cur.month,
        cur.upstream_actions,
        cur.downstream_actions,
        cur.ingestion_without_completion_actions,
        cur.is_partial_chain,
        coalesce(cur.is_partial_chain and prev.is_partial_chain, false) as is_sustained_partial
    from account_months cur
    left join account_months prev
        on prev.account_id = cur.account_id
        and prev.month = cur.month - interval 1 month

)

select
    segment,
    month,
    sum(upstream_actions)                                   as upstream_actions_sum,
    sum(downstream_actions)                                 as downstream_actions_sum,
    sum(ingestion_without_completion_actions)               as ingestion_without_completion_actions_sum,
    case
        when sum(upstream_actions) > 0
            then 1 - sum(downstream_actions)::double / sum(upstream_actions)
    end                                                     as ingestion_without_completion_rate,
    count(*)                                                as accounts_with_chain,
    count(*) filter (where is_partial_chain)                as partial_chain_account_count,
    count(*) filter (where not is_partial_chain)            as full_chain_account_count,
    count(*) filter (where is_sustained_partial)            as sustained_partial_account_count
from with_prior_month
group by segment, month
order by segment, month
