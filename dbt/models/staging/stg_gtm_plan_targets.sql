-- Grain: one row per (layer1_metric, month), blended/company-wide (no
-- segment cut). FP&A/RevOps plan (target) values for 10 of the metric
-- tree's 11 Layer-1 nodes -- see generators/gtm_plan.py's module docstring
-- for why Activation carries no plan row and for the per-metric units
-- (revenue lines in USD/month, magic_number/am_efficiency as dimensionless
-- multiples, consumption_payback in months, onboarding_cs_efficiency as
-- AM/CS touchpoints per automated Action, and nrr/grr/logo_retention as
-- decimal ANNUAL-EQUIVALENT rates). This model does light typing only --
-- unit interpretation and the annual-vs-monthly mismatch against
-- mart_durability are surfaced at the mart layer, not resolved here.

select
    layer1_metric,
    try_cast(month as date)        as month,
    try_cast(plan_value as double) as plan_value,
    pillar
from {{ source('raw', 'gtm_plan_targets') }}
