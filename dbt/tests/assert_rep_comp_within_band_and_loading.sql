-- Every rep's compensation must sit inside its rep_type's OTE band and carry a
-- loading factor inside the documented range. Bands mirror
-- generators/config.py REP_OTE_BAND; the loading range is
-- 1 + REP_LOADING_BENEFITS_TAX + REP_LOADING_TOOLING_TE[rep_type] +
-- REP_LOADING_MANAGEMENT_OPS (1.42-1.49 across rep types), widened by rounding
-- of OTE to $500 and cost to $1. Returns offending reps (test passes on 0 rows).

select
    rep_id,
    rep_type,
    annual_ote_usd,
    fully_loaded_annual_cost_usd,
    fully_loaded_annual_cost_usd::double / annual_ote_usd as loading_factor
from {{ ref('stg_users') }}
where
    (rep_type = 'ISR'           and annual_ote_usd not between 105000 and 145000)
 or (rep_type = 'AE'            and annual_ote_usd not between 240000 and 340000)
 or (rep_type = 'SE'            and annual_ote_usd not between 170000 and 230000)
 or (rep_type = 'AM-Commercial' and annual_ote_usd not between  95000 and 135000)
 or (rep_type = 'AM-Enterprise' and annual_ote_usd not between 150000 and 210000)
 or fully_loaded_annual_cost_usd::double / annual_ote_usd not between 1.40 and 1.50
