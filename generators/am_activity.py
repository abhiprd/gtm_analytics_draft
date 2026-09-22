"""am_activity generator.

Build spec Section 5 (CS-ops): `am_activity` (touchpoints, QBRs -- Enterprise
only, check-ins -- Commercial), feeding the account health score alongside
support_tickets. SMB has no AM (self-serve, build spec Section 1) and gets
no rows here at all. Event grain -- one row per touchpoint.

AM ownership: opportunities.py already assigns an AM rep_id per expansion/
renewal opportunity, but that's a per-opportunity draw, not a persistent
"who owns this account's relationship right now" mapping, which ongoing
touchpoints need. This module derives one: each account gets a single
primary AM for its tenure, chosen deterministically (seeded) from the
eligible AM pool for its segment as of contract start, and reassigned --
mirroring the project's existing "no orphaned ownership on departure" rule
(build spec Section 5 / QA plan Test A) -- if that AM later departs.

Sentiment is driven by the same data-derived pre-churn "fading" window
support_tickets.py computes (not an independent draw), so AM sentiment
notes move with the same real trajectory as usage decline and ticket
volume -- exactly what makes the eventual health-score model's combined
signal predictive rather than each input being unrelated noise.
"""
import numpy as np
import pandas as pd

from . import config

AM_REP_TYPE_BY_SEGMENT = {"Commercial": "AM-Commercial", "Enterprise": "AM-Enterprise"}


def _month_floor(d) -> pd.Timestamp:
    return pd.Timestamp(d).to_period("M").start_time


def _departed_by(rep_status_history: pd.DataFrame) -> dict:
    departed = rep_status_history[rep_status_history["status"] == "departed"]
    return dict(zip(departed["rep_id"], pd.to_datetime(departed["effective_date"])))


def _eligible_ams(users: pd.DataFrame, departed_by: dict, rep_type: str, at_date) -> pd.DataFrame:
    at_ts = pd.Timestamp(at_date)
    pool = users[users["rep_type"] == rep_type]
    hired = pd.to_datetime(pool["hire_date"]) <= at_ts
    not_departed = ~pool["rep_id"].map(lambda r: r in departed_by and departed_by[r] <= at_ts)
    return pool[hired & not_departed]


def _churn_date_by_account(subscriptions: pd.DataFrame) -> dict:
    last_rows = subscriptions.sort_values("start_date").groupby("account_id").last()
    churned = last_rows[last_rows["status"] == "churned"]
    return {aid: pd.Timestamp(r.end_date) for aid, r in zip(churned.index, churned.itertuples())}


def _declining_accounts(usage_monthly: pd.DataFrame, churn_date_by_account: dict) -> set:
    """Same derivation as support_tickets._declining_accounts -- duplicated
    rather than imported, since each module is independently runnable from
    its own inputs per this project's existing module boundary (contracts.py
    is the one shared substrate; this one data-derived check is cheap enough
    not to warrant a new shared module for two callers)."""
    declining = set()
    for account_id, churn_ts in churn_date_by_account.items():
        acct_usage = usage_monthly[usage_monthly["account_id"] == account_id].sort_values("month")
        if acct_usage.empty:
            continue
        acct_usage = acct_usage.set_index(pd.to_datetime(acct_usage["month"]))
        window_start = churn_ts - pd.DateOffset(months=config.DECLINE_MONTHS_BEFORE_CHURN)
        pre_window = acct_usage[acct_usage.index < window_start]
        in_window = acct_usage[(acct_usage.index >= window_start) & (acct_usage.index < churn_ts)]
        if pre_window.empty or in_window.empty:
            continue
        peak = pre_window["actions_consumed"].tail(6).max()
        trough = in_window["actions_consumed"].min()
        if peak > 0 and trough / peak < 0.5:
            declining.add(account_id)
    return declining


def _assign_primary_am(rng: np.random.Generator, account_id: str, segment: str, start_ts: pd.Timestamp,
                        end_ts: pd.Timestamp, users: pd.DataFrame, departed_by: dict) -> list:
    """Returns [(am_rep_id, effective_from_ts), ...] -- one entry per AM the
    account has over its tenure. Loops rather than reassigning once: a
    replacement AM can itself depart again before the account's tenure
    ends (rare with only ~15 AMs and ~12% departure rate, but real), and a
    single-reassignment version left a handful of touchpoints attributed to
    an already-departed rep -- the exact orphaned-ownership bug build spec
    Section 5 / the QA plan's referential-integrity category rules out."""
    rep_type = AM_REP_TYPE_BY_SEGMENT[segment]
    assignments = []
    current_ts = start_ts
    excluded = set()

    while current_ts <= end_ts:
        eligible = _eligible_ams(users, departed_by, rep_type, current_ts)
        eligible = eligible[~eligible["rep_id"].isin(excluded)]
        if eligible.empty:
            break
        idx = rng.integers(0, len(eligible))
        am_rep_id = eligible.iloc[idx]["rep_id"]
        assignments.append((am_rep_id, current_ts))

        depart_ts = departed_by.get(am_rep_id)
        if depart_ts is not None and start_ts <= depart_ts <= end_ts and depart_ts > current_ts:
            excluded.add(am_rep_id)
            current_ts = depart_ts
        else:
            break
    return assignments


