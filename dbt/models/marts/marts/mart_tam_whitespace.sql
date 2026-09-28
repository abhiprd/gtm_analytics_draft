-- Grain: one row per territory x industry x employee_count_band.
--
-- territory is a deterministic sub-division of region (North America splits
-- into NA-East/NA-West; EMEA/APAC/LATAM each map 1:1 onto their own single
-- territory value) -- see dim_market_universe.territory/.region. Using
-- territory as the primary geographic grouping key loses no information
-- versus region and gives finer slicing for territory/routing use cases
-- (Wave 5's #21 artifact). region is included as a plain selected column,
-- not part of the group by, since it's already functionally determined by
-- territory -- every row's region is unambiguous once territory is fixed --
-- so existing region-level rollups stay easy to do from this table without
-- a second lookup.
--
-- high_icp_whitespace: non-customer companies with icp_fit_score >= 70
-- (the same "strong signal" band the build spec uses for Enterprise/
-- Commercial firmographic-fit entry) -- these are the best-fit accounts
-- with zero current coverage.

select
    territory,
    any_value(region)                                       as region,
    industry,
    employee_count_band,
    count(*)                                              as total_companies,
    count(*) filter (where is_customer)                   as total_customers,
    count(*) filter (where not is_customer)                as whitespace_companies,
    case
        when count(*) > 0
            then count(*) filter (where is_customer)::double / count(*)
    end                                                    as penetration_rate,
    avg(icp_fit_score)                                     as avg_icp_fit_score,
    count(*) filter (where not is_customer and icp_fit_score >= 70) as high_icp_whitespace_count
from {{ ref('dim_market_universe') }}
group by territory, industry, employee_count_band
