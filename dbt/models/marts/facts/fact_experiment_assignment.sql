-- Grain: one row per (experiment_id, lead_id) -- one lead's assignment to
-- one experiment's arm. Currently 1:1 with lead_id/assignment_id since only
-- one experiment exists in this data, but the grain is stated as the
-- compound pair, not just lead_id, since a future second experiment could
-- assign the same lead again.
--
-- FKs: experiment_id -> dim_experiment, lead_id -> fact_leads,
-- first_touch_campaign_id -> dim_campaign. account_id is a soft/nullable
-- reference into dim_accounts, populated only for converting leads --
-- mirrors fact_leads.account_id's nullability (see that column's
-- description for why an unqualified relationships test doesn't belong
-- here).
--
-- arm's assignment is not an independent random draw: it traces back to the
-- real is_holdout flag of the lead's real first-touch campaign
-- (dim_campaign.is_holdout), fixed at that first touch per the registry's
-- intention-to-treat assignment_mechanism.

with experiment_assignment as (

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
        assigned_date
    from {{ ref('stg_experiment_assignment') }}

)

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
    assigned_date
from experiment_assignment
