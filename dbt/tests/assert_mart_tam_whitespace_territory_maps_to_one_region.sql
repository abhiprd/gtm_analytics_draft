-- mart_tam_whitespace.region is pulled off any_value(region) per
-- territory/industry/employee_count_band group, which silently picks an
-- arbitrary region if a territory ever mapped to more than one region --
-- it would not error. This is the functional-dependency invariant that
-- any_value() depends on: every territory value maps to exactly one region
-- (NA-East/NA-West -> North America; EMEA/APAC/LATAM -> themselves 1:1).
-- A dbt test passes when this query returns zero rows.

select territory
from {{ ref('mart_tam_whitespace') }}
group by territory
having count(distinct region) > 1
