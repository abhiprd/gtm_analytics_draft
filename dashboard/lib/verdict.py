"""Scorecard-row treatment rules, Streamlit-free so they are unit-testable
(tests/test_dashboard_verdict.py).

The weekly readout carries a status per Layer-1 row (Ahead, Behind, On track, Not
computable) plus a `plan_comparability` flag. This module decides how a row is
presented, without recomputing any figure:

  * caveated   -- `plan_comparability == "caveated"`: the plan and the actual exist
                  and the variance is computed, but their LEVELS are not on the same
                  footing. The tile carries a small "Caveated comparison" marker and the
                  delta is shown in neutral gray, with its direction glyph and no
                  favorable/unfavorable color or status word, so the Ahead/Behind status
                  never reads as a business finding.
  * degenerate -- status "Not computable" with an actual, a prior value and a baseline
                  that are all the same number (blended TTFA is 0 in every month): the
                  card says "Not computable" in place of the number.
  * neutral    -- a delta that rounds to zero at its displayed precision carries no
                  status color and no direction glyph.

A delta's glyph follows the sign of the change (delta_glyph); status color and a status
word carry the judgment.

Conventions Sections 2.3, 7 and the Section 2.3 addendum recorded in the dashboard README.
"""
import math
import re
from typing import Dict, List, Optional

COMPARABILITY_CAVEATED = "caveated"
STATUS_AHEAD = "Ahead"
STATUS_BEHIND = "Behind"
STATUS_ON_TRACK = "On track"
STATUS_NOT_COMPUTABLE = "Not computable"

CAVEAT_TAG = "Caveated comparison"
CAVEAT_FOOTER = "Level differs in scope from the plan basis; see Notes."

# Metrics whose Layer-1 actual is a trailing-twelve-month figure rather than a single
# month (analytics/variance_diagnostic.py blend_layer1_actuals docstring). The readout
# row carries this only in its unit_label for the compounded rates, so the multiples are
# listed here. A row that carries its own `basis` field takes precedence.
_TTM_KEYS = {"magic_number", "am_efficiency", "nrr", "grr", "logo_retention"}


def missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def is_caveated(row: Dict) -> bool:
    return row.get("plan_comparability") == COMPARABILITY_CAVEATED


def is_degenerate(row: Dict) -> bool:
    """Not computable because the series carries no variation: the actual, the prior
    month and the trailing baseline are all present and identical."""
    if row.get("status") != STATUS_NOT_COMPUTABLE:
        return False
    vals = [row.get("actual"), row.get("prior_month_value"), row.get("trailing_baseline")]
    if any(missing(v) for v in vals):
        return False
    return len({float(v) for v in vals}) == 1


def display_rounds_to_zero(text: Optional[str]) -> bool:
    """True when a displayed delta ('+0.0%', '-0.00x', '+$0', '+0.0 pp') shows zero."""
    if not text:
        return False
    digits = re.findall(r"\d+(?:\.\d+)?", str(text))
    if not digits:
        return False
    return all(float(d) == 0.0 for d in digits)


GLYPH_UP = "▲"
GLYPH_DOWN = "▼"
_SIGNED_NUMBER_RE = re.compile(r"([+\-−])\s*\$?\d")


def delta_glyph(text: Optional[str]) -> str:
    """The direction glyph for a displayed change: an up arrow for a positive change, a
    down arrow for a negative one, nothing for a change that rounds to zero or carries
    no sign. It follows the sign of the number shown and never the judgment: a metric
    where lower is better and that fell shows a down arrow, and color and a status word
    say whether that is good (conventions Section 2.3)."""
    if not text or display_rounds_to_zero(text):
        return ""
    m = _SIGNED_NUMBER_RE.search(str(text))
    if not m:
        return ""
    return GLYPH_UP if m.group(1) == "+" else GLYPH_DOWN


def unsigned_if_zero(text: Optional[str]) -> Optional[str]:
    """A delta that displays as zero carries no sign: '-0.0 pp' -> '0.0 pp'."""
    if text and display_rounds_to_zero(text):
        return str(text).lstrip("+-−")
    return text


_SCI_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)[eE]([+-]?\d+)(?!\w)")


def plain_number(v: float) -> str:
    """A number with no exponent: thousands separators from 1,000 up, two decimals
    from 1, and enough decimals below 1 to keep three significant digits."""
    v = float(v)
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}"
    if a >= 1:
        return f"{v:.2f}"
    if a == 0:
        return "0"
    decimals = min(12, max(2, -int(math.floor(math.log10(a))) + 2))
    return f"{v:.{decimals}f}"


