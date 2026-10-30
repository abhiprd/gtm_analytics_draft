"""The Digest's "What changed" ranked bar as a Plotly figure, Streamlit-free so its spec is
unit-testable (tests/test_dashboard_whatchanged_view.py): bars at most 24px thick with a 4px
rounded end, a zero line, solid hairline gridlines, no legend box, and every value label
placed just right of its bar's right end (the zero line for a negative bar) so a label never
touches the axis or runs into the category names on a narrow screen. Colors are the status
pair for a comparable row and a quiet gray for a caveated one (conventions 2.3 and 4.10)."""
import textwrap
from typing import Dict, List

import plotly.graph_objects as go

try:  # Streamlit runtime: dashboard/ is on sys.path
    import chartkit
    import tokens as T
except ImportError:  # tests: the repo root is on sys.path
    from dashboard import chartkit, tokens as T

from . import whatchanged_view as view

ROW_PX = 44            # one category slot
BAR_PX = 22            # bar thickness: below the 24px cap
LABEL_WRAP = 26        # characters per line on the category axis
LABEL_GAP = 0.018      # label offset from the bar end, as a share of the axis span
RIGHT_PAD = 0.38       # empty axis span right of the longest bar, for its label
LEFT_PAD = 0.06        # empty axis span left of the most negative bar
BAR_COLOR = {view.FAVORABLE: T.FAVORABLE_GREEN, view.UNFAVORABLE: T.UNFAVORABLE_RED,
             view.NEUTRAL: T.MARK_MUTED}
KEY_TEXT = {view.FAVORABLE: "Ahead of plan", view.UNFAVORABLE: "Behind plan",
            view.NEUTRAL: "Caveated comparison, gray, no judgment"}


def axis_range(xs: List[float]) -> List[float]:
    lo, hi = min(list(xs) + [0.0]), max(list(xs) + [0.0])
    span = (hi - lo) or 1.0
    return [lo - LEFT_PAD * span, hi + RIGHT_PAD * span]


def figure(rs: List[Dict]) -> go.Figure:
    labels_y = ["<br>".join(textwrap.wrap(r["label"], LABEL_WRAP)) or r["label"] for r in rs]
    xs = [r["gap"] for r in rs]
    lo, hi = min(xs + [0.0]), max(xs + [0.0])
    span = (hi - lo) or 1.0
    fig = go.Figure(go.Bar(
        x=xs, y=labels_y, orientation="h", width=BAR_PX / ROW_PX,
        marker=dict(color=[BAR_COLOR[r["kind"]] for r in rs], cornerradius=T.RADIUS_MARK, line=dict(width=0)),
        customdata=[[r["gap_display"], r["status"], r["layer2_label"] or "none computable"] for r in rs],
        hovertemplate="%{y}<br>Gap %{customdata[0]}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=[max(x, 0.0) + LABEL_GAP * span for x in xs], y=labels_y, mode="text",
        text=[r["bar_label"] for r in rs], textposition="middle right", cliponaxis=False,
        hoverinfo="skip", showlegend=False,
        textfont=dict(color=T.INK, size=T.FS_XS, family=T.FONT_FAMILY),
    ))
    fig.update_layout(**chartkit.plotly_layout(
        height=ROW_PX * len(rs) + 56, showlegend=False, hovermode="closest",
        margin=dict(l=10, r=10, t=8, b=44), bargap=0,
    ))
    chartkit.style_axes(fig)
    fig.update_xaxes(range=axis_range(xs), tickformat=".0%", title_text=view.axis_title(rs), showgrid=True,
                     gridcolor=T.GRID_LINE, zeroline=True, zerolinecolor=T.TEXT_SECONDARY, zerolinewidth=1,
                     nticks=6)
    fig.update_yaxes(autorange="reversed", showgrid=False, ticklabelstandoff=6, automargin=True)
    return fig
