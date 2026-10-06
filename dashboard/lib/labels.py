"""Reader-facing labels and text cleaning, Streamlit-free so it is unit-testable
(tests/test_dashboard_labels.py).

The dashboard reads identifiers from several artifacts: rule ids from the
playbook-trigger catalog, mart and table names inside registry gap notes, guardrail
error codes from the semantic layer. None of those belong on a page as written
(conventions Section 11). Everything here maps an identifier to a label, or removes
build-process machinery from a sentence, and nothing here invents a fact: a text
that cannot be mapped is humanized, not dropped, unless the sentence is pure
machinery (a file path, a function name).
"""
import re
from typing import Dict, List, Optional, Tuple


def escape_markdown(text) -> str:
    """Make arbitrary text render literally in Streamlit markdown. Two '$' in one
    string would otherwise open a LaTeX span and drop the dollar signs; underscores,
    asterisks, brackets and '#' would become emphasis, links or headings."""
    out = str(text)
    for ch in ("\\", "$", "*", "_", "`", "[", "]", "<", ">", "#"):
        out = out.replace(ch, "\\" + ch)
    return out


def humanize(key: str) -> str:
    """'poc_pass_rate_below_threshold' -> 'Poc pass rate below threshold'."""
    text = re.sub(r"[_\s]+", " ", str(key)).strip()
    return text[:1].upper() + text[1:] if text else text


_NODE_LABEL_PREFIX = re.compile(r"\bSee (?:Growth|Efficiency|Durability):\s*")


def clean_node_label(text) -> str:
    """A metric-tree node's label without the engine's cross-reference prefix: the NRR and
    GRR children are named 'See Growth: Expansion (share of starting revenue)' in
    analytics/variance_diagnostic.py's label table; the reader sees 'Expansion (share of
    starting revenue)'. Display only; the fix belongs upstream (PHRASE_MAP_UPSTREAM)."""
    return _NODE_LABEL_PREFIX.sub("", str(text or "")).strip()


# Layer-3 nodes whose scalar is one slice of the quantity the tree names. The registry's
# own notes state the slice (loss-reason mix serves the competitive share only; the ramp
# mix is the share of closed deals from reps in their first 180 days; the deal-size trend
# is the share of wins at the segment band floor; overage realization is overage MRR as a
# share of total MRR, because a realization rate is 100% in every account-month), so the
# display label carries it.
NODE_QUALIFIERS = {
    "overage_realization": "overage share of MRR",
    "loss_reason_mix": "competitive share",
    "rep_capacity_ramp_mix": "share from ramping reps",
    "deal_size_trend_within_band": "share of wins at band floor",
    "deal_size_trend_within_segment_band": "share of wins at band floor",
    # The tree names a per-channel split; the registry serves the total across channels
    # (a segment cut exists, a channel cut does not).
    "marketing_spend_allocation_by_channel": "total across channels",
    # The complement of Workflow chain under-utilization: chain accounts AT or above the
    # 70% completion cut, which is why the value reads about 94-99% and rises as the
    # series falls away at the end of the data window.
    "declining_share_of_full_chain_vs_partial_chain_runs": "share of chain accounts at or above 70% completion",
    "full_vs_partial_chain_share": "share of chain accounts at or above 70% completion",
}

_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


def qualified_node_label(key: str, label) -> str:
    """The display label of a Layer-3 node, with its slice when the node is a scalar view
    of a wider quantity: 'Loss-reason mix' -> 'Loss-reason mix (competitive share)'. A
    parenthetical the name already carries is replaced by the qualifier, not stacked on it
    ('Loss-reason mix (competitive / no-decision / price)' names the tree's three-way mix,
    and the node serves one slice of it)."""
    base = clean_node_label(label)
    q = NODE_QUALIFIERS.get(key)
    if not q or q in base:
        return base
    base = _TRAILING_PAREN_RE.sub("", base) or base
    return f"{base} ({q})"


# --- Playbook rules ----------------------------------------------------------

RULE_LABELS = {
    "ingestion_without_completion": "Ingestion without completion",
    "poc_pass_rate_below_threshold": "POC pass rate below threshold",
    "post_close_underutilization": "Post-close under-utilization",
}


def rule_label(rule_id: str) -> str:
    return RULE_LABELS.get(rule_id) or _acronyms(humanize(rule_id))


