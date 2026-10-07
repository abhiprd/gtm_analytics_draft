"""Ask the metric tree -- a chat-style front end onto the Phase 3 semantic
layer (semantic/server.py's query_metric), called in-process via
dashboard/lib/semantic_bridge.py.

Audience tier: ad hoc / exploratory (dashboard-design-conventions.md
Section 4.1). Three pieces, per Sections 4.1 and 4.7:

  * a standing metric-tree panel in the sidebar -- all 11 Layer-1 nodes
    under their pillars, expandable to Layers 2 and 3, each labelled with
    its real status. Built from the semantic layer's own registry
    (semantic/metric_registry.json, generated from
    docs/acme-corp-gtm-metric-tree.md), never from a copy. Clicking a node
    submits a ready question about it.
  * a chat thread whose answers about a non-leaf metric carry the metric's
    own value and its immediate children's values.
  * one "Notes & assumptions" expander (Section 11.3).

Routing is deterministic keyword matching (lib/routing.py), not an LLM
call; the live-model version is the deferred seam recorded in
project_status.json (chat_live_llm_routing). The page discloses that.
"""
import html
import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

_DASHBOARD_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DASHBOARD_DIR)
import theme
from lib import answers as A
from lib import censoring
from lib import data
from lib import labels
from lib import semantic_bridge as sb

theme.page_config("Ask the metric tree | Acme Corp GTM", "\U0001F4AC")
theme.inject_global_css()

REGISTRY = sb.registry()
METRICS = REGISTRY["metrics"]
_SEGMENT_ORDER = list(theme.SEGMENT_COLOR.keys())
_FORMULA_INLINE_LIMIT = 220
# NRR and GRR charts show the trailing 24 months, the same window the
# Segment Efficiency page applies: the earliest months carry a near-zero
# starting-MRR denominator whose ratio spikes would flatten the recent trend.
_WINDOWED_KEYS = {"nrr", "grr"}
_WINDOW_PERIODS = 24


# =====================================================================
# Session state and callbacks
# =====================================================================

st.session_state.setdefault("ask_history", [])
st.session_state.setdefault("tree_open", set())


def _queue_question(question: str) -> None:
    st.session_state["ask_queue"] = question


def _toggle_node(key: str) -> None:
    opened = st.session_state["tree_open"]
    if key in opened:
        opened.discard(key)
    else:
        opened.add(key)


def _clear_history() -> None:
    st.session_state["ask_history"] = []


# =====================================================================
# Metric-tree panel (sidebar) -- Section 4.7
# =====================================================================

def _status_line(node: dict) -> str:
    status = A.node_status(node)
    return f"Layer {node['layer']} · {A.STATUS_GLYPH[status]} {A.STATUS_LABEL[status]}"


def _render_node(key: str, depth: int) -> None:
    node = METRICS[key]
    has_children = bool(node["children"])
    opened = key in st.session_state["tree_open"]
    # Indent columns, then a toggle column, then the label column.
    spec = [1] * (depth - 1) + [1, 8]
    cols = st.sidebar.columns(spec, vertical_alignment="top")
    with cols[-2]:
        if has_children:
            st.button(
                "▾" if opened else "▸", key=f"tg_{key}", on_click=_toggle_node, args=(key,),
                type="tertiary",
                help=f"{'Hide' if opened else 'Show'} children",
            )
    with cols[-1]:
        label = theme.escape_md(A.shorten(node["name"]))
        st.button(
            label, key=f"nd_{key}", on_click=_queue_question, args=(A.question_for_node(node),),
            # A tooltip only where the label is shortened; a long hover line over the
            # standing tree would cover neighboring nodes.
            help=node["name"] if A.shorten(node["name"]) != node["name"] else None,
            type="tertiary", width="stretch",
        )
        st.markdown(f'<div class="tree-meta">{_status_line(node)}</div>', unsafe_allow_html=True)
    if has_children and opened:
        for child in node["children"]:
            _render_node(child, depth + 1)


