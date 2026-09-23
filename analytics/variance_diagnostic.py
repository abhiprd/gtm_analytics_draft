"""Variance-diagnostic engine -- grain: one row per Layer-1 metric per
evaluation month (company-wide/blended, matching what the Layer-1
scorecard displays); source marts: mart_gtm_plan (plan side),
mart_growth_bridge / mart_efficiency / mart_durability (actuals side, all
segment x month, blended here), and mart_account_health (Layer-2 evidence
and the watchlist population).

WHAT THIS IS
------------
The engine that powers the weekly readout's drill-downs (build spec
Section 5, Phase 4). For every Layer-1 node it computes a variance
signal; where that signal breaches the threshold it walks DOWN the metric
tree -- never up, never sideways -- to whichever of that node's true
children is the actual outlier among its siblings, and then to that
child's own Layer-3 leaves where (and only where) the branch genuinely
has them.

STRUCTURAL GUARANTEE AGAINST THE OBVIOUS FAILURE MODE
-----------------------------------------------------
The failure this artifact is most likely to commit is surfacing an
intermediate node -- Win rate, say, which is a Layer-2 child of New logo
consumption revenue -- and labelling it "Layer 1". That is made
impossible here structurally rather than by care:

  * `_TREE` is the single, frozen transcription of
    docs/acme-corp-gtm-metric-tree.md. Every node carries its own `layer`
    and `parent_key`; `_register()` refuses any node whose layer is not
    exactly its parent's layer + 1, and the module-level integrity check
    re-verifies the whole tree at import.
  * A metric's layer is never assigned at emit time. Every record this
    module produces reads `layer` off the node definition.
  * The scan can only START at `layer1_nodes()` (nodes whose parent is a
    pillar). There is no code path by which a Layer-2 node enters the
    scorecard or becomes the head of a drill-down.
  * `Drilldown.__post_init__` asserts layer1.layer == 1, layer2.layer == 2
    and every layer-3 node's layer == 3 AND parent_key == the Layer-2
    node's key. A mislabelled record raises rather than renders.
  * `rank_siblings()` refuses any candidate that is not a real child of
    the parent it was asked about, so "the outlier among its siblings"
    cannot quietly become "the biggest mover anywhere in the tree."
  * Layer-3 depth is read from the tree, not assumed. Branches that are
    genuinely two layers deep (Consumption payback, Onboarding/CS
    efficiency, Activation, Logo retention) return
    `layer3_status="branch_depth_2"` and an empty evidence list -- a
    Layer 3 is never fabricated to force symmetry.

SCOPE RESOLUTION -- PLAYBOOK TRIGGERS ARE NOT BUILT HERE
--------------------------------------------------------
Build spec Section 5's Phase 4 prose bundles "playbook triggers" into
this artifact's deliverable description; Section 8's build-priority order
-- the section designated as the sequencing authority -- places
"Automated playbook triggers" in Wave 4, after Wave 1, because they need
"Wave 1's thresholds validated against real data first." That dependency
only makes sense if the triggers are built after this engine's thresholds
exist and have been validated. Resolved in favour of Section 8: no
playbook-trigger logic lives here, and nothing here reads or writes
fact_playbook_triggers (a table that does not exist yet in any case).
Recorded as a resolved scope decision in
docs/acme-corp-analytics-methods.md's Variance-diagnostic engine entry.

DETERMINISM
-----------
No stochastic step exists anywhere in this module -- no sampling, no
simulation, no train/test split -- so no random seed applies, matching
analytics/segment_migration.py's precedent. The one exception is
indirect: the watchlist calls analytics/health_score.py, which seeds its
own model via that module's `_RANDOM_SEED = 42`. This module does not
fit, re-fit, or replace that model; it consumes its scored output.
"""
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence

import duckdb
import numpy as np
import pandas as pd

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_MODEL_NAME = "variance_diagnostic_engine"

# =====================================================================
# Thresholds and windows
# =====================================================================

# PROPOSED, NOT YET CONFIRMED. Sourced from the hand-illustrated sample
# weekly readout in docs/acme-corp-claude-design-brief.md, which used
# +/-8% to decide which Layer-1 nodes earned a drill-down. Build spec
# Section 7 lists "exact variance threshold for triggering a drill-down
# (used +/-8% in the sample readout -- confirm or adjust)" as explicitly
# still open, so this is adopted as the documented starting point rather
# than invented here, and is flagged as proposed in
# docs/acme-corp-analytics-methods.md exactly as segment migration's 10%
# firmographic-rescore floor was. See measure_threshold_selectivity()
# below for the build-time evidence on how selective it actually is at
# this data's monthly grain.
_VARIANCE_THRESHOLD = 0.08

# Trailing baseline length for Layer-2/Layer-3 sibling ranking, and for
# Activation's Layer-1 signal. The design brief's sample readout compares
# a week against a "trailing 8-week average"; this engine runs at monthly
# grain (every actuals mart is segment x month), so the same 8-period
# shape is carried over as 8 months. Stated rather than silently
# reinterpreted.
_TRAILING_BASELINE_MONTHS = 8

# Activation's own baseline window. The design brief reports Activation
# against "2.4d last month" -- a single prior period. A one-month
# baseline is the noisiest possible comparator, so this engine uses the
# mean of the prior 3 months as the variance signal and reports the prior
# month's raw value alongside it for readout fidelity. Own resolved
# decision; the mechanism (trailing baseline, not plan) is the design
# brief's, the window length is this artifact's.
_ACTIVATION_BASELINE_MONTHS = 3

# Trailing-twelve-month window used to annualise NRR/GRR/logo retention
# before comparing them against mart_gtm_plan's annual-equivalent rates.
_ANNUALISATION_MONTHS = 12

# An account is counted into `usage_dip_breadth` when its trailing-3-month
# mean actions_consumed falls below this share of its own cumulative-to-
# date mean. The metric tree's Cyclical/planned-usage-dip node requires
# normalisation "against the account's own historical baseline" -- this
# is that account-relative baseline made concrete. Own resolved decision
# on the 0.70 cut: deep enough to exclude ordinary month-to-month usage
# noise, shallow enough to catch a fade well before it reaches zero.
_USAGE_DIP_RATIO_THRESHOLD = 0.70
_USAGE_DIP_WINDOW_MONTHS = 3

# Segments carrying a win-rate / avg-initial-commitment concept at all.
# Build spec Section 2: SMB "gets exactly one Opportunity record, created
# at conversion, immediately Closed Won... no Closed Lost record... SMB
# has no win-rate concept to true up." Including SMB would pin blended
# win rate near 1.0 and swamp avg initial commitment with 6,500 no-touch
# conversions. Both legs of the New-logo decomposition use the same
# population so the tree's multiplicative identity is not broken by
# mixing scopes.
_REP_SOLD_SEGMENTS = ("Commercial", "Enterprise")

# Segments mart_gtm_plan's consumption-payback anchor was blended over.
# generators/gtm_plan.py's _blend() renormalises the benchmark reference
# table over "whichever segments the benchmark table actually covers (it
# marks SMB 'n/a' for magic number and payback)". The actuals side is
# blended over the same two segments so plan and actual describe the same
# population.
_PAYBACK_BLEND_SEGMENTS = ("Commercial", "Enterprise")


# =====================================================================
# The metric tree -- the single frozen transcription of
# docs/acme-corp-gtm-metric-tree.md
# =====================================================================

PILLARS = ("growth", "efficiency", "durability")

# Comparability of a Layer-1 metric's ACTUAL against mart_gtm_plan.
COMPARABLE = "comparable"
CAVEATED = "caveated"
NOT_COMPUTABLE = "not_computable"
NO_PLAN_BY_DESIGN = "no_plan_by_design"

# Computability of any node's actual from the mart_* tables this module
# is allowed to read.
COMPUTABLE = "computable"
PARTIAL = "partial"


@dataclass(frozen=True)
class MetricNode:
    """One node of docs/acme-corp-gtm-metric-tree.md. `layer` is the
    node's real depth (1/2/3) and is never reassigned downstream."""
    key: str
    label: str
    layer: int
    pillar: str
    parent_key: Optional[str]
    computability: str = NOT_COMPUTABLE
    # Why an actual is unavailable, or what makes it only partial. Always
    # populated when computability != COMPUTABLE, so a gap is reported
    # rather than silently dropped.
    gap_note: Optional[str] = None
    # Layer-1 only: which direction is a good result, used for
    # Ahead/Behind status. Breach of the threshold is symmetric (+/-8%)
    # regardless of direction.
    favorable_direction: Optional[str] = None
    # Layer-1 only: whether the actual can be diffed against the plan.
    plan_comparability: Optional[str] = None
    plan_comparability_note: Optional[str] = None
    # False for nodes the tree itself excludes from the parent's
    # arithmetic: the marketing-sales handoff overlay ("a diagnostic
    # overlay on the above three, not a fourth multiplicative factor")
    # and Brand & awareness ("leading indicator, not summed into the
    # pipeline math"). They stay in the tree but never compete in a
    # sibling ranking.
    is_ranking_sibling: bool = True
    # Set on Durability's children, which the tree defines by reference
    # ("See Growth -- expansion, contraction, churn drivers") rather than
    # as fresh nodes. Lets the readout suppress a drill-down that merely
    # restates one already produced under Growth.
    cross_reference_to: Optional[str] = None
    # How this node's CHILDREN are compared against one another.
    #   relative_deviation -- % deviation from each child's own trailing
    #     baseline. The default, and the design brief's own read ("24%
    #     this week vs. a 31% trailing 8-week average"). Correct whenever
    #     siblings are measured in different units and only a normalised
    #     comparison is meaningful.
    #   additive_share -- absolute deviation, in the siblings' shared
    #     unit. Used where the children are additive components of the
    #     parent measured on one scale (NRR and GRR decompose into
    #     expansion/contraction/churn as shares of starting revenue).
    #     Ranking those by % deviation lets a large relative swing on a
    #     near-zero component outrank a component that actually moved the
    #     parent -- which would identify the wrong outlier.
    sibling_comparison_basis: str = "relative_deviation"


_TREE: Dict[str, MetricNode] = {}


def _register(node: MetricNode) -> MetricNode:
    """Adds a node, refusing any layer that is not exactly its parent's
    layer + 1. This is the mechanism that makes a Layer-2 node labelled
    'Layer 1' impossible rather than merely unlikely."""
    if node.key in _TREE:
        raise ValueError(f"duplicate metric-tree node: {node.key}")
    if node.pillar not in PILLARS:
        raise ValueError(f"{node.key}: unknown pillar {node.pillar}")
    if node.layer == 1:
        if node.parent_key is not None:
            raise ValueError(f"{node.key}: a Layer-1 node's parent is a pillar, not a metric")
    else:
        if node.parent_key is None:
            raise ValueError(f"{node.key}: layer {node.layer} node needs a parent")
        parent = _TREE[node.parent_key]
        if node.layer != parent.layer + 1:
            raise ValueError(
                f"{node.key}: layer {node.layer} under parent {parent.key} (layer {parent.layer})"
            )
        if node.pillar != parent.pillar:
            raise ValueError(f"{node.key}: pillar differs from parent {parent.key}")
    if node.computability != COMPUTABLE and not node.gap_note:
        raise ValueError(f"{node.key}: a non-computable node must state why")
    _TREE[node.key] = node
    return node


