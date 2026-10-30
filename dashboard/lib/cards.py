"""The HTML of one stat tile, Streamlit-free so it is unit-testable
(tests/test_dashboard_cards.py). theme.scorecard_row wraps these tiles in one CSS grid.

Anatomy (conventions Section 4.9): a sentence-case label, the value, a delta line (a
direction glyph from the sign of the change, the signed change, a status word when the
change carries a judgment), a comparison line, an optional 12-point sparkline, optional
neutral tag and footer lines, and an optional per-tile "About this number" disclosure.

Judgment is set only when a card carries both a favorable direction and an is_ahead
value; any other delta is neutral gray with its direction glyph and no status word
unless the card names one ("On track", "Not computable").
"""
from typing import Dict, List, Optional, Sequence, Tuple

try:  # Streamlit runtime: dashboard/ is on sys.path
    import tokens as T
except ImportError:  # tests: the repo root is on sys.path
    from dashboard import tokens as T

from . import formatting, verdict

SPARK_WIDTH = 120
SPARK_HEIGHT = 28
SPARK_PAD = 6
SPARK_POINTS = 12


def escape_html(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("$", "&#36;"))


def judgment(card: Dict) -> Optional[bool]:
    """True favorable, False unfavorable, None when the card carries no judgment."""
    if card.get("favorable_direction") is None or card.get("is_ahead") is None:
        return None
    return bool(card["is_ahead"])


def delta_color(card: Dict) -> str:
    j = judgment(card)
    if j is None:
        return T.TEXT_SECONDARY
    return T.FAVORABLE_GREEN if j else T.UNFAVORABLE_RED


def status_word(card: Dict) -> str:
    if card.get("status_word"):
        return str(card["status_word"])
    j = judgment(card)
    if j is None:
        return ""
    return "Favorable" if j else "Unfavorable"


def sparkline_svg(values: Sequence[float], color: str, label: str) -> str:
    """A quiet 12-point trend: muted 2px line, current point in `color` with a 2px
    surface ring. Drawn only for a series of at least two points that is not constant."""
    vals = [float(v) for v in values]
    if len(vals) < 2 or max(vals) == min(vals):
        return ""
    lo, hi = min(vals), max(vals)
    span = hi - lo
    inner_w = SPARK_WIDTH - 2 * SPARK_PAD
    inner_h = SPARK_HEIGHT - 2 * SPARK_PAD
    pts = [(SPARK_PAD + i * inner_w / (len(vals) - 1), SPARK_PAD + (hi - v) / span * inner_h)
           for i, v in enumerate(vals)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    lx, ly = pts[-1]
    return (
        f'<svg class="tile-spark" role="img" aria-label="{escape_html(label)}" width="{SPARK_WIDTH}" '
        f'height="{SPARK_HEIGHT}" viewBox="0 0 {SPARK_WIDTH} {SPARK_HEIGHT}">'
        f'<polyline points="{poly}" fill="none" stroke="{T.MARK_MUTED}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4" fill="{color}" stroke="{T.SURFACE}" stroke-width="2"/>'
        f'</svg>'
    )


def _marker_html(card: Dict) -> str:
    marker = card.get("marker")
    if not marker:
        return ""
    return (f'<span class="tile-flag" role="img" aria-label="{escape_html(marker)}" '
            f'title="{escape_html(marker)}">ⓘ</span>')


def _delta_html(card: Dict) -> str:
    variance = card.get("variance_display")
    comparison = card.get("comparison_display")
    if not variance and not comparison:
        return ""
    out = ""
    if variance:
        glyph = verdict.delta_glyph(variance)
        color = delta_color(card)
        word = status_word(card)
        main = " ".join(p for p in (glyph, escape_html(variance)) if p)
        out += (f'<div class="tile-delta"><span class="delta-main" style="color:{color}">{main}</span>'
                + (f' <span class="delta-word" style="color:{color}">{escape_html(word)}</span>' if word else "")
                + '</div>')
    if comparison:
        out += f'<div class="tile-vs">{escape_html(comparison)}</div>'
    # The marker sits beside the delta it qualifies, so a long label keeps the full row.
    return f'<div class="tile-delta-row"><div>{out}</div>{_marker_html(card)}</div>' if card.get("marker") else out


def _about_html(about: Optional[List[Tuple[str, str]]]) -> str:
    if not about:
        return ""
    rows = "".join(
        f'<div class="about-row"><span class="about-k">{escape_html(k)}</span>{escape_html(v)}</div>'
        for k, v in about
    )
    return f'<details class="tile-about"><summary>About this number</summary><div class="about-body">{rows}</div></details>'


def card_inner(card: Dict) -> str:
    """The HTML inside one tile. `card` keys: label, value_display (required); pillar,
    dot_color, comparison_display, variance_display, favorable_direction, is_ahead,
    status_word, footer, tag, marker, value_size ("sm" for a text value such as
    "Not computable"), sparkline (list of floats), spark_label, about ([(term, text)])."""
    pillar = card.get("pillar")
    dot_color = card.get("dot_color") or (T.PILLAR_COLOR.get(pillar, T.NEUTRAL_GRAY) if pillar else T.NEUTRAL_GRAY)
    value_display = card["value_display"]
    value_class = "card-value sm" if card.get("value_size") == "sm" else "card-value"
    split = formatting.split_unit_value(value_display)
    if split:
        # The number never breaks; the unit may drop below it as one piece.
        number, unit_text = split
        value_display = (f'<span class="card-num">{escape_html(number)}</span> '
                         f'<span class="card-unit">{escape_html(unit_text)}</span>')
    elif "<" not in value_display:
        value_display = escape_html(value_display)
        if value_class == "card-value":
            value_class = "card-value nw"  # a plain number is one unbreakable piece
    has_delta = bool(card.get("variance_display") or card.get("comparison_display"))
    head_marker = "" if has_delta else _marker_html(card)
    spark_html = ""
    if card.get("sparkline"):
        spark_html = f'<div class="tile-spark-row">{sparkline_svg(card["sparkline"], dot_color, card.get("spark_label") or "Trend")}</div>'
    tag_html = f'<div class="card-tag">ⓘ {escape_html(card["tag"])}</div>' if card.get("tag") else ""
    foot_html = ""
    if card.get("footer"):
        lines = "".join(f"<div>{escape_html(line)}</div>" for line in card["footer"])
        foot_html = f'<div class="card-foot">{lines}</div>'
    return (
        f'<div class="card-head"><span class="pillar-dot" style="background-color:{dot_color}"></span>'
        f'<span class="card-label">{escape_html(card["label"])}</span>{head_marker}</div>'
        f'<div class="{value_class}">{value_display}</div>'
        f'{_delta_html(card)}{spark_html}{tag_html}{foot_html}{_about_html(card.get("about"))}'
    )
