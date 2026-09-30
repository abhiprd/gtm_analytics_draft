-- Grain: one row per (rule_id, account_id, timestamp) trigger firing.
-- Operational log of Phase 4 automated-playbook-trigger firings
-- (analytics/playbook_triggers.py), per build spec line 118: "needed to
-- eventually backtest whether the triggers are worth keeping, not just to
-- fire them." Same fct_-naming rationale and same CSV-backed-source
-- pattern as fact_model_performance_history: a log, not a cross-cutting
-- business mart, materialized here so a backtest (drift-monitor or
-- otherwise) and a task-list read can query it like any other mart.
-- analytics/playbook_triggers.py writes the CSV directly
-- (log_triggers()/record_outcome()/read_trigger_log()) and never queries
-- this dbt-built mart.
--
-- The CSV stores what was observed or resolved once (outcome, owner, SLA
-- due time, recorded closure). sla_status and escalation_required are
-- COMPUTED here as of var('analysis_as_of_date') -- the repo's fixed
-- evaluation date, end of that day -- so the log itself never goes stale:
--   closed_within_sla / closed_late : a closure is recorded by that date
--   open_within_sla / breached      : otherwise, by whether sla_due_at has
--                                     passed
-- analytics/playbook_triggers.py's compute_sla_status() is the same rule.
-- escalation_to is null with escalation_reason 'no_reporting_line_in_
-- source' while the source data carries no manager / reporting line.

with triggers as (
    select * from {{ ref('stg_playbook_triggers') }}
),

evaluated as (
    select
        *,
        cast('{{ var("analysis_as_of_date") }}' as date) + interval 1 day as eval_instant
    from triggers
)

select
    md5(rule_id || '|' || account_id || '|' || cast(timestamp as varchar)) as playbook_trigger_id,
    rule_id,
    account_id,
    timestamp,
    resulting_action,
    outcome,
    outcome_date,
    outcome_metric_value,
    outcome_reason,
    outcome_window_end,
    outcome_evaluated_as_of,
    outcome_source,
    owner_rep_id,
    owner_role,
    owner_unresolved_reason,
    account_territory,
    sla_hours,
    sla_due_at,
    closed_at,
    case
        when sla_due_at is null then null
        when closed_at is not null and closed_at < eval_instant
            then case when closed_at <= sla_due_at then 'closed_within_sla' else 'closed_late' end
        when eval_instant <= sla_due_at then 'open_within_sla'
        else 'breached'
    end as sla_status,
    (closed_at is null or closed_at >= eval_instant) and eval_instant > sla_due_at as escalation_required,
    escalation_to,
    escalation_reason
from evaluated
