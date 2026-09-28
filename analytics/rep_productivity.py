"""Rep productivity & coaching diagnostics -- grain: one row per
quota-bearing rep (ISR/AE) per trailing-window snapshot (default 4
complete calendar quarters ending at the last complete quarter <=
as_of_date). Source marts: fact_sales_activities, fact_opportunities,
dim_reps.

Build spec item #14, Wave 4 ("deal/rep depth, builds on Wave 1-2, not
required for the core loop"). Answers a different question than the two
artifacts it sits next to: capacity planning (build spec item #3) answers
"is the team's aggregate quota achievable given its ramp mix" at
segment x rep_type x quarter grain; automated playbook triggers' rules
answer "did a stored threshold fire on an account/opportunity"; this
module answers "which NAMED rep, and why" -- a coaching-actionable
decomposition of activity volume and engagement quality, not a repeat of
either of those aggregates. It does not recompute capacity planning's
productivity/coverage/ramp-mix decomposition (that stays capacity
planning's, at team grain) and, as of this build, no cohort-level
"underperforming rep" rule exists in analytics/playbook_triggers.py to
duplicate -- that module's three shipped rules are account/opportunity-
scoped (ingestion stall, POC pass rate, post-close utilization), none of
them rep-scoped. The generator DOES inject a persistent, named
underperforming-rep-cohort mechanism (generators/sales_activities.py's
_assign_underperformer_cohort, config.SALES_ACTIVITY_UNDERPERFORMER_SHARE
= 0.16) and the QA plan's own test suite (tests/test_phase1_batch8.py,
TestInjectedIncidents.test_underperforming_rep_cohort_is_visible_in_
activity_patterns) already demonstrates that cohort is recoverable from
meeting-held rate alone, using only public activity data -- never an
internal generator flag. This module is what turns that raw recoverability
into a real, individual-rep, multi-signal, composition-adjusted
diagnostic; its validation borrows the same public, data-only recovery
method that test already established (see run_build_time_validation).

Scope -- ISR/AE only, deliberately, matching capacity planning's scope
exactly and for the identical reason: fact_sales_activities itself is
scoped to Commercial/Enterprise new-business opportunities (SMB has no
rep; AM-owned expansion/renewal activity already lives in fact_am_activity
and is out of scope by that table's own header), and only ISR/AE carry a
quota (dim_reps.quota_amount is null for AM/SE). SE appears in this data
only as an occasional Enterprise demo-giver (config.
SALES_ACTIVITY_SE_SHARE_OF_DEMO), never a deal owner, and is excluded by
construction: this module only reads rows whose rep_id joins to an ISR/AE
row in dim_reps, so an SE-attributed demo touch simply does not appear.

The leakage risk this module is built around
---------------------------------------------
generators/sales_activities.py's own docstring states the mechanism
directly: "is_won tightens cadence and lifts meeting/demo held-rate and
call-connect/email-reply rates: a deal that closed was worked harder and
engaged better than one that didn't. This reads the opportunity's
already-fixed outcome... a historical log generated after the fact." Every
one of held_rate, connect_rate, reply_rate, and multi-threading probability
is conditioned on is_won in the generator (_held_rate, _connect_rate,
_reply_rate, _new_contact_probability all take is_won as an argument). A
rep whose book happened to close more of its deals will therefore show
HIGHER raw engagement-quality numbers for a reason that has nothing to do
with that rep's actual skill -- the deal's already-known outcome
retroactively inflated the touches logged against it. Naively correlating
a rep's raw held/connect/reply rate (or raw win rate) against another raw
number would mostly be re-deriving this retrospective-disclosure artifact,
not finding a coaching signal -- the identical trivial-accuracy failure
mode the account health score's calibration note documents for scoring
inside a deterministic decline window, and capacity planning's and
segment migration's entries document for a classifier that would mostly
re-derive a known generator rule.

The fix used throughout this module is composition-adjustment, not a
raw correlation: every rep's actual rate is compared against a
LEAVE-ONE-OUT PEER BENCHMARK computed within the same (segment, is_won,
rep_is_ramped_at_opportunity_creation) stratum -- exactly the three
variables the generator conditions each engagement mechanic on. Because
both the rep's own actual rate and its peer expectation are computed
inside the same strata, a rep whose book happens to have more won deals
than average is compared only against OTHER reps' won-deal performance in
that same stratum, not against the pooled population -- the composition
effect cancels out of the residual by construction, not by care. The real,
ramp-and-outcome-independent signal this module surfaces (a persistent,
per-rep quality or volume gap that survives that adjustment) is exactly
what the generator's injected cohort mechanism is: real, but invisible to
a raw pooled correlation. A worked example from this build's own real-data
run is in docs/acme-corp-analytics-methods.md's Rep productivity entry
(REP-00063 -- raw held rate lands in the bottom quintile, entirely because
the rep spent the whole window ramping; the composition-adjusted residual
correctly clears that rep, while a genuine, ramp-independent touch-volume
gap for the same rep survives the adjustment and is still flagged).

Shape -- structural/descriptive with a composition-adjusted peer
benchmark, not a fitted model. Nothing here is fitted: there is no
train/test split, no estimated coefficient, no probability model. Per
analytics-engineering-conventions' "Structural/logic artifacts" category
(the same category capacity planning, segment migration, marketing
attribution, data quality governance and playbook triggers all use) --
no coefficient table, no AUC, no confusion matrix, no R^2/RMSE, no
calibration note. The correctness claim is narrower and fully checkable:
does the composition-adjusted decomposition correctly separate a
volume-only gap from a quality-only gap from a ramp-explained gap on
hand-constructed cases with known answers (run_synthetic_scenarios), and
does the real-data flag recover the same cohort the QA plan's own
data-only test already proved recoverable (run_build_time_validation).

No stochastic step lives in this module -- no train/test split, no
sampling, no simulation -- so no random seed applies, matching
analytics/capacity_planning.py's and analytics/segment_migration.py's
precedent.
"""
import os
from datetime import date

import duckdb
import numpy as np
import pandas as pd

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_MODEL_NAME = "rep_productivity"

