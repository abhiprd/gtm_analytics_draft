"""Orchestrator for the second Phase 1 generator batch: opportunities,
opportunity_stage_history, usage_monthly, fact_workflow_chain_events,
subscriptions, mrr_by_account_month, committed_vs_utilized_monthly.

Run from the repo root (after generators.run_foundation has produced
data/raw/{users,rep_status_history,market_universe,accounts,
account_segment_history}.csv):

    python3 -m generators.run_batch2

Uses a seed offset from batch 1's (config.SEED + 1000) so this batch is
independently reproducible without depending on batch 1 having just run in
the same process -- it reads batch 1's *output CSVs*, not its in-memory
state.
"""
import os

import numpy as np
import pandas as pd

from . import config
from .contracts import build_contract_plan
from .opportunities import (
    generate_new_business_opportunities,
    generate_expansion_opportunities,
    generate_renewal_opportunities,
    finalize_opportunities,
)
from .usage import generate_usage
from .billing import build_subscriptions, build_billing_monthly

DATA_DIR = "data/raw"
BATCH2_SEED = config.SEED + 1000


def _load_batch1():
    accounts = pd.read_csv(f"{DATA_DIR}/accounts.csv", parse_dates=["signup_date"])
    accounts["signup_date"] = accounts["signup_date"].dt.date
    segment_history = pd.read_csv(f"{DATA_DIR}/account_segment_history.csv", parse_dates=["effective_date"])
    segment_history["effective_date"] = segment_history["effective_date"].dt.date
    market_universe = pd.read_csv(f"{DATA_DIR}/market_universe.csv")
    users = pd.read_csv(f"{DATA_DIR}/users.csv", parse_dates=["hire_date"])
    users["hire_date"] = users["hire_date"].dt.date
    rep_status_history = pd.read_csv(f"{DATA_DIR}/rep_status_history.csv", parse_dates=["effective_date"])
    rep_status_history["effective_date"] = rep_status_history["effective_date"].dt.date
    return accounts, segment_history, market_universe, users, rep_status_history


def main():
    rng = np.random.default_rng(BATCH2_SEED)
    accounts, segment_history, market_universe, users, rep_status_history = _load_batch1()

    contract_plan, renewal_events = build_contract_plan(rng, accounts, segment_history)

    nb_opp, nb_stage = generate_new_business_opportunities(
        rng, accounts, segment_history, market_universe, users, rep_status_history, contract_plan
    )
    exp_opp, exp_stage = generate_expansion_opportunities(
        rng, accounts, segment_history, users, rep_status_history, contract_plan
    )
    ren_opp, ren_stage = generate_renewal_opportunities(rng, accounts, renewal_events, users, rep_status_history)
    opportunities_df, stage_history_df = finalize_opportunities(
        nb_opp + exp_opp + ren_opp, nb_stage + exp_stage + ren_stage
    )

    usage_monthly_df, chain_events_df = generate_usage(rng, accounts, segment_history, contract_plan)

    subscriptions_df = build_subscriptions(contract_plan, renewal_events)
    mrr_df, cvu_df = build_billing_monthly(usage_monthly_df, subscriptions_df)

    os.makedirs(DATA_DIR, exist_ok=True)
    opportunities_df.to_csv(f"{DATA_DIR}/opportunities.csv", index=False)
    stage_history_df.to_csv(f"{DATA_DIR}/opportunity_stage_history.csv", index=False)
    usage_monthly_df.to_csv(f"{DATA_DIR}/usage_monthly.csv", index=False)
    chain_events_df.to_csv(f"{DATA_DIR}/fact_workflow_chain_events.csv", index=False)
    subscriptions_df.to_csv(f"{DATA_DIR}/subscriptions.csv", index=False)
    mrr_df.to_csv(f"{DATA_DIR}/mrr_by_account_month.csv", index=False)
    cvu_df.to_csv(f"{DATA_DIR}/committed_vs_utilized_monthly.csv", index=False)

    print("=== Batch 2 generated ===")
    print(f"opportunities: {len(opportunities_df)} rows "
          f"({opportunities_df['is_won'].sum()} won, {(~opportunities_df['is_won']).sum()} lost)")
    print(f"  by opportunity_type: {opportunities_df['opportunity_type'].value_counts().to_dict()}")
    for seg in ["Commercial", "Enterprise"]:
        nb = opportunities_df[(opportunities_df["segment"] == seg) & (opportunities_df["opportunity_type"] == "new_business")]
        win_rate = nb["is_won"].mean()
        print(f"  {seg} new_business win rate: {win_rate:.1%} (n={len(nb)})")
    print(f"opportunity_stage_history: {len(stage_history_df)} rows")
    print(f"usage_monthly: {len(usage_monthly_df)} rows")
    print(f"fact_workflow_chain_events: {len(chain_events_df)} rows")
    print(f"subscriptions: {len(subscriptions_df)} rows "
          f"({(subscriptions_df['status'] == 'churned').sum()} churned periods)")
    print(f"mrr_by_account_month: {len(mrr_df)} rows, total end-of-window MRR run-rate check pending in tests")
    print(f"committed_vs_utilized_monthly: {len(cvu_df)} rows")
    n_churned_accounts = int(contract_plan["churn_date"].notna().sum())
    print(f"accounts with a pre-committed churn_date: {n_churned_accounts} / {len(contract_plan)} "
          f"({n_churned_accounts / len(contract_plan):.1%})")


if __name__ == "__main__":
    main()
