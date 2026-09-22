-- Grain: one row per region x industry x employee_count_band.
--
-- No "territory" field exists anywhere in the raw data (dim_reps has no
-- territory column either -- users.csv only carries rep_type/segment/
-- hire_date/book_size), so whitespace is sliced by region/industry/
-- employee_count_band instead of region/segment/territory as the build
-- spec's wording suggests. A real territory field would need to come from
-- a future raw source before territory-level whitespace/routing (Wave 5's
-- #21 artifact) can be built for real.
--
-- high_icp_whitespace: non-customer companies with icp_fit_score >= 70
-- (the same "strong signal" band the build spec uses for Enterprise/
-- Commercial firmographic-fit entry) -- these are the best-fit accounts
-- with zero current coverage.

select
    region,
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
group by 1, 2, 3