# The quota-bearing, new-business roles this artifact scores -- matching
# analytics/capacity_planning.py's scope exactly. fact_sales_activities
# itself is scoped to Commercial/Enterprise new-business, so no other
# rep_type has any rows to score in the first place.
_QUOTA_BEARING_REP_TYPES = ("ISR", "AE")

# "First 2 quarters" (build spec Section 4), the identical 180-day
# boundary generators/opportunities.py's _RAMP_FULL_DAYS and
# analytics/capacity_planning.py's _RAMP_FULL_DAYS both use, evaluated
# here at OPPORTUNITY CREATION per generators/sales_activities.py's own
# _is_ramped(hire_date, opp.created_date) -- the exact reference date the
# activity data's engagement mechanics are conditioned on, so this
# module's stratification variable matches the generator's own
# conditioning variable exactly rather than approximating it.
_RAMP_FULL_DAYS = 180

# Trailing window, in complete calendar quarters, ending at the last
# complete quarter <= as_of_date. A single quarter is too thin for a
# reliable per-rep engagement-quality read (median ~9 resolved meetings
# per rep-quarter at build time, against this module's own >=8 reliability
# floor for held_rate -- see below); 4 quarters puts every quota-bearing
# rep with any 2025 activity comfortably above every reliability floor at
# build time (min resolved meetings 10, min calls 34, min emails 25 across
# all 40 active reps) while staying a genuinely "current" coaching window,
# not a whole-career average.
_DEFAULT_TRAILING_QUARTERS = 4

# Reliability floors -- a metric computed off too few events is not a
# coaching signal, it's noise reported with false confidence. held_rate's
# floor of 8 is adopted directly from tests/test_phase1_batch8.py's own
# cohort-detection test ("too few reps with enough resolved meetings to
# detect a cohort" at n<8), not re-derived independently -- reusing the
# QA plan's own established reliability bar rather than inventing a new
# one for the same underlying signal. connect_rate/reply_rate get the
# same order-of-magnitude floor (calls/emails are far more numerous than
# meetings per rep at build time, so 10 is a real floor, not a binding
# one). n_opps >= 3 gates touches_per_opp and contacts_per_opp, since a
# per-opportunity average needs more than one or two observations to mean
# anything.
_MIN_RESOLVED_MEETINGS = 8
_MIN_CALLS = 10
_MIN_EMAILS = 10
_MIN_OPPORTUNITIES = 3

# A rep's composite quality score is the mean of however many of the four
# quality-dimension z-scores clear their own reliability floor; below this
# many reliable dimensions the composite is not reported at all (NaN,
# verdict "insufficient_data") rather than averaged over a single noisy
# dimension.
_MIN_RELIABLE_QUALITY_METRICS = 2

# Bottom-quintile flagging, chosen for the same reason the account health
# score's risk_tier is quantile-based rather than a fixed cutoff: this
# module's residuals are not assumed normal, and a quantile is robust to
# whatever shape the real distribution actually takes. 20% is a data-
# independent choice (not fit to this dataset's known injected share --
# see the "no answer-key leakage" note below) and matches the same
# non-trivial-minority reasoning the data-quality-governance and playbook-
# triggers entries already use for their own PROPOSED floors: neither
# near-0% (a threshold nobody would ever trip) nor near-universal (not a
# trigger, a constant).
_QUANTILE_FLAG_THRESHOLD = 0.20

# A rep-window is "predominantly ramping" when at least this share of the
# rep's own closed opportunities in the window were opened while that rep
# was still ramping (opportunity-count weighted -- the same "opportunity
# is the atomic unit of a rep's book" framing this module's attainment and
# win-rate figures already use). This gates the ramp_explained_on_par
# verdict, and ONLY that verdict -- see assign_diagnostic_flag.
_RAMP_MAJORITY_SHARE = 0.50

# A rep_type pool smaller than this makes a bottom-quintile cut
# meaningless (an 8-person pool's bottom 20% is under 2 reps). At build
# time AE (21) and ISR (19) both clear this comfortably; coded so a
# future, thinner checkpoint degrades to "insufficient_population" rather
# than a spurious flag.
_MIN_POOL_SIZE_FOR_QUANTILE = 10

# No-answer-key-leakage note, stated once here rather than repeated at
# every threshold: this module never imports generators.config and never
# reads generators/sales_activities.py's internal underperformer-cohort
# assignment. Every threshold above is grounded against real,
# already-materialized mart data or an existing QA-plan precedent. The
# one place the known generator design constant (SALES_ACTIVITY_
# UNDERPERFORMER_SHARE = 0.16) is even mentioned is in
# docs/acme-corp-analytics-methods.md, as a validation-time grounding
# note (how close the independently-chosen 20% quantile lands to the
# true generative share) -- exactly the same "cite for grounding in prose,
# never import in production logic" discipline analytics/capacity_
# planning.py already uses for RAMPING_REP_WIN_ASSIGNMENT_FACTOR.


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


def _last_complete_quarter_end(as_of_date: date) -> pd.Timestamp:
    q = pd.Period(pd.Timestamp(as_of_date), freq="Q")
    if q.end_time.normalize() > pd.Timestamp(as_of_date):
        q = q - 1
    return q.end_time.normalize()


def _window_bounds(as_of_date: date, window_quarters: int) -> tuple:
    window_end = _last_complete_quarter_end(as_of_date)
    window_start = (pd.Period(window_end, freq="Q") - (window_quarters - 1)).start_time
    return window_start, window_end


# --------------------------------------------------------------------------
# Loaders -- point-in-time by construction
# --------------------------------------------------------------------------

