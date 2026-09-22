-- Grain: one row per opportunity_id per stage-entered_date. Stage values
-- observed in the raw data: SAL, SQO, POC, Proposal/Negotiation,
-- Negotiation, Open, Closed Won, Closed Lost (Commercial skips POC per the
-- company's funnel design; SMB never appears here at all -- it gets exactly
-- one Closed Won opportunity record with no stage history).

select
    opportunity_id,
    stage,
    try_cast(entered_date as date) as entered_date
from {{ source('raw', 'opportunity_stage_history') }}
