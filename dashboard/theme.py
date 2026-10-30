"""Shared visual theme for every dashboard page: the mechanical enforcement of
dashboard-design-conventions Section 9's "set the palette and fonts once" rule. No page
should hardcode a hex code, a font name or a font size, or reimplement the
scorecard/status/honesty patterns below; import them from here instead.

The palette, text tokens, type scale and radii are not this module's own decisions:
they are defined in tokens.py, which transcribes .claude/skills/dashboard-design-conventions/SKILL.md
Sections 2 and 5.3-5.5. Changing one means updating that skill file first.
"""
import json
import os
from typing import Optional

import plotly.graph_objects as go
import streamlit as st

from tokens import *  # noqa: F401,F403  (re-exported: pages use theme.GROWTH_NAVY etc.)
import tokens as _t
from chartkit import PLOTLY_FONT, PLOTLY_TEXT_SECONDARY, plotly_layout, style_axes  # noqa: F401
from lib import cards as _cards


def _css() -> str:
    t = _t
    return f"""
        :root {{
            --ink: {t.INK};
            --ink-2: {t.TEXT_SECONDARY};
            --grid: {t.GRID_LINE};
            --card-border: {t.CARD_BORDER};
            --fs-xs: {t.FS_XS}px;
            --fs-sm: {t.FS_SM}px;
            --fs-md: {t.FS_MD}px;
            --fs-lg: {t.FS_LG}px;
            --fs-xl: {t.FS_XL}px;
            --fs-2xl: {t.FS_2XL}px;
            --r-container: {t.RADIUS_CONTAINER}px;
            --r-control: {t.RADIUS_CONTROL}px;
            --r-mark: {t.RADIUS_MARK}px;
        }}
        .stApp {{ background-color: {t.BACKGROUND_OFF_WHITE}; color: var(--ink); }}
        /* One family and six sizes on every element: native widgets are snapped to the
        scale here, and the custom cards below use the same tokens. */
        .stApp h1 {{ font-size: var(--fs-2xl) !important; font-weight: 700 !important; line-height: 1.15 !important; letter-spacing: -0.01em; }}
        .stApp h2 {{ font-size: var(--fs-xl) !important; font-weight: 600 !important; line-height: 1.2 !important; }}
        .stApp h3, .stApp h4, .stApp h5, .stApp h6 {{ font-size: var(--fs-lg) !important; font-weight: 600 !important; line-height: 1.3 !important; }}
        .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {{ color: var(--ink); }}
        .stApp, .stApp p, .stApp li {{ font-size: var(--fs-md); }}
        /* Secondary text is a color token at full opacity, never an opacity: Streamlit's
        default caption (0.6 opacity) measures 3.9:1. */
        [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] *,
        .stCaption, .stCaption * {{
            color: var(--ink-2) !important; opacity: 1 !important;
            font-size: var(--fs-sm) !important; line-height: 1.45;
        }}
        [data-testid="stMarkdownContainer"] p, [data-testid="stCaptionContainer"], [data-testid="stAlert"] p {{ max-width: {t.PROSE_CH}ch; }}
        [data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p, label p {{
            font-size: var(--fs-sm) !important; color: var(--ink-2) !important; opacity: 1 !important;
        }}
        [data-testid="stTooltipIcon"], [data-testid="stTooltipIcon"] svg {{ color: var(--ink-2) !important; opacity: 1 !important; }}
        button[data-baseweb="tab"] p {{ font-size: var(--fs-md) !important; font-weight: 500; }}
        button[data-baseweb="tab"][aria-selected="false"] p {{ color: var(--ink-2) !important; }}
        [data-testid="stSidebarNav"] * {{ font-size: var(--fs-sm) !important; }}
        [data-testid="stSidebar"] {{ font-size: var(--fs-sm); }}
        [data-testid="stSidebarCollapseButton"] *, [data-testid="stExpandSidebarButton"] *, [data-testid="stSidebarCollapsedControl"] * {{
            color: var(--ink-2) !important; opacity: 1 !important; font-size: var(--fs-lg) !important;
        }}
        [data-testid="stPageLink"] * {{ font-size: var(--fs-md) !important; }}
        [data-testid="stDateInput"] span, [data-testid="stDateInput"] input {{ color: var(--ink) !important; opacity: 1 !important; -webkit-text-fill-color: var(--ink) !important; }}
        /* A focused date segment is painted with the primary (ink) fill, so its text is the surface color. */
        [data-testid="stDateInput"] [role="spinbutton"]:focus {{ color: {t.SURFACE} !important; -webkit-text-fill-color: {t.SURFACE} !important; }}
        [data-testid="stExpander"] summary, [data-testid="stExpander"] summary p {{ font-size: var(--fs-md) !important; }}
        [data-testid="stExpander"] details {{ border-radius: var(--r-container) !important; border-color: var(--card-border) !important; background: {t.SURFACE}; }}
        [data-testid="stAlert"] {{ border-radius: var(--r-container) !important; }}
        [data-testid="stAlert"] p {{ font-size: var(--fs-md) !important; }}
        input, textarea, [data-baseweb="select"] > div {{ font-size: var(--fs-md) !important; }}
        input::placeholder, textarea::placeholder {{ color: var(--ink-2) !important; opacity: 1 !important; }}
        .pillar-dot {{
            display: inline-block; width: 10px; height: 10px; border-radius: 50%;
            margin-right: 8px; vertical-align: middle; flex: none;
        }}
        .card-label {{ font-size: var(--fs-sm); font-weight: 500; color: var(--ink-2); line-height: 1.3; }}
        /* One card anatomy for every page (Section 4.9): a CSS grid in a single markdown
        call, so cards in a row end at the same height. */
        /* Card grids pick their column count from the container's width (container queries on the
        wrapper), never from a fixed count: a tile is never narrower than TILE_MIN_PX, so labels,
        values and units fit at any viewport. Words never break mid-word inside a card. */
        .card-grid-wrap {{ container-type: inline-size; }}
        .card-grid {{ display: grid; gap: {t.GRID_GAP_PX}px; align-items: stretch; margin: 4px 0 16px 0; grid-template-columns: minmax(0, 1fr); }}
        @container (min-width: {2 * t.TILE_MIN_PX + t.GRID_GAP_PX}px) {{
            .card-grid[data-n="2"], .card-grid[data-n="3"], .card-grid[data-n="4"] {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
            .card-grid[data-odd="1"][data-n="3"] > :last-child, .card-grid[data-odd="1"][data-n="4"] > :last-child {{ grid-column: 1 / -1; }}
        }}
        @container (min-width: {3 * t.TILE_MIN_PX + 2 * t.GRID_GAP_PX}px) {{
            .card-grid[data-n="3"] {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
            .card-grid[data-odd="1"][data-n="3"] > :last-child {{ grid-column: auto; }}
        }}
        @container (min-width: {4 * t.TILE_MIN_PX + 3 * t.GRID_GAP_PX}px) {{
            .card-grid[data-n="4"] {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
            .card-grid[data-odd="1"][data-n="4"] > :last-child {{ grid-column: auto; }}
        }}
        .grid-card, .grid-card * {{ overflow-wrap: normal; word-break: normal; hyphens: none; }}
        .grid-card {{
            background-color: {t.SURFACE}; border: 1px solid var(--card-border);
            border-radius: var(--r-container); padding: 16px; min-width: 0;
            display: flex; flex-direction: column;
        }}
        .grid-card > .card-foot:last-child {{ margin-top: auto; padding-top: 8px; }}
        .info-grid {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(min(150px, 100%), 1fr)); }}
        .info-wide {{ grid-column: span 2; }}
        @container (max-width: 349px) {{ .info-wide {{ grid-column: 1 / -1; }} }}
        .info-label {{ font-size: var(--fs-sm); color: var(--ink-2); line-height: 1.3; }}
        .info-value {{ font-size: var(--fs-md); font-weight: 600; line-height: 1.4; margin-top: 2px; }}
        .card-tag, .repeat-chip, .source-chip {{
            display: inline-block; border: 1px solid #D1D5DB; border-radius: 999px;
            background-color: {t.SURFACE}; color: var(--ink-2); font-size: var(--fs-xs);
            font-weight: 500; padding: 1px 10px; line-height: 1.5;
        }}
        .card-tag {{ align-self: flex-start; margin-top: 8px; border-radius: var(--r-container); white-space: normal; max-width: 100%; }}
        .repeat-chip {{ margin-left: 10px; vertical-align: middle; }}
        .source-chip {{ margin: 0 4px 4px 0; }}
        .card-head {{ display: flex; align-items: flex-start; min-height: 2.6em; line-height: 1.3; }}
        .card-head .pillar-dot {{ margin-top: 4px; }}
        .card-head .card-label {{ flex: 1; min-width: 0; }}
        .tile-delta-row {{ display: flex; justify-content: space-between; align-items: flex-start; }}
        .tile-flag {{ flex: none; margin-left: 8px; color: var(--ink-2); font-size: var(--fs-sm); line-height: 1.3; cursor: help; }}
        .card-value {{
            font-size: var(--fs-xl); font-weight: 600; line-height: 1.15; margin-top: 4px;
            font-variant-numeric: proportional-nums; letter-spacing: -0.01em;
        }}
        .card-value.sm {{ font-size: var(--fs-lg); line-height: 1.4; letter-spacing: 0; }}
        .card-value.nw, .card-num {{ white-space: nowrap; }}
        .card-unit {{ display: inline-block; white-space: nowrap; font-size: var(--fs-sm); font-weight: 500; letter-spacing: 0; }}
        .tile-delta {{ font-size: var(--fs-sm); font-weight: 600; line-height: 1.4; margin-top: 8px; }}
        .tile-vs {{ font-size: var(--fs-sm); color: var(--ink-2); line-height: 1.4; margin-top: 2px; }}
        .tile-spark-row {{ margin-top: 10px; line-height: 0; }}
        .tile-spark {{ display: block; }}
        .card-foot {{ color: var(--ink-2); font-size: var(--fs-xs); line-height: 1.4; margin-top: 8px; }}
        .tile-about {{ margin-top: auto; padding-top: 12px; }}
        .tile-about summary {{
            font-size: var(--fs-xs); color: var(--ink-2); cursor: pointer; list-style: none; white-space: nowrap;
            line-height: 1.4; text-decoration: underline; text-underline-offset: 3px;
        }}
        .tile-about summary::-webkit-details-marker {{ display: none; }}
        .tile-about summary::before {{ content: "▸\u00a0"; text-decoration: none; display: inline-block; }}
        .tile-about[open] summary::before {{ content: "▾\u00a0"; }}
        .about-body {{ margin-top: 8px; font-size: var(--fs-xs); line-height: 1.45; color: var(--ink-2); }}
        .about-row {{ margin-bottom: 6px; }}
        .about-k {{ display: block; font-weight: 600; color: var(--ink); }}
        .note-line {{ margin: 0 0 6px 0; font-size: var(--fs-sm); line-height: 1.5; max-width: {t.PROSE_CH}ch; }}
        .note-details {{ display: inline; }}
        .note-details summary {{ display: inline; cursor: pointer; color: var(--ink-2); font-size: var(--fs-xs); margin-left: 6px; text-decoration: underline; text-underline-offset: 3px; }}
        .note-details div {{ margin-top: 4px; color: var(--ink-2); }}
        .section-note {{ font-size: var(--fs-sm); line-height: 1.5; max-width: {t.PROSE_CH}ch; color: var(--ink-2); margin: 0 0 12px 0; }}
        .section-note strong {{ color: var(--ink); }}
        .compact-notice {{ margin: 4px 0 16px 0; padding: 12px 16px; background: {t.SURFACE}; border: 1px solid var(--card-border); border-radius: var(--r-container); }}
        .prose {{ font-size: var(--fs-md); line-height: 1.5; max-width: {t.PROSE_CH}ch; margin: 0 0 8px 0; }}
        .prose.lead {{ font-size: var(--fs-lg); font-weight: 500; line-height: 1.4; margin-bottom: 12px; }}
        .inline-note {{ margin-left: 10px; color: var(--ink-2); font-size: var(--fs-sm); }}
        .block-heading {{ font-size: var(--fs-lg); font-weight: 600; line-height: 1.3; }}
        .status-mark {{ display: inline-flex; align-items: center; gap: 8px; }}
        .status-mark svg {{ flex: none; }}
        /* Narrow viewports: tighter card padding and 44px tap targets. */
        @media (max-width: 640px) {{
            .grid-card {{ padding: 12px; }}
            /* a disclosure is a tap target: 44px tall with the text size unchanged */
            .tile-about summary, .note-details summary {{ display: inline-block; padding: 13px 8px 13px 0; }}
            .tile-about {{ padding-top: 0; }}
            [data-testid="stExpander"] summary {{ min-height: 44px; padding-top: 10px; padding-bottom: 10px; }}
        }}
        /* Plotly draws lines with square joins by default; Section 3.2 asks for round. */
        .js-plotly-plot .scatterlayer .trace path.js-line {{ stroke-linejoin: round; stroke-linecap: round; }}
        .breadcrumb {{ color: var(--ink-2); font-size: var(--fs-sm); line-height: 1.45; max-width: {t.PROSE_CH}ch; }}
        .card-foot, .about-body, .note-details div {{ max-width: {t.PROSE_CH}ch; }}
        /* Metric-tree panel (Ask the Metric Tree, Section 4.7): node buttons are
        left-aligned text rows, node metadata is one small line. */
        [data-testid="stSidebar"] .stButton button {{
            justify-content: flex-start; text-align: left; min-height: 0; padding: 2px 6px; width: 100%;
        }}
        [data-testid="stSidebar"] .stButton button > div,
        [data-testid="stSidebar"] .stButton button span,
        [data-testid="stSidebar"] .stButton button [data-testid="stMarkdownContainer"] {{
            width: 100%; justify-content: flex-start; overflow: visible; text-overflow: clip; white-space: normal;
        }}
        [data-testid="stSidebar"] [data-testid="stTooltipHoverTarget"] {{ justify-content: flex-start !important; }}
        [data-testid="stSidebar"] .stButton button p {{
            font-size: var(--fs-sm) !important; text-align: left; line-height: 1.25;
            white-space: normal; overflow: visible; text-overflow: clip;
        }}
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap: 0.45rem; }}
        /* Chat avatars default to red and orange fills, which read as Palette B status
        colors (Section 2.3); neutral gray carries no judgment. */
        [data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] {{
            background-color: {t.NEUTRAL_GRAY} !important;
        }}
        .tree-meta {{ color: var(--ink-2); font-size: var(--fs-xs); margin: -6px 0 4px 6px; line-height: 1.25; display: flex; flex-wrap: wrap; gap: 0 12px; }}
        .meta-row {{ display: flex; flex-wrap: wrap; gap: 2px 16px; }}
        .tree-legend {{ font-size: var(--fs-xs); color: var(--ink-2); line-height: 1.5; margin: 4px 0 8px 0; }}
        .tree-legend-title {{ font-weight: 600; color: var(--ink); font-size: var(--fs-sm); }}
        .legend-glyph {{ display: inline-block; width: 1.4em; }}
        .tree-pillar {{ font-weight: 600; font-size: var(--fs-md); margin: 12px 0 2px 0; }}
        .answer-table, .answer-table th, .answer-table td {{ border: none; }}
        .answer-table {{ width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }}
        .answer-table th {{
            text-align: left; font-size: var(--fs-sm); font-weight: 600; color: var(--ink-2);
            padding: 4px 8px 6px 0; border-bottom: 1px solid var(--grid) !important;
        }}
        .answer-table td {{ vertical-align: top; padding: 8px 8px 8px 0; border-bottom: 1px solid #F1F2F4 !important; font-variant-numeric: tabular-nums; }}
        .answer-table tr:last-child td {{ border-bottom: none !important; }}
        .answer-table .reason {{ color: var(--ink-2); font-size: var(--fs-xs); line-height: 1.4; }}
        .source-row {{ margin-bottom: 6px; }}
        .kv-list {{ font-size: var(--fs-sm); line-height: 1.45; max-width: 90ch; }}
        .kv-row {{ display: flex; flex-wrap: wrap; gap: 0 16px; padding: 6px 0; border-bottom: 1px solid #F1F2F4; }}
        .kv-row:last-child {{ border-bottom: none; }}
        .kv-k {{ flex: 0 0 11em; color: var(--ink-2); }}
        .kv-v {{ flex: 1 1 14em; min-width: 0; overflow-wrap: anywhere; }}
        .table-wrap {{ background: {t.SURFACE}; border: 1px solid var(--card-border); border-radius: var(--r-container); padding: 4px 12px 4px 12px; overflow-x: auto; max-width: 100%; margin: 4px 0 16px 0; }}
        .data-table {{ width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }}
        .data-table th, .data-table td {{ border-left: none !important; border-right: none !important; }}
        .data-table th {{ position: sticky; top: 0; background: {t.SURFACE}; text-align: left; font-weight: 600; color: var(--ink-2); padding: 8px 12px 8px 0; border-bottom: 1px solid var(--grid); vertical-align: bottom; }}
        .data-table td {{ vertical-align: top; padding: 8px 12px 8px 0; border-bottom: 1px solid #F1F2F4; }}
        .data-table tr:last-child td {{ border-bottom: none; }}
        .data-table th.num, .data-table td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    """


