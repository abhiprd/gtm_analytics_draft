-- Build spec Section 2: SMB gets exactly one Opportunity record, created at
-- conversion, immediately Closed Won, no rep owner (owner_role = system).
-- No Closed Lost record for non-converting trials. A dbt test passes when
-- this query returns zero rows.

select
    account_id,
    count(*) as n_opportunities
from {{ ref('fact_opportunities') }}
where segment = 'SMB'
group by account_id
having count(*) > 1
