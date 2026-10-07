"""Right-censored months of the workflow-chain series, Streamlit-free so the rule is
unit-testable (tests/test_dashboard_censoring.py).

A partial workflow chain (full-chain completion below the 0.70 cut) exists in the data only
in the months before an account churns, and churns after the end of the data window are not
observed. Every series built on that share therefore falls away across the last months of the
window, and a fall there is not a change in behavior. The variance engine blanks that tail
(`analytics.variance_diagnostic._drop_censored_chain_tail`, which drops the last
`_WORKFLOW_CHAIN_PRECHURN_MONTHS` months of the window from all four workflow-chain series);
the semantic layer's query does not (its registry gap note says so). The Ask page therefore
applies the same exclusion at display time: no headline from a censored month, the months
drawn as open markers and flagged in the data table.

`CENSORED_TAIL_MONTHS` is the one table of affected registry nodes and the length of their
censored tail. The number is tied to the engine's constant by a test, so it cannot drift.
The tail is counted back from the last month of the data window (`data_window.
last_month_in_marts`, the month the engine reads from the mart), inclusive, so it includes the
window's own truncated final month.
"""
from typing import Dict, List, Optional

# Registry key -> months of the data window's tail that are right-censored. The engine
# applies the same exclusion to Workflow chain under-utilization and to its three Layer-3
# legs, the Actions-weighted ingestion-without-completion rate included (the engine's own
# note for that leg carries the censor sentence), so the table matches it node for node.
CENSORED_TAIL_MONTHS: Dict[str, int] = {
    "workflow_chain_under_utilization": 5,
    "ingestion_without_completion_rate": 5,
    "mid_chain_workflow_abandonment": 5,
    "declining_share_of_full_chain_vs_partial_chain_runs": 5,
}

# Registry key -> the variance engine's key for the same node (the engine's tree and label
# table use its own spellings); the tie test checks each engine key exists.
ENGINE_KEY = {
    "workflow_chain_under_utilization": "workflow_chain_underutilization",
    "ingestion_without_completion_rate": "ingestion_without_completion_rate",
    "mid_chain_workflow_abandonment": "mid_chain_abandonment",
    "declining_share_of_full_chain_vs_partial_chain_runs": "full_vs_partial_chain_share",
}

EXCLUDED_LABEL = "Excluded: incomplete window"
PARTIAL_LABEL = "Partial month"


def card_tag(key: Optional[str]) -> Optional[str]:
    """The tag shown on the headline card of an affected node."""
    n = CENSORED_TAIL_MONTHS.get(key or "")
    return f"Last {n} months excluded: incomplete window" if n else None


def is_censored_node(key: Optional[str]) -> bool:
    return key in CENSORED_TAIL_MONTHS


def _shift(month_iso: str, back: int) -> str:
    y, m = int(month_iso[:4]), int(month_iso[5:7])
    idx = y * 12 + (m - 1) - back
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}-01"


def censored_months(key: Optional[str], last_month_in_window: Optional[str]) -> List[str]:
    """ISO first-of-month dates (oldest first) of the censored tail for a registry node,
    counted back from and including the last month of the data window; [] for a node with no
    censored tail or when the window end is unknown."""
    n = CENSORED_TAIL_MONTHS.get(key or "")
    if not n or not last_month_in_window:
        return []
    last = str(last_month_in_window)[:7] + "-01"
    return [_shift(last, i) for i in range(n - 1, -1, -1)]


def excluded_months(key: Optional[str], last_month_in_window: Optional[str]) -> List[str]:
    """Months kept out of a node's headline: its censored tail (which already contains the
    window's truncated final month), or just the truncated final month for any other node."""
    tail = censored_months(key, last_month_in_window)
    if tail:
        return tail
    return [str(last_month_in_window)[:7] + "-01"] if last_month_in_window else []


def tail_range_text(key: Optional[str], last_month_in_window: Optional[str]) -> Optional[str]:
    """'2025-08 to 2025-12' for the censored tail, None when the node has none."""
    months = censored_months(key, last_month_in_window)
    return f"{months[0][:7]} to {months[-1][:7]}" if months else None


def tail_sentence(key: Optional[str], last_month_in_window: Optional[str]) -> Optional[str]:
    """The visible data note for an affected answer, in declarative production voice."""
    rng = tail_range_text(key, last_month_in_window)
    if rng is None:
        return None
    n = CENSORED_TAIL_MONTHS[key]
    return (f"The last {n} months of the data window ({rng}) are excluded from the headline and drawn "
            "as open markers. Partial chains exist only in the months before a churn, and churns "
            "after the end of the window are not observed, so the series falls away there without "
            "a change in behavior.")
