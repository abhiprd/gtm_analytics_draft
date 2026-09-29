-- Grain: one row per experiment_id.
--
-- SHAPE: a dimension, not a fact -- same call dim_campaign already makes for
-- this project's other not-quite-typical "is this a dim or a fact" table. An
-- experiment is a durable, descriptive registry entry (hypothesis,
-- population/treatment/control definitions, target + guardrail metrics, a
-- logged result once resolved), not an event stream -- fact_experiment_
-- assignment.experiment_id is a foreign key into it, the same way
-- fact_campaign_engagement_events.campaign_id is a foreign key into
-- dim_campaign.
--
-- Currently catalogs the one real, already-running randomized experiment in
-- this data -- the paid/community marketing holdout program
-- (dim_campaign.is_holdout) -- rather than a fabricated one.
--
-- cell_quarters is passed through as the raw semicolon-separated text (e.g.
-- "2023Q3; 2024Q2; 2025Q1"); splitting it into an array/table is left for a
-- consumer that actually needs it, not invented here.

with experiments_registry as (

    select
        experiment_id,
        experiment_name,
        hypothesis,
        population_definition,
        treatment_definition,
        control_definition,
        assignment_mechanism,
        cell_quarters,
        start_date,
        end_date,
        target_metric,
        guardrail_metrics,
        designed_effect_size,
        status,
        result_metric,
        result_value,
        result_se,
        result_z,
        result_significant,
        result_as_of_date,
        result_detail,
        result_source
    from {{ ref('stg_experiments_registry') }}

)

select
    experiment_id,
    experiment_name,
    hypothesis,
    population_definition,
    treatment_definition,
    control_definition,
    assignment_mechanism,
    cell_quarters,
    start_date,
    end_date,
    target_metric,
    guardrail_metrics,
    designed_effect_size,
    status,
    result_metric,
    result_value,
    result_se,
    result_z,
    result_significant,
    result_as_of_date,
    result_detail,
    result_source
from experiments_registry
