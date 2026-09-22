-- Grain: one row per calendar day.
-- Spans the full raw-data horizon (opportunities.created_date starts
-- 2019-12-01) plus a year of buffer past analysis_as_of_date so Phase 4/5
-- forecast and readout work has room to reference future/current periods
-- without regenerating this dimension.

with date_spine as (
    select
        cast('2019-01-01' as date) + interval (i) day as date_day
    from range(0, datediff(
        'day',
        cast('2019-01-01' as date),
        cast('{{ var("analysis_as_of_date") }}' as date) + interval 1 year
    ) + 1) as t(i)
)

select
    date_day,
    year(date_day)                                as year,
    quarter(date_day)                              as quarter,
    month(date_day)                                as month_of_year,
    date_trunc('month', date_day)                  as month_start_date,
    last_day(date_day)                              as month_end_date,
    strftime(date_day, '%B')                        as month_name,
    day(date_day)                                   as day_of_month,
    dayofweek(date_day)                             as day_of_week,
    strftime(date_day, '%A')                        as day_name,
    dayofweek(date_day) in (0, 6)                    as is_weekend,
    date_trunc('week', date_day)                    as week_start_date
from date_spine