def _render_tree_panel() -> None:
    by_pillar = A.layer1_by_pillar(REGISTRY)
    n_l1 = sum(len(v) for v in by_pillar.values())
    st.sidebar.markdown("### Metric tree")
    st.sidebar.caption(
        f"{n_l1} Layer-1 metrics under {len(by_pillar)} pillars. Select a node to ask about it; "
        "▸ opens its children."
    )
    st.sidebar.caption(
        " · ".join(f"{A.STATUS_GLYPH[s]} {A.STATUS_LABEL[s]}" for s in (
            A.STATUS_QUERYABLE, A.STATUS_PARTIAL, A.STATUS_NOT_COMPUTABLE,
            A.STATUS_OVERLAY, A.STATUS_CROSS_REFERENCE, A.STATUS_DEGENERATE))
    )
    for pillar, keys in by_pillar.items():
        dot = theme.PILLAR_COLOR.get(pillar.lower(), theme.NEUTRAL_GRAY)
        tagline = A.pillar_tagline(pillar, REGISTRY["pillars"].get(pillar, {}).get("tagline", ""))
        st.sidebar.markdown(
            f'<div class="tree-pillar"><span class="pillar-dot" style="background-color:{dot}"></span>'
            f'{pillar}</div><div class="tree-meta" style="margin-left:0">{html.escape(tagline)}</div>',
            unsafe_allow_html=True,
        )
        for key in keys:
            _render_node(key, 1)


_render_tree_panel()


# =====================================================================
# Chart helpers
# =====================================================================

def _axis_meta(own: dict) -> dict:
    """Y-axis title and tick format from the metric's display unit, so a
    unit is never carried by title text alone (Section 3.2)."""
    unit, name = own["unit"], own.get("display_name") or labels.qualified_node_label(own["key"], own["name"])
    if unit == "usd":
        return {"title": f"{name} (USD)", "tickprefix": "$", "tickformat": "~s"}
    if unit == "pct":
        return {"title": f"{name} (%)", "tickformat": ".0%"}
    if unit == "months":
        return {"title": f"{name} (months)", "ticksuffix": " mo"}
    if unit == "days":
        return {"title": f"{name} (days)"}
    if unit == "multiple":
        return {"title": f"{name} (multiple)", "ticksuffix": "x"}
    if unit == "count":
        return {"title": f"{name} (count)"}
    if unit == "converted_leads":
        return {"title": f"{name} (leads converted)"}
    if unit == "per_million_actions":
        return {"title": f"{name} (touchpoints per 1M Actions)"}
    if unit == "weighted_tickets_per_account_month":
        return {"title": f"{name} (severity-weighted tickets per account-month)"}
    if unit == "logins_per_account_month":
        return {"title": f"{name} (logins per account-month)"}
    if unit == "score":
        return {"title": f"{name} (score)"}
    return {"title": f"{name} (value)"}


def _scaled(own: dict, series: pd.Series) -> pd.Series:
    return series * 1_000_000 if own["unit"] == "per_million_actions" else series


def _figure(df: pd.DataFrame, own: dict, pillar_color: str, grain: str = "month") -> go.Figure:
    """Section 3.1: a metric over time -> line chart; split by segment ->
    one line per segment in the segment palette; single series -> the
    metric's pillar color (category identity, not a status judgment)."""
    meta = _axis_meta(own)
    fig = go.Figure()
    excluded = own.get("excluded_months") or ([own["partial_month"]] if own.get("partial_month") else [])
    mask = (df["period"].map(lambda p: A.period_is_excluded(p, grain, excluded))
            if excluded else pd.Series(False, index=df.index))
    partial, df = df[mask], df[~mask]
    excluded_label = censoring.EXCLUDED_LABEL if own.get("censored_months") else censoring.PARTIAL_LABEL
    if "segment" in df.columns:
        segs = [s for s in _SEGMENT_ORDER if s in df["segment"].unique()]
        segs += [s for s in df["segment"].unique() if s not in _SEGMENT_ORDER]
        for seg in segs:
            sdf = df[df["segment"] == seg].sort_values("period")
            color = theme.SEGMENT_COLOR.get(seg, theme.NEUTRAL_GRAY)
            fig.add_trace(go.Scatter(
                x=sdf["period"], y=_scaled(own, sdf["value"]), mode="lines+markers", name=seg,
                line=dict(color=color, width=2.5), marker=dict(color=color, size=6)))
        show_legend = True
    else:
        sdf = df.sort_values("period")
        fig.add_trace(go.Scatter(
            x=sdf["period"], y=_scaled(own, sdf["value"]), mode="lines+markers", name=own["name"],
            line=dict(color=pillar_color, width=2.5), marker=dict(color=pillar_color, size=6)))
        show_legend = False
    # The truncated final period, or a node's censored tail, is drawn as open markers
    # (never part of the line).
    if not partial.empty:
        colors = [theme.SEGMENT_COLOR.get(sg, theme.NEUTRAL_GRAY) for sg in partial["segment"]] \
            if "segment" in partial.columns else pillar_color
        fig.add_trace(go.Scatter(
            x=partial["period"], y=_scaled(own, partial["value"]), mode="markers", name=excluded_label,
            marker=dict(symbol="diamond-open", size=11, color=colors, line=dict(width=2))))
        show_legend = True
    fig.update_layout(**theme.plotly_layout(xaxis_title="Period", showlegend=show_legend, height=340))
    theme.style_axes(fig)
    tickformat = meta.get("tickformat")
    if own["unit"] == "pct" and "value" in df.columns and len(df) > 1:
        spread = float(df["value"].max() - df["value"].min())
        if spread < 0.05:
            # A narrow range (logo retention spans about 2 pp) needs a decimal, or two
            # neighboring ticks both read "100%".
            tickformat = ".1%"
    fig.update_yaxes(title_text=meta["title"], tickformat=tickformat,
                     tickprefix=meta.get("tickprefix"), ticksuffix=meta.get("ticksuffix"))
    return fig


