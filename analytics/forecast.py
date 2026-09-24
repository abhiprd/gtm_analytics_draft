"""Forecast -- grain: one row per (period, segment) forecast lens, where
period is a fiscal quarter and segment is Commercial or Enterprise; source
marts: fact_forecast_submissions, fact_opportunities,
fact_opportunity_stage_history, fact_cro_forecast_adjustments, dim_reps and
mart_account_health.

Build spec item #2, the second Wave 2 artifact: "Forecast (sales bottoms-up
+ ML/regression + CRO overlay)". Three lenses on one question -- how much
will close this period -- reconciled against each other rather than
collapsed into a single number, because the places they disagree are the
artifact's actual signal.

SHAPE -- HYBRID, NOT ONE TYPE
-----------------------------
This artifact is deliberately not one of analytics-engineering-conventions'
three categories end to end. It is two of them bolted together, and saying
so is more honest than forcing one validation style onto all of it:

  * Components 1, 3 and 4 (bottoms-up roll-up, CRO overlay, reconciliation)
    are STRUCTURAL/LOGIC. Nothing is fitted. A probability weight is
    estimated from observed history, but the roll-up itself is an exact
    weighted sum, the overlay is a lookup of a logged number, and the
    reconciliation is a spread. No coefficient table, no AUC, no confusion
    matrix and no R^2 applies to any of them; their correctness checks are
    structural tie-outs and non-vacuousness checks (see
    run_build_time_validation).
  * Component 2 (the ML lens) is a genuine CLASSIFICATION model and carries
    the full classification validation package that category requires:
    model-choice rationale, full coefficient table, held-out AUC, confusion
    matrix at a real operating threshold, calibration note, sample sizes.

There is no regression model anywhere in this artifact, and that differs
from analytics-engineering-conventions' expectation that "forecast" would
be one. The quantity forecast here is a sum of per-deal dollar amounts the
CRM already states; what is genuinely unknown is which of those deals
closes won. That is a binary outcome per deal, so the honest model class is
a win-probability classifier, and the dollar forecast is its expectation
under the CRM's own stated amounts. Regressing a period total directly
would fit ~12 quarterly observations per segment, discard every deal-level
driver, and produce an estimate no one could decompose or act on. Same
lesson capacity planning recorded: verify the shape against the data rather
than inheriting the label the conventions doc wrote in advance.

WHY THE ML LENS DOES NOT READ THE FORECAST CATEGORIES
-----------------------------------------------------
The single most predictive observable at any call is the manager's own
category -- and it is deliberately excluded from the classifier's feature
set. The bottoms-up lens IS the forecast categories, priced at their
observed close rates. An ML lens built on top of those same categories
would be a refinement of lens 1 rather than an independent third read, and
the reconciliation in component 4 would be measuring rounding rather than
genuine disagreement. The classifier therefore reads only deal mechanics --
stage, stall, deal age, POC outcome where revealed, rep ramp, account usage
trajectory -- which makes "the ML lens disagrees with the manager roll-up"
a statement about deal mechanics contradicting human judgement, which is
the diagnostic this artifact exists to surface. The rep-vs-manager gap's
own predictive value is reported as a measured diagnostic
(measure_rep_manager_gap_signal) rather than folded into a model.

POINT-IN-TIME DISCIPLINE
------------------------
Every function takes as_of_date. Submissions are filtered to
snapshot_date <= as_of_date, opportunities to created_date <= as_of_date,
stage history to entered_date <= as_of_date, CRO adjustments to
timestamp <= as_of_date, account usage to the last month that had already
ENDED at the evaluation date. Closed-outcome fields (is_won, loss_reason,
the deal-grain forecast_category) are never model inputs.

close_date is used for exactly one thing -- deciding which quarter a deal
belongs to -- and never as a feature. That use is legitimate here and worth
stating plainly rather than leaving implicit: Phase 1 generates no separate
"expected close date" CRM field, so close_date stands in for it, and
generators/forecast.py states that cycle length "is drawn from the same
distribution for won and lost deals upstream, so the length of the series
carries no outcome information either." The generator's own CRO-adjustment
code scopes its quarter the same way. A deal's close_date therefore says
when it resolved, not how.

Every stochastic step is seeded via _RANDOM_SEED.
"""
import os
from datetime import date

import duckdb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_MODEL_NAME = "forecast"
_RANDOM_SEED = 42

# The two segments that file a forecast at all. SMB is out of scope by
# construction, not by filter of convenience: build spec Section 1 gives it
# a no-touch motion closing in 0-7 days with no rep, no stage history and
# no weekly forecast cadence, and fact_forecast_submissions carries no SMB
# row for that reason.
_FORECAST_SEGMENTS = ("Commercial", "Enterprise")

_CATEGORIES = ("Omitted", "Pipeline", "Best Case", "Commit")
_CATEGORY_RANK = {name: i for i, name in enumerate(_CATEGORIES)}

# Opportunity types the win classifier is fitted on. Expansion is excluded
# and that is a finding, not a convenience: every one of the 918 closed
# expansion opportunities in this data (as of the canonical checkpoint)
# closed won, because
# generators/opportunities.py opens an expansion opportunity only once the
# account's own usage has already crossed the commitment it formalises.
# A classifier fitted on a perfectly separable class learns the class
# indicator and nothing else. Expansion dollars are instead priced at their
# own observed historical close rate (see _DETERMINISTIC_TYPES below) --
# a structural, not fitted, component of the ML lens, reported as such.
_FITTED_TYPES = ("new_business", "renewal")
_DETERMINISTIC_TYPES = ("expansion",)

# Stage funnels, transcribed from generators/config.py's NEW_BUSINESS_STAGES
# / RENEWAL_EXPANSION_STAGES (build spec Section 2's funnel-by-segment
# list). Re-declared here rather than imported, matching
# analytics/capacity_planning.py's precedent for generator constants a
# Phase 4 module depends on.
_NEW_BUSINESS_STAGES = {
    "Commercial": ["SAL", "SQO", "Proposal/Negotiation"],
    "Enterprise": ["SAL", "SQO", "POC", "Proposal/Negotiation"],
}
_RENEWAL_EXPANSION_STAGES = ["Open", "Negotiation"]
_CLOSED_STAGES = ("Closed Won", "Closed Lost")

# Expected end-to-end cycle length in days by (segment, opportunity_type) --
# the denominator that turns a raw day count into a stall ratio comparable
# across segments. New business is the midpoint of build spec Section 1's
# cycle-length band (Commercial 14-45, Enterprise 60-180); renewal and
# expansion are the midpoints of the notice windows opportunities.py opens
# those deals on. Same values generators/forecast.py uses for the same
# purpose.
_EXPECTED_CYCLE_DAYS = {
    ("Commercial", "new_business"): 29.5,
    ("Enterprise", "new_business"): 120.0,
    ("Commercial", "renewal"): 60.0,
    ("Enterprise", "renewal"): 105.0,
    ("Commercial", "expansion"): 30.0,
    ("Enterprise", "expansion"): 30.0,
}

# A POC result is knowable at a call only once the POC has actually
# concluded. generators/forecast.py gates its reveal on the deal having
# moved past the POC stage or having sat in it at least 14 days; the same
# gate is applied here. Reading poc_outcome ungated would hand the model a
# result for a deal that has not reached POC yet -- a leak, not a feature.
_POC_REVEAL_LAG_DAYS = 14

# Rep ramp cutoff -- generators/opportunities.py's own _RAMP_FULL_DAYS, the
# cutoff the data was generated against and its reading of build spec
# Section 4's "first 2 quarters". Same constant analytics/capacity_planning
# .py declares for the same reason.
_RAMP_FULL_DAYS = 180

# Shrinkage pseudo-count for the category probability-weight mapping: how
# many snapshot observations a (segment, opportunity_type, category) cell
# needs before its own observed close rate outweighs its parent
# (segment, opportunity_type) base rate. 40 is generators/forecast.py's
# _TRAILING_SHRINKAGE_PSEUDOCOUNT, adopted rather than newly invented, and
# it removes any need for a hard minimum-sample cutoff -- an empty cell
# yields the parent base rate exactly.
_WEIGHT_SHRINKAGE_PSEUDOCOUNT = 40

# The accounting convention generators/forecast.py applies when it prices a
# roll-up for its own CRO-coverage read. NOT used to weight anything here;
# held only so check_weight_mapping_is_grounded() can demonstrate that the
# derived weights are estimated from realized close rates rather than
# copied from a convention.
_GENERATOR_ACCOUNTING_WEIGHTS = {"Commit": 0.90, "Best Case": 0.60, "Pipeline": 0.30, "Omitted": 0.05}

# Minimum fitted-model training rows before the ML lens is reported at all.
# Below this the lens is returned as None with a stated reason rather than
# a number fitted on a handful of deals -- the same not-computable
# treatment analytics/variance_diagnostic.py gives a metric with no source.
_MIN_TRAINING_ROWS = 200

_NUMERIC_FEATURES = [
    "account_usage_trend_ratio",
    "has_entered_a_stage",
    "stage_progress",
    "days_in_current_stage",
    "stage_stall_ratio",
    "deal_age_days",
    "deal_age_ratio",
    "poc_revealed_pass",
    "poc_revealed_fail",
    "rep_is_ramping",
    "rep_tenure_days",
]
# days_to_period_end was dropped from this list (was: days from eval_date to
# the end of eval_date's quarter). In training every row carries its own
# eval_date, so it varies and picks up real-looking signal -- but that
# signal is deal-close-date position within the quarter (won deals close
# earlier in their quarter than lost ones on average), which is exactly a
# post-close attribute leaking backward, not a genuinely pre-close-knowable
# one. Worse, at scoring time every currently-open deal shares one
# as_of_date, so the feature is a CONSTANT across the whole scored
# population -- it contributes zero discrimination in production while
# still applying a fixed log-odds offset to every prediction from whatever
# coefficient training assigned it. A feature that is only informative
# because training and scoring disagree about what varies is a leak by
# construction, not a modeling choice to tune.
_CATEGORICAL_FEATURES = ["segment", "opportunity_type", "current_stage"]
_MODEL_INPUTS = _NUMERIC_FEATURES + _CATEGORICAL_FEATURES

