-- Grain: one row per (rule_id, account_id, timestamp) trigger firing.
-- Source CSV starts with zero data rows until analytics/playbook_
-- triggers.py's first build-time run -- explicit try_cast throughout
-- since DuckDB's read_csv can't infer real column types from a
-- header-only file, matching stg_model_performance_history.sql's
-- precedent.

select
    rule_id,
    account_id,
    try_cast(timestamp as date) as timestamp,
    resulting_action,
    nullif(outcome, '') as outcome
from {{ source('analytics', 'playbook_triggers') }}
