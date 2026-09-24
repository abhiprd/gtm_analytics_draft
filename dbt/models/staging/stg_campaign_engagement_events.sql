-- Grain: one row per event_id -- raw TOUCH grain. Never deduplicated to one
-- row per lead or per campaign: a lead is touched several times, by more
-- than one campaign and sometimes across sub-channels, and deduplicating
-- here would make first-touch, last-touch and linear attribution identical
-- by construction.
-- Light typing only.
-- `channel` on this table is the CAMPAIGN's sub-channel, which is not
-- always the lead's own sub-channel -- cross-sub-channel touch paths are
-- deliberate (5,786 of 135,965 touches today). Join to stg_leads for the
-- lead's channel; don't assume they match.

select
    event_id,
    lead_id,
    campaign_id,
    channel,
    event_type,
    try_cast(event_timestamp as timestamp) as event_timestamp
from {{ source('raw', 'campaign_engagement_events') }}
