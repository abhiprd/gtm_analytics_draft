-- Grain: one row per campaign_id. Named dim_campaign (singular) because
-- that is the exact name the build spec's Phase 2 dimension list uses.
--
-- SHAPE: a dimension, not a fact. A campaign is a durable, descriptive
-- entity with a validity window that touches and leads are attributed TO
-- (fact_campaign_engagement_events.campaign_id is a foreign key into it).
-- budget is an attribute of the program, not an additive per-event measure.
--
-- CHANNEL TAXONOMY: organic / paid / community is a DECOMPOSITION of the
-- `inbound_marketing` value of dim_accounts.channel, not a replacement for
-- it and not a second competing channel field. It carries no self_serve
-- volume (product-led, campaign-sourced only incidentally) and no
-- outbound_sdr volume (tracked under win rate per the metric tree's note).
-- Never join it to dim_accounts.channel as if the two were the same domain.
--
-- HOLDOUTS: is_holdout marks a genuinely suppressed control cell, not a
-- label -- its leads have the campaign treatment withheld (fewer touches,
-- no cross-campaign touches) and its budget is withheld rather than
-- re-spent, so the treated-vs-holdout gap is real incremental lift. Only
-- channels that can actually be switched off for a chosen cell carry one:
-- organic/SEO never does, so is_holdout is false for every organic row.

with campaigns as (

    select
        campaign_id,
        campaign_name,
        channel,
        start_date,
        end_date,
        budget,
        is_holdout
    from {{ ref('stg_campaigns') }}

)

select
    campaign_id,
    campaign_name,
    channel,
    start_date,
    end_date,
    date_trunc('month', start_date)            as start_month,
    datediff('day', start_date, end_date) + 1  as campaign_duration_days,
    budget,
    is_holdout
from campaigns
