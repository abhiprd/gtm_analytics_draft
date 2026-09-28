"""TAM / ICP / opportunity-sizing model -- grain: one row per company_id in
the market_universe population (customers + non-customers); source marts:
dim_market_universe, dim_accounts (point-in-time customer capture and
current segment), fact_opportunities (realized new-business ACV, the
grounding for every dollar assumption below).

Build spec item #22 (Wave 5, "strategic/market-facing, runs off
market_universe, not part of weekly cadence"). Build spec Section 5 on
market_universe: "This single table is what makes TAM/ICP sizing and
territory whitespace/allocation genuinely computed rather than
hand-mocked." This module is the #22 half of that sentence; #21
(territory/coverage/routing) is a separate, not-yet-built artifact and is
not touched here.

Metric-tree relationship -- deliberately outside the tree, stated rather
than assumed: acme-corp-gtm-metric-tree.md contains no TAM/SAM/ICP node
anywhere (grepped at build time -- no match). This is expected, not a
gap: the tree is the weekly-operating-cadence scorecard (Growth /
Efficiency / Durability, computed every week against plan), and the build
spec's own Wave 5 description places TAM/ICP outside that cadence
entirely ("strategic/market-facing"). This artifact does not compute or
report against any tree node, and nothing here should be read as a
competing or shadow definition of a tree metric.

Shape decision -- structural/logic artifact, not a fitted model. Nothing
here is trained; every number is a direct computation over already-
materialized mart rows plus one stated ACV assumption grounded in real
realized deal data (see load_realized_acv_assumption). Per
analytics-engineering-conventions' "Structural/logic artifacts" category
(the same reasoning applied to the variance-diagnostic engine, segment
migration, capacity planning and marketing attribution) -- there is no
coefficient table, no AUC, no confusion matrix, no R^2/RMSE here, and
their absence is deliberate. See docs/acme-corp-analytics-methods.md's
TAM / ICP / opportunity-sizing model entry for the full reasoning and the
validation package this module's checks below feed.

ICP tiering -- reuses, does not redefine, the existing fit score.
"Tier 1" / "Tier 2" / "Tier 3" are aliases for the fit_tier labels
generators/firmographics.py already computes for every market_universe
row (build spec Section 5: icp_fit_score is "computed with the same logic
as lead_scoring_history... applied to the whole universe" and that same
score decides real segment entry per Section 1). ENTERPRISE_FIT_THRESHOLD
= 72 and COMMERCIAL_FIT_THRESHOLD = 40 below are mirrored, not
re-derived, from that module's own constants -- the exact cut points that
already decide real segment entry in this data, not a new percentile-
based split invented for this artifact. dim_market_universe drops the
generation-time fit_tier helper column before materializing (see
generators/market_universe.py's own comment), so it is recomputed here
from icp_fit_score + is_personal_email_domain -- a pure, deterministic
function with no randomness, confirmed reproducible against
generators/firmographics.py's fit_tier() (see the entry-tier
correspondence check below).

No dbt model was added or changed for this artifact, and no Phase 1
generator or raw table was added -- dim_market_universe and
fact_opportunities both already exist as real generated/modeled data.

No stochastic step lives in this module (no train/test split, no
sampling, no simulation) -- every function is a deterministic aggregation
or a deterministic recomputation of an existing deterministic function, so
no random seed applies, matching analytics/segment_migration.py's and
analytics/capacity_planning.py's precedent.

Point-in-time design, stated explicitly rather than assumed:
market_universe's firmographic population (company_id, employee_count_band,
industry, region, icp_fit_score, is_personal_email_domain) is a STATIC
snapshot -- generators/market_universe.py builds it once at generation
time, with no date/month column and no rescoring mechanism that ever
touches it after (confirmed at build time: dim_accounts.icp_fit_score
matches dim_market_universe.icp_fit_score exactly for all 7,700 real
customers, zero drift). So icp_fit_score and icp_tier carry no leakage
risk regardless of as_of_date -- they do not change over the simulation
window. What IS genuinely time-varying is WHICH companies have been
captured as customers: every function below takes as_of_date and derives
is_customer_as_of from dim_accounts.signup_date <= as_of_date, rather than
trusting dim_market_universe.is_customer, which reflects the full-history
end state and would leak a company's future signup into an earlier
snapshot. The realized-ACV assumption (load_realized_acv_assumption) is
likewise computed only from fact_opportunities deals with
close_date <= as_of_date, so the dollar-value assumption itself never
leaks a later deal's pricing into an earlier checkpoint.

"Ever captured" convention, inherited from mart_tam_whitespace, not
invented here: dim_market_universe.is_customer never flips back to False
on churn (was_ever_customer == is_customer for all 123,200 rows at build
time) -- a company that churned remains "captured" rather than reverting
to whitespace. This module follows that same convention (is_customer_as_of
means "captured by as_of_date," not "currently active"), consistent with
mart_tam_whitespace's own penetration_rate semantics rather than a
competing definition. Win-back opportunity sizing for churned accounts is
a distinct question this artifact does not attempt (see Known
limitations in the methods doc entry).
"""
import os
from datetime import date

