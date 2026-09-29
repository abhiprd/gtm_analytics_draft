"""Retention / expansion cohort analytics -- descriptive, population-level
view by acquisition vintage (build spec item #20). Grain: one row per
(signup-quarter cohort x entry segment) per months-since-acquisition for
the logo-retention and revenue-retention "cohort triangles"; one row per
entry_segment (or channel) per months-since-acquisition for the coarser
pooled cross-cut curves. Source marts: dim_accounts (signup_date, channel),
fact_account_segment_history (entry segment, via is_initial_segment),
fact_revenue_monthly (mrr, account-month presence -- a churned account's
rows simply stop, there is no ongoing $0 row).

Distinct from two sibling artifacts, stated explicitly per this project's
convention of naming that relationship rather than leaving it implicit:

- Segment migration analysis (analytics/segment_migration.py) is an
  EVENT lens: which accounts moved segment, when, why, and how much MRR
  they carried with them. This module is a COHORT lens: population-level
  survival/revenue-retention curves anchored to acquisition vintage,
  independent of whether an account ever migrated. The two do not
  duplicate each other's numbers. In fact this module's revenue-retention
  curve deliberately does NOT follow mart_durability's segment-level
  convention of excluding migration-driven MRR change from the source
  segment's own NRR/GRR (reported separately there as "graduated
  revenue") -- a cohort here is defined by ACCOUNT IDENTITY at entry, not
  by current segment, so an account that migrates and grows is still the
  same cohort member growing, and its higher post-migration MRR is
  correctly part of its cohort's revenue trajectory. Logo retention is
  unaffected by migration either way in both artifacts, per the build
  spec ("the account persists, just at a different segment").
- Account health score (analytics/health_score.py) is PREDICTIVE and
  ACCOUNT-level (will *this specific* account churn, scored today). This
  module is DESCRIPTIVE and POPULATION-level (what does the *typical*
  account in a given acquisition cohort look like over elapsed time) --
  the build spec's own stated distinction (item #20 vs. item #4). No
  churn classifier lives here; there is nothing to fit, no train/test
  split, no probability.

No stochastic step exists anywhere in this module (no train/test split,
no sampling, no simulation) -- every function is a direct, deterministic
aggregation over already-generated mart data, so no random seed applies,
matching analytics/segment_migration.py's precedent.
"""
import os
from datetime import date

import duckdb
import numpy as np
import pandas as pd

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_MODEL_NAME = "retention_expansion_cohort_analytics"

_ENTRY_SEGMENTS = ["SMB", "Commercial", "Enterprise"]

# Reference elapsed-month mark used for the benchmark-grounding check
# below -- 36 months (3 years) since acquisition, NOT 12. This data wires
# Commercial/Enterprise churn to actual contract-term ends (build spec:
# "Commercial/Enterprise: ... churn (non-renewal)"), and the pooled curves
# below show that structure directly: Commercial's cumulative logo
# retention sits at a flat 100% through elapsed month 12 then drops off a
# cliff starting month 13 (its annual contract's first renewal decision);
# Enterprise sits flat at 100% through month 24 then cliffs at month 25
# (its multi-year term's first renewal decision). A 12-months-since-
# acquisition mark would therefore read both segments' churn as
# structurally zero -- a contract-term ceiling artifact, not a genuine
# retention reading. 36 is the smallest round (12-month-increment) mark
# that clears BOTH segments' first observed renewal cliff, so every
# segment's checked figure reflects a genuine churn opportunity having
# occurred, not an unexpired-contract ceiling.
_BENCHMARK_ELAPSED_MONTHS = 36

# docs/acme-corp-phase1-data-qa-plan.md's benchmark reference table, "Logo
# retention (annual)" row -- the one benchmark row that is directly
# comparable to this module's logo-retention curve, since (per
# dbt/models/marts/marts/mart_durability.sql's own comment) logo retention
# counts a migrating account as retained in both places, so no
# migration-accounting divergence exists for this specific row the way
# there is for NRR/GRR (see below).
_BENCHMARK_LOGO_RETENTION_ANNUAL = {
    "SMB": (0.75, 0.85),
    "Commercial": (0.88, 0.93),
    "Enterprise": (0.93, 0.97),
}

