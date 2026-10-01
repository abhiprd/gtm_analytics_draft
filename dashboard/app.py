"""Phase 5 -- CRO / leadership interface, entry point and router.

Per build spec Section 6's scope guardrail: a digest view, a forecast view, a
segment-efficiency view, and one working chat demo -- not a full BI platform. See
dashboard/README.md for how to run this and why it needs its own Python 3.12
virtualenv. Visual/layout choices follow
.claude/skills/dashboard-design-conventions/SKILL.md; theme.py is the shared
palette/font/component module every page imports rather than hardcoding.

st.navigation names the landing page "Home" in the sidebar (the file-based default
would show the script name, "app").
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

st.set_page_config(page_title="Acme Corp GTM | CRO Dashboard", page_icon="\U0001F4CA", layout="wide")

pages = [
    st.Page("home.py", title="Home", icon="\U0001F3E0", default=True),
    st.Page("pages/1_Digest.py", title="Digest", icon="\U0001F4CB"),
    st.Page("pages/2_Forecast.py", title="Forecast", icon="\U0001F4C8"),
    st.Page("pages/3_Segment_Efficiency.py", title="Segment efficiency", icon="\U0001F9ED"),
    st.Page("pages/4_Ask_the_Metric_Tree.py", title="Ask the metric tree", icon="\U0001F4AC"),
]
st.navigation(pages).run()
