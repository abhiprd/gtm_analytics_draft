-- Grain: one row per (layer1_metric, month). FP&A/RevOps plan (target)
-- values for 10 of the metric tree's 11 Layer-1 nodes, blended/company-wide
-- (no segment cut) -- exactly what the Layer-1 scorecard displays.
-- Activation is excluded by design: the readout reports it against a
-- trailing baseline ("2.4d last month"), not a plan figure, so a plan row
-- for it would be unused. See generators/gtm_plan.py's module docstring and
-- the build spec's gtm_plan_targets bullet.
--
-- NOT built here: any comparison to actuals. That is a later, separate
-- task (the Phase 4 variance-diagnostic engine) -- this mart only exposes
-- the plan data cleanly.
--
-- UNITS -- surfaced here exactly as generated, not normalized against the
-- actuals-side marts (see column-level notes in _mart_schema.yml and
-- generators/gtm_plan.py's "UNITS" section for the full citation):
--   - new_logo_consumption_revenue / expansion_consumption_revenue /
--     contraction_churned_revenue: USD, whole dollars of monthly MRR
--     movement (contraction+churn stored as a POSITIVE magnitude, matching
--     int_revenue_movements / mart_growth_bridge).
--   - magic_number / am_efficiency: dimensionless multiples.
--   - consumption_payback: months.
--   - onboarding_cs_efficiency: AM/CS touchpoints per automated Action
--     delivered (lower is better) -- matches
--     mart_efficiency.onboarding_cs_efficiency_ratio's orientation, not its
--     reciprocal.
--   - nrr / grr / logo_retention: decimal, ANNUAL-EQUIVALENT rates (1.15,
--     not 115). mart_durability currently exposes these three at MONTHLY
--     grain -- this mart does not annualize or otherwise reconcile that
--     mismatch. A future consumer comparing plan to actuals must annualize
--     (or use a trailing-twelve-month figure) first.

with plan as (

    select
        layer1_metric,
        month,
        pillar,
        plan_value
    from {{ ref('stg_gtm_plan_targets') }}

)

select
    layer1_metric,
    month,
    pillar,
    plan_value
from plan
