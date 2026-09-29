-- Grain: one row per lead_id assigned to an experiment (currently: one
-- experiment, so also one row per assignment_id). Light typing only.
-- account_id is populated only for converting leads, mirroring
-- stg_leads.account_id's nullability. arm's population traces each lead's
-- assignment back to the real is_holdout flag of its real first-touch
-- campaign -- not a fabricated random draw independent of the underlying
-- data.

select
    assignment_id,
    experiment_id,
    lead_id,
    account_id,
    company_id,
    channel,
    cell_quarter,
    first_touch_campaign_id,
    arm,
    try_cast(assigned_date as date) as assigned_date
from {{ source('raw', 'experiment_assignment') }}