def strip_scientific(text: Optional[str]) -> Optional[str]:
    """Last-resort guard: rewrite any 'd.dde-06' in a display string as a plain decimal."""
    if not text:
        return text
    return _SCI_RE.sub(lambda m: plain_number(float(m.group(0))), str(text))


PER_MILLION = 1_000_000
TOUCHES_UNIT = "touches_per_action"
TOUCHES_UNIT_LABEL = "AM/CS touchpoints per 1M automated Actions"


def per_million_text(v: float) -> str:
    """Touchpoints per automated Action, shown per 1M Actions (the Segment Efficiency
    scaling): 5.26e-06 -> '5.26 per 1M Actions'."""
    return f"{float(v) * PER_MILLION:.2f} per 1M Actions"


def pp_text(delta: float, decimals: int = 1) -> str:
    """A change in a rate, in percentage points: 0.0123 -> '+1.2 pp'."""
    return f"{delta * 100:+.{decimals}f} pp"


def basis_label(row: Dict) -> str:
    if row.get("basis"):
        return str(row["basis"])
    month = str(row.get("month") or "")[:7]
    unit_label = str(row.get("unit_label") or "").lower()
    ttm = row.get("metric_key") in _TTM_KEYS or "trailing-12" in unit_label or "trailing-twelve" in unit_label
    if ttm:
        return f"Trailing 12 months to {month}" if month else "Trailing 12 months"
    return f"Month of {month}" if month else "Monthly"


def format_baseline(value: float, unit: str) -> str:
    if unit == "usd":
        v = abs(value)
        sign = "-" if value < 0 else ""
        if v >= 1_000_000:
            return f"{sign}${v / 1_000_000:.1f}M"
        if v >= 1_000:
            return f"{sign}${v / 1_000:.1f}K"
        return f"{sign}${v:,.0f}"
    if unit == "rate":
        return f"{value * 100:.1f}%"
    if unit == "months":
        return f"{value:.2f} mo"
    if unit == "multiple":
        return f"{value:.2f}x"
    if unit == TOUCHES_UNIT:
        return per_million_text(value)
    return plain_number(value)


def is_ahead_for(status: str) -> Optional[bool]:
    if status == STATUS_AHEAD:
        return True
    if status == STATUS_BEHIND:
        return False
    return None


def _display_row(row: Dict) -> Dict:
    """Copy of the readout row with display strings made reader-friendly: touches per
    Action shown per 1M Actions, no scientific notation anywhere, no negative zero."""
    r = dict(row)
    if r.get("unit") == TOUCHES_UNIT:
        if not missing(r.get("actual")):
            r["value_display"] = per_million_text(r["actual"])
        if not missing(r.get("plan")):
            r["comparison_display"] = f"{per_million_text(r['plan'])} plan"
        if not missing(r.get("prior_month_value")) and str(r.get("comparison_display", "")).endswith("last month"):
            r["comparison_display"] = f"{per_million_text(r['prior_month_value'])} last month"
        r["unit_label"] = TOUCHES_UNIT_LABEL
    for key in ("value_display", "comparison_display", "variance_display", "unit_label"):
        r[key] = strip_scientific(r.get(key))
    r["variance_display"] = unsigned_if_zero(r.get("variance_display"))
    return r


NOT_JUDGED = "Not judged: caveated comparison"
SPARK_MONTHS = 12
STATUS_PHRASE = {STATUS_AHEAD: "Ahead of plan", STATUS_BEHIND: "Behind plan",
                 STATUS_ON_TRACK: "On track against plan", STATUS_NOT_COMPUTABLE: "Not computable"}


def _month_key(month) -> str:
    return str(month)[:7]


def _previous_months(month_key: str, n: int) -> List[str]:
    """The n consecutive month keys ending at month_key, oldest first."""
    year, mon = int(month_key[:4]), int(month_key[5:7])
    keys = []
    for _ in range(n):
        keys.append(f"{year:04d}-{mon:02d}")
        mon -= 1
        if mon == 0:
            year, mon = year - 1, 12
    return keys[::-1]


def monthly_series(frame) -> Dict[str, Dict[str, Optional[float]]]:
    """{metric_key: {"YYYY-MM": value}} from a DataFrame indexed by month (the variance
    engine's blend_layer1_actuals output); a missing value is None."""
    import pandas as pd
    return {key: {pd.Timestamp(ts).strftime("%Y-%m"): (None if pd.isna(v) else float(v))
                  for ts, v in frame[key].items()} for key in frame.columns}


