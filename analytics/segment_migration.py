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

The weekly executive readout's `segment_mix` section ("are we moving
upmarket") is a consumer of this module: compute_segment_mix() combines the
velocity and graduated-revenue functions below with each segment's share of
ending MRR from mart_growth_bridge, so the readout reuses these definitions
rather than carrying a second copy.

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


def load_segment_ending_mrr(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per segment per month, month <= as_of_date. Source
    mart: mart_growth_bridge -- ending_mrr is each segment's MRR at the end
    of the month (the next month's starting MRR); the segment mix is its
    share of the company total."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select segment, month, ending_mrr from main_marts.mart_growth_bridge "
            "where month <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    return df


def _last_month_in_marts(con) -> pd.Timestamp:
    return pd.Timestamp(con.execute(
        "select max(month) from main_marts.mart_growth_bridge").fetchone()[0])


def _trailing_window(as_of_date: date, window_months: int) -> tuple:
    """(window_start, as_of): rows dated after window_start and up to as_of. When
    as_of is a month end the start is the exact month boundary (the end of the month
    `window_months` before), not the same calendar day: on 28 February a one-month
    window must start after 31 January, not after 28 January, or it would take in
    the prior month's last days."""
    as_of_ts = pd.Timestamp(as_of_date)
    window_start = as_of_ts - pd.DateOffset(months=window_months)
    if as_of_ts == as_of_ts + pd.offsets.MonthEnd(0):
        window_start = window_start + pd.offsets.MonthEnd(0)
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
        avg_population = avg_starting_accounts.get(from_segment, np.nan)
        avg_population = float(avg_population) if pd.notna(avg_population) else np.nan
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


# =====================================================================
# Segment mix -- "are we moving upmarket" (the weekly readout's segment_mix)
# =====================================================================

SEGMENT_ORDER = ("SMB", "Commercial", "Enterprise")
UPMARKET_SEGMENTS = ("Commercial", "Enterprise")

SEGMENT_MIX_BASIS = (
    "Each segment's share of company ending MRR, with share changes against the prior month "
    "and the same month a year earlier, beside migration velocity (migration events divided by "
    "the source segment's accounts) and graduated MRR (MRR reclassified out of the source "
    "segment) as a share of the source segment's MRR. Monthly rates cover one month and "
    "trailing rates cover 12 months, so the two are not comparable with each other.")

SEGMENT_MIX_CAVEATS = (
    "Migration only moves accounts up (SMB to Commercial, Commercial to Enterprise; there is "
    "no downgrade path), so migration counts and graduated MRR rise with the base. The rates "
    "and the segment shares are the comparable measures.",
    "A segment's share of MRR also moves with expansion, contraction and churn inside each "
    "segment, not only with migration. A migrating account takes its whole MRR to the higher "
    "segment.",
    "Velocity divides events by the source segment's average starting accounts over the "
    "window; graduated MRR is divided by the source segment's average starting MRR over the "
    "window. A 12-month flow against an average base can exceed 100% when the base is "
    "replenished by new logos and expansion.",
    "The final month of the data window is not a representative month (each active account's "
    "last observed month is bucketed as contraction), so the section is unavailable for it.",
)


def _unavailable_mix(month: pd.Timestamp, reason: str, detail: str) -> dict:
    return {"status": "unavailable", "reason": reason, "detail": detail,
            "evaluation_month": month.date().isoformat(), "basis": SEGMENT_MIX_BASIS,
            "caveats": list(SEGMENT_MIX_CAVEATS)}


def _window_population(population: pd.DataFrame, as_of: date, window_months: int) -> pd.DataFrame:
    start, end = _trailing_window(as_of, window_months)
    return population[(population["month"] > start) & (population["month"] <= end)]


def _pair_window(as_of: date, window_months: int, velocity: pd.DataFrame,
                 graduated: pd.DataFrame, population: pd.DataFrame) -> dict:
    """Per segment pair over the `window_months` ending at `as_of`: events,
    velocity, graduated MRR, and graduated MRR as a share of the source
    segment's average starting MRR over the same window."""
    pop = _window_population(population, as_of, window_months)
    out = {}
    for from_segment, to_segment in _SEGMENT_PAIRS:
        v = velocity[(velocity["from_segment"] == from_segment)
                     & (velocity["to_segment"] == to_segment)].iloc[0]
        grad = float(graduated[(graduated["from_segment"] == from_segment)
                               & (graduated["to_segment"] == to_segment)]
                     ["graduated_revenue_mrr"].sum())
        seg_pop = pop[pop["segment"] == from_segment]
        avg_mrr = seg_pop["starting_mrr"].mean()
        accounts = float(seg_pop["starting_accounts"].sum())
        per_account = float(seg_pop["starting_mrr"].sum()) / accounts if accounts > 0 else None
        events = int(v["event_count"])
        multiple = ((grad / events) / per_account
                    if events > 0 and per_account else None)
        out[(from_segment, to_segment)] = {
            "migrating_account_mrr_multiple": multiple,
            "events": int(v["event_count"]),
            "velocity": None if pd.isna(v["migration_rate"]) else float(v["migration_rate"]),
            "avg_from_segment_accounts": (None if pd.isna(v["avg_from_segment_starting_accounts"])
                                          else float(v["avg_from_segment_starting_accounts"])),
            "graduated_mrr": grad,
            "graduated_share_of_source_mrr": (grad / float(avg_mrr)
                                              if pd.notna(avg_mrr) and avg_mrr > 0 else None),
        }
    return out


def _usd_short(v: float) -> str:
    return f"${v / 1e6:,.2f}M" if abs(v) >= 1e6 else f"${v / 1e3:,.0f}K"


def _measured_caveats(pair: dict, upmarket: dict) -> list:
    """Two caveats whose figures are this month's own: how large the graduated
    share is and why (migrating accounts are large for the source segment), and
    how much of the upmarket share is reclassification of existing MRR."""
    out = []
    mult = pair["migrating_account_mrr_multiple_trailing_12m"]
    on_end = pair["graduated_share_of_source_ending_mrr_trailing_12m"]
    on_ya = pair["graduated_share_of_source_mrr_a_year_earlier_trailing_12m"]
    if mult and on_end is not None:
        ya = (f" and {on_ya:.0%} of {pair['from_segment']} MRR 12 months earlier"
              if on_ya is not None else "")
        out.append(
            f"Graduated MRR over 12 months is a flow set against an average base, so its share of "
            f"the source segment's MRR can exceed 100%. The accounts that migrate are large for "
            f"their segment: {pair['from_segment']} accounts that moved to {pair['to_segment']} "
            f"carried about {mult:.0f} times the MRR of the average {pair['from_segment']} "
            f"account, and the {_usd_short(pair['graduated_mrr_trailing_12m'])} that left "
            f"{pair['from_segment']} is {on_end:.0%} of ending {pair['from_segment']} MRR"
            f"{ya}.")
    share = upmarket["smb_to_commercial_graduated_share_of_total_mrr_trailing_12m"]
    ch = upmarket["change_vs_12m_ago"]
    cmp = ""
    if ch is not None:
        cmp = (f", {'more' if share > abs(ch) else 'less'} than the {ch * 100:+.1f} pp change in "
               f"the upmarket share over the same period")
    out.append(
        f"The upmarket share of MRR rises partly because existing accounts are reclassified "
        f"upward: the {_usd_short(pair['graduated_mrr_trailing_12m'])} that moved from "
        f"{pair['from_segment']} to {pair['to_segment']} over 12 months is {share:.1%} of "
        f"company ending MRR{cmp}. The share answers where MRR is booked more than who the "
        f"company is selling to.")
    return out


def compute_segment_mix(evaluation_month: pd.Timestamp,
                        window_months: int = _DEFAULT_WINDOW_MONTHS, con=None) -> dict:
    """Segment mix and migration for one evaluation month. Grain: one record
    per month, with one row per segment and one per segment pair. Source
    marts: mart_growth_bridge (ending MRR by segment), mart_segment_migration
    (events and reclassified MRR) and mart_durability (the accounts and MRR
    denominators), through the velocity and graduated-revenue functions above.
    Point in time: everything is read at the end of `evaluation_month`, which
    must be a complete month; the truncated final month of the data window is
    `unavailable`, as is a month the marts have no segment rows for."""
    month = pd.Timestamp(evaluation_month).to_period("M").to_timestamp()
    as_of = (month + pd.offsets.MonthEnd(0)).date()
    owns_con = con is None
    con = con or _connect()
    try:
        last = _last_month_in_marts(con)
        if month > last:
            return _unavailable_mix(month, "no_segment_data_for_evaluation_month",
                                    "The marts have no segment rows for this month.")
        if month == last:
            return _unavailable_mix(
                month, "evaluation_month_is_truncated_final_month",
                "The evaluation month is the final month of the data window, which carries an "
                "end-of-window truncation artifact. The prior month is the last representative "
                "month.")
        ending = load_segment_ending_mrr(as_of, con=con)
        month_rows = ending[ending["month"] == month].set_index("segment")["ending_mrr"]
        if set(SEGMENT_ORDER) - set(month_rows.index) or month_rows.isna().any() \
                or not float(month_rows.sum()) > 0:
            return _unavailable_mix(
                month, "no_segment_data_for_evaluation_month",
                "The marts do not have MRR for all three segments in this month.")
        population = load_segment_population(as_of, con=con)
        year_ago_end = (month - pd.DateOffset(months=window_months)
                        + pd.offsets.MonthEnd(0)).date()
        vel_month = compute_migration_velocity(as_of, window_months=1, con=con)
        vel_trail = compute_migration_velocity(as_of, window_months=window_months, con=con)
        vel_year_ago = compute_migration_velocity(year_ago_end, window_months=window_months,
                                                  con=con)
        grad_month = compute_graduated_revenue(as_of, window_months=1, con=con)
        grad_trail = compute_graduated_revenue(as_of, window_months=window_months, con=con)
        grad_year_ago = compute_graduated_revenue(year_ago_end, window_months=window_months,
                                                  con=con)
        reconciliation = reconcile_graduated_revenue_to_growth_bridge(as_of, con=con)
    finally:
        if owns_con:
            con.close()

    first_month = ending["month"].min()
    prior_month = month - pd.DateOffset(months=1)
    year_ago_month = month - pd.DateOffset(months=window_months)

    def share_at(m):
        rows = ending[ending["month"] == m].set_index("segment")["ending_mrr"]
        if set(SEGMENT_ORDER) - set(rows.index) or rows[list(SEGMENT_ORDER)].isna().any():
            return None, None
        total = float(rows[list(SEGMENT_ORDER)].sum())
        return rows, total

    now_rows, now_total = share_at(month)
    prior_rows, prior_total = share_at(prior_month)
    ya_rows, ya_total = share_at(year_ago_month)

    def share(rows, total, seg):
        return None if rows is None else float(rows[seg]) / total

    def change(a, b):
        return None if a is None or b is None else a - b

    segments = []
    for seg in SEGMENT_ORDER:
        sh, sh_prior, sh_ya = (share(now_rows, now_total, seg), share(prior_rows, prior_total, seg),
                               share(ya_rows, ya_total, seg))
        segments.append({
            "segment": seg,
            "ending_mrr": float(now_rows[seg]),
            "mrr_share": sh,
            "mrr_share_prior_month": sh_prior,
            "share_change_vs_prior_month": change(sh, sh_prior),
            "mrr_share_12m_ago": sh_ya,
            "share_change_vs_12m_ago": change(sh, sh_ya),
        })

    def up(rows, total):
        return None if rows is None else float(rows[list(UPMARKET_SEGMENTS)].sum()) / total

    up_now, up_prior, up_ya = up(now_rows, now_total), up(prior_rows, prior_total), up(ya_rows, ya_total)

    in_month = _pair_window(as_of, 1, vel_month, grad_month, population)
    trailing = _pair_window(as_of, window_months, vel_trail, grad_trail, population)
    year_ago_window_available = (year_ago_month - pd.DateOffset(months=window_months - 1)
                                 >= first_month)
    year_ago = (_pair_window(year_ago_end, window_months, vel_year_ago, grad_year_ago, population)
                if year_ago_window_available else None)

    pairs = []
    for key in _SEGMENT_PAIRS:
        m, t = in_month[key], trailing[key]
        ya = year_ago[key] if year_ago else None
        pairs.append({
            "from_segment": key[0], "to_segment": key[1],
            "events_in_month": m["events"], "velocity_in_month": m["velocity"],
            "events_trailing_12m": t["events"], "velocity_trailing_12m": t["velocity"],
            "avg_from_segment_accounts_trailing_12m": t["avg_from_segment_accounts"],
            "events_trailing_12m_year_ago": ya["events"] if ya else None,
            "velocity_trailing_12m_year_ago": ya["velocity"] if ya else None,
            "velocity_change_vs_year_ago": (change(t["velocity"], ya["velocity"]) if ya else None),
            "graduated_mrr_in_month": m["graduated_mrr"],
            "graduated_mrr_trailing_12m": t["graduated_mrr"],
            "graduated_share_of_source_mrr_in_month": m["graduated_share_of_source_mrr"],
            "graduated_share_of_source_mrr_trailing_12m": t["graduated_share_of_source_mrr"],
            "migrating_account_mrr_multiple_trailing_12m": t["migrating_account_mrr_multiple"],
            "graduated_share_of_source_ending_mrr_trailing_12m": (
                t["graduated_mrr"] / float(now_rows[key[0]]) if float(now_rows[key[0]]) > 0 else None),
            "graduated_share_of_source_mrr_a_year_earlier_trailing_12m": (
                t["graduated_mrr"] / float(ya_rows[key[0]])
                if ya_rows is not None and float(ya_rows[key[0]]) > 0 else None),
        })

    smb_to_commercial = next(p for p in pairs if p["from_segment"] == "SMB")
    reclass_share = smb_to_commercial["graduated_mrr_trailing_12m"] / now_total
    upmarket = {
        "segments": list(UPMARKET_SEGMENTS),
        "mrr_share": up_now, "mrr_share_prior_month": up_prior,
        "change_vs_prior_month": change(up_now, up_prior),
        "mrr_share_12m_ago": up_ya, "change_vs_12m_ago": change(up_now, up_ya),
        # MRR that moved from SMB to Commercial in the trailing 12 months, as a share of
        # company ending MRR: that much of the upmarket share is reclassification
        "smb_to_commercial_graduated_share_of_total_mrr_trailing_12m": reclass_share,
    }
    return {
        "status": "present",
        "evaluation_month": month.date().isoformat(),
        "basis": SEGMENT_MIX_BASIS,
        "caveats": list(SEGMENT_MIX_CAVEATS) + _measured_caveats(smb_to_commercial, upmarket),
        "window": {
            "evaluation_month": month.date().isoformat(),
            "prior_month": prior_month.date().isoformat() if prior_rows is not None else None,
            "year_ago_month": year_ago_month.date().isoformat() if ya_rows is not None else None,
            "trailing_window_months": window_months,
            "trailing_window_first_month": (
                month - pd.DateOffset(months=window_months - 1)).date().isoformat(),
            "trailing_window_last_month": month.date().isoformat(),
            "year_ago_window_available": bool(year_ago_window_available),
            "last_month_in_marts": last.date().isoformat(),
            "partial_month_handling": (
                "The evaluation month is a complete month before the final month of the data "
                "window; the final month, which is truncated, is not reported."),
        },
        "total_ending_mrr": now_total,
        "segments": segments,
        "upmarket_share": upmarket,
        "migration": pairs,
        "reconciliation": reconciliation,
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
