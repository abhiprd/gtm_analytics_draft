"""Segment migration analysis -- grain: one row per migration event
(SMB->Commercial or Commercial->Enterprise, no skip-level migration);
source marts: mart_segment_migration (event detail), mart_durability
(segment population denominators for rate calculations), and
mart_growth_bridge (already-reconciled migration_in_mrr/migration_out_mrr,
used here only as a cross-check, not a competing computation).

This module is structural/descriptive, not a predictive model -- see
"Model type selection and rationale" in docs/acme-corp-analytics-
methods.md's Segment migration entry for why. In short: SMB->Commercial
and Commercial->Enterprise migration in this data is generated from a
known deterministic rule (usage/spend crossing a threshold for 2
consecutive months, with noise) plus an exogenous firmographic re-score
event -- a classifier trained to "predict" migration would mostly be
re-deriving the generator's own threshold rule, the same trivial-accuracy
failure mode the account health score's calibration note (see
analytics/health_score.py) explicitly guards against for churn scoring.
A genuinely predictive segmentation/scoring model is its own, later,
separate artifact (build spec item #11, "Lead/segmentation scoring --
model validation & drift detection", Wave 7, still TBD) -- not duplicated
here.

No stochastic step lives in this module (no train/test split, no
sampling, no simulation) -- every function is a direct, deterministic
aggregation over already-generated mart data, so there is nothing here
that needs a random seed.
"""
import os
from datetime import date

import duckdb
import numpy as np
import pandas as pd

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_MODEL_NAME = "segment_migration_analysis"

# Segment pairs this data ever contains -- no skip-level migration exists
# (build spec Section 1), so these two adjacent pairs are exhaustive.
_SEGMENT_PAIRS = [("SMB", "Commercial"), ("Commercial", "Enterprise")]

# Proposed, not yet confirmed (see docs/acme-corp-analytics-methods.md's
# Segment migration entry) -- floor share of migrations attributable to
# firmographic_rescore, both overall and within each segment pair. QA plan
# ("Segment & migration" section) requires firmographic_rescore migrations
# to fire "at non-trivial frequency, not just as a schema value that never
# occurs" but gives no number. 10% is proposed as a floor that is
# unambiguously non-trivial (materially above 0%, evidence the trigger
# path actually fires under realistic generator conditions) while leaving
# comfortable headroom below the ~29-41% observed at build time for
# ordinary period-to-period variation before a real regression would trip
# it.
_MIN_FIRMOGRAPHIC_RESCORE_SHARE = 0.10

# Reconciliation tolerance between this module's graduated-revenue sums
# and mart_growth_bridge's migration_in_mrr/migration_out_mrr -- both are
# derived from the same int_revenue_movements rows, so any gap beyond
# ordinary floating-point noise indicates a real bug, not statistical
# drift.
_RECONCILIATION_TOLERANCE_USD = 0.01

_DEFAULT_WINDOW_MONTHS = 12


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


