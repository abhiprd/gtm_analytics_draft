"""Shared rendering of one segment's forecast read, used by both the Digest
(from the weekly readout JSON's forecast section) and the Forecast page
(from analytics/forecast.py's reconciliation row), so the two pages show the
same figures in the same form for the same forecast call.

Takes a plain dict row with the reconciliation columns. When the row carries
the readout's pre-formatted `*_display` strings they are used verbatim;
otherwise the same formatting rule the readout uses is applied
(analytics/weekly_readout.py `_fmt_usd`: $x.xxM, $x.xK, $x). No forecast
arithmetic happens here.
"""
import math
from typing import Dict, List, Optional, Tuple

import plotly.graph_objects as go
import streamlit as st

import theme
from . import forecast_logic

LENS_ORDER = ("bottoms_up_rep", "bottoms_up_manager", "ml", "cro_adjusted")


fmt_usd = forecast_logic.fmt_usd


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


_FIELD_ALIAS = {"open_pipeline": "open_pipeline_amount"}


def display(row: dict, field: str) -> str:
    shown = row.get(f"{field}_display")
    if shown:
        return shown
    v = row.get(_FIELD_ALIAS.get(field, field))
    return "n/a" if _missing(v) else fmt_usd(float(v))


def lens_rows(row: dict, lens_labels: Dict[str, str]) -> List[Tuple[str, float, str]]:
    """(label, value, display) for each computable lens, ascending by value
    so the largest bar plots at the top of a horizontal bar chart."""
    out = []
    for lens in LENS_ORDER:
        if lens == "ml" and not row.get("ml_computable", True):
            continue
        v = row.get(lens)
        if _missing(v):
            continue
        out.append((lens_labels[lens], float(v), display(row, lens)))
    out.sort(key=lambda t: t[1])
    return out


def headline_comparison(row: dict) -> str:
    shown = row.get("cro_display")
    if shown:
        return shown[0].upper() + shown[1:]
    if row.get("has_logged_cro_adjustment"):
        amount = row["cro_adjustment_amount"]
        signed = f"-{fmt_usd(abs(amount))}" if amount < 0 else f"+{fmt_usd(amount)}"
        reason = str(row["cro_reason"]).replace("_", " ")
        return f"CRO override {signed} filed ({reason})"
    return "No CRO override filed"


def widest_pair_text(row: dict, lens_labels: Dict[str, str]) -> str:
    shown = row.get("widest_pair_display")
    if shown:
        return shown
    return " vs ".join(lens_labels.get(p, p) for p in str(row["widest_pair"]).split(" vs "))


def spread_text(row: dict) -> str:
    shown = row.get("lens_spread_display")
    return shown if shown else f"{float(row['lens_spread_pct']) * 100:.1f}%"


def render_segment(row: dict, lens_labels: Dict[str, str], key: str,
                   divergence_threshold_text: Optional[str] = None,
                   days_left: Optional[int] = None) -> None:
    """One segment: heading, a card row (headline CRO-adjusted lens, open pipeline,
    lens agreement), then the four lenses as a sorted horizontal bar chart in the
    segment's palette color (Section 3.1: a small number of categories at one point
    in time, largest at the top). No plan figure exists at this grain, so the
    headline carries the CRO override as its comparison and no favorable/unfavorable
    color. When the headline lens exceeds the open pipeline it prices (late in a
    quarter) the card says so."""
    segment = row["segment"]
    seg_color = theme.SEGMENT_COLOR.get(segment, theme.NEUTRAL_GRAY)
    st.markdown(
        f'<span class="pillar-dot" style="background-color:{seg_color}"></span>'
        f'<span style="font-family:{theme.FONT_HEADER};font-size:1.3rem;font-weight:700;">'
        f'{segment}</span>',
        unsafe_allow_html=True,
    )
    diverges = bool(row["diverges_materially"])
    badge_color = theme.CAUTION_AMBER if diverges else theme.NEUTRAL_GRAY
    badge_symbol = "⚠" if diverges else "●"
    badge_text = "Diverge materially" if diverges else "Lenses agree"
    note = forecast_logic.late_quarter_note(row, days_left)
    headline = dict(
        label="Headline forecast (CRO-adjusted)", value_display=display(row, "cro_adjusted"),
        pillar="growth", comparison_display=headline_comparison(row),
        footer=[note] if note else None,
        tag="Exceeds open pipeline" if note else None,
    )
    pipeline = dict(
        label="Open pipeline", value_display=display(row, "open_pipeline"), pillar="growth",
        footer=[f"{int(row['open_deals'])} open deals"],
    )
    # Text stays navy; the badge color drives the glyph only (amber text on its own
    # tint measured below the 4.5:1 floor, 2.5).
    divergence_footer = [
        f"Spread {spread_text(row)} across {int(row['lenses_computable'])} computable lenses.",
        f"Widest pair: {widest_pair_text(row, lens_labels)}",
    ]
    if divergence_threshold_text:
        divergence_footer.append(divergence_threshold_text)
    agreement = dict(
        label="Lens agreement",
        value_display=f'<span style="color:{badge_color}">{badge_symbol}</span> {badge_text}',
        value_size="sm", pillar="growth", footer=divergence_footer,
    )
    theme.scorecard_row([headline, pipeline, agreement])

    rows = lens_rows(row, lens_labels)
    if rows:
        fig = go.Figure(go.Bar(
            x=[r[1] for r in rows], y=[r[0] for r in rows], orientation="h",
            marker_color=seg_color, text=[r[2] for r in rows],
            textposition="outside", cliponaxis=False,
        ))
        fig.update_layout(**theme.plotly_layout(
            height=210, showlegend=False, xaxis_title="Forecasted closed-won amount (USD)",
            margin=dict(l=10, r=40, t=20, b=30),
        ))
        fig.update_xaxes(tickprefix="$", tickformat=".2s")
        theme.style_axes(fig)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key=key)

    if not row.get("ml_computable", True):
        st.caption("ML lens: not computable for this call date (insufficient closed-deal history to "
                   "fit the classifier). The other three lenses are shown.")
