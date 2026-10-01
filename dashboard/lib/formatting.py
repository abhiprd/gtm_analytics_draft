"""Small display-formatting helpers shared across dashboard pages.

Formatting only -- no metric math lives here. Values arrive already
computed from a mart or from analytics/*.py's own functions.
"""
import math
from typing import Optional


def usd(v: Optional[float], decimals: int = 0) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "N/A"
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1_000_000:
        return f"{sign}${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{sign}${v / 1_000:.1f}K"
    return f"{sign}${v:,.{decimals}f}"


def pct(v: Optional[float], decimals: int = 1) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "N/A"
    return f"{v * 100:.{decimals}f}%"


def num(v: Optional[float], decimals: int = 0) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "N/A"
    return f"{v:,.{decimals}f}"


def months(v: Optional[float]) -> str:
    """Months with enough precision that a non-zero value never prints as 0.0: one
    decimal from 1 month up, two decimals below 1, '<0.01' for a tiny positive value."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "N/A"
    a = abs(v)
    if a >= 1:
        return f"{v:,.1f}"
    if a == 0:
        return "0.0"
    if a < 0.005:
        return "<0.01" if v > 0 else ">-0.01"
    return f"{v:.2f}"
