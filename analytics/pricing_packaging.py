"""Pricing / packaging effectiveness diagnostic -- Wave 5 (build spec
Section 8, item #16). Two grains, both read from `main_marts` only:
(a) discount-realization / discount-vs-outcome / deal-size-trend legs are
one row per new-business or renewal/expansion opportunity at close (source:
`fact_opportunities`); (b) the packaging/committed-usage-calibration leg is
one row per account per month (source: `fact_committed_vs_utilized_monthly`).

WHAT THIS IS
------------
Build spec Section 8, item #16, Wave 5 ("strategic/market-facing, runs off
market_universe" -- this artifact does not, and does not need to; it is
fully served by `fact_opportunities` and `fact_committed_vs_utilized_
monthly`, both already real generated data with no dependency on the
territory-dimension work or the TAM/ICP work landing concurrently on this
branch). Answers three leadership-facing questions: (1) how deep are
discounts actually running against list, by segment and deal type, and
does that match this project's stated pricing/contract mechanics; (2) does
discount depth buy anything -- higher win rate, protection against
competitive losses; (3) are Commercial/Enterprise committed-usage minimums
sized sensibly against what accounts actually consume. Plus a fourth,
smaller read: whether realized new-business deal size is drifting within
its segment's ACV band over time.

RELATIONSHIP TO THE METRIC TREE'S "Discount rate vs. list" AND "Deal-size
trend within segment band" LEAVES -- AND TO THE SEPARATE, ALREADY-FLAGGED
variance_diagnostic.py FIX
--------------------------------------------------------------------------
`docs/acme-corp-gtm-metric-tree.md`'s New Logo branch names "Avg initial
commitment" (Layer 2: "Realized deal size at close, by segment") with two
Layer-3 leaves: "Discount rate vs. list" and "Deal-size trend within
segment band". A separate, already-flagged piece of work (not part of
this artifact, tracked separately) is correcting
`analytics/variance_diagnostic.py`'s stale `NOT_COMPUTABLE` marking on
those two leaves plus `loss_reason_mix`, now that `fact_opportunities` is
confirmed to expose `list_price`/`discount_rate`/`loss_reason`. This
module is NOT that fix and does not touch `variance_diagnostic.py` --
that fix makes two tree leaves compute a single ratio each for the weekly
readout's drill-down; this module is the deeper, standalone Phase 4
diagnostic the build spec's "Pricing / packaging analytics" item actually
calls for (discount-vs-outcome relationships, packaging/committed-usage
calibration, deal-size trend over time), consistent with the tree's exact
wording for both leaves but not a competing redefinition of them and not
a reproduction of the two-leaf tie-out itself. `compute_discount_
realization()` below happens to compute the same underlying ratio
(1 - amount/list_price) that leaf will read once the fix lands; the two
are expected to agree (see `check_discount_reconciliation()`), by
construction, not by coincidence.

SHAPE -- STRUCTURAL/DESCRIPTIVE, WITH ONE SEEDED NON-PARAMETRIC TEST
----------------------------------------------------------------------
Discount realization, packaging calibration and deal-size trend are all
direct, deterministic aggregations of already-materialized mart rows --
no coefficient, no AUC, no confusion matrix, no R^2/RMSE applies, per
`.claude/skills/analytics-engineering-conventions`' "Structural/logic
artifacts" category (the same category the variance-diagnostic engine,
segment migration, capacity planning, marketing attribution and playbook
triggers entries all use). The one place this module does more than
aggregate is the discount-vs-outcome and discount-vs-competitive-pressure
checks, which need to distinguish a real relationship from sampling
noise. Rather than pull in a new dependency (`scipy`, unused anywhere
else in `analytics/`) for a parametric t-test, both checks use a seeded
permutation test on the mean-discount difference (`numpy`-only, already a
project dependency everywhere else in this directory) -- a label-shuffle
null distribution is the more honest tool here anyway, since discount_rate
is not close to normally distributed (uniform-by-segment at generation
time, see the model-choice rationale below).

MODEL TYPE SELECTION AND RATIONALE (why not a fitted win-probability-
uplift-from-discount model)
----------------------------------------------------------------------
A logistic regression of `is_won` on `discount_rate` (plus controls) was
the credible predictive alternative and was rejected on the same grounds
`analytics/segment_migration.py` and `analytics/capacity_planning.py`
reject a fitted model for their own artifacts, but with the inverted
data-generating story: `generators/opportunities.py`'s
`_sample_discount_and_list_price()` draws `discount_rate` from
`rng.uniform(*config.DISCOUNT_RATE_RANGE[segment])` **independently of**
`is_won`, `loss_reason` and `amount` -- the same draw runs on the won
branch and the lost branch of `generate_new_business_opportunities()`,
with no shared randomness and no causal wire between them. There is
therefore no real relationship in this data for a classifier to fit; a
logistic regression would report a near-zero, statistically insignificant
coefficient on `discount_rate` dressed up as a fitted model, which is
worse than reporting the same null finding directly as what it is: a
population-level, checkable absence of a relationship. This is confirmed
empirically, not assumed -- see the permutation-test results and the
positive-control check below, which together show the test methodology
has real power to detect a relationship when one exists (forecast_category
vs. is_won) and still finds nothing for discount vs. is_won. A genuinely
predictive deal-level model (e.g. "will this specific open deal need a
deep discount to close") is a different question, belongs to build spec
item #17 (Deal-level diagnostics, already built in Wave 4 -- see
`analytics/deal_diagnostics.py`), and is not duplicated here.

POINT-IN-TIME DESIGN
---------------------
Every loader filters to `close_date <= as_of_date` / `month <= as_of_date`.
Discount realization, discount-vs-outcome, discount-vs-competitive-pressure
and packaging calibration are computed all-time-to-date as of `as_of_date`
(the same choice `analytics/segment_migration.py` makes for its
trigger-reason-mix and time-in-prior-segment reads -- these are level/
distributional statistics, not flows, so an all-time-to-date view is the
honest one and avoids thin-sample noise in any single trailing window).
Deal-size trend is the one genuinely time-series read and uses matched
trailing-12-month windows (current vs. immediately prior), both
strictly `<= as_of_date`.

DETERMINISM
-----------
The only stochastic step in this module is the two permutation tests'
label-shuffle draws, both seeded via `_RANDOM_SEED = 42` (same constant
`analytics/health_score.py` uses) through a dedicated
`np.random.default_rng` stream per call -- reproducible, and isolated
from any other module's randomness.
"""
import os
from datetime import date
from typing import Any, Dict, Optional

