-- Grain: one row per segment per month.
--
-- Efficiency pillar: Magic Number / Consumption Payback / Onboarding-CS
-- Efficiency / AM Efficiency.
--
-- RAW-DATA GAP, left null on purpose (per this build's explicit scope
-- instructions -- do not fabricate a placeholder cost):
--   - magic_number_sm_cost / magic_number: there is no rep-cost/comp data
--     anywhere in the raw sources (no salary, OTE, or fully-loaded-cost
--     field on dim_reps/users.csv), so the numerator (net new ARR) is
--     computed but the S&M cost denominator, and therefore the ratio
--     itself, stays NULL until a comp data source exists.
--   - am_cost / am_efficiency: same gap -- AM comp isn't in the raw data.
--     am_expansion_arr (the numerator) is computed.
--
-- Consumption Payback IS fully computable: CAC by channel comes from
-- fact_marketing_spend (spend / new_accounts), blended to a segment/month
-- CAC by weighting each channel's CAC by that channel's share of the
-- segment's new accounts that month (from dim_accounts.channel x
-- signup_date). The margin denominator uses fact_committed_vs_utilized_monthly
-- to isolate revenue attributable to Actions actually consumed: MRR is
-- haircut by min(1, utilized/committed) before applying the build spec's
-- flat ~80% gross margin assumption -- this is what "excludes committed-
-- but-unused capacity" (the tree's own qualifier) means operationalized
-- against this raw data; SMB has no commitment (committed_actions_monthly
-- is null, fully metered) so its ratio defaults to 1.0 (nothing to
-- exclude). Marketing spend only covers 2023-01 onward, so payback is
-- NULL for earlier months by construction (no CAC to compute against).

with revenue_bridge as (

    select
        movement_segment as segment,
        month,
        sum(case when movement_type = 'new_logo_mrr' then movement_amount else 0 end) as new_logo_mrr,
        sum(case when movement_type = 'expansion'    then movement_amount else 0 end) as expansion_mrr,
        sum(case when movement_type = 'contraction'  then movement_amount else 0 end) as contraction_mrr,
        sum(case when movement_type = 'churn'        then movement_amount else 0 end) as churn_mrr
    from {{ ref('int_revenue_movements') }}
    group by 1, 2

),

magic_number as (

    select
        segment,
        month,
        (new_logo_mrr + expansion_mrr - contraction_mrr - churn_mrr) * 12 as net_new_arr,
        cast(null as double) as magic_number_sm_cost,  -- GAP: no rep-cost/comp data in raw sources
        cast(null as double) as magic_number            -- GAP: undefined without the cost denominator
    from revenue_bridge

),

channel_cac as (

    select
        channel,
        month,
        case when new_accounts > 0 then spend / new_accounts end as cac
    from {{ ref('fact_marketing_spend') }}

),

new_accounts_by_segment_channel_month as (

    select
        segment,
        channel,
        date_trunc('month', signup_date) as month,
        count(*) as new_account_count
    from {{ ref('dim_accounts') }}
    group by 1, 2, 3

),

blended_cac as (

    select
        nas.segment,
        nas.month,
        sum(nas.new_account_count)                                                          as new_account_count,
        sum(nas.new_account_count * cc.cac) / nullif(sum(nas.new_account_count), 0)          as blended_cac
    from new_accounts_by_segment_channel_month nas
    left join channel_cac cc on cc.channel = nas.channel and cc.month = nas.month
    group by 1, 2

),

utilized_margin as (

    select
        cu.account_id,
        cu.month,
        cu.segment,
        rm.mrr,
        case
            when cu.committed_actions_monthly is not null and cu.committed_actions_monthly > 0
                then least(1.0, cu.utilized_actions_monthly / cu.committed_actions_monthly)
            else 1.0
        end as utilization_ratio
    from {{ ref('fact_committed_vs_utilized_monthly') }} cu
    left join {{ ref('fact_revenue_monthly') }} rm
        on rm.account_id = cu.account_id and rm.month = cu.month

),

utilized_margin_by_segment_month as (

    select
        segment,
        month,
        avg(mrr * utilization_ratio * 0.80) as avg_utilized_action_margin_per_account
    from utilized_margin
    group by 1, 2

),

consumption_payback as (

    select
        bc.segment,
        bc.month,
        bc.blended_cac,
        um.avg_utilized_action_margin_per_account,
        case
            when um.avg_utilized_action_margin_per_account > 0
                then bc.blended_cac / um.avg_utilized_action_margin_per_account
        end as consumption_payback_months
    from blended_cac bc
    left join utilized_margin_by_segment_month um
        on um.segment = bc.segment and um.month = bc.month

),

am_touchpoints as (

    select
        segment,
        date_trunc('month', activity_date) as month,
        count(*) as am_touchpoint_count
    from {{ ref('fact_am_activity') }}
    group by 1, 2

),

automated_actions as (

    select
        segment,
        month,
        sum(actions_consumed) as automated_actions_delivered
    from {{ ref('fact_usage_monthly') }}
    group by 1, 2

),

onboarding_cs_efficiency as (

    -- SMB never appears in am_touchpoints at all (no-touch, no AM) -- its
    -- am_touchpoint_count is coalesced to 0 (a real, meaningful value: zero
    -- human touches per Action delivered) rather than left NULL, which
    -- would misrepresent "genuinely zero" as "unknown."
    select
        coalesce(am.segment, aa.segment)          as segment,
        coalesce(am.month, aa.month)              as month,
        coalesce(am.am_touchpoint_count, 0)       as am_touchpoint_count,
        aa.automated_actions_delivered,
        case
            when aa.automated_actions_delivered > 0
                then coalesce(am.am_touchpoint_count, 0)::double / aa.automated_actions_delivered
        end as onboarding_cs_efficiency_ratio
    from am_touchpoints am
    full outer join automated_actions aa on aa.segment = am.segment and aa.month = am.month

),

am_efficiency as (

    select
        segment,
        month,
        expansion_mrr * 12 as am_expansion_arr,
        cast(null as double) as am_cost,        -- GAP: no rep-cost/comp data in raw sources
        cast(null as double) as am_efficiency    -- GAP: undefined without the cost denominator
    from revenue_bridge

)

select
    coalesce(mn.segment, cp.segment, oce.segment, ae.segment) as segment,
    coalesce(mn.month, cp.month, oce.month, ae.month)         as month,
    mn.net_new_arr,
    mn.magic_number_sm_cost,
    mn.magic_number,
    cp.blended_cac,
    cp.avg_utilized_action_margin_per_account,
    cp.consumption_payback_months,
    oce.am_touchpoint_count,
    oce.automated_actions_delivered,
    oce.onboarding_cs_efficiency_ratio,
    ae.am_expansion_arr,
    ae.am_cost,
    ae.am_efficiency
from magic_number mn
full outer join consumption_payback cp on cp.segment = mn.segment and cp.month = mn.month
full outer join onboarding_cs_efficiency oce on oce.segment = coalesce(mn.segment, cp.segment) and oce.month = coalesce(mn.month, cp.month)
full outer join am_efficiency ae on ae.segment = coalesce(mn.segment, cp.segment, oce.segment) and ae.month = coalesce(mn.month, cp.month, oce.month)
