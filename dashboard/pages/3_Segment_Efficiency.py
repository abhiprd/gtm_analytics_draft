"""Segment efficiency -- Growth, Efficiency, and Durability by segment
(SMB / Commercial / Enterprise), read straight from mart_growth_bridge,
mart_efficiency, mart_durability, and mart_segment_migration. A metric
with no defined value for a segment/month (AM Efficiency for SMB, which has
no AM; Magic Number before a prior-period S&M cost exists) is shown as a
gap, never backfilled with a fabricated number.

Audience: functional owner / analyst (dashboard-design-conventions.md
Section 4.1's own named example for this page). Layer-2/3 detail is
visible by default, density is a feature, segment-identity color can
dominate over status color since this page mostly answers "what's
different across segments," not "good or bad" -- see Section 4.2's table.
"""
import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import theme
from lib import data
from lib.formatting import num, pct, usd

st.set_page_config(page_title="Segment efficiency | Acme Corp GTM", page_icon="🧭", layout="wide")
theme.inject_global_css()

st.title("Segment efficiency")
st.caption(
    "Segment is what an account IS (SMB / Commercial / Enterprise); it never implies how "
    "the account was acquired. All three pillars below are segment x month grain."
)

# ---------------------------------------------------------------------------
# Favorable-direction map -- UI display metadata only, not a metric
# redefinition (the metric tree in docs/acme-corp-gtm-metric-tree.md owns the
# formula). Scoped deliberately to the metrics with an unambiguous,
# context-free favorable direction: win rate / NRR / GRR / logo retention
# (higher is favorable) and consumption payback (lower is favorable -- fewer
# months to pay back CAC is better). Dollar magnitudes on this page (Ending
# MRR, New logo MRR, Avg initial commitment) and the onboarding/CS efficiency
# ratio are deliberately left OUT of this map and rendered in neutral/segment
# color instead -- see the report for why.
FAVORABLE_DIRECTION = {
    "win_rate": "higher",
    "nrr": "higher",
    "grr": "higher",
    "logo_retention_rate": "higher",
    "consumption_payback_months": "lower",
}

# Layer labels -- checked directly against docs/acme-corp-gtm-metric-tree.md
# and cross-verified against analytics/variance_diagnostic.py's own
# registered tree (the one place layer numbers are mechanically enforced:
# every _child() node's layer is exactly parent.layer + 1). New logo
# consumption revenue, Magic number, Consumption payback, Onboarding/CS
# efficiency, AM efficiency, NRR, GRR and Logo retention are all Layer 1
# (direct children of a pillar). Win rate and Avg initial commitment are
# Layer 2, children of New logo consumption revenue -- this is the exact bug
# class CLAUDE.md documents (Win Rate previously mislabeled as Layer 1).
# "Ending MRR" is the growth-bridge TOTAL (starting + new - contraction -
# churn + expansion +/- migration), not itself a single tree node, so it is
# deliberately given no layer badge rather than a guessed one.
LAYER_LABEL = {
    "new_logo_mrr": "Layer 1 -- New logo consumption revenue",
    "win_rate": "Layer 2 -- New logo consumption revenue → Win rate",
    "avg_initial_commitment": "Layer 2 -- New logo consumption revenue → Avg initial commitment",
    "consumption_payback_months": "Layer 1 -- Efficiency",
    "onboarding_cs_efficiency_ratio": "Layer 1 -- Efficiency",
    "magic_number": "Layer 1 -- Efficiency",
    "am_efficiency": "Layer 1 -- Efficiency",
    "nrr": "Layer 1 -- Durability",
    "grr": "Layer 1 -- Durability",
    "logo_retention_rate": "Layer 1 -- Durability",
}

SEGMENT_ORDER = list(data.SEGMENTS)  # SMB, Commercial, Enterprise -- natural order, never alphabetical-sorted

efficiency = data.mart_efficiency()
durability = data.mart_durability()
growth = data.mart_growth_bridge()
migration = data.mart_segment_migration()

