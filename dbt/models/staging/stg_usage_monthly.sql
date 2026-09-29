-- Grain: one row per account_id per month. Product telemetry, generated
-- directly at this grain -- there is no per-Action-step source anywhere
-- upstream to aggregate from. workflow_chain_events / fact_workflow_chain_events
-- is the companion upstream-vs-downstream Action view, also account_id x
-- month grain, not touch-level (see that model's own header).

select
    account_id,
    try_cast(month as date)            as month,
    segment,
    try_cast(actions_consumed as bigint) as actions_consumed,
    try_cast(active_workflows as integer) as active_workflows
from {{ source('raw', 'usage_monthly') }}
