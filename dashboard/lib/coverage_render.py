"""Streamlit rendering of the Forecast page's pipeline-coverage section (the pure
rules live in coverage_view.py). Every figure is an artifact field or display string;
nothing is computed here. Cards come from theme.scorecard_row, so a row is one CSS grid
of equal-height cards (conventions Section 4.9)."""
from typing import Dict, Optional

import streamlit as st

import theme
from . import coverage_view as view


def _flush_chip(text: str) -> str:
    """A neutral chip with no left margin, for a chip that starts a line."""
    return theme.neutral_chip(text).replace('class="repeat-chip"', 'class="repeat-chip" style="margin-left:0"')


def _segment_heading(segment: str, chip: Optional[str]) -> None:
    color = theme.SEGMENT_COLOR.get(segment, theme.NEUTRAL_GRAY)
    chip_html = theme.neutral_chip(chip) if chip else ""
    st.markdown(
        f'<span class="pillar-dot" style="background-color:{color}"></span>'
        f'<span style="font-family:{theme.FONT_HEADER};font-size:1.3rem;font-weight:700;">'
        f'{theme.escape_html(segment)}</span>{chip_html}',
        unsafe_allow_html=True,
    )


def _render_poc(poc: Optional[Dict]) -> None:
    block = view.poc_view_block(poc)
    if not block:
        return
    lines = "".join(f"<div>{theme.escape_html(line)}</div>" for line in block["lines"])
    theme.card_block(
        f'<div class="card-label">{theme.escape_html(block["title"])}{theme.neutral_chip(block["chip"])}</div>'
        f'<div style="font-size:0.9rem;line-height:1.5;margin-top:6px;">{lines}</div>'
        f'<div class="card-foot">Basis: closed Enterprise new-business deals in the trailing 365 days</div>'
    )


def _render_segment(seg: Dict, reading: Dict) -> None:
    segment = seg["segment"]
    if seg.get("status") != "present":
        _segment_heading(segment, None)
        st.info(theme.escape_md(view.unavailable_message(seg, reading.get("data_window"))))
        return
    _segment_heading(segment, view.status_chip(seg, reading.get("status_rule")))
    summary = (seg.get("display") or {}).get("summary")
    if summary:
        st.caption(theme.escape_md(summary))
    theme.scorecard_row(view.segment_cards(seg, reading.get("period", ""), reading.get("as_of_date", "")))
    if segment == "Enterprise":
        _render_poc(seg.get("poc_view"))


def _render_next_quarter(nq: Dict) -> None:
    if nq["kind"] == "absent":
        return
    st.markdown(
        f'<span style="font-family:{theme.FONT_HEADER};font-size:1.15rem;font-weight:700;">'
        f'Next quarter: {theme.escape_html(nq["period"])}</span>{theme.neutral_chip("Indicative, no verdict")}',
        unsafe_allow_html=True,
    )
    if nq["kind"] == "unavailable":
        st.info(theme.escape_md(nq["message"]))
        with st.expander("Why this is blank"):
            st.write(f"**Reason:** {theme.escape_md(nq['detail'])}")
            st.write(f"**Needed:** {theme.escape_md(nq['needed'])}")
            st.write(f"**Component status:** {theme.status_label('pipeline_coverage')}")
        return
    rows = "".join(
        f'<div style="margin-bottom:4px;"><span class="pillar-dot" '
        f'style="background-color:{theme.SEGMENT_COLOR.get(seg, theme.NEUTRAL_GRAY)}"></span>'
        f'<strong>{theme.escape_html(seg)}:</strong> {theme.escape_html(text)}</div>'
        for seg, text in nq["lines"]
    )
    theme.card_block(
        f'<div style="font-size:0.95rem;line-height:1.5;">{rows}</div>'
        f'<div class="card-foot">{theme.escape_html(nq["note"])}</div>'
        f'<div class="card-foot">Basis: new-business deals dated to {theme.escape_html(nq["period"])}, '
        'open at the evaluation date</div>'
    )


def _render_reconciliation(rec: Dict) -> None:
    st.markdown(
        f'<span style="font-family:{theme.FONT_HEADER};font-size:1.15rem;font-weight:700;">'
        'Compared with the forecast</span>',
        unsafe_allow_html=True,
    )
    if not rec["available"]:
        st.info("Comparison with the forecast is not available for this date.")
        return
    head = "".join(f"<th>{theme.escape_html(h)}</th>" for h in rec["headers"])
    body = "".join(
        "<tr>" + "".join(f"<td>{theme.escape_html(c)}</td>" for c in row) + "</tr>" for row in rec["rows"]
    )
    theme.card_block(
        f'<table class="answer-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
        f'<div class="card-foot">{theme.escape_html(rec["tie_text"])} {theme.escape_html(rec["explanation"])}</div>'
        f'<div class="card-foot">Basis: forecast manager lens, new-business deals, same evaluation date</div>'
    )


def render_reading(reading: Dict) -> Dict:
    """Render the whole section for one reading and return its next-quarter view (the
    page does not need it; kept for tests and callers that want the state)."""
    built = theme.is_built("pipeline_coverage")
    status_text = view.artifact_status_text(theme.status_label("pipeline_coverage"), built)
    theme.info_row(view.info_items(reading, status_text))
    st.caption(theme.escape_md(view.scope_line(reading)))
    for seg in reading.get("segments") or []:
        _render_segment(seg, reading)
    nq = view.next_quarter_view(reading.get("next_quarter"), reading.get("data_window"))
    _render_next_quarter(nq)
    _render_reconciliation(view.reconciliation_view(reading.get("reconciliation")))
    return nq


def render_header(label: str) -> None:
    st.subheader("Pipeline coverage")
    st.markdown(
        f'{_flush_chip(label[:1].upper() + label[1:])}'
        '<span style="margin-left:10px;color:#4B5563;font-size:0.9rem;">'
        'Whether open new-business pipeline, at the recent win rate, covers the quota still to book this quarter.'
        '</span>',
        unsafe_allow_html=True,
    )