# ---------------------------------------------------------------------------
# Controls -- segment + snapshot month are this page's full filter set
# (Section 4.2: analyst pages get the full filter set). No grain toggle:
# every metric here (dollar/ARR figures, NRR/GRR, consumption payback,
# onboarding/CS efficiency) is monthly-only per Section 8's constraint
# table -- there is no finer grain in the underlying data to toggle to.
filter_col, info_col = st.columns([2, 1])
with filter_col:
    segments = st.multiselect("Segments", SEGMENT_ORDER, default=SEGMENT_ORDER)

    all_months = sorted(growth["month"].unique())
    # Default one month behind the mart's own literal max: the same
    # trailing-safe convention analytics/weekly_readout.py uses
    # (data_window.evaluation_month vs. last_month_in_marts) -- the newest
    # month in a fact/mart table can still be an in-flight, partially-closed
    # period (e.g. December's win rate here reflects the deals that had
    # closed as of the data snapshot, not a full month of closing activity).
    default_month = all_months[-2] if len(all_months) > 1 else all_months[-1]
    snapshot_month = st.selectbox(
        "Snapshot month", all_months, index=all_months.index(default_month),
        format_func=lambda m: pd.Timestamp(m).strftime("%Y-%m"),
        help="Defaults one month behind the mart's newest month, since the newest month can "
             "still be in-flight (not yet a full month of closing activity).",
    )
with info_col:
    st.caption(
        f"**Grain:** Monthly (segment × month) -- no toggle offered; every metric on this "
        f"page is monthly-only at the generator level (Section 8).\n\n"
        f"**Snapshot:** {pd.Timestamp(snapshot_month).strftime('%Y-%m')}"
    )

if not segments:
    st.info("Select at least one segment to see the pillars below.")
    st.stop()

ordered_segments = [s for s in SEGMENT_ORDER if s in segments]

tab_growth, tab_efficiency, tab_durability, tab_migration = st.tabs(
    ["Growth", "Efficiency", "Durability", "Segment migration"]
)


# ---------------------------------------------------------------------------
# Shared helpers

def prior_month_row(df: pd.DataFrame, seg: str, month, months_sorted: list) -> pd.Series | None:
    """The immediately preceding month IN THE MART's own sorted month list
    for this segment -- a genuine trailing comparison already present in
    already-loaded data, never a fabricated one. Returns None if this is the
    first month in the window or the segment has no row for it."""
    idx = months_sorted.index(month)
    if idx == 0:
        return None
    prior_month = months_sorted[idx - 1]
    row = df[(df["segment"] == seg) & (df["month"] == prior_month)]
    return None if row.empty else row.iloc[0]


def metric_card(label: str, col_key: str, value, prior_value, pillar: str, value_fmt,
                 layer_note: str | None = None, gap_note: str | None = None) -> None:
    """One scorecard for one metric, one segment. Colored favorable/
    unfavorable ONLY for metrics in FAVORABLE_DIRECTION, using a real
    trailing-month comparison; every other metric still shows its real MoM
    move, just in neutral gray with no arrow (Section 7 -- never a bare
    number when a real comparison exists, never a fabricated judgment when
    it doesn't)."""
    direction = FAVORABLE_DIRECTION.get(col_key)
    if gap_note:
        theme.scorecard(label, "Not computable", pillar=pillar, comparison_display=gap_note)
    elif value is None or (isinstance(value, float) and pd.isna(value)):
        theme.scorecard(label, "N/A", pillar=pillar)
    else:
        comparison_display = None
        variance_display = None
        is_ahead = None
        if prior_value is not None and not pd.isna(prior_value):
            delta = value - prior_value
            if direction is not None:
                is_ahead = delta >= 0 if direction == "higher" else delta <= 0
            comparison_display = f"vs {value_fmt(prior_value)} last month"
            sign = "+" if delta >= 0 else ""
            variance_display = f"{sign}{value_fmt(delta)}"
        theme.scorecard(
            label, value_fmt(value), pillar=pillar,
            comparison_display=comparison_display, variance_display=variance_display,
            favorable_direction=direction, is_ahead=is_ahead,
        )
    if layer_note:
        st.caption(layer_note)


