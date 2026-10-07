-- Grain: one row per segment (Commercial, Enterprise) per month. SMB is
-- excluded by design: SMB accounts carry no commitment
-- (committed_actions_monthly is NULL on every SMB row of
-- fact_committed_vs_utilized_monthly).
--
-- Exposes the metric tree's "Overage realization" input (Growth /
-- consumption branch: usage above the committed Action volume, billed at
-- the same rate) as Action counts and dollars. Restates no metric formula.
--
-- Join: fact_committed_vs_utilized_monthly and fact_revenue_monthly are
-- both exactly one row per (account_id, month) with identical key sets, so
-- the inner join is 1:1 and drops nothing.
--
-- Billing mechanic in the data: mrr = unit_price * greatest(committed,
-- utilized) on every committed account-month. overage_mrr therefore
-- apportions the account's own mrr by the overage share of the billed
-- Actions, mrr * greatest(utilized - committed, 0) / greatest(committed,
-- utilized), so no unit price is hard-coded and overage_mrr <= that
-- account's mrr by construction.
--
-- Scope of columns:
--   * committed_actions_sum, utilized_actions_sum, overage_actions_sum,
--     overage_mrr, accounts_over_commit_count, accounts_with_commitment_count
--     cover only account-months with a commitment (committed > 0). A
--     Commercial or Enterprise account-month with a NULL commitment is not
--     in them.
--   * total_mrr covers EVERY account-month of the segment, committed or
--     not, and equals fact_revenue_monthly's mrr sum for the segment-month;
--     overage_share_of_mrr = overage_mrr / total_mrr is therefore a share of
--     the segment's whole recognized MRR.

with account_months as (

    select
        c.segment,
        c.month,
        r.mrr,
        c.committed_actions_monthly as committed,
        c.utilized_actions_monthly as utilized,
        c.committed_actions_monthly > 0 as has_commitment
    from {{ ref('fact_committed_vs_utilized_monthly') }} c
    inner join {{ ref('fact_revenue_monthly') }} r
        on r.account_id = c.account_id
        and r.month = c.month
    where c.segment in ('Commercial', 'Enterprise')

)

select
    segment,
    month,
    coalesce(sum(committed) filter (where has_commitment), 0) as committed_actions_sum,
    coalesce(sum(utilized) filter (where has_commitment), 0)  as utilized_actions_sum,
    coalesce(sum(greatest(utilized - committed, 0)) filter (where has_commitment), 0) as overage_actions_sum,
    coalesce(
        sum(mrr * greatest(utilized - committed, 0) / greatest(committed, utilized))
            filter (where has_commitment),
        0
    )                                                          as overage_mrr,
    sum(mrr)                                                   as total_mrr,
    case
        when sum(mrr) > 0
            then coalesce(
                sum(mrr * greatest(utilized - committed, 0) / greatest(committed, utilized))
                    filter (where has_commitment),
                0
            ) / sum(mrr)
    end                                                        as overage_share_of_mrr,
    count(*) filter (where has_commitment and utilized > committed) as accounts_over_commit_count,
    count(*) filter (where has_commitment)                     as accounts_with_commitment_count
from account_months
group by segment, month
order by segment, month
