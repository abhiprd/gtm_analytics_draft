-- Grain: one row per activity_id. AM touchpoint (QBR for Enterprise,
-- check_in for Commercial) -- feeds Onboarding/CS Efficiency's numerator
-- (AM touchpoint volume) and the account health score's AM-sentiment input.
-- SMB never appears here -- no-touch means no human AM on either side.

select
    activity_id,
    account_id,
    segment,
    am_rep_id as rep_id,
    activity_date,
    activity_type,
    sentiment_score
from {{ ref('stg_am_activity') }}