def load_rep_dimension(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per quota-bearing rep (ISR/AE), collapsed from
    dim_reps' capacity-period history to the attributes that are constant
    per rep (hire_date, rep_type) -- period-varying fields (quota, status)
    are read separately, at the grain each computation actually needs them
    at. Source mart: dim_reps. period_start_date <= as_of_date on every
    row read, matching analytics/capacity_planning.py's identical guard
    against a future quota/status change leaking backward."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select distinct rep_id, rep_type, hire_date "
            "from main_marts.dim_reps "
            "where rep_type in ('ISR', 'AE') and period_start_date <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["hire_date"] = pd.to_datetime(df["hire_date"])
    return df


def load_rep_quota(as_of_date: date, window_start: pd.Timestamp, window_end: pd.Timestamp,
                    con=None) -> pd.DataFrame:
    """Grain: one row per rep per complete calendar quarter inside
    [window_start, window_end], stated quota only -- no coverage-share or
    ramp-factor pro-rating (that decomposition is capacity planning's, not
    duplicated here). Source mart: dim_reps. Used only to report
    attainment context alongside each rep's diagnostic flag, never to
    derive the flag itself."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select rep_id, date_trunc('quarter', period_start_date)::date as quarter, "
            "max(quota_amount) as stated_quota "
            "from main_marts.dim_reps "
            "where rep_type in ('ISR', 'AE') and period_start_date <= ? "
            "group by 1, 2",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["quarter"] = pd.to_datetime(df["quarter"])
    return df[(df["quarter"] >= window_start) & (df["quarter"] <= window_end)]


def load_new_business_opportunities(as_of_date: date, window_start: pd.Timestamp,
                                     window_end: pd.Timestamp, con=None) -> pd.DataFrame:
    """Grain: one row per opportunity, Commercial/Enterprise new-business,
    ISR/AE-owned, close_date inside [window_start, window_end] and
    close_date <= as_of_date -- no leakage from the future. Source mart:
    fact_opportunities. This is the population every activity/quality
    metric and the attainment context are computed over: closing an
    opportunity inside the window is what puts a deal's whole activity
    history (bounded to [created_date, close_date] by construction) inside
    scope, the same close-quarter attribution rule analytics/
    capacity_planning.py's load_new_business_wins already uses."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select opportunity_id, rep_id, segment, is_won, amount, "
            "created_date, close_date "
            "from main_marts.fact_opportunities "
            "where opportunity_type = 'new_business' and owner_role in ('ISR', 'AE') "
            "and segment in ('Commercial', 'Enterprise') "
            "and close_date between ? and ? and close_date <= ?",
            [window_start, window_end, as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    for c in ("created_date", "close_date"):
        df[c] = pd.to_datetime(df[c])
    return df


def load_activities_for_opportunities(opportunity_ids: list, con=None) -> pd.DataFrame:
    """Grain: one row per activity_id (raw touch), for the given set of
    opportunity_ids only. Source mart: fact_sales_activities. Every touch
    on an in-window opportunity is read regardless of the touch's own
    activity_date -- a touch is already date-bounded to
    [created_date, close_date] by construction (generators/
    sales_activities.py), and the opportunity's close_date is what put it
    in the window, not the individual touch dates."""
    owns_con = con is None
    con = con or _connect()
    try:
        if not opportunity_ids:
            return pd.DataFrame(columns=[
                "activity_id", "rep_id", "opportunity_id", "activity_type",
                "outcome", "activity_timestamp", "contact_ref",
            ])
        df = con.execute(
            "select activity_id, rep_id, opportunity_id, activity_type, outcome, "
            "activity_timestamp, contact_ref "
            "from main_marts.fact_sales_activities "
            "where opportunity_id in (select unnest($1))",
            [opportunity_ids],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["activity_timestamp"] = pd.to_datetime(df["activity_timestamp"])
    return df


# --------------------------------------------------------------------------
# Opportunity-level panel -- the one thing every downstream number is an
# aggregation of
# --------------------------------------------------------------------------

def build_opportunity_panel(as_of_date: date, window_quarters: int = _DEFAULT_TRAILING_QUARTERS,
                             con=None) -> pd.DataFrame:
    """Grain: one row per opportunity closed inside the trailing window.
    Carries the rep's ramp status at that opportunity's creation and every
    activity-derived count (touches, resolved meetings/held, calls/
    connected, emails/replied, distinct contacts, mean inter-touch gap)
    aggregated from fact_sales_activities over that opportunity's own
    touches. Source marts: fact_opportunities, fact_sales_activities,
    dim_reps.
    """
    owns_con = con is None
    con = con or _connect()
    try:
        window_start, window_end = _window_bounds(as_of_date, window_quarters)
        opps = load_new_business_opportunities(as_of_date, window_start, window_end, con=con)
        reps = load_rep_dimension(as_of_date, con=con)
        if opps.empty:
            return pd.DataFrame()

        opps = opps.merge(reps, on="rep_id", how="inner")  # inner: only ISR/AE owners score here
        opps["rep_is_ramped"] = (
            opps["created_date"] - opps["hire_date"]
        ).dt.days >= _RAMP_FULL_DAYS

        acts = load_activities_for_opportunities(opps["opportunity_id"].tolist(), con=con)
    finally:
        if owns_con:
            con.close()

    if acts.empty:
        agg = pd.DataFrame({"opportunity_id": opps["opportunity_id"]})
        for col in ("n_touches", "n_meet_resolved", "n_meet_held", "n_calls",
                    "n_calls_connected", "n_emails", "n_emails_replied", "n_contacts"):
            agg[col] = 0
        agg["mean_gap_days"] = np.nan
    else:
        def _agg(g: pd.DataFrame) -> pd.Series:
            is_meeting = g["activity_type"] == "meeting"
            is_call = g["activity_type"] == "call"
            is_email = g["activity_type"] == "email"
            meet_resolved = is_meeting & (g["outcome"] != "booked")
            ts = g.sort_values("activity_timestamp")["activity_timestamp"]
            gaps = ts.diff().dt.total_seconds().dropna() / 86400.0
            return pd.Series({
                "n_touches": len(g),
                "n_meet_resolved": int(meet_resolved.sum()),
                "n_meet_held": int((meet_resolved & (g["outcome"] == "held")).sum()),
                "n_calls": int(is_call.sum()),
                "n_calls_connected": int((is_call & (g["outcome"] == "connected")).sum()),
                "n_emails": int(is_email.sum()),
                "n_emails_replied": int((is_email & (g["outcome"] == "replied")).sum()),
                "n_contacts": int(g["contact_ref"].nunique()),
                "mean_gap_days": float(gaps.mean()) if len(gaps) else np.nan,
            })

        agg = acts.groupby("opportunity_id", group_keys=False).apply(
            _agg, include_groups=False
        ).reset_index()

    panel = opps.merge(agg, on="opportunity_id", how="left")
    for col in ("n_touches", "n_meet_resolved", "n_meet_held", "n_calls",
                "n_calls_connected", "n_emails", "n_emails_replied", "n_contacts"):
        panel[col] = panel[col].fillna(0).astype(int)
    panel["stratum"] = list(zip(panel["segment"], panel["is_won"], panel["rep_is_ramped"]))
    panel["window_start"] = window_start
    panel["window_end"] = window_end
    return panel


# --------------------------------------------------------------------------
# Pure computation -- no DB access below this line, so every function here
# is directly testable against a hand-built panel (run_synthetic_scenarios
# does exactly that)
# --------------------------------------------------------------------------

# (metric name -> (numerator column, denominator column, reliability floor))
# "one" is a constant-1 helper column build_opportunity_panel-shaped panels
# must carry so touches_per_opp / contacts_per_opp can share the same
# leave-one-out machinery as the rate metrics (denominator = opportunity
# count rather than an event count).
_QUALITY_METRICS = {
    "held_rate": ("n_meet_held", "n_meet_resolved", _MIN_RESOLVED_MEETINGS),
    "connect_rate": ("n_calls_connected", "n_calls", _MIN_CALLS),
    "reply_rate": ("n_emails_replied", "n_emails", _MIN_EMAILS),
    "contacts_per_opp": ("n_contacts", "one", _MIN_OPPORTUNITIES),
}
_INTENSITY_METRICS = {
    "touches_per_opp": ("n_touches", "one", _MIN_OPPORTUNITIES),
}
_ALL_METRICS = {**_QUALITY_METRICS, **_INTENSITY_METRICS}


def _leave_one_out_expected(panel: pd.DataFrame, rep_id: str, num_col: str, den_col: str) -> float:
    """Composition-adjusted expected value for one rep on one metric: for
    every (segment, is_won, rep_is_ramped) stratum the rep has events in,
    take the POOL rate in that same stratum with the rep's own
    contribution removed (leave-one-out -- a rep's own extreme performance
    never biases its own benchmark), then weight those peer rates by the
    rep's own stratum event counts. This is what makes the residual
    (actual - expected) immune to a rep's book simply having a different
    won/lost or ramp mix than the pool average -- the composition effect
    is present in both the actual and the expected figure and cancels out
    of the difference by construction."""
    rep_rows = panel[panel["rep_id"] == rep_id]
    total_num, total_den = 0.0, 0.0
    for stratum, g in rep_rows.groupby("stratum"):
        rep_num, rep_den = g[num_col].sum(), g[den_col].sum()
        if rep_den <= 0:
            continue
        pool = panel[panel["stratum"] == stratum]
        peer_num = pool[num_col].sum() - rep_num
        peer_den = pool[den_col].sum() - rep_den
        if peer_den <= 0:
            continue
        total_num += (peer_num / peer_den) * rep_den
        total_den += rep_den
    return total_num / total_den if total_den > 0 else np.nan


def compute_rep_metric_table(panel: pd.DataFrame) -> pd.DataFrame:
    """Grain: one row per rep. For every metric in _ALL_METRICS: the raw
    actual rate, its reliability flag (sample size >= that metric's
    floor), the composition-adjusted expected rate, and the residual
    (actual - expected). Pure function of an opportunity-level panel --
    no DB access, so this is exactly what run_synthetic_scenarios exercises
    directly."""
    panel = panel.copy()
    panel["one"] = 1
    rows = []
    for rep_id, g in panel.groupby("rep_id"):
        row = {
            "rep_id": rep_id,
            "rep_type": g["rep_type"].iloc[0],
            "n_opps": len(g),
            "n_won": int(g["is_won"].sum()),
            "n_lost": int((~g["is_won"]).sum()),
            "win_rate": float(g["is_won"].mean()),
            "ramp_majority_share": float((~g["rep_is_ramped"]).mean()),
        }
        for m, (num_col, den_col, floor) in _ALL_METRICS.items():
            actual_num, actual_den = g[num_col].sum(), g[den_col].sum()
            row[f"{m}_n"] = int(actual_den)
            row[f"{m}_actual"] = actual_num / actual_den if actual_den > 0 else np.nan
            row[f"{m}_reliable"] = bool(actual_den >= floor)
            row[f"{m}_expected"] = _leave_one_out_expected(panel, rep_id, num_col, den_col)
        rows.append(row)
    return pd.DataFrame(rows)


def compute_composite_scores(metric_table: pd.DataFrame) -> pd.DataFrame:
    """Adds, per metric, the residual (actual - expected) and its z-score
    standardized within the rep's OWN rep_type pool (AE and ISR are
    structurally different roles with different base rates and contact-
    pool sizes -- analytics/capacity_planning.py's "segment x rep_type is
    a degenerate cross" finding applies identically here, so pooling
    across rep_type would compare apples to oranges). Only rows passing
    that metric's reliability floor contribute to the pool's mean/std or
    receive a z-score; an unreliable cell is NaN, not zero.

    Adds two composites: quality_z (mean of the up-to-4 reliable quality
    dimension z-scores, NaN if fewer than _MIN_RELIABLE_QUALITY_METRICS
    are reliable) and intensity_z (touches_per_opp's own z-score -- a
    single metric, not averaged, since touches_per_opp and mean_gap_days
    are one underlying mechanism in this data, not two independent
    signals -- see the module docstring's "one mechanism" note; mean_gap
    is reported as a corroborating raw statistic elsewhere, never folded
    into this composite, to avoid double-counting the same signal the way
    the account health score's entry flags login_count_avg_3mo and
    login_frequency_weighted as "two representations of one underlying
    signal.").
    """
    df = metric_table.copy()
    for m in _ALL_METRICS:
        df[f"{m}_residual"] = df[f"{m}_actual"] - df[f"{m}_expected"]
        df[f"{m}_z"] = np.nan
        for rep_type, idx in df.groupby("rep_type").groups.items():
            sub = df.loc[idx]
            reliable = sub[sub[f"{m}_reliable"]]
            if len(reliable) < 2:
                continue
            mu, sd = reliable[f"{m}_residual"].mean(), reliable[f"{m}_residual"].std()
            if sd and sd > 0:
                df.loc[reliable.index, f"{m}_z"] = (reliable[f"{m}_residual"] - mu) / sd

    quality_cols = [f"{m}_z" for m in _QUALITY_METRICS]
    df["quality_n_reliable"] = df[[f"{m}_reliable" for m in _QUALITY_METRICS]].sum(axis=1)
    df["quality_z"] = np.where(
        df["quality_n_reliable"] >= _MIN_RELIABLE_QUALITY_METRICS,
        df[quality_cols].mean(axis=1, skipna=True),
        np.nan,
    )
    df["intensity_z"] = df["touches_per_opp_z"]
    df["intensity_reliable"] = df["touches_per_opp_reliable"]
    return df


def _quantile_flag(df: pd.DataFrame, z_col: str, reliable_mask: pd.Series) -> pd.Series:
    """Bottom-_QUANTILE_FLAG_THRESHOLD flag on z_col, computed SEPARATELY
    within each rep_type pool (never pooled across AE/ISR), and only over
    rows with enough reliable observations to make a pool-level quantile
    meaningful (_MIN_POOL_SIZE_FOR_QUANTILE). A pool too small returns
    False for every row in it rather than a spurious cut.

    Selects the bottom ceil(pool_size * _QUANTILE_FLAG_THRESHOLD) rows by
    RANK (pandas' nsmallest), not by comparing every row against a
    quantile VALUE. The two are only equivalent when the pool has no
    ties; with ties (e.g. several reps sharing an identical residual --
    happens by deliberate construction in run_synthetic_scenarios' peer
    pool, and is a real possibility in the smaller real-data pools too)
    a value-threshold comparison with `<=` flags every tied row, which can
    silently inflate the flagged share far past 20%. Rank-based selection
    flags exactly the intended count regardless of how the distribution's
    mass is arranged."""
    flag = pd.Series(False, index=df.index)
    for rep_type, idx in df.groupby("rep_type").groups.items():
        sub = df.loc[idx]
        pool = sub[reliable_mask.loc[idx] & sub[z_col].notna()]
        if len(pool) < _MIN_POOL_SIZE_FOR_QUANTILE:
            continue
        n_flag = max(1, int(np.ceil(len(pool) * _QUANTILE_FLAG_THRESHOLD)))
        bottom = pool.nsmallest(n_flag, z_col)
        flag.loc[bottom.index] = True
    return flag


def assign_diagnostic_flag(scored: pd.DataFrame) -> pd.DataFrame:
    """The named, mutually-exclusive, coaching-actionable verdict per rep.
    Priority order is what makes 'this rep's low numbers are fully
    explained by ramp status' structurally impossible to assign to a rep
    who is STILL below composition-adjusted par -- the same discipline
    the build spec asks of the variance-diagnostic engine's Layer-1/
    Layer-2 identification, applied here to ramp vs. genuine gap:

      1. quality_flag = bottom quintile of quality_z within rep_type pool
      2. intensity_flag = bottom quintile of intensity_z within rep_type pool
      3. If EITHER flag fires: 'volume_and_quality_constrained' (both),
         'engagement_quality_constrained' (quality only), or
         'volume_constrained' (intensity only) -- REGARDLESS of ramp
         status, because quality_z/intensity_z are already
         composition-adjusted for ramp status per-opportunity (a
         predominantly-ramping rep is compared against OTHER ramping
         reps' same-stratum peers, not against ramped peers), so a flag
         surviving that adjustment cannot be a ramp artifact by
         construction.
      3. Only if NEITHER flag fires: ramp_majority_share >=
         _RAMP_MAJORITY_SHARE -> 'ramp_explained_on_par' (raw numbers may
         look low next to the whole population, and that is fully
         explained by tenure -- not a coaching signal); otherwise
         'on_par'.
      4. If neither composite is computable (too few reliable metrics,
         or n_opps below _MIN_OPPORTUNITIES) -> 'insufficient_data'.

    A rep can therefore never receive 'ramp_explained_on_par' while also
    tripping a composition-adjusted threshold -- the ramp-explained
    verdict is checked LAST and only reached once both flags have already
    been ruled out, not assigned by looking at ramp status first.
    """
    df = scored.copy()
    quality_reliable = df["quality_n_reliable"] >= _MIN_RELIABLE_QUALITY_METRICS
    intensity_reliable = df["intensity_reliable"]

    df["quality_flag"] = _quantile_flag(df, "quality_z", quality_reliable)
    df["intensity_flag"] = _quantile_flag(df, "intensity_z", intensity_reliable)

    has_any_signal = quality_reliable | intensity_reliable

    def _verdict(r) -> str:
        if not has_any_signal.loc[r.name]:
            return "insufficient_data"
        if r["quality_flag"] and r["intensity_flag"]:
            return "volume_and_quality_constrained"
        if r["quality_flag"]:
            return "engagement_quality_constrained"
        if r["intensity_flag"]:
            return "volume_constrained"
        if r["ramp_majority_share"] >= _RAMP_MAJORITY_SHARE:
            return "ramp_explained_on_par"
        return "on_par"

    df["diagnostic_flag"] = df.apply(_verdict, axis=1)
    return df


def compute_rep_diagnostics(panel: pd.DataFrame) -> pd.DataFrame:
    """The full pure pipeline: opportunity-level panel -> per-rep metric
    table -> composite z-scores -> diagnostic flag. Grain: one row per
    rep. No DB access -- run_rep_productivity_diagnostics wraps this with
    the real-data loaders; run_synthetic_scenarios calls it directly on
    hand-built panels."""
    if panel.empty:
        return pd.DataFrame()
    metric_table = compute_rep_metric_table(panel)
    scored = compute_composite_scores(metric_table)
    return assign_diagnostic_flag(scored)


# --------------------------------------------------------------------------
# Attainment context -- reported alongside the flag, never used to derive it
# --------------------------------------------------------------------------

def compute_attainment_context(as_of_date: date, window_quarters: int = _DEFAULT_TRAILING_QUARTERS,
                                panel: pd.DataFrame = None, con=None) -> pd.DataFrame:
    """Grain: one row per rep -- won ARR and quota attainment over the
    same trailing window the diagnostic flag is computed on, reported
    for context only. This is NOT a re-implementation of capacity
    planning's productivity/coverage/ramp-mix decomposition (no coverage-
    share pro-rating, no baseline-productivity estimate, no achievability
    verdict) -- it is the simplest possible per-rep echo (won ARR / stated
    quota) of the same two source marts capacity planning already reads,
    included here only so this module's own honest-null correlation check
    (see run_build_time_validation) has something real to correlate the
    diagnostic flag against."""
    owns_con = con is None
    con = con or _connect()
    try:
        window_start, window_end = _window_bounds(as_of_date, window_quarters)
        panel = build_opportunity_panel(as_of_date, window_quarters, con=con) if panel is None else panel
        quota = load_rep_quota(as_of_date, window_start, window_end, con=con)
    finally:
        if owns_con:
            con.close()

    if panel.empty:
        return pd.DataFrame(columns=["rep_id", "won_arr", "stated_quota_sum", "attainment_pct"])

    won = panel[panel["is_won"]].groupby("rep_id")["amount"].sum().rename("won_arr")
    quota_sum = quota.groupby("rep_id")["stated_quota"].sum().rename("stated_quota_sum")
    ctx = pd.concat([won, quota_sum], axis=1).fillna(0.0)
    ctx["attainment_pct"] = np.where(
        ctx["stated_quota_sum"] > 0, ctx["won_arr"] / ctx["stated_quota_sum"], np.nan
    )
    return ctx.reset_index().rename(columns={"index": "rep_id"})


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def run_rep_productivity_diagnostics(as_of_date: date, window_quarters: int = _DEFAULT_TRAILING_QUARTERS,
                                      con=None) -> dict:
    """Grain: one row per quota-bearing rep. Source marts: dim_reps,
    fact_opportunities, fact_sales_activities. Builds the opportunity
    panel, computes the diagnostic flag, and joins the attainment context
    -- the single entry point real callers (a coaching dashboard, the
    build-time validation below) use."""
    owns_con = con is None
    con = con or _connect()
    try:
        panel = build_opportunity_panel(as_of_date, window_quarters, con=con)
        diagnostics = compute_rep_diagnostics(panel)
        attainment = compute_attainment_context(as_of_date, window_quarters, panel=panel, con=con)
    finally:
        if owns_con:
            con.close()

    if diagnostics.empty:
        window_start, window_end = _window_bounds(as_of_date, window_quarters)
        return {
            "as_of_date": as_of_date, "window_start": window_start, "window_end": window_end,
            "diagnostics": diagnostics, "panel": panel,
        }

    diagnostics = diagnostics.merge(attainment, on="rep_id", how="left")
    window_start, window_end = _window_bounds(as_of_date, window_quarters)
    return {
        "as_of_date": as_of_date, "window_start": window_start, "window_end": window_end,
        "diagnostics": diagnostics.sort_values(["rep_type", "rep_id"]).reset_index(drop=True),
        "panel": panel,
    }


# --------------------------------------------------------------------------
# Validation -- synthetic known-answer cases (structural/logic artifact,
# per analytics-engineering-conventions)
# --------------------------------------------------------------------------

def _synthetic_panel_row(opp_id, rep_id, rep_type, segment, is_won, rep_is_ramped,
                          n_touches, n_meet_resolved, n_meet_held, n_calls, n_calls_connected,
                          n_emails, n_emails_replied, n_contacts):
    return {
        "opportunity_id": opp_id, "rep_id": rep_id, "rep_type": rep_type, "segment": segment,
        "is_won": is_won, "amount": 50_000.0, "rep_is_ramped": rep_is_ramped,
        "n_touches": n_touches, "n_meet_resolved": n_meet_resolved, "n_meet_held": n_meet_held,
        "n_calls": n_calls, "n_calls_connected": n_calls_connected, "n_emails": n_emails,
        "n_emails_replied": n_emails_replied, "n_contacts": n_contacts,
        "stratum": (segment, is_won, rep_is_ramped),
    }


def _build_synthetic_population() -> pd.DataFrame:
    """A peer pool of 10 baseline AE reps (identical per-opportunity
    behavior, split across won/lost so every stratum this module
    stratifies on -- (segment, is_won, rep_is_ramped) -- is populated by
    more than one rep) plus 5 named test-subject reps, each engineered to
    trip exactly one verdict. Every peer and test rep clears every
    reliability floor (>= 8 resolved meetings, >= 10 calls, >= 10 emails,
    >= 3 opportunities) so the flags below are testing the composition-
    adjustment logic, not a reliability-gate edge case."""
    rows = []
    # 10 baseline peers: 3 opps each (2 won, 1 lost), all ramped,
    # identical per-opp behavior -- forms the benchmark pool.
    for i in range(10):
        rep = f"PEER-{i:02d}"
        for j, won in enumerate([True, True, False]):
            rows.append(_synthetic_panel_row(
                f"{rep}-OPP{j}", rep, "AE", "Enterprise", won, True,
                n_touches=15, n_meet_resolved=4, n_meet_held=3,
                n_calls=6, n_calls_connected=3, n_emails=5, n_emails_replied=2, n_contacts=3,
            ))
    # A ramping baseline sub-pool (3 peers, all ramping, lower raw
    # numbers than the ramped peers but internally consistent, and each
    # clearing every reliability floor on its own -- 3 opps, >=8 resolved
    # meetings, >=10 calls/emails) so the ramp-explained test rep below
    # has a real ramping-stratum benchmark to be compared against, not
    # just an empty or unreliable stratum.
    for i in range(3):
        rep = f"RAMPPEER-{i:02d}"
        for j, won in enumerate([True, True, False]):
            rows.append(_synthetic_panel_row(
                f"{rep}-OPP{j}", rep, "AE", "Enterprise", won, False,
                n_touches=10, n_meet_resolved=3, n_meet_held=2,
                n_calls=4, n_calls_connected=1, n_emails=4, n_emails_replied=1, n_contacts=2,
            ))

    # SYN-VOLUME-LOW: quality matches peers exactly; touches_per_opp is
    # roughly half the peer level.
    for j, won in enumerate([True, True, False]):
        rows.append(_synthetic_panel_row(
            f"SYN-VOLUME-LOW-OPP{j}", "SYN-VOLUME-LOW", "AE", "Enterprise", won, True,
            n_touches=7, n_meet_resolved=4, n_meet_held=3,
            n_calls=6, n_calls_connected=3, n_emails=5, n_emails_replied=2, n_contacts=3,
        ))

    # SYN-QUALITY-LOW: touches_per_opp matches peers exactly; held/
    # connect/reply/contacts are all well below the peer rate.
    for j, won in enumerate([True, True, False]):
        rows.append(_synthetic_panel_row(
            f"SYN-QUALITY-LOW-OPP{j}", "SYN-QUALITY-LOW", "AE", "Enterprise", won, True,
            n_touches=15, n_meet_resolved=4, n_meet_held=1,
            n_calls=6, n_calls_connected=1, n_emails=5, n_emails_replied=0, n_contacts=1,
        ))

    # SYN-BOTH-LOW: both volume and quality below peers. 3 opps (not 2)
    # so touches_per_opp/contacts_per_opp clear _MIN_OPPORTUNITIES.
    for j, won in enumerate([True, True, False]):
        rows.append(_synthetic_panel_row(
            f"SYN-BOTH-LOW-OPP{j}", "SYN-BOTH-LOW", "AE", "Enterprise", won, True,
            n_touches=6, n_meet_resolved=4, n_meet_held=1,
            n_calls=6, n_calls_connected=1, n_emails=5, n_emails_replied=0, n_contacts=1,
        ))

    # SYN-RAMP-EXPLAINED: entirely ramping-stratum opportunities, with raw
    # numbers well below the (ramped) PEER population's average -- but AT
    # OR ABOVE the ramping-stratum peer (RAMPPEER) benchmark once
    # composition-adjusted, so the residual should land at/above zero,
    # clear of the bottom quintile regardless of exactly which RAMPPEER
    # rows a tie-break happens to select. 3 opps to clear every
    # reliability floor on its own.
    for j, won in enumerate([True, True, False]):
        rows.append(_synthetic_panel_row(
            f"SYN-RAMP-EXPLAINED-OPP{j}", "SYN-RAMP-EXPLAINED", "AE", "Enterprise", won, False,
            n_touches=10, n_meet_resolved=3, n_meet_held=2,
            n_calls=4, n_calls_connected=2, n_emails=4, n_emails_replied=2, n_contacts=2,
        ))

    # SYN-ON-PAR: matches peer rates exactly, fully ramped.
    for j, won in enumerate([True, True, False]):
        rows.append(_synthetic_panel_row(
            f"SYN-ON-PAR-OPP{j}", "SYN-ON-PAR", "AE", "Enterprise", won, True,
            n_touches=15, n_meet_resolved=4, n_meet_held=3,
            n_calls=6, n_calls_connected=3, n_emails=5, n_emails_replied=2, n_contacts=3,
        ))

    return pd.DataFrame(rows)


def run_synthetic_scenarios() -> list:
    """Per analytics-engineering-conventions' "Structural/logic artifacts"
    category: one hand-constructed case per named verdict, run through the
    exact same compute_rep_diagnostics() pipeline real data uses. Returns
    a list of {name, expected, actual, passed} dicts."""
    panel = _build_synthetic_population()
    diagnostics = compute_rep_diagnostics(panel).set_index("rep_id")

    expected = {
        "SYN-VOLUME-LOW": "volume_constrained",
        "SYN-QUALITY-LOW": "engagement_quality_constrained",
        "SYN-BOTH-LOW": "volume_and_quality_constrained",
        "SYN-RAMP-EXPLAINED": "ramp_explained_on_par",
        "SYN-ON-PAR": "on_par",
    }
    results = []
    for rep_id, exp_flag in expected.items():
        actual_flag = diagnostics.loc[rep_id, "diagnostic_flag"] if rep_id in diagnostics.index else None
        results.append({
            "name": f"{rep_id.lower().replace('-', '_')}_gets_{exp_flag}",
            "expected": exp_flag,
            "actual": actual_flag,
            "passed": actual_flag == exp_flag,
        })
    return results


# --------------------------------------------------------------------------
# Build-time validation -- structural checks + real-data cohort recovery,
# not statistics (per analytics-engineering-conventions' "Structural/logic
# artifacts" category)
# --------------------------------------------------------------------------

def check_flags_are_mutually_exclusive_and_exhaustive(diagnostics: pd.DataFrame) -> dict:
    """Every scored rep gets exactly one of the five named verdicts --
    an invariant of assign_diagnostic_flag's if/elif chain, checked here
    rather than merely assumed from reading the code."""
    valid = {
        "volume_and_quality_constrained", "engagement_quality_constrained",
        "volume_constrained", "ramp_explained_on_par", "on_par", "insufficient_data",
    }
    bad = diagnostics[~diagnostics["diagnostic_flag"].isin(valid)]
    return {"check": "flags_are_mutually_exclusive_and_exhaustive",
            "passed": bool(len(bad) == 0), "n_bad": int(len(bad))}


def check_ramp_explained_never_coincides_with_a_flag(diagnostics: pd.DataFrame) -> dict:
    """Structural guarantee, not a hope: no rep can carry
    ramp_explained_on_par while quality_flag or intensity_flag is also
    True -- assign_diagnostic_flag's priority order makes this impossible
    by construction (the ramp-explained branch is only reached once both
    flags have already tested False), and this check recomputes it
    directly against the flag columns to confirm the code actually
    behaves the way the docstring claims."""
    bad = diagnostics[
        (diagnostics["diagnostic_flag"] == "ramp_explained_on_par")
        & (diagnostics["quality_flag"] | diagnostics["intensity_flag"])
    ]
    return {"check": "ramp_explained_never_coincides_with_a_flag",
            "passed": bool(len(bad) == 0), "n_bad": int(len(bad))}


def check_cohort_recovery_against_raw_quantile(panel: pd.DataFrame, diagnostics: pd.DataFrame) -> dict:
    """Non-vacuousness check, in the spirit of capacity planning's
    ramp_mechanism_is_real_not_vacuous: the composition-adjusted
    engagement_quality flag should be materially ENRICHED among the
    bottom-quintile-by-RAW-held-rate reps -- the exact recovery method
    tests/test_phase1_batch8.py's TestInjectedIncidents test already
    proves works on this data using only public activity data, no
    internal generator flag. This is a real-data check (not a synthetic
    one) confirming the two independent methods agree on which reps look
    bad, while allowing (and this build's own real-data run at 2025-12-31
    demonstrates) that the composition-adjusted method can legitimately
    clear a rep the raw method would have flagged -- see
    docs/acme-corp-analytics-methods.md for the concrete example
    (REP-00063, cleared once ramp status is composition-adjusted for)."""
    held = panel.groupby("rep_id").apply(
        lambda g: g["n_meet_held"].sum() / g["n_meet_resolved"].sum() if g["n_meet_resolved"].sum() else np.nan,
        include_groups=False,
    ).rename("raw_held_rate").reset_index()
    held = held.dropna(subset=["raw_held_rate"])
    if len(held) < _MIN_POOL_SIZE_FOR_QUANTILE:
        return {"check": "cohort_recovery_against_raw_quantile", "passed": None,
                "reason": "pool too small to evaluate", "n_pool": int(len(held))}

    n_bottom = max(1, int(np.ceil(len(held) * _QUANTILE_FLAG_THRESHOLD)))
    bottom_raw = set(held.nsmallest(n_bottom, "raw_held_rate")["rep_id"])
    flagged_quality = set(
        diagnostics.loc[diagnostics["diagnostic_flag"].isin(
            ["engagement_quality_constrained", "volume_and_quality_constrained"]
        ), "rep_id"]
    )
    overlap = bottom_raw & flagged_quality
    enrichment_rate = len(overlap) / len(bottom_raw) if bottom_raw else np.nan
    # A materially non-trivial overlap is the bar, not a perfect match --
    # composition-adjustment is EXPECTED to legitimately disagree with the
    # raw method on some reps (that disagreement is the artifact's value-
    # add, not a bug). >= 50% overlap means the two methods substantially
    # agree on who looks bad, while leaving visible room for the
    # composition adjustment to do real work on the rest.
    passed = enrichment_rate >= 0.50
    return {"check": "cohort_recovery_against_raw_quantile", "passed": bool(passed),
            "n_bottom_raw": len(bottom_raw), "n_overlap": len(overlap),
            "enrichment_rate": float(enrichment_rate) if not np.isnan(enrichment_rate) else None}


def run_build_time_validation(as_of_date: date, window_quarters: int = _DEFAULT_TRAILING_QUARTERS,
                               write: bool = True, con=None) -> dict:
    """Runs the synthetic-scenario suite plus the structural/real-data
    checks above, against a fresh run_rep_productivity_diagnostics() call.
    Logs scalar checkpoints to fact_model_performance_history via
    analytics/model_performance.py's log_performance(), matching every
    other Phase 4 artifact's persistence convention."""
    out = run_rep_productivity_diagnostics(as_of_date, window_quarters, con=con)
    diagnostics, panel = out["diagnostics"], out["panel"]

    synthetic = run_synthetic_scenarios()
    checks = [
        check_flags_are_mutually_exclusive_and_exhaustive(diagnostics),
        check_ramp_explained_never_coincides_with_a_flag(diagnostics),
        check_cohort_recovery_against_raw_quantile(panel, diagnostics),
    ]

    flag_counts = diagnostics["diagnostic_flag"].value_counts().to_dict()

    if write:
        log_performance(_MODEL_NAME, as_of_date, "synthetic_scenarios_passed",
                         float(sum(1 for s in synthetic if s["passed"])))
        log_performance(_MODEL_NAME, as_of_date, "synthetic_scenarios_total", float(len(synthetic)))
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_passed",
                         float(sum(1 for c in checks if c.get("passed"))))
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_total", float(len(checks)))
        log_performance(_MODEL_NAME, as_of_date, "reps_scored", float(len(diagnostics)))
        for flag_name, count in flag_counts.items():
            log_performance(_MODEL_NAME, as_of_date, f"reps_flagged_{flag_name}", float(count))

    return {
        "as_of_date": as_of_date, "window_start": out["window_start"], "window_end": out["window_end"],
        "diagnostics": diagnostics, "synthetic_scenarios": synthetic, "structural_checks": checks,
        "flag_counts": flag_counts,
    }


if __name__ == "__main__":
    result = run_build_time_validation(date(2025, 12, 31))
    print(f"Window: {result['window_start'].date()} -> {result['window_end'].date()}")
    print(f"Reps scored: {len(result['diagnostics'])}")
    print("Flag counts:", result["flag_counts"])
    print(f"Synthetic scenarios: {sum(1 for s in result['synthetic_scenarios'] if s['passed'])}/"
          f"{len(result['synthetic_scenarios'])} passed")
    for s in result["synthetic_scenarios"]:
        status = "PASS" if s["passed"] else "FAIL"
        print(f"  [{status}] {s['name']}: expected={s['expected']} actual={s['actual']}")
    print("Structural checks:")
    for c in result["structural_checks"]:
        print(f"  {c}")
