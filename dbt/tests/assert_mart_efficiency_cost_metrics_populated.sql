-- Magic Number and AM Efficiency are real values, not structural NULLs:
--   * Commercial / Enterprise carry magic_number (and its prior-period S&M
--     cost) for every month from 2023-02 -- the first month whose prior month
--     has marketing spend -- and am_cost / am_efficiency for every month of
--     the simulation window (2023-01 onward; earlier months are the
--     back-dated established-cohort tail, before every segment had an AM);
--   * SMB has no reps and no AM: rep_fully_loaded_cost and am_cost are a real
--     0 and am_efficiency is undefined (NULL), not a gap.
-- Returns offending rows (test passes on 0 rows).

select segment, month, 'rep_segment_missing_cost_metric' as reason
from {{ ref('mart_efficiency') }}
where segment in ('Commercial', 'Enterprise')
  and (
        (month >= date '2023-02-01'
            and (magic_number is null or magic_number_sm_cost is null or magic_number_sm_cost <= 0))
     or (month >= date '2023-01-01' and (am_cost is null or am_cost <= 0 or am_efficiency is null))
  )

union all

select segment, month, 'smb_cost_not_zero' as reason
from {{ ref('mart_efficiency') }}
where segment = 'SMB'
  and (rep_fully_loaded_cost <> 0 or am_cost <> 0 or am_efficiency is not null)
