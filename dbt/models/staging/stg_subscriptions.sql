-- Grain: one row per subscription_id. An account can have more than one
-- subscription row over its lifetime (contract renewals/replacements) --
-- NOT one row per account. committed_actions_monthly is null for SMB
-- (metered, no commitment).

select
    subscription_id,
    account_id,
    segment,
    try_cast(start_date as date)          as start_date,
    try_cast(end_date as date)            as end_date,
    contract_type,
    try_cast(committed_actions_monthly as double) as committed_actions_monthly,
    status
from {{ source('raw', 'subscriptions') }}
