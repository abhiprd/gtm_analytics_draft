"""Deterministic parser: docs/acme-corp-gtm-metric-tree.md -> semantic/metric_registry.json.

WHAT THIS IS
------------
The metric registry is a structured parse of the tree file's own markdown
structure (3 pillars -> Layer 1 -> Layer 2 -> Layer 3), never a hand-typed
second copy of a metric's formula. Run this script whenever the tree file
changes; it re-parses the markdown from scratch, diffs the result against
the previously-generated registry, bumps `registry_version` if the
structure changed, and appends one line to semantic/CHANGELOG.md stating
what changed. If nothing changed, no version bump and no changelog line.

WHAT IS -- AND ISN'T -- "PARSED"
---------------------------------
Two things come straight out of the tree file's text, mechanically, via
the line-by-line state machine below: node identity (pillar/layer/parent/
children), `name`, `formula`, `owner`, and the scope annotations the tree
itself writes inline ("by segment", "new-business only", the literal
`opportunity_type = renewal` token, the "not summed into"/"not a fourth
multiplicative factor" non-additive markers). Nothing in that path is
typed from memory -- it is read off the markdown at parse time.

One thing is NOT parseable from the tree file because the tree file never
names it: `source_mart` (which mart_* table under dbt/models/marts/
computes this node) and the SQL aggregation needed to query it. That
mapping is a separate, explicitly-labelled annotation layer
(_SOURCE_MART_MAP below), built by reading the actual dbt mart SQL and
schema.yml files this registry's author verified against (see the
comments on each entry), not invented. Every node not in that map is
NOT_COMPUTABLE and carries a gap_note saying why, grounded in the same
mart-schema reading -- never a fabricated placeholder value.

REGENERATION
------------
    semantic/.venv/bin/python semantic/build_registry.py

MCP GUIDANCE ON RUNTIME
------------------------
The MCP server (semantic/server.py) reads the generated
semantic/metric_registry.json at startup -- it does NOT re-parse the
markdown live on every request. This is deliberate: the registry is a
versioned artifact (`registry_version` + `source_tree_sha256`) so a
consumer of query_metric() results can know which tree shape they queried
against, per this project's versioning requirement. A tree-file edit only
takes effect after this script is re-run.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
_TREE_PATH = os.path.join(_REPO_ROOT, "docs", "acme-corp-gtm-metric-tree.md")
_REGISTRY_PATH = os.path.join(_HERE, "metric_registry.json")
_CHANGELOG_PATH = os.path.join(_HERE, "CHANGELOG.md")

PILLARS_EXPECTED = ("Growth", "Efficiency", "Durability")


# =====================================================================
# Small text helpers
# =====================================================================

def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _split_top_level_commas(text: str):
    """Comma split that doesn't break inside parentheses -- needed because
    some tree clauses carry a comma inside a parenthetical aside (e.g.
    marketing-sales handoff quality's "...above three, not a fourth
    multiplicative factor)")."""
    parts, depth, current = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


_SCOPE_CLAUSE_RE = re.compile(r"^(by\b|new-business only\b)", re.I)
_CROSS_REF_RE = re.compile(r"\bSee Growth\b|\btracked under\b", re.I)
_NON_ADDITIVE_RE = re.compile(
    r"not summed into|not a fourth multiplicative factor|non-additive", re.I
)
_OPP_TYPE_RE = re.compile(r"opportunity_type\s*=\s*`?([a-zA-Z_]+)`?")
_PAREN_WHOLE_RE = re.compile(r"^\((.*)\)$")
_PAREN_SUFFIX_RE = re.compile(r"^(.*?)\s*\((.*)\)$")


def _extract_scope_signals(text: str) -> dict:
    """Signals extractable from ANY tree text regardless of where it
    appears (heading suffix, formula trailing text, bullet suffix, plain
    description line): scope annotations, the opportunity_type filter
    token, the cross-reference marker, and the non-additive marker.
    Never classifies owner -- see _parse_owner_suffix for that, which is
    only meaningful on heading/bold/bullet "Name -- clause" text."""
    out = {
        "scope_note": None,
        "opportunity_type_filter": None,
        "cross_reference": bool(_CROSS_REF_RE.search(text)),
        "non_additive": bool(_NON_ADDITIVE_RE.search(text)),
    }
    m = _OPP_TYPE_RE.search(text)
    if m:
        out["opportunity_type_filter"] = m.group(1)
    elif re.search(r"new-business only", text, re.I):
        out["opportunity_type_filter"] = "new_business"
    scopes = [c for c in _split_top_level_commas(text) if _SCOPE_CLAUSE_RE.match(c)]
    if scopes:
        out["scope_note"] = "; ".join(scopes)
    return out


