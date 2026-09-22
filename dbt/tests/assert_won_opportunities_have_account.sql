-- account_id is legitimately null for Lost new-business opportunities that
-- never converted (no account was ever created). Every WON opportunity,
-- by contrast, must have an account_id -- winning a deal is what creates
-- (or is created alongside) the account. A dbt test passes when this
-- query returns zero rows.

select opportunity_id, account_id, is_won
from {{ ref('fact_opportunities') }}
where is_won = true
  and account_id is null
