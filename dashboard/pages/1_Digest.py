"""Digest -- renders analytics/weekly_readout.py's own generated output
verbatim (analytics/outputs/weekly_readout_<date>.json). This page adds no
computation of its own: every number here is read straight from the
readout artifact, which is itself read straight from
variance_diagnostic.run_diagnostic() and health_score.py's scored output.

Audience tier: CRO / exec (dashboard-design-conventions.md Section 4.1's
own worked example for this tier). Layout follows Section 4.3's
inverted-pyramid order top to bottom:
  1. Verdict row      -- Layer-1 scorecards by pillar
  2. What changed     -- drill-downs (breaching nodes only, never padded)
  3. What's coming    -- forecast (pointer to the Forecast page; this
                          readout module doesn't embed forecast numbers)
  4. What needs a decision -- watchlist + playbook triggers
  5. Everything else  -- sibling rankings, rule catalog, caveats -- behind
                          st.expander, never rendered flat on the page.

Every Layer label shown (1/2/3) is the readout JSON's own `layer` field,
which is itself sourced from docs/acme-corp-gtm-metric-tree.md -- this
page never relabels or re-derives a layer depth. The 11 Layer-1 metric
keys and the Layer-2 children referenced below (pipeline_generated,
win_rate, avg_initial_commitment, etc.) were checked against that file
directly while building this page.
"""
import os
import sys
from datetime import date

import pandas as pd
import streamlit as st

_DASHBOARD_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DASHBOARD_DIR)
import theme
from lib import data
from lib.formatting import num, pct, usd


def _format_baseline(value: float, unit: str) -> str:
    """Format a row's trailing_baseline using its own `unit` field -- no
    metric-specific logic, purely a display formatter for a value the
    engine already computed."""
    if unit == "usd":
        return usd(value)
    if unit == "rate":
        return pct(value)
    if unit == "months":
        return f"{value:.2f} mo"
    if unit == "multiple":
        return f"{value:.2f}x"
    return f"{value:.4g}"

st.set_page_config(page_title="Digest | Acme Corp GTM", page_icon="📋", layout="wide")
theme.inject_global_css()

# Formulas transcribed verbatim from docs/acme-corp-gtm-metric-tree.md
# (the New logo / Expansion / Efficiency / Durability formula lines) --
# display-only citation for the Section 6 "show the formula" requirement,
# never a re-derivation. Contraction+churned revenue has no single
# multiplicative formula in the tree (it's described qualitatively), so
# its entry is the tree's own driver list instead of a formula.
LAYER1_FORMULA = {
    "new_logo_consumption_revenue": "Pipeline generated × Win rate × Avg initial commitment",
    "activation": "Days from provisioning to first production Action (TTFA)",
    "expansion_consumption_revenue": "Wallet share progression × Overage realization",
    "contraction_churned_revenue": (
        "Driven by: workflow chain under-utilization, account health score, "
        "cyclical/structural usage dip, renewal win rate (no single multiplicative "
        "formula -- tree describes this node qualitatively)"
    ),
    "magic_number": "Net new ARR ÷ prior-period S&M cost",
    "consumption_payback": "CAC ÷ utilized-Action margin",
    "onboarding_cs_efficiency": "Manual AM/CS touchpoints ÷ volume of automated Actions delivered",
    "am_efficiency": "Expansion consumption revenue ÷ AM cost",
    "nrr": "(Starting − Contraction − Churn + Expansion) ÷ Starting consumption revenue",
    "grr": "(Starting − Contraction − Churn) ÷ Starting consumption revenue",
    "logo_retention": "Retained accounts ÷ Starting accounts",
}

PILLAR_LABEL = {"growth": "Growth", "efficiency": "Efficiency", "durability": "Durability"}


def is_ahead(status: str):
    """Map the engine's own `status` field to theme.py's is_ahead input.
    'Ahead' -> True (green), 'Behind' -> False (red). 'On track' (within
    the +/-8% threshold -- a real non-breaching state, not a missing
    comparison) and 'Not computable' both map to None (neutral gray) --
    a deliberate decision, not yet in the skill file: 'on track' gets no
    directional color because a threshold-bounded, could-be-either-side
    variance doesn't warrant the same favorable/unfavorable judgment as a
    genuine breach. See the report for this flagged as a skill-file gap."""
    if status == "Ahead":
        return True
    if status == "Behind":
        return False
    return None


st.title("Weekly executive readout")
st.caption(
    "CRO / GTM leadership digest -- verdict first, detail on demand. "
    "Renders analytics/weekly_readout.py's generated output verbatim; no computation here."
)