def _parse_owner_suffix(text: str) -> dict:
    """Parses the "-- clause1, clause2" grammar used after an em-dash on
    H3 headings, bold Layer-2 lines, and bullet lines: the first non-scope,
    non-cross-reference clause is the owner; any parenthetical on that
    clause is a note; remaining clauses become additional notes."""
    result = {"owner": None, "note": None}
    signals = _extract_scope_signals(text)
    if signals["cross_reference"]:
        result["note"] = text.strip()
        return {**result, **signals}

    clauses = _split_top_level_commas(text)
    owners, notes = [], []
    for c in clauses:
        whole_paren = _PAREN_WHOLE_RE.match(c)
        if whole_paren:
            notes.append(whole_paren.group(1))
            continue
        base, paren_note = c, None
        suffix_paren = _PAREN_SUFFIX_RE.match(c)
        if suffix_paren:
            base, paren_note = suffix_paren.group(1).strip(), suffix_paren.group(2)
        if _SCOPE_CLAUSE_RE.match(base):
            continue  # already captured by _extract_scope_signals
        owners.append(base)
        if paren_note:
            notes.append(paren_note)
    if owners:
        result["owner"] = owners[0]
        notes = owners[1:] + notes
    if notes:
        result["note"] = "; ".join(notes)
    return {**result, **signals}


# =====================================================================
# The parser -- a line-by-line state machine over the tree markdown
# =====================================================================

_H2_RE = re.compile(r"^## (?!#)(.+)$")
_H3_RE = re.compile(r"^### (.+)$")
_BOLD_RE = re.compile(r"^\*\*(.+?)\*\*(.*)$")
_FORMULA_RE = re.compile(r"^`([^`]+)`(.*)$")
_BULLET_RE = re.compile(r"^(\s*)-\s+(.+)$")
_TRAILING_PAREN_RE = re.compile(r"^(.*?)\s*\(([^()]+)\)\s*$")


def _strip_name_parenthetical(name: str):
    """A node's own display name sometimes carries a trailing parenthetical
    with no preceding em-dash ("AM touchpoint volume (book size, ramp
    status, check-in cadence)", "POC pass rate (Enterprise)"). Slugging the
    parenthetical into the node's key would produce an unreadable, overlong
    slug for a detail that belongs in `note`, not the identity -- split it
    off. A short parenthetical that IS the node's identity marker (e.g.
    'CAC by channel (unblended)') is kept in the display name regardless;
    only the SLUG is derived from the base."""
    m = _TRAILING_PAREN_RE.match(name)
    if not m:
        return name, None
    base, note = m.group(1).strip(), m.group(2).strip()
    return base, note


def _new_node(key, name, layer, pillar, parent):
    return {
        "key": key,
        "name": name,
        "layer": layer,
        "pillar": pillar,
        "parent": parent,
        "children": [],
        "owner": None,
        "formula": None,
        "formula_note": None,
        "scope_note": None,
        "note": None,
        "opportunity_type_filter": None,
        "cross_reference": False,
        "non_additive": False,
        "detail": [],
    }


