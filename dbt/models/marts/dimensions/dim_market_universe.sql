-- Grain: one row per company_id (prospect + customer universe).
-- Joins to dim_accounts where is_customer = true (account_id populated).
-- territory is a deterministic sub-division of region (North America splits
-- into NA-East/NA-West; EMEA/APAC/LATAM each map 1:1 onto their own single
-- territory value), sourced from stg_company_territory, which resolves for
-- every row here -- every market_universe company has exactly one
-- territory row.

select
    mu.company_id,
    mu.employee_count_band,
    mu.industry,
    mu.region,
    ct.territory,
    mu.is_personal_email_domain,
    mu.icp_fit_score,
    mu.is_customer,
    mu.was_ever_customer,
    mu.account_id,
    da.segment as customer_segment
from {{ ref('stg_market_universe') }} mu
left join {{ ref('dim_accounts') }} da on da.account_id = mu.account_id
left join {{ ref('stg_company_territory') }} ct on ct.company_id = mu.company_id
