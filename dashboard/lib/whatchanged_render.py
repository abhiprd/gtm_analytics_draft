"""Streamlit rendering of the Digest's "What changed" block: the ranked bar (built by
whatchanged_figure.py), its color key and the table-view twin. The pure rules live in
whatchanged_view.py."""
from typing import Dict, List

import streamlit as st

import theme
from . import whatchanged_view as view
from .whatchanged_figure import BAR_COLOR, KEY_TEXT, figure


def color_key(rs: List[Dict]) -> str:
    kinds = [k for k in (view.FAVORABLE, view.UNFAVORABLE, view.NEUTRAL) if any(r["kind"] == k for r in rs)]
    items = "".join(
        f'<span style="display:inline-flex;align-items:center;margin-right:18px;">'
        f'<span style="display:inline-block;width:12px;height:12px;border-radius:{theme.RADIUS_MARK}px;'
        f'background:{BAR_COLOR[k]};margin-right:8px;flex:none;"></span>{theme.escape_html(KEY_TEXT[k])}</span>'
        for k in kinds
    )
    return f'<div class="section-note" style="margin:0 0 8px 0;">{items}</div>'


def render(rs: List[Dict], key: str) -> None:
    """The chart, its color key and the table-view twin."""
    if not rs:
        return
    st.markdown(color_key(rs), unsafe_allow_html=True)
    st.plotly_chart(figure(rs), width="stretch", key=key, config={"displayModeBar": False})
    with st.expander("Table view"):
        theme.table(view.table_rows(rs))
