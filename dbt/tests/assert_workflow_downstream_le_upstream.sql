-- QA plan invariant: downstream (completion) Actions <= upstream (trigger)
-- Actions, per account per period, always. A dbt test passes when this
-- query returns zero rows.

select
    account_id,
    month,
    upstream_actions,
    downstream_actions
from {{ ref('fact_workflow_chain_events') }}
where downstream_actions > upstream_actions
