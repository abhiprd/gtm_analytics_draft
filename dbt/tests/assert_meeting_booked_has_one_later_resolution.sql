-- Structural invariant (fact_sales_activities grain comment): every
-- meeting 'booked' row has exactly one later resolution row (outcome in
-- held/no_show/rescheduled/cancelled) on the same opportunity_id --
-- meetings_booked is this table's antecedent event, never a standalone
-- artifact. Checked as a same-opportunity, chronological-rank pairing: the
-- k-th earliest booked row is paired with the k-th earliest resolution row
-- on that opportunity_id. If a valid 1:1 later-resolution pairing exists
-- at all, sorting both sides and pairing by rank finds it (a standard
-- exchange-argument result), so this also catches an unequal count of
-- booked vs. resolution rows per opportunity, not just mistimed ones. A
-- dbt test passes when this query returns zero rows.

with booked as (

    select
        activity_id,
        opportunity_id,
        activity_timestamp,
        row_number() over (
            partition by opportunity_id order by activity_timestamp, activity_id
        ) as rn
    from {{ ref('fact_sales_activities') }}
    where activity_type = 'meeting' and outcome = 'booked'

),

resolution as (

    select
        activity_id,
        opportunity_id,
        activity_timestamp,
        row_number() over (
            partition by opportunity_id order by activity_timestamp, activity_id
        ) as rn
    from {{ ref('fact_sales_activities') }}
    where activity_type = 'meeting'
      and outcome in ('held', 'no_show', 'rescheduled', 'cancelled')

)

select
    coalesce(b.opportunity_id, r.opportunity_id) as opportunity_id,
    b.activity_id as booked_activity_id,
    b.activity_timestamp as booked_timestamp,
    r.activity_id as resolution_activity_id,
    r.activity_timestamp as resolution_timestamp
from booked as b
full outer join resolution as r
    on b.opportunity_id = r.opportunity_id
    and b.rn = r.rn
where b.activity_id is null
   or r.activity_id is null
   or r.activity_timestamp <= b.activity_timestamp
