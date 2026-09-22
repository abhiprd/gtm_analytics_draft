-- Grain: one row per segment per month.
--
-- Durability pillar:
--   NRR  = (Starting − Contraction − Churn + Expansion) ÷ Starting
--   GRR  = (Starting − Contraction − Churn) ÷ Starting
--   Logo retention = Retained accounts ÷ Starting accounts
--
-- All three are literal ratios of int_revenue_movements' dollar/account
-- sums -- not approximations. Logo retention counts an account as
-- "starting" in a segment whenever it had revenue in that segment last
-- month (see int_revenue_movements' 'starting' bucket, which includes
-- accounts that go on to migrate away this month) and "retained" unless it
-- churned -- migrating accounts count as retained, per the build spec:
-- "Logo retention is unaffected by migration either way (the account
-- persists, just at a different segment)."

with movements as (

    select
        movement_segment as segment,
        month,
        movement_type,
        account_id,
        movement_amount
    from {{ ref('int_revenue_movements') }}

),

dollar_bridge as (

    select
        segment,
        month,
        sum(case when movement_type = 'starting'    then movement_amount else 0 end) as starting_mrr,
        sum(case when movement_type = 'expansion'   then movement_amount else 0 end) as expansion_mrr,
        sum(case when movement_type = 'contraction' then movement_amount else 0 end) as contraction_mrr,
        sum(case when movement_type = 'churn'       then movement_amount else 0 end) as churn_mrr
    from movements
    group by 1, 2

),

account_counts as (

    select
        segment,
        month,
        count(distinct case when movement_type = 'starting' then account_id end) as starting_accounts,
        count(distinct case when movement_type = 'churn'    then account_id end) as churned_accounts
    from movements
    where movement_type in ('starting', 'churn')
    group by 1, 2

)

select
    db.segment,
    db.month,
    db.starting_mrr,
    db.expansion_mrr,
    db.contraction_mrr,
    db.churn_mrr,
    case when db.starting_mrr > 0
        then (db.starting_mrr - db.contraction_mrr - db.churn_mrr + db.expansion_mrr) / db.starting_mrr
    end as nrr,
    case when db.starting_mrr > 0
        then (db.starting_mrr - db.contraction_mrr - db.churn_mrr) / db.starting_mrr
    end as grr,
    ac.starting_accounts,
    ac.churned_accounts,
    ac.starting_accounts - ac.churned_accounts as retained_accounts,
    case when ac.starting_accounts > 0
        then (ac.starting_accounts - ac.churned_accounts)::double / ac.starting_accounts
    end as logo_retention_rate
from dollar_bridge db
left join account_counts ac on ac.segment = db.segment and ac.month = db.month
