-- Grain: one row per activity_id (AM touchpoint: QBR for Enterprise,
-- check_in for Commercial). SMB has no AM activity at all -- no-touch
-- means no-touch on the retention side too.

select
    activity_id,
    account_id,
    segment,
    am_rep_id,
    try_cast(activity_date as date)   as activity_date,
    activity_type,
    try_cast(sentiment_score as double) as sentiment_score
from {{ source('raw', 'am_activity') }}
