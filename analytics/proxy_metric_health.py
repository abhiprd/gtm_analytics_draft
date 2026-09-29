"""Proxy-metric health / analytics investment prioritization -- grain: one
governance-catalog run per as_of_date; a structural read over three
already-materialized sources, never a fitted model and never a raw mart --
docs/acme-corp-analytics-methods.md's own text (the drift-monitor-hook
catalog), analytics/variance_diagnostic.py's `_TREE` (live NOT_COMPUTABLE
tree coverage) and analytics/data_quality_governance.py's
`_METRIC_TREE_EDGES_STATIC` (live governance-edge status), cross-referenced
against data/model_performance_history.csv via analytics/model_performance.py
(the one named fact_* exception every Phase 4 module reads/writes directly,
per analytics-engineering-conventions).

Build spec item #15 (Wave 7, infrastructure/governance), explicitly named
"last by necessity -- not computable meaningfully until real history
accumulates" (build spec Section 8's Wave 7 description).

============================================================================
THE HEADLINE FINDING, STATED HERE RATHER THAN LEFT FOR A READER TO DISCOVER
============================================================================
This artifact does NOT build a time-series drift/decay tool. `check_
checkpoint_depth()` below is a hard, checkable reconciliation against
`data/model_performance_history.csv` (the sole record of what has actually
been logged) and it shows: every one of the 17 models with any logged
checkpoint has 1, 2 or 3 real checkpoints, spanning at most three real
dates (2025-06-30 / 2025-11-14-or-2025-11-30 / 2025-12-31, all inside one
development pass, not a monthly-recurring operational cadence). No genuine
drift or decay CLAIM is possible yet for anything in this project -- a
trend needs more than 1-3 points to be a trend rather than a coin flip.
Fabricating additional historical checkpoints to make this artifact look
more capable than the data supports would violate this project's own
"don't fabricate to fill a gap" discipline (the same discipline the MMM/
incrementality entry demonstrates by reporting a weak, underpowered result
honestly rather than inventing confidence). So this artifact is a
GOVERNANCE CATALOG AND FRAMEWORK: it inventories every drift-monitor hook
this project's own build process has already identified (by artifact, by
name, by threshold), reconciles exactly how many readings each one
currently has (frequently zero -- see below), and ranks where the next
unit of analytics-engineering investment does the most good, using only
what is genuinely computable today. It becomes more useful as
`drift-monitor` actually runs on a recurring cadence and
`fact_model_performance_history` accumulates real history; it says so
honestly rather than overclaiming present usefulness.

A second, more specific finding, uncovered by actually reconciling the
catalog against the persisted log rather than assuming the doc's prose
was already wired up: at least three drift-monitor hooks this project's
own methods doc names as "genuinely worth watching" have ZERO persisted
readings at all, not merely a thin two -- `rep_productivity`'s
`cohort_recovery_against_raw_quantile`, `data_quality_governance`'s three
not-independently-random spot-check margins, and `deal_diagnostics`' per-
flag real-data firing counts. These are nearer-term, cheaper fixes than
"wait for more history": the metric already exists in each artifact's own
code, it simply was never passed to `log_performance()`. See
`find_unpersisted_hooks()`.

A third finding: `analytics/variance_diagnostic.py`'s NOT_COMPUTABLE
marking on `pipeline_generated` (and its three Layer-3 children) is
itself STALE, the same failure mode `mart_growth_bridge`'s own header
comment was already found to have (see the Marketing attribution & channel
mix entry in the methods doc) -- `analytics/data_quality_governance.py`'s
own governance-edge table already correctly marks the identical formula
`VALIDATED_ELSEWHERE`, computed and validated in
`analytics/marketing_attribution.py`. See `check_pipeline_generated_
staleness()`: this is a live, self-checking cross-reference, not a
one-time note that will itself go stale.

============================================================================
SHAPE AND WHAT "as_of_date" MEANS HERE
============================================================================
Structural/logic artifact per analytics-engineering-conventions'
"Structural/logic artifacts" category (the same category the variance-
diagnostic engine, segment migration, capacity planning, marketing
attribution and data quality governance all use): nothing here is fitted,
so no coefficient table, no AUC, no confusion matrix, no R^2/RMSE, no
calibration note -- their absence is deliberate, not pending. Model-type
selection and rationale: a deterministic catalog-and-reconciliation read
is the correct shape because every question this artifact answers
("what has this project already flagged as worth watching," "how many
readings does it actually have," "which data gap blocks the most
downstream evidence") has an exact, already-materialized answer -- fitting
anything to answer them would manufacture false precision the same way a
regression-based variance attribution would on the metric tree's own exact
identities (see the Variance-diagnostic engine entry's identical
reasoning).

`as_of_date` is accepted per convention and is genuinely point-in-time
for exactly one component: the checkpoint-reading reconciliation, which
filters data/model_performance_history.csv to `as_of_date_ <= as_of_date`
(a real, dated record) -- a caller who asks for an earlier as_of_date
genuinely sees fewer, or zero, checkpoints, which is itself an honest
illustration of how thin this history still is. The catalog of drift-
monitor hooks, the live NOT_COMPUTABLE tree-coverage read and the
governance-edge cross-reference are NOT point-in-time in that sense: they
are a structural read of the CURRENT state of this codebase and
docs/acme-corp-analytics-methods.md, because no versioned history of the
metric tree, the governance-edge table or the methods doc exists to query
"as of" a past date. Stated explicitly rather than fabricating pseudo-
point-in-time behavior for components that genuinely have none -- the
same honesty the point-in-time-discipline section at the top of the
methods doc asks every entry to observe.

No stochastic step exists anywhere in this module -- no sampling, no
simulation, no train/test split -- so no random seed applies, matching
analytics/segment_migration.py's, analytics/variance_diagnostic.py's,
analytics/data_quality_governance.py's and analytics/scenario_planning.py's
precedent.
"""
import csv
import json
import os
import re
from datetime import date

from . import data_quality_governance as dqg
from . import variance_diagnostic as vd
from .model_performance import log_performance, read_performance_history

_MODEL_NAME = "proxy_metric_health"
_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
_METHODS_DOC_PATH = os.path.join(
    os.path.dirname(__file__), "..", "docs", "acme-corp-analytics-methods.md"
)
_CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "model_performance_history.csv")

# Rule families a hook can fall under -- the two named in the methods
# doc's own general rules, plus a third, empirically necessary bucket (see
# `rule_family_notes()` for why the third bucket exists and is itself a
# finding, not a modeling convenience of this artifact's own invention).
RULE_MODEL_CALIBRATION = "model_calibration_accuracy_drift"
RULE_GROUNDING_INTEGRITY = "grounding_or_apparatus_integrity"
RULE_FIRING_RATE = "firing_rate_or_reuse_integrity"

