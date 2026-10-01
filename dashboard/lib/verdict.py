"""Scorecard-row treatment rules, Streamlit-free so they are unit-testable
(tests/test_dashboard_verdict.py).

The weekly readout carries a status per Layer-1 row (Ahead, Behind, On track, Not
computable) plus a `plan_comparability` flag. This module decides how a row is
presented, without recomputing any figure:

  * caveated   -- `plan_comparability == "caveated"`: the plan and the actual exist
                  and the variance is computed, but their LEVELS are not on the same
                  footing. The card carries a visible "Caveated comparison" tag and the
                  delta is shown with no favorable/unfavorable color or arrow, so the
                  Ahead/Behind status never reads as a business finding.
  * degenerate -- status "Not computable" with an actual, a prior value and a baseline
                  that are all the same number (blended TTFA is 0 in every month): the
                  card says "Not computable" in place of the number.
  * neutral    -- a delta that rounds to zero at its displayed precision carries no
                  status color and no arrow.

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


def card_for_row(row: Dict, pillar: Optional[str] = None, baseline_months: Optional[int] = None) -> Dict:
    """The theme.scorecard_row() dict for one readout scorecard row."""
    row = _display_row(row)
    status = row.get("status")
    pillar = pillar or row.get("pillar")
    footer: List[str] = []
    card: Dict = dict(label=row["label"], pillar=pillar, value_display=row.get("value_display", "n/a"))

    if is_degenerate(row):
        card["value_display"] = "Not computable"
        card["value_size"] = "sm"
        card["tag"] = "No variation in data"
        footer.append(f"{row['label']} does not vary in the data, so no variance can be computed.")
        footer.append(f"Basis: {basis_label(row)}")
        if row.get("layer") is not None:
            footer.append(f"Layer {row['layer']}")
        card["footer"] = [f for f in footer if f]
        return card

    variance = row.get("variance_display")
    comparison = row.get("comparison_display")
    direction = row.get("favorable_direction")
    ahead = is_ahead_for(status)

    if status == STATUS_NOT_COMPUTABLE:
        card.update(variance_display="n/a · Not computable", comparison_display=None,
                    favorable_direction=None, is_ahead=None)
    elif status == STATUS_ON_TRACK:
        card.update(variance_display=f"● On track · {variance}", comparison_display=comparison,
                    favorable_direction=None, is_ahead=None)
    elif is_caveated(row):
        # Neutral treatment: the sign and size of the gap are shown, the judgment is not.
        card.update(variance_display=variance, comparison_display=comparison,
                    favorable_direction=None, is_ahead=None, tag=CAVEAT_TAG)
    elif display_rounds_to_zero(variance):
        card.update(variance_display=variance, comparison_display=comparison,
                    favorable_direction=None, is_ahead=None)
    else:
        card.update(variance_display=variance, comparison_display=comparison,
                    favorable_direction=direction, is_ahead=ahead)

    if row.get("unit_label"):
        footer.append(str(row["unit_label"]))
    footer.append(f"Basis: {basis_label(row)}")
    baseline = row.get("trailing_baseline")
    if not missing(baseline):
        window = f"{baseline_months}-mo " if baseline_months else ""
        text = format_baseline(float(baseline), str(row.get("unit")))
        base_var = row.get("baseline_variance_pct")
        footer.append(f"{window}trailing baseline: {text}"
                      + (f" ({base_var * 100:+.1f}%)" if not missing(base_var) else ""))
    if is_caveated(row) and status != STATUS_NOT_COMPUTABLE:
        footer.append(CAVEAT_FOOTER)
    if row.get("layer") is not None:
        footer.append(f"Layer {row['layer']}")
    card["footer"] = footer
    return card
