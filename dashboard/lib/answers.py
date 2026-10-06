"""Answer assembly and tree structure for the Ask the Metric Tree page.

Pure Python, no Streamlit and no semantic-layer import: callers pass in the
registry mapping and a `query_fn` with query_metric()'s signature, so the
logic is unit-testable under the repo's default interpreter
(tests/test_dashboard_answers.py) with a fake query function.

Nothing here defines or computes a metric. Values come from query_metric();
this module chooses which period to headline, formats a value for display,
and decides how a rejected or unavailable child is described.

Conventions section 4.1: an answer about a non-leaf metric includes the
metric's own value and the values of its immediate children (the
registry's `children`), each obtained through the same query_fn call. A
child that cannot be queried is listed with its real reason, never dropped
and never given a value.
"""
import math
from typing import Callable, Dict, List, Optional

from . import censoring, labels

# --- Node status -----------------------------------------------------------

STATUS_QUERYABLE = "queryable"
STATUS_PARTIAL = "partial"
STATUS_NOT_COMPUTABLE = "not_computable"
STATUS_OVERLAY = "non_additive_overlay"
STATUS_CROSS_REFERENCE = "cross_reference"
# A node that is queryable but whose data carries no variation (blended TTFA is 0 in
# every month): a sixth state beside the five in conventions 4.9.
STATUS_DEGENERATE = "degenerate"

STATUS_LABEL = {
    STATUS_QUERYABLE: "Queryable",
    STATUS_PARTIAL: "Queryable (partial)",
    STATUS_NOT_COMPUTABLE: "Not computable",
    STATUS_OVERLAY: "Non-additive overlay",
    STATUS_CROSS_REFERENCE: "Cross-reference",
    STATUS_DEGENERATE: "No variation in data",
}
# Glyph plus text carries the status; the glyph is a second, non-color cue.
STATUS_GLYPH = {
    STATUS_QUERYABLE: "●",
    STATUS_PARTIAL: "◐",
    STATUS_NOT_COMPUTABLE: "○",
    STATUS_OVERLAY: "◇",
    STATUS_CROSS_REFERENCE: "↗",
    STATUS_DEGENERATE: "◌",
}

# Registry gap notes describe a degenerate series with one of these words ("identically
# 0", "degenerate on this data"). The registry carries no structured flag for it, so the
# note text is the signal; a node is only treated as degenerate when its data also shows
# the same value in every period (result_is_degenerate).
DEGENERATE_MARKERS = ("identically", "degenerate")
# A structural constant (SMB win rate is 100% because every SMB opportunity is created
# already Closed Won) is described as "always shows". It applies to the data check
# (result_is_degenerate, per-segment) but not to the node's static tree status, because
# the metric as a whole varies.
STRUCTURAL_MARKERS = ("always shows",)
# Pillar taglines as declarative labels (the registry's own taglines are phrased as
# questions or fragments; conventions 11.4).
PILLAR_TAGLINE = {
    "Growth": "Consumption revenue growth",
    "Efficiency": "Touch-model efficiency",
    "Durability": "Revenue retention",
}


def pillar_tagline(pillar: str, registry_tagline: str = "") -> str:
    return PILLAR_TAGLINE.get(pillar) or registry_tagline


def is_flagged_degenerate(node: dict) -> bool:
    note = str(node.get("gap_note") or "").lower()
    return bool(node.get("computable")) and any(m in note for m in DEGENERATE_MARKERS)


def node_status(node: dict) -> str:
    """The node's real status from its own registry flags."""
    if node.get("cross_reference"):
        return STATUS_CROSS_REFERENCE
    if not node.get("additive", True):
        return STATUS_OVERLAY
    if node.get("computable") and is_flagged_degenerate(node):
        return STATUS_DEGENERATE
    if node.get("computable"):
        return STATUS_PARTIAL if node.get("computability") == "partial" else STATUS_QUERYABLE
    return STATUS_NOT_COMPUTABLE


# --- Tree structure ---------------------------------------------------------

def pillar_order(registry: dict) -> List[str]:
    """Pillars in the order the tree file introduces them (first appearance
    in the registry's metric_order), not alphabetical."""
    seen: List[str] = []
    for key in registry["metric_order"]:
        p = registry["metrics"][key]["pillar"]
        if p not in seen:
            seen.append(p)
    return seen


