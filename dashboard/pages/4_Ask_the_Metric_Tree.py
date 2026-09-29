"""Ask the metric tree -- a chat-style front end onto the Phase 3
semantic layer (semantic/server.py's list_metrics/get_metric_definition/
query_metric), called in-process via dashboard/lib/semantic_bridge.py.

Question routing here is deterministic keyword/substring matching against
the registry's own whitelisted names and aliases -- not an LLM call. The
natural extension point is routing through the Claude API per build spec
Section 3, the same deliberately deferred seam the weekly readout's
executive-summary narrative documents; this page demonstrates the
guardrails a live NL layer would sit on top of, honestly, rather than
faking the LLM half.

This is the ad hoc / exploratory audience tier (dashboard-design-
conventions.md Section 4.1) -- a free-text question box plus a metric
browser is the right shape here, and this page is explicitly exempt from
the exec/analyst density and inverted-pyramid rules in Sections 4-6.
What still applies, exactly as on every other page: Section 2 (color
meaning) and Section 3 (chart-type selection) for anything this page
renders as a chart or number, and Section 7's honesty patterns for the
routing mechanism itself (chat_live_llm_routing is a deferred seam, not
built -- this page must keep disclosing that its routing is deterministic,
never imply a live LLM is answering).
"""
import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

_DASHBOARD_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DASHBOARD_DIR)
import theme
from lib import semantic_bridge as sb

st.set_page_config(page_title="Ask the metric tree | Acme Corp GTM", page_icon="\U0001F4AC", layout="wide")
theme.inject_global_css()

st.title("Ask the metric tree")
st.caption(
    "Every answer here comes from query_metric() against the whitelisted metric "
    "registry -- the same guardrailed tool an MCP client (Claude Desktop, Claude Code) "
    "calls. A metric name outside the registry is rejected, not guessed at. Question "
    "routing below is deterministic keyword/substring matching, not a live LLM -- see "
    "“How this was routed.”"
)

all_metrics = sb.list_metrics()["metrics"]
queryable_names = sorted(
    m["name"] for m in all_metrics if m["computable"] and m["additive"]
)

# --- Segment order for chart traces: SMB -> Commercial -> Enterprise is
# the segment's own natural order (Section 3.2: sort by natural order when
# one exists, not alphabetically), and matches theme.SEGMENT_COLOR's key
# order (light -> dark slate).
_SEGMENT_ORDER = list(theme.SEGMENT_COLOR.keys())

# --- Axis-unit inference. The semantic registry (semantic/metric_registry.json)
# carries no explicit unit/format field per metric, so the y-axis unit
# label is inferred here from the metric's own key/name text, falling
# back to the returned value range for a ratio-shaped metric with no
# dollar/percent keyword. This is a page-local decision, not a rule from
# the skill file -- flagged in the build report as something the skill
# (or the registry itself) should formalize with a real `unit` field
# rather than leaving every consuming page to guess. ---
_DOLLAR_HINTS = (
    "revenue", "mrr", "arr", "cost", "cac", "commitment", "bookings",
    "pipeline", "amount", "acv", "tcv",
)
_PCT_HINTS = (
    "rate", "retention", "nrr", "grr", "efficiency", "pct", "percentage", "completion",
)
# Checked before the numeric-range percent fallback below: a ratio-shaped
# metric whose real values happen to fall in the same 0-1.5 range a
# fraction would (e.g. consumption_payback genuinely runs ~0.2-1.6
# months) gets mislabeled "%" by the fallback on numeric coincidence, not
# on any real signal -- found live during a render/inspect pass (a chart
# titled "Consumption payback" showed a "140%, 120%, 100%..." axis for a
# months-denominated metric). Named explicitly here rather than folded
# into the fallback, since this is a correction of a real wrong label,
# not a style preference.
_MONTHS_HINTS = ("payback",)


