"""Orchestrator for the foundational Phase 1 generator batch: users (reps),
market_universe, accounts, account_segment_history.

Run from the repo root:
    python3 -m generators.run_foundation

Writes CSVs to data/raw/ and prints a summary of what was generated.
"""
import math

import numpy as np

from . import config
from .accounts import generate_accounts_and_segment_history, solve_entry_cohort_sizes
from .market_universe import generate_market_universe
from .reps import generate_reps

OUT_DIR = "data/raw"


def main():
    rng = np.random.default_rng(config.SEED)

    n_am_commercial = math.ceil(config.FINAL_COMMERCIAL / config.COMMERCIAL_BOOK_SIZE)
    n_am_enterprise = math.ceil(config.FINAL_ENTERPRISE / config.ENTERPRISE_BOOK_SIZE)

    users_df, quota_history_df, rep_status_history_df = generate_reps(rng, n_am_commercial, n_am_enterprise)
    market_universe_df = generate_market_universe(rng)
    accounts_df, segment_history_df, market_universe_df = generate_accounts_and_segment_history(
        rng, market_universe_df
    )

    import os
    os.makedirs(OUT_DIR, exist_ok=True)
    users_df.to_csv(f"{OUT_DIR}/users.csv", index=False)
    quota_history_df.to_csv(f"{OUT_DIR}/quota_history.csv", index=False)
    rep_status_history_df.to_csv(f"{OUT_DIR}/rep_status_history.csv", index=False)
    market_universe_df.to_csv(f"{OUT_DIR}/market_universe.csv", index=False)
    accounts_df.to_csv(f"{OUT_DIR}/accounts.csv", index=False)
    segment_history_df.to_csv(f"{OUT_DIR}/account_segment_history.csv", index=False)

    cohorts = solve_entry_cohort_sizes()
    print("=== Foundation batch generated ===")
    print(f"users: {len(users_df)} reps "
          f"(ISR={config.N_ISR}, AE={config.N_AE}, "
          f"SE={round(config.N_AE * config.SE_TO_AE_RATIO)}, "
          f"AM-Commercial={n_am_commercial}, AM-Enterprise={n_am_enterprise})")
    print(f"quota_history: {len(quota_history_df)} rows")
    print(f"rep_status_history: {len(rep_status_history_df)} rows "
          f"({(rep_status_history_df['status'] == 'departed').sum()} departures)")
    print(f"market_universe: {len(market_universe_df)} rows "
          f"({market_universe_df['is_customer'].sum()} customers, "
          f"{(~market_universe_df['is_customer']).sum()} non-customers)")
    print(f"accounts: {len(accounts_df)} rows -- entry cohorts {cohorts}")
    print(f"  current-state segment mix: {accounts_df['segment'].value_counts().to_dict()}")
    print(f"account_segment_history: {len(segment_history_df)} rows")
    print(f"  trigger_reason counts: {segment_history_df['trigger_reason'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
