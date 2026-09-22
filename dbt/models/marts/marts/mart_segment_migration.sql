-- Grain: one row per migration event (an account_id / effective_date pair
-- in fact_account_segment_history that is NOT the account's initial
-- segment row). trigger_reason is one of usage_threshold or
-- firmographic_rescore for every row here (the two migration-only values;
-- initial_firmographic/initial_default only ever appear on segment_sequence = 1,
-- which this model excludes by construction).
--
-- mrr_reclassified is the dollar value int_revenue_movements moved from
-- from_segment to to_segment for this event (the account's prior_mrr,
-- reclassified -- see int_revenue_movements design note #1). No skip-level
-- migration exists in this data (SMB -> Enterprise directly) per the build
-- spec's restriction; from_segment/to_segment pairs are always adjacent
-- (SMB->Commercial or Commercial->Enterprise).

with segment_history as (

    select
        account_id,
        segment,
        effective_date,
        trigger_reason,
        segment_sequence
    from {{ ref('fact_account_segment_history') }}

),

segment_history_with_lag as (

    -- lag() must run over EVERY row per account (including the initial
    -- segment_sequence = 1 row) before filtering to migrations only --
    -- filtering first would strip out the initial row an account's FIRST
    -- migration needs to look back to, making lag() return NULL for every
    -- account with exactly one migration (the common case).
    select
        account_id,
        segment,
        effective_date,
        trigger_reason,
        segment_sequence,
        lag(segment) over (partition by account_id order by effective_date) as from_segment
    from segment_history

),

migrations as (

    select
        account_id,
        from_segment,
        segment as to_segment,
        effective_date as migration_date,
        trigger_reason,
        segment_sequence
    from segment_history_with_lag
    where segment_sequence > 1

),

prior_span as (

    select account_id, segment, segment_end_date, days_in_segment
    from {{ ref('int_account_segment_spans') }}

),

migration_mrr as (

    select account_id, cast(month as date) as month, movement_amount
    from {{ ref('int_revenue_movements') }}
    where movement_type = 'migration_in'

)

select
    m.account_id,
    m.from_segment,
    m.to_segment,
    m.migration_date,
    m.trigger_reason,
    m.trigger_reason = 'usage_threshold'      as is_usage_threshold_migration,
    m.trigger_reason = 'firmographic_rescore' as is_firmographic_rescore_migration,
    ps.days_in_segment as days_in_prior_segment,
    mm.movement_amount as mrr_reclassified
from migrations m
left join prior_span ps
    on ps.account_id = m.account_id
    and ps.segment = m.from_segment
    and ps.segment_end_date = m.migration_date
left join migration_mrr mm
    on mm.account_id = m.account_id
    and mm.month = m.migration_date
