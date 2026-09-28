-- Structural invariant (fact_sales_activities grain comment / schema.yml
-- description for is_outbound_touch): is_outbound_touch is true only ever
-- on Enterprise-segment call/email rows -- a rep-initiated prospecting
-- touch into an already-open deal's buying committee, never a meeting or
-- demo row, and never on a Commercial-segment deal. segment lives on
-- fact_opportunities, not on fact_sales_activities itself (by design, see
-- that model's grain comment), so this requires the join the generic
-- not_null/accepted_values tests on fact_sales_activities alone can't
-- express. A dbt test passes when this query returns zero rows.

select
    a.activity_id,
    a.opportunity_id,
    a.activity_type,
    a.is_outbound_touch,
    o.segment
from {{ ref('fact_sales_activities') }} as a
join {{ ref('fact_opportunities') }} as o
    on a.opportunity_id = o.opportunity_id
where a.is_outbound_touch
  and (o.segment <> 'Enterprise' or a.activity_type not in ('call', 'email'))
