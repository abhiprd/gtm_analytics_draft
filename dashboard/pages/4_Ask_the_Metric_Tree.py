"""Ask the metric tree -- a chat-style front end onto the Phase 3
semantic layer (semantic/server.py's list_metrics/get_metric_definition/
query_metric), called in-process via dashboard/lib/semantic_bridge.py.

Question routing here is deterministic keyword/substring matching against
the registry's own whitelisted names and aliases -- not an LLM call. The
natural extension point is routing through the Claude API per build spec
Section 3, the same deliberately deferred seam the weekly readout's
executive-summary narrative documents; this page demonstrates the
guardrails a live NL layer would sit on top of, honestly, rather than
faking the LLM half.
"""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import semantic_bridge as sb

st.set_page_config(page_title="Ask the metric tree | Acme Corp GTM", page_icon="💬", layout="wide")
st.title("Ask the metric tree")
st.caption(
    "Every answer here comes from query_metric() against the whitelisted metric "
    "registry -- the same guardrailed tool an MCP client (Claude Desktop, Claude Code) "
    "calls. A metric name outside the registry is rejected, not guessed at."
)

all_metrics = sb.list_metrics()["metrics"]
queryable_names = sorted(
    m["name"] for m in all_metrics if m["computable"] and m["additive"]
)

st.markdown("#### Ask a question")
example = "e.g. \"What was win rate for Enterprise last year?\" or \"Show me NRR by segment\""
question = st.text_input("Question", placeholder=example)

if question:
    parsed = sb.parse_question(question)
    with st.expander("How this was routed", expanded=False):
        st.json(parsed)

    metric_key = parsed["resolved_metric"]
    if metric_key is None:
        st.warning("No exact match in the whitelisted registry for that question.")
        if parsed["suggestions"]:
            st.write("Closest registered names:")
            for s in parsed["suggestions"]:
                st.markdown(f"- {s}")
        st.info("Pick a metric from the browser below instead.")
    else:
        result = sb.query_metric(
            metric_key,
            dimensions=parsed["dimensions"],
            filters=parsed["filters"],
            grain=parsed["grain"],
        )
        if "error" in result:
            st.error(f"{result['error']}: {result['message']}")
        else:
            metric = result["metric"]
            st.success(f"Resolved to **{metric['name']}** ({metric['pillar']}, Layer {metric['layer']})")
            st.caption(f"{metric['formula']}{metric.get('formula_note') or ''}")

            df = pd.DataFrame(result["data"])
            if df.empty:
                st.info("Query returned no rows for this filter/date range.")
            else:
                if "segment" in df.columns and len(df["segment"].unique()) > 1:
                    pivot = df.pivot_table(index="period", columns="segment", values="value")
                    st.line_chart(pivot)
                else:
                    chart_df = df.set_index("period")[["value"]]
                    st.line_chart(chart_df)
                st.dataframe(df, hide_index=True, use_container_width=True)

            for w in result.get("warnings") or []:
                st.warning(w)
            with st.expander("SQL executed"):
                st.code(result["sql"], language="sql")

st.divider()
st.markdown("#### Browse the whitelist")
picked = st.selectbox("Metric", ["--"] + queryable_names)
if picked != "--":
    definition = sb.get_metric_definition(picked)["metric"]
    st.write(definition)
