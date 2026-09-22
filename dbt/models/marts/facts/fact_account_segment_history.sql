-- Grain: one row per account_id per segment-effective_date (initial row at
-- account creation + one row per migration event). Time-in-segment
-- (segment_end_date, days_in_segment) joined in from int_account_segment_spans.

select
    sh.account_id,
    md5(sh.account_id || '|' || cast(sh.effective_date as varchar)) as account_segment_history_id,
    sh.segment,
    sh.effective_date,
    sh.trigger_reason,
    spans.segment_sequence,
    spans.is_initial_segment,
    spans.segment_end_date,
    spans.is_current_segment,
    spans.days_in_segment
from {{ ref('stg_account_segment_history') }} sh
left join {{ ref('int_account_segment_spans') }} spans
    on spans.account_id = sh.account_id
    and spans.segment_start_date = sh.effective_date
