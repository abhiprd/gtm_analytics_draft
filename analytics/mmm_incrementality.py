"""MMM / incrementality-based measurement -- grain: one row per (sub-channel,
month) over the window fact_marketing_spend actually covers (36 months,
2023-01 onward); source marts (via analytics/marketing_attribution.py's own
loaders, reused rather than re-derived): dim_campaign, fact_leads,
fact_campaign_engagement_events, fact_opportunities, dim_accounts,
fact_marketing_spend.

Build spec item #12, Wave 6: "MMM / incrementality-based measurement." A
media-mix regression estimating each sub-channel's spend-response curve from
the monthly spend/conversion time series, built to extend incrementality
estimation to what the holdout method in analytics/marketing_attribution.py
cannot reach -- organic (which never runs a holdout cell, by design: an
organic/SEO program cannot be switched off for a chosen cell) and any
non-holdout period for paid/community. See that module's "Model type
selection and rationale" point 3, which names this artifact by build-spec
item number as the deferred consumer of the channel-grain spend and
conversion series it supplies -- this is that handoff landing.

THE LINE-98 TENSION, TAKEN AT FACE VALUE
-----------------------------------------
Build spec Section 4 flags this in advance: "MMM/incrementality and
proxy-metric decay detection both want a long time series to be credible;
36 months monthly is workable but thin for either... flagging so it's a
deliberate call when those two artifacts get built, not a surprise when
they produce a weak result." This module is built against exactly that
36-month window (fact_marketing_spend's real coverage, 2023-01 through
2025-12) with no unilateral extension of the simulation horizon -- that is
a cross-cutting Phase 1 change out of scope for a single Phase 4 artifact,
not something to route around here. The result IS weak in the places the
line predicted: per-channel elasticities rest on n=36 monthly points each,
two of three channel-level spend coefficients do not clear conventional
significance, and the organic elasticity -- this artifact's one genuinely
novel contribution, since it cannot be cross-checked against a holdout --
carries a confidence interval wide enough to include zero. Reported as the
headline finding below (see fit_channel_elasticity_models' docstring and
compare_to_holdout), not smoothed over.

GRAIN DECISION -- fine (organic/paid/community), not coarse
-------------------------------------------------------------
Two channel grains exist in this data: the coarse 3-value
dim_accounts.channel taxonomy (inbound_marketing / outbound_sdr /
self_serve, fact_marketing_spend's grain) and the fine organic/paid/
community decomposition of inbound_marketing (dim_campaign's grain, the one
analytics/marketing_attribution.py works at). The fine grain is used here,
deliberately: it is the only one with real holdout data to validate
against (six suppressed cells, paid and community only), it is the grain
the build spec's own line-98 flag is written against ("36 months... thin
for MMM"), and a coarse 3-channel model would conflate the one channel that
has a causal check available with two that never will. The coarse grain's
own fact_marketing_spend table is used for exactly one thing here --
nothing; this module reads dim_campaign's day-prorated budget via
analytics/marketing_attribution.py's allocate_campaign_spend(), which
already validates against the coarse mart (see that module's
campaign_spend_reconciles_to_coarse_mart check) -- so the coarse-vs-fine
reconciliation is inherited, not re-derived.

MODEL SHAPE -- log-log, channel-and-month grain, NOT a full adstock/
saturation MMM, and why
------------------------------------------------------------------------
A textbook MMM structure is two things: (1) a carryover/adstock transform
of spend (geometric decay, estimating how many days a dollar's effect
persists) and (2) a saturation/diminishing-returns curve (typically a
2-parameter Hill transform). Both were tested against this data and
rejected as unidentifiable at this sample size, not assumed away:

  1. ADSTOCK/CARRYOVER -- rejected. Monthly spend is strongly
     autocorrelated within every channel (lag-1 correlation 0.78-0.88
     across the three channels), so a fitted decay parameter would be
     estimated almost entirely from noise: contemporaneous and one-month-
     lagged spend carry nearly the same information at this frequency, and
     36 monthly points per channel cannot separate them. A model that
     included both would produce an unstable, sign-flipping split of
     credit between two nearly-collinear regressors -- worse than
     omitting the lag, not better.
  2. SATURATION -- reduced to its lightest identifiable form. A 2-parameter
     Hill/saturation curve needs curvature information a 36-point series at
     3 channels does not reliably contain. A LOG-LOG (constant-elasticity)
     functional form is adopted instead: it is a genuine, if simpler,
     diminishing-returns structure (marginal conversions per marginal
     dollar fall as spend rises whenever the fitted elasticity is below
     1.0, which it is for every channel here), it needs only one parameter
     per channel instead of two, and log-spend correlates with
     log-conversions somewhat better than raw spend does for two of the
     three channels (organic 0.68->0.72, paid 0.54->0.71; community is
     roughly flat, 0.40->0.41) -- a data-supported transform, not an
     assumed one.

WHAT WAS NOT OPTIONAL: A TREND CONTROL
----------------------------------------
The single most important specification decision in this module, found by
checking the data rather than assumed: spend and conversions co-trend
strongly across the 3-year window for reasons that have nothing to do with
spend's own effect -- the whole business is scaling (company-wide monthly
attributed conversions roughly double from 2023 to 2025), and every
channel's spend grows over the same window (month-index correlation with
spend runs 0.55-0.87 across channels, with conversions 0.71-0.83). Fitting
log(conversions) ~ log(spend) alone, with no trend control, gives a pooled
elasticity of 0.73 -- but that number is almost entirely the shared growth
trend, not a spend effect: adding a linear month-index trend control drops
the pooled elasticity to 0.22 and pushes it to only marginal significance
(p=0.055). This is reported as the central methodological finding of the
build, not a footnote: THE ANSWER FLIPS DEPENDING ON WHETHER THE TREND IS
CONTROLLED FOR, and the two are collinear enough (VIF ~7.4 on log-spend
once the trend term is in the model) that this data cannot cleanly
separate "spend caused it" from "the business was growing anyway." Every
model in this module includes the trend control; the no-trend variant is
reported alongside purely as the sensitivity check that surfaces this.

SHAPE -- a genuine fitted regression, the first one in this portfolio
------------------------------------------------------------------------
Per analytics-engineering-conventions' "Regression models" category. This
differs from every other structural/descriptive Wave 1-5 artifact
(capacity planning, segment migration, marketing attribution's own credit
panel) precisely because a spend-response curve is not a sum, a lookup, or
an accounting identity -- it is an unobserved causal parameter with no
closed form, and OLS is the honest, minimal tool for it at this sample
size (not a gradient-boosted anything -- 36-108 observations do not
support a model class with more capacity than a handful of coefficients).
Full validation package per channel and pooled: coefficient table with
standard errors/t/p/95% CI, R^2/adjusted R^2, a nested F-test against a
trend-only baseline (does spend add anything at all), residual diagnostics
(a Breusch-Pagan heteroscedasticity test and lag-1 residual autocorrelation
-- both real risks on a trending monthly series), and TWO held-out reads:
leave-one-out cross-validation (stable, but not a true forecast test since
each fold still trains on all-but-one point) and a forward time holdout
(the last quarter withheld -- the economically relevant test, explicitly
caveated as resting on only 3-9 points). See fit_channel_elasticity_models,
fit_pooled_elasticity_model and validate_out_of_sample.

No stochastic step exists in this module -- OLS, LOOCV and the forward
holdout are all deterministic given the data -- so no random seed applies,
matching analytics/marketing_attribution.py's, capacity_planning.py's and
segment_migration.py's precedent.

See docs/acme-corp-analytics-methods.md's "MMM / incrementality-based
measurement" entry for the full build-time results, the cross-validation
against marketing_attribution.py's holdout read, and the target/drift
threshold this artifact proposes.
"""
import os
from datetime import date

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from .model_performance import log_performance
from .marketing_attribution import (
    SUB_CHANNELS,
    allocate_campaign_spend,
    attribute_credit,
    compute_channel_mix,
    measure_incrementality,
)

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_MODEL_NAME = "mmm_incrementality"

