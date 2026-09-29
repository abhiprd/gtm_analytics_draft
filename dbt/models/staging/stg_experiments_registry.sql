-- Grain: one row per experiment_id -- a logged, randomized experiment
-- (design, population/treatment/control definitions, target + guardrail
-- metrics, and a logged result once resolved). Light typing only. Currently
-- catalogs the one real, already-running randomized experiment in this
-- data -- the paid/community marketing holdout program
-- (dim_campaign.is_holdout) -- rather than a fabricated one.
-- cell_quarters is a semicolon-separated list of quarter labels (e.g.
-- "2023Q3; 2024Q2; 2025Q1"), deliberately left as text here -- splitting it
-- into an array is business logic that doesn't belong in staging.

select
    experiment_id,
    experiment_name,
    hypothesis,
    population_definition,
    treatment_definition,
    control_definition,
    assignment_mechanism,
    cell_quarters,
    try_cast(start_date as date)          as start_date,
    try_cast(end_date as date)            as end_date,
    target_metric,
    guardrail_metrics,
    try_cast(designed_effect_size as double) as designed_effect_size,
    status,
    result_metric,
    try_cast(result_value as double)      as result_value,
    try_cast(result_se as double)         as result_se,
    try_cast(result_z as double)          as result_z,
    try_cast(result_significant as boolean) as result_significant,
    try_cast(result_as_of_date as date)   as result_as_of_date,
    result_detail,
    result_source
from {{ source('raw', 'experiments_registry') }}
