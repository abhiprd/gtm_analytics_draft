"""LTV by entry segment (SMB / Commercial / Enterprise) with an SMB acquisition-channel
cut -- grain: one lifetime-value reading per (as-of date, entry segment) over a 60-month
horizon, plus one LTV:CAC row per (entry segment, acquisition-channel cell) where a cell is
large enough to be shown. Source marts: dim_accounts (signup, acquisition channel),
fact_account_segment_history (entry segment), fact_revenue_monthly (per-account MRR by month;
account presence is how churn shows up), fact_marketing_spend (spend by channel-month),
fact_rep_monthly_cost (rep fully-loaded cost) and fact_opportunities (won new-business logos).
Account loading is shared with analytics/retention_cohorts.py (load_cohort_accounts).

The model behind the metric-tree node "LTV by segment x acquisition channel" (registry key
ltv_by_segment_acquisition_channel). That node is a NON-ADDITIVE diagnostic overlay on
Consumption payback, not a mathematical child, and it has no children: this module reads the
tree, redefines nothing in it, and is computed outside the mart engine. The tree fixes three
things this module reuses rather than re-derives: a 5-year horizon, a flat 10% annual
discount rate, and the ~80% gross margin that Consumption payback uses.

WHAT IT COMPUTES -- every number below is this artifact's own definition, PROPOSED, NOT YET
CONFIRMED (docs/acme-corp-analytics-methods.md, "LTV by segment x acquisition channel")

  entry segment    the segment an account had at signup (fact_account_segment_history,
                   is_initial_segment), never dim_accounts.segment (the CURRENT segment, which
                   differs for accounts that later migrated). An account that migrates and
                   grows stays in its entry-segment cohort, as in retention_cohorts: the
                   graduation upside belongs to the segment that acquired the account.
  age a            months since the signup month (a = 0 is the signup month, a partial month).
  S(a)             probability an account is still a paying customer at age a. Kaplan-Meier
                   (discrete-time, monthly) over every account in the entry segment: at-risk at
                   age k = accounts present at k and old enough to be observed at k+1;
                   S(a) = product over k < a of (1 - churned_k / at_risk_k). Pooled across all
                   vintages. Observed through the last age whose transition still has
                   MIN_AT_RISK (30) accounts at risk. Greenwood 95% interval over the observed ages.
  tail             beyond the observed age, a constant monthly hazard equal to events / at-risk
                   months over the last TAIL_WINDOW_MONTHS (12) observed transitions (one full
                   renewal cycle for annual-contract segments); the projected band takes the Wilson 95% bound on that rate from the
                   Greenwood bound at the last observed age, so it compounds worst x worst (best x best) and is NOT a 95%
                   interval.
  m(a)             mean MRR per SURVIVING account at age a. Three scenarios (the path is the
                   dominant uncertainty because per-survivor MRR rises with age AND with
                   calendar time -- age and calendar year cannot be separated in this data):
                     central  recent_flat   direct mean over accounts that signed up in the last
                                            RECENT_VINTAGE_MONTHS (36) months, to the last age
                                            with max(15, 5% of the window's accounts) survivors
                                            (mean MRR is heavy-tailed: about one account in ten
                                            graduates to a segment with 5 to 30 times the MRR),
                                            then held flat (no further expansion assumed past
                                            what recent vintages have shown)
                     alt      recent_chain  the same, then grown by link ratios (matched
                                            accounts, any vintage) -- older vintages supply the
                                            tail growth
                     alt      older_flat    direct mean over vintages older than the recent
                                            window, then held flat
                   The LTV range takes the lowest and highest LTV across the three paths
                   (crossed with the survival band); which path is lower differs by segment
                   (older vintages are lower for SMB and Commercial, higher for Enterprise).
  margin           GROSS_MARGIN (0.80), the same flat gross margin as mart_efficiency's
                   Consumption payback (dbt var consumption_gross_margin; a test ties the two).
                   MRR is billed MRR x margin; the payback model's utilization haircut is not
                   applied (LTV is "cumulative margin-adjusted revenue" per the tree).
  discount         10% a year, monthly factor (1 + r) ** (-a / 12): the revenue of age a is
                   treated as received a months after signup (month 0 undiscounted).
  LTV              sum over a = 0..59 of S(a) * m(a) * margin / (1 + r) ** (a / 12): margin-
                   adjusted, discounted revenue per ORIGINAL account (not per survivor).
  CAC              2023+ entry vintages only (marketing spend exists only from 2023-01).
                   Marketing-only CAC = marketing spend allocated to the entry segment (the
                   rule mart_efficiency uses for its S&M cost: a channel-month's spend is split
                   across segments by each segment's share of the channel-month's new accounts)
                   / new accounts of that entry segment. Rep-loaded CAC adds the segment's
                   acquisition-role rep cost (Commercial: ISR; Enterprise: AE and SE; AM cost
                   excluded) per won new-business logo; effort spent on lost deals is spread
                   evenly over the wins. SMB has no reps.
  Evidence grade   point (>= 200 churn events), range (20 to 199), directional only (< 20).

Shape decision: a projection built from observed rates, not a classifier; there is no AUC.
Per analytics-engineering-conventions its validation is the structural / projection kind:
reconciliation to the facts, a no-look-ahead perturbation, synthetic planted-hazard scenarios
with closed-form answers, and an out-of-time backtest of the retention curve and of the
discounted-revenue LTV (SMB; Commercial directional; Enterprise cannot be backtested).

Model type selection and rationale: a Kaplan-Meier survival curve with a constant-hazard tail
was chosen over (a) compounding mart_durability's GRR (monthly GRR counts month-to-month usage
contraction and compounds to roughly 50% a year, against logo retention of about 83% for SMB to
99% for Enterprise: it measures revenue contraction, not whether the account is still a
customer), (b) a parametric survival fit (Weibull, Cox with channel): the data shows
contract-structured cliffs (annual Commercial renewals) a smooth parametric shape would blur,
and the generators do not use channel in churn, so there is nothing for a covariate to find,
and (c) the retention_cohorts pooled at-risk ratio (active / at risk): that ratio is a
cross-section that mixes vintages of different ages at each age; Kaplan-Meier uses every
vintage's hazard at the ages it has observed and is monotone. The pooled ratio is reported
alongside for reconciliation.

Point-in-time discipline: every function takes as_of_date, normalised to the last complete
month end on or before it (data_through); nothing after it is read. validation proves it
against a perturbed copy of the marts. The one stochastic step is the synthetic scenarios'
seeded draws (_RANDOM_SEED).

No dbt model was added; the only dbt change is lifting the 0.80 literal in mart_efficiency
into the consumption_gross_margin var, which leaves every mart value unchanged.
"""
import calendar
import json
import math
import os
import re
from datetime import date, timedelta
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

from . import retention_cohorts as rc
from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
_DBT_PROJECT = os.path.join(os.path.dirname(__file__), "..", "dbt", "dbt_project.yml")
_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "..", "semantic", "metric_registry.json")
_MODEL_NAME = "ltv_by_segment"
_RANDOM_SEED = 42

NODE_KEY = "ltv_by_segment_acquisition_channel"
ENTRY_SEGMENTS = ("SMB", "Commercial", "Enterprise")

# --- The tree's three fixed inputs, defined once here ---------------------------------------
HORIZON_MONTHS = 60               # 5-year horizon (metric tree)
ANNUAL_DISCOUNT_RATE = 0.10       # flat 10% annual discount rate (metric tree)
# Flat ~80% gross margin (metric tree; build spec). The same value as dbt var
# consumption_gross_margin, which mart_efficiency reads; tests/test_phase4_ltv_by_segment.py
# fails if the two differ or the SQL carries a literal again.
GROSS_MARGIN = 0.80

# --- This artifact's own proposed parameters ------------------------------------------------
MIN_AT_RISK = 30                  # accounts at risk for a retention transition to be "observed"
MIN_SURVIVORS_MRR = 15            # survivors for a per-age MRR mean (or a link ratio) to be used, at least
MIN_SURVIVORS_SHARE = 0.05        # ... and for a per-age MRR mean at least this share of the window's accounts
TAIL_WINDOW_MONTHS = 12           # observed transitions that set the extrapolated hazard
RECENT_VINTAGE_MONTHS = 36        # signup window that defines the "recent vintage" MRR path
Z95 = 1.959964                    # two-sided 95% normal quantile (Greenwood, Wilson)
POINT_MIN_EVENTS = 200            # evidence grades by churn events in the entry segment
RANGE_MIN_EVENTS = 20
BACKTEST_LAG_MONTHS = 36          # backtest origin = data_through minus this
RETENTION_MARKS = (6, 12, 24, 36, 48, 60)
_N_AGES = HORIZON_MONTHS + 1      # retention is carried to age 60 (a = 0..60); LTV uses a < 60

# Acquisition-role rep cost by entry segment (fact_rep_monthly_cost.rep_type). AM roles are
# retention / expansion cost and are excluded; SDR/BDR cost does not exist in the data.
ACQUISITION_REP_TYPES = {"Commercial": ("ISR",), "Enterprise": ("AE", "SE")}

_FLOAT_TOLERANCE = 1e-9
_TOLERANCE_USD = 0.01
_SMALL_CHANNEL_NOTE = {
    "SMB": "shown",
    "Commercial": "suppressed: 44 churn events in the whole segment, so a channel cut would rest on a handful of events",
    "Enterprise": "suppressed: 5 churn events in the whole segment",
}

STATUS_RULE = {
    "status": "proposed, not yet confirmed",
    "evidence_grades": {
        "point": f"at least {POINT_MIN_EVENTS} churn events in the entry segment: a point estimate with a band",
        "range": f"{RANGE_MIN_EVENTS} to {POINT_MIN_EVENTS - 1} churn events: report the range, not the point",
        "directional": f"fewer than {RANGE_MIN_EVENTS} churn events: directional only",
    },
}

DEFINITIONS = {
    "entry_segment": "The segment an account had at signup. Accounts that later migrate stay in their entry-segment cohort.",
    "survival": "Kaplan-Meier monthly survival, pooled across vintages, observed while at least 30 accounts are at risk; beyond that a constant hazard from the last 12 observed months.",
    "mrr_path": "Mean MRR per surviving account by age. Central: recent vintages to the last well-supported age, then flat. High: older vintages' growth for the tail. Low: older vintages' own path.",
    "ltv": "Sum over the first 60 months of survival x MRR per survivor x 80% margin, discounted at 10% a year, per account acquired.",
    "cac_marketing_only": "Marketing spend allocated to the entry segment by its share of each channel-month's new accounts, per new account (2023 onward).",
    "cac_rep_loaded": "Marketing-only CAC plus acquisition-role rep cost (ISR for Commercial, AE and SE for Enterprise; no AM cost) per won new-business logo.",
}

LTV_CAVEATS = (
    "A modeled lifetime view, not an observed value: the oldest accounts are 71 months old, and a large part of every segment's five-year value is projection (see observed_share).",
    "Per-account MRR rises with account age and with calendar time, and the two cannot be separated in this history, so the MRR path is the largest single uncertainty; the central path assumes no growth beyond what recent vintages have shown.",
    "Acquisition channel shows no detectable retention or revenue difference in this synthetic data (an absence of evidence, not proof); the channel split is a CAC split.",
    "The CAC spread by channel is a data-generation parameter, not an observed market price; SMB marketing-only LTV:CAC is very large by construction and is a floor on cost (no marketing headcount in the data), so read it as a direction, not a multiple.",
    "Marketing-only LTV:CAC is not decision-grade for Commercial or Enterprise: their reps are the acquisition cost.",
    "Pre-2023 vintages have no CAC (marketing spend starts 2023-01); they supply the retention tail and the MRR path, never an LTV:CAC.",
    "Commercial and Enterprise tails are thin (22 and 6 accounts at month 60): their LTVs are ranges, and Enterprise is directional only.",
    "Entry-segment LTV includes the MRR of accounts that migrated up; the account-management cost of serving and expanding them is not netted.",
)


# --------------------------------------------------------------------------
# Formatting helpers
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


def _x(value) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}x" if value < 100 else f"{value:,.0f}x"


def _pct(value, digits=1) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def _round(value, digits):
    if value is None:
        return None
    value = float(value)
    return round(value, digits) if np.isfinite(value) else None


def _jsonable(obj):
    """Recursively converts numpy/pandas/date values to JSON-safe Python values; non-finite floats become None."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_jsonable(v) for v in obj.tolist()]
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


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

def last_complete_month_end(d: date) -> date:
    """The last day of the last complete calendar month on or before d: the point-in-time cut every loader uses."""
    last = calendar.monthrange(d.year, d.month)[1]
    if d.day >= last:
        return date(d.year, d.month, last)
    return d.replace(day=1) - timedelta(days=1)


def month_index(ts) -> "pd.Series":
    """Months as an integer year * 12 + month, so age arithmetic never depends on datetime resolution."""
    return ts.dt.year * 12 + ts.dt.month


def index_to_month_end(idx: int) -> date:
    year, month = (idx - 1) // 12, (idx - 1) % 12 + 1
    return date(year, month, calendar.monthrange(year, month)[1])


def _as_of_index(d: date) -> int:
    return d.year * 12 + d.month


# --------------------------------------------------------------------------
# Loaders -- finished marts only, complete months only
# --------------------------------------------------------------------------

def load_frames(as_of_eff: date, con) -> dict:
    """Grain: the module's five input frames as of a month end. accounts: one row per account with
    signup_date <= as_of_eff (entry segment, channel); revenue: one row per account-month <= as_of_eff
    carrying age; spend: one row per channel-month; rep_cost: one row per rep_type-month; wins: one row
    per won new-business logo. Source marts: dim_accounts, fact_account_segment_history,
    fact_revenue_monthly, fact_marketing_spend, fact_rep_monthly_cost, fact_opportunities."""
    accounts = rc.load_cohort_accounts(as_of_eff, con=con)[
        ["account_id", "entry_segment", "channel", "signup_date"]].copy()
    accounts["m0"] = month_index(pd.to_datetime(accounts["signup_date"]))

    rev = con.execute(
        "select account_id, month, mrr, segment from main_marts.fact_revenue_monthly where month <= ?",
        [as_of_eff]).df()
    rev["month"] = pd.to_datetime(rev["month"])
    rev["r_idx"] = month_index(rev["month"])
    rev = rev.merge(accounts[["account_id", "entry_segment", "channel", "m0"]], on="account_id", how="inner")
    rev["age"] = rev["r_idx"] - rev["m0"]
    rev["mrr_in_entry"] = np.where(rev["segment"] == rev["entry_segment"], rev["mrr"], 0.0)
    rev = rev.drop(columns=["segment"])

    spend = con.execute(
        "select channel, month, spend, new_accounts from main_marts.fact_marketing_spend where month <= ?",
        [as_of_eff]).df()
    spend["month"] = pd.to_datetime(spend["month"])
    spend["r_idx"] = month_index(spend["month"])

    rep_cost = con.execute(
        "select month, rep_type, segment, sum(monthly_fully_loaded_cost_usd) as cost "
        "from main_marts.fact_rep_monthly_cost where month <= ? group by 1, 2, 3", [as_of_eff]).df()
    rep_cost["month"] = pd.to_datetime(rep_cost["month"])
    rep_cost["r_idx"] = month_index(rep_cost["month"])

    segment_revenue = con.execute(
        "select segment, month, sum(mrr) as mrr from main_marts.fact_revenue_monthly where month <= ? group by 1, 2",
        [as_of_eff]).df()
    segment_revenue["month"] = pd.to_datetime(segment_revenue["month"])
    segment_revenue["r_idx"] = month_index(segment_revenue["month"])

    wins = con.execute(
        "select segment, close_date from main_marts.fact_opportunities "
        "where opportunity_type = 'new_business' and is_won and close_date <= ?", [as_of_eff]).df()
    wins["close_date"] = pd.to_datetime(wins["close_date"])
    wins["r_idx"] = month_index(wins["close_date"])
    return {"accounts": accounts, "revenue": rev, "spend": spend, "rep_cost": rep_cost, "wins": wins,
            "segment_revenue": segment_revenue}


# --------------------------------------------------------------------------
# Survival: Kaplan-Meier with Greenwood band, constant-hazard tail
# --------------------------------------------------------------------------

def account_state(acc: pd.DataFrame, rev: pd.DataFrame, as_of_idx: int):
    """Grain: one (last_age, max_age) pair per account as of a month index. last_age = the last age with
    a revenue row (churn shows up as rows stopping); max_age = months from signup to the as-of month.
    Source: the accounts and revenue frames (fact_revenue_monthly, dim_accounts)."""
    a = acc[acc["m0"] <= as_of_idx]
    r = rev[rev["r_idx"] <= as_of_idx]
    last = r.groupby("account_id")["age"].max()
    last_age = a["account_id"].map(last).fillna(-1).to_numpy(dtype=int)
    max_age = (as_of_idx - a["m0"]).to_numpy(dtype=int)
    return last_age, max_age


def km_curve(last_age, max_age) -> dict:
    """Grain: one transition (age k -> k+1) per row. at_risk[k] = accounts present at k and old enough to
    be observed at k+1; events[k] = those absent at k+1. S[a] is the product of (1 - events / at_risk)
    over k < a; gw[a] the Greenwood variance sum. Pure arrays, no data access."""
    last_age = np.asarray(last_age, dtype=int)
    max_age = np.asarray(max_age, dtype=int)
    K = int(max_age.max()) if max_age.size else 0
    n = np.zeros(K)
    d = np.zeros(K)
    for k in range(K):
        observable = max_age >= k + 1
        n[k] = np.count_nonzero(observable & (last_age >= k))
        d[k] = np.count_nonzero(observable & (last_age == k))
    S = np.full(K + 1, np.nan)
    gw = np.full(K + 1, np.nan)
    S[0], gw[0] = 1.0, 0.0
    for k in range(K):
        if n[k] > 0:
            S[k + 1] = S[k] * (1.0 - d[k] / n[k])
            gw[k + 1] = gw[k] + (d[k] / (n[k] * (n[k] - d[k])) if n[k] > d[k] else 0.0)
    return {"at_risk": n, "events": d, "S": S, "gw": gw, "K": K}


def wilson_interval(k: float, n: float, z: float = Z95):
    """Wilson score interval for k events in n trials (here person-months of exposure)."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n)) / denom
    return (0.0 if k <= 0 else max(0.0, center - half)), (1.0 if k >= n else min(1.0, center + half))