def _axis_meta(metric: dict, values: list) -> dict:
    """Returns a y-axis title plus an explicit tick format so the unit is
    never conveyed by the title text alone (Section 3.2: 'always label the
    y-axis with units' -- a '(%)' suffix in the title with raw 0-1 tick
    values would itself be a units bug, since the reader sees fractions
    but reads 'percent'). Dollar and percent ticks are self-labeling
    (tickformat/tickprefix); the generic fallback keeps the unit in the
    title text since there's no better signal available."""
    # Only the metric's own key/name are scanned for hints -- the formula
    # text is free prose (e.g. NRR's formula literally contains the word
    # "revenue" as part of "starting consumption revenue") and matching
    # against it produced a real false positive (NRR rendering with a "$"
    # axis) during this page's own render/inspect pass. Key/name alone is
    # a narrower, more reliable signal even though it still isn't a real
    # unit field.
    text = " ".join([metric.get("key") or "", metric.get("name") or ""]).lower()
    if any(h in text for h in _DOLLAR_HINTS):
        return {"title": metric["name"], "tickprefix": "$", "tickformat": "~s"}
    if any(h in text for h in _MONTHS_HINTS):
        return {"title": f"{metric['name']} (months)"}
    if any(h in text for h in _PCT_HINTS):
        return {"title": metric["name"], "tickformat": ".0%"}
    numeric = [v for v in values if v is not None and not pd.isna(v)]
    if numeric and max(abs(v) for v in numeric) <= 1.5:
        return {"title": metric["name"], "tickformat": ".0%"}
    return {"title": f"{metric['name']} (value)"}


def _apply_axis_meta(fig: go.Figure, axis_meta: dict) -> None:
    fig.update_yaxes(
        title_text=axis_meta["title"],
        tickformat=axis_meta.get("tickformat"),
        tickprefix=axis_meta.get("tickprefix"),
    )


def _line_figure(x, y, color, name, axis_meta, show_legend=False) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="lines+markers", name=name,
        line=dict(color=color, width=2.5),
        marker=dict(color=color, size=6),
    ))
    fig.update_layout(**theme.plotly_layout(
        xaxis_title="Period", showlegend=show_legend, height=380,
    ))
    theme.style_axes(fig)
    _apply_axis_meta(fig, axis_meta)
    return fig


def _segment_figure(df: pd.DataFrame, axis_meta: dict) -> go.Figure:
    fig = go.Figure()
    segments = [s for s in _SEGMENT_ORDER if s in df["segment"].unique()]
    segments += [s for s in df["segment"].unique() if s not in _SEGMENT_ORDER]
    for seg in segments:
        seg_df = df[df["segment"] == seg].sort_values("period")
        color = theme.SEGMENT_COLOR.get(seg, theme.NEUTRAL_GRAY)
        fig.add_trace(go.Scatter(
            x=seg_df["period"], y=seg_df["value"], mode="lines+markers", name=seg,
            line=dict(color=color, width=2.5),
            marker=dict(color=color, size=6),
        ))
    fig.update_layout(**theme.plotly_layout(
        xaxis_title="Period", showlegend=True, height=380,
    ))
    theme.style_axes(fig)
    _apply_axis_meta(fig, axis_meta)
    return fig


st.markdown("#### Ask a question")
example = "e.g. \"What was win rate for Enterprise last year?\" or \"Show me NRR by segment\""
question = st.text_input("Question", placeholder=example)