# ============================================================================
# 1. THE DRIFT-MONITOR HOOK CATALOG
# ============================================================================
# Every entry below is extracted, not invented, from
# docs/acme-corp-analytics-methods.md's own text -- one artifact, by name,
# per hook, with the exact condition/threshold the doc states and a short
# verbatim `doc_anchor` substring used by `verify_hooks_trace_to_doc()`
# below to confirm the hook still traces to real text in the doc (catches
# this catalog itself going stale if the doc is edited later without this
# module being updated -- the same discipline
# analytics/marketing_attribution.py's and analytics/variance_diagnostic.py's
# own stale-comment findings argue for applying here).
#
# `persisted_metric_names`: the metric_name string(s) that would carry this
# hook's actual reading(s) in fact_model_performance_history, per the
# artifact's own Persistence paragraph. Left as () where the artifact's own
# doc names the series as "worth watching" but its Persistence paragraph
# does not actually log it -- a real, checkable, currently-zero-readings
# case, not an estimate (see `find_unpersisted_hooks()`).
DRIFT_HOOK_CATALOG = [
    dict(
        hook_id="health_score_auc",
        artifact="account_health_score",
        rule_family=RULE_MODEL_CALIBRATION,
        persisted_metric_names=("auc_holdout",),
        condition="AUC below 0.65 for 2 consecutive monthly checkpoints",
        doc_anchor="AUC below 0.65 for 2 consecutive monthly checkpoints",
    ),
    dict(
        hook_id="segment_migration_firmographic_rescore_share",
        artifact="segment_migration_analysis",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=(
            "pct_firmographic_rescore_overall",
            "pct_firmographic_rescore_smb_to_commercial",
            "pct_firmographic_rescore_commercial_to_enterprise",
        ),
        condition="firmographic_rescore share falls below its 10% floor, overall or within either segment pair, for 2 consecutive checkpoints",
        doc_anchor="the firmographic-rescore share floor is the one worth actually watching",
    ),
    dict(
        hook_id="marketing_mix_shift_tvd",
        artifact="marketing_attribution",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=("first_to_last_mix_shift_tvd",),
        condition="collapses toward its floor -> the multi-touch apparatus has stopped distinguishing anything",
        doc_anchor="`first_to_last_mix_shift_tvd`",
    ),
    dict(
        hook_id="marketing_channel_switch_share",
        artifact="marketing_attribution",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=("channel_switch_share",),
        condition="collapses toward its floor -> the multi-touch apparatus has stopped distinguishing anything",
        doc_anchor="`channel_switch_share`",
    ),
    dict(
        hook_id="marketing_measured_incremental_share_pooled",
        artifact="marketing_attribution",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=("measured_incremental_share_pooled",),
        condition="drifts outside 0.45-0.85 -> the holdout cells have stopped functioning as a control",
        doc_anchor="`measured_incremental_share_pooled`**: drifting outside 0.45",
    ),
    dict(
        hook_id="forecast_ml_calibration_gap",
        artifact="forecast",
        rule_family=RULE_MODEL_CALIBRATION,
        persisted_metric_names=("ml_calibration_gap",),
        condition="outside +/-0.05",
        doc_anchor="`ml_calibration_gap` outside **±0.05**",
    ),
    dict(
        hook_id="forecast_ml_auc_ratio_vs_leak_proof_baseline",
        artifact="forecast",
        rule_family=RULE_MODEL_CALIBRATION,
        persisted_metric_names=("ml_auc_ratio_vs_leak_proof_baseline",),
        condition="above 1.15 (leakage alarm)",
        doc_anchor="`ml_auc_ratio_vs_leak_proof_baseline` above **1.15**",
    ),
    dict(
        hook_id="capacity_empirical_ramp_ratio_pooled",
        artifact="capacity_planning",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=("empirical_ramp_ratio_pooled",),
        condition="drifts outside 0.40-0.60 -> the 0.50 ramp-capacity discount no longer describes the data",
        doc_anchor="`empirical_ramp_ratio_pooled`**: if it drifted outside 0.40",
    ),
    dict(
        hook_id="capacity_ramped_baseline_attainment_pooled",
        artifact="capacity_planning",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=("ramped_baseline_attainment_pooled",),
        condition="drifts outside 0.70-1.30 -> quota and deal-closing supply have decoupled again",
        doc_anchor="`ramped_baseline_attainment_pooled`**: now that quota",
    ),
    dict(
        hook_id="dq_governance_metric_tree_edges_not_computable",
        artifact="data_quality_governance",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=("metric_tree_edges_not_computable",),
        condition="should only ever decrease; an increase means a mart regressed",
        doc_anchor="`metric_tree_edges_not_computable` (should only ever *decrease*",
    ),
    dict(
        hook_id="dq_governance_not_independently_random_spot_checks",
        artifact="data_quality_governance",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=(),  # confirmed zero -- see find_unpersisted_hooks()
        condition=(
            "a real narrowing of the win_probability gap/z, churn_probability median "
            "decline, or usage_growth ratio margins over time, even while still "
            "technically clearing its floor, is the leading indicator a generator or "
            "dbt change quietly weakened a causal relationship (CLAUDE.md's "
            "'independently-random columns are a bug' invariant) other artifacts depend on"
        ),
        doc_anchor=(
            "not-independently-random spot-check margins (`win_probability` gap/z, "
            "`churn_probability` median decline, `usage_growth` ratio)"
        ),
    ),
    dict(
        hook_id="playbook_triggers_firing_counts",
        artifact="automated_playbook_triggers",
        rule_family=RULE_FIRING_RATE,
        persisted_metric_names=(
            "triggers_fired_ingestion_without_completion",
            "triggers_fired_poc_pass_rate_below_threshold",
            "triggers_fired_post_close_underutilization",
        ),
        condition="a sudden collapse to near-zero on a rule whose real-data firing count has been stable",
        doc_anchor="each rule's `triggers_fired_<rule_id>` count",
    ),
    dict(
        hook_id="deal_diagnostics_flag_firing_counts",
        artifact="deal_diagnostics",
        rule_family=RULE_FIRING_RATE,
        persisted_metric_names=(),  # confirmed zero -- see find_unpersisted_hooks()
        condition="any flag's real-data firing count collapsing to exactly 0 on a checkpoint where it has previously fired",
        doc_anchor="any flag's real-data firing count collapsing to exactly 0 on a checkpoint where it has previously fired",
    ),
    dict(
        hook_id="deal_diagnostics_ml_auc",
        artifact="deal_diagnostics",
        rule_family=RULE_MODEL_CALIBRATION,
        persisted_metric_names=("auc_holdout_out_of_time",),
        condition="outside 0.60-0.85",
        doc_anchor="`auc_holdout_out_of_time` outside 0.60–0.85",
    ),
    dict(
        hook_id="deal_diagnostics_calibration_gap",
        artifact="deal_diagnostics",
        rule_family=RULE_MODEL_CALIBRATION,
        persisted_metric_names=("calibration_gap",),
        condition="outside +/-0.05",
        doc_anchor="`calibration_gap` outside ±0.05",
    ),
    dict(
        hook_id="rep_productivity_cohort_recovery",
        artifact="rep_productivity",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=(),  # confirmed zero -- see find_unpersisted_hooks()
        condition="cohort_recovery_against_raw_quantile's enrichment rate collapses toward 0%",
        doc_anchor="`cohort_recovery_against_raw_quantile`'s enrichment rate is the genuinely worth-watching series",
    ),
    dict(
        hook_id="rep_productivity_flag_firing_counts",
        artifact="rep_productivity",
        rule_family=RULE_FIRING_RATE,
        persisted_metric_names=(
            "reps_flagged_volume_constrained",
            "reps_flagged_volume_and_quality_constrained",
            "reps_flagged_engagement_quality_constrained",
            "reps_flagged_ramp_explained_on_par",
            "reps_flagged_on_par",
        ),
        condition="reps_flagged_<flag_name> collapsing to exactly 0 on a flag that has previously fired",
        doc_anchor="`reps_flagged_<flag_name>` collapsing to exactly 0",
    ),
    dict(
        hook_id="pricing_deal_size_drift",
        artifact="pricing_packaging_analytics",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=(
            "deal_size_pct_change_smb",
            "deal_size_pct_change_commercial",
            "deal_size_pct_change_enterprise",
        ),
        condition="+/-15% relative change vs. the prior trailing-12-month window, within a segment (mature/2024+ era only)",
        doc_anchor="Deal-size drift threshold: ±15% relative change",
    ),
    dict(
        hook_id="pricing_packaging_calibration",
        artifact="pricing_packaging_analytics",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=(
            "packaging_median_utilization_commercial",
            "packaging_median_utilization_enterprise",
        ),
        condition="median utilization outside +/-10 percentage points of EXPECTED_STEADY_STATE_UTILIZATION",
        doc_anchor="Packaging calibration reference: median utilization within ±10 percentage points",
    ),
    dict(
        hook_id="tam_icp_non_vacuousness_floors",
        artifact="tam_icp_opportunity_sizing",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=(
            "tier_acv_separation_ratio_tier1_tier2",
            "tier_acv_separation_ratio_tier2_tier3",
            "entry_tier_explained_share",
            "entry_tier_downgrade_anomaly_share",
        ),
        condition="a generator-integrity watch -- icp_fit_score is static, so these should be near-constant; real drift means a generator/mart change",
        doc_anchor="(`tier_acv_separation_ratio_tier1_tier2`",
    ),
    dict(
        hook_id="territory_coverage_index_whitespace",
        artifact="territory_coverage_routing",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=(
            "coverage_index_whitespace_apac",
            "coverage_index_whitespace_emea",
            "coverage_index_whitespace_latam",
            "coverage_index_whitespace_na_east",
            "coverage_index_whitespace_na_west",
        ),
        condition="a roster-integrity signal -- e.g. APAC's index rising above its 0.75 floor would mean the deliberately-injected imbalance was organically corrected",
        doc_anchor="(`coverage_index_whitespace_apac`",
    ),
    dict(
        hook_id="mmm_checks_passed",
        artifact="mmm_incrementality",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=("checks_passed",),
        condition="dropping to 0 of 3 for 2 consecutive checkpoints (already observed once, at 2025-06-30)",
        doc_anchor="`checks_passed`** dropping to 0 of 3 for 2 consecutive checkpoints",
    ),
    dict(
        hook_id="mmm_vif_log_spend_with_trend",
        artifact="mmm_incrementality",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=("vif_log_spend_with_trend",),
        condition="pooled VIF exceeding 15 (roughly 2x the 7.42 observed at 2025-12-31)",
        doc_anchor="`vif_log_spend_with_trend`** (pooled) exceeding 15",
    ),
    dict(
        hook_id="mmm_gap_vs_holdout",
        artifact="mmm_incrementality",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=("gap_vs_holdout_paid", "gap_vs_holdout_community"),
        condition="watched, not gated -- a future checkpoint's movement (gap narrowing or widening) is itself the observable",
        doc_anchor="**`gap_vs_holdout_{paid,community}`** is watched but not gated",
    ),
    dict(
        hook_id="retention_cohort_annualized_logo_retention_benchmark",
        artifact="retention_expansion_cohort_analytics",
        rule_family=RULE_GROUNDING_INTEGRITY,
        persisted_metric_names=(
            "implied_annual_logo_retention_smb",
            "implied_annual_logo_retention_commercial",
            "implied_annual_logo_retention_enterprise",
        ),
        condition="a segment's annualized figure drifts outside its +/-5pp benchmark buffer as new cohorts age into the 36-month mark",
        doc_anchor="(`implied_annual_logo_retention_smb`",
    ),
    dict(
        hook_id="scenario_planning_baseline_self_check",
        artifact="scenario_planning",
        rule_family=RULE_FIRING_RATE,
        persisted_metric_names=("baseline_self_check_nodes_passed",),
        condition="a drop against its own _total would mean this module's reuse of vd's baseline computation has silently diverged",
        doc_anchor="`baseline_self_check_nodes_passed` against `_total`",
    ),
]