def inject_global_css() -> None:
    """Call once at the top of every page (main script or subpage). Injects the base
    typography, token and card CSS so no page repeats hex codes or font names inline.
    The font is Streamlit's bundled Source Sans, set in .streamlit/config.toml, so the
    custom cards inherit it and nothing is fetched from outside."""
    st.markdown(f"<style>{_css()}</style>", unsafe_allow_html=True)


def status_text_color(favorable_direction: Optional[str], is_ahead: Optional[bool]) -> str:
    """Text color for a status judgment: Palette B green or red when a judgment applies,
    otherwise the secondary text token (the neutral gray of Palette B is for marks, not
    text, Section 2.6)."""
    if favorable_direction is None or is_ahead is None:
        return TEXT_SECONDARY
    return FAVORABLE_GREEN if is_ahead else UNFAVORABLE_RED


def delta_glyph(text: Optional[str]) -> str:
    """Direction glyph for a displayed change (sign of the number, never the judgment)."""
    from lib import verdict
    return verdict.delta_glyph(text)


def scorecard_row(cards: list, columns: Optional[int] = None) -> None:
    """A row of stat tiles as one CSS grid in a single markdown call, so every tile in
    the row stretches to the tallest one (Section 5.2, uneven card fill; st.columns()
    cannot equalize heights). `cards` is a list of dicts with lib/cards.card_inner's
    keys. `columns` fixes the grid width when rows of different length should share one
    tile width (the Digest's pillars). The only card implementation on the dashboard:
    one card is a row of one."""
    if not cards:
        return
    cells = "".join(f'<div class="grid-card">{_cards.card_inner(c)}</div>' for c in cards)
    n = max(1, min(columns or len(cards), 4))
    odd = ' data-odd="1"' if len(cards) % 2 else ""
    st.markdown(
        f'<div class="card-grid-wrap"><div class="card-grid" data-n="{n}"{odd}>{cells}</div></div>',
        unsafe_allow_html=True,
    )


