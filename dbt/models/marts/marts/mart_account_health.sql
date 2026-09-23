-- Grain: one row per account_id per month. Feeds the account health score
-- / churn-risk model (analytics/health_score.py) -- the single mart that
-- model reads from, per analytics-engineering-conventions' "mart_* only"
-- rule, so it never has to reach into fact_usage_monthly / fact_support_
-- tickets / fact_product_logins / fact_am_activity / fact_subscriptions
-- directly. Anchored on fact_usage_monthly (an account-month row exists
-- for every month the account is live, including near-zero-usage months
-- leading up to churn -- see the QA plan's silent-churn edge case), left-
-- joined against the other three health-score input facts plus a per-
-- account churn outcome derived from fact_subscriptions.
--
-- account_tenure_days / is_within_first_90_days exist so the model can
-- apply the QA plan's login-frequency reweighting (higher weight in an
-- account's first ~90 days, lower after) without re-deriving tenure
-- itself. is_eventually_churned / churn_month / is_censored are TRAINING
-- LABELS (the account's actual future outcome) -- deliberately NOT an
-- input to the health score itself, only used by the model to fit/backtest
-- against, consistent with as_of_date point-in-time discipline: a caller
-- scoring "as of" a given month uses this mart's month <= as_of_date rows
-- for features and must not use is_eventually_churned as a feature.

with usage as (

    select
        account_id,
        month,
        segment,
        actions_consumed,
        active_workflows
    from {{ ref('fact_usage_monthly') }}

),

account_base as (

    select
        account_id,
        segment,
        signup_date,
        channel,
        customer_status
    from {{ ref('dim_accounts') }}

),

-- One row per account: the account's own last subscription record
-- determines its churn outcome (int_revenue_movements / fact_subscriptions
-- design note: status = 'churned' on the most-recent-by-start_date row).
churn_outcome as (

    select
        account_id,
        status = 'churned'                                   as is_eventually_churned,
        case when status = 'churned' then date_trunc('month', end_date) end as churn_month
    from {{ ref('fact_subscriptions') }}
    where is_latest_subscription

),

tickets_monthly as (

    select
        account_id,
        date_trunc('month', created_date) as month,
        count(*)                                                        as ticket_count,
        avg(case severity
                when 'low' then 1 when 'medium' then 2
                when 'high' then 3 when 'critical' then 4 end)           as avg_ticket_severity_score,
        sum(case when severity in ('high', 'critical') then 1 else 0 end) as high_severity_ticket_count,
        avg(resolution_time_hours) / 24.0                                as avg_resolution_days
    from {{ ref('fact_support_tickets') }}
    group by 1, 2

),

logins_monthly as (

    select
        account_id,
        date_trunc('month', login_date) as month,
        count(*)                        as login_count
    from {{ ref('fact_product_logins') }}
    group by 1, 2

),

am_activity_monthly as (

    select
        account_id,
        date_trunc('month', activity_date) as month,
        count(*)                           as am_touchpoint_count,
        avg(sentiment_score)               as avg_am_sentiment_score
    from {{ ref('fact_am_activity') }}
    group by 1, 2

)

select
    u.account_id,
    u.month,
    u.segment,
    ab.channel,
    ab.signup_date,
    datediff('day', ab.signup_date, u.month) as account_tenure_days,
    datediff('day', ab.signup_date, u.month) <= 90 as is_within_first_90_days,
    u.actions_consumed,
    u.active_workflows,
    coalesce(t.ticket_count, 0)              as ticket_count,
    t.avg_ticket_severity_score,
    coalesce(t.high_severity_ticket_count, 0) as high_severity_ticket_count,
    t.avg_resolution_days,
    coalesce(l.login_count, 0)               as login_count,
    coalesce(am.am_touchpoint_count, 0)      as am_touchpoint_count,
    am.avg_am_sentiment_score,
    ab.customer_status,
    coalesce(co.is_eventually_churned, false) as is_eventually_churned,
    co.churn_month,
    co.churn_month is null                    as is_censored
from usage u
left join account_base ab on ab.account_id = u.account_id
left join churn_outcome co on co.account_id = u.account_id
left join tickets_monthly t on t.account_id = u.account_id and t.month = u.month
left join logins_monthly l on l.account_id = u.account_id and l.month = u.month
left join am_activity_monthly am on am.account_id = u.account_id and am.month = u.month
