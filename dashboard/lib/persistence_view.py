"""Presentation rules for the weekly readout's drill-down `persistence` record,
Streamlit-free so they are unit-testable (tests/test_dashboard_persistence_view.py).

The record is produced by analytics/variance_diagnostic.py's compute_persistence() and
carried verbatim in each drill-down entry. This module only decides how it is shown; it
never recomputes a streak, a threshold or a deviation.

What the marker is, and is not. It says the same Layer-2 driver was the largest adverse
outlier against its own trailing baseline in consecutive months. It is a repeat detector:
an independent profile found it fires about as often on shuffled, unrelated months as on
real data (the methods document records the figures), because with two or three siblings a
volatile sibling is the top outlier in most months. So the chip reads "Repeat", never
"Persistent trend", and no text here claims a trend or a cause.

State -> display:
  flagged         chip "Repeat: N consecutive months" (neutral gray: a marker, not a
                  status judgment), a streak line, the engine's note, the streak table
  not_flagged     no chip; the line "Streak N of K months", the note, the streak table
  not_applicable  no chip; "Repeat marker: not applicable." with the reason
  absent          the entry carries no record (an older readout): no chip, a plain line
"""
from typing import Dict, List, Optional

from . import labels

STATUS_FLAGGED = "flagged"
STATUS_NOT_FLAGGED = "not_flagged"
STATUS_NOT_APPLICABLE = "not_applicable"
KIND_ABSENT = "absent"

# Reader-facing wording for a not_applicable record, used only when the record carries no
# note of its own (the engine writes one for every code).
NOT_APPLICABLE_REASONS = {
    "single_candidate_read": ("Only one Layer-2 child has a computable value, so there is no "
                             "sibling comparison and no streak is tracked."),
    "no_layer2_outlier": "No Layer-2 outlier was identified, so there is no driver to track.",
    "truncated_final_month": ("The evaluation month is the truncated final month of the data "
                              "window, so no streak is computed."),
    "no_adverse_direction_defined": "The driver has no defined adverse direction, so no streak is computed.",
}

BREAK_TEXT = {
    "driver_changed": "a different driver was the largest outlier",
    "not_adverse": "the same driver was not moving in the adverse direction",
    "tie_at_top": "two siblings tied for the largest outlier",
    "no_sibling_comparison": "fewer than 2 siblings had a computable value",
    "start_of_history": "no earlier months are available",
}

clean_node_label = labels.clean_node_label


def _months(n: int) -> str:
    return f"{n} month" if n == 1 else f"{n} months"


def threshold_phrase(p: Dict) -> Optional[str]:
    """'2 months, proposed' from threshold_months and threshold_status; None when the
    record carries no threshold."""
    k = p.get("threshold_months")
    if not isinstance(k, int):
        return None
    status = str(p.get("threshold_status") or "").strip().lower()
    if status.startswith("proposed"):
        return f"{_months(k)}, proposed"
    return f"{_months(k)}, {status}" if status else _months(k)


def chip_text(p: Optional[Dict]) -> Optional[str]:
    """The compact chip: only for a flagged record, never for any other state."""
    if not p or p.get("status") != STATUS_FLAGGED:
        return None
    n = p.get("streak_months")
    if not isinstance(n, int) or n < 1:
        return None
    return f"Repeat: {n} consecutive months"


def streak_line(p: Optional[Dict]) -> str:
    """The plain status line shown at the top of the expander's persistence block."""
    if not p:
        return "Repeat marker: not in this readout."
    status = p.get("status")
    n = p.get("streak_months")
    k = p.get("threshold_months")
    if status == STATUS_NOT_APPLICABLE:
        return "Repeat marker: not applicable."
    if status == STATUS_FLAGGED and isinstance(n, int):
        # The threshold's own status travels with it ("2 months, proposed"): the line is read
        # on its own, away from the page's scope note.
        phrase = threshold_phrase(p)
        marker = f" (marker threshold: {phrase})" if phrase else ""
        return f"Streak: {_months(n)}{marker}"
    if status == STATUS_NOT_FLAGGED and isinstance(n, int) and isinstance(k, int):
        return f"Streak {n} of {_months(k)}"
    return "Repeat marker: not in this readout."


def caveat_text(p: Optional[Dict]) -> Optional[str]:
    """The engine's own caveat for the record ('...not evidence of a trend or cause'), shown
    under the streak line; None when the record carries none."""
    text = (p or {}).get("caveat")
    return clean_node_label(text) if text else None


def basis_line(p: Optional[Dict]) -> Optional[str]:
    """'Basis: the same Layer-2 driver ...': the engine's basis sentence under a label, with
    its first letter lowered so the line reads as one sentence, not 'Basis: The ...'."""
    text = str((p or {}).get("basis") or "").strip()
    if not text:
        return None
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        text = text[0].lower() + text[1:]
    return f"Basis: {text}"


