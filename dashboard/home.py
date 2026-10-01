"""Home -- the landing page: what each view is for, the latest readout's headline
counts, and the pipeline behind them. Routed by app.py (st.navigation)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

import theme
from lib import data
from lib.formatting import usd

theme.inject_global_css()

st.title("Acme Corp GTM Analytics")
st.caption("Revenue leadership dashboard over the Acme Corp GTM metric tree.")
theme.override_banner()

st.markdown(
    "Data sources: the finished data marts and the weekly readouts produced by the analytics "
    "models. Four views:"
)

col1, col2 = st.columns(2)
with col1:
    st.markdown(
        "- **Digest** — the weekly executive readout: Layer-1 scorecard, drill-downs, "
        "forecast, playbook triggers and the churn-risk watchlist\n"
        "- **Forecast** — bottoms-up (rep and manager), ML and CRO-adjusted lenses reconciled "
        "side by side for the quarter of a chosen forecast call"
    )
with col2:
    st.markdown(
        "- **Segment efficiency** — Growth, Efficiency and Durability by segment "
        "(SMB, Commercial, Enterprise), with data gaps shown as gaps\n"
        "- **Ask the metric tree** — the metric tree as a navigable panel, with questions "
        "answered from the semantic layer's whitelisted metric registry"
    )

st.divider()

readout_dates = data.list_readout_dates()
if readout_dates:
    latest = data.load_readout(readout_dates[0])
    header = latest["header"]
    st.subheader(f"Latest readout — {header['reporting_period_label']}")

    scorecard = latest["layer1_scorecard"]
    breaching = scorecard["nodes_breaching_threshold"]
    drilldowns = latest["drilldowns"]["count"]
    watchlist_arr = sum(r["est_arr_at_risk_usd"] for r in latest["watchlist"]["rows"])

    # Informational counts only -- no favorable/unfavorable judgment
    # applied here (neutral, no pillar accent). A verdict needs a real
    # comparison point per Section 7; that lives on the Digest page,
    # not this landing teaser.
    threshold = f"±{header['variance_threshold'] * 100:.0f}%"
    as_of = f"Readout as of {header['as_of_date']}"
    theme.scorecard_row([
        dict(label="Layer-1 nodes tracked", value_display=str(scorecard["nodes_total"]), footer=[as_of]),
        dict(label=f"Outside {threshold} of plan", value_display=str(breaching),
             footer=[as_of, "Includes metrics with a caveated plan comparison"]),
        dict(label="Drill-downs generated", value_display=str(drilldowns), footer=[as_of]),
        dict(label="ARR at risk (watchlist)", value_display=usd(watchlist_arr),
             footer=[as_of, "Estimated from segment-average ARR"]),
    ])

    st.caption(
        f"As of {header['as_of_date']} · {header['audience']}. "
        "Open Digest in the sidebar for the full scorecard, comparisons and drill-downs."
    )
else:
    st.warning("No weekly readout has been generated yet.")

st.divider()
theme.notes_and_assumptions([
    ("Scope", "Counts are read from the newest weekly readout. Comparisons against plan are on the Digest."),
    ("Scope", "ARR at risk is the sum of the watchlist's estimated ARR at risk, which uses each "
              "account's segment-average ARR."),
    ("Scope", "Pipeline: simulated raw data → data models → semantic layer → diagnostic analytics → "
              "this interface."),
])