def project_retention(curve: dict, n_ages: int = _N_AGES, min_at_risk: int = MIN_AT_RISK,
                      tail_window: int = TAIL_WINDOW_MONTHS) -> dict:
    """Grain: one survival value per age 0..n_ages-1, central plus a low/high band: a Greenwood 95% interval through
    the observed ages, and beyond them a COMPOUNDED worst-case / best-case band (not a 95% interval). Observed
    (Kaplan-Meier + Greenwood) through the last age whose transition has at least min_at_risk accounts
    at risk; beyond it a constant monthly hazard = events / at-risk months over the last tail_window
    observed transitions (low band: Wilson upper hazard from the low survival; high band: Wilson lower
    hazard from the high survival). Unavailable, with a reason, when there is no usable observed curve
    or fewer than tail_window observed months to set a tail on."""
    n, d, S, gw = curve["at_risk"], curve["events"], curve["S"], curve["gw"]
    below = np.nonzero(n < min_at_risk)[0]
    a_obs = int(below[0]) if below.size else int(curve["K"])
    a_end = min(a_obs, n_ages - 1)
    if a_end < 1:
        return {"status": "unavailable", "reason_code": "insufficient_at_risk",
                "reason": f"fewer than {min_at_risk} accounts are at risk at the first transition"}
    central = np.full(n_ages, np.nan)
    low = np.full(n_ages, np.nan)
    high = np.full(n_ages, np.nan)
    se = S[:a_end + 1] * np.sqrt(gw[:a_end + 1])
    central[:a_end + 1] = S[:a_end + 1]
    low[:a_end + 1] = np.clip(S[:a_end + 1] - Z95 * se, 0.0, 1.0)
    high[:a_end + 1] = np.clip(S[:a_end + 1] + Z95 * se, 0.0, 1.0)
    tail = None
    if a_end < n_ages - 1:
        if a_end < tail_window:
            return {"status": "unavailable", "reason_code": "insufficient_observed_history",
                    "reason": f"only {a_end} months are observed with {min_at_risk}+ accounts at risk; "
                              f"a tail needs {tail_window}"}
        w0 = a_end - tail_window
        events = float(d[w0:a_end].sum())
        exposure = float(n[w0:a_end].sum())
        h = events / exposure
        h_lo, h_hi = wilson_interval(events, exposure)
        for a in range(a_end + 1, n_ages):
            central[a] = central[a - 1] * (1.0 - h)
            low[a] = low[a - 1] * (1.0 - h_hi)
            high[a] = high[a - 1] * (1.0 - h_lo)
        tail = {"monthly_hazard": h, "monthly_hazard_low": h_lo, "monthly_hazard_high": h_hi,
                "window_events": events, "window_exposure_months": exposure,
                "window_start_age": w0, "window_end_age": a_end}
    return {"status": "present", "central": central, "low": low, "high": high,
            "observed_through": a_end, "observed_through_uncapped": a_obs, "tail": tail,
            "events_total": float(d[:a_end].sum()), "at_risk_at_end": float(n[a_end - 1])}


# --------------------------------------------------------------------------
# MRR per surviving account by age
# --------------------------------------------------------------------------

def _direct_path(rev: pd.DataFrame, col: str, H: int, min_surv: int, share: float = MIN_SURVIVORS_SHARE):
    """Mean of col per age 0..A among rows with age < H, while at least max(min_surv, share x the window's
    accounts) survivors remain; (array, A). The share floor exists because mean MRR is heavy-tailed (about
    one account in ten graduates to a segment with 5 to 30 times the MRR), so a mean over a few dozen
    survivors is swung by a single graduate."""
    sub = rev[rev["age"] < H]
    if sub.empty:
        return None, -1
    g = sub.groupby("age")[col].agg(["mean", "count"])
    if 0 not in g.index:
        return None, -1
    floor = max(min_surv, share * g.at[0, "count"])
    A = -1
    for a in range(H):
        if a in g.index and g.at[a, "count"] >= floor:
            A = a
        else:
            break
    if A < 0:
        return None, -1
    return g["mean"].reindex(range(A + 1)).to_numpy(dtype=float), A


def _link_ratios(rev: pd.DataFrame, col: str, H: int, min_pairs: int) -> np.ndarray:
    """ratio[a] = sum of col at age a+1 over sum at age a among accounts present at both; NaN where fewer than min_pairs."""
    r = rev[["account_id", "age", col]].sort_values(["account_id", "age"])
    nxt_age = r.groupby("account_id")["age"].shift(-1)
    nxt_val = r.groupby("account_id")[col].shift(-1)
    ok = nxt_age == r["age"] + 1
    pairs = pd.DataFrame({"age": r.loc[ok, "age"], "num": nxt_val[ok], "den": r.loc[ok, col]})
    g = pairs.groupby("age").agg(num=("num", "sum"), den=("den", "sum"), n=("num", "size"))
    ratio = np.full(H, np.nan)
    for a, row in g.iterrows():
        if a < H and row["n"] >= min_pairs and row["den"] > 0:
            ratio[int(a)] = row["num"] / row["den"]
    return ratio


def _extend_flat(path: np.ndarray, H: int) -> np.ndarray:
    out = np.empty(H)
    out[:len(path)] = path
    out[len(path):] = path[-1]
    return out


def _extend_chain(path: np.ndarray, ratio: np.ndarray, H: int) -> np.ndarray:
    out = np.empty(H)
    out[:len(path)] = path
    for a in range(len(path), H):
        g = ratio[a - 1]
        out[a] = out[a - 1] * (g if np.isfinite(g) and g > 0 else 1.0)
    return out


def mrr_path_scenarios(acc: pd.DataFrame, rev: pd.DataFrame, as_of_idx: int, col: str = "mrr",
                       H: int = HORIZON_MONTHS, min_surv: int = MIN_SURVIVORS_MRR,
                       recent_months: int = RECENT_VINTAGE_MONTHS) -> dict:
    """Grain: one MRR-per-survivor path of H ages per scenario (recent_flat central, recent_chain and
    older_flat alternatives), each with the last age it is directly observed. Source: the accounts and revenue
    frames (dim_accounts, fact_account_segment_history, fact_revenue_monthly)."""
    rev = rev[rev["r_idx"] <= as_of_idx]
    recent_start = as_of_idx - (recent_months - 1)
    rec = rev[rev["m0"] >= recent_start]
    old = rev[rev["m0"] < recent_start]
    base, A = _direct_path(rec, col, H, min_surv)
    out = {}
    if base is None:
        return out
    ratio = _link_ratios(rev, col, H, min_surv)
    out["recent_flat"] = {"values": _extend_flat(base, H), "direct_through": A, "role": "central"}
    out["recent_chain"] = {"values": _extend_chain(base, ratio, H), "direct_through": A,
                           "role": "alternative: older vintages' growth for the tail"}
    older, A_old = _direct_path(old, col, H, min_surv)
    if older is not None:
        out["older_flat"] = {"values": _extend_flat(older, H), "direct_through": A_old,
                             "role": "alternative: the older vintages' own path"}
    return out


# --------------------------------------------------------------------------
# LTV arithmetic
# --------------------------------------------------------------------------

def discount_factors(H: int = HORIZON_MONTHS, annual_rate: float = ANNUAL_DISCOUNT_RATE) -> np.ndarray:
    return (1.0 + annual_rate) ** (-np.arange(H) / 12.0)


def ltv_terms(S, m, margin: float = GROSS_MARGIN, annual_rate: float = ANNUAL_DISCOUNT_RATE,
              H: int = HORIZON_MONTHS) -> np.ndarray:
    """Per-age contribution to LTV: S(a) * m(a) * margin / (1 + r) ** (a / 12), a = 0..H-1, per original account."""
    return np.asarray(S[:H], dtype=float) * np.asarray(m[:H], dtype=float) * margin * discount_factors(H, annual_rate)


def ltv_value(S, m, **kw) -> float:
    return float(ltv_terms(S, m, **kw).sum())


def evaluate_ltv(ret: dict, paths: dict, in_entry_paths: Optional[dict] = None,
                 tail_window_alt: Optional[dict] = None, margin: float = GROSS_MARGIN,
                 annual_rate: float = ANNUAL_DISCOUNT_RATE) -> dict:
    """Grain: one LTV block for an entry segment. central = survival central x central MRR path; the
    range crosses the survival band with the MRR-path scenarios (low = lowest, high = highest). Also the
    observed-only value and observed/projected share, and one-factor sensitivities."""
    S_c, S_l, S_h = ret["central"], ret["low"], ret["high"]
    p = {name: v["values"] for name, v in paths.items()}
    central_path = p["recent_flat"]

    def ltv_value(S, m, **override):          # this scope's margin and rate unless a sensitivity overrides one
        return globals()["ltv_value"](S, m, **{"margin": margin, "annual_rate": annual_rate, **override})
    central = ltv_value(S_c, central_path)
    lows = [ltv_value(S_l, m) for m in p.values()]
    highs = [ltv_value(S_h, m) for m in p.values()]
    terms = ltv_terms(S_c, central_path, margin, annual_rate)
    a_direct = min(ret["observed_through"], paths["recent_flat"]["direct_through"], HORIZON_MONTHS - 1)
    observed = float(terms[:a_direct + 1].sum())
    sens = {
        "retention_band_low": ltv_value(S_l, central_path),
        "retention_band_high": ltv_value(S_h, central_path),
    }
    for name, v in paths.items():
        if name != "recent_flat":
            sens[f"mrr_path_{name}"] = ltv_value(S_c, v["values"])
    if in_entry_paths and "recent_flat" in in_entry_paths:
        sens["entry_segment_revenue_only"] = ltv_value(S_c, in_entry_paths["recent_flat"]["values"])
    sens["undiscounted"] = ltv_value(S_c, central_path, annual_rate=0.0)
    if tail_window_alt is not None and tail_window_alt.get("status") == "present":
        sens["tail_window_24_months"] = ltv_value(tail_window_alt["central"], central_path)
    sens["observed_window_only"] = observed
    return {
        "central": central, "low": min(lows + [central]), "high": max(highs + [central]),
        "observed_through_month": int(a_direct), "observed_usd": observed,
        "observed_share": observed / central if central > 0 else None,
        "projected_share": 1.0 - observed / central if central > 0 else None,
        "sensitivity": sens,
    }


def evidence_grade(events: float) -> str:
    if events >= POINT_MIN_EVENTS:
        return "point"
    if events >= RANGE_MIN_EVENTS:
        return "range"
    return "directional"


def fit_segment(acc: pd.DataFrame, rev: pd.DataFrame, as_of_idx: int, margin: float = GROSS_MARGIN,
                annual_rate: float = ANNUAL_DISCOUNT_RATE) -> dict:
    """Grain: one fitted entry segment (survival, MRR paths, LTV block) as of a month index. Source: the
    accounts and revenue frames filtered to that segment (dim_accounts, fact_revenue_monthly)."""
    acc = acc[acc["m0"] <= as_of_idx]
    rev = rev[rev["r_idx"] <= as_of_idx]
    if acc.empty:
        return {"status": "unavailable", "reason_code": "no_accounts", "reason": "no accounts of this entry segment exist yet"}
    last_age, max_age = account_state(acc, rev, as_of_idx)
    curve = km_curve(last_age, max_age)
    ret = project_retention(curve)
    n_events = float(np.count_nonzero(last_age < max_age))
    base = {"n_accounts": int(len(acc)), "n_churned": int(n_events), "curve": curve,
            "n_old_enough_for_month_60": int(np.count_nonzero(max_age >= HORIZON_MONTHS)),
            "n_moved_up": int(rev.loc[rev["mrr_in_entry"] < rev["mrr"], "account_id"].nunique())}
    if ret["status"] != "present":
        return {**base, "status": "unavailable", "reason_code": ret["reason_code"], "reason": ret["reason"]}
    paths = mrr_path_scenarios(acc, rev, as_of_idx)
    if "recent_flat" not in paths:
        return {**base, "status": "unavailable", "reason_code": "no_recent_vintage_mrr",
                "reason": f"fewer than {MIN_SURVIVORS_MRR} recent-vintage accounts to set an MRR path"}
    in_entry = mrr_path_scenarios(acc, rev, as_of_idx, col="mrr_in_entry")
    alt = project_retention(curve, tail_window=2 * TAIL_WINDOW_MONTHS)
    ltv = evaluate_ltv(ret, paths, in_entry, alt, margin, annual_rate)
    return {**base, "status": "present", "retention": ret, "paths": paths, "ltv": ltv,
            "grade": evidence_grade(n_events), "events": n_events}


# --------------------------------------------------------------------------
# CAC: marketing-only and rep-loaded, on ENTRY segment
# --------------------------------------------------------------------------