def load_migration_events(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per migration event, migration_date <= as_of_date --
    no leakage from the future. Source mart: mart_segment_migration."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select * from main_marts.mart_segment_migration where migration_date <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["migration_date"] = pd.to_datetime(df["migration_date"])
    return df


def load_segment_population(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per segment per month, month <= as_of_date. Source
    mart: mart_durability -- starting_accounts is this module's population
    denominator for migration-rate calculations."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select segment, month, starting_accounts, starting_mrr "
            "from main_marts.mart_durability where month <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    return df


def load_growth_bridge_migration(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per segment per month, month <= as_of_date. Source
    mart: mart_growth_bridge -- migration_in_mrr/migration_out_mrr, read
    here only as an independent cross-check on this module's own
    graduated-revenue sums, never recomputed as a competing definition."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select segment, month, migration_in_mrr, migration_out_mrr "
            "from main_marts.mart_growth_bridge where month <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    return df


def _trailing_window(as_of_date: date, window_months: int) -> tuple:
    as_of_ts = pd.Timestamp(as_of_date)
    window_start = as_of_ts - pd.DateOffset(months=window_months)
    return window_start, as_of_ts


def compute_migration_velocity(as_of_date: date, window_months: int = _DEFAULT_WINDOW_MONTHS,
                                con=None) -> pd.DataFrame:
    """Migration velocity by segment pair: event count and rate (events /
    avg. trailing starting_accounts of the FROM segment) over the trailing
    window_months ending at as_of_date. Grain: one row per segment pair.
    Source marts: mart_segment_migration (events), mart_durability
    (population denominator)."""
    owns_con = con is None
    con = con or _connect()
    try:
        events = load_migration_events(as_of_date, con=con)
        population = load_segment_population(as_of_date, con=con)
    finally:
        if owns_con:
            con.close()

    window_start, window_end = _trailing_window(as_of_date, window_months)
    events_w = events[(events["migration_date"] > window_start) & (events["migration_date"] <= window_end)]
    population_w = population[(population["month"] > window_start) & (population["month"] <= window_end)]
    avg_starting_accounts = population_w.groupby("segment")["starting_accounts"].mean()

    rows = []
    for from_segment, to_segment in _SEGMENT_PAIRS:
        event_count = int(
            ((events_w["from_segment"] == from_segment) & (events_w["to_segment"] == to_segment)).sum()
        )
        avg_population = float(avg_starting_accounts.get(from_segment, np.nan))
        rate = event_count / avg_population if avg_population and avg_population > 0 else np.nan
        rows.append({
            "from_segment": from_segment,
            "to_segment": to_segment,
            "window_start": window_start,
            "window_end": window_end,
            "event_count": event_count,
            "avg_from_segment_starting_accounts": avg_population,
            "migration_rate": rate,
        })
    return pd.DataFrame(rows)


def compute_trigger_reason_mix(as_of_date: date, con=None) -> pd.DataFrame:
    """Trigger-reason mix (usage_threshold vs. firmographic_rescore) as a
    share of all-time-to-date migrations, both overall and by segment
    pair. Grain: one row per segment pair (plus one 'All' row) per
    trigger_reason. Source mart: mart_segment_migration."""
    events = load_migration_events(as_of_date, con=con)

    def _mix(df: pd.DataFrame, from_segment: str, to_segment: str) -> list:
        total = len(df)
        counts = df["trigger_reason"].value_counts()
        return [
            {
                "from_segment": from_segment,
                "to_segment": to_segment,
                "trigger_reason": reason,
                "count": int(counts.get(reason, 0)),
                "total_migrations": total,
                "share": (counts.get(reason, 0) / total) if total else np.nan,
            }
            for reason in ["usage_threshold", "firmographic_rescore"]
        ]

    rows = _mix(events, "All", "All")
    for from_segment, to_segment in _SEGMENT_PAIRS:
        pair_df = events[(events["from_segment"] == from_segment) & (events["to_segment"] == to_segment)]
        rows += _mix(pair_df, from_segment, to_segment)
    return pd.DataFrame(rows)


def compute_time_in_prior_segment_distribution(as_of_date: date, con=None) -> pd.DataFrame:
    """Distribution of days_in_prior_segment by segment pair and
    trigger_reason, all-time-to-date (no leakage: only migrations with
    migration_date <= as_of_date are included). Grain: one row per
    (segment pair, trigger_reason). Source mart: mart_segment_migration."""
    events = load_migration_events(as_of_date, con=con)
    rows = []
    for from_segment, to_segment in _SEGMENT_PAIRS:
        pair_df = events[(events["from_segment"] == from_segment) & (events["to_segment"] == to_segment)]
        for reason in ["usage_threshold", "firmographic_rescore"]:
            sub = pair_df.loc[pair_df["trigger_reason"] == reason, "days_in_prior_segment"]
            rows.append({
                "from_segment": from_segment,
                "to_segment": to_segment,
                "trigger_reason": reason,
                "n": int(sub.shape[0]),
                "mean_days": float(sub.mean()) if len(sub) else np.nan,
                "median_days": float(sub.median()) if len(sub) else np.nan,
                "p25_days": float(sub.quantile(0.25)) if len(sub) else np.nan,
                "p75_days": float(sub.quantile(0.75)) if len(sub) else np.nan,
                "min_days": float(sub.min()) if len(sub) else np.nan,
                "max_days": float(sub.max()) if len(sub) else np.nan,
            })
    return pd.DataFrame(rows)


def compute_graduated_revenue(as_of_date: date, window_months: int = _DEFAULT_WINDOW_MONTHS,
                               con=None) -> pd.DataFrame:
    """'Graduated revenue' -- MRR reclassified out of the source segment
    via migration (build spec: excluded from the source segment's own
    churn/contraction, reported separately) -- summed by segment pair and
    trigger_reason over the trailing window_months ending at as_of_date.
    Grain: one row per segment pair (plus one 'All' row) per
    trigger_reason. Source mart: mart_segment_migration."""
    events = load_migration_events(as_of_date, con=con)
    window_start, window_end = _trailing_window(as_of_date, window_months)
    events_w = events[(events["migration_date"] > window_start) & (events["migration_date"] <= window_end)]

    def _agg(df: pd.DataFrame, from_segment: str, to_segment: str) -> list:
        rows = []
        for reason in ["usage_threshold", "firmographic_rescore"]:
            sub = df.loc[df["trigger_reason"] == reason, "mrr_reclassified"]
            rows.append({
                "from_segment": from_segment,
                "to_segment": to_segment,
                "trigger_reason": reason,
                "window_start": window_start,
                "window_end": window_end,
                "n": int(sub.shape[0]),
                "graduated_revenue_mrr": float(sub.sum()) if len(sub) else 0.0,
            })
        return rows

    rows = _agg(events_w, "All", "All")
    for from_segment, to_segment in _SEGMENT_PAIRS:
        pair_df = events_w[(events_w["from_segment"] == from_segment) & (events_w["to_segment"] == to_segment)]
        rows += _agg(pair_df, from_segment, to_segment)
    return pd.DataFrame(rows)


def reconcile_graduated_revenue_to_growth_bridge(as_of_date: date, con=None) -> dict:
    """Cross-checks this module's own mrr_reclassified sums (grouped by
    to_segment/month for migration-in, from_segment/month for
    migration-out) against mart_growth_bridge's independently-materialized
    migration_in_mrr/migration_out_mrr for the same segment/month -- both
    are derived from the same int_revenue_movements rows upstream, so any
    gap beyond floating-point noise (_RECONCILIATION_TOLERANCE_USD) is a
    real bug, not a modeling choice or statistical drift. Grain of the
    comparison: one row per segment per month; this function returns a
    scalar summary (max absolute diff, pass/fail), not the row-level
    detail. Source marts: mart_segment_migration, mart_growth_bridge."""
    events = load_migration_events(as_of_date, con=con)
    bridge = load_growth_bridge_migration(as_of_date, con=con)

    migration_in_calc = (
        events.groupby(["to_segment", "migration_date"])["mrr_reclassified"].sum()
        .rename("migration_in_calc").reset_index()
        .rename(columns={"to_segment": "segment", "migration_date": "month"})
    )
    migration_out_calc = (
        events.groupby(["from_segment", "migration_date"])["mrr_reclassified"].sum()
        .rename("migration_out_calc").reset_index()
        .rename(columns={"from_segment": "segment", "migration_date": "month"})
    )

    in_merged = bridge.merge(migration_in_calc, on=["segment", "month"], how="outer")
    in_merged["migration_in_mrr"] = in_merged["migration_in_mrr"].fillna(0)
    in_merged["migration_in_calc"] = in_merged["migration_in_calc"].fillna(0)
    in_diff = (in_merged["migration_in_mrr"] - in_merged["migration_in_calc"]).abs()

    out_merged = bridge.merge(migration_out_calc, on=["segment", "month"], how="outer")
    out_merged["migration_out_mrr"] = out_merged["migration_out_mrr"].fillna(0)
    out_merged["migration_out_calc"] = out_merged["migration_out_calc"].fillna(0)
    out_diff = (out_merged["migration_out_mrr"] - out_merged["migration_out_calc"]).abs()

    max_abs_diff = float(max(in_diff.max() if len(in_diff) else 0.0, out_diff.max() if len(out_diff) else 0.0))
    return {
        "max_abs_diff_usd": max_abs_diff,
        "tolerance_usd": _RECONCILIATION_TOLERANCE_USD,
        "reconciles": max_abs_diff <= _RECONCILIATION_TOLERANCE_USD,
    }


def check_trigger_reason_diversity(as_of_date: date, con=None,
                                    min_share: float = _MIN_FIRMOGRAPHIC_RESCORE_SHARE) -> dict:
    """QA plan existence check (Segment & migration section / Test E
    analog): firmographic_rescore migrations must actually fire at
    non-trivial frequency, both overall and within each segment pair --
    not just exist as an unused schema value alongside usage_threshold.
    Compares the observed firmographic_rescore share against the proposed
    _MIN_FIRMOGRAPHIC_RESCORE_SHARE floor (see module-level comment; marked
    proposed, not yet confirmed, in docs/acme-corp-analytics-methods.md).
    Grain: one row per segment pair (plus one 'All' row)."""
    mix = compute_trigger_reason_mix(as_of_date, con=con)
    rescore = mix[mix["trigger_reason"] == "firmographic_rescore"].copy()
    rescore["passes_floor"] = rescore["share"] >= min_share
    return {
        "min_share_floor": min_share,
        "detail": rescore[["from_segment", "to_segment", "count", "total_migrations", "share", "passes_floor"]],
        "all_pairs_pass": bool(rescore["passes_floor"].all()),
    }


def run_build_time_validation(as_of_date: date, window_months: int = _DEFAULT_WINDOW_MONTHS,
                               log: bool = True) -> dict:
    """End-to-end build-time computation: migration velocity, trigger-
    reason mix, time-in-prior-segment distribution, graduated revenue, the
    growth-bridge reconciliation check, and the trigger-reason-diversity
    existence check -- everything analytics-model-validator needs to
    independently recompute this artifact's correctness claims. Logs the
    natural scalar time-series metrics to fact_model_performance_history
    (via analytics/model_performance.py) when log=True; the full
    coefficient-equivalent tables (mix, distribution, graduated revenue
    detail) are NOT logged there -- see docs/acme-corp-analytics-
    methods.md's Persistence note -- they are recorded as structured
    detail in the methods doc instead."""
    con = _connect()
    try:
        events = load_migration_events(as_of_date, con=con)
        velocity = compute_migration_velocity(as_of_date, window_months=window_months, con=con)
        trigger_mix = compute_trigger_reason_mix(as_of_date, con=con)
        time_in_segment = compute_time_in_prior_segment_distribution(as_of_date, con=con)
        graduated_revenue = compute_graduated_revenue(as_of_date, window_months=window_months, con=con)
        reconciliation = reconcile_graduated_revenue_to_growth_bridge(as_of_date, con=con)
        diversity = check_trigger_reason_diversity(as_of_date, con=con)
    finally:
        con.close()

    if log:
        for _, row in velocity.iterrows():
            pair_key = f"{row['from_segment'].lower()}_to_{row['to_segment'].lower()}"
            log_performance(_MODEL_NAME, as_of_date, f"migration_count_{pair_key}", float(row["event_count"]))
            if pd.notna(row["migration_rate"]):
                log_performance(_MODEL_NAME, as_of_date, f"migration_rate_{pair_key}", float(row["migration_rate"]))

        overall_mix = trigger_mix[(trigger_mix["from_segment"] == "All") & (trigger_mix["trigger_reason"] == "firmographic_rescore")]
        if len(overall_mix):
            log_performance(_MODEL_NAME, as_of_date, "pct_firmographic_rescore_overall", float(overall_mix["share"].iloc[0]))
        for from_segment, to_segment in _SEGMENT_PAIRS:
            pair_key = f"{from_segment.lower()}_to_{to_segment.lower()}"
            pair_mix = trigger_mix[
                (trigger_mix["from_segment"] == from_segment)
                & (trigger_mix["to_segment"] == to_segment)
                & (trigger_mix["trigger_reason"] == "firmographic_rescore")
            ]
            if len(pair_mix) and pd.notna(pair_mix["share"].iloc[0]):
                log_performance(_MODEL_NAME, as_of_date, f"pct_firmographic_rescore_{pair_key}", float(pair_mix["share"].iloc[0]))

        total_graduated = graduated_revenue[(graduated_revenue["from_segment"] == "All")]["graduated_revenue_mrr"].sum()
        log_performance(_MODEL_NAME, as_of_date, "graduated_revenue_mrr_total", float(total_graduated))
        for from_segment, to_segment in _SEGMENT_PAIRS:
            pair_key = f"{from_segment.lower()}_to_{to_segment.lower()}"
            pair_total = graduated_revenue[
                (graduated_revenue["from_segment"] == from_segment) & (graduated_revenue["to_segment"] == to_segment)
            ]["graduated_revenue_mrr"].sum()
            log_performance(_MODEL_NAME, as_of_date, f"graduated_revenue_mrr_{pair_key}", float(pair_total))

        for from_segment, to_segment in _SEGMENT_PAIRS:
            pair_key = f"{from_segment.lower()}_to_{to_segment.lower()}"
            # True median of the combined sample, not an average of the two
            # trigger-reason subgroup medians -- those aren't the same
            # statistic and diverge as subgroup sizes grow apart.
            pair_days = events.loc[
                (events["from_segment"] == from_segment) & (events["to_segment"] == to_segment),
                "days_in_prior_segment",
            ]
            if len(pair_days):
                log_performance(_MODEL_NAME, as_of_date, f"median_days_in_prior_segment_{pair_key}", float(pair_days.median()))

        log_performance(_MODEL_NAME, as_of_date, "graduated_revenue_reconciliation_max_abs_diff_usd", reconciliation["max_abs_diff_usd"])

    return {
        "migration_velocity": velocity,
        "trigger_reason_mix": trigger_mix,
        "time_in_prior_segment": time_in_segment,
        "graduated_revenue": graduated_revenue,
        "reconciliation": reconciliation,
        "trigger_reason_diversity": diversity,
    }


if __name__ == "__main__":
    result = run_build_time_validation(date(2025, 12, 31))
    print("Migration velocity (trailing 12mo):")
    print(result["migration_velocity"].to_string(index=False))
    print()
    print("Trigger-reason mix:")
    print(result["trigger_reason_mix"].to_string(index=False))
    print()
    print("Time-in-prior-segment distribution (days):")
    print(result["time_in_prior_segment"].to_string(index=False))
    print()
    print("Graduated revenue (trailing 12mo, MRR):")
    print(result["graduated_revenue"].to_string(index=False))
    print()
    print("Growth-bridge reconciliation:", result["reconciliation"])
    print()
    print("Trigger-reason diversity check:")
    print(result["trigger_reason_diversity"]["detail"].to_string(index=False))
    print("All pairs pass proposed floor:", result["trigger_reason_diversity"]["all_pairs_pass"])
