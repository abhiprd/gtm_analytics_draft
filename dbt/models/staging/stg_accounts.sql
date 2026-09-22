-- Grain: one row per account_id.
-- Light typing/renaming only -- accounts.segment here is the account's
-- CURRENT segment (post any migration); full history lives in
-- stg_account_segment_history / fact_account_segment_history.

select
    account_id,
    company_id,
    segment,
    employee_count_band,
    industry,
    region,
    channel,
    try_cast(signup_date as date)      as signup_date,
    try_cast(icp_fit_score as double)  as icp_fit_score,
    try_cast(is_personal_email_domain as boolean) as is_personal_email_domain
from {{ source('raw', 'accounts') }}