_ACRONYMS = {"poc": "POC", "nrr": "NRR", "grr": "GRR", "sdr": "SDR", "arr": "ARR", "mrr": "MRR",
             "cac": "CAC", "ttfa": "TTFA", "am": "AM", "cs": "CS", "cro": "CRO", "ml": "ML"}


def _acronyms(text: str) -> str:
    return " ".join(_ACRONYMS.get(w.lower(), w) for w in text.split(" "))


# --- Data sources --------------------------------------------------------------

SOURCE_LABELS = {
    "fact_workflow_chain_events": "Workflow chain events",
    "fact_opportunities": "Opportunities",
    "fact_committed_vs_utilized_monthly": "Committed vs. utilized Actions (monthly)",
    "fact_leads": "Leads",
    "fact_campaign_engagement_events": "Campaign engagement events",
    "fact_usage_monthly": "Monthly product usage",
    "fact_sales_activities": "Sales activities",
    "fact_am_activity": "Account-manager activity",
    "fact_opportunity_stage_history": "Opportunity stage history",
    "fact_rep_monthly_cost": "Rep monthly cost",
    "mart_growth_bridge": "Growth bridge",
    "mart_efficiency": "Efficiency",
    "mart_durability": "Durability",
    "mart_account_health": "Account health",
    "mart_gtm_plan": "GTM plan",
    "mart_segment_migration": "Segment migration",
}

_IDENT_RE = re.compile(r"\b(?:fact|dim|mart|stg|int)_[a-z0-9]+(?:_[a-z0-9]+)*\b")


def _ident_label(ident: str) -> str:
    kind = ident.split("_", 1)[0]
    body = SOURCE_LABELS[ident].lower() if ident in SOURCE_LABELS else re.sub(
        r"^(?:fact|dim|mart|stg|int)_", "", ident).replace("_", " ")
    return f"the {body} reporting table" if kind == "mart" else f"{body} data"


def source_label(text: str) -> str:
    """'fact_committed_vs_utilized_monthly + fact_opportunities' -> a readable
    list. Unknown identifiers fall back to their humanized body."""
    parts = [p.strip() for p in re.split(r"\s*\+\s*|,\s*", str(text)) if p.strip()]
    out = []
    for p in parts:
        if p in SOURCE_LABELS:
            out.append(SOURCE_LABELS[p])
        else:
            out.append(humanize(re.sub(r"^(?:fact|dim|mart|stg|int)_", "", p)))
    return " and ".join(out) if out else str(text)


# --- Display labels for evidence-table columns -------------------------------------

FIELD_LABELS = {
    "label": "Metric",
    "metric": "Metric",
    "layer": "Layer",
    "parent_key": "Under",
    "parent": "Under",
    "value": "Value",
    "baseline": "Baseline",
    "deviation_pct": "Deviation",
    "status": "Status",
    "reason": "Reason",
    "gap_note": "Reason",
}
# Columns that only repeat another column in identifier form.
HIDDEN_FIELDS = {"metric_key", "computability", "cross_reference_to", "comparison_basis"}


def field_label(name: str) -> str:
    return FIELD_LABELS.get(name) or humanize(name)


# --- Explicit phrase map -------------------------------------------------------------
# Display-time rewrites of text that originates upstream (the registry, the readout)
# and cannot be edited from the dashboard. Each entry keeps the fact and changes only the
# wording: process references (build-spec sections, document paths, snake_case column
# names), assistant-style hedging and machine syntax. Entries are exact phrases or narrow
# patterns, so an unlisted string passes through unchanged; PHRASE_MAP_UPSTREAM lists the
# source strings that should be fixed where they originate, after which an entry here is
# harmless dead code.

def _drivers_reference(m: "re.Match") -> str:
    names = {"expansion_consumption_revenue": "Expansion consumption revenue",
             "contraction_churned_consumption_revenue": "Contraction + churned consumption revenue"}
    rest = re.sub(r"nrr_expansion/contraction/churn via ", "", m.group("rest"))
    rest = re.sub(r"\b(?:expansion|contraction)_[a-z_]+\b", lambda k: names.get(k.group(0), k.group(0)), rest)
    rest = rest.replace(" and its children", " and its children")
    topic = m.group("topic")
    return (f"This node points to the Growth {topic} and holds no value of its own; "
            f"ask about {rest} instead.")