# =====================================================================
# Answer rendering
# =====================================================================

def _fmt_by_segment(unit: str, values: dict, subset=None) -> str:
    if set(values) == {""}:
        return A.format_value(unit, values[""])
    parts = []
    for seg in _SEGMENT_ORDER:
        if seg in values and (not subset or seg in subset):
            parts.append(f"{seg} {A.format_value(unit, values[seg])}")
    return "<br>".join(parts) if parts else "n/a"


def _children_table(own: dict, children: list, subset) -> None:
    layer = children[0]["layer"]
    rows = []
    for c in children:
        status = c.get("status_label") or A.STATUS_LABEL[c["status"]]
        glyph = A.STATUS_GLYPH[c["status"]]
        if c["state"] == "value":
            period_note = "" if c.get("aligned") else f' <span class="reason">({c["period_label"]})</span>'
            value = _fmt_by_segment(c["unit"], c["values"], subset) + period_note
            detail = " ".join(x for x in (c.get("gap_note"), c.get("tail_note")) if x)
        elif c["state"] == "degenerate":
            value = "Not computable"
            detail = c.get("reason") or "The value is the same in every period."
        elif c["state"] == "all_null":
            value = "n/a"
            detail = c.get("message") or "No computable value for this query."
        elif c["state"] == "no_rows":
            value = "n/a"
            detail = "No rows for this filter."
        else:
            value = "n/a"
            detail = c.get("reason") or c.get("message") or ""
        rows.append(
            f'<tr><td><strong>{html.escape(c.get("display_name") or c["name"])}</strong>'
            f'<div class="reason">Layer {c["layer"]}</div></td>'
            f'<td>{value}</td>'
            f'<td>{glyph} {html.escape(status)}'
            f'{f"<div class=reason>{html.escape(detail)}</div>" if detail else ""}</td></tr>'
        )
    period = own.get("period_label")
    value_head = f"Value ({period})" if period else "Value"
    theme.card_block(
        f'<div class="card-label">Immediate children of {html.escape(own.get("display_name") or own["name"])} (Layer {layer})</div>'
        f'<table class="answer-table"><thead><tr><th style="width:34%">Metric</th>'
        f'<th style="width:18%">{html.escape(value_head)}</th><th>Status</th></tr></thead>'
        f'<tbody>{"".join(rows).replace("$", "&#36;")}</tbody></table>'
    )


def _note_box(text: str) -> None:
    """A registry data note on a live answer, above the chart: short text inline, the
    remainder behind a Details toggle (no expander nesting inside the chat message)."""
    short, rest = labels.first_sentences(text, 260)
    body = f"<strong>Data note.</strong> {theme.escape_html(short)}"
    if rest:
        body += (f' <details class="note-details"><summary>Details</summary>'
                 f'<div>{theme.escape_html(rest)}</div></details>')
    theme.card_block(f'<div style="font-size:0.9rem;line-height:1.45">{body}</div>')


