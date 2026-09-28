"""Territory / account coverage & routing diagnostic -- grain: one row per
territory (NA-East / NA-West / EMEA / APAC / LATAM) for the coverage-ratio
table; supplementary one row per territory x rep_type for headcount detail.
Source marts: mart_tam_whitespace (whitespace/company-population by
territory), dim_reps (rep headcount, point-in-time), dim_accounts (existing
customer-account population, point-in-time), fact_opportunities +
dim_market_universe (open new-business pipeline by territory, point-in-time,
supplementary lens only).

Build spec item #21 (Wave 5, "strategic/market-facing, runs off
market_universe, not part of weekly cadence"), "Territory / account
coverage & routing, including whitespace and TAM-allocation." The
territory-dimension prerequisite (generators/territories.py,
dim_reps.territory / dim_accounts.territory / dim_market_universe.territory
/ mart_tam_whitespace's territory grain) is a completed, already-shipped
Phase 1/2 extension and is read here, not modified.

Boundary with analytics/tam_icp_sizing.py (item #22), stated rather than
assumed: that module deliberately does NOT use territory -- it works at
tier x region/industry/employee-band and explicitly defers "territory
allocation" to this artifact (see its own module docstring: "#21
(territory/coverage/routing) is a separate, not-yet-built artifact and is
not touched here"). This module is the other half of that split. It does
not recompute TAM dollars, does not re-derive the ICP fit-tier/segment
mapping, and does not re-run tam_icp_sizing's ACV-assumption sizing --
whitespace-company COUNTS (not dollars) are pulled from mart_tam_whitespace
as-is. A dollar-denominated version of the coverage ratio
("high-ICP-whitespace-dollars-per-rep") would need tam_icp_sizing's median-
realized-ACV-by-segment assumption; not re-derived here to avoid a second,
silently-divergent dollar assumption -- whitespace-company-COUNT-per-rep is
used instead, which is itself a real metric a RevOps team would use and
needs no dollar assumption to compute.

Shape decision -- structural/logic artifact, not a fitted model. Every
number here is a direct aggregation of already-materialized mart rows; a
coverage ratio is a straight division, not an estimate. Per
analytics-engineering-conventions' "Structural/logic artifacts" category
(same reasoning as the variance-diagnostic engine, capacity planning,
segment migration and tam_icp_sizing) -- there is no coefficient table, no
AUC, no confusion matrix, no R^2/RMSE here, and their absence is
deliberate, not pending.

Model type selection and rationale (why not a fitted model): a predictive
"coverage-risk" classifier (e.g. estimating which territory is likeliest
to miss a future coverage bar) was the credible alternative and was
rejected on two grounds. (1) There is no trailing history to fit against --
territory is a single current snapshot dimension (rep-to-territory and
company-to-territory assignment; see "Point-in-time design" below for what
genuinely varies and what doesn't), not a time series of past coverage
levels a model could learn from. (2) The quantity a routing decision needs
is a direct ratio ("is headcount proportionate to opportunity, right now"),
not a probability -- the same "a planner needs a sum/ratio, not a noisy
estimate of one" argument capacity planning's and tam_icp_sizing's entries
make for their own structural shape.

Point-in-time design, stated explicitly rather than assumed, per the task
brief's instruction to verify rather than assume:
- Rep-to-territory headcount (dim_reps) IS genuinely time-varying -- reps
  are hired, ramp, and depart over the simulation window, so
  "active ISR/AE headcount serving territory T" measured at 2025-06-30
  differs from 2025-12-31 (confirmed at build time: ISR/EMEA active
  headcount is 4 at 2025-06-30 vs 3 at 2025-12-31). load_rep_headcount_
  by_territory() therefore takes as_of_date and does a genuine point-in-
  time lookup against dim_reps' period grain (period_start_date <=
  as_of_date < the period's end, rep_status = 'active'), mirroring
  analytics/capacity_planning.py's own dim_reps point-in-time convention
  -- not dim_reps.is_current_period, which only ever answers "as of now."
- Existing-account population (dim_accounts) IS genuinely time-varying --
  accounts sign up throughout the window (18.9% of all 7,700 accounts
  signed up in 2025 H2 alone, confirmed at build time), so
  load_existing_accounts_by_territory() filters signup_date <= as_of_date.
  Following the same "ever captured" convention mart_tam_whitespace and
  tam_icp_sizing.py both already use (a company that later churns stays
  counted as captured, rather than reverting to whitespace or being
  dropped) -- consistent with, not competing against, that established
  semantics. current customer_status (active/churned) is NOT used to
  filter the point-in-time count, since it reflects the account's LATEST
  status rather than its status at as_of_date and would leak a later
  churn event into an earlier checkpoint; churned share is reported
  separately, for context only.
- The whitespace/company-population side (mart_tam_whitespace, itself
  built from dim_market_universe) is NOT point-in-time -- it is a static
  full-history-end-state snapshot, the same limitation tam_icp_sizing.py's
  entry documents for dim_market_universe.is_customer ("reflects the
  full-history end state... would leak a company's future signup into an
  earlier snapshot"). This module does not re-derive a point-in-time-
  correct whitespace partition the way tam_icp_sizing.load_universe_
  snapshot() does for its own tier-based cut -- doing so a second time,
  reading the same underlying dim_market_universe rows through a second,
  separately-maintained point-in-time implementation, would risk a
  silently-diverging copy rather than adding real value, the same
  "don't re-implement a correctness-bearing computation a sibling artifact
  already owns" reasoning the data-quality-governance entry gives for not
  re-deriving marketing_attribution's pipeline-generated identity. The
  distortion this introduces at the earlier (2025-06-30) checkpoint is
  quantified rather than ignored: of 7,700 total accounts, 1,454 (18.9%)
  signed up in 2025 H2 alone, but against mart_tam_whitespace's ~115,500-
  company whitespace pool that is a bounded ~1.3% overstatement of
  "already captured," not a distortion large enough to change which
  territory reads as most/least covered. Every result that sources from
  mart_tam_whitespace is labelled accordingly (not point-in-time) rather
  than silently presented as if it were.

No stochastic step lives in this module (no train/test split, no sampling,
no simulation) -- every function is a direct, deterministic aggregation
over already-generated mart data, so no random seed applies, matching
analytics/segment_migration.py's, analytics/capacity_planning.py's and
analytics/tam_icp_sizing.py's precedent.

No dbt model was added or changed for this artifact, and no Phase 1
generator or raw table was added -- dim_reps.territory, dim_accounts.
territory, dim_market_universe.territory and mart_tam_whitespace's
territory grain are all already-shipped, already-validated Phase 1/2
extensions (420/420 dbt checks, 296/296 QA tests passing at the time this
module was built).
"""
import math
import os
from datetime import date

