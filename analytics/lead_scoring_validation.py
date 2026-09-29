"""Lead/segmentation scoring -- model validation & drift detection (build
spec item #11, Wave 7). Grain: one row per lead_id (its most recent
fact_lead_scoring_history scoring event on or before as_of_date), restricted
to leads whose eventual outcome is already knowable as of as_of_date -- not a
newly-trained model. Source marts: fact_lead_scoring_history, fact_leads.

Shape decision -- structural validation of an already-fixed score, not a
fitted classifier
--------------------------------------------------------------------------
`predicted_fit_score` is `generators/firmographics.py`'s `compute_fit_score()`
-- a fixed, pre-existing formula (0.6*employee_band_weight +
0.3*industry_weight [+ region_modifier from MODEL_CUTOVER_DATE onward] +
noise) -- re-applied by `generators/lead_scoring.py` on a recurring cadence.
Nothing about that formula is estimated from data anywhere in this project,
and this module does not fit anything either: no train/test split, no
coefficients, no feature-importance table, because there is no model being
trained here to produce any of those. This is the same "don't force a shape
onto data that doesn't support it" call the Segment migration and Marketing
attribution entries already made for their own artifacts, applied to a
scoring/validation artifact rather than a descriptive one. A genuinely new
classifier (e.g. logistic regression on employee band/industry/region
against is_converted) was considered and rejected -- not because it would
trivially re-derive the generator's own construction (unlike segment
migration's rejected classifier, `is_converted` is NOT a deterministic
function of fit; only the non-converting lead POOL's company mix is tilted
toward lower fit -- see generators/marketing_funnel.py's
`_sample_noncustomer_companies`), but because the task this artifact actually
serves is "is the score already in production well-calibrated and has it
drifted," not "can a better model be fit." Building a second, competing
scoring model here would duplicate build spec item #11's own stated job
description ("model validation & drift detection" of an existing system) and
give this artifact two different, uncoordinated scoring functions in one
place.

What IS applied here, because the object being validated is a score against
a real binary outcome (conversion), is the discrimination/calibration
DIAGNOSTIC toolkit `analytics-engineering-conventions`' classification
package names -- AUC, a confusion matrix at a real (not arbitrary-0.5)
operating threshold, a calibration read, and sample sizes -- because those
tools are general-purpose ways to evaluate any score against an outcome,
fitted or not. No coefficient/feature-importance table is produced (nothing
was fit); in its place this entry cites `compute_fit_score()`'s own fixed,
already-documented weights directly, since those are what predicted_fit_score
actually is.

No-leakage / historical-depth note
-----------------------------------
`lead_scoring_history` spans the full 36-month simulation window with real
historical scoring events already generated (132,599 v1 rows, 135,829 v2
rows at build time) -- this is NOT the thin-monitoring-history situation
`analytics/proxy_metric_health.py` had to report for its own artifact; there
is genuinely enough scoring history here to validate against. Every scoring
event's own no-leakage guarantee (score computed from firmographics only,
strictly before `is_converted`/`converted_date` could have been read) is
generated-data-layer, already covered by `tests/test_phase1_batch11.py`, and
is not re-checked here -- this module's own leakage discipline is a
different, module-level one: only using a lead's LAST score at-or-before
as_of_date, and only evaluating leads whose eventual fate is already resolved
by as_of_date (see load_resolved_leads).

fact_leads.lead_score vs. lead_scoring_history.predicted_fit_score
---------------------------------------------------------------------
Deliberately two different things, not two views of one metric.
`fact_leads.lead_score` is a terminal-state composite (firmographic fit AND
observed touch-engagement depth) that `analytics/marketing_attribution.py`
already reads for channel-mix/lead-quality reporting and explicitly never as
a point-in-time predictive feature (it leaks the outcome by construction --
see that module's own docstring). `predicted_fit_score` here is the pure-
firmographic, point-in-time score this module validates. Neither module
treats the other's score as validating or substituting for its own; this
module does not touch `lead_score` anywhere.
"""
import os
from datetime import date

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_MODEL_NAME = "lead_scoring_model"