def _l1(key, label, pillar, favorable_direction, plan_comparability,
        computability=COMPUTABLE, gap_note=None, plan_comparability_note=None,
        sibling_comparison_basis="relative_deviation"):
    return _register(MetricNode(
        key=key, label=label, layer=1, pillar=pillar, parent_key=None,
        computability=computability, gap_note=gap_note,
        favorable_direction=favorable_direction,
        plan_comparability=plan_comparability,
        plan_comparability_note=plan_comparability_note,
        sibling_comparison_basis=sibling_comparison_basis,
    ))


def _child(key, label, parent_key, computability=NOT_COMPUTABLE, gap_note=None,
           is_ranking_sibling=True, cross_reference_to=None):
    parent = _TREE[parent_key]
    return _register(MetricNode(
        key=key, label=label, layer=parent.layer + 1, pillar=parent.pillar,
        parent_key=parent_key, computability=computability, gap_note=gap_note,
        is_ranking_sibling=is_ranking_sibling, cross_reference_to=cross_reference_to,
    ))


_NO_LEADS_DATA = (
    "No mart_* table exposes leads, campaign touches or PQL signals -- "
    "mart_growth_bridge's own header records that the organic/paid/community "
    "pipeline breakdown was not built because that raw data does not exist. "
    "A closed-new-business opportunity count is available but is a different "
    "quantity (deals that closed, not pipeline generated), so it is not "
    "substituted in as a proxy."
)
_NO_OPPORTUNITY_MART = (
    "Needs opportunity-level detail (stage history, loss_reason, list_price, "
    "opportunity_type='renewal'). fact_opportunities / "
    "fact_opportunity_stage_history exist but are fact_* tables, outside the "
    "mart_*-only read scope Phase 4 code operates under "
    "(.claude/skills/analytics-engineering-conventions). Closing this is a "
    "Phase 2 mart change, not a Phase 4 workaround."
)
_NO_COST_DATA = (
    "No rep-cost/comp data exists anywhere in the raw sources, so the "
    "denominator is undefined -- mart_efficiency leaves magic_number and "
    "am_efficiency NULL on purpose for the same reason."
)

# ---------------------------------------------------------------- Growth

_l1("new_logo_consumption_revenue", "New logo consumption revenue", "growth",
    "higher", COMPARABLE)
_child("pipeline_generated", "Pipeline generated", "new_logo_consumption_revenue",
       NOT_COMPUTABLE, _NO_LEADS_DATA)
_child("organic_content", "Organic/content", "pipeline_generated", NOT_COMPUTABLE, _NO_LEADS_DATA)
_child("paid", "Paid", "pipeline_generated", NOT_COMPUTABLE, _NO_LEADS_DATA)
_child("community_events", "Community/events", "pipeline_generated", NOT_COMPUTABLE, _NO_LEADS_DATA)

_child("win_rate", "Win rate", "new_logo_consumption_revenue", COMPUTABLE)
_child("stage_to_stage_conversion", "Stage-to-stage conversion", "win_rate",
       NOT_COMPUTABLE, _NO_OPPORTUNITY_MART)
_child("poc_pass_rate", "POC pass rate (Enterprise)", "win_rate",
       NOT_COMPUTABLE, _NO_OPPORTUNITY_MART)
_child("rep_capacity_ramp_mix", "Rep capacity / ramp mix", "win_rate",
       NOT_COMPUTABLE,
       "Needs rep-level quota/ramp joined to deal ownership; dim_reps and "
       "int_rep_capacity_periods are not mart_* tables and no mart exposes "
       "win rate cut by rep ramp status.")
_child("loss_reason_mix", "Loss-reason mix", "win_rate", NOT_COMPUTABLE, _NO_OPPORTUNITY_MART)

_child("avg_initial_commitment", "Avg initial commitment", "new_logo_consumption_revenue", COMPUTABLE)
_child("discount_rate_vs_list", "Discount rate vs. list", "avg_initial_commitment",
       NOT_COMPUTABLE, _NO_OPPORTUNITY_MART)
_child("deal_size_trend_within_band", "Deal-size trend within segment band",
       "avg_initial_commitment", NOT_COMPUTABLE, _NO_OPPORTUNITY_MART)

_child("marketing_sales_handoff_quality", "Marketing-sales handoff quality",
       "new_logo_consumption_revenue", NOT_COMPUTABLE,
       "No leads/MQL/SAL data in any mart. Excluded from sibling ranking "
       "regardless: the tree calls it 'a diagnostic overlay on the above "
       "three, not a fourth multiplicative factor'.",
       is_ranking_sibling=False)
_child("mql_response_sla", "MQL response SLA", "marketing_sales_handoff_quality",
       NOT_COMPUTABLE, _NO_LEADS_DATA)
_child("mql_to_sal_acceptance_rate", "MQL -> SAL acceptance rate",
       "marketing_sales_handoff_quality", NOT_COMPUTABLE, _NO_LEADS_DATA)
_child("lead_recycling_rate", "Lead recycling / nurture re-qualification rate",
       "marketing_sales_handoff_quality", NOT_COMPUTABLE, _NO_LEADS_DATA)

_child("brand_awareness", "Brand & awareness", "new_logo_consumption_revenue",
       NOT_COMPUTABLE,
       "No web-traffic, branded-search or share-of-voice source exists. "
       "Excluded from sibling ranking regardless: the tree marks it a "
       "'leading indicator, not summed into the pipeline math' -- the one "
       "deliberate non-additive node in the tree (CLAUDE.md invariant).",
       is_ranking_sibling=False)
_child("branded_search_volume_trend", "Branded search volume trend", "brand_awareness",
       NOT_COMPUTABLE, "No web-traffic/search source exists in any layer of this project.")
_child("direct_traffic_share", "Direct traffic share", "brand_awareness",
       NOT_COMPUTABLE, "No web-traffic source exists in any layer of this project.")
_child("share_of_voice", "Share of voice vs. named competitors", "brand_awareness",
       NOT_COMPUTABLE, "No competitive-intelligence source exists in any layer of this project.")

_l1("activation", "Activation (TTFA, blended)", "growth", "lower", NO_PLAN_BY_DESIGN,
    plan_comparability_note=(
        "Activation is the one Layer-1 node mart_gtm_plan deliberately carries "
        "no plan row for (its own header, and generators/gtm_plan.py). The "
        "design brief's sample readout reports it against a trailing baseline "
        "('2.1 days vs. 2.4d last month'), not a plan figure. This engine "
        "therefore gives Activation its own trailing-baseline variance "
        "mechanism -- a different mechanism from the other ten metrics, stated "
        "explicitly rather than forced into the plan-diff shape. DEGENERATE IN "
        "THE CURRENT DATA: blended TTFA is identically 0 in every month of the "
        "36-month window, because fact_usage_monthly is monthly grain and every "
        "account records its first Action in its own signup month (see "
        "mart_growth_bridge's own Activation comment). The baseline mechanism is "
        "implemented and exercised, but on this data it has a zero baseline and "
        "therefore no computable deviation -- which is why Activation reports "
        "'Not computable' rather than 'On track'. A real TTFA signal needs a "
        "day-grain first-Action timestamp in Phase 1 plus a mart change, not a "
        "Phase 4 workaround."))
_child("onboarding_completion_rate", "Onboarding completion rate", "activation",
       PARTIAL,
       "Computed as mart_growth_bridge.activated_count / signup_cohort_size -- "
       "the share of a signup cohort that reached a first production Action. "
       "In the current generated data this is identically 1.0 in every month "
       "(every account produces a first Action in its signup month), so the "
       "series carries no variance signal -- a data property, not an engine "
       "limitation.")
_child("time_to_first_integration", "Time-to-first-integration / first successful run",
       "activation", NOT_COMPUTABLE,
       "No integration or first-successful-run event exists in the raw data; "
       "fact_usage_monthly is monthly grain with no first-Action timestamp.")
_child("quickstart_docs_engagement_rate", "Quickstart/docs content engagement rate",
       "activation", NOT_COMPUTABLE,
       "The build spec's content_engagement source was never generated, so no "
       "mart or fact table carries docs/quickstart interaction at all.")

_l1("expansion_consumption_revenue", "Expansion consumption revenue", "growth",
    "higher", COMPARABLE)
_child("wallet_share_progression", "Wallet share progression",
       "expansion_consumption_revenue", NOT_COMPUTABLE,
       "Requires an account's total addressable workflow footprint (the "
       "denominator of 'wallet share'). No source in this project estimates "
       "an account's non-Acme workflow volume, so the ratio has no "
       "denominator at all.")
_child("workflow_migration_rate", "Workflow migration rate", "wallet_share_progression",
       NOT_COMPUTABLE, "Needs business-process-level onboarding events; not generated.")
_child("am_touch_effectiveness", "AM touch effectiveness", "wallet_share_progression",
       NOT_COMPUTABLE,
       "fact_am_activity exists but no mart exposes AM touches joined to a "
       "recommitment outcome; mart_efficiency exposes only the touch count.")
_child("existing_account_community_engagement", "Existing-account community engagement depth",
       "wallet_share_progression", NOT_COMPUTABLE,
       "The build spec's community_membership source was never generated.")
_child("overage_realization", "Overage realization", "expansion_consumption_revenue",
       NOT_COMPUTABLE,
       "Committed-vs-utilized Action volume exists only in "
       "fact_committed_vs_utilized_monthly, a fact_* table outside this "
       "module's mart_*-only read scope. mart_efficiency consumes it "
       "internally but exposes only a utilisation-haircut margin figure, not "
       "realised overage billing. Closing this is a Phase 2 mart change.")

_l1("contraction_churned_revenue", "Contraction + churned revenue", "growth",
    "lower", COMPARABLE)
_child("workflow_chain_underutilization", "Workflow chain under-utilization",
       "contraction_churned_revenue", NOT_COMPUTABLE,
       "fact_workflow_chain_events exists but is not exposed through any "
       "mart_* table, so upstream-vs-downstream Action completion is outside "
       "this module's read scope. Phase 2 mart gap.")
_child("ingestion_without_completion_rate", "Ingestion-without-completion rate",
       "workflow_chain_underutilization", NOT_COMPUTABLE, "See parent's gap note.")
_child("mid_chain_abandonment", "Mid-chain workflow abandonment",
       "workflow_chain_underutilization", NOT_COMPUTABLE, "See parent's gap note.")
_child("full_vs_partial_chain_share", "Declining share of full-chain vs. partial-chain runs",
       "workflow_chain_underutilization", NOT_COMPUTABLE, "See parent's gap note.")

_child("account_health_score", "Account health score", "contraction_churned_revenue",
       NOT_COMPUTABLE,
       "Not computable AS A POINT-IN-TIME TRAILING SERIES, which is what a "
       "sibling ranking needs. analytics/health_score.py's score_accounts() "
       "defines its scored population as accounts whose mart_account_health "
       "customer_status is 'Active' -- a final-status field. Scored at a "
       "historical month that silently drops every account that has churned "
       "since, biasing older months upward and manufacturing a spurious "
       "deterioration trend. Producing an honest series needs score_accounts() "
       "to gate the population on churn_month > month instead, a change to "
       "analytics/health_score.py that is out of this artifact's scope. The "
       "model's CURRENT-state output is still used, at as_of_date only, for "
       "the watchlist -- see build_watchlist().")
_child("usage_trend_account_relative", "Usage trend (account-relative baseline)",
       "account_health_score", NOT_COMPUTABLE, "See parent's gap note.")
_child("support_ticket_volume_severity", "Support ticket volume / severity",
       "account_health_score", NOT_COMPUTABLE, "See parent's gap note.")
_child("engagement_login_frequency", "Engagement / login frequency",
       "account_health_score", NOT_COMPUTABLE, "See parent's gap note.")
