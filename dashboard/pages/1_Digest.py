"""Digest -- renders analytics/weekly_readout.py's own generated output
verbatim (analytics/outputs/weekly_readout_<date>.json). This page adds no
computation of its own: every number here is read straight from the
readout artifact, which is itself read straight from
variance_diagnostic.run_diagnostic() and health_score.py's scored output.
"""
import os
import sys
from datetime import datetime

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import data
from lib.formatting import usd

st.set_page_config(page_title="Digest | Acme Corp GTM", page_icon="📋", layout="wide")
st.title("Weekly executive readout")

readout_dates = data.list_readout_dates()
if not readout_dates:
    st.warning("No weekly readout output found under analytics/outputs/.")
    st.stop()

as_of = st.selectbox(
    "As-of date", readout_dates, format_func=lambda d: d.isoformat(),
    help="One entry per date analytics/weekly_readout.py has been run for.",
)
readout = data.load_readout(as_of)
header = readout["header"]

st.subheader(header["reporting_period_label"])
c1, c2, c3 = st.columns(3)
c1.metric("Audience", header["audience"])
c2.metric("Variance threshold", f"±{header['variance_threshold'] * 100:.0f}%")
c3.metric("Grain", header["reporting_period_grain"])
st.caption(header["reporting_period_grain_note"])

st.markdown("#### Executive summary")
exec_summary = readout["executive_summary"]
if exec_summary["status"] == "deferred":
    st.info(exec_summary["placeholder_marker"])
    with st.expander("Why this is blank"):
        st.write(exec_summary["note"])
else:
    st.write(exec_summary)

st.divider()

st.markdown("#### Layer-1 scorecard")
scorecard = readout["layer1_scorecard"]
m1, m2, m3 = st.columns(3)
m1.metric("Nodes tracked", scorecard["nodes_total"])
m2.metric("Breaching ±8%", scorecard["nodes_breaching_threshold"])
m3.metric("Not computable", scorecard["nodes_not_computable"])

rows = pd.DataFrame(scorecard["rows"])
for pillar in ["growth", "efficiency", "durability"]:
    pillar_rows = rows[rows["pillar"] == pillar]
    if pillar_rows.empty:
        continue
    st.markdown(f"**{pillar.title()}**")
    st.dataframe(
        pillar_rows[[
            "label", "value_display", "comparison_display", "variance_display", "status",
        ]].rename(columns={
            "label": "Metric", "value_display": "Actual",
            "comparison_display": "vs. plan/baseline", "variance_display": "Variance",
            "status": "Status",
        }),
        hide_index=True, use_container_width=True,
    )

st.divider()

st.markdown("#### Drill-downs")
drilldowns = readout["drilldowns"]
st.caption(
    f"{drilldowns['count']} generated -- only for Layer-1 nodes with a real Layer-2 "
    "outlier among their true siblings, never padded to a fixed count."
)
for entry in drilldowns["entries"]:
    l1 = entry["layer1"]
    l2 = entry["layer2_outlier"]
    title = (
        f"{l1['label']} ({l1['status']}, {l1['variance_display']}) "
        + (f"-> {l2['label']} is the outlier" if l2 else "-> no computable Layer-2 outlier")
    )
    with st.expander(title):
        col1, col2 = st.columns(2)
        col1.metric(l1["label"], l1["value_display"], l1["variance_display"])
        if l2:
            col2.metric(l2["label"], f"{l2['value']:.4g}", f"{l2['deviation_pct'] * 100:+.1f}% vs baseline")
        else:
            col2.info("No Layer-2 child has a mart-computable actual with a usable baseline.")

        if entry.get("sibling_ranking"):
            st.caption("Ranked against its true Layer-2 siblings:")
            sib_df = pd.DataFrame(entry["sibling_ranking"])[
                ["label", "value_display", "baseline_display", "deviation_display", "rank"]
            ].rename(columns={
                "label": "Metric", "value_display": "Value",
                "baseline_display": "Baseline", "deviation_display": "Deviation", "rank": "Rank",
            })
            st.dataframe(sib_df, hide_index=True, use_container_width=True)

        missing = entry.get("sibling_coverage", {}).get("missing_siblings") or []
        if missing:
            st.caption(
                "Not in the ranking (no mart_* data): "
                + ", ".join(m["label"] for m in missing)
            )
        for note in entry.get("notes") or []:
            st.caption(f"Note: {note}")

st.divider()

st.markdown("#### Automated playbook triggers")
triggers = readout["playbook_triggers"]
trig_df = pd.DataFrame(triggers["triggers"])
trig_df["timestamp"] = pd.to_datetime(trig_df["timestamp"])
as_of_ts = pd.Timestamp(as_of)
recent = trig_df[trig_df["timestamp"] >= as_of_ts - pd.Timedelta(days=90)]

st.caption(
    f"{triggers['count']} logged across this project's full history; "
    f"{len(recent)} fired in the 90 days ending {as_of.isoformat()}. Binary rules, unranked."
)
if not recent.empty:
    st.dataframe(
        recent.sort_values("timestamp", ascending=False)[
            ["timestamp", "rule_id", "account_id", "resulting_action"]
        ],
        hide_index=True, use_container_width=True, height=280,
    )
with st.expander(f"Rule catalog ({len(triggers['rules'])} rules)"):
    for rule_id, rule in triggers["rules"].items():
        st.markdown(f"**{rule_id}** -- {rule['description']}")
        st.caption(f"Action: {rule['resulting_action']} | Source: {rule['source_mart']}")

st.divider()

st.markdown("#### Watchlist")
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
        hide_index=True, use_container_width=True,
    )
with st.expander("Caveats"):
    for caveat in watchlist["caveats"]:
        st.caption(caveat)

st.divider()

st.markdown("#### Forecast")
forecast = readout["forecast"]
if forecast["status"] == "not_yet_built":
    st.info("Not embedded in this readout (see the **Forecast** page for the built artifact).")
    st.caption(forecast["note"])
else:
    st.write(forecast)
