-- Grain: one row per opportunity_id. One pipeline table for all three
-- segments, filterable by opportunity_type/owner_role -- not parallel
-- per-segment structures. loss_reason is blank (empty string in the raw
-- CSV) for every won deal; normalized to NULL here rather than left as ''.
-- SMB opportunities (owner_role = 'system') carry no rep_id.

select
    opportunity_id,
    account_id,
    company_id,
    segment,
    opportunity_type,
    owner_role,
    nullif(trim(rep_id), '')                    as rep_id,
    try_cast(is_won as boolean)                 as is_won,
    nullif(trim(loss_reason), '')                as loss_reason,
    forecast_category,
    try_cast(amount as double)                  as amount,
    try_cast(list_price as double)               as list_price,
    try_cast(discount_rate as double)            as discount_rate,
    nullif(trim(poc_outcome), '')                as poc_outcome,
    try_cast(created_date as date)               as created_date,
    try_cast(close_date as date)                 as close_date
from {{ source('raw', 'opportunities') }}