def scorecard(
    label: str,
    value_display: str,
    pillar: Optional[str] = None,
    comparison_display: Optional[str] = None,
    variance_display: Optional[str] = None,
    favorable_direction: Optional[str] = None,
    is_ahead: Optional[bool] = None,
    footer: Optional[list] = None,
    **extra,
) -> None:
    """One scorecard (a row of one). `is_ahead=None` renders the delta in neutral
    gray with no judgment, per Section 7."""
    scorecard_row([dict(
        label=label, value_display=value_display, pillar=pillar, comparison_display=comparison_display,
        variance_display=variance_display, favorable_direction=favorable_direction, is_ahead=is_ahead,
        footer=footer, **extra)])


def info_row(items: list, columns: Optional[int] = None) -> None:
    """A single white block of label/value pairs (as-of date, grain, threshold): the
    Section 7 context row. `items` is a list of (label, value) tuples; values are
    escaped; an optional third element widens a cell by that many columns. Labels are sentence case; a value never joins several facts with a middle
    dot (Section 5.3), so each fact is its own cell."""
    spans = [(it[2] if len(it) > 2 else 1) for it in items]
    cells = "".join(
        f'<div class="{"info-wide" if span > 1 else ""}"><div class="info-label">{escape_html(it[0])}</div>'
        f'<div class="info-value">{escape_html(it[1])}</div></div>'
        for it, span in zip(items, spans)
    )
    st.markdown(
        f'<div class="card-grid-wrap"><div class="card-grid single"><div class="grid-card">'
        f'<div class="info-grid">{cells}</div></div></div></div>',
        unsafe_allow_html=True,
    )