_child("am_sentiment_notes", "AM sentiment notes", "account_health_score",
       NOT_COMPUTABLE, "See parent's gap note.")

_child("cyclical_vs_structural_usage_dip", "Cyclical/planned usage dip vs. structural churn",
       "contraction_churned_revenue", PARTIAL,
       "Computed as usage_dip_breadth: the share of the active account "
       "population whose trailing-3-month mean actions_consumed sits below "
       "_USAGE_DIP_RATIO_THRESHOLD of that account's own cumulative-to-date "
       "mean -- the node's first Layer-3 leaf ('account-specific baseline "
       "deviation') made concrete from mart_account_health. PARTIAL because it "
       "measures the breadth of account-relative dips without performing the "
       "cyclical-vs-structural classification the node's headline asks for; "
       "that needs the second leaf's cohort comparison (same account type, "
       "same period last cycle), which no mart supports. Descriptive only -- "
       "no model is fitted here.")
_child("account_specific_baseline_deviation", "Account-specific baseline deviation",
       "cyclical_vs_structural_usage_dip", NOT_COMPUTABLE,
       "Already folded into the parent's own computation (usage_dip_breadth IS "
       "the account-relative baseline deviation, aggregated); surfacing it as "
       "a separate Layer-3 leaf would restate the parent, not add evidence.")
_child("cohort_comparison", "Cohort comparison (same account type, same period last cycle)",
       "cyclical_vs_structural_usage_dip", NOT_COMPUTABLE,
       "No mart exposes an account-type x usage-cycle cohort baseline.")

_child("renewal_win_rate", "Renewal win rate", "contraction_churned_revenue",
       NOT_COMPUTABLE, _NO_OPPORTUNITY_MART)
_child("time_to_respond_churn_risk_flag", "Time-to-respond on churn-risk flag",
       "renewal_win_rate", NOT_COMPUTABLE,
       "Needs a churn-risk flag event joined to AM response; no mart exposes it.")
_child("loud_vs_silent_churn_mix", "Loud vs. silent churn mix", "renewal_win_rate",
       NOT_COMPUTABLE, _NO_OPPORTUNITY_MART)

# ------------------------------------------------------------ Efficiency

_l1("magic_number", "Magic number (blended)", "efficiency", "higher", NOT_COMPUTABLE,
    computability=NOT_COMPUTABLE, gap_note=_NO_COST_DATA,
    plan_comparability_note=(
        "mart_gtm_plan carries a plan value (a top-down target does not need "
        "cost data the way a computed ratio does), but mart_efficiency leaves "
        "magic_number NULL by design. Variance from plan is therefore "
        "STRUCTURALLY NOT COMPUTABLE -- a genuine data gap, not a bug. An "
        "actual is never fabricated to close it."))
_child("sm_cost", "S&M cost", "magic_number", NOT_COMPUTABLE, _NO_COST_DATA)
_child("cost_per_channel_activity", "Cost per channel activity", "sm_cost",
       NOT_COMPUTABLE, _NO_COST_DATA)
_child("rep_fully_loaded_cost", "Rep fully-loaded cost, incl. ramp", "sm_cost",
       NOT_COMPUTABLE, _NO_COST_DATA)
_child("marketing_spend_allocation_by_channel", "Marketing spend allocation by channel",
       "sm_cost", NOT_COMPUTABLE,
       "fact_marketing_spend exists but is a fact_* table; no mart exposes "
       "spend by channel. Phase 2 mart gap.")

_l1("consumption_payback", "Consumption payback (blended)", "efficiency", "lower", CAVEATED,
    plan_comparability_note=(
        "Both sides exist and the variance IS computed, but the LEVELS are not "
        "on the same footing and the readout must not present the gap as a "
        "business finding. mart_gtm_plan's anchor is the QA plan's benchmark "
        "payback band (Commercial ~14-18mo, Enterprise ~9-13mo), which assumes "
        "a fully-loaded CAC. mart_efficiency's actual CAC comes from "
        "fact_marketing_spend only -- generators/config.py records that "
        "outbound_sdr's channel spend 'covers tooling/data enrichment only, NOT "
        "rep headcount cost', so the actual numerator systematically excludes "
        "sales headcount. The actual's denominator is also average utilised "
        "margin across the whole installed base rather than per NEW account. "
        "Both push the computed actual far below the benchmark band. The "
        "Layer-2 drill-down is unaffected: it ranks each leg against its own "
        "trailing baseline, which is immune to a constant level offset."))
_child("cac_by_channel", "CAC by channel (unblended)", "consumption_payback", PARTIAL,
       "mart_efficiency exposes blended_cac (already blended across channels "
       "by each channel's share of the segment's new accounts). The per-channel "
       "unblending the tree names is not exposed by any mart_* table, so the "
       "leg is ranked in blended form. Enough to identify CAC as the outlier "
       "leg; not enough to name the responsible channel.")
_child("utilized_vs_committed_action_volume", "Utilized vs. committed Action volume",
       "consumption_payback", PARTIAL,
       "mart_efficiency exposes avg_utilized_action_margin_per_account, which "
       "is MRR haircut by min(1, utilized/committed) and multiplied by the "
       "build spec's flat 80% gross margin. The raw utilised/committed ratio "
       "is not separately exposed, so movement in this leg can come from "
       "either utilisation or the MRR base.")

_l1("onboarding_cs_efficiency", "Onboarding/CS efficiency (blended)", "efficiency",
    "lower", COMPARABLE)
_child("am_touchpoint_volume", "AM touchpoint volume", "onboarding_cs_efficiency", COMPUTABLE)
_child("automated_action_volume", "Automated Action volume delivered",
       "onboarding_cs_efficiency", COMPUTABLE)

_l1("am_efficiency", "AM efficiency (blended)", "efficiency", "higher", NOT_COMPUTABLE,
    computability=NOT_COMPUTABLE, gap_note=_NO_COST_DATA,
    plan_comparability_note=(
        "Same structural gap as magic number: mart_gtm_plan carries a plan "
        "value, mart_efficiency leaves am_efficiency NULL because no AM comp "
        "data exists. Variance from plan is not computable and no actual is "
        "fabricated."))
_child("expansion_revenue_drivers", "Expansion revenue drivers", "am_efficiency",
       NOT_COMPUTABLE,
       "Defined by reference in the tree ('See Growth -- expansion revenue "
       "drivers'); with am_efficiency's own actual undefined there is nothing "
       "to drill into here.",
       cross_reference_to="expansion_consumption_revenue")
_child("am_cost_by_segment", "AM cost by segment", "am_efficiency",
       NOT_COMPUTABLE, _NO_COST_DATA)

# ------------------------------------------------------------ Durability

_l1("nrr", "NRR", "durability", "higher", CAVEATED,
    sibling_comparison_basis="additive_share",
    plan_comparability_note=(
        "Two adjustments, both stated rather than applied silently. (1) UNITS: "
        "mart_gtm_plan's nrr is an annual-equivalent decimal rate while "
        "mart_durability exposes a monthly rate -- this engine compounds the "
        "trailing 12 company-wide monthly rates before diffing, per "
        "mart_gtm_plan's own header instruction. (2) SCOPE OF THE CONTRACTION "
        "BUCKET. The plan side is internally consistent: generators/gtm_plan.py "
        "derives its monthly expansion and contraction+churn shares of base "
        "FROM the benchmark-blended nrr/grr anchors (1 - grr**(1/12), and "
        "nrr**(1/12) - 1 + that), so the plan's flow rows and its durability "
        "rows are two readings of one identity rather than two independent "
        "guesses. The remaining gap is on the ACTUALS side and is definitional, "
        "not performance. Over the twelve months to 2025-11 the marts carry "
        "gross contraction+churn at ~5.4% of starting revenue per month against "
        "gross expansion at ~10.8%, of which outright churn is only ~0.2%: "
        "int_revenue_movements buckets ANY month-on-month usage decline as "
        "contraction, so in a consumption business whose base grows ~88% a year "
        "both gross legs are large and largely offsetting, while a benchmark "
        "NRR/GRR band describes durable downsell in a mature base. That one "
        "difference drives both signs at once -- TTM GRR lands ~0.51 against a "
        "0.93 plan while TTM NRR lands ~1.82 against a 1.17 plan. Logo "
        "retention, which has no gross-flow bucket, reconciles to plan within "
        "2%, which is the evidence that the churn leg is sound and it is the "
        "contraction bucket's SCOPE that differs. Read the Layer-2 drill-down, "
        "which ranks each leg against its own trailing baseline and is immune "
        "to a definitional level offset."))
_child("nrr_expansion_rate", "Expansion (share of starting revenue)", "nrr", COMPUTABLE,
       cross_reference_to="expansion_consumption_revenue")
_child("nrr_contraction_rate", "Contraction (share of starting revenue)", "nrr", COMPUTABLE,
       cross_reference_to="contraction_churned_revenue")
_child("nrr_churn_rate", "Churn (share of starting revenue)", "nrr", COMPUTABLE,
       cross_reference_to="contraction_churned_revenue")

_l1("grr", "GRR", "durability", "higher", CAVEATED,
    sibling_comparison_basis="additive_share",
    plan_comparability_note="Same two adjustments as NRR -- see the NRR entry.")
_child("grr_contraction_rate", "Contraction (share of starting revenue)", "grr", COMPUTABLE,
       cross_reference_to="contraction_churned_revenue")
_child("grr_churn_rate", "Churn (share of starting revenue)", "grr", COMPUTABLE,
       cross_reference_to="contraction_churned_revenue")

_l1("logo_retention", "Logo retention", "durability", "higher", COMPARABLE)
_child("tenure_at_churn", "Tenure-at-churn (early vs. late lifecycle)", "logo_retention",
       COMPUTABLE)
_child("churn_reason_category", "Churn reason category (loud vs. silent)", "logo_retention",
       NOT_COMPUTABLE, _NO_OPPORTUNITY_MART)


# =====================================================================
# Tree accessors -- the only sanctioned way to reach a node
# =====================================================================

def get_node(key: str) -> MetricNode:
    return _TREE[key]


def layer1_nodes() -> List[MetricNode]:
    """All 11 Layer-1 nodes, pillar order. The scorecard shows every one
    of them unconditionally (build spec Section 5) and this is the ONLY
    entry point a drill-down scan may start from."""
    return [n for pillar in PILLARS for n in _TREE.values()
            if n.layer == 1 and n.pillar == pillar]


def children_of(key: str) -> List[MetricNode]:
    parent = _TREE[key]
    kids = [n for n in _TREE.values() if n.parent_key == key]
    for kid in kids:
        if kid.layer != parent.layer + 1:
            raise ValueError(f"tree corruption at {kid.key}")
    return kids


def ranking_siblings_of(key: str) -> List[MetricNode]:
    """Children eligible to compete in an outlier ranking -- excludes the
    tree's own explicitly non-additive nodes (handoff overlay, Brand &
    awareness)."""
    return [n for n in children_of(key) if n.is_ranking_sibling]


def branch_max_depth(key: str) -> int:
    """Real depth of the branch rooted at `key`, read from the tree. Used
    to distinguish 'this branch has no Layer 3' from 'it has one but the
    data is missing' -- the two produce different, honest statuses."""
    kids = children_of(key)
    if not kids:
        return _TREE[key].layer
    return max(branch_max_depth(k.key) for k in kids)