readout_dates = data.list_readout_dates()
if not readout_dates:
    st.warning("No weekly readout output found under analytics/outputs/.")
    st.stop()

title_col, control_col = st.columns([3, 1])
with control_col:
    as_of = st.selectbox(
        "As-of date", readout_dates, format_func=lambda d: d.isoformat(),
        help="One entry per date analytics/weekly_readout.py has been run for.",
    )

readout = data.load_readout(as_of)
header = readout["header"]
scorecard = readout["layer1_scorecard"]

with title_col:
    st.subheader(header["reporting_period_label"])

# --- Standing requirement (Section 7): as-of date, grain, and threshold
# visible in a prominent info row, not buried in a settings panel. Built
# as one atomic HTML block (CSS grid, not st.columns()) inside
# .theme-card-fill -- the negative-margin white-fill trick only holds up
# for a single markdown call; splitting this across st.columns() produced
# a visible seam (verified live, see theme.py's inject_global_css()
# docstring for the general rule this follows). ---
with st.container(border=True):
    st.markdown(
        f'<div class="theme-card-fill">'
        f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;">'
        f'<div><div class="card-label">Audience</div><div class="card-delta">{header["audience"]}</div></div>'
        f'<div><div class="card-label">Grain</div><div class="card-delta">Monthly only (Sec. 8 -- no toggle, no finer grain exists)</div></div>'
        f'<div><div class="card-label">Variance threshold</div><div class="card-delta">±{header["variance_threshold"] * 100:.0f}%</div></div>'
        f'<div><div class="card-label">Nodes tracked</div>'
        f'<div class="card-delta">{scorecard["nodes_total"]} '
        f'({scorecard["nodes_breaching_threshold"]} breaching, {scorecard["nodes_not_computable"]} not computable)</div></div>'
        f'</div>'
        f'<div class="breadcrumb" style="margin-top:10px;">{header["reporting_period_grain_note"]}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

st.markdown("#### Executive summary")
exec_summary = readout["executive_summary"]
if exec_summary["status"] == "deferred":
    st.caption(exec_summary["placeholder_marker"])
    theme.render_pending(
        "executive_summary_narrative",
        extra_note=(
            exec_summary["note"] + " Once built, this step consumes: "
            + ", ".join(exec_summary["consumes"]) + "."
        ),
    )
else:
    st.write(exec_summary)

st.divider()

# =====================================================================
# 1. VERDICT ROW -- Layer-1 scorecards by pillar (Section 4.3, item 1)
# =====================================================================
st.markdown("#### Verdict -- Layer-1 scorecard")
st.caption(
    "Every card below is a Layer-1 node per docs/acme-corp-gtm-metric-tree.md. "
    "Status color is computed per-metric from favorable_direction, never from the raw sign "
    "of the variance (Section 2.3)."
)

rows_df = pd.DataFrame(scorecard["rows"])

for pillar in ["growth", "efficiency", "durability"]:
    pillar_rows = rows_df[rows_df["pillar"] == pillar]
    if pillar_rows.empty:
        continue
    breaching_n = int(pillar_rows["breaches_threshold"].sum())
    dot = theme.PILLAR_COLOR[pillar]
    st.markdown(
        f'<span class="pillar-dot" style="background-color:{dot}"></span>'
        f'<strong>{PILLAR_LABEL[pillar]}</strong> '
        f'<span class="breadcrumb">({breaching_n} of {len(pillar_rows)} breaching ±{header["variance_threshold"] * 100:.0f}%)</span>',
        unsafe_allow_html=True,
    )
    cols = st.columns(len(pillar_rows))
    gap_notes = []
    for col, (_, row) in zip(cols, pillar_rows.iterrows()):
        status = row["status"]
        ahead = is_ahead(status)
        variance_text = row["variance_display"]
        favorable_dir = row["favorable_direction"]
        # "On track" and "Not computable" both map to is_ahead=None (no
        # directional judgment), but they are not the same thing -- one has
        # a real, within-threshold comparison, the other has none at all.
        # theme.scorecard()'s default neutral arrow ("->") can't tell them
        # apart, so each gets its own explicit glyph/text here instead of
        # relying on theme's arrow (favorable_direction=None suppresses
        # it), per the visual-QA finding that both rendered identically.
        if status == "On track":
            variance_text = f"● On track · {variance_text}"
            favorable_dir = None
        elif status == "Not computable":
            variance_text = "n/a · Not computable"
            favorable_dir = None
        with col:
            theme.scorecard(
                label=row["label"],
                value_display=row["value_display"],
                pillar=pillar,
                comparison_display=row["comparison_display"] if status not in ("On track", "Not computable") else None,
                variance_display=variance_text,
                favorable_direction=favorable_dir,
                is_ahead=ahead,
            )
            # Uniform footer content on every computable card (unit label
            # + trailing-baseline comparison, both real engine-computed
            # fields already on the row) so a row of cards fills evenly
            # without padding any card with invented content (Section 5.2
            # -- uneven card-fill bug). Not-computable cards (magic
            # number, AM efficiency) legitimately stay shorter here --
            # they have no trailing_baseline because there's truly
            # nothing to show, which is the honest state, not a layout
            # bug to paper over.
            st.caption(row["unit_label"])
            baseline = row.get("trailing_baseline")
            # rows_df round-trips the JSON's `null` through pandas as NaN,
            # not None -- both must be treated as "nothing to show" here.
            if baseline is not None and pd.notna(baseline):
                baseline_text = _format_baseline(baseline, row["unit"])
                base_var = row.get("baseline_variance_pct")
                if base_var is not None and pd.notna(base_var):
                    st.caption(f"8-mo trailing baseline: {baseline_text} ({base_var * 100:+.1f}%)")
                else:
                    st.caption(f"8-mo trailing baseline: {baseline_text}")
        # Same NaN-vs-None gotcha as trailing_baseline above: a raw `or`
        # treats a float NaN as truthy, so a missing note must be checked
        # explicitly rather than relying on Python truthiness.
        note = row.get("plan_comparability_note")
        if note is None or (isinstance(note, float) and pd.isna(note)):
            note = row.get("gap_note")
        if note is not None and not (isinstance(note, float) and pd.isna(note)):
            gap_notes.append((row["label"], note))
    if gap_notes:
        with st.expander(f"Why some {PILLAR_LABEL[pillar]} metrics are blank or degenerate"):
            for label, note in gap_notes:
                st.markdown(f"**{label}**")
                st.caption(note)

st.divider()

# =====================================================================
# 2. WHAT CHANGED -- drill-downs (Section 4.3, item 2; Section 6)
# =====================================================================
st.markdown("#### What changed")
drilldowns = readout["drilldowns"]
st.caption(drilldowns["note"])

for entry in drilldowns["entries"]:
    l1 = entry["layer1"]
    l2 = entry["layer2_outlier"]
    pillar = l1["pillar"]
    dot = theme.PILLAR_COLOR.get(pillar, theme.NEUTRAL_GRAY)
    breadcrumb = (
        f'{PILLAR_LABEL.get(pillar, pillar.title())} › Layer 1: {l1["label"]} '
        f'({l1["status"]}, {l1["variance_display"]}) › Layer 2: '
        + (f'{l2["label"]} is the outlier' if l2 else "no computable outlier")
    )
    with st.expander(breadcrumb):
        st.markdown(
            f'<span class="pillar-dot" style="background-color:{dot}"></span>'
            f'<span class="breadcrumb">{PILLAR_LABEL.get(pillar, pillar.title())} › '
            f'{l1["label"]}</span>',
            unsafe_allow_html=True,
        )
        st.caption(f'Layer-1 formula: {LAYER1_FORMULA.get(l1["metric_key"], "-- not in tree as a formula")}')

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Layer 1**")
            theme.scorecard(
                label=l1["label"], value_display=l1["value_display"], pillar=pillar,
                comparison_display=l1["comparison_display"], variance_display=l1["variance_display"],
                favorable_direction=None, is_ahead=is_ahead(l1["status"]),
            )
        with c2:
            st.markdown("**Layer 2 outlier**")
            if l2:
                theme.scorecard(
                    label=l2["label"], value_display=f'{l2["value"]:.4g}', pillar=pillar,
                    comparison_display="vs. trailing baseline",
                    variance_display=f'{l2["deviation_pct"] * 100:+.1f}%',
                    favorable_direction=None, is_ahead=None,
                )
            else:
                st.info("No Layer-2 child has a mart-computable actual with a usable baseline.")

        l3_status = entry.get("layer3_status")
        if l3_status == "branch_depth_2":
            st.caption("Layer 3: this branch has no Layer-3 children in the tree -- depth stops at Layer 2.")
        elif entry.get("layer3_evidence"):
            st.markdown("**Layer 3 evidence**")
            st.dataframe(pd.DataFrame(entry["layer3_evidence"]), hide_index=True, use_container_width=True)
        else:
            st.caption("Layer 3: no mart-computable evidence for this branch this period.")

        if entry.get("sibling_ranking"):
            st.caption("Layer-2 siblings ranked by deviation from their own trailing baseline:")
            sib_df = pd.DataFrame(entry["sibling_ranking"])[
                ["label", "value_display", "baseline_display", "deviation_display", "rank"]
            ].rename(columns={
                "label": "Metric (Layer 2)", "value_display": "Value",
                "baseline_display": "Baseline", "deviation_display": "Deviation", "rank": "Rank",
            })
            st.dataframe(sib_df, hide_index=True, use_container_width=True)

        missing = entry.get("sibling_coverage", {}).get("missing_siblings") or []
        if missing:
            st.caption("Not in the ranking (no mart_* data): " + ", ".join(m["label"] for m in missing))
        for note in entry.get("notes") or []:
            st.caption(f"Note: {note}")

st.divider()

# =====================================================================
# 3. WHAT'S COMING -- forecast (Section 4.3, item 3)
# =====================================================================
st.markdown("#### What's coming -- forecast")
forecast = readout["forecast"]
if forecast["status"] == "not_yet_built":
    st.info(
        "This readout does not embed a forecast section by design -- forecast reconciliation "
        "(bottoms-up rep/manager, ML, CRO overlay) is a separate, already-built artifact "
        "(`analytics/forecast.py`, status **built_and_validated** per project_status.json). "
        "Open the **Forecast** page for the live view."
    )
    st.page_link("pages/2_Forecast.py", label="Open Forecast →", icon="\U0001F4C8")
    with st.expander("Readout artifact's own note (as generated -- see caveat below)"):
        st.caption(forecast["note"])
        st.caption(
            "Caveat: the note above was written into analytics/weekly_readout.py before the "
            "Forecast artifact (Wave 2) was built, and still describes it as an unbuilt future "
            "wave. It is shown here verbatim for transparency, not because it's current -- "
            "project_status.json is the authoritative status and shows forecast as built."
        )
else:
    st.write(forecast)

st.divider()

# =====================================================================
# 4. WHAT NEEDS A DECISION -- watchlist + playbook triggers
# (Section 4.3, item 4. Tables are used here as a deliberate, scoped
# exception to Section 4.2's "exec pages avoid tables" rule: a short,
# ranked, action-oriented list is exactly the case Section 4.2 already
# anticipates an exception for. This choice isn't yet written into the
# skill file -- flagged in the build report.)
# =====================================================================
st.markdown("#### What needs a decision")
st.caption(
    "Watchlist and playbook triggers are shown as tables here as a deliberate, scoped "
    "exception to Section 4.2's 'exec pages avoid tables' rule -- a short, ranked, "
    "action-oriented list of named accounts is exactly the case that rule already "
    "anticipates an exception for; a card layout would either hide the account IDs a CRO "
    "needs to actually act on or take far more vertical space to show the same 7-10 rows. "
    "Full-width stacking (not side-by-side) so no column gets cut off. Not yet written "
    "into the skill file -- flagged in the build report."
)

st.markdown("**Watchlist -- churn risk**")
watchlist = readout["watchlist"]
st.caption(watchlist["selection_rule"])
wl_df = pd.DataFrame(watchlist["rows"])
if not wl_df.empty:
    st.dataframe(
        wl_df[["rank", "account_id", "segment", "risk_tier", "health_score", "est_arr_at_risk_display"]]
        .rename(columns={
            "rank": "Rank", "account_id": "Account", "segment": "Segment",
            "risk_tier": "Risk tier", "health_score": "Health score",
            "est_arr_at_risk_display": "Est. ARR at risk",
        }),
        hide_index=True, use_container_width=True, height=280,
    )
with st.expander("Watchlist caveats"):
    for caveat in watchlist["caveats"]:
        st.caption(caveat)

st.markdown("**Automated playbook triggers**")
triggers = readout["playbook_triggers"]
trig_df = pd.DataFrame(triggers["triggers"])
trig_df["timestamp"] = pd.to_datetime(trig_df["timestamp"])
as_of_ts = pd.Timestamp(as_of)
recent = trig_df[trig_df["timestamp"] >= as_of_ts - pd.Timedelta(days=90)]
st.caption(
    f"{triggers['count']} logged across this project's full history; {len(recent)} fired "
    f"in the 90 days ending {as_of.isoformat()}. Binary rules, unranked."
)
if not recent.empty:
    st.dataframe(
        recent.sort_values("timestamp", ascending=False)[
            ["timestamp", "rule_id", "account_id", "resulting_action"]
        ],
        hide_index=True, use_container_width=True, height=280,
    )
else:
    st.caption("No triggers fired in this window.")
with st.expander(f"Rule catalog ({len(triggers['rules'])} rules)"):
    for rule_id, rule in triggers["rules"].items():
        st.markdown(f"**{rule_id}** -- {rule['description']}")
        st.caption(f"Action: {rule['resulting_action']} | Source: {rule['source_mart']}")
