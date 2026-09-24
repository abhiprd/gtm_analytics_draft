-- Grain: one row per lead_id.
-- Light typing only. account_id is populated only on converting leads
-- (is_converted = true); it is NULL by design for the non-converting
-- population, which is sized off a per-sub-channel lead-to-customer
-- conversion rate and drawn from market_universe's never-customer
-- companies.
-- lead_score is the lead's composite as of its TERMINAL state (conversion,
-- or the end of its engagement), NOT a point-in-time score -- it reads
-- observed engagement depth, so it must not be used as a feature to predict
-- the conversion it already reflects. Point-in-time scoring belongs to the
-- separate lead_scoring_history source (not yet generated); this column is
-- not a substitute for it.

select
    lead_id,
    account_id,
    company_id,
    channel,
    try_cast(created_date as date)   as created_date,
    try_cast(lead_score as double)   as lead_score,
    try_cast(converted_date as date) as converted_date,
    try_cast(is_converted as boolean) as is_converted
from {{ source('raw', 'leads') }}
