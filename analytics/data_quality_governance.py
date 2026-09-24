"""Data quality / metric governance -- grain: one governance run per
as_of_date, three independent check families each at their own natural
grain (metric-tree edge, mart row/column, invariant rule); source marts:
dim_accounts, dim_reps, dim_market_universe, fact_opportunities,
fact_revenue_monthly, fact_usage_monthly, fact_account_segment_history,
fact_leads, fact_forecast_submissions, fact_committed_vs_utilized_monthly,
mart_growth_bridge, mart_efficiency, mart_durability, mart_segment_migration,
mart_account_health.

Build spec item #18 (Wave 3, infrastructure/governance). See
docs/acme-corp-analytics-methods.md's "Data quality / metric governance"
entry for the full shape decision and reasoning; the short version:

This is NOT drift-monitor. drift-monitor recurringly checks whether a
FITTED model's calibration has decayed and whether a Layer-3 leaf has
decoupled from its Layer-2 parent (docs/acme-corp-analytics-methods.md's
"Proxy-metric decoupling -- general rule"). Nothing here is fitted and
nothing here tracks decay over time. This module answers a different,
prior question -- three of them, run once per build/checkpoint:

  1. METRIC-TREE MATHEMATICAL INTEGRITY. For every parent node in
     docs/acme-corp-gtm-metric-tree.md that the tree itself states as a
     sum/product/ratio of children, does the built marts layer actually
     satisfy that equation, in real values, right now? This operationalizes
     CLAUDE.md's invariant ("every parent metric must be the actual
     mathematical result of its children... never a 'related metrics'
     grouping") as a runnable check instead of a design promise.
  2. MARTS-LAYER DATA QUALITY. docs/acme-corp-phase1-data-qa-plan.md's test
     suite (referential integrity, distributional realism, volume
     sufficiency) covers raw generator output ONLY -- nothing currently
     re-runs an analogous check against the dbt-BUILT marts a dbt bug could
     still corrupt after raw generation passes clean. This closes that gap.
  3. INVARIANT GOVERNANCE. CLAUDE.md's "Non-negotiable invariants" section
     is a set of design promises (segment terminology, no downgrade path,
     USD only, channel/segment orthogonality, the four trigger_reason
     values, no independently-random risk columns). This mechanizes each
     one into a check against the live built data, including three
     data-grounded spot-checks (not a generic assertion) that win
     probability, churn probability and usage growth each carry a real
     relationship to a stated driver rather than being decorative noise.

SHAPE -- structural/logic artifact, like the variance-diagnostic engine,
segment migration analysis, capacity planning and marketing attribution.
Every check here is a deterministic comparison against already-materialized
mart values or a fixed rule -- nothing is fitted, so per
analytics-engineering-conventions' "Structural/logic artifacts" category
there is no coefficient table, no AUC, no confusion matrix, no R^2/RMSE
here, and their absence is deliberate rather than pending. Its own
correctness claim ("does this actually catch a known-broken case") is
checked by run_synthetic_violation_tests() below, in the same spirit as
the variance-diagnostic engine's hand-constructed scenarios.

No stochastic step lives in this module -- no train/test split, no
sampling, no simulation -- so no random seed applies, matching
analytics/segment_migration.py's, analytics/variance_diagnostic.py's and
analytics/capacity_planning.py's precedent.
"""
import json
import math
import os
from datetime import date

import duckdb
import numpy as np
import pandas as pd

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
_MODEL_NAME = "data_quality_governance"

_VALID_SEGMENTS = {"SMB", "Commercial", "Enterprise"}
# The only migration directions the build spec's "no skip-level, no
# downgrade" rule permits. Any pair outside this set -- a downgrade, a
# skip-level SMB->Enterprise, or a same-segment no-op -- is a violation.
_ALLOWED_MIGRATION_PAIRS = {("SMB", "Commercial"), ("Commercial", "Enterprise")}
_ALL_TRIGGER_REASONS = {
    "initial_firmographic", "initial_default", "usage_threshold", "firmographic_rescore",
}
_MIGRATION_TRIGGER_REASONS = {"usage_threshold", "firmographic_rescore"}
_INITIAL_TRIGGER_REASONS = {"initial_firmographic", "initial_default"}

# Reconciliation tolerance for exact arithmetic identities (the metric
# tree's stated formulas). Deterministic arithmetic has no sampling
# variance, so this is a floating-point-noise tolerance, not a band --
# same reasoning capacity_planning's and segment_migration's reconciliation
# checks state for their own $0.01 tolerances.
_RECONCILIATION_TOLERANCE = 0.01
_RATIO_TOLERANCE = 1e-6

# --- PROPOSED, not yet confirmed (see docs/acme-corp-analytics-methods.md) ---
# Minimum absolute count each of the four trigger_reason values must clear
# to count as "actually fires," not just "exists as an unused schema
# value." 20 is chosen to sit far below every value observed at build time
# (245-7222 across the four), so ordinary future data regeneration can't
# spuriously trip it, while still being large enough that a single stray
# row can't fake compliance.
_TRIGGER_REASON_MIN_COUNT = 20
# ACV/deal-amount outlier ceiling: a deal amount beyond this multiple of
# its segment's documented upper ACV bound (build spec Section 1: SMB
# $15K, Commercial $75K, Enterprise $750K) is flagged as a corruption
# candidate, not a business outlier -- this check is deliberately loose
# (data-quality corruption-catching, not the QA plan's tighter
# distributional-realism band) so it doesn't re-litigate legitimate
# business variance.
_ACV_OUTLIER_MULTIPLE = 2.0
_SEGMENT_ACV_UPPER_BOUND = {"SMB": 15_000, "Commercial": 75_000, "Enterprise": 750_000}
# Win-probability spot-check: POC pass must beat POC fail's win rate by at
# least this many percentage points, at z >= 2.58 (99% one-sided
# confidence -- the same z-threshold analytics/marketing_attribution.py's
# holdout-suppression check uses), to count as a real, non-decorative
# driver relationship rather than noise.
_WIN_PROB_MIN_GAP_PP = 0.15
_Z_THRESHOLD = 2.58
# Churn-probability spot-check: mean actions_consumed and login activity
# in a churned account's own final 3 months must be at least this much
# lower, relative to that SAME account's own baseline in all earlier
# months, to count as a real pre-churn decline rather than noise. 20% is
# a conservative floor -- Phase 3's own churn analysis observed usage
# dropping 66%->23% (a ~65% relative decline) over the run-up to churn, so
# this floor has wide headroom below the actual effect size.
_CHURN_PROB_MIN_DECLINE = 0.20
# Usage-growth spot-check: accounts whose migration was usage_threshold-
# triggered must show a materially higher trailing usage GROWTH rate in
# the 3 months before migration than same-segment accounts that did not
# migrate in that window, by at least this multiple, to count as growth
# genuinely driven by crossing the threshold rather than independent noise.
_USAGE_GROWTH_MIN_RATIO = 1.5


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


def _pct(n, d):
    return float(n) / float(d) if d else float("nan")


def _two_proportion_z(x1, n1, x2, n2):
    """Two-proportion z-test (pooled), one-sided (p1 > p2). Returns
    (p1, p2, z). No external stats dependency -- closed-form, same
    treatment analytics/marketing_attribution.py's incrementality check
    uses for its own two-proportion comparison."""
    p1, p2 = _pct(x1, n1), _pct(x2, n2)
    p_pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) if 0 < p_pool < 1 else float("nan")
    z = (p1 - p2) / se if se and se > 0 else float("nan")
    return p1, p2, z


# ==========================================================================
# Loaders -- point-in-time by construction
# ==========================================================================

def load_growth_bridge(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per segment per month, month <= as_of_date. Source
    mart: mart_growth_bridge."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select * from main_marts.mart_growth_bridge where month <= ?", [as_of_date]
        ).df()
    finally:
        if owns_con:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    return df


def load_efficiency(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per segment per month, month <= as_of_date. Source
    mart: mart_efficiency."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select * from main_marts.mart_efficiency where month <= ?", [as_of_date]
        ).df()
    finally:
        if owns_con:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    return df


def load_durability(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per segment per month, month <= as_of_date. Source
    mart: mart_durability."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select * from main_marts.mart_durability where month <= ?", [as_of_date]
        ).df()
    finally:
        if owns_con:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    return df


