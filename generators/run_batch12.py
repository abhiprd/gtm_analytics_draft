"""Orchestrator for the twelfth Phase 1 generator batch: experiments_registry
and experiment_assignment.

Run from the repo root (after generators.run_batch7 has produced
data/raw/{campaigns,leads,campaign_engagement_events}.csv):

    python3 -m generators.run_batch12

Fills the data gap Wave 7's "Testing/experimentation methodology &
platform" artifact (build spec Section 8, item #13, marked infrastructure)
is blocked on -- the same situation Wave 2 was in before run_batch7.py's
campaigns/leads/campaign_engagement_events existed, Wave 4 before
run_batch8.py's fact_sales_activities, and Wave 5 before run_batch9.py's
territory dimension.

Batch number note: `lead_scoring_history` (Wave 7's other Phase 1 addition
on this branch) claims batches 10 and 11, so this module is numbered 12 --
the next free slot as of this write. This batch does not read, write, or
otherwise depend on anything the lead_scoring_history batch produces.

Design decision, stated once here and in full in generators/experiments.py:
this batch catalogs the one real, already-running randomized experiment in
this data -- the paid/community holdout program run_batch7.py's
marketing_funnel already generates -- rather than inventing a second,
parallel one. `docs/acme-corp-analytics-methods.md`'s "Marketing
attribution & channel mix" entry already independently validated that
program's incremental lift; this batch does not recompute it, only
registers the experiment and its real per-lead assignment. See
generators/experiments.py's module docstring for the full reasoning,
including the grep across docs/ and generators/ that confirmed no other
holdout/control-group mechanism exists in this data.

This batch adds no campaigns, no leads and no events -- it reads
campaigns.csv, leads.csv and campaign_engagement_events.csv and never
writes back to any of them, the same read-only-against-prior-batches shape
run_batch8.py and run_batch9.py use.

No randomness is drawn in this batch -- experiment_assignment is a
deterministic replay of the real first-touch-campaign assignment batch 7
already fixed (see experiments.py's _first_touch_campaign), and
experiments_registry restates already-validated, already-published
constants rather than sampling anything. There is therefore no
BATCH12_SEED: a seed would document randomness this batch does not have.
"""
import os

import pandas as pd

from .experiments import (
    ASSIGNMENT_COLUMNS,
    REGISTRY_COLUMNS,
    build_experiment_assignment,
    build_experiments_registry,
)

DATA_DIR = "data/raw"


def _load_prior_batches():
    campaigns = pd.read_csv(f"{DATA_DIR}/campaigns.csv", parse_dates=["start_date", "end_date"])
    leads = pd.read_csv(f"{DATA_DIR}/leads.csv", parse_dates=["created_date", "converted_date"])
    events = pd.read_csv(f"{DATA_DIR}/campaign_engagement_events.csv", parse_dates=["event_timestamp"])
    return campaigns, leads, events


def main():
    campaigns, leads, events = _load_prior_batches()

    registry = build_experiments_registry(campaigns)
    assignment = build_experiment_assignment(campaigns, leads, events)

    os.makedirs(DATA_DIR, exist_ok=True)
    registry[REGISTRY_COLUMNS].to_csv(f"{DATA_DIR}/experiments_registry.csv", index=False)
    assignment[ASSIGNMENT_COLUMNS].to_csv(f"{DATA_DIR}/experiment_assignment.csv", index=False)

    print("=== Batch 12 generated ===")
    print(f"experiments_registry:   {len(registry)} row(s)")
    print(f"experiment_assignment:  {len(assignment)} rows "
          f"({assignment['lead_id'].nunique()} distinct leads, "
          f"{assignment['first_touch_campaign_id'].nunique()} distinct sourcing campaigns)")

    # --- referential sanity --------------------------------------------------
    print("\n  sanity checks:")
    print(f"    every assignment.lead_id resolves to a real lead: "
          f"{set(assignment['lead_id']) <= set(leads['lead_id'])}")
    print(f"    every assignment.first_touch_campaign_id resolves to a real campaign: "
          f"{set(assignment['first_touch_campaign_id']) <= set(campaigns['campaign_id'])}")
    print(f"    every assignment.experiment_id resolves to a registry row: "
          f"{set(assignment['experiment_id']) <= set(registry['experiment_id'])}")
    converting_ids = set(leads.loc[leads['is_converted'], 'lead_id'])
    account_mismatch = assignment[
        assignment['lead_id'].isin(converting_ids) != assignment['account_id'].notna()
    ]
    print(f"    account_id is populated iff the lead converted: "
          f"{len(account_mismatch) == 0} ({len(account_mismatch)} mismatches)")

    # --- the real assignment this batch traces to, not fabricates ----------
    print("\n  build spec requirement -- assignment flags trace to the real is_holdout data:")
    campaign_holdout = dict(zip(campaigns["campaign_id"], campaigns["is_holdout"]))
    implied_arm = assignment["first_touch_campaign_id"].map(campaign_holdout).map(
        {True: "control", False: "treatment"})
    print(f"    assignment.arm matches campaigns.is_holdout of the first-touch campaign: "
          f"{(assignment['arm'] == implied_arm).all()}")

    by_arm = assignment.groupby("arm").size()
    print(f"    treatment: {int(by_arm.get('treatment', 0))}   control: {int(by_arm.get('control', 0))}")
    by_cell = assignment.groupby(["channel", "cell_quarter", "arm"]).size().unstack(fill_value=0)
    print("\n  cell composition (channel x quarter):")
    print(by_cell.to_string())

    # --- registry content sanity --------------------------------------------
    print("\n  registry content:")
    r = registry.iloc[0]
    print(f"    experiment_id:        {r['experiment_id']}")
    print(f"    result_metric:        {r['result_metric']} = {r['result_value']} "
          f"(z={r['result_z']}, significant={r['result_significant']})")
    print(f"    designed_effect_size: {r['designed_effect_size']}")
    print(f"    result_source cites analytics/marketing_attribution.py, not recomputed here: "
          f"{'marketing_attribution.py' in r['result_source']}")


if __name__ == "__main__":
    main()
