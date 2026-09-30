-- Grain: one row per segment per month.
--
-- Efficiency pillar: Magic Number / Consumption Payback / Onboarding-CS
-- Efficiency / AM Efficiency.
--
-- COST SIDE (Magic Number, AM Efficiency). Source: fact_rep_monthly_cost
-- (per-rep OTE x loading factor, accrued from hire to departure -- ramping
-- reps cost money before they produce) and fact_marketing_spend.
--
--   S&M cost (per the metric tree: rep fully-loaded cost incl. ramp +
--   marketing spend allocation by channel) = rep_fully_loaded_cost +
--   marketing_spend_allocated, both attributed to a segment by an explicit rule:
--     * Rep cost follows the rep's own segment (dim_reps.segment, which is
--       fixed by rep_type: ISR / AM-Commercial -> Commercial; AE / SE /
--       AM-Enterprise -> Enterprise). SMB has no reps, so its rep cost is a
--       real zero, not a gap. Every rep type counts toward S&M cost,
--       including AMs, because net_new_arr includes expansion ARR and the
--       AMs are what generate it.
--     * Marketing spend is a channel-level figure and channel does NOT imply
--       segment, so each channel-month's spend is split across segments in
--       proportion to that segment's share of the channel-month's new
--       accounts (the same weighting blended_cac already uses). A channel-
--       month with no new accounts (outbound_sdr only, ~$2K in total) falls
--       back to that channel's whole-window segment mix, so the segment
--       allocations always sum back to fact_marketing_spend.
--   S&M cost is NULL before the first month marketing spend exists
--   (2023-01): a rep-only figure there would understate cost, not measure
--   it. Rep cost columns are populated for every month except the four Enterprise
--   months 2020-03 to 2020-06, where they are NULL: reps were on payroll before
--   any Enterprise revenue-bridge row existed. The dbt reconcile test checks
--   2023-01 onward.
--   Scope note: the tree's S&M definition has no marketing headcount, sales
--   management or RevOps line. The loading factor carries a management/ops
--   allocation for the reps; marketing-team headcount is absent from the raw
--   data, so S&M cost, and therefore magic_number's denominator, is a floor.
--
--   magic_number = net_new_arr / magic_number_sm_cost, where
--   magic_number_sm_cost is the PRIOR month's sm_cost (the tree's
--   "prior-period S&M cost"); both are monthly flows, so no annualisation is
--   applied to the cost. NULL where the prior month has no S&M cost.
--
--   am_cost = fully-loaded cost of the AM-Commercial / AM-Enterprise reps of
--   the segment in the month (a real 0 for SMB, which has no AM).
--   am_efficiency = expansion consumption revenue / am_cost, in the tree's
--   own terms: monthly expansion MRR movement (am_expansion_arr / 12) over
--   the same month's AM cost. NULL where am_cost is 0 (SMB, and any month
--   before a segment's first AM).
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

new_accounts_by_segment_channel_month as (

    select
        segment,
        channel,
        date_trunc('month', signup_date) as month,
        count(*) as new_account_count
    from {{ ref('dim_accounts') }}
    group by 1, 2, 3

),

rep_cost_by_segment_month as (

    select
        segment,
        month,
        sum(monthly_fully_loaded_cost_usd)                                                         as rep_fully_loaded_cost,
        sum(monthly_ramping_cost_usd)                                                              as rep_ramp_cost,
        sum(case when rep_type in ('AM-Commercial', 'AM-Enterprise')
                 then monthly_fully_loaded_cost_usd else 0 end)                                    as am_cost
    from {{ ref('fact_rep_monthly_cost') }}
    group by 1, 2

),

marketing_spend_window as (

    select
        min(month) as first_month
    from {{ ref('fact_marketing_spend') }}

),

channel_month_segment_mix as (

    select
        segment,
        channel,
        month,
        new_account_count,
        sum(new_account_count) over (partition by channel, month) as channel_month_new_accounts
    from new_accounts_by_segment_channel_month

),

