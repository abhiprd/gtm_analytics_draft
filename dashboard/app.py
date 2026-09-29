"""Phase 5 -- CRO / leadership interface, entry point.

Per build spec Section 6's scope guardrail: a digest view, a forecast
view, a segment-efficiency view, and one working chat demo -- not a full
BI platform. See dashboard/README.md for how to run this and why it needs
its own Python 3.12 virtualenv. Visual/layout choices on this page follow
.claude/skills/dashboard-design-conventions/SKILL.md; theme.py is the
shared palette/font/component module every page imports rather than
hardcoding.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

import theme
from lib import data
from lib.formatting import usd

st.set_page_config(page_title="Acme Corp GTM | CRO Dashboard", page_icon="📊", layout="wide")
theme.inject_global_css()

st.title("Acme Corp GTM Analytics")
st.caption("CRO / leadership interface -- Phase 5 of the build spec's five-phase system.")

st.markdown(
    "This reads live from the finished dbt marts (`data/acme_gtm.duckdb`, `main_marts` "
    "schema) and from the Phase 4 artifacts' own generated output -- nothing on this site "
    "is a mock or a static screenshot. Four views, matching Section 6's scope guardrail:"
)

col1, col2 = st.columns(2)
with col1:
    st.markdown(
        "- **Digest** -- the weekly executive readout: Layer-1 scorecard, drill-downs, "
        "playbook triggers, and the churn-risk watchlist\n"
        "- **Forecast** -- bottoms-up (rep/manager), ML, and CRO-overlay lenses reconciled "
        "side by side, current quarter"
    )
with col2:
    st.markdown(
        "- **Segment efficiency** -- Growth, Efficiency, and Durability by segment "
        "(SMB / Commercial / Enterprise), with known raw-data gaps shown as gaps, not "
        "fabricated numbers\n"
        "- **Ask the metric tree** -- a natural-language front end onto the Phase 3 "
        "semantic layer's whitelisted metric registry"
    )

st.divider()

readout_dates = data.list_readout_dates()
if readout_dates:
    latest = data.load_readout(readout_dates[0])
    header = latest["header"]
    st.subheader(f"Latest readout -- {header['reporting_period_label']}")

    scorecard = latest["layer1_scorecard"]
    breaching = scorecard["nodes_breaching_threshold"]
    drilldowns = latest["drilldowns"]["count"]
    watchlist_arr = sum(r["est_arr_at_risk_usd"] for r in latest["watchlist"]["rows"])

    # Informational counts only -- no favorable/unfavorable judgment
    # applied here (neutral, no pillar accent). A verdict needs a real
    # comparison point per Section 7; that lives on the Digest page,
    # not this landing teaser.
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        theme.scorecard("Layer-1 nodes tracked", str(scorecard["nodes_total"]))
    with m2:
        theme.scorecard("Breaching ±8% variance", str(breaching))
    with m3:
        theme.scorecard("Drill-downs generated", str(drilldowns))
    with m4:
        theme.scorecard("ARR at risk (watchlist)", usd(watchlist_arr))

    st.caption(
        f"As of {header['as_of_date']} -- {header['audience']}. "
        "Open **Digest** in the sidebar for the full scorecard, comparisons, and drill-downs."
    )
else:
    st.warning("No weekly readout output found under analytics/outputs/.")

st.divider()
st.caption(
    "Built end-to-end: simulated raw data -> dbt models -> semantic layer (MCP) -> "
    "diagnostic analytics -> this interface. See the repo README for the full pipeline."
)
