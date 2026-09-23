"""product_logins generator.

Fills a gap the QA plan names explicitly but no earlier batch produced:
"engagement/login frequency" as its own signal, distinct from usage volume
(usage_monthly.actions_consumed/active_workflows). Without it, the
account health score can't implement the QA plan's specific health-score
rule -- "a fully automated, 'set and forget' workflow can be perfectly
healthy with almost no logins" -- since there was nothing to show a
high-usage, low-login account actually existing. Event grain -- one row
per login/session, not a pre-aggregated monthly count.

Each account's login intensity is its own latent draw, independent of
contracts.py's usage_scale by construction (this module's own rng stream,
never derived from usage). That independence is the actual mechanism: an
account can land high on usage_scale and low on login-intensity purely by
chance, the same way two unrelated draws would -- which is what makes the
automated-but-healthy cohort exist in the data rather than being asserted.

Onboarding-boost and pre-churn-decline mirror support_tickets.py/
am_activity.py's mechanisms (same data-derived "fading" window, same
first/last partial-month day-offset clamp), so every health-score input
moves together around the same real trajectory instead of each generator
inventing an unrelated one -- except pre-churn direction is reversed here:
logins decline for a genuinely disengaging account, where tickets/AM
outreach rise as a reactive signal.
"""
import numpy as np
import pandas as pd

from . import config


def _month_floor(d) -> pd.Timestamp:
    return pd.Timestamp(d).to_period("M").start_time


def _churn_date_by_account(subscriptions: pd.DataFrame) -> dict:
    """Last subscription row per account; status == 'churned' means that
    row's end_date is the account's churn_date (billing.py sets status this
    way at the closing subscription row -- see build_subscriptions)."""
    last_rows = subscriptions.sort_values("start_date").groupby("account_id").last()
    churned = last_rows[last_rows["status"] == "churned"]
    return {aid: pd.Timestamp(r.end_date) for aid, r in zip(churned.index, churned.itertuples())}


def _declining_accounts(usage_monthly: pd.DataFrame, churn_date_by_account: dict) -> set:
    """Same derivation as support_tickets.py/am_activity.py -- duplicated
    rather than imported, matching this project's existing module boundary
    (each batch-3/4 generator is independently runnable from its own
    inputs; contracts.py is the one shared substrate, from batch 2)."""
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


def generate_product_logins(rng: np.random.Generator, accounts: pd.DataFrame,
                             usage_monthly: pd.DataFrame, subscriptions: pd.DataFrame) -> pd.DataFrame:
    churn_date_by_account = _churn_date_by_account(subscriptions)
    declining = _declining_accounts(usage_monthly, churn_date_by_account)

    # One latent login-intensity draw per account -- independent of
    # usage_scale (contracts.py) by construction; this rng stream never
    # touches usage_monthly's values, only account_id/segment/signup_date.
    intensity_by_account = dict(zip(
        accounts["account_id"],
        rng.lognormal(mean=0.0, sigma=config.LOGIN_INTENSITY_SIGMA, size=len(accounts)),
    ))

    rows = []
    login_seq = 0
    sim_end_ts = pd.Timestamp(config.SIM_END)

    for acc in accounts.itertuples():
        signup_ts = pd.Timestamp(acc.signup_date)
        churn_ts = churn_date_by_account.get(acc.account_id)
        end_ts = churn_ts if churn_ts is not None else sim_end_ts
        if end_ts < signup_ts:
            continue

        months = pd.period_range(_month_floor(signup_ts), _month_floor(end_ts), freq="M")
        intensity = intensity_by_account[acc.account_id]
        fading = acc.account_id in declining
        decline_start = (
            (churn_ts - pd.DateOffset(months=config.DECLINE_MONTHS_BEFORE_CHURN)) if (fading and churn_ts is not None) else None
        )
        onboarding_end = signup_ts + pd.Timedelta(days=config.LOGIN_ONBOARDING_DAYS)

        for period in months:
            month_start = period.start_time
            month_end = month_start + pd.DateOffset(months=1)
            rate = config.LOGIN_RATE_BASELINE[acc.segment] * intensity

            # Onboarding boost is date-based (LOGIN_ONBOARDING_DAYS from
            # signup), not month-index-based -- scale it down if only part
            # of this month falls inside the onboarding window.
            onboarding_overlap_days = max(
                0, (min(month_end, onboarding_end) - max(month_start, signup_ts)).days
            )
            month_span_days = period.days_in_month
            onboarding_frac = onboarding_overlap_days / month_span_days
            rate *= 1 + onboarding_frac * (config.LOGIN_ONBOARDING_MULTIPLIER - 1)

            prechurn = fading and decline_start is not None and month_start >= decline_start and month_start < churn_ts
            if prechurn:
                rate *= config.LOGIN_PRECHURN_MULTIPLIER

            n_logins = rng.poisson(rate)
            if n_logins == 0:
                continue

            # First/last partial month of an account's tenure -- clamp the
            # day offset so no login lands before signup_date or after
            # churn_date (same fix support_tickets.py/am_activity.py needed).
            day_lo = (signup_ts.day - 1) if period == months[0] else 0
            day_hi = (churn_ts.day - 1) if (churn_ts is not None and period == months[-1]) else month_span_days - 1
            day_hi = max(day_hi, day_lo)
            offsets = rng.integers(day_lo, day_hi + 1, size=n_logins)

            for offset in offsets:
                login_seq += 1
                login_date = (month_start + pd.Timedelta(days=int(offset))).date()
                rows.append({
                    "login_id": f"LGN-{login_seq:07d}",
                    "account_id": acc.account_id,
                    "segment": acc.segment,
                    "login_date": login_date,
                })

    return pd.DataFrame(rows)