# Artifacts whose own methods-doc entry explicitly states drift monitoring
# does not apply -- catalogued so a reader can tell "deliberately not
# monitored" apart from "not yet catalogued."
NOT_DRIFT_MONITORED_ARTIFACTS = [
    dict(
        artifact="variance_diagnostic_engine",
        reason="Structural/logic artifact with no calibration to drift; its own scalars exist to check a future build against this one, not to track decay over time.",
        doc_anchor="**Not subject to drift monitoring.**",
    ),
    dict(
        artifact="weekly_executive_readout",
        reason="Pure assembly of already-validated artifacts' outputs with no arithmetic of its own; its three checks are binary structural invariants with no sampling variance.",
        doc_anchor="### Drift monitoring — not applicable",
    ),
]

# The one Wave 7 sibling artifact this build does not touch (built in
# parallel, per task scope) but whose methods-doc entry is still TBD --
# catalogued for completeness of "which artifacts have zero drift-monitor
# hooks at all because they don't exist yet."
NOT_YET_BUILT_ARTIFACTS = [
    dict(
        artifact="segment_lead_scoring_model",
        reason="Build spec item #11 (Wave 7). Methods doc entry still TBD -- inputs, target and drift threshold all unset. Not built by this artifact; being built in parallel by a sibling agent.",
        doc_anchor="## Segment/lead scoring model",
    ),
]