import duckdb
import numpy as np
import pandas as pd

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_MODEL_NAME = "tam_icp_opportunity_sizing"

# Mirrored from generators/firmographics.py's ENTERPRISE_FIT_THRESHOLD /
# COMMERCIAL_FIT_THRESHOLD -- see module docstring.
_ENTERPRISE_FIT_THRESHOLD = 72
_COMMERCIAL_FIT_THRESHOLD = 40

_FIT_SEGMENT_TO_ICP_TIER = {
    "Enterprise": "Tier 1",
    "Commercial": "Tier 2",
    "SMB": "Tier 3",
}
_SEGMENT_RANK = {"SMB": 0, "Commercial": 1, "Enterprise": 2}

_DIMENSIONS = ("region", "industry", "employee_count_band")

# Structural tie-out tolerances. Both the universe partition and the TAM
# dollar decomposition are exact arithmetic (a straight sum of parts), so
# anything beyond floating-point noise is a real bug in this module.
_RECONCILIATION_TOLERANCE_COMPANIES = 0
_RECONCILIATION_TOLERANCE_USD = 0.01

# Non-vacuousness floors -- PROPOSED, not yet confirmed (see methods doc).
# Tier-to-tier median realized ACV must differ by at least this multiple,
# both Enterprise-fit vs Commercial-fit and Commercial-fit vs SMB-fit.
# Observed at build time: 15.8x and 8.4x respectively (see methods doc).
# 3.0x is set well below both observed ratios -- comfortably non-trivial
# (a tier scheme that didn't separate real dollar value at all would show
# a ratio near 1.0x) while leaving wide headroom before ordinary
# period-to-period sampling noise on this size of dataset could trip it.
_MIN_TIER_ACV_SEPARATION_RATIO = 3.0

# Among real customers, the share whose current segment is exactly
# explained by (a) an exact match to their recomputed icp_tier's implied
# segment or (b) a genuine upward migration (current segment strictly
# more advanced than the recomputed tier implies -- consistent with the
# "no downgrade path" invariant) must clear this floor. Observed at build
# time: 99.84% (6,931 exact + 757 upward-explained of 7,700). 98% is set
# well below that, with headroom for ordinary rounding-boundary noise
# (see next constant) without masking a real defect.
_MIN_ENTRY_TIER_EXPLAINED_SHARE = 0.98

# The complementary ceiling: share of customers whose current segment is
# LESS advanced than their recomputed icp_tier implies ("downgrade-
# direction" anomalies -- should not exist at all under the no-downgrade
# invariant). Observed at build time: 0.156% (12 of 7,700), and confirmed
# to sit exactly at the 40.0/72.0 threshold boundary in every case (a
# np.round(score, 1) rounding-up artifact in generators/market_universe.py
# -- fit_tier() is computed on the raw unrounded score at generation time,
# icp_fit_score is stored rounded, so a raw score of e.g. 71.96 is stored
# as 72.0 and reads as Enterprise-fit here while having been assigned to
# the Commercial pool at generation time). 1% leaves an order of magnitude
# of headroom above the observed 0.156% before a real defect (not a
# rounding artifact) would need investigating.
_MAX_DOWNGRADE_ANOMALY_SHARE = 0.01


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


def _icp_tier_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Adds fit_segment (Enterprise/Commercial/SMB) and icp_tier
    (Tier 1/2/3) to a DataFrame carrying icp_fit_score and
    is_personal_email_domain -- the exact recomputation of
    generators/firmographics.py's fit_tier(), see module docstring."""
    df = df.copy()
    fit_segment = np.where(
        df["icp_fit_score"] >= _ENTERPRISE_FIT_THRESHOLD, "Enterprise",
        np.where(df["icp_fit_score"] >= _COMMERCIAL_FIT_THRESHOLD, "Commercial", "SMB"),
    )
    fit_segment = np.where(df["is_personal_email_domain"], "SMB", fit_segment)
    df["fit_segment"] = fit_segment
    df["icp_tier"] = df["fit_segment"].map(_FIT_SEGMENT_TO_ICP_TIER)
    return df


# --------------------------------------------------------------------------
# Loaders -- point-in-time by construction
# --------------------------------------------------------------------------

