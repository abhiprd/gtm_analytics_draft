"""Rules for the Digest's "What changed" block, Streamlit-free so they are unit-testable
(tests/test_dashboard_whatchanged_view.py).

The block is one ranked horizontal bar of the Layer-1 gaps that crossed the variance
threshold, taken verbatim from the weekly readout's `drilldowns.entries` (each entry's
`layer1` carries the gap and its display strings; `layer2_outlier` the driver). Nothing is
recomputed: this module orders, labels and colors what the readout already holds.

  order     descending by the absolute size of the gap, so the largest bar is on top
  color     status color (favorable/unfavorable) when the comparison is comparable, so
            the bar carries the same judgment as the verdict tile; a caveated comparison
            is neutral gray with no judgment, matching the tile's "Caveated" marker
  label     the readout's own signed `variance_display`, plus the status word whenever a
            judgment applies, so color is never the only carrier of good or bad
  twin      a table of the same rows plus each row's Layer-2 outlier and repeat marker
"""
from typing import Dict, List, Optional

from . import labels, persistence_view, verdict

FAVORABLE = "favorable"
UNFAVORABLE = "unfavorable"
NEUTRAL = "neutral"
PLAN_BASIS = "plan_diff"

AXIS_TITLE_PLAN = "Gap to plan (%)"
AXIS_TITLE_OTHER = "Gap to comparison (%)"


def judgment(entry: Dict, caveated: bool) -> str:
    """favorable / unfavorable / neutral for one drill-down entry. A caveated comparison
    is neutral whatever its Ahead/Behind status."""
    if caveated:
        return NEUTRAL
    status = entry["layer1"].get("status")
    if status == verdict.STATUS_AHEAD:
        return FAVORABLE
    if status == verdict.STATUS_BEHIND:
        return UNFAVORABLE
    return NEUTRAL


def _gap(entry: Dict) -> Optional[float]:
    v = entry["layer1"].get("variance_pct")
    return None if verdict.missing(v) else float(v)


def bar_label(gap_display: str, kind: str, caveated: bool) -> str:
    """'+128.2% Ahead' for a judged row; the bare signed gap for a neutral one (a caveated
    row is gray with no judgment word, and the chart's color key and the table view say
    so)."""
    if kind == FAVORABLE:
        return f"{gap_display} Ahead"
    if kind == UNFAVORABLE:
        return f"{gap_display} Behind"
    return gap_display


def rows(entries: List[Dict], caveated_keys: set) -> List[Dict]:
    """One dict per entry that carries a numeric gap, largest absolute gap first.
    `caveated_keys` is the set of Layer-1 metric keys whose scorecard row is caveated."""
    out = []
    for e in entries or []:
        gap = _gap(e)
        if gap is None:
            continue
        l1, l2 = e["layer1"], e.get("layer2_outlier")
        caveated = l1["metric_key"] in caveated_keys
        kind = judgment(e, caveated)
        persist = persistence_view.state(e.get("persistence"))
        out.append(dict(
            metric_key=l1["metric_key"], label=l1["label"], pillar=l1.get("pillar"), layer=l1.get("layer"),
            gap=gap, gap_display=l1.get("variance_display") or "", status=l1.get("status"),
            mechanism=l1.get("mechanism"), caveated=caveated, kind=kind,
            bar_label=bar_label(l1.get("variance_display") or "", kind, caveated),
            layer2_label=(labels.qualified_node_label(l2["metric_key"], l2["label"]) if l2 else None),
            layer2_deviation=(None if not l2 or verdict.missing(l2.get("deviation_pct"))
                              else f'{l2["deviation_pct"] * 100:+.1f}%'),
            repeat=persist["chip"] or "",
        ))
    out.sort(key=lambda r: abs(r["gap"]), reverse=True)
    for i, r in enumerate(out, start=1):
        r["rank"] = i
    return out


def axis_title(rs: List[Dict]) -> str:
    return AXIS_TITLE_PLAN if rs and all(r["mechanism"] == PLAN_BASIS for r in rs) else AXIS_TITLE_OTHER


def table_rows(rs: List[Dict]) -> List[Dict]:
    """The table-view twin: every value the chart shows, plus the Layer-2 driver."""
    pillar_label = {"growth": "Growth", "efficiency": "Efficiency", "durability": "Durability"}
    return [{
        "Rank": r["rank"],
        "Metric": r["label"],
        "Pillar": pillar_label.get(r["pillar"], str(r["pillar"] or "").title()),
        "Gap": r["gap_display"],
        "Status": ("Caveated comparison" if r["caveated"] else str(r["status"] or "")),
        "Layer-2 outlier": r["layer2_label"] or "None computable",
        "Outlier against its own baseline": r["layer2_deviation"] or "",
        "Repeat marker": r["repeat"],
    } for r in rs]


def caveat_note(n_caveated: int, n_total: int) -> Optional[str]:
    """The one section-level statement of the caveated comparison (conventions 4.10);
    None when no tile is caveated."""
    if not n_caveated:
        return None
    return (f"{n_caveated} of {n_total} tiles carry the ⓘ marker: their plan is not on the same footing "
            "as the actual, so the gap is shown in gray with no judgment. The size of the gap is not a "
            "business finding on its own.")


def intro_text(rs: List[Dict], nodes_total: int, threshold_pct: float) -> str:
    """The sentence above the chart. It states the caveated count itself, so the caveat does
    not live only in the chart's color key."""
    n = len(rs)
    n_cav = sum(1 for r in rs if r["caveated"])
    text = (f"{n} of {nodes_total} Layer-1 metrics are outside \u00b1{threshold_pct:.0f}% of plan, "
            "ranked by the size of the gap.")
    if n_cav:
        text += (f" {n_cav} of {n} {'is a caveated comparison' if n_cav == 1 else 'are caveated comparisons'},"
                 " shown in gray without a verdict.")
    return text
