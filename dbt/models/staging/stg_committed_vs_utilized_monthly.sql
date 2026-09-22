-- Grain: one row per account_id per month. Billing-side committed vs.
-- utilized Action volume -- the input Consumption Payback needs to exclude
-- subsidized, non-consuming capacity. committed_actions_monthly is null
-- for SMB months before a commitment exists (metered, no minimum).

select
    account_id,
    try_cast(month as date) as month,
    segment,
    try_cast(committed_actions_monthly as double) as committed_actions_monthly,
    try_cast(utilized_actions_monthly as double)  as utilized_actions_monthly
from {{ source('raw', 'committed_vs_utilized_monthly') }}
