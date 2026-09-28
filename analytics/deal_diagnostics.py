"""Deal-level diagnostics -- grain: one row per OPEN Commercial/Enterprise
new-business opportunity as of as_of_date; source marts: fact_opportunities,
fact_sales_activities, fact_opportunity_stage_history,
fact_forecast_submissions, dim_reps.

Build spec item #17, Wave 4: "Deal-level diagnostics (the evolution of
Pipeline Scanner -- per-opportunity risk detection, not just aggregate
variance)." A different altitude than analytics/variance_diagnostic.py: that
engine walks the metric tree at portfolio/aggregate grain; this module
answers "which specific live deals look at-risk right now" at per-opportunity
grain, using fact_sales_activities' individual-touch data the variance
engine's mart-of-marts view can never see at deal grain.

SHAPE -- HYBRID, and stated as such rather than forced into one category,
following analytics/forecast.py's own precedent for this project:
  * A STRUCTURAL/LOGIC component: six named, deterministic risk FLAGS
    (gone_dark, single_threaded, competitive_pressure, stalled_in_stage,
    forecast_downgraded, poc_at_risk), each a stored threshold rule over
    already-materialized mart values, validated with synthetic
    known-answer test cases -- no coefficient, no AUC, applies to this half.
  * A genuine CLASSIFICATION component: a fitted composite risk score
    (P(eventual loss)) blending the same engagement/mechanics/forecast
    signals into one ranking, carrying the full classification validation
    package analytics-engineering-conventions requires.
Both are reported side by side for every open deal; they are not fused into
one meta-verdict, the same discipline forecast.py's four lenses and
variance_diagnostic.py's mechanism column both apply -- an interpretable
"why" (flags) and a ranking (score) answer different questions and a reader
should see both rather than one absorbing the other.

THE LEAKAGE QUESTION THIS ARTIFACT HAD TO ANSWER BEFORE CHOOSING A SHAPE
-------------------------------------------------------------------------
generators/opportunities.py decides every opportunity's is_won from its OWN
drivers (segment, cycle timing, discount, POC, rep ramp) with no dependency
on activity data -- fact_sales_activities does not exist yet when
opportunities.py runs, so there is no formula-circularity of the kind this
artifact was built to rule out first ("was n_touches literally used to
generate is_won upstream").

generators/sales_activities.py then reads is_won (already decided) to set
each opportunity's cadence, held/connect/reply rate and multi-threading
probability -- realistic reverse-conditioning ("a deal that closed was
worked harder"), the same pattern generators/opportunities.py already uses
for poc_outcome (drawn conditional on the already-decided is_won) and that
analytics/forecast.py already accepts poc_revealed_pass/fail as a
legitimate, non-leaky feature once gated on reveal. The open question was
whether this reverse-conditioning is a MODEST, realistic tilt (like
POC outcome) or a near-deterministic collapse of the kind
docs/acme-corp-analytics-methods.md's Account health score entry documents
finding and had to gate around (0.93-0.99 AUC scoring inside the
generator's deterministic pre-churn decline window).

Checked empirically at build time, not assumed either way: a classifier
fitted on ENGAGEMENT-ONLY point-in-time features (touches strictly on or
before a synthetic evaluation date drawn uniformly across each closed deal's
own [created_date, close_date)) scores 0.64 AUC at early-lifecycle snapshots,
0.75 at late-lifecycle snapshots, 0.69-0.72 pooled across the whole
lifecycle -- the same order of magnitude as analytics/forecast.py's own
deal-mechanics-only ML lens (0.70-0.85 target, 0.8153 achieved), nowhere
near the health score's 0.93-0.99 danger zone. That result, not an a priori
argument, is why this module builds a genuine fitted classifier rather than
declaring the engagement signal unusable and falling back to a purely
structural shape. The full achieved figures for the actual pipeline below
are in the Achieved section and docs/acme-corp-analytics-methods.md.

POINT-IN-TIME DESIGN
---------------------
Every function takes as_of_date. Activities are filtered to
activity_timestamp <= as_of_date, stage history to entered_date <=
as_of_date, forecast submissions to snapshot_date <= as_of_date,
opportunities to created_date <= as_of_date. close_date is used only to
decide whether a deal is still open (close_date > as_of_date) or, for
training rows, which quarter/window it falls in -- never read as a feature,
matching analytics/forecast.py's own documented discipline for the same
field. discount_rate and list_price are excluded as features for the exact
reason analytics/forecast.py already established and is reused rather than
re-derived: generators/forecast.py states the final negotiated amount and
discount are set together at generation time, "none of the three can be
treated as a stable pre-close observation" for an OPEN deal.

Every stochastic step (the synthetic evaluation-date draw, the train/test
split) is seeded via _RANDOM_SEED.
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
_MODEL_NAME = "deal_diagnostics"
_RANDOM_SEED = 42

# Scope: Commercial/Enterprise new-business opportunities only, matching
# fact_sales_activities' own scope exactly (see that mart's grain comment
# and generators/sales_activities.py's docstring) -- SMB has no rep and no
# activity rows; expansion/renewal are AM-owned and covered by am_activity,
# not this table.
_SEGMENTS = ("Commercial", "Enterprise")
_OPPORTUNITY_TYPE = "new_business"

# Stage funnels, transcribed from generators/config.py's NEW_BUSINESS_STAGES
# -- re-declared here rather than imported, matching analytics/forecast.py's
# and analytics/capacity_planning.py's precedent for a generator constant a
# Phase 4 module depends on.
_STAGES = {
    "Commercial": ["SAL", "SQO", "Proposal/Negotiation"],
    "Enterprise": ["SAL", "SQO", "POC", "Proposal/Negotiation"],
}
_CLOSED_STAGES = ("Closed Won", "Closed Lost")

# Expected end-to-end new-business cycle length in days by segment --
# analytics/forecast.py's own _EXPECTED_CYCLE_DAYS values for
# (segment, 'new_business'), restated here (new-business only; this module
# has no renewal/expansion population to carry the other four entries).
_EXPECTED_CYCLE_DAYS = {"Commercial": 29.5, "Enterprise": 120.0}

# POC reveal gate -- identical to analytics/forecast.py's
# _POC_REVEAL_LAG_DAYS and the identical reasoning: a POC result is knowable
# at eval_date only once the POC has actually concluded (past the POC stage,
# or sitting in it at least 14 days). Reading poc_outcome ungated would hand
# the model a result for a deal that hasn't reached POC yet.
_POC_REVEAL_LAG_DAYS = 14

# Rep ramp cutoff -- generators/opportunities.py's own _RAMP_FULL_DAYS,
# restated here matching analytics/forecast.py's and
# analytics/capacity_planning.py's precedent.
_RAMP_FULL_DAYS = 180

_RANK_ORDER = {"Omitted": 0, "Pipeline": 1, "Best Case": 2, "Commit": 3}
_CONFIDENT_REP_CATEGORIES = ("Commit", "Best Case")
_FORECAST_TREND_WINDOW_DAYS = 21

# =====================================================================
# Risk-flag thresholds -- PROPOSED, not yet confirmed. Each grounded
# against this build's own real-data distribution, the same discipline
# analytics/playbook_triggers.py's three rule thresholds use, and each
# checked for a real win-rate differential where one plausibly exists
# (reported honestly, including where it does NOT -- see
# _stalled_in_stage's own note below and docs/acme-corp-analytics-
# methods.md for the full grounding tables). Computed on a seeded random
# point-in-time snapshot drawn uniformly across each closed new-business
# deal's own [created_date, close_date) -- see build_training_rows.
# =====================================================================

# GONE_DARK: days since the deal's last touch, gated on deal_age_days >= 14
# so a brand-new deal with no activity yet is never flagged for having "gone
# quiet" before there was time to go quiet at all. 6 days sits at the 85th
# percentile of days-since-last-touch among deals with >=1 touch and
# deal_age_days >= 14 (n=902 snapshots at the canonical as_of_date=2025-11-30
# build_training_rows() population; both segments carry an indistinguishable
# distribution, so one shared threshold is used rather than two). Win rate
# 30.1% (not flagged) vs 15.3% (flagged, n=124) -- real, not huge,
# differential. Figures verified directly against compute_risk_flags()'s
# own output, not a separate approximation -- see
# docs/acme-corp-analytics-methods.md's Deal-level diagnostics entry.
_GONE_DARK_MIN_DEAL_AGE_DAYS = 14
_GONE_DARK_DAYS_SINCE_LAST_TOUCH = 6

# SINGLE_THREADED: distinct contact_ref count <= 1, gated on
# deal_age_days >= 21 (by day 21 the share of deals still single-threaded
# drops to 11.1% of the eligible population -- a genuine minority, not the
# norm -- vs. 26.7% at a 7-day gate, which would flag over a quarter of all
# deals and not be a trigger). This is the strongest single flag in this
# set: win rate 30.3% (not flagged) vs 0.0% (flagged, n=74, zero wins) --
# consistent with the generator's own multi-threading-vs-outcome wiring in
# generators/sales_activities.py.
_SINGLE_THREADED_MIN_DEAL_AGE_DAYS = 21
_SINGLE_THREADED_MAX_CONTACTS = 1

# COMPETITIVE_PRESSURE: >=3 competitive_signal touches in the trailing 60
# days. 3 sits at the 85th percentile of the trailing-60-day competitive-
# touch-count distribution (n=902). This flag differentiates OVERALL win
# rate only modestly (29.5% not flagged vs 23.4% flagged, n=145) -- elevated
# on won deals too, per generators/config.py's own
# SALES_ACTIVITY_COMPETITIVE_SIGNAL_RATE (0.09 for won vs only 0.04 for
# other_loss), so "any competitive chatter" alone is a middling win/loss
# signal. It IS a sharp, specific predictor of *which* lost deals lose to a
# competitor: among lost deals, the flag fires on 27.0% of competitive-
# loss-reason deals against 0.4-1.1% of every other loss_reason (n=389/364/
# 178/222). Read this flag primarily as "competitive risk," not "loss risk."
_COMPETITIVE_TRAILING_WINDOW_DAYS = 60
_COMPETITIVE_MIN_TOUCHES = 3

# STALLED_IN_STAGE: days_in_current_stage / (segment's expected cycle days /
# stage count) > 1.5 -- sits between the 85th (1.12) and 90th (1.33)
# percentile of the observed ratio (n=1,248 staged snapshots), fires on
# 6.2% of the population (n=100). Stated honestly rather than oversold:
# this flag shows the SMALLEST win-rate differential of the six (29.1%
# not flagged vs 27.0% flagged) -- consistent with analytics/forecast.py's
# own coefficient on the equivalent feature (stage_stall_ratio, -0.0101,
# near zero on the standardized scale). It is kept as a named flag because
# "this deal has sat in its current stage far longer than its segment's
# norm" is operationally actionable to a manager regardless of how weakly
# it independently predicts final outcome in this dataset -- the same
# treatment analytics/playbook_triggers.py's Rule 3 gives its own
# unexplained-direction finding: reported at its real, modest size, not
# inflated.
_STALL_RATIO_THRESHOLD = 1.5

# FORECAST_DOWNGRADED: the rep's most recent filed category is Commit or
# Best Case AND the manager downgraded at that same snapshot
# (is_manager_downgrade). This reuses, at per-deal current-snapshot grain,
# exactly the signal docs/acme-corp-analytics-methods.md's Forecast entry
# already validates over closing-quarter calls (a 20.2pp win-rate penalty)
# -- not a new, weaker composite invented for this module. Measured over
# this module's own (broader, whole-lifecycle) population the differential
# is more modest -- 29.3% (not flagged) vs. 24.6% (flagged, n=126, 7.8% of
# the population) -- because most of this module's snapshots are earlier in
# a deal's life than the Forecast entry's closing-quarter-only calls, not
# because the underlying signal is different.
_FORECAST_DOWNGRADE_MIN_REP_RANK = _RANK_ORDER["Best Case"]

# POC_AT_RISK (Enterprise only): poc_outcome == 'fail', gated on the POC
# having actually concluded (_POC_REVEAL_LAG_DAYS, identical gate to
# analytics/forecast.py). Among revealed Enterprise POCs (n=91 of 440
# Enterprise new-business rows in the canonical fitted population), win
# rate falls from a 28.8% base rate to 9.3% once a fail is revealed (n=54)
# and moves to 37.8% on a revealed pass (n=37) -- the strongest
# deal-mechanics flag in the set on the loss side, matching
# analytics/forecast.py's own large coefficient on poc_revealed_fail
# (though this module's own fitted coefficient on it is small -- see the
# collinearity caveat in docs/acme-corp-analytics-methods.md).
_POC_AT_RISK_SEGMENT = "Enterprise"

# Minimum closed-deal training rows before the ML component is fitted at
# all -- matching analytics/forecast.py's _MIN_TRAINING_ROWS precedent and
# reasoning: below this, "not computable, reason stated" beats a model
# fitted on a handful of deals.
_MIN_TRAINING_ROWS = 200

_NUMERIC_FEATURES = [
    "n_touches", "n_contacts", "days_since_last_touch", "meeting_held_rate",
    "touch_rate", "comp_count_60d", "deal_age_days", "deal_age_ratio",
    "has_entered_a_stage", "stage_progress", "days_in_current_stage",
    "stage_stall_ratio", "poc_revealed_pass", "poc_revealed_fail",
    "rep_is_ramping", "rep_tenure_days", "rep_confident_manager_downgrade",
]
_CATEGORICAL_FEATURES = ["segment", "current_stage"]
_MODEL_INPUTS = _NUMERIC_FEATURES + _CATEGORICAL_FEATURES

_TEST_FRACTION = 0.25

# Stated BEFORE reading the achieved figures into this file, per
# analytics-engineering-conventions' rule that an artifact with no stated
# success criterion cannot be validated later. Full grounding in
# docs/acme-corp-analytics-methods.md's Deal-level diagnostics entry.
#
# Floor: this module's snapshot population spans a deal's ENTIRE lifecycle
# (a synthetic eval_date drawn uniformly across [created_date, close_date)),
# not just the closing quarter analytics/forecast.py's ML lens is scored
# on -- so it deliberately mixes near-chance early-life snapshots (0.64 AUC
# measured in isolation at build time) with much stronger late-life ones
# (0.75). A pooled floor has to sit below either extreme.
# Ceiling: the leak-alarm floor/ceiling analytics/forecast.py and the
# Account health score both use for the identical reason -- a pooled AUC
# above this would be evidence of pattern-matching the generator's
# is_won -> engagement construction (see the module docstring's leakage
# investigation) rather than a genuine early-warning signal, and would be
# investigated as a breach rather than celebrated, the same treatment
# analytics/forecast.py's 2025-08-15 checkpoint received.
_TARGET_AUC_RANGE = (0.60, 0.85)
_TARGET_CALIBRATION_GAP = 0.05


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


def _ns(df: pd.DataFrame, columns) -> pd.DataFrame:
    """DuckDB returns datetime64[us]; pandas merge_asof refuses to join
    columns of differing datetime resolution. Normalise once at load,
    matching analytics/forecast.py's identical helper."""
    for column in columns:
        df[column] = pd.to_datetime(df[column]).astype("datetime64[ns]")
    return df