def status_mark(kind: str, label: str) -> str:
    """HTML for a status icon shape paired with its word label. `caution` is an amber
    triangle (a non-text fill, never amber text), `neutral` a gray circle; the label is
    text-token ink. Escaped."""
    if kind == "caution":
        icon = (f'<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">'
                f'<path d="M8 1.5 15 14H1z" fill="{CAUTION_AMBER}" stroke="{CAUTION_AMBER}" '
                f'stroke-width="1" stroke-linejoin="round"/></svg>')
    else:
        icon = (f'<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">'
                f'<circle cx="8" cy="8" r="5" fill="{NEUTRAL_GRAY}"/></svg>')
    return f'<span class="status-mark">{icon}<span>{escape_html(label)}</span></span>'


def compact_notice(headline: str, reason: str, details: list) -> None:
    """A slim notice for a component that is not available: one bold line, the reason on
    the next, and the "Why this is blank" disclosure (conventions Sections 4.8 and 7)
    holding `details`, a list of (label, text) pairs. The gap is stated on the face of
    the page and the detail is one click away. Escaped."""
    rows = "".join(
        f'<div class="about-row"><span class="about-k">{escape_html(k)}</span>{escape_html(v)}</div>'
        for k, v in details)
    st.markdown(
        f'<div class="compact-notice"><div class="section-note" style="margin:0;"><strong>{escape_html(headline)}.</strong> '
        f'{escape_html(reason)}</div>'
        f'<details class="tile-about" style="padding-top:6px;"><summary>Why this is blank</summary>'
        f'<div class="about-body">{rows}</div></details></div>',
        unsafe_allow_html=True,
    )


