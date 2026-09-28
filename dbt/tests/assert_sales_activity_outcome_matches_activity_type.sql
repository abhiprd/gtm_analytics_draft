-- QA plan invariant (Sales engagement): outcome's vocabulary is scoped per
-- activity_type, not shared across all four -- a 'call' row may never carry
-- a 'held' outcome, a 'meeting' row may never carry 'bounced', and so on.
-- The accepted_values test on outcome alone can only check membership in
-- the union of all four vocabularies; this asserts the per-type mapping.
-- A dbt test passes when this query returns zero rows.

select
    activity_id,
    activity_type,
    outcome
from {{ ref('fact_sales_activities') }}
where (activity_type = 'call' and outcome not in ('connected', 'voicemail', 'no_answer', 'gatekeeper'))
   or (activity_type = 'email' and outcome not in ('replied', 'opened_no_reply', 'no_response', 'bounced'))
   or (activity_type = 'meeting' and outcome not in ('booked', 'held', 'no_show', 'rescheduled', 'cancelled'))
   or (activity_type = 'demo' and outcome not in ('held', 'no_show', 'cancelled'))
