-- Grain: one row per opportunity_id per stage-entered_date. Raw historized
-- fact (pass-through); time-in-stage duration lives in
-- int_opportunity_stage_spans, joined in here for convenience since it's a
-- 1:1 enrichment of the same grain, not a separate business concept.

select
    sh.opportunity_id,
    md5(sh.opportunity_id || '|' || sh.stage || '|' || cast(sh.entered_date as varchar)) as opportunity_stage_history_id,
    sh.stage,
    sh.entered_date,
    spans.stage_sequence,
    spans.stage_end_date,
    spans.days_in_stage
from {{ ref('stg_opportunity_stage_history') }} sh
left join {{ ref('int_opportunity_stage_spans') }} spans
    on spans.opportunity_id = sh.opportunity_id
    and spans.stage = sh.stage
    and spans.stage_start_date = sh.entered_date
