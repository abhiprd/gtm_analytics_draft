-- Grain: one row per opportunity_id. One pipeline table for all three
-- segments and all opportunity_types (new_business / renewal / expansion),
-- filterable -- not parallel per-segment structures.

select
    opportunity_id,
    account_id,
    company_id,
    segment,
    opportunity_type,
    owner_role,
    rep_id,
    is_won,
    loss_reason,
    forecast_category,
    amount,
    list_price,
    discount_rate,
    poc_outcome,
    created_date,
    close_date,
    datediff('day', created_date, close_date) as days_in_pipeline
from {{ ref('stg_opportunities') }}