# Held-out split fraction, and the split strategy. Out-of-time, not random:
# this model's production use is "fit on closed history, score the quarter
# now in flight", so a holdout drawn from strictly later evaluation dates
# than every training row is the split that matches deployment. A random
# split would let the model train on deals from the same quarter it is
# scored on. The random split is still computed and reported alongside for
# comparability with analytics/health_score.py's methodology -- it is a
# secondary read, not the headline.
_TEST_FRACTION = 0.25

# Stated BEFORE fitting, per analytics-engineering-conventions' rule that
# an artifact with no stated success criterion cannot be validated later.
# Full grounding in docs/acme-corp-analytics-methods.md's Forecast entry.
_TARGET_AUC_RANGE = (0.70, 0.85)
# Within-stratum criterion, stated as a ratio rather than an absolute AUC.
# Each (segment, opportunity_type) stratum has a different achievable
# ceiling -- the manager's own category separates Commercial new business
# by only a few points of close rate in this data while it separates
# renewals by tens of points -- so a single absolute floor across strata
# would import a number from another artifact's context. The manager
# category lookup on the same held-out rows IS that stratum's demonstrated
# ceiling, and the deal-mechanics model must recover essentially all of it
# from disjoint inputs.
_TARGET_WITHIN_STRATUM_AUC_RATIO = 0.95
_WITHIN_STRATUM_MIN_N = 100
# Calibration is load-bearing for this artifact in a way it is not for the
# health score: the ML lens is summed as sum(amount * p) into a dollar
# figure, so a systematic probability bias becomes a dollar bias one for
# one. 0.05 on a ~0.40 base rate is a <=12.5% relative bias -- inside the
# divergence threshold below, so mis-calibration alone cannot be what makes
# the ML lens diverge from the others.
_TARGET_CALIBRATION_GAP = 0.05

# Reconciliation divergence threshold -- PROPOSED, not yet confirmed. See
# docs/acme-corp-analytics-methods.md for the selectivity grounding;
# measure_divergence_selectivity() below reproduces the curve it cites.
_DIVERGENCE_THRESHOLD = 0.25


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


def _ns(df: pd.DataFrame, columns) -> pd.DataFrame:
    """DuckDB returns datetime64[us]; pandas merge_asof refuses to join
    columns of differing datetime resolution. Normalise every date column
    to [ns] once at load rather than at each join site."""
    for column in columns:
        df[column] = pd.to_datetime(df[column]).astype("datetime64[ns]")
    return df


def _period_label(ts) -> str:
    period = pd.Timestamp(ts).to_period("Q")
    return f"{period.year}-Q{period.quarter}"


# =====================================================================
# Loaders -- marts layer only
# =====================================================================