def _verify_tree_integrity() -> None:
    # raise, not assert: this check must hold even under python -O, since
    # the guarantee it enforces ("impossible structurally, not by care") is
    # exactly the property this module claims to give the readout.
    l1 = [n for n in _TREE.values() if n.layer == 1]
    if len(l1) != 11:
        raise ValueError(f"metric tree must have exactly 11 Layer-1 nodes, found {len(l1)}")
    if len([n for n in l1 if n.pillar == "growth"]) != 4:
        raise ValueError("growth pillar must have exactly 4 Layer-1 nodes")
    if len([n for n in l1 if n.pillar == "efficiency"]) != 4:
        raise ValueError("efficiency pillar must have exactly 4 Layer-1 nodes")
    if len([n for n in l1 if n.pillar == "durability"]) != 3:
        raise ValueError("durability pillar must have exactly 3 Layer-1 nodes")
    for node in _TREE.values():
        if node.layer not in (1, 2, 3):
            raise ValueError(f"{node.key}: layer {node.layer} outside the tree's 3 layers")
        if node.parent_key is not None and _TREE[node.parent_key].layer != node.layer - 1:
            raise ValueError(f"{node.key}: parent {node.parent_key} is not one layer above it")
    # Branches the design brief and the tree explicitly say are two deep.
    for two_deep in ("consumption_payback", "onboarding_cs_efficiency",
                     "activation", "logo_retention"):
        if branch_max_depth(two_deep) != 2:
            raise ValueError(f"{two_deep} must be a 2-layer branch")
    # Branches that genuinely do reach Layer 3.
    for three_deep in ("new_logo_consumption_revenue", "contraction_churned_revenue",
                       "expansion_consumption_revenue", "magic_number"):
        if branch_max_depth(three_deep) != 3:
            raise ValueError(f"{three_deep} must reach Layer 3")


_verify_tree_integrity()


# =====================================================================
# Mart loaders -- mart_* only (plus fact_model_performance_history via
# analytics/model_performance.py), per analytics-engineering-conventions
# =====================================================================

def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


def load_plan(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per (layer1_metric, month), month <= as_of_date.
    Source mart: mart_gtm_plan."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select layer1_metric, month, pillar, plan_value "
            "from main_marts.mart_gtm_plan where month <= ?", [as_of_date]).df()
    finally:
        if owns:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    return df


def load_growth_bridge(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per segment per month, month <= as_of_date. Source
    mart: mart_growth_bridge."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select * from main_marts.mart_growth_bridge where month <= ?", [as_of_date]).df()
    finally:
        if owns:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    return df


def load_efficiency(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per segment per month, month <= as_of_date. Source
    mart: mart_efficiency."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select * from main_marts.mart_efficiency where month <= ?", [as_of_date]).df()
    finally:
        if owns:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    return df


def load_durability(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per segment per month, month <= as_of_date. Source
    mart: mart_durability."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select * from main_marts.mart_durability where month <= ?", [as_of_date]).df()
    finally:
        if owns:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    return df


def load_account_health(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per account_id per month, month <= as_of_date.
    Source mart: mart_account_health. Only backward-looking columns are
    used for series construction -- customer_status / is_eventually_churned
    are final-status fields and would leak."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select account_id, month, segment, actions_consumed, "
            "account_tenure_days, churn_month "
            "from main_marts.mart_account_health where month <= ?", [as_of_date]).df()
    finally:
        if owns:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    df["churn_month"] = pd.to_datetime(df["churn_month"])
    return df


# =====================================================================
# Blending the actuals side to mart_gtm_plan's company-wide grain
# =====================================================================

def _evaluation_month(as_of_date: date) -> pd.Timestamp:
    """The last COMPLETE month at or before as_of_date. A mid-month
    as_of_date would otherwise diff a partial month's actual against a
    whole month's plan, which is a unit mismatch in disguise."""
    ts = pd.Timestamp(as_of_date)
    month_start = ts.to_period("M").to_timestamp()
    month_end = ts.to_period("M").to_timestamp("M")
    return month_start if ts >= month_end else month_start - pd.DateOffset(months=1)


def blend_layer1_actuals(as_of_date: date, con=None) -> pd.DataFrame:
    """Company-wide (blended, no segment cut) monthly actual for each
    Layer-1 metric -- the same grain mart_gtm_plan is published at.
    Grain: one row per month <= as_of_date, one column per Layer-1 metric
    key. Source marts: mart_growth_bridge, mart_efficiency,
    mart_durability.

    Blending rules, one per metric family, chosen to match how
    generators/gtm_plan.py built the plan side rather than picked ad hoc:
      * Dollar movements (new logo / expansion / contraction+churn) --
        a straight sum across segments. Company-wide segment migration
        nets to zero by construction (mart_growth_bridge's bridge
        identity), so the sum is exact, not an approximation.
      * Activation (TTFA) -- signup-cohort-size-weighted mean, i.e.
        logo-weighted, since TTFA is a per-account average.
      * Consumption payback -- revenue-weighted (starting_mrr share)
        across Commercial and Enterprise only, mirroring
        gtm_plan._blend(BENCHMARK_CONSUMPTION_PAYBACK_MONTHS,
        _final_revenue_mix()), which renormalises over the segments the
        benchmark table covers (SMB is marked n/a).
      * Onboarding/CS efficiency -- an aggregate ratio, total AM/CS
        touchpoints over total automated Actions across all three
        segments. Matches gtm_plan._steady_state_touch_per_action(),
        which counts SMB's Actions in the denominator with zero touches
        in the numerator (a real zero -- SMB is no-touch).
      * NRR / GRR -- the company-wide MONTHLY rate is the aggregate
        dollar ratio (revenue-weighted by construction); the ANNUAL-
        equivalent figure mart_gtm_plan publishes is the product of the
        trailing 12 monthly rates. Compounding, not averaging: a
        retention rate is multiplicative across periods.
      * Logo retention -- identical, on account counts rather than
        dollars (logo-weighted), mirroring gtm_plan's use of
        _final_logo_mix() for this one metric.
      * Magic number / AM efficiency -- left NaN. mart_efficiency leaves
        both NULL because no rep-cost/comp data exists anywhere in the
        raw sources. Never imputed.
    """
    owns = con is None
    con = con or _connect()
    try:
        gb = load_growth_bridge(as_of_date, con=con)
        eff = load_efficiency(as_of_date, con=con)
        dur = load_durability(as_of_date, con=con)
    finally:
        if owns:
            con.close()

    out = pd.DataFrame(index=pd.Index(sorted(gb["month"].unique()), name="month"))

    money = gb.groupby("month").agg(
        new_logo=("new_logo_mrr", "sum"),
        expansion=("expansion_mrr", "sum"),
        contraction=("contraction_mrr", "sum"),
        churn=("churn_mrr", "sum"),
    )
    out["new_logo_consumption_revenue"] = money["new_logo"]
    out["expansion_consumption_revenue"] = money["expansion"]
    out["contraction_churned_revenue"] = money["contraction"] + money["churn"]

    act = gb.dropna(subset=["signup_cohort_size"]).copy()
    act["weighted"] = act["activation_ttfa_months_avg"] * act["signup_cohort_size"]
    act_g = act.groupby("month").agg(w=("weighted", "sum"), n=("signup_cohort_size", "sum"))
    out["activation"] = act_g["w"] / act_g["n"].replace(0, np.nan)

    pay = eff[eff["segment"].isin(_PAYBACK_BLEND_SEGMENTS)].merge(
        dur[["segment", "month", "starting_mrr"]], on=["segment", "month"], how="left")
    pay = pay.dropna(subset=["consumption_payback_months"])
    pay["weight"] = pay["starting_mrr"].fillna(0.0)
    pay_g = pay.groupby("month").apply(
        lambda d: np.average(d["consumption_payback_months"], weights=d["weight"])
        if d["weight"].sum() > 0 else np.nan, include_groups=False)
    out["consumption_payback"] = pay_g

    oce = eff.groupby("month").agg(
        touches=("am_touchpoint_count", "sum"),
        actions=("automated_actions_delivered", "sum"))
    out["onboarding_cs_efficiency"] = (
        oce["touches"].astype(float) / oce["actions"].astype(float).replace(0, np.nan))

    cw = dur.groupby("month").agg(
        s=("starting_mrr", "sum"), e=("expansion_mrr", "sum"),
        c=("contraction_mrr", "sum"), ch=("churn_mrr", "sum"),
        sa=("starting_accounts", "sum"), ca=("churned_accounts", "sum"))
    nrr_m = (cw["s"] - cw["c"] - cw["ch"] + cw["e"]) / cw["s"].replace(0, np.nan)
    grr_m = (cw["s"] - cw["c"] - cw["ch"]) / cw["s"].replace(0, np.nan)
    lr_m = (cw["sa"] - cw["ca"]) / cw["sa"].replace(0, np.nan)
    out["nrr"] = nrr_m.rolling(_ANNUALISATION_MONTHS).apply(np.prod, raw=True)
    out["grr"] = grr_m.rolling(_ANNUALISATION_MONTHS).apply(np.prod, raw=True)
    out["logo_retention"] = lr_m.rolling(_ANNUALISATION_MONTHS).apply(np.prod, raw=True)

    out["magic_number"] = np.nan
    out["am_efficiency"] = np.nan

    out["nrr_monthly"] = nrr_m
    out["grr_monthly"] = grr_m
    out["logo_retention_monthly"] = lr_m
    return out.sort_index()


# =====================================================================
# Layer-2 / Layer-3 candidate series
# =====================================================================

def build_child_series(parent_key: str, as_of_date: date, con=None) -> Dict[str, pd.Series]:
    """Monthly series for every COMPUTABLE child of `parent_key`, keyed
    by that child's own tree key. Grain: one value per month <=
    as_of_date. Source marts: mart_growth_bridge, mart_efficiency,
    mart_durability, mart_account_health. Children with no mart-computable
    actual are simply absent from the returned dict -- their gap_note in
    the tree is what gets reported, never a substituted proxy."""
    owns = con is None
    con = con or _connect()
    try:
        return _build_child_series(parent_key, as_of_date, con)
    finally:
        if owns:
            con.close()


def _build_child_series(parent_key: str, as_of_date: date, con) -> Dict[str, pd.Series]:
    if parent_key == "new_logo_consumption_revenue":
        gb = load_growth_bridge(as_of_date, con=con)
        rep = gb[gb["segment"].isin(_REP_SOLD_SEGMENTS)].groupby("month").agg(
            won=("new_business_won_count", "sum"),
            lost=("new_business_lost_count", "sum"),
            bookings=("new_logo_bookings_amount", "sum"))
        closed = (rep["won"] + rep["lost"]).replace(0, np.nan)
        return {
            "win_rate": rep["won"] / closed,
            "avg_initial_commitment": rep["bookings"] / rep["won"].replace(0, np.nan),
        }

    if parent_key == "activation":
        gb = load_growth_bridge(as_of_date, con=con)
        a = gb.dropna(subset=["signup_cohort_size"]).groupby("month").agg(
            activated=("activated_count", "sum"), cohort=("signup_cohort_size", "sum"))
        return {"onboarding_completion_rate": a["activated"] / a["cohort"].replace(0, np.nan)}

    if parent_key == "expansion_consumption_revenue":
        return {}

    if parent_key == "contraction_churned_revenue":
        return {"cyclical_vs_structural_usage_dip": _usage_dip_breadth_series(as_of_date, con)}

    if parent_key == "consumption_payback":
        eff = load_efficiency(as_of_date, con=con)
        dur = load_durability(as_of_date, con=con)
        pay = eff[eff["segment"].isin(_PAYBACK_BLEND_SEGMENTS)].merge(
            dur[["segment", "month", "starting_mrr"]], on=["segment", "month"], how="left")
        pay["weight"] = pay["starting_mrr"].fillna(0.0)

        def _wavg(col):
            return pay.dropna(subset=[col]).groupby("month").apply(
                lambda d: np.average(d[col], weights=d["weight"])
                if d["weight"].sum() > 0 else np.nan, include_groups=False)

        return {
            "cac_by_channel": _wavg("blended_cac"),
            "utilized_vs_committed_action_volume": _wavg("avg_utilized_action_margin_per_account"),
        }

    if parent_key == "onboarding_cs_efficiency":
        eff = load_efficiency(as_of_date, con=con)
        g = eff.groupby("month").agg(
            touches=("am_touchpoint_count", "sum"),
            actions=("automated_actions_delivered", "sum"))
        return {
            "am_touchpoint_volume": g["touches"].astype(float),
            "automated_action_volume": g["actions"].astype(float),
        }

    if parent_key in ("nrr", "grr"):
        dur = load_durability(as_of_date, con=con)
        cw = dur.groupby("month").agg(
            s=("starting_mrr", "sum"), e=("expansion_mrr", "sum"),
            c=("contraction_mrr", "sum"), ch=("churn_mrr", "sum"))
        start = cw["s"].replace(0, np.nan)
        if parent_key == "nrr":
            return {
                "nrr_expansion_rate": cw["e"] / start,
                "nrr_contraction_rate": cw["c"] / start,
                "nrr_churn_rate": cw["ch"] / start,
            }
        return {
            "grr_contraction_rate": cw["c"] / start,
            "grr_churn_rate": cw["ch"] / start,
        }

    if parent_key == "logo_retention":
        return {"tenure_at_churn": _tenure_at_churn_series(as_of_date, con)}

    # magic_number / am_efficiency and every Layer-2 node: no computable
    # children exist in any mart. Returning {} is the honest answer; the
    # tree's gap notes carry the reason.
    return {}