def trend_points(series_by_month: Optional[Dict[str, float]], row: Dict) -> Optional[List[float]]:
    """The 12 monthly points for a tile's sparkline, or None. A trend is drawn only when
    all 12 consecutive months ending at the row's own month exist, none is missing, the
    series is not constant, and the last point equals the readout's own actual for the
    row: a series on a different basis than the headline would draw a trend that
    disagrees with the number beside it. Nothing is imputed or interpolated."""
    if not series_by_month or missing(row.get("actual")) or not row.get("month"):
        return None
    keys = _previous_months(_month_key(row["month"]), SPARK_MONTHS)
    vals = [series_by_month.get(k) for k in keys]
    if any(missing(v) for v in vals):
        return None
    vals = [float(v) for v in vals]
    if not math.isclose(vals[-1], float(row["actual"]), rel_tol=1e-6, abs_tol=1e-12):
        return None
    if len(set(vals)) == 1:
        return None
    return vals


def card_for_row(row: Dict, pillar: Optional[str] = None, baseline_months: Optional[int] = None,
                 series_by_month: Optional[Dict[str, float]] = None) -> Dict:
    """The theme.scorecard_row() dict for one readout scorecard row (Section 4.9):
    label, value, a delta and, when `series_by_month` yields a valid 12-month trend, a
    sparkline. Unit, basis, baseline, status, caveat and Layer text go to `about`
    (the tile's "About this number"); a caveated comparison carries a `marker`."""
    row = _display_row(row)
    status = row.get("status")
    pillar = pillar or row.get("pillar")
    about: List = []
    card: Dict = dict(label=row["label"], pillar=pillar, value_display=row.get("value_display", "n/a"))

    def layer_about():
        if row.get("layer") is not None:
            about.append(("Layer", f"Layer {row['layer']}"))

    if is_degenerate(row):
        card["value_display"] = "Not computable"
        card["value_size"] = "sm"
        card["tag"] = "No variation in data"
        card["footer"] = [f"{row['label']} does not vary in the data, so no variance can be computed."]
        about.append(("Basis", basis_label(row)))
        layer_about()
        card["about"] = about
        return card

    variance = row.get("variance_display")
    comparison = row.get("comparison_display")
    direction = row.get("favorable_direction")
    ahead = is_ahead_for(status)
    vs = f"vs {comparison}" if comparison else None

    if status == STATUS_NOT_COMPUTABLE:
        card.update(variance_display="n/a", status_word="Not computable", comparison_display=None,
                    favorable_direction=None, is_ahead=None)
    elif status == STATUS_ON_TRACK:
        card.update(variance_display=variance, status_word="On track", comparison_display=vs,
                    favorable_direction=None, is_ahead=None)
    elif is_caveated(row):
        # Neutral treatment: the sign and size of the gap are shown, the judgment is not.
        card.update(variance_display=variance, comparison_display=vs,
                    favorable_direction=None, is_ahead=None, marker=CAVEAT_TAG)
    elif display_rounds_to_zero(variance):
        card.update(variance_display=variance, comparison_display=vs,
                    favorable_direction=None, is_ahead=None)
    else:
        card.update(variance_display=variance, comparison_display=vs,
                    favorable_direction=direction, is_ahead=ahead,
                    status_word=STATUS_AHEAD if ahead else (STATUS_BEHIND if ahead is False else None))

    if row.get("unit_label"):
        about.append(("Unit", str(row["unit_label"])))
    about.append(("Basis", basis_label(row)))
    baseline = row.get("trailing_baseline")
    if not missing(baseline):
        window = f"{baseline_months}-month " if baseline_months else ""
        text = format_baseline(float(baseline), str(row.get("unit")))
        base_var = row.get("baseline_variance_pct")
        about.append((f"{window}trailing baseline".capitalize(),
                      text + (f" ({base_var * 100:+.1f}% against it)" if not missing(base_var) else "")))
    if is_caveated(row) and status != STATUS_NOT_COMPUTABLE:
        # A caveated gap is not judged anywhere on the tile, including here.
        about.append(("Status", NOT_JUDGED))
        about.append((CAVEAT_TAG, CAVEAT_FOOTER))
    elif status in STATUS_PHRASE:
        about.append(("Status", STATUS_PHRASE[status]))
    layer_about()
    card["about"] = about

    points = trend_points(series_by_month, row)
    if points:
        card["sparkline"] = points
        card["spark_label"] = f"Trend over the 12 months to {_month_key(row['month'])}"
    return card
