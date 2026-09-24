-- QA plan invariant (Marketing attribution): campaigns.is_holdout is set
-- only on channels the holdout program actually defines. A holdout is a
-- genuinely suppressed control cell, so it only exists where the treatment
-- can actually be switched off for a chosen cell -- paid and community. A
-- flag on an organic/SEO campaign would have no operational meaning.
-- A dbt test passes when this query returns zero rows.

select
    campaign_id,
    campaign_name,
    channel,
    is_holdout
from {{ ref('dim_campaign') }}
where is_holdout
  and channel not in ('paid', 'community')
