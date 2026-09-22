-- Grain: one row per account_id per month. Product telemetry, aggregated to
-- monthly Actions-consumed by the generator (raw touch-level workflow
-- events are in workflow_chain_events / fact_workflow_chain_events).

select
    account_id,
    try_cast(month as date)            as month,
    segment,
    try_cast(actions_consumed as bigint) as actions_consumed,
    try_cast(active_workflows as integer) as active_workflows
from {{ source('raw', 'usage_monthly') }}
