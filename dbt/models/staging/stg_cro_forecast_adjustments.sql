-- Grain: at most one row per (period, segment), period being a fiscal
-- quarter ('YYYY-Qn') and segment being Commercial or Enterprise -- the two
-- segments that file a bottoms-up forecast at all. Sparse by design: the
-- CRO logs an override only where the top-down read of a segment-quarter
-- differs materially from the bottoms-up roll-up, so the presence of a row
-- is itself informative and an absent (period, segment) pair means "no
-- override", not "missing data".
--
-- `timestamp` keeps the build spec's column name rather than being renamed
-- to avoid the type keyword; DuckDB accepts it unquoted as an identifier.
-- Light typing only; period is left as its raw 'YYYY-Qn' label here and
-- resolved to calendar dates at the fact layer.

select
    period,
    segment,
    try_cast(adjustment_amount as double) as adjustment_amount,
    reason,
    try_cast("timestamp" as timestamp)    as "timestamp"
from {{ source('raw', 'cro_forecast_adjustments') }}
