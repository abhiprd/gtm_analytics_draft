-- Grain: one row per lead_id.
--
-- SHAPE -- why a fact and not a dimension (the non-obvious call in this
-- batch): a lead is not a durable entity with descriptive attributes, it is
-- a funnel occurrence with a lifecycle (created_date -> converted_date) and
-- an outcome measure (is_converted, lead_score, days_to_conversion) that
-- the Pipeline-generated branch of the metric tree aggregates. Structurally
-- it is an accumulating-snapshot fact, and it sits in exactly the same
-- relationship to fact_campaign_engagement_events that fact_opportunities
-- sits in to fact_opportunity_stage_history -- an outcome-bearing parent
-- fact with a child event stream keyed to it. The firmographic attributes
-- a dimension would carry (industry, region, employee band, icp_fit_score)
-- are not on this table at all; they live on dim_market_universe, reachable
-- via company_id. That is what settles it.
--
-- NULLABILITY: account_id and converted_date are populated only when
-- is_converted = true. Every account acquired through inbound_marketing is
-- explained by exactly one converting lead, created strictly earlier than
-- that account's signup_date; converting leads are therefore 1:1 with the
-- inbound_marketing slice of dim_accounts, in both directions. The
-- non-converting population (the large majority) is sized off a stated
-- per-sub-channel lead-to-customer conversion rate and draws its companies
-- from market_universe rows that are neither current nor former customers,
-- so account_id is legitimately NULL there -- not missing data.
--
-- POINT-IN-TIME WARNING: lead_score is the lead's composite as of its
-- TERMINAL state, not a point-in-time score. It reads observed engagement
-- depth, so a model using it to predict conversion leaks the outcome. It is
-- exposed here for channel-mix and lead-quality reporting only. Point-in-
-- time scoring belongs to lead_scoring_history (not yet generated); this
-- column is not a substitute for it.
--
-- CHANNEL TAXONOMY: organic / paid / community decomposes the
-- `inbound_marketing` value of dim_accounts.channel -- not a replacement
-- for it, and carrying no self_serve or outbound_sdr volume. Channel stays
-- orthogonal to segment: each sub-channel produces leads in all three
-- segments, with a firmographic tilt rather than a partition.

with leads as (

    select
        lead_id,
        account_id,
        company_id,
        channel,
        created_date,
        lead_score,
        converted_date,
        is_converted
    from {{ ref('stg_leads') }}

)

select
    lead_id,
    account_id,
    company_id,
    channel,
    created_date,
    converted_date,
    is_converted,
    lead_score,
    -- Lead-to-signup gap in days. NULL for non-converting leads. Strictly
    -- positive for converting ones: a lead created the same day as the
    -- signup it explains would leave no funnel behind it to attribute.
    case
        when is_converted
            then datediff('day', created_date, converted_date)
    end as days_to_conversion
from leads