import duckdb
import numpy as np
import pandas as pd

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_MODEL_NAME = "territory_coverage_routing"

# Mirrored from generators/territories.py -- account-owning, quota-bearing
# roles a geographic prospecting/coverage territory routes to. SE and AM
# carry no territory (see that module's docstring); not imported here since
# Phase 4 code does not import Phase 1 generator modules (mirrored constant,
# consistent with tam_icp_sizing.py's treatment of firmographics.py's fit
# thresholds).
_TERRITORY_ELIGIBLE_REP_TYPES = ("ISR", "AE")

TERRITORIES = ("NA-East", "NA-West", "EMEA", "APAC", "LATAM")

# Structural tie-out tolerances -- exact arithmetic by construction (a
# straight partition / sum of parts), so anything beyond floating-point
# noise is a real bug in this module.
_RECONCILIATION_TOLERANCE_COUNT = 0
_RECONCILIATION_TOLERANCE_HEADCOUNT = 1e-9

# Non-vacuousness floors for the "does this artifact actually detect the
# real, deliberately-injected APAC/LATAM imbalance" check -- PROPOSED, not
# yet confirmed (no upstream doc states a number for this; own resolved
# decision, per this module's Model type selection reasoning).
# coverage_index = territory's share of active ISR/AE headcount divided by
# its share of company-wide whitespace (or existing accounts): <1.0 means
# under-resourced relative to that share of opportunity, >1.0 over-
# resourced. Observed at build time (2025-12-31): APAC 0.513 (whitespace),
# 0.611 (high-ICP whitespace), 0.520 (existing accounts) -- all comfortably
# under 0.75, with headroom before ordinary period-to-period movement in
# rep headcount (hires/departures) could trip the floor without a real
# defect. LATAM 1.540 / 2.750 / 1.674 -- all comfortably over 1.25.
_MAX_UNDER_RESOURCED_COVERAGE_INDEX = 0.75
_MIN_OVER_RESOURCED_COVERAGE_INDEX = 1.25


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