def compute_cac(accounts: pd.DataFrame, spend: pd.DataFrame, rep_cost: pd.DataFrame, wins: pd.DataFrame) -> dict:
    """Grain: one CAC reading per entry segment and one per (entry segment, channel) over the marketing-spend
    window (first spend month through the as-of month). Marketing spend of a channel-month is split across
    entry segments by each segment's share of that channel-month's new accounts (the allocation
    mart_efficiency uses, on entry rather than current segment); a channel-month with spend and no new
    accounts falls back to the channel's whole-window segment mix. Rep-loaded adds acquisition-role rep
    cost per won new-business logo. Source marts: dim_accounts, fact_account_segment_history,
    fact_marketing_spend, fact_rep_monthly_cost, fact_opportunities."""
    if spend.empty:
        return {"status": "unavailable", "reason_code": "before_marketing_spend_window",
                "reason": "marketing spend exists only from 2023-01, so no CAC can be computed yet"}
    months = sorted(spend["r_idx"].unique())
    first, last = int(months[0]), int(months[-1])
    in_window = accounts[(accounts["m0"] >= first) & (accounts["m0"] <= last)]
    n_sc_m = (in_window.groupby(["entry_segment", "channel", "m0"]).size().rename("n").reset_index()
              .rename(columns={"m0": "r_idx"}))
    n_ch_m = n_sc_m.groupby(["channel", "r_idx"])["n"].sum().rename("n_ch").reset_index()
    n_sc = n_sc_m.groupby(["entry_segment", "channel"])["n"].sum().rename("n_win").reset_index()
    n_ch = n_sc.groupby("channel")["n_win"].sum().rename("n_ch_win").reset_index()

    rows = []
    for _, s in spend.iterrows():
        ch, m, amt = s["channel"], int(s["r_idx"]), float(s["spend"])
        tot = n_ch_m[(n_ch_m["channel"] == ch) & (n_ch_m["r_idx"] == m)]
        if len(tot) and tot["n_ch"].iloc[0] > 0:
            part = n_sc_m[(n_sc_m["channel"] == ch) & (n_sc_m["r_idx"] == m)]
            for _, p in part.iterrows():
                rows.append((p["entry_segment"], ch, amt * p["n"] / tot["n_ch"].iloc[0]))
        else:
            part = n_sc[n_sc["channel"] == ch].merge(n_ch, on="channel")
            for _, p in part.iterrows():
                rows.append((p["entry_segment"], ch, amt * p["n_win"] / p["n_ch_win"]))
    alloc = pd.DataFrame(rows, columns=["entry_segment", "channel", "spend"])
    by_cell = alloc.groupby(["entry_segment", "channel"])["spend"].sum().rename("spend_usd").reset_index()
    by_cell = by_cell.merge(n_sc, on=["entry_segment", "channel"], how="outer").fillna({"spend_usd": 0.0, "n_win": 0})
    by_seg = by_cell.groupby("entry_segment").agg(spend_usd=("spend_usd", "sum"), n_win=("n_win", "sum")).reset_index()

    rc_win = rep_cost[(rep_cost["r_idx"] >= first) & (rep_cost["r_idx"] <= last)]
    wins_win = wins[(wins["r_idx"] >= first) & (wins["r_idx"] <= last)]
    seg_out, cell_out = {}, []
    for seg in ENTRY_SEGMENTS:
        row = by_seg[by_seg["entry_segment"] == seg]
        n_logos = int(row["n_win"].iloc[0]) if len(row) else 0
        spend_alloc = float(row["spend_usd"].iloc[0]) if len(row) else 0.0
        if n_logos == 0:
            seg_out[seg] = {"status": "unavailable", "reason_code": "no_new_accounts_in_window",
                            "reason": "no accounts of this entry segment were acquired in the spend window"}
            continue
        roles = ACQUISITION_REP_TYPES.get(seg, ())
        rep_total = float(rc_win[(rc_win["rep_type"].isin(roles))]["cost"].sum()) if roles else 0.0
        n_wins = int((wins_win["segment"] == seg).sum()) if roles else n_logos
        rep_per_logo = rep_total / n_wins if n_wins > 0 else None
        mkt = spend_alloc / n_logos
        seg_out[seg] = {
            "status": "present", "new_accounts": n_logos, "marketing_spend_allocated_usd": spend_alloc,
            "marketing_only_cac_usd": mkt,
            "rep_acquisition_roles": list(roles), "rep_cost_usd": rep_total, "won_new_business_logos": n_wins,
            "rep_cost_per_logo_usd": rep_per_logo,
            "rep_loaded_cac_usd": (mkt + rep_per_logo) if rep_per_logo is not None else None,
            "thin": n_logos < 30,
        }
        for _, c in by_cell[by_cell["entry_segment"] == seg].iterrows():
            if c["n_win"] > 0:
                cell_out.append({"entry_segment": seg, "channel": c["channel"], "new_accounts": int(c["n_win"]),
                                 "marketing_spend_allocated_usd": float(c["spend_usd"]),
                                 "marketing_only_cac_usd": float(c["spend_usd"]) / float(c["n_win"]),
                                 "rep_cost_per_logo_usd": rep_per_logo})
    return {"status": "present", "window_first_month": index_to_month_end(first).replace(day=1).isoformat(),
            "window_last_month": index_to_month_end(last).replace(day=1).isoformat(), "window_months": last - first + 1,
            "segments": seg_out, "cells": cell_out,
            "totals": {"allocated_usd": float(alloc["spend"].sum()), "spend_usd": float(spend["spend"].sum())}}


AM_REP_TYPES = {"Commercial": ("AM-Commercial",), "Enterprise": ("AM-Enterprise",)}


def compute_am_cost_share(rep_cost: pd.DataFrame, segment_revenue: pd.DataFrame, spend: pd.DataFrame) -> dict:
    """Grain: one reading per segment with account managers (Commercial, Enterprise) over the CAC window: AM
    fully-loaded cost as a share of the revenue booked in that (current) segment. Used to size what netting AM
    cost against LTV would do (AM cost is not acquisition cost and is not in CAC). Source marts:
    fact_rep_monthly_cost, fact_revenue_monthly, fact_marketing_spend (the window)."""
    if spend.empty:
        return {"status": "unavailable", "reason": "no CAC window before 2023"}
    first, last = int(spend["r_idx"].min()), int(spend["r_idx"].max())
    out = {}
    for seg, roles in AM_REP_TYPES.items():
        cost = float(rep_cost[(rep_cost["r_idx"] >= first) & (rep_cost["r_idx"] <= last)
                              & rep_cost["rep_type"].isin(roles)]["cost"].sum())
        revenue = float(segment_revenue[(segment_revenue["segment"] == seg) & (segment_revenue["r_idx"] >= first)
                                        & (segment_revenue["r_idx"] <= last)]["mrr"].sum())
        cost, revenue = round(cost, 2), round(revenue, 2)      # cents: no last-digit summation-order noise
        out[seg] = {"am_cost_usd": cost, "segment_revenue_usd": revenue,
                    "share_of_segment_revenue": round(cost / revenue, 10) if revenue > 0 else None}
    return {"status": "present", "window_first_month": index_to_month_end(first).replace(day=1).isoformat(),
            "window_last_month": index_to_month_end(last).replace(day=1).isoformat(), "segments": out}


def am_netting_factor(seg: str, post_move_share: float, am: dict) -> Optional[float]:
    """Approximate factor on LTV (and LTV:CAC) if account-management cost were netted: the value earned inside
    the entry segment bears that segment's AM-cost share of revenue, the value earned after the move the share of
    the segment above (SMB: the mean of Commercial and Enterprise). Margin is reduced by the share:
    (margin - share) / margin."""
    if am.get("status") != "present":
        return None
    sh = {k: v["share_of_segment_revenue"] for k, v in am["segments"].items()}
    if any(v is None for v in sh.values()):
        return None
    own = sh.get(seg, 0.0)
    above = {"SMB": (sh["Commercial"] + sh["Enterprise"]) / 2.0, "Commercial": sh["Enterprise"], "Enterprise": 0.0}[seg]
    s_eff = (1.0 - post_move_share) * own + post_move_share * above
    return (GROSS_MARGIN - s_eff) / GROSS_MARGIN


# --------------------------------------------------------------------------
# Channel: log-rank test and the SMB channel cut
# --------------------------------------------------------------------------

def logrank_test(last_a, max_a, last_b, max_b) -> dict:
    """Two-group log-rank test on the same discrete monthly at-risk sets the survival curve uses."""
    last_a, max_a, last_b, max_b = (np.asarray(x, dtype=int) for x in (last_a, max_a, last_b, max_b))
    K = int(max(max_a.max() if max_a.size else 0, max_b.max() if max_b.size else 0))
    o1 = e1 = v = 0.0
    for k in range(K):
        obs_a, obs_b = max_a >= k + 1, max_b >= k + 1
        n1, n2 = np.count_nonzero(obs_a & (last_a >= k)), np.count_nonzero(obs_b & (last_b >= k))
        d1, d2 = np.count_nonzero(obs_a & (last_a == k)), np.count_nonzero(obs_b & (last_b == k))
        n, dd = n1 + n2, d1 + d2
        if n > 1 and dd > 0 and n1 > 0 and n2 > 0:
            e1 += dd * n1 / n
            v += dd * (n1 / n) * (1.0 - n1 / n) * (n - dd) / (n - 1)
            o1 += d1
        elif dd > 0:
            o1 += d1
            e1 += dd * n1 / n if n > 0 else 0.0
    chi2 = (o1 - e1) ** 2 / v if v > 0 else 0.0
    return {"chi2": chi2, "p_value": math.erfc(math.sqrt(chi2 / 2.0)), "observed_group_a": o1, "expected_group_a": e1}


def channel_retention_test(acc: pd.DataFrame, rev: pd.DataFrame, as_of_idx: int, seg: str,
                           ch_a: str = "self_serve", ch_b: str = "inbound_marketing") -> dict:
    """Is one acquisition channel's retention different from another's within an entry segment? Log-rank p-value and n/events per channel."""
    a = acc[(acc["entry_segment"] == seg) & (acc["channel"] == ch_a)]
    b = acc[(acc["entry_segment"] == seg) & (acc["channel"] == ch_b)]
    if len(a) < MIN_AT_RISK or len(b) < MIN_AT_RISK:
        return {"segment": seg, "available": False}
    la, ma = account_state(a, rev[rev["entry_segment"] == seg], as_of_idx)
    lb, mb = account_state(b, rev[rev["entry_segment"] == seg], as_of_idx)
    t = logrank_test(la, ma, lb, mb)
    return {"segment": seg, "available": True, "channels": [ch_a, ch_b],
            "n_accounts": [int(len(a)), int(len(b))],
            "churn_events": [int(np.count_nonzero(la < ma)), int(np.count_nonzero(lb < mb))],
            "chi2": t["chi2"], "p_value": t["p_value"], "significant_at_5pct": bool(t["p_value"] < 0.05)}


def mann_whitney(x, y) -> dict:
    """Two-sided Mann-Whitney U test (normal approximation, tie-corrected) of two samples."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    n1, n2 = len(x), len(y)
    ranks = pd.Series(np.concatenate([x, y])).rank(method="average").to_numpy()
    u1 = ranks[:n1].sum() - n1 * (n1 + 1) / 2.0
    N = n1 + n2
    _, counts = np.unique(np.concatenate([x, y]), return_counts=True)
    var = n1 * n2 / 12.0 * ((N + 1) - float((counts ** 3 - counts).sum()) / (N * (N - 1)))
    z = (u1 - n1 * n2 / 2.0) / math.sqrt(var) if var > 0 else 0.0
    return {"u": u1, "z": z, "p_value": math.erfc(abs(z) / math.sqrt(2.0))}


CHANNEL_MRR_AGES = (6, 12, 24, 36)


def channel_mrr_tests(rev: pd.DataFrame, ch_a: str = "self_serve", ch_b: str = "inbound_marketing") -> dict:
    """Does MRR per surviving SMB account differ by acquisition channel? Mann-Whitney on the MRR of accounts present
    at months 6, 12, 24 and 36, all vintages pooled. Commercial and Enterprise are not tested (their channel cuts are
    suppressed for thin evidence)."""
    smb = rev[rev["entry_segment"] == "SMB"]
    rows = []
    for age in CHANNEL_MRR_AGES:
        at = smb[smb["age"] == age]
        a, b = at.loc[at["channel"] == ch_a, "mrr"], at.loc[at["channel"] == ch_b, "mrr"]
        if len(a) < MIN_SURVIVORS_MRR or len(b) < MIN_SURVIVORS_MRR:
            continue
        t = mann_whitney(a, b)
        rows.append({"age": age, "channels": [ch_a, ch_b], "n": [int(len(a)), int(len(b))],
                     "mean_mrr_usd": [float(a.mean()), float(b.mean())], "median_mrr_usd": [float(a.median()), float(b.median())],
                     "p_value": t["p_value"]})
    return {"SMB": {"test": "Mann-Whitney U (normal approximation, tie-corrected) on MRR of accounts present at the age",
                    "rows": rows, "any_significant_at_5pct": any(r["p_value"] < 0.05 for r in rows)},
            "Commercial": {"status": "untested", "reason": "channel cut suppressed (44 churn events in the whole segment)"},
            "Enterprise": {"status": "untested",
                           "reason": "channel cut suppressed (5 churn events); a test on that few accounts is not interpretable"}}


def smb_channel_cut(acc, rev, as_of_idx, fit_smb: dict, cac: dict, test: dict) -> list:
    """Grain: one row per SMB acquisition channel. The LTV uses the segment's pooled survival and MRR path
    unless the log-rank test finds a channel difference at 5% (it does not), so the channel difference in
    LTV:CAC is CAC. The channel's own-survival LTV is reported as a sensitivity."""
    out = []
    smb_acc = acc[acc["entry_segment"] == "SMB"]
    smb_rev = rev[rev["entry_segment"] == "SMB"]
    central_path = fit_smb["paths"]["recent_flat"]["values"]
    shared_ltv = fit_smb["ltv"]["central"]
    for ch in sorted(smb_acc["channel"].unique()):
        sub = smb_acc[smb_acc["channel"] == ch]
        la, ma = account_state(sub, smb_rev[smb_rev["channel"] == ch], as_of_idx)
        events = int(np.count_nonzero(la < ma))
        row = {"entry_segment": "SMB", "channel": ch, "n_accounts": int(len(sub)), "churn_events": events}
        ret = project_retention(km_curve(la, ma))
        if ret["status"] == "present":
            row["own_survival_ltv_usd"] = ltv_value(ret["central"], central_path)
            row["own_survival_month60"] = float(ret["central"][HORIZON_MONTHS])
        use_own = bool(test.get("available") and test["significant_at_5pct"] and "own_survival_ltv_usd" in row)
        row["ltv_central_usd"] = row["own_survival_ltv_usd"] if use_own else shared_ltv
        row["ltv_basis"] = "channel's own survival (channels differ at 5%)" if use_own else \
            "segment-wide survival and MRR path (no channel retention difference at 5%)"
        cell = next((c for c in (cac.get("cells") or []) if c["entry_segment"] == "SMB" and c["channel"] == ch), None)
        if cell:
            row["marketing_only_cac_usd"] = cell["marketing_only_cac_usd"]
            row["new_accounts_in_cac_window"] = cell["new_accounts"]
            row["ltv_to_cac_marketing_only"] = row["ltv_central_usd"] / cell["marketing_only_cac_usd"]
            if "own_survival_ltv_usd" in row:
                row["ltv_to_cac_own_survival"] = row["own_survival_ltv_usd"] / cell["marketing_only_cac_usd"]
        out.append(row)
    return out


# --------------------------------------------------------------------------
# Reading assembly
# --------------------------------------------------------------------------

def _checkpoints(ret: dict) -> dict:
    out = {}
    for mark in RETENTION_MARKS:
        out[str(mark)] = {
            "central": _round(ret["central"][mark], 6), "low": _round(ret["low"][mark], 6),
            "high": _round(ret["high"][mark], 6),
            "kind": "observed" if mark <= ret["observed_through"] else "projected",
        }
    return out


DECISION_GRADE_RULE = ("A rep-loaded LTV:CAC is decision-grade only if (1) the segment's evidence grade is 'point', (2) rep cost is "
                       "loaded wherever the segment has acquisition reps, and (3) no more than half of the LTV is revenue earned "
                       "after the account moves up a segment. The marketing-only ratio is decision-grade only where the segment "
                       "has no acquisition reps and the same three conditions hold. PROPOSED, not yet confirmed.")