# =====================================================================
# Loaders -- marts layer only
# =====================================================================

def load_opportunities(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per opportunity_id, Commercial/Enterprise new-business
    only, restricted to created_date <= as_of_date. Source mart:
    fact_opportunities."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            """
            select opportunity_id, account_id, segment, opportunity_type, rep_id,
                   is_won, loss_reason, amount, poc_outcome, created_date, close_date
            from main_marts.fact_opportunities
            where segment in ('Commercial', 'Enterprise')
              and opportunity_type = 'new_business'
              and created_date <= ?
            """,
            [as_of_date],
        ).df()
    finally:
        if owns:
            con.close()
    return _ns(df, ["created_date", "close_date"])


def load_activities(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per activity_id, restricted to
    activity_timestamp <= as_of_date. Source mart: fact_sales_activities."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            """
            select opportunity_id, activity_type, outcome, activity_timestamp,
                   contact_ref, competitive_signal
            from main_marts.fact_sales_activities
            where activity_date <= ?
            """,
            [as_of_date],
        ).df()
    finally:
        if owns:
            con.close()
    return _ns(df, ["activity_timestamp"])


def load_stage_history(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per (opportunity_id, stage, entered_date), restricted
    to entered_date <= as_of_date and OPEN stages only. Source mart:
    fact_opportunity_stage_history. Matches analytics/forecast.py's identical
    loader and reasoning: dropping Closed Won/Lost rows at load makes it
    structurally impossible for a terminal stage row (entered on the close
    date) to leak into an as-of-date lookup."""
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
                   is_manager_downgrade
            from main_marts.fact_forecast_submissions
            where snapshot_date <= ?
            """,
            [as_of_date],
        ).df()
    finally:
        if owns:
            con.close()
    return _ns(df, ["snapshot_date"])


def load_rep_hire_dates(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per rep_id -- earliest hire_date across that rep's
    capacity periods. Source mart: dim_reps. Matches analytics/forecast.py's
    identical loader."""
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


def load_all(as_of_date: date, con=None) -> dict:
    """Loads every input this module reads, once, under one connection.
    Source marts: fact_opportunities, fact_sales_activities,
    fact_opportunity_stage_history, fact_forecast_submissions, dim_reps."""
    owns = con is None
    con = con or _connect()
    try:
        return {
            "opportunities": load_opportunities(as_of_date, con=con),
            "activities": load_activities(as_of_date, con=con),
            "stage_history": load_stage_history(as_of_date, con=con),
            "submissions": load_forecast_submissions(as_of_date, con=con),
            "rep_hire_dates": load_rep_hire_dates(as_of_date, con=con),
        }
    finally:
        if owns:
            con.close()


# =====================================================================
# Populations
# =====================================================================

def open_population(data: dict, as_of_date: date) -> pd.DataFrame:
    """Grain: one row per opportunity_id open at as_of_date -- created on or
    before it, not yet closed. Source mart: fact_opportunities. close_date
    is used only to decide open/closed, never as a feature, matching
    analytics/forecast.py's identical discipline for the same field."""
    as_of_ts = pd.Timestamp(as_of_date)
    opps = data["opportunities"]
    population = opps[
        (opps["created_date"] <= as_of_ts) & (opps["close_date"] > as_of_ts)
    ].copy()
    population["eval_date"] = as_of_ts
    return population.reset_index(drop=True)


def closed_population(data: dict, as_of_date: date) -> pd.DataFrame:
    """Grain: one row per opportunity_id closed on or before as_of_date.
    Source mart: fact_opportunities."""
    as_of_ts = pd.Timestamp(as_of_date)
    opps = data["opportunities"]
    return opps[opps["close_date"] <= as_of_ts].reset_index(drop=True)


# =====================================================================
# Point-in-time feature assembly (shared by flags and the ML component)
# =====================================================================

def _stage_funnel(segment: str):
    return _STAGES[segment]


def build_point_in_time_features(evaluations: pd.DataFrame, data: dict) -> pd.DataFrame:
    """Grain: one row per (opportunity_id, eval_date) supplied in
    `evaluations` (must carry opportunity_id, segment, rep_id, poc_outcome,
    created_date, eval_date). Source marts: fact_sales_activities,
    fact_opportunity_stage_history, fact_forecast_submissions, dim_reps.

    Every column is computed only from what was observable strictly on or
    before eval_date -- the latest open stage entered by then, the latest
    forecast submission filed by then, rep tenure at it, and every touch
    with activity_timestamp <= eval_date."""
    frame = evaluations.sort_values("eval_date").reset_index(drop=True)
    frame["eval_date"] = frame["eval_date"].astype("datetime64[ns]")

    # --- Engagement features from fact_sales_activities ---
    touches = data["activities"].merge(frame[["opportunity_id", "eval_date"]], on="opportunity_id")
    touches = touches[touches["activity_timestamp"] <= touches["eval_date"]]

    resolved_outcomes = ("held", "no_show", "rescheduled", "cancelled")
    agg = touches.groupby("opportunity_id").agg(
        n_touches=("activity_type", "size"),
        n_contacts=("contact_ref", "nunique"),
        last_touch=("activity_timestamp", "max"),
        n_meetings_held=("outcome", lambda s: (s == "held").sum()),
        n_meetings_resolved=("outcome", lambda s: s.isin(resolved_outcomes).sum()),
    ).reset_index()
    frame = frame.merge(agg, on="opportunity_id", how="left")
    for col in ["n_touches", "n_contacts", "n_meetings_held", "n_meetings_resolved"]:
        frame[col] = frame[col].fillna(0)

    days_before_eval = (touches["eval_date"] - touches["activity_timestamp"]).dt.days
    trailing_competitive = touches[
        (days_before_eval >= 0) & (days_before_eval <= _COMPETITIVE_TRAILING_WINDOW_DAYS)
    ]
    comp_counts = trailing_competitive.groupby("opportunity_id")["competitive_signal"].sum()
    comp_counts.name = "comp_count_60d"
    frame = frame.merge(comp_counts.reset_index(), on="opportunity_id", how="left")
    frame["comp_count_60d"] = frame["comp_count_60d"].fillna(0)

    frame["deal_age_days"] = (frame["eval_date"] - frame["created_date"]).dt.days
    # No touch yet: days_since_last_touch falls back to deal_age_days -- a
    # deal that has never been touched has been "dark" for its entire life,
    # not for an undefined/zero span.
    frame["days_since_last_touch"] = (frame["eval_date"] - frame["last_touch"]).dt.days
    frame["days_since_last_touch"] = frame["days_since_last_touch"].fillna(frame["deal_age_days"])
    # No meetings resolved yet: neutral 0.5 rather than 0.0, matching
    # analytics/forecast.py's neutral-fill precedent for an unobserved rate
    # (0.0 would read as "every meeting no-showed," which is not what "no
    # meeting has resolved yet" means).
    frame["meeting_held_rate"] = np.where(
        frame["n_meetings_resolved"] > 0,
        frame["n_meetings_held"] / frame["n_meetings_resolved"].replace(0, np.nan),
        np.nan,
    )
    frame["meeting_held_rate"] = frame["meeting_held_rate"].fillna(0.5)
    frame["touch_rate"] = frame["n_touches"] / frame["deal_age_days"].clip(lower=1)

    # --- Deal mechanics from fact_opportunity_stage_history ---
    frame = pd.merge_asof(
        frame.sort_values("eval_date"), data["stage_history"].sort_values("entered_date"),
        left_on="eval_date", right_on="entered_date", by="opportunity_id", direction="backward",
    )
    stage_counts, stage_indexes = [], []
    for segment, stage in zip(frame["segment"], frame["stage"]):
        funnel = _stage_funnel(segment)
        stage_counts.append(len(funnel))
        stage_indexes.append(funnel.index(stage) if isinstance(stage, str) and stage in funnel else -1)
    frame["stage_count"] = stage_counts
    frame["stage_index"] = stage_indexes
    frame["has_entered_a_stage"] = (frame["stage_index"] >= 0).astype(float)
    frame["current_stage"] = np.where(
        frame["stage_index"] >= 0, frame["stage"].astype(str), "pre_stage"
    )
    frame["stage_progress"] = np.where(
        frame["stage_index"] >= 0, (frame["stage_index"] + 1) / frame["stage_count"], 0.0
    )
    frame["days_in_current_stage"] = np.where(
        frame["stage_index"] >= 0,
        (frame["eval_date"] - frame["entered_date"]).dt.days,
        frame["deal_age_days"],
    )
    frame["expected_cycle_days"] = frame["segment"].map(_EXPECTED_CYCLE_DAYS)
    frame["stage_stall_ratio"] = frame["days_in_current_stage"] / (
        frame["expected_cycle_days"] / frame["stage_count"]
    )
    frame["deal_age_ratio"] = frame["deal_age_days"] / frame["expected_cycle_days"]

    poc_eligible = frame["segment"] == _POC_AT_RISK_SEGMENT
    poc_index = _STAGES[_POC_AT_RISK_SEGMENT].index("POC")
    revealed = poc_eligible & (
        (frame["stage_index"] > poc_index)
        | ((frame["stage_index"] == poc_index) & (frame["days_in_current_stage"] >= _POC_REVEAL_LAG_DAYS))
    )
    frame["poc_revealed"] = revealed
    frame["poc_revealed_pass"] = (revealed & (frame["poc_outcome"] == "pass")).astype(float)
    frame["poc_revealed_fail"] = (revealed & (frame["poc_outcome"] == "fail")).astype(float)

    # --- Rep ramp status from dim_reps ---
    frame = frame.merge(data["rep_hire_dates"], on="rep_id", how="left")
    frame["rep_tenure_days"] = (frame["eval_date"] - frame["hire_date"]).dt.days
    frame["rep_is_ramping"] = (frame["rep_tenure_days"] < _RAMP_FULL_DAYS).astype(float)

    # --- Forecast trajectory from fact_forecast_submissions ---
    submissions = data["submissions"].sort_values("snapshot_date")
    frame = pd.merge_asof(
        frame.sort_values("eval_date"), submissions,
        left_on="eval_date", right_on="snapshot_date", by="opportunity_id", direction="backward",
    )
    frame["is_manager_downgrade"] = frame["is_manager_downgrade"].map(lambda v: bool(v) if pd.notna(v) else False)
    frame["rep_forecast_rank"] = frame["rep_forecast_category"].map(_RANK_ORDER)
    frame["rep_confident_manager_downgrade"] = (
        frame["is_manager_downgrade"]
        & (frame["rep_forecast_rank"].fillna(-1) >= _FORECAST_DOWNGRADE_MIN_REP_RANK)
    ).astype(float)

    return frame.reset_index(drop=True)


# =====================================================================
# Structural component -- named risk flags (no fitting)
# =====================================================================

def compute_risk_flags(features: pd.DataFrame) -> pd.DataFrame:
    """Grain: one row per opportunity carried in `features`
    (build_point_in_time_features' output). Six deterministic threshold
    rules, each grounded against this build's own real-data distribution --
    see the _GONE_DARK_*/_SINGLE_THREADED_*/etc. constants above for the
    grounding of every threshold. No fitting anywhere in this function."""
    out = features.copy()

    out["flag_gone_dark"] = (
        (out["deal_age_days"] >= _GONE_DARK_MIN_DEAL_AGE_DAYS)
        & (out["days_since_last_touch"] > _GONE_DARK_DAYS_SINCE_LAST_TOUCH)
    )
    out["flag_single_threaded"] = (
        (out["deal_age_days"] >= _SINGLE_THREADED_MIN_DEAL_AGE_DAYS)
        & (out["n_contacts"] <= _SINGLE_THREADED_MAX_CONTACTS)
    )
    out["flag_competitive_pressure"] = out["comp_count_60d"] >= _COMPETITIVE_MIN_TOUCHES
    out["flag_stalled_in_stage"] = (
        (out["has_entered_a_stage"] == 1.0) & (out["stage_stall_ratio"] > _STALL_RATIO_THRESHOLD)
    )
    out["flag_forecast_downgraded"] = out["rep_confident_manager_downgrade"] == 1.0
    out["flag_poc_at_risk"] = (out["segment"] == _POC_AT_RISK_SEGMENT) & (out["poc_revealed_fail"] == 1.0)

    flag_columns = [
        "flag_gone_dark", "flag_single_threaded", "flag_competitive_pressure",
        "flag_stalled_in_stage", "flag_forecast_downgraded", "flag_poc_at_risk",
    ]
    out["risk_flags"] = out[flag_columns].apply(
        lambda row: [c[len("flag_"):] for c in flag_columns if row[c]], axis=1
    )
    out["flag_count"] = out[flag_columns].sum(axis=1).astype(int)
    return out


# =====================================================================
# Classification component -- fitted composite risk score
# =====================================================================

def build_training_rows(data: dict, as_of_date: date, seed: int = _RANDOM_SEED) -> pd.DataFrame:
    """Grain: one row per CLOSED Commercial/Enterprise new-business
    opportunity with close_date <= as_of_date, evaluated at one seeded
    synthetic point-in-time snapshot drawn UNIFORMLY across the deal's own
    [created_date, close_date) span. Source marts: fact_opportunities (via
    closed_population), fact_sales_activities, fact_opportunity_stage_history,
    fact_forecast_submissions, dim_reps.

    Uniform-across-the-whole-lifecycle, not "one call inside the closing
    quarter" (analytics/forecast.py's approach for ITS training rows): this
    module's production use is scoring an open deal at an ARBITRARY point in
    its life, from just-created to nearly closed, so training has to sample
    that same range for the two to be comparable -- a lesson stated directly
    for a different reason in analytics/forecast.py's own training-vs-
    production lead-time comparability check."""
    closed = closed_population(data, as_of_date)
    closed = closed[closed["close_date"] > closed["created_date"]]
    if closed.empty:
        return pd.DataFrame()

    rng = np.random.default_rng(seed)
    span_days = (closed["close_date"] - closed["created_date"]).dt.days.to_numpy()
    fractions = rng.uniform(0.0, 0.99, size=len(closed))
    closed = closed.reset_index(drop=True)
    closed["eval_date"] = closed["created_date"] + pd.to_timedelta(
        (fractions * span_days).astype(int), unit="D"
    )

    featured = build_point_in_time_features(closed, data)
    featured["label"] = featured["is_won"].apply(lambda w: 0 if w else 1)  # label = eventual LOSS
    return featured.sort_values(["eval_date", "opportunity_id"]).reset_index(drop=True)


def _make_pipeline() -> Pipeline:
    """Logistic regression, deliberately WITHOUT class_weight='balanced' --
    same reasoning analytics/forecast.py's ML lens gives for the same
    choice: the score is read as a risk-ranking probability, and this
    population's ~28.6% loss-... wait, this label is P(loss), base rate
    ~71.4% loss / 28.6% win-equivalent-base -- see the calibration note in
    docs/acme-corp-analytics-methods.md for the actual achieved base rate.
    Balancing is mild enough to skip cleanly, and skipping it keeps the
    score honestly calibrated rather than systematically inflated."""
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
    """Full fitted-coefficient table, one row per model input, on the
    STANDARDIZED / one-hot-encoded scale the classifier actually sees --
    relative-magnitude comparisons, not raw-unit effects, matching
    analytics/forecast.py's and analytics/health_score.py's identical
    disclosure."""
    preprocessor = pipeline.named_steps["preprocess"]
    classifier = pipeline.named_steps["classify"]
    return (
        pd.DataFrame({"feature": _feature_names(preprocessor), "coefficient": classifier.coef_[0]})
        .sort_values("coefficient", key=np.abs, ascending=False)
        .reset_index(drop=True)
    )


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
    """Mean predicted probability vs. actual base rate on held-out data.
    This model is expected to be calibrated (no reweighting applied),
    matching analytics/forecast.py's disclosure pattern rather than
    analytics/health_score.py's (which uses class_weight='balanced' and
    documents that this breaks calibration)."""
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


def train_risk_model(data: dict, as_of_date: date, log: bool = True) -> dict:
    """Fits the deal-level composite risk-score classifier
    (P(eventual loss)) and validates it on an OUT-OF-TIME held-out split
    (sorted by synthetic eval_date, last 25% held out) -- matching
    analytics/forecast.py's split rationale: production scores a deal at
    whatever point its life happens to be in "now," so a holdout drawn from
    later evaluation dates than every training row is the split that
    matches deployment.

    Grain: one row per closed new-business opportunity at one synthetic
    point-in-time snapshot. Source marts: fact_opportunities,
    fact_sales_activities, fact_opportunity_stage_history,
    fact_forecast_submissions, dim_reps.

    Returns computable=False with a stated reason rather than a model when
    fewer than _MIN_TRAINING_ROWS closed deals exist as of as_of_date."""
    features = build_training_rows(data, as_of_date)
    if len(features) < _MIN_TRAINING_ROWS or features["label"].nunique() < 2:
        return {
            "computable": False,
            "reason": f"fewer than {_MIN_TRAINING_ROWS} closed Commercial/Enterprise "
                      f"new-business opportunities as of {as_of_date} (have {len(features)})",
            "n_training_rows": len(features),
        }

    ordered = features.sort_values(["eval_date", "opportunity_id"]).reset_index(drop=True)
    cut = int(len(ordered) * (1 - _TEST_FRACTION))
    train_df, test_df = ordered.iloc[:cut].copy(), ordered.iloc[cut:].copy()

    pipeline = _make_pipeline()
    pipeline.fit(train_df[_MODEL_INPUTS], train_df["label"])
    test_proba = pipeline.predict_proba(test_df[_MODEL_INPUTS])[:, 1]
    auc = float(roc_auc_score(test_df["label"], test_proba))

    # Secondary read only -- stratified random split, same methodology
    # analytics/health_score.py and analytics/forecast.py both report
    # alongside their headline out-of-time figure for comparability.
    random_train, random_test = train_test_split(
        features, test_size=_TEST_FRACTION, random_state=_RANDOM_SEED, stratify=features["label"]
    )
    random_pipeline = _make_pipeline()
    random_pipeline.fit(random_train[_MODEL_INPUTS], random_train["label"])
    random_auc = float(roc_auc_score(
        random_test["label"], random_pipeline.predict_proba(random_test[_MODEL_INPUTS])[:, 1]
    ))

    # Operating threshold for the confusion matrix: the top quartile of
    # scored probability on the TRAINING population, matching
    # analytics/health_score.py's quantile-tier precedent for a score whose
    # primary consumption is a ranking (a watchlist), not a fixed 0.5 cut.
    train_proba_all = pipeline.predict_proba(train_df[_MODEL_INPUTS])[:, 1]
    operating_threshold = float(np.quantile(train_proba_all, 0.75))
    confusion = _confusion_at_threshold(test_df["label"], test_proba, operating_threshold)
    calibration = _calibration_check(test_df["label"], test_proba)
    coefficients = _coefficient_table(pipeline)

    if log:
        log_performance(_MODEL_NAME, as_of_date, "auc_holdout_out_of_time", auc)
        log_performance(_MODEL_NAME, as_of_date, "auc_holdout_random_split", random_auc)
        log_performance(_MODEL_NAME, as_of_date, "precision_flagged_tier", confusion["precision"])
        log_performance(_MODEL_NAME, as_of_date, "recall_flagged_tier", confusion["recall"])
        log_performance(_MODEL_NAME, as_of_date, "f1_flagged_tier", confusion["f1"])
        log_performance(_MODEL_NAME, as_of_date, "true_positive_flagged_tier", confusion["true_positive"])
        log_performance(_MODEL_NAME, as_of_date, "false_positive_flagged_tier", confusion["false_positive"])
        log_performance(_MODEL_NAME, as_of_date, "true_negative_flagged_tier", confusion["true_negative"])
        log_performance(_MODEL_NAME, as_of_date, "false_negative_flagged_tier", confusion["false_negative"])
        log_performance(_MODEL_NAME, as_of_date, "operating_threshold_probability",
                        confusion["operating_threshold_probability"])
        log_performance(_MODEL_NAME, as_of_date, "mean_predicted_probability",
                        calibration["mean_predicted_probability"])
        log_performance(_MODEL_NAME, as_of_date, "actual_base_rate", calibration["actual_base_rate"])
        log_performance(_MODEL_NAME, as_of_date, "calibration_gap", calibration["calibration_gap"])
        log_performance(_MODEL_NAME, as_of_date, "n_train", float(len(train_df)))
        log_performance(_MODEL_NAME, as_of_date, "n_holdout", float(len(test_df)))

    return {
        "computable": True,
        "pipeline": pipeline,
        "auc_holdout": auc,
        "auc_holdout_random_split": random_auc,
        "meets_auc_target": _TARGET_AUC_RANGE[0] <= auc <= _TARGET_AUC_RANGE[1],
        "n_train": len(train_df),
        "n_test": len(test_df),
        "n_train_positive": int(train_df["label"].sum()),
        "n_test_positive": int(test_df["label"].sum()),
        "features": features,
        "validation_package": {
            "coefficients": coefficients,
            "confusion_matrix_flagged_tier": confusion,
            "calibration": calibration,
        },
    }


# =====================================================================
# Top-level entry point
# =====================================================================

def score_open_deals(data: dict, as_of_date: date, model: dict = None) -> pd.DataFrame:
    """Grain: one row per open Commercial/Enterprise new-business
    opportunity as of as_of_date, carrying both the structural risk flags
    and (if the ML component is computable) the fitted composite risk
    score. Source marts: fact_opportunities, fact_sales_activities,
    fact_opportunity_stage_history, fact_forecast_submissions, dim_reps."""
    population = open_population(data, as_of_date)
    if population.empty:
        return population

    featured = build_point_in_time_features(population, data)
    flagged = compute_risk_flags(featured)

    if model is not None and model.get("computable"):
        proba = model["pipeline"].predict_proba(flagged[_MODEL_INPUTS])[:, 1]
        flagged["risk_score"] = proba
        threshold = model["validation_package"]["confusion_matrix_flagged_tier"][
            "operating_threshold_probability"
        ]
        flagged["score_flagged"] = flagged["risk_score"] >= threshold
    else:
        flagged["risk_score"] = np.nan
        flagged["score_flagged"] = False

    return flagged[
        [
            "opportunity_id", "account_id", "segment", "rep_id", "amount",
            "deal_age_days", "current_stage", "stage_progress",
            "risk_score", "score_flagged", "flag_count", "risk_flags",
            "flag_gone_dark", "flag_single_threaded", "flag_competitive_pressure",
            "flag_stalled_in_stage", "flag_forecast_downgraded", "flag_poc_at_risk",
        ]
    ].reset_index(drop=True)


def run_deal_diagnostics(as_of_date: date, con=None, log: bool = True) -> dict:
    """Top-level entry point. Loads all inputs once, fits/validates the
    risk-score classifier, scores every currently-open Commercial/Enterprise
    new-business opportunity with both flags and score, and returns a
    single dict a caller (a future weekly-readout wiring, or
    analytics-model-validator) can consume without re-deriving anything."""
    owns = con is None
    con = con or _connect()
    try:
        data = load_all(as_of_date, con=con)
        model = train_risk_model(data, as_of_date, log=log)
        scored = score_open_deals(data, as_of_date, model=model)
        return {
            "as_of_date": as_of_date,
            "n_open_deals": len(scored),
            "scored_deals": scored,
            "model": model,
            "flag_prevalence": (
                {
                    flag: int(scored[f"flag_{flag}"].sum())
                    for flag in [
                        "gone_dark", "single_threaded", "competitive_pressure",
                        "stalled_in_stage", "forecast_downgraded", "poc_at_risk",
                    ]
                }
                if not scored.empty else {}
            ),
        }
    finally:
        if owns:
            con.close()


# =====================================================================
# Validation -- synthetic known-answer scenarios for the flag layer,
# per analytics-engineering-conventions' "Structural/logic artifacts"
# category. Each scenario builds a minimal features-shaped row by hand and
# runs it through the exact same compute_risk_flags() the real diagnostic
# uses, matching analytics/playbook_triggers.py's and
# analytics/variance_diagnostic.py's identical pattern.
# =====================================================================

def _synthetic_row(**overrides) -> pd.DataFrame:
    """A minimal, fully-specified single-row features frame -- every column
    compute_risk_flags() reads, defaulted to an unambiguously "healthy deal"
    state, then overridden per scenario. Kept in one place so every
    scenario only states what it changes."""
    base = {
        "opportunity_id": "SYN-0001", "segment": "Commercial",
        "deal_age_days": 40, "days_since_last_touch": 1, "n_contacts": 3,
        "comp_count_60d": 0, "has_entered_a_stage": 1.0, "stage_stall_ratio": 0.5,
        "rep_confident_manager_downgrade": 0.0, "poc_revealed_fail": 0.0,
    }
    base.update(overrides)
    return pd.DataFrame([base])


def run_synthetic_scenarios() -> list:
    """Runs every scenario through compute_risk_flags() and checks the
    result against its declared expectation. Returns a list of
    {name, passed, detail} -- the same shape analytics/forecast.py's and
    analytics/variance_diagnostic.py's build-time validation functions use.
    """
    scenarios = [
        ("gone_dark_fires_past_threshold_on_aged_deal",
         _synthetic_row(deal_age_days=30, days_since_last_touch=7), "flag_gone_dark", True),
        ("gone_dark_does_not_fire_on_recent_touch",
         _synthetic_row(deal_age_days=30, days_since_last_touch=2), "flag_gone_dark", False),
        ("gone_dark_does_not_fire_on_brand_new_deal_even_with_no_touch",
         _synthetic_row(deal_age_days=5, days_since_last_touch=5), "flag_gone_dark", False),
        ("single_threaded_fires_on_aged_single_contact_deal",
         _synthetic_row(deal_age_days=25, n_contacts=1), "flag_single_threaded", True),
        ("single_threaded_does_not_fire_with_multiple_contacts",
         _synthetic_row(deal_age_days=25, n_contacts=4), "flag_single_threaded", False),
        ("single_threaded_does_not_fire_before_the_deal_age_gate",
         _synthetic_row(deal_age_days=10, n_contacts=1), "flag_single_threaded", False),
        ("competitive_pressure_fires_on_repeated_signals",
         _synthetic_row(comp_count_60d=3), "flag_competitive_pressure", True),
        ("competitive_pressure_does_not_fire_on_a_single_isolated_signal",
         _synthetic_row(comp_count_60d=1), "flag_competitive_pressure", False),
        ("stalled_in_stage_fires_well_past_segment_norm",
         _synthetic_row(has_entered_a_stage=1.0, stage_stall_ratio=2.0), "flag_stalled_in_stage", True),
        ("stalled_in_stage_does_not_fire_pre_stage",
         _synthetic_row(has_entered_a_stage=0.0, stage_stall_ratio=5.0), "flag_stalled_in_stage", False),
        ("forecast_downgraded_fires_on_confident_rep_manager_downgrade",
         _synthetic_row(rep_confident_manager_downgrade=1.0), "flag_forecast_downgraded", True),
        ("forecast_downgraded_does_not_fire_absent_a_downgrade",
         _synthetic_row(rep_confident_manager_downgrade=0.0), "flag_forecast_downgraded", False),
        ("poc_at_risk_fires_on_revealed_enterprise_fail",
         _synthetic_row(segment="Enterprise", poc_revealed_fail=1.0), "flag_poc_at_risk", True),
        ("poc_at_risk_excludes_commercial_even_with_a_revealed_fail_flag_set",
         _synthetic_row(segment="Commercial", poc_revealed_fail=1.0), "flag_poc_at_risk", False),
    ]
    results = []
    for name, row, flag_column, expected in scenarios:
        actual = bool(compute_risk_flags(row)[flag_column].iloc[0])
        results.append({
            "name": name, "passed": actual == expected,
            "detail": f"expected {flag_column}={expected}, got {actual}",
        })
    return results


def run_build_time_validation(as_of_date: date) -> list:
    """Runs every check this artifact has at build time and returns them
    all rather than raising on the first failure -- matching
    analytics/forecast.py's run_build_time_validation shape."""
    checks = []

    scenario_results = run_synthetic_scenarios()
    scenarios_passed = sum(r["passed"] for r in scenario_results)
    checks.append({
        "name": "synthetic_flag_scenarios",
        "passed": scenarios_passed == len(scenario_results),
        "detail": f"{scenarios_passed} of {len(scenario_results)} passed; "
                  f"failures: {[r['name'] for r in scenario_results if not r['passed']]}",
    })

    result = run_deal_diagnostics(as_of_date, log=False)
    scored = result["scored_deals"]
    flag_columns = [
        "flag_gone_dark", "flag_single_threaded", "flag_competitive_pressure",
        "flag_stalled_in_stage", "flag_forecast_downgraded", "flag_poc_at_risk",
    ]
    if not scored.empty:
        for col in flag_columns:
            share = scored[col].mean()
            checks.append({
                "name": f"{col}_is_selective",
                "passed": 0.0 < share < 1.0 or scored[col].sum() == 0,  # never-fires is reported, not a failure
                "detail": f"fires on {int(scored[col].sum())} of {len(scored)} open deals ({share:.1%})",
            })
    else:
        checks.append({
            "name": "open_population_nonempty",
            "passed": False,
            "detail": f"no open Commercial/Enterprise new-business deals as of {as_of_date} "
                      f"-- flag selectivity not checkable at this checkpoint",
        })

    model = result["model"]
    if model.get("computable"):
        vp = model["validation_package"]
        checks.append({
            "name": "auc_within_target",
            "passed": model["meets_auc_target"],
            "detail": f"out-of-time AUC {model['auc_holdout']:.4f}, target {_TARGET_AUC_RANGE}",
        })
        checks.append({
            "name": "calibration_within_target",
            "passed": vp["calibration"]["within_target"],
            "detail": f"gap {vp['calibration']['calibration_gap']:.4f}, "
                      f"target +/-{_TARGET_CALIBRATION_GAP}",
        })
    else:
        checks.append({
            "name": "ml_component_computable",
            "passed": False,
            "detail": model.get("reason", "not computable"),
        })

    return checks