def layer1_by_pillar(registry: dict) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {p: [] for p in pillar_order(registry)}
    for key in registry["metric_order"]:
        node = registry["metrics"][key]
        if node["layer"] == 1:
            out[node["pillar"]].append(key)
    return out


def question_for_node(node: dict) -> str:
    """The ready question a tree-panel click submits. The metric's own
    display name is embedded verbatim, so the router resolves it through
    the same name matching any typed question uses."""
    if node.get("children"):
        return f"What is {node['name']} and what is driving it?"
    return f"What is {node['name']}?"


def shorten(name: str, limit: int = 52) -> str:
    return name if len(name) <= limit else name[: limit - 1].rstrip() + "…"


# --- Units and value display -------------------------------------------------
# The registry carries no unit field. Units for the registry's queryable
# nodes are assigned here, keyed by registry key; anything not listed falls
# back to name hints. Proposed upstream: a `unit` field on each registry
# node, which would replace this table.
_UNIT_BY_KEY = {
    "new_logo_consumption_revenue": "usd",
    "expansion_consumption_revenue": "usd",
    "contraction_churned_consumption_revenue": "usd",
    "win_rate": "pct",
    "avg_initial_commitment": "usd",
    "activation": "months",
    "onboarding_completion_rate": "pct",
    "magic_number": "multiple",
    "s_m_cost": "usd",
    "rep_fully_loaded_cost_incl_ramp": "usd",
    "marketing_spend_allocation_by_channel": "usd",
    "consumption_payback": "months",
    "cac_by_channel": "usd",
    "utilized_vs_committed_action_volume": "usd",
    "onboarding_cs_efficiency": "per_million_actions",
    "am_touchpoint_volume": "count",
    "automated_action_volume_delivered": "count",
    "am_efficiency": "multiple",
    "am_cost_by_segment": "usd",
    "nrr": "pct",
    "grr": "pct",
    "logo_retention": "pct",
    "tenure_at_churn": "days",
    # Layer-2/3 keys the variance engine surfaces in the Digest drill-downs.
    "pipeline_generated": "converted_leads",
    "organic_content": "count",
    "paid": "count",
    "community_events": "count",
    "cyclical_vs_structural_usage_dip": "pct",
    "sm_cost": "usd",
    "automated_action_volume": "count",
    "nrr_expansion_rate": "pct",
    "nrr_contraction_rate": "pct",
    "nrr_churn_rate": "pct",
    "grr_contraction_rate": "pct",
    "grr_churn_rate": "pct",
    "rep_fully_loaded_cost": "usd",
    # Deal-level, workflow-chain, overage and account-health-input nodes (registry keys,
    # then the variance engine's own keys where they differ).
    "poc_pass_rate": "pct",
    "rep_capacity_ramp_mix": "pct",
    "loss_reason_mix": "pct",
    "discount_rate_vs_list": "pct",
    "deal_size_trend_within_segment_band": "pct",
    "deal_size_trend_within_band": "pct",
    "renewal_win_rate": "pct",
    "workflow_chain_under_utilization": "pct",
    "workflow_chain_underutilization": "pct",
    "ingestion_without_completion_rate": "pct",
    "mid_chain_workflow_abandonment": "pct",
    "mid_chain_abandonment": "pct",
    "declining_share_of_full_chain_vs_partial_chain_runs": "pct",
    "full_vs_partial_chain_share": "pct",
    "overage_realization": "pct",
    "support_ticket_volume_severity": "weighted_tickets_per_account_month",
    "engagement_login_frequency": "logins_per_account_month",
    "am_sentiment_notes": "score",
}
_DOLLAR_HINTS = ("revenue", "mrr", "arr", "cost", "cac", "commitment", "bookings", "pipeline",
                 "amount", "acv", "tcv", "spend")
_PCT_HINTS = ("rate", "retention", "nrr", "grr", "pct", "percentage", "completion")


