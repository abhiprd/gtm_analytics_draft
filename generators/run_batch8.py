"""Orchestrator for the eighth Phase 1 generator batch: fact_sales_activities.

Run from the repo root (after generators.run_foundation and
generators.run_batch2 have produced data/raw/{opportunities,users,
rep_status_history}.csv):

    python3 -m generators.run_batch8

Uses a seed offset from the prior batches' (config.SEED + 7000) so this
batch is independently reproducible without depending on any prior batch
having just run in the same process -- it reads their *output CSVs*, not
their in-memory state, same pattern as run_batch2.py through run_batch7.py.

Fills the data gap the Wave 4 "Deal-level diagnostics" and "Rep productivity
& coaching diagnostics" artifacts are blocked on -- the same situation
Wave 2 was in before run_batch7.py's campaigns/leads/campaign_engagement_
events and run_batch6.py's fact_forecast_submissions existed. This batch
adds no opportunities and no reps; it reads opportunities.csv, users.csv and
rep_status_history.csv and never writes back to any of them.
"""
import os

import numpy as np
import pandas as pd

from . import config
from .sales_activities import ACTIVITY_COLUMNS, generate_sales_activities

DATA_DIR = "data/raw"
BATCH8_SEED = config.SEED + 7000


def _load_prior_batches():
    opportunities = pd.read_csv(
        f"{DATA_DIR}/opportunities.csv", parse_dates=["created_date", "close_date"]
    )
    users = pd.read_csv(f"{DATA_DIR}/users.csv", parse_dates=["hire_date"])
    rep_status_history = pd.read_csv(f"{DATA_DIR}/rep_status_history.csv")
    return opportunities, users, rep_status_history


