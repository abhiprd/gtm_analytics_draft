"""Segment efficiency -- Growth, Efficiency, and Durability by segment
(SMB / Commercial / Enterprise), read straight from mart_growth_bridge,
mart_efficiency, mart_durability, and mart_segment_migration. Known
raw-data gaps (Magic Number, AM Efficiency -- no rep-cost/comp data
anywhere in the raw sources) are shown as gaps, never backfilled with a
fabricated number.
"""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import data
from lib.formatting import num, pct, usd

st.set_page_config(page_title="Segment efficiency | Acme Corp GTM", page_icon="🧭", layout="wide")
st.title("Segment efficiency")
st.caption(
    "Segment is what an account IS (SMB / Commercial / Enterprise); it never implies how "
    "the account was acquired. All three pillars below are segment x month grain."
)

efficiency = data.mart_efficiency()
durability = data.mart_durability()
growth = data.mart_growth_bridge()
migration = data.mart_segment_migration()

segments = st.multiselect("Segments", list(data.SEGMENTS), default=list(data.SEGMENTS))

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

tab_growth, tab_efficiency, tab_durability, tab_migration = st.tabs(
    ["Growth", "Efficiency", "Durability", "Segment migration"]
)

with tab_growth:
    g = growth[growth["segment"].isin(segments)].copy()
    latest = g[g["month"] == snapshot_month]
    cols = st.columns(len(segments) or 1)
    for col, seg in zip(cols, segments):
        row = latest[latest["segment"] == seg]
        if row.empty:
            continue
        row = row.iloc[0]
        with col:
            st.markdown(f"**{seg}**")
            st.metric("Ending MRR", usd(row["ending_mrr"]))
            st.metric("New logo MRR", usd(row["new_logo_mrr"]))
            st.metric("Win rate", pct(row["win_rate"]))
            st.metric("Avg initial commitment", usd(row["avg_initial_commitment"]))

    st.markdown("**Ending MRR over time**")
    pivot = g.pivot_table(index="month", columns="segment", values="ending_mrr")
    st.line_chart(pivot)

with tab_efficiency:
    e = efficiency[efficiency["segment"].isin(segments)].copy()
    latest = e[e["month"] == snapshot_month]

    cols = st.columns(len(segments) or 1)
    for col, seg in zip(cols, segments):
        row = latest[latest["segment"] == seg]
        if row.empty:
            continue
        row = row.iloc[0]
        with col:
            st.markdown(f"**{seg}**")
            st.metric("Consumption payback (months)", num(row["consumption_payback_months"], 1))
            ratio = row["onboarding_cs_efficiency_ratio"]
            st.metric(
                "AM touches per 1M Actions delivered",
                "N/A" if pd.isna(ratio) else num(ratio * 1_000_000, 2),
            )
            st.metric("Magic Number", "N/A (no rep-cost data)" if pd.isna(row["magic_number"]) else num(row["magic_number"], 2))
            st.metric("AM Efficiency", "N/A (no AM-cost data)" if pd.isna(row["am_efficiency"]) else num(row["am_efficiency"], 2))

    st.caption(
        "Magic Number and AM Efficiency are null by design, not a missing-data bug: no "
        "rep-cost or AM-comp field exists anywhere in the raw sources, so the cost "
        "denominator -- and therefore the ratio -- is undefined rather than fabricated."
    )

    st.markdown("**Consumption payback over time**")
    pivot = e.pivot_table(index="month", columns="segment", values="consumption_payback_months")
    st.line_chart(pivot)

with tab_durability:
    d = durability[durability["segment"].isin(segments)].copy()
    latest = d[d["month"] == snapshot_month]

    cols = st.columns(len(segments) or 1)
    for col, seg in zip(cols, segments):
        row = latest[latest["segment"] == seg]
        if row.empty:
            continue
        row = row.iloc[0]
        with col:
            st.markdown(f"**{seg}**")
            st.metric("NRR", pct(row["nrr"]))
            st.metric("GRR", pct(row["grr"]))
            st.metric("Logo retention", pct(row["logo_retention_rate"]))

    st.markdown("**NRR over time**")
    pivot = d.pivot_table(index="month", columns="segment", values="nrr")
    st.line_chart(pivot)

with tab_migration:
    m = migration.copy()
    m["migration_date"] = pd.to_datetime(m["migration_date"])
    m = m[m["to_segment"].isin(segments) | m["from_segment"].isin(segments)]

    st.caption(
        "One row per migration event. Every row's trigger_reason is either "
        "usage_threshold or firmographic_rescore -- migration is always upward, "
        "never a downgrade."
    )
    c1, c2 = st.columns(2)
    c1.metric("Total migrations", len(m))
    c2.metric("MRR reclassified", usd(m["mrr_reclassified"].sum()))

    by_reason = m["trigger_reason"].value_counts().rename_axis("trigger_reason").reset_index(name="count")
    st.dataframe(by_reason, hide_index=True, use_container_width=True)

    by_path = (
        m.groupby(["from_segment", "to_segment"]).size()
        .rename("count").reset_index()
        .sort_values("count", ascending=False)
    )
    st.dataframe(by_path, hide_index=True, use_container_width=True)
