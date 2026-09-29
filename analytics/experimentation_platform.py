"""Testing / experimentation methodology & platform -- grain: one evaluation
run per (experiment_id, as_of_date), operating over dim_experiment (one row
per registered experiment) and fact_experiment_assignment (one row per
experiment-unit assignment); the one outcome-specific adapter this artifact
ships (EXP-0001's) additionally reads fact_leads and fact_campaign_
engagement_events. Build spec item #13, Wave 7, marked infrastructure.

============================================================================
WHAT THIS IS -- AND WHAT IT DELIBERATELY IS NOT
============================================================================
This is the reusable evaluation ENGINE a RevOps/growth team would want for
ANY experiment registered in dim_experiment/fact_experiment_assignment --
target-metric lift, a significance test, guardrail-metric monitoring, and
sample-size/power context -- built as general, parameterized functions over
the registry/assignment tables, not hand-coded for the one experiment that
happens to exist. It is NOT a recomputation of that one experiment's result:
`analytics/marketing_attribution.py` already derives the holdout
incrementality read correctly (point-in-time-safe cell resolution,
censored-cell exclusion, a design-based two-proportion estimator with a
closed-form standard error) and is not modified or imported by this module.
Instead, this module re-derives the SAME number independently, through its
own general machinery, and checks that the two agree -- which is the
correctness proof that the general framework produces the right answer on
the one case where the right answer is already known.

THE ONE HONEST LIMIT OF "GENERAL": OUTCOME SOURCING NEEDS AN ADAPTER
----------------------------------------------------------------------
The statistical core below (resolution-horizon derivation, point-in-time
outcome resolution, the two-proportion test, cell pooling, power/MDE) is
100% generic -- it operates on plain (unit_id, arm, group, created_date,
event_flag, event_date) columns and has no EXP-0001-specific logic in it
anywhere. What CANNOT be made generic from free text alone is *where* a
given experiment's target-metric outcome event actually lives --
dim_experiment.target_metric is a human-written sentence
("lead_to_pql_rate ... scoped to leads whose channel-specific resolution
horizon has elapsed"), not a machine-actionable join path, and
fact_experiment_assignment carries no outcome column of its own by design
(the same reason fact_leads and fact_opportunities don't carry each
other's columns -- an assignment fact is not an outcome fact). So each
experiment needs exactly one small outcome adapter (a function that knows
which mart(s) hold its outcome event and returns the framework's plain
schema) and, if its guardrail_metrics reference something outcome
adapters don't already cover, one guardrail adapter. Registering a new
experiment means writing that one adapter; the evaluation math above is
reused completely unchanged. This is the honest scope of "general" for a
platform proven against a single real case -- the same shape of documented
seam this project already uses for the weekly readout's narrative
generation (build spec Section 5): the seam is real and load-bearing, not
a placeholder pretending to be finished work.

============================================================================
AS_OF_DATE -- WHAT IT MEANS FOR A CLOSED EXPERIMENT VS. A RUNNING ONE
============================================================================
Three independent point-in-time cuts, all driven by the same as_of_date,
so the framework behaves correctly whether the experiment it's evaluating
is fully resolved (EXP-0001's real case) or hypothetically still enrolling
and still accumulating outcomes:
  1. Which UNITS are even visible: load_experiment_assignment() only
     returns assignment rows with assigned_date <= as_of_date. A
     still-enrolling experiment's population grows as as_of_date advances;
     a closed experiment's population is already fixed by its last
     assigned_date, so this cut is a no-op past that date.
  2. Which OUTCOME EVENTS are visible: resolve_binary_outcome_state() only
     counts a unit's target event as having happened if its event date is
     <= as_of_date -- exactly the discipline marketing_attribution.py's
     build_lead_panel() applies, reimplemented independently here (see
     below).
  3. Which UNITS are RESOLVED (usable in the denominator) at all: a unit
     that has neither hit the event nor exceeded its group's observed
     resolution horizon is `open` and excluded from both the numerator and
     denominator, per group -- so a cell whose tail hasn't finished
     resolving by as_of_date is measured on the part of it that has,
     never silently scored as a block of non-events. This is what makes
     evaluating a still-running experiment safe: nothing forces every cell
     to already be closed out for the framework to return a real,
     honestly-scoped number for the parts that are.
For EXP-0001 specifically, the experiment's own end_date (2025-03-31) is
already in the past at both checkpoints this module runs, so cut (1) is
moot -- every real change between the 2025-06-30 and 2025-12-31 checkpoints
is entirely driven by cut (3): more cells cross their resolution horizon
and become poolable. That is not a limitation of a "closed" experiment --
it is the exact same resolution-horizon mechanic a still-running experiment
needs, demonstrated on real data because this dataset's own simulation
window (2023-01 to 2025-12) ends before community's 314-day horizon
closes out its final cell.

============================================================================
SHAPE -- STRUCTURAL/LOGIC ARTIFACT, PER analytics-engineering-conventions
============================================================================
Nothing here is fitted. The core estimator is a design-based (randomized-
cell) two-proportion comparison with a closed-form standard error --
exactly marketing_attribution.py's own choice, made for the same reason:
this project's one real experiment IS a randomized holdout, so a fitted
propensity/uplift model would replace a causal answer with a correlational
proxy for a quantity already measured causally. Per
analytics-engineering-conventions' "Structural/logic artifacts" category,
there is no coefficient table, no R^2/RMSE, no AUC, no confusion matrix and
no calibration note here, and their absence is deliberate, not pending.
The power/MDE calculations are closed-form normal-approximation formulas,
not simulations -- no random seed applies anywhere in this module, the
same "no stochastic step" note marketing_attribution.py, segment_
migration.py, variance_diagnostic.py and capacity_planning.py all carry.

MODEL-TYPE SELECTION AND RATIONALE (why a design-based two-proportion test,
and not, e.g., a regression-adjusted or Bayesian estimator): the only
credible alternative considered was a regression-adjusted (CUPED-style)
estimator, which reduces variance by conditioning on pre-experiment
covariates. Rejected for this data because it would still have to be
computed on the same treated/control arms and the same closed-form
variance machinery already validated in marketing_attribution.py --
adding a covariate-adjustment layer changes precision, not correctness,
and the validation bar for a brand-new platform is "does it get the
existing answer right," not "can it get it right with a tighter interval."
It is a legitimate future refinement once a second registered experiment
actually needs the extra precision, not a requirement for this one.

============================================================================
HONEST SCOPE ON "ONE EXPERIMENT" -- read before citing this module's output
============================================================================
This project has exactly one real, catalogued, randomized experiment
(EXP-0001) today. This module does not simulate a second one to make the
platform look richer than it is -- the same discipline
analytics/proxy_metric_health.py applies to its own thin checkpoint
history. What IS genuinely complete, and the actual deliverable here, is
the FRAMEWORK: evaluate_experiment(), check_registry_completeness(), and
the statistical core they're built on are proven correct against the one
real case with a known-correct answer, and are ready to evaluate the next
registered experiment the moment it exists -- via one new outcome adapter,
not a rewrite.
"""
import os
import json
from datetime import date

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
_MODEL_NAME = "experimentation_platform"

