"""Orchestrator for the sixth Phase 1 generator batch: the forecasting
source system -- fact_forecast_submissions and cro_forecast_adjustments.

Run from the repo root (after generators.run_foundation and
generators.run_batch2 have produced data/raw/{opportunities,
opportunity_stage_history,users,usage_monthly}.csv):

    python3 -m generators.run_batch6

Uses a seed offset from the prior batches' (config.SEED + 5000) so this
batch is independently reproducible without depending on any prior batch
having just run in the same process -- it reads their *output CSVs*, not
their in-memory state, same pattern as run_batch2.py through run_batch4.py.

Fills the Wave-2 data gap the Forecast artifact sits on. Build spec
Section 8 lists Forecast as "sales bottoms-up + ML/regression + CRO
overlay," but the raw layer carried no bottoms-up submission history and
no logged overlay -- `opportunities.forecast_category` is a single
close-time field, not the weekly snapshot series the build spec's
Forecasting bullet specifies, and nothing recorded the CRO's top-down
adjustment at all.
"""
import os

import numpy as np
import pandas as pd

from . import config
from .forecast import (
    CRO_ADJUSTMENT_REASONS,
    FORECAST_CATEGORIES,
    generate_cro_forecast_adjustments,
    generate_forecast_submissions,
)

DATA_DIR = "data/raw"
BATCH6_SEED = config.SEED + 5000

_RANK = {name: i for i, name in enumerate(FORECAST_CATEGORIES)}


def _load_prior_batches():
    opportunities = pd.read_csv(
        f"{DATA_DIR}/opportunities.csv", parse_dates=["created_date", "close_date"]
    )
    stage_history = pd.read_csv(
        f"{DATA_DIR}/opportunity_stage_history.csv", parse_dates=["entered_date"]
    )
    reps = pd.read_csv(f"{DATA_DIR}/users.csv", parse_dates=["hire_date"])
    usage_monthly = pd.read_csv(f"{DATA_DIR}/usage_monthly.csv", parse_dates=["month"])
    return opportunities, stage_history, reps, usage_monthly


def _final_call_per_opportunity(submissions: pd.DataFrame) -> pd.DataFrame:
    """The last forecast call filed on each opportunity before it closed --
    the submission a bottoms-up forecast for that period would actually
    have been built on."""
    ordered = submissions.sort_values(["opportunity_id", "snapshot_date"])
    return ordered.groupby("opportunity_id", as_index=False).last()


def _win_rate_gap(submissions: pd.DataFrame, opportunities: pd.DataFrame, subset=None):
    """Win rate where the manager downgraded a confident rep call, against
    win rate where the two agreed on a confident call.

    Both groups are conditioned on the same confident rep call (Commit or
    Best Case), so the comparison isolates the manager's disagreement
    rather than picking up the difference between a confident deal and a
    written-off one.
    """
    final = _final_call_per_opportunity(submissions).merge(
        opportunities[["opportunity_id", "segment", "opportunity_type", "is_won"]],
        on="opportunity_id", how="inner",
    )
    if subset is not None:
        final = final[subset(final)]
    rep_rank = final["rep_forecast_category"].map(_RANK)
    manager_rank = final["manager_forecast_category"].map(_RANK)
    confident = rep_rank >= _RANK["Best Case"]

    downgraded = final[confident & (manager_rank < rep_rank)]
    agreed = final[confident & (manager_rank == rep_rank)]
    if len(downgraded) == 0 or len(agreed) == 0:
        return None
    return {
        "n_downgraded": len(downgraded),
        "win_downgraded": downgraded["is_won"].mean(),
        "n_agreed": len(agreed),
        "win_agreed": agreed["is_won"].mean(),
    }


def _print_gap(label, gap):
    if gap is None:
        print(f"    {label:<34} (no comparable population)")
        return
    delta = gap["win_agreed"] - gap["win_downgraded"]
    print(f"    {label:<34} downgraded {gap['win_downgraded']:.1%} (n={gap['n_downgraded']:>4})  "
          f"vs agreed {gap['win_agreed']:.1%} (n={gap['n_agreed']:>4})  "
          f"gap {delta:+.1%}  {'PASS' if delta > 0 else 'FAIL'}")