if question:
    parsed = sb.parse_question(question)
    with st.expander("How this was routed", expanded=False):
        st.caption(
            "Deterministic keyword/substring match against the registry's own "
            "whitelisted names -- never fuzzy, never an LLM call."
        )
        st.json(parsed)

    metric_key = parsed["resolved_metric"]
    if metric_key is None:
        # A routing miss is expected, normal behavior for free-text input,
        # not a failure -- kept visually neutral (st.info, not a warning/
        # error state) per Section 2.3: no judgment color belongs on a
        # component that isn't reporting a business result.
        st.info("No exact match in the whitelisted registry for that question.")
        if parsed["suggestions"]:
            st.markdown("**Closest registered names:**")
            for s in parsed["suggestions"]:
                st.markdown(f"- {s}")
        st.caption("Pick a metric from the browser below instead.")
    else:
        result = sb.query_metric(
            metric_key,
            dimensions=parsed["dimensions"],
            filters=parsed["filters"],
            grain=parsed["grain"],
        )
        if "error" in result:
            st.error(f"{result['error']}: {result['message']}")
        else:
            metric = result["metric"]
            # Layer label comes straight from the registry, which is
            # itself generated from docs/acme-corp-gtm-metric-tree.md --
            # correct by construction, not a hand-placed label that needs
            # separate verification the way a static page's layer tag
            # would. (Spot-checked here against the tree file for Win
            # Rate: Layer 2 under New Logo Revenue -- matches.)
            pillar_key = (metric.get("pillar") or "").lower()
            dot_color = theme.PILLAR_COLOR.get(pillar_key, theme.NEUTRAL_GRAY)
            # Reuses the same .theme-card-fill wrapper theme.scorecard()
            # uses (see theme.py's inject_global_css() docstring for why
            # this needs to be one single st.markdown call, not content
            # spread across several inside the container -- the
            # negative-margin fill trick only holds up for one atomic HTML
            # block; verified broken otherwise). No hex is hardcoded here
            # -- only the pillar dot, which is theme.PILLAR_COLOR itself.
            # Deliberately not a full scorecard (no headline number/delta):
            # this is a status/confirmation message, not a metric card.
            with st.container(border=True):
                st.markdown(
                    f'<div class="theme-card-fill">'
                    f'<span class="pillar-dot" style="background-color:{dot_color}"></span>'
                    f'Resolved to <strong>{metric["name"]}</strong> '
                    f'({metric["pillar"]}, Layer {metric["layer"]})'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            st.caption(f"{metric['formula']}{metric.get('formula_note') or ''}")

            # Section 7's "as-of-date / grain / filter state visible, not
            # hidden" honesty pattern, applied here: grain and any active
            # filter are shown in a plain info line rather than left only
            # inside the collapsed "How this was routed" JSON dump.
            filter_bits = ", ".join(f"{k}={v}" for k, v in (parsed["filters"] or {}).items())
            st.caption(
                f"Grain: {parsed['grain']}"
                + (f" · Filter: {filter_bits}" if filter_bits else " · Filter: none")
                + (" · Split by: segment" if "segment" in (parsed["dimensions"] or []) else "")
            )

            df = pd.DataFrame(result["data"])
            all_null = (not df.empty) and df["value"].isna().all()
            if df.empty:
                st.info("Query returned no rows for this filter/date range.")
            elif all_null:
                # Every row resolved but every value is NULL -- a genuine
                # structural gap (e.g. Magic Number: no rep-cost data
                # anywhere in the raw sources), not "no data yet." Lead
                # with the honest-gap message per Section 7, the same
                # pattern Digest and Segment Efficiency both already use
                # for this identical gap -- never plot an empty chart or a
                # table of blank rows first and explain afterward. The
                # real explanation is already in result["warnings"];
                # surfaced here instead of only after a confusing chart.
                st.info(f"**{metric['name']}** has no computable value for this query.")
                for w in result.get("warnings") or []:
                    st.caption(w)
            else:
                axis_meta = _axis_meta(metric, df["value"].tolist())
                if "segment" in df.columns and len(df["segment"].unique()) > 1:
                    # Section 3.1: a metric over time, one series -> line
                    # chart; split by segment -> one trace per segment,
                    # colored with theme.SEGMENT_COLOR explicitly so
                    # segment color stays consistent with every other
                    # page (never Plotly's default colorway, which would
                    # collide with Palette A/B meaning elsewhere).
                    fig = _segment_figure(df, axis_meta)
                else:
                    # Single series -> single line, colored with the
                    # resolved metric's own pillar color (Palette A
                    # category identity, not a status judgment) -- the
                    # same pillar accent already used on the confirmation
                    # banner above, applied consistently to the chart of
                    # that same metric.
                    chart_df = df.sort_values("period")
                    fig = _line_figure(
                        chart_df["period"], chart_df["value"], dot_color,
                        metric["name"], axis_meta,
                    )
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, hide_index=True, use_container_width=True)

            if not all_null:
                for w in result.get("warnings") or []:
                    st.warning(w)
            with st.expander("SQL executed"):
                st.code(result["sql"], language="sql")

st.divider()
st.markdown("#### Browse the whitelist")
picked = st.selectbox("Metric", ["--"] + queryable_names)
if picked != "--":
    definition = sb.get_metric_definition(picked)["metric"]
    st.write(definition)