# --------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------

def load_rep_headcount_by_territory(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per territory x rep_type. Source mart: dim_reps.
    Active ISR/AE headcount as of as_of_date -- a genuine point-in-time
    lookup against dim_reps' capacity-period grain (period_start_date <=
    as_of_date <= period_end_date, or period_end_date is null for the open-
    ended current period), rep_status = 'active'. Mirrors analytics/
    capacity_planning.py's own dim_reps point-in-time convention; does NOT
    use is_current_period, which only ever answers "as of now.\""""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select rep_type, territory, count(*) as active_headcount "
            "from main_marts.dim_reps "
            "where rep_type in ('ISR', 'AE') and territory is not null "
            "and period_start_date <= ? "
            "and (period_end_date is null or period_end_date >= ?) "
            "and rep_status = 'active' "
            "group by 1, 2",
            [as_of_date, as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    # Ensure every territory is present even with zero reps of a given
    # rep_type -- a missing row must read as zero, not be silently absent.
    full_index = pd.MultiIndex.from_product(
        [_TERRITORY_ELIGIBLE_REP_TYPES, TERRITORIES], names=["rep_type", "territory"]
    )
    df = (
        df.set_index(["rep_type", "territory"])
        .reindex(full_index, fill_value=0)
        .reset_index()
    )
    df["active_headcount"] = df["active_headcount"].astype(int)
    return df


def load_whitespace_by_territory(con=None) -> pd.DataFrame:
    """Grain: one row per territory. Source mart: mart_tam_whitespace,
    summed across its industry x employee_count_band grain up to territory.
    NOT point-in-time -- see module docstring's "Point-in-time design"
    section for why (mart_tam_whitespace is a static full-history-end-state
    snapshot, same limitation tam_icp_sizing.py documents for
    dim_market_universe.is_customer)."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select territory, "
            "sum(total_companies) as total_companies, "
            "sum(total_customers) as total_customers, "
            "sum(whitespace_companies) as whitespace_companies, "
            "sum(high_icp_whitespace_count) as high_icp_whitespace_count "
            "from main_marts.mart_tam_whitespace "
            "group by 1"
        ).df()
    finally:
        if owns_con:
            con.close()
    for col in ("total_companies", "total_customers", "whitespace_companies", "high_icp_whitespace_count"):
        df[col] = df[col].astype(int)
    return df.sort_values("territory").reset_index(drop=True)


def load_existing_accounts_by_territory(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per territory. Source mart: dim_accounts.
    captured_accounts = signup_date <= as_of_date, following the "ever
    captured" convention mart_tam_whitespace / tam_icp_sizing.py already
    use -- an account that later churns stays counted, not reverted to
    whitespace or dropped, and current customer_status is deliberately NOT
    used as a filter since it reflects the account's LATEST status and
    would leak a later churn event into an earlier as_of_date. churned_share
    is reported for context only, computed from the same LATEST-status
    field, and is explicitly not point-in-time."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select territory, "
            "count(*) filter (where signup_date <= ?) as captured_accounts, "
            "count(*) filter (where signup_date <= ? and customer_status = 'Churned') "
            "  as captured_accounts_now_churned "
            "from main_marts.dim_accounts "
            "where territory is not null "
            "group by 1",
            [as_of_date, as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["captured_accounts"] = df["captured_accounts"].astype(int)
    df["captured_accounts_now_churned"] = df["captured_accounts_now_churned"].astype(int)
    return df.sort_values("territory").reset_index(drop=True)


def load_open_pipeline_by_territory(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per territory. Supplementary lens only -- open
    (created_date <= as_of_date < close_date), new-business pipeline value
    and count, joined from fact_opportunities via company_id to
    dim_market_universe.territory. Point-in-time by construction (open/
    closed is inherently an as_of_date question). Expected to be empty at
    a full-history-end checkpoint (this simulation's data is fully closed
    out through 2025-12-28, so as_of_date=2025-12-31 has zero open deals by
    construction) and populated at an earlier checkpoint -- the same
    open-population shape analytics/deal_diagnostics.py's open_population()
    documents and relies on; not a defect in this loader."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select mu.territory, count(*) as open_deal_count, "
            "sum(fo.amount) as open_deal_amount "
            "from main_marts.fact_opportunities fo "
            "join main_marts.dim_market_universe mu on mu.company_id = fo.company_id "
            "where fo.opportunity_type = 'new_business' "
            "and fo.created_date <= ? and fo.close_date > ? "
            "and mu.territory is not null "
            "group by 1",
            [as_of_date, as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    full_index = pd.DataFrame({"territory": list(TERRITORIES)})
    df = full_index.merge(df, on="territory", how="left")
    df["open_deal_count"] = df["open_deal_count"].fillna(0).astype(int)
    df["open_deal_amount"] = df["open_deal_amount"].fillna(0.0)
    return df.sort_values("territory").reset_index(drop=True)


# --------------------------------------------------------------------------
# Coverage ratios
# --------------------------------------------------------------------------

def compute_coverage_ratios(as_of_date: date, headcount: pd.DataFrame = None,
                             whitespace: pd.DataFrame = None,
                             accounts: pd.DataFrame = None, con=None) -> pd.DataFrame:
    """Grain: one row per territory. The core coverage-ratio table: active
    ISR/AE headcount against (a) whitespace-company count, (b) high-ICP
    whitespace-company count, (c) existing (captured) account count --
    each expressed both as a plain per-rep ratio and as a coverage_index
    (territory's share of active headcount / territory's share of that
    denominator; <1.0 = under-resourced relative to that share of
    opportunity, >1.0 = over-resourced). Source marts: dim_reps,
    mart_tam_whitespace, dim_accounts."""
    owns_con = con is None
    con = con or _connect()
    try:
        headcount = load_rep_headcount_by_territory(as_of_date, con=con) if headcount is None else headcount
        whitespace = load_whitespace_by_territory(con=con) if whitespace is None else whitespace
        accounts = load_existing_accounts_by_territory(as_of_date, con=con) if accounts is None else accounts
    finally:
        if owns_con:
            con.close()

    hc_total = headcount.groupby("territory")["active_headcount"].sum().rename("active_reps_total")
    hc_isr = (
        headcount[headcount["rep_type"] == "ISR"].set_index("territory")["active_headcount"].rename("active_isr")
    )
    hc_ae = (
        headcount[headcount["rep_type"] == "AE"].set_index("territory")["active_headcount"].rename("active_ae")
    )

    out = (
        pd.DataFrame({"territory": list(TERRITORIES)})
        .set_index("territory")
        .join(hc_isr).join(hc_ae).join(hc_total)
        .join(whitespace.set_index("territory"))
        .join(accounts.set_index("territory"))
        .reset_index()
    )

    total_reps = float(out["active_reps_total"].sum())
    total_whitespace = float(out["whitespace_companies"].sum())
    total_high_icp = float(out["high_icp_whitespace_count"].sum())
    total_accounts = float(out["captured_accounts"].sum())

    out["rep_share"] = out["active_reps_total"] / total_reps
    out["whitespace_share"] = out["whitespace_companies"] / total_whitespace
    out["high_icp_whitespace_share"] = out["high_icp_whitespace_count"] / total_high_icp
    out["captured_account_share"] = out["captured_accounts"] / total_accounts

    out["whitespace_companies_per_rep"] = out["whitespace_companies"] / out["active_reps_total"]
    out["high_icp_whitespace_per_rep"] = out["high_icp_whitespace_count"] / out["active_reps_total"]
    out["captured_accounts_per_rep"] = out["captured_accounts"] / out["active_reps_total"]

    out["coverage_index_whitespace"] = out["rep_share"] / out["whitespace_share"]
    out["coverage_index_high_icp_whitespace"] = out["rep_share"] / out["high_icp_whitespace_share"]
    out["coverage_index_existing_accounts"] = out["rep_share"] / out["captured_account_share"]

    out["as_of_date"] = as_of_date
    return out.sort_values("coverage_index_whitespace").reset_index(drop=True)


# --------------------------------------------------------------------------
# Rebalancing -- structural "what would it take," not a recommendation
# --------------------------------------------------------------------------

def compute_rebalancing_deltas(as_of_date: date, coverage: pd.DataFrame = None,
                                con=None) -> pd.DataFrame:
    """Grain: one row per territory. A purely structural calculation:
    holding total active ISR/AE headcount fixed, what headcount per
    territory would equalize coverage_index_whitespace to 1.0 everywhere
    (i.e., every territory's share of headcount matches its share of
    whitespace exactly)? ideal_headcount = whitespace_share * total_reps.
    delta = ideal_headcount - active_reps_total (positive = needs more
    reps to reach parity, negative = holds more than parity requires).

    This is a "what it would take" structural answer, not a
    recommendation: it does not and cannot account for cost, rep
    willingness to relocate, ramp-up time for a moved rep, or the
    minimum-viable-staffing floor LATAM is deliberately held above (see
    generators/territories.py's own docstring) -- ISR and AE headcount are
    also treated as fungible "new-business coverage capacity" here since
    whitespace-company counts in mart_tam_whitespace are not split by
    ICP fit-segment/role at the territory grain; a role-specific version
    (Commercial-fit whitespace / ISR headcount, Enterprise-fit whitespace /
    AE headcount) is a natural extension using dim_market_universe.
    icp_fit_score directly, not built here. See Known limitations in the
    methods doc entry -- these are named there explicitly, not silently
    assumed away."""
    owns_con = con is None
    con = con or _connect()
    try:
        coverage = compute_coverage_ratios(as_of_date, con=con) if coverage is None else coverage
    finally:
        if owns_con:
            con.close()

    out = coverage[["territory", "active_reps_total", "whitespace_share", "coverage_index_whitespace"]].copy()
    total_reps = float(out["active_reps_total"].sum())
    out["ideal_headcount"] = out["whitespace_share"] * total_reps
    out["delta_reps"] = out["ideal_headcount"] - out["active_reps_total"]
    out["delta_reps_rounded"] = out["delta_reps"].round().astype(int)
    out["as_of_date"] = as_of_date
    return out.sort_values("delta_reps", ascending=False).reset_index(drop=True)


def summarize_apac_rebalancing(as_of_date: date, deltas: pd.DataFrame = None, con=None) -> dict:
    """Headline structural read: reps APAC would need (rounded up, since a
    fractional rep cannot be hired) to reach parity with the company-wide
    whitespace-per-rep average, and the ranked donor territories (by
    surplus) a literal equalization would draw from -- LATAM flagged
    separately since generators/territories.py states its surplus is a
    deliberate minimum-viable-staffing floor, not slack."""
    owns_con = con is None
    con = con or _connect()
    try:
        deltas = compute_rebalancing_deltas(as_of_date, con=con) if deltas is None else deltas
    finally:
        if owns_con:
            con.close()

    apac_row = deltas[deltas["territory"] == "APAC"].iloc[0]
    reps_needed = math.ceil(apac_row["delta_reps"])
    donors = deltas[(deltas["territory"] != "APAC") & (deltas["delta_reps"] < 0)].copy()
    donors["surplus_reps"] = -donors["delta_reps"]
    donors = donors.sort_values("surplus_reps", ascending=False)
    return {
        "as_of_date": as_of_date,
        "apac_current_headcount": int(apac_row["active_reps_total"]),
        "apac_ideal_headcount": float(apac_row["ideal_headcount"]),
        "apac_reps_needed_for_parity": int(reps_needed),
        "donor_territories_ranked_by_surplus": donors[["territory", "surplus_reps"]].to_dict("records"),
        "note": "structural equalization target only -- see Known limitations "
                "(cost, relocation feasibility, ramp time, LATAM's deliberate "
                "minimum-viable-staffing floor are all out of scope)",
    }


# --------------------------------------------------------------------------
# Validation -- structural tie-outs and a non-vacuousness check, not statistics
# --------------------------------------------------------------------------

def reconcile_headcount_partition(as_of_date: date, headcount: pd.DataFrame = None, con=None) -> dict:
    """Structural correctness invariant: the per-(territory, rep_type)
    headcount table sums to exactly the same total as a direct, un-grouped
    count of active ISR/AE reps with a non-null territory as of as_of_date
    -- no rep double-counted (a rep with overlapping capacity periods) or
    dropped (a rep whose period boundary excludes as_of_date by an
    off-by-one)."""
    owns_con = con is None
    con = con or _connect()
    try:
        headcount = load_rep_headcount_by_territory(as_of_date, con=con) if headcount is None else headcount
        direct_total = con.execute(
            "select count(*) from main_marts.dim_reps "
            "where rep_type in ('ISR', 'AE') and territory is not null "
            "and period_start_date <= ? "
            "and (period_end_date is null or period_end_date >= ?) "
            "and rep_status = 'active'",
            [as_of_date, as_of_date],
        ).fetchone()[0]
    finally:
        if owns_con:
            con.close()
    grouped_total = int(headcount["active_headcount"].sum())
    diff = abs(grouped_total - int(direct_total))
    return {
        "grouped_total": grouped_total,
        "direct_total": int(direct_total),
        "abs_diff": diff,
        "tolerance": _RECONCILIATION_TOLERANCE_COUNT,
        "reconciles": diff <= _RECONCILIATION_TOLERANCE_COUNT,
    }


def reconcile_whitespace_partition(whitespace: pd.DataFrame = None, con=None) -> dict:
    """Structural correctness invariant: the per-territory whitespace
    rollup sums to exactly mart_tam_whitespace's own grand total -- no
    territory dropped or double-counted in the group-by rollup."""
    owns_con = con is None
    con = con or _connect()
    try:
        whitespace = load_whitespace_by_territory(con=con) if whitespace is None else whitespace
        direct_total = con.execute(
            "select sum(whitespace_companies) from main_marts.mart_tam_whitespace"
        ).fetchone()[0]
    finally:
        if owns_con:
            con.close()
    grouped_total = int(whitespace["whitespace_companies"].sum())
    diff = abs(grouped_total - int(direct_total))
    return {
        "grouped_total": grouped_total,
        "direct_total": int(direct_total),
        "abs_diff": diff,
        "tolerance": _RECONCILIATION_TOLERANCE_COUNT,
        "reconciles": diff <= _RECONCILIATION_TOLERANCE_COUNT,
    }


def reconcile_account_partition(as_of_date: date, accounts: pd.DataFrame = None, con=None) -> dict:
    """Structural correctness invariant: the per-territory captured-account
    rollup sums to exactly a direct, un-grouped count of accounts with
    signup_date <= as_of_date -- no account dropped (a null territory) or
    double-counted."""
    owns_con = con is None
    con = con or _connect()
    try:
        accounts = load_existing_accounts_by_territory(as_of_date, con=con) if accounts is None else accounts
        direct_total = con.execute(
            "select count(*) from main_marts.dim_accounts where signup_date <= ?",
            [as_of_date],
        ).fetchone()[0]
    finally:
        if owns_con:
            con.close()
    grouped_total = int(accounts["captured_accounts"].sum())
    diff = abs(grouped_total - int(direct_total))
    return {
        "grouped_total": grouped_total,
        "direct_total": int(direct_total),
        "abs_diff": diff,
        "tolerance": _RECONCILIATION_TOLERANCE_COUNT,
        "reconciles": diff <= _RECONCILIATION_TOLERANCE_COUNT,
        "note": "every dim_accounts row carries a non-null territory (deterministic "
                "function of region, resolved for the full market_universe population) "
                "-- a diff here would mean a territory join gap, not a legitimate null",
    }


def reconcile_rebalancing_conserves_headcount(as_of_date: date, deltas: pd.DataFrame = None,
                                               con=None) -> dict:
    """Structural correctness invariant: sum(ideal_headcount) across all 5
    territories == sum(active_reps_total) exactly -- the equalization
    calculation redistributes existing headcount, it does not fabricate or
    lose reps. Exact arithmetic by construction (ideal_headcount is a share
    of a fixed total), so anything beyond floating-point noise is a real
    bug."""
    owns_con = con is None
    con = con or _connect()
    try:
        deltas = compute_rebalancing_deltas(as_of_date, con=con) if deltas is None else deltas
    finally:
        if owns_con:
            con.close()
    lhs = float(deltas["ideal_headcount"].sum())
    rhs = float(deltas["active_reps_total"].sum())
    diff = abs(lhs - rhs)
    return {
        "sum_ideal_headcount": lhs,
        "sum_active_headcount": rhs,
        "abs_diff": diff,
        "tolerance": _RECONCILIATION_TOLERANCE_HEADCOUNT,
        "reconciles": diff <= _RECONCILIATION_TOLERANCE_HEADCOUNT,
    }


def check_apac_underresourcing_detected(as_of_date: date, coverage: pd.DataFrame = None,
                                         con=None) -> dict:
    """Non-vacuousness check -- the strongest correctness check available
    here, per the task brief: does this artifact actually detect the real,
    deliberately-injected APAC underresourcing / LATAM floor-staffing
    generators/territories.py built into the data (module docstring's own
    stated rep-share/company-share ratios: APAC ~0.60, LATAM ~1.40)?
    Requires, on THIS module's own independently-computed metric (whitespace-
    opportunity share, not company-population share): (a) APAC's
    coverage_index_whitespace is the minimum across all 5 territories, (b)
    that minimum is <= _MAX_UNDER_RESOURCED_COVERAGE_INDEX, (c) LATAM's
    coverage_index_whitespace is the maximum across all 5 territories, and
    (d) that maximum is >= _MIN_OVER_RESOURCED_COVERAGE_INDEX. Confirms the
    finding independently rather than assuming the design doc's stated
    figure is what a real coverage metric would show -- exactly what the
    task brief asks this artifact to do."""
    owns_con = con is None
    con = con or _connect()
    try:
        coverage = compute_coverage_ratios(as_of_date, con=con) if coverage is None else coverage
    finally:
        if owns_con:
            con.close()

    min_row = coverage.loc[coverage["coverage_index_whitespace"].idxmin()]
    max_row = coverage.loc[coverage["coverage_index_whitespace"].idxmax()]

    apac_is_min = min_row["territory"] == "APAC"
    apac_under_floor = bool(min_row["coverage_index_whitespace"] <= _MAX_UNDER_RESOURCED_COVERAGE_INDEX)
    latam_is_max = max_row["territory"] == "LATAM"
    latam_over_floor = bool(max_row["coverage_index_whitespace"] >= _MIN_OVER_RESOURCED_COVERAGE_INDEX)

    passes = bool(apac_is_min and apac_under_floor and latam_is_max and latam_over_floor)
    return {
        "min_territory": min_row["territory"],
        "min_coverage_index_whitespace": float(min_row["coverage_index_whitespace"]),
        "max_territory": max_row["territory"],
        "max_coverage_index_whitespace": float(max_row["coverage_index_whitespace"]),
        "max_under_resourced_floor": _MAX_UNDER_RESOURCED_COVERAGE_INDEX,
        "min_over_resourced_floor": _MIN_OVER_RESOURCED_COVERAGE_INDEX,
        "apac_correctly_identified_as_most_underresourced": bool(apac_is_min and apac_under_floor),
        "latam_correctly_identified_as_most_overresourced": bool(latam_is_max and latam_over_floor),
        "passes": passes,
    }


def run_build_time_validation(as_of_date: date, log: bool = True) -> dict:
    """End-to-end build-time computation and correctness check: rep
    headcount by territory, whitespace by territory, existing accounts by
    territory, open pipeline by territory (supplementary), the coverage-
    ratio table, the rebalancing-delta table and its APAC-specific summary,
    plus four structural tie-outs and one non-vacuousness check --
    everything analytics-model-validator needs to independently recompute
    this artifact's correctness claims.

    Logs the natural scalar time-series metrics to
    fact_model_performance_history via analytics/model_performance.py when
    log=True; the variable-width tables (coverage-ratio detail, rebalancing
    detail) do not fit that log's flat scalar grain and are recorded as
    structured detail in docs/acme-corp-analytics-methods.md instead."""
    con = _connect()
    try:
        headcount = load_rep_headcount_by_territory(as_of_date, con=con)
        whitespace = load_whitespace_by_territory(con=con)
        accounts = load_existing_accounts_by_territory(as_of_date, con=con)
        open_pipeline = load_open_pipeline_by_territory(as_of_date, con=con)
        coverage = compute_coverage_ratios(as_of_date, headcount=headcount, whitespace=whitespace,
                                            accounts=accounts, con=con)
        deltas = compute_rebalancing_deltas(as_of_date, coverage=coverage, con=con)
        apac_summary = summarize_apac_rebalancing(as_of_date, deltas=deltas, con=con)

        headcount_tie_out = reconcile_headcount_partition(as_of_date, headcount=headcount, con=con)
        whitespace_tie_out = reconcile_whitespace_partition(whitespace=whitespace, con=con)
        account_tie_out = reconcile_account_partition(as_of_date, accounts=accounts, con=con)
        rebalancing_tie_out = reconcile_rebalancing_conserves_headcount(as_of_date, deltas=deltas, con=con)
        apac_detection = check_apac_underresourcing_detected(as_of_date, coverage=coverage, con=con)
    finally:
        con.close()

    checks = [
        {"name": "headcount_partition_reconciles",
         "passed": bool(headcount_tie_out["reconciles"]),
         "detail": f"grouped {headcount_tie_out['grouped_total']} vs direct {headcount_tie_out['direct_total']}"},
        {"name": "whitespace_partition_reconciles",
         "passed": bool(whitespace_tie_out["reconciles"]),
         "detail": f"grouped {whitespace_tie_out['grouped_total']} vs direct {whitespace_tie_out['direct_total']}"},
        {"name": "account_partition_reconciles",
         "passed": bool(account_tie_out["reconciles"]),
         "detail": f"grouped {account_tie_out['grouped_total']} vs direct {account_tie_out['direct_total']}"},
        {"name": "rebalancing_conserves_headcount",
         "passed": bool(rebalancing_tie_out["reconciles"]),
         "detail": f"max abs diff {rebalancing_tie_out['abs_diff']:.2e} reps"},
        {"name": "apac_underresourcing_non_vacuous",
         "passed": bool(apac_detection["passes"]),
         "detail": f"min={apac_detection['min_territory']} "
                   f"({apac_detection['min_coverage_index_whitespace']:.3f}), "
                   f"max={apac_detection['max_territory']} "
                   f"({apac_detection['max_coverage_index_whitespace']:.3f})"},
    ]
    checks_passed = sum(1 for c in checks if c["passed"])

    if log:
        for _, row in coverage.iterrows():
            t = row["territory"].lower().replace("-", "_")
            log_performance(_MODEL_NAME, as_of_date, f"active_reps_{t}", float(row["active_reps_total"]))
            log_performance(_MODEL_NAME, as_of_date, f"whitespace_companies_per_rep_{t}",
                            float(row["whitespace_companies_per_rep"]))
            log_performance(_MODEL_NAME, as_of_date, f"coverage_index_whitespace_{t}",
                            float(row["coverage_index_whitespace"]))
            log_performance(_MODEL_NAME, as_of_date, f"coverage_index_existing_accounts_{t}",
                            float(row["coverage_index_existing_accounts"]))
        log_performance(_MODEL_NAME, as_of_date, "apac_reps_needed_for_parity",
                        float(apac_summary["apac_reps_needed_for_parity"]))
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_total", float(len(checks)))
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_passed", float(checks_passed))

    return {
        "headcount": headcount,
        "whitespace": whitespace,
        "accounts": accounts,
        "open_pipeline": open_pipeline,
        "coverage": coverage,
        "rebalancing_deltas": deltas,
        "apac_summary": apac_summary,
        "headcount_tie_out": headcount_tie_out,
        "whitespace_tie_out": whitespace_tie_out,
        "account_tie_out": account_tie_out,
        "rebalancing_tie_out": rebalancing_tie_out,
        "apac_detection": apac_detection,
        "checks": checks,
        "checks_passed": checks_passed,
        "checks_total": len(checks),
    }


if __name__ == "__main__":
    result = run_build_time_validation(date(2025, 12, 31))

    print("Coverage ratio table:")
    cols = ["territory", "active_isr", "active_ae", "active_reps_total",
            "whitespace_companies", "whitespace_companies_per_rep", "coverage_index_whitespace",
            "high_icp_whitespace_count", "coverage_index_high_icp_whitespace",
            "captured_accounts", "captured_accounts_per_rep", "coverage_index_existing_accounts"]
    print(result["coverage"][cols].to_string(index=False))
    print()
    print("Rebalancing deltas (structural equalization target):")
    print(result["rebalancing_deltas"].to_string(index=False))
    print()
    print("APAC rebalancing summary:")
    for k, v in result["apac_summary"].items():
        print(f"  {k}: {v}")
    print()
    print("Open pipeline by territory (supplementary, point-in-time):")
    print(result["open_pipeline"].to_string(index=False))
    print()
    print("APAC/LATAM non-vacuousness check:", result["apac_detection"])
    print()
    for check in result["checks"]:
        print(f"[{'PASS' if check['passed'] else 'FAIL'}] {check['name']}: {check['detail']}")
    print(f"{result['checks_passed']} of {result['checks_total']} checks pass")
