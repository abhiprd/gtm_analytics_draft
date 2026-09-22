-- Grain: one row per rep_id per status-effective-date (active / departed /
-- on-leave) -- feeds int_rep_capacity_periods and headcount trending.

select
    rep_id,
    status,
    try_cast(effective_date as date) as effective_date
from {{ source('raw', 'rep_status_history') }}
