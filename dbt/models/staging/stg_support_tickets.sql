-- Grain: one row per ticket_id. csat_score is frequently null (not every
-- ticket gets a satisfaction response) -- left nullable, not defaulted.

select
    ticket_id,
    account_id,
    segment,
    try_cast(created_date as date)          as created_date,
    try_cast(resolved_date as date)         as resolved_date,
    severity,
    try_cast(resolution_time_hours as double) as resolution_time_hours,
    try_cast(csat_score as double)          as csat_score
from {{ source('raw', 'support_tickets') }}
