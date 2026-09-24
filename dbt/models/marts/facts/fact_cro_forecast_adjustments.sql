-- Grain: at most one row per (period, segment) -- one logged CRO override
-- of a segment-quarter's bottoms-up forecast roll-up. Log grain, sparse by
-- design: a row exists only where the top-down read differed materially
-- from the roll-up, so the presence of a row is itself informative and an
-- absent (period, segment) pair means "no override filed", never "missing
-- data". Commercial/Enterprise only -- they are the two segments that file
-- a bottoms-up forecast at all.
--
-- fct_-named rather than mart_-named per dbt-conventions: this is an
-- event/log table at its own grain, not a cross-cutting rollup aligned to
-- a metric-tree pillar -- the same call made for
-- fact_model_performance_history, and it keeps this table discoverable
-- alongside fact_forecast_submissions, the bottoms-up figure it overrides.
--
-- Derived here: period_start_date / period_end_date, resolving the raw
-- 'YYYY-Qn' label to calendar dates so a consumer can join this to
-- dim_date or to a monthly mart without re-parsing the string. The label
-- itself is kept as generated.

with adjustments as (

    select
        period,
        segment,
        adjustment_amount,
        reason,
        "timestamp"
    from {{ ref('stg_cro_forecast_adjustments') }}

),

with_period_dates as (

    select
        period,
        segment,
        adjustment_amount,
        reason,
        "timestamp",
        cast(split_part(period, '-Q', 1) as integer) as period_year,
        cast(split_part(period, '-Q', 2) as integer) as period_quarter
    from adjustments

)

select
    md5(period || '|' || segment)                       as cro_forecast_adjustment_id,
    period,
    period_year,
    period_quarter,
    make_date(period_year, period_quarter * 3 - 2, 1)   as period_start_date,
    last_day(make_date(period_year, period_quarter * 3, 1)) as period_end_date,
    segment,
    adjustment_amount,
    adjustment_amount < 0                                as is_downward_adjustment,
    reason,
    "timestamp"
from with_period_dates
