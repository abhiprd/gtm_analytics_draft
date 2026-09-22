-- Grain: one row per account_id per month -- upstream (trigger) vs.
-- downstream (completion) Action counts, the silent-churn proxy input
-- (ingestion-without-completion rate, mid-chain abandonment). Incremental:
-- the largest, most event-like fact in this batch and the one that will
-- keep growing every time the generator adds another month of usage --
-- materialized/tested as full-refresh here on first build, then only new
-- months reprocess on subsequent runs.

select
    account_id,
    md5(account_id || '|' || cast(month as varchar)) as workflow_chain_event_id,
    month,
    upstream_actions,
    downstream_actions,
    upstream_actions - downstream_actions as ingestion_without_completion_actions,
    case
        when upstream_actions > 0
            then downstream_actions / upstream_actions
    end as full_chain_completion_rate
from {{ ref('stg_workflow_chain_events') }}

{% if is_incremental() %}
where month > (select coalesce(max(month), date '1900-01-01') from {{ this }})
{% endif %}