import duckdb
import numpy as np
import pandas as pd

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_MODEL_NAME = "pricing_packaging_analytics"
_RANDOM_SEED = 42
_N_PERMUTATIONS = 2000

# =====================================================================
# Reference constants -- transcribed from generators/config.py and the QA
# plan's benchmark reference table for grounding comparisons only. Never
# imported at runtime (analytics/ code does not depend on generators/,
# matching analytics/deal_diagnostics.py's and analytics/forecast.py's
# precedent of transcribing rather than importing generator constants).
# =====================================================================

# Build spec Section 1 / QA plan benchmark table.
ACV_RANGES = {"SMB": (0.0, 15_000.0), "Commercial": (15_000.0, 75_000.0), "Enterprise": (75_000.0, 750_000.0)}

# generators/config.py's DISCOUNT_RATE_RANGE -- what SMB's no-negotiation
# metered pricing, Commercial's negotiated annual contract and Enterprise's
# negotiated multi-year graduated commitment are each expected to produce.
DISCOUNT_RATE_RANGE = {"SMB": (0.00, 0.05), "Commercial": (0.05, 0.20), "Enterprise": (0.10, 0.30)}

# generators/config.py's COMMITTED_VOLUME_FACTOR: committed Action minimum
# is deliberately set at this fraction of an account's baseline usage, by
# design, so overage billing above the commitment is a common, growing
# event (build spec Section 1: "committed usage minimum + monthly overage
# billing" for Commercial, "graduated usage commitments, true-up at
# renewal" for Enterprise). This is the number packaging calibration is
# checked against, not an assumed 1.0.
COMMITTED_VOLUME_FACTOR = 0.65
EXPECTED_STEADY_STATE_UTILIZATION = round(1.0 / COMMITTED_VOLUME_FACTOR, 4)  # ~1.5385

