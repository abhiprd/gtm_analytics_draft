-- QA plan invariant (Marketing attribution, Test A): every account acquired
-- through `inbound_marketing` is explained by exactly one converting lead,
-- created strictly earlier than that account's signup_date. Checked in BOTH
-- directions -- a converting lead resolving to a real account is not
-- sufficient if part of the inbound population has no lead at all. The
-- relationships + conditional-unique tests on fact_leads.account_id cover
-- the lead -> account direction only; this covers account -> lead, plus the
-- strict date ordering neither can express.
--
-- This test only reads dim_accounts; it asserts nothing about the
-- self_serve or outbound_sdr populations, which carry no leads by design.
-- A dbt test passes when this query returns zero rows.

with inbound_accounts as (

    select account_id, signup_date
    from {{ ref('dim_accounts') }}
    where channel = 'inbound_marketing'

),

converting_leads as (

    select account_id, count(*) as lead_count, min(created_date) as earliest_created_date
    from {{ ref('fact_leads') }}
    where is_converted
    group by account_id

)

select
    a.account_id,
    a.signup_date,
    coalesce(l.lead_count, 0) as converting_lead_count,
    l.earliest_created_date
from inbound_accounts a
left join converting_leads l on l.account_id = a.account_id
where coalesce(l.lead_count, 0) <> 1
   or l.earliest_created_date >= a.signup_date
