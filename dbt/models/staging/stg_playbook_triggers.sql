-- Grain: one row per (rule_id, account_id, timestamp) trigger firing.
-- Source CSV starts with zero data rows until analytics/playbook_
-- triggers.py's first build-time run -- explicit try_cast throughout
-- since DuckDB's read_csv can't infer real column types from a
-- header-only file (or from columns that are empty on every row),
-- matching stg_model_performance_history.sql's precedent. Each column
-- is cast to varchar first so an all-empty column parses the same way as
-- a populated one.

select
    rule_id,
    account_id,
    try_cast(timestamp as date) as timestamp,
    resulting_action,
    nullif(cast(outcome as varchar), '') as outcome,
    try_cast(nullif(cast(outcome_date as varchar), '') as date) as outcome_date,
    try_cast(nullif(cast(outcome_metric_value as varchar), '') as double) as outcome_metric_value,
    nullif(cast(outcome_reason as varchar), '') as outcome_reason,
    try_cast(nullif(cast(outcome_window_end as varchar), '') as date) as outcome_window_end,
    try_cast(nullif(cast(outcome_evaluated_as_of as varchar), '') as date) as outcome_evaluated_as_of,
    nullif(cast(outcome_source as varchar), '') as outcome_source,
    nullif(cast(owner_rep_id as varchar), '') as owner_rep_id,
    nullif(cast(owner_role as varchar), '') as owner_role,
    nullif(cast(owner_unresolved_reason as varchar), '') as owner_unresolved_reason,
    nullif(cast(account_territory as varchar), '') as account_territory,
    try_cast(nullif(cast(sla_hours as varchar), '') as integer) as sla_hours,
    try_cast(nullif(cast(sla_due_at as varchar), '') as timestamp) as sla_due_at,
    nullif(cast(escalation_to as varchar), '') as escalation_to,
    nullif(cast(escalation_reason as varchar), '') as escalation_reason,
    try_cast(nullif(cast(closed_at as varchar), '') as timestamp) as closed_at
from {{ source('analytics', 'playbook_triggers') }}
