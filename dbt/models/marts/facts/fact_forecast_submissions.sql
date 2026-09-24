-- Grain: one row per (opportunity_id, snapshot_date) -- one weekly
-- forecast call on one open opportunity. Snapshot grain, not deal grain: a
-- forecast submission is a judgement recorded on a Friday, and the same
-- opportunity carries one row for every Friday it was open (created_date
-- inclusive, close_date exclusive). Commercial/Enterprise only -- SMB's
-- no-touch, 0-7-day motion has no weekly forecast cadence to snapshot.
--
-- Distinct from fact_opportunities.forecast_category, which is a single
-- close-time field on the deal. This table is the point-in-time series
-- behind it and shares only the four-value vocabulary.
--
-- Derived here and nowhere else: the rep-vs-manager comparison. The build
-- spec calls the gap between the two categorisations "itself a signal", so
-- the ordinal rank each category sits at (Omitted 0 -> Commit 3) and the
-- signed gap between them are materialized once rather than re-derived by
-- every consumer. Orientation matches the generator's own read: the gap is
-- rep rank MINUS manager rank, so positive = rep more confident than
-- manager (the manager-downgrade case the QA plan's correlational test
-- keys on) and negative = manager more confident than rep.
--
-- No join to fact_opportunities: segment, opportunity_type and outcome all
-- live there at deal grain and joining them in would make a point-in-time
-- snapshot table carry close-time columns, which is exactly the leak the
-- generator is built to avoid. Consumers needing them join on
-- opportunity_id themselves.

with submissions as (

    select
        opportunity_id,
        snapshot_date,
        rep_forecast_category,
        manager_forecast_category
    from {{ ref('stg_forecast_submissions') }}

),

ranked as (

    select
        opportunity_id,
        snapshot_date,
        rep_forecast_category,
        manager_forecast_category,
        case rep_forecast_category
            when 'Omitted'   then 0
            when 'Pipeline'  then 1
            when 'Best Case' then 2
            when 'Commit'    then 3
        end as rep_forecast_rank,
        case manager_forecast_category
            when 'Omitted'   then 0
            when 'Pipeline'  then 1
            when 'Best Case' then 2
            when 'Commit'    then 3
        end as manager_forecast_rank
    from submissions

)

select
    md5(opportunity_id || '|' || cast(snapshot_date as varchar)) as forecast_submission_id,
    opportunity_id,
    snapshot_date,
    rep_forecast_category,
    manager_forecast_category,
    rep_forecast_rank,
    manager_forecast_rank,
    rep_forecast_rank - manager_forecast_rank as rep_minus_manager_rank_gap,
    rep_forecast_rank > manager_forecast_rank as is_manager_downgrade,
    manager_forecast_rank > rep_forecast_rank as is_manager_upgrade
from ranked