# Mirrored, not imported, from generators/lead_scoring.py's
# MAX_ACTIVE_SCORING_DAYS -- the same cross-package convention
# analytics/tam_icp_sizing.py already established for firmographics.py's
# ENTERPRISE_FIT_THRESHOLD/COMMERCIAL_FIT_THRESHOLD (Phase 4 code reads
# business input from marts only; a grounding constant mirrored as a literal,
# with a comment naming its source, is not the same thing as reaching into
# generator code for data). A non-converting lead the generator stopped
# re-scoring COLD_CAP_DAYS after created_date is "resolved" (will never
# convert) by that same cutoff.
_COLD_CAP_DAYS = 180

# Mirrored from generators/firmographics.py's ENTERPRISE_FIT_THRESHOLD /
# COMMERCIAL_FIT_THRESHOLD -- the real production cut points this score's
# predicted_segment already uses (and analytics/tam_icp_sizing.py already
# reuses for the same reason), not an arbitrary 0.5 probability cutoff.
# predicted_fit_score was never fit as a probability, so a 0.5 cutoff has no
# meaning here at all.
_ENTERPRISE_FIT_THRESHOLD = 72
_COMMERCIAL_FIT_THRESHOLD = 40

_RANDOM_SEED = 42
_N_CALIBRATION_BINS = 10
_N_BOOTSTRAP = 300


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


