"""Pipeline coverage -- grain: one coverage reading per (evaluation date,
segment) for the quarter containing the evaluation date, Commercial and
Enterprise only; source marts: fact_opportunities (open and closed
new-business deals) and dim_reps (quota-bearing ISR/AE capacity periods),
reconciled against forecast.py's bottoms-up manager lens and
capacity_planning.py's quota panel.

Not one of the build spec's 22 Section 8 artifacts: a deliberate scope
addition made after that order closed, the post-Wave-8 improvement plan's
Wave 10 "Pipeline coverage artifact -- by segment, against realized
conversion, gap to quota in dollars." The question it answers is the one a
CRO asks every Monday: is there enough open new-business pipeline, at the
conversion this team has actually been realizing, to book the quota still
left to book this quarter?

A COVERAGE READING, NOT A FORECAST
----------------------------------
analytics/forecast.py is the only artifact that owns "what will close", and
this module never modifies, replaces or competes with its lenses. A coverage
reading answers a different question -- is the pipeline large enough --
using one realized-conversion constant per segment rather than a per-deal
probability. The two are reconciled against each other (reconcile_to_
forecast) and reported side by side, never merged, and every output field is
named so it cannot be mistaken for a forecast (conversion_implied_expected_
close_usd, never "forecast").

DEFINITIONS -- THIS ARTIFACT'S OWN, PROPOSED, NOT YET CONFIRMED
----------------------------------------------------------------
The metric tree defines no coverage metric (and this module redefines none
of the tree's metrics), so these are the artifact's own definitions. All of
them are stated in docs/acme-corp-analytics-methods.md's "Pipeline coverage"
entry; none is confirmed by an upstream document.

  quota                    sum of stated quota, for the quarter, of every
                           ISR (Commercial) / AE (Enterprise) with at least
                           one active day in [quarter start, evaluation
                           date]. capacity_planning's rule: stated quota is
                           never pro-rated for a mid-quarter hire or
                           departure, and a rep hired after the evaluation
                           date is not yet knowable and is not counted.
  won_to_date              new-business closed-won amount with close_date in
                           [quarter start, evaluation date].
  remaining_quota          max(0, quota - won_to_date).
  open_pipeline            ISR/AE-owned new-business deals open at the
                           evaluation date (created_date <= t < close_date)
                           whose close_date falls in the evaluation quarter
                           -- forecast.open_period_population's scoping,
                           where CRM close_date stands in for an expected-
                           close field Phase 1 does not generate.
  realized_conversion      dollar-weighted new-business win rate (won amount
                           / closed amount) of deals closed in the trailing
                           365 days, never reaching before 2023-01-01 (no
                           lost deal is logged before 2023, so any earlier
                           win rate is a structural 100%), by segment, and
                           only when at least 30 closed deals fall in the
                           window.
  required_pipeline_multiple   1 / realized_conversion.
  pipeline_coverage_ratio  open_pipeline / remaining_quota. (Named so it
                           cannot be confused with capacity_planning's
                           quota_coverage_ratio, which is expected capacity /
                           stated quota, a supply-side quantity.)
  coverage_vs_required     pipeline_coverage_ratio / required_pipeline_
                           multiple = open_pipeline x realized_conversion /
                           remaining_quota.
  conversion_implied_gap   remaining_quota - open_pipeline x realized_
                           conversion, in dollars; positive = shortfall.
  coverage_status          covered if coverage_vs_required >= 1.0; thin if
                           0.75 <= coverage_vs_required < 1.0; shortfall
                           below 0.75; quota_met if remaining quota is 0.
                           PROPOSED, not yet confirmed.

UNITS TRAP. forecast.open_pipeline_amount mixes new business, renewal and
expansion opportunities. Quota covers ISR/AE new business only, so every
figure here is restricted to opportunity_type = 'new_business' and the
difference is reported in the reconciliation block rather than hidden.

EVALUATION POINT. Commercial cycles are 14-45 days, so most Commercial
pipeline is created and closed inside the quarter; a reading taken at a
fixed relative point makes quarters comparable. The canonical point is
forecast._backtest_eval_date's mid-quarter Friday; as_of_date is the
evaluation date and any date can be used.

Shape decision -- structural/logic artifact, not a fitted model. Every
figure is a direct sum, ratio or difference of mart rows; the one estimated
quantity is the realized conversion, a pooled dollar-weighted rate. Per
analytics-engineering-conventions' "Structural/logic artifacts" category
there is no coefficient table, AUC, confusion matrix or R^2, and their
absence is deliberate. Model type selection and rationale: a fitted
pipeline-to-bookings regression (bookings ~ open pipeline x stage mix) was
the credible alternative and was rejected because (1) it would fit about 11
quarterly points per segment, (2) stage-conditional win rates are flat in
this data (every new-business deal logs every stage, so stage carries no
information about the outcome) and (3) the quantity a RevOps owner needs is
the arithmetic coverage identity, which a fitted estimate of it would only
blur. A per-deal win-probability model already exists, and is the forecast
artifact.

Point-in-time discipline. Every function takes as_of_date. Deals are
filtered to created_date <= as_of_date and a deal not closed by it carries no
outcome (known_at masks is-won and POC outcome), so a later outcome can never
reach a figure; quota periods are filtered to period_start_date <=
as_of_date. validation_no_lookahead() proves it against a perturbed copy of
the marts. No stochastic step exists except the seeded permutation test in
the backtest (_RANDOM_SEED).

No dbt model was added or changed for this artifact and no Phase 1
generator was touched.
"""
import json
import os
from datetime import date, timedelta
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

from . import capacity_planning as cp
from . import forecast as fc
from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
_MODEL_NAME = "pipeline_coverage"
_RANDOM_SEED = 42
_N_PERMUTATIONS = 10000

SEGMENTS = ("Commercial", "Enterprise")
# Verified one to one in the data (validation_segment_role_mapping): quota-
# bearing ISRs own Commercial new business, AEs own Enterprise. SMB has no
# rep, no pipeline and no quota.
_SEGMENT_ROLE = {"Commercial": "ISR", "Enterprise": "AE"}

# No lost deal is logged before 2023 (the first lost new-business deal
# closes 2023-01-03; every earlier closed deal is won), so any win rate
# measured earlier is a structural 100%, not a conversion. Also the start of
# the window in which quota is a steady-state target (capacity_planning's
# "fully supplied" window).
CONVERSION_WINDOW_START = date(2023, 1, 1)
_CONVERSION_TRAILING_DAYS = 365
# Below this many closed deals in the window the rate is reported as
# unavailable rather than computed off a handful of lumpy deals -- the same
# treatment forecast._MIN_TRAINING_ROWS and capacity_planning.
# _MIN_BASELINE_REP_QUARTERS give an under-supported estimate. PROPOSED.
_MIN_CLOSED_DEALS_FOR_CONVERSION = 30

# coverage_vs_required bands -- PROPOSED, not yet confirmed. 1.0 is the
# break-even by definition (expected closes equal remaining quota); 0.75 is
# the lower edge of "thin": a quarter of the required level is inside what
# deals still to be created in the quarter can plausibly add for Commercial
# (see the methods doc's late-created-bookings finding).
COVERED_MIN = 1.0
THIN_MIN = 0.75
# Relative tolerance at the band boundaries: a coverage_vs_required within
# this of 1.0 (or 0.75) sits on the boundary and takes the upper band, so the
# status and the sign of the conversion-implied gap can never disagree through
# floating-point noise.
_BAND_EPSILON = 1e-9

_FIRST_EVALUATED_QUARTER = pd.Period("2023Q1", freq="Q")
# Fixed constant-rate comparator for the backtest: expected bookings = won to
# date + 0.25 x open pipeline. 0.25 is stated in advance and is not fitted to
# the backtest quarters: it is the midpoint of the QA plan's benchmark
# new-business win-rate range for Enterprise (20-30%) and the floor of its
# Commercial range (25-35%). It is a comparator, not a recommendation.
_CONSTANT_RATE_BASELINE = 0.25
# Closed deals needed in each POC outcome class before the Enterprise POC-
# conditioned view is shown. PROPOSED.
_POC_MIN_CLOSED_PER_OUTCOME = 20

# Exact structural tie-outs: dollars to the cent, counts exactly.
_TOLERANCE_USD = 0.01
_FLOAT_TOLERANCE = 1e-9



def _ends_on_or_after(periods: pd.DataFrame, ts) -> pd.Series:
    """Mask of capacity periods still running on `ts` (an open-ended period,
    with a null end date, runs forever)."""
    end = periods["period_end_date"]
    return end.isna() | (end >= pd.Timestamp(ts))


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


# --------------------------------------------------------------------------
# Published text -- read verbatim by consumers (the dashboard) so none
# restates the artifact's own wording
# --------------------------------------------------------------------------

DEFINITIONS = {
    "pipeline_coverage_ratio": (
        "Open new-business pipeline expected to close this quarter, divided by the quota still "
        "left to book. 2.0x means two dollars of open pipeline for every dollar still needed."),
    "realized_conversion": (
        "The share of closed new-business dollars that were won, over the trailing 365 days and "
        "never reaching before January 2023 (no lost deals are logged earlier, so older win rates "
        "are a structural 100%)."),
    "required_pipeline_multiple": (
        "One divided by the realized conversion: how many dollars of open pipeline it has taken, "
        "on average, to book one dollar."),
    "coverage_vs_required": (
        "Coverage ratio divided by the required multiple. 1.0x means the open pipeline, at the "
        "conversion realized recently, is expected to close exactly the quota still left; below "
        "1.0x is short, above is ahead."),
    "conversion_implied_gap": (
        "Quota still left to book minus open pipeline x realized conversion, in dollars. Positive "
        "is a shortfall; negative means the pipeline is expected to over-deliver."),
    "coverage_status": (
        "covered at 1.0x or above, thin from 0.75x to 1.0x, shortfall below 0.75x, quota met when "
        "no quota is left. These bands are proposed, not yet confirmed."),
    "reading_not_forecast": (
        "A coverage reading says whether the pipeline is large enough. The forecast is "
        "the only owner of what will close; the two are reconciled, not merged."),
}

STATUS_RULE = {
    "covered_min_coverage_vs_required": COVERED_MIN,
    "thin_min_coverage_vs_required": THIN_MIN,
    "status": "proposed, not yet confirmed",
}

PIPELINE_COVERAGE_CAVEATS = (
    "Commercial and Enterprise new business only, owned by ISRs and AEs. Renewal and expansion "
    "opportunities are excluded because quota does not cover them; SMB is excluded because it "
    "has no pipeline and no quota.",
    "This is a coverage reading, not a forecast. It uses one realized conversion rate per "
    "segment; the forecast prices each open deal individually and stays the only owner "
    "of what will close. The two are reconciled in the reconciliation block and never merged.",
    "Open pipeline counts deals whose CRM close date falls in the quarter, the same stand-in for "
    "an expected-close date the forecast uses. The deal's eventual close date therefore decides "
    "which open deals count toward the quarter, an information advantage a live CRM expected-close "
    "field would not have. A backtest scenario scoping by created date plus the trailing median "
    "cycle instead, which uses no hindsight, is reported in the methods document. Deals expected "
    "to close after the quarter end are reported separately and not counted against this "
    "quarter's quota.",
    "Commercial deals are created and closed inside a quarter (14 to 45 day cycles), so a "
    "mid-quarter reading cannot see pipeline that has not been created yet and understates "
    "Commercial bookings by the amount that is. Enterprise cycles run 60 to 180 days, so the "
    "same effect is negligible there.",
    "Realized conversion is a dollar-weighted rate over the trailing 365 days, from January 2023 "
    "only. Stage-conditional win rates are flat in this data (every deal logs every stage), so "
    "no stage adjustment is applied; Enterprise rests on far fewer deals than Commercial and its "
    "rate moves more.",
    "Quota is the stated quarterly quota of every quota-bearing rep with an active day so far "
    "this quarter, never pro-rated for a mid-quarter hire or departure; a rep hired later in the "
    "quarter is not yet knowable and is not counted. Reps still ramping carry full stated quota.",
    "Quota is not a steady-state target before 2023 (attainment is structurally depressed in the "
    "build-out years), so readings are evaluated from 2023 onward.",
    "The data window ends in late December 2025: no deal closes after the last close date, so "
    "next-quarter coverage is structurally unavailable there, and is reported as unavailable, "
    "never as zero coverage.",
)


# --------------------------------------------------------------------------
# Formatting helpers (display strings the dashboard prints verbatim)
# --------------------------------------------------------------------------

def _usd(value) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "n/a"
    sign = "-" if value < 0 else ""
    v = abs(float(value))
    if v >= 1e6:
        return f"{sign}${v / 1e6:.2f}M"
    if v >= 1e3:
        return f"{sign}${v / 1e3:.1f}K"
    return f"{sign}${v:.0f}"


def _x(value, digits=2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}x"


def _pct(value, digits=1) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _deals(n: int) -> str:
    return f"{n} deal" if n == 1 else f"{n} deals"


def _round(value, digits):
    if value is None:
        return None
    value = float(value)
    return round(value, digits) if np.isfinite(value) else None


# --------------------------------------------------------------------------
# Loaders -- marts layer only, point-in-time by construction
# --------------------------------------------------------------------------