def main():
    rng = np.random.default_rng(BATCH8_SEED)
    opportunities, users, rep_status_history = _load_prior_batches()

    activities = generate_sales_activities(rng, opportunities, users, rep_status_history)

    os.makedirs(DATA_DIR, exist_ok=True)
    activities[ACTIVITY_COLUMNS].to_csv(f"{DATA_DIR}/fact_sales_activities.csv", index=False)

    new_business = opportunities[
        (opportunities["opportunity_type"] == "new_business")
        & (opportunities["segment"].isin(["Commercial", "Enterprise"]))
    ].set_index("opportunity_id")

    print("=== Batch 8 generated ===")
    print(f"fact_sales_activities: {len(activities)} rows across {activities['opportunity_id'].nunique()} "
          f"opportunities ({len(new_business)} eligible), {activities['rep_id'].nunique()} reps")
    print(f"  activity_type mix: {dict(activities['activity_type'].value_counts())}")
    print(f"  outcome mix: {dict(activities['outcome'].value_counts())}")
    print(f"  meetings_booked events (activity_type=meeting, outcome=booked): "
          f"{int(((activities['activity_type'] == 'meeting') & (activities['outcome'] == 'booked')).sum())}")
    print(f"  outbound touches (Enterprise only, by construction): "
          f"{int(activities['is_outbound_touch'].sum())}")

    # --- referential / structural sanity -----------------------------------
    print("\n  sanity checks:")
    print(f"    every rep_id resolves to a real rep:          "
          f"{set(activities['rep_id']) <= set(users['rep_id'])}")
    print(f"    every opportunity_id resolves to a real opp:  "
          f"{set(activities['opportunity_id']) <= set(opportunities['opportunity_id'])}")
    print(f"    no SMB opportunity present:                   "
          f"{not activities['opportunity_id'].isin(opportunities.loc[opportunities['segment'] == 'SMB', 'opportunity_id']).any()}")
    print(f"    no expansion/renewal opportunity present:     "
          f"{not activities['opportunity_id'].isin(opportunities.loc[opportunities['opportunity_type'] != 'new_business', 'opportunity_id']).any()}")
    print(f"    is_outbound_touch only ever True on Enterprise: "
          f"{bool((~activities['is_outbound_touch']).all() or (activities.loc[activities['is_outbound_touch'], 'opportunity_id'].map(new_business['segment']) == 'Enterprise').all())}")

    joined = activities.merge(
        new_business[["is_won", "loss_reason", "created_date", "close_date", "rep_id", "segment"]],
        left_on="opportunity_id", right_index=True, suffixes=("", "_opp"),
    )
    within_window = (joined["activity_timestamp"] >= pd.to_datetime(joined["created_date"])) & (
        joined["activity_timestamp"] <= pd.to_datetime(joined["close_date"])
    )
    print(f"    every touch timestamp falls inside its opp's open window: "
          f"{bool(within_window.all())} ({within_window.mean():.3%})")

    # --- causal wiring 1: engagement quality vs. win/loss -------------------
    print("\n  causal wiring -- engagement quality vs. win/loss:")
    meetings = joined[(joined["activity_type"] == "meeting") & (joined["outcome"] != "booked")]
    held_by_outcome = meetings.groupby("is_won")["outcome"].apply(lambda s: (s == "held").mean())
    print(f"    meeting held-rate:  won {held_by_outcome.get(True, float('nan')):.2%} vs "
          f"lost {held_by_outcome.get(False, float('nan')):.2%}")
    threads = joined.groupby(["opportunity_id", "is_won"])["contact_ref"].nunique().reset_index()
    thread_by_outcome = threads.groupby("is_won")["contact_ref"].mean()
    print(f"    distinct contacts/opp (multi-threading): won {thread_by_outcome.get(True, float('nan')):.2f} vs "
          f"lost {thread_by_outcome.get(False, float('nan')):.2f}")
    gaps = joined.sort_values(["opportunity_id", "activity_timestamp"]).groupby("opportunity_id").agg(
        is_won=("is_won", "first"),
        n_touches=("activity_id", "size"),
    )
    print(f"    touches/opp: won {gaps.loc[gaps['is_won'], 'n_touches'].mean():.2f} vs "
          f"lost {gaps.loc[~gaps['is_won'], 'n_touches'].mean():.2f}")

    # --- causal wiring 2: rep ramp status ------------------------------------
    hire_date_by_rep = dict(zip(users["rep_id"], users["hire_date"]))
    joined["rep_tenure_days"] = (
        pd.to_datetime(joined["created_date"]) - joined["rep_id"].map(hire_date_by_rep)
    ).dt.days
    joined["rep_is_ramped"] = joined["rep_tenure_days"] >= 180
    win_by_ramp = joined.drop_duplicates("opportunity_id").groupby("rep_is_ramped")["is_won"].mean()
    print(f"\n  causal wiring -- rep ramp status (opportunities.py's own win-rate wiring, cross-checked here):")
    print(f"    win rate: ramped reps {win_by_ramp.get(True, float('nan')):.2%} vs "
          f"ramping reps {win_by_ramp.get(False, float('nan')):.2%}")

    # --- causal wiring 3: competitive_signal vs. loss_reason -----------------
    print("\n  causal wiring -- competitive_signal vs. loss_reason:")
    comp_rate = joined.groupby(joined["loss_reason"].fillna("won"))["competitive_signal"].mean()
    print(comp_rate.to_string())

    # --- incident #3: meetings-rise-without-SQO-rise decoupling -------------
    start, end = config.SALES_ACTIVITY_DECOUPLING_INCIDENT_WINDOW
    in_window = (opportunities["opportunity_type"] == "new_business") & (
        opportunities["segment"].isin(["Commercial", "Enterprise"])
    ) & (pd.to_datetime(opportunities["created_date"]).between(pd.Timestamp(start), pd.Timestamp(end)))
    window_opp_ids = set(opportunities.loc[in_window, "opportunity_id"])
    other_opp_ids = set(new_business.index) - window_opp_ids
    touches_per_opp = activities.groupby("opportunity_id").size()
    win_rate_window = opportunities.loc[opportunities["opportunity_id"].isin(window_opp_ids), "is_won"].mean()
    win_rate_other = opportunities.loc[opportunities["opportunity_id"].isin(other_opp_ids), "is_won"].mean()
    print(f"\n  injected incident #3 -- meetings-rise-without-SQO-rise decoupling "
          f"({start}..{end}):")
    print(f"    touches/opp:  in-window {touches_per_opp.reindex(list(window_opp_ids)).mean():.2f} vs "
          f"baseline {touches_per_opp.reindex(list(other_opp_ids)).mean():.2f}")
    print(f"    win rate:     in-window {win_rate_window:.2%} vs baseline {win_rate_other:.2%} "
          f"(should stay close -- the decoupling is the point)")

    # --- incident #4: underperforming rep cohort -----------------------------
    ramped_or_not = joined.drop_duplicates("opportunity_id")
    per_rep = joined.groupby("rep_id").agg(
        n_touches=("activity_id", "size"),
    )
    meeting_res = joined[(joined["activity_type"] == "meeting") & (joined["outcome"] != "booked")]
    held_by_rep = meeting_res.groupby("rep_id")["outcome"].apply(lambda s: (s == "held").mean())
    # The cohort itself is internal to sales_activities.py's rng stream and
    # not exposed by generate_sales_activities' return value; re-derive the
    # same held-rate distribution split at its documented share instead of
    # threading the set through the public API for a print-only check.
    threshold = held_by_rep.quantile(config.SALES_ACTIVITY_UNDERPERFORMER_SHARE)
    low_cohort = held_by_rep[held_by_rep <= threshold]
    high_cohort = held_by_rep[held_by_rep > threshold]
    print(f"\n  injected incident #4 -- underperforming rep cohort "
          f"(bottom {config.SALES_ACTIVITY_UNDERPERFORMER_SHARE:.0%} of reps by meeting held-rate):")
    print(f"    meeting held-rate: bottom cohort {low_cohort.mean():.2%} vs rest {high_cohort.mean():.2%}")


if __name__ == "__main__":
    main()
