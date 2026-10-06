-- mart_deal_funnel invariants. A dbt test passes when this returns zero rows;
-- each branch labels the invariant it breaks.

-- 1. New-business won/lost counts equal mart_growth_bridge's for every
--    Commercial/Enterprise segment-month, in both directions (a month absent
--    from mart_growth_bridge's count columns is zero).
select 'counts_differ_from_growth_bridge' as failed_check, f.segment, cast(f.month as varchar) as month
from {{ ref('mart_deal_funnel') }} f
left join {{ ref('mart_growth_bridge') }} g on g.segment = f.segment and g.month = f.month
where f.new_business_won_count  <> coalesce(g.new_business_won_count, 0)
   or f.new_business_lost_count <> coalesce(g.new_business_lost_count, 0)

union all

select 'growth_bridge_month_missing_from_funnel', g.segment, cast(g.month as varchar)
from {{ ref('mart_growth_bridge') }} g
left join {{ ref('mart_deal_funnel') }} f on f.segment = g.segment and f.month = g.month
where g.segment in ('Commercial', 'Enterprise')
  and coalesce(g.new_business_won_count, 0) + coalesce(g.new_business_lost_count, 0) > 0
  and f.segment is null

union all

-- 2. The four loss-reason counts sum to the lost count.
select 'loss_reasons_do_not_sum_to_lost', segment, cast(month as varchar)
from {{ ref('mart_deal_funnel') }}
where lost_competitive_count + lost_no_decision_count + lost_price_count + lost_other_count
      <> new_business_lost_count

union all

-- 3. Enterprise POC pass + fail equals the Enterprise closed new-business
--    deals that carry a poc_outcome; Commercial POC columns are NULL.
select 'poc_pass_fail_differs_from_closed_with_outcome', f.segment, cast(f.month as varchar)
from {{ ref('mart_deal_funnel') }} f
left join (
    select date_trunc('month', close_date)::date as month, count(*) as n
    from {{ ref('fact_opportunities') }}
    where segment = 'Enterprise' and opportunity_type = 'new_business' and poc_outcome is not null
    group by 1
) o on o.month = f.month
where f.segment = 'Enterprise'
  and f.poc_pass_count + f.poc_fail_count <> coalesce(o.n, 0)

union all

select 'commercial_poc_not_null', segment, cast(month as varchar)
from {{ ref('mart_deal_funnel') }}
where segment = 'Commercial' and (poc_pass_count is not null or poc_fail_count is not null)

union all

-- 4. Discount in [0, 1); shares in [0, 1]; counts and sums non-negative;
--    ramping subsets bounded by their totals; won amount <= list price.
select 'value_out_of_range', segment, cast(month as varchar)
from {{ ref('mart_deal_funnel') }}
where avg_discount_rate_won < 0 or avg_discount_rate_won >= 1
   or share_won_at_band_floor < 0 or share_won_at_band_floor > 1
   or share_won_at_band_cap < 0 or share_won_at_band_cap > 1
   or won_amount_sum < 0 or won_amount_sum > won_list_price_sum
   or stage_regression_count < 0
   or closed_by_ramping_rep_count > new_business_won_count + new_business_lost_count
   or won_by_ramping_rep_count > closed_by_ramping_rep_count
   or won_by_ramping_rep_count > new_business_won_count
   or avg_days_in_sal < 0 or avg_days_in_sqo < 0 or avg_days_in_poc < 0 or avg_days_in_proposal < 0

union all

-- 5. Every won new-business deal's amount is within a rounding step of
--    list_price * (1 - discount_rate) (list_price is derived from amount).
select 'amount_not_list_times_one_minus_discount', segment, opportunity_id
from {{ ref('fact_opportunities') }}
where opportunity_type = 'new_business' and is_won
  and abs(amount / list_price - (1 - discount_rate)) > 0.001
