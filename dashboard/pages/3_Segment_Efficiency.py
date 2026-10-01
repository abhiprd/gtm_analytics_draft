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
from lib import data, labels, verdict
from lib.formatting import months, num, pct, usd

theme.page_config("Segment efficiency | Acme Corp GTM", "\U0001F9ED")
theme.inject_global_css()

st.title("Segment efficiency")
st.caption(
    "Growth, Efficiency and Durability by segment (SMB, Commercial, Enterprise), "
    "segment × month. Segment describes the account; it does not imply how the account was acquired."
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
    "new_logo_mrr": "Layer 1 · New logo consumption revenue",
    "win_rate": "Layer 2 · New logo consumption revenue → Win rate",
    "avg_initial_commitment": "Layer 2 · New logo consumption revenue → Avg initial commitment",
    "consumption_payback_months": "Layer 1 · Efficiency",
    "onboarding_cs_efficiency_ratio": "Layer 1 · Efficiency",
    "magic_number": "Layer 1 · Efficiency",
    "am_efficiency": "Layer 1 · Efficiency",
    "nrr": "Layer 1 · Durability",
    "grr": "Layer 1 · Durability",
    "logo_retention_rate": "Layer 1 · Durability",
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
final_month = data.final_month_in_marts()  # the truncated final month of the data window
filter_col, info_col = st.columns([2, 1])
with filter_col:
    segments = st.multiselect("Segments", SEGMENT_ORDER, default=SEGMENT_ORDER)

    all_months = sorted(growth["month"].unique())
    # Default one month behind the mart's own literal max: the final month of the
    # window is truncated (analytics/variance_diagnostic.py `_data_window_check`).
    default_month = all_months[-2] if len(all_months) > 1 else all_months[-1]

    def _month_label(m) -> str:
        text = pd.Timestamp(m).strftime("%Y-%m")
        return f"{text} (partial month)" if final_month and text == str(final_month)[:7] else text

    snapshot_month = st.selectbox(
        "Snapshot month", all_months, index=all_months.index(default_month),
        format_func=_month_label,
        help="Defaults to the last complete month. The newest month in the data is partial.",
    )
with info_col:
    st.caption(
        f"**Grain:** Monthly (segment × month)\n\n"
        f"**Snapshot:** {_month_label(snapshot_month)}"
    )

if not segments:
    st.info("Select at least one segment to see the pillars below.")
    st.stop()

ordered_segments = [s for s in SEGMENT_ORDER if s in segments]
snapshot_is_partial = bool(final_month) and pd.Timestamp(snapshot_month).strftime("%Y-%m") == str(final_month)[:7]

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


PCT_KEYS = {"win_rate", "nrr", "grr", "logo_retention_rate"}

# Consumption payback's CAC is marketing spend only (fact_marketing_spend), so its level
# is not comparable with a fully loaded benchmark. The month-over-month move on the same
# basis is unaffected and keeps its status color; the level carries a caveat tag.
CAVEATED_METRICS = {
    "consumption_payback_months": (
        "Caveated: CAC scope",
        "CAC is marketing spend only; the level is not comparable with a fully loaded benchmark.",
    ),
}

try:
    from lib import semantic_bridge as _sb
    _WIN_RATE_GAP = (_sb.registry()["metrics"]["win_rate"].get("gap_note") or "")
except Exception:  # registry unavailable: the structural card still renders from its own copy
    _WIN_RATE_GAP = ""
SMB_WIN_RATE_STRUCTURAL = "smb" in _WIN_RATE_GAP.lower() or not _WIN_RATE_GAP


def _layer_short(layer_note: str | None) -> str | None:
    return layer_note.split(" · ")[0] if layer_note else None


def _delta_texts(col_key: str, value, prior_value, value_fmt):
    """(variance_display, comparison_display, direction, is_ahead) for a month-over-month
    move. Percentage-point metrics are labeled pp; a move that rounds to zero is neutral."""
    direction = FAVORABLE_DIRECTION.get(col_key)
    if prior_value is None or pd.isna(prior_value):
        return None, "No comparison loaded for this metric", direction, None
    delta = value - prior_value
    if col_key in PCT_KEYS:
        variance = verdict.pp_text(delta)
    else:
        variance = f"{'+' if delta >= 0 else ''}{value_fmt(delta)}"
    comparison = f"vs {value_fmt(prior_value)} last month"
    if verdict.display_rounds_to_zero(variance):
        return verdict.unsigned_if_zero(variance), comparison, None, None
    is_ahead = None if direction is None else (delta >= 0 if direction == "higher" else delta <= 0)
    return variance, comparison, direction, is_ahead


def metric_cards(title: str, col_key: str, frame: pd.DataFrame, months: list, pillar: str, value_fmt,
                 layer_note: str | None = None, basis: str = "Monthly", scale: float = 1.0,
                 gap_for=None) -> None:
    """One metric across the selected segments: a heading, then one equal-height card
    per segment (the Digest's card grid). Colored favorable/unfavorable ONLY for metrics
    in FAVORABLE_DIRECTION, against the real prior month; every other metric shows its
    real move in neutral gray (Section 7). `gap_for(seg, row)` returns a reason string
    when the value is undefined for that segment."""
    layer_short = _layer_short(layer_note)
    st.markdown(
        f'<div style="margin-top:6px"><strong>{theme.escape_html(title)}</strong>'
        + (f' <span class="breadcrumb">{theme.escape_html(layer_note)}</span>' if layer_note else "")
        + '</div>',
        unsafe_allow_html=True,
    )
    cards = []
    for seg in ordered_segments:
        base = dict(label=seg, dot_color=theme.SEGMENT_COLOR[seg])
        row_df = frame[(frame["segment"] == seg) & (frame["month"] == snapshot_month)]
        footer = [f"Basis: {basis}"] + ([layer_short] if layer_short else ["No tree layer (bridge total)"])
        if row_df.empty:
            cards.append(dict(base, value_display="No data", footer=footer))
            continue
        row = row_df.iloc[0]
        value = row[col_key] if col_key in row else None
        value = None if value is None or pd.isna(value) else value * scale
        gap = gap_for(seg, row) if gap_for else None
        if gap:
            cards.append(dict(base, value_display="Not computable", value_size="sm",
                              comparison_display=gap, footer=footer))
            continue
        if value is None:
            cards.append(dict(base, value_display="N/A", footer=footer))
            continue
        prior = prior_month_row(frame, seg, snapshot_month, months)
        prior_value = None if prior is None or pd.isna(prior[col_key]) else prior[col_key] * scale
        card = dict(base, value_display=value_fmt(value), footer=footer)
        if col_key == "win_rate" and seg == "SMB" and SMB_WIN_RATE_STRUCTURAL:
            # Every SMB opportunity is created already Closed Won (registry gap note):
            # 100% by construction, so no comparison and no status.
            card.update(tag="Structural gap", footer=[
                "Every SMB opportunity is created already Closed Won; win rate is not a meaningful read.",
                "Commercial and Enterprise are the meaningful read."] + footer)
            cards.append(card)
            continue
        variance, comparison, direction, is_ahead = _delta_texts(col_key, value, prior_value, value_fmt)
        card.update(variance_display=variance, comparison_display=comparison,
                    favorable_direction=direction, is_ahead=is_ahead)
        if col_key in CAVEATED_METRICS:
            tag, foot = CAVEATED_METRICS[col_key]
            card["tag"] = tag
            card["footer"] = [foot] + footer
        cards.append(card)
    theme.scorecard_row(cards)


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
    actually shown keeps its true, untruncated value. The final (partial)
    month is drawn with an open marker."""
    if window:
        months_in_window = sorted(df["month"].unique())[-TREND_WINDOW_MONTHS:]
        df = df[df["month"].isin(months_in_window)]
    fig = go.Figure()
    partial_x, partial_y, partial_c = [], [], []
    for seg in ordered_segments:
        sdf = df[df["segment"] == seg].sort_values("month")
        fig.add_trace(go.Scatter(
            x=sdf["month"], y=sdf[value_col], mode="lines+markers", name=seg,
            line=dict(color=theme.SEGMENT_COLOR[seg], width=2.5), marker=dict(size=5),
        ))
        if final_month:
            last = sdf[sdf["month"].dt.strftime("%Y-%m") == str(final_month)[:7]] if hasattr(sdf["month"], "dt") else sdf.iloc[0:0]
            for _, r in last.iterrows():
                partial_x.append(r["month"]); partial_y.append(r[value_col]); partial_c.append(theme.SEGMENT_COLOR[seg])
    if partial_x:
        fig.add_trace(go.Scatter(
            x=partial_x, y=partial_y, mode="markers", name="Partial month",
            marker=dict(symbol="diamond-open", size=11, color=partial_c, line=dict(width=2)),
        ))
    fig.update_layout(**theme.plotly_layout(height=320))
    theme.style_axes(fig)
    fig.update_yaxes(title_text=y_title, tickformat=".0%" if y_is_pct else None)
    fig.update_xaxes(title_text="Month")
    return fig


def segment_bar_chart(latest_df: pd.DataFrame, value_col: str, x_title: str, value_fmt,
                       tickprefix: str = None, tickformat: str = None,
                       reference: float = None, reference_label: str = None) -> go.Figure:
    """Horizontal bars, largest at the top on every page (Section 3.2: sorted by value).
    The axis starts at zero (or at the most negative bar) and extends past the longest
    bar so the outside label is never clipped; `reference` draws a labeled line (e.g.
    100% for a retention rate). `tickprefix`/`tickformat` make the axis self-labeling,
    matching the unit `value_fmt` applies to each bar's text label."""
    d = latest_df[["segment", value_col]].dropna()
    d = d[d["segment"].isin(ordered_segments)].sort_values(value_col, ascending=True)
    vals = list(d[value_col])
    fig = go.Figure(go.Bar(
        x=vals, y=d["segment"], orientation="h",
        marker_color=[theme.SEGMENT_COLOR[s] for s in d["segment"]],
        text=[value_fmt(v) for v in vals], textposition="outside", cliponaxis=False,
    ))
    fig.update_layout(**theme.plotly_layout(height=190, showlegend=False))
    theme.style_axes(fig)
    if vals:
        top = max(max(vals), reference or 0)
        bottom = min(min(vals), 0)
        span = (top - bottom) or 1
        fig.update_xaxes(range=[bottom - (0.18 * span if bottom < 0 else 0), top + 0.2 * span])
    if reference is not None:
        fig.add_vline(x=reference, line_dash="dash", line_color=theme.NEUTRAL_GRAY,
                      annotation_text=reference_label, annotation_position="top")
    fig.update_xaxes(title_text=x_title, tickprefix=tickprefix, tickformat=tickformat)
    fig.update_yaxes(title_text="")
    return fig


def _pillar_heading(pillar: str, text: str) -> None:
    st.markdown(
        f'<span class="pillar-dot" style="background-color:{theme.PILLAR_COLOR[pillar]}"></span>'
        f"**{text}**",
        unsafe_allow_html=True,
    )


def _partial_caption() -> None:
    if snapshot_is_partial:
        st.caption("The snapshot month is the truncated final month of the data window; its values are "
                   "not representative.")


# ---------------------------------------------------------------------------
with tab_growth:
    _pillar_heading("growth", "Growth by segment")
    st.caption("Ending MRR (the growth-bridge total) and the New logo consumption revenue drivers.")
    _partial_caption()
    g = growth[growth["segment"].isin(segments)].copy()
    g_months = sorted(g["month"].unique())
    latest = g[g["month"] == snapshot_month]

    metric_cards("Ending MRR (bridge total)", "ending_mrr", g, g_months, "growth", usd)
    metric_cards("New logo MRR", "new_logo_mrr", g, g_months, "growth", usd, layer_note=LAYER_LABEL["new_logo_mrr"])
    metric_cards("Win rate", "win_rate", g, g_months, "growth", pct, layer_note=LAYER_LABEL["win_rate"])
    metric_cards("Avg initial commitment", "avg_initial_commitment", g, g_months, "growth", usd,
                 layer_note=LAYER_LABEL["avg_initial_commitment"])

    st.markdown("**New logo MRR by segment — snapshot**")
    st.plotly_chart(
        segment_bar_chart(latest, "new_logo_mrr", "New logo MRR ($)", usd, tickprefix="$", tickformat="~s"),
        width="stretch",
    )

    st.markdown("**Ending MRR over time** (full history)")
    st.plotly_chart(segment_line_chart(g, "ending_mrr", "Ending MRR ($)"), width="stretch")

# ---------------------------------------------------------------------------
with tab_efficiency:
    _pillar_heading("efficiency", "Efficiency by segment")
    st.caption("Consumption payback, onboarding/CS efficiency, Magic Number and AM Efficiency.")
    _partial_caption()
    e = efficiency[efficiency["segment"].isin(segments)].copy()
    e_months = sorted(e["month"].unique())
    latest = e[e["month"] == snapshot_month]

    metric_cards("Consumption payback (months)", "consumption_payback_months", e, e_months, "efficiency",
                 months, layer_note=LAYER_LABEL["consumption_payback_months"])
    metric_cards("AM touches per 1M Actions delivered", "onboarding_cs_efficiency_ratio", e, e_months,
                 "efficiency", lambda v: num(v, 2), layer_note=LAYER_LABEL["onboarding_cs_efficiency_ratio"],
                 scale=1_000_000)
    metric_cards("Magic Number (monthly)", "magic_number", e, e_months, "efficiency", lambda v: num(v, 2),
                 layer_note=LAYER_LABEL["magic_number"],
                 gap_for=lambda seg, row: "Not defined before 2023-02 (no prior-month S&M cost)"
                 if pd.isna(row["magic_number"]) else None)
    metric_cards("AM Efficiency (monthly)", "am_efficiency", e, e_months, "efficiency", lambda v: num(v, 2),
                 layer_note=LAYER_LABEL["am_efficiency"],
                 gap_for=lambda seg, row: (("Not defined for SMB (no AM)" if seg == "SMB" else "Not computable")
                                           if pd.isna(row["am_efficiency"]) else None))

    st.markdown("**Consumption payback by segment — snapshot**")
    st.plotly_chart(
        segment_bar_chart(latest, "consumption_payback_months", "Consumption payback (months)",
                           months),
        width="stretch",
    )

    st.markdown("**Consumption payback over time** (full history)")
    st.plotly_chart(
        segment_line_chart(e, "consumption_payback_months", "Months"), width="stretch",
    )

# ---------------------------------------------------------------------------
with tab_durability:
    _pillar_heading("durability", "Durability by segment")
    st.caption("NRR, GRR and Logo retention as monthly rates for the snapshot month.")
    _partial_caption()
    d = durability[durability["segment"].isin(segments)].copy()
    d_months = sorted(d["month"].unique())
    latest = d[d["month"] == snapshot_month]

    metric_cards("NRR", "nrr", d, d_months, "durability", pct, layer_note=LAYER_LABEL["nrr"])
    metric_cards("GRR", "grr", d, d_months, "durability", pct, layer_note=LAYER_LABEL["grr"])
    metric_cards("Logo retention", "logo_retention_rate", d, d_months, "durability", pct,
                 layer_note=LAYER_LABEL["logo_retention_rate"])

    st.markdown("**NRR by segment — snapshot**")
    st.plotly_chart(
        segment_bar_chart(latest, "nrr", "NRR (monthly rate)", pct, tickformat=".0%",
                          reference=1.0, reference_label="100%"),
        width="stretch",
    )

    st.markdown(f"**NRR over time** (trailing {TREND_WINDOW_MONTHS} months)")
    st.plotly_chart(
        segment_line_chart(d, "nrr", "NRR", y_is_pct=True, window=True), width="stretch",
    )
# ---------------------------------------------------------------------------
with tab_migration:
    _pillar_heading("growth", "Segment migration — upward only")
    m = migration.copy()
    m["migration_date"] = pd.to_datetime(m["migration_date"])
    m = m[m["to_segment"].isin(segments) | m["from_segment"].isin(segments)]

    st.caption(
        "One row per migration event, all dates (the snapshot month does not filter this tab). "
        "Every event's trigger reason is usage threshold or firmographic rescore."
    )

    theme.scorecard_row([
        dict(label="Total migrations (all time)", value_display=str(len(m)), pillar="growth"),
        dict(label="MRR reclassified (all time)", value_display=usd(m["mrr_reclassified"].sum()), pillar="growth"),
    ])

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
                name=f"{labels.humanize(reason)} ({n}, {share:.0%})",
                marker_color=reason_colors[reason],
                text=f"{labels.humanize(reason)}: {n} ({share:.0%})",
                textposition="inside", insidetextanchor="middle",
                textfont=dict(color=reason_text_colors[reason]),
            ))
        fig.update_layout(barmode="stack", **theme.plotly_layout(height=170))
        theme.style_axes(fig)
        fig.update_xaxes(title_text="Migration events")
        fig.update_yaxes(title_text="")
        st.plotly_chart(fig, width="stretch")

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
            hide_index=True, width="stretch",
        )

