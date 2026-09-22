-- Grain: one row per ticket_id. Account health score input (ticket
-- volume/severity); csat_score is nullable (not every ticket gets a
-- response).

select
    ticket_id,
    account_id,
    segment,
    created_date,
    resolved_date,
    severity,
    resolution_time_hours,
    csat_score,
    datediff('day', created_date, resolved_date) as resolution_days
from {{ ref('stg_support_tickets') }}