def _render_value_answer(own: dict, parsed: dict, idx: int) -> None:
    pillar_key = (own["pillar"] or "").lower()
    pillar_color = theme.PILLAR_COLOR.get(pillar_key, theme.NEUTRAL_GRAY)
    unit = own["unit"]
    grain = parsed["grain"]
    subset = parsed.get("segment_subset") or None
    values = own["values"]
    basis = [own["basis"]] if own.get("basis") else []

    censored_note = own.get("censored_note")
    if own.get("headline_is_partial"):
        st.caption("Every period in this result includes the truncated final month or excluded months, so "
                   "the headline is a partial figure.")
    elif censored_note and own.get("newest_partial_label"):
        # A series with a right-censored tail (lib/censoring.py): the headline is the last
        # uncensored period and the note is visible, not behind a Details toggle.
        theme.card_block(f'<div style="font-size:0.9rem;line-height:1.45"><strong>Data note.</strong> '
                         f'{theme.escape_html(censored_note)}</div>')
    elif own.get("newest_partial_label"):
        st.caption(f"{own['newest_partial_label']} is the truncated final period of the data window. It is "
                   "excluded from the headline and drawn as an open marker in the chart; the data table "
                   "labels it.")
    card_name = own.get("display_name") or own["name"]
    tag = own.get("censored_tag")

    def comparison_for(seg_key):
        prior = own["prior_values"].get(seg_key)
        if own["prior_period"] and prior is not None:
            return f"{A.format_value(unit, prior)} in {own['prior_period_label']}"
        return "No prior period in this result"

    if set(values) == {""}:
        cards = [dict(label=f"{card_name} · {own['period_label']}", pillar=pillar_key,
                      value_display=A.format_value(unit, values[""]),
                      comparison_display=comparison_for(""), footer=basis, tag=tag)]
    else:
        segs = [s for s in _SEGMENT_ORDER if s in values and (not subset or s in subset)]
        constant = set(own.get("constant_segments") or [])
        cards = []
        for seg in segs:
            if seg in constant:
                # A segment whose whole series is one value (SMB win rate is 100% by
                # construction) is a gap, not a headline over a flat line.
                cards.append(dict(label=f"{seg} · {own['period_label']}", dot_color=theme.SEGMENT_COLOR[seg],
                                  value_display="Not computable", value_size="sm", tag="Structural gap",
                                  footer=["The value is the same in every period; see the data note."] + basis))
            else:
                cards.append(dict(label=f"{seg} · {own['period_label']}", dot_color=theme.SEGMENT_COLOR[seg],
                                  value_display=A.format_value(unit, values[seg]),
                                  comparison_display=comparison_for(seg), footer=basis, tag=tag))
    if own.get("gap_note"):
        _note_box(own["gap_note"])
    theme.scorecard_row(cards)

    df = pd.DataFrame(own["result"]["data"])
    if subset and "segment" in df.columns:
        df = df[df["segment"].isin(subset)]
    chart_df = df
    if own.get("constant_segments") and "segment" in df.columns:
        chart_df = df[~df["segment"].isin(own["constant_segments"])]
    if own["key"] in _WINDOWED_KEYS and grain == "month" and "period" in chart_df.columns:
        keep = sorted(chart_df["period"].unique())[-_WINDOW_PERIODS:]
        chart_df = chart_df[chart_df["period"].isin(keep)]
    if "period" in chart_df.columns and chart_df["period"].nunique() > 1:
        st.plotly_chart(_figure(chart_df, own, pillar_color, grain), width="stretch",
                        key=f"chart_{idx}", config={"displayModeBar": False})
    with st.expander("Data"):
        shown = A.table_rows({"data": df.to_dict("records")}, unit, grain, own.get("partial_month"),
                             censored=own.get("censored_months"))
        st.dataframe(pd.DataFrame(shown), hide_index=True, width="stretch")


def _render_split_notice(parsed: dict, own: dict, idx: int) -> None:
    """A split the reader asked for that the registry has no dimension for: said plainly,
    with the nearest real node offered as a suggestion (never routed to silently)."""
    phrases = parsed.get("unsupported_splits") or []
    if not phrases:
        return
    st.info(theme.escape_md(A.split_notice(phrases, own.get("display_name") or own["name"])))
    for j, sug in enumerate(A.split_suggestions(phrases, METRICS, own["key"])):
        st.button(f"Ask instead: {sug['label']}", key=f"sug_{idx}_{j}", on_click=_queue_question,
                  args=(sug["question"],))