def verify_hooks_trace_to_doc(methods_doc_path: str = None) -> dict:
    """Correctness check #1: does every catalogued hook (and every
    not-monitored / not-yet-built entry) actually trace to real text in
    docs/acme-corp-analytics-methods.md, by exact substring match on its
    `doc_anchor`? Guards against this catalog itself drifting away from
    the doc it was extracted from. Returns {passed, results, n_total,
    n_passed}."""
    path = methods_doc_path or _METHODS_DOC_PATH
    with open(path, encoding="utf-8") as f:
        text = f.read()
    all_entries = (
        [dict(kind="hook", **h) for h in DRIFT_HOOK_CATALOG]
        + [dict(kind="not_monitored", **e) for e in NOT_DRIFT_MONITORED_ARTIFACTS]
        + [dict(kind="not_yet_built", **e) for e in NOT_YET_BUILT_ARTIFACTS]
    )
    results = []
    for entry in all_entries:
        found = entry["doc_anchor"] in text
        results.append(dict(
            id=entry.get("hook_id", entry.get("artifact")),
            kind=entry["kind"],
            artifact=entry["artifact"],
            doc_anchor=entry["doc_anchor"],
            traces_to_doc=found,
        ))
    n_passed = sum(1 for r in results if r["traces_to_doc"])
    return dict(passed=n_passed == len(results), n_total=len(results), n_passed=n_passed, results=results)


# ============================================================================
# 2. DATA-GAP / INVESTMENT-PRIORITIZATION CATALOG
# ============================================================================
# Cost tiers, from cheapest to most expensive to close -- curated judgment
# (the tier assignment is not itself derivable from the tree), but every
# node key named below is cross-checked live against
# analytics/variance_diagnostic.py's real, current `_TREE` by
# `verify_data_gap_keys_are_live()`: if a cited key's computability has
# changed (closed, renamed, or removed) since this catalog was curated,
# that check fails loudly rather than silently reporting a stale claim.
TIER_ALREADY_COMPUTED_ELSEWHERE = "A_already_computed_elsewhere_wiring_only"
TIER_MART_EXPOSURE_ONLY = "B_phase2_mart_exposure_only"
TIER_PHASE4_CODE_OR_DESIGN_FIX = "C_phase4_code_or_design_fix"
TIER_GENUINE_NEW_PHASE1_DATA = "D_genuine_new_phase1_data"
TIER_NOT_ACTIONABLE = "E_not_a_real_gap"