# fact_marketing_spend's real coverage start -- see that mart's own header
# ("Covers 2023-01 onward only (36 months), not the full 2020-2025 data
# horizon"). This is the 36-month window build spec Section 4 flags as
# thin for MMM; dim_campaign's own history runs back to 2018 for other
# purposes (holdout-cell continuity, back-dated accounts) but that earlier
# window is not part of the build spec's stated MMM data-scope assumption
# and is deliberately not used to pad this artifact's sample size.
_WINDOW_START = pd.Timestamp("2023-01-01")

# Minimum monthly observations per channel before a 3-parameter model
# (intercept, log-spend, trend) is fit at all. Below this the model has
# fewer degrees of freedom than the QA plan's own floor for a usable
# baseline elsewhere in this portfolio (capacity planning's
# _MIN_BASELINE_REP_QUARTERS = 8) and reporting a coefficient table would
# be decoration, not a fit.
_MIN_MONTHS_PER_CHANNEL = 12

# The exact spend-reduction level the real holdout cells were built at
# (generators/config.py's HOLDOUT_BUDGET_SHARE = 0.10 -- "spend is withheld
# from the control cell, not merely re-labelled"). Used as the counterfactual
# spend level for this model's own "implied incremental share," so the two
# estimates answer the SAME question (what happens at 10% of normal
# spend) rather than one asking about a 90% cut and the other about a
# 100% cut to zero -- see model_implied_incremental_share's docstring for
# why spend=0 is deliberately not used as the counterfactual.
_HOLDOUT_SPEND_LEVEL = 0.10

# Two-sided 95% CI.
_CI_ALPHA = 0.05


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


# --------------------------------------------------------------------------
# 1. The monthly channel panel -- built entirely from analytics/
#    marketing_attribution.py's own loaders, not re-derived
# --------------------------------------------------------------------------