def parse_tree(tree_text: str) -> dict:
    nodes: dict = {}
    order: list = []
    pillars: dict = {}

    current_pillar = None
    current_l1 = None
    current_l2 = None
    last_bullet_node = None

    def register(node):
        if node["key"] in nodes:
            raise ValueError(f"duplicate slug '{node['key']}' -- tree has two nodes with the same name")
        nodes[node["key"]] = node
        order.append(node["key"])
        if node["parent"]:
            nodes[node["parent"]]["children"].append(node["key"])

    def merge_note(existing, extra):
        if not extra:
            return existing
        return extra if not existing else existing + "; " + extra

    def apply_scope(node, text):
        sig = _extract_scope_signals(text)
        if sig["scope_note"]:
            node["scope_note"] = (
                sig["scope_note"] if not node["scope_note"]
                else node["scope_note"] + "; " + sig["scope_note"]
            )
        if sig["opportunity_type_filter"] and not node["opportunity_type_filter"]:
            node["opportunity_type_filter"] = sig["opportunity_type_filter"]
        node["cross_reference"] = node["cross_reference"] or sig["cross_reference"]
        node["non_additive"] = node["non_additive"] or sig["non_additive"]

    for raw_line in tree_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        m = _H2_RE.match(line)
        if m and not line.startswith("### "):
            text = m.group(1).strip()
            if " — " in text:
                name, tagline = text.split(" — ", 1)
            else:
                name, tagline = text, None
            current_pillar = name.strip()
            pillars[current_pillar] = {"tagline": tagline.strip() if tagline else None, "bridge_formula": None}
            current_l1 = None
            current_l2 = None
            last_bullet_node = None
            continue

        m = _H3_RE.match(line)
        if m:
            text = m.group(1).strip()
            if " — " in text:
                name, suffix = text.split(" — ", 1)
            else:
                name, suffix = text, ""
            parsed = _parse_owner_suffix(suffix) if suffix else {
                "owner": None, "note": None, "scope_note": None,
                "opportunity_type_filter": None, "cross_reference": False, "non_additive": False,
            }
            slug_base, paren_note = _strip_name_parenthetical(name.strip())
            key = _slugify(slug_base)
            node = _new_node(key, name.strip(), 1, current_pillar, None)
            node["owner"] = parsed["owner"]
            node["note"] = merge_note(parsed["note"], paren_note)
            apply_scope(node, suffix)
            register(node)
            current_l1 = node
            current_l2 = None
            last_bullet_node = None
            continue

        m = _BOLD_RE.match(line)
        if m:
            title = m.group(1).strip()
            suffix = m.group(2).strip()
            if suffix.startswith("—"):
                suffix = suffix.lstrip("—").strip()
            parsed = _parse_owner_suffix(suffix) if suffix else {
                "owner": None, "note": None, "scope_note": None,
                "opportunity_type_filter": None, "cross_reference": False, "non_additive": False,
            }
            slug_base, paren_note = _strip_name_parenthetical(title)
            key = _slugify(slug_base)
            node = _new_node(key, title, current_l1["layer"] + 1, current_l1["pillar"], current_l1["key"])
            node["owner"] = parsed["owner"]
            node["note"] = merge_note(parsed["note"], paren_note)
            apply_scope(node, suffix)
            register(node)
            current_l2 = node
            last_bullet_node = None
            continue

        m = _FORMULA_RE.match(line)
        if m:
            formula_text, trailing = m.group(1).strip(), m.group(2).strip()
            if current_l2 is None and current_l1 is None:
                # Pillar-level bridge formula (Growth's header formula line).
                if current_pillar:
                    pillars[current_pillar]["bridge_formula"] = formula_text
                continue
            target = current_l2 if current_l2 is not None else current_l1
            if target["formula"] is None:
                target["formula"] = formula_text
                target["formula_note"] = trailing or None
            apply_scope(target, trailing)
            continue

        m = _BULLET_RE.match(line)
        if m:
            indent, text = m.group(1), m.group(2).strip()
            if len(indent) == 0:
                parent_node = current_l2 if current_l2 is not None else current_l1
                if _CROSS_REF_RE.search(text):
                    # A bullet that explicitly points elsewhere in the tree
                    # rather than naming its own leaf ("See Growth --
                    # expansion, contraction, churn drivers"; "tracked
                    # under win rate..."). Keep the full sentence as the
                    # node's identity so two such bullets in different
                    # sections don't collide on the same slug, and skip
                    # owner parsing entirely -- there is no owner here.
                    name, suffix = text, ""
                else:
                    name, suffix = (text.split(" — ", 1) if " — " in text else (text, ""))
                parsed = _parse_owner_suffix(suffix) if suffix else {
                    "owner": None, "note": None, "scope_note": None,
                    "opportunity_type_filter": None, "cross_reference": False, "non_additive": False,
                }
                slug_base, paren_note = _strip_name_parenthetical(name.strip())
                key = _slugify(slug_base)
                node = _new_node(key, name.strip(), parent_node["layer"] + 1, parent_node["pillar"], parent_node["key"])
                node["owner"] = parsed["owner"]
                node["note"] = merge_note(
                    parsed["note"] or (text.strip() if _CROSS_REF_RE.search(text) else None),
                    paren_note,
                )
                apply_scope(node, text)
                register(node)
                last_bullet_node = node
            else:
                if last_bullet_node is not None:
                    last_bullet_node["detail"].append(text)
            continue

        # Plain description line (no backticks, no bullet, no heading) --
        # e.g. "Realized deal size at close, by segment" for Avg initial
        # commitment, which the tree gives no code-formula for at all.
        target = current_l2 if current_l2 is not None else current_l1
        if target is not None:
            if target["formula"] is None:
                target["formula"] = line.strip()
            apply_scope(target, line)

    return {"nodes": nodes, "order": order, "pillars": pillars}


