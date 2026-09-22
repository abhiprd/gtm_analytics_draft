-- Grain: one row per account_id per month. Recognized MRR, segment-stamped
-- at that point in time (verified to change in the same month an
-- account's migration takes effect). This is the base fact
-- int_revenue_movements diffs to build the Growth-pillar bridge.

select
    account_id,
    md5(account_id || '|' || cast(month as varchar)) as revenue_monthly_id,
    month,
    segment,
    mrr
from {{ ref('stg_mrr_by_account_month') }}
