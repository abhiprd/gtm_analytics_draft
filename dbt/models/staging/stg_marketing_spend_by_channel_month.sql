-- Grain: one row per channel per month. Channel taxonomy here is the same
-- coarse 3-value field as accounts.channel (inbound_marketing /
-- outbound_sdr / self_serve) -- NOT the finer organic/paid/community split
-- the metric tree's Layer-2 "Pipeline generated" node describes. That finer
-- split needs campaign/lead-source data that doesn't exist yet (see
-- mart_growth_bridge header comment). This table only covers 2023-01
-- onward (36 months), even though the rest of the raw data goes back to
-- 2020 -- CAC/payback math is only computable for that recent window.

select
    channel,
    try_cast(month as date)         as month,
    try_cast(spend as double)       as spend,
    try_cast(new_accounts as integer) as new_accounts
from {{ source('raw', 'marketing_spend_by_channel_month') }}