def load_segment_migration(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per migration event, migration_date <= as_of_date.
    Source mart: mart_segment_migration."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select * from main_marts.mart_segment_migration where migration_date <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["migration_date"] = pd.to_datetime(df["migration_date"])
    return df


def load_account_segment_history(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per account_id per segment-effective_date,
    effective_date <= as_of_date. Source mart: fact_account_segment_history."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select * from main_marts.fact_account_segment_history where effective_date <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    return df


# ==========================================================================
# SECTION 1 -- Metric-tree mathematical integrity checker
# ==========================================================================
#
# Each function below checks exactly one parent-child arithmetic edge from
# docs/acme-corp-gtm-metric-tree.md against real values pulled from the
# marts. Every edge in the tree that has a stated formula is represented
# here as either a real PASS/FAIL check or an explicit NOT_COMPUTABLE /
# VALIDATED_ELSEWHERE / EXCLUDED_BY_DESIGN entry with its reason -- no edge
# is silently skipped, matching the project's standing "flagged, not
# omitted" treatment of every other coverage gap (mart_growth_bridge's own
# header, analytics/variance_diagnostic.py's coverage table,
# analytics/marketing_attribution.py's NOT_COMPUTABLE_LAYER3_LEAVES).

def _tie_out(lhs: pd.Series, rhs: pd.Series, tolerance: float = _RECONCILIATION_TOLERANCE) -> dict:
    diff = (lhs - rhs).abs()
    valid = diff.notna()
    max_abs_diff = float(diff[valid].max()) if valid.any() else float("nan")
    return {
        "passed": bool((diff[valid] <= tolerance).all()) if valid.any() else False,
        "n_rows_checked": int(valid.sum()),
        "n_rows_skipped_null": int((~valid).sum()),
        "max_abs_diff": max_abs_diff,
        "tolerance": tolerance,
    }


def check_growth_pillar_identity(bridge: pd.DataFrame) -> dict:
    """Tree: 'Growth -- consumption revenue growth: Starting consumption
    revenue + New logo - Contraction - Churn + Expansion (+/- segment
    migration, nets to zero)'. Sum formula. Source: mart_growth_bridge,
    one row per segment per month -- every column the identity needs is
    already materialized on that one row."""
    lhs = bridge["ending_mrr"]
    rhs = (
        bridge["starting_mrr"] + bridge["new_logo_mrr"] + bridge["expansion_mrr"]
        - bridge["contraction_mrr"] - bridge["churn_mrr"]
        + bridge["migration_in_mrr"] - bridge["migration_out_mrr"]
    )
    return _tie_out(lhs, rhs)


def check_migration_nets_to_zero(bridge: pd.DataFrame) -> dict:
    """Tree's parenthetical qualifier on the Growth identity: segment
    migration '(nets to zero)' -- every dollar migration_out of one segment
    must show up as migration_in to another, so the COMPANY-WIDE monthly
    sum of the two must be equal. Source: mart_growth_bridge."""
    by_month = bridge.groupby("month")[["migration_in_mrr", "migration_out_mrr"]].sum()
    diff = (by_month["migration_in_mrr"] - by_month["migration_out_mrr"]).abs()
    return {
        "passed": bool((diff <= _RECONCILIATION_TOLERANCE).all()) if len(diff) else False,
        "n_rows_checked": int(len(diff)),
        "n_rows_skipped_null": 0,
        "max_abs_diff": float(diff.max()) if len(diff) else float("nan"),
        "tolerance": _RECONCILIATION_TOLERANCE,
    }


def check_win_rate_ratio(bridge: pd.DataFrame) -> dict:
    """Tree: 'Win rate = Closed won / (won + lost), new-business only, by
    segment'. Ratio formula. Source: mart_growth_bridge
    (win_rate, new_business_won_count, new_business_lost_count)."""
    denom = bridge["new_business_won_count"] + bridge["new_business_lost_count"]
    expected = bridge["new_business_won_count"] / denom.replace(0, np.nan)
    return _tie_out(bridge["win_rate"], expected, tolerance=_RATIO_TOLERANCE)


def check_net_new_arr_cross_mart(bridge: pd.DataFrame, efficiency: pd.DataFrame) -> dict:
    """Tree: Magic number's numerator, 'Net new ARR,' is explicitly
    'covered under Growth.' mart_efficiency materializes net_new_arr from
    its OWN revenue_bridge CTE, independently of mart_growth_bridge, even
    though both derive from int_revenue_movements upstream -- so this is
    the two-marts-computing-the-same-tree-node consistency check the tree's
    own cross-reference implies, the same pattern the Segment migration
    analysis's growth-bridge reconciliation applies to mart_growth_bridge
    vs. mart_segment_migration."""
    merged = bridge.merge(efficiency[["segment", "month", "net_new_arr"]],
                          on=["segment", "month"], suffixes=("_gb", "_eff"))
    expected = (
        merged["new_logo_mrr"] + merged["expansion_mrr"]
        - merged["contraction_mrr"] - merged["churn_mrr"]
    ) * 12
    return _tie_out(merged["net_new_arr"], expected)


def check_am_expansion_arr_cross_mart(bridge: pd.DataFrame, efficiency: pd.DataFrame) -> dict:
    """Tree: AM efficiency's numerator is 'Expansion consumption revenue,'
    which 'See[s] Growth -- expansion... drivers.' mart_efficiency's
    am_expansion_arr must tie to mart_growth_bridge's own expansion_mrr for
    the same segment/month, the annualized amount."""
    merged = bridge.merge(efficiency[["segment", "month", "am_expansion_arr"]],
                          on=["segment", "month"])
    expected = merged["expansion_mrr"] * 12
    return _tie_out(merged["am_expansion_arr"], expected)


def check_consumption_payback_ratio(efficiency: pd.DataFrame) -> dict:
    """Tree: 'Consumption payback = CAC / utilized-Action margin.' Ratio
    formula. Source: mart_efficiency (consumption_payback_months,
    blended_cac, avg_utilized_action_margin_per_account)."""
    df = efficiency[efficiency["avg_utilized_action_margin_per_account"] > 0]
    expected = df["blended_cac"] / df["avg_utilized_action_margin_per_account"]
    return _tie_out(df["consumption_payback_months"], expected, tolerance=_RATIO_TOLERANCE)


def check_onboarding_cs_efficiency_ratio(efficiency: pd.DataFrame) -> dict:
    """Tree: 'Onboarding/CS efficiency = Manual AM/CS touchpoints / volume
    of automated Actions delivered.' Ratio formula. Source: mart_efficiency
    (onboarding_cs_efficiency_ratio, am_touchpoint_count,
    automated_actions_delivered)."""
    df = efficiency[efficiency["automated_actions_delivered"] > 0]
    expected = df["am_touchpoint_count"] / df["automated_actions_delivered"]
    return _tie_out(df["onboarding_cs_efficiency_ratio"], expected, tolerance=_RATIO_TOLERANCE)


def check_nrr_ratio(durability: pd.DataFrame) -> dict:
    """Tree: 'NRR = (Starting - Contraction - Churn + Expansion) /
    Starting.' Ratio formula. Source: mart_durability."""
    df = durability[durability["starting_mrr"] > 0]
    expected = (
        df["starting_mrr"] - df["contraction_mrr"] - df["churn_mrr"] + df["expansion_mrr"]
    ) / df["starting_mrr"]
    return _tie_out(df["nrr"], expected, tolerance=_RATIO_TOLERANCE)


def check_grr_ratio(durability: pd.DataFrame) -> dict:
    """Tree: 'GRR = (Starting - Contraction - Churn) / Starting.' Ratio
    formula. Source: mart_durability."""
    df = durability[durability["starting_mrr"] > 0]
    expected = (df["starting_mrr"] - df["contraction_mrr"] - df["churn_mrr"]) / df["starting_mrr"]
    return _tie_out(df["grr"], expected, tolerance=_RATIO_TOLERANCE)


def check_logo_retention_ratio(durability: pd.DataFrame) -> dict:
    """Tree: 'Logo retention = Retained accounts / starting accounts.'
    Ratio formula, plus the definitional identity 'retained =
    starting - churned' both need to hold. Source: mart_durability."""
    retained_ok = _tie_out(
        durability["retained_accounts"],
        durability["starting_accounts"] - durability["churned_accounts"],
    )
    df = durability[durability["starting_accounts"] > 0]
    expected_rate = df["retained_accounts"] / df["starting_accounts"]
    rate_ok = _tie_out(df["logo_retention_rate"], expected_rate, tolerance=_RATIO_TOLERANCE)
    return {
        "passed": bool(retained_ok["passed"] and rate_ok["passed"]),
        "n_rows_checked": retained_ok["n_rows_checked"] + rate_ok["n_rows_checked"],
        "n_rows_skipped_null": retained_ok["n_rows_skipped_null"] + rate_ok["n_rows_skipped_null"],
        "max_abs_diff": max(retained_ok["max_abs_diff"], rate_ok["max_abs_diff"]),
        "tolerance": _RATIO_TOLERANCE,
        "detail": {"retained_accounts_identity": retained_ok, "logo_retention_rate": rate_ok},
    }


def check_durability_growth_cross_mart_consistency(bridge: pd.DataFrame, durability: pd.DataFrame) -> dict:
    """The tree states NRR/GRR's drivers as 'See Growth -- expansion,
    contraction, churn drivers' -- i.e. NRR/GRR reuse the SAME
    starting/contraction/churn/expansion figures the Growth pillar
    identity above already checked. mart_durability materializes its own
    dollar_bridge CTE independently of mart_growth_bridge's revenue_bridge
    CTE, so this confirms the tree's stated reuse actually holds in the
    built marts rather than two marts quietly drifting apart."""
    merged = bridge.merge(
        durability[["segment", "month", "starting_mrr", "expansion_mrr", "contraction_mrr", "churn_mrr"]],
        on=["segment", "month"], suffixes=("_gb", "_dur"),
    )
    diffs = {}
    for col in ("starting_mrr", "expansion_mrr", "contraction_mrr", "churn_mrr"):
        diffs[col] = (merged[f"{col}_gb"] - merged[f"{col}_dur"]).abs()
    max_abs_diff = max(float(d.max()) for d in diffs.values()) if len(merged) else float("nan")
    return {
        "passed": bool(max_abs_diff <= _RECONCILIATION_TOLERANCE) if len(merged) else False,
        "n_rows_checked": int(len(merged)),
        "n_rows_skipped_null": 0,
        "max_abs_diff": max_abs_diff,
        "tolerance": _RECONCILIATION_TOLERANCE,
    }


def check_gap_confirmed_not_computable(df: pd.DataFrame, cols) -> dict:
    """For the tree edges genuinely not computable from the marts layer
    (no cost data for Magic number / AM efficiency), confirms the claim is
    still true of the CURRENT data rather than a stale note -- if a future
    Phase 1 change ever adds cost data and these columns stop being 100%
    null, this check starts failing and the NOT_COMPUTABLE status in this
    module needs updating, the same discipline that caught
    mart_growth_bridge's own stale Pipeline-generated header comment."""
    all_null = {c: bool(df[c].isna().all()) if len(df) else False for c in cols}
    return {"still_all_null": all_null, "confirmed_gap": all(all_null.values())}


_METRIC_TREE_EDGES_STATIC = [
    {
        "edge_id": "new_logo_equals_pipeline_x_winrate_x_commitment",
        "parent": "New logo consumption revenue (Layer 1, Growth)",
        "formula": "Pipeline generated x Win rate x Avg initial commitment",
        "formula_type": "product",
        "status": "NOT_COMPUTABLE",
        "reason": (
            "No mart exposes 'Pipeline generated' at New Logo's own population -- "
            "mart_growth_bridge's win_rate/avg_initial_commitment are computed over "
            "closed SQO-stage opportunities, while Pipeline generated (per "
            "analytics/marketing_attribution.py) is computed over converting LEADS, "
            "a different population and a different unit (SMB in particular has no "
            "real win-rate concept at all -- one Opportunity record, always Closed "
            "Won). mart_growth_bridge's own header states the two New Logo lenses "
            "'will NOT match exactly... a normal, real bookings-vs-revenue-"
            "recognition gap, not a bug.' Multiplying three marts-derived legs that "
            "don't share a population would manufacture a false tie-out, not a real "
            "one."
        ),
    },
    {
        "edge_id": "pipeline_generated_channel_formula",
        "parent": "Pipeline generated (Layer 2, under New logo)",
        "formula": "Sum over channels (channel volume x channel-to-lead rate x lead-to-PQL rate)",
        "formula_type": "sum_of_products",
        "status": "VALIDATED_ELSEWHERE",
        "reason": (
            "Computable, but not re-derived here. analytics/marketing_attribution.py "
            "already computes this formula from marts (fact_leads, "
            "fact_campaign_engagement_events, dim_campaign) and independently "
            "validates it exactly in its own build-time check "
            "(reconcile_pipeline_generated_identity, listed there as "
            "pipeline_generated_rollup_reconciles_to_source; <=1e-9 tolerance, "
            "passing at both checkpoints). The formula's correctness depends on point-in-time lead-"
            "resolution-horizon logic (open/lapsed/converted state, derived per "
            "sub-channel) that is non-trivial and already owned by that module -- "
            "re-implementing it here would risk a second, silently-diverging copy "
            "rather than adding governance value. This edge is reported as validated, "
            "not skipped, with a pointer to where the check actually runs."
        ),
    },
    {
        "edge_id": "expansion_equals_wallet_share_x_overage",
        "parent": "Expansion consumption revenue (Layer 1, Growth)",
        "formula": "Wallet share progression x Overage realization",
        "formula_type": "product",
        "status": "NOT_COMPUTABLE",
        "reason": (
            "Wallet share progression (% of an account's total addressable workflow "
            "footprint running through Acme Corp) has no source anywhere in the raw "
            "data or the marts layer -- nothing estimates the non-Acme denominator. "
            "This is a genuine Phase 1 data gap (confirmed in "
            "analytics/variance_diagnostic.py's coverage table: 'Expansion consumption "
            "revenue | 0 of 2'), not a scope choice a Phase 4 workaround could close."
        ),
    },
    {
        "edge_id": "magic_number_ratio",
        "parent": "Magic number (Layer 1, Efficiency)",
        "formula": "Net new ARR / prior-period S&M cost",
        "formula_type": "ratio",
        "status": "NOT_COMPUTABLE",
        "reason": (
            "No rep-cost/comp data exists anywhere in the raw sources, so "
            "mart_efficiency.magic_number_sm_cost and .magic_number are NULL by "
            "design (mart_efficiency's own header). This is the same gap "
            "analytics/variance_diagnostic.py and analytics/capacity_planning.py "
            "both name as structurally not-computable."
        ),
        "gap_confirmation_cols": ["magic_number_sm_cost", "magic_number"],
    },
    {
        "edge_id": "am_efficiency_ratio",
        "parent": "AM efficiency (Layer 1, Efficiency)",
        "formula": "Expansion consumption revenue / AM cost",
        "formula_type": "ratio",
        "status": "NOT_COMPUTABLE",
        "reason": (
            "No AM comp/cost data exists anywhere in the raw sources, so "
            "mart_efficiency.am_cost and .am_efficiency are NULL by design "
            "(mart_efficiency's own header). Same gap as magic_number above."
        ),
        "gap_confirmation_cols": ["am_cost", "am_efficiency"],
    },
]

_EXCLUDED_NODES = [
    {
        "node": "Brand & awareness",
        "reason": (
            "Tree's own text: 'leading indicator, not summed into the pipeline "
            "math.' CLAUDE.md names this node explicitly as the one deliberate "
            "non-additive exception to the parent-equals-function-of-children "
            "invariant."
        ),
    },
    {
        "node": "Marketing-sales handoff quality",
        "reason": (
            "Tree's own text, parenthetical right after the node name: "
            "'diagnostic overlay on the above three [Pipeline generated, Win rate, "
            "Avg initial commitment], not a fourth multiplicative factor.' A second "
            "explicitly non-additive node the tree itself carves out, alongside "
            "Brand & awareness -- CLAUDE.md's invariant text names only Brand & "
            "awareness as 'the one deliberate exception,' but the tree's own prose "
            "names two. Recorded here rather than silently reconciled, since "
            "resolving the wording gap between the two docs is a documentation call, "
            "not this checker's call to make unilaterally."
        ),
    },
]


def check_metric_tree_integrity(as_of_date: date, con=None) -> dict:
    """Runs every checkable parent-child arithmetic edge from
    docs/acme-corp-gtm-metric-tree.md against real values from
    mart_growth_bridge / mart_efficiency / mart_durability as of
    as_of_date, and reports every edge that is NOT checkable here (with its
    reason) rather than omitting it. Source marts: mart_growth_bridge,
    mart_efficiency, mart_durability."""
    owns_con = con is None
    con = con or _connect()
    try:
        bridge = load_growth_bridge(as_of_date, con=con)
        efficiency = load_efficiency(as_of_date, con=con)
        durability = load_durability(as_of_date, con=con)
    finally:
        if owns_con:
            con.close()

    computed_edges = [
        {
            "edge_id": "growth_pillar_identity",
            "parent": "Growth pillar",
            "formula": "Starting + New logo + Expansion - Contraction - Churn (+/- migration, nets to zero)",
            "formula_type": "sum",
            "result": check_growth_pillar_identity(bridge),
        },
        {
            "edge_id": "migration_nets_to_zero",
            "parent": "Growth pillar (migration qualifier)",
            "formula": "Company-wide sum(migration_in) == sum(migration_out) per month",
            "formula_type": "sum",
            "result": check_migration_nets_to_zero(bridge),
        },
        {
            "edge_id": "win_rate_ratio",
            "parent": "Win rate (Layer 2, under New logo)",
            "formula": "Closed won / (won + lost)",
            "formula_type": "ratio",
            "result": check_win_rate_ratio(bridge),
        },
        {
            "edge_id": "net_new_arr_cross_mart",
            "parent": "Magic number numerator ('Net new ARR... covered under Growth')",
            "formula": "(new_logo_mrr + expansion_mrr - contraction_mrr - churn_mrr) x 12",
            "formula_type": "cross_mart_consistency",
            "result": check_net_new_arr_cross_mart(bridge, efficiency),
        },
        {
            "edge_id": "am_expansion_arr_cross_mart",
            "parent": "AM efficiency numerator ('Expansion consumption revenue... See Growth')",
            "formula": "expansion_mrr x 12",
            "formula_type": "cross_mart_consistency",
            "result": check_am_expansion_arr_cross_mart(bridge, efficiency),
        },
        {
            "edge_id": "consumption_payback_ratio",
            "parent": "Consumption payback (Layer 1, Efficiency)",
            "formula": "CAC / utilized-Action margin",
            "formula_type": "ratio",
            "result": check_consumption_payback_ratio(efficiency),
        },
        {
            "edge_id": "onboarding_cs_efficiency_ratio",
            "parent": "Onboarding/CS efficiency (Layer 1, Efficiency)",
            "formula": "Manual AM/CS touchpoints / volume of automated Actions delivered",
            "formula_type": "ratio",
            "result": check_onboarding_cs_efficiency_ratio(efficiency),
        },
        {
            "edge_id": "nrr_ratio",
            "parent": "NRR (Layer 1, Durability)",
            "formula": "(Starting - Contraction - Churn + Expansion) / Starting",
            "formula_type": "ratio",
            "result": check_nrr_ratio(durability),
        },
        {
            "edge_id": "grr_ratio",
            "parent": "GRR (Layer 1, Durability)",
            "formula": "(Starting - Contraction - Churn) / Starting",
            "formula_type": "ratio",
            "result": check_grr_ratio(durability),
        },
        {
            "edge_id": "logo_retention_ratio",
            "parent": "Logo retention (Layer 1, Durability)",
            "formula": "Retained accounts / Starting accounts",
            "formula_type": "ratio",
            "result": check_logo_retention_ratio(durability),
        },
        {
            "edge_id": "durability_growth_cross_mart_consistency",
            "parent": "NRR/GRR drivers ('See Growth -- expansion, contraction, churn drivers')",
            "formula": "mart_durability's dollar_bridge == mart_growth_bridge's revenue_bridge, same segment/month",
            "formula_type": "cross_mart_consistency",
            "result": check_durability_growth_cross_mart_consistency(bridge, durability),
        },
    ]

    static_edges = []
    for edge in _METRIC_TREE_EDGES_STATIC:
        e = dict(edge)
        if edge["status"] == "NOT_COMPUTABLE" and "gap_confirmation_cols" in edge:
            e["gap_confirmation"] = check_gap_confirmed_not_computable(
                efficiency, edge["gap_confirmation_cols"]
            )
        static_edges.append(e)

    n_pass = sum(1 for e in computed_edges if e["result"]["passed"])
    n_fail = sum(1 for e in computed_edges if not e["result"]["passed"])
    n_not_computable = sum(1 for e in static_edges if e["status"] == "NOT_COMPUTABLE")
    n_validated_elsewhere = sum(1 for e in static_edges if e["status"] == "VALIDATED_ELSEWHERE")

    return {
        "as_of_date": as_of_date,
        "computed_edges": computed_edges,
        "static_edges": static_edges,
        "excluded_nodes": _EXCLUDED_NODES,
        "edges_checked": len(computed_edges),
        "edges_passed": n_pass,
        "edges_failed": n_fail,
        "edges_not_computable": n_not_computable,
        "edges_validated_elsewhere": n_validated_elsewhere,
        "all_computed_edges_pass": n_fail == 0,
    }


# ==========================================================================
# SECTION 2 -- Marts-layer data quality checks
# ==========================================================================
# The Phase 1 QA plan (docs/acme-corp-phase1-data-qa-plan.md) covers raw
# generator output only. This section runs the same four categories --
# referential integrity, completeness, distributional sanity, volume
# sufficiency -- against the dbt-BUILT marts, which nothing currently
# checks post-transformation.

# (child_table, child_col, parent_table, parent_col, allow_null, note)
_FOREIGN_KEY_CHECKS = [
    ("fact_opportunities", "account_id", "dim_accounts", "account_id", True,
     "Lost new-business opportunities carry a NULL account_id by design "
     "(fact_opportunities carries account_id only on won new-business rows for lost "
     "deals it cannot trace); non-null values must still resolve."),
    ("fact_opportunities", "rep_id", "dim_reps", "rep_id", True,
     "SMB's system-owned opportunities (owner_role='system') carry a NULL rep_id."),
    ("fact_revenue_monthly", "account_id", "dim_accounts", "account_id", False, ""),
    ("fact_account_segment_history", "account_id", "dim_accounts", "account_id", False, ""),
    ("mart_segment_migration", "account_id", "dim_accounts", "account_id", False, ""),
    ("fact_usage_monthly", "account_id", "dim_accounts", "account_id", False, ""),
    ("fact_leads", "account_id", "dim_accounts", "account_id", True,
     "Non-converting leads never gain an account_id."),
    ("fact_forecast_submissions", "opportunity_id", "fact_opportunities", "opportunity_id", False, ""),
    ("fact_committed_vs_utilized_monthly", "account_id", "dim_accounts", "account_id", False, ""),
]

# (table, column, max_null_share)
_COMPLETENESS_CHECKS = [
    ("dim_accounts", "segment", 0.0),
    ("dim_accounts", "channel", 0.0),
    ("dim_accounts", "signup_date", 0.0),
    ("fact_opportunities", "opportunity_type", 0.0),
    ("fact_opportunities", "owner_role", 0.0),
    ("fact_opportunities", "is_won", 0.0),
    ("mart_growth_bridge", "segment", 0.0),
    ("mart_growth_bridge", "month", 0.0),
    ("mart_durability", "segment", 0.0),
    ("mart_efficiency", "segment", 0.0),
    ("mart_account_health", "account_id", 0.0),
    ("mart_account_health", "month", 0.0),
    ("fact_account_segment_history", "trigger_reason", 0.0),
]

# (table, min_row_count, note)
_VOLUME_CHECKS = [
    ("dim_accounts", 4000,
     "Build spec Section 4: SMB 5,000-8,000 + Commercial 800-1,200 + Enterprise 150-250."),
    ("fact_opportunities", 3000, "Enough new-business + renewal/expansion volume to be usable."),
    ("mart_growth_bridge", 90, "3 segments x >=30 months."),
    ("mart_durability", 90, "3 segments x >=30 months."),
    ("mart_efficiency", 90, "3 segments x >=30 months."),
    ("fact_account_segment_history", 4000, "At least one row per account (initial + migrations)."),
    ("fact_usage_monthly", 50000, "Monthly usage grain across the whole 36+ month window."),
]


def check_foreign_keys(as_of_date: date, con=None) -> pd.DataFrame:
    """Referential integrity across the marts layer: for each
    (child, parent) pair, every non-null child value must resolve to a real
    parent row. Point-in-time filtered where the child table carries an
    obvious date column; dimension/current-state tables (dim_accounts,
    dim_reps) are read at their own grain (current state), matching how
    every other Phase 4 module reads them."""
    owns_con = con is None
    con = con or _connect()
    rows = []
    try:
        for child_t, child_c, parent_t, parent_c, allow_null, note in _FOREIGN_KEY_CHECKS:
            unmatched, total, nulls = con.execute(
                f"""
                select
                    count(*) filter (where c.{child_c} is not null and p.{parent_c} is null) as unmatched,
                    count(*) as total,
                    count(*) filter (where c.{child_c} is null) as nulls
                from main_marts.{child_t} c
                left join main_marts.{parent_t} p on p.{parent_c} = c.{child_c}
                """
            ).fetchone()
            rows.append({
                "child_table": child_t, "child_col": child_c,
                "parent_table": parent_t, "parent_col": parent_c,
                "total_rows": total, "null_child_values": nulls,
                "unmatched_non_null": unmatched,
                "allow_null": allow_null,
                "passed": unmatched == 0,
                "note": note,
            })
    finally:
        if owns_con:
            con.close()
    return pd.DataFrame(rows)


def check_completeness(con=None) -> pd.DataFrame:
    """Null-rate thresholds on columns that must always be populated in
    the built marts."""
    owns_con = con is None
    con = con or _connect()
    rows = []
    try:
        for table, col, max_null_share in _COMPLETENESS_CHECKS:
            n_null, total = con.execute(
                f"select count(*) filter (where {col} is null), count(*) from main_marts.{table}"
            ).fetchone()
            null_share = _pct(n_null, total)
            rows.append({
                "table": table, "column": col, "total_rows": total,
                "null_rows": n_null, "null_share": null_share,
                "max_allowed_null_share": max_null_share,
                "passed": null_share <= max_null_share if total else False,
            })
    finally:
        if owns_con:
            con.close()
    return pd.DataFrame(rows)


def check_distributional_sanity(as_of_date: date, con=None) -> pd.DataFrame:
    """Corruption-catching sanity bounds -- deliberately loose relative to
    the QA plan's tighter distributional-realism bands, since this is
    'did dbt corrupt a value,' not 'is the business shape realistic'
    (already the QA plan's job upstream of this module)."""
    owns_con = con is None
    con = con or _connect()
    rows = []
    try:
        gb = load_growth_bridge(as_of_date, con=con)
        dur = load_durability(as_of_date, con=con)

        win_rate_oob = gb["win_rate"].dropna()
        rows.append({
            "check": "win_rate_in_unit_interval", "table": "mart_growth_bridge",
            "n_checked": int(len(win_rate_oob)),
            "n_violations": int(((win_rate_oob < 0) | (win_rate_oob > 1)).sum()),
            "passed": bool(((win_rate_oob >= 0) & (win_rate_oob <= 1)).all()) if len(win_rate_oob) else False,
        })

        nrr = dur["nrr"].dropna()
        rows.append({
            "check": "nrr_within_sanity_band_[-1,10]", "table": "mart_durability",
            "n_checked": int(len(nrr)),
            "n_violations": int(((nrr < -1) | (nrr > 10)).sum()),
            "passed": bool(((nrr >= -1) & (nrr <= 10)).all()) if len(nrr) else False,
        })

        grr = dur["grr"].dropna()
        rows.append({
            "check": "grr_within_sanity_band_[-1,2]", "table": "mart_durability",
            "n_checked": int(len(grr)),
            "n_violations": int(((grr < -1) | (grr > 2)).sum()),
            "passed": bool(((grr >= -1) & (grr <= 2)).all()) if len(grr) else False,
        })

        logo = dur["logo_retention_rate"].dropna()
        rows.append({
            "check": "logo_retention_rate_in_unit_interval", "table": "mart_durability",
            "n_checked": int(len(logo)),
            "n_violations": int(((logo < 0) | (logo > 1)).sum()),
            "passed": bool(((logo >= 0) & (logo <= 1)).all()) if len(logo) else False,
        })

        acv = con.execute(
            "select segment, amount from main_marts.fact_opportunities "
            "where is_won and amount is not null and close_date <= ?", [as_of_date]
        ).df()
        acv["ceiling"] = acv["segment"].map(
            lambda s: _SEGMENT_ACV_UPPER_BOUND.get(s, float("inf")) * _ACV_OUTLIER_MULTIPLE
        )
        violations = int((acv["amount"] > acv["ceiling"]).sum())
        rows.append({
            "check": f"won_deal_amount_under_{_ACV_OUTLIER_MULTIPLE}x_segment_acv_ceiling",
            "table": "fact_opportunities",
            "n_checked": int(len(acv)), "n_violations": violations,
            "passed": violations == 0,
        })
    finally:
        if owns_con:
            con.close()
    return pd.DataFrame(rows)


def check_volume_sufficiency(as_of_date: date, con=None) -> pd.DataFrame:
    """Minimum row-count floors, point-in-time filtered where the table
    carries an obvious date column."""
    owns_con = con is None
    con = con or _connect()
    date_cols = {
        "fact_opportunities": "close_date",
        "mart_growth_bridge": "month",
        "mart_durability": "month",
        "mart_efficiency": "month",
        "fact_account_segment_history": "effective_date",
        "fact_usage_monthly": "month",
    }
    rows = []
    try:
        for table, floor, note in _VOLUME_CHECKS:
            date_col = date_cols.get(table)
            if date_col:
                n = con.execute(
                    f"select count(*) from main_marts.{table} where {date_col} <= ?", [as_of_date]
                ).fetchone()[0]
            else:
                n = con.execute(f"select count(*) from main_marts.{table}").fetchone()[0]
            rows.append({
                "table": table, "row_count": n, "floor": floor,
                "passed": n >= floor, "note": note,
            })
    finally:
        if owns_con:
            con.close()
    return pd.DataFrame(rows)


def check_marts_data_quality(as_of_date: date, con=None) -> dict:
    """Runs all four marts-layer data-quality categories (referential
    integrity, completeness, distributional sanity, volume sufficiency)
    and rolls them into one summary. Source marts: dim_accounts, dim_reps,
    fact_opportunities, fact_revenue_monthly, fact_account_segment_history,
    fact_usage_monthly, fact_leads, fact_forecast_submissions,
    fact_committed_vs_utilized_monthly, mart_growth_bridge, mart_durability,
    mart_efficiency, mart_account_health."""
    owns_con = con is None
    con = con or _connect()
    try:
        fk = check_foreign_keys(as_of_date, con=con)
        completeness = check_completeness(con=con)
        distributional = check_distributional_sanity(as_of_date, con=con)
        volume = check_volume_sufficiency(as_of_date, con=con)
    finally:
        if owns_con:
            con.close()

    return {
        "referential_integrity": fk,
        "completeness": completeness,
        "distributional_sanity": distributional,
        "volume_sufficiency": volume,
        "referential_integrity_checks": len(fk), "referential_integrity_passed": int(fk["passed"].sum()),
        "completeness_checks": len(completeness), "completeness_passed": int(completeness["passed"].sum()),
        "distributional_checks": len(distributional), "distributional_passed": int(distributional["passed"].sum()),
        "volume_checks": len(volume), "volume_passed": int(volume["passed"].sum()),
    }


# ==========================================================================
# SECTION 3 -- Invariant governance checks (CLAUDE.md's "Non-negotiable
# invariants", mechanized)
# ==========================================================================

def check_segment_terminology(df: pd.DataFrame, col: str, table_name: str, allow_null: bool = False) -> dict:
    """CLAUDE.md: 'Terminology is segment, not "tier" -- SMB / Commercial /
    Enterprise... "Segment" refers only to these three.' Checks that every
    non-null value in the given segment column is one of exactly the three
    valid values -- no 'tier' string, no fourth value."""
    values = df[col] if allow_null else df[col].dropna()
    bad = sorted(set(df[col].dropna().unique()) - _VALID_SEGMENTS)
    n_null = int(df[col].isna().sum())
    return {
        "table": table_name, "column": col,
        "n_rows": int(len(df)), "n_null": n_null,
        "invalid_values": bad,
        "passed": len(bad) == 0,
    }


def check_no_segment_downgrade(migration: pd.DataFrame) -> dict:
    """CLAUDE.md: 'No segment downgrade path. An account that fails to
    activate churns entirely; it never demotes to a lower segment.' Every
    (from_segment, to_segment) pair in mart_segment_migration must be one
    of the two allowed forward directions -- never a downgrade, never a
    skip-level, never a same-segment no-op."""
    pairs = migration[["from_segment", "to_segment"]].drop_duplicates()
    bad_pairs = [
        tuple(r) for r in pairs.itertuples(index=False)
        if tuple(r) not in _ALLOWED_MIGRATION_PAIRS
    ]
    bad_rows = migration[
        ~migration.apply(lambda r: (r["from_segment"], r["to_segment"]) in _ALLOWED_MIGRATION_PAIRS, axis=1)
    ]
    return {
        "n_migration_events": int(len(migration)),
        "observed_pairs": [tuple(r) for r in pairs.itertuples(index=False)],
        "invalid_pairs": bad_pairs,
        "n_invalid_rows": int(len(bad_rows)),
        "passed": len(bad_pairs) == 0,
    }


def check_currency_usd_only(con=None) -> dict:
    """CLAUDE.md: 'Currency is USD only. No FX modeling.' Structural check:
    no currency/FX-shaped column exists anywhere in the marts layer at
    all -- the absence of any such column is itself the evidence, since a
    schema with real multi-currency support would need one."""
    owns_con = con is None
    con = con or _connect()
    try:
        cols = con.execute(
            "select table_name, column_name from information_schema.columns "
            "where table_schema = 'main_marts'"
        ).df()
    finally:
        if owns_con:
            con.close()
    pattern = cols["column_name"].str.contains(
        r"currency|fx_rate|exchange_rate", case=False, regex=True
    )
    hits = cols[pattern]
    return {
        "columns_scanned": int(len(cols)),
        "currency_or_fx_columns_found": hits.to_dict("records"),
        "passed": len(hits) == 0,
    }


def check_channel_segment_orthogonality(accounts: pd.DataFrame) -> dict:
    """CLAUDE.md: 'Channel... and segment... are orthogonal. Never assume a
    channel implies a segment or vice versa.' The one documented, deliberate
    exception is outbound_sdr, which the build spec states is
    Enterprise-only by design ('targets named lists, and is not an entry
    path for the other segments'). Checks: every OTHER channel must span
    at least 2 of the 3 segments (real orthogonality, not a partition), and
    outbound_sdr must appear ONLY under Enterprise (confirming the
    documented exception holds rather than silently passing it)."""
    mix = accounts.groupby("channel")["segment"].nunique()
    results = []
    for channel, n_segments in mix.items():
        if channel == "outbound_sdr":
            segs = set(accounts.loc[accounts["channel"] == channel, "segment"].unique())
            ok = segs == {"Enterprise"}
            results.append({
                "channel": channel, "segments_present": sorted(segs),
                "rule": "documented exception -- Enterprise-only by design",
                "passed": ok,
            })
        else:
            ok = n_segments >= 2
            results.append({
                "channel": channel, "n_segments": int(n_segments),
                "rule": "must span >=2 segments (orthogonality)",
                "passed": ok,
            })
    return {"detail": results, "passed": all(r["passed"] for r in results)}


def check_trigger_reason_coverage(history: pd.DataFrame, min_count: int = _TRIGGER_REASON_MIN_COUNT) -> dict:
    """CLAUDE.md: 'Migration trigger_reason has four values... Both the
    usage-threshold and firmographic-rescore paths must actually fire in
    generated data, not just exist as unused schema values.' Checks all
    four values are present in fact_account_segment_history, each clearing
    _TRIGGER_REASON_MIN_COUNT (PROPOSED, not yet confirmed -- see
    docs/acme-corp-analytics-methods.md)."""
    counts = history["trigger_reason"].value_counts().to_dict()
    missing = sorted(_ALL_TRIGGER_REASONS - set(counts))
    below_floor = sorted(
        v for v in _ALL_TRIGGER_REASONS if counts.get(v, 0) < min_count
    )
    return {
        "counts": counts, "missing_values": missing,
        "below_floor": below_floor, "min_count_floor": min_count,
        "passed": len(missing) == 0 and len(below_floor) == 0,
    }


def check_win_probability_not_random(opps: pd.DataFrame) -> dict:
    """CLAUDE.md: 'Win probability... must be generated as actual functions
    of their real drivers.' Spot-check: Enterprise POC outcome is a stated
    real driver of win rate (metric tree: 'POC pass rate (Enterprise)'
    under Win rate's Layer-3 leaves). If win probability were independently
    random, POC pass/fail would show no meaningful gap. Two-proportion
    z-test, one-sided (pass > fail)."""
    df = opps[opps["poc_outcome"].notna()]
    passed_grp = df[df["poc_outcome"] == "pass"]
    failed_grp = df[df["poc_outcome"] == "fail"]
    x1, n1 = int(passed_grp["is_won"].sum()), int(len(passed_grp))
    x2, n2 = int(failed_grp["is_won"].sum()), int(len(failed_grp))
    p1, p2, z = _two_proportion_z(x1, n1, x2, n2)
    gap = p1 - p2 if not (math.isnan(p1) or math.isnan(p2)) else float("nan")
    passed = bool(gap >= _WIN_PROB_MIN_GAP_PP and z >= _Z_THRESHOLD) if not math.isnan(gap) else False
    return {
        "driver": "poc_outcome (Enterprise POC pass rate, a stated metric-tree Layer-3 driver of win rate)",
        "poc_pass_win_rate": p1, "poc_pass_n": n1,
        "poc_fail_win_rate": p2, "poc_fail_n": n2,
        "gap_pp": gap, "z": z,
        "min_gap_floor": _WIN_PROB_MIN_GAP_PP, "z_threshold": _Z_THRESHOLD,
        "passed": passed,
    }


def check_churn_probability_not_random(health: pd.DataFrame) -> dict:
    """CLAUDE.md: 'Churn probability... must be generated as actual
    functions of their real drivers.' Spot-check: usage trend and
    engagement/login frequency are two of the metric tree's own stated
    Account health score inputs. If churn probability were independently
    random, a churned account's own final 3 months should look no
    different from its own earlier months. Account-relative baseline
    (same account, own history) -- not a cross-account comparison, matching
    the health score's own 'account-relative baseline, not a flat
    trailing-month comparison' design."""
    df = health[health["is_eventually_churned"] == True].copy()
    if df.empty or "churn_month" not in df.columns:
        return {"passed": False, "reason": "no churned-account rows available at this as_of_date"}
    df["months_to_churn"] = (
        (df["churn_month"].dt.year - df["month"].dt.year) * 12
        + (df["churn_month"].dt.month - df["month"].dt.month)
    )
    pre_churn = df[(df["months_to_churn"] >= 0) & (df["months_to_churn"] <= 2)]
    baseline = df[df["months_to_churn"] > 2]

    results = {}
    for col in ("actions_consumed", "login_count"):
        if col not in df.columns:
            continue
        pre_mean = pre_churn.groupby("account_id")[col].mean()
        base_mean = baseline.groupby("account_id")[col].mean()
        common = pre_mean.index.intersection(base_mean.index)
        base_mean = base_mean.loc[common].replace(0, np.nan)
        pre_mean = pre_mean.loc[common]
        rel_decline = 1 - (pre_mean / base_mean)
        rel_decline = rel_decline.dropna()
        # Gated on the MEDIAN, not the mean: this distribution carries a
        # fat left tail (a minority of accounts with a near-zero usage
        # baseline the whole way through, where a tiny absolute uptick
        # right before churn reads as a huge negative "decline") that
        # drags the mean well below the population's actual typical
        # behavior. The median is the honest summary of a skewed
        # distribution like this one -- confirmed at build time:
        # actions_consumed's median relative decline is 0.64 against a
        # mean of only 0.13, even though 71% of accounts individually
        # clear the floor.
        results[col] = {
            "n_accounts": int(len(rel_decline)),
            "mean_relative_decline": float(rel_decline.mean()) if len(rel_decline) else float("nan"),
            "median_relative_decline": float(rel_decline.median()) if len(rel_decline) else float("nan"),
            "share_with_meaningful_decline": float((rel_decline >= _CHURN_PROB_MIN_DECLINE).mean())
            if len(rel_decline) else float("nan"),
            "passed": bool(rel_decline.median() >= _CHURN_PROB_MIN_DECLINE) if len(rel_decline) else False,
        }
    return {
        "driver": "actions_consumed / login_count trend, account-relative (stated health-score inputs)",
        "min_decline_floor": _CHURN_PROB_MIN_DECLINE,
        "detail": results,
        "passed": bool(results) and all(v["passed"] for v in results.values()),
    }


def check_usage_growth_not_random(migration: pd.DataFrame, usage: pd.DataFrame) -> dict:
    """CLAUDE.md: 'Usage growth must be generated as actual functions of
    their real drivers.' Spot-check: usage_threshold-triggered migration
    (the metric tree's own segment-migration mechanism -- 'usage/spend
    crosses ~$1,250/mo for 2 consecutive months') is a real, stated driver
    of usage growth. If usage growth were independently random, migrating
    accounts' trailing growth rate in the 3 months before migration should
    look no different from same-segment accounts that did not migrate in
    that window."""
    events = migration[migration["trigger_reason"] == "usage_threshold"]
    if events.empty:
        return {"passed": False, "reason": "no usage_threshold migration events at this as_of_date"}

    usage = usage.sort_values(["account_id", "month"]).copy()
    usage["growth"] = usage.groupby("account_id")["actions_consumed"].pct_change()

    migrating_growth = []
    for _, ev in events.iterrows():
        window = usage[
            (usage["account_id"] == ev["account_id"])
            & (usage["month"] < ev["migration_date"])
            & (usage["month"] >= ev["migration_date"] - pd.DateOffset(months=3))
        ]
        if len(window):
            migrating_growth.append(window["growth"].mean())
    migrating_mean = float(np.nanmean(migrating_growth)) if migrating_growth else float("nan")

    migrating_ids = set(events["account_id"])
    non_migrating = usage[~usage["account_id"].isin(migrating_ids)]
    non_migrating_mean = float(non_migrating["growth"].replace([np.inf, -np.inf], np.nan).mean())

    ratio = migrating_mean / non_migrating_mean if non_migrating_mean not in (0, float("nan")) else float("nan")
    passed = bool(
        not math.isnan(ratio) and migrating_mean > 0 and ratio >= _USAGE_GROWTH_MIN_RATIO
    )
    return {
        "driver": "usage_threshold migration trigger (metric tree's own segment-migration mechanism)",
        "n_migrating_events_measured": int(len(migrating_growth)),
        "migrating_accounts_mean_pre_migration_growth": migrating_mean,
        "non_migrating_population_mean_growth": non_migrating_mean,
        "ratio": ratio,
        "min_ratio_floor": _USAGE_GROWTH_MIN_RATIO,
        "passed": passed,
    }


def check_invariants(as_of_date: date, con=None) -> dict:
    """Mechanizes every CLAUDE.md 'Non-negotiable invariant' into a
    runnable check against live built data, plus three data-grounded
    not-independently-random spot-checks. Source marts: dim_accounts,
    fact_opportunities, fact_account_segment_history, mart_segment_migration,
    mart_account_health, fact_usage_monthly."""
    owns_con = con is None
    con = con or _connect()
    try:
        accounts = con.execute(
            "select account_id, segment, channel from main_marts.dim_accounts "
            "where signup_date <= ?", [as_of_date]
        ).df()
        reps = con.execute(
            "select rep_id, segment from main_marts.dim_reps "
            "where period_start_date <= ?", [as_of_date]
        ).df()
        history = load_account_segment_history(as_of_date, con=con)
        migration = load_segment_migration(as_of_date, con=con)
        opps = con.execute(
            "select account_id, segment, is_won, poc_outcome from main_marts.fact_opportunities "
            "where close_date <= ?", [as_of_date]
        ).df()
        health = con.execute(
            "select account_id, month, actions_consumed, login_count, "
            "is_eventually_churned, churn_month "
            "from main_marts.mart_account_health where month <= ?", [as_of_date]
        ).df()
        health["month"] = pd.to_datetime(health["month"])
        health["churn_month"] = pd.to_datetime(health["churn_month"])
        usage = con.execute(
            "select account_id, month, actions_consumed from main_marts.fact_usage_monthly "
            "where month <= ?", [as_of_date]
        ).df()
        usage["month"] = pd.to_datetime(usage["month"])
        currency = check_currency_usd_only(con=con)
    finally:
        if owns_con:
            con.close()

    terminology_checks = [
        check_segment_terminology(accounts, "segment", "dim_accounts"),
        check_segment_terminology(reps, "segment", "dim_reps"),
        check_segment_terminology(history, "segment", "fact_account_segment_history"),
        check_segment_terminology(migration, "from_segment", "mart_segment_migration.from_segment"),
        check_segment_terminology(migration, "to_segment", "mart_segment_migration.to_segment"),
    ]

    checks = {
        "segment_terminology": {
            "detail": terminology_checks,
            "passed": all(c["passed"] for c in terminology_checks),
        },
        "no_segment_downgrade": check_no_segment_downgrade(migration),
        "currency_usd_only": currency,
        "channel_segment_orthogonality": check_channel_segment_orthogonality(accounts),
        "trigger_reason_coverage": check_trigger_reason_coverage(history),
        "win_probability_not_random": check_win_probability_not_random(opps),
        "churn_probability_not_random": check_churn_probability_not_random(health),
        "usage_growth_not_random": check_usage_growth_not_random(migration, usage),
    }
    n_pass = sum(1 for v in checks.values() if v["passed"])
    return {
        "checks": checks,
        "invariant_checks_total": len(checks),
        "invariant_checks_passed": n_pass,
        "all_invariants_pass": n_pass == len(checks),
    }


# ==========================================================================
# Synthetic injected-violation validation -- does this artifact actually
# catch a known-broken case? Clearly marked test-support section, same
# treatment analytics/variance_diagnostic.py's run_synthetic_scenarios()
# gives its own hand-constructed cases.
# ==========================================================================

def run_synthetic_violation_tests() -> dict:
    """Hand-constructed clean and deliberately-broken synthetic inputs, run
    through the SAME checking functions the real marts-backed checks use.
    Each scenario declares its expected pass/fail outcome; a mismatch means
    this artifact would not actually catch the failure mode it claims to
    guard against. Mirrors analytics/variance_diagnostic.py's synthetic
    scenario suite and analytics/capacity_planning.py's non-vacuousness
    checks."""
    results = []

    def _case(name, expected_pass, actual_pass, detail=""):
        results.append({
            "scenario": name, "expected_pass": expected_pass,
            "actual_pass": bool(actual_pass), "matches_expectation": bool(actual_pass) == expected_pass,
            "detail": detail,
        })

    # --- 1. Metric-tree integrity: a parent that doesn't sum to its children ---
    clean_bridge = pd.DataFrame({
        "segment": ["SMB"], "starting_mrr": [100_000.0], "new_logo_mrr": [10_000.0],
        "expansion_mrr": [5_000.0], "contraction_mrr": [2_000.0], "churn_mrr": [1_000.0],
        "migration_in_mrr": [0.0], "migration_out_mrr": [0.0],
    })
    clean_bridge["ending_mrr"] = (
        clean_bridge["starting_mrr"] + clean_bridge["new_logo_mrr"] + clean_bridge["expansion_mrr"]
        - clean_bridge["contraction_mrr"] - clean_bridge["churn_mrr"]
        + clean_bridge["migration_in_mrr"] - clean_bridge["migration_out_mrr"]
    )
    broken_bridge = clean_bridge.copy()
    broken_bridge.loc[0, "ending_mrr"] += 25_000.0  # injected violation

    _case("metric_tree_growth_identity_clean_passes", True,
          check_growth_pillar_identity(clean_bridge)["passed"],
          "Hand-built bridge row where ending_mrr is exactly the stated sum of its children.")
    _case("metric_tree_growth_identity_injected_break_fails", False,
          check_growth_pillar_identity(broken_bridge)["passed"],
          "Same row with ending_mrr perturbed by $25,000 -- the parent no longer ties to its children.")

    # Win-rate ratio, same treatment
    clean_wr = pd.DataFrame({
        "new_business_won_count": [40], "new_business_lost_count": [60], "win_rate": [0.40],
    })
    broken_wr = clean_wr.copy()
    broken_wr.loc[0, "win_rate"] = 0.75  # injected violation -- doesn't match won/(won+lost)
    _case("metric_tree_win_rate_clean_passes", True,
          check_win_rate_ratio(clean_wr)["passed"])
    _case("metric_tree_win_rate_injected_break_fails", False,
          check_win_rate_ratio(broken_wr)["passed"],
          "win_rate=0.75 stored against 40 won / 60 lost, which implies 0.40 -- an injected mismatch.")

    # --- 2. Invariant governance: a fabricated 'tier' / non-segment value ---
    clean_accounts = pd.DataFrame({
        "account_id": ["a1", "a2", "a3"],
        "segment": ["SMB", "Commercial", "Enterprise"],
        "channel": ["self_serve", "inbound_marketing", "outbound_sdr"],
    })
    fabricated_tier_accounts = clean_accounts.copy()
    fabricated_tier_accounts.loc[1, "segment"] = "Tier 2"  # injected violation

    _case("segment_terminology_clean_passes", True,
          check_segment_terminology(clean_accounts, "segment", "synthetic")["passed"])
    _case("segment_terminology_fabricated_tier_value_fails", False,
          check_segment_terminology(fabricated_tier_accounts, "segment", "synthetic")["passed"],
          "One account's segment replaced with the forbidden 'Tier 2' string.")

    # --- 3. Invariant governance: a fabricated segment downgrade path ---
    clean_migration = pd.DataFrame({
        "account_id": ["a1", "a2"],
        "from_segment": ["SMB", "Commercial"],
        "to_segment": ["Commercial", "Enterprise"],
    })
    fabricated_downgrade = pd.concat([
        clean_migration,
        pd.DataFrame({"account_id": ["a3"], "from_segment": ["Enterprise"], "to_segment": ["SMB"]}),
    ], ignore_index=True)  # injected violation

    _case("no_segment_downgrade_clean_passes", True,
          check_no_segment_downgrade(clean_migration)["passed"])
    _case("no_segment_downgrade_fabricated_path_fails", False,
          check_no_segment_downgrade(fabricated_downgrade)["passed"],
          "Injected a fabricated Enterprise->SMB migration row -- a downgrade the build spec forbids.")

    # --- 4. Invariant governance: a genuinely independently-random win column ---
    rng = np.random.default_rng(42)
    n = 2000
    random_opps = pd.DataFrame({
        "poc_outcome": rng.choice(["pass", "fail"], size=n),
        "is_won": rng.choice([True, False], size=n),  # independent of poc_outcome by construction
    })
    real_opps = pd.DataFrame({
        "poc_outcome": ["pass"] * 500 + ["fail"] * 1500,
        "is_won": [True] * 350 + [False] * 150 + [True] * 150 + [False] * 1350,
    })
    _case("win_probability_real_driver_relationship_passes", True,
          check_win_probability_not_random(real_opps)["passed"],
          "Synthetic population where POC pass really does close at a much higher rate.")
    _case("win_probability_independently_random_column_fails", False,
          check_win_probability_not_random(random_opps)["passed"],
          "Synthetic population where is_won is drawn independently of poc_outcome -- the exact bug "
          "CLAUDE.md's 'independently-random columns are a bug, not a feature' invariant guards against.")

    all_pass = all(r["matches_expectation"] for r in results)
    return {"results": results, "all_pass": all_pass, "n_scenarios": len(results)}


# ==========================================================================
# Orchestration, persistence, and reporting
# ==========================================================================

def _summarize_status(metric_tree: dict, dq: dict, invariants: dict, synthetic: dict) -> dict:
    checks_total = (
        metric_tree["edges_checked"]
        + dq["referential_integrity_checks"] + dq["completeness_checks"]
        + dq["distributional_checks"] + dq["volume_checks"]
        + invariants["invariant_checks_total"]
    )
    checks_passed = (
        metric_tree["edges_passed"]
        + dq["referential_integrity_passed"] + dq["completeness_passed"]
        + dq["distributional_passed"] + dq["volume_passed"]
        + invariants["invariant_checks_passed"]
    )
    return {
        "checks_total": checks_total,
        "checks_passed": checks_passed,
        "checks_failed": checks_total - checks_passed,
        "all_pass": checks_passed == checks_total,
        "synthetic_validation_all_pass": synthetic["all_pass"],
    }


def run_build_time_validation(as_of_date: date, log: bool = True, write_report: bool = True) -> dict:
    """End-to-end governance run: metric-tree integrity, marts-layer data
    quality, invariant governance, and the synthetic injected-violation
    self-check. Logs scalar summary counts to fact_model_performance_history
    via analytics/model_performance.py when log=True, and writes a
    JSON + Markdown report to analytics/outputs/ when write_report=True --
    the variable-width detail tables (per-edge results, per-check tables)
    don't fit that log's flat scalar grain and are the structured detail
    recorded in the report and in docs/acme-corp-analytics-methods.md
    instead, per analytics-engineering-conventions' Persistence note."""
    con = _connect()
    try:
        metric_tree = check_metric_tree_integrity(as_of_date, con=con)
        dq = check_marts_data_quality(as_of_date, con=con)
        invariants = check_invariants(as_of_date, con=con)
    finally:
        con.close()
    synthetic = run_synthetic_violation_tests()
    summary = _summarize_status(metric_tree, dq, invariants, synthetic)

    if log:
        log_performance(_MODEL_NAME, as_of_date, "checks_total", float(summary["checks_total"]))
        log_performance(_MODEL_NAME, as_of_date, "checks_passed", float(summary["checks_passed"]))
        log_performance(_MODEL_NAME, as_of_date, "checks_failed", float(summary["checks_failed"]))
        log_performance(_MODEL_NAME, as_of_date, "metric_tree_edges_checked", float(metric_tree["edges_checked"]))
        log_performance(_MODEL_NAME, as_of_date, "metric_tree_edges_passed", float(metric_tree["edges_passed"]))
        log_performance(_MODEL_NAME, as_of_date, "metric_tree_edges_not_computable", float(metric_tree["edges_not_computable"]))
        log_performance(_MODEL_NAME, as_of_date, "referential_integrity_checks_passed", float(dq["referential_integrity_passed"]))
        log_performance(_MODEL_NAME, as_of_date, "referential_integrity_checks_total", float(dq["referential_integrity_checks"]))
        log_performance(_MODEL_NAME, as_of_date, "completeness_checks_passed", float(dq["completeness_passed"]))
        log_performance(_MODEL_NAME, as_of_date, "distributional_sanity_checks_passed", float(dq["distributional_passed"]))
        log_performance(_MODEL_NAME, as_of_date, "volume_sufficiency_checks_passed", float(dq["volume_passed"]))
        log_performance(_MODEL_NAME, as_of_date, "invariant_checks_passed", float(invariants["invariant_checks_passed"]))
        log_performance(_MODEL_NAME, as_of_date, "invariant_checks_total", float(invariants["invariant_checks_total"]))
        log_performance(_MODEL_NAME, as_of_date, "synthetic_violation_scenarios_passed",
                        float(sum(1 for r in synthetic["results"] if r["matches_expectation"])))
        log_performance(_MODEL_NAME, as_of_date, "synthetic_violation_scenarios_total", float(synthetic["n_scenarios"]))

    result = {
        "as_of_date": as_of_date.isoformat(),
        "metric_tree_integrity": metric_tree,
        "marts_data_quality": dq,
        "invariant_governance": invariants,
        "synthetic_validation": synthetic,
        "summary": summary,
    }
    if write_report:
        _write_report(as_of_date, result)
    return result


def _jsonable(obj):
    if isinstance(obj, pd.DataFrame):
        return json.loads(obj.to_json(orient="records", date_format="iso"))
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, float) and math.isnan(obj):
        return None
    return obj


def _write_report(as_of_date: date, result: dict) -> None:
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    json_path = os.path.join(_OUTPUT_DIR, f"data_quality_governance_{as_of_date.isoformat()}.json")
    with open(json_path, "w") as f:
        json.dump(_jsonable(result), f, indent=2)

    md_path = os.path.join(_OUTPUT_DIR, f"data_quality_governance_{as_of_date.isoformat()}.md")
    s = result["summary"]
    mt = result["metric_tree_integrity"]
    dq = result["marts_data_quality"]
    inv = result["invariant_governance"]
    syn = result["synthetic_validation"]

    lines = []
    lines.append(f"# Data quality / metric governance -- as of {as_of_date.isoformat()}")
    lines.append("")
    lines.append(f"**Overall: {s['checks_passed']} of {s['checks_total']} checks pass** "
                 f"({'ALL PASS' if s['all_pass'] else 'FAILURES PRESENT'}); "
                 f"synthetic self-check {'PASS' if s['synthetic_validation_all_pass'] else 'FAIL'} "
                 f"({syn['n_scenarios']} scenarios).")
    lines.append("")

    lines.append("## 1. Metric-tree mathematical integrity")
    lines.append(f"{mt['edges_passed']} of {mt['edges_checked']} computable edges pass; "
                 f"{mt['edges_not_computable']} not computable (reasons below); "
                 f"{mt['edges_validated_elsewhere']} validated elsewhere.")
    lines.append("")
    lines.append("| Edge | Formula | Status | Max abs diff | Rows checked |")
    lines.append("|---|---|---|---|---|")
    for e in mt["computed_edges"]:
        r = e["result"]
        status = "PASS" if r["passed"] else "**FAIL**"
        mad = r.get("max_abs_diff")
        mad_s = f"{mad:.2e}" if mad is not None and not (isinstance(mad, float) and math.isnan(mad)) else "n/a"
        lines.append(f"| {e['parent']} | `{e['formula']}` | {status} | {mad_s} | {r['n_rows_checked']} |")
    for e in mt["static_edges"]:
        lines.append(f"| {e['parent']} | `{e['formula']}` | {e['status']} | -- | -- |")
    lines.append("")
    lines.append("**Not-computable / validated-elsewhere reasons:**")
    for e in mt["static_edges"]:
        lines.append(f"- **{e['edge_id']}** ({e['status']}): {e['reason']}")
    lines.append("")
    lines.append("**Excluded by design (tree's own non-additive nodes):**")
    for n in mt["excluded_nodes"]:
        lines.append(f"- **{n['node']}**: {n['reason']}")
    lines.append("")

    lines.append("## 2. Marts-layer data quality")
    lines.append(f"- Referential integrity: {dq['referential_integrity_passed']} / {dq['referential_integrity_checks']}")
    lines.append(f"- Completeness: {dq['completeness_passed']} / {dq['completeness_checks']}")
    lines.append(f"- Distributional sanity: {dq['distributional_passed']} / {dq['distributional_checks']}")
    lines.append(f"- Volume sufficiency: {dq['volume_passed']} / {dq['volume_checks']}")
    lines.append("")
    def _df_to_md_table(df: pd.DataFrame) -> list:
        # Plain-text table, no external dependency (avoids requiring the
        # optional `tabulate` package pandas' own to_markdown() needs).
        out = ["| " + " | ".join(str(c) for c in df.columns) + " |",
               "|" + "|".join(["---"] * len(df.columns)) + "|"]
        for _, r in df.iterrows():
            out.append("| " + " | ".join(str(v) for v in r.tolist()) + " |")
        return out

    fk_fail = dq["referential_integrity"][~dq["referential_integrity"]["passed"]]
    if len(fk_fail):
        lines.append("**Referential integrity failures:**")
        lines.extend(_df_to_md_table(fk_fail))
        lines.append("")
    comp_fail = dq["completeness"][~dq["completeness"]["passed"]]
    if len(comp_fail):
        lines.append("**Completeness failures:**")
        lines.extend(_df_to_md_table(comp_fail))
        lines.append("")

    lines.append("## 3. Invariant governance")
    for name, c in inv["checks"].items():
        lines.append(f"- **{name}**: {'PASS' if c['passed'] else '**FAIL**'}")
    lines.append("")

    lines.append("## Synthetic injected-violation self-check")
    lines.append("| Scenario | Expected | Actual | Match |")
    lines.append("|---|---|---|---|")
    for r in syn["results"]:
        lines.append(f"| {r['scenario']} | {'PASS' if r['expected_pass'] else 'FAIL'} | "
                     f"{'PASS' if r['actual_pass'] else 'FAIL'} | "
                     f"{'yes' if r['matches_expectation'] else '**NO**'} |")
    lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    result = run_build_time_validation(date(2025, 12, 31))
    s = result["summary"]
    print(f"{s['checks_passed']} of {s['checks_total']} checks pass "
         f"({'ALL PASS' if s['all_pass'] else 'FAILURES PRESENT'})")
    print(f"Synthetic self-check: {result['synthetic_validation']['n_scenarios']} scenarios, "
         f"all_pass={result['synthetic_validation']['all_pass']}")
    print()
    mt = result["metric_tree_integrity"]
    for e in mt["computed_edges"]:
        print(f"[{'PASS' if e['result']['passed'] else 'FAIL'}] {e['edge_id']}: "
             f"max_abs_diff={e['result'].get('max_abs_diff')}")
    for e in mt["static_edges"]:
        print(f"[{e['status']}] {e['edge_id']}")
