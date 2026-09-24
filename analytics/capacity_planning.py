"""Capacity planning / quota achievability -- grain: one row per
quota-bearing rep (ISR/AE) per complete calendar quarter; source marts:
dim_reps (point-in-time quota and active/departed status per capacity
period) and fact_opportunities (closed-won new-business ARR by rep and
close quarter).

Build spec item #3, which absorbs quota setting and attainment analysis:
"is the quota mathematically achievable given capacity, not just headcount
count." Two teams with identical headcount but different ramp mixes do not
have the same real capacity, and this module is what makes that difference
a computed number rather than an assertion.

Scope -- ISR/AE only, deliberately. generators/reps.py scopes
quota_history to ISR and AE ("the new-business, quota-bearing roles per
build spec Section 2; AM comp isn't described as quota-based"), so quota
attainment and quota achievability are only meaningful concepts for those
two roles. AM headcount/book-size economics is a different question with
its own home in the metric tree (Onboarding/CS efficiency and AM
efficiency, both computed in mart_efficiency) and is not forced into a
quota-attainment framing it does not have. SE carries no quota either and
is likewise out of scope.

Shape -- structural/descriptive, not a fitted model. Every number here is
a direct computation from real empirical inputs (observed closed-won ARR,
stated quota, hire dates, status history) plus one stated ramp rule taken
from the build spec. Nothing is fitted, so per analytics-engineering-
conventions' "Structural/logic artifacts" category there is no coefficient
table, no R^2/RMSE, no AUC and no confusion matrix here, and their absence
is deliberate rather than pending. See docs/acme-corp-analytics-methods.md's
Capacity planning entry for the full reasoning.

No stochastic step lives in this module -- no train/test split, no
sampling, no simulation -- so no random seed applies, matching
analytics/segment_migration.py's and analytics/variance_diagnostic.py's
precedent.
"""
import os
from datetime import date

import duckdb
import numpy as np
import pandas as pd

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_MODEL_NAME = "capacity_planning"

# The quota-bearing, new-business roles. Not a filter of convenience --
# quota_history simply has no rows for any other rep_type.
_QUOTA_BEARING_REP_TYPES = ("ISR", "AE")

# Ramp-capacity discount. Build spec Section 4 states the design
# assumption directly: "Unramped reps at ~50% quota capacity for first 2
# quarters, any segment/role." That stated assumption is adopted here
# rather than a newly invented number. It is not asserted on the build
# spec's authority alone: generators/config.py's
# RAMPING_REP_WIN_ASSIGNMENT_FACTOR = 0.55 is the mechanism that makes it
# real in the generated data (a ramping rep gets 0.55x a ramped rep's
# probability of being assigned a won deal), and
# check_ramp_discount_reconciles() below measures what ramping reps
# actually produced and confirms the two agree. The realized ratio lands
# slightly under 0.55 because that factor is a relative weight inside an
# assignment pool, not a direct multiplier on a rep's output.
_RAMP_CAPACITY_DISCOUNT = 0.50

# "First 2 quarters" (build spec Section 4), evaluated at each quarter's
# midpoint against a 180-day boundary. 180 days is generators/
# opportunities.py's own _RAMP_FULL_DAYS -- the same cutoff the data was
# generated against -- and the midpoint evaluation is what makes the rule
# land on exactly two quarters for every hire date rather than two or
# three depending on where in a quarter the rep happened to start.
_RAMP_FULL_DAYS = 180

# Achievability margin -- PROPOSED, not yet confirmed (see docs/
# acme-corp-analytics-methods.md). A team-quarter is flagged when stated
# quota exceeds ramp-adjusted expected capacity by more than this share of
# expected capacity. Grounded in the precision of the one estimated
# quantity the capacity figure is built from: the empirical ramped-
# attainment baseline. Across the 12 complete in-window quarters its
# team-level relative standard error is ~14.6% (AE) and ~8.6% (ISR); a gap
# narrower than the wider of those is inside the noise of the number it is
# being measured against, so it is not a finding.
_ACHIEVABILITY_MARGIN = 0.15

# Minimum rep-quarters of ramped observation before an expanding-window
# baseline is treated as usable. Below this the baseline is reported as
# NaN rather than computed off a handful of lumpy Enterprise deals.
_MIN_BASELINE_REP_QUARTERS = 8

# Floor for "the ramp mechanism is real, not vacuous": observed ramping
# reps must produce materially less per capacity-day than ramped reps.
# 0.80 is a deliberately loose ceiling -- it only asks that the observed
# penalty be at least 20%, far short of the 50% the rule assumes, so the
# check fails on a vacuous mechanism without quietly re-testing the
# discount itself (check_ramp_discount_reconciles does that separately).
_MAX_VACUOUS_RAMP_RATIO = 0.80

# Tolerance on the empirical ramp ratio vs. the adopted 0.50 discount.
# +/-0.10 spans both the build spec's ~50% assumption and the generator's
# 0.55 win-assignment factor, so the check confirms the rule is consistent
# with what the data actually produced without claiming more precision
# than ~100 ramping rep-quarters can support.
_RAMP_RATIO_TOLERANCE = 0.10

# Structural tie-out tolerance. The capacity decomposition is exact
# arithmetic, so anything beyond floating-point noise is a real bug.
_RECONCILIATION_TOLERANCE_USD = 0.01


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


# --------------------------------------------------------------------------
# Loaders -- point-in-time by construction
# --------------------------------------------------------------------------