# ---------------------------------------------------------------------------
# Notes & assumptions -- the single home for every caveat on this page
# (Section 11.3). Magic Number / AM Efficiency facts are from
# docs/acme-corp-analytics-methods.md (the magic_number / am_efficiency entry).
theme.notes_and_assumptions([
    ("Scope", "Every metric on this page is a single-month value, segment × month. Monthly is the only grain "
              "the underlying data holds, so no grain toggle is offered."),
    ("Scope", "The snapshot month defaults to the last complete month. The newest month in the data is a "
              "truncated final month and is marked partial; charts draw it with an open marker."),
    ("Scope", "Win rate, Consumption payback, NRR, GRR and Logo retention are colored against last month "
              "for the same segment (higher is favorable, except Consumption payback where lower is "
              "favorable). This is a trailing comparison, not a plan comparison."),
    ("Scope", "A move that rounds to zero is neutral. Rate moves are in percentage points (pp)."),
    ("Scope", "Ending MRR, New logo MRR, Avg initial commitment and AM touches per 1M Actions show their "
              "month-over-month move in neutral gray. No plan is loaded at this grain for these figures."),
    ("Scope", "NRR and GRR here are monthly rates for the snapshot month. The Digest shows NRR, GRR and Logo "
              "retention as trailing-12-month compounded rates, so the two pages show different levels by "
              "design."),
    ("Scope", "Consumption payback uses CAC from marketing spend only, which excludes sales headcount cost, "
              "so its level is not comparable with a fully loaded benchmark. The month-over-month move on "
              "the same basis is unaffected."),
    ("Scope", "Magic Number is net new ARR over the prior month's S&M cost. S&M cost is rep fully-loaded "
              "cost including ramp plus marketing spend allocated by channel. AM Efficiency is monthly "
              "expansion MRR over AM cost."),
    ("Scope", "Single-month Magic Number and AM Efficiency are seasonal and can be negative in a month of "
              "net contraction. The Digest reads both as trailing-twelve-month ratios and compares them "
              "with plan under a level-comparability caveat."),
    ("Scope", "S&M cost excludes marketing-team headcount, which the raw data does not carry. Magic "
              "Number is a ceiling against the benchmark and its S&M denominator a floor."),
    ("Data gap", "Magic Number is not defined before 2023-02, the first month with a prior-month S&M cost."),
    ("Data gap", "SMB has no reps or AM: its Magic Number reflects program spend only and its AM "
                 "Efficiency is not defined."),
    ("Data gap", labels.clean_registry_text(_WIN_RATE_GAP) and
        ("Win rate: " + labels.clean_registry_text(_WIN_RATE_GAP)) or
        "Win rate: every SMB opportunity is created already Closed Won, so SMB win rate is 100% by construction."),
    ("Scope", "The NRR trend shows the trailing 24 months. The earliest months have a near-zero "
              "starting-MRR denominator, and their ratio spikes would flatten the recent trend."),
    ("Scope", "The NRR snapshot chart starts at zero and marks 100%; a rate above 100% means expansion "
              "exceeded contraction and churn in the month."),
    ("Scope", "Segment migration is shown with the Growth accent. Graduated revenue is part of the growth "
              "bridge and is excluded from the source segment's own churn and contraction."),
])