# =====================================================================
# source_mart annotation layer -- NOT parsed from the tree (the tree
# never names a mart table). Built by reading the actual dbt mart SQL and
# _mart_schema.yml under dbt/models/marts/marts/, cited per entry.
# =====================================================================
# aggregation: how query_metric() rolls the mart column up across months
# within a requested grain -- 'sum' for dollar/count flow quantities,
# 'avg' for ratios/rates, 'avg_special' for the one leaf (tenure_at_churn)
# that needs its own WHERE clause rather than a plain column read.

_SOURCE_MART_MAP = {
    # ---------------------------------------------------------------- L1
    "new_logo_consumption_revenue": {
        "source_mart": "mart_growth_bridge", "column": "new_logo_mrr", "aggregation": "sum",
    },
    "activation": {
        "source_mart": "mart_growth_bridge", "column": "activation_ttfa_months_avg", "aggregation": "avg",
        "note": "Blended TTFA is identically 0 in the current generated data (fact_usage_monthly is "
                "monthly grain -- every account's first Action lands in its own signup month). Real, "
                "not fabricated, just degenerate on this data.",
    },
    "expansion_consumption_revenue": {
        "source_mart": "mart_growth_bridge", "column": "expansion_mrr", "aggregation": "sum",
    },
    "contraction_churned_consumption_revenue": {
        "source_mart": "mart_growth_bridge", "column": "contraction_mrr + churn_mrr", "aggregation": "sum",
    },
    "magic_number": {
        "source_mart": "mart_efficiency", "column": "magic_number", "aggregation": "avg",
        "note": "NULL for every row -- no rep-cost/comp data exists anywhere in the raw sources, so "
                "mart_efficiency leaves the S&M-cost denominator (and this ratio) NULL by design, not "
                "an execution bug.",
    },
    "consumption_payback": {
        "source_mart": "mart_efficiency", "column": "consumption_payback_months", "aggregation": "avg",
    },
    "onboarding_cs_efficiency": {
        "source_mart": "mart_efficiency", "aggregation": "ratio",
        "numerator": "am_touchpoint_count", "denominator": "automated_actions_delivered",
    },
    "am_efficiency": {
        "source_mart": "mart_efficiency", "column": "am_efficiency", "aggregation": "avg",
        "note": "NULL for every row -- same raw-data gap as magic_number (no AM comp data).",
    },
    "nrr": {
        "source_mart": "mart_durability", "aggregation": "ratio",
        "numerator": "starting_mrr - contraction_mrr - churn_mrr + expansion_mrr", "denominator": "starting_mrr",
    },
    "grr": {
        "source_mart": "mart_durability", "aggregation": "ratio",
        "numerator": "starting_mrr - contraction_mrr - churn_mrr", "denominator": "starting_mrr",
    },
    "logo_retention": {
        "source_mart": "mart_durability", "aggregation": "ratio",
        "numerator": "starting_accounts - churned_accounts", "denominator": "starting_accounts",
    },
    # ---------------------------------------------------------------- L2
    "win_rate": {
        "source_mart": "mart_growth_bridge", "aggregation": "ratio",
        "numerator": "new_business_won_count", "denominator": "new_business_won_count + new_business_lost_count",
        "note": "SMB always shows win_rate = 1.0 (every SMB opportunity is created already Closed Won "
                "-- build spec Section 2); the tree itself notes SMB 'has no win-rate concept to true "
                "up', so a Commercial/Enterprise segment filter is the meaningful read.",
    },
    "avg_initial_commitment": {
        "source_mart": "mart_growth_bridge", "aggregation": "ratio",
        "numerator": "new_logo_bookings_amount", "denominator": "new_business_won_count",
    },
    "onboarding_completion_rate": {
        "source_mart": "mart_growth_bridge", "aggregation": "ratio",
        "numerator": "activated_count", "denominator": "signup_cohort_size",
        "note": "Identically 1.0 in every month of the current generated data -- every account "
                "produces a first Action in its signup month. A real data property, not a query bug.",
    },
    "am_touchpoint_volume": {
        "source_mart": "mart_efficiency", "column": "am_touchpoint_count", "aggregation": "sum",
    },
    "automated_action_volume_delivered": {
        "source_mart": "mart_efficiency", "column": "automated_actions_delivered", "aggregation": "sum",
    },
    "cac_by_channel": {
        "source_mart": "mart_efficiency", "column": "blended_cac", "aggregation": "avg",
        "computability": "partial",
        "note": "mart_efficiency exposes blended_cac (already blended across channels by each "
                "channel's share of the segment's new accounts) -- the tree's own per-channel "
                "'unblended' cut is not exposed by any mart_* table, so `channel` is listed in "
                "allowed_dimensions per the tree but is NOT in queryable_dimensions until a Phase 2 "
                "mart change exposes it.",
    },
    "utilized_vs_committed_action_volume": {
        "source_mart": "mart_efficiency", "column": "avg_utilized_action_margin_per_account", "aggregation": "avg",
        "computability": "partial",
        "note": "mart_efficiency exposes the resulting utilization-haircut margin, not the raw "
                "utilized/committed ratio the tree names -- movement here can come from either "
                "utilization or the underlying MRR base.",
    },
    "am_cost_by_segment": {
        "source_mart": "mart_efficiency", "column": "am_cost", "aggregation": "avg",
        "note": "NULL for every row -- no AM comp data in the raw sources.",
    },
    # ---------------------------------------------------------------- L3
    "tenure_at_churn": {
        "source_mart": "mart_account_health", "column": "account_tenure_days", "aggregation": "avg_special",
        "note": "Computed as avg(account_tenure_days) filtered to rows where month = churn_month -- "
                "the mean tenure, in days, of accounts that churned within the requested window.",
    },
}

