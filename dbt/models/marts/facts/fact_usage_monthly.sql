-- Grain: one row per account_id per month. Product telemetry: Actions
-- consumed and active workflows.

select
    account_id,
    md5(account_id || '|' || cast(month as varchar)) as usage_monthly_id,
    month,
    segment,
    actions_consumed,
    active_workflows
from {{ ref('stg_usage_monthly') }}
