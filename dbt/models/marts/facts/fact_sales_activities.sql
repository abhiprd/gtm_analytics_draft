-- Grain: one row per rep-opportunity sales-engagement touch (activity_id)
-- -- a call, email, meeting, or demo. Commercial/Enterprise new-business
-- opportunities only; SMB's no-touch motion and expansion/renewal activity
-- are out of scope by design (see generators/sales_activities.py). Every
-- "booked" meeting (activity_type = 'meeting', outcome = 'booked') has
-- exactly one later resolution row (held/no_show/rescheduled/cancelled) on
-- the same opportunity_id -- meetings_booked is this table's antecedent
-- event, not a separate raw table.
--
-- No join to fact_opportunities: segment, is_won, loss_reason and every
-- other deal-level column live there, not here -- the same discipline
-- fact_forecast_submissions follows for the same reason. Consumers join on
-- opportunity_id themselves.
--
-- NOT COMPUTED HERE: per-activity_type outcome resolution flags (e.g. "was
-- this meeting held"), multi-threading counts (distinct contact_ref per
-- opportunity), and booked-to-resolution pairing. Each of those is a
-- judgement call belonging to a specific downstream diagnostic (deal-level
-- diagnostics, rep productivity -- both Wave 4, not yet built), not a
-- structural property of a single touch row. Baking one reading of them in
-- here would encode that artifact's assumptions into the fact table.
--
-- Incremental per the dbt-conventions materialization rule: activity_date
-- is derived alongside activity_timestamp for the same reason
-- fact_campaign_engagement_events derives event_date -- a stable date
-- column to filter and dedupe incremental loads on.

with activities as (

    select
        activity_id,
        rep_id,
        opportunity_id,
        activity_type,
        outcome,
        activity_timestamp,
        contact_ref,
        competitive_signal,
        is_outbound_touch
    from {{ ref('stg_sales_activities') }}

)

select
    activity_id,
    rep_id,
    opportunity_id,
    activity_type,
    outcome,
    activity_timestamp,
    cast(activity_timestamp as date) as activity_date,
    contact_ref,
    competitive_signal,
    is_outbound_touch
from activities

{% if is_incremental() %}
where cast(activity_timestamp as date) >= (
    select coalesce(max(activity_date), date '1900-01-01') from {{ this }}
)
{% endif %}