# Gap notes for tree nodes with no mart_* table exposing the data they
# need -- grounded in dbt/models/marts' actual contents (only dim_*/
# fact_*/mart_* models under dbt/models/marts exist as queryable tables;
# leads/campaigns/opportunity-stage-detail/workflow-chain-detail/AM-comp
# data are either absent from the raw sources entirely or sit in a
# fact_* table that no mart_* rollup currently exposes for this purpose).
_NO_LEADS_MARKETING_DATA = (
    "No mart_* table exposes leads, campaign touches, or PQL signals -- fact_leads and "
    "fact_campaign_engagement_events exist but no mart_* rollup surfaces the organic/paid/community "
    "pipeline breakdown this leaf needs."
)
_NO_OPPORTUNITY_DETAIL_MART = (
    "Needs opportunity-level detail (stage history, loss_reason, list_price, or "
    "opportunity_type='renewal' scoping) that lives in fact_opportunities / "
    "fact_opportunity_stage_history -- fact_* tables outside a mart_* rollup for this cut."
)
_NO_COST_DATA = (
    "No rep-cost/comp data exists anywhere in the raw sources, so the cost denominator this leaf "
    "needs is undefined."
)
_NO_WORKFLOW_CHAIN_MART = (
    "fact_workflow_chain_events exists but no mart_* table exposes upstream-vs-downstream Action "
    "completion at this grain."
)
_NO_HEALTH_SCORE_SERIES = (
    "The account health score is a fitted model output (analytics/health_score.py), not a plain "
    "mart_* column -- querying it needs the scoring model, not a SQL aggregation."
)

