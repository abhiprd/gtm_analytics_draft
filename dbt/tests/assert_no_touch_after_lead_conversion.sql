-- QA plan invariant (Marketing attribution): no touch attributed as
-- pre-conversion evidence may fall on or after its lead's converted_date.
-- Touches are placed on [created_date, converted_date - 1 day], so every
-- attributed pre-conversion touch is strictly before the signup day, with
-- no same-day ambiguity to resolve downstream. Also checks the lower bound:
-- no touch predates its lead's created_date.
-- A dbt test passes when this query returns zero rows.

select
    e.event_id,
    e.lead_id,
    e.event_timestamp,
    l.created_date,
    l.converted_date
from {{ ref('fact_campaign_engagement_events') }} e
join {{ ref('fact_leads') }} l on l.lead_id = e.lead_id
where e.event_date < l.created_date
   or (l.is_converted and e.event_timestamp >= l.converted_date)