def decision_grade(grade: str, has_reps: bool, rep_loaded_present: bool, post_move_share: Optional[float]) -> dict:
    """Applies DECISION_GRADE_RULE; returns the two flags and the unmet conditions."""
    unmet = []
    if grade != "point":
        unmet.append(f"evidence is '{grade}', not 'point'")
    if has_reps and not rep_loaded_present:
        unmet.append("rep cost is not loaded")
    if post_move_share is not None and post_move_share > 0.5:
        unmet.append(f"{post_move_share:.0%} of the value arrives after the account moves up a segment")
    rep_ok = not unmet
    return {"rep_loaded": rep_ok, "marketing_only": rep_ok and not has_reps, "unmet": unmet}


def _ltv_cac_block(ltv: dict, cac: dict, seg: str, grade: str, am_factor: Optional[float] = None) -> dict:
    out = {}
    if cac.get("status") != "present" or ltv is None:
        return out
    for basis, key in (("marketing_only", "marketing_only_cac_usd"), ("rep_loaded", "rep_loaded_cac_usd")):
        v = cac.get(key)
        if v is None or v <= 0:
            continue
        out[basis] = {"cac_usd": v, "central": ltv["central"] / v, "low": ltv["low"] / v, "high": ltv["high"] / v}
        inside = ltv["sensitivity"].get("entry_segment_revenue_only")
        if inside is not None and seg != "Enterprise":
            out[basis]["entry_segment_revenue_only"] = inside / v
    central = ltv["central"]
    post_move = (1.0 - ltv["sensitivity"]["entry_segment_revenue_only"] / central) if (
        seg != "Enterprise" and central > 0 and "entry_segment_revenue_only" in ltv["sensitivity"]) else None
    dg = decision_grade(grade, bool(cac.get("rep_acquisition_roles")), cac.get("rep_loaded_cac_usd") is not None, post_move)
    if am_factor is not None and "rep_loaded" in out:
        out["rep_loaded"]["if_am_cost_netted"] = out["rep_loaded"]["central"] * am_factor
    if seg == "SMB":
        reading = ("a floor on cost (no marketing headcount in the data) and a data-generation CAC parameter: "
                   "read as 'far above any threshold', not as a precise multiple")
    elif seg == "Commercial":
        reading = "usable as a range against the rep-loaded cost only; the marketing-only ratio omits the reps, who are the acquisition cost"
    else:
        reading = "directional only: 5 churn events, thin tail; the marketing-only ratio omits the reps, who are the acquisition cost"
    out["marketing_only_decision_grade"] = dg["marketing_only"]
    out["rep_loaded_decision_grade"] = dg["rep_loaded"]
    out["decision_grade_unmet_conditions"] = dg["unmet"]
    out["decision_grade_rule"] = DECISION_GRADE_RULE
    out["how_to_read"] = reading
    return out


def _graduation_block(seg: str, fit: dict, ltv: dict, ratio: dict, am: dict) -> Optional[dict]:
    """What share of the LTV is earned after the account moves up a segment, how few accounts that is, and why the
    gap to the inside-segment ratio is attribution, not account-management cost (sized from the data)."""
    inside = ltv["sensitivity"].get("entry_segment_revenue_only")
    if seg == "Enterprise" or inside is None or ltv["central"] <= 0:
        return None
    post = 1.0 - inside / ltv["central"]
    n, moved = fit["n_accounts"], fit["n_moved_up"]
    factor = am_netting_factor(seg, post, am)
    rl = ratio.get("rep_loaded") or {}
    block = {"share_of_ltv_after_move": post, "entry_segment_revenue_only_usd": inside,
             "accounts": n, "accounts_moved_up": moved, "share_of_accounts_moved_up": moved / n if n else None}
    if factor is not None:
        block["am_cost_netting_factor"] = factor
        block["ltv_to_cac_rep_loaded_if_am_cost_netted"] = rl.get("if_am_cost_netted")
        sh = {k: v["share_of_segment_revenue"] for k, v in am["segments"].items()}
        block["am_cost_share_of_segment_revenue"] = sh
    return block


def _graduation_text(seg: str, g: dict, ratio: dict) -> str:
    rl = ratio.get("rep_loaded") or {}
    text = (f"{_pct(g['share_of_ltv_after_move'], 0)} of the value is revenue earned after the account moves up a segment, "
            f"carried by {g['accounts_moved_up']} of {g['accounts']} accounts ({_pct(g['share_of_accounts_moved_up'], 0)}); "
            f"revenue earned inside {seg} alone is {_usd(g['entry_segment_revenue_only_usd'])}")
    if "am_cost_share_of_segment_revenue" in g and rl:
        sh = g["am_cost_share_of_segment_revenue"]
        text += (f". Account-management cost is about {_pct(sh['Commercial'])} of Commercial and {_pct(sh['Enterprise'])} of "
                 f"Enterprise revenue, so netting it would lower the ratio only to about {_x(rl.get('if_am_cost_netted'))}; "
                 "the gap to the inside-segment ratio is how the upside of the few accounts that move up is credited, "
                 "not that cost")
    return text


def _segment_display(seg: str, r: dict, ratio: Optional[dict] = None, cac: Optional[dict] = None,
                     graduation: Optional[dict] = None) -> dict:
    ltv, ret = r["ltv"], r["retention"]
    disp = {}
    grade_text = {"point": "point estimate with a band", "range": "a range, not a point", "directional": "directional only"}[r["grade"]]
    disp["evidence"] = grade_text
    disp["ltv"] = (f"{_usd(ltv['central'])} of margin-adjusted revenue per new account over five years, discounted "
                   f"(range {_usd(ltv['low'])} to {_usd(ltv['high'])}); {grade_text}")
    disp["retention_month_60"] = (f"{_pct(ret['central'][60])} of accounts remain at month 60 "
                                  + (f"(95% interval {_pct(ret['low'][60])} to {_pct(ret['high'][60])}; observed)" if ret['observed_through'] >= 60 else
                                     f"(worst-to-best-case range {_pct(ret['low'][60])} to {_pct(ret['high'][60])}, not a 95% interval; "
                                     f"projected beyond month {ret['observed_through']})"))
    disp["projection_share"] = (f"{_pct(ltv['projected_share'], 0)} of the five-year value is projection beyond what the data "
                                f"directly shows (observed through month {ltv['observed_through_month']})")
    if graduation is not None:
        disp["graduation"] = _graduation_text(seg, graduation, ratio or {})
    if cac and cac.get("status") == "present":
        loaded = cac.get("rep_loaded_cac_usd")
        disp["cac"] = (f"{_usd(cac['marketing_only_cac_usd'])} marketing-only"
                       + (f", {_usd(loaded)} with sales-rep cost" if cac.get("rep_acquisition_roles") else " (no sales reps in this segment, so the same figure with rep cost)"))
    if ratio and ratio.get("rep_loaded"):
        q = ratio["rep_loaded"]
        inside = q.get("entry_segment_revenue_only")
        has_reps = bool(cac and cac.get("rep_acquisition_roles"))
        unmet = ratio.get("decision_grade_unmet_conditions") or []
        disp["ltv_to_cac"] = (f"{_x(q['central'])} (range {_x(q['low'])} to {_x(q['high'])}) against "
                              + ("the rep-loaded cost" if has_reps else
                                 "marketing cost, which is the whole CAC for SMB (no sales reps)")
                              + (f", {_x(inside)} counting only revenue earned inside {seg}" if inside is not None else "") + "; "
                              + ("the marketing-only ratio is not decision-grade here because the reps are the acquisition cost"
                                 if has_reps else
                                 "a floor on cost, so read it as a direction rather than a multiple")
                              + ("; not decision-grade itself: " + "; ".join(unmet) if unmet else ""))
    parts = [f"A new {seg} account is worth about {_usd(ltv['central'])} of margin-adjusted revenue over five years, discounted "
             f"({disp['evidence']}; range {_usd(ltv['low'])} to {_usd(ltv['high'])})"]
    if "graduation" in disp:
        parts.append(disp["graduation"])
    if "ltv_to_cac" in disp:
        parts.append("LTV:CAC " + disp["ltv_to_cac"])
    disp["summary"] = ". ".join(parts) + "."
    return disp


def _segment_reading(seg: str, fit: dict, cac: dict, am: Optional[dict] = None) -> dict:
    if fit["status"] != "present":
        return {"entry_segment": seg, "status": "unavailable", "reason_code": fit["reason_code"], "reason": fit["reason"],
                "n_accounts": fit.get("n_accounts", 0), "display": {"ltv": f"{seg}: unavailable ({fit['reason']})"}}
    ret, ltv, paths = fit["retention"], fit["ltv"], fit["paths"]
    seg_cac = (cac.get("segments") or {}).get(seg, cac) if cac.get("status") == "present" else cac
    am = am or {"status": "unavailable"}
    post = (1.0 - ltv["sensitivity"]["entry_segment_revenue_only"] / ltv["central"]) if (
        seg != "Enterprise" and ltv["central"] > 0) else 0.0
    factor = am_netting_factor(seg, post, am) if seg_cac.get("status") == "present" else None
    ratio = _ltv_cac_block(ltv, seg_cac, seg, fit["grade"], factor) if seg_cac.get("status") == "present" else {}
    graduation = _graduation_block(seg, fit, ltv, ratio, am) if seg_cac.get("status") == "present" else None
    tail = ret["tail"]
    reading = {
        "entry_segment": seg, "status": "present", "evidence_grade": fit["grade"],
        "n_accounts": fit["n_accounts"], "n_churned": fit["n_churned"],
        "retention": {
            "observed_through_month": ret["observed_through"], "at_risk_at_observed_end": ret["at_risk_at_end"],
            "checkpoints": _checkpoints(ret),
            "tail": None if tail is None else {k: _round(v, 8) for k, v in tail.items()},
            "curve": {"ages": list(range(_N_AGES)), "central": [_round(v, 6) for v in ret["central"]],
                      "low": [_round(v, 6) for v in ret["low"]], "high": [_round(v, 6) for v in ret["high"]]},
        },
        "mrr_path": {
            name: {"role": v["role"], "directly_observed_through_month": v["direct_through"],
                   "month_12": _round(v["values"][12], 2), "month_36": _round(v["values"][36], 2),
                   "month_59": _round(v["values"][59], 2)} for name, v in paths.items()},
        "ltv": {
            "central_usd": _round(ltv["central"], 2), "low_usd": _round(ltv["low"], 2), "high_usd": _round(ltv["high"], 2),
            "observed_through_month": ltv["observed_through_month"], "observed_usd": _round(ltv["observed_usd"], 2),
            "observed_share": _round(ltv["observed_share"], 6), "projected_share": _round(ltv["projected_share"], 6),
            "sensitivity_usd": {k: _round(v, 2) for k, v in ltv["sensitivity"].items()},
        },
        "cac": None if seg_cac.get("status") != "present" else {k: (_round(v, 2) if isinstance(v, float) else v)
                                                                  for k, v in seg_cac.items()},
        "cac_status": seg_cac.get("status"),
        "ltv_to_cac": {k: ({kk: _round(vv, 4) for kk, vv in v.items()} if isinstance(v, dict) else v) for k, v in ratio.items()},
        "graduation": None if graduation is None else _jsonable_round(graduation),
        "display": _segment_display(seg, {"ltv": ltv, "retention": ret, "grade": fit["grade"]}, ratio,
                                    seg_cac if seg_cac.get("status") == "present" else None, graduation),
    }
    if seg_cac.get("status") != "present":
        reading["cac_reason"] = seg_cac.get("reason")
    cav = [f"{int(fit['events'])} churn events in this entry segment in total; {fit['n_old_enough_for_month_60']} accounts are old enough to have reached month {HORIZON_MONTHS}. "
           f"Survival is observed through month {ret['observed_through']}"
           + (f"; beyond it a constant monthly hazard of {_pct(tail['monthly_hazard'], 2)} from {int(tail['window_events'])} events "
              f"in the last {TAIL_WINDOW_MONTHS} observed months." if tail else ".")]
    if fit["grade"] == "directional":
        cav.append("Directional only: too few churn events for a point estimate or a trustworthy range.")
    elif fit["grade"] == "range":
        cav.append("Report the range, not the central value.")
    reading["caveats"] = cav
    return reading


def _jsonable_round(obj, digits=6):
    if isinstance(obj, dict):
        return {k: _jsonable_round(v, digits) for k, v in obj.items()}
    if isinstance(obj, float):
        return _round(obj, digits)
    return obj


def _headline(readings: list) -> str:
    parts = []
    for r in readings:
        if r["status"] == "present":
            parts.append(f"{r['entry_segment']} {_usd(r['ltv']['central_usd'])} ({_usd(r['ltv']['low_usd'])} to {_usd(r['ltv']['high_usd'])})")
    return ("Modeled five-year lifetime value per new account, discounted: " + "; ".join(parts) + "." if parts
            else "No lifetime value can be computed at this date.")


def run_ltv(as_of_date: date, con=None, frames: Optional[dict] = None) -> dict:
    """The artifact's headline output. Grain: one lifetime-value reading per entry segment as of the last
    complete month end on or before as_of_date, plus the SMB channel cut and the CAC / LTV:CAC blocks.
    Source marts: dim_accounts, fact_account_segment_history, fact_revenue_monthly, fact_marketing_spend,
    fact_rep_monthly_cost, fact_opportunities. JSON-safe; read verbatim by consumers."""
    as_of_eff = last_complete_month_end(as_of_date)
    as_of_idx = _as_of_index(as_of_eff)
    owns = con is None and frames is None
    if frames is None:
        con = con or _connect()
    try:
        fr = frames if frames is not None else load_frames(as_of_eff, con)
    finally:
        if owns:
            con.close()
    acc, rev = fr["accounts"], fr["revenue"]
    cac = compute_cac(acc, fr["spend"], fr["rep_cost"], fr["wins"])
    am = compute_am_cost_share(fr["rep_cost"], fr["segment_revenue"], fr["spend"])
    fits = {seg: fit_segment(acc[acc["entry_segment"] == seg], rev[rev["entry_segment"] == seg], as_of_idx)
            for seg in ENTRY_SEGMENTS}
    segments = [_segment_reading(seg, fits[seg], cac, am) for seg in ENTRY_SEGMENTS]
    mrr_tests = channel_mrr_tests(rev)

    tests = {seg: channel_retention_test(acc, rev, as_of_idx, seg) for seg in ("SMB", "Commercial")}
    channel_cut = []
    if fits["SMB"]["status"] == "present":
        channel_cut = smb_channel_cut(acc, rev, as_of_idx, fits["SMB"], cac if cac.get("status") == "present" else {}, tests["SMB"])
    suppressed = [{"entry_segment": s, "status": "suppressed", "reason": _SMALL_CHANNEL_NOTE[s]}
                  for s in ("Commercial", "Enterprise")]
    suppressed.append({"entry_segment": "SMB", "channel": "outbound_sdr", "status": "suppressed",
                       "reason": "no SMB account was acquired through outbound_sdr; its 18 accounts are all Enterprise (tooling spend only, no SDR headcount in the data)"})

    return _jsonable({
        "artifact": "ltv_by_segment",
        "node": NODE_KEY,
        "label": "modeled lifetime view, a projection from observed rates; non-additive overlay on Consumption payback",
        "non_additive": True,
        "as_of_date": as_of_date.isoformat(), "data_through": as_of_eff.isoformat(),
        "constants": {"horizon_months": HORIZON_MONTHS, "annual_discount_rate": ANNUAL_DISCOUNT_RATE,
                      "gross_margin": GROSS_MARGIN, "min_at_risk": MIN_AT_RISK, "min_survivors_mrr": MIN_SURVIVORS_MRR,
                      "min_survivors_share": MIN_SURVIVORS_SHARE,
                      "tail_window_months": TAIL_WINDOW_MONTHS, "recent_vintage_months": RECENT_VINTAGE_MONTHS,
                      "timing": "revenue of age a is discounted a months; month 0 (the signup month) is undiscounted",
                      "status": "proposed, not yet confirmed"},
        "headline": _headline(segments),
        "segments": segments,
        "cac_window": None if cac.get("status") != "present" else {
            k: cac[k] for k in ("window_first_month", "window_last_month", "window_months")},
        "cac_status": cac.get("status"),
        "cac_reason": cac.get("reason"),
        "smb_channel_cut": channel_cut,
        "channel_cells_not_shown": suppressed,
        "channel_retention_tests": tests,
        "channel_mrr_tests": mrr_tests,
        "channel_finding": _channel_finding(tests, channel_cut, mrr_tests),
        "am_cost_context": am,
        "status_rule": STATUS_RULE, "definitions": DEFINITIONS, "caveats": list(LTV_CAVEATS),
    })


