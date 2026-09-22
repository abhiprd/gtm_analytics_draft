-- Grain: one row per (model_name, as_of_date, metric_name). Append-only
-- event log of Phase 4 model-eval checkpoints (build-time validation and
-- drift-monitor's recurring backtests both write here via
-- analytics/model_performance.py) -- referred to informally as
-- "mart_model_performance_history" in docs/acme-corp-analytics-methods.md
-- and the drift-monitor agent, but named fact_ here per dbt-conventions:
-- it's an append-only log with no aggregation, not a cross-cutting
-- business mart, and marts must never read stg_ directly (this does).

select
    md5(model_name || '|' || cast(as_of_date as varchar) || '|' || metric_name) as model_performance_id,
    model_name,
    as_of_date,
    metric_name,
    metric_value
from {{ ref('stg_model_performance_history') }}
