"""Shared visual theme for every dashboard page -- the mechanical
enforcement of dashboard-design-conventions.md Section 9's "set the
palette and fonts once" rule. No page should hardcode a hex code, a font
name, or reimplement the scorecard/status/honesty patterns below; import
them from here instead.

Palette and font choices are not this module's own decisions -- they are
transcribed from .claude/skills/dashboard-design-conventions/SKILL.md
Sections 2 and 5.4 verbatim. Changing a color or font here means updating
that skill file first, not the other way around.
"""
import json
import os
from typing import Optional

import plotly.graph_objects as go
import streamlit as st

# --- Palette A: pillar/category identity (Section 2.2) -- never used for
# status judgment. ---
GROWTH_NAVY = "#1E2761"
GROWTH_ICE_BLUE = "#CADCFC"
EFFICIENCY_TEAL = "#1C7293"
DURABILITY_TERRACOTTA = "#B85042"
BACKGROUND_OFF_WHITE = "#F7F8FA"

PILLAR_COLOR = {
    "growth": GROWTH_NAVY,
    "efficiency": EFFICIENCY_TEAL,
    "durability": DURABILITY_TERRACOTTA,
}

# --- Palette B: performance/status semantics (Section 2.3) -- never used
# for category identity. ---
FAVORABLE_GREEN = "#2E7D4F"
UNFAVORABLE_RED = "#C0392B"
CAUTION_AMBER = "#D89614"
NEUTRAL_GRAY = "#6B7280"

# --- Segment palette (Section 2.4) -- its own hue family, outside both
# Palette A and Palette B, so a segment chart is never misread as a
# pillar or status chart. ---
SEGMENT_COLOR = {
    "SMB": "#94A3B8",
    "Commercial": "#475569",
    "Enterprise": "#1E293B",
}

# --- Fonts (Section 5.4) ---
FONT_HEADER = "'Source Serif 4', Georgia, serif"
FONT_BODY = "'Inter', -apple-system, sans-serif"

_GOOGLE_FONTS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Source+Serif+4:wght@600;700&family=Inter:wght@400;500;600&display=swap"
)


