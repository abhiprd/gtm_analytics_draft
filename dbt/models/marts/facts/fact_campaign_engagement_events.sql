-- Grain: one row per event_id -- raw TOUCH grain, one row per touch. This
-- is the multi-touch-attribution event stream and it is NEVER deduplicated
-- to one row per lead or one row per campaign. A lead is touched several
-- times, by more than one campaign and sometimes across sub-channels;
-- collapsing that here would make first-touch, last-touch and linear
-- attribution return identical answers by construction, which is precisely
-- what this table exists to prevent.
--
-- POINT-IN-TIME SAFETY (the invariant this table is responsible for):
-- no touch on a converting lead may fall on or after that lead's
-- converted_date. Touches are placed on [created_date, converted_date - 1
-- day], so every attributed pre-conversion touch is strictly before the
-- signup day with no same-day ambiguity to resolve downstream. Every touch
-- also falls inside its own campaign's [start_date, end_date] window -- a
-- touch never lands on a campaign that had not started or had already
-- ended -- and timestamps are strictly unique within a lead, so a lead's
-- first-touch and last-touch positions are never ambiguous. Enforced by
-- tests/assert_no_touch_after_lead_conversion.sql,
-- tests/assert_touch_within_campaign_window.sql and
-- tests/assert_lead_touch_timestamps_unique.sql.
--
-- CHANNEL: this is the CAMPAIGN's sub-channel and it is not always the
-- lead's own sub-channel -- cross-sub-channel touch paths are deliberate
-- and load-bearing for attribution. Join to fact_leads for the lead's
-- channel rather than assuming the two agree.
--
-- NOT COMPUTED HERE -- touch_seq / is_first_touch / is_last_touch: these
-- are window functions over a lead's whole touch history, which an
-- incremental model cannot maintain correctly (a newly-arrived touch
-- silently invalidates the previously-written last-touch flag for that
-- lead). They are also attribution decisions, not raw-stream facts. The
-- Phase 4 marketing attribution artifact derives them from this mart.
--
-- Incremental per the dbt-conventions materialization rule: this is the
-- large, append-only event fact in this batch (135,965 touches and growing
-- with every campaign month). The filter is >= max(event_date) rather than
-- >, so the boundary day is always reprocessed; delete+insert on event_id
-- then replaces those rows instead of duplicating them.

with touches as (

    select
        event_id,
        lead_id,
        campaign_id,
        channel,
        event_type,
        event_timestamp
    from {{ ref('stg_campaign_engagement_events') }}

)

select
    event_id,
    lead_id,
    campaign_id,
    channel,
    event_type,
    event_timestamp,
    cast(event_timestamp as date) as event_date
from touches

{% if is_incremental() %}
where cast(event_timestamp as date) >= (
    select coalesce(max(event_date), date '1900-01-01') from {{ this }}
)
{% endif %}
