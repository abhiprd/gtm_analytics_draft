-- Grain: one row per account_id per segment-effective-date (initial row at
-- account creation plus one row per migration event). trigger_reason takes
-- exactly 4 values: initial_firmographic, initial_default, usage_threshold,
-- firmographic_rescore.

select
    account_id,
    segment,
    try_cast(effective_date as date) as effective_date,
    trigger_reason
from {{ source('raw', 'account_segment_history') }}
