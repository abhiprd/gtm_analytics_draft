-- Grain: one row per company_id (prospect + customer universe).
-- Joins to dim_accounts where is_customer = true (account_id populated).
-- No "territory" column exists anywhere in the raw data (dim_reps has no
-- territory field either) -- mart_tam_whitespace therefore slices
-- whitespace by region/industry/employee_count_band, not territory; a real
-- territory field would need to come from a future raw source.

select
    mu.company_id,
    mu.employee_count_band,
    mu.industry,
    mu.region,
    mu.is_personal_email_domain,
    mu.icp_fit_score,
    mu.is_customer,
    mu.was_ever_customer,
    mu.account_id,
    da.segment as customer_segment
from {{ ref('stg_market_universe') }} mu
left join {{ ref('dim_accounts') }} da on da.account_id = mu.account_id
