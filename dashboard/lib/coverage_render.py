"""Streamlit rendering of the Forecast page's pipeline-coverage section (the pure
rules live in coverage_view.py). Every figure is an artifact field or display string;
nothing is computed here. Cards come from theme.scorecard_row, so a row is one CSS grid
of equal-height cards (conventions Section 4.9).

Key sentences use the page's body-small style (`.note-line`, navy on the page fill), not
st.caption, whose gray measures below the 4.5:1 AA floor (Section 2.5). ISO dates in any
section text are set with non-breaking hyphens so a date never wraps mid-date.
"""
from typing import Dict, Optional

import streamlit as st

import theme
from . import coverage_view as view

_keep = view.keep_dates_whole


def _flush_chip(text: str) -> str:
    """A neutral chip with no left margin, for a chip that starts a line."""
    return theme.neutral_chip(text).replace('class="repeat-chip"', 'class="repeat-chip" style="margin-left:0"')


def _body_small(text: str) -> None:
    st.markdown(f'<div class="note-line">{theme.escape_html(_keep(text))}</div>', unsafe_allow_html=True)


def _block(inner_html: str) -> None:
    """One white card around caller-built (already escaped) HTML. Unlike theme.card_block
    its single grid column is minmax(0, 1fr), so wide content scrolls inside the card
    instead of stretching the card past a narrow viewport."""
    st.markdown(
        '<div class="card-grid single" style="grid-template-columns:minmax(0,1fr)">'
        f'<div class="grid-card" style="min-width:0"><div style="min-width:0">{inner_html}</div></div></div>',
        unsafe_allow_html=True,
    )


def _segment_heading(segment: str, chip: Optional[str]) -> None:
    color = theme.SEGMENT_COLOR.get(segment, theme.NEUTRAL_GRAY)
    chip_html = theme.neutral_chip(_keep(chip)) if chip else ""
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
    lines = "".join(f"<div>{theme.escape_html(_keep(line))}</div>" for line in block["lines"])
    chips = "".join(theme.neutral_chip(c) for c in block["chips"])
    since = f" since {block['window_start']}" if block.get("window_start") else ""
    _block(
        f'<div class="card-label">{theme.escape_html(block["title"])}{chips}</div>'
        f'<div style="font-size:0.9rem;line-height:1.5;margin-top:6px;">{lines}</div>'
        f'<div class="card-foot">{theme.escape_html(_keep("Basis: closed Enterprise new-business deals" + since))}</div>'
    )


def _render_segment(seg: Dict, reading: Dict, backtest_summary: Optional[Dict]) -> None:
    segment = seg["segment"]
    if seg.get("status") != "present":
        _segment_heading(segment, None)
        st.info(theme.escape_md(_keep(view.unavailable_message(seg, reading.get("data_window")))))
        return
    _segment_heading(segment, view.status_chip(seg, reading.get("status_rule")))
    summary = view.segment_summary(seg)
    if summary:
        _body_small(summary)
    qualifier = view.segment_qualifier(segment, backtest_summary)
    if qualifier:
        _body_small(qualifier)
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
        st.info(theme.escape_md(_keep(nq["message"])))
        with st.expander("Why this is blank"):
            st.write(f"**Reason:** {theme.escape_md(_keep(nq['detail']))}")
            st.write(f"**Needed:** {theme.escape_md(_keep(nq['needed']))}")
            st.write(f"**Component status:** {theme.status_label('pipeline_coverage')}")
        return
    rows = "".join(
        f'<div style="margin-bottom:4px;"><span class="pillar-dot" '
        f'style="background-color:{theme.SEGMENT_COLOR.get(seg, theme.NEUTRAL_GRAY)}"></span>'
        f'<strong>{theme.escape_html(seg)}:</strong> {theme.escape_html(_keep(text))}</div>'
        for seg, text in nq["lines"]
    )
    _block(
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
    hidden = "".join(f"<div>{theme.escape_html(n)}</div>" for n in rec["hidden_notes"])
    table = ""
    if rec["rows"]:
        head = "".join(f"<th>{theme.escape_html(h)}</th>" for h in rec["headers"])
        body = "".join(
            "<tr>" + "".join(f"<td>{theme.escape_html(c)}</td>" for c in row) + "</tr>" for row in rec["rows"]
        )
        # The table scrolls sideways inside the card on a narrow viewport; the explanation
        # and basis lines below it wrap normally and are never cut off.
        table = (f'<div style="overflow-x:auto;max-width:100%"><table class="answer-table" '
                 f'style="min-width:720px"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
    foot = ""
    if rec["rows"]:
        foot += (f'<div class="card-foot">{theme.escape_html(rec["tie_text"])} {theme.escape_html(rec["explanation"])}</div>'
                 '<div class="card-foot">Basis: forecast manager lens, new-business deals, same evaluation date</div>')
    if hidden:
        foot += f'<div class="card-foot">{hidden}</div>'
    if table or foot:
        _block(table + foot)


def render_header(label: str) -> None:
    st.subheader("Pipeline coverage")
    st.markdown(
        f'{_flush_chip(label[:1].upper() + label[1:])}'
        '<span style="margin-left:10px;color:#4B5563;font-size:0.9rem;">'
        'Whether open new-business pipeline, at the recent win rate, covers the quota still to book this quarter.'
        '</span>',
        unsafe_allow_html=True,
    )


def render_reading(reading: Dict, backtest_summary: Optional[Dict] = None,
                   mid_quarter_date: Optional[str] = None) -> Dict:
    """Render the section body for one reading and return its next-quarter view."""
    built = theme.is_built("pipeline_coverage")
    status_text = view.artifact_status_text(theme.status_label("pipeline_coverage"), built)
    note = view.evaluation_point_note(reading.get("as_of_date"), mid_quarter_date)
    if note:
        st.markdown(f'<div class="note-line" style="margin-top:6px"><strong>{theme.escape_html(_keep(note))}'
                    '</strong></div>', unsafe_allow_html=True)
    theme.info_row(view.info_items(reading, status_text))
    _body_small(view.scope_line(reading))
    for seg in reading.get("segments") or []:
        _render_segment(seg, reading, backtest_summary)
    hidden = view.hidden_segments(reading)
    nq = view.next_quarter_view(reading.get("next_quarter"), reading.get("data_window"), hidden)
    _render_next_quarter(nq)
    _render_reconciliation(view.reconciliation_view(reading.get("reconciliation"), hidden))
    return nq