def _channel_finding(tests: dict, channel_cut: list, mrr_tests: dict) -> str:
    """The plain-language channel statement, built from the tests it reports: an absence-of-evidence statement, not proof of no effect."""
    smb = tests["SMB"]
    if not smb.get("available"):
        return "Channel retention could not be tested at this date."
    surv = {c["channel"]: c.get("own_survival_month60") for c in channel_cut}
    gap = ""
    if surv.get("self_serve") is not None and surv.get("inbound_marketing") is not None:
        gap = f", a {abs(surv['self_serve'] - surv['inbound_marketing']) * 100:.1f}-point gap in month-60 survival"
    com = tests["Commercial"]
    ret_sig = smb["significant_at_5pct"] or bool(com.get("significant_at_5pct"))
    text = ((f"Retention differs by channel at 5% somewhere (log-rank p = {smb['p_value']:.2f} for SMB self_serve vs inbound_marketing)"
             if ret_sig else
             f"Acquisition channel shows no detectable difference in retention (log-rank p = {smb['p_value']:.2f} for SMB "
             f"self_serve vs inbound_marketing{gap}"
             + (f"; p = {com['p_value']:.2f} for Commercial" if com.get("available") else "") + ")"))
    rows = mrr_tests["SMB"]["rows"]
    if rows:
        ps = [r["p_value"] for r in rows]
        text += (f" or in revenue per surviving SMB account (Mann-Whitney p = {min(ps):.2f} to {max(ps):.2f} at months "
                 + ", ".join(str(r["age"]) for r in rows) + ")" if not mrr_tests["SMB"]["any_significant_at_5pct"] else
                 f"; revenue per surviving SMB account does differ at 5% at some age (smallest Mann-Whitney p = {min(ps):.3f})")
    text += (", and the generators do not use channel in churn or usage. This is an absence of evidence on synthetic data, not proof "
             "of no effect. Enterprise is untested (channel cut suppressed on 5 churn events; a test on that few accounts is not "
             "interpretable). The channel difference in LTV:CAC is a CAC difference.")
    return text


# --------------------------------------------------------------------------
# Out-of-time backtest
# --------------------------------------------------------------------------

BACKTEST_MARKS = (36, 42, 48, 54, 60)
BACKTEST_LTV_HORIZONS = (36, 60)
# PROPOSED drift rule (docs/acme-corp-analytics-methods.md). SMB is the one segment large enough for a point claim, so
# its realized retention at months 48 and 60 must sit within this many percentage points of the projection; a range segment
# (Commercial) is held to its own band; Enterprise cannot be backtested until enough accounts reach month 36.
SMB_GAP_PP_LIMIT = 5.0
SMB_LTV_36M_ERROR_LIMIT = 0.25
ENTERPRISE_BACKTESTABLE_AT_RISK_MONTH_36 = 30


def backtest_segment(acc: pd.DataFrame, rev: pd.DataFrame, as_of_idx: int, lag: int = BACKTEST_LAG_MONTHS) -> dict:
    """Grain: one out-of-time backtest per entry segment. Fits survival and the MRR paths using only data up
    to (as-of month - lag), projects to month 60 and the 60-month LTV, then compares them with what the same
    accounts did through the as-of month: survival by age (Kaplan-Meier on the same accounts, plus the
    retention_cohorts-style pooled ratio) and the discounted-margin LTV of accounts old enough to have the
    horizon observed, with the error split into a retention part and an MRR part. Source marts: dim_accounts,
    fact_account_segment_history, fact_revenue_monthly."""
    origin = as_of_idx - lag
    fit = fit_segment(acc, rev, origin)
    base = {"origin": index_to_month_end(origin).isoformat()}
    if fit["status"] != "present":
        return {**base, "status": "unavailable", "reason_code": fit["reason_code"], "reason": fit["reason"],
                "n_accounts_at_origin": fit.get("n_accounts", 0)}
    ret = fit["retention"]
    acc_o = acc[acc["m0"] <= origin]
    la, ma = account_state(acc_o, rev, as_of_idx)
    cur = km_curve(la, ma)
    rows = []
    for mark in BACKTEST_MARKS:
        if mark <= ret["observed_through"]:
            continue
        if mark - 1 >= cur["K"] or cur["at_risk"][mark - 1] < MIN_AT_RISK:
            continue
        real = float(cur["S"][mark])
        n_pool = int(np.count_nonzero(ma >= mark))
        pooled = float(np.count_nonzero((la >= mark) & (ma >= mark)) / n_pool) if n_pool else None
        proj, lo, hi = float(ret["central"][mark]), float(ret["low"][mark]), float(ret["high"][mark])
        rows.append({"age": mark, "projected": proj, "band_low": lo, "band_high": hi, "realized_km": real,
                     "realized_pooled_ratio": pooled, "n_at_risk_realized": int(cur["at_risk"][mark - 1]),
                     "gap_pp": (real - proj) * 100.0, "in_band": bool(lo <= real <= hi)})
    ltv_rows = []
    disc = discount_factors(HORIZON_MONTHS)
    for H in BACKTEST_LTV_HORIZONS:
        sel = acc_o[acc_o["m0"] <= as_of_idx - (H - 1)]
        if len(sel) < MIN_AT_RISK:
            continue
        rr = rev[rev["account_id"].isin(sel["account_id"]) & (rev["age"] < H) & (rev["r_idx"] <= as_of_idx)]
        real_ltv = float((rr["mrr"].to_numpy() * GROSS_MARGIN * disc[rr["age"].to_numpy()]).sum() / len(sel))
        last_sel, _ = account_state(sel, rev, as_of_idx)
        S_real = np.array([np.mean(last_sel >= a) for a in range(H)])
        m_real = rr.groupby("age")["mrr"].mean().reindex(range(H)).fillna(0.0).to_numpy()
        identity = ltv_value(S_real, m_real, H=H)
        central = fit["paths"]["recent_flat"]["values"]
        proj_ltv = ltv_value(ret["central"], central, H=H)
        entry = {
            "horizon_months": H, "n_accounts": int(len(sel)), "projected_usd": proj_ltv, "realized_usd": real_ltv,
            "error_pct": (proj_ltv / real_ltv - 1.0) * 100.0 if real_ltv > 0 else None,
            "realized_identity_max_abs_diff_usd": abs(identity - real_ltv),
            "retention_only_error_pct": (ltv_value(ret["central"], m_real, H=H) / identity - 1.0) * 100.0 if identity > 0 else None,
            "mrr_only_error_pct": (ltv_value(S_real, central, H=H) / identity - 1.0) * 100.0 if identity > 0 else None,
            "by_mrr_path": {name: {"projected_usd": ltv_value(ret["central"], v["values"], H=H),
                                   "error_pct": (ltv_value(ret["central"], v["values"], H=H) / real_ltv - 1.0) * 100.0
                                   if real_ltv > 0 else None}
                            for name, v in fit["paths"].items()},
        }
        ltv_rows.append(entry)
    return {**base, "status": "present", "fit_observed_through_month": ret["observed_through"],
            "fit_tail": ret["tail"], "fit_n_accounts": fit["n_accounts"], "fit_churn_events": fit["n_churned"],
            "retention_rows": rows, "ltv_rows": ltv_rows,
            "max_abs_gap_pp": max((abs(r["gap_pp"]) for r in rows), default=None),
            "all_realized_in_band": all(r["in_band"] for r in rows) if rows else None}


def drift_assessment(backtests: dict, at_risk_month_36_enterprise: Optional[int]) -> dict:
    """Applies the proposed segment-appropriate drift rule to one checkpoint's backtests (a flag here is one
    checkpoint; the rule needs two consecutive)."""
    out = {}
    smb = backtests.get("SMB", {})
    late = [r for r in smb.get("retention_rows", []) if r["age"] in (48, 60)]
    if smb.get("status") == "present" and late:
        worst = max(abs(r["gap_pp"]) for r in late)
        outside = [r["age"] for r in late if not r["in_band"]]
        out["SMB"] = {"flag": bool(worst > SMB_GAP_PP_LIMIT or outside), "max_abs_gap_pp_months_48_60": worst,
                      "limit_pp": SMB_GAP_PP_LIMIT, "marks_outside_band": outside}
    else:
        out["SMB"] = {"flag": None, "reason": "no SMB retention mark beyond the fit window is observable at this checkpoint"}
    com = backtests.get("Commercial", {})
    late = [r for r in com.get("retention_rows", []) if r["age"] >= 48]
    if com.get("status") == "present" and late:
        outside = [r["age"] for r in late if not r["in_band"]]
        out["Commercial"] = {"flag": bool(outside), "marks_outside_band": outside,
                             "note": "held to its own band (a range segment); directional"}
    else:
        out["Commercial"] = {"flag": None, "reason": "no Commercial mark at month 48 or later is observable with 30 accounts at risk"}
    out["Enterprise"] = {"flag": None, "backtestable": bool((at_risk_month_36_enterprise or 0) >= ENTERPRISE_BACKTESTABLE_AT_RISK_MONTH_36),
                         "accounts_at_risk_month_36": at_risk_month_36_enterprise,
                         "reason": f"not backtestable until {ENTERPRISE_BACKTESTABLE_AT_RISK_MONTH_36} accounts have reached month 36"}
    return out


# --------------------------------------------------------------------------
# Validation -- reconciliations, perturbation, synthetic known answers
# --------------------------------------------------------------------------

def _mark(check: dict) -> str:
    """Printed marker: PASS; otherwise FAIL for a structural check, MISS for an unmet target, INFO for a reported comparison that gates nothing."""
    if check["passed"] and check["kind"] != "info":
        return "PASS"
    return {"structural": "FAIL", "target": "MISS", "info": "INFO"}[check["kind"]]


def _check(name, passed, detail, kind="structural") -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail, "kind": kind}


def validation_data_integrity(frames: dict) -> dict:
    """Every account has a signup-month revenue row, no revenue precedes signup, and each account's rows are contiguous (a churned account's rows simply stop)."""
    rev, acc = frames["revenue"], frames["accounts"]
    g = rev.groupby("account_id")["age"].agg(["min", "max", "size"])
    missing = int(len(acc) - len(g))
    bad_start = int((g["min"] != 0).sum())
    gaps = int((g["size"] != g["max"] + 1).sum())
    return _check("account_revenue_rows_start_at_signup_and_are_contiguous", missing == 0 and bad_start == 0 and gaps == 0,
                  f"{len(acc)} accounts: {missing} without revenue, {bad_start} not starting at age 0, {gaps} with gaps")


def validation_counts_tie_to_retention_cohorts(frames: dict, as_of_eff: date, con) -> dict:
    """The at-risk and still-present counts this module's survival uses equal retention_cohorts' pooled curve, age by age, for every entry segment (exact)."""
    as_of_idx = _as_of_index(as_of_eff)
    pooled = rc.compute_pooled_curve_by_segment(as_of_eff, con=con)
    worst, cells = 0.0, 0
    for seg in ENTRY_SEGMENTS:
        acc = frames["accounts"][frames["accounts"]["entry_segment"] == seg]
        la, ma = account_state(acc, frames["revenue"][frames["revenue"]["entry_segment"] == seg], as_of_idx)
        p = pooled[pooled["entry_segment"] == seg].set_index("elapsed_months")
        for age in range(0, int(ma.max()) + 1):
            mine_n, mine_a = int(np.count_nonzero(ma >= age)), int(np.count_nonzero((la >= age) & (ma >= age)))
            worst = max(worst, abs(mine_n - int(p.at[age, "n_accounts_at_risk"])), abs(mine_a - int(p.at[age, "active_count"])))
            cells += 1
    return _check("at_risk_and_active_counts_tie_to_retention_cohorts", worst == 0,
                  f"max abs count difference {worst:g} over {cells} segment-ages")


def validation_oldest_cohort_revenue_identity(frames: dict, as_of_eff: date, con) -> dict:
    """For the accounts old enough to have 60 months observed, the module's survival x MRR-per-survivor x margin x discount sum equals an independent SQL sum of their observed revenue (identity), and Kaplan-Meier equals the plain alive fraction when nothing is censored."""
    as_of_idx = _as_of_index(as_of_eff)
    worst_rel, worst_km, detail = 0.0, 0.0, []
    for seg in ENTRY_SEGMENTS:
        acc = frames["accounts"][frames["accounts"]["entry_segment"] == seg]
        sel = acc[acc["m0"] <= as_of_idx - (HORIZON_MONTHS - 1)]
        if sel.empty:
            continue
        rev = frames["revenue"]
        rr = rev[rev["account_id"].isin(sel["account_id"]) & (rev["age"] < HORIZON_MONTHS)]
        la, ma = account_state(sel, rev, as_of_idx)
        S = km_curve(la, ma)["S"][:HORIZON_MONTHS]
        alive = np.array([np.mean(la >= a) for a in range(HORIZON_MONTHS)])
        worst_km = max(worst_km, float(np.max(np.abs(S - alive))))
        m = rr.groupby("age")["mrr"].mean().reindex(range(HORIZON_MONTHS)).fillna(0.0).to_numpy()
        module_value = ltv_value(S, m)
        sql = con.execute(
            f"""
            select sum(r.mrr * {GROSS_MARGIN} / power(1 + {ANNUAL_DISCOUNT_RATE},
                       datediff('month', date_trunc('month', a.signup_date), r.month) / 12.0)) / count(distinct a.account_id)
            from main_marts.dim_accounts a
            join main_marts.fact_account_segment_history e on e.account_id = a.account_id and e.is_initial_segment
            join main_marts.fact_revenue_monthly r on r.account_id = a.account_id
            where e.segment = ? and r.month <= ?
              and datediff('month', date_trunc('month', a.signup_date), cast(? as date)) >= {HORIZON_MONTHS - 1}
              and datediff('month', date_trunc('month', a.signup_date), r.month) < {HORIZON_MONTHS}
            """, [seg, as_of_eff, as_of_eff]).fetchone()[0]
        rel = abs(module_value - sql) / sql if sql else 0.0
        worst_rel = max(worst_rel, rel)
        detail.append(f"{seg}: {len(sel)} accounts, ${module_value:,.2f} vs ${sql:,.2f}")
    return _check("oldest_cohort_margin_adjusted_revenue_ties_to_fact_revenue_monthly",
                  worst_rel <= _FLOAT_TOLERANCE and worst_km <= _FLOAT_TOLERANCE,
                  f"max relative difference {worst_rel:.2e}; Kaplan-Meier vs alive fraction max {worst_km:.2e}; " + "; ".join(detail))


