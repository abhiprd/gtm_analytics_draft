"""Variance-diagnostic engine -- grain: one row per Layer-1 metric per
evaluation month (company-wide/blended, matching what the Layer-1
scorecard displays); source marts: mart_gtm_plan (plan side),
mart_growth_bridge / mart_efficiency / mart_durability (actuals side, all
segment x month, blended here), mart_deal_funnel / mart_workflow_chain_health /
mart_consumption_utilization (the deal-level, workflow-chain and overage
Layer-2/3 evidence), mart_account_health (Layer-2 evidence, the account-health
inputs and the watchlist population), and, for Pipeline generated and its channel
legs, fact_leads / fact_campaign_engagement_events read through
analytics/marketing_attribution.py's validated lead panel (never a second
copy of that logic).

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

PERSISTENCE -- IS IT WEATHER OR A TREND?
-----------------------------------------
Each drill-down also carries a `persistence` record (compute_persistence()):
how many consecutive months, ending at the evaluation month, the SAME Layer-2
driver has been the largest adverse outlier against its own trailing baseline,
among at least 2 computable siblings. The record is flagged when that streak
reaches K_PERSISTENCE (PROPOSED, not yet confirmed) and is `not_applicable` for
a single-candidate read, a branch with no outlier, a driver with no defined
adverse direction, or the truncated final month. It is computed here, not in
the readout, and validated by a known-streak scenario suite
(run_persistence_scenarios) and a real-data profile
(measure_persistence_selectivity) whose result is recorded as measured in the
methods doc.

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
import math
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, Optional, Sequence

import duckdb
import numpy as np
import pandas as pd

from . import marketing_attribution as ma
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
# conversions. Both of these legs of the New-logo decomposition use the same
# population so the tree's multiplicative identity is not broken by
# mixing scopes. Pipeline generated is deliberately NOT forced onto this
# scope: it counts converted inbound leads company-wide (see
# PIPELINE_GENERATED_SCOPE_NOTE), so it competes with these two legs in the
# sibling ranking but is never multiplied with them.
_REP_SOLD_SEGMENTS = ("Commercial", "Enterprise")

# Segments mart_gtm_plan's consumption-payback anchor was blended over.
# generators/gtm_plan.py's _blend() renormalises the benchmark reference
# table over "whichever segments the benchmark table actually covers (it
# marks SMB 'n/a' for magic number and payback)". The actuals side is
# blended over the same two segments so plan and actual describe the same
# population.
_PAYBACK_BLEND_SEGMENTS = ("Commercial", "Enterprise")

# Segments Magic number and AM efficiency are blended over: the ones with rep
# cost and an AM (SMB is no-touch; the benchmark table marks it n/a for
# magic number, and AM efficiency has no denominator there).
_COST_BLEND_SEGMENTS = ("Commercial", "Enterprise")

# PROPOSED, NOT YET CONFIRMED. The persistence flag (see compute_persistence()
# below) fires when the SAME Layer-2 driver has been the adverse outlier
# against its own trailing baseline for at least this many consecutive months,
# counting back from the evaluation month. Two is the smallest streak that
# separates "persisting" from "a single month's noise" and the owner's stated
# decision for the "weather versus decision" question; it is not derived from a
# loss function, and the real-data selectivity it produces is measured by
# measure_persistence_selectivity() and recorded in
# docs/acme-corp-analytics-methods.md rather than tuned to a target rate.
K_PERSISTENCE = 2


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
    # Long-form version of plan_comparability_note (every disclosed fact);
    # the short note is what a list view shows.
    plan_comparability_detail: Optional[str] = None
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
        sibling_comparison_basis="relative_deviation", plan_comparability_detail=None):
    return _register(MetricNode(
        key=key, label=label, layer=1, pillar=pillar, parent_key=None,
        computability=computability, gap_note=gap_note,
        favorable_direction=favorable_direction,
        plan_comparability=plan_comparability,
        plan_comparability_note=plan_comparability_note,
        plan_comparability_detail=plan_comparability_detail,
        sibling_comparison_basis=sibling_comparison_basis,
    ))


def _child(key, label, parent_key, computability=NOT_COMPUTABLE, gap_note=None,
           is_ranking_sibling=True, cross_reference_to=None,
           sibling_comparison_basis="relative_deviation"):
    parent = _TREE[parent_key]
    return _register(MetricNode(
        key=key, label=label, layer=parent.layer + 1, pillar=parent.pillar,
        parent_key=parent_key, computability=computability, gap_note=gap_note,
        is_ranking_sibling=is_ranking_sibling, cross_reference_to=cross_reference_to,
        sibling_comparison_basis=sibling_comparison_basis,
    ))


# Pipeline generated is computed by analytics/marketing_attribution.py from
# fact_leads / fact_campaign_engagement_events (its validated lead panel);
# this engine reads that computation rather than re-deriving it. The scope
# note travels with every drill-down that ranks the node, because its
# population is not the one Win rate and Avg initial commitment use.
PIPELINE_GENERATED_SCOPE_NOTE = (
    "Pipeline generated counts inbound-sourced leads converting to signup (PQL) across all "
    "three segments; Win rate and Avg initial commitment cover Commercial and Enterprise "
    "opportunities. Each sibling is ranked against its own trailing baseline and the three "
    "are not multiplied into a New logo figure."
)
PIPELINE_GENERATED_SCOPE_DETAIL = (
    "Pipeline generated is read from the marketing attribution artifact as a monthly flow: "
    "leads that converted to a PQL (this funnel's signup) in the month, by the lead's "
    "sourcing sub-channel (organic, paid, community), company-wide. It covers "
    "inbound-marketing-sourced accounts only, across all three segments (SMB included), "
    "and is indexed by conversion month rather than lead-creation month so the latest "
    "month is not right-censored. Win rate and Avg initial commitment are measured on "
    "rep-sold Commercial and Enterprise opportunities, a different population and unit, so "
    "Pipeline generated is ranked against its own trailing baseline like any sibling and "
    "the three legs are not multiplied into a New logo figure (the governance module's "
    "New-logo product edge is Not computable for the same reason)."
)
_NO_MQL_SAL_LIFECYCLE = (
    "No MQL or SAL stage exists in the lead data: leads carry creation and conversion "
    "dates, a score and a converted flag, with no stage or status field, so the "
    "marketing-to-sales handoff is not an observable event. Leads and campaign touches "
    "measure conversion to signup, not handoff."
)
_NO_MQL_RESPONSE_SLA = (
    "Needs an MQL timestamp and a first-sales-touch timestamp per lead. Neither exists: the "
    "only lead lifecycle timestamp is the signup date, and sales activities are keyed to "
    "opportunity and contact with no lead id, so a touch cannot be tied to the lead that "
    "sourced it. Days to conversion measures lead-to-signup time, not response time, and is "
    "not substituted."
)
_NO_MQL_SAL_ACCEPTANCE = (
    "Needs an MQL and an SAL stage, or an accept/reject disposition, per lead. The lead "
    "data records only converted or not, which is the lead-to-PQL rate already inside "
    "Pipeline generated, not an MQL-to-SAL acceptance rate."
)
_NO_LEAD_RECYCLING_HISTORY = (
    "Needs lead status history (a lead returning to nurture and re-qualifying). Each lead "
    "has one creation date and no status changes; lead re-scoring history carries no "
    "nurture or recycling disposition, so a re-score is not treated as a re-qualification."
)
_STAGE_CONVERSION_DEGENERATE = (
    "Degenerate by construction: every new-business deal logs every stage of its segment's "
    "path (SAL, SQO, Proposal/Negotiation, plus POC for Enterprise), won or lost, so the "
    "share of deals advancing at each hop is 100% in every month and carries no variance "
    "signal. Deals differ in how long they spend in each stage, not in whether they reach "
    "it. Same treatment as Onboarding completion rate, which is 1.0 in every month."
)
_NO_LOUD_SILENT_CHURN_FLAG = (
    "Needs each churn classified as an explicit cancellation (loud) or a non-renewal "
    "(silent). No record carries that classification: subscription status is "
    "active, churned, renewed, expanded or contracted with no reason or mode field, and a "
    "lost renewal opportunity records a loss reason (price, no decision, competitive, other) "
    "that is not a cancellation-versus-lapse flag. The generator's abrupt-versus-gradual "
    "usage-decline switch is not persisted in any table."
)
_NO_CHURN_REASON_CATEGORY = (
    "Needs a churn reason per churned account, loud (explicit cancellation) versus silent "
    "(non-renewal). No churn, subscription or account record carries a reason or mode "
    "field, so tenure at churn is the only churn-event attribute available."
)
_NO_CHANNEL_ACTIVITY_MART = (
    "Cost per channel activity (cost per MQL, cost per SDR meeting) needs channel spend "
    "joined to per-channel lead and meeting counts. Rep cost, marketing cost, leads and rep "
    "meetings each exist, but no reporting table joins channel cost to those counts."
)
_NO_UPSTREAM_EXPANSION_DRIVERS = (
    "Defined by reference in the metric tree ('See Growth \u2014 expansion revenue "
    "drivers'), so it has no series of its own. Of the two drivers it points to, Overage "
    "realization is computed (as overage share of MRR, partial), but Wallet share "
    "progression has no footprint denominator (see its gap note), so the driver pair cannot "
    "be recombined into the expansion figure and the reference stays blocked. AM cost, the "
    "other side of the ratio, is a computed input."
)

# Computability notes for the nodes wired to mart_deal_funnel,
# mart_workflow_chain_health and mart_consumption_utilization. Each states
# the series definition and its limits; the registry mirrors the same
# definitions in semantic/build_registry.py.
_POC_PASS_NOTE = (
    "Enterprise only, as the tree specifies: passed POCs over closed new-business "
    "opportunities (won or lost) with a POC outcome, by close month. Monthly n is small "
    "(about 10-15 per month from 2023, fewer before), so the series is noisy and months "
    "with fewer than 5 outcomes are left blank. A POC can fail on a won deal (22 of 113 "
    "Enterprise wins), so a failed POC is not a lost deal."
)
_LOSS_REASON_NOTE = (
    "Scalar view of a three-way mix: the competitive share of lost new-business "
    "opportunities (Commercial and Enterprise, by close month). The tree names competitive, "
    "no-decision and price; a single share cannot show a shift between the other reasons, "
    "which the mart carries as counts."
)
_RAMP_MIX_NOTE = (
    "Share of closed (won or lost) new-business opportunities, Commercial and Enterprise "
    "combined, that were created within 180 days of the owning rep's hire date (the "
    "ramp window rep productivity uses). Approximate: the owner on an opportunity is the "
    "current owner after any reassignment on a rep's departure, so ramp attribution is not "
    "exact. Blank before 2023-01, the first month with a logged lost deal: earlier months "
    "hold won deals only."
)
_DISCOUNT_NOTE = (
    "Amount-weighted discount on won new-business deals (1 - won amount / won list price), "
    "Commercial and Enterprise combined. List price is generated as amount / (1 - discount "
    "rate), so discount versus list is an identity up to rounding rather than an "
    "independent observation: it is a faithful read of the discount rate, not a separate "
    "check on pricing."
)
_DEAL_SIZE_NOTE = (
    "Share of won new-business deals (Commercial and Enterprise, won-count weighted) whose "
    "amount sits at or below the segment's ACV band floor. Deal amounts are clipped to the "
    "band at generation, so the share measures how often the clip binds: 53% of Commercial "
    "wins sit at the floor and no Enterprise win does. Variation inside the band is "
    "compressed, and the combined share also moves with the Commercial/Enterprise win mix."
)
_RENEWAL_WIN_NOTE = (
    "Closed-won renewal opportunities over closed renewals, Commercial and Enterprise "
    "(SMB has no renewal opportunities), by close month. Renewal opportunities begin in "
    "2021-02."
)
_WORKFLOW_CHAIN_CENSOR_NOTE = (
    " Partial chains are a pre-churn state (in the data only accounts within 5 months of "
    "churning ever have one), so the series falls away at the end of the data window, "
    "where future churners are not yet present; the last 5 months of the window are left "
    "blank rather than read as an improvement."
)
_WORKFLOW_CHAIN_NOTE = (
    "Breadth, not volume: the share of accounts with a workflow chain in the month whose "
    "full-chain completion rate (downstream over upstream Actions) is below 0.70, all three "
    "segments combined (SMB is most of the accounts). The 0.70 cut is the playbook rule's "
    "value, proposed and not confirmed." + _WORKFLOW_CHAIN_CENSOR_NOTE
)
_INGESTION_NOTE = (
    "Actions-weighted: 1 - downstream Actions / upstream Actions summed over all accounts, "
    "all three segments combined. A ratio of sums, so it weights accounts by volume where "
    "the Layer-2 breadth counts each account once." + _WORKFLOW_CHAIN_CENSOR_NOTE
)
_MID_CHAIN_NOTE = (
    "Share of chain accounts partial (below 0.70 completion) in this month and in the "
    "calendar-prior month, all segments combined. A subset of the Layer-2 breadth, using "
    "the playbook rule's two-consecutive-month idea; the 0.70 cut is proposed, not "
    "confirmed." + _WORKFLOW_CHAIN_CENSOR_NOTE
)
_FULL_VS_PARTIAL_NOTE = (
    "Share of chain accounts at or above the 0.70 completion cut, all segments combined. "
    "Exactly the complement of the Layer-2 breadth, so it adds no information beyond that "
    "node's partial share; it is kept because the tree names it." + _WORKFLOW_CHAIN_CENSOR_NOTE
)
_OVERAGE_NOTE = (
    "Overage billing realized against usage over committed minimums, as overage share of "
    "MRR in dollars (overage MRR over total MRR), Commercial and Enterprise. A realization "
    "rate is 100% on every account-month: billed MRR equals unit price times the larger of "
    "committed and utilized Actions, so all overage usage is billed. The "
    "dollar share is the series with variance in it. From 2021 it runs 16-42% of MRR "
    "(mean 32%) because utilization exceeds commitment on about 90-93% of committed "
    "Commercial and Enterprise account-months."
)
_HEALTH_INPUT_REACHABILITY = (
    " This node sits under the Account health score, which is not computable, so it can "
    "never be reached from a Layer-2 outlier and does not appear in a drill-down."
)

# ---------------------------------------------------------------- Growth

_l1("new_logo_consumption_revenue", "New logo consumption revenue", "growth",
    "higher", COMPARABLE)
# Pipeline generated and its three channel legs are the tree's own sum of
# channels, all in one unit (converted leads), so the legs are additive
# components of the parent: compared by absolute deviation, the same basis
# NRR/GRR/S&M cost use for the same reason. Computed by
# analytics/marketing_attribution.py; see PIPELINE_GENERATED_SCOPE_NOTE.
_child("pipeline_generated", "Pipeline generated", "new_logo_consumption_revenue",
       COMPUTABLE, sibling_comparison_basis="additive_share")
_child("organic_content", "Organic/content", "pipeline_generated", COMPUTABLE)
_child("paid", "Paid", "pipeline_generated", COMPUTABLE)
_child("community_events", "Community/events", "pipeline_generated", COMPUTABLE)

_child("win_rate", "Win rate", "new_logo_consumption_revenue", COMPUTABLE)
_child("stage_to_stage_conversion", "Stage-to-stage conversion", "win_rate",
       NOT_COMPUTABLE, _STAGE_CONVERSION_DEGENERATE)
_child("poc_pass_rate", "POC pass rate (Enterprise)", "win_rate", PARTIAL, _POC_PASS_NOTE)
_child("rep_capacity_ramp_mix", "Rep capacity / ramp mix", "win_rate", PARTIAL,
       _RAMP_MIX_NOTE)
_child("loss_reason_mix", "Loss-reason mix", "win_rate", PARTIAL, _LOSS_REASON_NOTE)

_child("avg_initial_commitment", "Avg initial commitment", "new_logo_consumption_revenue", COMPUTABLE)
_child("discount_rate_vs_list", "Discount rate vs. list", "avg_initial_commitment",
       PARTIAL, _DISCOUNT_NOTE)
_child("deal_size_trend_within_band", "Deal-size trend within segment band",
       "avg_initial_commitment", PARTIAL, _DEAL_SIZE_NOTE)

_child("marketing_sales_handoff_quality", "Marketing-sales handoff quality",
       "new_logo_consumption_revenue", NOT_COMPUTABLE,
       _NO_MQL_SAL_LIFECYCLE + " Excluded from sibling ranking: the metric tree defines "
       "it as a diagnostic overlay on the three factors above, not a fourth "
       "multiplicative factor.",
       is_ranking_sibling=False)
_child("mql_response_sla", "MQL response SLA", "marketing_sales_handoff_quality",
       NOT_COMPUTABLE, _NO_MQL_RESPONSE_SLA)
_child("mql_to_sal_acceptance_rate", "MQL -> SAL acceptance rate",
       "marketing_sales_handoff_quality", NOT_COMPUTABLE, _NO_MQL_SAL_ACCEPTANCE)
_child("lead_recycling_rate", "Lead recycling / nurture re-qualification rate",
       "marketing_sales_handoff_quality", NOT_COMPUTABLE, _NO_LEAD_RECYCLING_HISTORY)

_child("brand_awareness", "Brand & awareness", "new_logo_consumption_revenue",
       NOT_COMPUTABLE,
       "No web-traffic, branded-search or share-of-voice source exists. Excluded from "
       "sibling ranking: the metric tree marks it a leading indicator that is not summed "
       "into the pipeline math.",
       is_ranking_sibling=False)
_child("branded_search_volume_trend", "Branded search volume trend", "brand_awareness",
       NOT_COMPUTABLE, "No web-traffic or search source exists in the project.")
_child("direct_traffic_share", "Direct traffic share", "brand_awareness",
       NOT_COMPUTABLE, "No web-traffic source exists in the project.")
_child("share_of_voice", "Share of voice vs. named competitors", "brand_awareness",
       NOT_COMPUTABLE, "No competitive-intelligence source exists in the project.")

_l1("activation", "Activation (TTFA, blended)", "growth", "lower", NO_PLAN_BY_DESIGN,
    computability=PARTIAL,
    gap_note=(
        "Blended time to first Action is identically 0 in every month, so the series "
        "carries no variance signal and no deviation from its trailing baseline can be "
        "computed. Usage is recorded monthly and every account records its first Action "
        "in its signup month."),
    plan_comparability_note=(
        "No plan row exists for Activation, so it is compared with its trailing 3-month "
        "baseline. Blended time to first Action is 0 in every month, so the baseline is 0 "
        "and no variance is computable."),
    plan_comparability_detail=(
        "The plan table carries no Activation row by design, and the design brief's sample "
        "readout reports Activation against a trailing baseline ('2.1 days vs. 2.4d last "
        "month') rather than a plan figure. The engine therefore gives Activation its own "
        "variance mechanism, a trailing-baseline comparison, separate from the "
        "plan-difference mechanism used for the other ten metrics. In the current data "
        "blended time to first Action (TTFA) is 0 in every month of the 36-month window, "
        "because usage is recorded monthly and every account records its first Action in "
        "its signup month. The baseline is therefore 0 and no deviation is computable, so "
        "Activation reports Not computable rather than On track. A real TTFA signal needs a "
        "day-grain first-Action timestamp in the raw data and a corresponding mart change."))
_child("onboarding_completion_rate", "Onboarding completion rate", "activation",
       PARTIAL,
       "Share of a signup cohort that reached a first production Action (activated accounts "
       "divided by signup cohort size). The value is 1.0 in every month because every "
       "account produces a first Action in its signup month, so the series carries no "
       "variance signal.")
_child("time_to_first_integration", "Time-to-first-integration / first successful run",
       "activation", NOT_COMPUTABLE,
       "No integration or first-successful-run event exists in the raw data; usage is "
       "recorded monthly, with no first-Action timestamp.")
_child("quickstart_docs_engagement_rate", "Quickstart/docs content engagement rate",
       "activation", NOT_COMPUTABLE,
       "No docs or quickstart engagement source exists; the content-engagement source in the "
       "build spec was not generated.")

_l1("expansion_consumption_revenue", "Expansion consumption revenue", "growth",
    "higher", CAVEATED,
    plan_comparability_note=(
        "Caveated: the actual counts any month-on-month usage increase as expansion, while "
        "the plan's expansion is derived from the benchmark NRR. The level gap against plan "
        "is definitional."),
    plan_comparability_detail=(
        "The variance is computed, but plan and actual are not on the same footing, so the "
        "level gap is not a performance finding on its own. The plan's monthly expansion is "
        "not a separate forecast of expansion bookings: it is a share of the revenue base "
        "solved out of the benchmark-blended NRR and GRR anchors (NRR^(1/12) - 1 plus the "
        "contraction-plus-churn share, about 1.95% of base a month in each plan year), so "
        "the plan's flow rows and its NRR and GRR rows are two readings of one identity. "
        "The actual is the gross month-on-month bucket: the revenue-movement model counts "
        "any month-on-month usage increase as expansion. In a consumption business whose "
        "base grows about 88% a year that bucket is about 11% of starting revenue a month "
        "in each of 2023, 2024 and 2025, about 5.6 times the plan's share. The plan's "
        "dollar base tracks the actual base to within about 10% in those years, so the "
        "dollar gap is a gap in the share of base, not in the size of the base. It is the "
        "same definitional difference that caveats NRR (trailing-12-month NRR about 1.82 "
        "against a 1.17 plan) and moves with Contraction + churned revenue, because large "
        "gross increases and decreases largely offset in the actuals. Read the sign and "
        "the Layer-2 drill-down, not the level. The drill-down ranks each leg against its "
        "own trailing baseline and is not affected by a level offset."))
_child("wallet_share_progression", "Wallet share progression",
       "expansion_consumption_revenue", NOT_COMPUTABLE,
       "Needs an account's total addressable workflow footprint as the denominator of "
       "wallet share. No source estimates an account's non-Acme workflow volume, so the "
       "ratio has no denominator.")
_child("workflow_migration_rate", "Workflow migration rate", "wallet_share_progression",
       NOT_COMPUTABLE, "Needs business-process-level onboarding events, which are not in the raw data.")
_child("am_touch_effectiveness", "AM touch effectiveness", "wallet_share_progression",
       NOT_COMPUTABLE,
       "AM activity is recorded, but no reporting table joins AM touches to a recommitment "
       "outcome; only the touch count is exposed.")
_child("existing_account_community_engagement", "Existing-account community engagement depth",
       "wallet_share_progression", NOT_COMPUTABLE,
       "The community-membership source in the build spec was not generated.")
_child("overage_realization", "Overage realization", "expansion_consumption_revenue",
       PARTIAL, _OVERAGE_NOTE)

_l1("contraction_churned_revenue", "Contraction + churned revenue", "growth",
    "lower", CAVEATED,
    plan_comparability_note=(
        "Caveated: the actual counts any month-on-month usage decline as contraction, while "
        "the plan's contraction and churn are derived from the benchmark GRR. The level gap "
        "against plan is definitional."),
    plan_comparability_detail=(
        "The variance is computed, but plan and actual are not on the same footing, so the "
        "level gap is not a performance finding on its own. The plan's monthly contraction "
        "plus churn is a share of the revenue base solved out of the benchmark-blended GRR "
        "anchor (1 - GRR^(1/12), about 0.6% to 0.8% of base a month across the plan years), "
        "so it describes durable downsell and outright churn in a mature base, and the "
        "plan's flow rows and its NRR and GRR rows are two readings of one identity. The "
        "actual is the gross month-on-month bucket: the revenue-movement model counts any "
        "month-on-month usage decline as contraction. In a consumption business whose base "
        "grows about 88% a year, that bucket is about 5.1% to 5.4% of starting revenue a "
        "month in each of 2023, 2024 and 2025, seven to nine times the plan's share, of "
        "which outright churn is about 0.1% to 0.3%. The plan's dollar base tracks the "
        "actual base to within about 10% in those years, so the dollar gap is a gap in the "
        "share of base, not in the size of the base. It is the same definitional difference "
        "that caveats GRR (trailing-12-month GRR about 0.51 against a 0.93 plan) and NRR, "
        "and it moves with Expansion consumption revenue, because large gross increases and "
        "decreases largely offset in the actuals. Logo retention, which has no gross-flow "
        "bucket, reconciles to plan within about 2%, which indicates the churn leg is sound "
        "and the scope of the contraction bucket is what differs. Read the sign and the "
        "Layer-2 drill-down, not the level. The drill-down ranks each leg against its own "
        "trailing baseline and is not affected by a level offset."))
_child("workflow_chain_underutilization", "Workflow chain under-utilization",
       "contraction_churned_revenue", PARTIAL, _WORKFLOW_CHAIN_NOTE)
_child("ingestion_without_completion_rate", "Ingestion-without-completion rate",
       "workflow_chain_underutilization", COMPUTABLE, _INGESTION_NOTE)
_child("mid_chain_abandonment", "Mid-chain workflow abandonment",
       "workflow_chain_underutilization", PARTIAL, _MID_CHAIN_NOTE)
_child("full_vs_partial_chain_share", "Declining share of full-chain vs. partial-chain runs",
       "workflow_chain_underutilization", PARTIAL, _FULL_VS_PARTIAL_NOTE)

_child("account_health_score", "Account health score", "contraction_churned_revenue",
       NOT_COMPUTABLE,
       "The composite is a churn-model score computed at a single as-of date over the "
       "currently active accounts; no artifact or reporting table holds it as a monthly "
       "history. Scoring a past month would need the score "
       "population gated on churn month, because defining it by final account status "
       "(Active) drops accounts that churned later, biases older months upward and "
       "creates a spurious deterioration trend. The current-month score feeds the "
       "watchlist. Its four inputs are computed separately (see their notes) but cannot "
       "be reached from a drill-down while this node is blocked.")
_child("usage_trend_account_relative", "Usage trend (account-relative baseline)",
       "account_health_score", PARTIAL,
       "The same signal as the usage-dip breadth under Cyclical/planned usage dip: the "
       "share of active accounts whose trailing 3-month mean Actions sits below 70% of "
       "their own cumulative mean. A breadth measure, not a per-account trend slope; all "
       "three segments combined." + _HEALTH_INPUT_REACHABILITY)
_child("support_ticket_volume_severity", "Support ticket volume / severity",
       "account_health_score", PARTIAL,
       "Severity-weighted ticket load: the sum of each month's ticket severity scores "
       "(ticket count times average severity, low=1 to critical=4) per active account, all "
       "three segments combined. One scalar standing for two attributes (volume and "
       "severity); the mart carries both separately." + _HEALTH_INPUT_REACHABILITY)
_child("engagement_login_frequency", "Engagement / login frequency",
       "account_health_score", COMPUTABLE,
       "Mean logins per active account-month, all three segments combined (a real 0 for "
       "an account with no login that month)." + _HEALTH_INPUT_REACHABILITY)
_child("am_sentiment_notes", "AM sentiment notes", "account_health_score", PARTIAL,
       "Mean AM sentiment score over the account-months that have one. Sentiment exists "
       "only where an AM touchpoint was logged: absent for 96% of SMB account-months "
       "(SMB has no AM), 53% of Commercial and 28% of Enterprise account-months, so the "
       "covered population shifts with AM touch cadence." + _HEALTH_INPUT_REACHABILITY)

_child("cyclical_vs_structural_usage_dip", "Cyclical/planned usage dip vs. structural churn",
       "contraction_churned_revenue", PARTIAL,
       "Computed as usage-dip breadth: the share of active accounts whose trailing "
       "3-month mean Actions consumed is below a set ratio of that account's own "
       "cumulative mean. Partial: it measures account-relative dip breadth without "
       "classifying dips as cyclical or structural, which needs a same-account-type, "
       "same-period-last-cycle cohort comparison that no reporting table supports. "
       "Descriptive only; no model is fitted.")
_child("account_specific_baseline_deviation", "Account-specific baseline deviation",
       "cyclical_vs_structural_usage_dip", NOT_COMPUTABLE,
       "Already included in the parent's computation (usage-dip breadth is the aggregated "
       "account-relative baseline deviation); a separate leaf would restate the parent.")
_child("cohort_comparison", "Cohort comparison (same account type, same period last cycle)",
       "cyclical_vs_structural_usage_dip", NOT_COMPUTABLE,
       "No reporting table exposes an account-type by usage-cycle cohort baseline.")

_child("renewal_win_rate", "Renewal win rate", "contraction_churned_revenue",
       COMPUTABLE, _RENEWAL_WIN_NOTE)
_child("time_to_respond_churn_risk_flag", "Time-to-respond on churn-risk flag",
       "renewal_win_rate", NOT_COMPUTABLE,
       "Needs churn-risk flag events joined to AM response; no reporting table exposes them.")
_child("loud_vs_silent_churn_mix", "Loud vs. silent churn mix", "renewal_win_rate",
       NOT_COMPUTABLE, _NO_LOUD_SILENT_CHURN_FLAG)

# ------------------------------------------------------------ Efficiency

_l1("magic_number", "Magic number (blended)", "efficiency", "higher", CAVEATED,
    computability=COMPUTABLE,
    plan_comparability_note=(
        "Caveated: the plan is a benchmark for a fully scoped S&M line, while the actual "
        "excludes marketing-team headcount and is a trailing-12-month ratio. The level gap "
        "against plan is definitional."),
    plan_comparability_detail=(
        "The variance is computed, but plan and actual are not on the same footing, so the "
        "gap is not a performance finding on its own. (1) S&M cost scope: the plan anchor is "
        "the QA benchmark Magic Number band for Commercial and Enterprise (about 0.7-0.9), a "
        "figure for a fully scoped S&M line. The actual uses the metric tree's three-part "
        "S&M cost: rep fully-loaded cost (including ramp, with a management and operations "
        "allocation in the loading factor) plus marketing program spend. Marketing-team "
        "headcount is not in the raw data, so the denominator is a floor and the actual a "
        "ceiling against the benchmark. (2) Basis: the actual is a trailing-12-month ratio "
        "of net new ARR (new logo plus expansion minus contraction minus churn, so it "
        "includes usage-driven expansion) to the prior month's S&M cost over the same 12 "
        "months, blended over Commercial and Enterprise only (SMB carries no rep cost and "
        "has no benchmark), the same population the plan blend uses. (3) Trend: net new ARR "
        "compounds with a revenue base growing about 88% a year while quota-carrying and AM "
        "headcount is close to flat, so the actual climbs through the window (about 0.9 to "
        "2.5) against a plan that moves about 3% a year, and the gap widens with scale "
        "rather than tracking any one month. The sign and trend of the variance and the "
        "Layer-2 drill-down are the comparable signals; the level is not."))
# S&M cost = rep fully-loaded cost + marketing spend, two additive USD
# components of one identity, so its children are compared by absolute dollar
# deviation (a small component's large % swing must not outrank the one that
# actually moved the total) -- the same basis NRR/GRR use for the same reason.
_child("sm_cost", "S&M cost", "magic_number", COMPUTABLE,
       sibling_comparison_basis="additive_share")
_child("cost_per_channel_activity", "Cost per channel activity", "sm_cost",
       NOT_COMPUTABLE, _NO_CHANNEL_ACTIVITY_MART)
_child("rep_fully_loaded_cost", "Rep fully-loaded cost, incl. ramp", "sm_cost", COMPUTABLE)
_child("marketing_spend_allocation_by_channel", "Marketing spend allocation by channel",
       "sm_cost", PARTIAL,
       "Channel spend attributed to segment (by each segment's share of the channel-month's "
       "new accounts), summed over channels. The per-channel split is not exposed by any "
       "reporting table, so the leg is ranked in channel-summed form: it shows that "
       "marketing spend moved, not which channel moved it.")

_l1("consumption_payback", "Consumption payback (blended)", "efficiency", "lower", CAVEATED,
    plan_comparability_note=(
        "Caveated: the plan band assumes a fully loaded CAC, while the actual CAC is "
        "marketing spend only. The actual sits far below the band by definition."),
    plan_comparability_detail=(
        "The variance is computed, but plan and actual are not on the same footing. The "
        "plan anchor is the QA benchmark payback band (Commercial about 14-18 months, "
        "Enterprise about 9-13 months), which assumes a fully loaded CAC. The actual CAC "
        "comes from marketing spend only: channel spend for outbound SDR covers tooling and "
        "data enrichment, not rep headcount cost, so the numerator excludes sales "
        "headcount. The actual's denominator is also average utilized margin across the "
        "whole installed base rather than per new account. Both push the actual far below "
        "the benchmark band. The Layer-2 drill-down is unaffected, because it ranks each "
        "leg against its own trailing baseline, which a constant level offset does not "
        "change."))
_child("cac_by_channel", "CAC by channel (unblended)", "consumption_payback", PARTIAL,
       "Blended CAC (blended across channels by each channel's share of the segment's new "
       "accounts). The per-channel split is not exposed by any reporting table, so the leg "
       "is ranked in blended form: it identifies CAC as the outlier leg, not the "
       "responsible channel.")
_child("utilized_vs_committed_action_volume", "Utilized vs. committed Action volume",
       "consumption_payback", PARTIAL,
       "Ranked as average utilized margin per account (MRR reduced by the "
       "utilized-to-committed ratio, times the flat 80% gross margin), so movement can come "
       "from utilization or from the MRR base. The raw committed and utilized Action sums are "
       "now available (Commercial and Enterprise) but this leg still ranks the margin series, "
       "which is what Consumption payback itself is built on. Utilization is above commitment "
       "on about 93% of Commercial and Enterprise account-months, so the utilized-only "
       "haircut in the margin is close to a no-op.")

_l1("onboarding_cs_efficiency", "Onboarding/CS efficiency (blended)", "efficiency",
    "lower", COMPARABLE)
_child("am_touchpoint_volume", "AM touchpoint volume", "onboarding_cs_efficiency", COMPUTABLE)
_child("automated_action_volume", "Automated Action volume delivered",
       "onboarding_cs_efficiency", COMPUTABLE)

_l1("am_efficiency", "AM efficiency (blended)", "efficiency", "higher", CAVEATED,
    computability=COMPUTABLE,
    plan_comparability_note=(
        "Caveated: the actual covers Commercial and Enterprise over a trailing 12 months and "
        "counts any usage increase as expansion, while the plan includes SMB expansion."),
    plan_comparability_detail=(
        "The variance is computed, with three differences in footing. (1) Units and basis: "
        "the tree defines the ratio as Expansion consumption revenue divided by AM cost; "
        "both are read as monthly flows (monthly expansion MRR movement over the same "
        "month's AM cost), the basis the plan anchor uses, and the actual is a "
        "trailing-12-month aggregate because a single month carries the raw data's Q4 "
        "seasonality. (2) Population: the plan anchor's numerator is built on the "
        "company-wide revenue base (SMB included), while the actual is blended over "
        "Commercial and Enterprise, the only segments with an AM, so the actual sits below "
        "a like-for-like plan by roughly SMB's share of expansion. (3) Scope of expansion: "
        "the revenue-movement model counts any month-on-month usage increase as expansion, "
        "the same gross-bucket definition that caveats NRR and GRR. The actual rises "
        "through the window (about 0.8 to 2.6) toward a nearly flat plan, so the negative "
        "gap narrows over time."))
_child("expansion_revenue_drivers", "Expansion revenue drivers", "am_efficiency",
       NOT_COMPUTABLE, _NO_UPSTREAM_EXPANSION_DRIVERS,
       cross_reference_to="expansion_consumption_revenue")
_child("am_cost_by_segment", "AM cost by segment", "am_efficiency", COMPUTABLE)

# ------------------------------------------------------------ Durability

_l1("nrr", "NRR", "durability", "higher", CAVEATED,
    sibling_comparison_basis="additive_share",
    plan_comparability_note=(
        "Caveated: the contraction bucket counts any month-on-month usage decline, so gross "
        "expansion and contraction are both large, while the plan benchmark describes "
        "durable downsell. Trailing-12-month NRR and GRR differ from plan by definition."),
    plan_comparability_detail=(
        "Two adjustments apply. (1) Units: the plan's NRR is an annual-equivalent decimal "
        "rate while the durability table carries a monthly rate; the engine compounds the "
        "trailing 12 company-wide monthly rates before comparing, as the plan table's own "
        "header specifies. (2) Scope of the contraction bucket: the plan side is "
        "internally consistent, since its monthly expansion and contraction-plus-churn "
        "shares of base are derived from the benchmark-blended NRR and GRR anchors "
        "(1 - GRR^(1/12), and NRR^(1/12) - 1 plus that), so the plan's flow rows and "
        "durability rows are two readings of one identity. The remaining gap is on the "
        "actuals side and is definitional, not performance. Over the 12 months to 2025-11 "
        "the marts carry gross contraction plus churn at about 5.4% of starting revenue per "
        "month against gross expansion at about 10.8%, of which outright churn is about "
        "0.2%. The revenue-movement model counts any month-on-month usage decline as "
        "contraction, so in a consumption business whose base grows about 88% a year both "
        "gross legs are large and largely offsetting, while a benchmark NRR/GRR band "
        "describes durable downsell in a mature base. That one difference drives both "
        "signs: trailing-12-month GRR is about 0.51 against a 0.93 plan and NRR about 1.82 "
        "against a 1.17 plan. Logo retention, which has no gross-flow bucket, reconciles to "
        "plan within 2%, which indicates the churn leg is sound and the contraction "
        "bucket's scope is what differs. The Layer-2 drill-down ranks each leg against its "
        "own trailing baseline and is not affected by a definitional level offset."))
_child("nrr_expansion_rate", "See Growth: Expansion (share of starting revenue)", "nrr", COMPUTABLE,
       cross_reference_to="expansion_consumption_revenue")
_child("nrr_contraction_rate", "See Growth: Contraction (share of starting revenue)", "nrr", COMPUTABLE,
       cross_reference_to="contraction_churned_revenue")
_child("nrr_churn_rate", "See Growth: Churn (share of starting revenue)", "nrr", COMPUTABLE,
       cross_reference_to="contraction_churned_revenue")

_l1("grr", "GRR", "durability", "higher", CAVEATED,
    sibling_comparison_basis="additive_share",
    plan_comparability_note=(
        "Caveated: same contraction-bucket scope and unit adjustments as NRR."),
    plan_comparability_detail=(
        "Same two adjustments as NRR (units, and the scope of the contraction bucket); the "
        "NRR detail gives the full explanation and figures."))
_child("grr_contraction_rate", "See Growth: Contraction (share of starting revenue)", "grr", COMPUTABLE,
       cross_reference_to="contraction_churned_revenue")
_child("grr_churn_rate", "See Growth: Churn (share of starting revenue)", "grr", COMPUTABLE,
       cross_reference_to="contraction_churned_revenue")

_l1("logo_retention", "Logo retention", "durability", "higher", COMPARABLE)
_child("tenure_at_churn", "Tenure-at-churn (early vs. late lifecycle)", "logo_retention",
       COMPUTABLE)
_child("churn_reason_category", "Churn reason category (loud vs. silent)", "logo_retention",
       NOT_COMPUTABLE, _NO_CHURN_REASON_CATEGORY)


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
    are final-status fields and would leak. The ticket, login and sentiment
    columns are that month's own events."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select account_id, month, segment, actions_consumed, "
            "account_tenure_days, churn_month, ticket_count, avg_ticket_severity_score, "
            "login_count, avg_am_sentiment_score "
            "from main_marts.mart_account_health where month <= ?", [as_of_date]).df()
    finally:
        if owns:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    df["churn_month"] = pd.to_datetime(df["churn_month"])
    return df


def _load_month_mart(table: str, as_of_date: date, con=None) -> pd.DataFrame:
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            f"select * from main_marts.{table} where month <= ?", [as_of_date]).df()
    finally:
        if owns:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    return df


def load_deal_funnel(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per segment (Commercial, Enterprise) per close month,
    month <= as_of_date. Source mart: mart_deal_funnel."""
    return _load_month_mart("mart_deal_funnel", as_of_date, con)


