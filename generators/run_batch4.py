"""Orchestrator for the fourth Phase 1 generator batch: product_logins.

Run from the repo root (after generators.run_foundation and
generators.run_batch2 have produced data/raw/{accounts,usage_monthly,
subscriptions}.csv):

    python3 -m generators.run_batch4

Uses a seed offset from the prior batches' (config.SEED + 3000) so this
batch is independently reproducible without depending on any prior batch
having just run in the same process -- it reads their *output CSVs*, not
their in-memory state, same pattern as run_batch2.py/run_batch3.py.

Fills the one Wave-1-blocking gap batch 3 didn't cover: engagement/login
frequency as its own signal, distinct from usage volume. Without this, the
account health score couldn't implement the QA plan's specific rule that a
fully-automated, high-usage account can be healthy despite low logins --
there was nothing to show that pattern actually existing in the data.
"""
import os

import numpy as np
import pandas as pd

from . import config
from .product_logins import generate_product_logins

DATA_DIR = "data/raw"
BATCH4_SEED = config.SEED + 3000


def _load_prior_batches():
    accounts = pd.read_csv(f"{DATA_DIR}/accounts.csv", parse_dates=["signup_date"])
    accounts["signup_date"] = accounts["signup_date"].dt.date
    usage_monthly = pd.read_csv(f"{DATA_DIR}/usage_monthly.csv", parse_dates=["month"])
    usage_monthly["month"] = usage_monthly["month"].dt.date
    subscriptions = pd.read_csv(f"{DATA_DIR}/subscriptions.csv", parse_dates=["start_date", "end_date"])
    return accounts, usage_monthly, subscriptions


def main():
    rng = np.random.default_rng(BATCH4_SEED)
    accounts, usage_monthly, subscriptions = _load_prior_batches()

    logins_df = generate_product_logins(rng, accounts, usage_monthly, subscriptions)

    os.makedirs(DATA_DIR, exist_ok=True)
    logins_df.to_csv(f"{DATA_DIR}/product_logins.csv", index=False)

    print("=== Batch 4 generated ===")
    print(f"product_logins: {len(logins_df)} rows across {logins_df['account_id'].nunique()} accounts")
    logins_per_account = logins_df.groupby("account_id").size()
    print(f"  logins/account: mean={logins_per_account.mean():.1f}, "
          f"median={logins_per_account.median():.1f}, max={logins_per_account.max()}")

    # Quick sanity check on the automation edge case this batch exists to
    # enable: accounts with high total usage but low login count should
    # exist in non-trivial numbers (formal QA-plan test lives in
    # tests/test_phase1_batch4.py; this is just a build-time signal).
    usage_totals = usage_monthly.groupby("account_id")["actions_consumed"].sum()
    high_usage_cutoff = usage_totals.quantile(0.75)
    login_counts = logins_df.groupby("account_id").size()
    high_usage_accounts = set(usage_totals[usage_totals >= high_usage_cutoff].index)
    low_login_accounts = set(login_counts[login_counts <= login_counts.quantile(0.25)].index) | (
        set(accounts["account_id"]) - set(login_counts.index)
    )
    automated_cohort = high_usage_accounts & low_login_accounts
    print(f"  high-usage + low-login (automated-but-healthy candidate) accounts: {len(automated_cohort)}")


if __name__ == "__main__":
    main()