def validation_cac_inputs_tie(frames: dict, cac: dict, con) -> list:
    """The spend allocation sums back to the spend, the new-account counts equal fact_marketing_spend's, won logos equal the entry accounts for Commercial and Enterprise, and the acquisition rep cost equals an independent SQL sum."""
    if cac.get("status") != "present":
        return []
    out = []
    t = cac["totals"]
    out.append(_check("marketing_allocation_sums_back_to_spend", abs(t["allocated_usd"] - t["spend_usd"]) <= _TOLERANCE_USD,
                      f"allocated ${t['allocated_usd']:,.2f} vs spend ${t['spend_usd']:,.2f}"))
    spend, acc = frames["spend"], frames["accounts"]
    first, last = int(spend["r_idx"].min()), int(spend["r_idx"].max())
    n = (acc[(acc["m0"] >= first) & (acc["m0"] <= last)].groupby(["channel", "m0"]).size().rename("n").reset_index()
         .rename(columns={"m0": "r_idx"}))
    j = spend.merge(n, on=["channel", "r_idx"], how="left").fillna({"n": 0})
    mismatch = int((j["new_accounts"] != j["n"]).sum())
    out.append(_check("new_accounts_by_channel_month_tie_to_fact_marketing_spend", mismatch == 0,
                      f"{mismatch} of {len(j)} channel-months differ"))
    wins = frames["wins"]
    wins_w = wins[(wins["r_idx"] >= first) & (wins["r_idx"] <= last)]
    diffs = []
    for seg in ("Commercial", "Enterprise"):
        a = int(((acc["entry_segment"] == seg) & (acc["m0"] >= first) & (acc["m0"] <= last)).sum())
        w = int((wins_w["segment"] == seg).sum())
        diffs.append(abs(a - w))
    out.append(_check("won_new_business_logos_equal_entry_accounts_commercial_enterprise", max(diffs) == 0,
                      f"max abs difference {max(diffs)} (Commercial, Enterprise)"))
    sql = con.execute(
        "select coalesce(sum(monthly_fully_loaded_cost_usd), 0) from main_marts.fact_rep_monthly_cost "
        "where month >= ? and month <= ? and rep_type in ('ISR', 'AE', 'SE')",
        [index_to_month_end(first).replace(day=1), index_to_month_end(last)]).fetchone()[0]
    mine = sum(v.get("rep_cost_usd", 0.0) for v in cac["segments"].values() if v.get("status") == "present")
    out.append(_check("acquisition_rep_cost_ties_to_fact_rep_monthly_cost", abs(sql - mine) <= _TOLERANCE_USD,
                      f"module ${mine:,.2f} vs SQL ${sql:,.2f}; AM roles excluded"))
    am = compute_am_cost_share(frames["rep_cost"], frames["segment_revenue"], spend)
    sql_am = con.execute(
        "select coalesce(sum(monthly_fully_loaded_cost_usd), 0) from main_marts.fact_rep_monthly_cost "
        "where month >= ? and month <= ? and rep_type in ('AM-Commercial', 'AM-Enterprise')",
        [index_to_month_end(first).replace(day=1), index_to_month_end(last)]).fetchone()[0]
    sql_rev = con.execute(
        "select coalesce(sum(mrr), 0) from main_marts.fact_revenue_monthly "
        "where month >= ? and month <= ? and segment in ('Commercial', 'Enterprise')",
        [index_to_month_end(first).replace(day=1), index_to_month_end(last)]).fetchone()[0]
    mine_am = sum(v["am_cost_usd"] for v in am["segments"].values())
    mine_rev = sum(v["segment_revenue_usd"] for v in am["segments"].values())
    out.append(_check("am_cost_share_inputs_tie_to_the_facts",
                      abs(sql_am - mine_am) <= _TOLERANCE_USD and abs(sql_rev - mine_rev) <= _TOLERANCE_USD,
                      f"AM cost ${mine_am:,.2f} vs SQL ${sql_am:,.2f}; Commercial and Enterprise revenue ${mine_rev:,.2f} vs SQL ${sql_rev:,.2f}"))
    return out


def validation_node_is_non_additive_overlay(reading: dict) -> dict:
    """The tree and the registry both keep the LTV node a non-additive overlay on Consumption payback with no children, and this module emits no children."""
    with open(_REGISTRY_PATH) as f:
        node = json.load(f)["metrics"][NODE_KEY]
    tree_path = os.path.join(os.path.dirname(__file__), "..", "docs", "acme-corp-gtm-metric-tree.md")
    with open(tree_path) as f:
        tree_line = next(l for l in f if l.startswith("**LTV by segment"))
    ok = (node["additive"] is False and node["children"] == [] and node["parent"] == "consumption_payback"
          and node["source_mart"] is None and "**non-additive**" in tree_line
          and reading["non_additive"] is True and "children" not in reading)
    return _check("ltv_node_stays_a_non_additive_overlay_with_no_children", ok,
                  f"registry additive={node['additive']}, children={node['children']}, parent={node['parent']}, "
                  f"source_mart={node['source_mart']}; tree marks it non-additive")


def validation_margin_constant_ties_to_dbt() -> dict:
    """GROSS_MARGIN equals the dbt var mart_efficiency reads, and mart_efficiency carries no margin literal."""
    with open(_DBT_PROJECT) as f:
        m = re.search(r"^\s*consumption_gross_margin:\s*([0-9.]+)", f.read(), re.M)
    sql_path = os.path.join(os.path.dirname(__file__), "..", "dbt", "models", "marts", "marts", "mart_efficiency.sql")
    with open(sql_path) as f:
        sql = f.read()
    uses_var = 'var("consumption_gross_margin")' in sql
    no_literal = "0.80" not in sql
    ok = bool(m) and float(m.group(1)) == GROSS_MARGIN and uses_var and no_literal
    return _check("gross_margin_constant_ties_to_the_dbt_var", ok,
                  f"dbt var {m.group(1) if m else None}, module {GROSS_MARGIN}, mart_efficiency reads the var: {uses_var}, "
                  f"no 0.80 literal: {no_literal}")


def validation_tree_constants() -> dict:
    """The horizon, discount rate and margin equal what the metric tree's LTV node states."""
    tree_path = os.path.join(os.path.dirname(__file__), "..", "docs", "acme-corp-gtm-metric-tree.md")
    with open(tree_path) as f:
        lines = f.read().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("**LTV by segment"))
    text = " ".join(lines[start:start + 3])      # the node's heading line and its definition paragraph
    ok = ("5-year horizon" in text and HORIZON_MONTHS == 60 and "10% annual discount rate" in text
          and ANNUAL_DISCOUNT_RATE == 0.10 and "~80% gross margin" in text and GROSS_MARGIN == 0.80)
    return _check("horizon_discount_rate_and_margin_equal_the_metric_tree", ok,
                  f"tree states a 5-year horizon, 10% annual discount rate and ~80% margin; module {HORIZON_MONTHS} months, "
                  f"{ANNUAL_DISCOUNT_RATE}, {GROSS_MARGIN}")


def validation_channel_not_claimed_as_retention_signal(reading: dict) -> dict:
    """Where the log-rank test finds no channel retention difference at 5%, every SMB channel row uses the segment-wide survival (identical LTV); where it does, the channel's own."""
    test = reading["channel_retention_tests"]["SMB"]
    cut = reading["smb_channel_cut"]
    if not test.get("available") or not cut:
        return _check("channel_retention_signal_not_overclaimed", True, "channel test unavailable at this date")
    seg_ltv = next(s for s in reading["segments"] if s["entry_segment"] == "SMB")["ltv"]["central_usd"]
    if test["significant_at_5pct"]:
        ok = all("own survival" in r["ltv_basis"] for r in cut)
    else:
        ok = all(abs(r["ltv_central_usd"] - seg_ltv) <= 0.01 and "no channel retention difference" in r["ltv_basis"] for r in cut) \
            and "no detectable difference in retention" in reading["channel_finding"]
    return _check("channel_retention_signal_not_overclaimed", ok,
                  f"log-rank p {test['p_value']:.3f} (SMB self_serve vs inbound_marketing): "
                  f"{'channels differ' if test['significant_at_5pct'] else 'no difference'}; LTV basis stated per channel row")


_PERTURB_TABLES = ("dim_accounts", "fact_account_segment_history", "fact_revenue_monthly",
                   "fact_marketing_spend", "fact_rep_monthly_cost", "fact_opportunities")


def validation_no_lookahead(t: date, con) -> dict:
    """Builds an in-memory copy of the marts in which everything after t is corrupted (later revenue scaled and
    churned accounts revived, later spend and rep cost inflated, later accounts re-channelled, later deal
    outcomes flipped) and checks the reading at t is identical to the reading on the untouched marts."""
    clean = run_ltv(t, con=con)
    mem = duckdb.connect(":memory:")
    try:
        mem.execute("create schema main_marts")
        for name in _PERTURB_TABLES:
            df = con.execute(f"select * from main_marts.{name}").df()
            mem.register("_src", df)
            mem.execute(f"create table main_marts.{name} as select * from _src")
            mem.unregister("_src")
        mem.execute("update main_marts.fact_revenue_monthly set mrr = mrr * 7, segment = 'Enterprise' where month > ?", [t])
        mem.execute(
            "insert into main_marts.fact_revenue_monthly "
            "select account_id, md5(account_id || 'revived'), "
            "cast(date_trunc('month', cast(? as date)) + interval 1 month as date), segment, 9999.0 "
            "from (select account_id, max(month) m, any_value(segment) segment from main_marts.fact_revenue_monthly "
            "      where month <= ? group by 1) where m < date_trunc('month', cast(? as date))", [t, t, t])
        mem.execute("update main_marts.dim_accounts set channel = 'inbound_marketing' where signup_date > ?", [t])
        mem.execute("update main_marts.fact_marketing_spend set spend = spend * 10, new_accounts = new_accounts + 5 where month > ?", [t])
        mem.execute("update main_marts.fact_rep_monthly_cost set monthly_fully_loaded_cost_usd = monthly_fully_loaded_cost_usd * 5 where month > ?", [t])
        mem.execute("update main_marts.fact_opportunities set is_won = not is_won where close_date > ?", [t])
        corrupted = run_ltv(t, con=mem)
    finally:
        mem.close()
    same = clean == corrupted
    return _check(f"no_lookahead_reading_unchanged_by_post_{t.isoformat()}_data", same,
                  "reading on marts with every post-cut fact corrupted is identical to the untouched reading"
                  if same else "post-cut data changed the reading")


def validation_backtest_fit_equals_direct_reading(frames: dict, as_of_eff: date, con) -> dict:
    """The backtest's fit (the full frames truncated to the origin) equals run_ltv computed directly at the origin date."""
    origin = index_to_month_end(_as_of_index(as_of_eff) - BACKTEST_LAG_MONTHS)
    direct = run_ltv(origin, con=con)
    worst = 0.0
    for seg in ENTRY_SEGMENTS:
        acc = frames["accounts"][frames["accounts"]["entry_segment"] == seg]
        rev = frames["revenue"][frames["revenue"]["entry_segment"] == seg]
        fit = fit_segment(acc, rev, _as_of_index(origin))
        d = next(s for s in direct["segments"] if s["entry_segment"] == seg)
        if fit["status"] == "present" and d["status"] == "present":
            worst = max(worst, abs(round(fit["ltv"]["central"], 2) - d["ltv"]["central_usd"]))
        elif (fit["status"] == "present") != (d["status"] == "present"):
            worst = float("inf")
    return _check("backtest_fit_on_truncated_frames_equals_a_direct_reading_at_the_origin", worst <= _TOLERANCE_USD,
                  f"origin {origin}: max abs LTV difference ${worst:.2f} across the three segments")


# --- Synthetic planted-hazard scenarios ------------------------------------------------------

def _synthetic_frames(n: int, hazard_by_age: np.ndarray, signup_span: int, mrr_fn, seed: int,
                      as_of_idx: int = 1200, recent_level: Optional[float] = None) -> tuple:
    """Grain: one synthetic entry segment of n accounts signed up uniformly over the last signup_span months,
    each leaving at an age drawn from hazard_by_age (last_age = the last age it pays) and paying mrr_fn(age)
    while present. Returns (accounts, revenue) frames shaped like the loaders'. Seeded."""
    rng = np.random.default_rng(seed)
    m0 = as_of_idx - rng.integers(0, signup_span, size=n)
    surv = np.cumprod(1.0 - hazard_by_age)                 # surv[k] = P(present at age k+1)
    u = rng.random(n)
    last_true = (surv[None, :] > u[:, None]).sum(axis=1)     # present at ages 0..last_true
    max_age = as_of_idx - m0
    last = np.minimum(last_true, max_age)
    ids = np.arange(n)
    rep = np.repeat(ids, last + 1)
    ages = np.concatenate([np.arange(k + 1) for k in last])
    acc = pd.DataFrame({"account_id": ids, "entry_segment": "SMB", "channel": "self_serve", "m0": m0})
    mrr = np.array([mrr_fn(a) for a in range(int(ages.max()) + 1)])[ages]
    if recent_level is not None:
        recent = (m0[rep] >= as_of_idx - (RECENT_VINTAGE_MONTHS - 1))
        mrr = np.where(recent, mrr * recent_level, mrr)
    rev = pd.DataFrame({"account_id": rep, "age": ages, "mrr": mrr, "mrr_in_entry": mrr})
    rev["m0"] = m0[rev["account_id"].to_numpy()]
    rev["r_idx"] = rev["m0"] + rev["age"]
    rev["entry_segment"], rev["channel"] = "SMB", "self_serve"
    return acc, rev


def _independent_ltv(survival, mrr_fn, margin: float, annual_rate: float) -> float:
    """The scenarios' expected LTV, written as an explicit loop with its own arithmetic: it deliberately does not call
    ltv_value, ltv_terms or discount_factors, so an error in those cannot cancel against itself."""
    total = 0.0
    for a in range(60):
        total += survival[a] * mrr_fn(a) * margin / math.pow(1.0 + annual_rate, a / 12.0)
    return total


def _closed_form(hazard_by_age, mrr_fn, margin: float = 0.80, annual_rate: float = 0.10) -> tuple:
    """(survival list S(0..60), expected LTV) for a planted per-age hazard, by explicit loops. The default margin and
    rate restate the tree's 0.80 and 10% as literals on purpose."""
    S = [1.0]
    for k in range(60):
        S.append(S[-1] * (1.0 - float(hazard_by_age[k])))
    return S, _independent_ltv(S, mrr_fn, margin, annual_rate)