def unit_for(node: dict) -> str:
    """One of usd, pct, months, days, multiple, count, per_million_actions,
    value."""
    key = node.get("key") or ""
    if key in _UNIT_BY_KEY:
        return _UNIT_BY_KEY[key]
    text = f"{key} {node.get('name') or ''}".lower()
    if "payback" in text:
        return "months"
    if any(h in text for h in _DOLLAR_HINTS):
        return "usd"
    if any(h in text for h in _PCT_HINTS):
        return "pct"
    return "value"


def _is_missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def format_value(unit: str, v) -> str:
    if _is_missing(v):
        return "n/a"
    v = float(v)
    if unit == "usd":
        sign = "-" if v < 0 else ""
        a = abs(v)
        if a >= 1_000_000:
            return f"{sign}${a / 1_000_000:.2f}M"
        if a >= 1_000:
            return f"{sign}${a / 1_000:.1f}K"
        return f"{sign}${a:,.0f}"
    if unit == "pct":
        return f"{v * 100:.1f}%"
    if unit == "months":
        return f"{v:.2f} mo"
    if unit == "days":
        return f"{v:,.0f} days"
    if unit == "multiple":
        return f"{v:.2f}x"
    if unit == "count":
        return f"{v:,.0f}"
    if unit == "converted_leads":
        return f"{v:,.0f} leads converted"
    if unit == "per_million_actions":
        return f"{v * 1_000_000:.2f} per 1M Actions"
    if unit == "weighted_tickets_per_account_month":
        return f"{v:.2f} weighted tickets per account-month"
    if unit == "logins_per_account_month":
        return f"{v:.1f} logins per account-month"
    if unit == "score":
        return f"{v:.2f}"
    # Unknown unit: a plain number, never scientific notation.
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 1:
        return f"{v:,.2f}"
    return f"{v:.3f}"


def join_formula(formula: str, note: Optional[str]) -> str:
    """Formula plus its note. A note that opens with punctuation attaches to the formula
    (', by segment'); one that opens with a bracket or a word needs a space."""
    note = note or ""
    if not note:
        return formula
    return f"{formula}{'' if note[0] in ',;:.' else ' '}{note}"


def unit_for_key(key: str) -> str:
    """Display unit for a metric key the dashboard knows (registry or engine key)."""
    return unit_for({"key": key, "name": key.replace("_", " ")})


def format_for_key(key: str, v) -> str:
    return format_value(unit_for_key(key), v)


# --- Result summarization ------------------------------------------------------

def _rows(result: dict) -> List[dict]:
    return list(result.get("data") or [])


def latest_period(result: dict) -> Optional[str]:
    """Latest period that carries at least one non-null value, or None when
    the result has no period column (grain 'all') or no value."""
    periods = [r["period"] for r in _rows(result)
               if "period" in r and not _is_missing(r.get("value"))]
    return max(periods) if periods else None


def has_any_value(result: dict) -> bool:
    return any(not _is_missing(r.get("value")) for r in _rows(result))


def values_at(result: dict, period: Optional[str]) -> Dict[str, object]:
    """{'' or segment: value} at `period` (or across all rows when the
    result has no period column)."""
    out: Dict[str, object] = {}
    for r in _rows(result):
        if "period" in r and period is not None and r["period"] != period:
            continue
        out[r.get("segment", "")] = r.get("value")
    return out


def prior_period(result: dict, period: Optional[str]) -> Optional[str]:
    if period is None:
        return None
    earlier = [r["period"] for r in _rows(result)
               if "period" in r and r["period"] < period and not _is_missing(r.get("value"))]
    return max(earlier) if earlier else None


def period_label(period: Optional[str], grain: str) -> str:
    if not period:
        return "all periods"
    if grain == "year":
        return period[:4]
    if grain == "quarter":
        q = (int(period[5:7]) - 1) // 3 + 1
        return f"{period[:4]} Q{q}"
    return period[:7]


# --- Answer assembly -----------------------------------------------------------

# Guardrail codes that mean the request itself was malformed: no child
# answers are attempted, the guardrail's message is the whole answer.
_REQUEST_ERRORS = {
    "unknown_metric", "invalid_dimension", "dimension_not_queryable",
    "invalid_filter_dimension", "invalid_segment_value", "invalid_grain", "invalid_request",
}


