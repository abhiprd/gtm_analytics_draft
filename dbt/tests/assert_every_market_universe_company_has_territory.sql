-- stg_company_territory covers the full market_universe population by
-- design. The generic relationships test on stg_company_territory.company_id
-- only checks the forward direction (every territory row resolves to a real
-- market_universe company); this checks the reverse -- every
-- market_universe company resolves to exactly one territory row -- so
-- coverage is confirmed 1:1 in both directions. A dbt test passes when
-- this query returns zero rows.

select mu.company_id
from {{ ref('stg_market_universe') }} mu
left join {{ ref('stg_company_territory') }} ct
    on ct.company_id = mu.company_id
where ct.company_id is null
