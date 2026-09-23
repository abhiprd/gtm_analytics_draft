-- Grain: one row per login_id. Feeds the account health score's
-- engagement/login-frequency input, independent of usage volume by
-- construction (see generators/product_logins.py) -- what makes a
-- high-usage, low-login "automated but healthy" account distinguishable
-- from a genuinely disengaging one.

select
    login_id,
    account_id,
    segment,
    login_date
from {{ ref('stg_product_logins') }}