PHRASE_MAP: List[Tuple["re.Pattern", object]] = [(re.compile(p, re.S), r) for p, r in [
    # Process references
    (r"\s*(?:--|—)\s*build spec Section \d+", ""),
    (r"The build spec's (\w+) source", r"The \1 source"),
    (r"docs/acme-corp-analytics-methods\.md", "the analytics methods document"),
    (r"docs/acme-corp-gtm-metric-tree\.md", "the metric tree document"),
    (r"docs/acme-corp-gtm-portfolio-build-spec\.md", "the build specification"),
    # Machine syntax
    (r"SMB always shows win_rate = 1\.0", "SMB always shows a win rate of 100%"),
    (r"full_chain_completion_rate < 70%", "full-chain completion rate below 70%"),
    (r"spread > ", "spread above "),
    (r"use grain=year for a stable read", "use the year grain for a stable read"),
    (r"opportunity_type='renewal' scoping", "renewal-only scoping"),
    (r"that lives in fact_opportunities / fact_opportunity_stage_history -- fact_\* tables outside a mart_\* rollup for this cut",
     "that is held in the opportunity and stage-history records, which the reporting tables do not roll up for this cut"),
    (r"channel is listed in allowed_dimensions per the tree but is NOT in queryable_dimensions until a Phase 2 mart change exposes it",
     "channel is a split the tree allows but it is not available until the data model exposes it"),
    (r"channel is listed in allowed_dimensions per the tree but is NOT in queryable_dimensions",
     "channel is a split the tree allows but it is not available yet"),
    (r"\bno mart or fact table\b", "no reporting or event table"),
    (r"\bno mart exposes\b", "no reporting table exposes"),
    (r"Defined by reference in the tree \('See Growth -- (?P<topic>[^']+)'\)(?:, not a leaf with its own actual)? -- query (?P<rest>[^.]+?) instead\.",
     _drivers_reference),
    (r"\(mart_deal_funnel\.avg_days_in_\*\)", "(the average days in each stage)"),
    (r"\bthe mart carries\b", "the reporting table carries"),
    (r"mart_efficiency\.sm_cost", "the S&M cost in the efficiency reporting table"),
    (r"\bblended_cac\b", "blended CAC"),
    (r"\bam_expansion_arr\b", "AM expansion ARR"),
    (r"\bSee (?:Growth|Efficiency|Durability): ", ""),
    # Voice
    (r"Real, not fabricated, just degenerate on this data\.", "The value is a property of the data."),
    (r"A real data property, not a query bug\.", "The value is a property of the data."),
    (r"PRIOR-period", "prior-period"),
]]

# Source strings that read badly and should be rewritten where they live. Each is
# handled by an entry above; this list is the follow-up checklist.
PHRASE_MAP_UPSTREAM = [
    "analytics/variance_diagnostic.py label table: the NRR and GRR Layer-2 children are labelled 'See Growth: Expansion "
    "(share of starting revenue)' and likewise for Contraction and Churn; the 'See Growth:' prefix is a tree "
    "cross-reference marker, not part of the metric name (lib/labels.py clean_node_label strips it for display).",
    "semantic/metric_registry.json (generated from the tree and build_registry.py): gap notes that cite build-spec "
    "sections, table names, column names, file paths, 'grain=year', 'PRIOR-period', 'Real, not fabricated', "
    "'A real data property, not a query bug', 'NOT in queryable_dimensions until a Phase 2 mart change', "
    "'query ... instead' pointers, and the 'See Growth' cross-reference notes.",
    "semantic/metric_registry.json: the stage_to_stage_conversion gap note cites 'mart_deal_funnel.avg_days_in_*' and the "
    "loss_reason_mix / support_ticket_volume_severity notes say 'the mart carries'.",
    "semantic/server.py guardrail messages: 'gap_note:' / 'queryable_dimensions' quoted inside the message, "
    "'(note: ...)' wrapper and '**non-additive**' markdown.",
    "analytics/outputs readout: watchlist caveat citing docs/acme-corp-analytics-methods.md; rule catalog "
    "description with 'full_chain_completion_rate < 70%'; forecast divergence status with 'spread > 25%'; "
    "the forecast caveat about 'the marts' final selects'.",
]


def apply_phrase_map(text: Optional[str]) -> str:
    """Apply the explicit phrase map to upstream text. Nothing else is changed."""
    if not text:
        return "" if text is None else str(text)
    out = str(text)
    for pattern, repl in PHRASE_MAP:
        out = pattern.sub(repl, out)
    return out


