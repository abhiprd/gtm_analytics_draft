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
OUTPUTS_DIR = os.path.join(REPO_ROOT, "analytics", "outputs")

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