def load_resolved_leads(as_of_date: date, con=None) -> pd.DataFrame:
    """One row per lead_id whose eventual outcome is already knowable as of
    as_of_date -- converted (converted_date <= as_of_date), or non-converting
    and gone cold (created_date + COLD_CAP_DAYS <= as_of_date). Leads still
    'live' (created recently, not yet converted, not yet cold) are excluded:
    their eventual label is not yet knowable as of as_of_date, and including
    them with today's is_converted=False would leak a future-only-certain
    label backward. Source mart: fact_leads."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select lead_id, created_date, converted_date, is_converted "
            "from main_marts.fact_leads "
            "where created_date <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["created_date"] = pd.to_datetime(df["created_date"])
    df["converted_date"] = pd.to_datetime(df["converted_date"])
    as_of_ts = pd.Timestamp(as_of_date)

    converted_resolved = df["is_converted"] & (df["converted_date"] <= as_of_ts)
    gone_cold_resolved = (~df["is_converted"]) & (
        df["created_date"] + pd.Timedelta(days=_COLD_CAP_DAYS) <= as_of_ts
    )
    return df.loc[converted_resolved | gone_cold_resolved].reset_index(drop=True)


def load_last_score_before_outcome(as_of_date: date, con=None) -> pd.DataFrame:
    """One row per resolved lead_id (per load_resolved_leads) -- its most
    recent fact_lead_scoring_history scoring event with scored_at <=
    as_of_date, joined to its eventual is_converted outcome. This is the
    grain every discrimination/calibration/confusion-matrix check below
    operates on. Source marts: fact_lead_scoring_history, fact_leads."""
    owns_con = con is None
    con = con or _connect()
    try:
        resolved = load_resolved_leads(as_of_date, con=con)
        hist = con.execute(
            "select score_id, lead_id, scored_at, model_version, predicted_segment, "
            "predicted_fit_score, employee_band_component, industry_component, "
            "region_component, noise_component "
            "from main_marts.fact_lead_scoring_history where scored_at <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    hist["scored_at"] = pd.to_datetime(hist["scored_at"])

    merged = hist.merge(
        resolved[["lead_id", "is_converted", "created_date", "converted_date"]],
        on="lead_id", how="inner",
    )
    last = (
        merged.sort_values("scored_at", kind="mergesort")
        .groupby("lead_id", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
    return last


def compute_discrimination(scored: pd.DataFrame) -> dict:
    """Rank-based discrimination (AUC) of predicted_fit_score against
    eventual is_converted, overall and split by the model_version that
    produced each lead's last score. No train/holdout split applies -- see
    module docstring: predicted_fit_score is an already-fixed formula, not
    something this module fits, so the full resolved population (per
    load_last_score_before_outcome) is the honest evaluation set, not a
    held-out subset of a training run."""
    y = scored["is_converted"].to_numpy()
    s = scored["predicted_fit_score"].to_numpy()
    result = {
        "auc_overall": float(roc_auc_score(y, s)),
        "n_resolved": int(len(scored)),
        "n_resolved_positive": int(y.sum()),
        "base_rate": float(y.mean()),
        "by_model_version": {},
    }
    for version, group in scored.groupby("model_version"):
        gy = group["is_converted"].to_numpy()
        gs = group["predicted_fit_score"].to_numpy()
        result["by_model_version"][version] = {
            "auc": float(roc_auc_score(gy, gs)) if gy.sum() and (~gy.astype(bool)).sum() else float("nan"),
            "n": int(len(group)),
            "n_positive": int(gy.sum()),
            "base_rate": float(gy.mean()),
            "mean_predicted_fit_score": float(group["predicted_fit_score"].mean()),
        }
    return result


def bootstrap_auc_ci(scored: pd.DataFrame, seed: int = _RANDOM_SEED,
                      n_boot: int = _N_BOOTSTRAP) -> dict:
    """Seeded row-level bootstrap 90% CI on the overall AUC from
    compute_discrimination -- the one stochastic step in this module (a
    validation resampling procedure, not a model-fitting step), seeded per
    analytics-engineering-conventions."""
    y = scored["is_converted"].to_numpy()
    s = scored["predicted_fit_score"].to_numpy()
    n = len(scored)
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boots[i] = roc_auc_score(y[idx], s[idx])
    lo, hi = np.percentile(boots, [5, 95])
    return {"auc_ci90_low": float(lo), "auc_ci90_high": float(hi), "n_boot": n_boot, "seed": seed}


def compute_calibration(scored: pd.DataFrame, n_bins: int = _N_CALIBRATION_BINS) -> pd.DataFrame:
    """Decile bins of predicted_fit_score vs. actual conversion rate.

    Calibration means something different here than in health_score.py:
    predicted_fit_score is a 0-100 ICP-fit index, never fit or stated as a
    conversion probability, so there is no "mean predicted probability vs.
    actual base rate" comparison to make (unlike churn_probability, nothing
    here claims to BE a probability). The honest calibration question for a
    fixed-formula fit index is narrower: do higher-score bins carry
    materially and monotonically higher conversion rates, i.e. is the 0-100
    scale itself informative in a graded way, or only useful for a coarse
    rank ordering."""
    df = scored.copy()
    df["score_decile"] = pd.qcut(df["predicted_fit_score"], n_bins, duplicates="drop")
    calib = df.groupby("score_decile", observed=True).agg(
        conversion_rate=("is_converted", "mean"),
        n=("is_converted", "size"),
        mean_score=("predicted_fit_score", "mean"),
    ).reset_index()
    return calib


def confusion_at_operating_thresholds(scored: pd.DataFrame) -> dict:
    """Confusion matrices at the two real production operating thresholds
    predicted_segment already encodes (mirrored ENTERPRISE_FIT_THRESHOLD /
    COMMERCIAL_FIT_THRESHOLD, not an arbitrary 0.5 cutoff -- see module
    constants). Reported separately for 'Commercial-or-better' (>= 40) and
    'Enterprise-only' (>= 72) since the two carry materially different real
    lift over the base rate in this data (see methods doc entry) -- folding
    them into one threshold would hide that."""
    y = scored["is_converted"].astype(bool).to_numpy()

    def _confusion(pred_positive: np.ndarray, label: str) -> dict:
        tp = int((pred_positive & y).sum())
        fp = int((pred_positive & ~y).sum())
        fn = int((~pred_positive & y).sum())
        tn = int((~pred_positive & ~y).sum())
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / (tp + fn) if (tp + fn) else float("nan")
        f1 = (2 * precision * recall / (precision + recall)
              if precision and recall and (precision + recall) else float("nan"))
        return {
            "threshold": label,
            "true_positive": tp, "false_positive": fp,
            "true_negative": tn, "false_negative": fn,
            "precision": precision, "recall": recall, "f1": f1,
            "predicted_positive_rate": float(pred_positive.mean()),
            "base_rate": float(y.mean()),
            "lift_vs_base_rate": (precision / y.mean()) if y.mean() else float("nan"),
        }

    commercial_plus = (scored["predicted_segment"] != "SMB").to_numpy()
    enterprise_only = (scored["predicted_segment"] == "Enterprise").to_numpy()
    return {
        "commercial_or_better": _confusion(commercial_plus, f">= {_COMMERCIAL_FIT_THRESHOLD} (Commercial or better)"),
        "enterprise_only": _confusion(enterprise_only, f">= {_ENTERPRISE_FIT_THRESHOLD} (Enterprise only)"),
    }


def isolate_region_marginal_value(as_of_date: date, con=None,
                                   seed: int = _RANDOM_SEED, n_boot: int = _N_BOOTSTRAP) -> dict:
    """The trustworthy drift-detection causal read (see module docstring's
    shape note and methods doc entry). v1 and v2 never coexist for the same
    scored_at range in this data (v1 max scored_at 2024-06-30, v2 min
    scored_at 2024-07-01, per fact_lead_scoring_history) -- so directly
    comparing v1-era vs v2-era AUC (compute_regime_comparison, below)
    confounds the model-version change with any other calendar-time drift in
    the lead population itself (channel/campaign vintage mix, etc.) and
    cannot isolate region's own marginal effect.

    This function isolates it instead: for every v2-scored event (all of
    them, not just each lead's last -- employee_band_component and
    industry_component are static per lead regardless of which event, so
    this is a same-population, same-time-period, same-row A/B on one column,
    not a resample across different times), it reconstructs a "v1-
    equivalent" score by zeroing region_component
    (employee_band_component + industry_component + noise_component) and
    compares that reconstruction's AUC against the actual v2 score's AUC
    (which adds region_component back in) -- literally the same rows, held-
    out region on vs. off. Grain: one row per v2 scoring event on a resolved
    lead. Source marts: fact_lead_scoring_history, fact_leads (via
    load_resolved_leads)."""
    owns_con = con is None
    con = con or _connect()
    try:
        resolved = load_resolved_leads(as_of_date, con=con)
        hist = con.execute(
            "select lead_id, scored_at, employee_band_component, industry_component, "
            "region_component, noise_component "
            "from main_marts.fact_lead_scoring_history "
            "where model_version = 'lead_fit_v2_region_aware' and scored_at <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    hist["scored_at"] = pd.to_datetime(hist["scored_at"])
    m = hist.merge(resolved[["lead_id", "is_converted"]], on="lead_id", how="inner").reset_index(drop=True)

    m["score_with_region"] = (
        m["employee_band_component"] + m["industry_component"] + m["region_component"] + m["noise_component"]
    )
    m["score_without_region"] = m["employee_band_component"] + m["industry_component"] + m["noise_component"]

    y = m["is_converted"].to_numpy()
    s_with = m["score_with_region"].to_numpy()
    s_without = m["score_without_region"].to_numpy()
    auc_with = float(roc_auc_score(y, s_with))
    auc_without = float(roc_auc_score(y, s_without))

    # Seeded lead-level bootstrap (resample leads, not individual events, so
    # a lead's repeated scoring events move together -- the unit of
    # independent random variation here is the lead, not the event) via
    # sklearn's sample_weight, not per-resample concatenation, so this stays
    # fast at ~110k events x n_boot resamples.
    lead_ids = m["lead_id"].unique()
    lead_pos = {lid: i for i, lid in enumerate(lead_ids)}
    row_lead_idx = m["lead_id"].map(lead_pos).to_numpy()
    n_leads = len(lead_ids)
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        counts = np.bincount(rng.integers(0, n_leads, size=n_leads), minlength=n_leads)
        w = counts[row_lead_idx]
        mask = w > 0
        a_with = roc_auc_score(y[mask], s_with[mask], sample_weight=w[mask])
        a_without = roc_auc_score(y[mask], s_without[mask], sample_weight=w[mask])
        diffs[i] = a_with - a_without
    ci_lo, ci_hi = np.percentile(diffs, [5, 95])

    return {
        "auc_with_region": auc_with,
        "auc_without_region": auc_without,
        "auc_delta": auc_with - auc_without,
        "auc_delta_ci90_low": float(ci_lo),
        "auc_delta_ci90_high": float(ci_hi),
        "auc_delta_distinguishable_from_zero": bool(ci_lo > 0),
        "n_events": int(len(m)),
        "n_leads": int(n_leads),
        "mean_region_component": float(m["region_component"].mean()),
        "mean_region_component_by_outcome": {
            bool(k): float(v) for k, v in m.groupby("is_converted")["region_component"].mean().items()
        },
        "seed": seed,
        "n_boot": n_boot,
    }


def compute_regime_comparison(scored: pd.DataFrame) -> dict:
    """The direct, CONFOUNDED-with-time comparison of each model version's
    actual real-world scoring era (last-score-before-outcome AUC and mean
    predicted_fit_score, v1-era leads vs v2-era leads). Reported as context
    and because it corroborates isolate_region_marginal_value's finding
    directionally, but this comparison alone cannot separate 'the model
    changed' from 'the lead population/composition changed over the same
    calendar time' -- see that function's docstring. Not the causal claim on
    its own."""
    discrimination = compute_discrimination(scored)
    return discrimination["by_model_version"]


def compute_score_distribution_shift(as_of_date: date, con=None) -> dict:
    """Mean/std of predicted_fit_score by model_version across ALL scoring
    events (not just last-per-lead -- this is a population-level
    distributional read, independent of the outcome-validation grain above).
    Decomposes the v1->v2 mean shift into its two real, checkable sources:
    region_component's own mean contribution (structural, mechanical -- v1
    never computes a region term at all) plus any residual difference in
    employee_band_component/industry_component means between the two eras
    (real population/cohort composition drift over calendar time, not a
    model-formula effect). Source mart: fact_lead_scoring_history."""
    owns_con = con is None
    con = con or _connect()
    try:
        hist = con.execute(
            "select model_version, employee_band_component, industry_component, "
            "region_component, predicted_fit_score "
            "from main_marts.fact_lead_scoring_history where scored_at <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()

    by_version = hist.groupby("model_version").agg(
        mean_score=("predicted_fit_score", "mean"),
        std_score=("predicted_fit_score", "std"),
        mean_employee_band_component=("employee_band_component", "mean"),
        mean_industry_component=("industry_component", "mean"),
        n=("predicted_fit_score", "size"),
    )
    v1 = by_version.loc["lead_fit_v1_preregion"]
    v2 = by_version.loc["lead_fit_v2_region_aware"]
    v2_mean_region = hist.loc[hist["model_version"] == "lead_fit_v2_region_aware", "region_component"].mean()
    non_region_shift = (
        (v2["mean_employee_band_component"] - v1["mean_employee_band_component"])
        + (v2["mean_industry_component"] - v1["mean_industry_component"])
    )
    return {
        "mean_score_v1": float(v1["mean_score"]),
        "mean_score_v2": float(v2["mean_score"]),
        "std_score_v1": float(v1["std_score"]),
        "std_score_v2": float(v2["std_score"]),
        "n_v1": int(v1["n"]),
        "n_v2": int(v2["n"]),
        "total_shift": float(v2["mean_score"] - v1["mean_score"]),
        "region_explained_shift": float(v2_mean_region),
        "residual_non_region_shift": float(non_region_shift),
    }


def run_build_time_validation(as_of_date: date, log: bool = True) -> dict:
    """End-to-end build-time validation: loads the resolved-lead scoring
    population, computes discrimination (overall + by version + bootstrap
    CI), calibration bins, confusion matrices at both real operating
    thresholds, the isolated region-marginal-value causal test, the
    confounded regime comparison (context only), and the score-distribution-
    shift decomposition -- then logs the scalar time-series metrics to
    fact_model_performance_history via analytics/model_performance.py. This
    is what analytics-model-validator consumes."""
    con = _connect()
    try:
        scored = load_last_score_before_outcome(as_of_date, con=con)
        discrimination = compute_discrimination(scored)
        auc_ci = bootstrap_auc_ci(scored)
        calibration = compute_calibration(scored)
        confusion = confusion_at_operating_thresholds(scored)
        region_isolation = isolate_region_marginal_value(as_of_date, con=con)
        regime_comparison = compute_regime_comparison(scored)
        distribution_shift = compute_score_distribution_shift(as_of_date, con=con)
    finally:
        con.close()

    if log:
        log_performance(_MODEL_NAME, as_of_date, "auc_overall", discrimination["auc_overall"])
        log_performance(_MODEL_NAME, as_of_date, "auc_ci90_low", auc_ci["auc_ci90_low"])
        log_performance(_MODEL_NAME, as_of_date, "auc_ci90_high", auc_ci["auc_ci90_high"])
        log_performance(_MODEL_NAME, as_of_date, "n_resolved_leads", discrimination["n_resolved"])
        log_performance(_MODEL_NAME, as_of_date, "n_resolved_positive", discrimination["n_resolved_positive"])
        for version, stats in discrimination["by_model_version"].items():
            suffix = "v1" if "v1" in version else "v2"
            log_performance(_MODEL_NAME, as_of_date, f"auc_regime_{suffix}", stats["auc"])
            log_performance(_MODEL_NAME, as_of_date, f"n_regime_{suffix}", stats["n"])
        for key, c in confusion.items():
            log_performance(_MODEL_NAME, as_of_date, f"precision_{key}", c["precision"])
            log_performance(_MODEL_NAME, as_of_date, f"recall_{key}", c["recall"])
            log_performance(_MODEL_NAME, as_of_date, f"f1_{key}", c["f1"])
        log_performance(_MODEL_NAME, as_of_date, "region_marginal_auc_delta", region_isolation["auc_delta"])
        log_performance(_MODEL_NAME, as_of_date, "region_marginal_auc_delta_ci90_low", region_isolation["auc_delta_ci90_low"])
        log_performance(_MODEL_NAME, as_of_date, "region_marginal_auc_delta_ci90_high", region_isolation["auc_delta_ci90_high"])
        log_performance(_MODEL_NAME, as_of_date, "score_distribution_total_shift_v1_to_v2", distribution_shift["total_shift"])
        log_performance(_MODEL_NAME, as_of_date, "score_distribution_region_explained_shift", distribution_shift["region_explained_shift"])

    return {
        "as_of_date": as_of_date,
        "discrimination": discrimination,
        "auc_ci90": auc_ci,
        "calibration": calibration,
        "confusion": confusion,
        "region_isolation": region_isolation,
        "regime_comparison": regime_comparison,
        "distribution_shift": distribution_shift,
        "scored": scored,
    }


if __name__ == "__main__":
    result = run_build_time_validation(date(2025, 12, 31))
    d = result["discrimination"]
    print(f"Overall AUC: {d['auc_overall']:.4f} (90% CI {result['auc_ci90']['auc_ci90_low']:.4f}-"
          f"{result['auc_ci90']['auc_ci90_high']:.4f}), n={d['n_resolved']} (positive={d['n_resolved_positive']}, "
          f"base rate={d['base_rate']:.4f})")
    for version, stats in d["by_model_version"].items():
        print(f"  {version}: AUC={stats['auc']:.4f}, n={stats['n']} (positive={stats['n_positive']}, "
              f"base rate={stats['base_rate']:.4f}, mean score={stats['mean_predicted_fit_score']:.2f})")
    print()
    print("Calibration bins:")
    print(result["calibration"].to_string(index=False))
    print()
    print("Confusion matrices at real operating thresholds:")
    for key, c in result["confusion"].items():
        print(f"  {key}: precision={c['precision']:.4f}, recall={c['recall']:.4f}, f1={c['f1']:.4f}, "
              f"lift_vs_base_rate={c['lift_vs_base_rate']:.2f}x, n_predicted_positive="
              f"{c['true_positive'] + c['false_positive']}")
    print()
    ri = result["region_isolation"]
    print(f"Region marginal AUC delta (isolated, v2-only, same rows): {ri['auc_delta']:+.4f} "
          f"(90% CI {ri['auc_delta_ci90_low']:+.4f} to {ri['auc_delta_ci90_high']:+.4f}), "
          f"distinguishable from zero: {ri['auc_delta_distinguishable_from_zero']}, "
          f"n_events={ri['n_events']}, n_leads={ri['n_leads']}")
    print()
    ds = result["distribution_shift"]
    print(f"Score distribution shift v1->v2: {ds['total_shift']:+.2f} total "
          f"({ds['region_explained_shift']:+.2f} region-explained, "
          f"{ds['residual_non_region_shift']:+.2f} residual/cohort)")
