-- Grain: one row per subscription_id. An account can have more than one
-- subscription record over its lifetime (renewals/contract replacements).
-- The account's CHURN event for revenue-bridge purposes (int_revenue_movements)
-- is derived from this table's most-recent-by-start_date row per account.

select
    subscription_id,
    account_id,
    segment,
    start_date,
    end_date,
    contract_type,
    committed_actions_monthly,
    status,
    row_number() over (partition by account_id order by start_date desc) = 1 as is_latest_subscription
from {{ ref('stg_subscriptions') }}