# One entry per NOT_COMPUTABLE root subtree in vd._TREE (a NOT_COMPUTABLE
# node whose parent is COMPUTABLE/PARTIAL or is a pillar -- i.e. the
# highest point at which the gap starts). `node_key` is looked up live
# against vd._TREE at call time; nothing about a node's existence,
# computability or gap_note is hardcoded here beyond the curated `tier`
# and `rationale` judgment.
DATA_GAP_ROOTS = [
    dict(
        node_key="pipeline_generated",
        tier=TIER_ALREADY_COMPUTED_ELSEWHERE,
        rationale=(
            "STALE marking, not a real gap. analytics/marketing_attribution.py "
            "already computes this exact formula from marts (fact_leads, "
            "dim_campaign, fact_campaign_engagement_events) and validates it "
            "(reconcile_pipeline_generated_identity, <=1e-9 tolerance, passing at "
            "both checkpoints) -- analytics/data_quality_governance.py's own "
            "governance-edge table already marks the identical formula "
            "VALIDATED_ELSEWHERE (edge_id pipeline_generated_channel_formula). "
            "Closing this needs no new data and no new mart -- only wiring "
            "analytics/variance_diagnostic.py's pipeline_generated/organic_content/"
            "paid/community_events nodes to call into marketing_attribution.py's "
            "already-validated functions, the same reuse pattern "
            "analytics/mmm_incrementality.py and analytics/scenario_planning.py "
            "already establish for borrowing another Phase 4 module's logic. "
            "Restores New Logo's first-ever real Layer-3 evidence anywhere in the "
            "tree -- today 0 of 32 Layer-3 leaves are computable from any mart."
        ),
    ),
    dict(
        node_key="discount_rate_vs_list",
        tier=TIER_MART_EXPOSURE_ONLY,
        rationale=(
            "Already named and scoped in the Pricing/packaging analytics methods-"
            "doc entry as a separate, already-flagged piece of work: "
            "fact_opportunities is confirmed to expose list_price/discount_rate/"
            "loss_reason; the fix is a Phase 2 mart change (expose the columns "
            "through a mart), not new Phase 1 data."
        ),
    ),
    dict(
        node_key="deal_size_trend_within_band",
        tier=TIER_MART_EXPOSURE_ONLY,
        rationale="Same already-scoped fix as discount_rate_vs_list -- see that entry.",
    ),
    dict(
        node_key="loss_reason_mix",
        tier=TIER_MART_EXPOSURE_ONLY,
        rationale="Same already-scoped fix as discount_rate_vs_list -- loss_reason is the field this leaf needs.",
    ),
    dict(
        node_key="stage_to_stage_conversion",
        tier=TIER_MART_EXPOSURE_ONLY,
        rationale=(
            "Needs fact_opportunity_stage_history's stage-transition detail exposed "
            "through a mart -- the raw fact already exists (fact_opportunity_stage_"
            "history), it is simply outside the mart_*-only read scope Phase 4 code "
            "operates under. Same root cause as poc_pass_rate, renewal_win_rate and "
            "churn_reason_category below -- one mart change could close several of "
            "these at once."
        ),
    ),
    dict(
        node_key="poc_pass_rate",
        tier=TIER_MART_EXPOSURE_ONLY,
        rationale="Same stage-history mart-exposure gap as stage_to_stage_conversion.",
    ),
    dict(
        node_key="renewal_win_rate",
        tier=TIER_MART_EXPOSURE_ONLY,
        rationale=(
            "Same opportunity-detail mart-exposure gap. Blocks its own two Layer-3 "
            "children (time_to_respond_churn_risk_flag, loud_vs_silent_churn_mix) "
            "as well -- closing the parent mart gap would also need those two "
            "leaves' own source events (a churn-risk-flag timestamp, an AM response "
            "timestamp) which are a separate, smaller gap on top."
        ),
    ),
    dict(
        node_key="churn_reason_category",
        tier=TIER_MART_EXPOSURE_ONLY,
        rationale="Same opportunity-detail (loss_reason) mart-exposure gap as the other opportunity-mart leaves.",
    ),
    dict(
        node_key="overage_realization",
        tier=TIER_MART_EXPOSURE_ONLY,
        rationale=(
            "fact_committed_vs_utilized_monthly already exists and mart_efficiency "
            "already consumes it internally (exposing only a derived utilisation-"
            "haircut margin) -- realised overage billing itself just needs its own "
            "mart exposure, not new raw data."
        ),
    ),
    dict(
        node_key="workflow_chain_underutilization",
        tier=TIER_MART_EXPOSURE_ONLY,
        rationale=(
            "fact_workflow_chain_events already exists but is not exposed through "
            "any mart_* table. Closing this one mart gap would also close its three "
            "Layer-3 children (ingestion_without_completion_rate, mid_chain_"
            "abandonment, full_vs_partial_chain_share) -- notably, "
            "analytics/playbook_triggers.py's own ingestion_without_completion rule "
            "already computes a version of this signal for its own purpose, a "
            "second real precedent (alongside pipeline_generated) that this "
            "project's own other artifacts have already done some of this work."
        ),
    ),
    dict(
        node_key="account_health_score",
        tier=TIER_PHASE4_CODE_OR_DESIGN_FIX,
        rationale=(
            "No new data and no new mart needed -- mart_account_health already "
            "carries everything. analytics/health_score.py's score_accounts() "
            "defines its scored population by customer_status = 'Active' (a "
            "final-status field), which biases a historical trailing series. "
            "Gating the population on churn_month > month instead (a code change "
            "to health_score.py, out of the variance-diagnostic engine's own scope "
            "per that entry's explicit note) would close this node and its four "
            "Layer-3 children -- the single largest node count closed by a pure "
            "code fix with zero new data anywhere in this catalog."
        ),
    ),
    dict(
        node_key="magic_number",
        tier=TIER_GENUINE_NEW_PHASE1_DATA,
        rationale=(
            "No rep-cost/comp data exists anywhere in the raw sources. This is the "
            "single highest-node-count gap in the whole tree (5 nodes) and the "
            "only gap that blocks an entire Layer-1 metric outright, alongside "
            "am_efficiency below -- together the only two of the tree's 11 Layer-1 "
            "nodes with zero computable actual. Needs a genuine new Phase 1 "
            "generator (rep comp/cost by role/segment/month), the most expensive "
            "tier in this catalog."
        ),
    ),
    dict(
        node_key="am_efficiency",
        tier=TIER_GENUINE_NEW_PHASE1_DATA,
        rationale="Same rep-cost/comp gap as magic_number -- the other of the tree's two entirely-NOT_COMPUTABLE Layer-1 nodes.",
    ),
    dict(
        node_key="marketing_sales_handoff_quality",
        tier=TIER_GENUINE_NEW_PHASE1_DATA,
        rationale=(
            "Needs an MQL/SAL lifecycle-stage field on the lead funnel. Verified "
            "directly against dbt/models/marts/facts/fact_leads.sql: the mart "
            "carries lead_id/account_id/channel/created_date/converted_date/"
            "is_converted/lead_score/days_to_conversion and nothing else -- no "
            "stage/status field of any kind, so this is a genuine gap and NOT the "
            "same stale-marking case pipeline_generated is (marketing_attribution.py "
            "computes Pipeline generated from exactly these columns; it does not "
            "and structurally cannot compute an MQL->SAL acceptance rate from them)."
        ),
    ),
    dict(
        node_key="brand_awareness",
        tier=TIER_GENUINE_NEW_PHASE1_DATA,
        rationale=(
            "No web-traffic, branded-search or competitive-intelligence source "
            "exists anywhere in this project. Lowest actionable priority of the "
            "four-node-or-larger gaps despite its node count, because the tree "
            "itself excludes Brand & awareness from every sibling ranking (the "
            "one deliberate non-additive leading-indicator exception, per "
            "CLAUDE.md) -- closing it would add descriptive detail, never change "
            "a drill-down outcome."
        ),
    ),
    dict(
        node_key="wallet_share_progression",
        tier=TIER_GENUINE_NEW_PHASE1_DATA,
        rationale=(
            "Needs an estimate of an account's non-Acme workflow footprint (the "
            "wallet-share denominator) -- nothing in this project's raw data or "
            "marts estimates it. This is Expansion consumption revenue's ONLY "
            "Layer-2 driver (0 of 2 computable per the variance-diagnostic "
            "engine's own coverage table, once overage_realization above is also "
            "counted) -- closing this is what it would take for the Expansion "
            "branch to produce any drill-down evidence at all when it breaches "
            "variance, which today it structurally cannot."
        ),
    ),
    dict(
        node_key="rep_capacity_ramp_mix",
        tier=TIER_MART_EXPOSURE_ONLY,
        rationale=(
            "dim_reps and int_rep_capacity_periods already exist with the needed "
            "ramp/quota detail; win rate cut by rep ramp status just needs a mart "
            "that joins deal ownership to that detail. Distinct root cause from "
            "the opportunity-detail group above -- a different mart, not the "
            "same fix."
        ),
    ),
    dict(
        node_key="time_to_first_integration",
        tier=TIER_GENUINE_NEW_PHASE1_DATA,
        rationale="No integration/first-successful-run event exists anywhere in the raw data; fact_usage_monthly is monthly grain with no first-Action timestamp.",
    ),
    dict(
        node_key="quickstart_docs_engagement_rate",
        tier=TIER_GENUINE_NEW_PHASE1_DATA,
        rationale="The build spec's content_engagement source was never generated at all.",
    ),
    dict(
        node_key="cohort_comparison",
        tier=TIER_GENUINE_NEW_PHASE1_DATA,
        rationale="No mart exposes an account-type x usage-cycle cohort baseline; nothing in the raw data currently supports deriving one either.",
    ),
    dict(
        node_key="account_specific_baseline_deviation",
        tier=TIER_NOT_ACTIONABLE,
        rationale=(
            "Not a real gap: the node's own gap_note states it is already folded "
            "into its parent's computation (usage_dip_breadth IS this leaf, "
            "aggregated) -- surfacing it separately would restate the parent, not "
            "add evidence. No investment closes this because there is nothing "
            "distinct left to compute."
        ),
    ),
]


def live_not_computable_gaps() -> list:
    """Live read of every NOT_COMPUTABLE node in analytics/variance_diagnostic.py's
    `_TREE`, by layer -- always the artifact's current state, never a
    snapshot, since this walks `vd._TREE` directly rather than a copy."""
    return [
        dict(key=k, label=n.label, layer=n.layer, parent_key=n.parent_key,
             pillar=n.pillar, gap_note=n.gap_note)
        for k, n in vd._TREE.items()
        if n.computability == vd.NOT_COMPUTABLE
    ]


def _children_map():
    m = {}
    for k, n in vd._TREE.items():
        if n.parent_key:
            m.setdefault(n.parent_key, []).append(k)
    return m


def _subtree_not_computable_count(node_key: str, children: dict) -> int:
    n = vd._TREE[node_key]
    total = 1 if n.computability == vd.NOT_COMPUTABLE else 0
    for c in children.get(node_key, []):
        total += _subtree_not_computable_count(c, children)
    return total


