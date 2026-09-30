-- fact_playbook_triggers consistency invariants; a dbt test passes when
-- this query returns zero rows.
--   1. owner_rep_id, owner_role and owner_unresolved_reason move together:
--      a resolved owner carries a role and no unresolved reason; an
--      unresolved owner carries a reason and no role. No owner is ever
--      fabricated without a reason, and no reason sits beside an owner.
--   2. An automated outcome is never decided before its observation window
--      has elapsed: a non-pending automated outcome requires
--      outcome_window_end <= outcome_evaluated_as_of.
--   3. A pending outcome carries no decided evidence.

select playbook_trigger_id, 'owner_fields_inconsistent' as violation
from {{ ref('fact_playbook_triggers') }}
where (owner_rep_id is not null and (owner_role is null or owner_unresolved_reason is not null))
   or (owner_rep_id is null and (owner_role is not null or owner_unresolved_reason is null))

union all

select playbook_trigger_id, 'outcome_decided_before_window_elapsed'
from {{ ref('fact_playbook_triggers') }}
where outcome_source = 'automated'
  and outcome <> 'pending'
  and (outcome_window_end is null
       or outcome_evaluated_as_of is null
       or outcome_window_end > outcome_evaluated_as_of)

union all

select playbook_trigger_id, 'pending_outcome_carries_evidence'
from {{ ref('fact_playbook_triggers') }}
where outcome = 'pending'
  and (outcome_date is not null or outcome_metric_value is not null)
