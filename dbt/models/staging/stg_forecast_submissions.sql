-- Grain: one row per (opportunity_id, snapshot_date). A weekly (Friday)
-- point-in-time forecast call on every open Commercial/Enterprise
-- opportunity -- a judgement recorded on a date, not a mutable property of
-- the deal. SMB is absent by construction: build spec Section 1 gives it a
-- no-touch motion closing in 0-7 days with no rep and no stage history, so
-- there is no weekly forecast cadence for an SMB deal to have.
--
-- Both categories draw on the same four-value vocabulary as
-- opportunities.forecast_category (Omitted / Pipeline / Best Case /
-- Commit) but are generated independently of it -- that column is a single
-- close-time field, this table is the point-in-time series. Light typing
-- only; the rep-vs-manager rank comparison is derived at the fact layer.

select
    opportunity_id,
    try_cast(snapshot_date as date) as snapshot_date,
    rep_forecast_category,
    manager_forecast_category
from {{ source('raw', 'forecast_submissions') }}
