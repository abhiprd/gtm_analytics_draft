-- Grain: one row per account_id per month. mrr already reflects the
-- account's point-in-time segment (verified against
-- account_segment_history -- an account's segment column here changes in
-- the same month its migration takes effect).

select
    account_id,
    try_cast(month as date) as month,
    segment,
    try_cast(mrr as double) as mrr
from {{ source('raw', 'mrr_by_account_month') }}
