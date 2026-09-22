-- Grain: one row per account_id per month. Billing-side committed vs.
-- utilized Action volume -- what Consumption Payback's utilized-Action
-- margin needs to exclude subsidized, non-consuming capacity.

select
    account_id,
    md5(account_id || '|' || cast(month as varchar)) as committed_vs_utilized_monthly_id,
    month,
    segment,
    committed_actions_monthly,
    utilized_actions_monthly,
    case
        when committed_actions_monthly is not null and committed_actions_monthly > 0
            then utilized_actions_monthly / committed_actions_monthly
    end as utilization_rate
from {{ ref('stg_committed_vs_utilized_monthly') }}