def table(data, numeric_columns=None, max_height=None) -> None:
    """A table as HTML in the page's own type and colors (a canvas dataframe draws its header
    below the 4.5:1 floor and cannot be styled). `data` is a DataFrame or a list of dicts;
    cells are escaped; numeric columns (by dtype, or named in `numeric_columns`) are right-aligned
    with tabular figures. The table is as tall as its rows, so it never scrolls inside the page,
    and scrolls sideways inside its own card only when a narrow screen cannot fit it. The one
    exception is a long archive inside a closed expander (a full monthly history, an older
    trigger log): pass `max_height` (px) and it scrolls inside that card with a sticky header."""
    import pandas as pd
    df = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    numeric = set(numeric_columns or []) | {c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])}

    def cell(v) -> str:
        return "" if v is None or (isinstance(v, float) and v != v) else escape_html(v)

    head = "".join(f'<th class="{"num" if c in numeric else ""}">{escape_html(c)}</th>' for c in df.columns)
    body = "".join(
        "<tr>" + "".join(f'<td class="{"num" if c in numeric else ""}">{cell(v)}</td>'
                         for c, v in zip(df.columns, row)) + "</tr>"
        for row in df.itertuples(index=False, name=None))
    style = f' style="max-height:{int(max_height)}px;overflow-y:auto;"' if max_height else ""
    st.markdown(f'<div class="table-wrap"{style}><table class="data-table"><thead><tr>{head}</tr></thead>'
                f'<tbody>{body}</tbody></table></div>', unsafe_allow_html=True)