def verify_data_gap_keys_are_live() -> dict:
    """Correctness check #2: does every node_key cited in DATA_GAP_ROOTS
    still exist in vd._TREE and still carry computability == NOT_COMPUTABLE
    (except account_specific_baseline_deviation, which is deliberately
    catalogued as TIER_NOT_ACTIONABLE and is still expected to be
    NOT_COMPUTABLE in the live tree -- its tier reflects "not worth fixing",
    not "already fixed")? A key that has closed, been renamed, or vanished
    since this catalog was curated fails this check loudly rather than the
    catalog silently reporting a stale claim."""
    results = []
    for root in DATA_GAP_ROOTS:
        key = root["node_key"]
        exists = key in vd._TREE
        still_not_computable = exists and vd._TREE[key].computability == vd.NOT_COMPUTABLE
        results.append(dict(node_key=key, exists_live=exists, still_not_computable=still_not_computable))
    n_passed = sum(1 for r in results if r["exists_live"] and r["still_not_computable"])
    return dict(passed=n_passed == len(results), n_total=len(results), n_passed=n_passed, results=results)


def rank_data_gap_priorities() -> list:
    """Ranks DATA_GAP_ROOTS by (a) cost tier, cheapest first, then (b) live
    downstream node count blocked, largest first. This is the artifact's
    actual investment-prioritization output: a gap that is both cheap to
    close AND blocks many downstream leaves/artifacts outranks one that is
    either expensive or narrow. `blocked_node_count` is always computed
    live against vd._TREE, never hardcoded."""
    children = _children_map()
    tier_order = {
        TIER_ALREADY_COMPUTED_ELSEWHERE: 0,
        TIER_MART_EXPOSURE_ONLY: 1,
        TIER_PHASE4_CODE_OR_DESIGN_FIX: 2,
        TIER_GENUINE_NEW_PHASE1_DATA: 3,
        TIER_NOT_ACTIONABLE: 4,
    }
    ranked = []
    for root in DATA_GAP_ROOTS:
        key = root["node_key"]
        node = vd._TREE[key]
        blocked = _subtree_not_computable_count(key, children)
        blocks_full_layer1 = node.layer == 1
        ranked.append(dict(
            node_key=key,
            label=node.label,
            layer=node.layer,
            parent_key=node.parent_key,
            tier=root["tier"],
            blocked_node_count=blocked,
            blocks_full_layer1_metric=blocks_full_layer1,
            rationale=root["rationale"],
        ))
    ranked.sort(key=lambda r: (tier_order[r["tier"]], -r["blocked_node_count"]))
    return ranked


def check_pipeline_generated_staleness() -> dict:
    """Live, self-checking cross-reference behind this artifact's third
    headline finding: analytics/variance_diagnostic.py marks
    `pipeline_generated` (and its 3 Layer-3 children) NOT_COMPUTABLE, while
    analytics/data_quality_governance.py's own governance-edge table marks
    the identical formula VALIDATED_ELSEWHERE, computed by
    analytics/marketing_attribution.py. Both facts are re-checked live each
    run -- if either module changes (the staleness gets fixed, or the DQ
    edge status changes), this reports the new, current state rather than
    a frozen claim."""
    vd_node = vd._TREE.get("pipeline_generated")
    vd_children = [k for k, n in vd._TREE.items() if n.parent_key == "pipeline_generated"]
    dqg_edge = next(
        (e for e in dqg._METRIC_TREE_EDGES_STATIC if e["edge_id"] == "pipeline_generated_channel_formula"),
        None,
    )
    vd_says_not_computable = vd_node is not None and vd_node.computability == vd.NOT_COMPUTABLE
    dqg_says_validated_elsewhere = dqg_edge is not None and dqg_edge["status"] == "VALIDATED_ELSEWHERE"
    return dict(
        vd_node_computability=vd_node.computability if vd_node else None,
        vd_children_still_not_computable=[
            k for k in vd_children if vd._TREE[k].computability == vd.NOT_COMPUTABLE
        ],
        dqg_edge_status=dqg_edge["status"] if dqg_edge else None,
        is_stale_marking=vd_says_not_computable and dqg_says_validated_elsewhere,
    )


# ============================================================================
# 3. CHECKPOINT-DEPTH RECONCILIATION -- the headline finding, made exact
# ============================================================================

