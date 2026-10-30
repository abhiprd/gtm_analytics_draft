"""Plotly defaults shared by every chart, with no Streamlit import so figure builders
can be unit-tested (tests/test_dashboard_whatchanged_view.py). theme.py re-exports these.
All chart text is the xs step of the one type family (conventions Section 5.3)."""
try:  # Streamlit runtime: dashboard/ is on sys.path
    import tokens as T
except ImportError:  # tests: the repo root is on sys.path
    from dashboard import tokens as T

import plotly.graph_objects as go

PLOTLY_FONT = dict(family=T.FONT_FAMILY, color=T.INK, size=T.FS_XS)
PLOTLY_TEXT_SECONDARY = dict(family=T.FONT_FAMILY, color=T.TEXT_SECONDARY, size=T.FS_XS)


def plotly_layout(**overrides) -> dict:
    """Shared Plotly layout defaults (Section 9) -- pass as
    fig.update_layout(**plotly_layout()). Never sets a colorway of its
    own: callers pass explicit colors from Palette A/B/segment per trace,
    since color meaning is context-dependent (pillar vs status vs
    segment) and a fixed default colorway would risk reusing a status hue
    for a category series. All chart text is the xs step in the one family."""
    base = dict(
        font=PLOTLY_FONT,
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=PLOTLY_FONT),
        hovermode="x unified",
    )
    base.update(overrides)
    return base


def style_axes(fig: go.Figure) -> go.Figure:
    """Hairline solid gridlines and axis text in the secondary text token (Section 3.2)."""
    fig.update_xaxes(showgrid=False, tickfont=PLOTLY_TEXT_SECONDARY, title_font=PLOTLY_TEXT_SECONDARY,
                     linecolor=T.GRID_LINE)
    fig.update_yaxes(showgrid=True, gridcolor=T.GRID_LINE, gridwidth=1, tickfont=PLOTLY_TEXT_SECONDARY,
                     title_font=PLOTLY_TEXT_SECONDARY, linecolor=T.GRID_LINE, zeroline=False)
    return fig
