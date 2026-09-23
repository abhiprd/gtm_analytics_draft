-- Composite-key uniqueness for every mart whose grain isn't a single
-- surrogate-key column (dbt_utils isn't installed for this project -- see
-- dim_schema.yml's note on assert_dim_reps_period_uniqueness for the same
-- pattern). Each mart's stated grain (its own model header comment) is the
-- primary key checked here. A dbt test passes when this query returns
-- zero rows.

select 'mart_growth_bridge' as mart, cast(segment as varchar) as key_1, cast(month as varchar) as key_2, cast(null as varchar) as key_3, count(*) as n_rows
from {{ ref('mart_growth_bridge') }}
group by 1, 2, 3, 4
having count(*) > 1

union all

select 'mart_durability' as mart, cast(segment as varchar), cast(month as varchar), cast(null as varchar), count(*)
from {{ ref('mart_durability') }}
group by 1, 2, 3, 4
having count(*) > 1

union all

select 'mart_efficiency' as mart, cast(segment as varchar), cast(month as varchar), cast(null as varchar), count(*)
from {{ ref('mart_efficiency') }}
group by 1, 2, 3, 4
having count(*) > 1

union all

select 'mart_segment_migration' as mart, cast(account_id as varchar), cast(migration_date as varchar), cast(null as varchar), count(*)
from {{ ref('mart_segment_migration') }}
group by 1, 2, 3, 4
having count(*) > 1

union all

select 'mart_tam_whitespace' as mart, cast(region as varchar), cast(industry as varchar), cast(employee_count_band as varchar), count(*)
from {{ ref('mart_tam_whitespace') }}
group by 1, 2, 3, 4
having count(*) > 1

union all

select 'mart_account_health' as mart, cast(account_id as varchar), cast(month as varchar), cast(null as varchar), count(*)
from {{ ref('mart_account_health') }}
group by 1, 2, 3, 4
having count(*) > 1