# --- Registry and guardrail text ---------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'0-9])")

# A sentence that still names a constant or a build script after path replacement
# describes how the build works, not what the metric is.
_MACHINERY_RE = re.compile(r"_[A-Z][A-Z_]{3,}\b|\bbuild_registry\b")
_PATH_RE = re.compile(r"(?:[\w-]+/)*([\w-]+)\.py(?:'s)?")


def split_sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(str(text).strip()) if s.strip()]


def _strip_markdown(text: str) -> str:
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def _tuple_to_list(text: str) -> str:
    """"must be one of ('SMB', 'Commercial', 'Enterprise')" -> "SMB, Commercial or Enterprise"."""
    def repl(m: "re.Match") -> str:
        items = re.findall(r"'([^']+)'", m.group(0))
        if not items:
            return m.group(0)
        return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]
    return re.sub(r"\(\s*'[^']+'(?:\s*,\s*'[^']+')*\s*,?\s*\)", repl, text)


def clean_registry_text(text: Optional[str]) -> str:
    """Make registry or guardrail wording readable: markdown stripped,
    table identifiers turned into data-source names, process-only sentences
    (file paths, function and constant names) dropped. The substantive reason is
    kept."""
    if not text:
        return ""
    kept = []
    prepared = _PATH_RE.sub(lambda m: "the " + m.group(1).replace("_", " ") + " step", _strip_markdown(str(text)))
    prepared = re.sub(r"\bquery_metric\b", "the query interface", prepared)
    prepared = apply_phrase_map(prepared)
    for sentence in split_sentences(prepared):
        if _MACHINERY_RE.search(sentence):
            continue
        kept.append(sentence)
    out = " ".join(kept)
    out = re.sub(r"\ba fact_\* table\b", "an event table", out)
    out = re.sub(r"\bmart_\*(?:\s+(?:table|rollup))?", "reporting table", out)
    out = re.sub(r"\bfact_\*(?:\s+tables?)?", "event tables", out)
    out = re.sub(r"\b(mart_[a-z0-9_]+)\.([a-z0-9_]+)",
                 lambda m: f"{_ident_label(m.group(1))} ({m.group(2).replace('_', ' ')})", out)
    out = _IDENT_RE.sub(lambda m: _ident_label(m.group(0)), out)
    out = _tuple_to_list(out)
    out = re.sub(r"\b[a-z]+(?:_[a-z]+)+\b", lambda m: m.group(0).replace("_", " "), out)
    out = out.replace(" -- ", " — ")
    out = re.sub(r"\s+", " ", out).strip()
    def _cap(m: "re.Match") -> str:
        # Not after an abbreviation ("convert vs. not", "e.g. the"): those continue a sentence.
        before = out[:m.start()].rstrip(". ").rsplit(" ", 1)[-1].lower()
        return m.group(0) if before in {"vs", "e.g", "i.e", "etc"} else m.group(1).upper()
    out = re.sub(r"(?<=[.!?] )([a-z])", _cap, out)
    out = out[:1].upper() + out[1:]
    if kept and not out:
        out = "No further detail is registered for this metric."
    return out


GUARDRAIL_LABELS = {
    "unknown_metric": "Metric not in the registry",
    "invalid_dimension": "Split not supported",
    "dimension_not_queryable": "Split not available yet",
    "invalid_filter_dimension": "Filter not supported",
    "invalid_segment_value": "Segment not recognized",
    "invalid_grain": "Grain not supported",
    "invalid_request": "Request not supported",
    "non_additive_metric": "Non-additive overlay",
    "metric_not_queryable": "Not computable",
    "segment_not_available": "Segment not available",
}


def guardrail_label(code: Optional[str]) -> str:
    if not code:
        return "Request not supported"
    return GUARDRAIL_LABELS.get(code) or "Request not supported"


_DIM_NOT_QUERYABLE_RE = re.compile(
    r"The metric tree allows '(?P<dim>[^']+)' on '(?P<key>[^']+)', but no mart_\* table currently exposes "
    r"that cut\s*--\s*queryable_dimensions today:\s*\[(?P<avail>[^\]]*)\]\.?\s*(?:gap_note:\s*(?P<tail>.*))?$",
    re.DOTALL,
)


