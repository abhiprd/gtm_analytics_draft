-- Grain: one row per opportunity_id per stage-entered-date span.
-- Derives time-in-stage from stg_opportunity_stage_history: each row's
-- span runs from its own entered_date up to the next stage's entered_date
-- for that opportunity, or through the opportunity's close_date if it's
-- the last stage recorded. Backward stage movement (regression) is left
-- intact here -- stage_sequence is entry order, not a monotonic funnel
-- position, since the QA plan calls out stage regression as an expected,
-- real pattern in a small % of deals.

with stage_history as (

    select
        opportunity_id,
        stage,
        entered_date,
        row_number() over (
            partition by opportunity_id order by entered_date
        ) as stage_sequence
    from {{ ref('stg_opportunity_stage_history') }}

),

opportunities as (

    select opportunity_id, close_date
    from {{ ref('stg_opportunities') }}

)

select
    sh.opportunity_id,
    sh.stage,
    sh.stage_sequence,
    sh.entered_date as stage_start_date,
    coalesce(
        lead(sh.entered_date) over (
            partition by sh.opportunity_id order by sh.entered_date
        ),
        o.close_date
    ) as stage_end_date,
    datediff(
        'day',
        sh.entered_date,
        coalesce(
            lead(sh.entered_date) over (
                partition by sh.opportunity_id order by sh.entered_date
            ),
            o.close_date
        )
    ) as days_in_stage
from stage_history sh
left join opportunities o on o.opportunity_id = sh.opportunity_id