TREND_WINDOW_MONTHS = 24


def segment_line_chart(df: pd.DataFrame, value_col: str, y_title: str, y_is_pct: bool = False,
                        window: bool = False) -> go.Figure:
    """Full company history by default. `window=True` (only NRR/GRR-shaped
    ratio metrics should pass this) restricts to the trailing
    TREND_WINDOW_MONTHS months instead: the company's earliest live months
    carry a near-zero starting-MRR denominator that produces extreme
    NRR/GRR ratio spikes (documented in docs/acme-corp-analytics-methods.md's
    NRR/GRR plan-comparability note), which would otherwise dominate the
    y-axis scale and make the decision-relevant recent trend illegible.
    This windows the TIME AXIS, never the Y-axis -- Section 3.2's "never
    truncate a y-axis to exaggerate a trend" rule is about compressing the
    value scale to dramatize a move, which this does not do; every point
    actually shown keeps its true, untruncated value. Not applied by
    default to every chart: a dollar figure (Ending MRR) or a months
    figure (Consumption payback) has no equivalent near-zero-denominator
    artifact, so windowing them without a specific documented reason would
    just be hiding real history for no reason -- found as a real issue in
    review (the window was being applied uniformly by this shared
    function regardless of whether the metric actually needed it)."""
    if window:
        months_in_window = sorted(df["month"].unique())[-TREND_WINDOW_MONTHS:]
        df = df[df["month"].isin(months_in_window)]
    fig = go.Figure()
    for seg in ordered_segments:
        sdf = df[df["segment"] == seg].sort_values("month")
        fig.add_trace(go.Scatter(
            x=sdf["month"], y=sdf[value_col], mode="lines+markers", name=seg,
            line=dict(color=theme.SEGMENT_COLOR[seg], width=2.5), marker=dict(size=5),
        ))
    fig.update_layout(**theme.plotly_layout(height=320))
    theme.style_axes(fig)
    fig.update_yaxes(title_text=y_title, tickformat=".0%" if y_is_pct else None)
    fig.update_xaxes(title_text="Month")
    return fig


def segment_bar_chart(latest_df: pd.DataFrame, value_col: str, x_title: str, value_fmt,
                       ascending: bool = False, tickprefix: str = None,
                       tickformat: str = None) -> go.Figure:
    """`tickprefix`/`tickformat` make the axis self-labeling (Section 3.2
    -- e.g. "$"/"~s" for dollars, ".0%" for a ratio), matching whatever
    unit `value_fmt` already applies to each bar's outside text label, so
    the axis and the bar labels never disagree on units (found live as a
    real bug: NRR's bars read "102.0%" while the axis showed a bare 0-1
    scale with no percent sign)."""
    d = latest_df[["segment", value_col]].dropna()
    d = d[d["segment"].isin(ordered_segments)].sort_values(value_col, ascending=ascending)
    fig = go.Figure(go.Bar(
        x=d[value_col], y=d["segment"], orientation="h",
        marker_color=[theme.SEGMENT_COLOR[s] for s in d["segment"]],
        text=[value_fmt(v) for v in d[value_col]], textposition="outside",
    ))
    fig.update_layout(**theme.plotly_layout(height=190, showlegend=False))
    theme.style_axes(fig)
    fig.update_xaxes(title_text=x_title, tickprefix=tickprefix, tickformat=tickformat)
    fig.update_yaxes(title_text="")
    return fig