channel_window_segment_mix as (

    select
        nas.channel,
        nas.segment,
        sum(nas.new_account_count)::double
            / sum(sum(nas.new_account_count)) over (partition by nas.channel) as window_share
    from new_accounts_by_segment_channel_month nas
    inner join {{ ref('fact_marketing_spend') }} fms
        on fms.channel = nas.channel and fms.month = nas.month
    group by nas.channel, nas.segment

),

marketing_spend_allocated as (

    -- Channel-months with new accounts: split by that month's segment mix.
    select
        cms.segment,
        fms.month,
        fms.spend * cms.new_account_count::double / cms.channel_month_new_accounts as allocated_spend
    from {{ ref('fact_marketing_spend') }} fms
    inner join channel_month_segment_mix cms
        on cms.channel = fms.channel and cms.month = fms.month
    where fms.new_accounts > 0

    union all

    -- Channel-months with no new accounts: split by the channel's whole-window mix.
    select
        cws.segment,
        fms.month,
        fms.spend * cws.window_share as allocated_spend
    from {{ ref('fact_marketing_spend') }} fms
    inner join channel_window_segment_mix cws on cws.channel = fms.channel
    where fms.new_accounts = 0

),

marketing_spend_by_segment_month as (

    select
        segment,
        month,
        sum(allocated_spend) as marketing_spend_allocated
    from marketing_spend_allocated
    group by 1, 2

),

sm_cost as (

    select
        rb.segment,
        rb.month,
        coalesce(rc.rep_fully_loaded_cost, 0)   as rep_fully_loaded_cost,
        coalesce(rc.rep_ramp_cost, 0)           as rep_ramp_cost,
        coalesce(rc.am_cost, 0)                 as am_cost,
        ms.marketing_spend_allocated,
        case
            when rb.month >= mw.first_month
                then coalesce(rc.rep_fully_loaded_cost, 0) + coalesce(ms.marketing_spend_allocated, 0)
        end as sm_cost
    from revenue_bridge rb
    cross join marketing_spend_window mw
    left join rep_cost_by_segment_month rc on rc.segment = rb.segment and rc.month = rb.month
    left join marketing_spend_by_segment_month ms on ms.segment = rb.segment and ms.month = rb.month

),

magic_number as (

    select
        rb.segment,
        rb.month,
        (rb.new_logo_mrr + rb.expansion_mrr - rb.contraction_mrr - rb.churn_mrr) * 12 as net_new_arr,
        sc.rep_fully_loaded_cost,
        sc.rep_ramp_cost,
        sc.marketing_spend_allocated,
        sc.sm_cost,
        prior.sm_cost as magic_number_sm_cost,
        case
            when prior.sm_cost > 0
                then (rb.new_logo_mrr + rb.expansion_mrr - rb.contraction_mrr - rb.churn_mrr) * 12 / prior.sm_cost
        end as magic_number
    from revenue_bridge rb
    left join sm_cost sc on sc.segment = rb.segment and sc.month = rb.month
    left join sm_cost prior
        on prior.segment = rb.segment and prior.month = cast(rb.month - interval 1 month as date)

),

channel_cac as (

    select
        channel,
        month,
        case when new_accounts > 0 then spend / new_accounts end as cac
    from {{ ref('fact_marketing_spend') }}

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
        rb.segment,
        rb.month,
        rb.expansion_mrr * 12 as am_expansion_arr,
        sc.am_cost,
        case
            when sc.am_cost > 0 then rb.expansion_mrr / sc.am_cost
        end as am_efficiency
    from revenue_bridge rb
    left join sm_cost sc on sc.segment = rb.segment and sc.month = rb.month

)

select
    coalesce(mn.segment, cp.segment, oce.segment, ae.segment) as segment,
    coalesce(mn.month, cp.month, oce.month, ae.month)         as month,
    mn.net_new_arr,
    mn.rep_fully_loaded_cost,
    mn.rep_ramp_cost,
    mn.marketing_spend_allocated,
    mn.sm_cost,
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
