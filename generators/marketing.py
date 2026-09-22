"""marketing_spend_by_channel_month generator.

Build spec Section 5 (Marketing automation): `marketing_spend_by_channel_month`
(channel, month, spend, geo/segment -- "doesn't exist yet, and several
metrics already in the tree assume it does"). Unlike the event-grain rule
elsewhere in this project, spend genuinely is a periodic aggregate in the
real source system (an ad platform or finance ledger reports spend
per-channel-per-month, not per-event) -- generating this pre-aggregated is
the correct grain here, not a shortcut.

channel here is the same 3-value taxonomy already on accounts.channel
(inbound_marketing / outbound_sdr / self_serve), not the finer organic/
paid/community sub-channel split the design brief's "Pipeline generated"
Layer 2 node describes -- that finer split needs leads/campaigns data this
batch doesn't produce, same deferral logic as config.py notes for rep cost.
No geo/segment breakdown either -- Wave 1's Efficiency-pillar metrics only
need CAC by channel, not by channel x region, so that dimension is left for
whichever later artifact (territory/channel-mix analytics) actually needs it.

Spend is derived from real, already-generated new-account volume (accounts.
signup_date x accounts.channel), not invented independently: spend =
new_accounts_this_channel_month x target_CAC x noise. This is what makes
realized CAC (spend / new accounts, computed downstream in dbt) land near
config.TARGET_CAC_BY_CHANNEL by construction while still varying
realistically month to month -- and lets the CAC-creep incident below raise
spend without touching the (already-fixed) volume side, exactly the
"detectable via a straightforward variance check" shape the QA plan wants.
"""
import numpy as np
import pandas as pd

from . import config


def _month_floor(d) -> pd.Timestamp:
    return pd.Timestamp(d).to_period("M").start_time


def _new_accounts_by_channel_month(accounts: pd.DataFrame) -> pd.DataFrame:
    df = accounts.copy()
    df["month"] = pd.to_datetime(df["signup_date"]).apply(_month_floor)
    return df.groupby(["channel", "month"]).size().rename("new_accounts").reset_index()


def generate_marketing_spend(rng: np.random.Generator, accounts: pd.DataFrame) -> pd.DataFrame:
    counts = _new_accounts_by_channel_month(accounts)

    months = pd.period_range(
        _month_floor(config.SIM_START), _month_floor(config.SIM_END), freq="M"
    ).to_timestamp()
    channels = list(config.TARGET_CAC_BY_CHANNEL.keys())
    grid = pd.MultiIndex.from_product([channels, months], names=["channel", "month"]).to_frame(index=False)
    grid = grid.merge(counts, on=["channel", "month"], how="left")
    grid["new_accounts"] = grid["new_accounts"].fillna(0).astype(int)

    incident_start, incident_end = config.CAC_CREEP_INCIDENT_WINDOW
    incident_start_ts, incident_end_ts = pd.Timestamp(incident_start), pd.Timestamp(incident_end)

    rows = []
    for r in grid.itertuples():
        target_cac = config.TARGET_CAC_BY_CHANNEL[r.channel]
        noise = rng.lognormal(0, config.MARKETING_SPEND_NOISE_SIGMA)
        if r.new_accounts > 0:
            spend = r.new_accounts * target_cac * noise
        else:
            # Real channel programs (content retainers, SDR tooling) still
            # carry a minimum baseline cost in a zero-conversion month,
            # rather than spend snapping to exactly $0 -- but that baseline
            # is a small fraction of a full CAC, not "1 phantom account's
            # worth," which would badly distort realized CAC for a
            # low-volume channel like outbound_sdr (own resolved decision).
            spend = 0.15 * target_cac * noise

        is_incident = (
            r.channel == config.CAC_CREEP_INCIDENT_CHANNEL
            and incident_start_ts <= r.month <= incident_end_ts
        )
        if is_incident:
            spend *= config.CAC_CREEP_INCIDENT_SPEND_MULTIPLIER

        rows.append({
            "channel": r.channel,
            "month": r.month.date(),
            "spend": round(spend, 2),
            "new_accounts": r.new_accounts,
        })

    return pd.DataFrame(rows)