def load_opportunities(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per opportunity_id, Commercial/Enterprise only,
    restricted to created_date <= as_of_date. Source mart:
    fact_opportunities."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            """
            select opportunity_id, account_id, segment, opportunity_type, owner_role,
                   rep_id, is_won, amount, poc_outcome, created_date, close_date
            from main_marts.fact_opportunities
            where segment in ('Commercial', 'Enterprise')
              and created_date <= ?
            """,
            [as_of_date],
        ).df()
    finally:
        if owns:
            con.close()
    return _ns(df, ["created_date", "close_date"])


def load_forecast_submissions(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per (opportunity_id, snapshot_date), restricted to
    snapshot_date <= as_of_date. Source mart: fact_forecast_submissions."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            """
            select opportunity_id, snapshot_date, rep_forecast_category,
                   manager_forecast_category, rep_forecast_rank, manager_forecast_rank,
                   rep_minus_manager_rank_gap, is_manager_downgrade, is_manager_upgrade
            from main_marts.fact_forecast_submissions
            where snapshot_date <= ?
            """,
            [as_of_date],
        ).df()
    finally:
        if owns:
            con.close()
    return _ns(df, ["snapshot_date"])


def load_stage_history(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per (opportunity_id, stage, entered_date), restricted
    to entered_date <= as_of_date and to OPEN stages only. Source mart:
    fact_opportunity_stage_history.

    Closed Won / Closed Lost rows are dropped at load. A deal's terminal
    stage row is entered on its close date, so it could only ever be picked
    up by an as-of lookup at or after the close -- but dropping it here
    makes the leak structurally impossible rather than merely improbable."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            """
            select opportunity_id, stage, entered_date
            from main_marts.fact_opportunity_stage_history
            where entered_date <= ?
              and stage not in ('Closed Won', 'Closed Lost')
            """,
            [as_of_date],
        ).df()
    finally:
        if owns:
            con.close()
    return _ns(df, ["entered_date"])


def load_cro_adjustments(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: at most one row per (period, segment), restricted to
    timestamp <= as_of_date -- an override filed later in the quarter is
    not knowable at an earlier call. Source mart:
    fact_cro_forecast_adjustments."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            """
            select period, segment, adjustment_amount, reason, is_downward_adjustment,
                   period_start_date, period_end_date, "timestamp" as filed_at
            from main_marts.fact_cro_forecast_adjustments
            where "timestamp" <= ?
            """,
            [as_of_date],
        ).df()
    finally:
        if owns:
            con.close()
    return _ns(df, ["period_start_date", "period_end_date", "filed_at"])


def load_rep_hire_dates(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per rep_id -- earliest hire_date across that rep's
    capacity periods. Source mart: dim_reps."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select rep_id, min(hire_date) as hire_date from main_marts.dim_reps group by 1"
        ).df()
    finally:
        if owns:
            con.close()
    return _ns(df, ["hire_date"])


def load_account_usage_trend(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per (account_id, available_from) -- an account's most
    recent complete month of Actions against the three months before it,
    tagged with the first date that reading was knowable. Source mart:
    mart_account_health.

    available_from is the first day of the month AFTER the month measured:
    a month's consumption is only observable once the month has ended, so
    a call on 14 Nov reads October's Actions, never November's."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            """
            select account_id, month, actions_consumed
            from main_marts.mart_account_health
            where month <= ?
            """,
            [as_of_date],
        ).df()
    finally:
        if owns:
            con.close()
    df = _ns(df, ["month"]).sort_values(["account_id", "month"])
    prior3 = df.groupby("account_id")["actions_consumed"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=1).mean()
    )
    df["account_usage_trend_ratio"] = df["actions_consumed"] / prior3.replace(0, np.nan)
    df["available_from"] = df["month"] + pd.offsets.MonthBegin(1)
    return (
        df.dropna(subset=["account_usage_trend_ratio"])[
            ["account_id", "available_from", "account_usage_trend_ratio"]
        ]
        .sort_values("available_from")
        .reset_index(drop=True)
    )


def load_all(as_of_date: date, con=None) -> dict:
    """Loads every input this module reads, once, under one connection.
    Grain per frame is documented on each loader above; source marts:
    fact_opportunities, fact_forecast_submissions,
    fact_opportunity_stage_history, fact_cro_forecast_adjustments, dim_reps,
    mart_account_health."""
    owns = con is None
    con = con or _connect()
    try:
        return {
            "opportunities": load_opportunities(as_of_date, con=con),
            "submissions": load_forecast_submissions(as_of_date, con=con),
            "stage_history": load_stage_history(as_of_date, con=con),
            "cro_adjustments": load_cro_adjustments(as_of_date, con=con),
            "rep_hire_dates": load_rep_hire_dates(as_of_date, con=con),
            "usage_trend": load_account_usage_trend(as_of_date, con=con),
        }
    finally:
        if owns:
            con.close()


# =====================================================================
# Populations
# =====================================================================

def _stage_list(segment: str, opportunity_type: str):
    if opportunity_type == "new_business":
        return _NEW_BUSINESS_STAGES[segment]
    return _RENEWAL_EXPANSION_STAGES


def open_period_population(data: dict, eval_date: pd.Timestamp) -> pd.DataFrame:
    """Grain: one row per opportunity_id open at eval_date whose close
    lands in eval_date's own quarter -- the deals a forecast call on that
    date is actually forecasting. Source mart: fact_opportunities.

    close_date scopes the period only (standing in for the expected-close
    field Phase 1 does not generate) and is never read as an outcome; see
    the module docstring."""
    eval_date = pd.Timestamp(eval_date)
    opps = data["opportunities"]
    quarter = eval_date.to_period("Q")
    population = opps[
        (opps["created_date"] <= eval_date)
        & (opps["close_date"] > eval_date)
        & (opps["close_date"].dt.to_period("Q") == quarter)
    ].copy()
    population["period"] = _period_label(eval_date)
    population["eval_date"] = eval_date
    return population.reset_index(drop=True)


def closed_period_population(data: dict, eval_date: pd.Timestamp,
                              as_of_date: date) -> pd.DataFrame:
    """Grain: one row per opportunity that was in open_period_population at
    eval_date AND has since closed on or before as_of_date -- the realised
    outcome of exactly the population the lenses forecast. Source mart:
    fact_opportunities. Returns an empty frame while the quarter is still
    in flight."""
    population = open_period_population(data, eval_date)
    return population[population["close_date"] <= pd.Timestamp(as_of_date)].reset_index(drop=True)


# =====================================================================
# Point-in-time feature assembly (shared by the ML lens and the diagnostics)
# =====================================================================

def build_point_in_time_features(evaluations: pd.DataFrame, data: dict) -> pd.DataFrame:
    """Grain: one row per (opportunity_id, eval_date) supplied in
    `evaluations`. Source marts: fact_forecast_submissions,
    fact_opportunity_stage_history, dim_reps, mart_account_health.

    Every column is computed from what was observable on eval_date and
    nothing later: the latest forecast submission filed on or before it,
    the latest open stage entered on or before it, rep tenure at it, and
    the account's last COMPLETE usage month before it."""
    frame = evaluations.sort_values("eval_date").reset_index(drop=True)
    frame["eval_date"] = frame["eval_date"].astype("datetime64[ns]")

    submissions = data["submissions"].sort_values("snapshot_date")[
        ["opportunity_id", "snapshot_date", "rep_forecast_category",
         "manager_forecast_category", "rep_forecast_rank", "manager_forecast_rank",
         "rep_minus_manager_rank_gap", "is_manager_downgrade"]
    ]
    frame = pd.merge_asof(
        frame, submissions, left_on="eval_date", right_on="snapshot_date",
        by="opportunity_id", direction="backward",
    )
    frame = pd.merge_asof(
        frame.sort_values("eval_date"), data["stage_history"].sort_values("entered_date"),
        left_on="eval_date", right_on="entered_date", by="opportunity_id", direction="backward",
    )
    frame = frame.merge(data["rep_hire_dates"], on="rep_id", how="left")
    frame = pd.merge_asof(
        frame.sort_values("eval_date"), data["usage_trend"],
        left_on="eval_date", right_on="available_from", by="account_id", direction="backward",
    )

    stage_counts, stage_indexes = [], []
    for segment, opportunity_type, stage in zip(
        frame["segment"], frame["opportunity_type"], frame["stage"]
    ):
        funnel = _stage_list(segment, opportunity_type)
        stage_counts.append(len(funnel))
        stage_indexes.append(funnel.index(stage) if isinstance(stage, str) and stage in funnel else -1)
    frame["stage_count"] = stage_counts
    frame["stage_index"] = stage_indexes

    # A deal sits created-but-unstaged for a median 7-17 days in this data
    # (its first stage row is entered after creation). That is a real
    # point-in-time state, so it gets its own encoding -- progress 0.0 and
    # a 'pre_stage' category -- rather than a median imputation that would
    # silently place an unstaged deal mid-funnel.
    frame["has_entered_a_stage"] = (frame["stage_index"] >= 0).astype(float)
    frame["current_stage"] = np.where(
        frame["stage_index"] >= 0, frame["stage"].astype(str), "pre_stage"
    )
    frame["stage_progress"] = np.where(
        frame["stage_index"] >= 0, (frame["stage_index"] + 1) / frame["stage_count"], 0.0
    )
    frame["deal_age_days"] = (frame["eval_date"] - frame["created_date"]).dt.days
    frame["days_in_current_stage"] = np.where(
        frame["stage_index"] >= 0,
        (frame["eval_date"] - frame["entered_date"]).dt.days,
        frame["deal_age_days"],
    )
    frame["expected_cycle_days"] = [
        _EXPECTED_CYCLE_DAYS[(segment, opportunity_type)]
        for segment, opportunity_type in zip(frame["segment"], frame["opportunity_type"])
    ]
    frame["stage_stall_ratio"] = frame["days_in_current_stage"] / (
        frame["expected_cycle_days"] / frame["stage_count"]
    )
    frame["deal_age_ratio"] = frame["deal_age_days"] / frame["expected_cycle_days"]

    # POC outcome, gated on the POC having actually concluded by eval_date.
    poc_eligible = (frame["segment"] == "Enterprise") & (frame["opportunity_type"] == "new_business")
    poc_index = _NEW_BUSINESS_STAGES["Enterprise"].index("POC")
    revealed = poc_eligible & (
        (frame["stage_index"] > poc_index)
        | ((frame["stage_index"] == poc_index)
           & (frame["days_in_current_stage"] >= _POC_REVEAL_LAG_DAYS))
    )
    frame["poc_outcome_revealed"] = revealed.astype(float)
    frame["poc_revealed_pass"] = (revealed & (frame["poc_outcome"] == "pass")).astype(float)
    frame["poc_revealed_fail"] = (revealed & (frame["poc_outcome"] == "fail")).astype(float)

    frame["rep_tenure_days"] = (frame["eval_date"] - frame["hire_date"]).dt.days
    frame["rep_is_ramping"] = (frame["rep_tenure_days"] < _RAMP_FULL_DAYS).astype(float)
    frame["is_manager_downgrade"] = frame["is_manager_downgrade"].astype(float)

    # An account with no complete usage month before eval_date, and every
    # new-business deal (the buyer is not consuming anything yet), get a
    # neutral 1.0 = flat trajectory rather than a median fill.
    frame["account_usage_trend_ratio"] = np.where(
        frame["opportunity_type"] == "new_business", 1.0, frame["account_usage_trend_ratio"]
    )
    frame["account_usage_trend_ratio"] = frame["account_usage_trend_ratio"].fillna(1.0)
    return frame


# =====================================================================
# Component 1 -- bottoms-up roll-up (structural)
# =====================================================================

def _isotonic_by_rank(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Pool-adjacent-violators over an already rank-ordered vector: returns
    the weighted-least-squares fit subject to non-decreasing order.

    The forecast categories are ordinal by definition -- Omitted, Pipeline,
    Best Case, Commit is a confidence ordering, not four unrelated labels --
    so a mapping that prices a written-off deal above a Pipeline deal is
    wrong on its face regardless of what a thin cell's sample happened to
    show. Two things produce that inversion here without isotonic ordering:
    a cell with no observations at all falls back to its parent base rate,
    which for renewals (~85% close) sits well above the observed Pipeline
    rate; and a cell with a handful of observations gets pulled most of the
    way to that same parent by shrinkage. Pooling adjacent violators
    weighted by evidence collapses exactly those indistinguishable cells
    into one shared weight rather than inventing an ordering the sample
    cannot support."""
    fitted = [float(v) for v in values]
    counts = [float(w) for w in weights]
    sizes = [1] * len(fitted)
    index = 0
    while index < len(fitted) - 1:
        if fitted[index] <= fitted[index + 1] + 1e-12:
            index += 1
            continue
        total_weight = counts[index] + counts[index + 1]
        pooled = ((fitted[index] * counts[index] + fitted[index + 1] * counts[index + 1]) / total_weight
                  if total_weight else (fitted[index] + fitted[index + 1]) / 2)
        fitted[index:index + 2] = [pooled]
        counts[index:index + 2] = [total_weight]
        sizes[index:index + 2] = [sizes[index] + sizes[index + 1]]
        index = max(index - 1, 0)
    expanded = []
    for value, size in zip(fitted, sizes):
        expanded.extend([value] * size)
    return np.array(expanded, dtype=float)


def derive_category_weights(data: dict, as_of_date: date, lens: str = "manager") -> pd.DataFrame:
    """Grain: one row per (segment, opportunity_type, forecast category).
    Source marts: fact_forecast_submissions joined to fact_opportunities on
    opportunity_id.

    The probability weight attached to a category is its DOLLAR-WEIGHTED
    observed close rate -- of every dollar carried at category C on a call
    inside its own closing quarter, what share actually closed won -- taken
    over deals already closed on or before as_of_date. Dollar-weighted
    rather than count-weighted because the roll-up multiplies dollars: for
    sum(amount * w) to reproduce realised won dollars, w has to be the
    share of dollars that convert, not the share of deals.

    Cells are shrunk toward their (segment, opportunity_type) base close
    rate by _WEIGHT_SHRINKAGE_PSEUDOCOUNT so a thin cell falls back to its
    parent rather than chasing noise, and a cell with no observations at
    all lands exactly on the parent.

    The mapping is keyed by (segment, opportunity_type) and not pooled
    across them, and that is load-bearing: pooled, 'Commit' carries a 92%
    close rate in this data, but 51% of pooled Commit snapshots are
    expansion deals that close won by construction. Within new business the
    same category closes at 36%. A pooled mapping would price a Commercial
    new-business Commit deal at roughly two and a half times its real
    conversion."""
    category_column = f"{lens}_forecast_category"
    opps = data["opportunities"]
    closed = opps[opps["close_date"] <= pd.Timestamp(as_of_date)]
    joined = data["submissions"].merge(
        closed[["opportunity_id", "segment", "opportunity_type", "is_won", "amount", "close_date"]],
        on="opportunity_id",
    )
    joined = joined[
        (joined["snapshot_date"].dt.to_period("Q") == joined["close_date"].dt.to_period("Q"))
        & (joined["snapshot_date"] < joined["close_date"])
    ]
    joined["won_amount"] = joined["amount"] * joined["is_won"].astype(float)

    parent = joined.groupby(["segment", "opportunity_type"], as_index=False).agg(
        parent_dollars=("amount", "sum"), parent_won_dollars=("won_amount", "sum")
    )
    parent["parent_close_rate"] = parent["parent_won_dollars"] / parent["parent_dollars"]

    cells = joined.groupby(["segment", "opportunity_type", category_column], as_index=False).agg(
        n_snapshots=("opportunity_id", "size"),
        n_opportunities=("opportunity_id", "nunique"),
        dollars=("amount", "sum"),
        won_dollars=("won_amount", "sum"),
        n_won_snapshots=("is_won", "sum"),
    )
    cells = cells.rename(columns={category_column: "forecast_category"})
    cells["raw_dollar_close_rate"] = cells["won_dollars"] / cells["dollars"]
    cells["raw_count_close_rate"] = cells["n_won_snapshots"] / cells["n_snapshots"]

    # Every (segment, type, category) combination gets a row, including
    # combinations never observed -- they fall back to the parent base rate
    # rather than being absent and silently dropping deals from the rollup.
    full_index = pd.MultiIndex.from_product(
        [sorted(parent["segment"].unique()), sorted(parent["opportunity_type"].unique()), list(_CATEGORIES)],
        names=["segment", "opportunity_type", "forecast_category"],
    ).to_frame(index=False)
    weights = full_index.merge(cells, on=["segment", "opportunity_type", "forecast_category"], how="left")
    weights = weights.merge(parent, on=["segment", "opportunity_type"], how="left")
    weights[["n_snapshots", "n_opportunities", "dollars", "won_dollars"]] = weights[
        ["n_snapshots", "n_opportunities", "dollars", "won_dollars"]
    ].fillna(0.0)

    shrink = weights["n_snapshots"] / (weights["n_snapshots"] + _WEIGHT_SHRINKAGE_PSEUDOCOUNT)
    weights["shrunk_close_rate"] = (
        shrink * weights["raw_dollar_close_rate"].fillna(weights["parent_close_rate"])
        + (1 - shrink) * weights["parent_close_rate"]
    )
    weights["lens"] = lens
    weights["category_rank"] = weights["forecast_category"].map(_CATEGORY_RANK)
    weights = weights.sort_values(
        ["segment", "opportunity_type", "category_rank"]
    ).reset_index(drop=True)

    # Final step: enforce the category ordering the four labels already
    # declare. See _isotonic_by_rank for why shrinkage alone can invert it.
    weights["probability_weight"] = np.nan
    for (_, _), group in weights.groupby(["segment", "opportunity_type"], sort=False):
        ordered = group.sort_values("category_rank")
        weights.loc[ordered.index, "probability_weight"] = _isotonic_by_rank(
            ordered["shrunk_close_rate"].to_numpy(),
            (ordered["n_snapshots"] + _WEIGHT_SHRINKAGE_PSEUDOCOUNT).to_numpy(),
        )
    weights["pooled_with_neighbour"] = ~np.isclose(
        weights["probability_weight"], weights["shrunk_close_rate"], atol=1e-9
    )
    return weights


def bottoms_up_rollup(data: dict, eval_date: pd.Timestamp, as_of_date: date,
                       lens: str = "manager", weights: pd.DataFrame = None) -> dict:
    """Grain: one result per (period, segment) for the quarter containing
    eval_date. Source marts: fact_opportunities, fact_forecast_submissions.

    Structural, not fitted: each open deal's dollar amount is multiplied by
    the probability weight of whichever category `lens` carried at the most
    recent call on or before eval_date, and the products are summed."""
    eval_date = pd.Timestamp(eval_date)
    weights = derive_category_weights(data, as_of_date, lens=lens) if weights is None else weights
    population = open_period_population(data, eval_date)
    if population.empty:
        return {"period": _period_label(eval_date), "lens": lens, "by_segment": pd.DataFrame(), "deals": population}

    featured = build_point_in_time_features(population, data)
    category_column = f"{lens}_forecast_category"
    # A deal created after the quarter's last call has no submission yet.
    # It is carried at Pipeline -- the category generators/forecast.py's own
    # cut points place a deal at its segment's base win rate, i.e. the
    # weakest non-written-off call -- rather than dropped from the roll-up.
    featured["weighting_category"] = featured[category_column].fillna("Pipeline")
    featured["has_filed_submission"] = featured[category_column].notna()

    merged = featured.merge(
        weights[["segment", "opportunity_type", "forecast_category", "probability_weight"]],
        left_on=["segment", "opportunity_type", "weighting_category"],
        right_on=["segment", "opportunity_type", "forecast_category"],
        how="left",
    )
    merged["probability_weight"] = merged["probability_weight"].fillna(0.0)
    merged["weighted_amount"] = merged["amount"] * merged["probability_weight"]

    by_segment = merged.groupby("segment", as_index=False).agg(
        open_deals=("opportunity_id", "nunique"),
        open_pipeline_amount=("amount", "sum"),
        weighted_forecast=("weighted_amount", "sum"),
        deals_without_submission=("has_filed_submission", lambda s: int((~s).sum())),
    )
    by_segment["period"] = _period_label(eval_date)
    by_segment["lens"] = f"bottoms_up_{lens}"
    by_segment["eval_date"] = eval_date
    return {"period": _period_label(eval_date), "lens": lens, "by_segment": by_segment, "deals": merged}


# =====================================================================
# Component 2 -- ML lens (fitted classifier)
# =====================================================================

def build_training_rows(data: dict, as_of_date: date, seed: int = _RANDOM_SEED) -> pd.DataFrame:
    """Grain: one row per CLOSED opportunity (new_business/renewal,
    Commercial/Enterprise) with close_date <= as_of_date, evaluated at one
    seeded-random forecast call drawn from the calls filed on it inside its
    own closing quarter. Source marts: fact_opportunities,
    fact_forecast_submissions.

    One row per opportunity, not one per call: a deal open for eleven weeks
    files eleven highly-correlated snapshots, and counting them as
    independent observations would inflate the sample size and let near-
    duplicate rows straddle a train/test boundary.

    Drawing the call at random from inside the closing quarter, rather than
    fixing a lead time, is what makes training comparable to production.
    Production scores deals open at an arbitrary as_of_date inside the
    quarter they are expected to close in, so the lead-time distribution
    the model is scored at spans the whole quarter -- and so does this."""
    opps = data["opportunities"]
    closed = opps[
        (opps["close_date"] <= pd.Timestamp(as_of_date))
        & (opps["opportunity_type"].isin(_FITTED_TYPES))
    ]
    eligible = data["submissions"][["opportunity_id", "snapshot_date"]].merge(
        closed[["opportunity_id", "close_date"]], on="opportunity_id"
    )
    eligible = eligible[
        (eligible["snapshot_date"].dt.to_period("Q") == eligible["close_date"].dt.to_period("Q"))
        & (eligible["snapshot_date"] < eligible["close_date"])
    ].sort_values(["opportunity_id", "snapshot_date"])
    if eligible.empty:
        return pd.DataFrame()

    rng = np.random.default_rng(seed)
    picked = eligible.groupby("opportunity_id")["snapshot_date"].apply(
        lambda s: s.iloc[int(rng.integers(0, len(s)))]
    )
    evaluations = picked.reset_index().rename(columns={"snapshot_date": "eval_date"})
    evaluations["eval_date"] = evaluations["eval_date"].astype("datetime64[ns]")
    evaluations = evaluations.merge(closed, on="opportunity_id")

    featured = build_point_in_time_features(evaluations, data)
    featured["label"] = featured["is_won"].astype(int)
    return featured.sort_values(["eval_date", "opportunity_id"]).reset_index(drop=True)


def _make_pipeline() -> Pipeline:
    """Logistic regression, deliberately WITHOUT class_weight='balanced'.
    analytics/health_score.py uses balancing because its output is consumed
    as a ranking (quantile risk tiers), and the calibration it costs does
    not matter there. Here the output is multiplied by dollars and summed,
    so a systematically inflated probability becomes a systematically
    inflated forecast. Calibrated probabilities are the requirement; the
    class balance in this population (~40% won) is mild enough that
    balancing buys nothing to trade against it."""
    preprocessor = ColumnTransformer(
        [
            (
                "num",
                Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]),
                _NUMERIC_FEATURES,
            ),
            ("cat", OneHotEncoder(handle_unknown="ignore"), _CATEGORICAL_FEATURES),
        ]
    )
    return Pipeline(
        [
            ("preprocess", preprocessor),
            ("classify", LogisticRegression(max_iter=2000, random_state=_RANDOM_SEED)),
        ]
    )


def _feature_names(preprocessor: ColumnTransformer) -> list:
    encoder = preprocessor.named_transformers_["cat"]
    return _NUMERIC_FEATURES + list(encoder.get_feature_names_out(_CATEGORICAL_FEATURES))


def _coefficient_table(pipeline: Pipeline) -> pd.DataFrame:
    """Full fitted-coefficient table, one row per model input. Coefficients
    are on the STANDARDIZED / one-hot-encoded scale the classifier actually
    sees (StandardScaler on all numeric inputs), so they compare to each
    other in relative magnitude but are not 'one raw unit of X' effects."""
    preprocessor = pipeline.named_steps["preprocess"]
    classifier = pipeline.named_steps["classify"]
    return (
        pd.DataFrame({"feature": _feature_names(preprocessor), "coefficient": classifier.coef_[0]})
        .sort_values("coefficient", key=np.abs, ascending=False)
        .reset_index(drop=True)
    )


def _category_lookup_baseline(train_df: pd.DataFrame, test_df: pd.DataFrame) -> np.ndarray:
    """The bottoms-up lens used as a classifier: score each held-out deal
    at the observed close rate of its own (segment, opportunity_type,
    manager category) cell, estimated on the training rows only. This is
    the ceiling the manager's own judgement demonstrates on the same rows,
    and the reference the ML lens's within-stratum criterion is stated
    against."""
    cells = train_df.groupby(
        ["segment", "opportunity_type", "manager_forecast_category"]
    )["label"].mean()
    parents = train_df.groupby(["segment", "opportunity_type"])["label"].mean()
    overall = train_df["label"].mean()
    return np.array([
        cells.get((segment, opportunity_type, category),
                  parents.get((segment, opportunity_type), overall))
        for segment, opportunity_type, category in zip(
            test_df["segment"], test_df["opportunity_type"], test_df["manager_forecast_category"]
        )
    ], dtype=float)


def _confusion_at_threshold(labels: pd.Series, proba: np.ndarray, threshold: float) -> dict:
    predicted = proba >= threshold
    actual = labels.to_numpy() == 1
    tp = int((predicted & actual).sum())
    fp = int((predicted & ~actual).sum())
    fn = int((~predicted & actual).sum())
    tn = int((~predicted & ~actual).sum())
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall and (precision + recall) else float("nan"))
    return {
        "operating_threshold_probability": float(threshold),
        "true_positive": tp, "false_positive": fp, "true_negative": tn, "false_negative": fn,
        "precision": precision, "recall": recall, "f1": f1,
    }


def _calibration_check(labels: pd.Series, proba: np.ndarray, buckets: int = 5) -> dict:
    """Mean predicted probability vs. actual base rate on held-out data,
    plus a bucketed reliability read. Unlike analytics/health_score.py's
    equivalent this model is EXPECTED to be calibrated -- no reweighting is
    applied -- and calibration is a stated target here rather than a
    documented limitation, because the ML lens's output is summed as
    sum(amount * p) into a dollar figure."""
    mean_predicted = float(np.mean(proba))
    base_rate = float(labels.mean())
    frame = pd.DataFrame({"label": labels.to_numpy(), "p": proba})
    try:
        frame["bucket"] = pd.qcut(frame["p"], buckets, duplicates="drop")
        reliability = frame.groupby("bucket", observed=True).agg(
            n=("label", "size"), mean_predicted=("p", "mean"), actual_rate=("label", "mean")
        ).reset_index()
        reliability["bucket"] = reliability["bucket"].astype(str)
    except ValueError:
        reliability = pd.DataFrame()
    return {
        "mean_predicted_probability": mean_predicted,
        "actual_base_rate": base_rate,
        "calibration_gap": mean_predicted - base_rate,
        "within_target": abs(mean_predicted - base_rate) <= _TARGET_CALIBRATION_GAP,
        "reliability_by_bucket": reliability,
    }


def train_win_model(data: dict, as_of_date: date, log: bool = True) -> dict:
    """Fits the deal-level win-probability classifier and validates it on an
    OUT-OF-TIME held-out split -- grain: one row per closed opportunity at
    one point-in-time forecast call. Source marts: fact_opportunities,
    fact_forecast_submissions, fact_opportunity_stage_history, dim_reps,
    mart_account_health.

    Returns None-valued lens fields (with a stated reason) rather than a
    model when fewer than _MIN_TRAINING_ROWS closed deals exist as of
    as_of_date.

    The full classification validation package per analytics-engineering-
    conventions is returned in 'validation_package'. No R^2/RMSE applies --
    this is a binary classifier, not a regression model."""
    features = build_training_rows(data, as_of_date)
    if len(features) < _MIN_TRAINING_ROWS or features["label"].nunique() < 2:
        return {
            "computable": False,
            "reason": f"fewer than {_MIN_TRAINING_ROWS} closed opportunities with a forecast "
                      f"call in their closing quarter as of {as_of_date} "
                      f"(have {len(features)})",
            "n_training_rows": len(features),
        }

    ordered = features.sort_values(["eval_date", "opportunity_id"]).reset_index(drop=True)
    cut = int(len(ordered) * (1 - _TEST_FRACTION))
    train_df, test_df = ordered.iloc[:cut].copy(), ordered.iloc[cut:].copy()

    pipeline = _make_pipeline()
    pipeline.fit(train_df[_MODEL_INPUTS], train_df["label"])
    test_proba = pipeline.predict_proba(test_df[_MODEL_INPUTS])[:, 1]
    auc = float(roc_auc_score(test_df["label"], test_proba))

    baseline_proba = _category_lookup_baseline(train_df, test_df)
    baseline_auc = float(roc_auc_score(test_df["label"], baseline_proba))

    # Secondary read only -- same stratified random split analytics/
    # health_score.py uses, reported for methodological comparability.
    random_train, random_test = train_test_split(
        features, test_size=_TEST_FRACTION, random_state=_RANDOM_SEED, stratify=features["label"]
    )
    random_pipeline = _make_pipeline()
    random_pipeline.fit(random_train[_MODEL_INPUTS], random_train["label"])
    random_auc = float(roc_auc_score(
        random_test["label"], random_pipeline.predict_proba(random_test[_MODEL_INPUTS])[:, 1]
    ))

    # Production operating threshold for the confusion matrix. The ML lens's
    # PRIMARY use has no threshold at all -- it multiplies a probability by
    # a dollar amount -- so an arbitrary 0.5 would be theatre. Its secondary
    # use does: flagging which open deals are commit-grade. That threshold
    # is derived exactly the way the bottoms-up weights are, as the observed
    # close rate of manager-Commit deals in the training population, so the
    # two components answer "what does Commit mean" with one number.
    commit_rows = train_df[train_df["manager_forecast_category"] == "Commit"]
    commit_threshold = float(commit_rows["label"].mean()) if len(commit_rows) else 0.5
    confusion = _confusion_at_threshold(test_df["label"], test_proba, commit_threshold)
    calibration = _calibration_check(test_df["label"], test_proba)
    coefficients = _coefficient_table(pipeline)

    strata = []
    scored_test = test_df.assign(model_p=test_proba, baseline_p=baseline_proba)
    for (segment, opportunity_type), group in scored_test.groupby(["segment", "opportunity_type"]):
        if group["label"].nunique() < 2:
            continue
        model_stratum_auc = float(roc_auc_score(group["label"], group["model_p"]))
        baseline_stratum_auc = float(roc_auc_score(group["label"], group["baseline_p"]))
        gated = len(group) >= _WITHIN_STRATUM_MIN_N
        strata.append({
            "segment": segment,
            "opportunity_type": opportunity_type,
            "n_holdout": len(group),
            "model_auc": model_stratum_auc,
            "manager_lookup_auc": baseline_stratum_auc,
            "auc_ratio": model_stratum_auc / baseline_stratum_auc if baseline_stratum_auc else float("nan"),
            "gated_by_min_n": gated,
            "meets_criterion": (not gated) or (
                model_stratum_auc >= _TARGET_WITHIN_STRATUM_AUC_RATIO * baseline_stratum_auc
            ),
        })
    strata_df = pd.DataFrame(strata)

    if log:
        log_performance(_MODEL_NAME, as_of_date, "ml_auc_holdout_out_of_time", auc)
        log_performance(_MODEL_NAME, as_of_date, "ml_auc_holdout_random_split", random_auc)
        log_performance(_MODEL_NAME, as_of_date, "ml_auc_manager_category_lookup_baseline", baseline_auc)
        log_performance(_MODEL_NAME, as_of_date, "ml_precision_commit_grade", confusion["precision"])
        log_performance(_MODEL_NAME, as_of_date, "ml_recall_commit_grade", confusion["recall"])
        log_performance(_MODEL_NAME, as_of_date, "ml_f1_commit_grade", confusion["f1"])
        log_performance(_MODEL_NAME, as_of_date, "ml_true_positive_commit_grade", confusion["true_positive"])
        log_performance(_MODEL_NAME, as_of_date, "ml_false_positive_commit_grade", confusion["false_positive"])
        log_performance(_MODEL_NAME, as_of_date, "ml_true_negative_commit_grade", confusion["true_negative"])
        log_performance(_MODEL_NAME, as_of_date, "ml_false_negative_commit_grade", confusion["false_negative"])
        log_performance(_MODEL_NAME, as_of_date, "ml_operating_threshold_probability",
                        confusion["operating_threshold_probability"])
        log_performance(_MODEL_NAME, as_of_date, "ml_mean_predicted_probability",
                        calibration["mean_predicted_probability"])
        log_performance(_MODEL_NAME, as_of_date, "ml_actual_base_rate", calibration["actual_base_rate"])
        log_performance(_MODEL_NAME, as_of_date, "ml_calibration_gap", calibration["calibration_gap"])
        log_performance(_MODEL_NAME, as_of_date, "ml_n_train", float(len(train_df)))
        log_performance(_MODEL_NAME, as_of_date, "ml_n_holdout", float(len(test_df)))
        log_performance(_MODEL_NAME, as_of_date, "ml_auc_ratio_vs_leak_proof_baseline",
                        auc / baseline_auc if baseline_auc else float("nan"))

    return {
        "computable": True,
        "pipeline": pipeline,
        "auc_holdout": auc,
        "auc_holdout_random_split": random_auc,
        "manager_lookup_baseline_auc": baseline_auc,
        "meets_auc_target": _TARGET_AUC_RANGE[0] <= auc <= _TARGET_AUC_RANGE[1],
        "n_train": len(train_df),
        "n_test": len(test_df),
        "n_train_positive": int(train_df["label"].sum()),
        "n_test_positive": int(test_df["label"].sum()),
        "train_eval_date_range": (train_df["eval_date"].min(), train_df["eval_date"].max()),
        "test_eval_date_range": (test_df["eval_date"].min(), test_df["eval_date"].max()),
        "features": features,
        "validation_package": {
            "coefficients": coefficients,
            "confusion_matrix_commit_grade": confusion,
            "calibration": calibration,
            "within_stratum_auc": strata_df,
        },
    }


def deterministic_type_close_rates(data: dict, as_of_date: date) -> pd.DataFrame:
    """Grain: one row per (segment, opportunity_type) in _DETERMINISTIC_TYPES.
    Source mart: fact_opportunities. Observed dollar-weighted close rate of
    the types the classifier is not fitted on -- computed from closed
    history as of as_of_date, never asserted."""
    opps = data["opportunities"]
    closed = opps[
        (opps["close_date"] <= pd.Timestamp(as_of_date))
        & (opps["opportunity_type"].isin(_DETERMINISTIC_TYPES))
    ].copy()
    closed["won_amount"] = closed["amount"] * closed["is_won"].astype(float)
    grouped = closed.groupby(["segment", "opportunity_type"], as_index=False).agg(
        n_closed=("opportunity_id", "size"), dollars=("amount", "sum"), won_dollars=("won_amount", "sum")
    )
    grouped["observed_close_rate"] = grouped["won_dollars"] / grouped["dollars"]
    return grouped


def ml_rollup(data: dict, eval_date: pd.Timestamp, as_of_date: date,
              model: dict = None, deterministic_rates: pd.DataFrame = None) -> dict:
    """Grain: one row per (period, segment) for the quarter containing
    eval_date. Source marts: as build_point_in_time_features, plus
    fact_opportunities for amounts.

    sum(amount * P(win)) over the open population, where P(win) comes from
    the fitted classifier for new_business/renewal deals and from the
    observed historical close rate for expansion deals (structural, not
    fitted -- see _DETERMINISTIC_TYPES)."""
    eval_date = pd.Timestamp(eval_date)
    model = train_win_model(data, as_of_date, log=False) if model is None else model
    if not model.get("computable"):
        return {"period": _period_label(eval_date), "computable": False,
                "reason": model.get("reason"), "by_segment": pd.DataFrame(), "deals": pd.DataFrame()}

    population = open_period_population(data, eval_date)
    if population.empty:
        return {"period": _period_label(eval_date), "computable": True,
                "by_segment": pd.DataFrame(), "deals": population}

    featured = build_point_in_time_features(population, data)
    rates = (deterministic_type_close_rates(data, as_of_date)
             if deterministic_rates is None else deterministic_rates)
    rate_lookup = {
        (row.segment, row.opportunity_type): row.observed_close_rate for row in rates.itertuples()
    }

    fitted_mask = featured["opportunity_type"].isin(_FITTED_TYPES)
    featured["win_probability"] = np.nan
    featured["probability_source"] = np.where(fitted_mask, "fitted_classifier", "observed_close_rate")
    if fitted_mask.any():
        featured.loc[fitted_mask, "win_probability"] = model["pipeline"].predict_proba(
            featured.loc[fitted_mask, _MODEL_INPUTS]
        )[:, 1]
    if (~fitted_mask).any():
        featured.loc[~fitted_mask, "win_probability"] = [
            rate_lookup.get((segment, opportunity_type), np.nan)
            for segment, opportunity_type in zip(
                featured.loc[~fitted_mask, "segment"], featured.loc[~fitted_mask, "opportunity_type"]
            )
        ]
    featured["win_probability"] = featured["win_probability"].fillna(0.0)
    featured["weighted_amount"] = featured["amount"] * featured["win_probability"]

    by_segment = featured.groupby("segment", as_index=False).agg(
        open_deals=("opportunity_id", "nunique"),
        open_pipeline_amount=("amount", "sum"),
        weighted_forecast=("weighted_amount", "sum"),
        deals_priced_structurally=("probability_source",
                                   lambda s: int((s == "observed_close_rate").sum())),
    )
    by_segment["period"] = _period_label(eval_date)
    by_segment["lens"] = "ml"
    by_segment["eval_date"] = eval_date
    return {"period": _period_label(eval_date), "computable": True,
            "by_segment": by_segment, "deals": featured}


# =====================================================================
# Component 3 -- CRO overlay (structural lookup, never fabricated)
# =====================================================================

def apply_cro_overlay(rollup_by_segment: pd.DataFrame, data: dict,
                       base_column: str = "weighted_forecast") -> pd.DataFrame:
    """Grain: one row per (period, segment) in the supplied roll-up. Source
    mart: fact_cro_forecast_adjustments.

    A logged override is applied verbatim as a dollar delta. Where no row
    exists for a (period, segment) -- which is most of them; the log holds
    18 rows across 11 quarters x 2 segments -- the adjustment is exactly
    0.0, has_logged_cro_adjustment is False, and the adjusted figure equals
    the unadjusted one to the bit. Nothing is interpolated, smoothed,
    carried forward from a neighbouring quarter, or inferred from the
    reasons present elsewhere in the log: an absent row means 'no override
    was filed', never 'missing data' (the mart's own grain comment says so),
    and a fabricated adjustment would be this artifact inventing a
    leadership judgement that was never made."""
    if rollup_by_segment.empty:
        return rollup_by_segment.copy()
    adjustments = data["cro_adjustments"][
        ["period", "segment", "adjustment_amount", "reason", "is_downward_adjustment"]
    ].rename(columns={"adjustment_amount": "cro_adjustment_amount", "reason": "cro_reason"})
    merged = rollup_by_segment.merge(adjustments, on=["period", "segment"], how="left")
    merged["has_logged_cro_adjustment"] = merged["cro_adjustment_amount"].notna()
    merged["cro_adjustment_amount"] = merged["cro_adjustment_amount"].fillna(0.0)
    merged["cro_adjusted_forecast"] = merged[base_column] + merged["cro_adjustment_amount"]
    return merged


# =====================================================================
# Component 4 -- reconciliation
# =====================================================================

_LENS_COLUMNS = ("bottoms_up_rep", "bottoms_up_manager", "ml", "cro_adjusted")


def reconcile_period(data: dict, eval_date: pd.Timestamp, as_of_date: date,
                      model: dict = None) -> pd.DataFrame:
    """Grain: one row per (period, segment) for the quarter containing
    eval_date, carrying all four lenses side by side. Source marts: all of
    this module's inputs.

    The CRO overlay is applied to the MANAGER bottoms-up roll-up, not to the
    rep roll-up or the ML lens. That is its provenance, not a preference:
    generators/forecast.py derives each logged override from the manager-
    categorised roll-up at the quarter's first call, so the manager lens is
    the number the override was actually filed against. The same delta
    applied to the ML lens is reported alongside as
    cro_adjusted_ml_forecast, clearly secondary."""
    eval_date = pd.Timestamp(eval_date)
    rep = bottoms_up_rollup(data, eval_date, as_of_date, lens="rep")["by_segment"]
    manager = bottoms_up_rollup(data, eval_date, as_of_date, lens="manager")["by_segment"]
    ml_result = ml_rollup(data, eval_date, as_of_date, model=model)
    ml = ml_result["by_segment"]

    if manager.empty:
        return pd.DataFrame()

    frame = manager[["period", "segment", "eval_date", "open_deals", "open_pipeline_amount",
                     "weighted_forecast", "deals_without_submission"]].rename(
        columns={"weighted_forecast": "bottoms_up_manager"}
    )
    frame = frame.merge(
        rep[["period", "segment", "weighted_forecast"]].rename(
            columns={"weighted_forecast": "bottoms_up_rep"}), on=["period", "segment"], how="left"
    )
    if not ml.empty:
        frame = frame.merge(
            ml[["period", "segment", "weighted_forecast", "deals_priced_structurally"]].rename(
                columns={"weighted_forecast": "ml"}), on=["period", "segment"], how="left"
        )
    else:
        frame["ml"] = np.nan
        frame["deals_priced_structurally"] = np.nan
    frame["ml_computable"] = ml_result.get("computable", False) and not ml.empty
    frame["ml_not_computable_reason"] = (
        None if frame["ml_computable"].all() else ml_result.get("reason")
    )

    overlaid = apply_cro_overlay(
        frame.rename(columns={"bottoms_up_manager": "_base"}), data, base_column="_base"
    ).rename(columns={"_base": "bottoms_up_manager", "cro_adjusted_forecast": "cro_adjusted"})
    overlaid["cro_adjusted_ml_forecast"] = overlaid["ml"] + overlaid["cro_adjustment_amount"]

    lens_values = overlaid[list(_LENS_COLUMNS)]
    # Reported alongside the spread rather than buried: before enough closed
    # history accumulates to fit the classifier, the spread is taken over
    # three lenses, not four, and a reader comparing spreads across periods
    # needs to know which.
    overlaid["lenses_computable"] = lens_values.notna().sum(axis=1)
    overlaid["lens_max"] = lens_values.max(axis=1)
    overlaid["lens_min"] = lens_values.min(axis=1)
    overlaid["lens_mean"] = lens_values.mean(axis=1)
    overlaid["lens_spread_pct"] = (
        (overlaid["lens_max"] - overlaid["lens_min"]) / overlaid["lens_mean"].abs()
    )
    overlaid["diverges_materially"] = overlaid["lens_spread_pct"] > _DIVERGENCE_THRESHOLD
    overlaid["widest_pair"] = [
        f"{lens_values.columns[np.nanargmax(row.to_numpy())]} vs "
        f"{lens_values.columns[np.nanargmin(row.to_numpy())]}"
        if row.notna().any() else None
        for _, row in lens_values.iterrows()
    ]
    return overlaid.reset_index(drop=True)


def _backtest_eval_date(quarter: pd.Period) -> pd.Timestamp:
    """The mid-quarter forecast call: the last Friday snapshot on or before
    the quarter's midpoint. A fixed relative position, so every backtested
    quarter is evaluated at a comparable point in its own cycle rather than
    at whatever offset as_of_date happens to sit at."""
    midpoint = quarter.start_time + (quarter.end_time - quarter.start_time) / 2
    grid = pd.date_range(quarter.start_time, midpoint, freq="W-FRI")
    return grid[-1] if len(grid) else pd.Timestamp(midpoint).normalize()


def backtest_reconciliation(data_by_eval_date, as_of_date: date, con=None,
                             refit_each_quarter: bool = True) -> pd.DataFrame:
    """Grain: one row per (period, segment) for every quarter whose
    mid-quarter call falls on or before as_of_date. Source marts: all of
    this module's inputs.

    Each quarter is evaluated using ONLY data available at that quarter's
    own mid-quarter call -- weights re-derived and (when refit_each_quarter)
    the classifier re-fitted from closed deals as of that date. A single
    model fitted at as_of_date and applied backwards would leak every later
    quarter's outcomes into every earlier quarter's forecast, which is the
    exact failure this artifact's point-in-time rule exists to prevent.

    For quarters that have since completed, realised_won_amount is the
    actual closed-won dollars of exactly the population the lenses
    forecast -- same deals, same scoping -- so lens error is measured
    against a like-for-like denominator rather than against a period total
    that includes deals no lens ever saw."""
    owns = con is None
    con = con or _connect()
    try:
        full = load_all(as_of_date, con=con)
        opps = full["opportunities"]
        if opps.empty:
            return pd.DataFrame()
        first_snapshot = full["submissions"]["snapshot_date"].min()
        quarters = pd.period_range(
            pd.Timestamp(first_snapshot).to_period("Q"),
            pd.Timestamp(as_of_date).to_period("Q"), freq="Q",
        )
        rows = []
        for quarter in quarters:
            eval_date = _backtest_eval_date(quarter)
            if eval_date > pd.Timestamp(as_of_date):
                continue
            quarter_data = load_all(eval_date.date(), con=con)
            model = train_win_model(quarter_data, eval_date.date(), log=False) if refit_each_quarter else None
            reconciled = reconcile_period(quarter_data, eval_date, eval_date.date(), model=model)
            if reconciled.empty:
                continue
            realised = closed_period_population(full, eval_date, as_of_date)
            realised["won_amount"] = realised["amount"] * realised["is_won"].astype(float)
            actuals = realised.groupby("segment").agg(
                realised_won_amount=("won_amount", "sum"),
                resolved_deals=("opportunity_id", "nunique"),
            )
            reconciled = reconciled.merge(actuals, on="segment", how="left")
            reconciled["quarter_complete"] = quarter.end_time <= pd.Timestamp(as_of_date)
            rows.append(reconciled)
        if not rows:
            return pd.DataFrame()
        backtest = pd.concat(rows, ignore_index=True)
    finally:
        if owns:
            con.close()

    for lens in _LENS_COLUMNS:
        backtest[f"error_{lens}"] = backtest[lens] - backtest["realised_won_amount"]
        backtest[f"abs_pct_error_{lens}"] = (
            backtest[f"error_{lens}"].abs() / backtest["realised_won_amount"].replace(0, np.nan)
        )
    return backtest


def measure_divergence_selectivity(backtest: pd.DataFrame, thresholds=None) -> pd.DataFrame:
    """Grain: one row per candidate threshold. Source: the backtest frame.
    The evidence the _DIVERGENCE_THRESHOLD proposal rests on -- a flag that
    never fires is vacuous and one that always fires is trivial, so the
    threshold has to sit somewhere the curve is genuinely selective."""
    thresholds = thresholds or [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75, 1.00]
    spread = backtest["lens_spread_pct"].dropna()
    return pd.DataFrame([
        {
            "threshold": t,
            "period_segments_flagged": int((spread > t).sum()),
            "period_segments_total": int(len(spread)),
            "share_flagged": float((spread > t).mean()) if len(spread) else float("nan"),
        }
        for t in thresholds
    ])


def measure_rep_manager_gap_signal(data: dict, as_of_date: date) -> dict:
    """Grain: one summary over closed opportunities as of as_of_date.
    Source marts: fact_forecast_submissions, fact_opportunities.

    The build spec's claim that the rep-vs-manager gap "is itself a signal",
    measured rather than modelled: do deals where the manager downgraded a
    confident rep call close at a lower rate than deals where the two
    agreed? Reported as a documented diagnostic and deliberately NOT fed to
    the classifier -- see the module docstring on lens independence."""
    opps = data["opportunities"]
    closed = opps[opps["close_date"] <= pd.Timestamp(as_of_date)]
    joined = data["submissions"].merge(
        closed[["opportunity_id", "segment", "opportunity_type", "is_won", "amount", "close_date"]],
        on="opportunity_id",
    )
    joined = joined[
        (joined["snapshot_date"].dt.to_period("Q") == joined["close_date"].dt.to_period("Q"))
        & (joined["snapshot_date"] < joined["close_date"])
    ]
    confident = joined[joined["rep_forecast_category"].isin(["Commit", "Best Case"])]
    downgraded = confident[confident["is_manager_downgrade"]]
    agreed = confident[confident["rep_minus_manager_rank_gap"] == 0]
    rate = lambda frame: float(frame["is_won"].mean()) if len(frame) else float("nan")
    return {
        "n_confident_rep_calls": int(len(confident)),
        "n_manager_downgraded": int(len(downgraded)),
        "n_rep_manager_agreed": int(len(agreed)),
        "close_rate_manager_downgraded": rate(downgraded),
        "close_rate_rep_manager_agreed": rate(agreed),
        "downgrade_penalty": rate(agreed) - rate(downgraded),
        "signal_present": rate(downgraded) < rate(agreed),
    }


# =====================================================================
# Validation -- structural checks for components 1/3/4, plus the ML
# package's own targets. analytics-model-validator recomputes these.
# =====================================================================

def check_weight_mapping_is_grounded(data: dict, as_of_date: date, lens: str = "manager") -> dict:
    """Confirms the probability-weight mapping is genuinely estimated from
    realised close rates rather than asserted. Four claims, each a real
    property the mapping would lose if the weights were made up:

    1. Shrinkage invariant -- every cell's shrunk rate sits between its own
       observed dollar close rate and its parent (segment, opportunity_type)
       base rate. A weight outside that interval did not come from either.
    2. Ordering -- the final weights are weakly non-decreasing in category
       rank within every (segment, opportunity_type).
    3. Pass-through -- a cell not pooled by the isotonic step carries its
       shrunk rate unchanged, so pooling is confined to genuine violators.
    4. Independence from convention -- the mapping differs materially from
       the flat accounting weights generators/forecast.py uses for its own
       coverage read. A derived mapping that landed on the convention it is
       meant to replace would be the convention wearing a derivation."""
    weights = derive_category_weights(data, as_of_date, lens=lens)
    observed = weights.dropna(subset=["raw_dollar_close_rate"])
    between = (
        (observed["shrunk_close_rate"] >= np.minimum(observed["raw_dollar_close_rate"], observed["parent_close_rate"]) - 1e-9)
        & (observed["shrunk_close_rate"] <= np.maximum(observed["raw_dollar_close_rate"], observed["parent_close_rate"]) + 1e-9)
    )
    monotone_failures = []
    for (segment, opportunity_type), group in weights.groupby(["segment", "opportunity_type"]):
        ordered = group.sort_values("category_rank")["probability_weight"].to_numpy()
        if np.any(np.diff(ordered) < -1e-9):
            monotone_failures.append(f"{segment}/{opportunity_type}")
    unpooled = weights[~weights["pooled_with_neighbour"]]
    pass_through = bool(
        np.allclose(unpooled["probability_weight"], unpooled["shrunk_close_rate"], atol=1e-9)
    )
    convention = weights["forecast_category"].map(_GENERATOR_ACCOUNTING_WEIGHTS)
    max_deviation = float((weights["probability_weight"] - convention).abs().max())
    return {
        "name": "weight_mapping_is_grounded",
        "passed": bool(between.all()) and not monotone_failures and pass_through and max_deviation > 0.05,
        "detail": (
            f"{len(observed)} of {len(weights)} cells have their own observations; shrunk rate "
            f"between own and parent rate in all of them: {bool(between.all())}; final weights "
            f"monotone in category rank for every (segment, opportunity_type): "
            f"{not monotone_failures} {monotone_failures if monotone_failures else ''}; "
            f"{int(weights['pooled_with_neighbour'].sum())} cells pooled by the isotonic step, "
            f"the remaining {len(unpooled)} passed through unchanged: {pass_through}; "
            f"max deviation from the generator's accounting convention {max_deviation:.4f}"
        ),
        "weights": weights,
        "max_deviation_from_convention": max_deviation,
    }


def check_weights_reproduce_realised_dollars(backtest: pd.DataFrame) -> dict:
    """Out-of-sample grounding: over completed quarters, does the manager
    bottoms-up roll-up -- weights derived only from deals closed before each
    quarter's own call -- actually land near the dollars that closed won?
    A weight mapping that were arbitrary would fail here even though it
    passes the in-sample structural check above."""
    complete = backtest[backtest["quarter_complete"] & backtest["realised_won_amount"].notna()]
    if complete.empty:
        return {"name": "weights_reproduce_realised_dollars", "passed": False,
                "detail": "no completed quarters available"}
    total_forecast = float(complete["bottoms_up_manager"].sum())
    total_actual = float(complete["realised_won_amount"].sum())
    aggregate_bias = (total_forecast - total_actual) / total_actual
    mape = float(complete["abs_pct_error_bottoms_up_manager"].mean())
    return {
        "name": "weights_reproduce_realised_dollars",
        "passed": abs(aggregate_bias) <= 0.20,
        "detail": (
            f"{len(complete)} completed period-segments; aggregate bias {aggregate_bias:+.2%} "
            f"(${total_forecast:,.0f} forecast vs ${total_actual:,.0f} realised), "
            f"per-period-segment MAPE {mape:.2%}"
        ),
        "aggregate_bias": aggregate_bias,
        "mape": mape,
    }


def check_cro_overlay_never_fabricates(reconciled: pd.DataFrame, data: dict) -> dict:
    """The named anti-fabrication check. Every (period, segment) with no
    logged override must carry an adjustment of exactly 0.0 and an adjusted
    figure bit-identical to the unadjusted one; every one with a logged
    override must carry exactly the logged amount, unscaled and unsmoothed;
    and the count of non-zero adjustments must equal the count of log rows
    matched."""
    if reconciled.empty:
        return {"name": "cro_overlay_never_fabricates", "passed": False, "detail": "no rows to check"}
    unlogged = reconciled[~reconciled["has_logged_cro_adjustment"]]
    fabricated = unlogged[
        (unlogged["cro_adjustment_amount"] != 0.0)
        | (unlogged["cro_adjusted"] != unlogged["bottoms_up_manager"])
    ]
    logged = reconciled[reconciled["has_logged_cro_adjustment"]]
    log = data["cro_adjustments"].set_index(["period", "segment"])["adjustment_amount"]
    mismatched = [
        (row.period, row.segment)
        for row in logged.itertuples()
        if abs(row.cro_adjustment_amount - float(log.loc[(row.period, row.segment)])) > 1e-9
    ]
    matched_log_rows = int(len(logged))
    nonzero = int((reconciled["cro_adjustment_amount"] != 0.0).sum())
    return {
        "name": "cro_overlay_never_fabricates",
        "passed": fabricated.empty and not mismatched and nonzero <= matched_log_rows,
        "detail": (
            f"{len(unlogged)} period-segments with no logged override -> "
            f"{len(fabricated)} fabricated (must be 0); {matched_log_rows} with a logged "
            f"override -> {len(mismatched)} amount mismatches (must be 0); "
            f"{nonzero} non-zero adjustments against {matched_log_rows} log rows matched"
        ),
    }


def check_divergence_flag_is_selective(backtest: pd.DataFrame) -> dict:
    """The flag must be neither vacuous (never fires) nor trivial (always
    fires) on real data across the whole backtest window."""
    if backtest.empty or backtest["lens_spread_pct"].dropna().empty:
        return {"name": "divergence_flag_is_selective", "passed": False,
                "detail": "no period-segments with a computable spread"}
    flagged = backtest["diverges_materially"]
    share = float(flagged.mean())
    return {
        "name": "divergence_flag_is_selective",
        "passed": 0 < flagged.sum() < len(flagged),
        "detail": (
            f"{int(flagged.sum())} of {len(flagged)} period-segments flagged at a "
            f"{_DIVERGENCE_THRESHOLD:.0%} spread threshold ({share:.1%}); "
            f"spread range {backtest['lens_spread_pct'].min():.1%}-"
            f"{backtest['lens_spread_pct'].max():.1%}, median "
            f"{backtest['lens_spread_pct'].median():.1%}"
        ),
        "share_flagged": share,
    }


def check_rollup_ties_to_deal_detail(data: dict, eval_date: pd.Timestamp, as_of_date: date) -> dict:
    """Exact structural tie-out: the per-segment roll-up must equal the sum
    of its own per-deal weighted amounts, and the open-deal count must equal
    the distinct opportunities in the population -- no deal dropped by a
    failed weight join, none double-counted by a fan-out."""
    result = bottoms_up_rollup(data, eval_date, as_of_date, lens="manager")
    rollup, deals = result["by_segment"], result["deals"]
    if rollup.empty:
        return {"name": "rollup_ties_to_deal_detail", "passed": False,
                "detail": "no open population at the evaluation date"}
    recomputed = deals.groupby("segment")["weighted_amount"].sum()
    max_diff = float((rollup.set_index("segment")["weighted_forecast"] - recomputed).abs().max())
    population = open_period_population(data, eval_date)
    count_matches = int(rollup["open_deals"].sum()) == population["opportunity_id"].nunique()
    unweighted = int(deals["probability_weight"].isna().sum())
    return {
        "name": "rollup_ties_to_deal_detail",
        "passed": max_diff <= 0.01 and count_matches and unweighted == 0,
        "detail": (
            f"max abs diff ${max_diff:.6f} across {len(rollup)} segments; deal count "
            f"{int(rollup['open_deals'].sum())} vs population "
            f"{population['opportunity_id'].nunique()} ({count_matches}); "
            f"{unweighted} deals with no weight matched"
        ),
        "max_abs_diff": max_diff,
    }


def check_ml_targets(model: dict) -> dict:
    """The ML lens against the three targets stated before fitting: pooled
    out-of-time AUC inside _TARGET_AUC_RANGE, within-stratum AUC at least
    _TARGET_WITHIN_STRATUM_AUC_RATIO of the manager-lookup ceiling on every
    stratum with _WITHIN_STRATUM_MIN_N held-out deals, and a held-out
    calibration gap inside _TARGET_CALIBRATION_GAP.

    The upper bound of _TARGET_AUC_RANGE exists as a leakage alarm, not as
    a performance cap, so a breach of it is reported with the evidence a
    reader needs to tell the two apart. The manager-category lookup on the
    same held-out rows CANNOT leak -- it is a human judgement filed before
    the close, priced at its own historical rate -- so its AUC is a
    leak-proof read of how separable that particular holdout slice is. A
    model AUC that breaches the ceiling while sitting close to that
    baseline is a composition effect (an easy slice); one that breaches it
    while running far above the baseline is the alarm firing for real."""
    if not model.get("computable"):
        return {"name": "ml_targets", "passed": False, "detail": model.get("reason")}
    auc = model["auc_holdout"]
    baseline_auc = model["manager_lookup_baseline_auc"]
    calibration = model["validation_package"]["calibration"]
    strata = model["validation_package"]["within_stratum_auc"]
    gated = strata[strata["gated_by_min_n"]] if not strata.empty else strata
    strata_pass = bool(gated["meets_criterion"].all()) if not gated.empty else False
    auc_pass = _TARGET_AUC_RANGE[0] <= auc <= _TARGET_AUC_RANGE[1]
    leak_ratio = auc / baseline_auc if baseline_auc else float("nan")
    return {
        "name": "ml_targets",
        "passed": bool(auc_pass and strata_pass and calibration["within_target"]),
        "detail": (
            f"out-of-time holdout AUC {auc:.4f} vs target "
            f"{_TARGET_AUC_RANGE[0]}-{_TARGET_AUC_RANGE[1]} ({auc_pass}); "
            f"{len(gated)} gated strata, all meeting the {_TARGET_WITHIN_STRATUM_AUC_RATIO:.2f}x "
            f"manager-lookup ratio: {strata_pass}; calibration gap "
            f"{calibration['calibration_gap']:+.4f} vs +/-{_TARGET_CALIBRATION_GAP} "
            f"({calibration['within_target']}); leak diagnostic -- model AUC is "
            f"{leak_ratio:.3f}x the leak-proof manager-lookup AUC ({baseline_auc:.4f}) on the "
            f"same held-out rows"
        ),
        "auc_ratio_vs_leak_proof_baseline": leak_ratio,
    }


def run_build_time_validation(as_of_date: date, backtest: pd.DataFrame = None,
                               log: bool = True) -> dict:
    """End-to-end build-time check: derives the weight mapping, fits the
    classifier, reconciles the current period, runs the backtest, and runs
    all six checks. This is what analytics-model-validator consumes; it does
    not itself re-fit."""
    con = _connect()
    try:
        data = load_all(as_of_date, con=con)
        model = train_win_model(data, as_of_date, log=log)
        eval_date = pd.Timestamp(as_of_date)
        reconciled = reconcile_period(data, eval_date, as_of_date, model=model)
        if backtest is None:
            backtest = backtest_reconciliation(None, as_of_date, con=con)
        grounding = check_weight_mapping_is_grounded(data, as_of_date)
        gap_signal = measure_rep_manager_gap_signal(data, as_of_date)
        checks = [
            grounding,
            check_weights_reproduce_realised_dollars(backtest),
            check_rollup_ties_to_deal_detail(data, eval_date, as_of_date),
            check_cro_overlay_never_fabricates(backtest, data),
            check_divergence_flag_is_selective(backtest),
            check_ml_targets(model),
        ]
    finally:
        con.close()

    passed = sum(1 for check in checks if check["passed"])
    if log:
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_total", float(len(checks)))
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_passed", float(passed))
        log_performance(_MODEL_NAME, as_of_date, "divergence_threshold", _DIVERGENCE_THRESHOLD)
        log_performance(_MODEL_NAME, as_of_date, "divergence_share_flagged_backtest",
                        float(backtest["diverges_materially"].mean()) if not backtest.empty else float("nan"))
        log_performance(_MODEL_NAME, as_of_date, "backtest_period_segments",
                        float(len(backtest)))
        log_performance(_MODEL_NAME, as_of_date, "rep_manager_downgrade_penalty",
                        gap_signal["downgrade_penalty"])
        complete = backtest[backtest["quarter_complete"] & backtest["realised_won_amount"].notna()] \
            if not backtest.empty else pd.DataFrame()
        for lens in _LENS_COLUMNS:
            if not complete.empty:
                log_performance(_MODEL_NAME, as_of_date, f"backtest_mape_{lens}",
                                float(complete[f"abs_pct_error_{lens}"].mean()))
        if not reconciled.empty:
            for row in reconciled.itertuples():
                key = row.segment.lower()
                log_performance(_MODEL_NAME, as_of_date, f"current_period_bottoms_up_manager_{key}",
                                float(row.bottoms_up_manager))
                log_performance(_MODEL_NAME, as_of_date, f"current_period_bottoms_up_rep_{key}",
                                float(row.bottoms_up_rep))
                log_performance(_MODEL_NAME, as_of_date, f"current_period_ml_{key}", float(row.ml))
                log_performance(_MODEL_NAME, as_of_date, f"current_period_cro_adjusted_{key}",
                                float(row.cro_adjusted))
                log_performance(_MODEL_NAME, as_of_date, f"current_period_lens_spread_pct_{key}",
                                float(row.lens_spread_pct))

    return {
        "as_of_date": as_of_date,
        "period": _period_label(as_of_date),
        "model": model,
        "reconciled_current_period": reconciled,
        "backtest": backtest,
        "category_weights": grounding["weights"],
        "rep_manager_gap_signal": gap_signal,
        "divergence_selectivity": measure_divergence_selectivity(backtest),
        "checks": checks,
        "checks_passed": passed,
        "checks_total": len(checks),
    }


def run_forecast(as_of_date: date) -> dict:
    """The artifact's headline output -- grain: one row per (period, segment)
    for the quarter containing as_of_date, with all four lenses side by side
    and the divergence flag. Source marts: fact_opportunities,
    fact_forecast_submissions, fact_opportunity_stage_history,
    fact_cro_forecast_adjustments, dim_reps, mart_account_health."""
    con = _connect()
    try:
        data = load_all(as_of_date, con=con)
        model = train_win_model(data, as_of_date, log=False)
        reconciled = reconcile_period(data, pd.Timestamp(as_of_date), as_of_date, model=model)
    finally:
        con.close()
    return {
        "as_of_date": as_of_date,
        "period": _period_label(as_of_date),
        "reconciliation": reconciled,
        "model": model,
        "data_window": {
            "note": (
                "fact_forecast_submissions ends 2025-12-26 and the last opportunity closes "
                "2025-12-28, so an as_of_date inside 2025-Q4 sees a quarter with no deals "
                "closing beyond the simulation window -- every open deal scopes into the "
                "current period by construction. Reported rather than silently absorbed."
            ),
        },
    }


if __name__ == "__main__":
    result = run_build_time_validation(date(2025, 11, 14))
    model = result["model"]
    print(f"=== Forecast, as_of_date {result['as_of_date']} ({result['period']}) ===\n")
    print("Category probability weights (manager lens):")
    print(result["category_weights"][
        ["segment", "opportunity_type", "forecast_category", "n_snapshots", "n_opportunities",
         "raw_dollar_close_rate", "parent_close_rate", "shrunk_close_rate",
         "probability_weight", "pooled_with_neighbour"]
    ].to_string(index=False))
    print("\nReconciliation, current period:")
    print(result["reconciled_current_period"][
        ["period", "segment", "open_deals", "open_pipeline_amount", "bottoms_up_rep",
         "bottoms_up_manager", "ml", "cro_adjustment_amount", "cro_adjusted",
         "lens_spread_pct", "diverges_materially", "widest_pair"]
    ].to_string(index=False))
    if model.get("computable"):
        print(f"\nML lens: out-of-time holdout AUC {model['auc_holdout']:.4f} "
              f"(target {_TARGET_AUC_RANGE[0]}-{_TARGET_AUC_RANGE[1]}), "
              f"random-split AUC {model['auc_holdout_random_split']:.4f}, "
              f"manager-lookup baseline {model['manager_lookup_baseline_auc']:.4f}")
        print(f"  n_train={model['n_train']} ({model['n_train_positive']} won), "
              f"n_holdout={model['n_test']} ({model['n_test_positive']} won)")
        print("\nCoefficients:")
        print(model["validation_package"]["coefficients"].to_string(index=False))
        print("\nConfusion matrix at the commit-grade operating threshold:")
        print(model["validation_package"]["confusion_matrix_commit_grade"])
        calibration = model["validation_package"]["calibration"]
        print(f"\nCalibration: mean predicted {calibration['mean_predicted_probability']:.4f} vs "
              f"base rate {calibration['actual_base_rate']:.4f} "
              f"(gap {calibration['calibration_gap']:+.4f})")
        print(calibration["reliability_by_bucket"].to_string(index=False))
        print("\nWithin-stratum AUC vs the manager-lookup ceiling:")
        print(model["validation_package"]["within_stratum_auc"].to_string(index=False))
    print("\nRep-manager gap diagnostic:", result["rep_manager_gap_signal"])
    backtest = result["backtest"]
    complete = backtest[backtest["quarter_complete"] & backtest["realised_won_amount"].notna()]
    print(f"\nBacktest ({len(backtest)} period-segments, {len(complete)} with a realised actual):")
    for lens in _LENS_COLUMNS:
        bias = (complete[lens].sum() - complete["realised_won_amount"].sum()) / complete["realised_won_amount"].sum()
        print(f"  {lens:>20}: MAPE {complete[f'abs_pct_error_{lens}'].mean():.2%}  "
              f"aggregate bias {bias:+.2%}")
    print(backtest[["period", "segment", "bottoms_up_rep", "bottoms_up_manager", "ml",
                    "cro_adjusted", "realised_won_amount", "lens_spread_pct",
                    "diverges_materially"]].to_string(index=False))
    print("\nDivergence selectivity:")
    print(result["divergence_selectivity"].to_string(index=False))
    print(f"\nChecks: {result['checks_passed']} of {result['checks_total']} passed")
    for check in result["checks"]:
        print(f"  [{'PASS' if check['passed'] else 'FAIL'}] {check['name']}: {check['detail']}")
