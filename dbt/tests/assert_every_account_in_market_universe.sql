-- Build spec Section 5: every real customer account should also have a
-- corresponding market_universe row marked is_customer = true, so
-- penetration is a clean ratio rather than an estimate. A dbt test passes
-- when this query returns zero rows.

select da.account_id
from {{ ref('dim_accounts') }} da
left join {{ ref('dim_market_universe') }} dmu
    on dmu.account_id = da.account_id and dmu.is_customer = true
where dmu.account_id is null