def _reason(node: dict, metrics: Dict[str, dict], state: str, message: Optional[str]) -> Optional[str]:
    """Short, factual reason a node has no value, from its own registry
    fields, cleaned of table identifiers and build machinery. Falls back to the
    semantic layer's message."""
    gap = labels.clean_registry_text(node.get("gap_note"))
    if state == "overlay":
        parent = metrics[node["parent"]]["name"] if node.get("parent") else "its parent"
        text = f"Non-additive overlay on {parent}; not a mathematical child and not queryable as a rollup contributor."
        if not node.get("computable") and gap:
            text += f" {gap}"
        return text
    if state in ("not_computable", "cross_reference"):
        return gap or labels.clean_registry_text(message)
    if state == "degenerate":
        return labels.first_sentences(gap, 260)[0] if gap else "The value is the same in every period."
    return labels.clean_registry_text(message) if message else message


def _classify(result: dict) -> str:
    err = result.get("error")
    if err is None:
        if not _rows(result):
            return "no_rows"
        return "value" if has_any_value(result) else "all_null"
    if err == "non_additive_metric":
        return "overlay"
    if err == "metric_not_queryable":
        return "not_computable"
    if err in _REQUEST_ERRORS:
        return "rejected"
    return "rejected"


def is_flagged_constant(node: dict) -> bool:
    """Registry note says the series (or one segment's series) is constant."""
    note = str(node.get("gap_note") or "").lower()
    return bool(node.get("computable")) and any(m in note for m in DEGENERATE_MARKERS + STRUCTURAL_MARKERS)


def constant_segments(node: dict, result: dict) -> List[str]:
    """Segments whose whole series is one value, for a node whose registry note flags a
    constant. Only meaningful when the result is split by segment."""
    if not is_flagged_constant(node):
        return []
    by_seg: Dict[str, set] = {}
    for r in _rows(result):
        if "segment" in r and not _is_missing(r.get("value")):
            by_seg.setdefault(r["segment"], set()).add(float(r["value"]))
    return sorted(seg for seg, vals in by_seg.items() if len(vals) == 1)


def result_is_degenerate(node: dict, result: dict) -> bool:
    """A registry-flagged node whose every non-null value (all segments, all periods)
    is the same number. Both signals are required: a constant series without a registry
    note could be real, and a note without constant data would be stale."""
    if not is_flagged_constant(node):
        return False
    vals = {float(r["value"]) for r in _rows(result) if not _is_missing(r.get("value"))}
    return len(vals) == 1


# --- Partial (truncated) and censored period handling ---------------------------------

def period_covers_month(period: Optional[str], grain: str, month_iso: Optional[str]) -> bool:
    """True when the period (as query_metric labels it: the first day of the month,
    quarter or year) contains the given month (YYYY-MM-DD or YYYY-MM)."""
    if not period or not month_iso or grain == "all":
        return False
    p, m = str(period)[:7], str(month_iso)[:7]
    if grain == "month":
        return p == m
    if grain == "year":
        return p[:4] == m[:4]
    if grain == "quarter":
        if p[:4] != m[:4]:
            return False
        start = int(p[5:7])
        return start <= int(m[5:7]) <= start + 2
    return False


def _as_months(excluded) -> List[str]:
    """One month, a list of months or None as a list."""
    if not excluded:
        return []
    if isinstance(excluded, str):
        return [excluded]
    return list(excluded)


def period_is_excluded(period: Optional[str], grain: str, excluded) -> bool:
    """True when the period contains any excluded month (the truncated final month, or a
    node's censored tail). `excluded` is one ISO month or a list of them."""
    return any(period_covers_month(period, grain, m) for m in _as_months(excluded))


def last_complete_period(result: dict, grain: str, partial_month) -> Optional[str]:
    """Latest period with a non-null value that contains no excluded month (`partial_month`
    is the truncated final month, or the list of months excluded for the node); None when
    there is none."""
    excluded = _as_months(partial_month)
    periods = [r["period"] for r in _rows(result)
               if "period" in r and not _is_missing(r.get("value"))
               and not period_is_excluded(r["period"], grain, excluded)]
    return max(periods) if periods else None