def load_rep_capacity_periods(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per quota-bearing rep per capacity period (a period
    boundary is any date quota or status changed), period_start_date <=
    as_of_date -- a period beginning after as_of_date is future
    information and is never read. Source mart: dim_reps."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select rep_id, rep_type, segment, hire_date, period_start_date, "
            "period_end_date, quota_amount, rep_status "
            "from main_marts.dim_reps "
            "where rep_type in ('ISR', 'AE') and period_start_date <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    for col in ("hire_date", "period_start_date", "period_end_date"):
        df[col] = pd.to_datetime(df[col])
    return df


def load_opportunity_supply_window(as_of_date: date, con=None) -> dict:
    """The first quarter in which any ISR/AE-owned new-business
    opportunity exists at all, won or lost. Source mart:
    fact_opportunities.

    reps.py back-dates ~65% of hires to before the account generator's
    earliest possible account, so the earliest rep-quarters carry a real
    stated quota against a market that does not yet exist in the data.
    Those quarters are reported with has_opportunity_supply = False rather
    than dropped silently -- their attainment is structurally zero and
    says nothing about capacity."""
    owns_con = con is None
    con = con or _connect()
    try:
        row = con.execute(
            "select min(date_trunc('quarter', close_date))::date "
            "from main_marts.fact_opportunities "
            "where opportunity_type = 'new_business' and owner_role in ('ISR', 'AE') "
            "and close_date <= ?",
            [as_of_date],
        ).fetchone()
    finally:
        if owns_con:
            con.close()
    first = pd.to_datetime(row[0]) if row and row[0] is not None else pd.NaT
    return {"first_opportunity_quarter": first}


def load_new_business_wins(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per rep per close quarter, close_date <= as_of_date
    -- no leakage from the future. Closed-won, opportunity_type =
    'new_business', ISR/AE-owned only (SMB's system-owned auto-won records
    and AM-owned renewal/expansion records carry no quota and are
    excluded). Source mart: fact_opportunities."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select rep_id, date_trunc('quarter', close_date)::date as quarter, "
            "sum(amount) as won_arr, count(*) as won_deals "
            "from main_marts.fact_opportunities "
            "where is_won and opportunity_type = 'new_business' "
            "and owner_role in ('ISR', 'AE') and close_date <= ? "
            "group by 1, 2",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["quarter"] = pd.to_datetime(df["quarter"])
    return df


# --------------------------------------------------------------------------
# The rep-quarter panel -- everything else is an aggregation of this
# --------------------------------------------------------------------------

def build_rep_quarter_panel(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per quota-bearing rep per COMPLETE calendar quarter
    in which that rep had at least one active day, quarter end <=
    as_of_date. Carries the quarter's stated quota, active-day coverage
    share, ramp status, and realized closed-won new-business ARR. Source
    marts: dim_reps, fact_opportunities.

    Only complete quarters are admitted: a partial quarter's realized ARR
    measured against a whole quarter's stated quota is a unit mismatch in
    disguise, the same reason analytics/variance_diagnostic.py evaluates
    the last complete month rather than a part-month.

    Coverage share is active days / quarter days. A rep hired or departed
    mid-quarter genuinely had less selling time than a full-quarter rep,
    and the capacity model pro-rates for that -- while stated quota is
    NOT pro-rated, because the generator does not reduce it (quota is set
    at the quarter grain for whoever holds the seat). Quota and achievable
    capacity diverging is the thing this artifact exists to measure, not a
    defect to normalize away.
    """
    periods = load_rep_capacity_periods(as_of_date, con=con)
    wins = load_new_business_wins(as_of_date, con=con)
    if periods.empty:
        return periods.assign(quarter=pd.NaT)

    as_of_ts = pd.Timestamp(as_of_date)
    first_quarter = periods["period_start_date"].min().to_period("Q").start_time
    quarters = pd.period_range(first_quarter, as_of_ts, freq="Q")
    # Only quarters that have fully closed as of as_of_date.
    quarters = [q for q in quarters if q.end_time.normalize() <= as_of_ts]

    open_end = pd.Timestamp("2999-12-31")
    rows = []
    for q in quarters:
        q_start, q_end = q.start_time, q.end_time.normalize()
        quarter_days = (q_end - q_start).days + 1
        overlap = periods[
            (periods["period_start_date"] <= q_end)
            & (periods["period_end_date"].fillna(open_end) >= q_start)
        ]
        if overlap.empty:
            continue
        active = overlap[overlap["rep_status"] == "active"].copy()
        active["overlap_days"] = (
            np.minimum(active["period_end_date"].fillna(open_end), q_end)
            - np.maximum(active["period_start_date"], q_start)
        ).dt.days + 1
        active_days = active.groupby("rep_id")["overlap_days"].sum()

        # Quota is set at quarter-start effective dates, so it is constant
        # within a quarter for a given rep; max() over the overlapping
        # periods picks that one value without depending on which status
        # sub-period happens to be first.
        quota = overlap.groupby("rep_id")["quota_amount"].max()
        attrs = overlap.groupby("rep_id")[["rep_type", "segment", "hire_date"]].first()

        frame = attrs.join(quota.rename("stated_quota")).join(
            active_days.rename("active_days")
        )
        frame["active_days"] = frame["active_days"].fillna(0)
        frame = frame[frame["active_days"] > 0].reset_index()
        frame["quarter"] = q_start
        frame["quarter_end"] = q_end
        frame["quarter_days"] = quarter_days
        rows.append(frame)

    if not rows:
        return pd.DataFrame(
            columns=["rep_id", "rep_type", "segment", "hire_date", "quarter"]
        )

    panel = pd.concat(rows, ignore_index=True)
    panel["coverage_share"] = panel["active_days"] / panel["quarter_days"]
    quarter_midpoint = panel["quarter"] + (panel["quarter_end"] - panel["quarter"]) / 2
    panel["tenure_days_at_quarter_midpoint"] = (
        quarter_midpoint - panel["hire_date"]
    ).dt.days
    panel["ramp_status"] = np.where(
        panel["tenure_days_at_quarter_midpoint"] < _RAMP_FULL_DAYS, "ramping", "ramped"
    )
    panel["ramp_factor"] = np.where(
        panel["ramp_status"] == "ramping", _RAMP_CAPACITY_DISCOUNT, 1.0
    )

    panel = panel.merge(wins, on=["rep_id", "quarter"], how="left")
    panel["won_arr"] = panel["won_arr"].fillna(0.0)
    panel["won_deals"] = panel["won_deals"].fillna(0).astype(int)
    panel["quota_attainment"] = panel["won_arr"] / panel["stated_quota"]
    # Capacity-days = the quota a rep was actually on the hook for after
    # pro-rating for partial-quarter tenure. This is the denominator every
    # baseline below uses, so a rep who worked half a quarter is not
    # counted as a full quarter of under-production.
    panel["capacity_day_quota"] = panel["stated_quota"] * panel["coverage_share"]
    return panel.sort_values(["quarter", "rep_type", "rep_id"]).reset_index(drop=True)


# --------------------------------------------------------------------------
# 1. Attainment analysis
# --------------------------------------------------------------------------

def compute_attainment(as_of_date: date, panel: pd.DataFrame = None, con=None) -> pd.DataFrame:
    """Quota attainment aggregated by rep_type x segment x quarter, plus a
    company-wide row per quarter. Grain: one row per (segment, rep_type,
    quarter) with segment/rep_type = 'All' for the company-wide roll-up.
    Source marts: dim_reps, fact_opportunities.

    Aggregate attainment is the dollar ratio (total won ARR / total stated
    quota), not the mean of per-rep attainment ratios -- those are
    different statistics and diverge sharply when quota varies across reps,
    which it does (AE $60-105K vs. ISR $22.5-33K base per quarter, before
    the generator's per-quarter step-up). The mean
    of per-rep ratios is reported alongside as mean_rep_attainment, named
    for what it is.
    """
    panel = build_rep_quarter_panel(as_of_date, con=con) if panel is None else panel
    if panel.empty:
        return pd.DataFrame()

    def _agg(df: pd.DataFrame) -> pd.Series:
        return pd.Series({
            "reps": int(df["rep_id"].nunique()),
            "ramping_reps": int((df["ramp_status"] == "ramping").sum()),
            "stated_quota": float(df["stated_quota"].sum()),
            "capacity_day_quota": float(df["capacity_day_quota"].sum()),
            "won_arr": float(df["won_arr"].sum()),
            "won_deals": int(df["won_deals"].sum()),
            "attainment": float(df["won_arr"].sum() / df["stated_quota"].sum())
            if df["stated_quota"].sum() else np.nan,
            "mean_rep_attainment": float(df["quota_attainment"].mean()),
            "median_rep_attainment": float(df["quota_attainment"].median()),
        })

    by_team = (
        panel.groupby(["segment", "rep_type", "quarter"])
        .apply(_agg, include_groups=False)
        .reset_index()
    )
    company = panel.groupby("quarter").apply(_agg, include_groups=False).reset_index()
    company["segment"] = "All"
    company["rep_type"] = "All"
    return pd.concat([by_team, company], ignore_index=True).sort_values(
        ["quarter", "segment", "rep_type"]
    ).reset_index(drop=True)


# --------------------------------------------------------------------------
# 2. Ramp-adjusted capacity model
# --------------------------------------------------------------------------

def compute_ramped_baseline(as_of_date: date, panel: pd.DataFrame = None,
                            mode: str = "as_of_date", con=None) -> pd.DataFrame:
    """Empirical baseline productivity: the attainment a FULLY RAMPED rep
    of a given rep_type/segment actually achieves per capacity-day of
    quota. Grain: one row per (segment, rep_type, quarter). Source marts:
    dim_reps, fact_opportunities.

    This is derived, never invented -- it is observed ramped won ARR
    divided by observed ramped capacity-day quota. Two modes, both
    point-in-time honest:

    - 'as_of_date' (default): one baseline per team, estimated over every
      complete quarter up to as_of_date and applied uniformly to all of
      them. This is the descriptive read -- "given everything known at
      as_of_date, what does a ramped rep produce" -- and is what the
      build-time checkpoint reports. Two runs at different as_of_dates
      can legitimately give the same quarter different capacity figures,
      because the baseline itself is an as-of estimate.
    - 'prior_quarters_only': an expanding-window baseline using only
      quarters strictly before the quarter being evaluated. This is the
      forward-planning read, and it avoids judging a quarter's quota
      against that same quarter's own realized productivity. Reported as
      NaN until _MIN_BASELINE_REP_QUARTERS ramped rep-quarters have
      accumulated, rather than computed off a handful of lumpy Enterprise
      deals.
    """
    if mode not in ("as_of_date", "prior_quarters_only"):
        raise ValueError(f"unknown baseline mode: {mode!r}")
    panel = build_rep_quarter_panel(as_of_date, con=con) if panel is None else panel
    if panel.empty:
        return pd.DataFrame()

    ramped = panel[panel["ramp_status"] == "ramped"]
    teams = panel[["segment", "rep_type"]].drop_duplicates()
    quarters = sorted(panel["quarter"].unique())

    rows = []
    for _, team in teams.iterrows():
        team_ramped = ramped[
            (ramped["segment"] == team["segment"]) & (ramped["rep_type"] == team["rep_type"])
        ]
        for q in quarters:
            window = team_ramped if mode == "as_of_date" else team_ramped[team_ramped["quarter"] < q]
            denom = float(window["capacity_day_quota"].sum())
            n = int(len(window))
            usable = n >= _MIN_BASELINE_REP_QUARTERS and denom > 0
            rows.append({
                "segment": team["segment"],
                "rep_type": team["rep_type"],
                "quarter": q,
                "baseline_mode": mode,
                "baseline_attainment": float(window["won_arr"].sum() / denom) if usable else np.nan,
                "baseline_rep_quarters": n,
            })
    return pd.DataFrame(rows)


def compute_expected_capacity(as_of_date: date, panel: pd.DataFrame = None,
                              baseline: pd.DataFrame = None,
                              mode: str = "as_of_date", con=None) -> pd.DataFrame:
    """Ramp-adjusted expected achievable capacity per rep-quarter, in ARR.
    Grain: one row per rep per complete quarter. Source marts: dim_reps,
    fact_opportunities.

        expected_capacity = stated_quota
                          x baseline_attainment   (what a ramped rep does)
                          x coverage_share        (days actually on seat)
                          x ramp_factor           (0.50 while ramping)

    Expected capacity is deliberately NOT the rep's quota. The generator
    sets quota independent of ramp status -- a rep in their first quarter
    carries the same quota as a four-year veteran -- so quota and
    achievable capacity genuinely diverge, and measuring that divergence
    is the artifact's whole purpose.

    Also emits fully_ramped_capacity (the same figure with ramp_factor
    forced to 1.0), which is the level-immune comparison basis the
    achievability assessment uses to separate a ramp-mix problem from a
    quota-level problem.
    """
    panel = build_rep_quarter_panel(as_of_date, con=con) if panel is None else panel
    if panel.empty:
        return panel
    if baseline is None:
        baseline = compute_ramped_baseline(as_of_date, panel=panel, mode=mode, con=con)

    df = panel.merge(
        baseline[["segment", "rep_type", "quarter", "baseline_mode",
                  "baseline_attainment", "baseline_rep_quarters"]],
        on=["segment", "rep_type", "quarter"],
        how="left",
    )
    df["fully_ramped_capacity"] = (
        df["stated_quota"] * df["baseline_attainment"] * df["coverage_share"]
    )
    df["expected_capacity"] = df["fully_ramped_capacity"] * df["ramp_factor"]
    return df


# --------------------------------------------------------------------------
# 3. Is the quota mathematically achievable given capacity?
# --------------------------------------------------------------------------

def assess_quota_achievability(as_of_date: date, capacity: pd.DataFrame = None,
                               mode: str = "as_of_date",
                               margin: float = _ACHIEVABILITY_MARGIN,
                               first_opportunity_quarter=None,
                               con=None) -> pd.DataFrame:
    """The artifact's actual diagnostic output. Grain: one row per
    (segment, rep_type, quarter) plus a company-wide 'All' row per
    quarter. Source marts: dim_reps, fact_opportunities.

    For each team-quarter, sums the team's stated quota from its active
    reps' dim_reps rows and its ramp-adjusted expected capacity from
    compute_expected_capacity(), and decomposes the gap between them into
    three exactly-additive parts:

        stated_quota - expected_capacity
          = productivity_gap   quota x (1 - baseline)
          + coverage_gap       quota x baseline x (1 - coverage)
          + ramp_mix_gap       quota x baseline x coverage x (1 - ramp_factor)

    The decomposition is what makes this more than a headcount count: two
    teams with the same headcount and the same stated quota land on
    different expected capacity purely through ramp_mix_gap, and the
    column names which part of a shortfall is attributable to ramp mix
    rather than to the quota's own level.

    Two comparison bases are reported, and the difference between them is
    load-bearing:
      - quota_coverage_ratio = expected_capacity / stated_quota, the
        literal answer to "is the quota achievable." Flagged comparable:
        generators/reps.py's _QUOTA_BASE_RANGE is back-solved from the
        opportunity generator's own realized deal supply (opportunities
        per ramped rep-quarter x win rate x average won deal size), so
        quota and capacity are denominated in the same units and this
        ratio's absolute level is a capacity reading rather than a gap
        between two independently-parameterised generators.
      - ramp_attributable_gap_pct = ramp_mix_gap / expected_capacity, the
        level-immune share of the gap caused by ramp mix alone. Immune to
        a constant level offset in the baseline, in the same way
        analytics/variance_diagnostic.py's trailing-baseline signal is
        immune to its caveated plan-level offsets.
    """
    if capacity is None:
        capacity = compute_expected_capacity(as_of_date, mode=mode, con=con)
    if capacity is None or capacity.empty:
        return pd.DataFrame()
    if first_opportunity_quarter is None:
        first_opportunity_quarter = load_opportunity_supply_window(
            as_of_date, con=con
        )["first_opportunity_quarter"]

    df = capacity.copy()
    df["productivity_gap"] = df["stated_quota"] * (1 - df["baseline_attainment"])
    df["coverage_gap"] = (
        df["stated_quota"] * df["baseline_attainment"] * (1 - df["coverage_share"])
    )
    df["ramp_mix_gap"] = df["fully_ramped_capacity"] * (1 - df["ramp_factor"])

    def _agg(g: pd.DataFrame) -> pd.Series:
        # skipna=False on every capacity-derived sum: in `prior_quarters_only`
        # mode a rep with fewer than _MIN_BASELINE_REP_QUARTERS prior ramped
        # rep-quarters has NaN baseline_attainment (genuinely not estimable
        # yet, not zero). pandas' default skipna=True would silently drop
        # that rep from the sum -- fabricating "this rep contributes zero
        # capacity" instead of the honest "this team-quarter's capacity
        # isn't computable yet," and would corrupt the exact-reconciliation
        # identity below by the size of the dropped rep's capacity. A
        # not-yet-estimable rep poisons the whole team-quarter's capacity
        # figures to NaN, the same way any other artifact in this project
        # reports "not computable" rather than a fabricated number.
        quota = float(g["stated_quota"].sum())
        capacity_sum = float(g["expected_capacity"].sum(skipna=False))
        fully_ramped = float(g["fully_ramped_capacity"].sum(skipna=False))
        ramp_gap = float(g["ramp_mix_gap"].sum(skipna=False))
        productivity_gap = float(g["productivity_gap"].sum(skipna=False))
        coverage_gap = float(g["coverage_gap"].sum(skipna=False))
        gap = quota - capacity_sum
        return pd.Series({
            "reps": int(g["rep_id"].nunique()),
            "ramping_reps": int((g["ramp_status"] == "ramping").sum()),
            "ramping_quota_share": float(
                g.loc[g["ramp_status"] == "ramping", "stated_quota"].sum() / quota
            ) if quota else np.nan,
            "stated_quota": quota,
            "expected_capacity": capacity_sum,
            "fully_ramped_capacity": fully_ramped,
            "won_arr": float(g["won_arr"].sum()),
            "productivity_gap": productivity_gap,
            "coverage_gap": coverage_gap,
            "ramp_mix_gap": ramp_gap,
            "quota_coverage_ratio": capacity_sum / quota if quota else np.nan,
            "quota_gap_pct": gap / capacity_sum if capacity_sum else np.nan,
            "ramp_attributable_gap_pct": ramp_gap / capacity_sum if capacity_sum else np.nan,
            "ramp_capacity_haircut": capacity_sum / fully_ramped if fully_ramped else np.nan,
        })

    by_team = (
        df.groupby(["segment", "rep_type", "quarter"]).apply(_agg, include_groups=False).reset_index()
    )
    company = df.groupby("quarter").apply(_agg, include_groups=False).reset_index()
    company["segment"] = "All"
    company["rep_type"] = "All"
    out = pd.concat([by_team, company], ignore_index=True)

    out["achievability_margin"] = margin
    out["baseline_mode"] = df["baseline_mode"].iloc[0]
    out["has_opportunity_supply"] = (
        out["quarter"] >= first_opportunity_quarter
        if pd.notna(first_opportunity_quarter) else False
    )
    # The literal achievability verdict, on the absolute basis.
    out["quota_achievable"] = out["quota_gap_pct"] <= margin
    out["quota_basis_comparability"] = "comparable"
    # The level-immune verdict: is ramp mix alone enough to put this team
    # outside the margin, independent of where the quota level sits?
    out["ramp_mix_breaches_margin"] = out["ramp_attributable_gap_pct"] > margin
    return out.sort_values(["quarter", "segment", "rep_type"]).reset_index(drop=True)


# --------------------------------------------------------------------------
# Validation -- structural tie-outs and a non-vacuousness check, not statistics
# --------------------------------------------------------------------------

def reconcile_attainment_to_source(as_of_date: date, panel: pd.DataFrame = None,
                                   con=None) -> dict:
    """Structural correctness invariant: the rep-quarter panel's won_arr
    must sum to exactly the closed-won new-business ARR fact_opportunities
    reports for ISR/AE-owned deals in the same complete quarters -- no
    dollar dropped (a rep-quarter with no matching dim_reps period) and
    none double-counted (a rep with several capacity periods inside one
    quarter fanning out the join). This is capacity planning's analog of
    the segment-migration analysis's growth-bridge tie-out."""
    owns_con = con is None
    con = con or _connect()
    try:
        panel = build_rep_quarter_panel(as_of_date, con=con) if panel is None else panel
        wins = load_new_business_wins(as_of_date, con=con)
    finally:
        if owns_con:
            con.close()

    if panel.empty:
        return {"max_abs_diff_usd": np.nan, "reconciles": False,
                "tolerance_usd": _RECONCILIATION_TOLERANCE_USD}

    complete_quarters = set(panel["quarter"].unique())
    source = wins[wins["quarter"].isin(complete_quarters)]
    source_total = float(source["won_arr"].sum())
    panel_total = float(panel["won_arr"].sum())

    merged = (
        panel.groupby(["rep_id", "quarter"])["won_arr"].sum().rename("panel_won").reset_index()
        .merge(source[["rep_id", "quarter", "won_arr"]].rename(columns={"won_arr": "source_won"}),
               on=["rep_id", "quarter"], how="outer")
    )
    merged[["panel_won", "source_won"]] = merged[["panel_won", "source_won"]].fillna(0.0)
    row_diff = (merged["panel_won"] - merged["source_won"]).abs()
    max_abs_diff = float(max(abs(panel_total - source_total), row_diff.max() if len(row_diff) else 0.0))

    return {
        "panel_won_arr": panel_total,
        "source_won_arr": source_total,
        "unmatched_rep_quarters": int((row_diff > _RECONCILIATION_TOLERANCE_USD).sum()),
        "max_abs_diff_usd": max_abs_diff,
        "tolerance_usd": _RECONCILIATION_TOLERANCE_USD,
        "reconciles": max_abs_diff <= _RECONCILIATION_TOLERANCE_USD,
    }


def reconcile_capacity_decomposition(as_of_date: date, achievability: pd.DataFrame = None,
                                     mode: str = "as_of_date", con=None) -> dict:
    """Structural correctness invariant: for every team-quarter,
    productivity_gap + coverage_gap + ramp_mix_gap must equal
    stated_quota - expected_capacity exactly. The decomposition is exact
    arithmetic by construction, so any gap beyond floating-point noise is
    a real bug in the model, not drift."""
    if achievability is None:
        achievability = assess_quota_achievability(as_of_date, mode=mode, con=con)
    if achievability.empty:
        return {"max_abs_diff_usd": np.nan, "reconciles": False,
                "tolerance_usd": _RECONCILIATION_TOLERANCE_USD}
    lhs = (
        achievability["productivity_gap"]
        + achievability["coverage_gap"]
        + achievability["ramp_mix_gap"]
    )
    rhs = achievability["stated_quota"] - achievability["expected_capacity"]
    diff = (lhs - rhs).abs()
    # A NaN row here means the team-quarter's capacity isn't computable yet
    # (at least one rep hasn't accumulated _MIN_BASELINE_REP_QUARTERS of
    # baseline history in prior_quarters_only mode) -- that is not a
    # reconciliation failure, it's an honest "not yet known," so it's
    # counted separately and excluded from max_abs_diff (pandas' default
    # skipna=True on .max()) rather than either masking a real mismatch or
    # being misreported as one.
    not_computable = int(diff.isna().sum())
    max_abs_diff = float(diff.max()) if diff.notna().any() else 0.0
    return {
        "rows_checked": int(len(achievability)),
        "rows_not_yet_computable": not_computable,
        "max_abs_diff_usd": max_abs_diff,
        "tolerance_usd": _RECONCILIATION_TOLERANCE_USD,
        "reconciles": max_abs_diff <= _RECONCILIATION_TOLERANCE_USD,
    }


def measure_empirical_ramp_effect(as_of_date: date, panel: pd.DataFrame = None,
                                  con=None) -> pd.DataFrame:
    """What ramping reps ACTUALLY produced relative to ramped reps, per
    capacity-day of quota. Grain: one row per (segment, rep_type) plus a
    pooled 'All' row. Source marts: dim_reps, fact_opportunities.

    Capacity-day weighted on both sides, which matters: ramping reps
    average ~0.81 of a quarter on seat (they are hired mid-quarter), so an
    unadjusted comparison would charge partial tenure to the ramp effect
    and overstate it."""
    panel = build_rep_quarter_panel(as_of_date, con=con) if panel is None else panel
    if panel.empty:
        return pd.DataFrame()

    def _one(df: pd.DataFrame, segment: str, rep_type: str) -> dict:
        out = {"segment": segment, "rep_type": rep_type}
        for status in ("ramped", "ramping"):
            sub = df[df["ramp_status"] == status]
            denom = float(sub["capacity_day_quota"].sum())
            out[f"{status}_rep_quarters"] = int(len(sub))
            out[f"{status}_attainment"] = float(sub["won_arr"].sum() / denom) if denom else np.nan
        out["empirical_ramp_ratio"] = (
            out["ramping_attainment"] / out["ramped_attainment"]
            if out["ramped_attainment"] else np.nan
        )
        return out

    rows = [_one(panel, "All", "All")]
    for (segment, rep_type), g in panel.groupby(["segment", "rep_type"]):
        rows.append(_one(g, segment, rep_type))
    return pd.DataFrame(rows)


def check_ramp_mechanism_is_real(as_of_date: date, effect: pd.DataFrame = None,
                                 con=None) -> dict:
    """Non-vacuousness check, and the reason this artifact is not just an
    assertion dressed as a model: the 0.50 discount is only meaningful if
    ramping reps in the real generated data genuinely produce less than
    ramped ones. Requires, for every team and pooled, a positive but
    materially depressed ramping/ramped ratio -- strictly above 0 (the
    mechanism is not total) and at or below _MAX_VACUOUS_RAMP_RATIO (the
    mechanism is not cosmetic). This mirrors the QA plan's Test C
    requirement that ramping reps show "measurably lower win rate than
    ramped reps, but not zero."""
    effect = measure_empirical_ramp_effect(as_of_date, con=con) if effect is None else effect
    if effect.empty:
        return {"all_pass": False, "detail": effect}
    detail = effect.copy()
    detail["passes"] = (
        (detail["empirical_ramp_ratio"] > 0)
        & (detail["empirical_ramp_ratio"] <= _MAX_VACUOUS_RAMP_RATIO)
    )
    return {
        "max_vacuous_ratio": _MAX_VACUOUS_RAMP_RATIO,
        "detail": detail[["segment", "rep_type", "ramped_attainment", "ramping_attainment",
                          "ramped_rep_quarters", "ramping_rep_quarters",
                          "empirical_ramp_ratio", "passes"]],
        "all_pass": bool(detail["passes"].all()),
    }


def check_ramp_discount_reconciles(as_of_date: date, effect: pd.DataFrame = None,
                                   con=None) -> dict:
    """Confirms the adopted _RAMP_CAPACITY_DISCOUNT is consistent with
    what the data actually shows, rather than a third number invented
    alongside the build spec's ~50% assumption and the generator's
    RAMPING_REP_WIN_ASSIGNMENT_FACTOR = 0.55. Checks the pooled,
    capacity-day-weighted empirical ratio against 0.50 within
    _RAMP_RATIO_TOLERANCE."""
    effect = measure_empirical_ramp_effect(as_of_date, con=con) if effect is None else effect
    if effect.empty:
        return {"reconciles": False}
    pooled = effect[(effect["segment"] == "All") & (effect["rep_type"] == "All")].iloc[0]
    observed = float(pooled["empirical_ramp_ratio"])
    return {
        "applied_discount": _RAMP_CAPACITY_DISCOUNT,
        "generator_win_assignment_factor": 0.55,
        "observed_pooled_ratio": observed,
        "abs_diff": abs(observed - _RAMP_CAPACITY_DISCOUNT),
        "tolerance": _RAMP_RATIO_TOLERANCE,
        "ramping_rep_quarters": int(pooled["ramping_rep_quarters"]),
        "reconciles": abs(observed - _RAMP_CAPACITY_DISCOUNT) <= _RAMP_RATIO_TOLERANCE,
    }


def run_build_time_validation(as_of_date: date, mode: str = "as_of_date",
                              log: bool = True) -> dict:
    """End-to-end build-time computation and correctness check: the
    rep-quarter panel, attainment by rep_type x segment x quarter and
    company-wide, the empirical ramped baseline, ramp-adjusted expected
    capacity, the quota-achievability assessment with its three-way gap
    decomposition, and four checks -- two structural tie-outs plus the
    ramp-mechanism and ramp-discount reconciliations. Everything
    analytics-model-validator needs to independently recompute this
    artifact's correctness claims.

    Logs the natural scalar time-series metrics to
    fact_model_performance_history via analytics/model_performance.py when
    log=True; the variable-width tables (attainment by team-quarter,
    achievability detail, ramp-effect breakdown) do not fit that log's
    flat scalar grain and are recorded as structured detail in
    docs/acme-corp-analytics-methods.md instead.
    """
    con = _connect()
    try:
        panel = build_rep_quarter_panel(as_of_date, con=con)
        supply = load_opportunity_supply_window(as_of_date, con=con)
        first_quarter = supply["first_opportunity_quarter"]
        attainment = compute_attainment(as_of_date, panel=panel, con=con)
        baseline = compute_ramped_baseline(as_of_date, panel=panel, mode=mode, con=con)
        capacity = compute_expected_capacity(as_of_date, panel=panel, baseline=baseline, con=con)
        achievability = assess_quota_achievability(
            as_of_date, capacity=capacity, first_opportunity_quarter=first_quarter, con=con
        )
        baseline_fwd = compute_ramped_baseline(
            as_of_date, panel=panel, mode="prior_quarters_only", con=con
        )
        achievability_fwd = assess_quota_achievability(
            as_of_date,
            capacity=compute_expected_capacity(
                as_of_date, panel=panel, baseline=baseline_fwd, con=con
            ),
            first_opportunity_quarter=first_quarter,
            con=con,
        )
        effect = measure_empirical_ramp_effect(as_of_date, panel=panel, con=con)
        source_tie_out = reconcile_attainment_to_source(as_of_date, panel=panel, con=con)
        decomposition_tie_out = reconcile_capacity_decomposition(
            as_of_date, achievability=achievability, con=con
        )
        # Also reconciled in prior_quarters_only mode -- the earlier check
        # above only exercises the default (as_of_date) baseline, which
        # never leaves a rep's baseline_attainment NaN. prior_quarters_only
        # does, whenever fewer than _MIN_BASELINE_REP_QUARTERS ramped
        # rep-quarters have accumulated for a rep, and that NaN has to
        # poison the team-quarter's aggregate rather than get silently
        # dropped by skipna=True -- this is the check that would have
        # caught that failure mode before it shipped.
        decomposition_tie_out_fwd = reconcile_capacity_decomposition(
            as_of_date, achievability=achievability_fwd, con=con
        )
        mechanism = check_ramp_mechanism_is_real(as_of_date, effect=effect, con=con)
        discount = check_ramp_discount_reconciles(as_of_date, effect=effect, con=con)
    finally:
        con.close()

    checks = [
        {"name": "attainment_reconciles_to_fact_opportunities",
         "passed": bool(source_tie_out["reconciles"]),
         "detail": f"max abs diff ${source_tie_out['max_abs_diff_usd']:.4f}"},
        {"name": "capacity_gap_decomposition_is_exact",
         "passed": bool(decomposition_tie_out["reconciles"]),
         "detail": f"max abs diff ${decomposition_tie_out['max_abs_diff_usd']:.6f}"},
        {"name": "capacity_gap_decomposition_is_exact_prior_quarters_only",
         "passed": bool(decomposition_tie_out_fwd["reconciles"]),
         "detail": f"max abs diff ${decomposition_tie_out_fwd['max_abs_diff_usd']:.6f}"},
        {"name": "ramp_mechanism_is_real_not_vacuous",
         "passed": bool(mechanism["all_pass"]),
         "detail": f"all teams' ramping/ramped ratio in (0, {_MAX_VACUOUS_RAMP_RATIO}]"},
        {"name": "ramp_discount_reconciles_to_observed",
         "passed": bool(discount["reconciles"]),
         "detail": f"observed pooled ratio {discount.get('observed_pooled_ratio', float('nan')):.4f} "
                   f"vs. applied {_RAMP_CAPACITY_DISCOUNT} (tol +/-{_RAMP_RATIO_TOLERANCE})"},
    ]
    checks_passed = sum(1 for c in checks if c["passed"])

    # Summary counts are scoped to quarters where a market actually
    # existed -- a quarter with quota-bearing reps and no opportunity
    # supply at all is a data-window artifact, not a capacity finding.
    teams = achievability[
        (achievability["segment"] != "All") & achievability["has_opportunity_supply"]
    ]

    if log:
        company = achievability[
            (achievability["segment"] == "All") & achievability["has_opportunity_supply"]
        ].sort_values("quarter")
        pooled = effect[(effect["segment"] == "All") & (effect["rep_type"] == "All")].iloc[0]

        log_performance(_MODEL_NAME, as_of_date, "structural_checks_total", float(len(checks)))
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_passed", float(checks_passed))
        log_performance(_MODEL_NAME, as_of_date, "ramp_capacity_discount_applied", _RAMP_CAPACITY_DISCOUNT)
        log_performance(_MODEL_NAME, as_of_date, "achievability_margin", _ACHIEVABILITY_MARGIN)
        log_performance(_MODEL_NAME, as_of_date, "empirical_ramp_ratio_pooled",
                        float(pooled["empirical_ramp_ratio"]))
        log_performance(_MODEL_NAME, as_of_date, "ramped_baseline_attainment_pooled",
                        float(pooled["ramped_attainment"]))
        log_performance(_MODEL_NAME, as_of_date, "ramping_rep_quarters_pooled",
                        float(pooled["ramping_rep_quarters"]))
        log_performance(_MODEL_NAME, as_of_date, "ramped_rep_quarters_pooled",
                        float(pooled["ramped_rep_quarters"]))

        for _, row in effect[effect["rep_type"] != "All"].iterrows():
            key = row["rep_type"].lower()
            log_performance(_MODEL_NAME, as_of_date, f"ramped_baseline_attainment_{key}",
                            float(row["ramped_attainment"]))
            log_performance(_MODEL_NAME, as_of_date, f"empirical_ramp_ratio_{key}",
                            float(row["empirical_ramp_ratio"]))

        log_performance(_MODEL_NAME, as_of_date, "team_quarters_evaluated", float(len(teams)))
        log_performance(_MODEL_NAME, as_of_date, "team_quarters_quota_not_achievable",
                        float((~teams["quota_achievable"]).sum()))
        log_performance(_MODEL_NAME, as_of_date, "team_quarters_ramp_mix_breaches_margin",
                        float(teams["ramp_mix_breaches_margin"].sum()))
        log_performance(_MODEL_NAME, as_of_date, "max_ramp_attributable_gap_pct",
                        float(teams["ramp_attributable_gap_pct"].max()))
        if len(company):
            latest = company.iloc[-1]
            log_performance(_MODEL_NAME, as_of_date, "company_quota_coverage_ratio_latest_quarter",
                            float(latest["quota_coverage_ratio"]))
            log_performance(_MODEL_NAME, as_of_date, "company_ramp_capacity_haircut_latest_quarter",
                            float(latest["ramp_capacity_haircut"]))
        company_attainment = attainment[attainment["segment"] == "All"].sort_values("quarter")
        if len(company_attainment):
            log_performance(_MODEL_NAME, as_of_date, "company_attainment_latest_quarter",
                            float(company_attainment.iloc[-1]["attainment"]))
        log_performance(_MODEL_NAME, as_of_date, "attainment_reconciliation_max_abs_diff_usd",
                        float(source_tie_out["max_abs_diff_usd"]))
        log_performance(_MODEL_NAME, as_of_date, "capacity_decomposition_max_abs_diff_usd",
                        float(decomposition_tie_out["max_abs_diff_usd"]))

    return {
        "rep_quarter_panel": panel,
        "attainment": attainment,
        "ramped_baseline": baseline,
        "expected_capacity": capacity,
        "achievability": achievability,
        "achievability_prior_quarters_only": achievability_fwd,
        "empirical_ramp_effect": effect,
        "source_tie_out": source_tie_out,
        "decomposition_tie_out": decomposition_tie_out,
        "ramp_mechanism_check": mechanism,
        "ramp_discount_check": discount,
        "data_window": {
            "as_of_date": as_of_date,
            "first_opportunity_quarter": first_quarter,
            "quarters_without_opportunity_supply": int(
                (~achievability.loc[achievability["segment"] == "All",
                                    "has_opportunity_supply"]).sum()
            ),
            "team_quarters_evaluated": int(len(teams)),
            "team_quarters_quota_not_achievable": int((~teams["quota_achievable"]).sum()),
            "team_quarters_ramp_mix_breaches_margin": int(
                teams["ramp_mix_breaches_margin"].sum()
            ),
            "max_ramp_attributable_gap_pct": float(teams["ramp_attributable_gap_pct"].max()),
        },
        "checks": checks,
        "checks_passed": checks_passed,
        "checks_total": len(checks),
    }


if __name__ == "__main__":
    result = run_build_time_validation(date(2025, 12, 31))

    att = result["attainment"]
    print("Quota attainment by rep_type x segment x quarter (last 8 quarters):")
    cols = ["quarter", "segment", "rep_type", "reps", "ramping_reps", "stated_quota",
            "won_arr", "attainment"]
    print(att[att["segment"] != "All"].tail(16)[cols].to_string(index=False))
    print()
    print("Company-wide attainment by quarter:")
    print(att[att["segment"] == "All"][cols].to_string(index=False))
    print()
    print("Empirical ramp effect (capacity-day weighted):")
    print(result["empirical_ramp_effect"].to_string(index=False))
    print()
    print("Data window:", result["data_window"])
    print()
    print("Quota achievability (company-wide, quarters with opportunity supply):")
    ach = result["achievability"]
    acols = ["quarter", "segment", "rep_type", "reps", "ramping_reps", "stated_quota",
             "expected_capacity", "quota_coverage_ratio", "quota_gap_pct",
             "ramp_attributable_gap_pct", "ramp_capacity_haircut", "quota_achievable",
             "ramp_mix_breaches_margin"]
    print(ach[(ach["segment"] == "All") & ach["has_opportunity_supply"]][acols].to_string(index=False))
    print()
    print("Quota achievability by team (last 8 team-quarters):")
    print(ach[ach["segment"] != "All"].tail(8)[acols].to_string(index=False))
    print()
    print("Gap decomposition (company-wide, last 4 quarters):")
    dcols = ["quarter", "stated_quota", "expected_capacity", "productivity_gap",
             "coverage_gap", "ramp_mix_gap"]
    print(ach[ach["segment"] == "All"].tail(4)[dcols].to_string(index=False))
    print()
    for check in result["checks"]:
        print(f"[{'PASS' if check['passed'] else 'FAIL'}] {check['name']}: {check['detail']}")
    print(f"{result['checks_passed']} of {result['checks_total']} checks pass")
