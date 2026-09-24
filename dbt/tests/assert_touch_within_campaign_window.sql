-- QA plan invariant (Marketing attribution): every touch is attributed only
-- to a campaign whose window actually covers that touch's date -- a touch
-- never lands on a campaign that had not started or had already ended. Also
-- asserts the touch's channel matches its campaign's channel, since the
-- accepted_values test on each column separately cannot express agreement
-- between the two.
-- A dbt test passes when this query returns zero rows.

select
    e.event_id,
    e.campaign_id,
    e.event_date,
    e.channel as event_channel,
    c.channel as campaign_channel,
    c.start_date,
    c.end_date
from {{ ref('fact_campaign_engagement_events') }} e
join {{ ref('dim_campaign') }} c on c.campaign_id = e.campaign_id
where e.event_date not between c.start_date and c.end_date
   or e.channel <> c.channel