# ---------------------------------------------------------------------------
with tab_growth:
    st.markdown(
        f'<span class="pillar-dot" style="background-color:{theme.PILLAR_COLOR["growth"]}"></span>'
        "**New logo consumption revenue, by segment**",
        unsafe_allow_html=True,
    )
    g = growth[growth["segment"].isin(segments)].copy()
    g_months = sorted(g["month"].unique())
    latest = g[g["month"] == snapshot_month]

    cols = st.columns(len(ordered_segments))
    for col, seg in zip(cols, ordered_segments):
        row_df = latest[latest["segment"] == seg]
        with col:
            st.markdown(f"**{seg}**")
            if row_df.empty:
                st.info("No data for this segment/month.")
                continue
            row = row_df.iloc[0]
            prior = prior_month_row(g, seg, snapshot_month, g_months)
            metric_card("Ending MRR (bridge total)", "ending_mrr", row["ending_mrr"],
                        prior["ending_mrr"] if prior is not None else None, "growth", usd)
            metric_card("New logo MRR", "new_logo_mrr", row["new_logo_mrr"],
                        prior["new_logo_mrr"] if prior is not None else None, "growth", usd,
                        layer_note=LAYER_LABEL["new_logo_mrr"])
            metric_card("Win rate", "win_rate", row["win_rate"],
                        prior["win_rate"] if prior is not None else None, "growth", pct,
                        layer_note=LAYER_LABEL["win_rate"])
            metric_card("Avg initial commitment", "avg_initial_commitment", row["avg_initial_commitment"],
                        prior["avg_initial_commitment"] if prior is not None else None, "growth", usd,
                        layer_note=LAYER_LABEL["avg_initial_commitment"])

    st.caption(
        "Win rate is colored for favorable/unfavorable direction (higher = favorable) against "
        "last month, same segment -- a real trailing comparison already present in this mart, "
        "not a plan figure. Ending MRR, New logo MRR and Avg initial commitment show the same "
        "real month-over-month move in neutral gray: this page has no plan/benchmark loaded for "
        "these dollar figures, so no favorable/unfavorable color is asserted (Section 7)."
    )

    st.markdown("**New logo MRR by segment -- snapshot**")
    st.plotly_chart(
        segment_bar_chart(latest, "new_logo_mrr", "New logo MRR ($)", usd, tickprefix="$", tickformat="~s"),
        use_container_width=True,
    )

    st.markdown("**Ending MRR over time** (full history)")
    st.plotly_chart(segment_line_chart(g, "ending_mrr", "Ending MRR ($)"), use_container_width=True)