def kv_list(pairs) -> None:
    """A label-and-value list in the page's own type (replaces raw JSON and code blocks, which
    render in a second monospace family at an off-scale size). `pairs` is (label, text); empty
    values are skipped; text is escaped."""
    rows = "".join(
        f'<div class="kv-row"><span class="kv-k">{escape_html(k)}</span><span class="kv-v">{escape_html(v)}</span></div>'
        for k, v in pairs if v not in (None, "", [], {}))
    st.markdown(f'<div class="kv-list">{rows}</div>', unsafe_allow_html=True)


def section_note(text: str) -> None:
    """One short secondary-text line under a section heading (<= 75ch). Escaped."""
    st.markdown(f'<div class="section-note">{escape_html(text)}</div>', unsafe_allow_html=True)


def neutral_chip(text: str) -> str:
    """HTML for a compact neutral-gray chip (a marker, never a status). Escaped."""
    return f'<span class="repeat-chip">{escape_html(text)}</span>'


def card_block(inner_html: str) -> None:
    """One white card around caller-built HTML (already escaped by the caller)."""
    st.markdown(f'<div class="card-grid single"><div class="grid-card"><div>{inner_html}</div></div></div>',
                unsafe_allow_html=True)


def escape_html(text) -> str:
    return _cards.escape_html(text)


