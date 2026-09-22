-- Grain: one row per (model_name, as_of_date, metric_name) checkpoint.
-- Source CSV starts with zero data rows (no Phase 4 model has been
-- backtested yet) -- explicit try_cast throughout since DuckDB's read_csv
-- can't infer real column types from a header-only file.

select
    model_name,
    try_cast(as_of_date as date)     as as_of_date,
    metric_name,
    try_cast(metric_value as double) as metric_value
from {{ source('analytics', 'model_performance_history') }}
