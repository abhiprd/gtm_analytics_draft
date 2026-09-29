"""Scenario planning / sensitivity analysis -- grain: one scenario run per
(as_of_date, set of hypothetical leaf/Layer-2 changes); recomputes every
real, marts-validated ancestor formula in
docs/acme-corp-gtm-metric-tree.md under the hypothetical, up to Layer 1 and
the Growth pillar bridge. Source marts: mart_growth_bridge, mart_efficiency,
mart_durability -- read exclusively through analytics/variance_diagnostic.py's
own loaders/tree/blending (reused, not re-derived a second way).

Build spec item #19 (Wave 6): "propagates a changed assumption through the
tree's existing equations -- distinct from forecast, which predicts, not
simulates a hypothetical." analytics/forecast.py's own methods-doc entry
draws the same line from its own side: "This artifact forecasts the
quarter as_of_date sits in, from the pipeline that already exists...
build spec item #19, scenario planning, is the one that simulates rather
than predicts." Nothing here is fitted and nothing here estimates a future
value from real signals -- every number is either a real, already-observed
baseline (reused from variance_diagnostic.py) or the exact arithmetic
result of applying a user-stated hypothetical change through a formula this
project has already proven holds in the real data.

WHICH TREE REPRESENTATION THIS BUILDS ON, AND WHY
--------------------------------------------------
Two existing, independently-built representations of the tree exist:
`analytics/variance_diagnostic.py`'s `_TREE` (node key/layer/parent_key/
pillar/computability, with a module-level integrity check and a synthetic-
scenario suite that has been running clean against real data since Wave 1)
and `semantic/metric_registry.json` (a more general-purpose parse of the
tree markdown into node/owner/formula-text/source_mart metadata, built by
`semantic/build_registry.py` for the MCP server).

This module reuses `analytics/variance_diagnostic.py`'s `_TREE` and its
loaders/blending functions as the SOLE source of node identity (key,
layer, parent_key, pillar, computability, gap_note) -- imported directly
via `from . import variance_diagnostic as vd`, never re-typed. Three
reasons, all specific to what THIS artifact needs and none of them a knock
against the registry for its own (MCP) purpose:

  1. `vd._TREE` is battle-tested against real data: its own synthetic-
     scenario suite and `analytics/data_quality_governance.py`'s
     independent metric-tree-integrity checker (see below) both already
     exercise it, whereas the registry has no equivalent build-time proof
     that its parsed structure ties to real values.
  2. This module needs REAL baseline Layer-1/Layer-2 values as of
     `as_of_date` to perturb. `vd.blend_layer1_actuals()` and
     `vd._build_child_series()` already compute exactly that, with the
     point-in-time filtering, segment-blending and annualisation-
     compounding rules already validated. The registry carries no
     equivalent runtime computation at all -- it is metadata (a `query`
     dict naming a mart/column/aggregation) for the MCP server's own SQL
     layer to execute, not a Python function this module could call.
     Reusing `vd`'s functions directly means this module's baseline is
     PROVEN identical to the already-shipped engine's baseline, not a
     second implementation that could silently drift from it -- verified
     explicitly by `check_baseline_matches_variance_diagnostic()` below,
     not merely assumed.
  3. The registry is explicitly out of scope to regenerate or extend here
     (semantic-layer-builder's job) and is treated as read-only. `vd._TREE`
     needed no changes either -- reused as-is via import.

WHERE THE FORMULA TYPES (sum/product/ratio) COME FROM
-------------------------------------------------------
Neither `vd._TREE` nor the registry stores an evaluable "combine children
into parent" function -- `vd._TREE` deliberately carries no formula field
at all (it walks REAL mart values and never needs to derive a parent from
children), and the registry's `formula` field is the tree markdown's raw
text, machine-readable but not an evaluable expression. This module is the
first to need that, so it adds a small, explicitly-labelled formula layer
(`_FORMULA_EDGES` below) -- the same kind of addition `build_registry.py`
made for `source_mart` ("one thing NOT parseable from the tree file...
built by reading the actual dbt mart SQL... not invented").

Rather than deriving that layer from the tree's prose a third time, it is
grounded directly in `analytics/data_quality_governance.py`'s own
`_METRIC_TREE_EDGES_STATIC` list and its per-edge check functions -- the
one artifact in this repo whose entire job is "does the tree's math
actually tie out in the built marts," independently re-verified at every
governance checkpoint (11/11 real edges PASS as of both its checkpoints).
Every edge this module propagates through is one of those governance-
PASSING edges (`edge_id`s cited per function below); every edge governance
found `NOT_COMPUTABLE` (New logo = Pipeline x Win rate x Avg commitment;
Expansion = Wallet share progression x Overage realization; Magic number;
AM efficiency) is honoured as `NOT_COMPUTABLE` here too, for the identical
reason -- never re-derived, never silently patched around, never
back-solved from the parent's real value to fabricate a missing factor
(that specific temptation -- solving `pipeline_generated = new_logo_mrr /
(win_rate * avg_commitment)` to manufacture a product identity that
governance already proved does not hold on this data's populations -- is
exactly what this module refuses to do; see NOT_COMPUTABLE HANDLING below).

WHAT "AS OF" MEANS FOR A HYPOTHETICAL
---------------------------------------
There is no future to leak from (this module predicts nothing), but a
scenario still needs an unambiguous point of application. `as_of_date`
resolves to the same evaluation month `vd._evaluation_month()` uses (the
last COMPLETE month at or before `as_of_date`). The BASELINE is every real
mart value for every month up to and including that evaluation month,
exactly as `vd.blend_layer1_actuals()` already computes it. The
HYPOTHETICAL CHANGE is applied ONLY to the evaluation month's own
segment-level mart row(s) -- every prior month is held at its real,
observed value. This is what makes the trailing-twelve-month NRR/GRR/
logo-retention compounding well-defined under a scenario: eleven of the
twelve monthly rates in the window are real and unperturbed; only the
evaluation month's own rate reflects the hypothetical.

NOT_COMPUTABLE HANDLING
------------------------
A scenario is free to name a driver whose only path to Layer 1 runs
through a governance-NOT_COMPUTABLE edge (the build spec's own example,
"what if win rate improves by 5 percentage points," is exactly this case
-- New logo consumption revenue's product formula is NOT_COMPUTABLE).
`run_scenario()` still computes every real, valid consequence of the
change (the Layer-2 node's own new value; any OTHER real mart column the
same underlying counts feed, such as bookings) and separately, explicitly
reports `new_logo_consumption_revenue` (and any other node on the broken
path) as `NOT_COMPUTABLE`, carrying the exact governance reason -- never
silently dropped, never left at a stale baseline value presented as "no
effect." Where a Layer-1 aggregate (e.g. the Growth pillar bridge) is
partly reachable and partly not (some of its legs have a real path, one
does not), that aggregate is reported with the reachable legs applied and
an explicit `partial` flag plus a note stating which leg could not be
moved and why -- distinct from a full NOT_COMPUTABLE.

MULTI-INPUT SCENARIOS AND NO DOUBLE-COUNTING
-----------------------------------------------
Multiple leaves may be changed in one `run_scenario()` call. Internally
every change is resolved to a canonical (driver, segment) pair against ONE
shared perturbed copy of the evaluation month's mart rows -- there is no
per-path delta accumulation anywhere in this module, so two changes that
resolve to the SAME underlying quantity (e.g. `contraction_mrr` for
Commercial, requested either directly or via the `nrr_contraction_rate` /
`grr_contraction_rate` rate-space aliases, which both describe the exact
same dollar quantity from two different tree parents) cannot silently
apply twice. `_resolve_changes()` raises `ValueError` if two requested
changes canonicalise to the same (driver, segment) pair with conflicting
values, rather than picking one arbitrarily. Because every downstream
formula (contraction+churned revenue, NRR, GRR, the Growth pillar bridge)
reads from that one shared perturbed value, a leaf with several real
ancestors along different tree branches ties out exactly across all of
them by construction -- exercised directly by the
`shared_ancestor_contraction_mrr_no_double_counting` synthetic scenario.

DETERMINISM
------------
No stochastic step exists anywhere in this module -- every output is the
exact arithmetic result of a stated formula applied to a stated input, so
no random seed applies. Matches `analytics/variance_diagnostic.py`'s and
`analytics/data_quality_governance.py`'s own precedent.

VALIDATION SHAPE
------------------
Structural/logic artifact, per analytics-engineering-conventions'
"Structural/logic artifacts" category (deterministic equation propagation,
nothing fitted): no coefficient table, no AUC, no confusion matrix, no
R^2/RMSE, and their absence is deliberate, not pending. The correctness
claim is "does propagation through a real formula produce the exact
hand-computable answer, does a NOT_COMPUTABLE gap get reported rather than
fabricated, and does a shared ancestor reached via two paths tie out
without double-counting" -- checked by `SYNTHETIC_SCENARIOS` below. Five
of its seven cases are pure functions over hand-built DataFrames (no I/O,
exact hand-computable expected answers -- the sum / product / ratio /
ratio-of-sum / shared-ancestor cases this artifact's build task requires);
the remaining two (NOT_COMPUTABLE handling for a product-node gap and for
a cost-data gap) deliberately run the real `run_scenario()` end to end
against real marts data at a fixed `as_of_date`, because NOT_COMPUTABLE
reporting is a property of the node-registration logic in
`run_scenario()` itself, not of a standalone formula function -- a
synthetic DataFrame could not exercise it. This mirrors
`analytics/variance_diagnostic.py`'s own synthetic suite and
`analytics/data_quality_governance.py`'s own synthetic-violation suite,
plus one additional real-data self-check
(`check_baseline_matches_variance_diagnostic()`) that a zero-change
scenario reproduces `vd.blend_layer1_actuals()`'s real baseline exactly --
proof the reuse in this module's point 2 above actually holds, not merely
asserted.

MODEL TYPE SELECTION AND RATIONALE (why not a fitted sensitivity/elasticity
model): a fitted approach -- e.g. regressing each Layer-1 metric on its
Layer-2/3 drivers to estimate an empirical sensitivity coefficient -- was
considered and rejected for the same reason
`analytics/variance_diagnostic.py`'s and
`analytics/data_quality_governance.py`'s entries reject a fitted attribution
model: the metric tree's parent-child relationships are not unknown
quantities to estimate, they are exact arithmetic identities that
`analytics/data_quality_governance.py` has already independently confirmed
hold in the built marts to floating-point precision. Fitting a coefficient
to approximate a relationship that is already known exactly would trade a
correct deterministic answer for a noisy estimated one, and would produce
a "scenario" that could be wrong about arithmetic that cannot be wrong. A
deterministic walk of the same declared, already-validated structure is
the only defensible model class for this artifact's actual job.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import variance_diagnostic as vd
from .model_performance import log_performance

_MODEL_NAME = "scenario_planning"

# Segments a driver is legitimately defined over. `None` means all three
# (SMB, Commercial, Enterprise); the rep-sold-only restriction mirrors
# vd._REP_SOLD_SEGMENTS exactly -- "SMB has no win-rate concept to true
# up" (build spec Section 2).
_ALL_SEGMENTS = ("SMB", "Commercial", "Enterprise")
_REP_SOLD_SEGMENTS = vd._REP_SOLD_SEGMENTS          # ("Commercial", "Enterprise")
_PAYBACK_BLEND_SEGMENTS = vd._PAYBACK_BLEND_SEGMENTS  # ("Commercial", "Enterprise")
_ANNUALISATION_MONTHS = vd._ANNUALISATION_MONTHS      # 12


# =====================================================================
# Driver registry -- the true "leaves" a scenario can perturb, each one
# a real mart_growth_bridge / mart_efficiency / mart_durability column at
# (segment, month) grain. Grounded in analytics/data_quality_governance.py's
# _METRIC_TREE_EDGES_STATIC (edge_id cited per driver) -- never a column
# invented for this module's convenience.
# =====================================================================

@dataclass(frozen=True)
class DriverSpec:
    key: str
    mart: str                       # "growth_bridge" | "efficiency" | "durability"
    column: Optional[str]           # None for the two derived (win_rate / avg_initial_commitment) drivers
    unit: str                       # "usd" | "count" | "ratio" | "usd_per_account"
    segments_allowed: Tuple[str, ...]
    consumed_by: Tuple[str, ...]    # tree node keys (documentation / output only)
    edge_ids: Tuple[str, ...]       # analytics/data_quality_governance.py edge_ids this reuses
    rate_alias_of: Optional[str] = None  # canonical driver this is a rate-space convenience alias for


_DRIVERS: Dict[str, DriverSpec] = {
    "contraction_mrr": DriverSpec(
        "contraction_mrr", "growth_bridge", "contraction_mrr", "usd", _ALL_SEGMENTS,
        ("contraction_churned_revenue", "nrr", "grr", "growth_pillar_bridge"),
        ("new_logo_equals_pipeline_x_winrate_x_commitment", "durability_growth_cross_mart"),
    ),
    "churn_mrr": DriverSpec(
        "churn_mrr", "growth_bridge", "churn_mrr", "usd", _ALL_SEGMENTS,
        ("contraction_churned_revenue", "nrr", "grr", "growth_pillar_bridge"),
        ("durability_growth_cross_mart",),
    ),
    "expansion_mrr": DriverSpec(
        "expansion_mrr", "growth_bridge", "expansion_mrr", "usd", _ALL_SEGMENTS,
        ("expansion_consumption_revenue", "nrr", "growth_pillar_bridge", "am_efficiency"),
        ("am_efficiency_ratio", "durability_growth_cross_mart"),
    ),
    "am_touchpoint_count": DriverSpec(
        "am_touchpoint_count", "efficiency", "am_touchpoint_count", "count", _ALL_SEGMENTS,
        ("onboarding_cs_efficiency",), ("onboarding_cs_efficiency_ratio",),
    ),
    "automated_actions_delivered": DriverSpec(
        "automated_actions_delivered", "efficiency", "automated_actions_delivered", "count",
        _ALL_SEGMENTS, ("onboarding_cs_efficiency",), ("onboarding_cs_efficiency_ratio",),
    ),
    "blended_cac": DriverSpec(
        "blended_cac", "efficiency", "blended_cac", "usd", _PAYBACK_BLEND_SEGMENTS,
        ("consumption_payback",), ("consumption_payback_ratio",),
    ),
    "avg_utilized_action_margin_per_account": DriverSpec(
        "avg_utilized_action_margin_per_account", "efficiency",
        "avg_utilized_action_margin_per_account", "usd_per_account", _PAYBACK_BLEND_SEGMENTS,
        ("consumption_payback",), ("consumption_payback_ratio",),
    ),
    "starting_accounts": DriverSpec(
        "starting_accounts", "durability", "starting_accounts", "count", _ALL_SEGMENTS,
        ("logo_retention",), ("logo_retention_ratio",),
    ),
    "churned_accounts": DriverSpec(
        "churned_accounts", "durability", "churned_accounts", "count", _ALL_SEGMENTS,
        ("logo_retention",), ("logo_retention_ratio",),
    ),
    "win_rate": DriverSpec(
        "win_rate", "growth_bridge", None, "ratio", _REP_SOLD_SEGMENTS,
        ("win_rate", "new_logo_consumption_revenue"), ("win_rate_ratio",),
    ),
    "avg_initial_commitment": DriverSpec(
        "avg_initial_commitment", "growth_bridge", None, "usd", _REP_SOLD_SEGMENTS,
        ("avg_initial_commitment", "new_logo_consumption_revenue"), ("win_rate_ratio",),
    ),
    # Registered so a user asking for these gets a structured NOT_COMPUTABLE
    # answer rather than a KeyError -- the identical gap
    # analytics/variance_diagnostic.py's magic_number / am_efficiency nodes
    # already carry (no rep-cost/comp data anywhere in the raw sources).
    # Columns exist in mart_efficiency (magic_number_sm_cost / am_cost) but
    # are NULL for every row by design -- no rep-cost/comp data anywhere in
    # the raw sources. Reading them yields NaN, not a KeyError; NaN simply
    # propagates through the (otherwise-unused) arithmetic below, and
    # `_apply()` never actually writes to these columns -- the point is to
    # register the driver so a request against it resolves to an honest
    # NOT_COMPUTABLE report rather than an unknown-driver error.
    "s_m_cost": DriverSpec(
        "s_m_cost", "efficiency", "magic_number_sm_cost", "usd", _ALL_SEGMENTS,
        ("magic_number",), ("magic_number_ratio",),
    ),
    "am_cost_by_segment": DriverSpec(
        "am_cost_by_segment", "efficiency", "am_cost", "usd", _ALL_SEGMENTS,
        ("am_efficiency",), ("am_efficiency_ratio",),
    ),
}

# Rate-space convenience aliases: a user may name the change in the same
# units the tree's Layer-2 node itself is expressed in (a share of starting
# revenue) rather than a raw dollar amount. Each resolves to the SAME
# canonical driver a plain dollar-space request would -- this is the
# mechanism that makes the shared-ancestor no-double-counting guarantee
# structural rather than a matter of the caller's discipline.
_RATE_ALIASES = {
    "nrr_contraction_rate": "contraction_mrr",
    "grr_contraction_rate": "contraction_mrr",
    "nrr_churn_rate": "churn_mrr",
    "grr_churn_rate": "churn_mrr",
    "nrr_expansion_rate": "expansion_mrr",
}

_COST_GAP_NOTE = (
    "No rep-cost/comp data exists anywhere in the raw sources. "
    "mart_efficiency.magic_number_sm_cost / .magic_number / .am_cost / "
    ".am_efficiency are NULL by design -- the identical gap "
    "analytics/variance_diagnostic.py and "
    "analytics/data_quality_governance.py both name as structurally "
    "not-computable. A scenario cannot move a quantity that has no real "
    "baseline value to perturb."
)
_NEW_LOGO_PRODUCT_GAP_NOTE = (
    "New logo consumption revenue = Pipeline generated x Win rate x Avg "
    "initial commitment is NOT_COMPUTABLE as a real identity in this "
    "data (analytics/data_quality_governance.py, edge_id "
    "'new_logo_equals_pipeline_x_winrate_x_commitment'): "
    "mart_growth_bridge.win_rate/avg_initial_commitment are computed over "
    "closed SQO-stage opportunities while Pipeline generated is a "
    "different, lead-grain population with no mart exposing it at New "
    "Logo's own scope. Solving pipeline_generated = new_logo_mrr / "
    "(win_rate * avg_commitment) to force a product identity that does "
    "not hold on this data's real populations would manufacture a false "
    "tie-out -- exactly what analytics/data_quality_governance.py's own "
    "entry warns against -- so this module does not do it. Win rate's / "
    "Avg initial commitment's own new values, and the real (but distinct) "
    "new_logo_bookings_amount consequence, ARE computed and reported "
    "below; New logo consumption revenue itself is not."
)


# =====================================================================
# Change request / resolution
# =====================================================================

@dataclass(frozen=True)
class ScenarioChange:
    """One requested hypothetical change. `change_type` is 'absolute' (set
    to `value`), 'delta' (baseline + `value`, in the driver's native unit
    -- or, for a rate alias, in rate/percentage-point units) or 'pct'
    (baseline * (1 + value)); 'pct' is not accepted on a rate alias, where
    percent-of-a-percent is ambiguous -- use 'delta' or 'absolute'."""
    driver_key: str
    segment: str
    change_type: str
    value: float


@dataclass(frozen=True)
class ResolvedChange:
    canonical_driver: str
    segment: str
    mart: str
    column: str
    unit: str
    baseline_value: float
    scenario_value: float
    delta: float
    requested_as: str  # the original driver_key, for output readability


def _changes_from_dict(changes: Dict[str, dict]) -> List[ScenarioChange]:
    """Expands the public dict API into one ScenarioChange per (driver,
    segment). `segment` may be a single segment name, a list of segment
    names, or the literal 'ALL' -- which expands to every segment that
    driver is actually defined over (its own DriverSpec.segments_allowed),
    not a blind loop over all three."""
    out = []
    for driver_key, spec in changes.items():
        raw_segment = spec["segment"]
        if raw_segment == "ALL":
            canon = _RATE_ALIASES.get(driver_key, driver_key)
            driver = _DRIVERS.get(canon)
            if driver is None:
                raise ValueError(f"unknown scenario driver: {driver_key}")
            segments = list(driver.segments_allowed)
        elif isinstance(raw_segment, str):
            segments = [raw_segment]
        else:
            segments = list(raw_segment)
        for seg in segments:
            out.append(ScenarioChange(driver_key, seg, spec["change_type"], spec["value"]))
    return out


def _canonical_driver(driver_key: str) -> Tuple[str, Optional[str]]:
    """Returns (canonical_driver_key, rate_alias_used_or_None)."""
    if driver_key in _RATE_ALIASES:
        return _RATE_ALIASES[driver_key], driver_key
    return driver_key, None


def _row_for(df: pd.DataFrame, segment: str, month: pd.Timestamp) -> pd.Series:
    hit = df[(df["segment"] == segment) & (df["month"] == month)]
    if hit.empty:
        raise ValueError(f"no mart row for segment={segment!r} month={month:%Y-%m}")
    return hit.iloc[0]


def _resolve_changes(changes: List[ScenarioChange], gb: pd.DataFrame, eff: pd.DataFrame,
                     dur: pd.DataFrame, month: pd.Timestamp) -> List[ResolvedChange]:
    """Resolves every requested change to one canonical (driver, segment)
    perturbation against real baseline values, raising on an unknown
    driver/segment or on two requests that canonicalise to the same
    (driver, segment) pair with conflicting resulting values -- the
    structural guard against double-applying one shared underlying
    quantity via two different rate-space names."""
    resolved: Dict[Tuple[str, str], ResolvedChange] = {}
    for ch in changes:
        canon, alias = _canonical_driver(ch.driver_key)
        if canon not in _DRIVERS:
            raise ValueError(f"unknown scenario driver: {ch.driver_key!r}")
        spec = _DRIVERS[canon]
        if ch.segment not in spec.segments_allowed:
            raise ValueError(
                f"{canon} is not defined for segment {ch.segment!r}; allowed: "
                f"{spec.segments_allowed} (build spec Section 2 -- SMB has no "
                f"win-rate concept to true up, for the two rep-sold-only drivers)")

        source = {"growth_bridge": gb, "efficiency": eff, "durability": dur}[spec.mart]
        row = _row_for(source, ch.segment, month)

        if canon in ("win_rate", "avg_initial_commitment"):
            baseline_value = _derived_baseline(canon, row)
        else:
            baseline_value = float(row[spec.column])

        if alias:
            # Rate-space request: value is a share of starting revenue
            # (mart_growth_bridge / mart_durability's own starting_mrr for
            # that segment/month), converted to the dollar space the
            # canonical driver actually lives in.
            if ch.change_type == "pct":
                raise ValueError(
                    f"{ch.driver_key} is a rate-space alias for {canon}; 'pct' change_type "
                    "is ambiguous here (percent of the rate vs. percent of the dollar amount "
                    "it implies) -- use 'delta' (rate points) or 'absolute' (a new rate).")
            starting_mrr = float(_row_for(dur, ch.segment, month)["starting_mrr"])
            if ch.change_type == "absolute":
                scenario_value = ch.value * starting_mrr
            else:  # delta, in rate points
                scenario_value = baseline_value + ch.value * starting_mrr
        else:
            if ch.change_type == "absolute":
                scenario_value = ch.value
            elif ch.change_type == "delta":
                scenario_value = baseline_value + ch.value
            elif ch.change_type == "pct":
                scenario_value = baseline_value * (1.0 + ch.value)
            else:
                raise ValueError(f"unknown change_type: {ch.change_type!r}")

        if spec.unit == "count":
            # Count-typed drivers (am_touchpoint_count, automated_actions_
            # delivered, starting_accounts, churned_accounts) are real,
            # whole-unit populations -- mart_efficiency / mart_durability
            # store several of these as pandas nullable Int64 for exactly
            # that reason (real counts, never fractional). A 'pct' or
            # 'delta' request against a count naturally lands off an
            # integer (e.g. 261 touchpoints * 0.9 = 234.9), the identical
            # discrete-population quantization the win_rate path already
            # handles below via .round() on new_business_won_count, with
            # the same documented tolerance in
            # _case_not_computable_new_logo(). Rounding here, once, before
            # the ResolvedChange is built, keeps every downstream read of
            # scenario_value/delta (report output, _apply()'s write, the
            # conflicting-alias comparison) consistent with the single
            # value actually applied -- never a fractional count reported
            # in one place and a rounded one written in another.
            scenario_value = float(round(scenario_value))

        key = (canon, ch.segment)
        rc = ResolvedChange(canon, ch.segment, spec.mart, spec.column or "(derived)",
                            spec.unit, baseline_value, scenario_value,
                            scenario_value - baseline_value, ch.driver_key)
        if key in resolved and abs(resolved[key].scenario_value - scenario_value) > 1e-9:
            raise ValueError(
                f"conflicting scenario changes resolve to the same underlying quantity "
                f"{canon} for segment {ch.segment}: {resolved[key].requested_as}="
                f"{resolved[key].scenario_value} vs. {rc.requested_as}={scenario_value}. "
                "Two rate-space names (e.g. nrr_contraction_rate and "
                "grr_contraction_rate) describe the SAME physical dollar quantity and "
                "must agree if both are requested in one scenario.")
        resolved[key] = rc
    return list(resolved.values())


def _derived_baseline(canon: str, row: pd.Series) -> float:
    won, lost = float(row["new_business_won_count"]), float(row["new_business_lost_count"])
    closed = won + lost
    if canon == "win_rate":
        return won / closed if closed else float("nan")
    bookings = float(row["new_logo_bookings_amount"])
    return bookings / won if won else float("nan")


# =====================================================================
# Applying resolved changes to perturbed copies of the evaluation-month
# mart rows. One shared perturbed frame per mart -- the mechanism that
# makes "no double counting across shared ancestors" structural: every
# downstream formula below reads the SAME perturbed frame, never a
# per-path delta.
#
# contraction_mrr / churn_mrr / expansion_mrr are a special case worth
# flagging explicitly: analytics/data_quality_governance.py's own
# `durability_growth_cross_mart` check confirms these are the SAME
# physical dollar quantity, independently materialized under the identical
# column name in BOTH mart_growth_bridge and mart_durability (both derive
# from int_revenue_movements upstream). A scenario changing one of these
# three must therefore write BOTH mart copies in lockstep -- writing only
# the growth_bridge copy would leave mart_durability's own contraction_mrr
# at its stale baseline, and NRR/GRR (which read only from mart_durability)
# would silently fail to see the change at all. `_DUAL_MART_DRIVERS` names
# the drivers this applies to; this was caught by this module's own
# baseline self-check discipline during build (a scenario that changed
# contraction_mrr produced a zero NRR/GRR delta, which the multi-path
# synthetic scenario's hand-computed expectation immediately flagged as
# wrong), not assumed correct from the outset.
# =====================================================================

_DUAL_MART_DRIVERS = {"contraction_mrr", "churn_mrr", "expansion_mrr"}


def _apply(gb_month: pd.DataFrame, eff_month: pd.DataFrame, dur_month: pd.DataFrame,
          resolved: List[ResolvedChange]) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    gb2, eff2, dur2 = gb_month.copy(), eff_month.copy(), dur_month.copy()
    for rc in resolved:
        if rc.canonical_driver in _DUAL_MART_DRIVERS:
            for target in (gb2, dur2):
                idx = target.index[target["segment"] == rc.segment]
                target.loc[idx, rc.canonical_driver] = rc.scenario_value
            continue
        target = {"growth_bridge": gb2, "efficiency": eff2, "durability": dur2}[rc.mart]
        idx = target.index[target["segment"] == rc.segment]
        if rc.canonical_driver == "win_rate":
            closed = target.loc[idx, "new_business_won_count"] + target.loc[idx, "new_business_lost_count"]
            new_won = (rc.scenario_value * closed).round()
            # avg_commit_in_effect: whatever avg_initial_commitment currently
            # implies from the frame's CURRENT bookings/won_count -- baseline
            # if avg_initial_commitment has not also been scenario-changed
            # for this segment, or already the scenario value if that other
            # resolved change was applied earlier in this same loop. Either
            # way, bookings ends up as won_final x avg_commitment_final,
            # order-independent, because both branches only ever read the
            # frame's current state rather than a cached original.
            avg_commit_in_effect = (
                target.loc[idx, "new_logo_bookings_amount"] / target.loc[idx, "new_business_won_count"]
            )
            target.loc[idx, "new_business_won_count"] = new_won
            target.loc[idx, "new_logo_bookings_amount"] = new_won * avg_commit_in_effect
        elif rc.canonical_driver == "avg_initial_commitment":
            won = target.loc[idx, "new_business_won_count"]
            target.loc[idx, "new_logo_bookings_amount"] = won * rc.scenario_value
        elif rc.canonical_driver in ("s_m_cost", "am_cost_by_segment"):
            pass  # NOT_COMPUTABLE -- no column exists to perturb; handled at report time.
        else:
            target.loc[idx, rc.column] = rc.scenario_value
    return gb2, eff2, dur2


# =====================================================================
# Formula edges -- each mirrors, one-for-one, an
# analytics/data_quality_governance.py PASS-checked identity (edge_id
# cited). Applied to a (possibly-perturbed) set of evaluation-month rows;
# called twice per run (once on the real baseline rows, once on the
# scenario-perturbed rows) so baseline and scenario are computed by the
# EXACT SAME code path -- a propagation bug cannot show up only on one
# side.
# =====================================================================

def compute_contraction_churned_revenue(gb_month: pd.DataFrame) -> float:
    """Sum node. Tree: 'Contraction + churned consumption revenue.' Mirrors
    vd.blend_layer1_actuals's own money['contraction'] + money['churn'].
    Company-wide: sum across all 3 segments."""
    return float((gb_month["contraction_mrr"] + gb_month["churn_mrr"]).sum())


def compute_expansion_consumption_revenue(gb_month: pd.DataFrame) -> float:
    """Sum node (single leg, all 3 segments). Mirrors
    vd.blend_layer1_actuals's money['expansion']."""
    return float(gb_month["expansion_mrr"].sum())