def _am_for_date(assignments: list, at_ts: pd.Timestamp) -> str:
    """Resolved per actual day, not per calendar month -- a reassignment
    that happens mid-month must not have the whole month attributed to
    the outgoing AM, or a touchpoint dated after their departure (but
    still within that same month) ends up orphaned."""
    am_rep_id = assignments[0][0]
    for rep_id, eff_from in assignments:
        if eff_from <= at_ts:
            am_rep_id = rep_id
        else:
            break
    return am_rep_id


_ACTIVITY_TYPE_BY_SEGMENT = {"Commercial": "check_in", "Enterprise": "QBR"}


def generate_am_activity(rng: np.random.Generator, accounts: pd.DataFrame, users: pd.DataFrame,
                          rep_status_history: pd.DataFrame, usage_monthly: pd.DataFrame,
                          subscriptions: pd.DataFrame) -> pd.DataFrame:
    departed_by = _departed_by(rep_status_history)
    churn_date_by_account = _churn_date_by_account(subscriptions)
    declining = _declining_accounts(usage_monthly, churn_date_by_account)

    covered = accounts[accounts["segment"].isin(AM_REP_TYPE_BY_SEGMENT.keys())]
    rows = []
    activity_seq = 0
    sim_end_ts = pd.Timestamp(config.SIM_END)

    for acc in covered.itertuples():
        signup_ts = pd.Timestamp(acc.signup_date)
        churn_ts = churn_date_by_account.get(acc.account_id)
        end_ts = churn_ts if churn_ts is not None else sim_end_ts
        if end_ts < signup_ts:
            continue

        assignments = _assign_primary_am(rng, acc.account_id, acc.segment, signup_ts, end_ts, users, departed_by)
        if not assignments:
            continue

        months = pd.period_range(_month_floor(signup_ts), _month_floor(end_ts), freq="M")
        fading = acc.account_id in declining
        decline_start = (
            (churn_ts - pd.DateOffset(months=config.DECLINE_MONTHS_BEFORE_CHURN)) if (fading and churn_ts is not None) else None
        )
        activity_type = _ACTIVITY_TYPE_BY_SEGMENT[acc.segment]

        for period in months:
            month_start = period.start_time

            rate = config.AM_TOUCH_RATE_BASELINE[acc.segment]
            prechurn = fading and decline_start is not None and month_start >= decline_start and month_start < churn_ts
            if prechurn:
                rate *= config.AM_TOUCH_PRECHURN_MULTIPLIER

            n_touches = rng.poisson(rate)
            if n_touches == 0:
                continue

            sentiment_mean = config.SENTIMENT_MEAN_PRECHURN if prechurn else config.SENTIMENT_MEAN_BASELINE
            # Same first/last partial-month clamp as support_tickets.py --
            # no touchpoint before signup_date or after churn_date.
            day_lo = (signup_ts.day - 1) if period == months[0] else 0
            day_hi = (churn_ts.day - 1) if (churn_ts is not None and period == months[-1]) else period.days_in_month - 1
            day_hi = max(day_hi, day_lo)
            offsets = rng.integers(day_lo, day_hi + 1, size=n_touches)

            for offset in offsets:
                activity_seq += 1
                activity_ts = month_start + pd.Timedelta(days=int(offset))
                am_rep_id = _am_for_date(assignments, activity_ts)
                activity_date = activity_ts.date()
                sentiment = float(np.clip(rng.normal(sentiment_mean, config.SENTIMENT_SIGMA), 1.0, 5.0))
                rows.append({
                    "activity_id": f"AMT-{activity_seq:07d}",
                    "account_id": acc.account_id,
                    "segment": acc.segment,
                    "am_rep_id": am_rep_id,
                    "activity_date": activity_date,
                    "activity_type": activity_type,
                    "sentiment_score": round(sentiment, 2),
                })

    return pd.DataFrame(rows)