# "Well-calibrated" band for a single account-month's utilization_rate --
# this module's own proposed read of "clustering sensibly," not a number
# stated anywhere upstream. See docs/acme-corp-analytics-methods.md's
# Pricing / packaging analytics entry for the grounding.
_CALIBRATION_BAND = (0.80, 1.20)

# Reconciliation tolerance between discount_rate and 1 - (amount /
# list_price): both are generated from the same draw (amount fixed first,
# list_price = amount / (1 - discount), each independently rounded to 2dp
# for amount/list_price and 4dp for discount_rate at generation time), so
# any gap beyond that rounding is a real bug, not statistical noise.
_DISCOUNT_RECONCILIATION_TOLERANCE = 0.001

# Deal-size drift threshold -- PROPOSED, not yet confirmed. See methods
# doc entry for grounding (same PROPOSED-threshold treatment as the
# variance engine's +/-8%, segment migration's 10% floor, and capacity
# planning's 15% margin).
DEAL_SIZE_DRIFT_THRESHOLD = 0.15


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


# =====================================================================
# Loaders -- main_marts only.
# =====================================================================

def load_opportunities(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per opportunity, close_date <= as_of_date. Source
    mart: fact_opportunities. Every opportunity in this mart is already
    closed (no open-pipeline rows exist in fact_opportunities -- open
    pipeline lives elsewhere, e.g. analytics/forecast.py's own loaders),
    so this filter is the complete point-in-time guard needed here."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select opportunity_id, segment, opportunity_type, is_won, loss_reason, "
            "forecast_category, amount, list_price, discount_rate, created_date, close_date "
            "from main_marts.fact_opportunities where close_date <= ?", [as_of_date]).df()
    finally:
        if owns:
            con.close()
    df["close_date"] = pd.to_datetime(df["close_date"])
    df["created_date"] = pd.to_datetime(df["created_date"])
    return df


def load_committed_vs_utilized(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per account_id per month, month <= as_of_date.
    Source mart: fact_committed_vs_utilized_monthly. SMB carries no rows
    in this mart at all (metered, no committed-minimum concept -- build
    spec Section 1), which this loader does not filter for or assume;
    it simply reflects what the mart contains."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select account_id, month, segment, committed_actions_monthly, "
            "utilized_actions_monthly, utilization_rate "
            "from main_marts.fact_committed_vs_utilized_monthly where month <= ?",
            [as_of_date]).df()
    finally:
        if owns:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    return df


# =====================================================================
# Leg 1 -- Discount realization by segment / opportunity_type
# =====================================================================

def compute_discount_realization(opps_df: pd.DataFrame) -> pd.DataFrame:
    """Grain out: one row per (segment, opportunity_type). Avg discount
    rate, avg amount/list_price, and the recomputed discount
    (1 - amount/list_price) alongside the stored discount_rate -- the
    exact quantity the metric tree's "Discount rate vs. list" leaf and
    the separate variance_diagnostic.py fix will read once it lands."""
    g = opps_df.groupby(["segment", "opportunity_type"], as_index=False).agg(
        n=("opportunity_id", "count"),
        avg_discount_rate=("discount_rate", "mean"),
        avg_amount=("amount", "mean"),
        avg_list_price=("list_price", "mean"),
    )
    g["recomputed_discount"] = 1.0 - (g["avg_amount"] / g["avg_list_price"])
    g["expected_range_lo"] = g["segment"].map(lambda s: DISCOUNT_RATE_RANGE[s][0])
    g["expected_range_hi"] = g["segment"].map(lambda s: DISCOUNT_RATE_RANGE[s][1])
    g["within_expected_mechanics_range"] = (
        (g["avg_discount_rate"] >= g["expected_range_lo"]) & (g["avg_discount_rate"] <= g["expected_range_hi"])
    )
    return g.sort_values(["segment", "opportunity_type"]).reset_index(drop=True)


def check_discount_reconciliation(opps_df: pd.DataFrame) -> Dict[str, Any]:
    """Exact-reconciliation check: discount realization computed two ways
    -- the stored discount_rate, and 1 - (amount / list_price) recomputed
    per opportunity -- must tie out to rounding precision. This is a
    structural correctness invariant, not a statistical estimate."""
    recomputed = 1.0 - (opps_df["amount"] / opps_df["list_price"])
    diff = (recomputed - opps_df["discount_rate"]).abs()
    return {
        "max_abs_diff": float(diff.max()),
        "mean_abs_diff": float(diff.mean()),
        "tolerance": _DISCOUNT_RECONCILIATION_TOLERANCE,
        "passed": bool(diff.max() <= _DISCOUNT_RECONCILIATION_TOLERANCE),
        "n": int(len(opps_df)),
    }


def check_deal_size_within_band(opps_df: pd.DataFrame) -> Dict[str, Any]:
    """Exact-reconciliation check: every new-business opportunity's amount
    must fall within its segment's ACV_RANGES band -- a hard structural
    invariant (generators/opportunities.py clips every amount to
    config.ACV_RANGES at generation time), so anything short of 100% here
    indicates a real defect, not sampling variation."""
    new_biz = opps_df[opps_df["opportunity_type"] == "new_business"]
    result: Dict[str, Any] = {}
    all_passed = True
    for segment, (lo, hi) in ACV_RANGES.items():
        sub = new_biz[new_biz["segment"] == segment]["amount"]
        if len(sub) == 0:
            continue
        share_within = float(((sub >= lo - 0.01) & (sub <= hi + 0.01)).mean())
        result[segment] = {"share_within_band": share_within, "n": int(len(sub)),
                           "min": float(sub.min()), "max": float(sub.max())}
        all_passed = all_passed and (share_within == 1.0)
    result["all_passed"] = all_passed
    return result


# =====================================================================
# Leg 2 -- Discount depth vs. outcome (win rate, competitive pressure)
# =====================================================================

def _permutation_test_mean_diff(rng: np.random.Generator, group_a: np.ndarray,
                                group_b: np.ndarray, n_perm: int = _N_PERMUTATIONS) -> float:
    """Two-sided permutation p-value on the difference in means between
    group_a and group_b, via label shuffling. numpy-only (no scipy
    dependency, unused elsewhere in analytics/) -- appropriate here since
    discount_rate is uniform-by-segment at generation, not normal, so a
    parametric t-test's assumptions are a worse fit than a
    label-shuffle null anyway."""
    obs_diff = float(group_a.mean() - group_b.mean())
    pooled = np.concatenate([group_a, group_b])
    n_a = len(group_a)
    at_least_as_extreme = 0
    for _ in range(n_perm):
        rng.shuffle(pooled)
        perm_diff = pooled[:n_a].mean() - pooled[n_a:].mean()
        if abs(perm_diff) >= abs(obs_diff):
            at_least_as_extreme += 1
    p_value = (at_least_as_extreme + 1) / (n_perm + 1)
    return obs_diff, p_value


def compute_discount_vs_win_rate(opps_df: pd.DataFrame, seed: int = _RANDOM_SEED) -> Dict[str, Any]:
    """Does discount depth correlate with win/loss, within new-business
    opportunities, by segment (Commercial/Enterprise only -- SMB has no
    win-rate concept, per the metric tree's own note under Pipeline
    generated: "SMB has no win-rate concept to true up"). Seeded
    permutation test per segment on mean discount, won vs. lost."""
    rng = np.random.default_rng(seed)
    result: Dict[str, Any] = {}
    for segment in ("Commercial", "Enterprise"):
        sub = opps_df[(opps_df["segment"] == segment) & (opps_df["opportunity_type"] == "new_business")]
        won = sub.loc[sub["is_won"], "discount_rate"].dropna().to_numpy()
        lost = sub.loc[~sub["is_won"], "discount_rate"].dropna().to_numpy()
        if len(won) == 0 or len(lost) == 0:
            continue
        diff, p_value = _permutation_test_mean_diff(rng, won, lost)
        is_won_float = sub["is_won"].astype(float)
        pearson_r = float(sub["discount_rate"].corr(is_won_float))
        result[segment] = {
            "n_won": int(len(won)), "n_lost": int(len(lost)),
            "avg_discount_won": float(won.mean()), "avg_discount_lost": float(lost.mean()),
            "diff_won_minus_lost": diff, "pearson_r": pearson_r, "permutation_p_value": p_value,
        }
    return result


def compute_discount_vs_competitive_pressure(opps_df: pd.DataFrame, seed: int = _RANDOM_SEED) -> Dict[str, Any]:
    """Does discount depth differ between competitive losses and other
    losses (no_decision/price/other), within lost new-business
    opportunities, by segment. loss_reason == 'price' is deliberately
    included in "other" here, not excluded: the question this check asks
    is whether deals lost specifically to a rival bid ran deeper discounts
    than losses overall, not a price-vs-everything-else split (that split
    is the loss_reason_mix leaf's job, not this one's)."""
    rng = np.random.default_rng(seed)
    result: Dict[str, Any] = {}
    for segment in ("Commercial", "Enterprise"):
        sub = opps_df[
            (opps_df["segment"] == segment) & (opps_df["opportunity_type"] == "new_business") & (~opps_df["is_won"])
        ]
        competitive = sub.loc[sub["loss_reason"] == "competitive", "discount_rate"].dropna().to_numpy()
        other = sub.loc[sub["loss_reason"] != "competitive", "discount_rate"].dropna().to_numpy()
        if len(competitive) == 0 or len(other) == 0:
            continue
        diff, p_value = _permutation_test_mean_diff(rng, competitive, other)
        result[segment] = {
            "n_competitive": int(len(competitive)), "n_other": int(len(other)),
            "avg_discount_competitive": float(competitive.mean()), "avg_discount_other": float(other.mean()),
            "diff_competitive_minus_other": diff, "permutation_p_value": p_value,
        }
    return result


def compute_positive_control_forecast_category(opps_df: pd.DataFrame) -> pd.DataFrame:
    """Non-vacuousness check for the two permutation tests above: confirms
    this module's test methodology has real power to detect a relationship
    when one genuinely exists in the data, using forecast_category vs.
    is_won as the positive control (generators/opportunities.py wires
    forecast_category to a perceived-win-probability logit that is a real
    function of cycle depth, POC outcome, loss reason, discount position
    and rep ramp status -- a deliberately strong, known-real driver of
    is_won, unlike discount_rate itself). If this shows a large win-rate
    spread across categories while the discount-vs-outcome tests above
    show none, the absence of a discount effect is a genuine finding, not
    a failure of the test to detect a real signal."""
    sub = opps_df[opps_df["opportunity_type"] == "new_business"]
    g = sub.groupby("forecast_category", as_index=False).agg(
        n=("opportunity_id", "count"), win_rate=("is_won", "mean"))
    return g.sort_values("win_rate", ascending=False).reset_index(drop=True)


# =====================================================================
# Leg 3 -- Packaging / committed-usage calibration
# =====================================================================

def compute_packaging_calibration(util_df: pd.DataFrame) -> pd.DataFrame:
    """Grain out: one row per segment (Commercial/Enterprise -- SMB has no
    committed-minimum concept and carries no rows in this mart, per the
    metered/no-contract pricing mechanic). Distributional read of
    utilization_rate (utilized Actions / committed-minimum Actions),
    checked against EXPECTED_STEADY_STATE_UTILIZATION rather than a naive
    1.0 -- see the module docstring's COMMITTED_VOLUME_FACTOR grounding.
    """
    rows = []
    for segment, sub in util_df.groupby("segment"):
        vals = sub["utilization_rate"].dropna()
        if len(vals) == 0:
            continue
        lo, hi = _CALIBRATION_BAND
        rows.append({
            "segment": segment, "n": int(len(vals)),
            "mean_utilization": float(vals.mean()), "median_utilization": float(vals.median()),
            "p25": float(vals.quantile(0.25)), "p75": float(vals.quantile(0.75)), "p90": float(vals.quantile(0.90)),
            "share_well_calibrated_0.8_1.2": float(((vals >= lo) & (vals <= hi)).mean()),
            "share_over_committed_lt_0.8": float((vals < lo).mean()),
            "share_under_committed_gt_1.2": float((vals > hi).mean()),
            "expected_steady_state_utilization": EXPECTED_STEADY_STATE_UTILIZATION,
            "diff_median_from_expected": float(vals.median() - EXPECTED_STEADY_STATE_UTILIZATION),
        })
    return pd.DataFrame(rows).sort_values("segment").reset_index(drop=True)


def compute_packaging_trend_by_year(util_df: pd.DataFrame) -> pd.DataFrame:
    """Grain out: one row per (segment, calendar_year). Median
    utilization_rate over time -- shows whether calibration is stable or
    converging/drifting as accounts season, distinct from
    compute_packaging_calibration()'s single all-time-to-date summary."""
    df = util_df.copy()
    df["year"] = df["month"].dt.year
    g = df.groupby(["segment", "year"], as_index=False)["utilization_rate"].median()
    return g.rename(columns={"utilization_rate": "median_utilization"}).sort_values(["segment", "year"]).reset_index(drop=True)


# =====================================================================
# Leg 4 -- Deal-size trend within segment band
# =====================================================================

def compute_deal_size_trend(opps_df: pd.DataFrame, as_of_date: date, window_months: int = 12) -> pd.DataFrame:
    """Grain out: one row per segment. Trailing-window_months mean/median
    new-business deal size ending at as_of_date, vs. the immediately prior
    trailing-window_months window -- both windows strictly <= as_of_date,
    so no leakage. Percent change flags drift within the segment's own
    ACV band (check_deal_size_within_band() above confirms every deal
    stays inside the band regardless; this is about the level trending up
    or down within it, not about escaping it)."""
    as_of_ts = pd.Timestamp(as_of_date)
    cur_start = as_of_ts - pd.DateOffset(months=window_months)
    prior_start = cur_start - pd.DateOffset(months=window_months)

    new_biz = opps_df[opps_df["opportunity_type"] == "new_business"]
    rows = []
    for segment in ACV_RANGES:
        sub = new_biz[new_biz["segment"] == segment]
        cur = sub[(sub["close_date"] > cur_start) & (sub["close_date"] <= as_of_ts)]["amount"]
        prior = sub[(sub["close_date"] > prior_start) & (sub["close_date"] <= cur_start)]["amount"]
        if len(cur) == 0 or len(prior) == 0:
            continue
        pct_change_mean = float((cur.mean() - prior.mean()) / prior.mean())
        rows.append({
            "segment": segment, "n_current_window": int(len(cur)), "n_prior_window": int(len(prior)),
            "mean_current": float(cur.mean()), "mean_prior": float(prior.mean()),
            "median_current": float(cur.median()), "median_prior": float(prior.median()),
            "pct_change_mean": pct_change_mean,
            "exceeds_drift_threshold": bool(abs(pct_change_mean) > DEAL_SIZE_DRIFT_THRESHOLD),
        })
    return pd.DataFrame(rows).sort_values("segment").reset_index(drop=True)


# =====================================================================
# Top-level: build-time run + persistence
# =====================================================================

def run_build_time_validation(as_of_date: date, log: bool = True) -> Dict[str, Any]:
    """Everything analytics-model-validator needs: every computed leg at
    as_of_date, plus the structural/non-vacuousness checks in place of a
    predictive target (per the shape decision -- see module docstring)."""
    con = _connect()
    try:
        opps = load_opportunities(as_of_date, con=con)
        util = load_committed_vs_utilized(as_of_date, con=con)
    finally:
        con.close()

    discount_realization = compute_discount_realization(opps)
    reconciliation_check = check_discount_reconciliation(opps)
    band_check = check_deal_size_within_band(opps)
    discount_vs_win = compute_discount_vs_win_rate(opps)
    discount_vs_competitive = compute_discount_vs_competitive_pressure(opps)
    positive_control = compute_positive_control_forecast_category(opps)
    deal_size_trend = compute_deal_size_trend(opps, as_of_date)
    packaging_calibration = compute_packaging_calibration(util)
    packaging_trend = compute_packaging_trend_by_year(util)

    positive_control_spread = float(positive_control["win_rate"].max() - positive_control["win_rate"].min())
    non_vacuous = positive_control_spread > 0.80  # forecast_category genuinely separates win rate

    if log:
        log_performance(_MODEL_NAME, as_of_date, "discount_reconciliation_max_abs_diff",
                        reconciliation_check["max_abs_diff"])
        log_performance(_MODEL_NAME, as_of_date, "deal_size_within_band_all_passed",
                        1.0 if band_check["all_passed"] else 0.0)
        log_performance(_MODEL_NAME, as_of_date, "positive_control_win_rate_spread", positive_control_spread)
        log_performance(_MODEL_NAME, as_of_date, "test_methodology_non_vacuous", 1.0 if non_vacuous else 0.0)
        for segment, stats in discount_vs_win.items():
            log_performance(_MODEL_NAME, as_of_date, f"discount_vs_win_diff_{segment.lower()}",
                            stats["diff_won_minus_lost"])
            log_performance(_MODEL_NAME, as_of_date, f"discount_vs_win_permutation_p_{segment.lower()}",
                            stats["permutation_p_value"])
        for segment, stats in discount_vs_competitive.items():
            log_performance(_MODEL_NAME, as_of_date, f"discount_vs_competitive_diff_{segment.lower()}",
                            stats["diff_competitive_minus_other"])
        for _, row in packaging_calibration.iterrows():
            seg_key = row["segment"].lower()
            log_performance(_MODEL_NAME, as_of_date, f"packaging_median_utilization_{seg_key}",
                            row["median_utilization"])
            log_performance(_MODEL_NAME, as_of_date, f"packaging_share_well_calibrated_{seg_key}",
                            row["share_well_calibrated_0.8_1.2"])
        for _, row in deal_size_trend.iterrows():
            log_performance(_MODEL_NAME, as_of_date, f"deal_size_pct_change_{row['segment'].lower()}",
                            row["pct_change_mean"])

    return {
        "discount_realization": discount_realization,
        "reconciliation_check": reconciliation_check,
        "band_check": band_check,
        "discount_vs_win": discount_vs_win,
        "discount_vs_competitive": discount_vs_competitive,
        "positive_control": positive_control,
        "positive_control_spread": positive_control_spread,
        "non_vacuous": non_vacuous,
        "deal_size_trend": deal_size_trend,
        "packaging_calibration": packaging_calibration,
        "packaging_trend": packaging_trend,
    }


if __name__ == "__main__":
    # 2025-11-30, matching analytics/playbook_triggers.py's and
    # analytics/variance_diagnostic.py's canonical build-time checkpoint --
    # 2025-12 carries that engine's documented end-of-window truncation
    # artifact, so 2025-11 is the last representative evaluation period.
    AS_OF = date(2025, 11, 30)
    out = run_build_time_validation(AS_OF)

    print(f"=== Pricing / packaging analytics -- as of {AS_OF} ===\n")
    print("-- Discount realization by segment / opportunity_type --")
    print(out["discount_realization"].to_string(index=False))
    print(f"\nReconciliation check: {out['reconciliation_check']}")
    print(f"Deal-size-within-band check: {out['band_check']}")

    print("\n-- Discount vs. win rate (permutation test) --")
    for segment, stats in out["discount_vs_win"].items():
        print(f"  {segment}: {stats}")

    print("\n-- Discount vs. competitive-loss pressure (permutation test) --")
    for segment, stats in out["discount_vs_competitive"].items():
        print(f"  {segment}: {stats}")

    print("\n-- Positive control: forecast_category vs. win rate --")
    print(out["positive_control"].to_string(index=False))
    print(f"Spread: {out['positive_control_spread']:.4f}  Non-vacuous: {out['non_vacuous']}")

    print("\n-- Deal-size trend (trailing 12mo vs. prior 12mo) --")
    print(out["deal_size_trend"].to_string(index=False))

    print("\n-- Packaging calibration (committed vs. utilized) --")
    print(out["packaging_calibration"].to_string(index=False))
    print("\n-- Packaging calibration trend by year --")
    print(out["packaging_trend"].to_string(index=False))
