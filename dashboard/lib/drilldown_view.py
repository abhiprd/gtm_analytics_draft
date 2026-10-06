"""Presentation rules for the Digest drill-down ranking tables (the Layer-2 sibling table and
the Layer-3 evidence table), Streamlit-free so they are unit-testable
(tests/test_dashboard_drilldown_view.py).

The readout's ranking rows come from analytics/variance_diagnostic.py's `rank_siblings()`.
Each row carries `comparison_basis`, which says how its siblings were ranked:

  relative_deviation  percentage deviation from each child's own trailing baseline (children
                      in different units, so only a normalized comparison is meaningful)
  additive_share      absolute deviation, in the siblings' shared unit (children that are
                      additive components of the parent: NRR/GRR rates, S&M cost legs). A
                      large relative swing on a near-zero component would otherwise outrank
                      the component that actually moved the parent.

So the table caption states the basis the rank was actually computed on, and a row that
carries no usable deviation (a series the engine blanks, such as the censored workflow-chain
tail) shows a dash in the rank column instead of a rank. Nothing here recomputes a rank, a
deviation or a baseline.
"""
from typing import Dict, List, Optional

from . import answers, verdict

BASIS_RELATIVE = "relative_deviation"
BASIS_ADDITIVE = "additive_share"
NO_RANK = "—"


def basis_of(rows: List[Dict]) -> str:
    """The ranking basis of a table: the rows' own `comparison_basis` (the engine sets it per
    parent, so a table has one), relative deviation when none is carried."""
    for r in rows or []:
        b = r.get("comparison_basis")
        if b in (BASIS_RELATIVE, BASIS_ADDITIVE):
            return b
    return BASIS_RELATIVE


def has_signal(row: Dict) -> bool:
    """True when the row has the value the engine ranks on: a value, and a deviation on the
    table's own basis. Rows without one are listed but not ranked."""
    if verdict.missing(row.get("value")):
        return False
    key = "absolute_deviation" if row.get("comparison_basis") == BASIS_ADDITIVE else "deviation_pct"
    return not verdict.missing(row.get(key))


def rank_cell(row: Dict) -> str:
    """The rank as shown: the engine's rank, or a dash when the row has no data to rank."""
    rank = row.get("rank")
    if not has_signal(row) or rank is None:
        return NO_RANK
    return str(rank)


def _unit_of(rows: List[Dict]) -> Optional[str]:
    for r in rows or []:
        if r.get("metric_key"):
            return answers.unit_for_key(r["metric_key"])
    return None


def caption(rows: List[Dict], layer: int) -> str:
    """The line above a ranking table, by the basis the rank was computed on."""
    prefix = f"Layer-{layer} drivers ranked by"
    if basis_of(rows) == BASIS_ADDITIVE:
        unit = _unit_of(rows)
        what = {"usd": "absolute dollar change", "pct": "absolute change in percentage points"}.get(
            unit or "", "absolute change")
        return f"{prefix} {what} from their own trailing baseline (components of a shared total):"
    return f"{prefix} deviation from their own trailing baseline:"


def change_cell(row: Dict) -> str:
    """The signed absolute change from the row's own baseline, in the metric's unit; shown
    only for additive-basis tables, where it is what the rank was computed on."""
    v = row.get("absolute_deviation")
    if verdict.missing(v):
        return "n/a"
    v = float(v)
    unit = answers.unit_for_key(row.get("metric_key") or "")
    if unit == "pct":
        return verdict.unsigned_if_zero(verdict.pp_text(v))
    shown = answers.format_value(unit, abs(v))
    sign = "" if v == 0 else ("+" if v > 0 else "-")
    return f"{sign}{shown}"


def table_dict(rows: List[Dict], label_fn, label_header: str = "Metric",
               extra: Optional[Dict[str, List]] = None) -> Dict[str, List]:
    """Columns for a ranking table. `label_fn(row)` supplies the metric label, shown
    under `label_header`; `extra` columns follow it. A 'Change vs baseline' column is added for an additive-basis table; the rank column is last."""
    cols: Dict[str, List] = {label_header: [label_fn(r) for r in rows]}
    for name, values in (extra or {}).items():
        cols[name] = values
    cols["Value"] = [answers.format_for_key(r["metric_key"], r.get("value")) for r in rows]
    cols["Baseline"] = [answers.format_for_key(r["metric_key"], r.get("baseline")) for r in rows]
    cols["Deviation"] = [r.get("deviation_display") or "n/a" for r in rows]
    if basis_of(rows) == BASIS_ADDITIVE:
        cols["Change vs baseline"] = [change_cell(r) for r in rows]
    cols["Rank"] = [rank_cell(r) for r in rows]
    return cols
