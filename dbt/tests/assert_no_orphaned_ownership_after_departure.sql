-- QA plan Category A: "No orphaned account/opportunity ownership after any
-- rep departure" -- reassignment must be atomic with the departure event,
-- per the QA plan's design decisions ("Rep departures trigger explicit
-- account reassignment ... no orphaned ownership"). Operationalized as: no
-- fact_opportunities or fact_am_activity row's rep_id/activity_date (resp.
-- close_date) can fall AFTER that rep's departure effective_date -- if it
-- does, the record is still crediting/attributing activity to a rep who
-- had already left, meaning the reassignment on departure didn't actually
-- happen for that record. A dbt test passes when this query returns zero
-- rows.

with departures as (

    select
        rep_id,
        min(period_start_date) as departure_date
    from {{ ref('dim_reps') }}
    where rep_status = 'departed'
    group by 1

)

select
    'fact_opportunities' as source_table,
    o.opportunity_id as record_id,
    o.rep_id,
    o.close_date as record_date,
    d.departure_date
from {{ ref('fact_opportunities') }} o
inner join departures d on d.rep_id = o.rep_id
where o.close_date > d.departure_date

union all

select
    'fact_am_activity' as source_table,
    a.activity_id as record_id,
    a.rep_id,
    a.activity_date as record_date,
    d.departure_date
from {{ ref('fact_am_activity') }} a
inner join departures d on d.rep_id = a.rep_id
where a.activity_date > d.departure_date
