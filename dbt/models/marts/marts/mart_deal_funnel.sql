-- Grain: one row per segment (Commercial, Enterprise) per month of
-- close_date. SMB is excluded by design: SMB opportunities are created
-- already Closed Won with no rep and no funnel (fact_opportunities,
-- owner_role = 'system').
--
-- Months form a dense spine per segment, from the segment's first
-- new-business or renewal close month through the last new-business or
-- renewal close month of either segment, so a month with no closes is a row of zero counts
-- and NULL averages, not a missing row.
--
-- Exposes the Layer-2/3 deal-level inputs of the metric tree's New logo
-- consumption revenue branch (win rate, avg initial commitment, POC pass
-- rate, loss-reason mix, discount rate vs list, deal size within band,
-- rep capacity ramp mix) and the renewal win rate, as plain counts and
-- sums. It restates no metric formula: a rate is a ratio of two columns
-- here, computed by the consumer from the tree's own definition.
--
-- Column scope:
--   * new_business_* / lost_* / won_* / poc_* / stage_* / avg_days_in_* /
--     *_ramping_rep_* / share_won_at_band_*  -> opportunity_type = 'new_business'
--   * renewal_*                               -> opportunity_type = 'renewal'
--   * expansion opportunities are not in this mart.
--
-- Caveats (also in _mart_schema.yml):
--   * list_price is generated as amount / (1 - discount_rate), so discount
--     versus list is an identity (up to rounding), not an independent
--     observation of list price.
--   * fact_opportunities.rep_id is the current owner after departure
--     reassignment, so ramp attribution (owner's hire_date vs the
--     opportunity's created_date) is approximate.
--   * Lost new-business opportunities carry no account_id.
--   * poc_pass_count / poc_fail_count are NULL for Commercial, which has no
--     POC stage.
--   * Stage regression = a new-business opportunity whose stage history
--     contains the same stage more than once (a re-entry of an earlier stage).

with segment_range as (

    select
        segment,
        min(date_trunc('month', close_date))::date as first_month,
        max(max(date_trunc('month', close_date))) over ()::date as last_month
    from {{ ref('fact_opportunities') }}
    where segment in ('Commercial', 'Enterprise')
      and opportunity_type in ('new_business', 'renewal')
    group by segment

),

spine as (

    select
        segment,
        unnest(generate_series(first_month, last_month, interval 1 month))::date as month
    from segment_range

),

rep_hire as (

    -- dim_reps repeats a rep on every capacity period; hire_date is static
    -- per rep, so min() collapses it to exactly one row per rep_id.
    select rep_id, min(hire_date) as hire_date
    from {{ ref('dim_reps') }}
    group by 1

),

acv_bands as (

{%- for seg, band in var('acv_bands').items() %}
    select '{{ seg }}' as segment, {{ band['floor'] }} as band_floor, {{ band['cap'] }} as band_cap
    {%- if not loop.last %}
    union all
    {%- endif %}
{%- endfor %}

),

new_business as (

    select
        o.opportunity_id,
        o.segment,
        date_trunc('month', o.close_date)::date as month,
        o.is_won,
        o.loss_reason,
        o.amount,
        o.list_price,
        o.poc_outcome,
        datediff('day', rh.hire_date, o.created_date) < {{ var('rep_ramp_window_days') }} as is_ramping_rep_opp,
        b.band_floor,
        b.band_cap
    from {{ ref('fact_opportunities') }} o
    left join rep_hire rh on rh.rep_id = o.rep_id
    inner join acv_bands b on b.segment = o.segment
    where o.opportunity_type = 'new_business'
      and o.segment in ('Commercial', 'Enterprise')

),

stage_regression as (

    -- One row per new-business opportunity that re-enters a stage it has
    -- already been in. Distinct on the opportunity: one that repeats two
    -- different stages must count once, and must not fan out the join below
    -- (which would inflate every count in its segment-month).
    select distinct repeated.opportunity_id
    from (
        select h.opportunity_id
        from {{ ref('fact_opportunity_stage_history') }} h
        inner join new_business nb on nb.opportunity_id = h.opportunity_id
        group by h.opportunity_id, h.stage
        having count(*) > 1
    ) repeated

),

days_per_stage as (

    -- Total days an opportunity spent in each stage (summed across
    -- re-entries), one row per opportunity per stage.
    select
        h.opportunity_id,
        sum(case when h.stage = 'SAL' then h.days_in_stage end)                  as sal_days,
        sum(case when h.stage = 'SQO' then h.days_in_stage end)                  as sqo_days,
        sum(case when h.stage = 'POC' then h.days_in_stage end)                  as poc_days,
        sum(case when h.stage = 'Proposal/Negotiation' then h.days_in_stage end) as proposal_days
    from {{ ref('fact_opportunity_stage_history') }} h
    inner join new_business nb on nb.opportunity_id = h.opportunity_id
    group by h.opportunity_id

),

new_business_monthly as (

    select
        nb.segment,
        nb.month,
        count(*) filter (where nb.is_won)                                          as new_business_won_count,
        count(*) filter (where not nb.is_won)                                      as new_business_lost_count,
        count(*) filter (where not nb.is_won and nb.loss_reason = 'competitive')   as lost_competitive_count,
        count(*) filter (where not nb.is_won and nb.loss_reason = 'no_decision')   as lost_no_decision_count,
        count(*) filter (where not nb.is_won and nb.loss_reason = 'price')         as lost_price_count,
        count(*) filter (where not nb.is_won and nb.loss_reason = 'other')         as lost_other_count,
        coalesce(sum(nb.amount) filter (where nb.is_won), 0)                       as won_amount_sum,
        coalesce(sum(nb.list_price) filter (where nb.is_won), 0)                   as won_list_price_sum,
        count(*) filter (where nb.is_won and nb.amount <= nb.band_floor)           as won_at_band_floor_count,
        count(*) filter (where nb.is_won and nb.amount >= nb.band_cap)             as won_at_band_cap_count,
        case when nb.segment = 'Enterprise'
            then count(*) filter (where nb.poc_outcome = 'pass') end               as poc_pass_count,
        case when nb.segment = 'Enterprise'
            then count(*) filter (where nb.poc_outcome = 'fail') end               as poc_fail_count,
        count(sr.opportunity_id)                                                   as stage_regression_count,
        avg(d.sal_days)                                                            as avg_days_in_sal,
        avg(d.sqo_days)                                                            as avg_days_in_sqo,
        avg(d.poc_days)                                                            as avg_days_in_poc,
        avg(d.proposal_days)                                                       as avg_days_in_proposal,
        count(*) filter (where nb.is_ramping_rep_opp)                              as closed_by_ramping_rep_count,
        count(*) filter (where nb.is_ramping_rep_opp and nb.is_won)                as won_by_ramping_rep_count
    from new_business nb
    left join stage_regression sr on sr.opportunity_id = nb.opportunity_id
    left join days_per_stage d on d.opportunity_id = nb.opportunity_id
    group by nb.segment, nb.month

),

renewals_monthly as (

    select
        segment,
        date_trunc('month', close_date)::date as month,
        count(*) filter (where is_won)     as renewal_won_count,
        count(*) filter (where not is_won) as renewal_lost_count
    from {{ ref('fact_opportunities') }}
    where opportunity_type = 'renewal'
      and segment in ('Commercial', 'Enterprise')
    group by 1, 2

)

select
    s.segment,
    s.month,
    coalesce(n.new_business_won_count, 0)         as new_business_won_count,
    coalesce(n.new_business_lost_count, 0)        as new_business_lost_count,
    coalesce(n.lost_competitive_count, 0)         as lost_competitive_count,
    coalesce(n.lost_no_decision_count, 0)         as lost_no_decision_count,
    coalesce(n.lost_price_count, 0)               as lost_price_count,
    coalesce(n.lost_other_count, 0)               as lost_other_count,
    coalesce(n.won_amount_sum, 0)                 as won_amount_sum,
    coalesce(n.won_list_price_sum, 0)             as won_list_price_sum,
    case
        when coalesce(n.won_list_price_sum, 0) > 0
            then 1 - n.won_amount_sum / n.won_list_price_sum
    end                                           as avg_discount_rate_won,
    case
        when coalesce(n.new_business_won_count, 0) > 0
            then n.won_at_band_floor_count::double / n.new_business_won_count
    end                                           as share_won_at_band_floor,
    case
        when coalesce(n.new_business_won_count, 0) > 0
            then n.won_at_band_cap_count::double / n.new_business_won_count
    end                                           as share_won_at_band_cap,
    case when s.segment = 'Enterprise' then coalesce(n.poc_pass_count, 0) end as poc_pass_count,
    case when s.segment = 'Enterprise' then coalesce(n.poc_fail_count, 0) end as poc_fail_count,
    coalesce(n.stage_regression_count, 0)         as stage_regression_count,
    n.avg_days_in_sal,
    n.avg_days_in_sqo,
    n.avg_days_in_poc,
    n.avg_days_in_proposal,
    coalesce(n.closed_by_ramping_rep_count, 0)    as closed_by_ramping_rep_count,
    coalesce(n.won_by_ramping_rep_count, 0)       as won_by_ramping_rep_count,
    coalesce(r.renewal_won_count, 0)              as renewal_won_count,
    coalesce(r.renewal_lost_count, 0)             as renewal_lost_count
from spine s
left join new_business_monthly n on n.segment = s.segment and n.month = s.month
left join renewals_monthly r     on r.segment = s.segment and r.month = s.month
order by s.segment, s.month