def run_synthetic_scenarios() -> dict:
    """Known-answer scenarios through the same fit functions: a planted constant hazard recovered (observed and
    extrapolated), a hazard change inside the observed window tracked, a hazard change beyond it missed in the
    amount the constant-hazard rule predicts, an annual-renewal-cliff segment, MRR-path levels by vintage, the
    zero-churn identity, an under-sampled segment reported unavailable, a no-event tail whose band is wider than its
    centre, a non-default margin and discount rate, and an exact survival-times-growing-MRR sum. Every expected LTV is
    computed by explicit loops in _independent_ltv, never by the module's own LTV functions (tests mutate the
    discount exponent, the month-0 term, the margin and the S/m alignment and require a scenario to fail). Seeded;
    no data access."""
    H = 200
    results = []

    def rec(name, passed, detail):
        results.append({"name": name, "passed": bool(passed), "detail": detail})

    flat = lambda a: 100.0
    # A. constant hazard, fully observed
    hz = np.full(H, 0.015)
    acc, rev = _synthetic_frames(20000, hz, 71, flat, seed=_RANDOM_SEED)
    fit = fit_segment(acc, rev, 1200)
    S_true, ltv_true = _closed_form(hz, flat)
    gaps = [abs(fit["retention"]["central"][a] - S_true[a]) for a in (12, 24, 36, 48, 60)]
    rel = abs(fit["ltv"]["central"] - ltv_true) / ltv_true
    rec("constant_hazard_fully_observed", max(gaps) <= 0.015 and rel <= 0.01 and fit["retention"]["tail"] is None,
        f"max survival gap {max(gaps) * 100:.2f}pp (<= 1.5pp), LTV ${fit['ltv']['central']:,.0f} vs closed form ${ltv_true:,.0f} ({rel:.2%})")
    # B. constant hazard, tail extrapolated from 29 observed months
    hz = np.full(H, 0.02)
    acc, rev = _synthetic_frames(40000, hz, 30, flat, seed=_RANDOM_SEED + 1)
    fit = fit_segment(acc, rev, 1200)
    S_true, ltv_true = _closed_form(hz, flat)
    gap60 = abs(fit["retention"]["central"][60] - S_true[60])
    rel = abs(fit["ltv"]["central"] - ltv_true) / ltv_true
    rec("constant_hazard_tail_extrapolated", fit["retention"]["tail"] is not None and gap60 <= 0.02 and rel <= 0.025,
        f"observed through month {fit['retention']['observed_through']}; month-60 survival {fit['retention']['central'][60]:.3f} vs "
        f"{S_true[60]:.3f} (gap {gap60 * 100:.2f}pp); LTV ${fit['ltv']['central']:,.0f} vs ${ltv_true:,.0f} ({rel:.2%})")
    # C. hazard rises beyond the observed window: the rule cannot see it
    hz = np.full(H, 0.01)
    hz[36:] = 0.03
    acc, rev = _synthetic_frames(40000, hz, 30, flat, seed=_RANDOM_SEED + 2)
    fit = fit_segment(acc, rev, 1200)
    S_true, ltv_true = _closed_form(hz, flat)
    predicted_by_rule = 0.99 ** 60
    mod60 = fit["retention"]["central"][60]
    overstate = fit["ltv"]["central"] / ltv_true - 1.0
    rec("hazard_rise_beyond_window_is_missed_as_the_rule_predicts",
        abs(mod60 - predicted_by_rule) <= 0.03 and overstate > 0.03 and not (fit["retention"]["low"][60] <= S_true[60] <= fit["retention"]["high"][60]),
        f"module month-60 survival {mod60:.3f} (the 1%-a-month rule predicts {predicted_by_rule:.3f}), truth {S_true[60]:.3f}; "
        f"LTV overstated by {overstate:.1%}; the band ({fit['retention']['low'][60]:.3f} to {fit['retention']['high'][60]:.3f}) covers sampling error, not a regime change")
    # D. hazard change inside the observed window is tracked
    hz = np.full(H, 0.01)
    hz[12:] = 0.025
    acc, rev = _synthetic_frames(30000, hz, 71, flat, seed=_RANDOM_SEED + 3)
    fit = fit_segment(acc, rev, 1200)
    S_true, ltv_true = _closed_form(hz, flat)
    gaps = [abs(fit["retention"]["central"][a] - S_true[a]) for a in (12, 24, 36, 48, 60)]
    rel = abs(fit["ltv"]["central"] - ltv_true) / ltv_true
    rec("hazard_change_inside_observed_window_is_tracked", max(gaps) <= 0.02 and rel <= 0.015,
        f"max survival gap {max(gaps) * 100:.2f}pp (<= 2pp), LTV ${fit['ltv']['central']:,.0f} vs ${ltv_true:,.0f} ({rel:.2%})")
    # E. annual renewal cliffs (Commercial-like), observed through month 47
    hz = np.zeros(H)
    hz[[12, 24, 36, 48, 60]] = 0.08
    acc, rev = _synthetic_frames(3000, hz, 48, flat, seed=_RANDOM_SEED + 4)
    fit = fit_segment(acc, rev, 1200)
    S_true, ltv_true = _closed_form(hz, flat)
    gap60 = abs(fit["retention"]["central"][60] - S_true[60])
    rel = abs(fit["ltv"]["central"] - ltv_true) / ltv_true
    rec("annual_renewal_cliffs_survive_a_constant_monthly_tail", gap60 <= 0.03 and rel <= 0.03,
        f"observed through month {fit['retention']['observed_through']}; month-60 survival {fit['retention']['central'][60]:.3f} vs "
        f"{S_true[60]:.3f} (gap {gap60 * 100:.2f}pp); LTV ${fit['ltv']['central']:,.0f} vs ${ltv_true:,.0f} ({rel:.2%})")
    # F. MRR level by vintage: the recent window, the older window and the flat hold
    growth = lambda a: 100.0 * (1.0 + 0.04 * a)
    hz = np.full(H, 0.01)
    acc, rev = _synthetic_frames(20000, hz, 71, growth, seed=_RANDOM_SEED + 5, recent_level=1.5)
    paths = mrr_path_scenarios(acc, rev, 1200)
    rf, of = paths["recent_flat"], paths["older_flat"]
    r12, o12 = rf["values"][12], of["values"][12]
    flat_hold = rf["values"][59] == rf["values"][rf["direct_through"]]
    rec("mrr_path_uses_recent_vintages_and_holds_flat_past_the_last_observed_age",
        abs(r12 - 150.0 * 1.48) <= 1e-6 and abs(o12 - 100.0 * 1.48) <= 1e-6 and flat_hold and rf["direct_through"] < 59,
        f"month-12 recent ${r12:,.2f} (planted ${150 * 1.48:,.2f}), older ${o12:,.2f} (planted ${100 * 1.48:,.2f}); flat after month {rf['direct_through']}")
    # G. zero churn, constant MRR: the closed-form discounted sum
    hz = np.zeros(H)
    acc, rev = _synthetic_frames(200, hz, 71, flat, seed=_RANDOM_SEED + 6)
    fit = fit_segment(acc, rev, 1200)
    closed = _independent_ltv([1.0] * 60, flat, 0.80, 0.10)
    rec("zero_churn_constant_mrr_equals_the_closed_form_discounted_sum",
        fit["status"] == "present" and abs(fit["ltv"]["central"] - closed) <= 1e-6,
        f"module ${fit['ltv']['central']:,.4f} vs closed form ${closed:,.4f}")
    # H. too few accounts: unavailable with a reason, not a number
    acc, rev = _synthetic_frames(20, np.full(H, 0.02), 71, flat, seed=_RANDOM_SEED + 7)
    fit = fit_segment(acc, rev, 1200)
    rec("under_sampled_segment_is_unavailable_with_a_reason", fit["status"] == "unavailable" and bool(fit.get("reason")),
        f"status {fit['status']} ({fit.get('reason_code')})")
    # I. no events in the tail window: the central tail is flat, the band is not
    acc, rev = _synthetic_frames(100, np.zeros(H), 40, flat, seed=_RANDOM_SEED + 8)
    fit = fit_segment(acc, rev, 1200)
    ret = fit["retention"]
    rec("zero_event_tail_keeps_a_wide_low_band",
        fit["status"] == "present" and ret["tail"] is not None and ret["central"][60] == 1.0 and ret["low"][60] < 0.85,
        f"central month-60 survival {ret['central'][60]:.3f}, low band {ret['low'][60]:.3f}")
    # J. a margin and discount rate that are not the defaults, on sampled data
    hz = np.full(H, 0.015)
    acc, rev = _synthetic_frames(20000, hz, 71, flat, seed=_RANDOM_SEED + 9)
    fit = fit_segment(acc, rev, 1200, margin=0.55, annual_rate=0.17)
    _, ltv_true = _closed_form(hz, flat, margin=0.55, annual_rate=0.17)
    rel = abs(fit["ltv"]["central"] - ltv_true) / ltv_true
    rec("non_default_margin_and_discount_rate_are_applied", rel <= 0.015,
        f"margin 0.55, rate 17%: LTV ${fit['ltv']['central']:,.0f} vs independent closed form ${ltv_true:,.0f} ({rel:.2%})")
    # K. exact arithmetic with survival and MRR both varying by age (catches a one-age misalignment of S and m)
    hz = np.full(H, 0.015)
    S_exact, ltv_exact = _closed_form(hz, lambda a: 100.0 * (1.0 + 0.04 * a), margin=0.55, annual_rate=0.17)
    ret = {"central": np.array(S_exact), "low": np.array(S_exact), "high": np.array(S_exact), "observed_through": 60}
    paths = {"recent_flat": {"values": np.array([100.0 * (1.0 + 0.04 * a) for a in range(60)]), "direct_through": 59, "role": "central"}}
    got = evaluate_ltv(ret, paths, margin=0.55, annual_rate=0.17)["central"]
    rec("exact_survival_times_growing_mrr_with_non_default_margin_and_rate", abs(got - ltv_exact) <= 1e-9 * ltv_exact,
        f"module ${got:,.6f} vs independent loop ${ltv_exact:,.6f}")
    return {"n_scenarios": len(results), "n_passed": sum(1 for r in results if r["passed"]), "scenarios": results}


# --------------------------------------------------------------------------
# Build-time validation, persistence and the report
# --------------------------------------------------------------------------

def _min_at_risk_sensitivity(frames: dict, as_of_idx: int) -> dict:
    """LTV (central) under alternative minimum-at-risk gates -- how much the observed/extrapolated boundary matters."""
    out = {}
    for gate in (20, MIN_AT_RISK, 50):
        row = {}
        for seg in ENTRY_SEGMENTS:
            acc = frames["accounts"][frames["accounts"]["entry_segment"] == seg]
            rev = frames["revenue"][frames["revenue"]["entry_segment"] == seg]
            la, ma = account_state(acc, rev, as_of_idx)
            ret = project_retention(km_curve(la, ma), min_at_risk=gate)
            paths = mrr_path_scenarios(acc, rev, as_of_idx)
            if ret["status"] == "present" and "recent_flat" in paths:
                row[seg] = {"observed_through_month": ret["observed_through"],
                            "ltv_central_usd": ltv_value(ret["central"], paths["recent_flat"]["values"])}
            else:
                row[seg] = None
        out[str(gate)] = row
    return out


def _km_vs_pooled(frames: dict, as_of_idx: int) -> list:
    """Kaplan-Meier survival beside retention_cohorts' pooled still-present ratio at the standard marks (they agree at month 1 and differ after, by vintage mix)."""
    rows = []
    for seg in ENTRY_SEGMENTS:
        acc = frames["accounts"][frames["accounts"]["entry_segment"] == seg]
        la, ma = account_state(acc, frames["revenue"][frames["revenue"]["entry_segment"] == seg], as_of_idx)
        cur = km_curve(la, ma)
        for age in (12, 24, 36, 48, 60):
            n_pool = int(np.count_nonzero(ma >= age))
            if age <= cur["K"] and n_pool > 0:
                rows.append({"entry_segment": seg, "age": age, "km": float(cur["S"][age]),
                             "pooled_ratio": float(np.count_nonzero((la >= age) & (ma >= age)) / n_pool),
                             "n_at_risk_pooled": n_pool})
    return rows


def run_build_time_validation(as_of_date: date, log: bool = True, write_report: bool = True) -> dict:
    """End-to-end: the reading at as_of_date, the structural checks (reconciliation to retention_cohorts and to
    fact_revenue_monthly, CAC input tie-outs, a no-look-ahead perturbation at the checkpoint and at 2023-06-30, the
    non-additive-overlay and constant checks, the channel-signal check), the synthetic planted-hazard scenarios and
    the 36-month out-of-time backtest with the proposed drift rule. Logs scalar metrics to
    fact_model_performance_history via model_performance.log_performance and writes a dated JSON and Markdown
    report; the variable-width tables (curves, backtest rows, scenarios) live in the report."""
    as_of_eff = last_complete_month_end(as_of_date)
    as_of_idx = _as_of_index(as_of_eff)
    con = _connect()
    try:
        frames = load_frames(as_of_eff, con)
        reading = run_ltv(as_of_date, frames=frames)
        acc, rev = frames["accounts"], frames["revenue"]
        cac = compute_cac(acc, frames["spend"], frames["rep_cost"], frames["wins"])
        backtests = {seg: backtest_segment(acc[acc["entry_segment"] == seg], rev[rev["entry_segment"] == seg], as_of_idx)
                     for seg in ENTRY_SEGMENTS}
        ent_acc = acc[acc["entry_segment"] == "Enterprise"]
        la, ma = account_state(ent_acc, rev[rev["entry_segment"] == "Enterprise"], as_of_idx)
        ent_at_risk_36 = int(np.count_nonzero(ma >= 36))
        drift = drift_assessment(backtests, ent_at_risk_36)
        synthetic = run_synthetic_scenarios()
        sensitivity = _min_at_risk_sensitivity(frames, as_of_idx)
        km_vs_pooled = _km_vs_pooled(frames, as_of_idx)

        checks = [
            validation_data_integrity(frames),
            validation_counts_tie_to_retention_cohorts(frames, as_of_eff, con),
            validation_oldest_cohort_revenue_identity(frames, as_of_eff, con),
            *validation_cac_inputs_tie(frames, cac, con),
            validation_node_is_non_additive_overlay(reading),
            validation_margin_constant_ties_to_dbt(),
            validation_tree_constants(),
            validation_channel_not_claimed_as_retention_signal(reading),
            validation_backtest_fit_equals_direct_reading(frames, as_of_eff, con),
            validation_no_lookahead(as_of_eff, con),
            validation_no_lookahead(date(2023, 6, 30), con),
            _check("synthetic_known_answer_scenarios", synthetic["n_passed"] == synthetic["n_scenarios"],
                   f"{synthetic['n_passed']} of {synthetic['n_scenarios']} scenarios match their known answers"),
        ]
        ident_ok = all(r["realized_identity_max_abs_diff_usd"] <= 1e-6
                       for b in backtests.values() if b["status"] == "present" for r in b["ltv_rows"])
        checks.append(_check("backtest_realized_ltv_equals_survival_times_mrr_identity", ident_ok,
                             "on accounts with the horizon fully observed, realized discounted margin per account equals the "
                             "alive-fraction x mean-MRR sum (no censoring), for every backtest horizon"))
    finally:
        con.close()
    structural = [c for c in checks if c["kind"] == "structural"]
    structural_passed = sum(1 for c in structural if c["passed"])

    smb_bt = backtests["SMB"]
    smb_flag = drift["SMB"]["flag"]
    checks.append(_check(
        "backtest_smb_retention_within_the_proposed_drift_rule",
        smb_flag is False,
        ("SMB realized retention at months 48 and 60 within "
         f"{SMB_GAP_PP_LIMIT:g}pp of the projection and inside its band: max abs gap "
         f"{drift['SMB'].get('max_abs_gap_pp_months_48_60', 0):.2f} pp" if smb_flag is not None else drift["SMB"].get("reason")),
        kind="target"))
    smb_36 = next((r for r in smb_bt.get("ltv_rows", []) if r["horizon_months"] == 36), None)
    checks.append(_check(
        "backtest_smb_36_month_ltv_error_within_limit",
        bool(smb_36 and smb_36["error_pct"] is not None and abs(smb_36["error_pct"]) / 100.0 <= SMB_LTV_36M_ERROR_LIMIT),
        (f"projected 36-month discounted margin per account {_usd(smb_36['projected_usd'])} vs realized {_usd(smb_36['realized_usd'])} "
         f"({smb_36['error_pct']:+.1f}%; limit +/-{SMB_LTV_36M_ERROR_LIMIT:.0%}); retention-only error "
         f"{smb_36['retention_only_error_pct']:+.1f}%, MRR-only error {smb_36['mrr_only_error_pct']:+.1f}%" if smb_36 else "no SMB LTV backtest at this checkpoint"),
        kind="target"))
    smb_60 = next((r for r in smb_bt.get("ltv_rows", []) if r["horizon_months"] == 60), None)
    checks.append(_check(
        "backtest_smb_60_month_ltv_error_reported_without_a_limit", False,
        (f"projected 60-month discounted margin per account {_usd(smb_60['projected_usd'])} vs realized {_usd(smb_60['realized_usd'])} "
         f"({smb_60['error_pct']:+.1f}%, n = {smb_60['n_accounts']}); the horizon the headline uses; the error is the MRR path "
         f"(MRR-only {smb_60['mrr_only_error_pct']:+.1f}%, retention-only {smb_60['retention_only_error_pct']:+.1f}%); no limit is set"
         if smb_60 else "no SMB 60-month LTV backtest at this checkpoint"), kind="info"))
    com = backtests["Commercial"]
    checks.append(_check(
        "backtest_commercial_realized_inside_band_directional",
        bool(com.get("all_realized_in_band")),
        (f"Commercial, fit through month {com.get('fit_observed_through_month')} at the origin, "
         f"{len(com.get('retention_rows', []))} marks; max abs gap {com.get('max_abs_gap_pp', 0):.2f} pp; reported, gates nothing"
         if com.get("status") == "present" else com.get("reason", "unavailable")), kind="info"))
    checks.append(_check(
        "backtest_enterprise_not_backtestable", False,
        f"Enterprise: {ent_at_risk_36} accounts have reached month 36 (needs {ENTERPRISE_BACKTESTABLE_AT_RISK_MONTH_36}); "
        f"{backtests['Enterprise'].get('reason', 'fit unavailable at the origin')}", kind="info"))
    target_met = all(c["passed"] for c in checks if c["kind"] == "target")

    if log:
        for seg_r in reading["segments"]:
            if seg_r["status"] != "present":
                continue
            key = seg_r["entry_segment"].lower()
            L_ = seg_r["ltv"]
            log_performance(_MODEL_NAME, as_of_date, f"ltv_central_usd_{key}", L_["central_usd"])
            log_performance(_MODEL_NAME, as_of_date, f"ltv_low_usd_{key}", L_["low_usd"])
            log_performance(_MODEL_NAME, as_of_date, f"ltv_high_usd_{key}", L_["high_usd"])
            log_performance(_MODEL_NAME, as_of_date, f"ltv_observed_share_{key}", L_["observed_share"])
            log_performance(_MODEL_NAME, as_of_date, f"retention_month36_{key}", seg_r["retention"]["checkpoints"]["36"]["central"])
            log_performance(_MODEL_NAME, as_of_date, f"retention_month60_{key}", seg_r["retention"]["checkpoints"]["60"]["central"])
            log_performance(_MODEL_NAME, as_of_date, f"churn_events_{key}", float(seg_r["n_churned"]))
            if seg_r["retention"]["tail"]:
                log_performance(_MODEL_NAME, as_of_date, f"tail_monthly_hazard_{key}", seg_r["retention"]["tail"]["monthly_hazard"])
            if seg_r.get("cac"):
                log_performance(_MODEL_NAME, as_of_date, f"cac_marketing_only_usd_{key}", seg_r["cac"]["marketing_only_cac_usd"])
                if seg_r["cac"].get("rep_loaded_cac_usd") is not None:
                    log_performance(_MODEL_NAME, as_of_date, f"cac_rep_loaded_usd_{key}", seg_r["cac"]["rep_loaded_cac_usd"])
            if seg_r["ltv_to_cac"].get("rep_loaded"):
                rl = seg_r["ltv_to_cac"]["rep_loaded"]
                log_performance(_MODEL_NAME, as_of_date, f"ltv_to_cac_rep_loaded_{key}", rl["central"])
                # the ratio counting only revenue earned inside the entry segment (Enterprise has no move-up, so equal)
                log_performance(_MODEL_NAME, as_of_date, f"ltv_to_cac_entry_only_{key}",
                                rl.get("entry_segment_revenue_only", rl["central"]))
        t = reading["channel_retention_tests"]["SMB"]
        if t.get("available"):
            log_performance(_MODEL_NAME, as_of_date, "smb_channel_log_rank_p_value", t["p_value"])
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_total", float(len(structural)))
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_passed", float(structural_passed))
        log_performance(_MODEL_NAME, as_of_date, "synthetic_scenarios_total", float(synthetic["n_scenarios"]))
        log_performance(_MODEL_NAME, as_of_date, "synthetic_scenarios_passed", float(synthetic["n_passed"]))
        if smb_bt["status"] == "present":
            for r in smb_bt["retention_rows"]:
                log_performance(_MODEL_NAME, as_of_date, f"backtest_retention_gap_pp_smb_m{r['age']}", r["gap_pp"])
            if smb_bt["max_abs_gap_pp"] is not None:
                log_performance(_MODEL_NAME, as_of_date, "backtest_retention_max_abs_gap_pp_smb", smb_bt["max_abs_gap_pp"])
                log_performance(_MODEL_NAME, as_of_date, "backtest_retention_realized_in_band_smb", 1.0 if smb_bt["all_realized_in_band"] else 0.0)
            for r in smb_bt["ltv_rows"]:
                log_performance(_MODEL_NAME, as_of_date, f"backtest_ltv_error_pct_smb_{r['horizon_months']}m", r["error_pct"])
        if com["status"] == "present" and com["retention_rows"]:
            log_performance(_MODEL_NAME, as_of_date, "backtest_retention_max_abs_gap_pp_commercial", com["max_abs_gap_pp"])
            log_performance(_MODEL_NAME, as_of_date, "backtest_retention_realized_in_band_commercial", 1.0 if com["all_realized_in_band"] else 0.0)
        log_performance(_MODEL_NAME, as_of_date, "enterprise_accounts_at_risk_month_36", float(ent_at_risk_36))

    result = {
        "as_of_date": as_of_date.isoformat(), "data_through": as_of_eff.isoformat(),
        "reading": reading,
        "checks": checks, "checks_total": len(structural), "checks_passed": structural_passed,
        "target_met": target_met,
        "synthetic": synthetic,
        "backtest": backtests,
        "drift_assessment": drift,
        "drift_rule": {
            "status": "proposed, not yet confirmed", "smb_gap_pp_limit": SMB_GAP_PP_LIMIT,
            "smb_ltv_36m_error_limit": SMB_LTV_36M_ERROR_LIMIT,
            "enterprise_backtestable_at_risk_month_36": ENTERPRISE_BACKTESTABLE_AT_RISK_MONTH_36,
        },
        "min_at_risk_sensitivity": sensitivity,
        "km_vs_pooled_ratio": km_vs_pooled,
    }
    if write_report:
        _write_report(as_of_date, result)
    return result