def load_workflow_chain_health(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per segment (all three) per month, month <= as_of_date.
    Source mart: mart_workflow_chain_health."""
    return _load_month_mart("mart_workflow_chain_health", as_of_date, con)


def load_consumption_utilization(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per segment (Commercial, Enterprise) per month,
    month <= as_of_date. Source mart: mart_consumption_utilization."""
    return _load_month_mart("mart_consumption_utilization", as_of_date, con)


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
      * Magic number / AM efficiency -- trailing-twelve-month aggregate
        ratios over Commercial and Enterprise, the segments that carry rep
        cost and an AM (SMB has neither and is 'n/a' in the benchmark
        table, the same population gtm_plan._blend uses). Magic number =
        12 months of net new ARR over the same 12 months' PRIOR-month S&M
        cost; AM efficiency = 12 months of monthly expansion MRR over 12
        months of AM cost. Trailing twelve months rather than one month
        because a single month's net new ARR carries the raw data's Q4
        seasonality and can be negative. NaN until twelve months of cost
        exist (2024-01 for magic number), never imputed.
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

    ce = eff[eff["segment"].isin(_COST_BLEND_SEGMENTS)]
    by_month = ce.groupby("month").agg(
        net_new_arr=("net_new_arr", "sum"),
        sm_cost_prior=("magic_number_sm_cost", lambda s: s.sum(min_count=1)),
        exp_arr=("am_expansion_arr", "sum"), am_cost=("am_cost", "sum"))
    # Trailing-twelve-month aggregate ratios (sum over sum). A single month's
    # net new ARR carries the raw data's Q4 seasonality and can be negative,
    # so a monthly ratio is not a stable statistic -- the same reason NRR/GRR
    # are annualised here. A month with no prior-period S&M cost (before
    # 2023-02) contributes NaN, so the window is only defined once all twelve
    # months carry cost.
    nn_window = by_month["net_new_arr"].where(by_month["sm_cost_prior"].notna())
    out["magic_number"] = (
        nn_window.rolling(_ANNUALISATION_MONTHS, min_periods=_ANNUALISATION_MONTHS).sum()
        / by_month["sm_cost_prior"].rolling(_ANNUALISATION_MONTHS, min_periods=_ANNUALISATION_MONTHS).sum()
    ).replace([np.inf, -np.inf], np.nan)
    out["am_efficiency"] = (
        (by_month["exp_arr"] / 12.0).rolling(_ANNUALISATION_MONTHS, min_periods=_ANNUALISATION_MONTHS).sum()
        / by_month["am_cost"].rolling(_ANNUALISATION_MONTHS, min_periods=_ANNUALISATION_MONTHS).sum()
    ).replace([np.inf, -np.inf], np.nan)

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
    mart_durability, mart_account_health, mart_deal_funnel,
    mart_workflow_chain_health, mart_consumption_utilization. Children with no mart-computable
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
            "pipeline_generated": _pipeline_generated_series(as_of_date, con)["pipeline_generated"],
            # blank before the first logged loss: with no lost deals on record the
            # "win rate" is a fake 100% (see _from_first_logged_loss)
            "win_rate": _from_first_logged_loss(rep["won"] / closed, rep["lost"]),
            "avg_initial_commitment": rep["bookings"] / rep["won"].replace(0, np.nan),
        }

    if parent_key == "pipeline_generated":
        series = _pipeline_generated_series(as_of_date, con)
        return {k: v for k, v in series.items() if k != "pipeline_generated"}

    if parent_key == "activation":
        gb = load_growth_bridge(as_of_date, con=con)
        a = gb.dropna(subset=["signup_cohort_size"]).groupby("month").agg(
            activated=("activated_count", "sum"), cohort=("signup_cohort_size", "sum"))
        return {"onboarding_completion_rate": a["activated"] / a["cohort"].replace(0, np.nan)}

    if parent_key == "win_rate":
        return _win_rate_leaf_series(as_of_date, con)

    if parent_key == "avg_initial_commitment":
        return _avg_commitment_leaf_series(as_of_date, con)

    if parent_key == "expansion_consumption_revenue":
        return {"overage_realization": _overage_share_series(as_of_date, con)}

    if parent_key == "overage_realization":
        return {}

    if parent_key == "contraction_churned_revenue":
        return {
            "cyclical_vs_structural_usage_dip": _usage_dip_breadth_series(as_of_date, con),
            "workflow_chain_underutilization": _workflow_chain_breadth_series(as_of_date, con),
            "renewal_win_rate": _renewal_win_rate_series(as_of_date, con),
        }

    if parent_key == "workflow_chain_underutilization":
        return _workflow_chain_leaf_series(as_of_date, con)

    if parent_key == "account_health_score":
        # Reachable only if a future change makes the composite computable:
        # the composite is NOT_COMPUTABLE, so no Layer-2 outlier can be it.
        return _account_health_input_series(as_of_date, con)

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

    if parent_key == "magic_number":
        ce = load_efficiency(as_of_date, con=con)
        ce = ce[ce["segment"].isin(_COST_BLEND_SEGMENTS)]
        return {"sm_cost": ce.dropna(subset=["sm_cost"]).groupby("month")["sm_cost"].sum()}

    if parent_key == "sm_cost":
        ce = load_efficiency(as_of_date, con=con)
        ce = ce[ce["segment"].isin(_COST_BLEND_SEGMENTS)]
        return {
            "rep_fully_loaded_cost": ce.groupby("month")["rep_fully_loaded_cost"].sum(),
            "marketing_spend_allocation_by_channel":
                ce.dropna(subset=["marketing_spend_allocated"])
                  .groupby("month")["marketing_spend_allocated"].sum(),
        }

    if parent_key == "am_efficiency":
        ce = load_efficiency(as_of_date, con=con)
        ce = ce[ce["segment"].isin(_COST_BLEND_SEGMENTS)]
        return {"am_cost_by_segment": ce.groupby("month")["am_cost"].sum()}

    # Every other Layer-2 node: no computable children exist in any mart.
    # Returning {} is the honest answer; the tree's gap notes carry the
    # reason.
    return {}