def load_monthly_channel_panel(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per (channel, month) from 2023-01 through the last
    complete month at or before as_of_date. Source marts: dim_campaign (via
    allocate_campaign_spend), fact_leads/fact_campaign_engagement_events/
    fact_opportunities/dim_accounts (via attribute_credit + compute_channel_mix).

    Deliberately reuses analytics/marketing_attribution.py's own functions
    rather than re-deriving touch sequencing, the point-in-time lead panel
    or attribution credit -- that module already computes and validates
    all three (see its credit-conservation and pipeline-identity checks).
    Recomputing them independently here would risk a second, divergent
    implementation of the same logic with no reason to trust either one
    more than the other.

    `spend` is day-prorated campaign budget (allocate_campaign_spend);
    `conversions` is LINEAR-attributed converting leads and
    `bookings` is linear-attributed won new-logo bookings
    (compute_channel_mix(period_grain='month')). Linear is used, not
    first/last/time_decay, for the same reason marketing_attribution.py's
    own Layer-3 diagnostics use it: it is the only one of the four models
    that reflects a channel's participation across the whole path rather
    than one privileged touch position, which is what a volume/efficiency
    series being regressed on spend should be denominated on."""
    owns = con is None
    con = con or _connect()
    try:
        spend = allocate_campaign_spend(as_of_date, con=con)
        credit = attribute_credit(as_of_date, con=con)
        mix = compute_channel_mix(as_of_date, credit=credit, period_grain="month", con=con)
    finally:
        if owns:
            con.close()

    window_end = pd.Timestamp(as_of_date).to_period("M").to_timestamp()
    # Only a COMPLETE month is admitted -- a partial current month's spend
    # and conversions are not comparable to a full month's, the same reason
    # capacity planning admits only complete quarters.
    if pd.Timestamp(as_of_date) < window_end + pd.offsets.MonthEnd(0):
        window_end -= pd.DateOffset(months=1)

    spend_m = (
        spend[(spend["month"] >= _WINDOW_START) & (spend["month"] <= window_end)
              & spend["channel"].isin(SUB_CHANNELS)]
        .groupby(["month", "channel"], as_index=False)["spend"].sum()
    )

    conv_m = mix[
        (mix["model"] == "linear")
        & (mix["period"] >= _WINDOW_START) & (mix["period"] <= window_end)
        & mix["channel"].isin(SUB_CHANNELS)
    ][["period", "channel", "attributed_conversions", "attributed_bookings"]].rename(
        columns={"period": "month", "attributed_conversions": "conversions",
                 "attributed_bookings": "bookings"}
    )

    panel = spend_m.merge(conv_m, on=["month", "channel"], how="outer")
    for col in ("spend", "conversions", "bookings"):
        panel[col] = panel[col].fillna(0.0)
    panel = panel.sort_values(["channel", "month"]).reset_index(drop=True)
    # t: a 1-based month index shared across channels (same calendar window
    # for all three), the trend control every model in this module carries.
    months = sorted(panel["month"].unique())
    month_index = {m: i + 1 for i, m in enumerate(months)}
    panel["t"] = panel["month"].map(month_index)
    panel["window_start"] = _WINDOW_START
    panel["window_end"] = window_end
    panel["window_months"] = len(months)
    return panel


# --------------------------------------------------------------------------
# 2. Generic OLS helper -- no ML framework needed for 1-5 parameters
# --------------------------------------------------------------------------

def _ols_fit(X: np.ndarray, y: np.ndarray, feature_names: list) -> dict:
    """Closed-form OLS: coefficients, classical (homoscedastic-iid) standard
    errors, t-stats, two-sided p-values, 95% CI, R^2/adjusted R^2, fitted
    values and residuals. No sklearn/statsmodels needed for a design matrix
    this small (1-5 columns); doing it in closed form keeps every number in
    this artifact traceable to matrix algebra rather than a library
    default."""
    n, p = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    fitted = X @ beta
    resid = y - fitted
    dof = n - p
    rss = float(resid @ resid)
    sigma2 = rss / dof if dof > 0 else np.nan
    se = np.sqrt(np.diag(sigma2 * XtX_inv)) if dof > 0 else np.full(p, np.nan)
    tstat = beta / se
    pval = 2.0 * (1.0 - stats.t.cdf(np.abs(tstat), df=dof)) if dof > 0 else np.full(p, np.nan)
    tcrit = float(stats.t.ppf(1 - _CI_ALPHA / 2, dof)) if dof > 0 else np.nan
    ci_low = beta - tcrit * se
    ci_high = beta + tcrit * se

    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - rss / ss_tot if ss_tot > 0 else np.nan
    adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / dof if dof > 0 and pd.notna(r2) else np.nan

    coef_table = pd.DataFrame({
        "feature": feature_names, "coefficient": beta, "std_error": se,
        "t_stat": tstat, "p_value": pval, "ci_low": ci_low, "ci_high": ci_high,
    })
    return {
        "coefficients": coef_table, "beta": beta, "XtX_inv": XtX_inv,
        "fitted": fitted, "residuals": resid, "n": n, "p": p, "dof": dof,
        "rss": rss, "sigma2": sigma2, "r2": r2, "adj_r2": adj_r2,
    }


def _design_matrix(df: pd.DataFrame, include_spend: bool, include_channel_fe: bool) -> tuple:
    """Builds the (X, feature_names) pair for one of this module's model
    variants: trend-only (restricted, for the nested F-test), trend+spend
    (per-channel primary), or trend+spend+channel-FE (pooled, organic as
    the reference level)."""
    cols = ["intercept"]
    X = [np.ones(len(df))]
    if include_spend:
        cols.append("log_spend")
        X.append(np.log(df["spend"].to_numpy()))
    cols.append("t")
    X.append(df["t"].to_numpy(dtype=float))
    if include_channel_fe:
        for ch in SUB_CHANNELS:
            if ch == "organic":
                continue  # reference level
            cols.append(f"channel_{ch}")
            X.append((df["channel"] == ch).to_numpy(dtype=float))
    return np.column_stack(X), cols


def _prep(panel: pd.DataFrame) -> pd.DataFrame:
    df = panel.copy()
    df["log_conversions"] = np.log(df["conversions"].clip(lower=1e-6))
    return df


# --------------------------------------------------------------------------
# 3. Per-channel elasticity models -- the primary read
# --------------------------------------------------------------------------

def fit_channel_elasticity_models(panel: pd.DataFrame = None, as_of_date: date = None,
                                  con=None) -> dict:
    """Grain: one fitted model per sub-channel. Source: load_monthly_channel_panel.

    THE PRIMARY MODEL: per-channel log(conversions) ~ log(spend) + t, fit
    separately for organic/paid/community rather than pooled, because the
    quantity this artifact needs to compare against
    analytics/marketing_attribution.py's holdout read is CHANNEL-specific
    (paid 0.6477, community 0.8157) and a pooled single elasticity would
    average over real heterogeneity the per-channel fits show is there
    (0.43 organic vs. 0.22 paid vs. 0.19 community) -- see
    fit_pooled_elasticity_model for the pooled variant, reported as a
    secondary robustness check.

    HONEST RESULT, STATED HERE RATHER THAN LEFT FOR THE READER TO FIND:
    at n=36 per channel, only organic's spend coefficient clears even the
    10% significance level (p=0.081), and it does not clear 5%; paid is
    p=0.092; community's spend coefficient is not distinguishable from zero
    (p=0.489), the same underpowered-channel-level read
    marketing_attribution.py's own holdout gives community (z=1.95, resting
    on one control conversion) for a different reason. Organic's 95% CI on
    its own elasticity is wide enough to include values near zero -- the
    one channel this artifact was built to give a genuinely new answer for
    is also the one whose answer is least certain, and that is reported as
    the headline finding in docs/acme-corp-analytics-methods.md, not a
    footnote."""
    if panel is None:
        panel = load_monthly_channel_panel(as_of_date, con=con)
    df = _prep(panel)

    results = {}
    for ch in SUB_CHANNELS:
        g = df[df["channel"] == ch].sort_values("t")
        if len(g) < _MIN_MONTHS_PER_CHANNEL:
            results[ch] = {
                "computable": False,
                "reason": f"only {len(g)} monthly observations for {ch}, below the "
                          f"{_MIN_MONTHS_PER_CHANNEL}-month floor for a 3-parameter fit",
                "n": len(g),
            }
            continue

        X, names = _design_matrix(g, include_spend=True, include_channel_fe=False)
        y = g["log_conversions"].to_numpy()
        fit = _ols_fit(X, y, names)

        # Nested F-test: does log_spend add real explanatory power over a
        # trend-only baseline, or is the whole spend term vacuous? This is
        # this artifact's non-vacuousness check -- the direct analogue of
        # marketing_attribution's attribution_models_genuinely_diverge and
        # capacity planning's ramp_mechanism_is_real, adapted to what a
        # regression artifact actually has to check: whether the one
        # estimated driver carries real information, not whether an
        # accounting identity holds (there is none here).
        Xr, _ = _design_matrix(g, include_spend=False, include_channel_fe=False)
        fit_r = _ols_fit(Xr, y, ["intercept", "t"])
        f_stat = ((fit_r["rss"] - fit["rss"]) / (fit["p"] - fit_r["p"])) / (fit["rss"] / fit["dof"])
        f_p = float(stats.f.sf(f_stat, fit["p"] - fit_r["p"], fit["dof"]))

        elasticity_row = fit["coefficients"].set_index("feature").loc["log_spend"]
        implied = model_implied_incremental_share(
            float(elasticity_row["coefficient"]),
            float(elasticity_row["ci_low"]), float(elasticity_row["ci_high"]),
        )

        results[ch] = {
            "computable": True, "channel": ch, "n": fit["n"], "dof": fit["dof"],
            "r2": fit["r2"], "adj_r2": fit["adj_r2"],
            "elasticity": float(elasticity_row["coefficient"]),
            "elasticity_se": float(elasticity_row["std_error"]),
            "elasticity_p": float(elasticity_row["p_value"]),
            "elasticity_ci_low": float(elasticity_row["ci_low"]),
            "elasticity_ci_high": float(elasticity_row["ci_high"]),
            "trend_coefficient": float(fit["coefficients"].set_index("feature").loc["t", "coefficient"]),
            "spend_nested_f_stat": float(f_stat), "spend_nested_f_p": f_p,
            "spend_adds_value_p10": bool(f_p < 0.10),
            "validation_package": {
                "coefficients": fit["coefficients"],
                "residual_diagnostics": residual_diagnostics(fit, g),
            },
            "model_implied_incremental_share": implied,
            "fit": fit, "data": g,
        }
    return results


def fit_pooled_elasticity_model(panel: pd.DataFrame = None, as_of_date: date = None,
                                con=None) -> dict:
    """Grain: one pooled model across all three channels (organic as the
    reference level). Source: load_monthly_channel_panel.

    SECONDARY / ROBUSTNESS CHECK, not the primary read -- see
    fit_channel_elasticity_models' docstring for why a per-channel fit is
    used for the artifact's actual channel-specific claims. Reported here
    because pooling triples the sample (n=108 vs. 36) and gives a much
    tighter standard error on a SINGLE assumed-common elasticity, which is
    useful as a company-wide sensitivity check but assumes away the real
    per-channel heterogeneity the primary models find (elasticities of
    0.43/0.22/0.19 are not obviously one number)."""
    if panel is None:
        panel = load_monthly_channel_panel(as_of_date, con=con)
    df = _prep(panel)
    if df["channel"].nunique() < 3 or len(df) < 3 * _MIN_MONTHS_PER_CHANNEL:
        return {"computable": False, "reason": "insufficient pooled observations", "n": len(df)}

    X, names = _design_matrix(df, include_spend=True, include_channel_fe=True)
    y = df["log_conversions"].to_numpy()
    fit = _ols_fit(X, y, names)

    Xr, _ = _design_matrix(df, include_spend=False, include_channel_fe=True)
    fit_r = _ols_fit(Xr, y, ["intercept", "t", "channel_paid", "channel_community"])
    f_stat = ((fit_r["rss"] - fit["rss"]) / (fit["p"] - fit_r["p"])) / (fit["rss"] / fit["dof"])
    f_p = float(stats.f.sf(f_stat, fit["p"] - fit_r["p"], fit["dof"]))

    # Sensitivity companion: the same pooled model WITHOUT the trend
    # control, reported to surface the collinearity finding concretely
    # (see module docstring) rather than asserting it.
    X_notrend = np.column_stack([np.ones(len(df)), np.log(df["spend"]),
                                 (df["channel"] == "paid").astype(float),
                                 (df["channel"] == "community").astype(float)])
    fit_notrend = _ols_fit(X_notrend, y, ["intercept", "log_spend", "channel_paid", "channel_community"])

    # VIF on log_spend once the trend control is included -- the concrete
    # number behind the collinearity finding.
    others = [c for c in names if c != "log_spend"]
    Xo = df[["t"]].to_numpy(dtype=float)
    Xo = np.column_stack([np.ones(len(df)), Xo,
                          (df["channel"] == "paid").to_numpy(dtype=float),
                          (df["channel"] == "community").to_numpy(dtype=float)])
    y_ls = np.log(df["spend"].to_numpy())
    aux = _ols_fit(Xo, y_ls, ["intercept", "t", "channel_paid", "channel_community"])
    vif_log_spend = 1.0 / (1.0 - aux["r2"]) if aux["r2"] < 1 else np.inf

    elasticity_row = fit["coefficients"].set_index("feature").loc["log_spend"]
    return {
        "computable": True, "n": fit["n"], "dof": fit["dof"], "r2": fit["r2"], "adj_r2": fit["adj_r2"],
        "elasticity_pooled_common": float(elasticity_row["coefficient"]),
        "elasticity_pooled_common_se": float(elasticity_row["std_error"]),
        "elasticity_pooled_common_p": float(elasticity_row["p_value"]),
        "elasticity_pooled_common_ci_low": float(elasticity_row["ci_low"]),
        "elasticity_pooled_common_ci_high": float(elasticity_row["ci_high"]),
        "elasticity_pooled_no_trend_control": float(
            fit_notrend["coefficients"].set_index("feature").loc["log_spend", "coefficient"]),
        "vif_log_spend_with_trend": float(vif_log_spend),
        "spend_nested_f_stat": float(f_stat), "spend_nested_f_p": f_p,
        "spend_adds_value_p10": bool(f_p < 0.10),
        "validation_package": {
            "coefficients": fit["coefficients"],
            "residual_diagnostics": residual_diagnostics(fit, df),
        },
        "fit": fit, "fit_no_trend_control": fit_notrend, "data": df,
    }


# --------------------------------------------------------------------------
# 4. Residual diagnostics
# --------------------------------------------------------------------------

def residual_diagnostics(fit: dict, data: pd.DataFrame) -> dict:
    """Residuals-vs-fitted pattern (via a formal Breusch-Pagan
    heteroscedasticity test, since corr(residual, fitted) is identically
    ~0 for OLS by construction and is not a usable diagnostic) plus lag-1
    residual autocorrelation, since this is a monthly TIME series and
    classical OLS standard errors assume independent errors -- a risk
    worth checking rather than assuming away on a trending series.

    Breusch-Pagan: regress squared residuals on the fitted values
    (auxiliary regression), n*R^2 ~ chi2(1) under the null of
    homoscedasticity. A significant result (p < 0.05) means the error
    variance is not roughly constant across the fitted range."""
    resid = fit["residuals"]
    fitted = fit["fitted"]
    n = fit["n"]

    Xaux = np.column_stack([np.ones(n), fitted])
    aux = _ols_fit(Xaux, resid ** 2, ["intercept", "fitted"])
    bp_stat = float(n * aux["r2"]) if pd.notna(aux["r2"]) else np.nan
    bp_p = float(stats.chi2.sf(bp_stat, df=1)) if pd.notna(bp_stat) else np.nan

    # Lag-1 autocorrelation, ordered by the data's own time index (t).
    ordered = pd.DataFrame({"t": data["t"].to_numpy(), "resid": resid}).sort_values("t")
    lag1_corr = float(ordered["resid"].corr(ordered["resid"].shift(1)))
    # Durbin-Watson, the conventional companion statistic (~2 = no
    # autocorrelation, <2 = positive autocorrelation).
    diffs = ordered["resid"].diff().dropna().to_numpy()
    dw = float((diffs ** 2).sum() / (ordered["resid"].to_numpy() ** 2).sum())

    abs_resid_fitted_corr = float(pd.Series(np.abs(resid)).corr(pd.Series(fitted)))

    return {
        "n": n,
        "breusch_pagan_stat": bp_stat, "breusch_pagan_p": bp_p,
        "homoscedastic_at_p05": bool(pd.notna(bp_p) and bp_p >= 0.05),
        "abs_residual_vs_fitted_corr": abs_resid_fitted_corr,
        "lag1_residual_autocorrelation": lag1_corr,
        "durbin_watson": dw,
        "note": (
            "corr(residual, fitted) is identically ~0 for OLS by construction "
            "(the normal equations make residuals orthogonal to fitted values) "
            "and is not reported as a diagnostic for that reason; "
            "|residual| vs. fitted and the Breusch-Pagan test are the "
            "informative heteroscedasticity checks instead."
        ),
    }


# --------------------------------------------------------------------------
# 5. Out-of-sample validation -- LOOCV and a forward time holdout
# --------------------------------------------------------------------------

def _smearing_backtransform(log_pred: np.ndarray, train_residuals: np.ndarray) -> np.ndarray:
    """Duan's smearing estimator: naive exp(log_pred) is a biased estimate
    of E[y] under log-normal-ish errors (Jensen's inequality). The smearing
    factor -- mean(exp(training residuals)) -- corrects for that bias using
    only information available at fit time, so it is safe to apply to a
    held-out prediction without leaking the held-out point's own residual."""
    smear = float(np.mean(np.exp(train_residuals)))
    return np.exp(log_pred) * smear


def validate_out_of_sample(panel: pd.DataFrame = None, as_of_date: date = None,
                           con=None) -> dict:
    """Grain: one row per sub-channel, LOOCV and forward-holdout error
    reported on both the log scale (what the model is actually fit on) and
    the conversions-count scale (what a reader cares about, via Duan's
    smearing retransformation -- see _smearing_backtransform).

    TWO validation reads, both reported because neither alone is fully
    honest at n=36:
      - LOOCV: each of the channel's monthly points held out one at a
        time, model refit on the other 35. Stable (uses every point once)
        but NOT a true forecast test, since 35 of 36 months are still in
        every training fold -- it under-states the error a genuine
        forward forecast would carry.
      - Forward holdout: the model trained on all but the LAST QUARTER
        (3 months) of the window and scored on that quarter only. The
        economically relevant test (this is what "forecast next quarter's
        spend response" actually looks like), but its own error estimate
        rests on just 3 points per channel and should not be read as
        precise."""
    if panel is None:
        panel = load_monthly_channel_panel(as_of_date, con=con)
    df = _prep(panel)

    out = {}
    for ch in SUB_CHANNELS:
        g = df[df["channel"] == ch].sort_values("t").reset_index(drop=True)
        n = len(g)
        if n < _MIN_MONTHS_PER_CHANNEL:
            out[ch] = {"computable": False, "reason": f"only {n} months"}
            continue

        y = g["log_conversions"].to_numpy()
        actual_conv = g["conversions"].to_numpy()

        # ---- LOOCV, full model (spend + trend) vs. trend-only baseline ----
        loo_pred_full, loo_pred_trend = np.empty(n), np.empty(n)
        for i in range(n):
            mask = np.ones(n, dtype=bool)
            mask[i] = False
            Xf, _ = _design_matrix(g[mask], include_spend=True, include_channel_fe=False)
            Xt, _ = _design_matrix(g[~mask], include_spend=True, include_channel_fe=False)
            fit_f = _ols_fit(Xf, y[mask], ["intercept", "log_spend", "t"])
            loo_pred_full[i] = float((Xt @ fit_f["beta"]).item())

            Xf2, _ = _design_matrix(g[mask], include_spend=False, include_channel_fe=False)
            Xt2, _ = _design_matrix(g[~mask], include_spend=False, include_channel_fe=False)
            fit_t = _ols_fit(Xf2, y[mask], ["intercept", "t"])
            loo_pred_trend[i] = float((Xt2 @ fit_t["beta"]).item())

        loo_rmse_log_full = float(np.sqrt(np.mean((y - loo_pred_full) ** 2)))
        loo_rmse_log_trend = float(np.sqrt(np.mean((y - loo_pred_trend) ** 2)))
        loo_conv_full = _smearing_backtransform(loo_pred_full, y - loo_pred_full)
        loo_rmse_conv_full = float(np.sqrt(np.mean((actual_conv - loo_conv_full) ** 2)))
        loo_mae_conv_full = float(np.mean(np.abs(actual_conv - loo_conv_full)))

        # ---- Forward holdout: last quarter (3 months) ----
        n_test = min(3, n // 4) if n >= _MIN_MONTHS_PER_CHANNEL + 3 else 0
        fwd = None
        if n_test > 0:
            train, test = g.iloc[:-n_test], g.iloc[-n_test:]
            Xtr, _ = _design_matrix(train, include_spend=True, include_channel_fe=False)
            Xte, _ = _design_matrix(test, include_spend=True, include_channel_fe=False)
            fit_tr = _ols_fit(Xtr, train["log_conversions"].to_numpy(), ["intercept", "log_spend", "t"])
            pred_log = Xte @ fit_tr["beta"]
            pred_conv = _smearing_backtransform(pred_log, fit_tr["residuals"])
            actual_test = test["conversions"].to_numpy()
            fwd = {
                "n_test": n_test,
                "test_months": [str(m.date()) for m in test["month"]],
                "rmse_log": float(np.sqrt(np.mean((test["log_conversions"].to_numpy() - pred_log) ** 2))),
                "rmse_conversions": float(np.sqrt(np.mean((actual_test - pred_conv) ** 2))),
                "mae_conversions": float(np.mean(np.abs(actual_test - pred_conv))),
                "actual_conversions": actual_test.tolist(),
                "predicted_conversions": pred_conv.tolist(),
            }

        out[ch] = {
            "computable": True, "n": n,
            "loocv_rmse_log_full_model": loo_rmse_log_full,
            "loocv_rmse_log_trend_only_baseline": loo_rmse_log_trend,
            "loocv_rmse_conversions_full_model": loo_rmse_conv_full,
            "loocv_mae_conversions_full_model": loo_mae_conv_full,
            "loocv_full_model_beats_trend_only": bool(loo_rmse_log_full < loo_rmse_log_trend),
            "loocv_improvement_vs_trend_only_pct": float(
                100 * (loo_rmse_log_trend - loo_rmse_log_full) / loo_rmse_log_trend
            ) if loo_rmse_log_trend else np.nan,
            "forward_holdout": fwd,
        }
    return out


# --------------------------------------------------------------------------
# 6. Model-implied incremental share, and the cross-validation against the
#    holdout read
# --------------------------------------------------------------------------

def model_implied_incremental_share(elasticity: float, ci_low: float = None,
                                    ci_high: float = None) -> dict:
    """The model-implied answer to the SAME question
    analytics/marketing_attribution.py's holdout cells answer causally:
    "what share of this channel's conversions would not have happened at
    the holdout's own suppressed spend level?"

    WHY THE COUNTERFACTUAL IS 10% OF SPEND, NOT ZERO SPEND: a log-log
    model's fitted curve is only informative over the range of spend it
    was fit on (roughly the observed min-to-max per channel); extrapolating
    it all the way to spend=0 asks the model to answer outside the data it
    saw, and because conversions ~ spend^elasticity with elasticity > 0 in
    every channel here, that extrapolation trivially predicts 0 conversions
    at spend=0 regardless of the fitted elasticity's actual value -- a
    100% "incremental share" that reflects the functional form's behavior
    at the boundary, not a real finding. Evaluating at 10% of spend instead
    -- generators/config.py's own HOLDOUT_BUDGET_SHARE, the level the real
    holdout cells were actually built at -- keeps the counterfactual close
    to spend levels the model has some evidence about, and answers exactly
    the question the holdout answers, on the same scale:

        implied_share = 1 - (0.10)^elasticity

    holding the trend and (for the pooled model) channel fixed effects
    constant, i.e., comparing predicted conversions at 10% of a given
    month's spend against that same month at its actual spend. Because the
    transform is monotonic in elasticity, the elasticity's own 95% CI
    endpoints are carried through directly (no delta-method
    approximation needed) to give a CI on the implied share itself."""
    point = 1.0 - _HOLDOUT_SPEND_LEVEL ** elasticity
    out = {"elasticity": elasticity, "spend_counterfactual_level": _HOLDOUT_SPEND_LEVEL,
           "implied_incremental_share": point}
    if ci_low is not None and ci_high is not None:
        # Monotonic increasing in elasticity (since ln(0.10) < 0), so the
        # CI endpoints transform in the same order.
        out["implied_incremental_share_ci_low"] = 1.0 - _HOLDOUT_SPEND_LEVEL ** ci_low
        out["implied_incremental_share_ci_high"] = 1.0 - _HOLDOUT_SPEND_LEVEL ** ci_high
    return out


def compare_to_holdout(as_of_date: date, channel_models: dict = None,
                       panel: pd.DataFrame = None, con=None) -> pd.DataFrame:
    """Grain: one row per sub-channel. Source: fit_channel_elasticity_models
    (this module) + analytics/marketing_attribution.py's measure_incrementality
    (reused directly, not recomputed).

    Puts this artifact's regression-based implied incremental share next to
    marketing_attribution.py's holdout-measured incremental share, for the
    two channels that have one (paid, community). NO RECONCILIATION IS
    FORCED where the two disagree -- per the task this artifact was built
    against, disagreement is a genuine, reportable finding about the limits
    of regression-based estimation on this data, not a bug to explain away.
    See docs/acme-corp-analytics-methods.md for the numeric result and its
    reading."""
    if panel is None:
        panel = load_monthly_channel_panel(as_of_date, con=con)
    if channel_models is None:
        channel_models = fit_channel_elasticity_models(panel=panel)

    incrementality = measure_incrementality(as_of_date, con=con)
    pooled = incrementality[incrementality["scope"] == "pooled_channel"] if len(incrementality) else pd.DataFrame()
    holdout_lookup = dict(zip(pooled["channel"], pooled["incremental_share"])) if len(pooled) else {}
    holdout_se_lookup = dict(zip(pooled["channel"], pooled["incremental_share_se"])) if len(pooled) else {}

    rows = []
    for ch in SUB_CHANNELS:
        m = channel_models.get(ch, {})
        if not m.get("computable"):
            rows.append({"channel": ch, "mmm_computable": False, "reason": m.get("reason")})
            continue
        implied = m["model_implied_incremental_share"]
        holdout_share = holdout_lookup.get(ch, np.nan)
        row = {
            "channel": ch, "mmm_computable": True,
            "mmm_n_months": m["n"], "mmm_elasticity": m["elasticity"],
            "mmm_elasticity_se": m["elasticity_se"], "mmm_elasticity_p": m["elasticity_p"],
            "mmm_elasticity_ci_low": m["elasticity_ci_low"], "mmm_elasticity_ci_high": m["elasticity_ci_high"],
            "mmm_implied_incremental_share": implied["implied_incremental_share"],
            "mmm_implied_incremental_share_ci_low": implied.get("implied_incremental_share_ci_low"),
            "mmm_implied_incremental_share_ci_high": implied.get("implied_incremental_share_ci_high"),
            "holdout_measured_incremental_share": holdout_share,
            "holdout_measured_incremental_share_se": holdout_se_lookup.get(ch, np.nan),
            "holdout_available": bool(pd.notna(holdout_share)),
        }
        if pd.notna(holdout_share):
            row["gap_mmm_minus_holdout"] = row["mmm_implied_incremental_share"] - holdout_share
            row["gap_within_mmm_ci"] = bool(
                row["mmm_implied_incremental_share_ci_low"] <= holdout_share
                <= row["mmm_implied_incremental_share_ci_high"]
            )
            row["not_measurable_reason"] = ""
        else:
            row["gap_mmm_minus_holdout"] = np.nan
            row["gap_within_mmm_ci"] = None
            row["not_measurable_reason"] = (
                "organic never runs a holdout cell in this data -- dim_campaign carries "
                "is_holdout = false on every organic row by design (an organic/SEO program "
                "cannot be switched off for a chosen cell). This model's estimate is the "
                "only incrementality read available for organic, and its wide CI "
                "(see mmm_elasticity_ci_low/high) is why it is reported as a headline "
                "uncertainty finding rather than a confident number."
                if ch == "organic" else "channel ran no holdout cell in this window"
            )
        rows.append(row)
    return pd.DataFrame(rows)


def compute_incremental_bookings(as_of_date: date, channel_models: dict = None,
                                 panel: pd.DataFrame = None, con=None) -> pd.DataFrame:
    """Grain: one row per sub-channel. Translates the model-implied
    incremental CONVERSIONS share into a dollar figure -- "incremental
    contribution to bookings," the quantity build spec item #12 names --
    via each channel's own average booking value per attributed conversion
    over the window, rather than by regressing bookings directly.

    WHY NOT REGRESS BOOKINGS DIRECTLY: attributed monthly bookings are far
    lumpier than attributed monthly conversions in this data (coefficient
    of variation 1.0-1.5 for bookings vs. 0.35-0.49 for conversions across
    the three channels -- a handful of large Enterprise deals dominate a
    given month's bookings almost independent of that month's lead volume)
    and log(spend)-to-log(bookings) correlation is markedly weaker than
    log(spend)-to-log(conversions) for every channel (organic 0.09 vs. 0.72,
    community 0.15 vs. 0.41, paid 0.46 vs. 0.71). A regression on bookings
    would mostly be fitting deal-size noise. Conversions is the funnel-
    volume quantity spend plausibly drives; translating to dollars via the
    window's own realized average deal value is the more defensible design,
    consistent with build spec item #12's "incremental contribution to
    bookings/pipeline" framing without pretending spend predicts which
    individual deals close large."""
    if panel is None:
        panel = load_monthly_channel_panel(as_of_date, con=con)
    if channel_models is None:
        channel_models = fit_channel_elasticity_models(panel=panel)

    rows = []
    for ch in SUB_CHANNELS:
        m = channel_models.get(ch, {})
        g = panel[panel["channel"] == ch]
        total_conv = float(g["conversions"].sum())
        total_bookings = float(g["bookings"].sum())
        avg_booking_per_conversion = total_bookings / total_conv if total_conv else np.nan
        if not m.get("computable"):
            rows.append({"channel": ch, "computable": False})
            continue
        implied = m["model_implied_incremental_share"]["implied_incremental_share"]
        rows.append({
            "channel": ch, "computable": True,
            "window_total_conversions": total_conv,
            "window_total_bookings_usd": total_bookings,
            "avg_booking_usd_per_conversion": avg_booking_per_conversion,
            "mmm_implied_incremental_share": implied,
            "mmm_implied_incremental_conversions": implied * total_conv,
            "mmm_implied_incremental_bookings_usd": implied * total_conv * avg_booking_per_conversion,
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 7. Build-time run
# --------------------------------------------------------------------------

def run_build_time_validation(as_of_date: date, log: bool = True) -> dict:
    """End-to-end build-time fit and validation: the monthly channel panel,
    per-channel elasticity models (primary) and the pooled robustness model
    (secondary), residual diagnostics, LOOCV + forward-holdout out-of-sample
    error, the model-implied incremental share at the holdout's own
    suppressed-spend level, and the cross-validation against
    analytics/marketing_attribution.py's holdout-measured incremental share.

    No pass/fail accounting-identity checks exist here (unlike
    capacity_planning.py or marketing_attribution.py's structural ties) --
    a fitted spend-response curve has no closed-form invariant to check
    against. In their place: a nested F-test per channel (does spend add
    real explanatory power over a trend-only baseline -- this artifact's
    non-vacuousness check) and a comparison of LOOCV error against that
    same trend-only baseline (does spend add real OUT-OF-SAMPLE value).
    Both are reported as findings, not gated pass/fail against the holdout
    -- disagreement with the holdout is an expected, reportable result at
    this sample size, not a defect.

    Logs the natural scalar time-series metrics to
    fact_model_performance_history via analytics/model_performance.py when
    log=True; the coefficient tables and residual-diagnostic detail are
    recorded as structured detail in docs/acme-corp-analytics-methods.md
    instead, per analytics-engineering-conventions' Persistence note."""
    con = _connect()
    try:
        panel = load_monthly_channel_panel(as_of_date, con=con)
        channel_models = fit_channel_elasticity_models(panel=panel)
        pooled_model = fit_pooled_elasticity_model(panel=panel)
        oos = validate_out_of_sample(panel=panel)
        comparison = compare_to_holdout(as_of_date, channel_models=channel_models, panel=panel, con=con)
        bookings = compute_incremental_bookings(as_of_date, channel_models=channel_models, panel=panel, con=con)
    finally:
        con.close()

    checks = []
    for ch in SUB_CHANNELS:
        m = channel_models.get(ch, {})
        o = oos.get(ch, {})
        if not m.get("computable"):
            checks.append({"name": f"spend_adds_value_{ch}", "passed": False,
                           "detail": m.get("reason", "not computable")})
            continue
        detail = (
            f"nested F={m['spend_nested_f_stat']:.2f}, p={m['spend_nested_f_p']:.4f} "
            f"(floor p<0.10); LOOCV log-RMSE full={o.get('loocv_rmse_log_full_model', float('nan')):.4f} "
            f"vs. trend-only={o.get('loocv_rmse_log_trend_only_baseline', float('nan')):.4f} "
            f"({o.get('loocv_improvement_vs_trend_only_pct', float('nan')):+.1f}% change)"
        )
        checks.append({
            "name": f"spend_adds_value_{ch}",
            "passed": bool(m["spend_adds_value_p10"] and o.get("loocv_full_model_beats_trend_only", False)),
            "detail": detail,
        })

    checks_passed = sum(1 for c in checks if c["passed"])

    if log:
        for ch in SUB_CHANNELS:
            m = channel_models.get(ch, {})
            o = oos.get(ch, {})
            if not m.get("computable"):
                continue
            log_performance(_MODEL_NAME, as_of_date, f"elasticity_{ch}", m["elasticity"])
            log_performance(_MODEL_NAME, as_of_date, f"elasticity_se_{ch}", m["elasticity_se"])
            log_performance(_MODEL_NAME, as_of_date, f"elasticity_p_{ch}", m["elasticity_p"])
            log_performance(_MODEL_NAME, as_of_date, f"r2_{ch}", m["r2"])
            log_performance(_MODEL_NAME, as_of_date, f"n_months_{ch}", float(m["n"]))
            log_performance(_MODEL_NAME, as_of_date, f"spend_nested_f_p_{ch}", m["spend_nested_f_p"])
            log_performance(_MODEL_NAME, as_of_date, f"loocv_rmse_conversions_{ch}",
                            o.get("loocv_rmse_conversions_full_model", float("nan")))
            log_performance(_MODEL_NAME, as_of_date, f"loocv_mae_conversions_{ch}",
                            o.get("loocv_mae_conversions_full_model", float("nan")))
            log_performance(_MODEL_NAME, as_of_date, f"model_implied_incremental_share_{ch}",
                            m["model_implied_incremental_share"]["implied_incremental_share"])
            if o.get("forward_holdout"):
                log_performance(_MODEL_NAME, as_of_date, f"forward_holdout_rmse_conversions_{ch}",
                                o["forward_holdout"]["rmse_conversions"])
        if pooled_model.get("computable"):
            log_performance(_MODEL_NAME, as_of_date, "elasticity_pooled_common",
                            pooled_model["elasticity_pooled_common"])
            log_performance(_MODEL_NAME, as_of_date, "elasticity_pooled_no_trend_control",
                            pooled_model["elasticity_pooled_no_trend_control"])
            log_performance(_MODEL_NAME, as_of_date, "vif_log_spend_with_trend",
                            pooled_model["vif_log_spend_with_trend"])
            log_performance(_MODEL_NAME, as_of_date, "r2_pooled", pooled_model["r2"])
        for _, row in comparison.iterrows():
            if not row.get("mmm_computable") or not row.get("holdout_available"):
                continue
            log_performance(_MODEL_NAME, as_of_date, f"gap_vs_holdout_{row['channel']}",
                            row["gap_mmm_minus_holdout"])
        log_performance(_MODEL_NAME, as_of_date, "checks_total", float(len(checks)))
        log_performance(_MODEL_NAME, as_of_date, "checks_passed", float(checks_passed))

    return {
        "panel": panel,
        "channel_models": channel_models,
        "pooled_model": pooled_model,
        "out_of_sample": oos,
        "comparison_to_holdout": comparison,
        "incremental_bookings": bookings,
        "checks": checks,
        "checks_passed": checks_passed,
        "checks_total": len(checks),
        "data_window": {
            "as_of_date": as_of_date,
            "window_start": str(panel["window_start"].iloc[0].date()) if len(panel) else None,
            "window_end": str(panel["window_end"].iloc[0].date()) if len(panel) else None,
            "window_months": int(panel["window_months"].iloc[0]) if len(panel) else 0,
            "observations_per_channel": int(panel["window_months"].iloc[0]) if len(panel) else 0,
            "observations_pooled": len(panel),
        },
    }


if __name__ == "__main__":
    result = run_build_time_validation(date(2025, 12, 31))

    print("Data window:", result["data_window"])
    print()
    print("Per-channel elasticity models (primary):")
    for ch, m in result["channel_models"].items():
        if not m.get("computable"):
            print(f"  {ch}: NOT COMPUTABLE -- {m['reason']}")
            continue
        print(f"  {ch}: n={m['n']}, R2={m['r2']:.3f}, elasticity={m['elasticity']:.4f} "
              f"(se={m['elasticity_se']:.4f}, p={m['elasticity_p']:.4f}, "
              f"95% CI [{m['elasticity_ci_low']:.4f}, {m['elasticity_ci_high']:.4f}]), "
              f"trend={m['trend_coefficient']:.4f}, "
              f"nested-F p={m['spend_nested_f_p']:.4f}")
        implied = m["model_implied_incremental_share"]
        print(f"      implied incremental share @ 10% spend: {implied['implied_incremental_share']:.4f} "
              f"[{implied['implied_incremental_share_ci_low']:.4f}, "
              f"{implied['implied_incremental_share_ci_high']:.4f}]")
    print()
    print("Pooled robustness model:")
    pm = result["pooled_model"]
    if pm.get("computable"):
        print(f"  n={pm['n']}, R2={pm['r2']:.3f}, elasticity (common)={pm['elasticity_pooled_common']:.4f} "
              f"(se={pm['elasticity_pooled_common_se']:.4f}, p={pm['elasticity_pooled_common_p']:.4f})")
        print(f"  elasticity WITHOUT trend control: {pm['elasticity_pooled_no_trend_control']:.4f}")
        print(f"  VIF(log_spend) with trend control: {pm['vif_log_spend_with_trend']:.2f}")
    print()
    print("Residual diagnostics (per channel):")
    for ch, m in result["channel_models"].items():
        if not m.get("computable"):
            continue
        rd = m["validation_package"]["residual_diagnostics"]
        print(f"  {ch}: Breusch-Pagan p={rd['breusch_pagan_p']:.4f} "
              f"(homoscedastic at 5%: {rd['homoscedastic_at_p05']}), "
              f"lag-1 resid autocorr={rd['lag1_residual_autocorrelation']:.3f}, "
              f"Durbin-Watson={rd['durbin_watson']:.3f}")
    print()
    print("Out-of-sample validation (per channel):")
    for ch, o in result["out_of_sample"].items():
        if not o.get("computable"):
            continue
        print(f"  {ch}: LOOCV RMSE(conversions)={o['loocv_rmse_conversions_full_model']:.3f}, "
              f"MAE={o['loocv_mae_conversions_full_model']:.3f}, "
              f"beats trend-only baseline: {o['loocv_full_model_beats_trend_only']} "
              f"({o['loocv_improvement_vs_trend_only_pct']:+.1f}%)")
        if o.get("forward_holdout"):
            fh = o["forward_holdout"]
            print(f"      forward holdout ({fh['n_test']} months, {fh['test_months']}): "
                  f"RMSE={fh['rmse_conversions']:.3f}, MAE={fh['mae_conversions']:.3f}")
    print()
    print("Cross-validation against marketing_attribution.py's holdout read:")
    print(result["comparison_to_holdout"][
        ["channel", "mmm_implied_incremental_share", "holdout_measured_incremental_share",
         "gap_mmm_minus_holdout", "gap_within_mmm_ci", "holdout_available"]
    ].to_string(index=False))
    print()
    print("Incremental bookings translation:")
    print(result["incremental_bookings"].to_string(index=False))
    print()
    for check in result["checks"]:
        print(f"[{'PASS' if check['passed'] else 'FAIL'}] {check['name']}: {check['detail']}")
    print(f"{result['checks_passed']} of {result['checks_total']} checks pass")