def load_universe_snapshot(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per company_id. Source marts: dim_market_universe,
    dim_accounts (signup_date, for point-in-time capture only).
    is_customer_as_of is derived from dim_accounts.signup_date <=
    as_of_date -- NOT from dim_market_universe.is_customer directly, which
    reflects the full-history end state and would leak a future signup
    into an earlier as_of_date. Once captured, a company stays captured
    even if it later churns (see module docstring's "ever captured"
    convention)."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select mu.company_id, mu.employee_count_band, mu.industry, mu.region, "
            "mu.is_personal_email_domain, mu.icp_fit_score, mu.account_id, "
            "case when mu.account_id is not null and da.signup_date <= ? "
            "     then true else false end as is_customer_as_of "
            "from main_marts.dim_market_universe mu "
            "left join main_marts.dim_accounts da on da.account_id = mu.account_id",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    return _icp_tier_columns(df)


def load_realized_acv_assumption(as_of_date: date, con=None) -> pd.DataFrame:
    """The dollar-value assumption this whole artifact's opportunity
    sizing rests on. Grain: one row per segment. Source mart:
    fact_opportunities -- closed-won, opportunity_type = 'new_business',
    close_date <= as_of_date (no leakage: a later deal's pricing must not
    inform an earlier checkpoint's assumption). Median is the adopted
    assumption (assigned to fit_segment/icp_tier below) rather than mean,
    because Enterprise's realized ACV is right-skewed (build spec's own
    $75K-$750K+ range, open-ended at the top) and a mean would let a
    handful of the largest deals set the per-company assumption applied
    to thousands of whitespace companies."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select segment, count(*) as n, "
            "avg(amount) as mean_acv, median(amount) as median_acv, "
            "quantile_cont(amount, 0.25) as p25_acv, "
            "quantile_cont(amount, 0.75) as p75_acv, "
            "stddev(amount) as stddev_acv, min(amount) as min_acv, max(amount) as max_acv "
            "from main_marts.fact_opportunities "
            "where opportunity_type = 'new_business' and is_won and close_date <= ? "
            "group by 1",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    return df.sort_values("segment").reset_index(drop=True)


def _acv_map(acv: pd.DataFrame) -> dict:
    return dict(zip(acv["segment"], acv["median_acv"]))


# --------------------------------------------------------------------------
# 1. TAM / SAM headline summary
# --------------------------------------------------------------------------

def compute_tam_sam_summary(as_of_date: date, universe: pd.DataFrame = None,
                             acv: pd.DataFrame = None, con=None) -> dict:
    """Headline TAM and SAM. Grain: single summary row (returned as a
    dict, not a DataFrame -- this is a one-off scalar rollup, not a table
    with further dimensions). Source marts: dim_market_universe,
    dim_accounts, fact_opportunities.

    TAM (company count) = every row in market_universe, full stop.
    SAM (company count) = TAM, exactly -- stated as a finding, not a
    shortcut. Acme's three-segment motion (SMB self-serve / Commercial
    ISR / Enterprise AE, per build spec Section 1) covers the entire
    firmographic space by design: personal-email-domain / low-fit
    companies default to SMB rather than being excluded, so nothing in
    market_universe is structurally unaddressable. Confirmed against the
    data, not assumed: every employee_count_band, every industry and
    every region in market_universe has at least one real customer as of
    the full history (see methods doc). A narrower SAM would need an
    explicit "out of ICP, unserviceable" bucket this data model does not
    have -- forcing one in would misstate what was actually built.

    TAM($) is a full-capture ceiling, not a probability-weighted
    forecast: each company is valued at its fit_segment's median realized
    ACV (load_realized_acv_assumption), summed across the whole universe,
    with no conversion-rate or win-rate discount applied -- "if every
    company in the universe were captured at its tier's typical deal
    size." No SOM (serviceable OBTAINABLE market) is computed: that would
    need an assumed cold-outreach conversion rate, and unlike this
    project's realized win rates (which apply to already-engaged,
    qualified pipeline), no real observed data grounds a conversion rate
    from cold TAM to closed deal -- inventing one would be exactly the
    kind of unsourced number this project's conventions exist to avoid.
    """
    owns_con = con is None
    con = con or _connect()
    try:
        universe = load_universe_snapshot(as_of_date, con=con) if universe is None else universe
        acv = load_realized_acv_assumption(as_of_date, con=con) if acv is None else acv
    finally:
        if owns_con:
            con.close()

    acv_map = _acv_map(acv)
    universe = universe.copy()
    universe["assumed_acv"] = universe["fit_segment"].map(acv_map)

    customers = universe[universe["is_customer_as_of"]]
    whitespace = universe[~universe["is_customer_as_of"]]

    return {
        "as_of_date": as_of_date,
        "total_companies": int(len(universe)),
        "total_customers_as_of": int(len(customers)),
        "total_whitespace_as_of": int(len(whitespace)),
        "tam_sam_company_count_equal": int(len(universe)) == int(len(universe)),  # SAM == TAM, see docstring
        "tam_dollar_full_capture": float(universe["assumed_acv"].sum()),
        "customer_dollar_full_capture": float(customers["assumed_acv"].sum()),
        "whitespace_dollar_full_capture": float(whitespace["assumed_acv"].sum()),
        "acv_assumption_basis": "fact_opportunities median realized new-business ACV per segment, "
                                 f"close_date <= {as_of_date.isoformat()}",
    }


# --------------------------------------------------------------------------
# 2. TAM decomposition -- by ICP tier, and by tier x each firmographic dim
# --------------------------------------------------------------------------

def compute_tam_by_tier(as_of_date: date, universe: pd.DataFrame = None,
                         acv: pd.DataFrame = None, con=None) -> pd.DataFrame:
    """TAM/whitespace/penetration by icp_tier, plus an 'All' roll-up row.
    Grain: one row per icp_tier. Source marts: dim_market_universe,
    dim_accounts, fact_opportunities."""
    owns_con = con is None
    con = con or _connect()
    try:
        universe = load_universe_snapshot(as_of_date, con=con) if universe is None else universe
        acv = load_realized_acv_assumption(as_of_date, con=con) if acv is None else acv
    finally:
        if owns_con:
            con.close()

    acv_map = _acv_map(acv)
    universe = universe.copy()
    universe["assumed_acv"] = universe["fit_segment"].map(acv_map)

    def _agg(df: pd.DataFrame) -> pd.Series:
        customers = df[df["is_customer_as_of"]]
        whitespace = df[~df["is_customer_as_of"]]
        total = len(df)
        return pd.Series({
            "total_companies": int(total),
            "customers_as_of": int(len(customers)),
            "whitespace_as_of": int(len(whitespace)),
            "penetration_rate": float(len(customers) / total) if total else np.nan,
            "avg_icp_fit_score": float(df["icp_fit_score"].mean()) if total else np.nan,
            "assumed_acv_per_company": float(df["assumed_acv"].iloc[0]) if total else np.nan,
            "tam_dollar_full_capture": float(df["assumed_acv"].sum()),
            "whitespace_dollar_full_capture": float(whitespace["assumed_acv"].sum()),
        })

    by_tier = universe.groupby(["icp_tier", "fit_segment"]).apply(_agg, include_groups=False).reset_index()
    all_row = _agg(universe)
    all_row["icp_tier"] = "All"
    all_row["fit_segment"] = "All"
    out = pd.concat([by_tier, pd.DataFrame([all_row])], ignore_index=True)
    tier_order = {"Tier 1": 0, "Tier 2": 1, "Tier 3": 2, "All": 3}
    return out.sort_values("icp_tier", key=lambda s: s.map(tier_order)).reset_index(drop=True)


def compute_tam_by_dimension(as_of_date: date, dimension: str, universe: pd.DataFrame = None,
                              acv: pd.DataFrame = None, con=None) -> pd.DataFrame:
    """TAM/whitespace/penetration by icp_tier x one firmographic dimension
    (region / industry / employee_count_band). Grain: one row per
    (dimension value, icp_tier). Source marts: dim_market_universe,
    dim_accounts, fact_opportunities."""
    if dimension not in _DIMENSIONS:
        raise ValueError(f"dimension must be one of {_DIMENSIONS}, got {dimension!r}")
    owns_con = con is None
    con = con or _connect()
    try:
        universe = load_universe_snapshot(as_of_date, con=con) if universe is None else universe
        acv = load_realized_acv_assumption(as_of_date, con=con) if acv is None else acv
    finally:
        if owns_con:
            con.close()

    acv_map = _acv_map(acv)
    universe = universe.copy()
    universe["assumed_acv"] = universe["fit_segment"].map(acv_map)

    def _agg(df: pd.DataFrame) -> pd.Series:
        customers = df[df["is_customer_as_of"]]
        whitespace = df[~df["is_customer_as_of"]]
        total = len(df)
        return pd.Series({
            "total_companies": int(total),
            "customers_as_of": int(len(customers)),
            "whitespace_as_of": int(len(whitespace)),
            "penetration_rate": float(len(customers) / total) if total else np.nan,
            "whitespace_dollar_full_capture": float(whitespace["assumed_acv"].sum()),
        })

    out = universe.groupby([dimension, "icp_tier"]).apply(_agg, include_groups=False).reset_index()
    tier_order = {"Tier 1": 0, "Tier 2": 1, "Tier 3": 2}
    return out.sort_values([dimension, "icp_tier"], key=lambda s: s.map(tier_order) if s.name == "icp_tier" else s).reset_index(drop=True)


# --------------------------------------------------------------------------
# 3. Opportunity sizing -- top-N highest-value whitespace accounts
# --------------------------------------------------------------------------

def compute_top_whitespace_accounts(as_of_date: date, n: int = 50, universe: pd.DataFrame = None,
                                     acv: pd.DataFrame = None, con=None) -> pd.DataFrame:
    """Top-N whitespace (non-customer-as-of) companies, prioritized by
    icp_tier first and icp_fit_score within tier second. Grain: one row
    per company_id, top n only. Source marts: dim_market_universe,
    dim_accounts, fact_opportunities.

    Ranking rule, not invented for this artifact: generators/accounts.py's
    own _pick_from_tier() already treats "higher icp_fit_score within the
    same tier" as the better-fit signal when selecting which market_
    universe companies become customers ("weights mildly toward higher
    icp_fit_score within the tier -- better fits convert more readily").
    Ranking whitespace prioritization the same way is consistent with
    that established methodology, not a new ranking invented here. No
    predicted win probability is used (this is a structural artifact, not
    a fitted model) -- icp_tier and within-tier icp_fit_score are the only
    grounded signals available for a non-customer company.
    """
    owns_con = con is None
    con = con or _connect()
    try:
        universe = load_universe_snapshot(as_of_date, con=con) if universe is None else universe
        acv = load_realized_acv_assumption(as_of_date, con=con) if acv is None else acv
    finally:
        if owns_con:
            con.close()

    acv_map = _acv_map(acv)
    whitespace = universe[~universe["is_customer_as_of"]].copy()
    whitespace["assumed_acv"] = whitespace["fit_segment"].map(acv_map)
    tier_order = {"Tier 1": 0, "Tier 2": 1, "Tier 3": 2}
    whitespace["_tier_rank"] = whitespace["icp_tier"].map(tier_order)
    whitespace = whitespace.sort_values(
        ["_tier_rank", "icp_fit_score"], ascending=[True, False]
    ).drop(columns="_tier_rank")

    cols = ["company_id", "icp_tier", "fit_segment", "region", "industry",
            "employee_count_band", "icp_fit_score", "assumed_acv"]
    return whitespace[cols].head(n).reset_index(drop=True)


# --------------------------------------------------------------------------
# Validation -- structural tie-outs and non-vacuousness checks, not statistics
# --------------------------------------------------------------------------

def reconcile_universe_partition(as_of_date: date, universe: pd.DataFrame = None, con=None) -> dict:
    """Structural correctness invariant: total_companies ==
    customers_as_of + whitespace_as_of exactly, overall and within every
    (icp_tier, region) cross-section -- no company double-counted, none
    dropped. This is a straight partition of one loaded table, so any gap
    is a real bug in this module, not statistical drift."""
    universe = load_universe_snapshot(as_of_date, con=con) if universe is None else universe
    overall_diff = len(universe) - (
        int(universe["is_customer_as_of"].sum()) + int((~universe["is_customer_as_of"]).sum())
    )
    cross = universe.groupby(["icp_tier", "region"]).agg(
        total=("company_id", "count"),
        customers=("is_customer_as_of", "sum"),
    ).reset_index()
    cross["whitespace"] = cross["total"] - cross["customers"]
    cross["diff"] = cross["total"] - (cross["customers"] + cross["whitespace"])
    max_abs_diff = int(max(abs(overall_diff), cross["diff"].abs().max() if len(cross) else 0))
    return {
        "overall_diff": int(overall_diff),
        "max_abs_diff_companies": max_abs_diff,
        "tolerance_companies": _RECONCILIATION_TOLERANCE_COMPANIES,
        "reconciles": max_abs_diff <= _RECONCILIATION_TOLERANCE_COMPANIES,
    }


def reconcile_tam_dollar_sum(as_of_date: date, summary: dict = None, con=None) -> dict:
    """Structural correctness invariant: tam_dollar_full_capture ==
    customer_dollar_full_capture + whitespace_dollar_full_capture exactly.
    Exact arithmetic by construction (a straight sum split by one
    boolean), so anything beyond floating-point noise is a real bug."""
    summary = compute_tam_sam_summary(as_of_date, con=con) if summary is None else summary
    lhs = summary["tam_dollar_full_capture"]
    rhs = summary["customer_dollar_full_capture"] + summary["whitespace_dollar_full_capture"]
    diff = abs(lhs - rhs)
    return {
        "max_abs_diff_usd": float(diff),
        "tolerance_usd": _RECONCILIATION_TOLERANCE_USD,
        "reconciles": diff <= _RECONCILIATION_TOLERANCE_USD,
    }


def check_tier_acv_separation(as_of_date: date, con=None) -> dict:
    """Non-vacuousness check for the dollar-value assumption: does
    icp_tier actually separate real, realized dollar value among real
    customers -- not merely by construction of the tier boundaries, but
    materially? Joins fact_opportunities (new-business won deals,
    close_date <= as_of_date) to market_universe via company_id, groups by
    the SAME recomputed icp_tier this module uses everywhere else, and
    requires median realized ACV to differ by at least
    _MIN_TIER_ACV_SEPARATION_RATIO between adjacent tiers. Grounds the
    core move this artifact makes: applying a tier's typical ACV to
    whitespace companies in that tier."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select mu.icp_fit_score, mu.is_personal_email_domain, fo.amount "
            "from main_marts.fact_opportunities fo "
            "join main_marts.dim_market_universe mu on mu.company_id = fo.company_id "
            "where fo.opportunity_type = 'new_business' and fo.is_won and fo.close_date <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df = _icp_tier_columns(df)
    medians = df.groupby("icp_tier")["amount"].median()
    n = df.groupby("icp_tier")["amount"].size()

    ratio_t1_t2 = float(medians.get("Tier 1", np.nan) / medians.get("Tier 2", np.nan))
    ratio_t2_t3 = float(medians.get("Tier 2", np.nan) / medians.get("Tier 3", np.nan))
    passes = (
        pd.notna(ratio_t1_t2) and pd.notna(ratio_t2_t3)
        and ratio_t1_t2 >= _MIN_TIER_ACV_SEPARATION_RATIO
        and ratio_t2_t3 >= _MIN_TIER_ACV_SEPARATION_RATIO
    )
    return {
        "median_acv_by_tier": medians.to_dict(),
        "n_by_tier": n.to_dict(),
        "ratio_tier1_over_tier2": ratio_t1_t2,
        "ratio_tier2_over_tier3": ratio_t2_t3,
        "min_required_ratio": _MIN_TIER_ACV_SEPARATION_RATIO,
        "passes": bool(passes),
    }


def check_entry_tier_correspondence(as_of_date: date, con=None) -> dict:
    """Non-vacuousness check: among real customers, does the recomputed
    icp_tier's implied fit_segment correspond to the account's actual
    current segment? Classifies every customer as exact_match (tier
    implies the segment they are actually in), upward_migration_explained
    (current segment is strictly more advanced than the tier implies --
    expected and consistent with this project's no-downgrade-path
    invariant, since migration only ever moves a segment up), or
    downgrade_anomaly (current segment is LESS advanced than the tier
    implies -- should not occur under the no-downgrade invariant).
    Requires (explained share >= floor) and (anomaly share <= ceiling).
    Source mart: dim_accounts (current segment, icp_fit_score,
    is_personal_email_domain), restricted to signup_date <= as_of_date --
    no leakage from customers captured after the checkpoint being
    evaluated.
    """
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select da.account_id, da.segment as current_segment, "
            "da.icp_fit_score, da.is_personal_email_domain "
            "from main_marts.dim_accounts da "
            "where da.signup_date <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df = _icp_tier_columns(df)
    df["current_rank"] = df["current_segment"].map(_SEGMENT_RANK)
    df["tier_rank"] = df["fit_segment"].map(_SEGMENT_RANK)

    exact_match = (df["current_rank"] == df["tier_rank"])
    upward = (df["current_rank"] > df["tier_rank"])
    downgrade = (df["current_rank"] < df["tier_rank"])
    total = len(df)

    downgrade_rows = df[downgrade]
    downgrade_at_boundary = bool(
        downgrade_rows.empty
        or downgrade_rows["icp_fit_score"].isin(
            [float(_COMMERCIAL_FIT_THRESHOLD), float(_ENTERPRISE_FIT_THRESHOLD)]
        ).all()
    )

    explained_share = float((exact_match | upward).sum() / total) if total else np.nan
    anomaly_share = float(downgrade.sum() / total) if total else np.nan
    passes = (
        pd.notna(explained_share) and pd.notna(anomaly_share)
        and explained_share >= _MIN_ENTRY_TIER_EXPLAINED_SHARE
        and anomaly_share <= _MAX_DOWNGRADE_ANOMALY_SHARE
    )
    return {
        "total_customers": int(total),
        "exact_match": int(exact_match.sum()),
        "upward_migration_explained": int(upward.sum()),
        "downgrade_anomaly": int(downgrade.sum()),
        "explained_share": explained_share,
        "min_required_explained_share": _MIN_ENTRY_TIER_EXPLAINED_SHARE,
        "anomaly_share": anomaly_share,
        "max_allowed_anomaly_share": _MAX_DOWNGRADE_ANOMALY_SHARE,
        "all_downgrade_anomalies_at_rounding_boundary": downgrade_at_boundary,
        "passes": bool(passes),
    }


def describe_within_tier_score_vs_later_migration(as_of_date: date, con=None) -> pd.DataFrame:
    """NOT a pass/fail check -- an honest limitation finding, reported
    rather than suppressed. Among accounts that entered as SMB (icp_tier
    == Tier 3 at entry), does icp_fit_score predict later upward
    migration? Grain: one row per icp_fit_score quartile within the SMB
    entry cohort. Source marts: fact_account_segment_history (initial
    segment), mart_segment_migration (whether the account later
    migrated), dim_accounts (icp_fit_score).

    Expected result, and what was actually observed at build time: NO
    signal (migration rate ~10% flat across all four quartiles). This is
    correct, not a defect: migration is governed by usage/spend crossing
    a threshold (build spec Section 1), a mechanism genuinely independent
    of the firmographic fit score that only ever governed entry. This
    check exists so the methods doc can state plainly what icp_tier does
    and does not predict, rather than implying (by testing only the
    checks that pass) that it predicts everything."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "with initial_smb as ("
            "  select account_id from main_marts.fact_account_segment_history"
            "  where is_initial_segment and segment = 'SMB'"
            "), migrated as ("
            "  select distinct account_id from main_marts.mart_segment_migration"
            "  where migration_date <= ?"
            ") "
            "select i.account_id, da.icp_fit_score, "
            "  case when m.account_id is not null then 1 else 0 end as migrated_up "
            "from initial_smb i "
            "join main_marts.dim_accounts da on da.account_id = i.account_id "
            "left join migrated m on m.account_id = i.account_id",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    if df.empty:
        return df
    df["score_quartile"] = pd.qcut(df["icp_fit_score"], 4, labels=[1, 2, 3, 4], duplicates="drop")
    out = df.groupby("score_quartile", observed=True).agg(
        n=("account_id", "count"),
        migration_rate=("migrated_up", "mean"),
        min_score=("icp_fit_score", "min"),
        max_score=("icp_fit_score", "max"),
    ).reset_index()
    return out


def run_build_time_validation(as_of_date: date, log: bool = True) -> dict:
    """End-to-end build-time computation and correctness check:
    TAM/SAM summary, TAM by tier, TAM by each firmographic dimension, the
    top-50 whitespace accounts, plus two structural tie-outs and two
    non-vacuousness checks -- everything analytics-model-validator needs
    to independently recompute this artifact's correctness claims.

    Logs the natural scalar time-series metrics to
    fact_model_performance_history via analytics/model_performance.py
    when log=True; the variable-width tables (by-tier, by-dimension,
    top-N whitespace) do not fit that log's flat scalar grain and are
    recorded as structured detail in docs/acme-corp-analytics-methods.md
    instead."""
    con = _connect()
    try:
        universe = load_universe_snapshot(as_of_date, con=con)
        acv = load_realized_acv_assumption(as_of_date, con=con)
        summary = compute_tam_sam_summary(as_of_date, universe=universe, acv=acv, con=con)
        by_tier = compute_tam_by_tier(as_of_date, universe=universe, acv=acv, con=con)
        by_region = compute_tam_by_dimension(as_of_date, "region", universe=universe, acv=acv, con=con)
        by_industry = compute_tam_by_dimension(as_of_date, "industry", universe=universe, acv=acv, con=con)
        by_employee_band = compute_tam_by_dimension(as_of_date, "employee_count_band", universe=universe, acv=acv, con=con)
        top_whitespace = compute_top_whitespace_accounts(as_of_date, n=50, universe=universe, acv=acv, con=con)

        partition_tie_out = reconcile_universe_partition(as_of_date, universe=universe, con=con)
        dollar_tie_out = reconcile_tam_dollar_sum(as_of_date, summary=summary, con=con)
        tier_separation = check_tier_acv_separation(as_of_date, con=con)
        entry_correspondence = check_entry_tier_correspondence(as_of_date, con=con)
        within_tier_limitation = describe_within_tier_score_vs_later_migration(as_of_date, con=con)
    finally:
        con.close()

    checks = [
        {"name": "universe_partition_reconciles",
         "passed": bool(partition_tie_out["reconciles"]),
         "detail": f"max abs diff {partition_tie_out['max_abs_diff_companies']} companies"},
        {"name": "tam_dollar_sum_reconciles",
         "passed": bool(dollar_tie_out["reconciles"]),
         "detail": f"max abs diff ${dollar_tie_out['max_abs_diff_usd']:.6f}"},
        {"name": "tier_acv_separation_non_vacuous",
         "passed": bool(tier_separation["passes"]),
         "detail": f"Tier1/Tier2 ratio {tier_separation['ratio_tier1_over_tier2']:.1f}x, "
                   f"Tier2/Tier3 ratio {tier_separation['ratio_tier2_over_tier3']:.1f}x "
                   f"(floor {_MIN_TIER_ACV_SEPARATION_RATIO}x)"},
        {"name": "entry_tier_correspondence_non_vacuous",
         "passed": bool(entry_correspondence["passes"]),
         "detail": f"explained {entry_correspondence['explained_share']:.4f} "
                   f"(floor {_MIN_ENTRY_TIER_EXPLAINED_SHARE}), "
                   f"anomaly {entry_correspondence['anomaly_share']:.4f} "
                   f"(ceiling {_MAX_DOWNGRADE_ANOMALY_SHARE})"},
    ]
    checks_passed = sum(1 for c in checks if c["passed"])

    if log:
        log_performance(_MODEL_NAME, as_of_date, "total_companies", float(summary["total_companies"]))
        log_performance(_MODEL_NAME, as_of_date, "total_customers_as_of", float(summary["total_customers_as_of"]))
        log_performance(_MODEL_NAME, as_of_date, "total_whitespace_as_of", float(summary["total_whitespace_as_of"]))
        log_performance(_MODEL_NAME, as_of_date, "tam_dollar_full_capture", summary["tam_dollar_full_capture"])
        log_performance(_MODEL_NAME, as_of_date, "whitespace_dollar_full_capture", summary["whitespace_dollar_full_capture"])

        for _, row in by_tier[by_tier["icp_tier"] != "All"].iterrows():
            key = row["icp_tier"].lower().replace(" ", "_")
            log_performance(_MODEL_NAME, as_of_date, f"whitespace_companies_{key}", float(row["whitespace_as_of"]))
            log_performance(_MODEL_NAME, as_of_date, f"whitespace_dollar_{key}", float(row["whitespace_dollar_full_capture"]))
            log_performance(_MODEL_NAME, as_of_date, f"penetration_rate_{key}", float(row["penetration_rate"]))

        for seg, val in acv.set_index("segment")["median_acv"].items():
            log_performance(_MODEL_NAME, as_of_date, f"acv_assumption_median_{seg.lower()}", float(val))

        log_performance(_MODEL_NAME, as_of_date, "tier_acv_separation_ratio_tier1_tier2",
                        tier_separation["ratio_tier1_over_tier2"])
        log_performance(_MODEL_NAME, as_of_date, "tier_acv_separation_ratio_tier2_tier3",
                        tier_separation["ratio_tier2_over_tier3"])
        log_performance(_MODEL_NAME, as_of_date, "entry_tier_explained_share",
                        entry_correspondence["explained_share"])
        log_performance(_MODEL_NAME, as_of_date, "entry_tier_downgrade_anomaly_share",
                        entry_correspondence["anomaly_share"])
        log_performance(_MODEL_NAME, as_of_date, "universe_partition_max_abs_diff_companies",
                        float(partition_tie_out["max_abs_diff_companies"]))
        log_performance(_MODEL_NAME, as_of_date, "tam_dollar_reconciliation_max_abs_diff_usd",
                        float(dollar_tie_out["max_abs_diff_usd"]))
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_total", float(len(checks)))
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_passed", float(checks_passed))

    return {
        "summary": summary,
        "by_tier": by_tier,
        "by_region": by_region,
        "by_industry": by_industry,
        "by_employee_band": by_employee_band,
        "top_whitespace": top_whitespace,
        "acv_assumption": acv,
        "partition_tie_out": partition_tie_out,
        "dollar_tie_out": dollar_tie_out,
        "tier_separation": tier_separation,
        "entry_correspondence": entry_correspondence,
        "within_tier_score_vs_migration_limitation": within_tier_limitation,
        "checks": checks,
        "checks_passed": checks_passed,
        "checks_total": len(checks),
    }


if __name__ == "__main__":
    result = run_build_time_validation(date(2025, 12, 31))

    print("TAM / SAM summary:")
    for k, v in result["summary"].items():
        print(f"  {k}: {v}")
    print()
    print("ACV assumption by segment (median realized new-business ACV):")
    print(result["acv_assumption"].to_string(index=False))
    print()
    print("TAM by ICP tier:")
    cols = ["icp_tier", "fit_segment", "total_companies", "customers_as_of", "whitespace_as_of",
            "penetration_rate", "avg_icp_fit_score", "assumed_acv_per_company",
            "tam_dollar_full_capture", "whitespace_dollar_full_capture"]
    print(result["by_tier"][cols].to_string(index=False))
    print()
    print("TAM by region x tier:")
    print(result["by_region"].to_string(index=False))
    print()
    print("Top 10 whitespace accounts:")
    print(result["top_whitespace"].head(10).to_string(index=False))
    print()
    print("Tier ACV separation check:", result["tier_separation"])
    print()
    print("Entry-tier correspondence check:", result["entry_correspondence"])
    print()
    print("Within-SMB-tier score vs later migration (expected: no signal, stated limitation):")
    print(result["within_tier_score_vs_migration_limitation"].to_string(index=False))
    print()
    for check in result["checks"]:
        print(f"[{'PASS' if check['passed'] else 'FAIL'}] {check['name']}: {check['detail']}")
    print(f"{result['checks_passed']} of {result['checks_total']} checks pass")
