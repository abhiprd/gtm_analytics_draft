"""Orchestrator for the fifth Phase 1 generator batch: gtm_plan_targets.

Run from the repo root:

    python3 -m generators.run_batch5

Uses a seed offset from the prior batches' (config.SEED + 4000) so this batch
is independently reproducible.

This is a new batch rather than an extension of batch 4 because it is a new
simulated source system: FP&A/RevOps plan values, not a product or CRM
telemetry feed. It also has no input dependency at all -- unlike every prior
batch, it loads no CSV, because a plan is set before its period and must not
be a function of what that period turned out to produce. That absence is the
point-in-time guarantee the Phase 4 variance-diagnostic engine relies on, and
it is enforced structurally here: there is no _load_prior_batches() to call.

Fills the last Wave-1-blocking gap. The build spec's Phase 4 requires
"for any Layer-1 metric, compute variance from plan," and the leadership
readout's Layer-1 scorecard reports every metric against plan -- but no table
in the raw layer carried a plan figure, so variance from plan had nothing to
compare against.
"""
import os

import numpy as np
import pandas as pd

from . import config
from .gtm_plan import generate_gtm_plan_targets, plan_anchors

DATA_DIR = "data/raw"
BATCH5_SEED = config.SEED + 4000

# Units per metric, for the summary only -- the stored column is a bare
# number, and the module docstring is the reference for what it means.
UNIT_LABEL = {
    "new_logo_consumption_revenue": "USD/mo",
    "expansion_consumption_revenue": "USD/mo",
    "contraction_churned_revenue": "USD/mo",
    "magic_number": "x",
    "consumption_payback": "months",
    "onboarding_cs_efficiency": "touches/Action",
    "am_efficiency": "x",
    "nrr": "decimal, annual-equiv",
    "grr": "decimal, annual-equiv",
    "logo_retention": "decimal, annual-equiv",
}


def main():
    rng = np.random.default_rng(BATCH5_SEED)
    plan_df = generate_gtm_plan_targets(rng)

    os.makedirs(DATA_DIR, exist_ok=True)
    plan_df.to_csv(f"{DATA_DIR}/gtm_plan_targets.csv", index=False)

    expected_rows = len(config.PLAN_LAYER1_METRICS) * config.N_MONTHS
    print("=== Batch 5 generated ===")
    print(f"gtm_plan_targets: {len(plan_df)} rows "
          f"({plan_df['layer1_metric'].nunique()} metrics x {plan_df['month'].nunique()} months)")

    anchors = plan_anchors()
    months = pd.to_datetime(plan_df["month"])
    print("\n  plan value range by metric (2023 anchor -> escalation rate):")
    for pillar in ("Growth", "Efficiency", "Durability"):
        print(f"    -- {pillar} --")
        for metric in config.PLAN_LAYER1_METRICS:
            if config.PLAN_PILLAR_BY_METRIC[metric] != pillar:
                continue
            values = plan_df.loc[plan_df["layer1_metric"] == metric, "plan_value"]
            anchor, change = anchors[metric]
            print(f"      {metric:<32} min={values.min():<14.6g} max={values.max():<14.6g} "
                  f"anchor={anchor:<12.6g} {change:+.1%}/yr  [{UNIT_LABEL[metric]}]")

    # Structural sanity checks -- the formal suite is
    # tests/test_phase1_batch5.py; these are the build-time signals.
    print("\n  sanity checks:")
    print(f"    row count == {expected_rows}: "
          f"{len(plan_df) == expected_rows}")
    print(f"    metric set is the expected closed set: "
          f"{set(plan_df['layer1_metric']) == set(config.PLAN_LAYER1_METRICS)}")
    print(f"    no duplicate (metric, month) pairs: "
          f"{not plan_df.duplicated(['layer1_metric', 'month']).any()}")
    print(f"    no nulls: {not plan_df.isna().any().any()}")

    expected_months = set(pd.date_range(config.SIM_START, periods=config.N_MONTHS, freq="MS"))
    gaps = {
        metric: sorted(expected_months - set(months[plan_df["layer1_metric"] == metric]))
        for metric in config.PLAN_LAYER1_METRICS
    }
    missing = {metric: gap for metric, gap in gaps.items() if gap}
    print(f"    all {config.N_MONTHS} months present for every metric, no gaps: {not missing}")
    if missing:
        print(f"      MISSING: {missing}")
    print(f"    window: {months.min().date()} -> {months.max().date()}")


if __name__ == "__main__":
    main()
