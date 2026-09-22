-- Grain: one row per channel per month. Marketing spend, coarse 3-value
-- channel taxonomy (inbound_marketing / outbound_sdr / self_serve) -- see
-- staging comment for the gap vs. the metric tree's finer organic/paid/
-- community split. Covers 2023-01 onward only (36 months), not the full
-- 2020-2025 data horizon.

select
    channel,
    md5(channel || '|' || cast(month as varchar)) as marketing_spend_id,
    month,
    spend,
    new_accounts,
    case when new_accounts > 0 then spend / new_accounts end as cac_unblended
from {{ ref('stg_marketing_spend_by_channel_month') }}