def reason_text(p: Optional[Dict]) -> Optional[str]:
    """Why a record is not applicable, as a sentence: the engine's own note, else a mapped
    reason code, else the humanized code."""
    if not p or p.get("status") != STATUS_NOT_APPLICABLE:
        return None
    if p.get("note"):
        return clean_node_label(p["note"])
    code = p.get("reason")
    if code in NOT_APPLICABLE_REASONS:
        return NOT_APPLICABLE_REASONS[code]
    return (str(code).replace("_", " ").capitalize() + ".") if code else None


def note_text(p: Optional[Dict]) -> Optional[str]:
    """The engine's persistence note, labels cleaned, for any record that has one."""
    if not p or not p.get("note"):
        return None
    return clean_node_label(p["note"])


def break_text(p: Optional[Dict]) -> Optional[str]:
    """Why a flagged streak starts where it does: the month before it and what differed.
    Only for a flagged record: a not_flagged note already carries this."""
    if not p or p.get("status") != STATUS_FLAGGED:
        return None
    brk = p.get("streak_break")
    if not brk or brk.get("reason") not in BREAK_TEXT:
        return None
    month = str(brk.get("month") or "")[:7]
    text = BREAK_TEXT[brk["reason"]]
    out = f"Month before the streak ({month}): {text}"
    if brk["reason"] == "driver_changed" and brk.get("outlier_label"):
        out += f", {clean_node_label(brk['outlier_label'])}"
    return out + "."


def deviation_text(v) -> str:
    """A signed deviation fraction as a percentage: -0.2178 -> '-21.8%'; one that rounds
    to zero carries no sign."""
    if v is None:
        return "n/a"
    shown = f"{float(v) * 100:+.1f}%"
    return shown.lstrip("+-") if float(shown.rstrip("%")) == 0.0 else shown


def streak_rows(p: Optional[Dict]) -> List[Dict]:
    """The streak detail, oldest month first: month (YYYY-MM), deviation, baseline months."""
    if not p:
        return []
    rows = []
    for d in sorted(p.get("streak_detail") or [], key=lambda d: str(d.get("month"))):
        rows.append({
            "Month": str(d.get("month"))[:7],
            "Deviation from own trailing baseline": deviation_text(d.get("deviation_pct")),
            "Baseline months": d.get("baseline_n"),
        })
    return rows


def adverse_direction_text(p: Optional[Dict]) -> Optional[str]:
    d = (p or {}).get("adverse_direction")
    if d in ("up", "down"):
        return f"Adverse direction for this driver: {d}."
    return None


def state(p: Optional[Dict]) -> Dict:
    """Everything the page needs for one drill-down entry, in one dict."""
    status = (p or {}).get("status") if p else None
    kind = status if status in (STATUS_FLAGGED, STATUS_NOT_FLAGGED, STATUS_NOT_APPLICABLE) else KIND_ABSENT
    if kind == KIND_ABSENT:
        p = None
    return {
        "kind": kind,
        "chip": chip_text(p),
        "line": streak_line(p),
        "note": reason_text(p) if kind == STATUS_NOT_APPLICABLE else note_text(p),
        "break_text": break_text(p),
        "rows": streak_rows(p),
        "adverse_direction": adverse_direction_text(p) if kind != STATUS_NOT_APPLICABLE else None,
        "basis": (p or {}).get("basis") if kind == STATUS_FLAGGED else None,
        "basis_line": basis_line(p) if kind == STATUS_FLAGGED else None,
        "caveat": caveat_text(p) if kind != KIND_ABSENT else None,
    }


# The profile of the marker on shuffled months (the methods document records the figures:
# about 17.7% of shuffled months flag against 17.1% of real ones) is why the page says what the
# marker is not. Shown with the other repeat-marker scope line in Notes & assumptions.
CHANCE_LEVEL_NOTE = ("In aggregate the marker appears about as often on shuffled months as on real data; "
                     "it is a repeat marker, not evidence of a trend or cause.")


def scope_notes(entries: List[Dict]) -> List[str]:
    """Every repeat-marker line for Notes & assumptions (all labelled Scope): the scope line
    with the threshold, then the chance-level line. Empty when no entry carries a record."""
    first = scope_note(entries)
    return [first, CHANCE_LEVEL_NOTE] if first else []


def scope_note(entries: List[Dict]) -> Optional[str]:
    """The single page-level Scope line for the repeat marker, or None when no entry
    carries a record. The threshold phrase comes from the first record that has one."""
    records = [e.get("persistence") for e in entries if state(e.get("persistence"))["kind"] != KIND_ABSENT]
    if not records:
        return None
    phrase = next((threshold_phrase(r) for r in records if threshold_phrase(r)), None)
    suffix = f" (threshold {phrase})" if phrase else ""
    return ("The repeat marker shows the same driver as the adverse outlier in consecutive months; "
            f"it does not establish a trend or a cause{suffix}.")