def _render_answer(ans: dict, idx: int) -> None:
    parsed = ans["parsed"]
    if ans["kind"] == "failed":
        st.info(theme.escape_md(ans["notice"]))
        return
    if ans["kind"] == "unresolved":
        # A routing miss is normal for free text, not a failure: neutral box.
        st.info("No exact match in the metric tree for that question.")
        if parsed["suggestions"]:
            st.markdown("**Closest registered names**")
            for s in parsed["suggestions"]:
                st.markdown(f"- {theme.escape_md(s)}")
        st.caption("Select a node in the metric tree to start from a registered name.")
        with st.expander("Query details"):
            st.json(parsed)
        return

    own = ans["own"]
    pillar_key = (own["pillar"] or "").lower()
    dot = theme.PILLAR_COLOR.get(pillar_key, theme.NEUTRAL_GRAY)
    under = f" · under {html.escape(own['parent_name'])}" if own["parent_name"] else ""
    theme.card_block(
        f'<span class="pillar-dot" style="background-color:{dot}"></span>'
        f'<strong>{html.escape(own["name"])}</strong>'
        f'<div class="breadcrumb">{html.escape(own["pillar"])} · Layer {own["layer"]}{under} · '
        f'{A.STATUS_GLYPH[own["status"]]} {A.STATUS_LABEL[own["status"]]}</div>'
    )
    if own.get("formula"):
        formula = A.join_formula(own["formula"], own.get("formula_note"))
        if len(formula) <= _FORMULA_INLINE_LIMIT:
            st.caption(theme.escape_md(f"Formula: {formula}"))
        else:
            st.caption("Formula: long definition, see the metric definition under Query details.")
    if parsed["secondary_metrics"]:
        names = ", ".join(METRICS[k]["name"] for k in parsed["secondary_metrics"])
        st.caption(theme.escape_md(f"Also named in the question: {names}. Ask about each separately."))

    filt = ", ".join(f"{k}={v}" for k, v in (parsed["filters"] or {}).items()) or "none"
    split = ", ".join(parsed["dimensions"]) if parsed["dimensions"] else "none"
    st.caption(theme.escape_md(f"Grain: {parsed['grain']} · Filter: {filt} · Split by: {split}"
                               + (" (default view)" if parsed.get("default_view_note") else "")))
    if parsed.get("default_view_note"):
        st.caption(theme.escape_md(parsed["default_view_note"]))
    _render_split_notice(parsed, own, idx)

    state = own["state"]
    if state == "rejected":
        tail_md = f" {theme.escape_md(own['message_tail'])}" if own.get("message_tail") else ""  # already escaped
        st.info(f"**{theme.escape_md(own['guardrail_label'])}.** {theme.escape_md(own['message'])}{tail_md}")
    elif state == "overlay":
        st.info(f"**Not queryable (non-additive overlay).** {theme.escape_md(own['message'])}")
    elif own.get("query_gap"):
        # The artifact exists and is validated; this interface cannot serve it (Section 7:
        # not the same case as an artifact that is missing). The registry paragraph is
        # shown once, here; each child row carries the short statement only.
        detail_md = f" {theme.escape_md(own['detail'])}" if own.get("detail") else ""
        st.info(f"**{theme.escape_md(own['message'])}**{detail_md}")
    elif state == "not_computable":
        st.info(f"**Not computable.** {theme.escape_md(own['message'])}")
    elif state == "degenerate":
        # Section 7, extended: a series with the same value in every period is a gap,
        # not a live headline. No number, no flat chart.
        st.info(f"**Not computable.** {theme.escape_md(own['message'])} No figure or trend is shown.")
    elif state == "all_null":
        # Section 7: lead with the gap, never an empty chart.
        st.info(f"**{theme.escape_md(own['message'])}**")
    elif state == "no_rows":
        st.info("Query returned no rows for this filter and date range.")
    else:
        _render_value_answer(own, parsed, idx)

    if ans["children"]:
        _children_table(own, ans["children"], parsed.get("segment_subset") or None)

    with st.expander("Query details"):
        st.caption("Routing: keyword match against the registry's whitelisted names, keys and aliases.")
        st.json(parsed)
        sql = own["result"].get("sql")
        if sql:
            st.code(sql, language="sql")
        if own["result"].get("metric"):
            st.caption("Registry definition")
            st.json(own["result"]["metric"])