_GAP_NOTE_OVERRIDES = {
    "pipeline_generated": _NO_LEADS_MARKETING_DATA,
    "organic_content": _NO_LEADS_MARKETING_DATA,
    "paid": _NO_LEADS_MARKETING_DATA,
    "community_events": _NO_LEADS_MARKETING_DATA,
    "outbound_sdr_and_segment_graduation_volume": (
        "Not a separately computed leaf by the tree's own instruction -- 'tracked under win rate and "
        "the company model's migration branch, not duplicated here'. Query win_rate or "
        "mart_segment_migration instead."
    ),
    "stage_to_stage_conversion": _NO_OPPORTUNITY_DETAIL_MART,
    "poc_pass_rate": _NO_OPPORTUNITY_DETAIL_MART,
    "rep_capacity_ramp_mix": (
        "Needs rep-level quota/ramp joined to deal ownership. dim_reps carries quota/ramp but no "
        "mart_* table exposes win rate cut by rep ramp status."
    ),
    "loss_reason_mix": _NO_OPPORTUNITY_DETAIL_MART,
    "discount_rate_vs_list": _NO_OPPORTUNITY_DETAIL_MART,
    "deal_size_trend_within_segment_band": _NO_OPPORTUNITY_DETAIL_MART,
    "marketing_sales_handoff_quality": _NO_LEADS_MARKETING_DATA,
    "mql_response_sla": _NO_LEADS_MARKETING_DATA,
    "mql_sal_acceptance_rate": _NO_LEADS_MARKETING_DATA,
    "lead_recycling_nurture_re_qualification_rate": _NO_LEADS_MARKETING_DATA,
    "brand_awareness": (
        "No web-traffic, branded-search, or share-of-voice source exists anywhere in this project's "
        "raw data."
    ),
    "branded_search_volume_trend": "No web-traffic/search source exists in any layer of this project.",
    "direct_traffic_share": "No web-traffic source exists in any layer of this project.",
    "share_of_voice_vs_named_competitors": "No competitive-intelligence source exists in any layer of this project.",
    "time_to_first_integration_first_successful_run": (
        "No integration or first-successful-run event exists in the raw data; fact_usage_monthly is "
        "monthly grain with no first-Action timestamp."
    ),
    "quickstart_docs_content_engagement_rate": (
        "The build spec's content_engagement source was never generated -- no mart or fact table "
        "carries docs/quickstart interaction at all."
    ),
    "wallet_share_progression": (
        "Requires an account's total addressable workflow footprint (the ratio's denominator) -- no "
        "source in this project estimates an account's non-Acme workflow volume."
    ),
    "workflow_migration_rate": "Needs business-process-level onboarding events; not generated.",
    "am_touch_effectiveness": (
        "fact_am_activity exists but no mart exposes AM touches joined to a recommitment outcome; "
        "mart_efficiency exposes only the touch count."
    ),
    "existing_account_community_engagement_depth": (
        "The build spec's community_membership source was never generated."
    ),
    "overage_realization": (
        "Committed-vs-utilized Action volume exists only in fact_committed_vs_utilized_monthly, a "
        "fact_* table not exposed as realised overage billing by any mart_* rollup."
    ),
    "workflow_chain_under_utilization": _NO_WORKFLOW_CHAIN_MART,
    "ingestion_without_completion_rate": _NO_WORKFLOW_CHAIN_MART,
    "mid_chain_workflow_abandonment": _NO_WORKFLOW_CHAIN_MART,
    "declining_share_of_full_chain_vs_partial_chain_runs": _NO_WORKFLOW_CHAIN_MART,
    "account_health_score": _NO_HEALTH_SCORE_SERIES,
    "usage_trend": _NO_HEALTH_SCORE_SERIES,
    "support_ticket_volume_severity": _NO_HEALTH_SCORE_SERIES,
    "engagement_login_frequency": _NO_HEALTH_SCORE_SERIES,
    "am_sentiment_notes": _NO_HEALTH_SCORE_SERIES,
    "account_specific_baseline_deviation": (
        "No mart_* table exposes an account-relative usage baseline series at this grain."
    ),
    "cohort_comparison": (
        "No mart_* table exposes an account-type x usage-cycle cohort baseline."
    ),
    "renewal_win_rate": _NO_OPPORTUNITY_DETAIL_MART,
    "time_to_respond_on_churn_risk_flag": (
        "Needs a churn-risk flag event joined to AM response; no mart_* table exposes it."
    ),
    "loud_explicit_cancellation_vs_silent_non_renewal_mix": _NO_OPPORTUNITY_DETAIL_MART,
    "s_m_cost": _NO_COST_DATA,
    "cost_per_channel_activity": _NO_COST_DATA,
    "rep_fully_loaded_cost_incl_ramp": _NO_COST_DATA,
    "marketing_spend_allocation_by_channel": (
        "fact_marketing_spend exists but no mart_* table exposes spend by channel."
    ),
    "see_growth_expansion_revenue_drivers": (
        "Defined by reference in the tree ('See Growth -- expansion revenue drivers'), not a leaf "
        "with its own actual -- query expansion_consumption_revenue and its children instead."
    ),
    "see_growth_expansion_contraction_churn_drivers": (
        "Defined by reference in the tree ('See Growth -- expansion, contraction, churn drivers') -- "
        "query nrr_expansion/contraction/churn via expansion_consumption_revenue and "
        "contraction_churned_consumption_revenue instead."
    ),
    "see_growth_contraction_churn_drivers": (
        "Defined by reference in the tree ('See Growth -- contraction, churn drivers') -- query "
        "contraction_churned_consumption_revenue and its children instead."
    ),
    "cyclical_planned_usage_dip_vs_structural_churn": (
        "The tree's full cyclical-vs-structural classification needs a same-account-type/same-period "
        "cohort baseline that no mart_* table exposes; only the underlying account-relative usage "
        "signal exists (mart_account_health), and it is not pre-aggregated into a queryable ratio."
    ),
    "churn_reason_category": _NO_OPPORTUNITY_DETAIL_MART,
}


