-- Grain: one row per account_id per segment-effective-date span.
-- Derives time-in-segment from stg_account_segment_history: each row's
-- span runs from its own effective_date up to (not including) the next
-- row's effective_date for that account, or through analysis_as_of_date
-- if it's the account's current segment. Per the QA plan, mid-month
-- migrations always take effect on the 1st of the following month, so no
-- proration logic is needed here.

with segment_history as (

    select
        account_id,
        segment,
        effective_date,
        trigger_reason,
        row_number() over (
            partition by account_id order by effective_date
        ) as segment_sequence
    from {{ ref('stg_account_segment_history') }}

),

spans as (

    select
        account_id,
        segment,
        trigger_reason,
        segment_sequence,
        effective_date as segment_start_date,
        lead(effective_date) over (
            partition by account_id order by effective_date
        ) as segment_end_date
    from segment_history

)

select
    account_id,
    segment,
    trigger_reason,
    segment_sequence,
    segment_sequence = 1                         as is_initial_segment,
    segment_start_date,
    segment_end_date,
    segment_end_date is null                      as is_current_segment,
    datediff(
        'day',
        segment_start_date,
        coalesce(segment_end_date, cast('{{ var("analysis_as_of_date") }}' as date) + interval 1 day)
    ) as days_in_segment
from spans
