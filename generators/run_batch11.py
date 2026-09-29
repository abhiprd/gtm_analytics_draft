"""Orchestrator for the eleventh Phase 1 generator batch: lead_scoring_history.

Run from the repo root (after generators.run_foundation and
generators.run_batch7 have produced data/raw/{market_universe,leads}.csv):

    python3 -m generators.run_batch11

Uses a seed offset from the prior batches' (config.SEED + 10000) so this
batch is independently reproducible without depending on any prior batch
having just run in the same process -- it reads market_universe.csv and
leads.csv's *output CSVs*, not their in-memory state, same pattern as
run_batch2.py through run_batch9.py.

Batch number note: this was originally staged as run_batch10.py. A sibling
batch built concurrently on this branch claimed batch 10 first for
experiments_registry/experiment_assignment (generators/experiments.py) --
this batch was renumbered to the next free slot rather than overwriting
that work, per this project's established concurrent-batch etiquette (each
batch adds its own entries/files rather than contesting a shared name).

Fills the data gap Wave 7's "Lead/segmentation scoring -- model validation &
drift detection" artifact (build spec Section 8, item #11) is blocked on --
the same situation Wave 2 was in before run_batch7.py's campaigns/leads
existed, Wave 4 before run_batch8.py's fact_sales_activities existed, and
Wave 5 before run_batch9.py's territory tables existed. This batch adds no
leads and no companies; it reads market_universe.csv and leads.csv and never
writes back to either -- lead_scoring_history is delivered as one new
event-grain table (score_id grain, lead_id FK) joined in at the dbt layer.

See generators/lead_scoring.py for the re-scoring-cadence and model_version
design decisions and their full grounding.
"""
import os

import numpy as np
import pandas as pd

from . import config
from .lead_scoring import (
    LEAD_SCORING_COLUMNS,
    MODEL_CUTOVER_DATE,
    MODEL_VERSION_V1,
    MODEL_VERSION_V2,
    generate_lead_scoring_history,
)

DATA_DIR = "data/raw"
BATCH11_SEED = config.SEED + 10000


def _load_prior_batches():
    market_universe = pd.read_csv(f"{DATA_DIR}/market_universe.csv")
    leads = pd.read_csv(
        f"{DATA_DIR}/leads.csv",
        parse_dates=["created_date", "converted_date"],
    )
    return market_universe, leads


def main():
    rng = np.random.default_rng(BATCH11_SEED)
    market_universe, leads = _load_prior_batches()

    history = generate_lead_scoring_history(rng, leads, market_universe)

    os.makedirs(DATA_DIR, exist_ok=True)
    history.to_csv(f"{DATA_DIR}/lead_scoring_history.csv", index=False)

    print("=== Batch 11 generated ===")
    print(f"lead_scoring_history: {len(history)} rows "
          f"({history['lead_id'].nunique()} distinct scored leads "
          f"of {leads['lead_id'].nunique()} total leads)")
    events_per_lead = history.groupby("lead_id").size()
    print(f"  events per lead: min={events_per_lead.min()} "
          f"median={events_per_lead.median():.1f} max={events_per_lead.max()}")
    print(f"  model_version mix: {dict(history['model_version'].value_counts())}")

    # --- referential / structural sanity -----------------------------------
    print("\n  sanity checks:")
    print(f"    every lead_id resolves to leads.csv: "
          f"{set(history['lead_id']) <= set(leads['lead_id'])}")
    print(f"    every lead has at least one scoring event: "
          f"{set(leads['lead_id']) == set(history['lead_id'])}")
    print(f"    score_id is unique: {history['score_id'].is_unique}")
    print(f"    (lead_id, scored_at) is unique -- no shared timestamps: "
          f"{not history.duplicated(['lead_id', 'scored_at']).any()}")
    print(f"    predicted_fit_score within [0, 100]: "
          f"{history['predicted_fit_score'].between(0, 100).all()}")
    print(f"    model_version is one of the two declared values: "
          f"{set(history['model_version']) == {MODEL_VERSION_V1, MODEL_VERSION_V2}}")
    print(f"    region_component is null iff model_version is v1: "
          f"{(history['region_component'].isna() == (history['model_version'] == MODEL_VERSION_V1)).all()}")
    print(f"    model_version matches scored_at vs. cutover ({MODEL_CUTOVER_DATE.date()}): "
          f"{((pd.to_datetime(history['scored_at']) >= MODEL_CUTOVER_DATE) == (history['model_version'] == MODEL_VERSION_V2)).all()}")

    # --- point-in-time safety: no scoring event on/after a known outcome ---
    converted = leads.loc[leads["is_converted"], ["lead_id", "created_date", "converted_date"]]
    merged = history.merge(converted, on="lead_id", how="inner")
    merged["scored_at"] = pd.to_datetime(merged["scored_at"])
    no_leak = (merged["scored_at"] < merged["converted_date"]).all()
    no_early = (merged["scored_at"] >= merged["created_date"]).all()
    print(f"\n  point-in-time safety:")
    print(f"    every scoring event on a converting lead precedes its converted_date: {no_leak}")
    print(f"    every scoring event is on or after its lead's created_date: {no_early}")

    # --- correlational validity (checked, not used, by the generator) ------
    print("\n  correlational validity (post-hoc check only -- the generator never reads is_converted):")
    last_score = history.sort_values("scored_at").groupby("lead_id").tail(1)
    joined = last_score.merge(leads[["lead_id", "is_converted"]], on="lead_id")
    by_outcome = joined.groupby("is_converted")["predicted_fit_score"].mean()
    print(f"    mean last predicted_fit_score, converted vs. non-converted: "
          f"{dict(by_outcome.round(1))}")

    v1 = history[history["model_version"] == MODEL_VERSION_V1]
    v2 = history[history["model_version"] == MODEL_VERSION_V2]
    region_by_company = dict(zip(market_universe["company_id"], market_universe["region"]))
    region_by_lead = dict(zip(leads["lead_id"], leads["company_id"].map(region_by_company)))
    v1_region_spread = v1.assign(region=v1["lead_id"].map(region_by_lead)).groupby("region")["predicted_fit_score"].mean()
    v2_region_spread = v2.assign(region=v2["lead_id"].map(region_by_lead)).groupby("region")["predicted_fit_score"].mean()
    print(f"    mean predicted_fit_score by region, v1 (region unused): {dict(v1_region_spread.round(1))}")
    print(f"    mean predicted_fit_score by region, v2 (region used): {dict(v2_region_spread.round(1))}")


if __name__ == "__main__":
    main()
