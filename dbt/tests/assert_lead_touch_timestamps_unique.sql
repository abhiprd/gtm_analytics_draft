-- QA plan invariant (Marketing attribution): touches are strictly ordered
-- within a lead -- two touches sharing a timestamp leave that lead's
-- first-touch and last-touch position ambiguous, which is exactly what
-- attribution reads. Note this is uniqueness WITHIN a lead, not globally:
-- two different leads may legitimately be touched at the same instant, so
-- a column-level unique test on event_timestamp would be wrong.
-- A dbt test passes when this query returns zero rows.

select
    lead_id,
    event_timestamp,
    count(*) as touches_sharing_timestamp
from {{ ref('fact_campaign_engagement_events') }}
group by lead_id, event_timestamp
having count(*) > 1