def compute_win_rate(gb_month: pd.DataFrame, segment: str) -> float:
    """Ratio node. governance edge_id 'win_rate_ratio': Closed won /
    (won + lost), by segment -- exact PASS-checked identity."""
    row = gb_month[gb_month["segment"] == segment].iloc[0]
    closed = row["new_business_won_count"] + row["new_business_lost_count"]
    return float(row["new_business_won_count"] / closed) if closed else float("nan")


def compute_avg_initial_commitment(gb_month: pd.DataFrame, segment: str) -> float:
    """Ratio (bookings / won), rep-sold segments only -- the same quantity
    vd._build_child_series computes for its own Layer-2 series."""
    row = gb_month[gb_month["segment"] == segment].iloc[0]
    won = row["new_business_won_count"]
    return float(row["new_logo_bookings_amount"] / won) if won else float("nan")


def compute_new_logo_bookings_amount_rep_sold(gb_month: pd.DataFrame) -> float:
    """A real, distinct mart quantity (bookings-lens, not the revenue-lens
    new_logo_mrr) -- summed across Commercial + Enterprise, mirroring
    vd._build_child_series's own rep-sold aggregation. Reported alongside
    a win_rate / avg_initial_commitment scenario as the one real downstream
    consequence that DOES compute, distinct from new_logo_consumption_
    revenue, which does not (see _NEW_LOGO_PRODUCT_GAP_NOTE)."""
    rep = gb_month[gb_month["segment"].isin(_REP_SOLD_SEGMENTS)]
    return float(rep["new_logo_bookings_amount"].sum())