def load_data_window(con=None) -> dict:
    """Grain: a single dict. The dataset's last recorded close date, a
    property of the data window used only to explain where it ends (never an
    input to a figure). Source mart: fact_opportunities."""
    owns = con is None
    con = con or _connect()
    try:
        last = con.execute("select max(close_date) from main_marts.fact_opportunities").fetchone()[0]
    finally:
        if owns:
            con.close()
    return {"last_opportunity_close": pd.Timestamp(last).date() if last is not None else None}


def load_new_business_deals(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per ISR/AE-owned new-business opportunity (Commercial
    or Enterprise) with created_date <= as_of_date. Source mart:
    fact_opportunities.

    A deal not closed by as_of_date carries no outcome: is_won and
    poc_outcome are masked to missing, so no later outcome can reach any
    figure. close_date is kept for open deals and is read only to scope a
    deal to a quarter -- the same use forecast.open_period_population makes
    of it."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            """
            select opportunity_id, segment, owner_role, rep_id, is_won, amount,
                   poc_outcome, created_date, close_date
            from main_marts.fact_opportunities
            where opportunity_type = 'new_business'
              and owner_role in ('ISR', 'AE')
              and segment in ('Commercial', 'Enterprise')
              and created_date <= ?
            order by opportunity_id
            """,
            [as_of_date],
        ).df()
    finally:
        if owns:
            con.close()
    df["created_date"] = pd.to_datetime(df["created_date"]).astype("datetime64[ns]")
    df["close_date"] = pd.to_datetime(df["close_date"]).astype("datetime64[ns]")
    df["amount"] = df["amount"].astype(float)
    df["won"] = df["is_won"].astype(float)
    df = df.drop(columns=["is_won"])
    return known_at(df, pd.Timestamp(as_of_date))


def known_at(deals: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Grain: one row per deal created on or before `as_of`, with the
    outcome (won, poc_outcome) masked to missing for every deal not closed by
    `as_of`. Idempotent and monotone: it can only remove information."""
    as_of = pd.Timestamp(as_of)
    out = deals[deals["created_date"] <= as_of].copy()
    out["is_closed"] = out["close_date"] <= as_of
    out.loc[~out["is_closed"], "won"] = np.nan
    out["poc_outcome"] = out["poc_outcome"].where(out["is_closed"], None)
    return out.reset_index(drop=True)


def load_quota_periods(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per quota-bearing rep (ISR/AE) per capacity period
    with period_start_date <= as_of_date. Source mart: dim_reps, through
    capacity_planning's loader so the two artifacts read quota identically."""
    return cp.load_rep_capacity_periods(as_of_date, con=con)


# --------------------------------------------------------------------------
# Quarter arithmetic
# --------------------------------------------------------------------------

def quarter_of(as_of_date) -> dict:
    """Grain: a single dict -- the calendar quarter containing as_of_date."""
    t = pd.Timestamp(as_of_date).normalize()
    q = t.to_period("Q")
    start, end = q.start_time.normalize(), q.end_time.normalize()
    nxt = q + 1
    return {
        "period": f"{q.year}-Q{q.quarter}", "start": start, "end": end,
        "next_period": f"{nxt.year}-Q{nxt.quarter}",
        "next_start": nxt.start_time.normalize(), "next_end": nxt.end_time.normalize(),
        "days_into_quarter": int((t - start).days), "days_to_quarter_end": int((end - t).days),
    }


def mid_quarter_eval_date(quarter: pd.Period) -> pd.Timestamp:
    """The canonical evaluation point: forecast._backtest_eval_date's last
    Friday on or before the quarter's midpoint, so every quarter is read at a
    comparable point in its own cycle."""
    return fc._backtest_eval_date(quarter)


# --------------------------------------------------------------------------
# Components -- each a pure function of already-loaded frames
# --------------------------------------------------------------------------

def compute_quota(periods: pd.DataFrame, as_of_date, quarter_start, quarter_end,
                  only_active_at_as_of: bool = False) -> pd.DataFrame:
    """Grain: one row per segment. Stated quota for the quarter containing
    as_of_date, summed over every rep with at least one active day in
    [quarter_start, as_of_date] (or, with only_active_at_as_of, active on
    as_of_date itself -- used only for the next-quarter carry-forward).
    Quota is never pro-rated (capacity_planning's convention) and is the max
    over the rep's overlapping periods, which is the one value it holds
    within a quarter. Source mart: dim_reps."""
    t = pd.Timestamp(as_of_date)
    qs, qe = pd.Timestamp(quarter_start), pd.Timestamp(quarter_end)
    p = periods[
        (periods["period_start_date"] <= t)
        & _ends_on_or_after(periods, qs)
    ]
    active = p[p["rep_status"] == "active"]
    if only_active_at_as_of:
        active = active[_ends_on_or_after(active, t)]
    reps = active["rep_id"].unique()
    rows = []
    midpoint = qs + (qe - qs) / 2
    for segment in SEGMENTS:
        seg_p = p[(p["segment"] == segment) & p["rep_id"].isin(reps)]
        quota = seg_p.groupby("rep_id")["quota_amount"].max()
        attrs = seg_p.groupby("rep_id")["hire_date"].first()
        departed = seg_p[seg_p["rep_status"] == "departed"]["rep_id"].nunique()
        ramping = attrs[(midpoint - attrs).dt.days < cp._RAMP_FULL_DAYS].index
        rows.append({
            "segment": segment,
            "quota_usd": float(quota.sum()),
            "quota_reps": int(len(quota)),
            "quota_reps_departed_in_quarter": int(departed) if not only_active_at_as_of else 0,
            "quota_reps_ramping": int(len(ramping)),
            "ramping_quota_usd": float(quota.loc[quota.index.isin(ramping)].sum()),
        })
    return pd.DataFrame(rows)


def compute_won_to_date(deals: pd.DataFrame, as_of_date, quarter_start) -> pd.DataFrame:
    """Grain: one row per segment. New-business closed-won amount and deal
    count with close_date in [quarter_start, as_of_date]. Source mart:
    fact_opportunities."""
    t, qs = pd.Timestamp(as_of_date), pd.Timestamp(quarter_start)
    won = deals[(deals["won"] == 1.0) & (deals["close_date"] >= qs) & (deals["close_date"] <= t)]
    rows = []
    for segment in SEGMENTS:
        seg = won[won["segment"] == segment]
        rows.append({"segment": segment, "won_to_date_usd": float(seg["amount"].sum()),
                     "won_to_date_deals": int(len(seg))})
    return pd.DataFrame(rows)


def compute_open_pipeline(deals: pd.DataFrame, as_of_date, quarter_end, next_quarter_end) -> pd.DataFrame:
    """Grain: one row per segment. Deals open at as_of_date (created_date <=
    t < close_date), split by where CRM close_date places them: this
    quarter, any later quarter, and the next quarter specifically. Source
    mart: fact_opportunities."""
    t = pd.Timestamp(as_of_date)
    qe, nqe = pd.Timestamp(quarter_end), pd.Timestamp(next_quarter_end)
    open_ = deals[(deals["created_date"] <= t) & (deals["close_date"] > t)]
    rows = []
    for segment in SEGMENTS:
        seg = open_[open_["segment"] == segment]
        in_q = seg[seg["close_date"] <= qe]
        later = seg[seg["close_date"] > qe]
        nxt = later[later["close_date"] <= nqe]
        rows.append({
            "segment": segment,
            "open_pipeline_usd": float(in_q["amount"].sum()), "open_pipeline_deals": int(len(in_q)),
            "open_after_quarter_usd": float(later["amount"].sum()),
            "open_after_quarter_deals": int(len(later)),
            "open_next_quarter_usd": float(nxt["amount"].sum()),
            "open_next_quarter_deals": int(len(nxt)),
        })
    return pd.DataFrame(rows)


def compute_realized_conversion(deals: pd.DataFrame, as_of_date, segment: str) -> dict:
    """Grain: a single dict per segment. Dollar-weighted new-business win
    rate of deals closed in [max(2023-01-01, as_of_date - 364 days),
    as_of_date]; unavailable below _MIN_CLOSED_DEALS_FOR_CONVERSION closed
    deals. Source mart: fact_opportunities."""
    t = pd.Timestamp(as_of_date)
    start = max(pd.Timestamp(CONVERSION_WINDOW_START), t - timedelta(days=_CONVERSION_TRAILING_DAYS - 1))
    closed = deals[(deals["segment"] == segment) & deals["is_closed"]
                   & (deals["close_date"] >= start) & (deals["close_date"] <= t)]
    n_closed, n_won = int(len(closed)), int((closed["won"] == 1.0).sum())
    closed_usd = float(closed["amount"].sum())
    won_usd = float(closed.loc[closed["won"] == 1.0, "amount"].sum())
    out = {
        "window_start": start.date(), "window_end": t.date(), "closed_deals": n_closed,
        "won_deals": n_won, "closed_usd": closed_usd, "won_usd": won_usd,
        "rate": None, "available": False, "reason_code": None, "reason": None,
    }
    if t < pd.Timestamp(CONVERSION_WINDOW_START):
        out["reason_code"] = "before_conversion_window"
        out["reason"] = (f"the evaluation date precedes {CONVERSION_WINDOW_START}; no lost deal is logged "
                         "before then, so any earlier win rate is a structural 100% and no realized "
                         "conversion exists")
        return out
    if n_closed < _MIN_CLOSED_DEALS_FOR_CONVERSION or closed_usd <= 0:
        out["reason_code"] = "insufficient_closed_deals"
        out["reason"] = (
            f"only {n_closed} {segment} new-business deals closed in the conversion window "
            f"({start.date()} to {t.date()}); at least {_MIN_CLOSED_DEALS_FOR_CONVERSION} are "
            "needed and no lost deals are logged before 2023-01-01, so the window cannot reach "
            "back further")
        return out
    out["rate"] = won_usd / closed_usd
    out["available"] = out["rate"] > 0
    if not out["available"]:
        out["reason_code"] = "no_wins_in_window"
        out["reason"] = f"no {segment} deal was won in the conversion window; the required multiple is undefined"
    return out


def assess_coverage(quota_usd: float, won_to_date_usd: float, open_pipeline_usd: float,
                    conversion_rate: Optional[float]) -> dict:
    """Grain: a single dict. The pure coverage arithmetic, with no data
    access: remaining quota, coverage ratio, required multiple, coverage
    versus required, the conversion-implied gap and the status. Every
    undefined quantity is None, never zero or infinity."""
    remaining = max(0.0, float(quota_usd) - float(won_to_date_usd))
    out = {
        "quota_usd": float(quota_usd), "won_to_date_usd": float(won_to_date_usd),
        "attainment_to_date": (float(won_to_date_usd) / float(quota_usd)) if quota_usd > 0 else None,
        "remaining_quota_usd": remaining, "open_pipeline_usd": float(open_pipeline_usd),
        "pipeline_coverage_ratio": (float(open_pipeline_usd) / remaining) if remaining > 0 else None,
        "realized_conversion": conversion_rate,
        "required_pipeline_multiple": (1.0 / conversion_rate) if conversion_rate else None,
        "coverage_vs_required": None, "conversion_implied_expected_close_usd": None,
        "conversion_implied_gap_usd": None, "coverage_status": "unavailable",
        "reason_code": None, "reason": None,
    }
    if quota_usd <= 0:
        out["reason_code"] = "no_quota"
        out["reason"] = "no quota-bearing rep has an active day in this quarter, so there is no quota to cover"
        return out
    if remaining == 0:
        # Quota already met needs no conversion to be stated: the status is a
        # fact about won versus quota, not an estimate.
        out["coverage_status"] = "quota_met"
        if conversion_rate:
            expected = float(open_pipeline_usd) * conversion_rate
            out["conversion_implied_expected_close_usd"] = expected
            out["conversion_implied_gap_usd"] = remaining - expected
        return out
    if not conversion_rate:
        out["reason_code"] = "no_realized_conversion"
        out["reason"] = "realized conversion is unavailable, so required coverage and the gap cannot be stated"
        return out
    expected = float(open_pipeline_usd) * conversion_rate
    out["conversion_implied_expected_close_usd"] = expected
    # One quantity decides both the status band and the gap's sign, so they
    # cannot disagree: the shortfall as a fraction of remaining quota. A
    # fraction within _BAND_EPSILON of zero is exactly on the 1.0 boundary
    # (floating-point division of non-dyadic numbers lands a few ulps either
    # side of it) and is snapped to a zero gap, which is `covered`.
    shortfall_fraction = (remaining - expected) / remaining
    on_boundary = abs(shortfall_fraction) <= _BAND_EPSILON
    out["conversion_implied_gap_usd"] = 0.0 if on_boundary else remaining - expected
    out["coverage_vs_required"] = out["pipeline_coverage_ratio"] / out["required_pipeline_multiple"]
    cvr = out["coverage_vs_required"]
    if on_boundary or shortfall_fraction < 0:
        out["coverage_status"] = "covered"
    elif cvr >= THIN_MIN - _BAND_EPSILON:
        out["coverage_status"] = "thin"
    else:
        out["coverage_status"] = "shortfall"
    return out


_STATUS_TEXT = {
    "covered": "Covered",
    "thin": "Thin",
    "shortfall": "Shortfall",
    "quota_met": "Quota met",
    "unavailable": "Unavailable",
}


def _status_sentence(segment: str, a: dict, open_deals: int) -> str:
    """Grain: one sentence per segment reading, built from assess_coverage output; no data access."""
    status = a["coverage_status"]
    if status == "unavailable":
        return f"{segment}: coverage reading unavailable. {_cap(a['reason'])}."
    if status == "quota_met":
        return (f"{segment}: quota met for the quarter ({_usd(a['won_to_date_usd'])} won against "
                f"{_usd(a['quota_usd'])}); {_usd(a['open_pipeline_usd'])} still open across "
                f"{open_deals} deals.")
    verb = {"covered": "covered", "thin": "thin", "shortfall": "short"}[status]
    gap = a["conversion_implied_gap_usd"]
    gap_text = (f"expected to close {_usd(gap)} short of the quota still to book" if gap > 0
                else f"expected to close {_usd(-gap)} ahead of the quota still to book")
    return (f"{segment}: {verb}. {_usd(a['open_pipeline_usd'])} open across {_deals(open_deals)} "
            f"against {_usd(a['remaining_quota_usd'])} still to book is {_x(a['pipeline_coverage_ratio'])} "
            f"coverage; {_x(a['required_pipeline_multiple'])} is needed at the recent "
            f"{_pct(a['realized_conversion'])} win rate, so the pipeline is {_x(a['coverage_vs_required'])} "
            f"of required and, at that win rate, is {gap_text}.")


def _segment_reading(segment, quarter, as_of, quota_row, won_row, pipe_row, conv, data_window) -> dict:
    """Grain: one coverage reading for a segment, assembled from the per-segment component rows (source marts: fact_opportunities, dim_reps)."""
    a = assess_coverage(quota_row["quota_usd"], won_row["won_to_date_usd"],
                        pipe_row["open_pipeline_usd"], conv["rate"] if conv["available"] else None)
    reason_code, reason = a["reason_code"], a["reason"]
    if a["coverage_status"] == "unavailable" and conv["reason_code"] and a["reason_code"] == "no_realized_conversion":
        reason_code, reason = conv["reason_code"], conv["reason"]
    last_close = data_window.get("last_opportunity_close")
    after_window = last_close is not None and as_of.date() >= last_close
    if after_window:
        reason_code = "after_data_window"
        reason = (f"the evaluation date is on or after the last close in the data ({last_close}); "
                  "no deal can be open, so a coverage reading would be an empty-pipeline artifact")
        a["coverage_status"] = "unavailable"
        for k in ("coverage_vs_required", "conversion_implied_gap_usd", "conversion_implied_expected_close_usd"):
            a[k] = None
    status = "present" if a["coverage_status"] != "unavailable" else "unavailable"
    unavailable_a = dict(a, reason=reason, coverage_status="unavailable") if status == "unavailable" else a

    display = {
        "status_text": _STATUS_TEXT[a["coverage_status"]],
        "quota": _usd(a["quota_usd"]),
        "won_to_date": _usd(a["won_to_date_usd"]),
        "attainment_to_date": _pct(a["attainment_to_date"]),
        "remaining_quota": _usd(a["remaining_quota_usd"]),
        "open_pipeline": f"{_usd(a['open_pipeline_usd'])} across {_deals(pipe_row['open_pipeline_deals'])}",
        "pipeline_after_quarter_end": (
            f"{_usd(pipe_row['open_after_quarter_usd'])} across {_deals(pipe_row['open_after_quarter_deals'])} "
            "expected to close after quarter end, not counted"),
        "pipeline_coverage_ratio": _x(a["pipeline_coverage_ratio"]),
        "realized_conversion": (
            f"{_pct(conv['rate'])} over {conv['closed_deals']} closed deals since {conv['window_start']}"
            if conv["rate"] is not None else "unavailable"),
        "required_pipeline_multiple": _x(a["required_pipeline_multiple"]),
        "coverage_vs_required": _x(a["coverage_vs_required"]),
        "conversion_implied_expected_close": _usd(a["conversion_implied_expected_close_usd"]),
        "conversion_implied_gap": (
            "n/a" if a["conversion_implied_gap_usd"] is None
            else f"{_usd(a['conversion_implied_gap_usd'])} short" if a["conversion_implied_gap_usd"] > 0
            else f"{_usd(-a['conversion_implied_gap_usd'])} ahead"),
        "quota_basis": (
            f"{quota_row['quota_reps']} {_SEGMENT_ROLE[segment]}s with an active day so far this "
            f"quarter, stated quota not pro-rated; {quota_row['quota_reps_ramping']} still ramping "
            f"({_usd(quota_row['ramping_quota_usd'])} of quota)"),
        "summary": (_status_sentence(segment, unavailable_a, pipe_row["open_pipeline_deals"])
                    if status == "present" else f"{segment}: coverage reading unavailable. {_cap(reason)}."),
    }
    return {
        "segment": segment, "owner_role": _SEGMENT_ROLE[segment],
        "status": status, "reason_code": reason_code if status == "unavailable" else None,
        "reason": reason if status == "unavailable" else None,
        "period": quarter["period"], "as_of_date": as_of.date().isoformat(),
        "days_to_quarter_end": quarter["days_to_quarter_end"],
        "quota_usd": _round(a["quota_usd"], 2),
        "quota_reps": quota_row["quota_reps"],
        "quota_reps_departed_in_quarter": quota_row["quota_reps_departed_in_quarter"],
        "quota_reps_ramping": quota_row["quota_reps_ramping"],
        "ramping_quota_share": _round(quota_row["ramping_quota_usd"] / a["quota_usd"], 6) if a["quota_usd"] > 0 else None,
        "won_to_date_usd": _round(a["won_to_date_usd"], 2),
        "won_to_date_deals": won_row["won_to_date_deals"],
        "attainment_to_date": _round(a["attainment_to_date"], 6),
        "remaining_quota_usd": _round(a["remaining_quota_usd"], 2),
        "open_pipeline_usd": _round(a["open_pipeline_usd"], 2),
        "open_pipeline_deals": pipe_row["open_pipeline_deals"],
        "open_pipeline_after_quarter_usd": _round(pipe_row["open_after_quarter_usd"], 2),
        "open_pipeline_after_quarter_deals": pipe_row["open_after_quarter_deals"],
        "pipeline_coverage_ratio": _round(a["pipeline_coverage_ratio"], 8),
        "realized_conversion": _round(conv["rate"], 8),
        "conversion_closed_deals": conv["closed_deals"], "conversion_won_deals": conv["won_deals"],
        "conversion_window_start": conv["window_start"].isoformat(),
        "conversion_window_end": conv["window_end"].isoformat(),
        "required_pipeline_multiple": _round(a["required_pipeline_multiple"], 8),
        "coverage_vs_required": _round(a["coverage_vs_required"], 8),
        "conversion_implied_expected_close_usd": _round(a["conversion_implied_expected_close_usd"], 2),
        "conversion_implied_gap_usd": _round(a["conversion_implied_gap_usd"], 2),
        "coverage_status": a["coverage_status"] if status == "present" else "unavailable",
        "coverage_status_rule": "proposed, not yet confirmed",
        "poc_view": None,
        "display": display,
        "caveats": _segment_caveats(segment, quarter, quota_row, conv),
    }


def _segment_caveats(segment, quarter, quota_row, conv) -> list:
    """Grain: the caveats that apply to one segment reading; no data access."""
    out = []
    if pd.Timestamp(quarter["start"]) < pd.Timestamp(CONVERSION_WINDOW_START):
        out.append("This quarter starts before 2023, when quota is not a steady-state target and no "
                   "lost deals are logged; treat the reading as descriptive only.")
    if segment == "Enterprise":
        out.append(f"Enterprise conversion rests on {conv['closed_deals']} closed deals "
                   f"({conv['won_deals']} won); it moves more from quarter to quarter than Commercial's.")
    if segment == "Commercial":
        out.append("Commercial pipeline created later in the quarter is not yet visible; a mid-quarter "
                   "reading understates Commercial bookings by that amount.")
    if quota_row["quota_reps_departed_in_quarter"]:
        out.append(f"{quota_row['quota_reps_departed_in_quarter']} rep(s) departed during the quarter; "
                   "their stated quota is still counted, as it is in the capacity planning artifact.")
    return out


def _next_quarter_block(quarter, as_of, quota_next, pipe, conv_by_segment, data_window) -> dict:
    """Grain: one next-quarter block (per segment, no verdict) or an unavailable block at the data-window end. Source mart: fact_opportunities, dim_reps."""
    last_close = data_window.get("last_opportunity_close")
    if last_close is not None and quarter["next_start"].date() > last_close:
        return {
            "period": quarter["next_period"], "status": "unavailable",
            "reason_code": "beyond_data_window",
            "reason": (f"{quarter['next_period']} starts after the last close recorded in the data "
                       f"({last_close}), so no pipeline can exist for it; this is the edge of the "
                       "simulated window, not zero coverage"),
            "segments": [],
        }
    segments = []
    for segment in SEGMENTS:
        q = quota_next[quota_next["segment"] == segment].iloc[0]
        p = pipe[pipe["segment"] == segment].iloc[0]
        conv = conv_by_segment[segment]
        quota = float(q["quota_usd"])
        cov = (p["open_next_quarter_usd"] / quota) if quota > 0 else None
        rate = conv["rate"] if conv["available"] else None
        cvr = (cov * rate) if (cov is not None and rate) else None
        segments.append({
            "segment": segment, "period": quarter["next_period"],
            "carried_forward_quota_usd": _round(quota, 2),
            "open_pipeline_usd": _round(p["open_next_quarter_usd"], 2),
            "open_pipeline_deals": int(p["open_next_quarter_deals"]),
            "pipeline_coverage_ratio": _round(cov, 6),
            "coverage_vs_required": _round(cvr, 6),
            "coverage_status": "not_assessed",
            "display": {
                "open_pipeline": f"{_usd(p['open_next_quarter_usd'])} across {_deals(int(p['open_next_quarter_deals']))}",
                "carried_forward_quota": _usd(quota),
                "pipeline_coverage_ratio": (_x(_round(cov, 6)) if int(p["open_next_quarter_deals"])
                                            else "none yet (no deal is open for next quarter)"),
                "coverage_vs_required": (_x(_round(cvr, 6)) if int(p["open_next_quarter_deals"]) else "n/a"),
                "note": ("indicative only: next quarter's quota is not set yet, so this quarter's stated "
                         "quota of the reps active today is carried forward, and pipeline that has not "
                         "been created yet (all of it, for Commercial's short cycles) is not visible"),
            },
        })
    return {"period": quarter["next_period"], "status": "present", "reason_code": None,
            "reason": None, "segments": segments}


def compute_readings(deals: pd.DataFrame, periods: pd.DataFrame, as_of_date,
                     data_window: dict) -> dict:
    """Grain: one coverage reading per segment for the quarter containing
    as_of_date, plus the next-quarter block. A pure function of already-
    loaded frames (deals as from load_new_business_deals, periods as from
    load_quota_periods): everything it reads is filtered to as_of_date again
    here, so it is correct even when handed frames loaded later."""
    as_of = pd.Timestamp(as_of_date).normalize()
    quarter = quarter_of(as_of)
    d = known_at(deals, as_of)
    p = periods[periods["period_start_date"] <= as_of]
    quota = compute_quota(p, as_of, quarter["start"], quarter["end"])
    quota_next = compute_quota(p, as_of, quarter["start"], quarter["end"], only_active_at_as_of=True)
    won = compute_won_to_date(d, as_of, quarter["start"])
    pipe = compute_open_pipeline(d, as_of, quarter["end"], quarter["next_end"])
    conv = {s: compute_realized_conversion(d, as_of, s) for s in SEGMENTS}
    segments = [
        _segment_reading(s, quarter, as_of, quota[quota["segment"] == s].iloc[0],
                         won[won["segment"] == s].iloc[0], pipe[pipe["segment"] == s].iloc[0],
                         conv[s], data_window)
        for s in SEGMENTS
    ]
    return {
        "as_of_date": as_of.date().isoformat(), "period": quarter["period"],
        "quarter_start": quarter["start"].date().isoformat(),
        "quarter_end": quarter["end"].date().isoformat(),
        "days_into_quarter": quarter["days_into_quarter"],
        "days_to_quarter_end": quarter["days_to_quarter_end"],
        "segments": segments,
        "next_quarter": _next_quarter_block(quarter, as_of, quota_next, pipe, conv, data_window),
        "_conversion": conv,
    }


# --------------------------------------------------------------------------
# Enterprise POC-conditioned view -- indicative, clearly labelled
# --------------------------------------------------------------------------

def poc_conditioned_view(forecast_deals: pd.DataFrame, deals: pd.DataFrame, as_of_date,
                         overall_conversion: Optional[float]) -> dict:
    """Grain: a single dict. The one point-in-time conditioner that moves a
    win rate in this data: Enterprise POC outcome (pass wins far more often
    than fail). Open Enterprise deals whose POC has concluded by as_of_date
    (forecast's reveal gate, so an unconcluded POC is never read) are priced
    at the realized pass or fail win rate of closed Enterprise deals in the
    same window; deals not yet revealed stay at the overall conversion.
    Indicative: the closed-deal samples per class are stated."""
    t = pd.Timestamp(as_of_date)
    start = max(pd.Timestamp(CONVERSION_WINDOW_START), t - timedelta(days=_CONVERSION_TRAILING_DAYS - 1))
    closed = deals[(deals["segment"] == "Enterprise") & deals["is_closed"]
                   & (deals["close_date"] >= start) & (deals["close_date"] <= t)]
    rates = {}
    for outcome in ("pass", "fail"):
        c = closed[closed["poc_outcome"] == outcome]
        usd = float(c["amount"].sum())
        rates[outcome] = {
            "closed_deals": int(len(c)), "won_deals": int((c["won"] == 1.0).sum()),
            "rate": (float(c.loc[c["won"] == 1.0, "amount"].sum()) / usd) if usd > 0 else None,
        }
    base = {"label": "indicative, not a forecast", "window_start": start.date().isoformat(),
            "rates": rates, "status": "unavailable", "reason": None}
    if overall_conversion is None:
        base["reason"] = "overall realized conversion is unavailable"
        return base
    if any(rates[o]["closed_deals"] < _POC_MIN_CLOSED_PER_OUTCOME or rates[o]["rate"] is None
           for o in rates):
        base["reason"] = (f"fewer than {_POC_MIN_CLOSED_PER_OUTCOME} closed Enterprise deals in the "
                          "window for a POC outcome class")
        return base
    needed = {"segment", "opportunity_type", "amount", "poc_revealed_pass", "poc_revealed_fail"}
    if forecast_deals is None or not needed.issubset(set(forecast_deals.columns)):
        # The forecast's roll-up returns a bare frame without its feature
        # columns when no deal is open in the quarter at this date.
        base["reason"] = "no open deal carries a point-in-time POC state at this date"
        return base
    f = forecast_deals[(forecast_deals["segment"] == "Enterprise")
                       & (forecast_deals["opportunity_type"] == "new_business")]
    pass_ = f[f["poc_revealed_pass"] == 1.0]
    fail = f[f["poc_revealed_fail"] == 1.0]
    unrevealed = f[(f["poc_revealed_pass"] != 1.0) & (f["poc_revealed_fail"] != 1.0)]
    expected = (pass_["amount"].sum() * rates["pass"]["rate"] + fail["amount"].sum() * rates["fail"]["rate"]
                + unrevealed["amount"].sum() * overall_conversion)
    base.update({
        "status": "present",
        "open_pass_usd": _round(pass_["amount"].sum(), 2), "open_pass_deals": int(len(pass_)),
        "open_fail_usd": _round(fail["amount"].sum(), 2), "open_fail_deals": int(len(fail)),
        "open_unrevealed_usd": _round(unrevealed["amount"].sum(), 2),
        "open_unrevealed_deals": int(len(unrevealed)),
        "poc_conditioned_expected_close_usd": _round(expected, 2),
    })
    return base


# --------------------------------------------------------------------------
# Reconciliation to forecast.py -- reported, never merged
# --------------------------------------------------------------------------

def reconcile_to_forecast(readings: dict, as_of_date: date, con=None):
    """Grain: one row per segment, plus the forecast deal frame. Compares the
    coverage reading's open new-business pipeline and conversion-implied
    expected close with forecast.py's bottoms-up manager lens filtered to
    new business, same evaluation date and the same scoping. The forecast
    lens is shown for reconciliation only and is never used in a figure.
    Source: fact_opportunities, fact_forecast_submissions and the forecast
    artifact's own loaders."""
    owns = con is None
    con = con or _connect()
    try:
        data = fc.load_all(as_of_date, con=con)
        roll = fc.bottoms_up_rollup(data, pd.Timestamp(as_of_date), as_of_date, lens="manager")
    finally:
        if owns:
            con.close()
    deals = roll["deals"]
    rows = []
    for seg in readings["segments"]:
        if len(deals):
            nb = deals[(deals["segment"] == seg["segment"]) & (deals["opportunity_type"] == "new_business")]
            allt = deals[deals["segment"] == seg["segment"]]
        else:
            nb = allt = pd.DataFrame({"amount": [], "weighted_amount": []})
        f_open = float(nb["amount"].sum())
        f_weighted = float(nb["weighted_amount"].sum()) if len(nb) else 0.0
        expected = seg["conversion_implied_expected_close_usd"]
        rows.append({
            "segment": seg["segment"],
            "coverage_reading_open_pipeline_usd": seg["open_pipeline_usd"],
            "coverage_reading_open_deals": seg["open_pipeline_deals"],
            "forecast_new_business_open_pipeline_usd": _round(f_open, 2),
            "forecast_new_business_open_deals": int(len(nb)),
            "open_pipeline_difference_usd": _round(seg["open_pipeline_usd"] - f_open, 2),
            "coverage_reading_conversion_implied_expected_close_usd": expected,
            "forecast_manager_lens_new_business_weighted_usd": _round(f_weighted, 2),
            "difference_usd": None if expected is None else _round(expected - f_weighted, 2),
            "difference_pct_of_forecast_lens": (
                None if expected is None or f_weighted <= 0 else _round((expected - f_weighted) / f_weighted, 6)),
            "forecast_open_pipeline_all_opportunity_types_usd": _round(float(allt["amount"].sum()), 2),
            "forecast_open_deals_all_opportunity_types": int(len(allt)),
        })
    ties = all(r["open_pipeline_difference_usd"] is not None
               and abs(r["open_pipeline_difference_usd"]) <= _TOLERANCE_USD
               and r["coverage_reading_open_deals"] == r["forecast_new_business_open_deals"]
               for r in rows)
    block = {
        "status": "present",
        "basis": ("forecast.py bottoms-up manager lens, new-business deals only, evaluated at the same "
                  "date with the same open-deal scoping"),
        "ties_on_open_pipeline": bool(ties),
        "by_segment": rows,
        "note": ("The coverage reading and the forecast agree on which deals are open; they differ in how "
                 "the open dollars are priced (one realized conversion per segment versus a per-deal "
                 "category weight). The forecast remains the only owner of what will close; the "
                 "forecast's all-opportunity-type pipeline additionally includes renewals and expansions "
                 "that quota does not cover, which is why it is not used as the coverage numerator."),
    }
    return block, deals


# --------------------------------------------------------------------------
# Public entry point -- the dashboard's in-process call
# --------------------------------------------------------------------------

def run_pipeline_coverage(as_of_date: date, con=None, reconcile: bool = True) -> dict:
    """The artifact's headline output. Grain: one coverage reading per
    segment (Commercial, Enterprise) for the quarter containing as_of_date,
    the next-quarter block and, with reconcile=True, the reconciliation to
    forecast.py and the Enterprise POC-conditioned view. Source marts:
    fact_opportunities, dim_reps (and the forecast artifact's own inputs for
    the reconciliation). Output is JSON-safe and read verbatim by the
    dashboard."""
    owns = con is None
    con = con or _connect()
    try:
        deals = load_new_business_deals(as_of_date, con=con)
        periods = load_quota_periods(as_of_date, con=con)
        window = load_data_window(con=con)
        readings = compute_readings(deals, periods, as_of_date, window)
        conv = readings.pop("_conversion")
        if reconcile and all(s["status"] == "present" or s["reason_code"] != "after_data_window"
                             for s in readings["segments"]):
            ent = next(s for s in readings["segments"] if s["segment"] == "Enterprise")
            try:
                reconciliation, fdeals = reconcile_to_forecast(readings, as_of_date, con=con)
                ent["poc_view"] = poc_conditioned_view(
                    fdeals, known_at(deals, pd.Timestamp(as_of_date)), as_of_date,
                    conv["Enterprise"]["rate"] if conv["Enterprise"]["available"] else None)
            except Exception as exc:  # the forecast side must never take the coverage reading down
                reconciliation = {
                    "status": "unavailable", "reason_code": "forecast_side_unavailable",
                    "reason": ("the forecast's point-in-time feature builder could not run at this date "
                               f"({type(exc).__name__}); the coverage reading does not depend on it"),
                }
                ent["poc_view"] = {"label": "indicative, not a forecast", "status": "unavailable",
                                   "reason": "needs the forecast's point-in-time POC state, which is unavailable at this date"}
        else:
            reconciliation = {"status": "unavailable", "reason_code": "not_requested_or_after_data_window",
                              "reason": "reconciliation not requested or the evaluation date is past the data window"}
    finally:
        if owns:
            con.close()
    last_close = window["last_opportunity_close"]
    return _jsonable({
        "artifact": "pipeline_coverage",
        "label": "coverage reading, not a forecast",
        **readings,
        "reconciliation": reconciliation,
        "status_rule": STATUS_RULE,
        "definitions": DEFINITIONS,
        "caveats": list(PIPELINE_COVERAGE_CAVEATS),
        "data_window": {
            "last_opportunity_close": last_close.isoformat() if last_close else None,
            "conversion_window_start": CONVERSION_WINDOW_START.isoformat(),
            "note": (
                f"The last opportunity in the data closes {last_close}. Conversion is measured from "
                f"{CONVERSION_WINDOW_START} only, because no lost deal is logged earlier. "
                + ("This evaluation date is inside the quarter that contains the window end, so every "
                   "open deal scopes into the current quarter by construction."
                   if last_close and pd.Timestamp(as_of_date).to_period("Q") == pd.Timestamp(last_close).to_period("Q")
                   else "This evaluation date's quarter ends before the data window does.")),
        },
    })


# --------------------------------------------------------------------------
# Backtest of the coverage reading
# --------------------------------------------------------------------------

def _quarter_actuals(deals_full: pd.DataFrame, quarter: pd.Period, eval_date: pd.Timestamp) -> pd.DataFrame:
    """Grain: one row per segment. Actual quarter-end new-business bookings and the part from deals created after the evaluation date. Source mart: fact_opportunities."""
    qs, qe = quarter.start_time.normalize(), quarter.end_time.normalize()
    won = deals_full[(deals_full["won"] == 1.0) & (deals_full["close_date"] >= qs)
                     & (deals_full["close_date"] <= qe)]
    rows = []
    for segment in SEGMENTS:
        s = won[won["segment"] == segment]
        late = s[s["created_date"] > eval_date]
        rows.append({"segment": segment, "actual_usd": float(s["amount"].sum()),
                     "late_created_won_usd": float(late["amount"].sum())})
    return pd.DataFrame(rows)


def _pipeline_scenarios(d_known: pd.DataFrame, as_of: pd.Timestamp, quarter_end: pd.Timestamp,
                        segment: str) -> dict:
    """Grain: a single dict per segment. Two alternative open-pipeline figures
    for the backtest. (1) cycle-proxy: scope open deals to the quarter by a
    HINDSIGHT-FREE expected close (created_date + the trailing median
    created-to-close cycle of deals already closed in the conversion window)
    instead of the deal's eventual CRM close_date. (2) unscoped: every deal
    open at as_of, whatever its eventual close_date. A deal's openness at
    as_of is knowable; its eventual close_date is not. Source mart:
    fact_opportunities."""
    t = pd.Timestamp(as_of)
    start = max(pd.Timestamp(CONVERSION_WINDOW_START), t - timedelta(days=_CONVERSION_TRAILING_DAYS - 1))
    closed = d_known[(d_known["segment"] == segment) & d_known["is_closed"]
                     & (d_known["close_date"] >= start) & (d_known["close_date"] <= t)]
    open_ = d_known[(d_known["segment"] == segment) & (d_known["created_date"] <= t)
                    & (d_known["close_date"] > t)]
    out = {"median_cycle_days": np.nan, "open_cycle_proxy_usd": np.nan, "open_cycle_proxy_deals": np.nan,
           "open_unscoped_usd": float(open_["amount"].sum())}
    if len(closed) >= _MIN_CLOSED_DEALS_FOR_CONVERSION:
        cycle = float((closed["close_date"] - closed["created_date"]).dt.days.median())
        expected_close = open_["created_date"] + pd.to_timedelta(cycle, unit="D")
        scoped = open_[expected_close <= pd.Timestamp(quarter_end)]
        out.update({"median_cycle_days": cycle, "open_cycle_proxy_usd": float(scoped["amount"].sum()),
                    "open_cycle_proxy_deals": int(len(scoped))})
    return out


def backtest_coverage(as_of_date: date, deals_full: pd.DataFrame, periods_full: pd.DataFrame,
                      data_window: dict, con=None, reconcile: bool = True) -> pd.DataFrame:
    """Grain: one row per (quarter, segment) for every complete quarter from
    2023-Q1 whose quarter end <= as_of_date, evaluated at its own mid-quarter
    Friday using only what was known then. For each row: the coverage
    reading's fields, the coverage-implied expected bookings (won to date +
    open pipeline x realized conversion), the actual quarter-end new-business
    bookings, two naive baselines (won to date alone; mean of the prior four
    quarters' bookings) and the forecast manager lens for reconciliation.
    Source marts: fact_opportunities, dim_reps."""
    rows = []
    first = _FIRST_EVALUATED_QUARTER
    last = pd.Timestamp(as_of_date).to_period("Q")
    for quarter in pd.period_range(first, last, freq="Q"):
        qe = quarter.end_time.normalize()
        if qe > pd.Timestamp(as_of_date):
            continue
        t = mid_quarter_eval_date(quarter)
        r = compute_readings(deals_full, periods_full, t, data_window)
        conv = r["_conversion"]
        actual = _quarter_actuals(deals_full, quarter, t)
        quota_end = compute_quota(periods_full, qe, quarter.start_time.normalize(), qe)
        d_known = known_at(deals_full, t)
        qs_ts = quarter.start_time.normalize()
        elapsed_fraction = ((t - qs_ts).days + 1) / ((qe - qs_ts).days + 1)
        fdeals = None
        if reconcile:
            fdata = fc.load_all(t.date(), con=con)
            fdeals = fc.bottoms_up_rollup(fdata, t, t.date(), lens="manager")["deals"]
        for seg in r["segments"]:
            s = seg["segment"]
            a = actual[actual["segment"] == s].iloc[0]
            prior = []
            for i in range(1, 5):
                pq = quarter - i
                w = deals_full[(deals_full["segment"] == s) & (deals_full["won"] == 1.0)
                               & (deals_full["close_date"] >= pq.start_time.normalize())
                               & (deals_full["close_date"] <= pq.end_time.normalize())]
                prior.append(float(w["amount"].sum()))
            scen = _pipeline_scenarios(d_known, t, qe, s)
            row = {
                "period": r["period"], "segment": s, "eval_date": t.date().isoformat(),
                "status": seg["status"], "coverage_status": seg["coverage_status"],
                "quota_usd": seg["quota_usd"],
                "quota_at_quarter_end_usd": float(quota_end[quota_end["segment"] == s]["quota_usd"].iloc[0]),
                "won_to_date_usd": seg["won_to_date_usd"], "remaining_quota_usd": seg["remaining_quota_usd"],
                "open_pipeline_usd": seg["open_pipeline_usd"],
                "pipeline_coverage_ratio": seg["pipeline_coverage_ratio"],
                "realized_conversion": seg["realized_conversion"],
                "coverage_vs_required": seg["coverage_vs_required"],
                "conversion_implied_gap_usd": seg["conversion_implied_gap_usd"],
                "actual_usd": float(a["actual_usd"]),
                "late_created_won_usd": float(a["late_created_won_usd"]),
                "naive_won_to_date_usd": seg["won_to_date_usd"],
                "naive_trailing_4q_mean_usd": float(np.mean(prior)),
                "naive_constant_rate_usd": seg["won_to_date_usd"] + _CONSTANT_RATE_BASELINE * seg["open_pipeline_usd"],
                "naive_pace_usd": seg["won_to_date_usd"] / elapsed_fraction,
                "quarter_elapsed_fraction": elapsed_fraction,
                "median_cycle_days": scen["median_cycle_days"],
                "open_cycle_proxy_usd": scen["open_cycle_proxy_usd"],
                "open_unscoped_usd": scen["open_unscoped_usd"],
                "won_from_open_usd": float(a["actual_usd"]) - seg["won_to_date_usd"] - float(a["late_created_won_usd"]),
                "forecast_manager_lens_new_business_weighted_usd": np.nan,
                "forecast_new_business_open_pipeline_usd": np.nan,
            }
            if seg["realized_conversion"] is not None:
                rate = seg["realized_conversion"]
                row["coverage_implied_expected_usd"] = seg["won_to_date_usd"] + seg["open_pipeline_usd"] * rate
                row["cycle_proxy_expected_usd"] = seg["won_to_date_usd"] + scen["open_cycle_proxy_usd"] * rate
                row["unscoped_expected_usd"] = seg["won_to_date_usd"] + scen["open_unscoped_usd"] * rate
                row["visible_pipeline_priced_usd"] = seg["open_pipeline_usd"] * rate
            else:
                for k in ("coverage_implied_expected_usd", "cycle_proxy_expected_usd",
                          "unscoped_expected_usd", "visible_pipeline_priced_usd"):
                    row[k] = np.nan
            if fdeals is not None and len(fdeals):
                nb = fdeals[(fdeals["segment"] == s) & (fdeals["opportunity_type"] == "new_business")]
                row["forecast_manager_lens_new_business_weighted_usd"] = float(nb["weighted_amount"].sum())
                row["forecast_new_business_open_pipeline_usd"] = float(nb["amount"].sum())
            rows.append(row)
    bt = pd.DataFrame(rows)
    if bt.empty:
        return bt
    for col, label in (("coverage_implied_expected_usd", "coverage_implied"),
                       ("naive_won_to_date_usd", "naive_won_to_date"),
                       ("naive_trailing_4q_mean_usd", "naive_trailing_4q_mean"),
                       ("naive_constant_rate_usd", "naive_constant_rate"),
                       ("naive_pace_usd", "naive_pace"),
                       ("cycle_proxy_expected_usd", "cycle_proxy"),
                       ("unscoped_expected_usd", "unscoped")):
        bt[f"ape_{label}"] = (bt[col] - bt["actual_usd"]).abs() / bt["actual_usd"].replace(0, np.nan)
    bt["signed_error_pct"] = (bt["coverage_implied_expected_usd"] - bt["actual_usd"]) / bt["actual_usd"].replace(0, np.nan)
    bt["final_attainment"] = bt["actual_usd"] / bt["quota_at_quarter_end_usd"]
    bt["rest_of_quarter_actual_usd"] = bt["actual_usd"] - bt["won_to_date_usd"]
    bt["open_conversion_implied_usd"] = bt["coverage_implied_expected_usd"] - bt["won_to_date_usd"]
    bt["rest_of_quarter_vs_remaining_quota"] = bt["rest_of_quarter_actual_usd"] / bt["remaining_quota_usd"].replace(0, np.nan)
    return bt


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman rank correlation of two equal-length arrays; no data access."""
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def rank_relationship(x: pd.Series, y: pd.Series, seed: int = _RANDOM_SEED,
                      n_perm: int = _N_PERMUTATIONS) -> dict:
    """Grain: a single dict. Spearman rank correlation of x with y over the
    rows where both exist, with a seeded two-sided permutation p-value (no
    distributional assumption; _RANDOM_SEED fixes the shuffles). Sample size
    is reported because n here is about two dozen segment-quarters."""
    m = x.notna() & y.notna() & np.isfinite(x.astype(float)) & np.isfinite(y.astype(float))
    xv, yv = x[m].to_numpy(float), y[m].to_numpy(float)
    n = int(len(xv))
    if n < 5:
        return {"n": n, "rho": None, "p_value": None}
    rho = _spearman(xv, yv)
    rng = np.random.default_rng(seed)
    ry = pd.Series(yv).rank().to_numpy()
    rx = pd.Series(xv).rank().to_numpy()
    perm = np.array([np.corrcoef(rx, rng.permutation(ry))[0, 1] for _ in range(n_perm)])
    p = float((np.sum(np.abs(perm) >= abs(rho) - 1e-12) + 1) / (n_perm + 1))
    return {"n": n, "rho": _round(rho, 4), "p_value": _round(p, 4)}


def summarize_backtest(bt: pd.DataFrame) -> dict:
    """Grain: a single dict. The error distribution of the coverage-implied
    expected bookings against actual quarter-end new-business bookings, per
    segment and pooled, against two naive baselines, with the rank
    relationship between coverage and attainment and a status hit table."""
    if bt.empty:
        return {"rows": 0}
    ev = bt[bt["coverage_implied_expected_usd"].notna() & (bt["actual_usd"] > 0)]
    out = {"segment_quarters": int(len(bt)), "evaluated_segment_quarters": int(len(ev)),
           "unevaluated_segment_quarters": int(len(bt) - len(ev)), "by_segment": {}}
    for label, frame in [("pooled", ev)] + [(s, ev[ev["segment"] == s]) for s in SEGMENTS]:
        if frame.empty:
            continue
        ape = frame["ape_coverage_implied"]
        stats = {
            "n": int(len(frame)),
            "mape_coverage_implied": _round(ape.mean(), 4),
            "median_ape_coverage_implied": _round(ape.median(), 4),
            "p90_ape_coverage_implied": _round(ape.quantile(0.9), 4),
            "max_ape_coverage_implied": _round(ape.max(), 4),
            "aggregate_bias_pct": _round((frame["coverage_implied_expected_usd"].sum() - frame["actual_usd"].sum())
                                         / frame["actual_usd"].sum(), 4),
            "mean_signed_error_pct": _round(frame["signed_error_pct"].mean(), 4),
            "mape_naive_won_to_date": _round(frame["ape_naive_won_to_date"].mean(), 4),
            "mape_naive_trailing_4q_mean": _round(frame["ape_naive_trailing_4q_mean"].mean(), 4),
            "late_created_share_of_actual": _round(frame["late_created_won_usd"].sum() / frame["actual_usd"].sum(), 4),
            "mape_naive_constant_rate_025": _round(frame["ape_naive_constant_rate"].mean(), 4),
            "mape_naive_pace": _round(frame["ape_naive_pace"].mean(), 4),
            "mape_hindsight_free_scoping": _round(frame["ape_cycle_proxy"].mean(), 4),
            "mape_no_scoping": _round(frame["ape_unscoped"].mean(), 4),
            "visible_pipeline_pricing_bias_pct": _round(
                frame["visible_pipeline_priced_usd"].sum() / frame["won_from_open_usd"].sum() - 1, 4)
            if frame["won_from_open_usd"].sum() > 0 else None,
            "visible_reading_vs_visible_actual_pct": _round(
                (frame["won_to_date_usd"].sum() + frame["visible_pipeline_priced_usd"].sum())
                / (frame["won_to_date_usd"].sum() + frame["won_from_open_usd"].sum()) - 1, 4),
            "visible_pricing_excess_share_of_actual": _round(
                (frame["visible_pipeline_priced_usd"].sum() - frame["won_from_open_usd"].sum())
                / frame["actual_usd"].sum(), 4),
            "median_cycle_days_mean": _round(frame["median_cycle_days"].mean(), 1),
        }
        stats["beats_both_naive_baselines"] = bool(
            stats["mape_coverage_implied"] < stats["mape_naive_won_to_date"]
            and stats["mape_coverage_implied"] < stats["mape_naive_trailing_4q_mean"])
        stats["beats_constant_rate_baseline"] = bool(stats["mape_coverage_implied"] < stats["mape_naive_constant_rate_025"])
        stats["beats_pace_baseline"] = bool(stats["mape_coverage_implied"] < stats["mape_naive_pace"])
        if label == "pooled":
            out["pooled"] = stats
        else:
            out["by_segment"][label] = stats
    pooled = out["pooled"]
    best_naive = min(pooled["mape_naive_won_to_date"], pooled["mape_naive_trailing_4q_mean"])
    out["mape_ratio_vs_naive_baseline"] = _round(pooled["mape_coverage_implied"] / best_naive, 4)
    rel = bt[bt["coverage_vs_required"].notna()]
    ev_rows = bt[bt["open_conversion_implied_usd"].notna()]
    out["rank_relationships"] = {
        "coverage_vs_required_to_final_attainment_pooled":
            rank_relationship(rel["coverage_vs_required"], rel["final_attainment"]),
        "pipeline_coverage_ratio_to_final_attainment_pooled":
            rank_relationship(rel["pipeline_coverage_ratio"], rel["final_attainment"]),
        "open_pipeline_x_conversion_to_rest_of_quarter_bookings_pooled":
            rank_relationship(ev_rows["open_conversion_implied_usd"], ev_rows["rest_of_quarter_actual_usd"]),
        "coverage_vs_required_to_rest_of_quarter_vs_remaining_quota_pooled":
            rank_relationship(rel["coverage_vs_required"], rel["rest_of_quarter_vs_remaining_quota"]),
        "won_to_date_attainment_to_final_attainment_pooled":
            rank_relationship(bt["won_to_date_usd"] / bt["quota_usd"], bt["final_attainment"]),
    }
    for s in SEGMENTS:
        r = rel[rel["segment"] == s]
        out["rank_relationships"][f"coverage_vs_required_to_final_attainment_{s.lower()}"] = (
            rank_relationship(r["coverage_vs_required"], r["final_attainment"]))
    hit = []
    for status in ("covered", "thin", "shortfall", "quota_met"):
        f = bt[bt["coverage_status"] == status]
        if f.empty:
            hit.append({"coverage_status": status, "n": 0, "reached_full_quota": None, "median_final_attainment": None})
            continue
        hit.append({"coverage_status": status, "n": int(len(f)),
                    "reached_full_quota": int((f["final_attainment"] >= 1.0).sum()),
                    "median_final_attainment": _round(f["final_attainment"].median(), 4)})
    out["status_outcomes"] = hit
    fr = bt[bt["forecast_manager_lens_new_business_weighted_usd"].notna()
            & bt["coverage_implied_expected_usd"].notna()]
    if not fr.empty:
        ratio = ((fr["coverage_implied_expected_usd"] - fr["won_to_date_usd"])
                 / fr["forecast_manager_lens_new_business_weighted_usd"].replace(0, np.nan))
        out["forecast_reconciliation"] = {
            "rows": int(len(fr)),
            "open_pipeline_max_abs_diff_usd": _round(
                (fr["open_pipeline_usd"] - fr["forecast_new_business_open_pipeline_usd"]).abs().max(), 4),
            "conversion_implied_to_forecast_manager_lens_ratio_median": _round(ratio.median(), 4),
            "conversion_implied_to_forecast_manager_lens_ratio_min": _round(ratio.min(), 4),
            "conversion_implied_to_forecast_manager_lens_ratio_max": _round(ratio.max(), 4),
        }
    return out


def backtest_sensitivity_expanding_window(deals_full: pd.DataFrame, periods_full: pd.DataFrame,
                                          as_of_date: date, bt: pd.DataFrame) -> dict:
    """Grain: a single dict. Sensitivity of the backtest MAPE to the choice
    of conversion window: the same coverage-implied expected bookings with
    realized conversion measured over an expanding window from 2023-01-01
    rather than the trailing 365 days. Reported, not tuned to."""
    rows = []
    for _, r in bt.iterrows():
        t = pd.Timestamp(r["eval_date"])
        d = known_at(deals_full, t)
        closed = d[(d["segment"] == r["segment"]) & d["is_closed"] & (d["close_date"] >= pd.Timestamp(CONVERSION_WINDOW_START))]
        if len(closed) < _MIN_CLOSED_DEALS_FOR_CONVERSION or closed["amount"].sum() <= 0:
            continue
        rate = closed.loc[closed["won"] == 1.0, "amount"].sum() / closed["amount"].sum()
        exp = r["won_to_date_usd"] + r["open_pipeline_usd"] * rate
        if r["actual_usd"] > 0:
            rows.append({"segment": r["segment"], "ape": abs(exp - r["actual_usd"]) / r["actual_usd"]})
    df = pd.DataFrame(rows)
    if df.empty:
        return {}
    return {"n": int(len(df)), "mape_expanding_window_pooled": _round(df["ape"].mean(), 4),
            **{f"mape_expanding_window_{s.lower()}": _round(df[df["segment"] == s]["ape"].mean(), 4)
               for s in SEGMENTS}}


# --------------------------------------------------------------------------
# Validation -- reconciliations, synthetic known answers, perturbation
# --------------------------------------------------------------------------

def _mark(check: dict) -> str:
    """Printed marker for a check: PASS; otherwise FAIL for a structural check,
    MISS for an unmet target, INFO for a reported comparison that gates nothing."""
    if check["passed"] and check["kind"] != "info":
        return "PASS"
    return {"structural": "FAIL", "target": "MISS", "info": "INFO"}[check["kind"]]


def _check(name, passed, detail, kind="structural") -> dict:
    """One validation result record; kind is structural (a failure prints [FAIL]) or target (an unmet target prints [MISS])."""
    return {"name": name, "passed": bool(passed), "detail": detail, "kind": kind}


def validation_open_pipeline_ties_to_sql(eval_dates, deals_full, con) -> dict:
    """Independent-path tie-out: the open new-business pipeline computed
    from frames equals a direct SQL aggregate over fact_opportunities, per
    segment, at each evaluation date -- dollars to the cent, counts exact."""
    worst, n = 0.0, 0
    count_mismatch = 0
    for t in eval_dates:
        t = pd.Timestamp(t)
        q = quarter_of(t)
        d = known_at(deals_full, t)
        pipe = compute_open_pipeline(d, t, q["end"], q["next_end"])
        sql = con.execute(
            """
            select segment, coalesce(sum(amount), 0), count(*)
            from main_marts.fact_opportunities
            where opportunity_type = 'new_business' and owner_role in ('ISR', 'AE')
              and segment in ('Commercial', 'Enterprise')
              and created_date <= ? and close_date > ? and close_date <= ?
            group by 1
            """,
            [t.date(), t.date(), q["end"].date()],
        ).fetchall()
        sql = {s: (float(a), int(c)) for s, a, c in sql}
        for _, row in pipe.iterrows():
            amount, count = sql.get(row["segment"], (0.0, 0))
            worst = max(worst, abs(row["open_pipeline_usd"] - amount))
            count_mismatch += int(row["open_pipeline_deals"] != count)
            n += 1
    return _check("open_pipeline_ties_to_independent_sql",
                  worst <= _TOLERANCE_USD and count_mismatch == 0,
                  f"{n} segment-dates; max abs diff ${worst:.2f}; {count_mismatch} count mismatches")


def validation_quota_and_wins_tie_to_capacity_planning(as_of_date, periods_full, deals_full, con) -> list:
    """Reconciles this module's quota rule and won-to-date to capacity_
    planning's complete-quarter panel: evaluated at each quarter's last day,
    quota equals the panel's stated quota (and rep count) and won-to-date
    equals its won ARR, per segment, for every complete quarter from 2023-Q1."""
    panel = cp.build_rep_quarter_panel(as_of_date, con=con)
    panel = panel[panel["quarter"] >= pd.Timestamp(CONVERSION_WINDOW_START)]
    agg = panel.groupby(["quarter", "segment"]).agg(
        quota=("stated_quota", "sum"), reps=("rep_id", "nunique"), won=("won_arr", "sum")).reset_index()
    worst_q, worst_w, rep_mismatch, n = 0.0, 0.0, 0, 0
    for _, row in agg.iterrows():
        qs = pd.Timestamp(row["quarter"])
        qe = (qs.to_period("Q")).end_time.normalize()
        quota = compute_quota(periods_full, qe, qs, qe)
        won = compute_won_to_date(known_at(deals_full, qe), qe, qs)
        qq = quota[quota["segment"] == row["segment"]].iloc[0]
        ww = won[won["segment"] == row["segment"]].iloc[0]
        worst_q = max(worst_q, abs(qq["quota_usd"] - row["quota"]))
        worst_w = max(worst_w, abs(ww["won_to_date_usd"] - row["won"]))
        rep_mismatch += int(qq["quota_reps"] != row["reps"])
        n += 1
    return [
        _check("quota_ties_to_capacity_planning_panel", worst_q <= _TOLERANCE_USD and rep_mismatch == 0,
               f"{n} segment-quarters; max abs diff ${worst_q:.2f}; {rep_mismatch} rep-count mismatches"),
        _check("won_to_date_ties_to_capacity_planning_wins", worst_w <= _TOLERANCE_USD,
               f"{n} segment-quarters; max abs diff ${worst_w:.2f}"),
    ]


def validation_quota_constant_within_quarter(periods_full, as_of_date) -> dict:
    """The quota rule takes one value per rep per quarter (the max over its
    overlapping periods); that is only the rep's quota if it never varies
    inside a quarter. Checked over every rep-quarter from 2023-Q1."""
    bad, n = 0, 0
    for quarter in pd.period_range(_FIRST_EVALUATED_QUARTER, pd.Timestamp(as_of_date).to_period("Q"), freq="Q"):
        qs, qe = quarter.start_time.normalize(), quarter.end_time.normalize()
        p = periods_full[(periods_full["period_start_date"] <= qe)
                         & _ends_on_or_after(periods_full, qs)
                         & periods_full["quota_amount"].notna()]
        spread = p.groupby("rep_id")["quota_amount"].agg(lambda s: s.max() - s.min())
        bad += int((spread > 0).sum())
        n += int(len(spread))
    return _check("quota_constant_within_quarter", bad == 0, f"{n} rep-quarters; {bad} with quota varying inside the quarter")


def validation_segment_role_mapping(con) -> dict:
    """Grain: one check. ISR owns only Commercial and AE only Enterprise new business. Source mart: fact_opportunities."""
    rows = con.execute(
        "select segment, owner_role, count(*) from main_marts.fact_opportunities "
        "where opportunity_type = 'new_business' and owner_role in ('ISR', 'AE') group by 1, 2"
    ).fetchall()
    ok = all(_SEGMENT_ROLE.get(s) == r for s, r, _ in rows) and len(rows) == 2
    return _check("segment_owner_role_one_to_one", ok, "; ".join(f"{s}/{r}: {c}" for s, r, c in sorted(rows)))


def validation_pre_2023_win_rate_is_structural(deals_full) -> dict:
    """Why the conversion window starts in 2023: every closed new-business
    ISR/AE deal before 2023-01-01 is won, so any rate measured there is a
    structural 100%, not a conversion."""
    pre = deals_full[deals_full["is_closed"] & (deals_full["close_date"] < pd.Timestamp(CONVERSION_WINDOW_START))]
    return _check("pre_2023_closed_deals_are_all_won", len(pre) > 0 and bool((pre["won"] == 1.0).all()),
                  f"{len(pre)} closed deals before {CONVERSION_WINDOW_START}; {int((pre['won'] == 1.0).sum())} won")


def validation_identities(rows: list) -> dict:
    """Arithmetic identities of the definitions, over every present reading
    given: remaining = max(0, quota - won); gap = remaining - open x
    conversion; coverage_vs_required = coverage x conversion; required x
    conversion = 1; and covered/thin/shortfall agree with the gap's sign and
    the stated bands."""
    bad = []
    for r in rows:
        if r["coverage_status"] in ("unavailable",):
            continue
        if abs(r["remaining_quota_usd"] - max(0.0, r["quota_usd"] - r["won_to_date_usd"])) > _TOLERANCE_USD:
            bad.append((r["segment"], r["as_of_date"], "remaining"))
        conv = r["realized_conversion"]
        if conv is None:
            continue
        if abs(r["required_pipeline_multiple"] * conv - 1.0) > 1e-6:
            bad.append((r["segment"], r["as_of_date"], "required multiple"))
        implied = r["remaining_quota_usd"] - r["open_pipeline_usd"] * conv
        if abs(r["conversion_implied_gap_usd"] - implied) > 0.05:
            bad.append((r["segment"], r["as_of_date"], "gap"))
        if r["coverage_status"] != "quota_met":
            if abs(r["coverage_vs_required"] - r["pipeline_coverage_ratio"] * conv) > 1e-6:
                bad.append((r["segment"], r["as_of_date"], "coverage vs required"))
            if (r["coverage_vs_required"] >= 1.0) != (r["conversion_implied_gap_usd"] <= 0.05):
                if abs(r["conversion_implied_gap_usd"]) > 0.05:
                    bad.append((r["segment"], r["as_of_date"], "gap sign"))
    return _check("coverage_definitions_hold_as_identities", not bad, f"{len(rows)} readings; violations: {bad[:3]}")


def validation_conversion_window(rows: list) -> dict:
    """Grain: one check over the readings given: no conversion window starts before 2023-01-01."""
    bad = [(r["segment"], r["as_of_date"]) for r in rows if r["conversion_window_start"] < CONVERSION_WINDOW_START.isoformat()]
    return _check("conversion_window_never_reaches_before_2023", not bad,
                  f"{len(rows)} readings; earliest window start "
                  f"{min(r['conversion_window_start'] for r in rows)}")


def _synthetic_deal(oid, segment, amount, created, close, won):
    """Grain: one synthetic deal row for the known-answer scenarios; no data access."""
    return {"opportunity_id": oid, "segment": segment,
            "owner_role": _SEGMENT_ROLE[segment], "rep_id": "REP-X", "won": float(won),
            "amount": float(amount), "poc_outcome": None,
            "created_date": pd.Timestamp(created), "close_date": pd.Timestamp(close)}


def _synthetic_periods(quota_c=100_000.0, quota_e=400_000.0, start="2024-01-01"):
    """Grain: one synthetic active quota period per segment for the known-answer scenarios; no data access."""
    rows = []
    for rep, seg, rtype, quota in (("C1", "Commercial", "ISR", quota_c), ("E1", "Enterprise", "AE", quota_e)):
        rows.append({"rep_id": rep, "rep_type": rtype, "segment": seg,
                     "hire_date": pd.Timestamp("2020-01-01"), "period_start_date": pd.Timestamp(start),
                     "period_end_date": pd.NaT, "quota_amount": quota, "rep_status": "active"})
    return pd.DataFrame(rows)


def run_synthetic_scenarios() -> dict:
    """Known-answer scenarios through the same compute functions the live
    path uses. Each scenario states its expected numbers and status."""
    window = {"last_opportunity_close": date(2030, 12, 31)}
    t = pd.Timestamp("2024-05-15")  # mid-2024-Q2
    results = []

    def run(name, deals, periods, expect, as_of=t):
        frame = pd.DataFrame(deals) if len(deals) else pd.DataFrame(
            columns=["opportunity_id", "segment", "owner_role", "rep_id", "won", "amount", "poc_outcome",
                     "created_date", "close_date"])
        frame["is_closed"] = frame["close_date"] <= as_of if len(frame) else pd.Series(dtype=bool)
        out = compute_readings(frame, periods, as_of, window)
        seg = {s["segment"]: s for s in out["segments"]}
        ok, notes = True, []
        for (segment, field), want in expect.items():
            got = seg[segment].get(field)
            match = (got == want) if not isinstance(want, float) else (got is not None and abs(got - want) < 1e-6)
            if not match:
                ok = False
                notes.append(f"{segment}.{field}: got {got!r}, want {want!r}")
        results.append({"scenario": name, "passed": ok, "notes": notes})

    # History that yields a 25% dollar-weighted conversion for both segments:
    # 40 closed deals of $1,000 in the window, 10 won.
    def history(seg):
        out = []
        for i in range(40):
            out.append(_synthetic_deal(f"H{seg[0]}{i}", seg, 1000, "2023-09-01", "2023-10-01",
                                       1 if i < 10 else 0))
        return out

    hist = history("Commercial") + history("Enterprise")
    # a) covered / thin / shortfall: quota 100,000, 0 won; conversion 25% so
    # required multiple 4.0x. Open pipeline 480,000 -> 1.2x of required.
    def open_deals(seg, amount, n=4):
        return [_synthetic_deal(f"O{seg[0]}{i}", seg, amount / n, "2024-04-20", "2024-06-10", 0) for i in range(n)]

    for name, usd, status in (("covered", 480_000, "covered"), ("thin", 360_000, "thin"),
                              ("shortfall", 200_000, "shortfall")):
        run(f"commercial_{name}", hist + open_deals("Commercial", usd), _synthetic_periods(),
            {("Commercial", "coverage_status"): status,
             ("Commercial", "remaining_quota_usd"): 100_000.0,
             ("Commercial", "pipeline_coverage_ratio"): usd / 100_000.0,
             ("Commercial", "required_pipeline_multiple"): 4.0,
             ("Commercial", "coverage_vs_required"): usd / 400_000.0,
             ("Commercial", "conversion_implied_gap_usd"): 100_000.0 - usd * 0.25},
            as_of=pd.Timestamp("2024-05-15"))
    # b) zero remaining quota -> quota_met, coverage ratio undefined, not 0 or inf.
    # The $120,000 win also enters the conversion window: (10,000 + 120,000) /
    # (40,000 + 120,000) = 81.25%, so the gap is 0 - 100,000 x 0.8125.
    won = [_synthetic_deal("W1", "Commercial", 120_000, "2024-03-01", "2024-04-15", 1)]
    run("zero_remaining_quota", hist + won + open_deals("Commercial", 100_000), _synthetic_periods(),
        {("Commercial", "coverage_status"): "quota_met", ("Commercial", "remaining_quota_usd"): 0.0,
         ("Commercial", "pipeline_coverage_ratio"): None, ("Commercial", "coverage_vs_required"): None,
         ("Commercial", "conversion_implied_gap_usd"): -81_250.0})
    # c) no open deals -> coverage 0.0 (a real zero), full remaining quota is the gap.
    run("no_open_deals", hist, _synthetic_periods(),
        {("Commercial", "coverage_status"): "shortfall", ("Commercial", "pipeline_coverage_ratio"): 0.0,
         ("Commercial", "conversion_implied_gap_usd"): 100_000.0})
    # d) no quota -> unavailable with reason, not a divide-by-zero or zero coverage.
    run("no_quota", hist + open_deals("Commercial", 100_000), _synthetic_periods(start="2024-06-01"),
        {("Commercial", "status"): "unavailable", ("Commercial", "reason_code"): "no_quota"})
    # e) segment with no wins yet this quarter: attainment 0.0, remaining = quota.
    run("no_wins_yet", hist + open_deals("Commercial", 480_000), _synthetic_periods(),
        {("Commercial", "won_to_date_usd"): 0.0, ("Commercial", "attainment_to_date"): 0.0,
         ("Commercial", "remaining_quota_usd"): 100_000.0})
    # f) a deal created after the evaluation date must not count as open.
    late = [_synthetic_deal("L1", "Commercial", 900_000, "2024-05-16", "2024-06-20", 0)]
    run("deal_created_after_evaluation_not_counted", hist + open_deals("Commercial", 480_000) + late,
        _synthetic_periods(), {("Commercial", "open_pipeline_usd"): 480_000.0,
                               ("Commercial", "open_pipeline_deals"): 4})
    # g) a deal that closed before the evaluation date is not open (it is won to date).
    early = [_synthetic_deal("E1", "Commercial", 30_000, "2024-04-01", "2024-05-10", 1)]
    run("deal_closed_before_evaluation_not_open", hist + open_deals("Commercial", 480_000) + early,
        _synthetic_periods(), {("Commercial", "open_pipeline_usd"): 480_000.0,
                               ("Commercial", "won_to_date_usd"): 30_000.0,
                               ("Commercial", "remaining_quota_usd"): 70_000.0})
    # h) quarter boundary: a deal won on the quarter's first day counts to date;
    # one won on the previous quarter's last day does not.
    edge = [_synthetic_deal("B1", "Commercial", 10_000, "2024-03-01", "2024-04-01", 1),
            _synthetic_deal("B2", "Commercial", 5_000, "2024-03-01", "2024-03-31", 1)]
    run("quarter_boundary", hist + edge, _synthetic_periods(),
        {("Commercial", "won_to_date_usd"): 10_000.0, ("Commercial", "won_to_date_deals"): 1})
    # i) a deal closing after the quarter end is open but not counted this quarter.
    beyond = [_synthetic_deal("N1", "Enterprise", 800_000, "2024-04-01", "2024-07-15", 0)]
    run("deal_closing_after_quarter_end_not_counted", hist + beyond, _synthetic_periods(),
        {("Enterprise", "open_pipeline_usd"): 0.0, ("Enterprise", "open_pipeline_after_quarter_deals"): 1})
    # j) conversion needs enough closed deals: below the floor it is unavailable.
    sparse = [_synthetic_deal(f"S{i}", "Commercial", 1000, "2024-01-10", "2024-02-01", i % 2) for i in range(5)]
    run("insufficient_conversion_history", sparse + open_deals("Commercial", 480_000), _synthetic_periods(),
        {("Commercial", "status"): "unavailable", ("Commercial", "reason_code"): "insufficient_closed_deals",
         ("Commercial", "coverage_vs_required"): None})
    # k0) quota already won needs no conversion: with too few closed deals
    # for a realized conversion the status is still quota_met, not unavailable.
    won_big = [_synthetic_deal("Q1", "Commercial", 130_000, "2024-03-01", "2024-04-15", 1)]
    run("quota_met_without_realized_conversion", sparse + won_big + open_deals("Commercial", 100_000),
        _synthetic_periods(),
        {("Commercial", "status"): "present", ("Commercial", "coverage_status"): "quota_met",
         ("Commercial", "remaining_quota_usd"): 0.0, ("Commercial", "realized_conversion"): None,
         ("Commercial", "conversion_implied_gap_usd"): None})
    # k) a deal closed before 2023 never enters the conversion window.
    old = [_synthetic_deal(f"P{i}", "Commercial", 1000, "2022-01-10", "2022-02-01", 1) for i in range(60)]
    run("pre_2023_deals_excluded_from_conversion", old + hist[:40] + open_deals("Commercial", 480_000),
        _synthetic_periods(), {("Commercial", "realized_conversion"): 0.25,
                               ("Commercial", "conversion_closed_deals"): 40},
        as_of=pd.Timestamp("2023-12-15") + pd.Timedelta(days=0))
    return {"n_scenarios": len(results), "n_passed": sum(1 for r in results if r["passed"]),
            "results": results}


def validation_no_lookahead(as_of_date: date, eval_date: pd.Timestamp, con) -> dict:
    """Builds an in-memory copy of the two source tables in which everything
    that happens after eval_date is corrupted -- outcomes of deals closing
    later are flipped, deals created later are dropped, quota periods
    starting later are altered -- and checks the coverage reading at
    eval_date is identical to the reading on the untouched marts."""
    t = pd.Timestamp(eval_date).date()
    clean = _reading_core(t, con)
    mem = duckdb.connect(":memory:")
    try:
        mem.execute("create schema main_marts")
        fo = con.execute("select * from main_marts.fact_opportunities").df()
        dr = con.execute("select * from main_marts.dim_reps").df()
        for df_name, df in (("fact_opportunities", fo), ("dim_reps", dr)):
            mem.register("_src", df)
            mem.execute(f"create table main_marts.{df_name} as select * from _src")
            mem.unregister("_src")
        mem.execute("update main_marts.fact_opportunities set is_won = not is_won, "
                    "poc_outcome = case when poc_outcome = 'pass' then 'fail' else 'pass' end "
                    "where close_date > ?", [t])
        mem.execute("delete from main_marts.fact_opportunities where created_date > ?", [t])
        mem.execute("update main_marts.dim_reps set quota_amount = quota_amount * 3, "
                    "rep_status = 'departed' where period_start_date > ?", [t])
        corrupted = _reading_core(t, mem)
    finally:
        mem.close()
    same = clean == corrupted
    return _check(f"no_lookahead_reading_unchanged_by_post_{t.isoformat()}_data", same,
                  "reading on marts with every post-evaluation fact corrupted is identical to the untouched reading"
                  if same else "post-evaluation data changed the reading")


def _reading_core(as_of: date, con) -> list:
    """Grain: the JSON-normalized segment readings and next-quarter block at as_of, on the connection given. Source marts: fact_opportunities, dim_reps."""
    r = compute_readings(load_new_business_deals(as_of, con=con), load_quota_periods(as_of, con=con),
                         as_of, load_data_window(con=con))
    r.pop("_conversion")
    return json.loads(json.dumps(_jsonable(r["segments"] + [r["next_quarter"]])))


def _jsonable(obj):
    """Recursively converts numpy/pandas/date values to JSON-safe Python values; non-finite floats become None."""
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (date, pd.Timestamp)):
        return obj.isoformat()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        value = float(obj)
        return value if np.isfinite(value) else None
    if isinstance(obj, float):
        return obj if np.isfinite(obj) else None
    return obj


# --------------------------------------------------------------------------
# Build-time validation, persistence and the report
# --------------------------------------------------------------------------

def run_build_time_validation(as_of_date: date, log: bool = True, write_report: bool = True) -> dict:
    """End-to-end: the live reading at as_of_date with its reconciliation to
    forecast.py, the structural checks (independent-SQL tie-outs, tie-outs to
    capacity_planning, identities, the conversion floor, a no-lookahead
    perturbation, synthetic known-answer scenarios) and the 2023-onward
    mid-quarter backtest with its error distribution and coverage-versus-
    attainment relationship. Logs scalar metrics to
    fact_model_performance_history via model_performance.log_performance and
    writes a dated JSON and Markdown report; the variable-width tables
    (backtest rows, scenarios) are the structured detail recorded in the
    methods doc."""
    con = _connect()
    try:
        reading = run_pipeline_coverage(as_of_date, con=con, reconcile=True)
        deals_full = load_new_business_deals(as_of_date, con=con)
        periods_full = load_quota_periods(as_of_date, con=con)
        window = load_data_window(con=con)
        backtest = backtest_coverage(as_of_date, deals_full, periods_full, window, con=con)
        summary = summarize_backtest(backtest)
        sensitivity = backtest_sensitivity_expanding_window(deals_full, periods_full, as_of_date, backtest)
        synthetic = run_synthetic_scenarios()

        mid_dates = [pd.Timestamp(d) for d in backtest["eval_date"].unique()] if not backtest.empty else []
        dates_for_ties = sorted(set(mid_dates + [pd.Timestamp(as_of_date)]))
        # Past evaluation dates recomputed using only the data up to each date.
        past = [d for d in mid_dates if d < pd.Timestamp(as_of_date)]
        past_probe = past[len(past) // 2] if past else None
        live_rows = reading["segments"]
        bt_rows = [dict(
            segment=r["segment"], as_of_date=r["eval_date"], coverage_status=r["coverage_status"],
            quota_usd=r["quota_usd"], won_to_date_usd=r["won_to_date_usd"],
            remaining_quota_usd=r["remaining_quota_usd"], open_pipeline_usd=r["open_pipeline_usd"],
            realized_conversion=r["realized_conversion"],
            required_pipeline_multiple=(1.0 / r["realized_conversion"]) if r["realized_conversion"] else None,
            pipeline_coverage_ratio=r["pipeline_coverage_ratio"], coverage_vs_required=r["coverage_vs_required"],
            conversion_implied_gap_usd=r["conversion_implied_gap_usd"],
            conversion_window_start=compute_realized_conversion(
                known_at(deals_full, pd.Timestamp(r["eval_date"])), r["eval_date"], r["segment"])["window_start"].isoformat(),
        ) for _, r in backtest.iterrows()]

        checks = [
            validation_open_pipeline_ties_to_sql(dates_for_ties, deals_full, con),
            *validation_quota_and_wins_tie_to_capacity_planning(as_of_date, periods_full, deals_full, con),
            validation_quota_constant_within_quarter(periods_full, as_of_date),
            validation_segment_role_mapping(con),
            validation_pre_2023_win_rate_is_structural(deals_full),
            validation_identities([r for r in live_rows if r["status"] == "present"] + bt_rows),
            validation_conversion_window(live_rows + bt_rows),
            _check("open_pipeline_ties_to_forecast_new_business_rollup",
                   reading["reconciliation"].get("ties_on_open_pipeline", False)
                   and summary.get("forecast_reconciliation", {}).get("open_pipeline_max_abs_diff_usd", 1) <= _TOLERANCE_USD,
                   f"live reading ties: {reading['reconciliation'].get('ties_on_open_pipeline')}; backtest max abs diff "
                   f"${summary.get('forecast_reconciliation', {}).get('open_pipeline_max_abs_diff_usd')}"),
            validation_no_lookahead(as_of_date, pd.Timestamp(as_of_date), con),
            _check("synthetic_known_answer_scenarios", synthetic["n_passed"] == synthetic["n_scenarios"],
                   f"{synthetic['n_passed']} of {synthetic['n_scenarios']} scenarios match their known answers"),
        ]
        if past_probe is not None:
            checks.append(validation_no_lookahead(as_of_date, past_probe, con))
    finally:
        con.close()

    pooled = summary.get("pooled", {})
    target_met = bool(pooled and all(v.get("beats_both_naive_baselines") for v in summary["by_segment"].values())
                      and pooled.get("beats_both_naive_baselines"))
    checks.append(_check(
        "backtest_beats_both_naive_baselines", target_met,
        "coverage-implied expected bookings versus actual quarter-end bookings: pooled MAPE "
        f"{pooled.get('mape_coverage_implied')} against won-to-date alone {pooled.get('mape_naive_won_to_date')} "
        f"and prior-four-quarter mean {pooled.get('mape_naive_trailing_4q_mean')}",
        kind="target"))
    ratio_note = (
        "reported, not part of the proposed target and gating nothing: pooled MAPE "
        f"{pooled.get('mape_coverage_implied')} against a fixed constant-rate comparator (won to date + "
        f"{_CONSTANT_RATE_BASELINE} x open) {pooled.get('mape_naive_constant_rate_025')} and a pace comparator "
        f"(won to date / fraction of the quarter elapsed) {pooled.get('mape_naive_pace')}; Enterprise "
        f"{summary.get('by_segment', {}).get('Enterprise', {}).get('mape_coverage_implied')} against "
        f"{summary.get('by_segment', {}).get('Enterprise', {}).get('mape_naive_constant_rate_025')} / "
        f"{summary.get('by_segment', {}).get('Enterprise', {}).get('mape_naive_pace')}")
    checks.append(_check(
        "backtest_versus_constant_rate_and_pace_comparators",
        bool(pooled.get("beats_constant_rate_baseline") and pooled.get("beats_pace_baseline")),
        ratio_note, kind="info"))
    structural = [c for c in checks if c["kind"] == "structural"]
    structural_passed = sum(1 for c in structural if c["passed"])

    if log:
        for seg in reading["segments"]:
            key = seg["segment"].lower()
            for metric, field in (("quota_usd", "quota_usd"), ("won_to_date_usd", "won_to_date_usd"),
                                  ("remaining_quota_usd", "remaining_quota_usd"),
                                  ("open_pipeline_usd", "open_pipeline_usd"),
                                  ("pipeline_coverage_ratio", "pipeline_coverage_ratio"),
                                  ("realized_conversion", "realized_conversion"),
                                  ("required_pipeline_multiple", "required_pipeline_multiple"),
                                  ("coverage_vs_required", "coverage_vs_required"),
                                  ("conversion_implied_gap_usd", "conversion_implied_gap_usd")):
                if seg[field] is not None:
                    log_performance(_MODEL_NAME, as_of_date, f"{metric}_{key}", float(seg[field]))
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_total", float(len(structural)))
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_passed", float(structural_passed))
        log_performance(_MODEL_NAME, as_of_date, "synthetic_scenarios_total", float(synthetic["n_scenarios"]))
        log_performance(_MODEL_NAME, as_of_date, "synthetic_scenarios_passed", float(synthetic["n_passed"]))
        if summary.get("evaluated_segment_quarters"):
            log_performance(_MODEL_NAME, as_of_date, "backtest_segment_quarters_evaluated",
                            float(summary["evaluated_segment_quarters"]))
            log_performance(_MODEL_NAME, as_of_date, "backtest_mape_coverage_implied_pooled", pooled["mape_coverage_implied"])
            for s, stats in summary["by_segment"].items():
                log_performance(_MODEL_NAME, as_of_date, f"backtest_mape_coverage_implied_{s.lower()}",
                                stats["mape_coverage_implied"])
                log_performance(_MODEL_NAME, as_of_date, f"backtest_aggregate_bias_{s.lower()}",
                                stats["aggregate_bias_pct"])
            log_performance(_MODEL_NAME, as_of_date, "backtest_mape_ratio_vs_naive_baseline",
                            summary["mape_ratio_vs_naive_baseline"])
            for label, stats in [("pooled", pooled)] + [(k.lower(), v) for k, v in summary["by_segment"].items()]:
                log_performance(_MODEL_NAME, as_of_date, f"backtest_mape_constant_rate_025_{label}",
                                stats["mape_naive_constant_rate_025"])
                log_performance(_MODEL_NAME, as_of_date, f"backtest_mape_pace_{label}", stats["mape_naive_pace"])
                log_performance(_MODEL_NAME, as_of_date, f"backtest_mape_hindsight_free_scoping_{label}",
                                stats["mape_hindsight_free_scoping"])
                log_performance(_MODEL_NAME, as_of_date, f"backtest_mape_no_scoping_{label}", stats["mape_no_scoping"])
            rr = summary["rank_relationships"]["coverage_vs_required_to_final_attainment_pooled"]
            if rr["rho"] is not None:
                log_performance(_MODEL_NAME, as_of_date, "rank_corr_coverage_vs_required_to_attainment", rr["rho"])
        for r in reading["reconciliation"].get("by_segment", []):
            if r["difference_pct_of_forecast_lens"] is not None:
                log_performance(_MODEL_NAME, as_of_date,
                                f"conversion_implied_vs_forecast_manager_lens_pct_{r['segment'].lower()}",
                                r["difference_pct_of_forecast_lens"])

    result = {
        "as_of_date": as_of_date.isoformat(),
        "reading": reading,
        "checks": checks, "checks_total": len(structural), "checks_passed": structural_passed,
        "target_met": target_met,
        "synthetic": synthetic,
        "backtest_summary": summary,
        "backtest_sensitivity_expanding_window": sensitivity,
        "backtest": _backtest_records(backtest),
    }
    if write_report:
        _write_report(as_of_date, result)
    return result


def _backtest_records(backtest: pd.DataFrame) -> list:
    """Backtest rows as JSON-safe records, dollars rounded to the cent and
    ratios to 8 places so the committed report does not carry last-digit
    float noise from platform differences."""
    if backtest.empty:
        return []
    frame = backtest.copy()
    for col in frame.columns:
        if frame[col].dtype.kind == "f":
            frame[col] = frame[col].round(2 if col.endswith("_usd") else 8)
    return json.loads(frame.replace({np.nan: None}).to_json(orient="records"))


def _write_report(as_of_date: date, result: dict) -> None:
    """Writes the dated JSON and Markdown report for one checkpoint to analytics/outputs/."""
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    json_path = os.path.join(_OUTPUT_DIR, f"pipeline_coverage_{as_of_date.isoformat()}.json")
    with open(json_path, "w") as f:
        json.dump(_jsonable(result), f, indent=2)
    md_path = os.path.join(_OUTPUT_DIR, f"pipeline_coverage_{as_of_date.isoformat()}.md")
    with open(md_path, "w") as f:
        f.write(render_markdown(result))


def render_markdown(result: dict) -> str:
    """Renders one checkpoint report (reading, reconciliation, checks, caveats) as Markdown; no data access."""
    r = result["reading"]
    lines = [f"# Pipeline coverage -- evaluation date {r['as_of_date']} ({r['period']})", "",
             f"*{r['label']}.* {r['days_to_quarter_end']} days to quarter end ({r['quarter_end']}).", ""]
    for seg in r["segments"]:
        lines += [f"## {seg['segment']}", "", seg["display"]["summary"], "",
                  "| Measure | Value |", "|---|---|",
                  f"| Quota | {seg['display']['quota']} ({seg['display']['quota_basis']}) |",
                  f"| Won to date | {seg['display']['won_to_date']} ({seg['display']['attainment_to_date']} of quota) |",
                  f"| Remaining quota | {seg['display']['remaining_quota']} |",
                  f"| Open pipeline | {seg['display']['open_pipeline']} |",
                  f"| Coverage ratio | {seg['display']['pipeline_coverage_ratio']} |",
                  f"| Realized conversion | {seg['display']['realized_conversion']} |",
                  f"| Required multiple | {seg['display']['required_pipeline_multiple']} |",
                  f"| Coverage vs required | {seg['display']['coverage_vs_required']} |",
                  f"| Conversion-implied gap | {seg['display']['conversion_implied_gap']} |",
                  f"| Status (proposed rule) | {seg['display']['status_text']} |", ""]
    nq = r["next_quarter"]
    lines += [f"## Next quarter ({nq['period']})", ""]
    if nq["status"] == "unavailable":
        lines += [f"Unavailable: {nq['reason']}.", ""]
    else:
        for s in nq["segments"]:
            lines.append(f"- {s['segment']}: {s['display']['open_pipeline']} against carried-forward quota "
                         f"{s['display']['carried_forward_quota']} ({s['display']['pipeline_coverage_ratio']}); "
                         f"{s['display']['note']}.")
        lines.append("")
    rec = r["reconciliation"]
    if rec.get("status") == "present":
        lines += ["## Reconciliation to the forecast (reported, never merged)", "", rec["note"], "",
                  "| Segment | Coverage open pipeline | Forecast new-business open pipeline | Conversion-implied expected close | Forecast manager lens (new business) |",
                  "|---|---|---|---|---|"]
        for x in rec["by_segment"]:
            lines.append(f"| {x['segment']} | {_usd(x['coverage_reading_open_pipeline_usd'])} | "
                         f"{_usd(x['forecast_new_business_open_pipeline_usd'])} | "
                         f"{_usd(x['coverage_reading_conversion_implied_expected_close_usd'])} | "
                         f"{_usd(x['forecast_manager_lens_new_business_weighted_usd'])} |")
        lines.append("")
    lines += ["## Checks", ""]
    for c in result["checks"]:
        mark = _mark(c)
        lines.append(f"- [{mark}] {c['name']}: {c['detail']}")
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in r["caveats"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    for checkpoint in (date(2025, 8, 15), date(2025, 11, 14)):
        out = run_build_time_validation(checkpoint)
        rd = out["reading"]
        print(f"=== Pipeline coverage, evaluation date {checkpoint} ({rd['period']}) ===")
        for seg in rd["segments"]:
            print(" ", seg["display"]["summary"])
            if seg.get("poc_view") and seg["poc_view"]["status"] == "present":
                p = seg["poc_view"]
                print(f"    POC-conditioned (indicative): expected close "
                      f"{_usd(p['poc_conditioned_expected_close_usd'])} vs "
                      f"{seg['display']['conversion_implied_expected_close']} unconditioned; closed-deal "
                      f"samples pass {p['rates']['pass']['closed_deals']}, fail {p['rates']['fail']['closed_deals']}")
        nq = rd["next_quarter"]
        print(f"  Next quarter {nq['period']}: {nq['status']}"
              + (f" ({nq['reason']})" if nq["reason"] else ""))
        for x in rd["reconciliation"].get("by_segment", []):
            print(f"  Reconciliation {x['segment']}: coverage open {_usd(x['coverage_reading_open_pipeline_usd'])} "
                  f"vs forecast new-business open {_usd(x['forecast_new_business_open_pipeline_usd'])}; "
                  f"conversion-implied {_usd(x['coverage_reading_conversion_implied_expected_close_usd'])} vs "
                  f"forecast manager lens {_usd(x['forecast_manager_lens_new_business_weighted_usd'])}")
        s = out["backtest_summary"]
        print(f"  Backtest: {s['evaluated_segment_quarters']} of {s['segment_quarters']} segment-quarters evaluated")
        for label, stats in [("pooled", s["pooled"])] + list(s["by_segment"].items()):
            print(f"    {label}: MAPE {stats['mape_coverage_implied']:.3f} (median {stats['median_ape_coverage_implied']:.3f}, "
                  f"p90 {stats['p90_ape_coverage_implied']:.3f}, max {stats['max_ape_coverage_implied']:.3f}), "
                  f"bias {stats['aggregate_bias_pct']:+.3f}; naive won-to-date {stats['mape_naive_won_to_date']:.3f}, "
                  f"prior-4Q mean {stats['mape_naive_trailing_4q_mean']:.3f}; late-created share "
                  f"{stats['late_created_share_of_actual']:.3f}")
            print(f"       comparators: constant-rate (won + {_CONSTANT_RATE_BASELINE} x open) "
                  f"{stats['mape_naive_constant_rate_025']:.3f}; pace {stats['mape_naive_pace']:.3f}; "
                  f"hindsight-free scoping {stats['mape_hindsight_free_scoping']:.3f}; "
                  f"no scoping {stats['mape_no_scoping']:.3f}; visible-pipeline pricing "
                  f"{stats['visible_pipeline_pricing_bias_pct']}, visible-reading bias "
                  f"{stats['visible_reading_vs_visible_actual_pct']}")
        for name, rr in s["rank_relationships"].items():
            print(f"    rank {name}: n={rr['n']} rho={rr['rho']} p={rr['p_value']}")
        for o in s["status_outcomes"]:
            print(f"    status {o['coverage_status']}: n={o['n']} reached quota {o['reached_full_quota']} "
                  f"median attainment {o['median_final_attainment']}")
        for c in out["checks"]:
            mark = _mark(c)
            print(f"  [{mark}] {c['name']}: {c['detail']}")
        print(f"  {out['checks_passed']} of {out['checks_total']} structural checks pass; "
              f"backtest target met: {out['target_met']}\n")