def inject_global_css() -> None:
    """Call once at the top of every page (main script or subpage).
    Injects the Google Fonts link and base typography/card CSS so no page
    repeats hex codes or font names inline."""
    st.markdown(
        f"""
        <link rel="stylesheet" href="{_GOOGLE_FONTS_URL}">
        <style>
        html, body, [class*="css"] {{
            font-family: {FONT_BODY};
            color: {GROWTH_NAVY};
        }}
        h1, h2, h3, .dashboard-header {{
            font-family: {FONT_HEADER} !important;
            color: {GROWTH_NAVY};
        }}
        .stApp {{
            background-color: {BACKGROUND_OFF_WHITE};
        }}
        .pillar-dot {{
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 6px;
            vertical-align: middle;
        }}
        .card-label {{
            font-size: 0.85rem;
            font-weight: 500;
            color: {NEUTRAL_GRAY};
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }}
        /* One card anatomy for every page (Section 4.9): a CSS grid in a single
        markdown call, so cards in a row end at the same height and nothing bleeds
        past a container. */
        .card-grid {{
            display: grid;
            gap: 1rem;
            align-items: stretch;
            margin: 0.35rem 0 1rem 0;
        }}
        .grid-card {{
            background-color: #FFFFFF;
            border: 1px solid rgba(30, 39, 97, 0.15);
            border-radius: 0.5rem;
            padding: 1rem;
            display: flex;
            flex-direction: column;
        }}
        .grid-card .card-foot:last-child {{
            margin-top: auto;
            padding-top: 8px;
        }}
        .info-grid {{
            display: grid;
            gap: 16px;
        }}
        .card-tag {{
            display: inline-block;
            align-self: flex-start;
            margin-top: 8px;
            padding: 1px 9px;
            border: 1px solid #D1D5DB;
            border-radius: 999px;
            color: #4B5563;
            font-size: 0.76rem;
            font-weight: 500;
        }}
        /* Repeat marker (Digest drill-downs): neutral gray like .card-tag. It marks a
        repeated driver, not a status judgment (Section 2.3). */
        .repeat-chip {{
            display: inline-block;
            margin-left: 10px;
            padding: 1px 9px;
            border: 1px solid #D1D5DB;
            border-radius: 999px;
            background-color: #FFFFFF;
            color: #4B5563;
            font-size: 0.78rem;
            font-weight: 500;
            vertical-align: middle;
        }}
        .card-value.sm {{
            font-size: 1.15rem;
            line-height: 1.7;
            white-space: nowrap;
        }}
        .note-line {{
            margin: 0 0 6px 0;
            font-size: 0.9rem;
            line-height: 1.45;
        }}
        .note-details {{
            display: inline;
        }}
        .note-details summary {{
            display: inline;
            cursor: pointer;
            color: {NEUTRAL_GRAY};
            font-size: 0.82rem;
            margin-left: 6px;
        }}
        .note-details div {{
            margin-top: 4px;
            color: #4B5563;
        }}
        /* Narrow viewports: cards wrap to two columns and info rows to two. */
        @media (max-width: 640px) {{
            .card-grid:not(.single) {{ grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }}
            .info-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }}
        }}
        .card-head {{
            min-height: 2.7em;
        }}
        .card-unit {{
            display: inline-block;
            white-space: nowrap;
            font-family: {FONT_BODY};
            font-size: 0.9rem;
            font-weight: 500;
        }}
        .card-foot {{
            color: {NEUTRAL_GRAY};
            font-size: 0.8rem;
            line-height: 1.35;
            margin-top: 8px;
        }}
        .card-value {{
            font-family: {FONT_HEADER};
            font-size: 2.1rem;
            font-weight: 700;
            line-height: 1.15;
        }}
        .card-delta {{
            font-size: 0.95rem;
            font-weight: 600;
        }}
        .breadcrumb {{
            color: {NEUTRAL_GRAY};
            font-size: 0.85rem;
        }}
        /* Source chips (executive-summary citations): neutral gray only --
        a citation is provenance, never a status judgment (Section 2.3). */
        /* Metric-tree panel (Ask the Metric Tree, Section 4.7): node buttons are
        left-aligned text rows, node metadata is one small gray line. */
        [data-testid="stSidebar"] .stButton button {{
            justify-content: flex-start;
            text-align: left;
            min-height: 0;
            padding: 2px 6px;
            width: 100%;
        }}
        [data-testid="stSidebar"] .stButton button > div,
        [data-testid="stSidebar"] .stButton button span,
        [data-testid="stSidebar"] .stButton button [data-testid="stMarkdownContainer"] {{
            width: 100%;
            justify-content: flex-start;
            overflow: visible;
            text-overflow: clip;
            white-space: normal;
        }}
        [data-testid="stSidebar"] [data-testid="stTooltipHoverTarget"] {{
            justify-content: flex-start !important;
        }}
        [data-testid="stSidebar"] .stButton button p {{
            font-size: 0.88rem;
            text-align: left;
            line-height: 1.25;
            white-space: normal;
            overflow: visible;
            text-overflow: clip;
        }}
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
            gap: 0.45rem;
        }}
        /* Chat avatars default to red and orange fills, which read as Palette B
        status colors (Section 2.3); neutral gray carries no judgment. */
        [data-testid="stChatMessageAvatarUser"],
        [data-testid="stChatMessageAvatarAssistant"] {{
            background-color: {NEUTRAL_GRAY} !important;
        }}
        .tree-meta {{
            color: {NEUTRAL_GRAY};
            font-size: 0.74rem;
            margin: -6px 0 4px 6px;
            line-height: 1.2;
        }}
        .tree-pillar {{
            font-family: {FONT_HEADER};
            font-weight: 700;
            font-size: 1.02rem;
            margin: 10px 0 2px 0;
        }}
        /* Answer table (children of a metric): neutral gray text for status. */
        .answer-table, .answer-table th, .answer-table td {{
            border: none;
        }}
        .answer-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }}
        .answer-table th {{
            text-align: left;
            font-size: 0.78rem;
            font-weight: 500;
            color: {NEUTRAL_GRAY};
            text-transform: uppercase;
            letter-spacing: 0.03em;
            padding: 4px 8px 6px 0;
            border-bottom: 1px solid #E5E7EB !important;
        }}
        .answer-table td {{
            vertical-align: top;
            padding: 8px 8px 8px 0;
            border-bottom: 1px solid #F1F2F4 !important;
        }}
        .answer-table tr:last-child td {{
            border-bottom: none !important;
        }}
        .answer-table .reason {{
            color: {NEUTRAL_GRAY};
            font-size: 0.8rem;
            line-height: 1.35;
        }}
        .source-row {{
            margin-bottom: 6px;
        }}
        .source-chip {{
            display: inline-block;
            background-color: #FFFFFF;
            border: 1px solid #D1D5DB;
            border-radius: 999px;
            color: #4B5563;
            font-size: 0.78rem;
            padding: 1px 9px;
            margin: 0 4px 4px 0;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_color(favorable_direction: Optional[str], is_ahead: Optional[bool]) -> str:
    """Palette B color for a variance/status judgment, computed per-metric
    from its own favorable direction (never from the raw sign of a delta
    -- Section 2.3). `favorable_direction` is 'higher' or 'lower'
    (whichever direction is good for THIS metric); `is_ahead` is whether
    the actual value is on the favorable side of its comparison point.
    Returns NEUTRAL_GRAY if either input is unknown -- a metric with no
    comparison point gets no judgment color, per Section 7."""
    if favorable_direction is None or is_ahead is None:
        return NEUTRAL_GRAY
    return FAVORABLE_GREEN if is_ahead else UNFAVORABLE_RED


def status_arrow(is_ahead: Optional[bool]) -> str:
    """Non-color signal paired with every red/green judgment (Section 2.5
    accessibility floor) -- an up/down glyph, never color alone."""
    if is_ahead is None:
        return "→"
    return "▲" if is_ahead else "▼"


def _card_inner(card: dict) -> str:
    """The HTML inside one scorecard: dot + label, the headline number as the
    card's largest text, a status-colored delta carrying both color and an arrow
    glyph, an optional neutral tag chip (e.g. "Caveated comparison"), and gray
    footer lines. A long value string ("4.22e-06 touches/Action") keeps its number
    large and sets the trailing unit in a smaller size so it stays on one line.

    `card` keys: label, value_display (required); pillar, dot_color,
    comparison_display, variance_display, favorable_direction, is_ahead, footer,
    tag, value_size ("sm" for a text value such as "Not computable")."""
    pillar = card.get("pillar")
    dot_color = card.get("dot_color") or (PILLAR_COLOR.get(pillar, NEUTRAL_GRAY) if pillar else NEUTRAL_GRAY)
    comparison_display = card.get("comparison_display")
    variance_display = card.get("variance_display")
    favorable_direction = card.get("favorable_direction")
    is_ahead = card.get("is_ahead")
    value_display = card["value_display"]
    delta_html = ""
    if comparison_display or variance_display:
        color = status_color(favorable_direction, is_ahead)
        arrow = status_arrow(is_ahead) if favorable_direction is not None else ""
        lead = " ".join(escape_html(p) for p in [arrow, variance_display] if p)
        parts = " · ".join(x for x in [lead, escape_html(comparison_display) if comparison_display else ""] if x)
        delta_html = f'<div class="card-delta" style="color:{color}">{parts}</div>'
    value_class = "card-value sm" if card.get("value_size") == "sm" else "card-value"
    if (len(value_display) > 12 and " " in value_display and value_display[0] in "0123456789-+$"
            and "<" not in value_display):
        number, unit_text = value_display.split(" ", 1)
        value_display = f'{number} <span class="card-unit">{escape_html(unit_text)}</span>'
    elif "<" not in value_display:
        value_display = escape_html(value_display)
    tag_html = f'<div class="card-tag">ⓘ {escape_html(card["tag"])}</div>' if card.get("tag") else ""
    foot_html = ""
    if card.get("footer"):
        lines = "".join(f"<div>{escape_html(line)}</div>" for line in card["footer"])
        foot_html = f'<div class="card-foot">{lines}</div>'
    return (
        f'<div class="card-head"><span class="pillar-dot" style="background-color:{dot_color}"></span>'
        f'<span class="card-label">{escape_html(card["label"])}</span></div>'
        f'<div class="{value_class}">{value_display}</div>'
        f'{delta_html}{tag_html}{foot_html}'
    )


def scorecard_row(cards: list) -> None:
    """A row of scorecards as one CSS grid in a single markdown call, so every
    card in the row stretches to the tallest one (Section 5.2, uneven card fill;
    st.columns() cannot equalize heights). `cards` is a list of dicts with
    _card_inner()'s keys. The only card implementation on the dashboard: one
    card is a row of one."""
    if not cards:
        return
    cells = "".join(f'<div class="grid-card">{_card_inner(c)}</div>' for c in cards)
    st.markdown(
        f'<div class="card-grid" style="grid-template-columns:repeat({len(cards)},minmax(0,1fr))">{cells}</div>',
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
    """A single white block of label/value pairs (as-of date, grain, threshold):
    the Section 7 context row. `items` is a list of (label, value) tuples; values
    are escaped."""
    n = columns or len(items)
    cells = "".join(
        f'<div><div class="card-label">{escape_html(label)}</div>'
        f'<div class="card-delta">{escape_html(value)}</div></div>'
        for label, value in items
    )
    st.markdown(
        f'<div class="card-grid single"><div class="grid-card"><div class="info-grid" '
        f'style="grid-template-columns:repeat({n},minmax(0,1fr))">{cells}</div></div></div>',
        unsafe_allow_html=True,
    )


def neutral_chip(text: str) -> str:
    """HTML for a compact neutral-gray chip (a marker, never a status). Escaped."""
    return f'<span class="repeat-chip">{escape_html(text)}</span>'


def card_block(inner_html: str) -> None:
    """One white card around caller-built HTML (already escaped by the caller)."""
    st.markdown(f'<div class="card-grid single"><div class="grid-card"><div>{inner_html}</div></div></div>',
                unsafe_allow_html=True)


def escape_html(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("$", "&#36;"))


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


PLOTLY_FONT = dict(family="Inter, sans-serif", color=GROWTH_NAVY, size=12)


def plotly_layout(**overrides) -> dict:
    """Shared Plotly layout defaults (Section 9) -- pass as
    fig.update_layout(**plotly_layout()). Never sets a colorway of its
    own: callers pass explicit colors from Palette A/B/segment per trace,
    since color meaning is context-dependent (pillar vs status vs
    segment) and a fixed default colorway would risk reusing a status hue
    for a category series."""
    base = dict(
        font=PLOTLY_FONT,
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified",
    )
    base.update(overrides)
    return base


def style_axes(fig: go.Figure) -> go.Figure:
    fig.update_xaxes(showgrid=False, tickfont=PLOTLY_FONT)
    fig.update_yaxes(showgrid=True, gridcolor="#E5E7EB", tickfont=PLOTLY_FONT)
    return fig


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
