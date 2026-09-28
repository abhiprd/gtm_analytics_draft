-- Grain: one row per (rule_id, account_id, timestamp) trigger firing.
-- Append-only operational log of Phase 4 automated-playbook-trigger
-- firings (analytics/playbook_triggers.py), per build spec line 118:
-- "needed to eventually backtest whether the triggers are worth
-- keeping, not just to fire them." Same fct_-naming rationale and same
-- CSV-backed-source pattern as fact_model_performance_history: an
-- append-only log, not a cross-cutting business mart, materialized here
-- so a future backtest (drift-monitor or otherwise) can read it like any
-- other mart. analytics/playbook_triggers.py itself writes the CSV
-- directly via csv.DictReader/writer (log_triggers()/read_trigger_log())
-- and never queries this dbt-built mart -- unlike
-- fact_model_performance_history, which analytics-engineering-
-- conventions names as the one artifact Phase 4 code both reads and
-- writes, this table is write-only from Phase 4's side, read-only from
-- dbt's/a future consumer's side.

select
    md5(rule_id || '|' || account_id || '|' || cast(timestamp as varchar)) as playbook_trigger_id,
    rule_id,
    account_id,
    timestamp,
    resulting_action,
    outcome
from {{ ref('stg_playbook_triggers') }}