# ---------------------------------------------------------------------------
with tab_efficiency:
    st.markdown(
        f'<span class="pillar-dot" style="background-color:{theme.PILLAR_COLOR["efficiency"]}"></span>'
        "**Is the touch model paying for itself, by segment**",
        unsafe_allow_html=True,
    )
    e = efficiency[efficiency["segment"].isin(segments)].copy()
    e_months = sorted(e["month"].unique())
    latest = e[e["month"] == snapshot_month]

    cols = st.columns(len(ordered_segments))
    for col, seg in zip(cols, ordered_segments):
        row_df = latest[latest["segment"] == seg]
        with col:
            st.markdown(f"**{seg}**")
            if row_df.empty:
                st.info("No data for this segment/month.")
                continue
            row = row_df.iloc[0]
            prior = prior_month_row(e, seg, snapshot_month, e_months)
            metric_card("Consumption payback (months)", "consumption_payback_months",
                        row["consumption_payback_months"],
                        prior["consumption_payback_months"] if prior is not None else None,
                        "efficiency", lambda v: num(v, 1), layer_note=LAYER_LABEL["consumption_payback_months"])

            ratio = row["onboarding_cs_efficiency_ratio"]
            prior_ratio = prior["onboarding_cs_efficiency_ratio"] if prior is not None else None
            metric_card(
                "AM touches per 1M Actions delivered", "onboarding_cs_efficiency_ratio_display",
                None if pd.isna(ratio) else ratio * 1_000_000,
                None if prior_ratio is None or pd.isna(prior_ratio) else prior_ratio * 1_000_000,
                "efficiency", lambda v: num(v, 2), layer_note=LAYER_LABEL["onboarding_cs_efficiency_ratio"],
            )

            metric_card("Magic Number", "magic_number", row["magic_number"], None, "efficiency",
                        lambda v: num(v, 2), layer_note=LAYER_LABEL["magic_number"],
                        gap_note="No prior-period S&M cost" if pd.isna(row["magic_number"]) else None)
            metric_card("AM Efficiency", "am_efficiency", row["am_efficiency"], None, "efficiency",
                        lambda v: num(v, 2), layer_note=LAYER_LABEL["am_efficiency"],
                        gap_note=("No AM (SMB is no-touch)" if seg == "SMB" else "No AM cost yet")
                        if pd.isna(row["am_efficiency"]) else None)

    st.caption(
        "Consumption payback is colored for favorable/unfavorable direction (fewer months = "
        "favorable) against last month, same segment. AM touches per 1M Actions delivered shows "
        "the same real month-over-month move in neutral gray -- it does have a tree-defined "
        "favorable direction (lower is more efficient), but is left uncolored here since this "
        "page's comparison is a trailing month, not the plan baseline the tree's own engine "
        "diffs against; see the report for this call."
    )
    st.caption(
        "Magic Number is net new ARR over the prior month's S&M cost (rep fully-loaded cost "
        "including ramp, plus marketing spend); AM Efficiency is monthly expansion MRR over "
        "AM cost. Both are single-month ratios, so they are seasonal and can go negative in a "
        "month of net contraction -- the Digest's scorecard reads them on a trailing-twelve-month "
        "basis. SMB has no reps, so its Magic Number reflects program spend only and its AM "
        "Efficiency is undefined."
    )

    st.markdown("**Consumption payback by segment -- snapshot**")
    st.plotly_chart(
        segment_bar_chart(latest, "consumption_payback_months", "Consumption payback (months)",
                           lambda v: num(v, 1), ascending=True),
        use_container_width=True,
    )

    st.markdown("**Consumption payback over time** (full history)")
    st.plotly_chart(
        segment_line_chart(e, "consumption_payback_months", "Months"), use_container_width=True,
    )

# ---------------------------------------------------------------------------
with tab_durability:
    st.markdown(
        f'<span class="pillar-dot" style="background-color:{theme.PILLAR_COLOR["durability"]}"></span>'
        "**Is what we sold sticking, by segment**",
        unsafe_allow_html=True,
    )
    d = durability[durability["segment"].isin(segments)].copy()
    d_months = sorted(d["month"].unique())
    latest = d[d["month"] == snapshot_month]

    cols = st.columns(len(ordered_segments))
    for col, seg in zip(cols, ordered_segments):
        row_df = latest[latest["segment"] == seg]
        with col:
            st.markdown(f"**{seg}**")
            if row_df.empty:
                st.info("No data for this segment/month.")
                continue
            row = row_df.iloc[0]
            prior = prior_month_row(d, seg, snapshot_month, d_months)
            metric_card("NRR", "nrr", row["nrr"], prior["nrr"] if prior is not None else None,
                        "durability", pct, layer_note=LAYER_LABEL["nrr"])
            metric_card("GRR", "grr", row["grr"], prior["grr"] if prior is not None else None,
                        "durability", pct, layer_note=LAYER_LABEL["grr"])
            metric_card("Logo retention", "logo_retention_rate", row["logo_retention_rate"],
                        prior["logo_retention_rate"] if prior is not None else None,
                        "durability", pct, layer_note=LAYER_LABEL["logo_retention_rate"])

    st.caption(
        "NRR, GRR and Logo retention are all colored for favorable/unfavorable direction "
        "(higher = favorable) against last month, same segment."
    )

    st.markdown("**NRR by segment -- snapshot**")
    st.plotly_chart(
        segment_bar_chart(latest, "nrr", "NRR", pct, tickformat=".0%"),
        use_container_width=True,
    )

    st.markdown(f"**NRR over time** (trailing {TREND_WINDOW_MONTHS} months)")
    st.plotly_chart(
        segment_line_chart(d, "nrr", "NRR", y_is_pct=True, window=True), use_container_width=True,
    )
    st.caption(
        "Windowed to the trailing 24 months rather than full company history: the earliest "
        "live months carry a near-zero starting-MRR denominator that produces extreme NRR/GRR "
        "ratio spikes unrelated to steady-state retention performance -- the same definitional "
        "gap docs/acme-corp-analytics-methods.md's NRR/GRR plan-comparability note documents. "
        "Showing the full history would compress this window's real, decision-relevant "
        "movement into an unreadable band at the bottom of the y-axis."
    )

