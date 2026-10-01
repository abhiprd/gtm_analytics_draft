"""Streamlit-free forecast display rules (tests/test_dashboard_forecast_logic.py).

  * late-quarter note   -- the CRO-adjusted lens can exceed the remaining open pipeline
                           late in a quarter (the override is a quarter-level dollar
                           delta that is not scaled to the shrinking pipeline).
  * readout comparison  -- the Forecast page re-runs the forecast live; where its call
                           date matches a weekly readout the two should agree. ML-lens
                           differences up to ML_TOLERANCE are rebuild noise and are
                           informational; any other lens differing is a warning.
  * AUC position        -- 'within', 'above' or 'below' the target range. Above the range
                           is not low, so it never takes the unfavorable treatment.
"""
import calendar
import math
from datetime import date
from typing import Dict, List, Optional, Tuple

ML_LENS = "ml"
# The ML lens varies by up to roughly half a percent across dbt rebuilds of the same
# data; 1% separates that noise from a real difference.
ML_TOLERANCE = 0.01
# Every other lens is deterministic given the data: near-zero tolerance.
EXACT_ABS_TOLERANCE = 1.0
EXACT_REL_TOLERANCE = 1e-6

LENS_FIELDS = ("bottoms_up_rep", "bottoms_up_manager", "ml", "cro_adjusted", "open_pipeline_amount")
FIELD_LABELS = {
    "bottoms_up_rep": "Bottoms-up (rep)",
    "bottoms_up_manager": "Bottoms-up (manager)",
    "ml": "ML",
    "cro_adjusted": "CRO-adjusted",
    "open_pipeline_amount": "Open pipeline",
}


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def fmt_usd(v: float) -> str:
    """The readout's own dollar rule (analytics/weekly_readout.py `_fmt_usd`)."""
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:,.2f}M"
    if abs(v) >= 1_000:
        return f"${v / 1_000:,.1f}K"
    return f"${v:,.0f}"


def days_to_quarter_end(period: str, call_date: date) -> Optional[int]:
    """Days from `call_date` to the last day of the quarter named by `period`
    ('2025-Q2'); None when the period string is not of that form."""
    try:
        year_text, q_text = str(period).split("-Q")
        year, quarter = int(year_text), int(q_text)
        month = quarter * 3
        end = date(year, month, calendar.monthrange(year, month)[1])
    except (ValueError, TypeError):
        return None
    return (end - call_date).days


def lens_exceeds_pipeline(row: Dict) -> bool:
    """True when the CRO-adjusted lens is larger than the open pipeline it prices."""
    cro, pipeline = row.get("cro_adjusted"), row.get("open_pipeline_amount")
    if _missing(cro) or _missing(pipeline):
        return False
    return float(cro) > float(pipeline)


def late_quarter_note(row: Dict, days_left: Optional[int] = None) -> Optional[str]:
    """A one-sentence on-card note when the headline lens exceeds the remaining open
    pipeline, derived from the row's own figures; None otherwise."""
    if not lens_exceeds_pipeline(row):
        return None
    ratio = float(row["cro_adjusted"]) / float(row["open_pipeline_amount"]) if float(row["open_pipeline_amount"]) else None
    when = f" with {days_left} days left in the quarter" if days_left is not None and days_left >= 0 else ""
    times = f" ({ratio:.1f}x)" if ratio is not None else ""
    return (f"The CRO-adjusted lens exceeds the {fmt_usd(float(row['open_pipeline_amount']))} still open"
            f"{times}{when}: the CRO override is a quarter-level amount and is not scaled to the remaining deals.")


def compare_to_readout(page_rows: List[Dict], readout_segments: List[Dict], readout_date: str) -> List[Dict]:
    """Findings from comparing the live forecast rows with a readout's forecast
    section for the same call date. Each finding is
    {severity: 'info'|'warning', text, segment, lens, pct_diff}."""
    findings: List[Dict] = []
    by_seg = {r["segment"]: r for r in readout_segments}
    for r in page_rows:
        other = by_seg.get(r["segment"])
        if other is None:
            findings.append(dict(severity="warning", segment=r["segment"], lens=None, pct_diff=None,
                                 text=f"{r['segment']} is on this page but not in the weekly readout "
                                      f"for the period ending {readout_date}."))
            continue
        for f in LENS_FIELDS:
            a, b = r.get(f), other.get(f)
            if _missing(a) and _missing(b):
                continue
            label = FIELD_LABELS[f]
            if _missing(a) or _missing(b):
                shown_a = "not computable" if _missing(a) else fmt_usd(float(a))
                shown_b = "not computable" if _missing(b) else fmt_usd(float(b))
                findings.append(dict(severity="warning", segment=r["segment"], lens=f, pct_diff=None,
                                     text=f"{r['segment']}, {label}: {shown_a} here, {shown_b} in the "
                                          f"weekly readout for the period ending {readout_date}."))
                continue
            a, b = float(a), float(b)
            diff = abs(a - b)
            pct = diff / abs(b) if b else (0.0 if diff == 0 else float("inf"))
            if f == ML_LENS:
                if diff <= max(EXACT_ABS_TOLERANCE, EXACT_REL_TOLERANCE * abs(b)):
                    continue
                severity = "info" if pct <= ML_TOLERANCE else "warning"
            else:
                if diff <= max(EXACT_ABS_TOLERANCE, EXACT_REL_TOLERANCE * abs(b)):
                    continue
                severity = "warning"
            pct_text = f"{pct * 100:.1f}%" if math.isfinite(pct) else "n/a"
            if severity == "info":
                text = (f"{r['segment']}: the ML lens differs by {pct_text} from the weekly readout for the "
                        f"period ending {readout_date} ({fmt_usd(a)} here, {fmt_usd(b)} in the readout). "
                        "The ML lens varies slightly across data rebuilds.")
            else:
                text = (f"{r['segment']}, {label}: {fmt_usd(a)} here, {fmt_usd(b)} in the weekly readout for the "
                        f"period ending {readout_date} ({pct_text} difference).")
            findings.append(dict(severity=severity, segment=r["segment"], lens=f, pct_diff=pct, text=text))
    missing_here = sorted(set(by_seg) - {r["segment"] for r in page_rows})
    for seg in missing_here:
        findings.append(dict(severity="warning", segment=seg, lens=None, pct_diff=None,
                             text=f"{seg} is in the weekly readout for the period ending {readout_date} "
                                  "but not on this page."))
    return findings


def auc_position(auc: float, lo: float, hi: float) -> str:
    """'within', 'above' or 'below' the [lo, hi] target range."""
    if auc < lo:
        return "below"
    if auc > hi:
        return "above"
    return "within"


def auc_statement(auc: float, lo: float, hi: float) -> Tuple[str, str]:
    """(position, phrase): e.g. ('above', 'above the 0.70–0.85 target range')."""
    pos = auc_position(auc, lo, hi)
    return pos, f"{pos} the {lo:.2f}–{hi:.2f} target range"