def _read_csv_rows_independently():
    """A second, independent read of data/model_performance_history.csv,
    deliberately NOT reusing analytics/model_performance.py's
    read_performance_history() -- used only by
    verify_checkpoint_reconciliation() below to cross-check that function's
    output against a from-scratch parse of the same file, the same
    two-independent-implementations discipline this project's other
    reconciliation checks use (e.g. segment_migration's growth-bridge
    reconciliation, forecast's rollup_ties_to_deal_detail)."""
    rows = []
    if not os.path.exists(_CSV_PATH):
        return rows
    with open(_CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        for row in reader:
            rows.append(dict(
                model_name=row[idx["model_name"]],
                as_of_date=row[idx["as_of_date"]],
                metric_name=row[idx["metric_name"]],
                metric_value=row[idx["metric_value"]],
            ))
    return rows


def checkpoint_counts_by_model(as_of_date: date) -> dict:
    """Every model_name in fact_model_performance_history, with the sorted,
    distinct as_of_date values logged for it at or before `as_of_date`
    (point-in-time: a checkpoint logged after `as_of_date` is not counted,
    the one place this artifact's `as_of_date` parameter genuinely changes
    the answer). This is the artifact's central evidentiary table -- the
    same rigor every other Phase 4 artifact in this project uses to state
    a sample size, applied here to the project's OWN model-performance
    bookkeeping rather than to business data."""
    rows = read_performance_history()
    by_model = {}
    for r in rows:
        if r["as_of_date"] > as_of_date.isoformat():
            continue
        by_model.setdefault(r["model_name"], set()).add(r["as_of_date"])
    return {
        model: dict(n_checkpoints=len(dates), as_of_dates=sorted(dates))
        for model, dates in sorted(by_model.items())
    }


def hook_reading_counts(as_of_date: date) -> list:
    """For every catalogued hook, how many distinct as_of_date checkpoints
    (at or before `as_of_date`) actually carry a logged value for each of
    its `persisted_metric_names` -- the exact reading count a real
    drift-monitor run would have to work with today, not an estimate. A
    hook whose persisted_metric_names is empty by catalog construction
    reports 0 without even querying the CSV (see
    find_unpersisted_hooks())."""
    rows = read_performance_history()
    results = []
    for hook in DRIFT_HOOK_CATALOG:
        per_metric = {}
        for metric_name in hook["persisted_metric_names"]:
            dates = sorted({
                r["as_of_date"] for r in rows
                if r["model_name"] == hook["artifact"]
                and r["metric_name"] == metric_name
                and r["as_of_date"] <= as_of_date.isoformat()
            })
            per_metric[metric_name] = dates
        max_readings = max((len(d) for d in per_metric.values()), default=0)
        results.append(dict(
            hook_id=hook["hook_id"],
            artifact=hook["artifact"],
            rule_family=hook["rule_family"],
            persisted_metric_names=hook["persisted_metric_names"],
            reading_dates_by_metric=per_metric,
            max_reading_count=max_readings,
        ))
    return results


def find_unpersisted_hooks(as_of_date: date) -> list:
    """The subset of catalogued hooks with ZERO actual readings as of
    `as_of_date` -- either because `persisted_metric_names` is empty by
    catalog construction (the metric was never wired into log_performance()
    at all, confirmed against the doc's own Persistence paragraph for that
    artifact) or because the CSV genuinely carries no row for it yet. This
    is a nearer-term, cheaper investment than 'wait for more history':
    each of these values already exists inside its artifact's own code at
    build time, it is simply never passed to log_performance()."""
    return [r for r in hook_reading_counts(as_of_date) if r["max_reading_count"] == 0]


def verify_checkpoint_reconciliation(as_of_date: date) -> dict:
    """Correctness check #3: does checkpoint_counts_by_model()'s per-model
    checkpoint count match an independent, from-scratch parse of the same
    CSV exactly -- a hard reconciliation, not an estimate, per the task's
    own bar. Any mismatch is a real bug in this module's counting logic,
    not a data question."""
    via_reader = checkpoint_counts_by_model(as_of_date)
    independent_rows = _read_csv_rows_independently()
    by_model_independent = {}
    for r in independent_rows:
        if r["as_of_date"] > as_of_date.isoformat():
            continue
        by_model_independent.setdefault(r["model_name"], set()).add(r["as_of_date"])
    mismatches = []
    all_models = set(via_reader) | set(by_model_independent)
    for model in sorted(all_models):
        a = set(via_reader.get(model, {}).get("as_of_dates", []))
        b = by_model_independent.get(model, set())
        if a != b:
            mismatches.append(dict(model=model, via_reader=sorted(a), via_independent_parse=sorted(b)))
    return dict(passed=len(mismatches) == 0, n_models_checked=len(all_models), mismatches=mismatches)


# ============================================================================
# 4. VALIDATION-MATURITY SUMMARY -- how much of this portfolio's own
#    thresholds have been independently confirmed vs. self-proposed
# ============================================================================
_ARTIFACT_SECTION_STOPLIST = {
    "Point-in-time discipline (applies to every entry below)",
    "Proxy-metric decoupling — general rule, applies to any Layer-3-to-Layer-2 relationship in the tree",
    "Drift review trigger — general rule",
    # Self-referential exclusion, found and fixed at build time, not a
    # convenience: this artifact's OWN methods-doc entry quotes both
    # 'PROPOSED, not yet confirmed' and 'CONFIRMED by
    # `analytics-model-validator`' verbatim, once each, while EXPLAINING
    # what this function searches for -- a naive scan over the whole doc
    # counts that meta-description as a real occurrence and silently
    # inflates both totals by one (caught by a build-time re-run showing
    # 2/15 instead of the correct 1/14). Excluded for the identical reason
    # the two general-rule sections above are excluded: this is the
    # artifact doing the counting, not an artifact being counted.
    "Proxy-metric health / analytics investment prioritization",
}


def validation_maturity_summary(methods_doc_path: str = None) -> list:
    """Splits docs/acme-corp-analytics-methods.md on its top-level `## `
    artifact headers and, per artifact, counts occurrences of 'PROPOSED,
    not yet confirmed' (a self-proposed threshold, still awaiting
    analytics-model-validator review) against 'CONFIRMED by
    `analytics-model-validator`' (a threshold that has actually been
    independently reviewed and confirmed). A structural text-scan of the
    doc's own language, not a statistical estimate -- the same kind of
    exact reconciliation this artifact applies to the checkpoint log."""
    path = methods_doc_path or _METHODS_DOC_PATH
    with open(path, encoding="utf-8") as f:
        text = f.read()
    sections = re.split(r"(?m)^## ", text)[1:]  # drop preamble before first ##
    results = []
    for section in sections:
        header = section.split("\n", 1)[0].strip()
        if header in _ARTIFACT_SECTION_STOPLIST:
            continue
        n_proposed = section.count("PROPOSED, not yet confirmed")
        n_confirmed = section.count("CONFIRMED by `analytics-model-validator`")
        results.append(dict(
            artifact_section=header,
            n_proposed_not_confirmed_mentions=n_proposed,
            n_confirmed_by_validator_mentions=n_confirmed,
        ))
    return results


# ============================================================================
# 5. BUILD-TIME VALIDATION, PERSISTENCE, REPORT
# ============================================================================

def run_build_time_validation(as_of_date: date, log: bool = True, write_report: bool = True) -> dict:
    """End-to-end run: the hook catalog with live reading-count
    reconciliation, the live NOT_COMPUTABLE data-gap ranking, the
    pipeline_generated staleness cross-reference, and the validation-
    maturity summary -- plus this module's own three correctness checks
    (hooks trace to doc text, cited gap keys are live, checkpoint counts
    reconcile against an independent CSV parse). Logs scalar summary
    counts to fact_model_performance_history via
    analytics/model_performance.py's log_performance() when log=True, and
    writes a JSON + Markdown report to analytics/outputs/ when
    write_report=True -- the variable-width catalog/ranking tables don't
    fit that log's flat scalar grain and are the structured detail
    recorded in the report and in docs/acme-corp-analytics-methods.md
    instead, per analytics-engineering-conventions' Persistence note."""
    doc_trace = verify_hooks_trace_to_doc()
    gap_keys_live = verify_data_gap_keys_are_live()
    checkpoint_recon = verify_checkpoint_reconciliation(as_of_date)
    staleness = check_pipeline_generated_staleness()
    checkpoints = checkpoint_counts_by_model(as_of_date)
    readings = hook_reading_counts(as_of_date)
    unpersisted = find_unpersisted_hooks(as_of_date)
    gap_ranking = rank_data_gap_priorities()
    maturity = validation_maturity_summary()

    checkpoint_count_values = [v["n_checkpoints"] for v in checkpoints.values()]
    n_hooks_zero_readings = len(unpersisted)
    n_confirmed_artifacts = sum(1 for m in maturity if m["n_confirmed_by_validator_mentions"] > 0)
    n_proposed_artifacts = sum(1 for m in maturity if m["n_proposed_not_confirmed_mentions"] > 0)

    summary = dict(
        checks_total=3,
        checks_passed=sum([doc_trace["passed"], gap_keys_live["passed"], checkpoint_recon["passed"]]),
        hooks_cataloged=len(DRIFT_HOOK_CATALOG),
        hooks_traced_to_doc=doc_trace["n_passed"],
        hooks_with_zero_persisted_readings=n_hooks_zero_readings,
        not_drift_monitored_artifacts=len(NOT_DRIFT_MONITORED_ARTIFACTS),
        not_yet_built_artifacts=len(NOT_YET_BUILT_ARTIFACTS),
        models_with_any_checkpoint=len(checkpoints),
        min_checkpoints_across_models=min(checkpoint_count_values) if checkpoint_count_values else 0,
        max_checkpoints_across_models=max(checkpoint_count_values) if checkpoint_count_values else 0,
        data_gap_roots_cataloged=len(DATA_GAP_ROOTS),
        data_gap_roots_live_confirmed=gap_keys_live["n_passed"],
        pipeline_generated_stale_marking_confirmed=staleness["is_stale_marking"],
        artifacts_with_confirmed_threshold=n_confirmed_artifacts,
        artifacts_with_proposed_not_confirmed_threshold=n_proposed_artifacts,
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
        doc_trace_check=doc_trace,
        data_gap_keys_live_check=gap_keys_live,
        checkpoint_reconciliation_check=checkpoint_recon,
        pipeline_generated_staleness=staleness,
        checkpoint_counts_by_model=checkpoints,
        hook_reading_counts=readings,
        unpersisted_hooks=unpersisted,
        data_gap_ranking=gap_ranking,
        validation_maturity_summary=maturity,
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
    return obj


def _write_report(as_of_date: date, result: dict) -> None:
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    json_path = os.path.join(_OUTPUT_DIR, f"proxy_metric_health_{as_of_date.isoformat()}.json")
    with open(json_path, "w") as f:
        json.dump(_jsonable(result), f, indent=2)

    s = result["summary"]
    lines = []
    lines.append(f"# Proxy-metric health / analytics investment prioritization -- as of {as_of_date.isoformat()}")
    lines.append("")
    lines.append(
        "**Headline finding**: no genuine drift/decay claim is possible yet for "
        "anything in this project. Every model with any logged checkpoint has "
        f"between {s['min_checkpoints_across_models']} and "
        f"{s['max_checkpoints_across_models']} real checkpoints "
        f"({s['models_with_any_checkpoint']} models total) -- see "
        "'Checkpoint depth by model' below. This artifact is a governance "
        "catalog and framework, not a time-series drift tool; it becomes more "
        "useful as `drift-monitor` actually runs on a recurring cadence."
    )
    lines.append("")
    lines.append(
        f"This module's own correctness checks: {s['checks_passed']} of "
        f"{s['checks_total']} pass "
        f"({'ALL PASS' if s['checks_passed'] == s['checks_total'] else 'FAILURES PRESENT'})."
    )
    lines.append("")

    lines.append("## Correctness checks")
    lines.append(f"- Hooks trace to real doc text: {result['doc_trace_check']['n_passed']} of {result['doc_trace_check']['n_total']}")
    lines.append(f"- Cited data-gap node keys are live in variance_diagnostic.py's `_TREE`: {result['data_gap_keys_live_check']['n_passed']} of {result['data_gap_keys_live_check']['n_total']}")
    lines.append(f"- Checkpoint counts reconcile against an independent CSV parse: {'PASS' if result['checkpoint_reconciliation_check']['passed'] else '**FAIL**'} ({result['checkpoint_reconciliation_check']['n_models_checked']} models checked)")
    lines.append(f"- `pipeline_generated` stale-marking cross-reference confirmed live: {result['pipeline_generated_staleness']['is_stale_marking']}")
    lines.append("")

    lines.append("## Checkpoint depth by model (as of " + as_of_date.isoformat() + ")")
    lines.append("| Model | n_checkpoints | as_of_dates |")
    lines.append("|---|---|---|")
    for model, v in result["checkpoint_counts_by_model"].items():
        lines.append(f"| {model} | {v['n_checkpoints']} | {', '.join(v['as_of_dates'])} |")
    lines.append("")

    lines.append("## Drift-monitor hook catalog -- reading counts")
    lines.append(f"{s['hooks_cataloged']} hooks catalogued across {len(set(h['artifact'] for h in DRIFT_HOOK_CATALOG))} artifacts; "
                  f"{s['hooks_with_zero_persisted_readings']} have zero persisted readings today.")
    lines.append("")
    lines.append("| Hook | Artifact | Rule family | Persisted metric(s) | Reading count |")
    lines.append("|---|---|---|---|---|")
    for r in result["hook_reading_counts"]:
        metrics = ", ".join(f"`{m}`" for m in r["persisted_metric_names"]) or "*(none logged)*"
        lines.append(f"| {r['hook_id']} | {r['artifact']} | {r['rule_family']} | {metrics} | {r['max_reading_count']} |")
    lines.append("")

    lines.append("## Data-gap / investment-prioritization ranking")
    lines.append("Ranked cheapest-to-close first, then by live count of downstream tree nodes blocked.")
    lines.append("")
    lines.append("| Node | Layer | Tier | Blocks full Layer-1? | Nodes blocked |")
    lines.append("|---|---|---|---|---|")
    for g in result["data_gap_ranking"]:
        lines.append(f"| {g['label']} (`{g['node_key']}`) | {g['layer']} | {g['tier']} | {g['blocks_full_layer1_metric']} | {g['blocked_node_count']} |")
    lines.append("")

    lines.append("## Validation-maturity summary (self-proposed vs. independently confirmed thresholds)")
    lines.append(f"{s['artifacts_with_confirmed_threshold']} artifact section(s) carry a threshold "
                  f"CONFIRMED by `analytics-model-validator`; "
                  f"{s['artifacts_with_proposed_not_confirmed_threshold']} carry at least one threshold "
                  "still PROPOSED, not yet confirmed.")
    lines.append("")
    lines.append("| Artifact section | PROPOSED mentions | CONFIRMED mentions |")
    lines.append("|---|---|---|")
    for m in result["validation_maturity_summary"]:
        if m["n_proposed_not_confirmed_mentions"] or m["n_confirmed_by_validator_mentions"]:
            lines.append(f"| {m['artifact_section']} | {m['n_proposed_not_confirmed_mentions']} | {m['n_confirmed_by_validator_mentions']} |")
    lines.append("")

    md_path = os.path.join(_OUTPUT_DIR, f"proxy_metric_health_{as_of_date.isoformat()}.md")
    with open(md_path, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    result = run_build_time_validation(date(2025, 12, 31))
    s = result["summary"]
    print(f"{s['checks_passed']} of {s['checks_total']} correctness checks pass")
    print(f"{s['hooks_cataloged']} hooks catalogued, {s['hooks_traced_to_doc']} trace to doc text, "
          f"{s['hooks_with_zero_persisted_readings']} have zero persisted readings")
    print(f"Checkpoint depth: {s['min_checkpoints_across_models']}-{s['max_checkpoints_across_models']} "
          f"across {s['models_with_any_checkpoint']} models")
    print(f"pipeline_generated stale marking confirmed live: {s['pipeline_generated_stale_marking_confirmed']}")
    print(f"Threshold maturity: {s['artifacts_with_confirmed_threshold']} confirmed, "
          f"{s['artifacts_with_proposed_not_confirmed_threshold']} proposed-not-confirmed")