def main():
    rng = np.random.default_rng(BATCH6_SEED)
    opportunities, stage_history, reps, usage_monthly = _load_prior_batches()

    submissions = generate_forecast_submissions(
        rng, opportunities, stage_history, reps, usage_monthly
    )
    adjustments = generate_cro_forecast_adjustments(rng, opportunities, submissions)

    os.makedirs(DATA_DIR, exist_ok=True)
    submissions.to_csv(f"{DATA_DIR}/fact_forecast_submissions.csv", index=False)
    adjustments.to_csv(f"{DATA_DIR}/cro_forecast_adjustments.csv", index=False)

    in_scope = opportunities[opportunities["segment"].isin(["Commercial", "Enterprise"])]
    print("=== Batch 6 generated ===")
    print(f"fact_forecast_submissions: {len(submissions)} rows across "
          f"{submissions['opportunity_id'].nunique()} opportunities "
          f"(of {len(in_scope)} Commercial/Enterprise opportunities)")
    print(f"  snapshot window: {submissions['snapshot_date'].min()} -> {submissions['snapshot_date'].max()}")
    per_opp = submissions.groupby("opportunity_id").size()
    print(f"  calls/opportunity: mean={per_opp.mean():.1f}, median={per_opp.median():.0f}, max={per_opp.max()}")

    print("\n  forecast category mix (all calls):")
    for column in ("rep_forecast_category", "manager_forecast_category"):
        mix = submissions[column].value_counts(normalize=True)
        rendered = "  ".join(f"{name} {mix.get(name, 0.0):.1%}" for name in reversed(FORECAST_CATEGORIES))
        print(f"    {column:<28} {rendered}")

    rep_rank = submissions["rep_forecast_category"].map(_RANK)
    manager_rank = submissions["manager_forecast_category"].map(_RANK)
    print(f"    rep above manager: {(rep_rank > manager_rank).mean():.1%}   "
          f"agree: {(rep_rank == manager_rank).mean():.1%}   "
          f"manager above rep: {(manager_rank > rep_rank).mean():.1%}")

    # The check this batch exists to satisfy: the build spec's stated
    # signal, that the rep/manager gap carries information about the
    # outcome. The formal assertion lives in tests/test_phase1_batch6.py;
    # this is the build-time signal.
    print("\n  correlational check -- manager downgrade of a confident rep call vs. actual outcome:")
    _print_gap("all Commercial/Enterprise", _win_rate_gap(submissions, opportunities))
    _print_gap("new_business only", _win_rate_gap(
        submissions, opportunities, lambda f: f["opportunity_type"] == "new_business"))
    _print_gap("renewal + expansion only", _win_rate_gap(
        submissions, opportunities, lambda f: f["opportunity_type"] != "new_business"))
    for segment in ("Commercial", "Enterprise"):
        _print_gap(f"{segment} new_business", _win_rate_gap(
            submissions, opportunities,
            lambda f, s=segment: (f["segment"] == s) & (f["opportunity_type"] == "new_business")))

    print("\n  structural sanity checks:")
    print(f"    no SMB opportunities present: "
          f"{not submissions['opportunity_id'].isin(opportunities.loc[opportunities['segment'] == 'SMB', 'opportunity_id']).any()}")
    print(f"    every opportunity_id resolves: "
          f"{submissions['opportunity_id'].isin(opportunities['opportunity_id']).all()}")
    print(f"    no duplicate (opportunity_id, snapshot_date): "
          f"{not submissions.duplicated(['opportunity_id', 'snapshot_date']).any()}")
    window_start = pd.Timestamp(config.SIM_START)
    window_end = window_start + pd.DateOffset(months=config.N_MONTHS)
    grid = pd.date_range(window_start, window_end - pd.Timedelta(days=1), freq="W-FRI")
    expected = in_scope[[
        grid.searchsorted(close, "left") > grid.searchsorted(created, "left")
        for created, close in zip(in_scope["created_date"], in_scope["close_date"])
    ]]
    print(f"    every opportunity open on at least one in-window call date has calls: "
          f"{submissions['opportunity_id'].nunique() == len(expected)} "
          f"({submissions['opportunity_id'].nunique()} of {len(expected)}; "
          f"{len(in_scope) - len(expected)} opportunities never open on a call date)")
    windows = submissions.merge(
        opportunities[["opportunity_id", "created_date", "close_date"]], on="opportunity_id"
    )
    snapshot_ts = pd.to_datetime(windows["snapshot_date"])
    print(f"    every snapshot_date inside its opportunity's open window: "
          f"{bool(((snapshot_ts >= windows['created_date']) & (snapshot_ts < windows['close_date'])).all())}")
    print(f"    every snapshot_date is a Friday: "
          f"{bool((snapshot_ts.dt.weekday == 4).all())}")

    print(f"\ncro_forecast_adjustments: {len(adjustments)} rows across "
          f"{adjustments['period'].nunique()} quarters x {adjustments['segment'].nunique()} segments")
    print(f"  adjustment magnitude: min={adjustments['adjustment_amount'].min():,.0f}  "
          f"max={adjustments['adjustment_amount'].max():,.0f}  "
          f"negative share={(adjustments['adjustment_amount'] < 0).mean():.1%}")
    print("  reason mix:")
    counts = adjustments["reason"].value_counts()
    for reason in CRO_ADJUSTMENT_REASONS:
        n = int(counts.get(reason, 0))
        sign = adjustments.loc[adjustments["reason"] == reason, "adjustment_amount"]
        direction = "negative" if (len(sign) and (sign < 0).all()) else ("positive" if len(sign) else "-")
        print(f"    {reason:<30} {n:>3} rows  ({direction})")
    print(f"    all four reasons occur: {set(counts.index) == set(CRO_ADJUSTMENT_REASONS)}")


if __name__ == "__main__":
    main()