def _pipeline_generated_series(as_of_date: date, con) -> Dict[str, pd.Series]:
    """Monthly Pipeline-generated flow (converted leads) for the parent and
    each channel leg, keyed by tree key, complete months only. Grain: one
    value per month <= the evaluation month. Source: analytics/
    marketing_attribution.py's compute_pipeline_generated_flow() (marts
    fact_leads, fact_campaign_engagement_events) -- called, not re-derived.
    The month-start index matches the growth-bridge series it is ranked
    against; a channel-month with no conversions is a real 0 there."""
    flow = ma.compute_pipeline_generated_flow(as_of_date, con=con)
    month = _evaluation_month(as_of_date)
    out = {}
    for channel, key in ma.PIPELINE_CHANNEL_TO_TREE_KEY.items():
        if flow.empty:
            out[key] = pd.Series(dtype=float, name=key)
            continue
        s = flow[flow["channel"] == channel].set_index("period")["pipeline_generated_flow"]
        out[key] = s[s.index <= month].astype(float).rename(key)
    return out


def reconcile_pipeline_generated_branch(as_of_date: date, con=None) -> dict:
    """Children-sum-to-parent reconciliation for the Pipeline-generated
    branch, on the exact series this engine ranks. Grain: one check per
    month <= the evaluation month. The three channel legs (built by
    _build_child_series('pipeline_generated')) must sum to the parent
    (built by _build_child_series('new_logo_consumption_revenue')) with zero
    difference, and marketing_attribution's independent recounts of the
    flow (straight from fact_leads, channel-agnostic) must agree with it --
    so a converted lead whose channel fell outside the three legs breaks the
    check instead of silently dropping out of the ranking. New logo's own
    three legs are NOT reconciled arithmetically: they sit on different
    populations and units (see PIPELINE_GENERATED_SCOPE_NOTE)."""
    owns = con is None
    con = con or _connect()
    try:
        parent = _build_child_series("new_logo_consumption_revenue", as_of_date, con)["pipeline_generated"]
        kids = _build_child_series("pipeline_generated", as_of_date, con)
        attribution = ma.reconcile_pipeline_generated_flow(as_of_date, con=con)
    finally:
        if owns:
            con.close()
    kid_sum = pd.concat(list(kids.values()), axis=1).sum(axis=1) if kids else pd.Series(dtype=float)
    diff = (parent - kid_sum.reindex(parent.index)).abs()
    return {
        "months_checked": int(len(parent)),
        "max_abs_diff_children_to_parent": float(diff.max()) if len(diff) else float("nan"),
        "attribution_tie_out": attribution,
        "reconciles": bool(len(diff) > 0 and diff.max() <= 1e-9 and attribution["reconciles"]),
    }