def _usage_dip_breadth_series(as_of_date: date, con) -> pd.Series:
    """Share of the month's active account population whose trailing-3-
    month mean actions_consumed sits below _USAGE_DIP_RATIO_THRESHOLD of
    that account's own cumulative-to-date mean. Grain: one value per
    month. Source mart: mart_account_health. Point-in-time clean: an
    account's baseline uses only its own months <= the month being
    evaluated, and the population is 'has a row this month', never the
    final customer_status."""
    ah = load_account_health(as_of_date, con=con)[["account_id", "month", "actions_consumed"]]
    ah = ah.sort_values(["account_id", "month"])
    grp = ah.groupby("account_id")["actions_consumed"]
    ah["trailing"] = grp.transform(
        lambda s: s.rolling(_USAGE_DIP_WINDOW_MONTHS, min_periods=_USAGE_DIP_WINDOW_MONTHS).mean())
    ah["baseline"] = grp.transform(lambda s: s.expanding().mean())
    ah = ah.dropna(subset=["trailing"])
    ah = ah[ah["baseline"] > 0]
    ah["is_dipping"] = ah["trailing"] < _USAGE_DIP_RATIO_THRESHOLD * ah["baseline"]
    g = ah.groupby("month").agg(dipping=("is_dipping", "sum"), n=("is_dipping", "size"))
    return (g["dipping"] / g["n"].replace(0, np.nan)).rename("usage_dip_breadth")


def _tenure_at_churn_series(as_of_date: date, con) -> pd.Series:
    """Mean account tenure (days) of the accounts that churned in each
    month. Grain: one value per month. Source mart: mart_account_health.
    Point-in-time clean: a churn in month M is an event already observed
    at M, so no future information is used."""
    ah = load_account_health(as_of_date, con=con)
    churned = ah[ah["churn_month"].notna() & (ah["month"] == ah["churn_month"])]
    return churned.groupby("churn_month")["account_tenure_days"].mean().rename("tenure_at_churn")


# =====================================================================
# Pure ranking logic -- the piece the synthetic test cases exercise
# =====================================================================

def _deviation_from_baseline(series: pd.Series, evaluation_month: pd.Timestamp,
                             baseline_months: int) -> dict:
    """Value at evaluation_month against the mean of the `baseline_months`
    months immediately before it. Deviation is expressed as a share of the
    baseline's magnitude so siblings on different scales are comparable;
    a z-score against the same window's standard deviation rides along as
    secondary context, never as the ranking key (a sibling that happens to
    be very stable would otherwise win every ranking on noise)."""
    series = series.dropna().sort_index()
    if evaluation_month not in series.index:
        return {"value": np.nan, "baseline": np.nan, "baseline_n": 0,
                "deviation_pct": np.nan, "deviation_z": np.nan}
    prior = series.loc[series.index < evaluation_month].tail(baseline_months)
    value = float(series.loc[evaluation_month])
    if len(prior) == 0:
        return {"value": value, "baseline": np.nan, "baseline_n": 0,
                "deviation_pct": np.nan, "deviation_z": np.nan}
    baseline = float(prior.mean())
    std = float(prior.std(ddof=1)) if len(prior) > 1 else np.nan
    dev = (value - baseline) / abs(baseline) if baseline != 0 else np.nan
    z = (value - baseline) / std if std and std > 0 else np.nan
    return {"value": value, "baseline": baseline, "baseline_n": int(len(prior)),
            "deviation_pct": dev, "deviation_z": z}