def _write_report(as_of_date: date, result: dict) -> None:
    """Writes the dated JSON and Markdown report for one checkpoint to analytics/outputs/."""
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    json_path = os.path.join(_OUTPUT_DIR, f"ltv_by_segment_{as_of_date.isoformat()}.json")
    with open(json_path, "w") as f:
        json.dump(_jsonable(_rounded(result)), f, indent=2)
    md_path = os.path.join(_OUTPUT_DIR, f"ltv_by_segment_{as_of_date.isoformat()}.md")
    with open(md_path, "w") as f:
        f.write(render_markdown(result))


def _rounded(obj, digits=8):
    """Rounds every float in a nested structure so the committed report carries no last-digit platform noise."""
    if isinstance(obj, dict):
        return {k: _rounded(v, digits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_rounded(v, digits) for v in obj]
    if isinstance(obj, (float, np.floating)) and np.isfinite(obj):
        return round(float(obj), digits)
    return obj


def render_markdown(result: dict) -> str:
    """Renders one checkpoint report (reading, CAC and LTV:CAC, SMB channel cut, backtest, checks, caveats) as Markdown; no data access."""
    r = result["reading"]
    lines = [f"# LTV by entry segment -- as of {r['as_of_date']} (data through {r['data_through']})", "",
             f"*{r['label']}.*", "", r["headline"], "",
             "## Lifetime value per new account (60 months, 10% a year, 80% margin)", "",
             "| Entry segment | Evidence | LTV central | Range | Observed share | Retention at month 60 | Projection starts after month |",
             "|---|---|---|---|---|---|---|"]
    for s in r["segments"]:
        if s["status"] != "present":
            lines.append(f"| {s['entry_segment']} | unavailable | | | | | |")
            continue
        m60 = s["retention"]["checkpoints"]["60"]
        lines.append(f"| {s['entry_segment']} | {s['evidence_grade']} | {_usd(s['ltv']['central_usd'])} | "
                     f"{_usd(s['ltv']['low_usd'])} to {_usd(s['ltv']['high_usd'])} | {_pct(s['ltv']['observed_share'], 0)} | "
                     f"{_pct(m60['central'])} ({_pct(m60['low'])} to {_pct(m60['high'])}, {m60['kind']}) | "
                     f"{s['ltv']['observed_through_month']} |")
    lines += ["", "## CAC and LTV:CAC", ""]
    if r["cac_status"] != "present":
        lines += [f"CAC unavailable: {r['cac_reason']}.", ""]
    else:
        lines += [f"CAC window {r['cac_window']['window_first_month']} to {r['cac_window']['window_last_month']} "
                  f"({r['cac_window']['window_months']} months).", "",
                  "| Entry segment | New accounts | Marketing-only CAC | Rep cost per logo | Rep-loaded CAC | LTV:CAC marketing-only | LTV:CAC rep-loaded (range) | How to read |",
                  "|---|---|---|---|---|---|---|---|"]
        for s in r["segments"]:
            if s["status"] != "present" or not s.get("cac"):
                continue
            c, q = s["cac"], s["ltv_to_cac"]
            mk, rl = q.get("marketing_only"), q.get("rep_loaded")
            has_reps = bool(c["rep_acquisition_roles"])
            mk_cell = (f"{_x(mk['central'])} " + ("(decision-grade)" if q["marketing_only_decision_grade"] else "(not decision-grade)")) if mk else "n/a"
            if not rl:
                rl_cell = "n/a"
            elif not has_reps:
                rl_cell = "same figure: no reps in this segment"
            else:
                rl_cell = (f"{_x(rl['central'])} ({_x(rl['low'])} to {_x(rl['high'])}) "
                           + ("(decision-grade)" if q["rep_loaded_decision_grade"] else "(not decision-grade)"))
            lines.append(f"| {s['entry_segment']} | {c['new_accounts']} | {_usd(c['marketing_only_cac_usd'])} | "
                         f"{_usd(c['rep_cost_per_logo_usd']) if has_reps else 'none (no reps)'} | {_usd(c['rep_loaded_cac_usd'])} | "
                         f"{mk_cell} | {rl_cell} | {q['how_to_read']} |")
        lines += ["", "Decision-grade rule: " + DECISION_GRADE_RULE, "",
                  "## Revenue earned after an account moves up a segment", "",
                  "| Entry segment | Share of LTV after the move | Accounts moved up | LTV:CAC rep-loaded | Inside the entry segment only | If account-management cost were netted |",
                  "|---|---|---|---|---|---|"]
        for s in r["segments"]:
            g = s.get("graduation") if s["status"] == "present" else None
            if not g:
                continue
            rl = s["ltv_to_cac"].get("rep_loaded") or {}
            lines.append(f"| {s['entry_segment']} | {_pct(g['share_of_ltv_after_move'], 0)} | {g['accounts_moved_up']} of {g['accounts']} "
                         f"({_pct(g['share_of_accounts_moved_up'], 1)}) | {_x(rl.get('central'))} | {_x(rl.get('entry_segment_revenue_only'))} | "
                         f"{_x(rl.get('if_am_cost_netted'))} |")
        am = r.get("am_cost_context") or {}
        if am.get("status") == "present":
            lines += ["", "Account-management cost over the CAC window: " + "; ".join(
                f"{k} {_usd(v['am_cost_usd'])} of {_usd(v['segment_revenue_usd'])} segment revenue ({_pct(v['share_of_segment_revenue'], 2)})"
                for k, v in am["segments"].items()) + ". That is too small to explain the gap between the two ratios; the gap is "
                "how the upside of the few accounts that move up is credited.", ""]
    lines += ["## SMB by acquisition channel", "", r["channel_finding"], "",
              "| Age (months) | Accounts self_serve / inbound | Mean MRR self_serve / inbound | Median MRR self_serve / inbound | Mann-Whitney p |",
              "|---|---|---|---|---|"] + [
              f"| {t['age']} | {t['n'][0]} / {t['n'][1]} | {_usd(t['mean_mrr_usd'][0])} / {_usd(t['mean_mrr_usd'][1])} | "
              f"{_usd(t['median_mrr_usd'][0])} / {_usd(t['median_mrr_usd'][1])} | {t['p_value']:.2f} |"
              for t in r["channel_mrr_tests"]["SMB"]["rows"]] + ["",
              "| Channel | Accounts | Churn events | LTV (segment-wide) | LTV with channel's own survival | Marketing-only CAC | LTV:CAC |",
              "|---|---|---|---|---|---|---|"]
    for c in r["smb_channel_cut"]:
        lines.append(f"| {c['channel']} | {c['n_accounts']} | {c['churn_events']} | {_usd(c['ltv_central_usd'])} | "
                     f"{_usd(c.get('own_survival_ltv_usd'))} | {_usd(c.get('marketing_only_cac_usd'))} | "
                     f"{_x(c.get('ltv_to_cac_marketing_only'))} |")
    lines += ["", "Not shown: " + "; ".join(f"{x['entry_segment']}{' ' + x['channel'] if 'channel' in x else ''} ({x['reason']})"
                                           for x in r["channel_cells_not_shown"]) + ".", "",
              "## Backtest (fit through the origin, compared with what happened)", ""]
    for seg, b in result["backtest"].items():
        if b["status"] != "present":
            lines += [f"- **{seg}**: unavailable at origin {b['origin']} ({b['reason']})."]
            continue
        lines += [f"- **{seg}** (origin {b['origin']}, fit observed through month {b['fit_observed_through_month']}):", ""]
        lines += ["  | Month | Projected | Band | Realized (Kaplan-Meier) | Pooled ratio | Gap (pp) | Inside band |", "  |---|---|---|---|---|---|---|"]
        for x in b["retention_rows"]:
            lines.append(f"  | {x['age']} | {_pct(x['projected'])} | {_pct(x['band_low'])} to {_pct(x['band_high'])} | "
                         f"{_pct(x['realized_km'])} | {_pct(x['realized_pooled_ratio'])} | {x['gap_pp']:+.1f} | {'yes' if x['in_band'] else 'no'} |")
        lines.append("")
        for x in b["ltv_rows"]:
            lines.append(f"  - {x['horizon_months']}-month LTV on {x['n_accounts']} accounts: projected {_usd(x['projected_usd'])} vs realized "
                         f"{_usd(x['realized_usd'])} ({x['error_pct']:+.1f}%); retention-only {x['retention_only_error_pct']:+.1f}%, MRR-only {x['mrr_only_error_pct']:+.1f}%.")
        lines.append("")
    lines += ["", "## Drift assessment (proposed rule, one checkpoint)", ""]
    for seg, d in result["drift_assessment"].items():
        lines.append(f"- {seg}: {json.dumps(_jsonable(_rounded(d, 2)))}")
    lines += ["", "## Checks", ""]
    for c in result["checks"]:
        lines.append(f"- [{_mark(c)}] {c['name']}: {c['detail']}")
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in r["caveats"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    for checkpoint in (date(2025, 6, 30), date(2025, 12, 31)):
        out = run_build_time_validation(checkpoint)
        rd = out["reading"]
        print(f"=== LTV by entry segment, as of {checkpoint} (data through {rd['data_through']}) ===")
        print(" ", rd["headline"])
        for s in rd["segments"]:
            if s["status"] != "present":
                print(f"  {s['entry_segment']}: unavailable ({s['reason']})")
                continue
            print(f"  {s['entry_segment']}: {s['display']['ltv']}")
            print(f"    {s['display']['retention_month_60']}; {s['display']['projection_share']}")
            q = s["ltv_to_cac"]
            if q.get("rep_loaded"):
                print(f"    LTV:CAC rep-loaded {_x(q['rep_loaded']['central'])} ({_x(q['rep_loaded']['low'])} to "
                      f"{_x(q['rep_loaded']['high'])}); marketing-only {_x(q['marketing_only']['central'])} (not decision-grade)")
        for c in rd["smb_channel_cut"]:
            print(f"  SMB {c['channel']}: LTV {_usd(c['ltv_central_usd'])}, CAC {_usd(c.get('marketing_only_cac_usd'))}, "
                  f"LTV:CAC {_x(c.get('ltv_to_cac_marketing_only'))}")
        print(" ", rd["channel_finding"])
        for seg, b in out["backtest"].items():
            if b["status"] != "present":
                print(f"  Backtest {seg}: unavailable ({b['reason']})")
                continue
            print(f"  Backtest {seg} (origin {b['origin']}): max abs gap {b['max_abs_gap_pp']} pp, all inside band {b['all_realized_in_band']}")
            for x in b["retention_rows"]:
                print(f"    month {x['age']}: projected {x['projected']:.3f} realized {x['realized_km']:.3f} gap {x['gap_pp']:+.2f}pp")
            for x in b["ltv_rows"]:
                print(f"    {x['horizon_months']}-month LTV: projected {_usd(x['projected_usd'])} vs realized {_usd(x['realized_usd'])} ({x['error_pct']:+.1f}%)")
        for seg, d in out["drift_assessment"].items():
            print(f"  Drift {seg}: {d}")
        for c in out["checks"]:
            print(f"  [{_mark(c)}] {c['name']}: {c['detail']}")
        print(f"  {out['checks_passed']} of {out['checks_total']} structural checks pass; backtest targets met: {out['target_met']}\n")