@st.cache_data(ttl=300, show_spinner=False)
def _answer(question: str) -> dict:
    # Never raises: a failure comes back as kind "failed" with a plain-language notice.
    return sb.safe_answer_question(question, partial_month=data.final_month_in_marts())


def _render_exchange(question: str, idx: int) -> None:
    with st.chat_message("user"):
        st.write(theme.escape_md(question))
    with st.chat_message("assistant"):
        try:
            _render_answer(_answer(question), idx)
        except Exception:  # noqa: BLE001 - a render failure is a notice, never a traceback
            st.info(theme.escape_md(A.FAILED_NOTICE))


def _notes(history: list) -> list:
    """Page-level notes: standing scope notes, then each answered
    metric's data caveats (once per metric), all in the page's single
    Notes & assumptions expander."""
    stamp = sb.registry_stamp()
    notes = [
        ("Scope", "Routing is deterministic keyword matching against the registry's whitelisted "
                  "names, keys and aliases. No language model is called; model-based routing is a "
                  "deferred build step."),
        ("Scope", "Every value comes from the semantic layer over the finished data marts. A name outside "
                  "the metric tree is rejected."),
        ("Scope", "The metric tree is read from the semantic layer's metric registry "
                  f"(version {stamp['registry_version']}, generated from the metric tree document)."),
        ("Scope", "An answer about a metric with children includes one level of children, queried "
                  "with the same grain and segment filter. The tree panel opens further levels."),
        ("Scope", "Headline values are the last complete period in the result. The final month of the "
                  "data window is truncated: it is excluded from the headline, drawn as an open marker "
                  "and labeled partial in the data table."),
        ("Scope", "Values are single-month figures at the selected grain. The Digest shows some of the "
                  "same metrics as trailing-12-month figures, so the two pages can differ."),
        ("Scope", "NRR and GRR charts show the trailing 24 months. The earliest months have a "
                  "near-zero starting-MRR denominator, and their ratio spikes would flatten the "
                  "recent trend; the Data table keeps the full history."),
        ("Assumption", "Display units (USD, %, months, multiple) are assigned by the dashboard per "
                       "metric; the registry carries no unit field."),
    ]
    seen = set()
    for q in dict.fromkeys(history):
        ans = _answer(q)
        if ans["kind"] != "answer":
            continue
        own_ = ans["own"]
        for item in ([("Scope", f"{own_['display_name']}: {own_['censored_note']}")] if own_.get("censored_note") else []) \
                + ([("Scope", ans["parsed"]["default_view_note"])] if ans["parsed"].get("default_view_note") else []):
            if item not in notes:
                notes.append(item)
        entries = [(own_["name"], own_["warnings"])]
        entries += [(c["name"], c["warnings"]) for c in ans["children"]]
        for name, warnings in entries:
            for w in warnings:
                if (name, w) not in seen:
                    seen.add((name, w))
                    notes.append(("Data gap", f"{name}: {w}"))
    return notes


# =====================================================================
# Page body
# =====================================================================

title_col, clear_col = st.columns([5, 1], vertical_alignment="center")
with title_col:
    st.title("Ask the metric tree")
with clear_col:
    if st.session_state["ask_history"]:
        st.button("Clear conversation", on_click=_clear_history)
st.caption(
    "Answers come from the semantic layer, which answers only metrics listed in the metric tree. "
    "Routing is deterministic keyword matching, not a live language model."
)

typed = st.chat_input("Ask about a metric, for example: What is win rate for Enterprise?")
queued = st.session_state.pop("ask_queue", None)
new_question = queued or typed
if new_question:
    st.session_state["ask_history"].append(new_question)

history = st.session_state["ask_history"]
if not history:
    theme.card_block(
        '<strong>Start from the metric tree.</strong>'
        '<div class="breadcrumb">Select any node in the sidebar to ask about it, or type a '
        'question below. Answers about a metric with children include those children.</div>'
    )
else:
    earlier, latest = history[:-1], history[-1]
    if earlier:
        with st.expander(f"Earlier questions ({len(earlier)})"):
            for i, q in enumerate(earlier):
                _render_exchange(q, i)
    _render_exchange(latest, len(history) - 1)

theme.notes_and_assumptions(_notes(history))
