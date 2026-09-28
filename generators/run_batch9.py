"""Orchestrator for the ninth Phase 1 generator batch: the territory
dimension (company_territory.csv, rep_territory.csv).

Run from the repo root (after generators.run_foundation and
generators.run_batch2 have produced data/raw/{market_universe,users}.csv):

    python3 -m generators.run_batch9

Uses a seed offset from the prior batches' (config.SEED + 8000) so this
batch is independently reproducible without depending on any prior batch
having just run in the same process -- it reads run_foundation's and
run_batch2's *output CSVs*, not their in-memory state, same pattern as
run_batch2.py through run_batch8.py.

Fills the data gap Wave 5's "Territory / account coverage & routing" (build
spec Section 8, item #21) is blocked on -- the same situation Wave 2 was in
before run_batch7.py's campaigns/leads/campaign_engagement_events existed,
and Wave 4 before run_batch8.py's fact_sales_activities existed.
`dim_market_universe.sql` and `mart_tam_whitespace.sql` both name this
specific gap in their own header comments already. This batch adds no
companies, no accounts and no reps; it reads market_universe.csv and
users.csv and never writes back to either -- territory is delivered as two
new lookup tables (company_territory.csv keyed by company_id,
rep_territory.csv keyed by rep_id) joined in at the dbt layer, exactly the
"new raw table, no change to an already-shipped generator" shape run_batch8
used for fact_sales_activities.

See generators/territories.py for the territory design decision (a
deterministic sub-division of `region`, grounded against rep headcount) and
its full reasoning.
"""
import os

import numpy as np
import pandas as pd

from . import config
from .territories import (
    REGION_FOR_TERRITORY,
    TERRITORIES,
    TERRITORY_ELIGIBLE_REP_TYPES,
    assign_company_territory,
    assign_rep_territory,
)

DATA_DIR = "data/raw"
BATCH9_SEED = config.SEED + 8000


def _load_prior_batches():
    market_universe = pd.read_csv(f"{DATA_DIR}/market_universe.csv")
    users = pd.read_csv(f"{DATA_DIR}/users.csv", parse_dates=["hire_date"])
    return market_universe, users


def main():
    rng = np.random.default_rng(BATCH9_SEED)
    market_universe, users = _load_prior_batches()

    company_territory = pd.DataFrame({
        "company_id": market_universe["company_id"],
        "territory": assign_company_territory(rng, market_universe["region"].to_numpy()),
    })
    rep_territory = assign_rep_territory(rng, users)

    os.makedirs(DATA_DIR, exist_ok=True)
    company_territory.to_csv(f"{DATA_DIR}/company_territory.csv", index=False)
    rep_territory.to_csv(f"{DATA_DIR}/rep_territory.csv", index=False)

    print("=== Batch 9 generated ===")
    print(f"company_territory: {len(company_territory)} rows "
          f"({company_territory['company_id'].nunique()} distinct companies)")
    print(f"  territory mix: {dict(company_territory['territory'].value_counts())}")
    print(f"rep_territory: {len(rep_territory)} rows "
          f"({rep_territory['rep_id'].nunique()} distinct reps)")
    print(f"  territory mix: {dict(rep_territory['territory'].value_counts())}")

    # --- referential / structural sanity -----------------------------------
    print("\n  sanity checks:")
    print(f"    every market_universe company_id has exactly one territory row: "
          f"{company_territory['company_id'].is_unique and set(company_territory['company_id']) == set(market_universe['company_id'])}")
    nb_reps = users.loc[users["rep_type"].isin(TERRITORY_ELIGIBLE_REP_TYPES), "rep_id"]
    print(f"    rep_territory covers exactly the ISR/AE population, no more, no less: "
          f"{set(rep_territory['rep_id']) == set(nb_reps)}")
    print(f"    every territory value is declared: "
          f"{set(company_territory['territory']) <= set(TERRITORIES) and set(rep_territory['territory']) <= set(TERRITORIES)}")

    region_by_company = dict(zip(market_universe["company_id"], market_universe["region"]))
    mismatched = [
        row.company_id for row in company_territory.itertuples()
        if REGION_FOR_TERRITORY[row.territory] != region_by_company[row.company_id]
    ]
    print(f"    every company's territory maps back to its own region: {len(mismatched) == 0} "
          f"({len(mismatched)} mismatches)")

    # --- distributional realism / grounded imbalance -------------------------
    print("\n  distributional realism:")
    company_share = (company_territory["territory"].value_counts(normalize=True) * 100).round(1)
    rep_share = (rep_territory["territory"].value_counts(normalize=True) * 100).round(1)
    for t in TERRITORIES:
        cs, rs = company_share.get(t, 0.0), rep_share.get(t, 0.0)
        ratio = (rs / cs) if cs else float("nan")
        print(f"    {t:<8s} company share {cs:5.1f}%  rep share {rs:5.1f}%  ratio {ratio:.2f}")


if __name__ == "__main__":
    main()