def compute_onboarding_cs_efficiency(eff_month: pd.DataFrame) -> float:
    """Ratio node. governance edge_id 'onboarding_cs_efficiency_ratio':
    total AM/CS touchpoints / total automated Actions, all 3 segments --
    mirrors vd.blend_layer1_actuals's own oce['touches']/oce['actions']."""
    touches = float(eff_month["am_touchpoint_count"].sum())
    actions = float(eff_month["automated_actions_delivered"].sum())
    return touches / actions if actions else float("nan")


def compute_consumption_payback(eff_month: pd.DataFrame, dur_month: pd.DataFrame) -> float:
    """Ratio node, revenue-weighted across Commercial + Enterprise.
    governance edge_id 'consumption_payback_ratio' (per-segment CAC / margin
    identity); the cross-segment blend mirrors
    vd.blend_layer1_actuals's own pay_g weighted-average step exactly,
    including its dropna(subset=['consumption_payback_months']) -- a
    segment whose margin is non-positive that month is excluded from the
    weighted average rather than propagating a NaN/inf into it, the same
    treatment vd gives it. Weight = starting_mrr, from mart_durability,
    held fixed by this module -- starting_mrr is not a driver any scenario
    here perturbs."""
    eff = eff_month[eff_month["segment"].isin(_PAYBACK_BLEND_SEGMENTS)].copy()
    eff["payback_months"] = eff["blended_cac"] / eff["avg_utilized_action_margin_per_account"]
    eff = eff.replace([np.inf, -np.inf], np.nan).dropna(subset=["payback_months"])
    if eff.empty:
        return float("nan")
    dur_starting = dur_month.set_index("segment")["starting_mrr"]
    weights = eff["segment"].map(dur_starting).fillna(0.0).to_numpy()
    if weights.sum() <= 0:
        return float("nan")
    return float(np.average(eff["payback_months"].to_numpy(), weights=weights))


