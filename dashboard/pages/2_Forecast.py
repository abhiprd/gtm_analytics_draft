"""Forecast -- calls analytics/forecast.py's run_forecast() directly (the
Wave 2 artifact: bottoms-up rep/manager, ML, and CRO-overlay lenses
reconciled per segment for the current quarter). No forecast math lives
in this page; it renders exactly what the artifact returns, with
log=False baked into run_forecast() so viewing the dashboard never writes
to fact_model_performance_history.

Audience: primarily analyst / functional-owner (RevOps, sales leadership
diagnosing *why* the four lenses disagree per segment) -- Section 4.2's
density/table allowances apply, and the four-lens detail stays visible by
default rather than behind a click. But every segment still leads with a
one-glance verdict (the CRO-adjusted headline + a divergence badge) before
the diagnostic detail, since a CRO glancing at this page for 30 seconds
needs that first. This split (analyst density, exec-style verdict lead-in)
isn't one of the skill's three named tiers -- flagged in the build report
as a new decision for the skill file.
"""
import os
import sys
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

_DASHBOARD_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_DASHBOARD_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, _DASHBOARD_DIR)
from analytics import forecast as fc
import theme
from lib.formatting import pct, usd

st.set_page_config(page_title="Forecast | Acme Corp GTM", page_icon="\U0001F4C8", layout="wide")
theme.inject_global_css()

LENS_LABELS = {
    "bottoms_up_rep": "Bottoms-up (rep)",
    "bottoms_up_manager": "Bottoms-up (manager)",
    "ml": "ML",
    "cro_adjusted": "CRO-adjusted",
}

st.title("Forecast")
st.caption(
    "Commercial and Enterprise only -- SMB's no-touch, 0-7-day motion has no weekly "
    "forecast cadence to snapshot. Four lenses: bottoms-up rep, bottoms-up manager, ML, "
    "and the CRO overlay, reconciled side by side per segment with a divergence flag."
)

default_date = date(2025, 11, 14)
as_of_date = st.date_input(
    "As-of date", value=default_date, min_value=date(2023, 6, 1), max_value=date(2025, 12, 20),
    help="Marketing spend (used in Consumption Payback elsewhere) starts 2023-01; forecast "
         "submissions run through 2025-12-26.",
)


@st.cache_data(ttl=600, show_spinner="Training the win-probability model and reconciling lenses...")
def _run(as_of_date: date) -> dict:
    result = fc.run_forecast(as_of_date)
    reconciliation = result["reconciliation"].copy()
    model = result["model"]
    return {
        "period": result["period"],
        "reconciliation": reconciliation,
        "model_computable": model.get("computable"),
        "auc_holdout": model.get("auc_holdout"),
        "meets_auc_target": model.get("meets_auc_target"),
        "n_train": model.get("n_train"),
        "n_test": model.get("n_test"),
        "data_window_note": result["data_window"]["note"],
    }


result = _run(as_of_date)
recon = result["reconciliation"]

# --- Section 7 honesty pattern: as-of-date, grain, and the threshold that
# governs the divergence badge below, all visible up front, never hidden
# in a settings panel. Grain is quarterly by construction (every dollar
# here traces to fact_opportunities/fact_forecast_submissions rolled to a
# fiscal-quarter forecast call) -- no weekly toggle is offered, per
# Section 8: there is nothing at a finer grain to toggle to on this page.
info1, info2, info3 = st.columns(3)
info1.metric("As-of date", as_of_date.isoformat())
info2.metric("Forecast period", result["period"])
info3.metric("Grain", "Quarterly")
st.caption(
    f"Divergence badge trips when the widest lens spread exceeds "
    f"{fc._DIVERGENCE_THRESHOLD:.0%} of the mean of the computable lenses."
)

st.divider()

if recon.empty:
    st.warning("No reconciliation rows returned for this as-of date.")
    st.stop()