EXP_MARKETING_HOLDOUT = "EXP-0001"

# Significance bars. 95% two-sided is this framework's own default
# reporting bar for any future experiment; marketing_attribution.py chose a
# deliberately more conservative 2.58 (99%) as EXP-0001's own operating
# floor (docs/acme-corp-analytics-methods.md, holdout_suppression_is_real_
# and_reconciles) -- cited here for comparison, not imported as this
# module's default.
_DEFAULT_ALPHA = 0.05
_EXP0001_METHODS_DOC_Z_FLOOR = 2.58

# Reproduction tolerance: dim_experiment.result_value/result_se are stored
# rounded to 4dp and result_z to 2dp (see generators/experiments.py). A
# genuine second derivation cannot match a rounded figure to more digits
# than the rounding itself carries, so the tolerance is set at roughly 2x
# each figure's own half-rounding-unit -- tight enough to catch a real
# disagreement, loose enough not to fail on the registry's own rounding.
_REPRODUCTION_TOLERANCE_SHARE = 0.0002
_REPRODUCTION_TOLERANCE_Z = 0.02


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


# ==========================================================================
# 1. Registry / assignment loaders -- marts only (dim_experiment,
#    fact_experiment_assignment), general over ANY experiment_id
# ==========================================================================

def load_experiment_registry(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per experiment registered in dim_experiment whose
    start_date <= as_of_date -- an experiment that hasn't started yet by
    as_of_date isn't evaluable and shouldn't appear. Source mart:
    dim_experiment."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select * from main_marts.dim_experiment where start_date <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    for c in ("start_date", "end_date", "result_as_of_date"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c])
    return df


def load_experiment_assignment(experiment_id: str, as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per (experiment_id, unit) assignment recorded at or
    before as_of_date -- the point-in-time cut that matters for a
    still-enrolling experiment (moot for EXP-0001, whose real population is
    already fixed by 2025-03-31). Source mart: fact_experiment_assignment."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select assignment_id, experiment_id, lead_id, account_id, company_id, "
            "channel, cell_quarter, first_touch_campaign_id, arm, assigned_date "
            "from main_marts.fact_experiment_assignment "
            "where experiment_id = ? and assigned_date <= ?",
            [experiment_id, as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["assigned_date"] = pd.to_datetime(df["assigned_date"])
    return df


# ==========================================================================
# 2. Generic statistical core -- no experiment-specific logic anywhere in
#    this section. Reimplemented independently from marketing_attribution.py
#    (not imported from it) so the reproduction check below is a genuine
#    second derivation, not a call into the module it's cross-checking.
# ==========================================================================

def derive_group_resolution_horizon(pool: pd.DataFrame, group_col: str, created_col: str,
                                     event_flag_col: str, event_date_col: str,
                                     as_of_date: date) -> dict:
    """Per-group maximum observed (event_date - created_date), in days,
    measured only over events already visible at as_of_date. General
    technique behind marketing_attribution.py's derive_resolution_horizon()
    -- the maximum, not a high quantile, is used deliberately: classifying
    a still-resolvable unit as a resolved non-event would bias every rate
    downward. `pool` should be the group's FULL observed population (e.g.
    all leads on that channel), not just the experiment's own subset --
    a group's resolution horizon is a property of the group's whole
    history, not of whichever slice happens to sit inside one experiment."""
    as_of_ts = pd.Timestamp(as_of_date)
    resolved = pool[pool[event_flag_col] & (pool[event_date_col] <= as_of_ts)]
    gap_days = (resolved[event_date_col] - resolved[created_col]).dt.days
    return gap_days.groupby(resolved[group_col]).max().to_dict()


def resolve_binary_outcome_state(df: pd.DataFrame, group_col: str, created_col: str,
                                  event_flag_col: str, event_date_col: str,
                                  as_of_date: date, horizon: dict) -> pd.DataFrame:
    """Adds `conversion_state` (converted / open / lapsed), `is_event_as_of`
    and `is_resolved_as_of` to df, point-in-time safe: a unit whose
    terminal event_flag is True but whose event_date falls after as_of_date
    is `open`, never `converted` -- the exact case where reading a terminal
    flag directly would leak the future. General; takes no experiment-
    specific input beyond its own column names."""
    as_of_ts = pd.Timestamp(as_of_date)
    out = df.copy()
    event_now = out[event_flag_col] & (out[event_date_col] <= as_of_ts)
    days_since_created = (as_of_ts - out[created_col]).dt.days
    group_horizon = out[group_col].map(horizon)
    out["conversion_state"] = np.where(
        event_now, "converted",
        np.where(days_since_created <= group_horizon, "open", "lapsed"),
    )
    out["is_event_as_of"] = event_now
    out["is_resolved_as_of"] = out["conversion_state"].isin(("converted", "lapsed"))
    return out


def two_arm_rate(df: pd.DataFrame, arm_col: str, arm_value, resolved_col: str = "is_resolved_as_of",
                  event_col: str = "is_event_as_of", state_col: str = "conversion_state") -> tuple:
    """(n_resolved, k_events, rate, n_open) for one arm of df. General --
    no assumption about what the arm labels mean beyond "one value picks
    out this arm's rows"."""
    sub = df[df[arm_col] == arm_value]
    resolved = sub[sub[resolved_col]]
    n = int(len(resolved))
    k = int(resolved[event_col].sum())
    n_open = int((sub[state_col] == "open").sum())
    return n, k, (k / n if n else float("nan")), n_open


def two_proportion_ztest(n_treatment: int, k_treatment: int, n_control: int, k_control: int) -> dict:
    """Closed-form two-proportion z-test on the rate difference, plus a
    delta-method standard error on the incremental share (1 - control_rate
    / treatment_rate) -- identical formulas to marketing_attribution.py's
    measure_incrementality()._one(), reimplemented independently. Applies
    to any two-arm binary-outcome experiment, not just a holdout design:
    `incremental_share` is just a rescaling of the same rate difference and
    is meaningful whenever the treatment arm's rate is expected to be
    directionally >= the control arm's."""
    pt = k_treatment / n_treatment if n_treatment else float("nan")
    pc = k_control / n_control if n_control else float("nan")
    out = {
        "n_treatment": n_treatment, "k_treatment": k_treatment, "rate_treatment": pt,
        "n_control": n_control, "k_control": k_control, "rate_control": pc,
    }
    if n_treatment and n_control and pd.notna(pt) and pd.notna(pc):
        pooled_p = (k_treatment + k_control) / (n_treatment + n_control)
        se_diff = np.sqrt(pooled_p * (1 - pooled_p) * (1 / n_treatment + 1 / n_control))
        out["absolute_lift_pp"] = 100.0 * (pt - pc)
        out["relative_lift"] = (pt / pc - 1.0) if pc else float("nan")
        out["z_stat"] = (pt - pc) / se_diff if se_diff > 0 else float("nan")
        out["p_value_two_sided"] = (
            float(2 * (1 - stats.norm.cdf(abs(out["z_stat"])))) if pd.notna(out["z_stat"]) else float("nan")
        )
        out["incremental_share"] = (1.0 - pc / pt) if pt else float("nan")
        se_t = np.sqrt(pt * (1 - pt) / n_treatment) if n_treatment else float("nan")
        se_c = np.sqrt(pc * (1 - pc) / n_control) if n_control else float("nan")
        if pt > 0 and pc > 0:
            ratio = pc / pt
            out["incremental_share_se"] = ratio * np.sqrt((se_c / pc) ** 2 + (se_t / pt) ** 2)
        else:
            # A control arm with zero events gives a point estimate of 1.0
            # with no closed-form SE -- reported as NaN, not a spuriously
            # precise 0.
            out["incremental_share_se"] = float("nan")
        out["significant_95pct"] = bool(abs(out["z_stat"]) >= 1.959964) if pd.notna(out["z_stat"]) else None
    else:
        out.update({"absolute_lift_pp": float("nan"), "relative_lift": float("nan"),
                    "z_stat": float("nan"), "p_value_two_sided": float("nan"),
                    "incremental_share": float("nan"), "incremental_share_se": float("nan"),
                    "significant_95pct": None})
    return out


def evaluate_cells(df: pd.DataFrame, arm_col: str, treat_value, control_value,
                    cell_cols=None, group_col: str = None) -> tuple:
    """General cell-pooling engine: one row per cell (any grouping columns
    -- e.g. channel x cohort-quarter for a staggered design, or none at
    all for a single-cohort experiment), plus fully-resolved-only pooled
    rows (an optional per-group rollup, and one overall pooled row).
    Reimplements, independently and generically, the censoring discipline
    marketing_attribution.py's measure_incrementality() established for
    this project's one real staggered-cohort design: a cell is only pooled
    once EVERY unit in it (both arms) has had its group's full resolution
    horizon to resolve (no leads_open remaining) -- censoring here is
    informative, not random, so an unresolved cell would otherwise pull a
    pooled estimate toward whatever a mostly-converted resolved subset
    looks like, for a reason that has nothing to do with the treatment.
    Unresolved cells are still reported at cell grain, flagged, never
    dropped silently. Returns (cells_df, pooled_df, n_cells_resolved,
    n_cells_total)."""
    cell_cols = cell_cols or []
    rows = []
    resolved_cell_keys = []

    if cell_cols:
        grouped = df.groupby(cell_cols)
        n_cells_total = grouped.ngroups
        iterator = list(grouped)
    else:
        n_cells_total = 1
        iterator = [(None, df)]

    for key, g in iterator:
        nt, kt, _, ot = two_arm_rate(g, arm_col, treat_value)
        nc, kc, _, oc = two_arm_rate(g, arm_col, control_value)
        stat = two_proportion_ztest(nt, kt, nc, kc)
        row = {}
        if cell_cols:
            row.update(dict(zip(cell_cols, key)))
        row.update(stat)
        row["leads_open_treatment"] = ot
        row["leads_open_control"] = oc
        cell_open = ot + oc
        row["cell_fully_resolved"] = (cell_open == 0)
        rows.append(row)
        if cell_open == 0:
            resolved_cell_keys.append(key)
    cells_df = pd.DataFrame(rows)

    if cell_cols:
        if resolved_cell_keys:
            idx = pd.MultiIndex.from_frame(df[cell_cols])
            resolved_df = df[idx.isin(resolved_cell_keys)]
        else:
            resolved_df = df.iloc[0:0]
    else:
        resolved_df = df if resolved_cell_keys else df.iloc[0:0]

    pooled_rows = []
    if group_col and cell_cols:
        for gval, g in resolved_df.groupby(group_col):
            nt, kt, _, _ = two_arm_rate(g, arm_col, treat_value)
            nc, kc, _, _ = two_arm_rate(g, arm_col, control_value)
            pooled_rows.append({group_col: gval, "scope": "pooled_group",
                                 **two_proportion_ztest(nt, kt, nc, kc)})
    if len(resolved_df):
        nt, kt, _, _ = two_arm_rate(resolved_df, arm_col, treat_value)
        nc, kc, _, _ = two_arm_rate(resolved_df, arm_col, control_value)
        pooled_rows.append({"scope": "pooled_all", **two_proportion_ztest(nt, kt, nc, kc)})
    pooled_df = pd.DataFrame(pooled_rows)

    return cells_df, pooled_df, len(resolved_cell_keys), n_cells_total


def _infer_arms(assignment_df: pd.DataFrame, arm_col: str = "arm") -> tuple:
    """Identifies (treatment_value, control_value) from whatever arm labels
    the data actually uses, by name -- general over any future experiment
    that follows the same 'control' naming convention EXP-0001 does
    (fact_experiment_assignment.arm in {'treatment','control'}). Raises
    rather than guesses for anything else, per this project's own
    'don't silently invent, flag it' discipline."""
    values = sorted(v for v in assignment_df[arm_col].dropna().unique().tolist())
    if len(values) != 2:
        raise ValueError(
            f"expected exactly 2 arms, found {values} -- this framework evaluates "
            "two-arm experiments only; a multi-arm design needs an explicit extension."
        )
    control = next((v for v in values if "control" in str(v).lower()), None)
    if control is None:
        raise ValueError(
            f"could not identify a 'control' arm by name among {values} -- pass "
            "treat_value/control_value explicitly rather than let this be guessed."
        )
    treatment = [v for v in values if v != control][0]
    return treatment, control


def power_two_proportion(n1: int, p1: float, n2: float, p2: float, alpha: float = _DEFAULT_ALPHA) -> float:
    """Achieved (two-sided) power of a two-proportion z-test at given arm
    sizes and hypothesized rates -- the standard closed-form normal-
    approximation formula. No simulation, no seed. n1/p1, n2/p2 are the
    two arms' sizes and hypothesized rates; order doesn't change the
    answer."""
    if not n1 or not n2:
        return float("nan")
    pooled = (n1 * p1 + n2 * p2) / (n1 + n2)
    se0 = np.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    se1 = np.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    if se1 == 0:
        return float("nan")
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    return float(stats.norm.cdf((abs(p1 - p2) - z_alpha * se0) / se1))


def minimum_detectable_effect(n1: int, n2: int, baseline_rate: float, alpha: float = _DEFAULT_ALPHA,
                               target_power: float = 0.80) -> float:
    """Smallest absolute rate difference these ACTUAL arm sizes could
    reliably detect at the stated alpha/power, given the observed control
    rate as the baseline. Solved by bisection over power_two_proportion()
    (monotonic increasing in effect size), not a closed-form inversion --
    deterministic, no seed."""
    if not n1 or not n2 or pd.isna(baseline_rate):
        return float("nan")
    lo, hi = 1e-6, 1.0 - baseline_rate - 1e-6
    if hi <= lo:
        return float("nan")
    for _ in range(60):
        mid = (lo + hi) / 2.0
        achieved = power_two_proportion(n1, baseline_rate + mid, n2, baseline_rate, alpha=alpha)
        if pd.isna(achieved) or achieved < target_power:
            lo = mid
        else:
            hi = mid
    return float(hi)


def sample_size_power_context(designed_effect_size: float, pooled_stat: dict,
                               alpha: float = _DEFAULT_ALPHA, target_power: float = 0.80) -> dict:
    """Was the experiment adequately powered given its ACTUAL (fully-
    resolved, pooled) cell sizes? Two closed-form reads: achieved power to
    detect the registry's own designed_effect_size at these real arm
    sizes, and the minimum effect these real arm sizes could detect at the
    conventional 80% bar -- both driven by what the experiment's data
    actually produced, not by the design-time sample-size assumption."""
    nt = pooled_stat.get("n_treatment")
    nc = pooled_stat.get("n_control")
    pc = pooled_stat.get("rate_control")
    out = {
        "n_treatment_resolved": nt, "n_control_resolved": nc,
        "control_rate_observed": pc, "designed_effect_size": designed_effect_size,
    }
    if not nt or not nc or pd.isna(pc) or pd.isna(designed_effect_size) or designed_effect_size >= 1:
        out.update({"implied_treatment_rate_at_design": None, "achieved_power_at_designed_effect": None,
                     "mde_at_80pct_power": None, "mde_implied_incremental_share": None,
                     "adequately_powered": None})
        return out
    implied_pt = pc / (1.0 - designed_effect_size)
    achieved_power = power_two_proportion(nt, implied_pt, nc, pc, alpha=alpha)
    mde = minimum_detectable_effect(nt, nc, pc, alpha=alpha, target_power=target_power)
    mde_share = (1.0 - pc / (pc + mde)) if pd.notna(mde) else float("nan")
    out.update({
        "implied_treatment_rate_at_design": implied_pt,
        "achieved_power_at_designed_effect": achieved_power,
        "mde_at_80pct_power": mde,
        "mde_implied_incremental_share": mde_share,
        "adequately_powered": bool(achieved_power >= target_power) if pd.notna(achieved_power) else None,
    })
    return out


# ==========================================================================
# 3. Outcome / guardrail adapters -- the one place genericity necessarily
#    stops. See module docstring's "outcome sourcing needs an adapter"
#    section. Registering EXP-0002 someday means adding one entry to each
#    dict below; the statistical core in section 2 does not change.
# ==========================================================================

def _exp0001_outcome_pool(as_of_date: date, con=None) -> pd.DataFrame:
    """Full fact_leads population (ALL channels, not just the paid/
    community subset EXP-0001 covers) -- the pool
    derive_group_resolution_horizon() needs. A channel's resolution horizon
    is a property of that channel's whole observed history, matching
    marketing_attribution.py's own scope, not of the smaller slice that
    happens to sit inside one holdout cell. Source mart: fact_leads."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select lead_id, channel, created_date, converted_date, is_converted "
            "from main_marts.fact_leads where created_date <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["created_date"] = pd.to_datetime(df["created_date"])
    df["converted_date"] = pd.to_datetime(df["converted_date"])
    return df


def _exp0001_outcomes(as_of_date: date, assignment: pd.DataFrame = None, con=None) -> pd.DataFrame:
    """One row per EXP-0001-assigned lead (both arms), joined to its own
    conversion outcome. Source marts: fact_experiment_assignment,
    fact_leads."""
    owns_con = con is None
    con = con or _connect()
    try:
        if assignment is None:
            assignment = load_experiment_assignment(EXP_MARKETING_HOLDOUT, as_of_date, con=con)
        leads = con.execute(
            "select lead_id, channel, created_date, converted_date, is_converted "
            "from main_marts.fact_leads"
        ).df()
    finally:
        if owns_con:
            con.close()
    leads["created_date"] = pd.to_datetime(leads["created_date"])
    leads["converted_date"] = pd.to_datetime(leads["converted_date"])
    out = assignment.merge(leads, on="lead_id", how="left", suffixes=("", "_lead"))
    mismatches = int((out["channel"] != out["channel_lead"]).sum())
    if mismatches:
        # Assignment integrity check: a lead's assignment channel is its
        # first-touch campaign's channel per the registry's own assignment
        # mechanism, and must agree with fact_leads.channel (the same
        # sourcing campaign) by construction. A mismatch here means the
        # dbt-layer join is broken, not a data quirk to shrug at.
        raise AssertionError(
            f"{mismatches} EXP-0001 assignment rows disagree with fact_leads.channel -- "
            "assignment/outcome join integrity is broken."
        )
    return out.drop(columns=["channel_lead"])


def _exp0001_guardrails(as_of_date: date, outcomes_df: pd.DataFrame, pooled_stat: dict, con=None) -> list:
    """The two guardrail metrics EXP-0001's own registry row actually
    specifies (dim_experiment.guardrail_metrics), evaluated structurally
    rather than merely cited:
      1. resolved_control_cell_lead_volume >= 300 (the QA plan's Test D
         power floor) -- read directly off this run's own pooled result.
      2. control_arm_crossover_rate stays low -- INDEPENDENTLY recomputed
         here from fact_campaign_engagement_events + dim_campaign (a
         control-assigned lead that later picks up a non-holdout touch,
         and vice versa for treatment), not merely restated from the
         methods doc. This is a genuine second derivation of the same
         13/1,239 figure cited there, not a copy of it."""
    guardrails = []
    n_control_resolved = pooled_stat.get("n_control") or 0
    guardrails.append({
        "guardrail_metric": "resolved_control_cell_lead_volume",
        "description": "QA plan Test D power floor -- an incrementality test on a "
                        "handful of leads is not a test.",
        "observed_value": n_control_resolved,
        "threshold": ">= 300",
        "passes": bool(n_control_resolved >= 300),
    })

    owns_con = con is None
    con_ = con or _connect()
    try:
        events = con_.execute(
            "select lead_id, campaign_id from main_marts.fact_campaign_engagement_events"
        ).df()
        campaigns = con_.execute("select campaign_id, is_holdout from main_marts.dim_campaign").df()
    finally:
        if owns_con:
            con_.close()
    ev = events.merge(campaigns, on="campaign_id", how="left")

    control_leads = set(outcomes_df.loc[outcomes_df["arm"] == "control", "lead_id"])
    treatment_leads = set(outcomes_df.loc[outcomes_df["arm"] == "treatment", "lead_id"])
    control_crossover = int(ev[ev["lead_id"].isin(control_leads) & (~ev["is_holdout"])]["lead_id"].nunique())
    treatment_crossover = int(ev[ev["lead_id"].isin(treatment_leads) & ev["is_holdout"]]["lead_id"].nunique())
    crossover_rate = (control_crossover / len(control_leads)) if control_leads else float("nan")

    guardrails.append({
        "guardrail_metric": "control_arm_crossover_rate",
        "description": "A control-assigned lead that later picks up a non-holdout "
                        "touch is no longer a clean control. Threshold is this "
                        "artifact's own proposal (see methods doc) -- the registry "
                        "row states 'stays low' without a numeric bar.",
        "observed_value": round(crossover_rate, 4) if pd.notna(crossover_rate) else None,
        "threshold": "<= 0.05 (PROPOSED, not yet confirmed)",
        "passes": bool(crossover_rate <= 0.05) if pd.notna(crossover_rate) else None,
        "detail": (
            f"{control_crossover} of {len(control_leads)} assigned-control leads picked up "
            f"a non-holdout touch; {treatment_crossover} of {len(treatment_leads)} "
            "assigned-treatment leads picked up a holdout touch (reported for completeness -- "
            "only the control-arm figure is gated, since crossover only threatens the "
            "control arm's cleanliness as a control)."
        ),
    })
    return guardrails


# One entry per registered, evaluable experiment. Adding a second real
# experiment means adding one entry to each dict -- not touching anything
# in section 2.
OUTCOME_ADAPTERS = {
    EXP_MARKETING_HOLDOUT: (_exp0001_outcome_pool, _exp0001_outcomes),
}
GUARDRAIL_ADAPTERS = {
    EXP_MARKETING_HOLDOUT: _exp0001_guardrails,
}


# ==========================================================================
# 4. Orchestrator -- the reusable evaluate_experiment() entrypoint
# ==========================================================================

def evaluate_experiment(experiment_id: str, as_of_date: date, con=None) -> dict:
    """Given an experiment_id, compute the standard evaluation package:
    target-metric lift (treatment vs. control) with a significance test,
    guardrail-metric monitoring, and sample-size/power context -- for ANY
    experiment registered in dim_experiment/fact_experiment_assignment
    that has an outcome adapter registered (section 3). Source marts:
    dim_experiment, fact_experiment_assignment, plus whatever marts that
    experiment's own outcome adapter reads."""
    owns_con = con is None
    con = con or _connect()
    try:
        registry = load_experiment_registry(as_of_date, con=con)
        match = registry[registry["experiment_id"] == experiment_id]
        if match.empty:
            return {"experiment_id": experiment_id, "as_of_date": as_of_date.isoformat(),
                     "evaluable": False,
                     "reason": f"{experiment_id} not found in dim_experiment as of {as_of_date} "
                               "(not registered, or not yet started)."}
        reg = match.iloc[0].to_dict()

        adapter = OUTCOME_ADAPTERS.get(experiment_id)
        if adapter is None:
            return {"experiment_id": experiment_id, "as_of_date": as_of_date.isoformat(),
                     "evaluable": False,
                     "reason": f"No outcome adapter registered for {experiment_id}. The "
                               "statistical core is fully general, but knowing where THIS "
                               "experiment's target-metric outcome event lives is not "
                               "derivable from free text alone -- register one in "
                               "OUTCOME_ADAPTERS before this experiment can be evaluated. "
                               "See module docstring."}
        pool_loader, outcome_loader = adapter

        assignment = load_experiment_assignment(experiment_id, as_of_date, con=con)
        if assignment.empty:
            return {"experiment_id": experiment_id, "as_of_date": as_of_date.isoformat(),
                     "evaluable": False,
                     "reason": "No assignment rows visible as of this date."}

        treat_value, control_value = _infer_arms(assignment)

        pool = pool_loader(as_of_date, con=con)
        outcomes = outcome_loader(as_of_date, assignment=assignment, con=con)

        horizon = derive_group_resolution_horizon(
            pool, group_col="channel", created_col="created_date",
            event_flag_col="is_converted", event_date_col="converted_date", as_of_date=as_of_date,
        )
        resolved = resolve_binary_outcome_state(
            outcomes, group_col="channel", created_col="created_date",
            event_flag_col="is_converted", event_date_col="converted_date",
            as_of_date=as_of_date, horizon=horizon,
        )

        cells_df, pooled_df, n_cells_resolved, n_cells_total = evaluate_cells(
            resolved, arm_col="arm", treat_value=treat_value, control_value=control_value,
            cell_cols=["channel", "cell_quarter"], group_col="channel",
        )
        pooled_all_rows = pooled_df[pooled_df["scope"] == "pooled_all"]
        pooled_stat = pooled_all_rows.iloc[0].to_dict() if len(pooled_all_rows) else {}

        power_ctx = sample_size_power_context(reg.get("designed_effect_size"), pooled_stat)

        guardrail_fn = GUARDRAIL_ADAPTERS.get(experiment_id)
        if guardrail_fn is not None:
            guardrails = guardrail_fn(as_of_date, outcomes_df=resolved, pooled_stat=pooled_stat, con=con)
        else:
            guardrails = []

        registry_published = {
            "result_metric": reg.get("result_metric"),
            "result_value": reg.get("result_value"),
            "result_se": reg.get("result_se"),
            "result_z": reg.get("result_z"),
            "result_significant": reg.get("result_significant"),
            "result_as_of_date": (
                reg.get("result_as_of_date").isoformat() if pd.notna(reg.get("result_as_of_date")) else None
            ),
        }
        recomputed = {
            "measured_incremental_share_pooled": pooled_stat.get("incremental_share"),
            "measured_incremental_share_se": pooled_stat.get("incremental_share_se"),
            "measured_z_stat": pooled_stat.get("z_stat"),
        }

        # The registry stores exactly ONE result -- the checkpoint the
        # experiment was actually resolved at (result_as_of_date). It is
        # only meaningful to check "does the general framework reproduce
        # the published number" when this run's as_of_date IS that
        # checkpoint; at any earlier as_of_date the two numbers describe
        # genuinely different, both-correct quantities (a point-in-time
        # read with fewer cells resolved vs. the final resolved read), and
        # comparing them would produce a false "mismatch." Reported as
        # not-applicable rather than a failure.
        result_as_of = reg.get("result_as_of_date")
        is_final_checkpoint = pd.notna(result_as_of) and pd.Timestamp(as_of_date) == pd.Timestamp(result_as_of)

        if is_final_checkpoint:
            share_ok = (
                pd.notna(recomputed["measured_incremental_share_pooled"])
                and pd.notna(registry_published["result_value"])
                and abs(recomputed["measured_incremental_share_pooled"] - registry_published["result_value"])
                < _REPRODUCTION_TOLERANCE_SHARE
            )
            z_ok = (
                pd.notna(recomputed["measured_z_stat"])
                and pd.notna(registry_published["result_z"])
                and abs(recomputed["measured_z_stat"] - registry_published["result_z"]) < _REPRODUCTION_TOLERANCE_Z
            )
            reproduction_check = {
                "applicable": True,
                "abs_diff_incremental_share": abs(
                    recomputed["measured_incremental_share_pooled"] - registry_published["result_value"]
                ),
                "abs_diff_z": abs(recomputed["measured_z_stat"] - registry_published["result_z"]),
                "share_tolerance": _REPRODUCTION_TOLERANCE_SHARE,
                "z_tolerance": _REPRODUCTION_TOLERANCE_Z,
                "reproduces_published_result": bool(share_ok and z_ok),
            }
        else:
            reproduction_check = {
                "applicable": False,
                "abs_diff_incremental_share": None,
                "abs_diff_z": None,
                "share_tolerance": _REPRODUCTION_TOLERANCE_SHARE,
                "z_tolerance": _REPRODUCTION_TOLERANCE_Z,
                "reproduces_published_result": None,
                "reason": (
                    f"as_of_date {as_of_date.isoformat()} is not the registry's own "
                    f"result_as_of_date ({registry_published['result_as_of_date']}) -- the registry "
                    "stores only the final resolved read, so this checkpoint's own point-in-time "
                    "result (fewer cells resolved) is a genuinely different, not-comparable number, "
                    "not a mismatch."
                ),
            }

        return dict(
            experiment_id=experiment_id, as_of_date=as_of_date.isoformat(), evaluable=True,
            target_metric=reg.get("target_metric"), hypothesis=reg.get("hypothesis"),
            treatment_arm_value=treat_value, control_arm_value=control_value,
            n_cells_total=n_cells_total, n_cells_resolved=n_cells_resolved,
            cell_results=cells_df.to_dict(orient="records"),
            pooled_group_results=pooled_df[pooled_df["scope"] == "pooled_group"].to_dict(orient="records"),
            pooled_all=pooled_stat,
            power_context=power_ctx,
            guardrails=guardrails,
            registry_published_result=registry_published,
            recomputed_result=recomputed,
            reproduction_check=reproduction_check,
        )
    finally:
        if owns_con:
            con.close()


# ==========================================================================
# 5. Registry / methodology governance -- structural completeness check,
#    fully general over dim_experiment's own schema. No adapter needed:
#    this only asks "is the definition well-formed and does a real
#    population back it up," never "what does the outcome mean."
# ==========================================================================

_REQUIRED_TEXT_FIELDS = [
    "hypothesis", "population_definition", "treatment_definition",
    "control_definition", "assignment_mechanism", "target_metric",
    "guardrail_metrics", "status",
]


def _is_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def check_registry_completeness(as_of_date: date = None, registry_df: pd.DataFrame = None,
                                 assignment_df: pd.DataFrame = None, con=None) -> pd.DataFrame:
    """One row per experiment_id: does it carry a complete, well-formed
    definition -- a stated hypothesis, target metric, guardrail metric(s),
    real treatment/control definitions, a stated assignment mechanism, a
    real effect-size target, AND a genuine two-armed population actually
    present in fact_experiment_assignment (not just a definition on paper)?
    Same discipline analytics/data_quality_governance.py applies to the
    metric tree, generalized to dim_experiment's own schema. Pass
    registry_df/assignment_df directly (bypassing the database) for
    synthetic/known-answer testing -- see
    run_synthetic_registry_completeness_test()."""
    owns_con = con is None and (registry_df is None or assignment_df is None)
    con = con or (_connect() if owns_con else None)
    try:
        if registry_df is None:
            registry_df = load_experiment_registry(as_of_date or date(2999, 1, 1), con=con)

        rows = []
        for _, r in registry_df.iterrows():
            missing = [f for f in _REQUIRED_TEXT_FIELDS if _is_blank(r.get(f))]
            has_effect_size = not _is_blank(r.get("designed_effect_size"))
            if not has_effect_size:
                missing.append("designed_effect_size")

            if assignment_df is not None:
                exp_assignment = assignment_df[assignment_df["experiment_id"] == r["experiment_id"]]
            elif con is not None:
                exp_assignment = con.execute(
                    "select arm from main_marts.fact_experiment_assignment where experiment_id = ?",
                    [r["experiment_id"]],
                ).df()
            else:
                exp_assignment = pd.DataFrame()
            arm_counts = (
                exp_assignment["arm"].value_counts().to_dict() if len(exp_assignment) else {}
            )
            has_two_real_arms = len(arm_counts) >= 2 and all(v > 0 for v in arm_counts.values())
            if not has_two_real_arms:
                missing.append("real_treatment_and_control_population")

            rows.append({
                "experiment_id": r["experiment_id"],
                "missing_fields": missing,
                "arm_counts": arm_counts,
                "is_complete": len(missing) == 0,
            })
        return pd.DataFrame(rows)
    finally:
        if owns_con and con is not None:
            con.close()


def run_synthetic_registry_completeness_test() -> dict:
    """Known-answer test, same discipline as data_quality_governance.py's
    run_synthetic_violation_tests(): a hand-built, fully-specified
    synthetic registration must pass, and a hand-built, deliberately
    incomplete one (missing guardrail_metrics, an empty control_definition,
    and an assignment population with no real control arm) must be flagged
    incomplete, by exactly those named reasons -- not just a generic
    fail."""
    results = []

    def _case(name, expected_pass, actual_pass, detail=""):
        results.append({
            "scenario": name, "expected_pass": expected_pass,
            "actual_pass": bool(actual_pass), "matches_expectation": bool(actual_pass) == expected_pass,
            "detail": detail,
        })

    clean_registry = pd.DataFrame([{
        "experiment_id": "EXP-TEST-CLEAN", "experiment_name": "Synthetic clean registration",
        "hypothesis": "Widget color changes signup rate.",
        "population_definition": "Visitors to the pricing page.",
        "treatment_definition": "Shown the blue widget.",
        "control_definition": "Shown the current gray widget.",
        "assignment_mechanism": "Randomized 50/50 at session start.",
        "target_metric": "signup_rate", "guardrail_metrics": "bounce_rate does not increase",
        "designed_effect_size": 0.10, "status": "running",
    }])
    clean_assignment = pd.DataFrame({
        "experiment_id": ["EXP-TEST-CLEAN"] * 4,
        "arm": ["treatment", "treatment", "control", "control"],
    })

    broken_registry = pd.DataFrame([{
        "experiment_id": "EXP-TEST-BROKEN", "experiment_name": "Synthetic broken registration",
        "hypothesis": "Widget color changes signup rate.",
        "population_definition": "Visitors to the pricing page.",
        "treatment_definition": "Shown the blue widget.",
        "control_definition": "",  # blank -- missing control population definition
        "assignment_mechanism": "Randomized 50/50 at session start.",
        "target_metric": "signup_rate",
        "guardrail_metrics": None,  # missing guardrail metric entirely
        "designed_effect_size": 0.10, "status": "running",
    }])
    broken_assignment = pd.DataFrame({
        "experiment_id": ["EXP-TEST-BROKEN"] * 4,
        "arm": ["treatment", "treatment", "treatment", "treatment"],  # no real control population
    })

    clean_result = check_registry_completeness(
        registry_df=clean_registry, assignment_df=clean_assignment
    ).iloc[0]
    broken_result = check_registry_completeness(
        registry_df=broken_registry, assignment_df=broken_assignment
    ).iloc[0]

    _case("clean_synthetic_registration_passes", True, clean_result["is_complete"],
          "Hand-built registration: every required field filled, a real two-armed population.")
    _case("broken_synthetic_registration_flagged_incomplete", False, broken_result["is_complete"],
          f"missing_fields={broken_result['missing_fields']}")
    _case("broken_flags_missing_control_definition", True,
          "control_definition" in broken_result["missing_fields"])
    _case("broken_flags_missing_guardrail_metrics", True,
          "guardrail_metrics" in broken_result["missing_fields"])
    _case("broken_flags_no_real_control_population", True,
          "real_treatment_and_control_population" in broken_result["missing_fields"])

    all_pass = all(r["matches_expectation"] for r in results)
    return {"results": results, "all_pass": all_pass, "n_scenarios": len(results)}


# ==========================================================================
# 6. Orchestration, persistence, and reporting
# ==========================================================================

def run_build_time_validation(as_of_date: date, log: bool = True, write_report: bool = True) -> dict:
    """End-to-end run: evaluate_experiment() applied to EXP-0001 (the
    reproduction-against-marketing_attribution.py check),
    check_registry_completeness() applied to the real dim_experiment
    catalog, and run_synthetic_registry_completeness_test()'s known-answer
    pair. Logs scalar summary metrics to fact_model_performance_history via
    analytics/model_performance.py's log_performance() when log=True, and
    writes a JSON + Markdown report to analytics/outputs/ when
    write_report=True -- the variable-width cell/guardrail tables don't fit
    that log's flat scalar grain and are the structured detail recorded in
    the report and in docs/acme-corp-analytics-methods.md instead, per
    analytics-engineering-conventions' Persistence note."""
    con = _connect()
    try:
        evaluation = evaluate_experiment(EXP_MARKETING_HOLDOUT, as_of_date, con=con)
        registry_completeness = check_registry_completeness(as_of_date=as_of_date, con=con)
    finally:
        con.close()

    synthetic = run_synthetic_registry_completeness_test()

    repro_check = evaluation.get("reproduction_check", {})
    reproduction_applicable = bool(repro_check.get("applicable"))
    reproduces = repro_check.get("reproduces_published_result")  # True / False / None
    registry_all_complete = bool(registry_completeness["is_complete"].all()) if len(registry_completeness) else False

    # The reproduction check only counts toward checks_total/checks_passed
    # when it's applicable (as_of_date is the registry's own final resolved
    # checkpoint) -- see evaluate_experiment()'s reproduction_check note.
    # A non-final as_of_date run (e.g. the 2025-06-30 second checkpoint)
    # still exercises and reports the framework fully; it just has nothing
    # in the registry to reproduce against yet.
    if reproduction_applicable:
        checks_total = 3
        checks_passed = sum([bool(reproduces), registry_all_complete, synthetic["all_pass"]])
    else:
        checks_total = 2
        checks_passed = sum([registry_all_complete, synthetic["all_pass"]])

    pooled = evaluation.get("pooled_all", {})
    power_ctx = evaluation.get("power_context", {})
    guardrails = evaluation.get("guardrails", [])
    guardrails_passed = sum(1 for g in guardrails if g.get("passes"))

    summary = dict(
        checks_total=checks_total,
        checks_passed=checks_passed,
        all_checks_pass=(checks_passed == checks_total),
        experiments_registered=int(len(registry_completeness)),
        experiments_registry_complete=int(registry_completeness["is_complete"].sum()) if len(registry_completeness) else 0,
        reproduction_check_applicable=reproduction_applicable,
        reproduces_marketing_attribution_result=reproduces,
        recomputed_incremental_share_pooled=evaluation.get("recomputed_result", {}).get("measured_incremental_share_pooled"),
        recomputed_z_stat=evaluation.get("recomputed_result", {}).get("measured_z_stat"),
        abs_diff_incremental_share=evaluation.get("reproduction_check", {}).get("abs_diff_incremental_share"),
        abs_diff_z=evaluation.get("reproduction_check", {}).get("abs_diff_z"),
        n_cells_total=evaluation.get("n_cells_total"),
        n_cells_resolved=evaluation.get("n_cells_resolved"),
        n_control_resolved=pooled.get("n_control"),
        n_treatment_resolved=pooled.get("n_treatment"),
        achieved_power_at_designed_effect=power_ctx.get("achieved_power_at_designed_effect"),
        mde_at_80pct_power_incremental_share=power_ctx.get("mde_implied_incremental_share"),
        adequately_powered=power_ctx.get("adequately_powered"),
        guardrails_total=len(guardrails),
        guardrails_passed=guardrails_passed,
        synthetic_completeness_checks_total=synthetic["n_scenarios"],
        synthetic_completeness_checks_passed=sum(1 for r in synthetic["results"] if r["matches_expectation"]),
    )

    if log:
        for k, v in summary.items():
            if isinstance(v, bool):
                v = float(v)
            if isinstance(v, (int, float)):
                log_performance(_MODEL_NAME, as_of_date, k, float(v))

    result = dict(
        as_of_date=as_of_date.isoformat(),
        summary=summary,
        evaluation=evaluation,
        registry_completeness=registry_completeness.to_dict(orient="records"),
        synthetic_completeness_test=synthetic,
    )
    if write_report:
        _write_report(as_of_date, result)
    return result


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj


def _write_report(as_of_date: date, result: dict) -> None:
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    json_path = os.path.join(_OUTPUT_DIR, f"experimentation_platform_{as_of_date.isoformat()}.json")
    with open(json_path, "w") as f:
        json.dump(_jsonable(result), f, indent=2)

    s = result["summary"]
    ev = result["evaluation"]
    lines = []
    lines.append(f"# Testing / experimentation methodology & platform -- as of {as_of_date.isoformat()}")
    lines.append("")
    lines.append(
        "**Scope, stated plainly**: this project has exactly one real, catalogued, "
        "randomized experiment (`EXP-0001`) today. What's built here is the reusable "
        "evaluation framework, proven correct against that one known-correct case, and "
        "ready for the next registration via one new outcome adapter."
    )
    lines.append("")
    lines.append(
        f"This module's own correctness checks: {s['checks_passed']} of {s['checks_total']} pass "
        f"({'ALL PASS' if s['all_checks_pass'] else 'FAILURES PRESENT'})."
    )
    lines.append("")

    lines.append("## 1. Reproduction check -- does the general framework get the known-correct answer?")
    if s["reproduction_check_applicable"]:
        lines.append(
            f"Recomputed pooled incremental share: **{s['recomputed_incremental_share_pooled']:.6f}** "
            f"(published: {ev.get('registry_published_result', {}).get('result_value')}, "
            f"abs diff {s['abs_diff_incremental_share']:.6f})."
        )
        lines.append(
            f"Recomputed pooled z-statistic: **{s['recomputed_z_stat']:.4f}** "
            f"(published: {ev.get('registry_published_result', {}).get('result_z')}, "
            f"abs diff {s['abs_diff_z']:.4f})."
        )
        lines.append(f"Reproduces published result within rounding tolerance: **{s['reproduces_marketing_attribution_result']}**.")
    else:
        lines.append(
            f"Not applicable at this checkpoint -- the registry stores only the final resolved "
            f"read ({ev.get('registry_published_result', {}).get('result_as_of_date')}). This "
            f"checkpoint's own recomputed pooled incremental share is "
            f"**{s['recomputed_incremental_share_pooled']:.6f}** (z={s['recomputed_z_stat']:.4f}), "
            "reported for framework-robustness comparison across time, not as a reproduction claim."
        )
    lines.append(f"Cells: {s['n_cells_resolved']} of {s['n_cells_total']} fully resolved as of this checkpoint.")
    lines.append("")

    lines.append("## 2. Sample-size / power context")
    lines.append(
        f"Pooled fully-resolved arm sizes: {s['n_treatment_resolved']} treatment, "
        f"{s['n_control_resolved']} control. Achieved power to detect the registry's "
        f"designed effect size at these actual sizes: "
        f"**{s['achieved_power_at_designed_effect']:.4f}**. "
        f"Minimum detectable effect at 80% power (as an implied incremental share): "
        f"**{s['mde_at_80pct_power_incremental_share']:.4f}**. "
        f"Adequately powered: **{s['adequately_powered']}**."
    )
    lines.append("")

    lines.append("## 3. Guardrail-metric monitoring")
    lines.append(f"{s['guardrails_passed']} of {s['guardrails_total']} guardrails pass.")
    lines.append("")
    lines.append("| Guardrail | Observed | Threshold | Passes |")
    lines.append("|---|---|---|---|")
    for g in ev.get("guardrails", []):
        lines.append(f"| {g['guardrail_metric']} | {g['observed_value']} | {g['threshold']} | {g['passes']} |")
    lines.append("")

    lines.append("## 4. Registry / methodology governance")
    lines.append(
        f"{s['experiments_registry_complete']} of {s['experiments_registered']} registered "
        "experiment(s) have a complete, well-formed definition."
    )
    lines.append("")
    lines.append("| experiment_id | is_complete | missing_fields | arm_counts |")
    lines.append("|---|---|---|---|")
    for r in result["registry_completeness"]:
        lines.append(f"| {r['experiment_id']} | {r['is_complete']} | {r['missing_fields']} | {r['arm_counts']} |")
    lines.append("")

    lines.append("## 5. Registry-completeness known-answer test")
    lines.append(
        f"{s['synthetic_completeness_checks_passed']} of {s['synthetic_completeness_checks_total']} "
        "synthetic scenarios matched their expected outcome."
    )
    lines.append("")
    lines.append("| Scenario | Expected pass | Actual pass | Matches |")
    lines.append("|---|---|---|---|")
    for r in result["synthetic_completeness_test"]["results"]:
        lines.append(f"| {r['scenario']} | {r['expected_pass']} | {r['actual_pass']} | {r['matches_expectation']} |")
    lines.append("")

    lines.append("## 6. Cell-level results (EXP-0001)")
    lines.append("| channel | cell_quarter | n_treatment | k_treatment | rate_treatment | n_control | k_control | rate_control | incremental_share | z_stat | fully_resolved |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for c in ev.get("cell_results", []):
        lines.append(
            f"| {c.get('channel')} | {c.get('cell_quarter')} | {c.get('n_treatment')} | {c.get('k_treatment')} | "
            f"{c.get('rate_treatment'):.4f} | {c.get('n_control')} | {c.get('k_control')} | "
            f"{c.get('rate_control') if pd.notna(c.get('rate_control')) else 'n/a'} | "
            f"{c.get('incremental_share') if pd.notna(c.get('incremental_share')) else 'n/a'} | "
            f"{c.get('z_stat') if pd.notna(c.get('z_stat')) else 'n/a'} | {c.get('cell_fully_resolved')} |"
        )
    lines.append("")

    md_path = os.path.join(_OUTPUT_DIR, f"experimentation_platform_{as_of_date.isoformat()}.md")
    with open(md_path, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    primary = run_build_time_validation(date(2025, 12, 31))
    print(json.dumps(_jsonable(primary["summary"]), indent=2))

    secondary = run_build_time_validation(date(2025, 6, 30), log=True, write_report=True)
    print("--- second checkpoint (2025-06-30) ---")
    print(json.dumps(_jsonable(secondary["summary"]), indent=2))