def rank_siblings(parent_key: str, series_by_key: Dict[str, pd.Series],
                  evaluation_month: pd.Timestamp,
                  baseline_months: int = _TRAILING_BASELINE_MONTHS) -> pd.DataFrame:
    """Ranks TRUE siblings of `parent_key` by absolute deviation from
    THEIR OWN trailing baseline -- not from the parent's plan, which
    would just repeat the parent's miss one layer down. Grain: one row per
    candidate child.

    Refuses any key that is not a registered child of `parent_key`, and
    any child the tree marks non-additive. That refusal is what keeps
    'the outlier among its siblings' from silently becoming 'the biggest
    mover anywhere in the tree'. Pure: takes series in, no I/O -- which
    is what lets the synthetic scenarios below drive it with hand-built
    data.

    The ranking key follows the parent's `sibling_comparison_basis`:
    % deviation where siblings carry different units, absolute deviation
    in the shared unit where they are additive components of the parent
    (NRR/GRR). Both columns are always populated; only which one sorts
    changes, and the chosen basis rides along in the output."""
    basis = _TREE[parent_key].sibling_comparison_basis
    valid = {n.key: n for n in ranking_siblings_of(parent_key)}
    rows = []
    for key, series in series_by_key.items():
        if key not in valid:
            raise ValueError(
                f"{key} is not a ranking-eligible child of {parent_key}; "
                f"eligible children are {sorted(valid)}")
        node = valid[key]
        stats = _deviation_from_baseline(series, evaluation_month, baseline_months)
        rows.append({
            "metric_key": key, "label": node.label, "layer": node.layer,
            "parent_key": node.parent_key, "computability": node.computability,
            "cross_reference_to": node.cross_reference_to,
            "comparison_basis": basis, **stats,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["abs_deviation_pct"] = df["deviation_pct"].abs()
    df["absolute_deviation"] = df["value"] - df["baseline"]
    df["abs_absolute_deviation"] = df["absolute_deviation"].abs()
    sort_key = "abs_absolute_deviation" if basis == "additive_share" else "abs_deviation_pct"
    df = df.sort_values(sort_key, ascending=False, na_position="last")
    df["rank"] = range(1, len(df) + 1)
    return df.reset_index(drop=True)


def _with_signal(parent_key: str, ranked: pd.DataFrame) -> pd.DataFrame:
    """Rows that actually carry a usable deviation under the parent's
    ranking basis -- a sibling whose trailing baseline is missing or
    degenerate is dropped rather than ranked on a NaN."""
    if ranked.empty:
        return ranked
    col = ("absolute_deviation"
           if _TREE[parent_key].sibling_comparison_basis == "additive_share"
           else "deviation_pct")
    return ranked[ranked[col].notna()]


def _sibling_coverage(parent_key: str, ranked: pd.DataFrame) -> dict:
    eligible = ranking_siblings_of(parent_key)
    covered = set(ranked["metric_key"]) if not ranked.empty else set()
    missing = [n for n in eligible if n.key not in covered]
    return {
        "eligible_siblings": len(eligible),
        "computable_siblings": len(covered),
        "missing_siblings": [{"metric_key": n.key, "label": n.label, "layer": n.layer,
                              "gap_note": n.gap_note} for n in missing],
        "is_genuine_sibling_comparison": len(covered) >= 2,
    }


# =====================================================================
# Drill-down assembly
# =====================================================================

@dataclass
class Drilldown:
    """One Layer-1 -> Layer-2 (-> Layer-3) drill-down. Every layer label
    is read off the tree, and the constructor re-asserts it -- a
    mislabelled record raises here rather than reaching a readout."""
    layer1_key: str
    layer2_key: Optional[str]
    layer3_keys: List[str]
    layer1_variance_pct: float
    layer1_mechanism: str
    sibling_ranking: pd.DataFrame
    sibling_coverage: dict
    layer3_status: str
    layer3_evidence: pd.DataFrame
    branch_max_depth_in_tree: int
    notes: List[str] = field(default_factory=list)

    def __post_init__(self):
        # raise, not assert: this re-check must hold even under python -O --
        # it is the last line of defense against a mislabelled record
        # reaching a readout, and that guarantee can't depend on assertions
        # being enabled.
        l1 = _TREE[self.layer1_key]
        if l1.layer != 1:
            raise ValueError(f"{l1.key} is layer {l1.layer}; a drill-down must head at Layer 1")
        if l1.parent_key is not None:
            raise ValueError(f"{l1.key} has a parent; it is not a Layer-1 node")
        if self.layer2_key is not None:
            l2 = _TREE[self.layer2_key]
            if l2.layer != 2:
                raise ValueError(f"{l2.key} is layer {l2.layer}, not 2")
            if l2.parent_key != self.layer1_key:
                raise ValueError(
                    f"{l2.key}'s parent is {l2.parent_key}, not {self.layer1_key} -- "
                    "a drill-down may only walk down its own branch")
            for k in self.layer3_keys:
                l3 = _TREE[k]
                if l3.layer != 3:
                    raise ValueError(f"{k} is layer {l3.layer}, not 3")
                if l3.parent_key != self.layer2_key:
                    raise ValueError(f"{k}'s parent is {l3.parent_key}, not {self.layer2_key}")
        elif self.layer3_keys:
            raise ValueError("no Layer-2 outlier means no Layer-3 evidence")

    def to_dict(self) -> dict:
        l1, l2 = _TREE[self.layer1_key], (_TREE[self.layer2_key] if self.layer2_key else None)
        return {
            "layer1": {"metric_key": l1.key, "label": l1.label, "layer": l1.layer,
                       "pillar": l1.pillar, "variance_pct": self.layer1_variance_pct,
                       "mechanism": self.layer1_mechanism},
            "layer2_outlier": None if l2 is None else {
                "metric_key": l2.key, "label": l2.label, "layer": l2.layer,
                "parent_key": l2.parent_key, "computability": l2.computability,
                "cross_reference_to": l2.cross_reference_to},
            "layer3_evidence": [{"metric_key": k, "label": _TREE[k].label, "layer": _TREE[k].layer,
                                 "parent_key": _TREE[k].parent_key} for k in self.layer3_keys],
            "layer3_status": self.layer3_status,
            "branch_max_depth_in_tree": self.branch_max_depth_in_tree,
            "sibling_coverage": self.sibling_coverage,
            "notes": self.notes,
        }


# Layer-3 status vocabulary.
L3_BRANCH_DEPTH_2 = "branch_depth_2"            # the tree stops at Layer 2 here
L3_NO_COMPUTABLE_DATA = "no_computable_layer3"  # tree has Layer 3; no mart does
L3_SURFACED = "surfaced"


def layer3_evidence(layer2_key: str, series_by_key: Dict[str, pd.Series],
                    evaluation_month: pd.Timestamp,
                    baseline_months: int = _TRAILING_BASELINE_MONTHS,
                    max_leaves: int = 2) -> dict:
    """1-2 supporting Layer-3 leaves under a flagged Layer-2 node, ranked
    the same way its parent's siblings were. Returns an explicit status
    rather than an empty list, because 'this branch is only two layers
    deep' and 'this branch has a Layer 3 but no mart computes it' are
    different facts and the readout should say which. A Layer 3 is never
    invented to fill either case."""
    node = _TREE[layer2_key]
    if node.layer != 2:
        raise ValueError(f"{layer2_key} is layer {node.layer}; Layer-3 evidence hangs off Layer 2")
    kids = children_of(layer2_key)
    if not kids:
        return {"status": L3_BRANCH_DEPTH_2, "keys": [], "ranking": pd.DataFrame(),
                "branch_max_depth_in_tree": 2}
    if not series_by_key:
        return {"status": L3_NO_COMPUTABLE_DATA, "keys": [], "ranking": pd.DataFrame(),
                "branch_max_depth_in_tree": 3,
                "missing": [{"metric_key": k.key, "label": k.label, "layer": 3,
                             "gap_note": k.gap_note} for k in kids]}
    ranked = _with_signal(layer2_key,
                          rank_siblings(layer2_key, series_by_key, evaluation_month, baseline_months))
    keys = list(ranked["metric_key"].head(max_leaves))
    return {"status": L3_SURFACED if keys else L3_NO_COMPUTABLE_DATA, "keys": keys,
            "ranking": ranked, "branch_max_depth_in_tree": 3}


# =====================================================================
# Layer-1 scorecard
# =====================================================================

def compute_layer1_scorecard(as_of_date: date, threshold: float = _VARIANCE_THRESHOLD,
                             con=None) -> pd.DataFrame:
    """All 11 Layer-1 nodes, unconditionally, for the last complete month
    at or before as_of_date -- the build spec's Layer-1 scorecard is shown
    every period whether or not anything moved. Grain: one row per
    Layer-1 metric. Source marts: mart_gtm_plan, mart_growth_bridge,
    mart_efficiency, mart_durability.

    Three variance mechanisms live side by side, each flagged in the
    `mechanism` column rather than blended into one number:
      * plan_diff -- the 8 metrics where both sides exist.
      * trailing_baseline -- Activation only, which has no plan row by
        design (mart_gtm_plan's header; design brief's '2.4d last month').
      * not_computable -- magic number and AM efficiency, whose actuals
        are undefined for want of any rep-cost/comp source. The plan value
        is still reported; the actual and the variance are None.
    """
    owns = con is None
    con = con or _connect()
    try:
        actuals = blend_layer1_actuals(as_of_date, con=con)
        plan = load_plan(as_of_date, con=con)
    finally:
        if owns:
            con.close()

    month = _evaluation_month(as_of_date)
    plan_wide = plan.pivot(index="month", columns="layer1_metric", values="plan_value")

    rows = []
    for node in layer1_nodes():
        plan_value = (float(plan_wide.loc[month, node.key])
                      if node.key in plan_wide.columns and month in plan_wide.index
                      and pd.notna(plan_wide.loc[month, node.key]) else None)
        actual = (float(actuals.loc[month, node.key])
                  if month in actuals.index and pd.notna(actuals.loc[month, node.key]) else None)

        baseline = baseline_variance = prior_month_value = None
        if node.key in actuals.columns:
            window = (_ACTIVATION_BASELINE_MONTHS if node.key == "activation"
                      else _TRAILING_BASELINE_MONTHS)
            stats = _deviation_from_baseline(actuals[node.key], month, window)
            baseline = None if pd.isna(stats["baseline"]) else stats["baseline"]
            baseline_variance = None if pd.isna(stats["deviation_pct"]) else stats["deviation_pct"]
            prior = actuals[node.key].dropna()
            prior = prior.loc[prior.index < month]
            prior_month_value = float(prior.iloc[-1]) if len(prior) else None

        if node.plan_comparability == NOT_COMPUTABLE:
            mechanism, variance = "not_computable", None
        elif node.plan_comparability == NO_PLAN_BY_DESIGN:
            mechanism, variance = "trailing_baseline", baseline_variance
        else:
            mechanism = "plan_diff"
            variance = ((actual - plan_value) / abs(plan_value)
                        if actual is not None and plan_value not in (None, 0) else None)

        if variance is None:
            status, breached = "Not computable", False
        elif abs(variance) <= threshold:
            status, breached = "On track", False
        else:
            favorable = (variance > 0) if node.favorable_direction == "higher" else (variance < 0)
            status, breached = ("Ahead" if favorable else "Behind"), True

        rows.append({
            "metric_key": node.key, "label": node.label, "layer": 1, "pillar": node.pillar,
            "month": month, "actual": actual, "plan": plan_value,
            "variance_pct": variance, "mechanism": mechanism,
            "trailing_baseline": baseline, "baseline_variance_pct": baseline_variance,
            "prior_month_value": prior_month_value,
            "favorable_direction": node.favorable_direction,
            "plan_comparability": node.plan_comparability,
            "plan_comparability_note": node.plan_comparability_note,
            "status": status, "breaches_threshold": breached,
        })
    return pd.DataFrame(rows)


# =====================================================================
# Watchlist
# =====================================================================

def build_watchlist(as_of_date: date, top_n: int = 25, con=None,
                    health_pipeline=None) -> pd.DataFrame:
    """Accounts whose composite health score breaches the risk threshold,
    ranked by ARR at risk. Grain: one row per flagged account_id. Source:
    analytics/health_score.py's already-built scored output (risk_tier /
    churn_probability -- no second risk model is fitted here) joined to
    mart_durability for segment-level ARR.

    ARR CAVEAT, stated rather than buried: no mart_* table exposes ARR at
    account grain. fact_revenue_monthly does, but it is a fact_* table,
    outside the mart_*-only read scope this Phase 4 code operates under.
    `est_arr_at_risk_usd` is therefore the account's SEGMENT-AVERAGE ARR
    for the evaluation month (mart_durability starting_mrr /
    starting_accounts x 12), not its own contracted ARR. It orders the
    watchlist correctly across segments and by risk within a segment, but
    it is an estimate and is named as one. Exposing account-grain ARR in
    mart_account_health (or a new mart) is a Phase 2 change that would
    make this exact.
    """
    from . import health_score  # local import: the watchlist is the only path that needs sklearn

    owns = con is None
    con = con or _connect()
    try:
        if health_pipeline is None:
            health_pipeline = health_score.train_churn_model(as_of_date, con=con, log=False)["pipeline"]
        scored = health_score.score_accounts(as_of_date, health_pipeline, con=con)
        dur = load_durability(as_of_date, con=con)
    finally:
        if owns:
            con.close()

    month = _evaluation_month(as_of_date)
    seg = dur[dur["month"] == month]
    seg_arr = (seg.set_index("segment")["starting_mrr"]
               / seg.set_index("segment")["starting_accounts"].replace(0, np.nan)) * 12

    flagged = scored[scored["risk_tier"] == "High"].copy()
    flagged["est_arr_at_risk_usd"] = flagged["segment"].map(seg_arr)
    flagged = flagged.sort_values(
        ["est_arr_at_risk_usd", "churn_probability"], ascending=[False, False])
    cols = ["account_id", "segment", "risk_tier", "churn_probability", "health_score",
            "est_arr_at_risk_usd", "scoring_date"]
    return flagged[cols].head(top_n).reset_index(drop=True)


# =====================================================================
# End-to-end run
# =====================================================================

def run_diagnostic(as_of_date: date, threshold: float = _VARIANCE_THRESHOLD,
                   baseline_months: int = _TRAILING_BASELINE_MONTHS,
                   include_watchlist: bool = True, watchlist_top_n: int = 25) -> dict:
    """Full engine run for one evaluation period: the 11-node Layer-1
    scorecard, a drill-down for every node that breached the threshold,
    and the watchlist. Grain: one evaluation month. Source marts:
    mart_gtm_plan, mart_growth_bridge, mart_efficiency, mart_durability,
    mart_account_health. Deterministic -- no stochastic step, so no seed
    applies (the watchlist's model is seeded inside
    analytics/health_score.py)."""
    con = _connect()
    try:
        scorecard = compute_layer1_scorecard(as_of_date, threshold=threshold, con=con)
        month = _evaluation_month(as_of_date)
        drilldowns = []
        for _, row in scorecard[scorecard["breaches_threshold"]].iterrows():
            drilldowns.append(_build_drilldown(row, as_of_date, month, baseline_months, con))
        watchlist = build_watchlist(as_of_date, top_n=watchlist_top_n, con=con) \
            if include_watchlist else pd.DataFrame()
    finally:
        con.close()

    return {
        "as_of_date": as_of_date,
        "evaluation_month": month,
        "threshold": threshold,
        "baseline_months": baseline_months,
        "layer1_scorecard": scorecard,
        "drilldowns": drilldowns,
        "watchlist": watchlist,
        "coverage": _coverage_report(),
        "data_window": _data_window_check(as_of_date, month),
    }


def _data_window_check(as_of_date: date, month: pd.Timestamp) -> dict:
    """Flags the one evaluation month this simulation's data cannot be
    read at face value: the final month of the 36-month window. Every
    account still on the books has its last observed month bucketed as
    contraction there, Enterprise marketing spend is absent, and Action
    volume is partial -- an end-of-window truncation artifact, not a
    business event. Surfaced as a warning rather than silently excluded,
    so a caller who genuinely wants that month gets it with the caveat
    attached."""
    con = _connect()
    try:
        last = pd.Timestamp(con.execute(
            "select max(month) from main_marts.mart_growth_bridge").fetchone()[0])
    finally:
        con.close()
    is_last = month == last
    return {
        "last_month_in_marts": last,
        "evaluation_month": month,
        "evaluation_month_is_last_month_in_window": is_last,
        "truncation_warning": (
            "The evaluation month is the final month of the simulated 36-month window. "
            "Contraction is inflated (every still-active account's last observed month "
            "lands in the contraction bucket), Enterprise marketing spend is missing so "
            "blended CAC is incomplete, and Action volume is partial. Variances for this "
            "month are truncation artifacts, not business signal -- prefer the prior "
            "month as the last representative evaluation period."
        ) if is_last else None,
    }


def _build_drilldown(scorecard_row, as_of_date, month, baseline_months, con) -> Drilldown:
    l1_key = scorecard_row["metric_key"]
    l2_series = _build_child_series(l1_key, as_of_date, con)
    ranked = rank_siblings(l1_key, l2_series, month, baseline_months) if l2_series \
        else pd.DataFrame()
    coverage = _sibling_coverage(l1_key, _with_signal(l1_key, ranked))
    notes = []
    if scorecard_row["plan_comparability"] == CAVEATED:
        notes.append(scorecard_row["plan_comparability_note"])

    if l1_key in ("nrr", "grr"):
        notes.append(
            f"Grain note: {l1_key}'s Layer-1 figure is the trailing-12-month compounded rate "
            "(to match mart_gtm_plan's annual-equivalent units), while its Layer-2 drivers are "
            "read at monthly grain -- the grain at which a driver actually moves. A driver can "
            "therefore point the opposite way to the annualised parent in any single month; "
            "read the driver ranking as 'what moved this month', not as a decomposition of the "
            "twelve-month figure.")

    scored = _with_signal(l1_key, ranked)
    if scored.empty:
        notes.append(
            f"No Layer-2 child of {l1_key} has a mart-computable actual with a usable "
            "trailing baseline, so no outlier can be identified. The Layer-1 variance "
            "stands on its own; see sibling_coverage for which children are missing and why.")
        return Drilldown(
            layer1_key=l1_key, layer2_key=None, layer3_keys=[],
            layer1_variance_pct=scorecard_row["variance_pct"],
            layer1_mechanism=scorecard_row["mechanism"],
            sibling_ranking=ranked, sibling_coverage=coverage,
            layer3_status=L3_NO_COMPUTABLE_DATA, layer3_evidence=pd.DataFrame(),
            branch_max_depth_in_tree=branch_max_depth(l1_key), notes=notes)

    l2_key = scored.iloc[0]["metric_key"]
    if not coverage["is_genuine_sibling_comparison"]:
        notes.append(
            f"Only {coverage['computable_siblings']} of {coverage['eligible_siblings']} "
            f"Layer-2 siblings under {l1_key} have a mart-computable actual, so this is a "
            "single-candidate read rather than a genuine outlier selection among siblings.")
    l3_series = _build_child_series(l2_key, as_of_date, con)
    l3 = layer3_evidence(l2_key, l3_series, month, baseline_months)
    if l3["status"] == L3_BRANCH_DEPTH_2:
        notes.append(f"{l2_key} has no Layer-3 children in the metric tree -- this branch is "
                     "genuinely two layers deep. No Layer 3 is fabricated to force symmetry.")
    elif l3["status"] == L3_NO_COMPUTABLE_DATA:
        notes.append(f"{l2_key} does have Layer-3 children in the tree, but none is computable "
                     "from any mart_* table; see layer3_evidence's missing list for the reasons.")

    return Drilldown(
        layer1_key=l1_key, layer2_key=l2_key, layer3_keys=l3["keys"],
        layer1_variance_pct=scorecard_row["variance_pct"],
        layer1_mechanism=scorecard_row["mechanism"],
        sibling_ranking=ranked, sibling_coverage=coverage,
        layer3_status=l3["status"], layer3_evidence=l3.get("ranking", pd.DataFrame()),
        branch_max_depth_in_tree=branch_max_depth(l1_key), notes=notes)


def _coverage_report() -> pd.DataFrame:
    """One row per Layer-1 node: how much of its branch this engine can
    actually see from the mart_* tables. Published with every run so a
    thin drill-down is visibly a data gap rather than a quiet 'nothing to
    see here'."""
    rows = []
    for node in layer1_nodes():
        sibs = ranking_siblings_of(node.key)
        computable = [s for s in sibs if s.computability in (COMPUTABLE, PARTIAL)]
        rows.append({
            "metric_key": node.key, "label": node.label, "layer": 1, "pillar": node.pillar,
            "layer1_actual_computable": node.computability != NOT_COMPUTABLE,
            "plan_comparability": node.plan_comparability,
            "layer2_siblings_in_tree": len(sibs),
            "layer2_siblings_computable": len(computable),
            "branch_max_depth_in_tree": branch_max_depth(node.key),
            "layer3_computable_anywhere": any(
                c.computability in (COMPUTABLE, PARTIAL)
                for s in sibs for c in children_of(s.key)),
        })
    return pd.DataFrame(rows)


def measure_threshold_selectivity(as_of_date: date,
                                  candidate_thresholds: Sequence[float] = (0.05, 0.08, 0.10,
                                                                           0.15, 0.20, 0.30, 0.50),
                                  months: int = 12, con=None) -> pd.DataFrame:
    """Evidence for build spec Section 7's open question on the +/-8%
    threshold: how many Layer-1 nodes each candidate threshold would have
    flagged, per month, over the trailing `months`. Grain: one row per
    candidate threshold. Produces the number to argue from instead of
    adjusting the threshold unilaterally -- the design brief's sample
    readout drilled into 3 of 11 nodes, which is the cadence to compare
    against."""
    owns = con is None
    con = con or _connect()
    try:
        actuals = blend_layer1_actuals(as_of_date, con=con)
        plan = load_plan(as_of_date, con=con)
    finally:
        if owns:
            con.close()

    plan_wide = plan.pivot(index="month", columns="layer1_metric", values="plan_value")
    end = _evaluation_month(as_of_date)
    eval_months = [end - pd.DateOffset(months=i) for i in range(months)]
    keys = [n.key for n in layer1_nodes()
            if n.plan_comparability in (COMPARABLE, CAVEATED)]

    variances = []
    for m in eval_months:
        if m not in actuals.index or m not in plan_wide.index:
            continue
        for k in keys:
            a, p = actuals.loc[m, k], plan_wide.loc[m, k] if k in plan_wide.columns else np.nan
            if pd.notna(a) and pd.notna(p) and p != 0:
                variances.append({"month": m, "metric_key": k, "variance_pct": (a - p) / abs(p)})
    v = pd.DataFrame(variances)

    rows = []
    for t in candidate_thresholds:
        flagged = v[v["variance_pct"].abs() > t]
        per_month = flagged.groupby("month").size().reindex(
            sorted(v["month"].unique()), fill_value=0) if not v.empty else pd.Series(dtype=float)
        rows.append({
            "threshold": t,
            "metrics_evaluated_per_month": len(keys),
            "mean_flagged_per_month": float(per_month.mean()) if len(per_month) else np.nan,
            "max_flagged_in_a_month": int(per_month.max()) if len(per_month) else 0,
            "share_of_metric_months_flagged": (len(flagged) / len(v)) if len(v) else np.nan,
        })
    return pd.DataFrame(rows)


# =====================================================================
# TEST SUPPORT -- synthetic scenarios for analytics-model-validator
#
# A structural/logic artifact has no AUC, no coefficient table and no R²
# to validate against (.claude/skills/analytics-engineering-conventions,
# "Structural/logic artifacts"). Its correctness check is exactly this:
# hand-constructed cases with a single unambiguous true answer, run
# through the same rank_siblings() / layer3_evidence() / Drilldown path
# the real run uses, with the expected answer declared alongside.
# analytics-model-validator runs run_synthetic_scenarios() and confirms
# every case resolves to its declared expectation.
# =====================================================================

def _synthetic_series(evaluation_month: pd.Timestamp, baseline: float,
                      final_deviation_pct: float, n_baseline: int = _TRAILING_BASELINE_MONTHS,
                      jitter: Sequence[float] = ()) -> pd.Series:
    """A flat (optionally lightly jittered) trailing baseline followed by
    one month deviating by exactly `final_deviation_pct`. Deterministic --
    the jitter is a caller-supplied literal sequence, not a random draw,
    so no seed is needed and every scenario is byte-reproducible."""
    months = [evaluation_month - pd.DateOffset(months=i) for i in range(n_baseline, 0, -1)]
    values = [baseline * (1 + (jitter[i] if i < len(jitter) else 0.0)) for i in range(n_baseline)]
    mean_baseline = float(np.mean(values))
    months.append(evaluation_month)
    values.append(mean_baseline * (1 + final_deviation_pct))
    return pd.Series(values, index=pd.DatetimeIndex(months))


_SYNTHETIC_MONTH = pd.Timestamp("2025-06-01")

SYNTHETIC_SCENARIOS = [
    {
        "name": "new_logo_miss_win_rate_outlier_with_layer3",
        "description": (
            "New logo consumption revenue (Layer 1, Growth) misses plan by -18%. Among its "
            "true Layer-2 siblings, win rate sits 22% below its own trailing baseline while "
            "avg initial commitment is within 1.5%. Win rate has real Layer-3 children in the "
            "tree, so four leaves are supplied and the engine must surface the two largest. "
            "This is the design brief's own worked example, made testable."),
        "layer1_key": "new_logo_consumption_revenue",
        "layer1_variance_pct": -0.18,
        "layer2_series": {
            "win_rate": _synthetic_series(_SYNTHETIC_MONTH, 0.31, -0.22,
                                          jitter=(0.01, -0.01, 0.02, -0.02, 0.0, 0.01, -0.01, 0.0)),
            "avg_initial_commitment": _synthetic_series(_SYNTHETIC_MONTH, 78_000.0, -0.015,
                                                        jitter=(0.02, -0.02, 0.01, -0.01, 0.0, 0.0, 0.01, -0.01)),
        },
        "layer3_series": {
            "poc_pass_rate": _synthetic_series(_SYNTHETIC_MONTH, 0.68, -0.21),
            "loss_reason_mix": _synthetic_series(_SYNTHETIC_MONTH, 0.35, 0.14),
            "stage_to_stage_conversion": _synthetic_series(_SYNTHETIC_MONTH, 0.44, -0.01),
            "rep_capacity_ramp_mix": _synthetic_series(_SYNTHETIC_MONTH, 0.60, 0.005),
        },
        "expected_layer2_key": "win_rate",
        "expected_layer3_keys": ["poc_pass_rate", "loss_reason_mix"],
        "expected_layer3_status": L3_SURFACED,
        "expected_branch_max_depth": 3,
    },
    {
        "name": "consumption_payback_cac_leg_two_layer_branch",
        "description": (
            "Consumption payback (Layer 1, Efficiency) runs 20% longer than plan. The CAC leg "
            "is 25% above its own trailing baseline; the utilised-Action-margin leg is within "
            "1%. This branch is genuinely TWO layers deep -- the design brief says so in as "
            "many words ('tree only goes to Layer 2 here -- don't invent a Layer 3'). The "
            "engine must return layer3_status='branch_depth_2' with no leaves, not a "
            "manufactured third layer."),
        "layer1_key": "consumption_payback",
        "layer1_variance_pct": 0.20,
        "layer2_series": {
            "cac_by_channel": _synthetic_series(_SYNTHETIC_MONTH, 1_400.0, 0.25,
                                                jitter=(0.03, -0.03, 0.02, -0.02, 0.01, -0.01, 0.0, 0.0)),
            "utilized_vs_committed_action_volume": _synthetic_series(
                _SYNTHETIC_MONTH, 9_500.0, 0.01,
                jitter=(0.01, -0.01, 0.0, 0.01, -0.01, 0.0, 0.0, 0.0)),
        },
        "layer3_series": {},
        "expected_layer2_key": "cac_by_channel",
        "expected_layer3_keys": [],
        "expected_layer3_status": L3_BRANCH_DEPTH_2,
        "expected_branch_max_depth": 2,
    },
    {
        "name": "onboarding_cs_efficiency_denominator_outlier",
        "description": (
            "Onboarding/CS efficiency (Layer 1, Efficiency) worsens 14% against plan. The "
            "intuitive culprit -- AM touchpoint volume, the ratio's numerator -- is within 2% "
            "of its baseline; the real outlier is the denominator, automated Action volume "
            "delivered, down 13%. Confirms the engine ranks by each sibling's own deviation "
            "rather than defaulting to the numerator. Also a two-layer branch."),
        "layer1_key": "onboarding_cs_efficiency",
        "layer1_variance_pct": 0.14,
        "layer2_series": {
            "am_touchpoint_volume": _synthetic_series(_SYNTHETIC_MONTH, 560.0, 0.02,
                                                      jitter=(0.02, -0.02, 0.01, -0.01, 0.0, 0.0, 0.01, -0.01)),
            "automated_action_volume": _synthetic_series(_SYNTHETIC_MONTH, 9.2e7, -0.13,
                                                         jitter=(0.01, -0.01, 0.02, -0.02, 0.0, 0.01, -0.01, 0.0)),
        },
        "layer3_series": {},
        "expected_layer2_key": "automated_action_volume",
        "expected_layer3_keys": [],
        "expected_layer3_status": L3_BRANCH_DEPTH_2,
        "expected_branch_max_depth": 2,
    },
    {
        "name": "true_siblings_only_guard",
        "description": (
            "The named failure mode, tested directly. Contraction + churned revenue (Layer 1, "
            "Growth) breaches. A Layer-2 node from a DIFFERENT parent (win rate, a child of "
            "New logo) is deviating far harder than anything on this branch. The engine must "
            "refuse it outright -- rank_siblings() raises rather than ranking a non-sibling -- "
            "and, on the branch's own candidates, pick the real one."),
        "layer1_key": "contraction_churned_revenue",
        "layer1_variance_pct": 0.19,
        "layer2_series": {
            "cyclical_vs_structural_usage_dip": _synthetic_series(_SYNTHETIC_MONTH, 0.12, 0.34),
        },
        "intruder_series": {
            "win_rate": _synthetic_series(_SYNTHETIC_MONTH, 0.31, -0.60),
        },
        "layer3_series": {},
        "expected_layer2_key": "cyclical_vs_structural_usage_dip",
        "expected_layer3_keys": [],
        "expected_layer3_status": L3_NO_COMPUTABLE_DATA,
        "expected_branch_max_depth": 3,
        "expects_intruder_rejected": True,
    },
    {
        "name": "nrr_additive_share_basis",
        "description": (
            "NRR (Layer 1, Durability) breaches. Its three Layer-2 drivers are additive "
            "components of one identity, all expressed as a share of starting revenue. Churn "
            "swings -40% in RELATIVE terms but only -0.0006 of starting revenue in absolute "
            "terms; contraction moves a smaller +13% relative but +0.0060 absolute -- ten times "
            "more of NRR's actual movement. Ranking on % deviation would name churn, which is "
            "the wrong answer. The engine must use the additive_share basis here and name "
            "contraction."),
        "layer1_key": "nrr",
        "layer1_variance_pct": -0.11,
        "layer2_series": {
            "nrr_churn_rate": _synthetic_series(_SYNTHETIC_MONTH, 0.0015, -0.40),
            "nrr_contraction_rate": _synthetic_series(_SYNTHETIC_MONTH, 0.0452, 0.1327),
            "nrr_expansion_rate": _synthetic_series(_SYNTHETIC_MONTH, 0.1034, -0.02),
        },
        "layer3_series": {},
        "expected_layer2_key": "nrr_contraction_rate",
        "expected_layer3_keys": [],
        "expected_layer3_status": L3_BRANCH_DEPTH_2,
        "expected_branch_max_depth": 2,
    },
]


def run_synthetic_scenario(scenario: dict, baseline_months: int = _TRAILING_BASELINE_MONTHS) -> dict:
    """Runs one hand-constructed scenario through the same ranking,
    Layer-3 and Drilldown code the real engine uses, and checks it against
    the scenario's declared expected answer. Returns a pass/fail record
    with the observed result, for analytics-model-validator to assert on."""
    month = _SYNTHETIC_MONTH
    l1_key = scenario["layer1_key"]
    failures = []

    intruder_rejected = None
    if scenario.get("expects_intruder_rejected"):
        try:
            rank_siblings(l1_key, {**scenario["layer2_series"], **scenario["intruder_series"]},
                          month, baseline_months)
            intruder_rejected = False
            failures.append(
                "rank_siblings accepted a non-sibling candidate; "
                "'outlier among its siblings' is not being enforced")
        except ValueError:
            intruder_rejected = True

    ranked = _with_signal(l1_key, rank_siblings(l1_key, scenario["layer2_series"],
                                                month, baseline_months))
    observed_l2 = ranked.iloc[0]["metric_key"] if not ranked.empty else None
    if observed_l2 != scenario["expected_layer2_key"]:
        failures.append(f"Layer-2 outlier: expected {scenario['expected_layer2_key']}, got {observed_l2}")

    l3 = layer3_evidence(observed_l2, scenario["layer3_series"], month, baseline_months) \
        if observed_l2 else {"status": L3_NO_COMPUTABLE_DATA, "keys": [],
                             "ranking": pd.DataFrame(), "branch_max_depth_in_tree": 0}
    if l3["status"] != scenario["expected_layer3_status"]:
        failures.append(f"Layer-3 status: expected {scenario['expected_layer3_status']}, got {l3['status']}")
    if l3["keys"] != scenario["expected_layer3_keys"]:
        failures.append(f"Layer-3 evidence: expected {scenario['expected_layer3_keys']}, got {l3['keys']}")
    if branch_max_depth(l1_key) != scenario["expected_branch_max_depth"]:
        failures.append(
            f"branch depth: expected {scenario['expected_branch_max_depth']}, got {branch_max_depth(l1_key)}")

    drilldown = Drilldown(
        layer1_key=l1_key, layer2_key=observed_l2, layer3_keys=l3["keys"],
        layer1_variance_pct=scenario["layer1_variance_pct"], layer1_mechanism="synthetic",
        sibling_ranking=ranked, sibling_coverage=_sibling_coverage(l1_key, ranked),
        layer3_status=l3["status"], layer3_evidence=l3.get("ranking", pd.DataFrame()),
        branch_max_depth_in_tree=branch_max_depth(l1_key))
    emitted = drilldown.to_dict()
    if emitted["layer1"]["layer"] != 1:
        failures.append("emitted Layer-1 record is not labelled layer 1")
    if emitted["layer2_outlier"] and emitted["layer2_outlier"]["layer"] != 2:
        failures.append("emitted Layer-2 record is not labelled layer 2")
    for leaf in emitted["layer3_evidence"]:
        if leaf["layer"] != 3:
            failures.append(f"emitted Layer-3 record {leaf['metric_key']} is not labelled layer 3")

    return {
        "name": scenario["name"], "description": scenario["description"],
        "expected_layer2_key": scenario["expected_layer2_key"], "observed_layer2_key": observed_l2,
        "expected_layer3_keys": scenario["expected_layer3_keys"], "observed_layer3_keys": l3["keys"],
        "expected_layer3_status": scenario["expected_layer3_status"], "observed_layer3_status": l3["status"],
        "branch_max_depth": branch_max_depth(l1_key), "intruder_rejected": intruder_rejected,
        "sibling_ranking": ranked, "drilldown": emitted,
        "passed": not failures, "failures": failures,
    }


def run_synthetic_scenarios(baseline_months: int = _TRAILING_BASELINE_MONTHS) -> List[dict]:
    """Every scenario in SYNTHETIC_SCENARIOS. This is the artifact's
    correctness check in full -- there is no statistical package for a
    structural/logic artifact."""
    return [run_synthetic_scenario(s, baseline_months) for s in SYNTHETIC_SCENARIOS]


# =====================================================================
# Build-time validation
# =====================================================================

def run_build_time_validation(as_of_date: date, threshold: float = _VARIANCE_THRESHOLD,
                              log: bool = True) -> dict:
    """Everything analytics-model-validator needs to independently
    re-check this artifact: the synthetic-scenario results (the
    correctness claim), the real-data run, branch coverage, and the
    threshold-selectivity evidence for build spec Section 7's open
    question. Logs only the scalars that are genuine correctness/coverage
    claims -- there is no AUC, coefficient table or confusion matrix here
    to log, by the nature of a structural artifact."""
    scenarios = run_synthetic_scenarios()
    result = run_diagnostic(as_of_date, threshold=threshold)
    selectivity = measure_threshold_selectivity(as_of_date)
    coverage = result["coverage"]

    if log:
        log_performance(_MODEL_NAME, as_of_date, "synthetic_scenarios_total", float(len(scenarios)))
        log_performance(_MODEL_NAME, as_of_date, "synthetic_scenarios_passed",
                        float(sum(s["passed"] for s in scenarios)))
        log_performance(_MODEL_NAME, as_of_date, "variance_threshold", float(threshold))
        log_performance(_MODEL_NAME, as_of_date, "layer1_nodes_total", float(len(layer1_nodes())))
        log_performance(_MODEL_NAME, as_of_date, "layer1_nodes_plan_comparable",
                        float((coverage["plan_comparability"].isin([COMPARABLE, CAVEATED])).sum()))
        log_performance(_MODEL_NAME, as_of_date, "layer1_nodes_actual_not_computable",
                        float((~coverage["layer1_actual_computable"]).sum()))
        log_performance(_MODEL_NAME, as_of_date, "layer1_nodes_breaching_threshold",
                        float(result["layer1_scorecard"]["breaches_threshold"].sum()))
        log_performance(_MODEL_NAME, as_of_date, "layer2_siblings_in_tree",
                        float(coverage["layer2_siblings_in_tree"].sum()))
        log_performance(_MODEL_NAME, as_of_date, "layer2_siblings_computable",
                        float(coverage["layer2_siblings_computable"].sum()))
        log_performance(_MODEL_NAME, as_of_date, "drilldowns_with_genuine_sibling_comparison",
                        float(sum(d.sibling_coverage["is_genuine_sibling_comparison"]
                                  for d in result["drilldowns"])))

    return {"synthetic_scenarios": scenarios, "diagnostic": result,
            "threshold_selectivity": selectivity, "coverage": coverage}


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    # 2025-11-30, not 2025-12-31: the simulation's final month carries an
    # end-of-window truncation artifact (see _data_window_check), so
    # 2025-11 is the last representative evaluation period.
    AS_OF = date(2025, 11, 30)
    out = run_build_time_validation(AS_OF)

    print("=== Synthetic scenarios (the correctness check for a structural artifact) ===")
    for s in out["synthetic_scenarios"]:
        print(f"[{'PASS' if s['passed'] else 'FAIL'}] {s['name']}: "
              f"L2={s['observed_layer2_key']} L3={s['observed_layer3_keys']} "
              f"status={s['observed_layer3_status']} depth={s['branch_max_depth']}")
        for f in s["failures"]:
            print(f"        {f}")

    d = out["diagnostic"]
    print(f"\n=== Layer-1 scorecard -- {d['evaluation_month']:%Y-%m} (threshold +/-{d['threshold']:.0%}) ===")
    sc = d["layer1_scorecard"]
    print(sc[["pillar", "metric_key", "actual", "plan", "variance_pct", "mechanism",
              "status", "breaches_threshold"]].to_string(index=False))

    print("\n=== Drill-downs ===")
    for dd in d["drilldowns"]:
        print(f"\n{dd.layer1_key} (Layer 1, variance {dd.layer1_variance_pct:+.1%}, "
              f"{dd.layer1_mechanism})")
        if dd.sibling_ranking.empty:
            print("  no Layer-2 candidates")
        else:
            print(dd.sibling_ranking[["rank", "metric_key", "layer", "value", "baseline",
                                      "deviation_pct", "absolute_deviation",
                                      "comparison_basis", "computability"]].to_string(index=False))
        print(f"  -> Layer-2 outlier: {dd.layer2_key} | Layer-3: {dd.layer3_keys} "
              f"({dd.layer3_status}, branch depth {dd.branch_max_depth_in_tree})")
        for n in dd.notes:
            print(f"     note: {n[:160]}")

    print("\n=== Branch coverage ===")
    print(out["coverage"].to_string(index=False))

    print("\n=== Threshold selectivity (evidence for build spec Section 7) ===")
    print(out["threshold_selectivity"].to_string(index=False))

    print("\n=== Watchlist (top 10) ===")
    print(d["watchlist"].head(10).to_string(index=False))