def basis_text(grain: str, complete: bool = True) -> str:
    """Basis line for a headline card on the Ask page."""
    unit = {"month": "month", "quarter": "quarter", "year": "year"}.get(grain)
    if unit is None:
        return "Basis: all periods"
    return f"Basis: last complete {unit}" if complete else f"Basis: latest {unit} (partial)"


def table_rows(result: dict, unit: str, grain: str, partial_month: Optional[str],
               censored=()) -> List[dict]:
    """The answer's data table with readable cells: period labels instead of
    timestamps, values with their unit, and a flag on the partial period. A period inside
    the node's censored tail is flagged 'Excluded: incomplete window'."""
    out = []
    censored = _as_months(censored)
    for r in _rows(result):
        row = {}
        for k, v in r.items():
            if k == "period":
                row["Period"] = period_label(v, grain)
            elif k == "value":
                continue
            else:
                row[k.replace("_", " ").capitalize()] = v
        row["Value"] = format_value(unit, r.get("value"))
        if "period" in r and period_is_excluded(r["period"], grain, censored):
            row["Note"] = (censoring.EXCLUDED_LABEL if grain == "month"
                           else f"Includes excluded months: {censoring.EXCLUDED_LABEL.lower()}")
        elif "period" in r and period_covers_month(r["period"], grain, partial_month):
            row["Note"] = "Partial month" if grain == "month" else "Includes partial month"
        out.append(row)
    # The Note column exists only when some row is flagged, and is blank (never None)
    # on the others.
    if any("Note" in row for row in out):
        for row in out:
            row.setdefault("Note", "")
    return out


# --- Default views and unsupported splits ----------------------------------------------

# A node whose all-segments figure is dominated by a structural constant opens on the
# meaningful segments when the question names none. Win rate: every SMB opportunity is
# created already Closed Won, so SMB is 100% by construction and the blended figure
# (85.8% in 2025-11) is mostly that constant; the Digest reads Commercial and Enterprise.
DEFAULT_SEGMENT_VIEW = {
    "win_rate": ("Commercial", "Enterprise"),
}
DEFAULT_VIEW_NOTE = ("No segment named: showing Commercial and Enterprise. SMB win rate is 100% by "
                     "construction, which would dominate an all-segment figure.")


def apply_default_view(parsed: dict) -> dict:
    """A copy of the routed question with the node's default segment view applied when the
    question names no segment, no segment split and no segment filter."""
    key = parsed.get("resolved_metric")
    subset = DEFAULT_SEGMENT_VIEW.get(key or "")
    out = dict(parsed)
    out["default_view_note"] = None
    if not subset:
        return out
    if parsed.get("filters", {}).get("segment") or "segment" in parsed.get("dimensions", []) \
            or parsed.get("segment_subset"):
        return out
    out["dimensions"] = list(parsed.get("dimensions", [])) + ["segment"]
    out["segment_subset"] = list(subset)
    out["default_view_note"] = DEFAULT_VIEW_NOTE
    return out


# A split the reader asked for that is not a queryable dimension, with the registry node
# that is the nearest real view of the same idea (offered as a suggestion, never routed to
# silently). Keys are the normalized split phrase; every target is checked against the
# registry by a test.
RELATED_SPLIT_NODES = {
    "loss reason": "loss_reason_mix",
    "loss reasons": "loss_reason_mix",
    "reason": "loss_reason_mix",
    "rep": "rep_capacity_ramp_mix",
    "reps": "rep_capacity_ramp_mix",
    "rep tenure": "rep_capacity_ramp_mix",
    "ramp": "rep_capacity_ramp_mix",
    "ramp status": "rep_capacity_ramp_mix",
}

FAILED_NOTICE = ("This question could not be answered. Rephrase it, or select a node in the metric "
                 "tree to start from a registered name.")


def split_notice(phrases: List[str], metric_name: str) -> str:
    """'Split by loss reason is not available for Win rate. The answer is not split.'"""
    if not phrases:
        return ""
    names = phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " or " + phrases[-1]
    return f"Split by {names} is not available for {metric_name}. The figures below are not split."


