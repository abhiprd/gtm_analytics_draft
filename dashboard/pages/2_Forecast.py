"""Forecast -- calls analytics/forecast.py's run_forecast() directly (the
Wave 2 artifact: bottoms-up rep/manager, ML, and CRO-overlay lenses
reconciled per segment for the current quarter). No forecast math lives
in this page; it renders exactly what the artifact returns, with
log=False so viewing the dashboard never writes to
fact_model_performance_history.
"""
import os
import sys
from datetime import date, timedelta

import pandas as pd
import streamlit as st

_DASHBOARD_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_DASHBOARD_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, _DASHBOARD_DIR)
from analytics import forecast as fc
from lib.formatting import pct, usd

st.set_page_config(page_title="Forecast | Acme Corp GTM", page_icon="📈", layout="wide")
st.title("Forecast")
st.caption(
    "Commercial and Enterprise only -- SMB's no-touch, 0-7-day motion has no weekly "
    "forecast cadence to snapshot. Four lenses: bottoms-up rep, bottoms-up manager, ML, "
    "and the CRO overlay, reconciled side by side with a divergence flag."
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

st.subheader(f"Current period: {result['period']}")

for _, row in recon.iterrows():
    st.markdown(f"**{row['segment']}**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Bottoms-up (rep)", usd(row["bottoms_up_rep"]))
    c2.metric("Bottoms-up (manager)", usd(row["bottoms_up_manager"]))
    ml_display = usd(row["ml"]) if row["ml_computable"] else "N/A"
    c3.metric("ML", ml_display)
    c4.metric(
        "CRO-adjusted", usd(row["cro_adjusted"]),
        delta=usd(row["cro_adjustment_amount"]) if row["has_logged_cro_adjustment"] else None,
    )
    flag = "⚠️ diverges materially" if row["diverges_materially"] else "lenses agree"
    st.caption(
        f"{row['open_deals']} open deals, {usd(row['open_pipeline_amount'])} open pipeline. "
        f"Lens spread {pct(row['lens_spread_pct'])} ({flag}, widest pair: {row['widest_pair']}). "
        + (f"CRO reason: {row['cro_reason']}." if row["has_logged_cro_adjustment"] else "No CRO override filed.")
    )
    st.divider()

st.markdown("#### ML lens quality")
if result["model_computable"]:
    st.write(
        f"Out-of-time holdout AUC **{result['auc_holdout']:.3f}** "
        f"({'meets' if result['meets_auc_target'] else 'below'} target), "
        f"trained on {result['n_train']} snapshots, held out {result['n_test']}."
    )
else:
    st.info("ML lens not computable for this as-of date (insufficient training data).")

with st.expander("Data window note"):
    st.caption(result["data_window_note"])
