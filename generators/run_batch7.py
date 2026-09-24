"""Orchestrator for the seventh Phase 1 generator batch: campaigns, leads
and campaign_engagement_events.

Run from the repo root (after generators.run_foundation has produced
data/raw/{accounts,market_universe}.csv):

    python3 -m generators.run_batch7

Uses a seed offset from the prior batches' (config.SEED + 6000) so this
batch is independently reproducible without depending on any prior batch
having just run in the same process -- it reads their *output CSVs*, not
their in-memory state, same pattern as run_batch2.py through run_batch4.py.

Fills the data gap the Wave 2 "Marketing attribution & channel mix"
artifact is blocked on. The metric tree's "Pipeline generated" node is
defined as a sum over channels, decomposed into organic/content, paid, and
community/events with their own owners and Layer-3 diagnostics -- but the
only marketing data in the raw layer was channel-level monthly spend at the
coarse 3-value acquisition taxonomy, with no lead, campaign or touch record
under it. marketing.py's module docstring names this exact deferral.

This batch adds no accounts. Every converting lead is anchored to an
inbound-sourced account that already exists, so the funnel it describes is
the one that actually produced the account population -- accounts.csv is
read and never written.
"""
import os

import numpy as np
import pandas as pd

from . import config
from .marketing_funnel import (
    CAMPAIGN_COLUMNS,
    EVENT_COLUMNS,
    LEAD_COLUMNS,
    generate_campaign_engagement_events,
    generate_campaigns,
    generate_leads,
)

DATA_DIR = "data/raw"
BATCH7_SEED = config.SEED + 6000


def _load_prior_batches():
    accounts = pd.read_csv(f"{DATA_DIR}/accounts.csv", parse_dates=["signup_date"])
    accounts["signup_date"] = accounts["signup_date"].dt.date
    market_universe = pd.read_csv(f"{DATA_DIR}/market_universe.csv")
    return accounts, market_universe


def _rate(numerator, denominator):
    return numerator / denominator if denominator else float("nan")