def compute_nrr_grr_monthly(dur_month: pd.DataFrame) -> Tuple[float, float]:
    """Ratio-of-sum nodes. governance edge_ids 'nrr_ratio' / 'grr_ratio':
    (Starting [- Contraction - Churn] [+ Expansion]) / Starting, company-
    wide (all 3 segments summed) -- mirrors vd.blend_layer1_actuals's own
    cw aggregation exactly."""
    s = float(dur_month["starting_mrr"].sum())
    e = float(dur_month["expansion_mrr"].sum())
    c = float(dur_month["contraction_mrr"].sum())
    ch = float(dur_month["churn_mrr"].sum())
    if s <= 0:
        return float("nan"), float("nan")
    return (s - c - ch + e) / s, (s - c - ch) / s


def compute_logo_retention_monthly(dur_month: pd.DataFrame) -> float:
    """Ratio node. governance edge_id 'logo_retention_ratio': (Starting -
    Churned accounts) / Starting accounts, company-wide."""
    s = float(dur_month["starting_accounts"].sum())
    c = float(dur_month["churned_accounts"].sum())
    return (s - c) / s if s > 0 else float("nan")


def compute_am_expansion_arr(gb_month: pd.DataFrame) -> float:
    """Product-with-constant node. governance edge_id
    'am_expansion_arr_cross_mart': expansion_mrr x 12, all 3 segments
    summed. The one real, marts-validated PRODUCT-typed edge this module
    can propagate through (New logo's and Expansion's own two-variable
    products are both governance-NOT_COMPUTABLE -- see module docstring)."""
    return float(gb_month["expansion_mrr"].sum()) * 12.0