def _apply_source_mart(node: dict) -> dict:
    key = node["key"]
    override = _SOURCE_MART_MAP.get(key)
    if override:
        node["source_mart"] = override["source_mart"]
        node["computable"] = True
        node["computability"] = override.get("computability", "full")
        if override["aggregation"] == "ratio":
            query = {
                "aggregation": "ratio",
                "numerator": override["numerator"],
                "denominator": override["denominator"],
            }
        else:
            query = {"aggregation": override["aggregation"], "column": override["column"]}
        node["query"] = query
        node["gap_note"] = override.get("note")
    else:
        node["source_mart"] = None
        node["computable"] = False
        node["computability"] = "not_computable"
        node["query"] = None
        if key in _GAP_NOTE_OVERRIDES:
            node["gap_note"] = _GAP_NOTE_OVERRIDES[key]
        elif node["cross_reference"]:
            node["gap_note"] = (
                "Cross-reference within the tree, not a separately computed leaf: " + (node["note"] or node["name"])
            )
        else:
            node["gap_note"] = (
                "Not registered as computable in semantic/build_registry.py's _SOURCE_MART_MAP -- no "
                "mart_* table has been identified for this leaf yet."
            )
    return node


# =====================================================================
# allowed_dimensions -- segment is the default on every node (this
# company's entire GTM model is segment-scoped per the build spec and
# CLAUDE.md's non-negotiable invariant); channel / opportunity_type are
# added only where the tree's own text for THIS node mentions them.
# =====================================================================

def _allowed_dimensions(node: dict) -> list:
    dims = ["segment"]
    haystack = " ".join(filter(None, [
        node["name"], node["formula"], node["formula_note"],
        node["scope_note"], node["note"],
    ])).lower()
    if "channel" in haystack:
        dims.append("channel")
    if node["opportunity_type_filter"] or "opportunity_type" in haystack:
        dims.append("opportunity_type")
    return dims


def _queryable_dimensions(node: dict) -> list:
    """Dimensions actually backed by a column in the node's source_mart --
    the intersection guardrail: a dimension can be in allowed_dimensions
    per the tree yet NOT be queryable today because the mart doesn't carry
    it (e.g. cac_by_channel's channel cut)."""
    if not node["computable"]:
        return []
    dims = ["segment"]  # every computable mart in _SOURCE_MART_MAP carries `segment`.
    if node["computability"] == "partial" and "channel" in node["allowed_dimensions"]:
        return dims  # channel explicitly NOT queryable yet -- see gap_note.
    return dims


# =====================================================================
# Build + write
# =====================================================================

