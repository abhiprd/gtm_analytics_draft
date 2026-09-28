-- Grain: one row per company_id (covers every market_universe company,
-- prospect and customer alike). Light typing/renaming only.

select
    company_id,
    territory
from {{ source('raw', 'company_territory') }}
