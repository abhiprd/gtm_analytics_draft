-- Grain: one row per score_id -- one scoring event on one lead.
-- Light typing only. region_component is NULL when model_version =
-- 'lead_fit_v1_preregion': that model version never computed a region
-- term at all, so this is a real "not computed" null, not a coincidental
-- zero. Every other component is always populated.

select
    score_id,
    lead_id,
    try_cast(scored_at as date)              as scored_at,
    model_version,
    predicted_segment,
    try_cast(predicted_fit_score as double)    as predicted_fit_score,
    try_cast(employee_band_component as double) as employee_band_component,
    try_cast(industry_component as double)      as industry_component,
    try_cast(region_component as double)        as region_component,
    try_cast(noise_component as double)         as noise_component
from {{ source('raw', 'lead_scoring_history') }}
