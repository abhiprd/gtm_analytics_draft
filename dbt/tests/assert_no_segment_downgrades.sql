-- CLAUDE.md non-negotiable invariant: no segment downgrade path. An
-- account's segment rank (SMB < Commercial < Enterprise) must never
-- decrease across consecutive rows in fact_account_segment_history.
-- A dbt test passes when this query returns zero rows.

with ranked as (

    select
        account_id,
        segment,
        effective_date,
        case segment
            when 'SMB' then 1
            when 'Commercial' then 2
            when 'Enterprise' then 3
        end as segment_rank,
        lag(case segment
            when 'SMB' then 1
            when 'Commercial' then 2
            when 'Enterprise' then 3
        end) over (partition by account_id order by effective_date) as prior_segment_rank
    from {{ ref('fact_account_segment_history') }}

)

select
    account_id,
    effective_date,
    prior_segment_rank,
    segment_rank
from ranked
where prior_segment_rank is not null
  and segment_rank < prior_segment_rank