# Which engine node each column of the three deal-funnel / workflow-chain /
# consumption-utilization marts feeds. A column is either mapped to the node(s)
# whose series it builds, or listed in WAVE10_MART_UNUSED_COLUMNS with the
# reason the engine does not read it, so a new mart column cannot sit
# unaccounted for and a node cannot stay NOT_COMPUTABLE while a mart column
# already feeds it (stale_markings_against_wave10_marts()).
WAVE10_MART_NODE_MAP: Dict[str, Dict[str, Sequence[str]]] = {
    "mart_deal_funnel": {
        "new_business_won_count": ("rep_capacity_ramp_mix", "deal_size_trend_within_band"),
        "new_business_lost_count": ("loss_reason_mix", "rep_capacity_ramp_mix"),
        "lost_competitive_count": ("loss_reason_mix",),
        "won_amount_sum": ("discount_rate_vs_list",),
        "won_list_price_sum": ("discount_rate_vs_list",),
        "share_won_at_band_floor": ("deal_size_trend_within_band",),
        "poc_pass_count": ("poc_pass_rate",),
        "poc_fail_count": ("poc_pass_rate",),
        "closed_by_ramping_rep_count": ("rep_capacity_ramp_mix",),
        "renewal_won_count": ("renewal_win_rate",),
        "renewal_lost_count": ("renewal_win_rate",),
    },
    "mart_workflow_chain_health": {
        "upstream_actions_sum": ("ingestion_without_completion_rate",),
        "ingestion_without_completion_actions_sum": ("ingestion_without_completion_rate",),
        "accounts_with_chain": ("workflow_chain_underutilization", "mid_chain_abandonment",
                                "full_vs_partial_chain_share"),
        "partial_chain_account_count": ("workflow_chain_underutilization",),
        "full_chain_account_count": ("full_vs_partial_chain_share",),
        "sustained_partial_account_count": ("mid_chain_abandonment",),
    },
    "mart_consumption_utilization": {
        "overage_mrr": ("overage_realization",),
        "total_mrr": ("overage_realization",),
    },
}

# Mart columns the engine does not read, each with the reason. Key columns
# (segment, month) are not listed.
WAVE10_MART_UNUSED_COLUMNS: Dict[str, Dict[str, str]] = {
    "mart_deal_funnel": {
        "lost_no_decision_count": "part of the three-way loss mix; Loss-reason mix is the competitive share only",
        "lost_price_count": "part of the three-way loss mix; Loss-reason mix is the competitive share only",
        "lost_other_count": "part of the three-way loss mix; Loss-reason mix is the competitive share only",
        "avg_discount_rate_won": "the engine recomputes the discount as a ratio of summed amount and list price",
        "share_won_at_band_cap": "no tree node reads the band cap; Deal-size trend uses the floor share",
        "stage_regression_count": "no tree node; Stage-to-stage conversion is degenerate (100% at every hop)",
        "avg_days_in_sal": "time in stage is not a tree node; Stage-to-stage conversion is degenerate",
        "avg_days_in_sqo": "time in stage is not a tree node; Stage-to-stage conversion is degenerate",
        "avg_days_in_poc": "time in stage is not a tree node; Stage-to-stage conversion is degenerate",
        "avg_days_in_proposal": "time in stage is not a tree node; Stage-to-stage conversion is degenerate",
        "won_by_ramping_rep_count": "win rate by ramp status is not a tree node; the mix uses closed deals",
    },
    "mart_workflow_chain_health": {
        "downstream_actions_sum": "the engine reads the idle Actions sum, the complement of downstream over upstream",
        "ingestion_without_completion_rate": "the engine recomputes it as a ratio of summed Actions",
    },
    "mart_consumption_utilization": {
        "committed_actions_sum": "available for Utilized vs. committed Action volume, which still ranks the margin series",
        "utilized_actions_sum": "available for Utilized vs. committed Action volume, which still ranks the margin series",
        "overage_actions_sum": "Overage realization is read in dollars (overage MRR over total MRR)",
        "overage_share_of_mrr": "the engine recomputes it as a ratio of summed dollars",
        "accounts_over_commit_count": "no tree node counts accounts over their commitment",
        "accounts_with_commitment_count": "no tree node counts committed accounts",
    },
}


def stale_markings_against_wave10_marts() -> List[str]:
    """Cross-artifact consistency guard, the deal-funnel / workflow-chain /
    consumption-utilization counterpart of stale_markings_against_attribution().
    Returns the keys of any tree node that a column of those marts feeds
    (WAVE10_MART_NODE_MAP) but that this tree marks NOT_COMPUTABLE or does not
    carry. Empty means no mapped column feeds a blocked node."""
    stale = set()
    for columns in WAVE10_MART_NODE_MAP.values():
        for nodes in columns.values():
            for key in nodes:
                node = _TREE.get(key)
                if node is None or node.computability == NOT_COMPUTABLE:
                    stale.add(key)
    return sorted(stale)


def stale_markings_against_attribution() -> List[str]:
    """Cross-artifact consistency guard. Returns the keys of any tree node
    that marketing_attribution.py computes and validates
    (PIPELINE_CHANNEL_TO_TREE_KEY) but that this tree marks NOT_COMPUTABLE
    or does not carry at all. Empty means the engine's markings agree with
    the artifact that owns the computation."""
    stale = []
    for key in ma.PIPELINE_CHANNEL_TO_TREE_KEY.values():
        node = _TREE.get(key)
        if node is None or node.computability == NOT_COMPUTABLE:
            stale.append(key)
    return stale


# Months with fewer closed Enterprise POC outcomes than this are left blank:
# a pass rate on 1-4 outcomes swings 25-100% on a single deal and would win any
# sibling ranking on noise. Own resolved decision; from 2023 the monthly n is
# about 10-15, before it is 0-4.
_MIN_POC_OUTCOMES_PER_MONTH = 5


def _rep_sold_deal_funnel(as_of_date: date, con) -> pd.DataFrame:
    df = load_deal_funnel(as_of_date, con=con)
    return df[df["segment"].isin(_REP_SOLD_SEGMENTS)]


def _ratio_by_month(df: pd.DataFrame, num: str, den: str, name: str) -> pd.Series:
    """Sum(num) / sum(den) per month -- a ratio of sums, never a mean of
    segment ratios -- blank where the denominator is 0."""
    g = df.groupby("month")[[num, den]].sum(min_count=1)
    return (g[num] / g[den].replace(0, np.nan)).dropna().rename(name)


def _from_first_logged_loss(series: pd.Series, lost: pd.Series) -> pd.Series:
    """Blanks every month before the first month in which any lost new-business
    deal is logged. The generator logs no lost Commercial or Enterprise
    new-business opportunity before 2023-01, so a win rate (or a share of
    "closed" deals) computed earlier counts only wins and reads 100%: a
    constant that is a logging fact, not performance. Left in, it would sit
    in the trailing baseline of every 2023 month and in persistence streaks.
    Derived from the data (the first month with a loss as of the as-of date),
    not a literal date, and the same fact that already leaves loss_reason_mix
    blank. With no loss logged at all the series is empty."""
    positive = lost[lost.fillna(0) > 0]
    if positive.empty:
        return series.iloc[0:0]
    return series[series.index >= positive.index.min()]


def _win_rate_leaf_series(as_of_date: date, con) -> Dict[str, pd.Series]:
    """Layer-3 candidates under Win rate, by close month. Grain: one value
    per month. Source mart: mart_deal_funnel, Commercial + Enterprise
    (_REP_SOLD_SEGMENTS) except POC pass rate, which is Enterprise only.
    Stage-to-stage conversion is deliberately absent: it is 100% at every
    hop in every month (see its gap note)."""
    df = _rep_sold_deal_funnel(as_of_date, con)
    ent = df[df["segment"] == "Enterprise"].set_index("month")
    n_poc = (ent["poc_pass_count"] + ent["poc_fail_count"]).astype(float)
    poc = (ent["poc_pass_count"].astype(float) / n_poc.replace(0, np.nan))
    poc = poc.where(n_poc >= _MIN_POC_OUTCOMES_PER_MONTH).dropna().rename("poc_pass_rate")
    closed = df.assign(closed=df["new_business_won_count"] + df["new_business_lost_count"])
    return {
        "poc_pass_rate": poc,
        "loss_reason_mix": _ratio_by_month(
            df, "lost_competitive_count", "new_business_lost_count", "loss_reason_mix"),
        "rep_capacity_ramp_mix": _from_first_logged_loss(
            _ratio_by_month(closed, "closed_by_ramping_rep_count", "closed",
                            "rep_capacity_ramp_mix"),
            df.groupby("month")["new_business_lost_count"].sum(min_count=1)),
    }


def _avg_commitment_leaf_series(as_of_date: date, con) -> Dict[str, pd.Series]:
    """Layer-3 candidates under Avg initial commitment, by close month.
    Source mart: mart_deal_funnel, Commercial + Enterprise. Discount is
    1 - won amount / won list price (a ratio of sums); deal-size position is
    the won-count-weighted share of wins at the segment ACV band floor."""
    df = _rep_sold_deal_funnel(as_of_date, con)
    g = df.groupby("month")[["won_amount_sum", "won_list_price_sum"]].sum(min_count=1)
    discount = (1.0 - g["won_amount_sum"] / g["won_list_price_sum"].replace(0, np.nan))
    floor = df.dropna(subset=["share_won_at_band_floor"]).assign(
        at_floor=lambda d: d["share_won_at_band_floor"] * d["new_business_won_count"])
    return {
        "discount_rate_vs_list": discount.dropna().rename("discount_rate_vs_list"),
        "deal_size_trend_within_band": _ratio_by_month(
            floor, "at_floor", "new_business_won_count", "deal_size_trend_within_band"),
    }


def _renewal_win_rate_series(as_of_date: date, con) -> pd.Series:
    """Closed-won renewals / closed renewals, by close month. Source mart:
    mart_deal_funnel, Commercial + Enterprise."""
    df = _rep_sold_deal_funnel(as_of_date, con)
    df = df.assign(closed=df["renewal_won_count"] + df["renewal_lost_count"])
    return _ratio_by_month(df, "renewal_won_count", "closed", "renewal_win_rate")


# A partial workflow chain (completion below the threshold) exists only in the
# months leading up to a churn: generators/config.py DECLINE_MONTHS_BEFORE_CHURN
# (mirrored here, and tied to the config by tests) is the months of decline
# before the churn month itself, so a month m shows partial chains caused by
# churns up to m + DECLINE months later. The data window ends in 2025-12 and that
# month is itself truncated (4 churn events against about 75 in a normal month),
# so a month m is clean only if m + DECLINE < the last month: the last
# DECLINE + 1 months of the window under-count partial chains and are blanked,
# not read (the partial share is 6.0% in 2025-07 and already 4.7% in 2025-08).
_WORKFLOW_CHAIN_DECLINE_MONTHS = 4
_WORKFLOW_CHAIN_PRECHURN_MONTHS = _WORKFLOW_CHAIN_DECLINE_MONTHS + 1


def _drop_censored_chain_tail(series: pd.Series, con) -> pd.Series:
    """Removes the last _WORKFLOW_CHAIN_PRECHURN_MONTHS months of the data
    window from a workflow-chain series (see the constant above). The window
    end is metadata about the mart, not business data after as_of_date; for an
    as_of_date before the tail nothing is removed."""
    last = pd.Timestamp(con.execute(
        "select max(month) from main_marts.mart_workflow_chain_health").fetchone()[0])
    cutoff = last - pd.DateOffset(months=_WORKFLOW_CHAIN_PRECHURN_MONTHS)
    return series[series.index <= cutoff]


def _workflow_chain_breadth_series(as_of_date: date, con) -> pd.Series:
    """Share of the month's chain accounts below the completion threshold,
    all three segments. Grain: one value per month. Source mart:
    mart_workflow_chain_health."""
    df = load_workflow_chain_health(as_of_date, con=con)
    return _drop_censored_chain_tail(
        _ratio_by_month(df, "partial_chain_account_count", "accounts_with_chain",
                        "workflow_chain_underutilization"), con)


def _workflow_chain_leaf_series(as_of_date: date, con) -> Dict[str, pd.Series]:
    """Layer-3 candidates under Workflow chain under-utilization. Grain: one
    value per month, all three segments. Source mart:
    mart_workflow_chain_health. The Actions-weighted idle share is a
    different statistic from the Layer-2 account-count breadth."""
    df = load_workflow_chain_health(as_of_date, con=con)
    return {k: _drop_censored_chain_tail(v, con) for k, v in {
        "ingestion_without_completion_rate": _ratio_by_month(
            df, "ingestion_without_completion_actions_sum", "upstream_actions_sum",
            "ingestion_without_completion_rate"),
        "mid_chain_abandonment": _ratio_by_month(
            df, "sustained_partial_account_count", "accounts_with_chain",
            "mid_chain_abandonment"),
        "full_vs_partial_chain_share": _ratio_by_month(
            df, "full_chain_account_count", "accounts_with_chain",
            "full_vs_partial_chain_share"),
    }.items()}


def _overage_share_series(as_of_date: date, con) -> pd.Series:
    """Overage MRR as a share of total MRR (a ratio of sums), Commercial +
    Enterprise. Grain: one value per month. Source mart:
    mart_consumption_utilization. Dollars, not a realization rate: the rate
    is identically 100% (billing is unit price times max(committed,
    utilized) on every account-month)."""
    df = load_consumption_utilization(as_of_date, con=con)
    return _ratio_by_month(df, "overage_mrr", "total_mrr", "overage_realization")