# Two message shapes: "has no rows for segment 'X': its source mart (m) carries [..] only." and
# "has no <what> data for segment 'X': <explanation>; the metric is defined for [..] only."
# (the POC pass rate message). Both end with the segments the metric covers and an optional
# quoted gap note.
_SEGMENT_NOT_AVAILABLE_RE = re.compile(
    r"'(?P<key>[^']+)' has no (?:rows|[^']*?data) for segment '(?P<seg>[^']+)':.*?"
    r"\[(?P<avail>[^\]]*)\] only\.\s*(?:(?:gap_note|Gap note):\s*(?P<tail>.*))?$",
    re.DOTALL,
)


def guardrail_sentence(code: Optional[str], message: Optional[str], metric_name: str = "this metric",
                       gap_note: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """(sentence, tail). `sentence` is the guardrail's reason as a clean sentence;
    `tail` is the registry's own explanation when the guardrail quoted it and it
    differs from the metric's gap note (which the page shows separately), else None."""
    message = str(message or "").strip()
    if code == "dimension_not_queryable":
        m = _DIM_NOT_QUERYABLE_RE.match(message)
        if m:
            avail = re.findall(r"'([^']+)'", m.group("avail"))
            avail_text = _join_or(avail) if avail else "none"
            sentence = (f"The metric tree allows a {m.group('dim').replace('_', ' ')} split on {metric_name}, "
                        f"but no reporting table exposes that split yet. Available split: {avail_text}.")
            tail = clean_registry_text(m.group("tail")) if m.group("tail") else None
            if tail and gap_note and clean_registry_text(gap_note) == tail:
                tail = None
            return sentence, tail or None
    if code == "segment_not_available":
        m = _SEGMENT_NOT_AVAILABLE_RE.match(message)
        if m:
            avail = re.findall(r"'([^']+)'", m.group("avail"))
            covers = f"covers {_join_or(avail)} only" if avail else "has no segment coverage"
            sentence = f"{metric_name} has no data for the {m.group('seg')} segment; it {covers}."
            tail = clean_registry_text(m.group("tail")) if m.group("tail") else None
            if tail and gap_note and clean_registry_text(gap_note) == tail:
                tail = None
            return sentence, tail or None
    if code == "non_additive_metric":
        return clean_registry_text(message), None
    return clean_registry_text(message), None


def _join_or(items: List[str]) -> str:
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " or " + items[-1]


def overlay_sentence(name: str, note: Optional[str], computable: bool, gap_note: Optional[str]) -> str:
    """The overlay message composed from the node's own fields rather than by
    cleaning the guardrail's sentence."""
    parts = [f"{name} is a diagnostic overlay: it is never summed into its parent's calculation and is not "
             "queryable as a rollup contributor."]
    if note:
        text = re.sub(r"^non-additive diagnostic overlay", "Overlay", clean_registry_text(note), flags=re.I)
        parts.append(text.rstrip(".") + ".")
    if not computable:
        gap = clean_registry_text(gap_note)
        parts.append(gap if gap else "It has no series of its own.")
    return " ".join(p for p in parts if p)


# --- Not queryable here vs. not computable -------------------------------------------
# A registry node can be marked not computable because the query interface cannot serve it
# (a validated analytics step computes it and the weekly readout shows it) or because no
# source supports it at all. The registry carries no structured flag; its gap note says
# "Computed and validated by ..." for the first case.

QUERY_GAP_LEAD = "Not available through this query interface; shown in the weekly readout."

_QUERY_GAP_RE = re.compile(r"^\s*computed and validated\b", re.I)


def is_query_interface_gap(gap_note: Optional[str]) -> bool:
    """True when the registry's gap note says a validated artifact computes the metric
    and only the query interface cannot serve it."""
    return bool(gap_note) and bool(_QUERY_GAP_RE.match(str(gap_note)))


def first_sentences(text: str, limit: int = 220) -> Tuple[str, str]:
    """(short, rest): whole sentences up to `limit` characters, the remainder
    separately. A first sentence over the limit is cut at a word boundary with an
    ellipsis and the full sentence goes to `rest` so no fact is lost."""
    sentences = split_sentences(text)
    if not sentences:
        return "", ""
    short: List[str] = []
    used = 0
    for s in sentences:
        if short and used + len(s) + 1 > limit:
            break
        if not short and len(s) > limit:
            cut = s[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
            return cut, " ".join(sentences)
        short.append(s)
        used += len(s) + 1
    rest = " ".join(sentences[len(short):])
    return " ".join(short), rest
