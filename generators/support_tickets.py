"""support_tickets generator.

Build spec Section 5 (CS-ops): `support_tickets` (volume, severity,
resolution time, CSAT), feeding the account health score. Event grain --
one row per ticket, not a pre-aggregated monthly count.

Ticket volume and severity are driven by two real, already-generated
signals rather than independent randomness (generate-gtm-data skill, rule
1): each account's onboarding period (config.ACTIVATION_RAMP_MONTHS,
computed from its own signup_date) and its pre-churn "fading" window,
derived from usage_monthly itself -- not from a hidden random flag no
downstream consumer could ever see. This mirrors usage.py's own pre-churn
decline mechanism so every health-score input moves together around the
same real trajectory instead of each generator inventing an unrelated one.
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
    """Data-derived proxy for usage.py's is_abrupt_churn flag, which isn't
    persisted to disk: an account "fades" if its actions_consumed in the
    DECLINE_MONTHS_BEFORE_CHURN window before churn sits well below its own
    prior-6-month peak. Deriving this from the real usage_monthly output
    (rather than needing the original hidden random draw) is itself more
    consistent with the causal-wiring rule -- ticket/AM signals key off the
    same observable pattern a real health-score model would actually see.
    """
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


def _severity_and_csat(rng: np.random.Generator, n: int, prechurn: bool):
    mix = config.SEVERITY_MIX_PRECHURN if prechurn else config.SEVERITY_MIX_BASELINE
    severities = rng.choice(list(mix.keys()), size=n, p=list(mix.values()))
    return severities


def generate_support_tickets(rng: np.random.Generator, accounts: pd.DataFrame,
                              usage_monthly: pd.DataFrame, subscriptions: pd.DataFrame) -> pd.DataFrame:
    churn_date_by_account = _churn_date_by_account(subscriptions)
    declining = _declining_accounts(usage_monthly, churn_date_by_account)

    rows = []
    ticket_seq = 0
    sim_end_ts = pd.Timestamp(config.SIM_END)

    for acc in accounts.itertuples():
        signup_ts = pd.Timestamp(acc.signup_date)
        churn_ts = churn_date_by_account.get(acc.account_id)
        end_ts = churn_ts if churn_ts is not None else sim_end_ts
        if end_ts < signup_ts:
            continue

        months = pd.period_range(_month_floor(signup_ts), _month_floor(end_ts), freq="M")
        ramp_months = config.ACTIVATION_RAMP_MONTHS[acc.segment]
        fading = acc.account_id in declining
        decline_start = (
            (churn_ts - pd.DateOffset(months=config.DECLINE_MONTHS_BEFORE_CHURN)) if (fading and churn_ts is not None) else None
        )

        for i, period in enumerate(months):
            month_start = period.start_time
            rate = config.TICKET_RATE_BASELINE[acc.segment]

            if i < ramp_months:
                rate *= config.TICKET_ONBOARDING_MULTIPLIER
            prechurn = fading and decline_start is not None and month_start >= decline_start and month_start < churn_ts
            if prechurn:
                rate *= config.TICKET_PRECHURN_MULTIPLIER

            n_tickets = rng.poisson(rate)
            if n_tickets == 0:
                continue

            severities = _severity_and_csat(rng, n_tickets, prechurn)
            # First/last month of an account's tenure is usually partial --
            # clamp the day offset so no ticket lands before signup_date or
            # after churn_date (QA plan's referential-integrity spirit:
            # events must fall within the account's actual observed window).
            day_lo = (signup_ts.day - 1) if period == months[0] else 0
            day_hi = (churn_ts.day - 1) if (churn_ts is not None and period == months[-1]) else period.days_in_month - 1
            day_hi = max(day_hi, day_lo)
            created_offsets = rng.integers(day_lo, day_hi + 1, size=n_tickets)

            for sev, offset in zip(severities, created_offsets):
                ticket_seq += 1
                created_date = (month_start + pd.Timedelta(days=int(offset))).date()
                lo, hi = config.RESOLUTION_HOURS_RANGE[sev]
                resolution_hours = rng.uniform(lo, hi)
                resolved_ts = pd.Timestamp(created_date) + pd.Timedelta(hours=resolution_hours)
                # Right-censored: a ticket opened very near SIM_END may not
                # have resolved within the observed window yet (QA plan's
                # time-window edge case, applied here too).
                is_resolved = resolved_ts <= sim_end_ts + pd.Timedelta(days=1)

                csat = None
                if is_resolved and rng.random() < config.CSAT_RESPONSE_RATE:
                    csat_mean = config.CSAT_MEAN_BY_SEVERITY[sev]
                    csat = int(np.clip(round(rng.normal(csat_mean, 0.7)), 1, 5))

                rows.append({
                    "ticket_id": f"TCK-{ticket_seq:07d}",
                    "account_id": acc.account_id,
                    "segment": acc.segment,
                    "created_date": created_date,
                    "resolved_date": resolved_ts.date() if is_resolved else None,
                    "severity": sev,
                    "resolution_time_hours": round(resolution_hours, 1) if is_resolved else None,
                    "csat_score": csat,
                })

    return pd.DataFrame(rows)
