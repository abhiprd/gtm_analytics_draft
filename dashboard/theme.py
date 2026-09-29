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
        /* Scorecard container fill (Section 5.2): st.container(border=True)
        in the installed Streamlit version (1.64.0) renders its border and
        radius reliably (verified against the live DOM -- it already picks
        up primaryColor from .streamlit/config.toml), but its background
        stays transparent, and there is no stable data-testid/class that
        distinguishes a bordered stVerticalBlock from an unbordered one in
        this version (the differentiating class is a content-hashed
        st-emotion-cache-* name, not a semantic attribute, so it can't be
        targeted safely and will change on the next Streamlit upgrade
        anyway). Fix: scorecard() wraps its own content in a
        .theme-card-fill div and this rule bleeds it to the parent
        container's edges via a negative margin larger than that
        container's own padding, then re-applies the same padding inside --
        a standard, version-independent workaround for this exact
        Streamlit limitation, rather than chasing an internal selector. */
        .theme-card-fill {{
            background-color: #FFFFFF;
            border-radius: 8px;
            margin: -20px;
            padding: 20px;
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


def scorecard(
    label: str,
    value_display: str,
    pillar: Optional[str] = None,
    comparison_display: Optional[str] = None,
    variance_display: Optional[str] = None,
    favorable_direction: Optional[str] = None,
    is_ahead: Optional[bool] = None,
) -> None:
    """One scorecard per dashboard-design-conventions.md Section 9: a
    bordered container, pillar-color accent dot (never a full-width bar),
    the headline number as the card's largest text, and a status-colored
    delta badge carrying both color and an arrow glyph. `is_ahead=None`
    (no comparison point) renders the delta in neutral gray with no
    arrow-based judgment, per Section 7's "never show a number without a
    comparison unless there genuinely isn't one" rule."""
    with st.container(border=True):
        dot_color = PILLAR_COLOR.get(pillar, NEUTRAL_GRAY) if pillar else NEUTRAL_GRAY
        delta_html = ""
        if comparison_display or variance_display:
            color = status_color(favorable_direction, is_ahead)
            arrow = status_arrow(is_ahead) if favorable_direction is not None else ""
            parts = " ".join(p for p in [arrow, variance_display, comparison_display] if p)
            delta_html = f'<div class="card-delta" style="color:{color}">{parts}</div>'
        # Single markdown call, one .theme-card-fill wrapper -- see
        # inject_global_css()'s comment for why this can't be three
        # separate st.markdown calls each styled independently.
        st.markdown(
            f'<div class="theme-card-fill">'
            f'<span class="pillar-dot" style="background-color:{dot_color}"></span>'
            f'<span class="card-label">{label}</span>'
            f'<div class="card-value">{value_display}</div>'
            f'{delta_html}'
            f'</div>',
            unsafe_allow_html=True,
        )


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


def render_pending(component_key: str, extra_note: Optional[str] = None) -> None:
    """The Section 7 honesty pattern, generalized: renders the same
    'not yet generated' + 'why this is blank' expander pattern the Digest
    page originated, for any component whose project_status.json status
    is not built_and_validated. Call this INSTEAD of rendering the
    component's chart/number -- never render a live-looking value and
    this pending marker together."""
    status = component_status(component_key)
    label = status["status"].replace("_", " ")
    st.info(f"_Not yet available -- status: {label}._")
    with st.expander("Why this is blank"):
        st.write(f"**Artifact:** {status['artifact']}")
        if status.get("note"):
            st.write(status["note"])
        if extra_note:
            st.write(extra_note)


def is_built(component_key: str) -> bool:
    return component_status(component_key)["status"] == "built_and_validated"