def split_suggestions(phrases: List[str], metrics: Dict[str, dict], resolved: Optional[str]) -> List[dict]:
    """[{key, label, question}] for each unsupported split phrase that has a related node
    (deduplicated, never the node already resolved)."""
    seen, out = set(), []
    for ph in phrases:
        target = RELATED_SPLIT_NODES.get(" ".join(ph.lower().split()))
        if target and target in metrics and target != resolved and target not in seen:
            seen.add(target)
            node = metrics[target]
            out.append({"key": target, "label": labels.qualified_node_label(target, node["name"]),
                        "question": question_for_node(node)})
    return out


def safe_answer(answer_fn: Callable[..., dict], question: str, **kwargs) -> dict:
    """Run an answer function so a failure becomes a plain-language notice instead of a
    stack trace: the Ask page never shows a traceback or a raw exception message."""
    try:
        return answer_fn(question, **kwargs)
    except Exception:  # noqa: BLE001 - any failure is reported as a notice, never raised
        return {"kind": "failed", "parsed": {"raw_question": question}, "notice": FAILED_NOTICE}


# --- Answer assembly -----------------------------------------------------------------

def build_answer(parsed: dict, query_fn: Callable[..., dict], metrics: Dict[str, dict],
                 partial_month: Optional[str] = None) -> dict:
    """Answer for one routed question.

    kind 'unresolved' when the router found no metric; otherwise kind
    'answer' with `own` (the metric's query result classified) and
    `children` (one entry per immediate child of a non-leaf metric).

    `partial_month` (ISO date of the truncated final month in the data window): the
    headline is the latest period that does not contain it, and the newest period
    is reported as partial. A node with a censored tail (lib/censoring.py) also excludes
    those months from the headline."""
    key = parsed["resolved_metric"]
    if key is None:
        return {"kind": "unresolved", "parsed": parsed}

    parsed = apply_default_view(parsed)
    node = metrics[key]
    dims = list(parsed["dimensions"])
    filters = dict(parsed["filters"])
    grain = parsed["grain"]

    result = query_fn(key, dimensions=dims, filters=filters, grain=grain)
    state = _classify(result)
    if state == "value" and result_is_degenerate(node, result):
        state = "degenerate"
    unit = unit_for(node)
    code = result.get("error")
    gap_clean = labels.clean_registry_text(node.get("gap_note"))
    query_gap = state == "not_computable" and labels.is_query_interface_gap(node.get("gap_note"))
    censored = censoring.censored_months(key, partial_month)
    excluded = censoring.excluded_months(key, partial_month)

    message = None
    message_tail = None
    detail = None
    if state == "rejected":
        message, message_tail = labels.guardrail_sentence(code, result.get("message"), node["name"])
    elif state == "overlay":
        message = labels.overlay_sentence(node["name"], node.get("note"), bool(node.get("computable")), node.get("gap_note"))
    elif state == "not_computable":
        if query_gap:
            # The artifact exists and is validated; only this interface cannot serve it.
            message = labels.QUERY_GAP_LEAD
            detail = gap_clean
        else:
            message = gap_clean or f"{node['name']} has no supporting source data."
    elif state == "degenerate":
        message = _reason(node, metrics, "degenerate", None)

    own = {
        "key": key,
        "name": node["name"],
        "display_name": labels.qualified_node_label(key, node["name"]),
        "pillar": node["pillar"],
        "layer": node["layer"],
        "parent": node.get("parent"),
        "parent_name": metrics[node["parent"]]["name"] if node.get("parent") else None,
        "status": node_status(node),
        "state": state,
        "query_gap": query_gap,
        "unit": unit,
        "result": result,
        "message": message,
        "message_tail": message_tail,
        "detail": detail,
        "guardrail_label": labels.guardrail_label(code) if state == "rejected" else None,
        "reason": _reason(node, metrics, state, result.get("message")),
        "gap_note": gap_clean if state == "value" else "",
        "warnings": [labels.clean_registry_text(w) for w in (result.get("warnings") or [])],
        "formula": (result.get("metric") or {}).get("formula") or node.get("formula"),
        "formula_note": (result.get("metric") or {}).get("formula_note") or node.get("formula_note"),
        "partial_month": partial_month,
        "censored_months": censored,
        "excluded_months": excluded,
    }
    period = None
    if state == "value":
        newest = latest_period(result)
        complete = last_complete_period(result, grain, excluded) if newest else None
        period = complete or newest
        own["period"] = period
        own["period_label"] = period_label(period, grain)
        own["headline_is_partial"] = period_is_excluded(period, grain, excluded)
        own["newest_partial_period"] = (
            newest if newest and period_is_excluded(newest, grain, excluded) and newest != period else None)
        own["newest_partial_label"] = period_label(own["newest_partial_period"], grain) if own["newest_partial_period"] else None
        own["values"] = values_at(result, period)
        own["constant_segments"] = constant_segments(node, result)
        prior = prior_period(result, period)
        own["prior_period"] = prior
        own["prior_period_label"] = period_label(prior, grain) if prior else None
        own["prior_values"] = values_at(result, prior) if prior else {}
        own["basis"] = basis_text(grain, complete=not own["headline_is_partial"])
        own["censored_tag"] = censoring.card_tag(key)
        own["censored_note"] = censoring.tail_sentence(key, partial_month)
    elif state == "all_null":
        own["message"] = (
            f"{node['name']} has no computable value for this query."
        )

    children: List[dict] = []
    if node.get("children") and state != "rejected":
        child_dims = [d for d in dims if d == "segment"]
        child_filters = {k: v for k, v in filters.items() if k == "segment"}
        for ckey in node["children"]:
            cnode = metrics[ckey]
            cres = query_fn(ckey, dimensions=child_dims, filters=child_filters, grain=grain)
            cstate = _classify(cres)
            if cstate == "value" and result_is_degenerate(cnode, cres):
                cstate = "degenerate"
            c_query_gap = cstate == "not_computable" and labels.is_query_interface_gap(cnode.get("gap_note"))
            c_excluded = censoring.excluded_months(ckey, partial_month)
            entry = {
                "key": ckey,
                "name": cnode["name"],
                "display_name": labels.qualified_node_label(ckey, cnode["name"]),
                "layer": cnode["layer"],
                "status": node_status(cnode),
                "status_label": None,
                "state": cstate,
                "query_gap": c_query_gap,
                "unit": unit_for(cnode),
                "has_children": bool(cnode.get("children")),
                "message": (labels.guardrail_sentence(cres.get("error"), cres.get("message"), cnode["name"])[0]
                            if cstate == "rejected"
                            else labels.clean_registry_text(cres.get("message")) if cstate in ("overlay", "not_computable") else None),
                "warnings": [labels.clean_registry_text(w) for w in (cres.get("warnings") or [])],
                "gap_note": "",
                "tail_note": None,
            }
            if cnode.get("cross_reference") and cstate == "not_computable":
                entry["state"] = "cross_reference"
            entry["reason"] = entry["message"] if cstate == "rejected" else _reason(cnode, metrics, entry["state"], cres.get("message"))
            if c_query_gap:
                # The long registry paragraph is shown once, with the parent; a row carries
                # the short statement.
                entry["status_label"] = "Not queryable here"
                entry["reason"] = labels.QUERY_GAP_LEAD
            if cstate == "value":
                cp_candidates = last_complete_period(cres, grain, c_excluded)
                cp = period if period is not None and any(
                    r.get("period") == period for r in _rows(cres)) else (cp_candidates or latest_period(cres))
                entry["period"] = cp
                entry["period_label"] = period_label(cp, grain)
                entry["values"] = values_at(cres, cp)
                entry["aligned"] = (cp == period)
                if cnode.get("gap_note"):
                    entry["gap_note"] = labels.first_sentences(labels.clean_registry_text(cnode["gap_note"]), 200)[0]
                if censoring.is_censored_node(ckey):
                    rng = censoring.tail_range_text(ckey, partial_month)
                    entry["tail_note"] = (f"Months {rng} excluded: incomplete window" if rng else None)
            elif cstate == "all_null":
                entry["message"] = labels.clean_registry_text(cres.get("warnings", [None])[0]) if cres.get("warnings") else (
                    "No computable value for this query.")
            children.append(entry)

    return {"kind": "answer", "parsed": parsed, "own": own, "children": children}