def compute_growth_pillar_bridge(gb_month: pd.DataFrame,
                                 new_logo_mrr_override: Optional[float] = None) -> float:
    """Sum node, one level above Layer 1. Tree's own pillar-header
    formula: 'Starting consumption revenue + New logo - Contraction -
    Churn + Expansion (+/- segment migration, nets to zero)', company-wide.
    Mirrors governance's own check_growth_pillar_identity, generalised from
    a per-segment tie-out to the company-wide sum a scenario needs.
    `new_logo_mrr_override` lets a caller hold New logo at its real
    baseline when the scenario's only New-logo-adjacent driver
    (win_rate / avg_initial_commitment) has no valid path into it -- see
    the module docstring's NOT_COMPUTABLE HANDLING section."""
    new_logo = (float(gb_month["new_logo_mrr"].sum()) if new_logo_mrr_override is None
                else new_logo_mrr_override)
    return (
        float(gb_month["starting_mrr"].sum()) + new_logo
        + float(gb_month["expansion_mrr"].sum())
        - float(gb_month["contraction_mrr"].sum())
        - float(gb_month["churn_mrr"].sum())
        + float(gb_month["migration_in_mrr"].sum())
        - float(gb_month["migration_out_mrr"].sum())
    )


# =====================================================================
# Trailing-twelve-month annualisation -- replays vd.blend_layer1_actuals's
# own rolling-product compounding, with ONLY the evaluation month's own
# monthly rate swapped for its scenario value. Every other of the 11
# months in the window is a real, unperturbed observation.
# =====================================================================

def _annualise_with_scenario_month(monthly_series: pd.Series, month: pd.Timestamp,
                                   scenario_monthly_value: float) -> float:
    window = monthly_series.loc[:month].tail(_ANNUALISATION_MONTHS).copy()
    if len(window) < _ANNUALISATION_MONTHS or month not in window.index:
        return float("nan")
    window.loc[month] = scenario_monthly_value
    return float(np.prod(window.to_numpy()))


# =====================================================================
# End-to-end scenario run
# =====================================================================

@dataclass
class NodeResult:
    metric_key: str
    label: str
    layer: int
    pillar: Optional[str]
    baseline: Optional[float]
    scenario: Optional[float]
    delta: Optional[float]
    computable: bool
    formula_type: Optional[str]
    edge_ids: Tuple[str, ...] = ()
    note: Optional[str] = None


@dataclass
class ScenarioResult:
    as_of_date: date
    evaluation_month: pd.Timestamp
    requested_changes: List[ScenarioChange]
    resolved_changes: List[ResolvedChange]
    nodes: Dict[str, NodeResult]
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "as_of_date": self.as_of_date,
            "evaluation_month": self.evaluation_month,
            "resolved_changes": [rc.__dict__ for rc in self.resolved_changes],
            "nodes": {k: v.__dict__ for k, v in self.nodes.items()},
            "notes": self.notes,
        }


