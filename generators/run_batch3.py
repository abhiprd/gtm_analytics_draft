"""Orchestrator for the third Phase 1 generator batch: support_tickets,
am_activity, marketing_spend_by_channel_month.

Run from the repo root (after generators.run_foundation and
generators.run_batch2 have produced data/raw/{accounts,
account_segment_history,users,rep_status_history,usage_monthly,
subscriptions}.csv):

    python3 -m generators.run_batch3

Uses a seed offset from batch 1/2's (config.SEED + 2000) so this batch is
independently reproducible without depending on either prior batch having
just run in the same process -- it reads their *output CSVs*, not their
in-memory state, same pattern as run_batch2.py.

Unblocks the account health score (support_tickets, am_activity) and part
of the Efficiency pillar (marketing_spend_by_channel_month, for Consumption
Payback's CAC-by-channel line). Still open after this batch: rep cost/comp
data, needed for Magic Number and AM Efficiency's S&M/AM cost inputs, and
the finer organic/paid/community channel split leads/campaigns data would
give the Growth pillar's "Pipeline generated" Layer 2 node -- both flagged
in config.py's comments rather than silently assumed away.
"""
import os

import numpy as np
import pandas as pd

from . import config
from .am_activity import generate_am_activity
from .marketing import generate_marketing_spend
from .support_tickets import generate_support_tickets

DATA_DIR = "data/raw"
BATCH3_SEED = config.SEED + 2000


def _load_prior_batches():
    accounts = pd.read_csv(f"{DATA_DIR}/accounts.csv", parse_dates=["signup_date"])
    accounts["signup_date"] = accounts["signup_date"].dt.date
    users = pd.read_csv(f"{DATA_DIR}/users.csv", parse_dates=["hire_date"])
    users["hire_date"] = users["hire_date"].dt.date
    rep_status_history = pd.read_csv(f"{DATA_DIR}/rep_status_history.csv", parse_dates=["effective_date"])
    rep_status_history["effective_date"] = rep_status_history["effective_date"].dt.date
    usage_monthly = pd.read_csv(f"{DATA_DIR}/usage_monthly.csv", parse_dates=["month"])
    usage_monthly["month"] = usage_monthly["month"].dt.date
    subscriptions = pd.read_csv(f"{DATA_DIR}/subscriptions.csv", parse_dates=["start_date", "end_date"])
    return accounts, users, rep_status_history, usage_monthly, subscriptions


def main():
    rng = np.random.default_rng(BATCH3_SEED)
    accounts, users, rep_status_history, usage_monthly, subscriptions = _load_prior_batches()

    tickets_df = generate_support_tickets(rng, accounts, usage_monthly, subscriptions)
    am_activity_df = generate_am_activity(rng, accounts, users, rep_status_history, usage_monthly, subscriptions)
    marketing_spend_df = generate_marketing_spend(rng, accounts)

    os.makedirs(DATA_DIR, exist_ok=True)
    tickets_df.to_csv(f"{DATA_DIR}/support_tickets.csv", index=False)
    am_activity_df.to_csv(f"{DATA_DIR}/am_activity.csv", index=False)
    marketing_spend_df.to_csv(f"{DATA_DIR}/marketing_spend_by_channel_month.csv", index=False)

    print("=== Batch 3 generated ===")
    print(f"support_tickets: {len(tickets_df)} rows across {tickets_df['account_id'].nunique()} accounts")
    print(f"  severity mix: {tickets_df['severity'].value_counts(normalize=True).round(3).to_dict()}")
    print(f"  csat response rate: {tickets_df['csat_score'].notna().mean():.1%}")
    print(f"am_activity: {len(am_activity_df)} rows across {am_activity_df['account_id'].nunique()} accounts "
          f"({am_activity_df['am_rep_id'].nunique()} distinct AMs touched)")
    print(f"  by activity_type: {am_activity_df['activity_type'].value_counts().to_dict()}")
    print(f"  sentiment_score: mean={am_activity_df['sentiment_score'].mean():.2f}, "
          f"min={am_activity_df['sentiment_score'].min():.2f}, max={am_activity_df['sentiment_score'].max():.2f}")
    print(f"marketing_spend_by_channel_month: {len(marketing_spend_df)} rows")
    spend_by_channel = marketing_spend_df.groupby("channel")["spend"].sum()
    accounts_by_channel = marketing_spend_df.groupby("channel")["new_accounts"].sum().clip(lower=1)
    realized_cac = spend_by_channel / accounts_by_channel
    print(f"  realized blended CAC by channel: {realized_cac.round(2).to_dict()}")
    incident_start, incident_end = config.CAC_CREEP_INCIDENT_WINDOW
    incident_mask = (
        (marketing_spend_df["channel"] == config.CAC_CREEP_INCIDENT_CHANNEL)
        & (pd.to_datetime(marketing_spend_df["month"]) >= pd.Timestamp(incident_start))
        & (pd.to_datetime(marketing_spend_df["month"]) <= pd.Timestamp(incident_end))
    )
    incident_cac = (
        marketing_spend_df[incident_mask]["spend"].sum()
        / max(marketing_spend_df[incident_mask]["new_accounts"].sum(), 1)
    )
    print(f"  CAC-creep incident ({config.CAC_CREEP_INCIDENT_CHANNEL}, "
          f"{incident_start}..{incident_end}): incident-window CAC=${incident_cac:,.0f} "
          f"vs. overall channel CAC=${realized_cac[config.CAC_CREEP_INCIDENT_CHANNEL]:,.0f}")


if __name__ == "__main__":
    main()