for _, row in recon.iterrows():
    segment = row["segment"]
    seg_color = theme.SEGMENT_COLOR.get(segment, theme.NEUTRAL_GRAY)

    # A plain (unbordered) grouping container, not a second nested card --
    # the segment's real "card" is the theme.scorecard() headline below,
    # which already gets a clean white fill. Stacking a second border
    # around chart + columns + scorecard produced a broken, two-tone seam
    # (the negative-margin fill trick that works for a single homogeneous
    # scorecard div doesn't hold up across heterogeneous Streamlit widgets
    # like a Plotly chart with its own internal margins -- verified live,
    # visible gap at the border edges). Segments are separated by
    # whitespace/a divider instead, per Section 5.2's own preference for
    # whitespace over borders between unrelated sections.
    with st.container():
        st.markdown(
            f'<span class="pillar-dot" style="background-color:{seg_color}"></span>'
            f'<span style="font-family:{theme.FONT_HEADER};font-size:1.3rem;font-weight:700;">'
            f'{segment}</span>',
            unsafe_allow_html=True,
        )

        head_col, badge_col = st.columns([2, 1])
        with head_col:
            reason_display = (
                str(row["cro_reason"]).replace("_", " ") if row["has_logged_cro_adjustment"] else None
            )
            comparison = (
                f"CRO override {usd(row['cro_adjustment_amount'])} filed -- {reason_display}"
                if row["has_logged_cro_adjustment"]
                else "No CRO override filed this quarter"
            )
            theme.scorecard(
                label="Reconciled headline (CRO-adjusted)",
                value_display=usd(row["cro_adjusted"]),
                pillar="growth",
                comparison_display=comparison,
                # No plan/benchmark figure exists for this lens in the
                # underlying reconciliation -- shown without a fabricated
                # delta rather than implying a favorable/unfavorable call
                # that isn't grounded in a comparison point (Section 7).
                favorable_direction=None,
                is_ahead=None,
            )
        with badge_col:
            diverges = bool(row["diverges_materially"])
            badge_color = theme.CAUTION_AMBER if diverges else theme.NEUTRAL_GRAY
            badge_symbol = "⚠" if diverges else "●"
            badge_text = "Lenses diverge materially" if diverges else "Lenses agree"
            widest_pair_display = " vs ".join(
                LENS_LABELS.get(p, p) for p in str(row["widest_pair"]).split(" vs ")
            )
            st.markdown(
                # Text color is fixed navy, not badge_color, deliberately:
                # badge_color-on-its-own-tint (the original treatment)
                # measured 2.27:1 (amber) / 4.16:1 (gray) contrast, both
                # under Section 2.5's 4.5:1 body-text floor -- found live
                # via a contrast check. badge_color now drives only the
                # border and glyph (still a real color+shape signal per
                # 2.5), with navy-on-light-tint carrying the text.
                f'<div style="margin-top:28px;">'
                f'<span style="background:{badge_color}1f;color:{theme.GROWTH_NAVY};'
                f'border:1px solid {badge_color};border-radius:14px;padding:4px 12px;'
                f'font-weight:600;font-size:0.85rem;display:inline-block;">'
                f'<span style="color:{badge_color};">{badge_symbol}</span> {badge_text}</span>'
                f'<div style="color:{theme.NEUTRAL_GRAY};font-size:0.85rem;margin-top:6px;">'
                f'Spread {pct(row["lens_spread_pct"])} across {int(row["lenses_computable"])} '
                f'computable lens(es), widest pair: {widest_pair_display}'
                f'</div></div>',
                unsafe_allow_html=True,
            )

        # Four-lens comparison. Per Section 3.1's matrix -- "comparing a
        # small number of categories at one point in time" -- the
        # prescribed chart is a horizontal bar chart sorted by value, not
        # a row of bare scorecards: it lets the reader rank and compare
        # magnitude at a glance, which four separately-styled st.metric
        # cards (the page's previous treatment) require the reader to do
        # mentally. All bars in a segment's chart share that segment's
        # SEGMENT_COLOR -- never a distinct hue per lens, which would
        # invent a fourth, undefined color meaning on top of Palette A/B.
        lens_rows = []
        for col in ("bottoms_up_rep", "bottoms_up_manager", "ml", "cro_adjusted"):
            val = row[col]
            if col == "ml" and not row["ml_computable"]:
                continue
            if pd.isna(val):
                continue
            lens_rows.append((LENS_LABELS[col], float(val)))
        lens_rows.sort(key=lambda t: t[1])  # ascending -> largest bar plots at top

        if lens_rows:
            labels = [t[0] for t in lens_rows]
            values = [t[1] for t in lens_rows]
            fig = go.Figure(
                go.Bar(
                    x=values, y=labels, orientation="h",
                    marker_color=seg_color,
                    text=[usd(v) for v in values],
                    textposition="outside",
                    cliponaxis=False,
                )
            )
            fig.update_layout(
                **theme.plotly_layout(
                    height=210,
                    showlegend=False,
                    xaxis_title="Forecasted amount (USD)",
                    margin=dict(l=10, r=40, t=20, b=30),
                )
            )
            fig.update_xaxes(tickprefix="$", tickformat=".2s")
            theme.style_axes(fig)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        if not row["ml_computable"]:
            st.caption(
                "ML lens: N/A for this as-of date -- insufficient closed-deal history to "
                "fit the classifier yet. Not fabricated, not interpolated; the other three "
                "lenses carry the read until enough history accumulates."
            )

        st.caption(
            f"{int(row['open_deals'])} open deals, {usd(row['open_pipeline_amount'])} open "
            f"pipeline."
        )
    st.divider()

# --- ML lens quality: Layer-2/3-ish diagnostic detail, appropriate for
# this analyst page but kept behind an expander so it doesn't crowd the
# per-segment verdict above (item 4 of the rewrite brief).
with st.expander("ML lens quality (model diagnostics)"):
    if result["model_computable"]:
        met = result["meets_auc_target"]
        auc_color = theme.status_color("higher", met)
        auc_arrow = theme.status_arrow(met)
        st.markdown(
            f'Out-of-time holdout AUC '
            f'<span style="color:{auc_color};font-weight:700;">'
            f'{result["auc_holdout"]:.3f} {auc_arrow}</span> '
            f'({"meets" if met else "below"} target 0.70-0.85), trained on '
            f'{result["n_train"]} snapshots, held out {result["n_test"]}.',
            unsafe_allow_html=True,
        )
        st.caption(
            "The classifier deliberately excludes the manager's own forecast category from "
            "its features (see docs/acme-corp-analytics-methods.md) -- it reads deal "
            "mechanics only, so a disagreement with the bottoms-up lenses is a statement "
            "about deal mechanics contradicting human judgement, not a rounding artifact."
        )
    else:
        st.info("ML lens not computable for this as-of date (insufficient training data).")

with st.expander("Data window note"):
    st.caption(result["data_window_note"])
