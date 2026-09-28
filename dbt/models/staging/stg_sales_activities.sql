-- Grain: one row per activity_id -- a single rep-opportunity sales-
-- engagement touch (call, email, meeting, demo). Commercial/Enterprise
-- new-business opportunities only; SMB's no-touch motion and expansion/
-- renewal work are out of scope by design. `outcome`'s vocabulary is
-- scoped per activity_type (call/email/meeting/demo each have their own
-- set of valid outcomes) rather than shared across all four. Light typing
-- only.

select
    activity_id,
    rep_id,
    opportunity_id,
    activity_type,
    outcome,
    try_cast(activity_timestamp as timestamp) as activity_timestamp,
    contact_ref,
    try_cast(competitive_signal as boolean) as competitive_signal,
    try_cast(is_outbound_touch as boolean) as is_outbound_touch
from {{ source('raw', 'sales_activities') }}
