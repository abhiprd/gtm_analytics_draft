-- Grain: one row per account_id (current state).
-- segment is the account's CURRENT segment (post any migration); full
-- migration history is in fact_account_segment_history. customer_status is
-- derived from the account's most recent subscription record -- 'Churned'
-- if that record's status = 'churned', 'Active' otherwise. channel (how
-- acquired) and segment (what it is) are independent columns here by
-- design -- never assume one implies the other.

with accounts as (
    select * from {{ ref('stg_accounts') }}
),

latest_subscription as (
    select
        account_id,
        status,
        contract_type,
        start_date as subscription_start_date,
        end_date   as subscription_end_date,
        row_number() over (partition by account_id order by start_date desc) as rn
    from {{ ref('stg_subscriptions') }}
),

current_subscription as (
    select account_id, status, contract_type, subscription_start_date, subscription_end_date
    from latest_subscription
    where rn = 1
)

select
    a.account_id,
    a.company_id,
    a.segment,
    a.employee_count_band,
    a.industry,
    a.region,
    a.channel,
    a.signup_date,
    a.icp_fit_score,
    a.is_personal_email_domain,
    cs.contract_type              as current_contract_type,
    cs.subscription_start_date    as current_subscription_start_date,
    cs.subscription_end_date      as current_subscription_end_date,
    case when cs.status = 'churned' then 'Churned' else 'Active' end as customer_status,
    datediff('day', a.signup_date, cast('{{ var("analysis_as_of_date") }}' as date)) as account_tenure_days
from accounts a
left join current_subscription cs on cs.account_id = a.account_id
