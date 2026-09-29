-- Grain: one row per score_id -- one point-in-time scoring event on one
-- lead. Not the lead's terminal/outcome-aware lead_score on fact_leads:
-- this is the accumulating log of every scoring pass a lead received over
-- time, keyed to score_id the same way fact_opportunity_stage_history is
-- keyed to its own surrogate id against fact_opportunities.
--
-- METHODOLOGY: predicted_fit_score is a re-application of
-- firmographics.py's compute_fit_score() to the leads.csv population over
-- time, not a new or independently-invented scoring methodology -- see the
-- build spec's market_universe.icp_fit_score framing (same logic, applied
-- to the whole universe rather than just inbound leads).
--
-- MODEL_VERSION: a real, dateable model change, not a fabricated version
-- history. lead_fit_v2_region_aware (from generators/lead_scoring.py's
-- MODEL_CUTOVER_DATE, 2024-07-01) is compute_fit_score() exactly, region
-- term included. lead_fit_v1_preregion is the identical employee-band and
-- industry coefficients with no region term at all -- no new weights were
-- invented for the earlier version.
--
-- NULLABILITY: region_component is NULL wherever model_version =
-- 'lead_fit_v1_preregion' -- that model version never computed a region
-- term, so this is a real "not computed" null, not a coincidental zero.
-- Every other score component is always populated.
--
-- NO-LEAKAGE / POINT-IN-TIME: every scoring event on a converting lead was
-- computed from company firmographics only and lands strictly before that
-- lead's converted_date -- the generator never had access to
-- is_converted/converted_date when it produced a score. This is what makes
-- the table usable to validate model predictions against outcomes the
-- scoring never saw (Wave 7's model-validation/drift-detection artifact);
-- already covered by tests/test_phase1_batch11.py's no-leakage tests on
-- the raw data, not re-checked here.

select
    score_id,
    lead_id,
    scored_at,
    model_version,
    predicted_segment,
    predicted_fit_score,
    employee_band_component,
    industry_component,
    region_component,
    noise_component
from {{ ref('stg_lead_scoring_history') }}
