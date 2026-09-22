-- Grain: one row per rep_id per quota-effective-date. Quota is
-- time-varying, not static -- feeds int_rep_capacity_periods.

select
    rep_id,
    try_cast(effective_date as date)  as effective_date,
    try_cast(amount as double)        as quota_amount
from {{ source('raw', 'quota_history') }}