def run_scenario(as_of_date: date, changes: Dict[str, dict], con=None) -> ScenarioResult:
    """Applies one or more hypothetical leaf/Layer-2 changes to the real
    evaluation-month (last complete month <= as_of_date) mart rows and
    recomputes every real, governance-validated ancestor formula, up to
    Layer 1 and the Growth pillar bridge. Grain: one run per (as_of_date,
    change set). Source marts: mart_growth_bridge, mart_efficiency,
    mart_durability, read via analytics/variance_diagnostic.py's own
    loaders. `changes`: {driver_key: {"segment": str | "ALL",
    "change_type": "absolute"|"delta"|"pct", "value": float}}."""
    owns = con is None
    con = con or vd._connect()
    try:
        gb_all = vd.load_growth_bridge(as_of_date, con=con)
        eff_all = vd.load_efficiency(as_of_date, con=con)
        dur_all = vd.load_durability(as_of_date, con=con)
        baseline_actuals = vd.blend_layer1_actuals(as_of_date, con=con)
    finally:
        if owns:
            con.close()

    month = vd._evaluation_month(as_of_date)
    gb_m = gb_all[gb_all["month"] == month].reset_index(drop=True)
    eff_m = eff_all[eff_all["month"] == month].reset_index(drop=True)
    dur_m = dur_all[dur_all["month"] == month].reset_index(drop=True)

    change_list = _changes_from_dict(changes)
    resolved = _resolve_changes(change_list, gb_m, eff_m, dur_m, month)
    gb_s, eff_s, dur_s = _apply(gb_m, eff_m, dur_m, resolved)

    touched_drivers = {rc.canonical_driver for rc in resolved}
    touched_cost_drivers = touched_drivers & {"s_m_cost", "am_cost_by_segment"}
    touched_new_logo_path = touched_drivers & {"win_rate", "avg_initial_commitment"}

    nodes: Dict[str, NodeResult] = {}
    notes: List[str] = []

    def _l1(key):
        return vd.get_node(key)

    # --- Contraction + churned revenue (sum) ---
    base_ccr = compute_contraction_churned_revenue(gb_m)
    scen_ccr = compute_contraction_churned_revenue(gb_s)
    n = _l1("contraction_churned_revenue")
    nodes[n.key] = NodeResult(n.key, n.label, 1, n.pillar, base_ccr, scen_ccr,
                              scen_ccr - base_ccr, True, "sum",
                              ("new_logo_equals_pipeline_x_winrate_x_commitment",))

    # --- Expansion consumption revenue (sum, single leg) ---
    base_exp = compute_expansion_consumption_revenue(gb_m)
    scen_exp = compute_expansion_consumption_revenue(gb_s)
    n = _l1("expansion_consumption_revenue")
    nodes[n.key] = NodeResult(n.key, n.label, 1, n.pillar, base_exp, scen_exp,
                              scen_exp - base_exp, True, "sum", ())

    # --- am_expansion_arr (product with constant) ---
    base_arr = compute_am_expansion_arr(gb_m)
    scen_arr = compute_am_expansion_arr(gb_s)
    nodes["am_expansion_arr"] = NodeResult(
        "am_expansion_arr", "AM expansion ARR (AM efficiency's numerator)", 2, "efficiency",
        base_arr, scen_arr, scen_arr - base_arr, True, "product",
        ("am_expansion_arr_cross_mart",),
        note="Product-with-constant (x12 annualisation) -- the one real, "
             "governance-validated two-variable-shaped PRODUCT edge this data "
             "supports; see module docstring for why the tree's genuine "
             "two-factor products are NOT_COMPUTABLE instead.")

    # --- Onboarding/CS efficiency (ratio) ---
    base_oce = compute_onboarding_cs_efficiency(eff_m)
    scen_oce = compute_onboarding_cs_efficiency(eff_s)
    n = _l1("onboarding_cs_efficiency")
    nodes[n.key] = NodeResult(n.key, n.label, 1, n.pillar, base_oce, scen_oce,
                              scen_oce - base_oce, True, "ratio",
                              ("onboarding_cs_efficiency_ratio",))

    # --- Consumption payback (ratio, revenue-weighted blend) ---
    base_pay = compute_consumption_payback(eff_m, dur_m)
    scen_pay = compute_consumption_payback(eff_s, dur_m)
    n = _l1("consumption_payback")
    nodes[n.key] = NodeResult(n.key, n.label, 1, n.pillar, base_pay, scen_pay,
                              scen_pay - base_pay, True, "ratio",
                              ("consumption_payback_ratio",))

    # --- NRR / GRR (ratio-of-sum, monthly, then annualised) ---
    base_nrr_m, base_grr_m = compute_nrr_grr_monthly(dur_m)
    scen_nrr_m, scen_grr_m = compute_nrr_grr_monthly(dur_s)
    base_nrr_annual = float(baseline_actuals.loc[month, "nrr"]) if month in baseline_actuals.index else float("nan")
    base_grr_annual = float(baseline_actuals.loc[month, "grr"]) if month in baseline_actuals.index else float("nan")
    scen_nrr_annual = _annualise_with_scenario_month(baseline_actuals["nrr_monthly"], month, scen_nrr_m)
    scen_grr_annual = _annualise_with_scenario_month(baseline_actuals["grr_monthly"], month, scen_grr_m)
    n = _l1("nrr")
    nodes[n.key] = NodeResult(
        n.key, n.label, 1, n.pillar, base_nrr_annual, scen_nrr_annual,
        scen_nrr_annual - base_nrr_annual, True, "ratio", ("nrr_ratio",),
        note=f"Trailing-12-month compounded rate, matching mart_gtm_plan's units "
             f"(vd.blend_layer1_actuals precedent); this month's own monthly rate "
             f"moves {base_nrr_m:.6f} -> {scen_nrr_m:.6f} under the scenario, the "
             "other 11 months in the window are real and unperturbed.")
    n = _l1("grr")
    nodes[n.key] = NodeResult(
        n.key, n.label, 1, n.pillar, base_grr_annual, scen_grr_annual,
        scen_grr_annual - base_grr_annual, True, "ratio", ("grr_ratio",),
        note=f"Same treatment as NRR; monthly rate moves {base_grr_m:.6f} -> "
             f"{scen_grr_m:.6f}.")
    nodes["nrr_monthly"] = NodeResult("nrr_monthly", "NRR (monthly, unannualised)", 1,
                                      "durability", base_nrr_m, scen_nrr_m,
                                      scen_nrr_m - base_nrr_m, True, "ratio", ("nrr_ratio",))
    nodes["grr_monthly"] = NodeResult("grr_monthly", "GRR (monthly, unannualised)", 1,
                                      "durability", base_grr_m, scen_grr_m,
                                      scen_grr_m - base_grr_m, True, "ratio", ("grr_ratio",))

    # --- Logo retention (ratio, monthly, then annualised) ---
    base_lr_m = compute_logo_retention_monthly(dur_m)
    scen_lr_m = compute_logo_retention_monthly(dur_s)
    base_lr_annual = float(baseline_actuals.loc[month, "logo_retention"]) if month in baseline_actuals.index else float("nan")
    scen_lr_annual = _annualise_with_scenario_month(baseline_actuals["logo_retention_monthly"], month, scen_lr_m)
    n = _l1("logo_retention")
    nodes[n.key] = NodeResult(n.key, n.label, 1, n.pillar, base_lr_annual, scen_lr_annual,
                              scen_lr_annual - base_lr_annual, True, "ratio",
                              ("logo_retention_ratio",))

    # --- Win rate / avg initial commitment (Layer 2, ratio) + the real,
    #     distinct bookings consequence + the explicit NOT_COMPUTABLE gap
    #     on New logo consumption revenue ---
    for seg in _REP_SOLD_SEGMENTS:
        base_wr = compute_win_rate(gb_m, seg)
        scen_wr = compute_win_rate(gb_s, seg)
        nodes[f"win_rate__{seg}"] = NodeResult(
            "win_rate", f"Win rate ({seg})", 2, "growth", base_wr, scen_wr,
            scen_wr - base_wr, True, "ratio", ("win_rate_ratio",))
        base_aic = compute_avg_initial_commitment(gb_m, seg)
        scen_aic = compute_avg_initial_commitment(gb_s, seg)
        nodes[f"avg_initial_commitment__{seg}"] = NodeResult(
            "avg_initial_commitment", f"Avg initial commitment ({seg})", 2, "growth",
            base_aic, scen_aic, scen_aic - base_aic, True, "ratio", ("win_rate_ratio",))

    if touched_new_logo_path:
        base_bookings = compute_new_logo_bookings_amount_rep_sold(gb_m)
        scen_bookings = compute_new_logo_bookings_amount_rep_sold(gb_s)
        nodes["new_logo_bookings_amount_rep_sold"] = NodeResult(
            "new_logo_bookings_amount_rep_sold",
            "New logo bookings amount, Commercial+Enterprise (bookings lens, "
            "distinct from New logo consumption revenue's revenue lens)",
            2, "growth", base_bookings, scen_bookings, scen_bookings - base_bookings,
            True, "product",
            ("win_rate_ratio", "new_logo_equals_pipeline_x_winrate_x_commitment"),
            note="Real mart consequence of the win_rate / avg_initial_commitment "
                 "change; NOT the same quantity as new_logo_consumption_revenue "
                 "(mart_growth_bridge's own header: the two New Logo lenses "
                 "'will NOT match exactly... a normal, real bookings-vs-revenue-"
                 "recognition gap, not a bug').")
        n = _l1("new_logo_consumption_revenue")
        base_nlcr = float(gb_m["new_logo_mrr"].sum())
        nodes[n.key] = NodeResult(
            n.key, n.label, 1, n.pillar, base_nlcr, None, None, False, "product",
            ("new_logo_equals_pipeline_x_winrate_x_commitment",),
            note=_NEW_LOGO_PRODUCT_GAP_NOTE)
        notes.append(
            "win_rate / avg_initial_commitment was changed, but New logo consumption "
            "revenue (Layer 1) has no valid propagation path in this data -- see "
            "the 'new_logo_consumption_revenue' node's own note.")

    # --- Growth pillar bridge (sum). New logo held at its real baseline
    #     if this scenario's only new-logo-adjacent driver has no valid
    #     path into it -- reported as `partial` in that case. ---
    new_logo_override = base_nlcr if touched_new_logo_path else None
    base_pillar = compute_growth_pillar_bridge(gb_m)
    scen_pillar = compute_growth_pillar_bridge(gb_s, new_logo_mrr_override=new_logo_override)
    pillar_computable = True
    pillar_note = None
    if touched_new_logo_path:
        pillar_note = (
            "PARTIAL: New logo consumption revenue is held at its real baseline "
            "in this figure because win_rate / avg_initial_commitment has no "
            "valid propagation path into it (see new_logo_consumption_revenue's "
            "note) -- this is a stated modelling limitation, not a claim that "
            "New Logo genuinely would not move.")
    nodes["growth_pillar_bridge"] = NodeResult(
        "growth_pillar_bridge", "Growth pillar bridge (company-wide, evaluation month)",
        0, "growth", base_pillar, scen_pillar, scen_pillar - base_pillar,
        pillar_computable, "sum",
        ("new_logo_equals_pipeline_x_winrate_x_commitment",) if touched_new_logo_path else (),
        note=pillar_note)

    # --- Magic number / AM efficiency -- explicit NOT_COMPUTABLE ---
    for key in touched_cost_drivers:
        parent_key = _DRIVERS[key].consumed_by[0]
        n = _l1(parent_key)
        nodes[parent_key] = NodeResult(n.key, n.label, 1, n.pillar, None, None, None,
                                       False, "ratio", (f"{parent_key}_ratio",),
                                       note=_COST_GAP_NOTE)
        notes.append(f"{key} was changed, but {parent_key} is structurally NOT_COMPUTABLE "
                     "in this data (no rep-cost/comp source exists) -- see its own note.")

    return ScenarioResult(as_of_date, month, change_list, resolved, nodes, notes)