# PROPOSED, not yet confirmed (see docs/acme-corp-analytics-methods.md's
# Retention/expansion cohort analytics entry) -- a +/-5 percentage point
# buffer applied on top of the QA plan's stated range before flagging a
# miss. This module's elapsed-12-months logo retention (a from-acquisition
# cumulative survival rate, pooled across vintages via the at-risk method
# below) and the QA plan's "annual logo retention" benchmark are RELATED
# but not definitionally identical constructs -- the benchmark likely
# describes a trailing-12-month calendar-anchored rate on a segment's whole
# population (mart_durability's own logo_retention_rate is a MONTHLY
# retained/starting ratio; the benchmark table's annual figure is that
# compounded, per analytics/segment_migration.py's precedent of deriving
# monthly shares from an annual GRR/NRR figure), while this module's figure
# is a from-acquisition cohort curve. 5pp is proposed as wide enough to
# absorb that definitional gap without being so wide it could never catch
# a genuine miscalibration.
_BENCHMARK_TOLERANCE_PP = 0.05

# Reconciliation tolerance for the two structural exact-match checks below
# -- both compare two independently-computed integer/float quantities that
# should match exactly (same underlying facts, two computation paths), so
# any gap beyond floating-point noise is a real bug.
_RECONCILIATION_TOLERANCE = 1e-9


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


