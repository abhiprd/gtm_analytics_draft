-- Grain: one row per company_id (prospect + customer universe). Every real
-- customer account has a corresponding row here with is_customer = true and
-- account_id populated -- that link is what makes TAM/whitespace math a
-- clean ratio instead of an estimate.

select
    company_id,
    employee_count_band,
    industry,
    region,
    try_cast(is_personal_email_domain as boolean) as is_personal_email_domain,
    try_cast(icp_fit_score as double)             as icp_fit_score,
    try_cast(is_customer as boolean)              as is_customer,
    try_cast(was_ever_customer as boolean)        as was_ever_customer,
    nullif(trim(account_id), '')                  as account_id
from {{ source('raw', 'market_universe') }}