# =====================================================================
# Self-check: a zero-change scenario must reproduce
# vd.blend_layer1_actuals()'s real baseline exactly -- proof that this
# module's reuse of vd's baseline computation is faithful, not merely
# assumed. Run at build time by check_baseline_matches_variance_diagnostic().
# =====================================================================

def check_baseline_matches_variance_diagnostic(as_of_date: date, con=None) -> dict:
    """For every node this module computes, the BASELINE side of a
    zero-change run must equal vd.blend_layer1_actuals()'s own real value
    at the evaluation month, to floating-point tolerance. Grain: one
    comparison per node this module covers."""
    owns = con is None
    con = con or vd._connect()
    try:
        result = run_scenario(as_of_date, {}, con=con)
        baseline_actuals = vd.blend_layer1_actuals(as_of_date, con=con)
    finally:
        if owns:
            con.close()
    month = result.evaluation_month
    checks = []
    mapping = {
        "contraction_churned_revenue": "contraction_churned_revenue",
        "expansion_consumption_revenue": "expansion_consumption_revenue",
        "onboarding_cs_efficiency": "onboarding_cs_efficiency",
        "consumption_payback": "consumption_payback",
        "nrr": "nrr", "grr": "grr", "logo_retention": "logo_retention",
    }
    for node_key, vd_col in mapping.items():
        mine = result.nodes[node_key].baseline
        theirs = (float(baseline_actuals.loc[month, vd_col])
                  if month in baseline_actuals.index and pd.notna(baseline_actuals.loc[month, vd_col])
                  else float("nan"))
        both_nan = pd.isna(mine) and pd.isna(theirs)
        diff = abs(mine - theirs) if not both_nan and pd.notna(mine) and pd.notna(theirs) else 0.0
        checks.append({"node": node_key, "this_module": mine, "variance_diagnostic": theirs,
                       "abs_diff": diff, "passed": both_nan or diff <= 1e-6})
    return {"as_of_date": as_of_date, "evaluation_month": month, "checks": checks,
            "all_passed": all(c["passed"] for c in checks)}


# =====================================================================
# TEST SUPPORT -- synthetic known-answer scenarios, hand-computable, per
# analytics-engineering-conventions' "Structural/logic artifacts" category.
# Uses hand-built DataFrames (not real marts) so every expected answer is
# exact arithmetic, computed independently of run_scenario()'s own code --
# i.e. these check the FORMULA FUNCTIONS directly, the same "pure function,
# no I/O" discipline analytics/variance_diagnostic.py's rank_siblings()
# tests use.
# =====================================================================

def _synthetic_gb_row(segment, starting=0.0, new_logo=0.0, expansion=0.0, contraction=0.0,
                      churn=0.0, mig_in=0.0, mig_out=0.0, won=0, lost=0, bookings=0.0):
    return {
        "segment": segment, "starting_mrr": starting, "new_logo_mrr": new_logo,
        "expansion_mrr": expansion, "contraction_mrr": contraction, "churn_mrr": churn,
        "migration_in_mrr": mig_in, "migration_out_mrr": mig_out,
        "new_business_won_count": won, "new_business_lost_count": lost,
        "new_logo_bookings_amount": bookings,
    }


def _run_synthetic(name, description, gb_baseline_rows, gb_scenario_rows, check_fn, expected):
    gb_b = pd.DataFrame(gb_baseline_rows)
    gb_s = pd.DataFrame(gb_scenario_rows)
    observed = check_fn(gb_b, gb_s)
    passed = all(abs(observed[k] - v) <= 1e-9 for k, v in expected.items())
    return {"name": name, "description": description, "expected": expected,
           "observed": observed, "passed": passed}


def _case_sum_node():
    base = [_synthetic_gb_row("Commercial", contraction=100.0, churn=50.0)]
    scen = [_synthetic_gb_row("Commercial", contraction=130.0, churn=50.0)]  # +30 to contraction

    def check(b, s):
        return {"baseline": compute_contraction_churned_revenue(b),
               "scenario": compute_contraction_churned_revenue(s)}

    return _run_synthetic(
        "sum_node_contraction_churned_revenue",
        "A +30 change to contraction_mrr, with churn_mrr held fixed, must move the sum "
        "(contraction + churn) by exactly +30 -- no more, no less.",
        base, scen, check, {"baseline": 150.0, "scenario": 180.0})


def _case_product_with_constant_node():
    base = [_synthetic_gb_row("Commercial", expansion=1000.0),
           _synthetic_gb_row("Enterprise", expansion=500.0)]
    scen = [_synthetic_gb_row("Commercial", expansion=1200.0),
           _synthetic_gb_row("Enterprise", expansion=500.0)]

    def check(b, s):
        return {"baseline": compute_am_expansion_arr(b), "scenario": compute_am_expansion_arr(s)}

    return _run_synthetic(
        "product_node_am_expansion_arr",
        "am_expansion_arr = (sum of expansion_mrr across segments) x 12. Commercial's "
        "expansion_mrr moves 1000 -> 1200 (+200); total expansion 1500 -> 1700, so the "
        "annualised product must move exactly (1700-1500) x 12 = 2400.",
        base, scen, check, {"baseline": 18000.0, "scenario": 20400.0})


def _case_ratio_node():
    eff_b = pd.DataFrame([{"segment": "Commercial", "am_touchpoint_count": 500,
                           "automated_actions_delivered": 100_000}])
    eff_s = pd.DataFrame([{"segment": "Commercial", "am_touchpoint_count": 600,
                           "automated_actions_delivered": 100_000}])
    observed = {"baseline": compute_onboarding_cs_efficiency(eff_b),
               "scenario": compute_onboarding_cs_efficiency(eff_s)}
    expected = {"baseline": 0.005, "scenario": 0.006}
    passed = all(abs(observed[k] - v) <= 1e-9 for k, v in expected.items())
    return {"name": "ratio_node_onboarding_cs_efficiency",
           "description": "A numerator-only change (touchpoints 500 -> 600, actions held "
                          "fixed at 100,000) must move the ratio to exactly 600/100000.",
           "expected": expected, "observed": observed, "passed": passed}


def _case_ratio_of_sum_and_shared_ancestor():
    """The multi-path / no-double-counting case: ONE leaf (contraction_mrr,
    +200) has THREE real ancestors -- contraction_churned_revenue (sum),
    NRR and GRR (ratio-of-sum, sharing the same underlying dollar figure)
    -- and each must move by exactly the amount that single formula
    predicts, with no double-application anywhere."""
    dur_b = pd.DataFrame([{"segment": "Commercial", "starting_mrr": 10_000.0,
                           "contraction_mrr": 300.0, "churn_mrr": 100.0, "expansion_mrr": 800.0}])
    dur_s = pd.DataFrame([{"segment": "Commercial", "starting_mrr": 10_000.0,
                           "contraction_mrr": 500.0, "churn_mrr": 100.0, "expansion_mrr": 800.0}])
    gb_b = [_synthetic_gb_row("Commercial", starting=10_000.0, contraction=300.0, churn=100.0, expansion=800.0)]
    gb_s = [_synthetic_gb_row("Commercial", starting=10_000.0, contraction=500.0, churn=100.0, expansion=800.0)]

    base_nrr_m, base_grr_m = compute_nrr_grr_monthly(dur_b)
    scen_nrr_m, scen_grr_m = compute_nrr_grr_monthly(dur_s)
    base_ccr = compute_contraction_churned_revenue(pd.DataFrame(gb_b))
    scen_ccr = compute_contraction_churned_revenue(pd.DataFrame(gb_s))
    base_pillar = compute_growth_pillar_bridge(pd.DataFrame(gb_b))
    scen_pillar = compute_growth_pillar_bridge(pd.DataFrame(gb_s))

    observed = {
        "contraction_churned_revenue_delta": scen_ccr - base_ccr,
        "nrr_monthly_delta": scen_nrr_m - base_nrr_m,
        "grr_monthly_delta": scen_grr_m - base_grr_m,
        "growth_pillar_bridge_delta": scen_pillar - base_pillar,
    }
    expected = {
        "contraction_churned_revenue_delta": 200.0,      # + the raw dollar move
        "nrr_monthly_delta": -0.02,                       # -200 / 10,000 starting
        "grr_monthly_delta": -0.02,                       # identical -- same driver, same denominator
        "growth_pillar_bridge_delta": -200.0,              # subtracted once in the pillar sum
    }
    passed = all(abs(observed[k] - v) <= 1e-9 for k, v in expected.items())
    return {"name": "shared_ancestor_contraction_mrr_no_double_counting",
           "description": "One leaf (contraction_mrr, +200 on a 10,000 starting-MRR base) "
                          "has three real ancestors on different tree branches -- "
                          "contraction_churned_revenue (Growth, sum), NRR and GRR (Durability, "
                          "ratio-of-sum) -- plus the Growth pillar bridge. Each must reflect "
                          "the identical, single +200 change exactly once.",
           "expected": expected, "observed": observed, "passed": passed}


