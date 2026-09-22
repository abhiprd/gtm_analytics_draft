-- Grain: one row per account_id per month per movement_type -- a single
-- account can contribute more than one row in a month (e.g. a migration
-- month contributes both a migration_out/migration_in pair AND an
-- expansion/contraction row for the growth on top of the migrated base).
--
-- This is the shared revenue-bridge engine behind mart_growth_bridge,
-- mart_durability, and mart_segment_migration -- built once here (per the
-- dbt-conventions skill: promote int_ to a real model, not a CTE repeated
-- in three marts, once it's reused by more than one).
--
-- Movement types: starting, new_logo_mrr, expansion, contraction, churn,
-- migration_in, migration_out. Summing movement_amount for a given
-- (movement_segment, month) by type reconstructs the segment's MRR bridge
-- exactly:
--   ending_mrr = starting + new_logo_mrr + expansion - contraction - churn
--                + migration_in - migration_out
-- This is provable row-by-row (see reasoning in mart_growth_bridge) and is
-- what makes Growth a real sum of its children per CLAUDE.md's invariant,
-- not an approximation.
--
-- Design choices, stated explicitly:
-- 0. "starting" is always attributed to an account's PRIOR segment, not its
--    current one -- otherwise an account migrating away this month would
--    never contribute a starting balance to its old segment, and
--    migration_out would double-subtract revenue the bridge never counted
--    as "starting" for that segment/month to begin with.
-- 1. Migration reclassifies the account's *prior* MRR value between
--    segments (migration_out(old) = migration_in(new) = prior_mrr) so the
--    migration bucket nets to exactly zero across segments, matching the
--    metric tree's "± segment migration, nets to zero" note. Any growth or
--    contraction that happens in the same month as the migration itself
--    (current mrr vs. prior mrr) is booked as expansion/contraction of the
--    NEW segment, consistent with the build spec's note that migration
--    "typically open[s] a renewal/expansion opportunity to formalize the
--    bigger contract."
-- 2. Churn is NOT detected from a $0 mrr row -- verified against the raw
--    data that churned accounts' MRR rows simply stop (last row is always
--    a positive value, in the same month as the account's latest
--    subscription end_date); there is no trailing $0 row to diff against.
--    Churn is instead detected from stg_subscriptions (status = 'churned'
--    on an account's most recent subscription), with the churn amount
--    equal to the account's last known MRR and the churn recognized in the
--    month immediately following that last MRR row (when revenue actually
--    drops to zero) -- this matches all 1,837 churned accounts in the raw
--    data with zero mismatches.

with account_month_mrr as (

    select
        account_id,
        month,
        segment,
        mrr,
        lag(mrr) over (partition by account_id order by month)     as prior_mrr,
        lag(segment) over (partition by account_id order by month) as prior_segment
    from {{ ref('stg_mrr_by_account_month') }}

),

-- the pre-existing base for the month, always attributed to the account's
-- PRIOR segment -- this covers both same-segment continuers AND accounts
-- that migrate away this month. Migrators must show up here (attributed to
-- the OLD segment) or migration_out below would double-subtract revenue
-- that was never counted as this month's "starting" base for the old
-- segment in the first place.
starting_movements as (
    select account_id, month, prior_segment as movement_segment, 'starting' as movement_type, prior_mrr as movement_amount
    from account_month_mrr
    where prior_segment is not null
),

-- an account's first-ever observed MRR month
new_logo_movements as (
    select account_id, month, segment as movement_segment, 'new_logo_mrr' as movement_type, mrr as movement_amount
    from account_month_mrr
    where prior_mrr is null
),

-- organic growth within the same segment
expansion_movements as (
    select account_id, month, segment as movement_segment, 'expansion' as movement_type, mrr - prior_mrr as movement_amount
    from account_month_mrr
    where prior_segment is not null and prior_segment = segment and mrr > prior_mrr
),

-- partial revenue loss within the same segment (not a full churn)
contraction_movements as (
    select account_id, month, segment as movement_segment, 'contraction' as movement_type, prior_mrr - mrr as movement_amount
    from account_month_mrr
    where prior_segment is not null and prior_segment = segment and mrr > 0 and mrr < prior_mrr
),

-- migration: reclassify prior_mrr from old segment to new segment (nets to zero)
migration_out_movements as (
    select account_id, month, prior_segment as movement_segment, 'migration_out' as movement_type, prior_mrr as movement_amount
    from account_month_mrr
    where prior_segment is not null and prior_segment <> segment
),

migration_in_movements as (
    select account_id, month, segment as movement_segment, 'migration_in' as movement_type, prior_mrr as movement_amount
    from account_month_mrr
    where prior_segment is not null and prior_segment <> segment
),

-- growth/contraction in the same month as a migration, booked to the new segment
migration_month_growth as (
    select
        account_id, month, segment as movement_segment,
        case when mrr > prior_mrr then 'expansion' else 'contraction' end as movement_type,
        abs(mrr - prior_mrr) as movement_amount
    from account_month_mrr
    where prior_segment is not null and prior_segment <> segment and mrr <> prior_mrr
),

-- churn: account's most recent subscription record has status = 'churned'
latest_subscription as (
    select
        account_id,
        status,
        end_date,
        row_number() over (partition by account_id order by start_date desc) as rn
    from {{ ref('stg_subscriptions') }}
),

last_mrr_row as (
    select
        account_id,
        month,
        segment,
        mrr,
        row_number() over (partition by account_id order by month desc) as rn
    from {{ ref('stg_mrr_by_account_month') }}
),

churn_movements as (
    select
        lmr.account_id,
        lmr.month + interval 1 month as month,
        lmr.segment as movement_segment,
        'churn' as movement_type,
        lmr.mrr as movement_amount
    from last_mrr_row lmr
    inner join latest_subscription ls
        on ls.account_id = lmr.account_id and ls.rn = 1 and ls.status = 'churned'
    where lmr.rn = 1 and lmr.mrr > 0
),

-- the churn month has no account_month_mrr row to source a 'starting'
-- contribution from -- add it synthetically so starting - churn = 0,
-- keeping the bridge equation exact for the month revenue formally drops.
churn_starting_movements as (
    select account_id, month, movement_segment, 'starting' as movement_type, movement_amount
    from churn_movements
),

unioned as (
    select * from starting_movements
    union all
    select * from new_logo_movements
    union all
    select * from expansion_movements
    union all
    select * from contraction_movements
    union all
    select * from migration_out_movements
    union all
    select * from migration_in_movements
    union all
    select * from migration_month_growth
    union all
    select * from churn_movements
    union all
    select * from churn_starting_movements
)

select
    account_id,
    month,
    movement_segment,
    movement_type,
    movement_amount
from unioned
where movement_amount is not null
  -- The synthetic churn month (last MRR row's month + 1) can land one
  -- calendar month past the data horizon for accounts whose last MRR row
  -- IS the horizon's final month -- there's no real "next month" of data
  -- to reconcile that phantom month against, so it's excluded here rather
  -- than left to produce a one-off, mostly-empty month in every downstream
  -- mart. Those accounts' final MRR simply stays uncounted as churn (right-
  -- censored, per the QA plan's explicit handling of accounts still active
  -- when the data window ends).
  and month <= date_trunc('month', cast('{{ var("analysis_as_of_date") }}' as date))
