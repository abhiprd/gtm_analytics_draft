"""Read-only data access for the Phase 5 dashboard.

Every query here reads from data/acme_gtm.duckdb's main_marts schema
(dim_*/fact_*/mart_*) or from analytics/outputs' already-generated
readout JSON -- never from stg_/int_/raw, per
analytics-engineering-conventions. Nothing here writes to the database or
to fact_model_performance_history; the dashboard is a read surface.
"""
import glob
import json
import os
from datetime import date, datetime
from typing import Optional

import duckdb
import pandas as pd
import streamlit as st

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
DB_PATH = os.path.join(REPO_ROOT, "data", "acme_gtm.duckdb")
# TEST/QA HOOK: ACME_DASHBOARD_OUTPUTS_DIR points the readout reader at a
# scratch copy of analytics/outputs (used to render the Digest's
# executive-summary "generated" state from a test fixture without touching
# committed outputs). Unset in normal use. When set, pages must say so
# visibly -- see OUTPUTS_OVERRIDE_ACTIVE.
OUTPUTS_DIR = os.environ.get("ACME_DASHBOARD_OUTPUTS_DIR") or os.path.join(REPO_ROOT, "analytics", "outputs")
OUTPUTS_OVERRIDE_ACTIVE = bool(os.environ.get("ACME_DASHBOARD_OUTPUTS_DIR"))

SEGMENTS = ("SMB", "Commercial", "Enterprise")


def connect():
    """Fresh read-only connection, closed by the caller. Same pattern as
    analytics/*.py and semantic/server.py -- never holds a lock that would
    block a concurrent dbt build."""
    return duckdb.connect(DB_PATH, read_only=True)


@st.cache_data(ttl=300)
def query_df(sql: str) -> pd.DataFrame:
    con = connect()
    try:
        return con.execute(sql).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def list_readout_dates() -> list:
    """Every as_of_date the weekly executive readout has been generated
    for, newest first -- sourced from analytics/outputs' own filenames,
    never hardcoded."""
    paths = sorted(glob.glob(os.path.join(OUTPUTS_DIR, "weekly_readout_*.json")))
    dates = []
    for p in paths:
        stem = os.path.basename(p).replace("weekly_readout_", "").replace(".json", "")
        try:
            dates.append(datetime.strptime(stem, "%Y-%m-%d").date())
        except ValueError:
            continue
    return sorted(dates, reverse=True)


@st.cache_data(ttl=300)
def load_readout(as_of_date: date) -> Optional[dict]:
    path = os.path.join(OUTPUTS_DIR, f"weekly_readout_{as_of_date.isoformat()}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


@st.cache_data(ttl=300)
def mart_efficiency() -> pd.DataFrame:
    return query_df("select * from main_marts.mart_efficiency order by segment, month")


@st.cache_data(ttl=300)
def mart_durability() -> pd.DataFrame:
    return query_df("select * from main_marts.mart_durability order by segment, month")


@st.cache_data(ttl=300)
def mart_growth_bridge() -> pd.DataFrame:
    return query_df("select * from main_marts.mart_growth_bridge order by segment, month")


@st.cache_data(ttl=300)
def mart_segment_migration() -> pd.DataFrame:
    return query_df("select * from main_marts.mart_segment_migration order by migration_date")


@st.cache_data(ttl=300)
def final_month_in_marts() -> Optional[str]:
    """ISO date (YYYY-MM-DD) of the final month of the simulated window, which is a
    truncated month: every still-active account's last observed month lands in the
    contraction bucket, Enterprise marketing spend is absent and Action volume is
    partial (analytics/variance_diagnostic.py `_data_window_check`). Read from the
    newest weekly readout's own `data_window.last_month_in_marts`, the value that
    check produced; falls back to the same query (max month of mart_growth_bridge)
    when no readout is available."""
    for d in list_readout_dates():
        value = ((load_readout(d) or {}).get("data_window") or {}).get("last_month_in_marts")
        if value:
            return str(value)[:10]
    try:
        df = query_df("select max(month) as m from main_marts.mart_growth_bridge")
        return str(df["m"].iloc[0])[:10]
    except Exception:
        return None


@st.cache_data(ttl=300)
def load_pipeline_coverage_backtest() -> Optional[dict]:
    """The backtest summary of the newest committed pipeline-coverage report, or None when
    no report carries one. Read as written: the page quotes it and computes nothing. The
    in-process coverage reading does not carry the backtest."""
    paths = sorted(glob.glob(os.path.join(OUTPUTS_DIR, "pipeline_coverage_*.json")), reverse=True)
    for p in paths:
        try:
            with open(p) as f:
                summary = json.load(f).get("backtest_summary")
        except (OSError, ValueError):
            continue
        if summary:
            return summary
    return None