def main():
    rng = np.random.default_rng(BATCH7_SEED)
    accounts, market_universe = _load_prior_batches()

    campaigns = generate_campaigns(rng, accounts)
    leads = generate_leads(rng, accounts, market_universe, campaigns)
    events = generate_campaign_engagement_events(rng, leads, campaigns)

    os.makedirs(DATA_DIR, exist_ok=True)
    campaigns[CAMPAIGN_COLUMNS].to_csv(f"{DATA_DIR}/campaigns.csv", index=False)
    leads[LEAD_COLUMNS].to_csv(f"{DATA_DIR}/leads.csv", index=False)
    events[EVENT_COLUMNS].to_csv(f"{DATA_DIR}/campaign_engagement_events.csv", index=False)

    inbound = accounts[accounts["channel"] == config.MARKETING_SUB_CHANNEL_PARENT]
    converted = leads[leads["is_converted"]]

    print("=== Batch 7 generated ===")
    print(f"campaigns:                  {len(campaigns)} rows "
          f"({int(campaigns['is_holdout'].sum())} holdout cells), "
          f"{campaigns['start_date'].min()} -> {campaigns['end_date'].max()}")
    print(f"leads:                      {len(leads)} rows "
          f"({len(converted)} converting, {len(leads) - len(converted)} not)")
    print(f"campaign_engagement_events: {len(events)} rows "
          f"({len(events) / len(leads):.2f} touches/lead, "
          f"{events['campaign_id'].nunique()} campaigns touched)")

    # --- the account population this batch exists to explain --------------
    print("\n  anchoring to the existing inbound account population:")
    print(f"    inbound_marketing accounts:                 {len(inbound)}")
    print(f"    converting leads:                           {len(converted)}")
    print(f"    exactly one converting lead per account:    "
          f"{len(converted) == len(inbound) and converted['account_id'].is_unique and set(converted['account_id']) == set(inbound['account_id'])}")
    gaps = (pd.to_datetime(converted["converted_date"]) - pd.to_datetime(converted["created_date"])).dt.days
    print(f"    lead created strictly before signup:        {bool((gaps >= 1).all())} "
          f"(gap min={gaps.min()}d median={gaps.median():.0f}d max={gaps.max()}d)")

    # --- causal wiring 1: touch volume predicts conversion ----------------
    touches = events.groupby("lead_id").size().rename("touches")
    joined = leads.merge(touches, left_on="lead_id", right_index=True, how="left")
    joined["touches"] = joined["touches"].fillna(0).astype(int)
    buckets = pd.cut(joined["touches"], [0, 1, 3, 6, 10, 10_000],
                     labels=["1", "2-3", "4-6", "7-10", "11+"])
    by_bucket = joined.groupby(buckets, observed=False)["is_converted"].agg(["mean", "size"])
    print("\n  causal wiring -- touch volume predicts conversion:")
    for bucket, row in by_bucket.iterrows():
        print(f"    {str(bucket):>6} touches   conversion {row['mean']:>7.2%}   n={int(row['size']):>6}")
    rates = by_bucket["mean"].to_numpy()
    print(f"    monotonically increasing across buckets:    {bool((np.diff(rates) > 0).all())}")

    # Recency, measured at a common horizon after lead creation: a
    # converting lead is still being touched when a non-converting one has
    # long gone quiet.
    last_touch = events.groupby("lead_id")["event_timestamp"].max()
    recency = leads.merge(last_touch.rename("last_touch"), left_on="lead_id", right_index=True, how="left")
    recency["days_to_last_touch"] = (
        recency["last_touch"] - pd.to_datetime(recency["created_date"])).dt.days
    med = recency.groupby("is_converted")["days_to_last_touch"].median()
    print(f"    median days lead-creation -> last touch:    "
          f"converting {med.get(True, float('nan')):.0f}d vs non-converting {med.get(False, float('nan')):.0f}d")

    # --- causal wiring 2: the three sub-channels are genuinely distinct ---
    print("\n  QA plan Test C -- organic / paid / community distinctness:")
    spend_by_channel = campaigns.groupby("channel")["budget"].sum()
    print(f"    {'channel':<11} {'leads':>7} {'conv':>6} {'conv rate':>10} "
          f"{'touches/lead':>13} {'gap(d)':>8} {'CAC':>9} {'lead score':>11}")
    for channel in config.MARKETING_SUB_CHANNELS:
        sub = joined[joined["channel"] == channel]
        sub_conv = sub[sub["is_converted"]]
        gap = (pd.to_datetime(sub_conv["converted_date"]) - pd.to_datetime(sub_conv["created_date"])).dt.days
        cac = _rate(spend_by_channel.get(channel, 0.0), len(sub_conv))
        print(f"    {channel:<11} {len(sub):>7} {len(sub_conv):>6} {sub['is_converted'].mean():>9.2%} "
              f"{sub['touches'].mean():>13.2f} {gap.median():>8.0f} ${cac:>8,.0f} "
              f"{sub['lead_score'].mean():>11.1f}")

    # --- edge case: the holdout group exists and is genuinely suppressed --
    holdout_ids = set(campaigns.loc[campaigns["is_holdout"], "campaign_id"])
    first_touch = (events.sort_values("event_timestamp", kind="mergesort")
                         .groupby("lead_id", as_index=False).first()[["lead_id", "campaign_id"]])
    tagged = joined.merge(first_touch, on="lead_id", how="left")
    tagged["in_holdout"] = tagged["campaign_id"].isin(holdout_ids)

    holdout_quarters = set(config.HOLDOUT_QUARTERS)
    created = pd.to_datetime(tagged["created_date"])
    comparable = tagged[
        tagged["channel"].isin(config.HOLDOUT_CHANNELS)
        & (created.dt.year.astype(str) + "Q" + created.dt.quarter.astype(str)).isin(holdout_quarters)
    ]
    treated = comparable[~comparable["in_holdout"]]
    control = comparable[comparable["in_holdout"]]
    print("\n  build spec incrementality requirement -- holdout cells:")
    print(f"    holdout campaigns:                          {len(holdout_ids)} "
          f"across {sorted(holdout_quarters)} in {list(config.HOLDOUT_CHANNELS)}")
    print(f"    leads in holdout cells:                     {len(control)}")
    print(f"    conversion rate treated vs control:         "
          f"{treated['is_converted'].mean():.2%} vs {control['is_converted'].mean():.2%}")
    print(f"    touches/lead treated vs control:            "
          f"{treated['touches'].mean():.2f} vs {control['touches'].mean():.2f}")
    lift = _rate(treated["is_converted"].mean() - control["is_converted"].mean(),
                 treated["is_converted"].mean())
    print(f"    implied incremental lift:                   {lift:.1%}")

    # --- structural sanity ------------------------------------------------
    # The formal suite is tests/test_phase1_batch7.py; these are the
    # build-time signals.
    ev = events.merge(leads[["lead_id", "converted_date"]], on="lead_id", how="left")
    post_conversion = ev["converted_date"].notna() & (
        ev["event_timestamp"] >= pd.to_datetime(ev["converted_date"]))
    campaign_windows = campaigns.set_index("campaign_id")[["start_date", "end_date", "channel"]]
    ev2 = events.join(campaign_windows, on="campaign_id", rsuffix="_c")
    outside = (ev2["event_timestamp"].dt.normalize() < pd.to_datetime(ev2["start_date"])) | (
        ev2["event_timestamp"].dt.normalize() > pd.to_datetime(ev2["end_date"]))
    print("\n  sanity checks:")
    print(f"    no lead references a missing campaign:      "
          f"{set(first_touch['campaign_id']) <= set(campaigns['campaign_id'])}")
    print(f"    no event references a missing lead:         "
          f"{set(events['lead_id']) <= set(leads['lead_id'])}")
    print(f"    no event references a missing campaign:     "
          f"{set(events['campaign_id']) <= set(campaigns['campaign_id'])}")
    print(f"    no touch on or after its conversion date:   {not bool(post_conversion.any())}")
    print(f"    every touch inside its campaign's window:   {not bool(outside.any())}")
    print(f"    every event channel matches its campaign:   "
          f"{bool((ev2['channel'] == ev2['channel_c']).all())}")
    print(f"    every lead has at least one touch:          "
          f"{joined['touches'].min() >= 1}")
    print(f"    no nulls outside the nullable lead columns: "
          f"{not leads[LEAD_COLUMNS].drop(columns=['account_id', 'converted_date']).isna().any().any()}")
    lead_channel = leads.set_index("lead_id")["channel"]
    cross_channel = (events["channel"].to_numpy() != events["lead_id"].map(lead_channel).to_numpy())
    multi_campaign_leads = events.groupby("lead_id")["campaign_id"].nunique()
    print(f"    cross-channel touches (MTA has a path):     "
          f"{int(cross_channel.sum())} ({cross_channel.mean():.1%} of touches)")
    print(f"    leads touched by >1 campaign:               "
          f"{int((multi_campaign_leads > 1).sum())} "
          f"({(multi_campaign_leads > 1).mean():.1%} of leads)")


if __name__ == "__main__":
    main()