def page_config(title: str, icon: str) -> None:
    """Per-page config. When the app is routed by st.navigation (app.py) the entry
    script has already set it, and the router's title/icon win; the call is kept so
    a page also runs standalone."""
    try:
        st.set_page_config(page_title=title, page_icon=icon, layout="wide")
    except st.errors.StreamlitAPIException:
        pass


def override_banner() -> None:
    """Warning shown on EVERY page that reads the readout output directory when
    ACME_DASHBOARD_OUTPUTS_DIR points it at a test fixture (Section 9). Call once
    per such page, directly under the title."""
    from lib import data
    if data.OUTPUTS_OVERRIDE_ACTIVE:
        st.warning(
            f"Test/QA mode: readouts are read from {data.OUTPUTS_DIR} (ACME_DASHBOARD_OUTPUTS_DIR), "
            "not analytics/outputs. Figures may come from a test fixture."
        )


# --- Notes & assumptions: the one consistent home for every assumption,
# scope statement and data gap on a page (Section 11.3). ---

NOTE_KINDS = ("Assumption", "Scope", "Data gap")
NOTE_LINE_LIMIT = 200


def escape_md(text) -> str:
    """Literal rendering of arbitrary text in Streamlit markdown (alert boxes, captions,
    write): see lib/labels.py escape_markdown. Every st.warning/info/error/success call
    that interpolates data must wrap the data in this (tests/test_dashboard_labels.py
    enforces it)."""
    from lib import labels
    return labels.escape_markdown(text)


def note_html(kind: str, text: str, limit: int = NOTE_LINE_LIMIT) -> str:
    """One note as a short line, with any remainder behind a 'Details' toggle so the
    section stays scannable and every disclosed fact is still on the page."""
    from lib import labels
    text = labels.apply_phrase_map(text)
    short, rest = labels.first_sentences(text, limit)
    body = f'<span class="note-kind"><strong>{escape_html(kind)}:</strong></span> {escape_html(short)}'
    if rest:
        body += (f' <details class="note-details"><summary>Details</summary>'
                 f'<div>{escape_html(rest)}</div></details>')
    return f'<div class="note-line">{body}</div>'


def notes_and_assumptions(items, label: str = "Notes & assumptions") -> None:
    """Render the page's single 'Notes & assumptions' expander. `items` is an
    iterable of (kind, text) pairs with kind one of NOTE_KINDS; one short line each,
    label first, long text split behind 'Details'. Call at most once per page."""
    items = list(items)
    for kind, _ in items:
        if kind not in NOTE_KINDS:
            raise ValueError(f"note kind must be one of {NOTE_KINDS}, got {kind!r}")
    with st.expander(label):
        if not items:
            st.caption("None for this view.")
        else:
            st.markdown("".join(note_html(kind, text) for kind, text in items), unsafe_allow_html=True)


# --- project-status: the honesty-pattern source of truth (Section 7) ---

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATUS_PATH = os.path.join(_HERE, "project_status.json")


@st.cache_data(ttl=300)
def load_project_status() -> dict:
    with open(_STATUS_PATH) as f:
        return json.load(f)


def component_status(component_key: str) -> dict:
    """Look up one component's status entry. Raises KeyError loudly if a
    page references a component not registered in project_status.json --
    an unregistered component is a gap in the status file, not something
    to silently treat as built."""
    return load_project_status()["components"][component_key]


def status_label(component_key: str) -> str:
    """Reader-facing status of a component: 'In progress', 'Planned', 'Deferred'."""
    text = component_status(component_key)["status"].replace("_", " ")
    return text[:1].upper() + text[1:]


def render_pending(component_key: str, what_is_needed: Optional[str] = None) -> None:
    """The Section 7 honesty pattern, generalized: renders the same
    'not yet generated' + 'why this is blank' expander pattern the Digest
    page originated, for any component whose project_status.json status
    is not built_and_validated. Call this INSTEAD of rendering the
    component's chart/number -- never render a live-looking value and
    this pending marker together. The expander is reader-facing: the status
    label and what is needed, never the status file's internal note."""
    st.info(f"Not yet available. Status: {status_label(component_key)}.")
    with st.expander("Why this is blank"):
        st.write(f"**Status:** {status_label(component_key)}")
        if what_is_needed:
            st.write(f"**Needed:** {what_is_needed}")


def is_built(component_key: str) -> bool:
    return component_status(component_key)["status"] == "built_and_validated"
