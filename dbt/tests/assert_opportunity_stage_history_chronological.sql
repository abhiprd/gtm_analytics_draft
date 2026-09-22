-- QA plan Category A: "opportunity_stage_history is chronologically
-- ordered per opportunity." Operationalized as: no opportunity's last
-- recorded stage-entered_date can be AFTER its own close_date -- a deal
-- can't be recorded as still progressing through the funnel after it was
-- already marked closed. int_opportunity_stage_spans already encodes this
-- as days_in_stage (via datediff(entered_date, coalesce(next_entered_date,
-- close_date))) for the last stage row per opportunity; a negative value
-- there is exactly this violation. A dbt test passes when this query
-- returns zero rows.

select
    opportunity_id,
    stage,
    stage_start_date,
    stage_end_date,
    days_in_stage
from {{ ref('int_opportunity_stage_spans') }}
where days_in_stage < 0
