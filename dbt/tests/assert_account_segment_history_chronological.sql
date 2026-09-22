-- QA plan Category A: "account_segment_history rows are chronological,
-- non-overlapping, no gaps." int_account_segment_spans already builds each
-- span as [effective_date, next effective_date) per account, which makes
-- gaps and overlaps structurally impossible EXCEPT when two rows for the
-- same account share the same effective_date -- an ambiguous case that
-- breaks the "chronological, non-overlapping" guarantee (LEAD/ROW_NUMBER
-- ordering over duplicate dates is undefined). A dbt test passes when this
-- query returns zero rows.

select
    account_id,
    effective_date,
    count(*) as n_rows
from {{ ref('stg_account_segment_history') }}
group by 1, 2
having count(*) > 1
