"""Streamlit rendering of the Digest's segment-mix block (pure rules live in
segment_mix_view.py). Segment colors come from the segment palette only (conventions
Section 2.4): the three bars are segment series, never a status."""
from typing import Dict, List

import plotly.graph_objects as go
import streamlit as st

import theme
from . import segment_mix_view as view

# Text on the lightest segment fill is navy; on the two darker fills it is white
# (WCAG AA, Section 2.5).
_LABEL_COLOR = {"SMB": theme.GROWTH_NAVY, "Commercial": "#FFFFFF", "Enterprise": "#FFFFFF"}


def stacked_share_figure(rows: List[Dict]) -> go.Figure:
    """A 100%-stacked horizontal bar of MRR share by segment (Section 3.1: composition of a
    small number of parts, compared across two periods). Earlier period on top, segments
    ordered SMB, Commercial, Enterprise, every bar labelled with its share."""
    fig = go.Figure()
    labels = [r["label"] for r in rows]
    for seg in view.SEGMENTS:
        shares = [r["shares"][seg] for r in rows]
        mrr = [[r["mrr"][seg] or "", r["labels"][seg]] for r in rows]
        fig.add_trace(go.Bar(
            y=labels, x=shares, name=seg, orientation="h",
            marker=dict(color=theme.SEGMENT_COLOR[seg]),
            text=[r["labels"][seg] for r in rows], textposition="inside", insidetextanchor="middle",
            textfont=dict(color=_LABEL_COLOR[seg], size=13),
            customdata=mrr,
            hovertemplate=f"{seg}: %{{customdata[1]}}<br>%{{customdata[0]}}<extra></extra>",
        ))
    fig.update_layout(**theme.plotly_layout(
        barmode="stack", height=60 + 56 * len(rows), hovermode="closest",
        margin=dict(l=10, r=24, t=36, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, traceorder="normal"),
    ))
    fig.update_xaxes(range=[0, 1], tickvals=[0, 0.2, 0.4, 0.6, 0.8, 1.0], tickformat=".0%", title_text="Share of company ending MRR (%)",
                     showgrid=False, tickfont=theme.PLOTLY_FONT)
    fig.update_yaxes(autorange="reversed", type="category", tickfont=theme.PLOTLY_FONT)
    return fig


def render(mix: Dict, key: str) -> Dict:
    """Render the block for a readout's segment_mix section. Returns the view state so the
    caller can add its notes to the page's Notes & assumptions."""
    s = view.state(mix)
    if s["kind"] == view.KIND_ABSENT:
        st.info("This readout carries no segment mix section.")
        return s
    if s["kind"] == view.KIND_UNAVAILABLE:
        st.info(theme.escape_md(s["reason_text"]))
        with st.expander("Why this is blank"):
            st.write(f"**Reason:** {theme.escape_md(s['reason_text'])}")
            if s.get("evaluation_month"):
                st.write(f"**Month considered:** {s['evaluation_month']}")
        return s
    if s.get("headline"):
        theme.card_block(
            f'<p style="margin:0 0 4px 0;font-size:1.1rem;font-weight:500;line-height:1.45;">'
            f'{theme.escape_html(s["headline"])}</p>'
            f'<div class="breadcrumb">{theme.escape_html(s["basis_line"])}'
            + (f' · Total ending MRR {theme.escape_html(s["total_ending_mrr"])}' if s.get("total_ending_mrr") else "")
            + '</div>'
        )
    if s["rows"]:
        st.plotly_chart(stacked_share_figure(s["rows"]), width="stretch", key=key,
                        config={"displayModeBar": False})
    if s["change_line"]:
        st.caption(s["change_line"])
    theme.scorecard_row(s["cards"])
    for line in s.get("mrr_vs_account_lines") or []:
        st.caption(theme.escape_md(line))
    return s
