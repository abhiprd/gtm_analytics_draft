-- Grain: one row per login_id. Engagement/login frequency, distinct from
-- usage volume (fact_usage_monthly) -- feeds the account health score's
-- login-frequency input (see docs/acme-corp-phase1-data-qa-plan.md's
-- health-score section: a fully-automated account can be healthy despite
-- low logins, so this must stay a separate signal, not usage relabeled).

select
    login_id,
    account_id,
    segment,
    try_cast(login_date as date) as login_date
from {{ source('raw', 'product_logins') }}