# ---------------------------------------------------------------------------
with tab_migration:
    st.markdown(
        f'<span class="pillar-dot" style="background-color:{theme.PILLAR_COLOR["growth"]}"></span>'
        "**Segment migration -- upward only, never a downgrade**",
        unsafe_allow_html=True,
    )
    m = migration.copy()
    m["migration_date"] = pd.to_datetime(m["migration_date"])
    m = m[m["to_segment"].isin(segments) | m["from_segment"].isin(segments)]

    st.caption(
        "One row per migration event. Every row's trigger_reason is either "
        "usage_threshold or firmographic_rescore -- migration is always upward, "
        "never a downgrade (CLAUDE.md invariant). Shown with the Growth pillar's accent "
        "color since graduated revenue is part of the growth-bridge story, even though the "
        "build spec deliberately excludes it from the source segment's own churn/contraction "
        "math."
    )

    c1, c2 = st.columns(2)
    with c1:
        theme.scorecard("Total migrations", str(len(m)), pillar="growth")
    with c2:
        theme.scorecard("MRR reclassified", usd(m["mrr_reclassified"].sum()), pillar="growth")

    if m.empty:
        st.info("No migration events for the selected segments.")
    else:
        st.markdown("**Trigger reason mix**")
        reason_counts = m["trigger_reason"].value_counts()
        total = reason_counts.sum()
        reason_colors = {"usage_threshold": theme.GROWTH_NAVY, "firmographic_rescore": theme.GROWTH_ICE_BLUE}
        reason_text_colors = {"usage_threshold": "#FFFFFF", "firmographic_rescore": theme.GROWTH_NAVY}
        fig = go.Figure()
        for reason in ["usage_threshold", "firmographic_rescore"]:
            n = int(reason_counts.get(reason, 0))
            if n == 0:
                continue
            share = n / total
            fig.add_trace(go.Bar(
                y=["Migrations"], x=[n], orientation="h",
                name=f"{reason.replace('_', ' ').title()} ({n}, {share:.0%})",
                marker_color=reason_colors[reason],
                text=f"{reason.replace('_', ' ').title()}: {n} ({share:.0%})",
                textposition="inside", insidetextanchor="middle",
                textfont=dict(color=reason_text_colors[reason]),
            ))
        fig.update_layout(barmode="stack", **theme.plotly_layout(height=170))
        theme.style_axes(fig)
        fig.update_xaxes(title_text="Migration events")
        fig.update_yaxes(title_text="")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("**Migration path**")
        by_path = (
            m.groupby(["from_segment", "to_segment"])
            .agg(migrations=("account_id", "count"), mrr_reclassified=("mrr_reclassified", "sum"))
            .reset_index()
        )
        by_path["share_of_migrations"] = by_path["migrations"] / by_path["migrations"].sum()
        by_path = by_path.sort_values("migrations", ascending=False)
        st.dataframe(
            by_path.rename(columns={
                "from_segment": "From", "to_segment": "To", "migrations": "Migrations",
                "mrr_reclassified": "MRR reclassified", "share_of_migrations": "Share",
            }).assign(**{
                "MRR reclassified": lambda x: x["MRR reclassified"].map(usd),
                "Share": lambda x: x["Share"].map(pct),
            }),
            hide_index=True, use_container_width=True,
        )
