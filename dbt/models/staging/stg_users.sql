-- Grain: one row per rep_id (static attributes only -- source table is
-- literally named "users" in the CRM; renamed to reps everywhere downstream
-- since that's what these rows represent). Time-varying quota and status
-- live in stg_quota_history / stg_rep_status_history and get assembled
-- into periods in int_rep_capacity_periods.

select
    rep_id,
    rep_type,
    segment,
    try_cast(hire_date as date) as hire_date,
    try_cast(nullif(trim(cast(book_size as varchar)), '') as integer) as book_size
from {{ source('raw', 'users') }}