def _quarter_start(ts: pd.Series) -> pd.Series:
    """Vectorized quarter-start-of-month, matching DuckDB's
    date_trunc('quarter', ...) exactly -- used so the pandas-side cohort
    assembly and the SQL-side independent reconciliation queries below
    agree on quarter boundaries."""
    q_month = ((ts.dt.month - 1) // 3) * 3 + 1
    return pd.to_datetime({"year": ts.dt.year, "month": q_month, "day": 1})


def load_cohort_accounts(as_of_date: date, con=None) -> pd.DataFrame:
    """One row per account whose signup_date <= as_of_date (no leakage
    from future cohorts). entry_segment comes from
    fact_account_segment_history's is_initial_segment row -- the segment
    at ACCOUNT CREATION -- not dim_accounts.segment, which is the
    account's CURRENT, possibly-migrated segment. Source marts:
    dim_accounts, fact_account_segment_history."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            """
            with entry as (
                select account_id, segment as entry_segment
                from main_marts.fact_account_segment_history
                where is_initial_segment and effective_date <= ?
            )
            select
                a.account_id,
                a.signup_date,
                a.channel,
                e.entry_segment
            from main_marts.dim_accounts a
            join entry e on e.account_id = a.account_id
            where a.signup_date <= ?
            """,
            [as_of_date, as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()

    df["signup_date"] = pd.to_datetime(df["signup_date"])
    df["account_month0"] = df["signup_date"].values.astype("datetime64[M]")
    df["cohort_quarter"] = _quarter_start(df["signup_date"])

    as_of_month0 = pd.Timestamp(as_of_date).to_period("M").to_timestamp()
    df["account_max_elapsed_months"] = (
        (as_of_month0.year - df["account_month0"].dt.year) * 12
        + (as_of_month0.month - df["account_month0"].dt.month)
    )
    return df


def load_account_revenue(as_of_date: date, con=None) -> pd.DataFrame:
    """One row per account_id per month with mrr, month <= as_of_date.
    Source mart: fact_revenue_monthly. Presence (not a $0 row) is how
    churn shows up here -- a churned account's rows simply stop at its
    last active month (confirmed contiguous, no gaps, for every account
    in this data -- see the Retention/expansion cohort analytics entry in
    docs/acme-corp-analytics-methods.md)."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select account_id, month, mrr from main_marts.fact_revenue_monthly where month <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    return df


def _build_panel(as_of_date: date, con=None):
    """Returns (accounts, revenue_elapsed): accounts is
    load_cohort_accounts' output; revenue_elapsed adds elapsed_months
    (months between the account's OWN signup month and the revenue row's
    month) to each (account_id, month, mrr) row -- elapsed_months is
    computed relative to each account's own signup month, not the
    cohort's nominal quarter-start, so a late-in-quarter signup's
    pre-existence period is never mistaken for early non-activity."""
    accounts = load_cohort_accounts(as_of_date, con=con)
    revenue = load_account_revenue(as_of_date, con=con)
    merged = revenue.merge(accounts[["account_id", "account_month0"]], on="account_id", how="inner")
    merged["elapsed_months"] = (
        (merged["month"].dt.year - merged["account_month0"].dt.year) * 12
        + (merged["month"].dt.month - merged["account_month0"].dt.month)
    )
    return accounts, merged[["account_id", "elapsed_months", "mrr"]]


def compute_cohort_definition(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per (cohort_quarter, entry_segment). cohort_size is
    the vintage's fixed month-0 population (no new logos ever enter a
    cohort after month 0, per the build spec's fixed-population framing).
    cohort_max_observable_elapsed_months = MIN of every member account's
    own account_max_elapsed_months -- the honest right-censoring cap: the
    cohort's curve is reported only out to whatever elapsed month its
    YOUNGEST member (the last account to sign up that quarter) has
    actually reached as of as_of_date, so every reported column reflects
    the cohort's full, fixed membership -- no member silently drops out
    of the denominator as elapsed grows."""
    accounts = load_cohort_accounts(as_of_date, con=con)
    grouped = accounts.groupby(["cohort_quarter", "entry_segment"]).agg(
        cohort_size=("account_id", "nunique"),
        min_signup_date=("signup_date", "min"),
        max_signup_date=("signup_date", "max"),
        cohort_max_observable_elapsed_months=("account_max_elapsed_months", "min"),
    ).reset_index()
    return grouped


def compute_logo_retention_triangle(as_of_date: date, con=None) -> pd.DataFrame:
    """The logo-retention cohort triangle -- grain: one row per
    (cohort_quarter, entry_segment, elapsed_months), elapsed_months
    ranging 0..cohort_max_observable_elapsed_months for that cohort only
    (right-censored columns are simply absent, never extrapolated or
    silently truncated). active_count = accounts in that cohort still
    present in fact_revenue_monthly at that elapsed month; a migrating
    account counts as active/retained (per mart_durability's own
    precedent -- "the account persists, just at a different segment").
    Source marts: dim_accounts, fact_account_segment_history,
    fact_revenue_monthly."""
    accounts, revenue_elapsed = _build_panel(as_of_date, con=con)
    cohort_def = compute_cohort_definition(as_of_date, con=con)

    active = revenue_elapsed.merge(
        accounts[["account_id", "cohort_quarter", "entry_segment"]], on="account_id"
    )
    active_counts = (
        active.groupby(["cohort_quarter", "entry_segment", "elapsed_months"])["account_id"]
        .nunique()
        .rename("active_count")
        .reset_index()
    )

    # Full triangle grid: every (cohort, elapsed) pair from 0 up to that
    # cohort's own censoring cap, so an elapsed month with zero survivors
    # is an explicit 0 row, not a silently-missing one.
    grid = cohort_def.loc[
        cohort_def.index.repeat(cohort_def["cohort_max_observable_elapsed_months"] + 1)
    ].copy()
    grid["elapsed_months"] = grid.groupby(["cohort_quarter", "entry_segment"]).cumcount()

    triangle = grid.merge(active_counts, on=["cohort_quarter", "entry_segment", "elapsed_months"], how="left")
    triangle["active_count"] = triangle["active_count"].fillna(0).astype(int)
    triangle["logo_retention_rate"] = triangle["active_count"] / triangle["cohort_size"]
    return triangle.sort_values(["entry_segment", "cohort_quarter", "elapsed_months"]).reset_index(drop=True)


def compute_revenue_retention_triangle(as_of_date: date, con=None) -> pd.DataFrame:
    """The revenue-retention cohort triangle (NRR/GRR-style but
    cohort-anchored, not calendar-anchored) -- same grain and same
    right-censoring cap as compute_logo_retention_triangle. total_mrr at
    elapsed N is the sum of mrr across every cohort member still active
    (churned members implicitly contribute $0, they simply have no row).
    revenue_retention_rate = total_mrr(N) / total_mrr(0).

    Also carries the logo-driven vs. expansion-driven decomposition:
    revenue_retention_rate == logo_retention_rate * expansion_factor,
    where expansion_factor is the change in average MRR PER SURVIVING
    ACCOUNT relative to month 0 -- this isolates "how many logos are left"
    from "how much is each surviving logo worth now" (which folds in
    organic usage growth/contraction AND migration-driven contract
    growth, by this module's account-identity-anchored design -- see the
    module docstring). Source marts: same as the logo triangle."""
    accounts, revenue_elapsed = _build_panel(as_of_date, con=con)
    cohort_def = compute_cohort_definition(as_of_date, con=con)

    active = revenue_elapsed.merge(
        accounts[["account_id", "cohort_quarter", "entry_segment"]], on="account_id"
    )
    cell_stats = (
        active.groupby(["cohort_quarter", "entry_segment", "elapsed_months"])
        .agg(active_count=("account_id", "nunique"), total_mrr=("mrr", "sum"))
        .reset_index()
    )

    grid = cohort_def.loc[
        cohort_def.index.repeat(cohort_def["cohort_max_observable_elapsed_months"] + 1)
    ].copy()
    grid["elapsed_months"] = grid.groupby(["cohort_quarter", "entry_segment"]).cumcount()

    triangle = grid.merge(cell_stats, on=["cohort_quarter", "entry_segment", "elapsed_months"], how="left")
    triangle["active_count"] = triangle["active_count"].fillna(0).astype(int)
    triangle["total_mrr"] = triangle["total_mrr"].fillna(0.0)
    triangle["logo_retention_rate"] = triangle["active_count"] / triangle["cohort_size"]

    month0 = triangle.loc[triangle["elapsed_months"] == 0, ["cohort_quarter", "entry_segment", "total_mrr"]]
    month0 = month0.rename(columns={"total_mrr": "month0_mrr"})
    triangle = triangle.merge(month0, on=["cohort_quarter", "entry_segment"], how="left")
    triangle["revenue_retention_rate"] = np.where(
        triangle["month0_mrr"] > 0, triangle["total_mrr"] / triangle["month0_mrr"], np.nan
    )

    triangle["avg_mrr_per_active_account"] = np.where(
        triangle["active_count"] > 0, triangle["total_mrr"] / triangle["active_count"], np.nan
    )
    avg_mrr_month0 = triangle.loc[triangle["elapsed_months"] == 0, ["cohort_quarter", "entry_segment", "avg_mrr_per_active_account"]]
    avg_mrr_month0 = avg_mrr_month0.rename(columns={"avg_mrr_per_active_account": "avg_mrr_per_active_account_month0"})
    triangle = triangle.merge(avg_mrr_month0, on=["cohort_quarter", "entry_segment"], how="left")
    triangle["expansion_factor"] = np.where(
        triangle["avg_mrr_per_active_account_month0"] > 0,
        triangle["avg_mrr_per_active_account"] / triangle["avg_mrr_per_active_account_month0"],
        np.nan,
    )
    triangle["revenue_retention_rate_from_decomposition"] = triangle["logo_retention_rate"] * triangle["expansion_factor"]

    return triangle.sort_values(["entry_segment", "cohort_quarter", "elapsed_months"]).reset_index(drop=True)


def _pooled_curve(accounts: pd.DataFrame, revenue_elapsed: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Shared pooled-curve engine for the entry_segment and channel
    cross-cuts, which each span MANY acquisition vintages of different
    ages. Deliberately a DIFFERENT censoring convention than the
    quarter-level triangle above: here, at each elapsed month N, the
    population at risk is every account (in that group) old enough to
    have reached N (account_max_elapsed_months >= N) -- a shrinking
    "number at risk" set, the standard survival-curve convention, not the
    triangle's whole-fixed-cohort-membership convention. This is the
    correct convention for a curve that pools across vintages of
    different ages: restricting a coarse pooled group to full-membership
    consistency would mean the whole group's curve could never extend
    past its single YOUNGEST vintage's censoring cap, discarding real
    signal from every older vintage."""
    active = revenue_elapsed.merge(accounts[["account_id", group_col]], on="account_id")
    rows = []
    for group_value, grp_accounts in accounts.groupby(group_col):
        max_elapsed = int(grp_accounts["account_max_elapsed_months"].max())
        grp_active = active[active[group_col] == group_value]
        max_elapsed_sorted = np.sort(grp_accounts["account_max_elapsed_months"].values)
        n_accounts_total = len(max_elapsed_sorted)

        by_elapsed = grp_active.groupby("elapsed_months").agg(
            active_count=("account_id", "nunique"), total_mrr=("mrr", "sum")
        )
        month0_mrr = float(by_elapsed["total_mrr"].get(0, 0.0))

        for n in range(0, max_elapsed + 1):
            # Accounts old enough to have reached elapsed month n as of
            # as_of_date -- the at-risk population, via a sorted-array
            # search rather than a per-row boolean filter each loop.
            n_at_risk = int(n_accounts_total - np.searchsorted(max_elapsed_sorted, n, side="left"))
            active_count = int(by_elapsed["active_count"].get(n, 0))
            total_mrr = float(by_elapsed["total_mrr"].get(n, 0.0))
            rows.append({
                group_col: group_value,
                "elapsed_months": n,
                "n_accounts_at_risk": n_at_risk,
                "active_count": active_count,
                "logo_retention_rate": (active_count / n_at_risk) if n_at_risk else np.nan,
                "total_mrr": total_mrr,
                "month0_mrr_pooled": month0_mrr,
                "revenue_retention_rate": (total_mrr / month0_mrr) if month0_mrr > 0 else np.nan,
            })
    return pd.DataFrame(rows)


def compute_pooled_curve_by_segment(as_of_date: date, con=None) -> pd.DataFrame:
    """Pooled logo/revenue retention curves by entry_segment, across ALL
    acquisition vintages (not crossed with cohort_quarter -- see
    _pooled_curve's at-risk convention). Grain: one row per entry_segment
    per elapsed_months. This is the primary segment-level differentiation
    cut the task calls for. Source marts: same as the triangles."""
    accounts, revenue_elapsed = _build_panel(as_of_date, con=con)
    return _pooled_curve(accounts, revenue_elapsed, "entry_segment").sort_values(
        ["entry_segment", "elapsed_months"]
    ).reset_index(drop=True)


def compute_pooled_curve_by_channel(as_of_date: date, con=None) -> pd.DataFrame:
    """Pooled logo/revenue retention curves by acquisition channel,
    across ALL entry segments and vintages (channel and segment are
    orthogonal per this project's invariants, so this is a separate cut,
    not crossed with entry_segment -- crossing the two would leave cells
    as thin as 18 total accounts for outbound_sdr). Grain: one row per
    channel per elapsed_months. Source marts: same as the triangles."""
    accounts, revenue_elapsed = _build_panel(as_of_date, con=con)
    return _pooled_curve(accounts, revenue_elapsed, "channel").sort_values(
        ["channel", "elapsed_months"]
    ).reset_index(drop=True)


# ---------------------------------------------------------------------
# Validation -- structural/descriptive artifact (see module docstring and
# docs/acme-corp-analytics-methods.md's entry): no accuracy/error target
# applies. Two exact structural reconciliations (independent recomputation
# of the same quantity via a separate code path) and one benchmark-
# grounded non-vacuousness check, per analytics-engineering-conventions'
# "Structural/logic artifacts" category.
# ---------------------------------------------------------------------

def validate_cohort_population_reconciliation(as_of_date: date, con=None) -> dict:
    """Structural check: each cohort's month-0 population count
    (compute_cohort_definition's cohort_size, built via pandas
    groupby over load_cohort_accounts) must match an INDEPENDENTLY
    computed count -- a fresh SQL group-by using DuckDB's own
    date_trunc('quarter', ...) rather than this module's pandas
    quarter-start arithmetic. Any gap beyond floating-point noise means
    the two date-truncation implementations disagree or an account was
    gained/lost somewhere in the pandas assembly -- a real bug either
    way, not statistical drift."""
    owns_con = con is None
    con = con or _connect()
    try:
        sql_counts = con.execute(
            """
            with entry as (
                select account_id, segment as entry_segment
                from main_marts.fact_account_segment_history
                where is_initial_segment and effective_date <= ?
            )
            select
                date_trunc('quarter', a.signup_date) as cohort_quarter,
                e.entry_segment,
                count(*) as cohort_size_sql
            from main_marts.dim_accounts a
            join entry e on e.account_id = a.account_id
            where a.signup_date <= ?
            group by 1, 2
            """,
            [as_of_date, as_of_date],
        ).df()
        cohort_def = compute_cohort_definition(as_of_date, con=con)
    finally:
        if owns_con:
            con.close()

    sql_counts["cohort_quarter"] = pd.to_datetime(sql_counts["cohort_quarter"])
    merged = cohort_def.merge(sql_counts, on=["cohort_quarter", "entry_segment"], how="outer")
    merged["cohort_size"] = merged["cohort_size"].fillna(0)
    merged["cohort_size_sql"] = merged["cohort_size_sql"].fillna(0)
    diff = (merged["cohort_size"] - merged["cohort_size_sql"]).abs()

    return {
        "max_abs_diff": float(diff.max()) if len(diff) else 0.0,
        "tolerance": _RECONCILIATION_TOLERANCE,
        "reconciles": bool((diff <= _RECONCILIATION_TOLERANCE).all()),
        "n_cohorts_checked": int(len(merged)),
    }


def validate_active_count_reconciliation(as_of_date: date, con=None) -> dict:
    """Structural check: every (cohort_quarter, entry_segment,
    elapsed_months) cell's active_count in compute_logo_retention_triangle
    (built via a pandas merge/groupby pipeline) must match an
    INDEPENDENTLY computed active_count -- a single SQL query using
    DuckDB's own datediff('month', ...) for elapsed_months, an entirely
    separate implementation of the same date arithmetic. Since
    cohort_size is independently reconciled above and active_count is
    independently reconciled here, the task's 'active + churned =
    cohort_size, no accounts gained or lost' invariant is validated
    end-to-end through these two independent reconciliations rather than
    needing a third, redundant anti-join check: churned_count is
    arithmetically cohort_size - active_count, and both terms are now
    pinned by a separate computation path each."""
    owns_con = con is None
    con = con or _connect()
    try:
        sql_active = con.execute(
            """
            with entry as (
                select account_id, segment as entry_segment
                from main_marts.fact_account_segment_history
                where is_initial_segment and effective_date <= ?
            ),
            accts as (
                select a.account_id, e.entry_segment,
                       date_trunc('month', a.signup_date) as account_month0,
                       date_trunc('quarter', a.signup_date) as cohort_quarter
                from main_marts.dim_accounts a
                join entry e on e.account_id = a.account_id
                where a.signup_date <= ?
            ),
            rev as (
                select account_id, month from main_marts.fact_revenue_monthly where month <= ?
            )
            select
                acc.cohort_quarter,
                acc.entry_segment,
                datediff('month', acc.account_month0, r.month) as elapsed_months,
                count(distinct r.account_id) as active_count_sql
            from accts acc
            join rev r on r.account_id = acc.account_id
            group by 1, 2, 3
            """,
            [as_of_date, as_of_date, as_of_date],
        ).df()
        triangle = compute_logo_retention_triangle(as_of_date, con=con)
    finally:
        if owns_con:
            con.close()

    sql_active["cohort_quarter"] = pd.to_datetime(sql_active["cohort_quarter"])
    merged = triangle.merge(
        sql_active, on=["cohort_quarter", "entry_segment", "elapsed_months"], how="left"
    )
    merged["active_count_sql"] = merged["active_count_sql"].fillna(0)
    diff = (merged["active_count"] - merged["active_count_sql"]).abs()

    return {
        "max_abs_diff": float(diff.max()) if len(diff) else 0.0,
        "tolerance": _RECONCILIATION_TOLERANCE,
        "reconciles": bool((diff <= _RECONCILIATION_TOLERANCE).all()),
        "n_cells_checked": int(len(merged)),
    }


def validate_revenue_decomposition_identity(as_of_date: date, con=None) -> dict:
    """Structural check: revenue_retention_rate ==
    logo_retention_rate * expansion_factor for every triangle cell, an
    exact arithmetic identity by construction -- any gap beyond
    floating-point noise is a real bug in the decomposition, not model
    drift. Mirrors capacity_planning's gap-decomposition tie-out."""
    triangle = compute_revenue_retention_triangle(as_of_date, con=con)
    comparable = triangle[triangle["month0_mrr"] > 0].copy()
    diff = (comparable["revenue_retention_rate"] - comparable["revenue_retention_rate_from_decomposition"]).abs()
    return {
        "max_abs_diff": float(diff.max()) if len(diff) else 0.0,
        "tolerance": _RECONCILIATION_TOLERANCE,
        "reconciles": bool((diff <= _RECONCILIATION_TOLERANCE).all()),
        "n_cells_checked": int(len(comparable)),
    }


def validate_benchmark_grounding(as_of_date: date, con=None,
                                  elapsed_months: int = _BENCHMARK_ELAPSED_MONTHS,
                                  tolerance_pp: float = _BENCHMARK_TOLERANCE_PP) -> dict:
    """Non-vacuousness check, evaluated at elapsed_months=36 (see the
    module-level comment on _BENCHMARK_ELAPSED_MONTHS for why not 12):
    (1) pooled logo retention must be measurably ordered
    Enterprise > Commercial > SMB -- confirming retention genuinely
    differs by entry segment in this data, a real checkable relationship,
    not decoration; (2) each segment's cumulative logo retention at that
    mark, ANNUALIZED via implied_annual = cumulative ** (12/elapsed_months)
    -- the same compounding convention this project already uses to move
    between annual and monthly rates (see analytics/segment_migration.py's
    module comment deriving monthly shares from an annual GRR/NRR figure)
    -- should land within the QA plan's benchmark reference table's "Logo
    retention (annual)" range for that segment, +/- the PROPOSED
    _BENCHMARK_TOLERANCE_PP buffer. Annualizing is necessary, not
    cosmetic: a raw 36-month cumulative survival rate and a stated annual
    rate describe different time horizons and are not directly comparable
    without it. Source: compute_pooled_curve_by_segment."""
    pooled = compute_pooled_curve_by_segment(as_of_date, con=con)
    at_mark = pooled[pooled["elapsed_months"] == elapsed_months].set_index("entry_segment")

    rows = []
    for segment in _ENTRY_SEGMENTS:
        if segment not in at_mark.index:
            rows.append({
                "entry_segment": segment, "cumulative_logo_retention": np.nan,
                "implied_annual_logo_retention": np.nan,
                "benchmark_low": np.nan, "benchmark_high": np.nan,
                "n_accounts_at_risk": 0, "within_tolerance": False,
            })
            continue
        cumulative = float(at_mark.loc[segment, "logo_retention_rate"])
        implied_annual = cumulative ** (12.0 / elapsed_months)
        n_at_risk = int(at_mark.loc[segment, "n_accounts_at_risk"])
        low, high = _BENCHMARK_LOGO_RETENTION_ANNUAL[segment]
        within = (implied_annual >= low - tolerance_pp) and (implied_annual <= high + tolerance_pp)
        rows.append({
            "entry_segment": segment, "cumulative_logo_retention": cumulative,
            "implied_annual_logo_retention": implied_annual,
            "benchmark_low": low, "benchmark_high": high,
            "n_accounts_at_risk": n_at_risk, "within_tolerance": bool(within),
        })
    detail = pd.DataFrame(rows)

    ordered_values = detail.set_index("entry_segment").loc[_ENTRY_SEGMENTS, "cumulative_logo_retention"]
    is_ordered = bool(
        ordered_values["SMB"] < ordered_values["Commercial"] < ordered_values["Enterprise"]
    ) if ordered_values.notna().all() else False

    return {
        "elapsed_months": elapsed_months,
        "tolerance_pp": tolerance_pp,
        "detail": detail,
        "segment_ordering_smb_lt_commercial_lt_enterprise": is_ordered,
        "all_within_tolerance": bool(detail["within_tolerance"].all()),
    }


def run_build_time_validation(as_of_date: date, log: bool = True) -> dict:
    """End-to-end build-time computation: both cohort triangles, both
    pooled cross-cuts, both structural reconciliations, the revenue-
    decomposition identity check, and the benchmark-grounding
    non-vacuousness check -- everything analytics-model-validator needs
    to independently recompute this artifact's correctness claims. Logs
    the natural scalar time-series metrics to fact_model_performance_history
    (via analytics/model_performance.py) when log=True; the full
    triangle/pooled-curve tables are NOT logged there -- variable-width,
    doesn't fit that log's flat scalar grain, per analytics-engineering-
    conventions' Persistence note -- they are the structured artifact
    output itself."""
    con = _connect()
    try:
        logo_triangle = compute_logo_retention_triangle(as_of_date, con=con)
        revenue_triangle = compute_revenue_retention_triangle(as_of_date, con=con)
        pooled_segment = compute_pooled_curve_by_segment(as_of_date, con=con)
        pooled_channel = compute_pooled_curve_by_channel(as_of_date, con=con)
        cohort_pop_check = validate_cohort_population_reconciliation(as_of_date, con=con)
        active_count_check = validate_active_count_reconciliation(as_of_date, con=con)
        decomposition_check = validate_revenue_decomposition_identity(as_of_date, con=con)
        benchmark_check = validate_benchmark_grounding(as_of_date, con=con)
        accounts = load_cohort_accounts(as_of_date, con=con)
    finally:
        con.close()

    if log:
        log_performance(_MODEL_NAME, as_of_date, "cohort_population_reconciliation_max_abs_diff",
                         cohort_pop_check["max_abs_diff"])
        log_performance(_MODEL_NAME, as_of_date, "active_count_reconciliation_max_abs_diff",
                         active_count_check["max_abs_diff"])
        log_performance(_MODEL_NAME, as_of_date, "revenue_decomposition_identity_max_abs_diff",
                         decomposition_check["max_abs_diff"])
        log_performance(_MODEL_NAME, as_of_date, "total_accounts_in_scope", float(len(accounts)))
        log_performance(_MODEL_NAME, as_of_date, "total_cohorts",
                         float(logo_triangle[["cohort_quarter", "entry_segment"]].drop_duplicates().shape[0]))

        mark = _BENCHMARK_ELAPSED_MONTHS
        at_mark = pooled_segment[pooled_segment["elapsed_months"] == mark].set_index("entry_segment")
        benchmark_detail = benchmark_check["detail"].set_index("entry_segment")
        for segment in _ENTRY_SEGMENTS:
            if segment in at_mark.index:
                log_performance(_MODEL_NAME, as_of_date, f"logo_retention_month{mark}_{segment.lower()}",
                                 float(at_mark.loc[segment, "logo_retention_rate"]))
                log_performance(_MODEL_NAME, as_of_date, f"revenue_retention_month{mark}_{segment.lower()}",
                                 float(at_mark.loc[segment, "revenue_retention_rate"]))
                log_performance(_MODEL_NAME, as_of_date, f"n_accounts_at_risk_month{mark}_{segment.lower()}",
                                 float(at_mark.loc[segment, "n_accounts_at_risk"]))
                log_performance(_MODEL_NAME, as_of_date, f"implied_annual_logo_retention_{segment.lower()}",
                                 float(benchmark_detail.loc[segment, "implied_annual_logo_retention"]))

    return {
        "logo_retention_triangle": logo_triangle,
        "revenue_retention_triangle": revenue_triangle,
        "pooled_curve_by_segment": pooled_segment,
        "pooled_curve_by_channel": pooled_channel,
        "cohort_population_reconciliation": cohort_pop_check,
        "active_count_reconciliation": active_count_check,
        "revenue_decomposition_identity": decomposition_check,
        "benchmark_grounding": benchmark_check,
    }


if __name__ == "__main__":
    result = run_build_time_validation(date(2025, 12, 31))
    print("Cohort population reconciliation:", result["cohort_population_reconciliation"])
    print("Active count reconciliation:", result["active_count_reconciliation"])
    print("Revenue decomposition identity:", result["revenue_decomposition_identity"])
    print()
    print("Pooled logo/revenue retention by entry_segment (elapsed 0, 6, 12, 24, 36 months):")
    pooled = result["pooled_curve_by_segment"]
    print(pooled[pooled["elapsed_months"].isin([0, 6, 12, 24, 36])].to_string(index=False))
    print()
    print("Pooled logo/revenue retention by channel (elapsed 0, 6, 12, 24, 36 months):")
    pooled_c = result["pooled_curve_by_channel"]
    print(pooled_c[pooled_c["elapsed_months"].isin([0, 6, 12, 24, 36])].to_string(index=False))
    print()
    print("Benchmark grounding check:")
    bg = result["benchmark_grounding"]
    print(bg["detail"].to_string(index=False))
    print("Segment ordering (SMB < Commercial < Enterprise):", bg["segment_ordering_smb_lt_commercial_lt_enterprise"])
    print("All within tolerance:", bg["all_within_tolerance"])