def _account_health_input_series(as_of_date: date, con) -> Dict[str, pd.Series]:
    """The four Account-health-score inputs as monthly company-wide series,
    one value per month (all three segments). Source mart:
    mart_account_health -- the same columns the health score reads."""
    ah = load_account_health(as_of_date, con=con)
    ah = ah.assign(severity_load=ah["ticket_count"] * ah["avg_ticket_severity_score"].fillna(0.0))
    g = ah.groupby("month")
    return {
        "usage_trend_account_relative": _usage_dip_breadth_series(as_of_date, con),
        "support_ticket_volume_severity": (
            g["severity_load"].sum() / g["account_id"].size()).rename("support_ticket_volume_severity"),
        "engagement_login_frequency": (
            g["login_count"].sum() / g["account_id"].size()).rename("engagement_login_frequency"),
        "am_sentiment_notes": g["avg_am_sentiment_score"].mean().dropna().rename("am_sentiment_notes"),
    }


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

    A sibling needs the full trailing window (`baseline_months` observations)
    to be ranked; with fewer its deviation is blank and it is dropped, as a
    series with no baseline at all always was.

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
        if stats["baseline_n"] < baseline_months:
            # Insufficient baseline: a sibling needs the full trailing window to be
            # ranked. Its deviation from a one- to seven-observation mean is noise
            # that would win rankings (and seed persistence streaks) at the start of
            # a series. The value and the observation count stay visible; the
            # deviation and baseline are blank, so _with_signal() drops it and it is
            # reported as a missing sibling, the path a baseline-less series already took.
            stats = {**stats, "baseline": np.nan, "deviation_pct": np.nan,
                     "deviation_z": np.nan}
        rows.append({
            "metric_key": key, "label": node.label, "layer": node.layer,
            "parent_key": node.parent_key, "computability": node.computability,
            "cross_reference_to": node.cross_reference_to,
            "cross_reference_label": (_TREE[node.cross_reference_to].label
                                      if node.cross_reference_to else None),
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
# Persistence -- is it the same Layer-2 driver, adverse, month after month?
# =====================================================================
#
# DEFINITION (the one place it is written down; the methods doc quotes it).
#
# For a drill-down whose Layer-2 outlier is D under Layer-1 node P, the
# persistence STREAK is the number of consecutive months, counting back from
# the evaluation month, in which ALL of the following hold:
#
#   1. Sibling comparison. At least 2 of P's ranking-eligible children have a
#      usable value and trailing baseline in that month (the same
#      `_with_signal()` rule the drill-down uses). A month with fewer is a
#      month with no comparison, and the streak ends there -- a lone sibling
#      would trivially "persist" (single-candidate branches such as Magic
#      number or Expansion are therefore `not_applicable`, not a streak).
#   2. Same driver. D is the top-ranked sibling that month under P's own
#      ranking basis (relative deviation, or absolute deviation for the
#      additive_share branches), ranked by `rank_siblings()` against each
#      sibling's own trailing `baseline_months`-month baseline. If another
#      sibling is the top outlier that month the streak ends: it RESETS to
#      the new driver, never accumulates across drivers.
#   3. No tie. If the top two siblings tie on the ranking key (float-equal,
#      relative tolerance 1e-9) there is no single outlier that month, so the
#      streak ends. Persistence is never claimed on a coin flip.
#   4. Adverse direction. D moved away from its baseline in the direction
#      that hurts P: `adverse_direction(D)` is "up" or "down" from the sign of
#      D's effect on P (`_EFFECT_ON_PARENT`) combined with P's own
#      `favorable_direction`. Movement in the favorable direction, or no
#      movement, ends the streak.
#
# Every prior month is read as of that month: its own series are cut at the
# month, so no later value reaches a baseline or a rank (a deviation never
# uses the future in any case; the cut makes that explicit and keeps a
# caller's series provider honest). The evaluation month itself must be the
# month the drill-down was built for; when that month is the truncated final
# month of the data window the status is `not_applicable`.
#
# The flag fires when the streak reaches K_PERSISTENCE (PROPOSED, not yet
# confirmed). The flag says the same driver keeps being the adverse outlier
# against a trailing baseline; it does not say why, and a series that trends
# adversely stays above its own trailing mean for several months, so some
# persistence is the trailing-baseline method rather than a recurring event.

PERSISTENCE_FLAGGED = "flagged"
PERSISTENCE_NOT_FLAGGED = "not_flagged"
PERSISTENCE_NOT_APPLICABLE = "not_applicable"

# `reason` codes of a not_applicable record
PERSISTENCE_NA_SINGLE_CANDIDATE = "single_candidate_read"
PERSISTENCE_NA_NO_OUTLIER = "no_layer2_outlier"
PERSISTENCE_NA_TRUNCATED = "truncated_final_month"
PERSISTENCE_NA_NO_DIRECTION = "no_adverse_direction_defined"

# `streak_break.reason` codes: why the streak did not extend one month further
BREAK_DRIVER_CHANGED = "driver_changed"
BREAK_NOT_ADVERSE = "not_adverse"
BREAK_TIE = "tie_at_top"
BREAK_NO_COMPARISON = "no_sibling_comparison"
BREAK_START_OF_HISTORY = "start_of_history"

PERSISTENCE_BASIS = (
    "The same Layer-2 driver as the largest adverse outlier against its own trailing "
    "baseline, counted back from the reporting month. Sibling comparisons with at least "
    "2 computable children only.")
PERSISTENCE_THRESHOLD_STATUS = "Proposed, not yet confirmed"
# Shown beside every applicable record: at this sample size the flag fires about as
# often as it does on month-shuffled series (methods doc), so it marks a repeat only.
PERSISTENCE_CAVEAT = (
    "Repeat marker: the same driver as the adverse outlier in consecutive months; not "
    "evidence of a trend or cause.")

# Which way a Layer-2 child's value moves its Layer-1 parent: +1 when a higher
# child value raises the parent, -1 when it lowers it, None when no direction
# is defined. Read off the tree's own arithmetic (see docs/acme-corp-gtm-metric-tree.md):
# New logo revenue is the product of its three children; contraction + churn
# rises with usage-dip breadth and workflow-chain under-utilization and falls
# with renewal win rate; NRR/GRR are 1 + expansion - contraction - churn;
# Magic number divides by S&M cost; Consumption payback divides CAC by margin;
# Onboarding/CS efficiency is touches per automated Action; AM efficiency
# divides by AM cost; Activation is a time, so more completed onboarding
# shortens it. Tenure-at-churn has no direction: an earlier-lifecycle churn
# is not unambiguously better or worse for logo retention.
_EFFECT_ON_PARENT: Dict[str, Optional[int]] = {
    "pipeline_generated": +1,
    "win_rate": +1,
    "avg_initial_commitment": +1,
    "onboarding_completion_rate": -1,
    "overage_realization": +1,
    "cyclical_vs_structural_usage_dip": +1,
    "workflow_chain_underutilization": +1,
    "renewal_win_rate": -1,
    "sm_cost": -1,
    "cac_by_channel": +1,
    "utilized_vs_committed_action_volume": -1,
    "am_touchpoint_volume": +1,
    "automated_action_volume": -1,
    "am_cost_by_segment": -1,
    "nrr_expansion_rate": +1,
    "nrr_contraction_rate": -1,
    "nrr_churn_rate": -1,
    "grr_contraction_rate": -1,
    "grr_churn_rate": -1,
    "tenure_at_churn": None,
}


def _verify_persistence_table() -> None:
    """Every ranking-eligible Layer-2 node the engine can compute carries a
    declared effect on its parent, and the table names nothing else -- so a
    node added to the tree cannot silently get no adverse direction, and a
    renamed node cannot leave a stale entry. Raises, not asserts."""
    needed = {n.key for n in _TREE.values()
              if n.layer == 2 and n.is_ranking_sibling and n.computability != NOT_COMPUTABLE}
    missing, stale = needed - set(_EFFECT_ON_PARENT), set(_EFFECT_ON_PARENT) - needed
    if missing or stale:
        raise ValueError(f"_EFFECT_ON_PARENT out of step with the tree: missing {sorted(missing)}, "
                         f"stale {sorted(stale)}")
    for key, effect in _EFFECT_ON_PARENT.items():
        if effect not in (+1, -1, None):
            raise ValueError(f"{key}: effect on parent must be +1, -1 or None")
        if _TREE[_TREE[key].parent_key].favorable_direction not in ("higher", "lower"):
            raise ValueError(f"{key}: parent has no favorable_direction")


_verify_persistence_table()


def adverse_direction(layer2_key: str) -> Optional[str]:
    """'up' or 'down': the direction in which this Layer-2 node's value
    moving away from its baseline hurts its Layer-1 parent, from the node's
    declared effect on the parent and the parent's favorable_direction. None
    when the node has no defined direction (tenure-at-churn)."""
    node = _TREE[layer2_key]
    if node.layer != 2:
        raise ValueError(f"{layer2_key} is layer {node.layer}; persistence is read at Layer 2")
    effect = _EFFECT_ON_PARENT.get(layer2_key)
    if effect is None:
        return None
    parent_is_hurt_by_rising = _TREE[node.parent_key].favorable_direction == "lower"
    return "up" if parent_is_hurt_by_rising == (effect > 0) else "down"


def _read_direction(adverse: str, absolute_deviation: float) -> str:
    if absolute_deviation == 0 or pd.isna(absolute_deviation):
        return "flat"
    return "adverse" if (absolute_deviation > 0) == (adverse == "up") else "favorable"


def _ranking_key(parent_key: str) -> str:
    return ("abs_absolute_deviation"
            if _TREE[parent_key].sibling_comparison_basis == "additive_share"
            else "abs_deviation_pct")


def _scored_read(parent_key: str, series_by_key: Dict[str, pd.Series], month: pd.Timestamp,
                 baseline_months: int) -> pd.DataFrame:
    """One month's usable sibling ranking, from series cut at `month`."""
    cut = {k: s[s.index <= month] for k, s in series_by_key.items()}
    if not cut:
        return pd.DataFrame()
    return _with_signal(parent_key, rank_siblings(parent_key, cut, month, baseline_months))


def _top_two_tied(parent_key: str, scored: pd.DataFrame) -> bool:
    if len(scored) < 2:
        return False
    col = _ranking_key(parent_key)
    return math.isclose(float(scored.iloc[0][col]), float(scored.iloc[1][col]),
                        rel_tol=1e-9, abs_tol=0.0)


def _month_label(month: pd.Timestamp) -> str:
    return pd.Timestamp(month).strftime("%Y-%m")


def _persistence_note(status: str, label: Optional[str], streak: Optional[int], k: int,
                      reason: Optional[str], direction: Optional[str],
                      first_month: Optional[str], brk: Optional[dict]) -> str:
    plural = "" if streak == 1 else "s"
    if status == PERSISTENCE_NOT_APPLICABLE:
        return {
            PERSISTENCE_NA_SINGLE_CANDIDATE: (
                "Only one Layer-2 child has a computable value, so there is no sibling "
                "comparison and no streak is tracked."),
            PERSISTENCE_NA_NO_OUTLIER: (
                "No Layer-2 outlier was identified, so there is no driver to track."),
            PERSISTENCE_NA_TRUNCATED: (
                "The evaluation month is the truncated final month of the data window, so "
                "no streak is computed."),
            PERSISTENCE_NA_NO_DIRECTION: (
                f"{label} has no defined adverse direction, so no streak is computed."),
        }[reason]
    if status == PERSISTENCE_FLAGGED:
        return (f"{label} has been the largest adverse Layer-2 outlier against its own "
                f"trailing baseline for {streak} consecutive months, since {first_month[:7]}.")
    # not flagged
    if streak == 0:
        if brk and brk["reason"] == BREAK_TIE:
            return ("Two Layer-2 siblings tie for the largest outlier this month, so no single "
                    "driver can be tracked.")
        if direction == "favorable":
            return (f"{label} is the largest Layer-2 outlier but is moving in the favorable "
                    "direction, so there is no adverse streak.")
        return (f"{label} is the largest Layer-2 outlier but is not moving in the adverse "
                "direction, so there is no adverse streak.")
    tail = ""
    if brk:
        when = brk["month"][:7]
        tail = {
            BREAK_DRIVER_CHANGED: f" In {when} the largest outlier was {brk.get('outlier_label')}.",
            BREAK_NOT_ADVERSE: f" In {when} it was not moving in the adverse direction.",
            BREAK_TIE: f" In {when} two siblings tied for the largest outlier.",
            BREAK_NO_COMPARISON: f" In {when} fewer than 2 siblings had a computable value.",
            BREAK_START_OF_HISTORY: " No earlier months are available.",
        }[brk["reason"]]
    return (f"{label} is the largest adverse Layer-2 outlier this month; the streak is "
            f"{streak} month{plural}, short of the {k}-month flag.{tail}")


def _persistence_record(status: str, *, parent_key: str, k: int, driver_key: Optional[str],
                        reason: Optional[str] = None, streak: Optional[int] = None,
                        direction: Optional[str] = None, adverse: Optional[str] = None,
                        detail: Optional[List[dict]] = None, brk: Optional[dict] = None) -> dict:
    label = _TREE[driver_key].label if driver_key else None
    first_month = detail[-1]["month"] if detail else None
    return {
        "status": status,
        "flagged": status == PERSISTENCE_FLAGGED,
        "threshold_months": k,
        "threshold_status": PERSISTENCE_THRESHOLD_STATUS,
        "streak_months": streak,
        "driver_key": driver_key,
        "driver_label": label,
        "driver_direction": direction,
        "adverse_direction": adverse,
        "first_month_of_streak": first_month,
        "streak_detail": detail or [],
        "streak_break": brk,
        "reason": reason,
        "basis": PERSISTENCE_BASIS,
        "caveat": PERSISTENCE_CAVEAT,
        "note": _persistence_note(status, label, streak, k, reason, direction, first_month, brk),
    }


def compute_persistence(parent_key: str, driver_key: Optional[str],
                        evaluation_month: pd.Timestamp,
                        series_as_of: Callable[[pd.Timestamp], Dict[str, pd.Series]],
                        baseline_months: int = _TRAILING_BASELINE_MONTHS,
                        k: int = K_PERSISTENCE,
                        evaluation_is_truncated: bool = False) -> dict:
    """The persistence record for one drill-down: how many consecutive months
    (ending at `evaluation_month`) `driver_key` was the adverse top outlier
    among its siblings under `parent_key` (definition above). Grain: one
    record per drill-down. Pure given `series_as_of`, a callable returning
    the parent's Layer-2 series as available at the end of a given month
    (the engine rebuilds them from the marts as of that month; the synthetic
    scenarios cut a fixed history). Deterministic -- no stochastic step."""
    parent = _TREE[parent_key]
    if parent.layer != 1:
        raise ValueError(f"{parent_key} is layer {parent.layer}; persistence heads at Layer 1")
    common = dict(parent_key=parent_key, k=k, driver_key=driver_key)
    if driver_key is None:
        return _persistence_record(PERSISTENCE_NOT_APPLICABLE, reason=PERSISTENCE_NA_NO_OUTLIER,
                                   **common)
    driver = _TREE[driver_key]
    if driver.layer != 2 or driver.parent_key != parent_key:
        raise ValueError(f"{driver_key} is not a Layer-2 child of {parent_key}")
    if evaluation_is_truncated:
        return _persistence_record(PERSISTENCE_NOT_APPLICABLE, reason=PERSISTENCE_NA_TRUNCATED,
                                   **common)
    adverse = adverse_direction(driver_key)
    if adverse is None:
        return _persistence_record(PERSISTENCE_NOT_APPLICABLE,
                                   reason=PERSISTENCE_NA_NO_DIRECTION, **common)

    current = series_as_of(evaluation_month)
    first_observation = min((s.dropna().index.min() for s in current.values() if len(s.dropna())),
                            default=None)
    scored_now = _scored_read(parent_key, current, evaluation_month, baseline_months)
    if len(scored_now) < 2:
        return _persistence_record(PERSISTENCE_NOT_APPLICABLE,
                                   reason=PERSISTENCE_NA_SINGLE_CANDIDATE, adverse=adverse,
                                   **common)
    if scored_now.iloc[0]["metric_key"] != driver_key:
        raise ValueError(
            f"{driver_key} is not the top-ranked sibling of {parent_key} at "
            f"{_month_label(evaluation_month)}; persistence tracks the drill-down's own outlier")

    streak, detail, brk = 0, [], None
    month = pd.Timestamp(evaluation_month)
    while True:
        scored = scored_now if month == evaluation_month else _scored_read(
            parent_key, series_as_of(month), month, baseline_months)
        if len(scored) < 2:
            reason = (BREAK_START_OF_HISTORY
                      if first_observation is None
                      or month < first_observation + pd.DateOffset(months=baseline_months)
                      else BREAK_NO_COMPARISON)
            brk = {"month": month.date().isoformat(), "reason": reason,
                   "outlier_key": None, "outlier_label": None}
            break
        top = scored.iloc[0]
        if _top_two_tied(parent_key, scored):
            brk = {"month": month.date().isoformat(), "reason": BREAK_TIE,
                   "outlier_key": None, "outlier_label": None}
            break
        if top["metric_key"] != driver_key:
            brk = {"month": month.date().isoformat(), "reason": BREAK_DRIVER_CHANGED,
                   "outlier_key": top["metric_key"], "outlier_label": top["label"]}
            break
        if _read_direction(adverse, float(top["absolute_deviation"])) != "adverse":
            brk = {"month": month.date().isoformat(), "reason": BREAK_NOT_ADVERSE,
                   "outlier_key": driver_key, "outlier_label": driver.label}
            break
        streak += 1
        detail.append({"month": month.date().isoformat(),
                       "deviation_pct": _none_float(top["deviation_pct"]),
                       "baseline_n": int(top["baseline_n"])})
        month = month - pd.DateOffset(months=1)

    top_now = scored_now.iloc[0]
    direction = _read_direction(adverse, float(top_now["absolute_deviation"]))
    if _top_two_tied(parent_key, scored_now):
        direction = None
    status = PERSISTENCE_FLAGGED if streak >= k else PERSISTENCE_NOT_FLAGGED
    return _persistence_record(status, streak=streak, direction=direction, adverse=adverse,
                               detail=detail, brk=brk, **common)


def _none_float(v) -> Optional[float]:
    return None if v is None or pd.isna(v) else float(v)


def _last_month_in_marts(con) -> pd.Timestamp:
    return pd.Timestamp(con.execute(
        "select max(month) from main_marts.mart_growth_bridge").fetchone()[0])


def _asof_series_provider(parent_key: str, evaluation_series: Dict[str, pd.Series],
                          evaluation_month: pd.Timestamp, con) -> Callable:
    """Series for a prior month, rebuilt from the marts AS OF that month's end
    (every loader filters month <= as_of), so a prior month is read with the
    data that existed then. The evaluation month reuses the series the
    drill-down already built."""
    cache = {pd.Timestamp(evaluation_month): evaluation_series}

    def provider(month: pd.Timestamp) -> Dict[str, pd.Series]:
        key = pd.Timestamp(month)
        if key not in cache:
            as_of = (key + pd.offsets.MonthEnd(0)).date()
            cache[key] = _build_child_series(parent_key, as_of, con)
        return cache[key]

    return provider


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
    # Long-form versions of the notes that have one: [{"note": <short>, "detail": <long>}].
    notes_detail: List[dict] = field(default_factory=list)
    # compute_persistence()'s record for this drill-down's Layer-2 driver.
    # None only for hand-built synthetic drill-downs that do not exercise it.
    persistence: Optional[dict] = None

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
        if self.persistence is not None:
            if self.persistence["status"] not in (PERSISTENCE_FLAGGED, PERSISTENCE_NOT_FLAGGED,
                                                  PERSISTENCE_NOT_APPLICABLE):
                raise ValueError(f"unknown persistence status {self.persistence['status']!r}")
            if self.persistence["driver_key"] != self.layer2_key:
                raise ValueError(
                    "persistence tracks the drill-down's own Layer-2 outlier "
                    f"({self.layer2_key}), not {self.persistence['driver_key']}")
            if self.persistence["flagged"] != (self.persistence["status"] == PERSISTENCE_FLAGGED):
                raise ValueError("persistence.flagged disagrees with persistence.status")

    def to_dict(self) -> dict:
        l1, l2 = _TREE[self.layer1_key], (_TREE[self.layer2_key] if self.layer2_key else None)
        return {
            "layer1": {"metric_key": l1.key, "label": l1.label, "layer": l1.layer,
                       "pillar": l1.pillar, "variance_pct": self.layer1_variance_pct,
                       "mechanism": self.layer1_mechanism},
            "layer2_outlier": None if l2 is None else {
                "metric_key": l2.key, "label": l2.label, "layer": l2.layer,
                "parent_key": l2.parent_key, "computability": l2.computability,
                "cross_reference_to": l2.cross_reference_to,
                "cross_reference_label": (_TREE[l2.cross_reference_to].label
                                          if l2.cross_reference_to else None)},
            "layer3_evidence": [{"metric_key": k, "label": _TREE[k].label, "layer": _TREE[k].layer,
                                 "parent_key": _TREE[k].parent_key} for k in self.layer3_keys],
            "layer3_status": self.layer3_status,
            "branch_max_depth_in_tree": self.branch_max_depth_in_tree,
            "sibling_coverage": self.sibling_coverage,
            "notes": self.notes,
            "notes_detail": self.notes_detail,
            "persistence": self.persistence,
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
      * plan_diff -- the 10 metrics where both sides exist.
      * trailing_baseline -- Activation only, which has no plan row by
        design (mart_gtm_plan's header; design brief's '2.4d last month').
      * not_computable -- a Layer-1 node whose plan_comparability is
        NOT_COMPUTABLE. No Layer-1 node is in that state in the current
        tree (magic number and AM efficiency became caveated plan_diff
        nodes once rep-cost data existed); the branch is retained for
        any node whose actual a future data change makes undefined again.
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
            "plan_comparability_detail": node.plan_comparability_detail,
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
        last = _last_month_in_marts(con)
    finally:
        con.close()
    is_last = month == last
    return {
        "last_month_in_marts": last,
        "evaluation_month": month,
        "evaluation_month_is_last_month_in_window": is_last,
        "truncation_warning": (
            "The evaluation month is the final month of the simulated 36-month window. "
            "Contraction is inflated (each still-active account's last observed month lands "
            "in the contraction bucket), Enterprise marketing spend is missing so blended CAC "
            "is incomplete, and Action volume is partial. Variances for this month reflect "
            "end-of-window truncation, not business signal; the prior month is the last "
            "representative evaluation period."
        ) if is_last else None,
    }


def _build_drilldown(scorecard_row, as_of_date, month, baseline_months, con) -> Drilldown:
    l1_key = scorecard_row["metric_key"]
    l2_series = _build_child_series(l1_key, as_of_date, con)
    ranked = rank_siblings(l1_key, l2_series, month, baseline_months) if l2_series \
        else pd.DataFrame()
    coverage = _sibling_coverage(l1_key, _with_signal(l1_key, ranked))
    notes: List[str] = []
    notes_detail: List[dict] = []
    l1_label = _TREE[l1_key].label
    if scorecard_row["plan_comparability"] == CAVEATED:
        notes.append(scorecard_row["plan_comparability_note"])
        if scorecard_row["plan_comparability_detail"]:
            notes_detail.append({"note": scorecard_row["plan_comparability_note"],
                                 "detail": scorecard_row["plan_comparability_detail"]})
    if not ranked.empty and "pipeline_generated" in set(ranked["metric_key"]):
        notes.append(PIPELINE_GENERATED_SCOPE_NOTE)
        notes_detail.append({"note": PIPELINE_GENERATED_SCOPE_NOTE,
                             "detail": PIPELINE_GENERATED_SCOPE_DETAIL})

    if l1_key in ("nrr", "grr"):
        drivers = ("expansion, contraction, churn drivers" if l1_key == "nrr"
                   else "contraction, churn drivers")
        notes.append(
            f"Tree definition: {l1_label}'s child in the metric tree is a single reference, "
            f"'See Growth \u2014 {drivers}'. The engine expands that reference into the named "
            "drivers, each shown as a share of starting revenue and linked to the Growth "
            "driver it mirrors.")
        notes.append(
            f"Grain: the {l1_label} figure is the trailing-12-month compounded rate "
            "(annual-equivalent, as in the plan), while the drivers are read monthly. A driver "
            "can point opposite to the annualised parent in a single month, so the driver "
            "ranking shows what moved this month, not a decomposition of the 12-month figure.")

    scored = _with_signal(l1_key, ranked)
    truncated = month == _last_month_in_marts(con)
    if scored.empty:
        notes.append(
            f"No Layer-2 child of {l1_label} has a computable actual with a usable trailing "
            "baseline, so no outlier is identified. The Layer-1 variance stands alone; the "
            "missing children and reasons are listed with the drill-down.")
        return Drilldown(
            layer1_key=l1_key, layer2_key=None, layer3_keys=[],
            layer1_variance_pct=scorecard_row["variance_pct"],
            layer1_mechanism=scorecard_row["mechanism"],
            sibling_ranking=ranked, sibling_coverage=coverage,
            layer3_status=L3_NO_COMPUTABLE_DATA, layer3_evidence=pd.DataFrame(),
            branch_max_depth_in_tree=branch_max_depth(l1_key), notes=notes,
            notes_detail=notes_detail,
            persistence=compute_persistence(l1_key, None, month, lambda m: l2_series,
                                            baseline_months, evaluation_is_truncated=truncated))

    l2_key = scored.iloc[0]["metric_key"]
    l2_label = _TREE[l2_key].label
    if not coverage["is_genuine_sibling_comparison"]:
        notes.append(
            f"Single-candidate read: only {coverage['computable_siblings']} of "
            f"{coverage['eligible_siblings']} Layer-2 children of {l1_label} has a computable "
            "actual, so no sibling comparison is possible.")
    l3_series = _build_child_series(l2_key, as_of_date, con)
    l3 = layer3_evidence(l2_key, l3_series, month, baseline_months)
    if l3["status"] == L3_BRANCH_DEPTH_2:
        notes.append(f"{l2_label} has no Layer-3 children in the metric tree; this branch is "
                     "two layers deep.")
    elif l3["status"] == L3_NO_COMPUTABLE_DATA:
        notes.append(f"{l2_label} has Layer-3 children in the tree, but none is computable "
                     "from the reporting tables; the missing leaves and reasons are listed "
                     "with the drill-down.")

    return Drilldown(
        layer1_key=l1_key, layer2_key=l2_key, layer3_keys=l3["keys"],
        layer1_variance_pct=scorecard_row["variance_pct"],
        layer1_mechanism=scorecard_row["mechanism"],
        sibling_ranking=ranked, sibling_coverage=coverage,
        layer3_status=l3["status"], layer3_evidence=l3.get("ranking", pd.DataFrame()),
        branch_max_depth_in_tree=branch_max_depth(l1_key), notes=notes,
        notes_detail=notes_detail,
        persistence=compute_persistence(
            l1_key, l2_key, month, _asof_series_provider(l1_key, l2_series, month, con),
            baseline_months, evaluation_is_truncated=truncated))


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
            # A Layer-3 child is surfaced only under a Layer-2 outlier, and an
            # outlier must itself be computable: leaves under a blocked
            # Layer-2 parent exist but can never appear in a drill-down.
            "layer3_computable_reachable": any(
                c.computability in (COMPUTABLE, PARTIAL)
                for s in computable for c in children_of(s.key)),
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
            "tree, so its three computable leaves are supplied (stage-to-stage conversion is "
            "degenerate and has no series) and the engine must surface the two largest. "
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
            "rep_capacity_ramp_mix": _synthetic_series(_SYNTHETIC_MONTH, 0.60, 0.005),
        },
        "expected_layer2_key": "win_rate",
        "expected_layer3_keys": ["poc_pass_rate", "loss_reason_mix"],
        "expected_layer3_status": L3_SURFACED,
        "expected_branch_max_depth": 3,
    },
    {
        "name": "contraction_workflow_chain_branch_with_layer3",
        "description": (
            "Contraction + churned revenue (Layer 1, Growth) runs 25% over plan. Of its true "
            "Layer-2 siblings, workflow chain under-utilization sits 30% above its own "
            "trailing baseline while renewal win rate (-4%) and usage-dip breadth (+2%) are "
            "near flat. The workflow-chain branch has three computable Layer-3 leaves; the "
            "engine must name the branch, then surface the two largest leaves, mid-chain "
            "abandonment (+26%) and ingestion-without-completion (+8%), and leave the "
            "full-chain share (-1%, the parent's own complement) out."),
        "layer1_key": "contraction_churned_revenue",
        "layer1_variance_pct": 0.25,
        "layer2_series": {
            "workflow_chain_underutilization": _synthetic_series(_SYNTHETIC_MONTH, 0.055, 0.30,
                                                                 jitter=(0.01, -0.01, 0.02, -0.02, 0.0, 0.01, -0.01, 0.0)),
            "renewal_win_rate": _synthetic_series(_SYNTHETIC_MONTH, 0.88, -0.04,
                                                  jitter=(0.01, -0.01, 0.0, 0.01, -0.01, 0.0, 0.0, 0.0)),
            "cyclical_vs_structural_usage_dip": _synthetic_series(_SYNTHETIC_MONTH, 0.028, 0.02,
                                                                  jitter=(0.02, -0.02, 0.01, -0.01, 0.0, 0.0, 0.01, -0.01)),
        },
        "layer3_series": {
            "mid_chain_abandonment": _synthetic_series(_SYNTHETIC_MONTH, 0.044, 0.26),
            "ingestion_without_completion_rate": _synthetic_series(_SYNTHETIC_MONTH, 0.089, 0.08),
            "full_vs_partial_chain_share": _synthetic_series(_SYNTHETIC_MONTH, 0.945, -0.01),
        },
        "expected_layer2_key": "workflow_chain_underutilization",
        "expected_layer3_keys": ["mid_chain_abandonment", "ingestion_without_completion_rate"],
        "expected_layer3_status": L3_SURFACED,
        "expected_branch_max_depth": 3,
    },
    {
        "name": "expansion_overage_single_candidate_depth_2_leaf",
        "description": (
            "Expansion consumption revenue (Layer 1, Growth) beats plan by 30%. Only one of "
            "its two Layer-2 children, overage realization, has a computable series (wallet "
            "share progression has no footprint denominator), so the read is a single-"
            "candidate one and must be reported as not a genuine sibling comparison. "
            "Overage realization is a leaf: it has no Layer-3 children in the tree, so the "
            "engine must return layer3_status='branch_depth_2' for it even though the "
            "branch as a whole (through wallet share progression) is three layers deep."),
        "layer1_key": "expansion_consumption_revenue",
        "layer1_variance_pct": 0.30,
        "layer2_series": {
            "overage_realization": _synthetic_series(_SYNTHETIC_MONTH, 0.33, 0.12,
                                                     jitter=(0.01, -0.01, 0.02, -0.02, 0.0, 0.01, -0.01, 0.0)),
        },
        "layer3_series": {},
        "expected_layer2_key": "overage_realization",
        "expected_layer3_keys": [],
        "expected_layer3_status": L3_BRANCH_DEPTH_2,
        "expected_branch_max_depth": 3,
        "expects_single_candidate": True,
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
    if scenario.get("expects_single_candidate") and \
            _sibling_coverage(l1_key, ranked)["is_genuine_sibling_comparison"]:
        failures.append("a single-candidate read was reported as a genuine sibling comparison")
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


# ---------------------------------------------------------------------
# Persistence scenarios: hand-built month-by-month histories with a known
# streak. Same role as SYNTHETIC_SCENARIOS above (the correctness check for a
# structural artifact), kept as a second suite because a persistence case is a
# history, not a single evaluation month. Each is driven through the same
# compute_persistence() / Drilldown path the real engine uses.
# ---------------------------------------------------------------------

_QUIET_JITTER = (0.005, -0.005)


def _history(levels: Dict[int, float], *, n_months: int = 14, jitter: bool = False,
             base: float = 100.0, missing: Sequence[int] = (), future: Dict[int, float] = None
             ) -> pd.Series:
    """A monthly series ending at _SYNTHETIC_MONTH (offset 0). `levels` maps a
    month offset (0 = evaluation month, -1 = the month before ...) to a
    multiplier of `base`; every other month sits at `base`, optionally with a
    +/-0.5% alternating jitter so a quiet sibling is a deterministic, tiny,
    non-tied outlier rather than an exact zero. `missing` offsets are left out
    of the series (a month with no value); `future` maps positive offsets to
    multipliers appended AFTER the evaluation month (to prove they are never
    read)."""
    values = {}
    for off in range(-(n_months - 1), 1):
        if off in missing:
            continue
        mult = levels.get(off, 1.0 + (_QUIET_JITTER[off % 2] if jitter else 0.0))
        values[_SYNTHETIC_MONTH + pd.DateOffset(months=off)] = base * mult
    for off, mult in (future or {}).items():
        values[_SYNTHETIC_MONTH + pd.DateOffset(months=off)] = base * mult
    return pd.Series(values).sort_index()


def _spikes(offsets: Sequence[int], size: float) -> Dict[int, float]:
    return {off: 1.0 + size for off in offsets}


def _persistence_scenarios() -> List[dict]:
    pay = "consumption_payback"
    return [
        {
            "name": "streak_of_one_is_not_flagged",
            "description": (
                "CAC by channel (adverse = up for Consumption payback) jumps +30% in the "
                "evaluation month only. The month before, the other sibling is the largest "
                "(tiny) outlier. Streak 1, below the 2-month flag."),
            "parent_key": pay, "driver_key": "cac_by_channel",
            "series": {"cac_by_channel": _history(_spikes([0], 0.30)),
                       "utilized_vs_committed_action_volume": _history({}, jitter=True)},
            "expected": {"status": "not_flagged", "streak_months": 1, "first_month_offset": 0,
                         "break_reason": BREAK_DRIVER_CHANGED},
        },
        {
            "name": "streak_of_exactly_two_is_flagged",
            "description": (
                "CAC by channel +30% in the evaluation month and the month before. Streak 2: "
                "the boundary case, flagged at K_PERSISTENCE = 2."),
            "parent_key": pay, "driver_key": "cac_by_channel",
            "series": {"cac_by_channel": _history(_spikes([-1, 0], 0.30)),
                       "utilized_vs_committed_action_volume": _history({}, jitter=True)},
            "expected": {"status": "flagged", "streak_months": 2, "first_month_offset": -1,
                         "break_reason": BREAK_DRIVER_CHANGED},
        },
        {
            "name": "streak_of_three_is_flagged_with_its_first_month",
            "description": (
                "CAC by channel +30% for three consecutive months. Streak 3, and the record "
                "names the first month of the streak."),
            "parent_key": pay, "driver_key": "cac_by_channel",
            "series": {"cac_by_channel": _history(_spikes([-2, -1, 0], 0.30)),
                       "utilized_vs_committed_action_volume": _history({}, jitter=True)},
            "expected": {"status": "flagged", "streak_months": 3, "first_month_offset": -2,
                         "break_reason": BREAK_DRIVER_CHANGED},
        },
        {
            "name": "driver_change_resets_the_streak",
            "description": (
                "CAC by channel is the adverse outlier in the evaluation month and the month "
                "before, but two months back the margin leg (adverse = down) fell 30% and was "
                "the larger outlier, and CAC was adverse again three months back. The streak "
                "is 2, not 4: it resets at a change of driver and does not bridge it."),
            "parent_key": pay, "driver_key": "cac_by_channel",
            "series": {"cac_by_channel": _history({**_spikes([-3, -1, 0], 0.30)}),
                       "utilized_vs_committed_action_volume": _history({-2: 0.70}, jitter=True)},
            "expected": {"status": "flagged", "streak_months": 2, "first_month_offset": -1,
                         "break_reason": BREAK_DRIVER_CHANGED,
                         "break_outlier_key": "utilized_vs_committed_action_volume"},
        },
        {
            "name": "missing_month_breaks_the_streak",
            "description": (
                "CAC by channel is adverse in the evaluation month, has no value the month "
                "before, and is adverse again two and three months back. With one sibling "
                "missing there is no sibling comparison that month, so the streak is 1."),
            "parent_key": pay, "driver_key": "cac_by_channel",
            "series": {"cac_by_channel": _history(_spikes([-3, -2, 0], 0.30), missing=(-1,)),
                       "utilized_vs_committed_action_volume": _history({}, jitter=True)},
            "expected": {"status": "not_flagged", "streak_months": 1, "first_month_offset": 0,
                         "break_reason": BREAK_NO_COMPARISON},
        },
        {
            "name": "favorable_outlier_is_not_an_adverse_streak",
            "description": (
                "CAC by channel is the top outlier in the evaluation month and the month "
                "before, but it fell 30% (favorable for payback). The same driver and the "
                "same size as the flagged case, opposite direction: streak 0."),
            "parent_key": pay, "driver_key": "cac_by_channel",
            "series": {"cac_by_channel": _history({-1: 0.70, 0: 0.70}),
                       "utilized_vs_committed_action_volume": _history({}, jitter=True)},
            "expected": {"status": "not_flagged", "streak_months": 0, "first_month_offset": None,
                         "break_reason": BREAK_NOT_ADVERSE, "driver_direction": "favorable"},
        },
        {
            "name": "direction_follows_the_parents_favorable_direction",
            "description": (
                "Onboarding/CS efficiency (lower is better; touches per automated Action). "
                "Automated Action volume is its denominator, so adverse = down: it falls 20% "
                "for two months while the numerator leg is quiet. Flagged. The same fall in "
                "AM touchpoint volume (adverse = up) would be favorable."),
            "parent_key": "onboarding_cs_efficiency", "driver_key": "automated_action_volume",
            "series": {"automated_action_volume": _history({-1: 0.80, 0: 0.80}),
                       "am_touchpoint_volume": _history({}, jitter=True)},
            "expected": {"status": "flagged", "streak_months": 2, "first_month_offset": -1,
                         "break_reason": BREAK_DRIVER_CHANGED, "adverse_direction": "down"},
        },
        {
            "name": "tie_at_top_ends_the_streak",
            "description": (
                "In the evaluation month CAC is +30% and the margin leg is flat. The month "
                "before, CAC is +20% and the margin leg is -20%: equal absolute deviation, so "
                "no single outlier. Streak 1; persistence is never claimed on a tie."),
            "parent_key": pay, "driver_key": "cac_by_channel",
            "series": {"cac_by_channel": _history({-1: 1.20, 0: 1.30}),
                       "utilized_vs_committed_action_volume": _history({-1: 0.80})},
            "expected": {"status": "not_flagged", "streak_months": 1, "first_month_offset": 0,
                         "break_reason": BREAK_TIE},
        },
        {
            "name": "additive_share_branch_ranks_by_absolute_deviation",
            "description": (
                "NRR's drivers are additive components of one identity, ranked by absolute "
                "deviation. Contraction rises +13% (0.006 of starting revenue) for two months; "
                "churn is -40% in relative terms but 0.0006 in absolute terms. Ranked by "
                "percentage deviation churn would win every month and contraction's streak "
                "would be 0; on the branch's own basis it is 2. Adverse for NRR = contraction "
                "up."),
            "parent_key": "nrr", "driver_key": "nrr_contraction_rate",
            "series": {
                "nrr_contraction_rate": _history({-1: 1.1327, 0: 1.1327}, base=0.0452),
                "nrr_churn_rate": _history({-1: 0.60, 0: 0.60}, base=0.0015),
                "nrr_expansion_rate": _history({}, base=0.1034, jitter=True)},
            "expected": {"status": "flagged", "streak_months": 2, "first_month_offset": -1,
                         "break_reason": BREAK_DRIVER_CHANGED, "adverse_direction": "up"},
        },
        {
            "name": "single_candidate_branch_is_not_applicable",
            "description": (
                "Expansion consumption revenue has one computable child (Overage realization), "
                "which rises for four consecutive months. A lone sibling would persist "
                "trivially, so the record is not_applicable with its reason and carries no "
                "streak."),
            "parent_key": "expansion_consumption_revenue", "driver_key": "overage_realization",
            "series": {"overage_realization": _history(_spikes([-3, -2, -1, 0], 0.30))},
            "expected": {"status": "not_applicable", "streak_months": None,
                         "first_month_offset": None, "reason": PERSISTENCE_NA_SINGLE_CANDIDATE},
        },
        {
            "name": "truncated_final_month_is_not_applicable",
            "description": (
                "A flagged-looking streak whose evaluation month is the truncated final month "
                "of the data window. Excluded: not_applicable, no streak."),
            "parent_key": pay, "driver_key": "cac_by_channel",
            "series": {"cac_by_channel": _history(_spikes([-1, 0], 0.30)),
                       "utilized_vs_committed_action_volume": _history({}, jitter=True)},
            "evaluation_is_truncated": True,
            "expected": {"status": "not_applicable", "streak_months": None,
                         "first_month_offset": None, "reason": PERSISTENCE_NA_TRUNCATED},
        },
        {
            "name": "no_outlier_is_not_applicable",
            "description": "A drill-down with no Layer-2 outlier has no driver to track.",
            "parent_key": pay, "driver_key": None,
            "series": {},
            "expected": {"status": "not_applicable", "streak_months": None,
                         "first_month_offset": None, "reason": PERSISTENCE_NA_NO_OUTLIER},
        },
        {
            "name": "undirected_driver_is_not_applicable",
            "description": (
                "Tenure-at-churn has no defined adverse direction for Logo retention, so no "
                "streak can be adverse; the record says so rather than guessing a sign."),
            "parent_key": "logo_retention", "driver_key": "tenure_at_churn",
            "series": {"tenure_at_churn": _history(_spikes([-1, 0], 0.30))},
            "expected": {"status": "not_applicable", "streak_months": None,
                         "first_month_offset": None, "reason": PERSISTENCE_NA_NO_DIRECTION},
        },
        {
            "name": "streak_stops_at_the_start_of_history",
            "description": (
                "CAC by channel compounds +30% a month from the first month of a 12-month "
                "history and stays the top adverse outlier in every month that has a "
                "full 8-month baseline. The first eight months have none, so the streak "
                "is 4 and ends at the start of the data, not at a change of driver."),
            "parent_key": pay, "driver_key": "cac_by_channel",
            "series": {
                "cac_by_channel": pd.Series(
                    [100.0 * 1.3 ** i for i in range(12)],
                    index=pd.date_range(end=_SYNTHETIC_MONTH, periods=12, freq="MS")),
                "utilized_vs_committed_action_volume": pd.Series(
                    [100.0 * (1 + _QUIET_JITTER[i % 2]) for i in range(12)],
                    index=pd.date_range(end=_SYNTHETIC_MONTH, periods=12, freq="MS"))},
            "expected": {"status": "flagged", "streak_months": 4, "first_month_offset": -3,
                         "break_reason": BREAK_START_OF_HISTORY},
        },
        {
            "name": "sibling_without_a_full_baseline_is_not_ranked",
            "description": (
                "CAC by channel has only 6 months of history and jumps +30% in the evaluation "
                "month. Eight observations are required to rank a sibling, so only the "
                "margin leg can be scored: a single-candidate read, not a streak driven by a "
                "deviation from a six-month mean."),
            "parent_key": pay, "driver_key": "utilized_vs_committed_action_volume",
            "series": {"cac_by_channel": _history(_spikes([0], 0.30), n_months=6),
                       "utilized_vs_committed_action_volume": _history({}, jitter=True)},
            "expected": {"status": "not_applicable", "streak_months": None,
                         "first_month_offset": None, "reason": PERSISTENCE_NA_SINGLE_CANDIDATE},
        },
        {
            "name": "future_months_are_never_read",
            "description": (
                "The streak-of-2 history with three later months appended after the evaluation "
                "month, each one a -90% crash that would change both the baseline and the "
                "ranking if it leaked. The record must be identical to the same history "
                "without them."),
            "parent_key": pay, "driver_key": "cac_by_channel",
            "series": {"cac_by_channel": _history(_spikes([-1, 0], 0.30),
                                                  future={1: 0.10, 2: 0.10, 3: 0.10}),
                       "utilized_vs_committed_action_volume": _history(
                           {}, jitter=True, future={1: 3.0, 2: 3.0, 3: 3.0})},
            "expected": {"status": "flagged", "streak_months": 2, "first_month_offset": -1,
                         "break_reason": BREAK_DRIVER_CHANGED},
            "same_as_without_future": True,
        },
    ]


def _cut_provider(series: Dict[str, pd.Series]) -> Callable[[pd.Timestamp], Dict[str, pd.Series]]:
    """Deliberately hands back the WHOLE history for any month -- the cut to
    the month is compute_persistence()'s job, so a provider that leaks the
    future is exactly what the 'future_months_are_never_read' case probes."""
    return lambda month: series


def run_persistence_scenario(scenario: dict, baseline_months: int = _TRAILING_BASELINE_MONTHS
                             ) -> dict:
    """Runs one persistence scenario and checks the record against its
    declared expectation, including the Drilldown round trip (the emitted
    record must be accepted by Drilldown and survive to_dict())."""
    failures: List[str] = []
    try:
        rec = compute_persistence(
            scenario["parent_key"], scenario["driver_key"], _SYNTHETIC_MONTH,
            _cut_provider(scenario["series"]), baseline_months,
            evaluation_is_truncated=scenario.get("evaluation_is_truncated", False))
    except Exception as e:  # a scenario must not raise; report it as a failure
        return {"name": scenario["name"], "description": scenario["description"],
                "passed": False, "failures": [f"raised {type(e).__name__}: {e}"], "record": None}
    exp = scenario["expected"]
    if rec["status"] != exp["status"]:
        failures.append(f"status: expected {exp['status']}, got {rec['status']}")
    if rec["streak_months"] != exp["streak_months"]:
        failures.append(f"streak: expected {exp['streak_months']}, got {rec['streak_months']}")
    want_first = (None if exp["first_month_offset"] is None else
                  (_SYNTHETIC_MONTH + pd.DateOffset(months=exp["first_month_offset"]))
                  .date().isoformat())
    if rec["first_month_of_streak"] != want_first:
        failures.append(f"first month: expected {want_first}, got {rec['first_month_of_streak']}")
    if "break_reason" in exp and (rec["streak_break"] or {}).get("reason") != exp["break_reason"]:
        failures.append(f"break: expected {exp['break_reason']}, got {rec['streak_break']}")
    if "break_outlier_key" in exp and (rec["streak_break"] or {}).get("outlier_key") != \
            exp["break_outlier_key"]:
        failures.append(f"break outlier: expected {exp['break_outlier_key']}, "
                        f"got {rec['streak_break']}")
    if "reason" in exp and rec["reason"] != exp["reason"]:
        failures.append(f"reason: expected {exp['reason']}, got {rec['reason']}")
    if "driver_direction" in exp and rec["driver_direction"] != exp["driver_direction"]:
        failures.append(f"direction: expected {exp['driver_direction']}, got {rec['driver_direction']}")
    if "adverse_direction" in exp and rec["adverse_direction"] != exp["adverse_direction"]:
        failures.append(f"adverse direction: expected {exp['adverse_direction']}, "
                        f"got {rec['adverse_direction']}")
    if rec["flagged"] != (rec["status"] == PERSISTENCE_FLAGGED):
        failures.append("flagged disagrees with status")
    if rec["status"] == PERSISTENCE_FLAGGED and (rec["streak_months"] or 0) < K_PERSISTENCE:
        failures.append("flagged below the threshold")
    if scenario.get("same_as_without_future"):
        trimmed = {k: v[v.index <= _SYNTHETIC_MONTH] for k, v in scenario["series"].items()}
        again = compute_persistence(scenario["parent_key"], scenario["driver_key"],
                                    _SYNTHETIC_MONTH, _cut_provider(trimmed), baseline_months)
        if again != rec:
            failures.append("a record computed with later months present differs from the same "
                            "history without them: the future leaked")
    try:
        l1 = scenario["parent_key"]
        emitted = Drilldown(
            layer1_key=l1, layer2_key=scenario["driver_key"], layer3_keys=[],
            layer1_variance_pct=0.0, layer1_mechanism="synthetic",
            sibling_ranking=pd.DataFrame(), sibling_coverage={},
            layer3_status=L3_NO_COMPUTABLE_DATA, layer3_evidence=pd.DataFrame(),
            branch_max_depth_in_tree=branch_max_depth(l1), persistence=rec).to_dict()
        if emitted["persistence"] != rec:
            failures.append("persistence record altered on its way through Drilldown.to_dict()")
    except Exception as e:
        failures.append(f"Drilldown rejected the record: {e}")
    return {"name": scenario["name"], "description": scenario["description"],
            "passed": not failures, "failures": failures, "record": rec}


def run_persistence_scenarios(baseline_months: int = _TRAILING_BASELINE_MONTHS) -> List[dict]:
    """Every persistence scenario -- the correctness check for the flag."""
    return [run_persistence_scenario(s, baseline_months) for s in _persistence_scenarios()]


# ---------------------------------------------------------------------
# Real-data profile of the flag: how often it fires, how stable it is
# ---------------------------------------------------------------------

def _truncating_provider(series: Dict[str, pd.Series]) -> Callable:
    return lambda month: {k: s[s.index <= month] for k, s in series.items()}


def _branch_months(first_month: pd.Timestamp, last_month: pd.Timestamp) -> List[pd.Timestamp]:
    return list(pd.date_range(first_month, last_month, freq="MS"))


def measure_persistence_selectivity(as_of_date: date,
                                    first_month: pd.Timestamp = pd.Timestamp("2023-01-01"),
                                    baseline_months: int = _TRAILING_BASELINE_MONTHS,
                                    k: int = K_PERSISTENCE, con=None,
                                    series_override: Optional[Dict[str, Dict[str, pd.Series]]] = None
                                    ) -> pd.DataFrame:
    """Evidence on how selective the persistence flag is, the counterpart of
    measure_threshold_selectivity(). Grain: one row per (Layer-1 branch,
    evaluation month) from `first_month` through the last representative
    evaluation month at or before as_of_date, for every Layer-1 node with at
    least one computable Layer-2 child. The month's top Layer-2 outlier is the
    driver the drill-down would name; its persistence is computed exactly as in
    a drill-down. `breached` records whether the Layer-1 node breached the
    variance threshold that month (only breaching nodes get a drill-down).
    Each branch's series are built once at `as_of_date` and cut per month: the
    marts' monthly values do not change with a later as-of date, which
    `verify_persistence_asof_equivalence()` checks against full engine runs.
    `series_override` lets the permutation null substitute shuffled series."""
    owns = con is None
    con = con or _connect()
    try:
        last_month = _evaluation_month(as_of_date)
        if last_month == _last_month_in_marts(con):
            last_month = last_month - pd.DateOffset(months=1)
        months = _branch_months(first_month, last_month)
        breach = {}
        if series_override is None:
            for m in months:
                sc = compute_layer1_scorecard((m + pd.offsets.MonthEnd(0)).date(), con=con)
                breach[m] = dict(zip(sc["metric_key"], sc["breaches_threshold"]))
        rows = []
        for node in layer1_nodes():
            series = (series_override or {}).get(node.key) if series_override is not None \
                else _build_child_series(node.key, as_of_date, con)
            if not series:
                continue
            provider = _truncating_provider(series)
            for m in months:
                scored = _scored_read(node.key, provider(m), m, baseline_months)
                if scored.empty:
                    continue
                driver = scored.iloc[0]["metric_key"]
                rec = compute_persistence(node.key, driver, m, provider, baseline_months, k)
                rows.append({
                    "layer1_key": node.key, "month": m, "driver_key": driver,
                    "status": rec["status"], "streak_months": rec["streak_months"],
                    "flagged": rec["flagged"], "reason": rec["reason"],
                    "driver_direction": rec["driver_direction"],
                    "eligible": rec["status"] != PERSISTENCE_NOT_APPLICABLE,
                    "breached": bool(breach.get(m, {}).get(node.key, False)),
                })
    finally:
        if owns:
            con.close()
    return pd.DataFrame(rows)


def summarize_persistence_selectivity(rows: pd.DataFrame) -> dict:
    """Flag rate and stability from measure_persistence_selectivity() rows.
    Rates are over ELIGIBLE branch-months (a genuine sibling comparison on a
    non-truncated month); the same rate over only the branch-months where the
    Layer-1 node breached (the ones a reader sees as drill-downs) is reported
    beside it. Stability: how often the flag flips between consecutive months
    of a branch, the chance a flagged month is followed by a flagged one, and
    the length of flagged runs."""
    elig = rows[rows["eligible"]]
    out = {"branch_months": int(len(rows)), "eligible_branch_months": int(len(elig)),
           "flagged_branch_months": int(elig["flagged"].sum()),
           "flag_rate": float(elig["flagged"].mean()) if len(elig) else float("nan"),
           "streak_distribution": {int(a): int(b) for a, b in
                                   elig["streak_months"].value_counts().sort_index().items()}}
    br = elig[elig["breached"]]
    out["breached_eligible_branch_months"] = int(len(br))
    out["flag_rate_breached"] = float(br["flagged"].mean()) if len(br) else float("nan")
    per_branch, flips, followed, flagged_total, runs = {}, 0, 0, 0, []
    transitions = 0
    for key, g in elig.sort_values("month").groupby("layer1_key"):
        f = g["flagged"].astype(bool).tolist()
        per_branch[key] = {"eligible": len(f), "flagged": int(sum(f)),
                           "flag_rate": sum(f) / len(f)}
        flips += sum(1 for a, b in zip(f, f[1:]) if a != b)
        transitions += max(len(f) - 1, 0)
        followed += sum(1 for a, b in zip(f, f[1:]) if a and b)
        flagged_total += sum(1 for a in f[:-1] if a)
        run = 0
        for a in f + [False]:
            if a:
                run += 1
            elif run:
                runs.append(run)
                run = 0
    out["per_branch"] = per_branch
    out["flag_flips_per_transition"] = flips / transitions if transitions else float("nan")
    out["p_flagged_given_flagged_previous_month"] = (followed / flagged_total
                                                     if flagged_total else float("nan"))
    out["mean_flagged_run_months"] = float(np.mean(runs)) if runs else float("nan")
    out["flagged_runs"] = len(runs)
    return out


def measure_persistence_sensitivity(as_of_date: date, con=None) -> dict:
    """How much the flag depends on its two free choices. Re-runs the profile
    with baseline windows of 6 and 12 months and with K = 3 and reports each
    variant's flag rate and its agreement with the proposed setting (8 months,
    K = 2) on the branch-months both call eligible: the share where both flag or
    both do not."""
    base = measure_persistence_selectivity(as_of_date, con=con)
    variants = {"baseline_6": dict(baseline_months=6), "baseline_12": dict(baseline_months=12),
                "k_3": dict(k=3)}
    out = {"proposed": {"flag_rate": float(base[base["eligible"]]["flagged"].mean()),
                        "eligible": int(base["eligible"].sum())}}
    key = ["layer1_key", "month"]
    for name, kw in variants.items():
        alt = measure_persistence_selectivity(as_of_date, con=con, **kw)
        both = base[base["eligible"]].merge(alt[alt["eligible"]], on=key, suffixes=("_a", "_b"))
        out[name] = {
            "flag_rate": float(alt[alt["eligible"]]["flagged"].mean()),
            "eligible": int(alt["eligible"].sum()),
            "agreement_with_proposed": float((both["flagged_a"] == both["flagged_b"]).mean()),
            "same_driver_share": float((both["driver_key_a"] == both["driver_key_b"]).mean()),
        }
    return out


def persistence_permutation_null(as_of_date: date, n_permutations: int = 50, seed: int = 42,
                                 k: int = K_PERSISTENCE, con=None) -> dict:
    """What flag rate the same machinery gives when the months of every
    sibling series are shuffled independently (seeded). A shuffled series has
    the same values and the same spread but no month-to-month order, so the
    rate it produces is the chance level for 'the same driver is the adverse
    outlier `k` months running' given each sibling's own volatility (a more
    volatile sibling is the top outlier more often, which already makes the
    same driver likely twice in a row). The observed rate is compared with it,
    overall and per Layer-1 branch."""
    rng = np.random.default_rng(seed)
    owns = con is None
    con = con or _connect()
    try:
        observed = measure_persistence_selectivity(as_of_date, k=k, con=con)
        built = {n.key: _build_child_series(n.key, as_of_date, con) for n in layer1_nodes()}
        rates, branch_rates = [], {}
        for _ in range(n_permutations):
            shuffled = {}
            for l1, series in built.items():
                shuffled[l1] = {key: pd.Series(rng.permutation(s.dropna().to_numpy()),
                                               index=s.dropna().index)
                                for key, s in series.items()} if series else {}
            rows = measure_persistence_selectivity(as_of_date, k=k, con=con,
                                                   series_override=shuffled)
            elig = rows[rows["eligible"]]
            rates.append(float(elig["flagged"].mean()) if len(elig) else float("nan"))
            for l1, g in elig.groupby("layer1_key"):
                branch_rates.setdefault(l1, []).append(float(g["flagged"].mean()))
    finally:
        if owns:
            con.close()
    obs = observed[observed["eligible"]]
    return {"k": k, "observed_flag_rate": float(obs["flagged"].mean()),
            "n_permutations": n_permutations, "seed": seed,
            "null_mean": float(np.nanmean(rates)), "null_min": float(np.nanmin(rates)),
            "null_max": float(np.nanmax(rates)), "null_p95": float(np.nanpercentile(rates, 95)),
            "share_of_permutations_at_or_above_observed":
                float(np.mean([r >= float(obs["flagged"].mean()) for r in rates])),
            "per_branch": {l1: {"observed": float(g["flagged"].mean()),
                                "null_mean": float(np.mean(branch_rates.get(l1, [np.nan])))}
                           for l1, g in obs.groupby("layer1_key")}}


def verify_persistence_asof_equivalence(as_of_dates: Sequence[date]) -> List[dict]:
    """Compares the persistence record a full engine run produces at each
    as-of date (prior months REBUILT from the marts as of their own month) with
    the profile's record for the same branch and month (series built once and
    cut). Equal records mean the cut is a faithful stand-in for rebuilding, so
    the profile is a profile of what the readout shows."""
    out = []
    for as_of in as_of_dates:
        run = run_diagnostic(as_of, include_watchlist=False)
        month = run["evaluation_month"]
        prof = measure_persistence_selectivity(as_of, first_month=month)
        prof = prof[prof["month"] == month].set_index("layer1_key")
        for dd in run["drilldowns"]:
            if dd.layer1_key not in prof.index:
                continue
            p = prof.loc[dd.layer1_key]
            same = (dd.persistence["driver_key"] == p["driver_key"]
                    and dd.persistence["status"] == p["status"]
                    and dd.persistence["streak_months"] == (None if pd.isna(p["streak_months"])
                                                            else int(p["streak_months"])))
            out.append({"as_of_date": as_of, "layer1_key": dd.layer1_key, "same": bool(same),
                        "engine": (dd.persistence["driver_key"], dd.persistence["status"],
                                   dd.persistence["streak_months"]),
                        "profile": (p["driver_key"], p["status"], p["streak_months"])})
    return out


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
    persistence_scenarios = run_persistence_scenarios()
    result = run_diagnostic(as_of_date, threshold=threshold)
    selectivity = measure_threshold_selectivity(as_of_date)
    persistence_profile = summarize_persistence_selectivity(
        measure_persistence_selectivity(as_of_date))
    coverage = result["coverage"]
    pipeline_recon = reconcile_pipeline_generated_branch(as_of_date)
    stale_markings = stale_markings_against_attribution()
    stale_wave10 = stale_markings_against_wave10_marts()

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
        log_performance(_MODEL_NAME, as_of_date, "pipeline_generated_children_max_abs_diff",
                        float(pipeline_recon["max_abs_diff_children_to_parent"]))
        log_performance(_MODEL_NAME, as_of_date, "nodes_marked_not_computable_but_covered_by_attribution",
                        float(len(stale_markings)))
        log_performance(_MODEL_NAME, as_of_date, "nodes_marked_not_computable_but_fed_by_wave10_marts",
                        float(len(stale_wave10)))
        log_performance(_MODEL_NAME, as_of_date, "persistence_scenarios_total",
                        float(len(persistence_scenarios)))
        log_performance(_MODEL_NAME, as_of_date, "persistence_scenarios_passed",
                        float(sum(s["passed"] for s in persistence_scenarios)))
        log_performance(_MODEL_NAME, as_of_date, "persistence_eligible_branch_months",
                        float(persistence_profile["eligible_branch_months"]))
        log_performance(_MODEL_NAME, as_of_date, "persistence_flag_rate",
                        float(persistence_profile["flag_rate"]))

    return {"synthetic_scenarios": scenarios, "diagnostic": result,
            "persistence_scenarios": persistence_scenarios,
            "persistence_profile": persistence_profile,
            "threshold_selectivity": selectivity, "coverage": coverage,
            "pipeline_generated_reconciliation": pipeline_recon,
            "stale_markings": stale_markings,
            "stale_markings_wave10_marts": stale_wave10}


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

    print("\n=== Persistence scenarios (known-streak histories) ===")
    for s in out["persistence_scenarios"]:
        print(f"[{'PASS' if s['passed'] else 'FAIL'}] {s['name']}: "
              f"status={s['record']['status'] if s['record'] else 'raised'} "
              f"streak={s['record']['streak_months'] if s['record'] else None}")
        for f in s["failures"]:
            print(f"        {f}")
    pp = out["persistence_profile"]
    print(f"Persistence flag, 2023-01 to last representative month: {pp['flagged_branch_months']} "
          f"of {pp['eligible_branch_months']} eligible branch-months flagged "
          f"({pp['flag_rate']:.1%}); among branch-months that breached the threshold "
          f"{pp['flag_rate_breached']:.1%}")

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
        print(f"     persistence: {dd.persistence['status']} "
              f"(streak {dd.persistence['streak_months']}) -- {dd.persistence['note']}")
        for n in dd.notes:
            print(f"     note: {n[:160]}")

    print("\n=== Pipeline-generated branch reconciliation ===")
    pr = out["pipeline_generated_reconciliation"]
    print(f"children sum to parent: max abs diff {pr['max_abs_diff_children_to_parent']:.1e} over "
          f"{pr['months_checked']} months; attribution tie-out reconciles: "
          f"{pr['attribution_tie_out']['reconciles']}; overall: {pr['reconciles']}")
    print(f"tree nodes marked NOT_COMPUTABLE while marketing_attribution covers them: "
          f"{out['stale_markings'] or 'none'}")
    print(f"tree nodes marked NOT_COMPUTABLE while a deal-funnel / workflow-chain / "
          f"consumption-utilization mart column feeds them: "
          f"{out['stale_markings_wave10_marts'] or 'none'}")

    print("\n=== Branch coverage ===")
    print(out["coverage"].to_string(index=False))

    print("\n=== Threshold selectivity (evidence for build spec Section 7) ===")
    print(out["threshold_selectivity"].to_string(index=False))

    print("\n=== Watchlist (top 10) ===")
    print(d["watchlist"].head(10).to_string(index=False))
