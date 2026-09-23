-- Grain: one row per segment per month.
--
-- Growth pillar: Starting consumption revenue + New logo − Contraction −
-- Churn + Expansion (± segment migration, nets to zero). The
-- starting/new_logo_mrr/expansion/contraction/churn/migration_* columns
-- below are pulled straight from int_revenue_movements and are provably
-- exact -- ending_mrr = starting_mrr + new_logo_mrr + expansion_mrr -
-- contraction_mrr - churn_mrr + migration_in_mrr - migration_out_mrr for
-- every row, every month (enforced by tests/assert_revenue_bridge_reconciles.sql).
-- This is what makes Growth the real sum of its children per CLAUDE.md's
-- invariant, not an approximation.
--
-- Two different lenses on "New Logo" are both surfaced, deliberately not
-- forced to tie out dollar-for-dollar:
--   - new_logo_mrr: the MRR-bridge lens (first recognized-revenue month for
--     the account) -- this is the one that makes the bridge arithmetic
--     above exact.
--   - new_logo_bookings_amount / win_rate / avg_initial_commitment: the
--     metric tree's own "New logo consumption revenue = Pipeline generated
--     x win rate x avg initial commitment" lens, computed from
--     fact_opportunities (won new_business deal amount at close, by close
--     month). These two New Logo figures will NOT match exactly -- a
--     bookings/ACV-at-close figure vs. a recognized-MRR-at-first-charge
--     figure is a normal, real bookings-vs-revenue-recognition gap, not a
--     bug. Reconciling them would require ramp/billing-schedule data this
--     project doesn't generate.
--
-- NOT built here: the Layer-2 "Pipeline generated" organic/paid/community
-- breakdown (Σ channel volume x channel-to-lead rate x lead-to-PQL rate).
-- That needs leads/campaign-touch data that doesn't exist in this raw data
-- (marketing_spend_by_channel_month has only a coarse 3-value channel
-- taxonomy, not organic/paid/community, and there's no leads or campaign
-- table at all). See docs gap note in stg_marketing_spend_by_channel_month.
--
-- Activation (TTFA) is a Layer-1 Growth node but is NOT part of the
-- additive bridge equation above -- it's reported here as a parallel
-- column (activation_ttfa_months_avg), cohorted by signup month, not
-- calendar month of revenue.

with revenue_bridge as (

    select
        movement_segment as segment,
        month,
        sum(case when movement_type = 'starting'      then movement_amount else 0 end) as starting_mrr,
        sum(case when movement_type = 'new_logo_mrr'  then movement_amount else 0 end) as new_logo_mrr,
        sum(case when movement_type = 'expansion'     then movement_amount else 0 end) as expansion_mrr,
        sum(case when movement_type = 'contraction'   then movement_amount else 0 end) as contraction_mrr,
        sum(case when movement_type = 'churn'         then movement_amount else 0 end) as churn_mrr,
        sum(case when movement_type = 'migration_in'  then movement_amount else 0 end) as migration_in_mrr,
        sum(case when movement_type = 'migration_out' then movement_amount else 0 end) as migration_out_mrr
    from {{ ref('int_revenue_movements') }}
    group by 1, 2

),

new_business_opps as (

    select
        segment,
        date_trunc('month', close_date) as month,
        is_won,
        amount
    from {{ ref('fact_opportunities') }}
    where opportunity_type = 'new_business'

),

new_logo_bookings as (

    select
        segment,
        month,
        sum(case when is_won then amount else 0 end)                              as new_logo_bookings_amount,
        count(*) filter (where is_won)                                            as new_business_won_count,
        count(*) filter (where not is_won)                                        as new_business_lost_count,
        case
            when count(*) > 0
                then count(*) filter (where is_won)::double / count(*)
        end                                                                        as win_rate,
        avg(amount) filter (where is_won)                                          as avg_initial_commitment
    from new_business_opps
    group by 1, 2

),

first_action_month as (

    select
        account_id,
        min(month) as first_production_action_month
    from {{ ref('fact_usage_monthly') }}
    where actions_consumed > 0
    group by 1

),

activation as (

    -- fact_usage_monthly is monthly grain, not daily -- there is no exact
    -- "first production Action" timestamp in this raw data, only the
    -- calendar month it happened in. datediff('day', signup_date,
    -- month_start_of_first_usage) would go NEGATIVE for any account that
    -- signs up after the 1st of the month it also shows first usage in
    -- (the usage row's month is truncated to the 1st, even though the
    -- actual usage happened later in that same month, possibly after
    -- signup). TTFA is therefore reported here in whole CALENDAR MONTHS
    -- (0 = signed up and produced a first Action in the same month), not
    -- the tree's literal day-level definition -- the closest honest
    -- approximation this grain of data supports.
    select
        a.segment,
        date_trunc('month', a.signup_date) as month,
        avg(datediff('month', date_trunc('month', a.signup_date), f.first_production_action_month)) as activation_ttfa_months_avg,
        count(*) as signup_cohort_size,
        count(f.account_id) as activated_count
    from {{ ref('dim_accounts') }} a
    left join first_action_month f on f.account_id = a.account_id
    group by 1, 2

)

select
    coalesce(rb.segment, nb.segment, act.segment) as segment,
    coalesce(rb.month, nb.month, act.month)        as month,
    rb.starting_mrr,
    rb.new_logo_mrr,
    rb.expansion_mrr,
    rb.contraction_mrr,
    rb.churn_mrr,
    rb.migration_in_mrr,
    rb.migration_out_mrr,
    rb.starting_mrr + rb.new_logo_mrr + rb.expansion_mrr - rb.contraction_mrr
        - rb.churn_mrr + rb.migration_in_mrr - rb.migration_out_mrr as ending_mrr,
    nb.new_logo_bookings_amount,
    nb.new_business_won_count,
    nb.new_business_lost_count,
    nb.win_rate,
    nb.avg_initial_commitment,
    act.activation_ttfa_months_avg,
    act.signup_cohort_size,
    act.activated_count
from revenue_bridge rb
full outer join new_logo_bookings nb on nb.segment = rb.segment and nb.month = rb.month
full outer join activation act       on act.segment = coalesce(rb.segment, nb.segment)
                                     and act.month   = coalesce(rb.month, nb.month)
