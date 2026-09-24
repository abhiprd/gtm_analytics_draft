-- QA plan Test A: every fact_forecast_submissions row resolves to a real
-- Commercial/Enterprise opportunity, no SMB opportunity appears, and every
-- snapshot_date falls on a Friday inside that opportunity's open window
-- (created_date inclusive, close_date exclusive -- a deal closing on a call
-- date is resolved by that call, not forecast by it).
--
-- The referential half and the duplicate-pair half of that test line are
-- covered by generic tests in _fct_schema.yml (relationships on
-- opportunity_id, unique on forecast_submission_id over the stated grain);
-- this singular test covers the three conditions a generic test can't
-- express. Structural, per-row assertions only -- the distributional and
-- correlational forecast checks (rep/manager gap predicting close rate,
-- both disagreement directions firing) belong to the QA plan's pytest
-- suite, not here.
--
-- DuckDB dayofweek(): 0 = Sunday, so Friday = 5.
-- A dbt test passes when this query returns zero rows.

select
    s.opportunity_id,
    s.snapshot_date,
    o.segment,
    o.created_date,
    o.close_date,
    case
        when o.segment = 'SMB'                  then 'smb_opportunity_forecast'
        when dayofweek(s.snapshot_date) <> 5    then 'snapshot_not_friday'
        when s.snapshot_date < o.created_date   then 'snapshot_before_creation'
        when s.snapshot_date >= o.close_date    then 'snapshot_on_or_after_close'
    end as violation
from {{ ref('fact_forecast_submissions') }} as s
join {{ ref('fact_opportunities') }} as o
    on s.opportunity_id = o.opportunity_id
where o.segment = 'SMB'
   or dayofweek(s.snapshot_date) <> 5
   or s.snapshot_date < o.created_date
   or s.snapshot_date >= o.close_date