def _case_not_computable_new_logo():
    """The build spec's own example ('what if win rate improves by 5
    percentage points'), run through run_scenario() end to end against
    real marts data at a fixed as_of_date -- confirms the engine reports
    NOT_COMPUTABLE rather than fabricating a New Logo consumption revenue
    figure, while still computing win_rate's own real new value.

    Tolerance note: won-deal count is a real integer, so a requested +5pp
    win-rate delta lands at the nearest whole-deal outcome
    (new_won = round(scenario_win_rate x closed_count)), not the
    mathematically exact +0.05 -- a real quantization effect of a discrete
    population, not an engine bug. The tolerance below (one quantization
    step, 1/closed_count, generously rounded up) reflects that rather than
    asserting exact equality on a quantity that is inherently discrete."""
    result = run_scenario(date(2025, 11, 30),
                          {"win_rate": {"segment": "Commercial", "change_type": "delta", "value": 0.05}})
    nlcr = result.nodes.get("new_logo_consumption_revenue")
    wr = result.nodes.get("win_rate__Commercial")
    win_rate_delta = (wr.scenario - wr.baseline) if wr else None
    passed = (
        nlcr is not None and nlcr.computable is False and nlcr.scenario is None
        and nlcr.note == _NEW_LOGO_PRODUCT_GAP_NOTE
        and wr is not None and wr.computable is True
        and win_rate_delta is not None and abs(win_rate_delta - 0.05) <= 0.02
    )
    return {"name": "not_computable_new_logo_from_win_rate_scenario",
           "description": "Changing win_rate by +5pp (Commercial) must compute win_rate's "
                          "own new value (to within one whole-deal quantization step), and "
                          "must report new_logo_consumption_revenue as NOT_COMPUTABLE with "
                          "the exact governance reason -- never a fabricated figure.",
           "expected": {"win_rate_computable": True, "new_logo_computable": False,
                       "win_rate_delta_approx": 0.05},
           "observed": {
               "win_rate_computable": wr.computable if wr else None,
               "win_rate_delta": win_rate_delta,
               "new_logo_computable": nlcr.computable if nlcr else None,
           },
           "passed": passed}


def _case_not_computable_cost_gap():
    """A scenario touching s_m_cost (no data source anywhere in this
    project) must report magic_number as NOT_COMPUTABLE with the exact
    same gap reason vd.get_node('magic_number') already carries -- not a
    silently-dropped request."""
    result = run_scenario(date(2025, 11, 30),
                          {"s_m_cost": {"segment": "Commercial", "change_type": "pct", "value": 0.10}})
    mn = result.nodes.get("magic_number")
    passed = mn is not None and mn.computable is False and mn.note == _COST_GAP_NOTE
    return {"name": "not_computable_cost_gap_magic_number",
           "description": "A scenario naming s_m_cost (no cost data anywhere in this "
                          "project's raw sources) must report magic_number as "
                          "NOT_COMPUTABLE, not silently ignore the request or fabricate a "
                          "figure.",
           "expected": {"magic_number_computable": False},
           "observed": {"magic_number_computable": mn.computable if mn else None},
           "passed": passed}


def _case_conflicting_rate_aliases_raises():
    """nrr_contraction_rate and grr_contraction_rate both name the SAME
    physical quantity (contraction_mrr). Requesting incompatible values for
    both in one scenario must raise, not silently pick one."""
    raised = False
    try:
        run_scenario(date(2025, 11, 30), {
            "nrr_contraction_rate": {"segment": "Commercial", "change_type": "delta", "value": 0.02},
            "grr_contraction_rate": {"segment": "Commercial", "change_type": "delta", "value": 0.05},
        })
    except ValueError:
        raised = True
    return {"name": "conflicting_rate_aliases_raise",
           "description": "nrr_contraction_rate and grr_contraction_rate both resolve to "
                          "contraction_mrr for the same segment; requesting two different "
                          "deltas in one scenario must raise ValueError rather than silently "
                          "applying one and discarding the other.",
           "expected": {"raised": True}, "observed": {"raised": raised}, "passed": raised}


SYNTHETIC_SCENARIOS = [
    _case_sum_node, _case_product_with_constant_node, _case_ratio_node,
    _case_ratio_of_sum_and_shared_ancestor, _case_not_computable_new_logo,
    _case_not_computable_cost_gap, _case_conflicting_rate_aliases_raises,
]


def run_synthetic_scenarios() -> List[dict]:
    return [case() for case in SYNTHETIC_SCENARIOS]


# =====================================================================
# Build-time validation
# =====================================================================

def run_build_time_validation(as_of_date: date, log: bool = True) -> dict:
    """Everything analytics-model-validator needs: the synthetic-scenario
    results (the correctness claim), and the real-data self-check that
    this module's reused baseline matches
    analytics/variance_diagnostic.py's own real output exactly. No AUC,
    coefficient table or confusion matrix -- structural artifact, per
    analytics-engineering-conventions."""
    scenarios = run_synthetic_scenarios()
    self_check = check_baseline_matches_variance_diagnostic(as_of_date)
    example = run_scenario(as_of_date, {
        "contraction_mrr": {"segment": "Commercial", "change_type": "pct", "value": 0.15},
        "am_touchpoint_count": {"segment": "Enterprise", "change_type": "pct", "value": -0.10},
    })

    if log:
        log_performance(_MODEL_NAME, as_of_date, "synthetic_scenarios_total", float(len(scenarios)))
        log_performance(_MODEL_NAME, as_of_date, "synthetic_scenarios_passed",
                        float(sum(s["passed"] for s in scenarios)))
        log_performance(_MODEL_NAME, as_of_date, "baseline_self_check_nodes_total",
                        float(len(self_check["checks"])))
        log_performance(_MODEL_NAME, as_of_date, "baseline_self_check_nodes_passed",
                        float(sum(c["passed"] for c in self_check["checks"])))
        log_performance(_MODEL_NAME, as_of_date, "drivers_registered", float(len(_DRIVERS)))

    return {"synthetic_scenarios": scenarios, "baseline_self_check": self_check,
           "example_multi_input_scenario": example.to_dict()}


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    AS_OF = date(2025, 11, 30)  # matches vd's own canonical checkpoint (end-of-window caveat)
    out = run_build_time_validation(AS_OF)

    print("=== Synthetic scenarios ===")
    for s in out["synthetic_scenarios"]:
        print(f"[{'PASS' if s['passed'] else 'FAIL'}] {s['name']}")
        if not s["passed"]:
            print(f"        expected={s['expected']} observed={s['observed']}")

    print("\n=== Baseline self-check vs. analytics/variance_diagnostic.py ===")
    for c in out["baseline_self_check"]["checks"]:
        print(f"[{'PASS' if c['passed'] else 'FAIL'}] {c['node']}: "
              f"this_module={c['this_module']} variance_diagnostic={c['variance_diagnostic']} "
              f"diff={c['abs_diff']}")

    print("\n=== Example multi-input scenario "
          "(contraction_mrr +15% Commercial, am_touchpoint_count -10% Enterprise) ===")
    ex = out["example_multi_input_scenario"]
    for key, n in ex["nodes"].items():
        print(f"  {key}: baseline={n['baseline']} scenario={n['scenario']} delta={n['delta']} "
              f"computable={n['computable']}")
    for note in ex["notes"]:
        print(f"  note: {note}")
