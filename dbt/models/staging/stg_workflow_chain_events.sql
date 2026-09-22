-- Grain: one row per account_id per month -- upstream (trigger) vs.
-- downstream (completion) Action counts, for detecting partial-chain
-- abandonment (silent-churn proxy). Invariant enforced downstream:
-- downstream_actions <= upstream_actions, always (QA plan + dbt singular
-- test assert_workflow_downstream_le_upstream).

select
    account_id,
    try_cast(month as date)              as month,
    try_cast(upstream_actions as bigint)   as upstream_actions,
    try_cast(downstream_actions as bigint) as downstream_actions
from {{ source('raw', 'workflow_chain_events') }}