def build_registry() -> dict:
    with open(_TREE_PATH, "r", encoding="utf-8") as f:
        tree_text = f.read()
    parsed = parse_tree(tree_text)
    nodes = parsed["nodes"]

    l1 = [n for n in nodes.values() if n["layer"] == 1]
    if len(l1) != 11:
        raise ValueError(f"expected 11 Layer-1 nodes, parsed {len(l1)}: {[n['key'] for n in l1]}")
    for pillar in PILLARS_EXPECTED:
        if pillar not in parsed["pillars"]:
            raise ValueError(f"pillar '{pillar}' not found while parsing the tree file")

    metrics = {}
    for key in parsed["order"]:
        node = nodes[key]
        node = _apply_source_mart(node)
        node["additive"] = not node["non_additive"]
        node["allowed_dimensions"] = _allowed_dimensions(node)
        node["queryable_dimensions"] = _queryable_dimensions(node)
        metrics[key] = node

    # Explicit CLAUDE.md invariant check: Brand & Awareness must be the
    # non-additive node the project's own docs name.
    if metrics.get("brand_awareness", {}).get("additive") is not False:
        raise ValueError("brand_awareness must parse as additive: false (CLAUDE.md invariant)")

    tree_hash = hashlib.sha256(tree_text.encode("utf-8")).hexdigest()
    content_hash = hashlib.sha256(
        json.dumps(metrics, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    return {
        "pillars": parsed["pillars"],
        "metrics": metrics,
        "metric_order": parsed["order"],
        "source_tree_file": "docs/acme-corp-gtm-metric-tree.md",
        "source_tree_sha256": tree_hash,
        "content_sha256": content_hash,
    }


def _load_existing_registry():
    if not os.path.exists(_REGISTRY_PATH):
        return None
    with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _append_changelog(version: int, summary: str) -> None:
    line = f"- v{version} ({datetime.now(timezone.utc).strftime('%Y-%m-%d')}): {summary}\n"
    header = "# Semantic layer registry changelog\n\n"
    if not os.path.exists(_CHANGELOG_PATH):
        with open(_CHANGELOG_PATH, "w", encoding="utf-8") as f:
            f.write(header)
            f.write(line)
        return
    with open(_CHANGELOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


def _diff_summary(old: dict, new: dict) -> str:
    old_keys = set((old or {}).get("metrics", {}).keys())
    new_keys = set(new["metrics"].keys())
    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    changed = sorted(
        k for k in (old_keys & new_keys)
        if json.dumps(old["metrics"][k], sort_keys=True) != json.dumps(new["metrics"][k], sort_keys=True)
    )
    parts = []
    if added:
        parts.append(f"added {len(added)} node(s) ({', '.join(added[:5])}{'...' if len(added) > 5 else ''})")
    if removed:
        parts.append(f"removed {len(removed)} node(s) ({', '.join(removed[:5])}{'...' if len(removed) > 5 else ''})")
    if changed:
        parts.append(f"changed {len(changed)} node(s) ({', '.join(changed[:5])}{'...' if len(changed) > 5 else ''})")
    return "; ".join(parts) if parts else "no structural change detected"


def main():
    new_registry = build_registry()
    existing = _load_existing_registry()

    l1 = [m for m in new_registry["metrics"].values() if m["layer"] == 1]
    computable = [m for m in new_registry["metrics"].values() if m["computable"]]
    print(f"Parsed {len(new_registry['metrics'])} nodes across 3 pillars "
          f"({len(l1)} Layer-1, {len(computable)} directly queryable).")

    if existing and existing.get("content_sha256") == new_registry["content_sha256"]:
        print(f"No structural change since v{existing['registry_version']} -- registry left untouched.")
        return

    version = 1 if not existing else existing["registry_version"] + 1
    new_registry["registry_version"] = version
    new_registry["generated_at"] = datetime.now(timezone.utc).isoformat()

    with open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(new_registry, f, indent=2, sort_keys=True)
        f.write("\n")

    if version == 1:
        summary = (
            f"initial registry generated from {new_registry['source_tree_file']} "
            f"({len(l1)} Layer-1 nodes across 3 pillars, {len(new_registry['metrics'])} total nodes, "
            f"{len(computable)} directly queryable against dbt marts)."
        )
    else:
        summary = _diff_summary(existing, new_registry)
    _append_changelog(version, summary)
    print(f"Wrote {_REGISTRY_PATH} as v{version}; appended semantic/CHANGELOG.md.")


if __name__ == "__main__":
    main()
