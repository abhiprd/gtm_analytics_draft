"""Right-censored workflow-chain months (dashboard/lib/censoring.py) and how the Ask answer
uses them. The tail length is tied to analytics/variance_diagnostic.py's own constant and to
its _drop_censored_chain_tail() behavior, so the dashboard table cannot drift from the
engine that blanks the same months on the Digest."""
import json
import os
import sys

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from analytics import variance_diagnostic as vd  # noqa: E402
from dashboard.lib import answers as A  # noqa: E402
from dashboard.lib import censoring  # noqa: E402

with open(os.path.join(REPO, "semantic", "metric_registry.json")) as _f:
    METRICS = json.load(_f)["metrics"]


class TestTiedToTheEngine:
    def test_every_tail_length_equals_the_engines_constant(self):
        for key, n in censoring.CENSORED_TAIL_MONTHS.items():
            assert n == vd._WORKFLOW_CHAIN_PRECHURN_MONTHS, key

    def test_every_key_is_a_registry_node_and_has_an_engine_node(self):
        assert set(censoring.ENGINE_KEY) == set(censoring.CENSORED_TAIL_MONTHS)
        for key, engine_key in censoring.ENGINE_KEY.items():
            assert key in METRICS
            assert engine_key in vd._TREE

    def test_the_months_dropped_by_the_engine_are_the_months_excluded_here(self):
        months = pd.date_range("2024-01-01", "2025-12-01", freq="MS")
        series = pd.Series(range(len(months)), index=months)

        class Con:
            def execute(self, sql):
                class R:
                    def fetchone(self_inner):
                        return (pd.Timestamp("2025-12-01"),)
                return R()

        kept = vd._drop_censored_chain_tail(series, Con())
        dropped = [d.strftime("%Y-%m-01") for d in series.index.difference(kept.index)]
        assert dropped == censoring.censored_months("workflow_chain_under_utilization", "2025-12-01")
        assert len(dropped) == vd._WORKFLOW_CHAIN_PRECHURN_MONTHS


class TestCensoredMonths:
    def test_tail_counts_back_from_and_includes_the_final_month(self):
        assert censoring.censored_months("mid_chain_workflow_abandonment", "2025-12-01") == [
            "2025-08-01", "2025-09-01", "2025-10-01", "2025-11-01", "2025-12-01"]

    def test_year_boundary(self):
        assert censoring.censored_months("workflow_chain_under_utilization", "2026-02-01")[0] == "2025-10-01"

    def test_other_nodes_have_no_tail_and_exclude_only_the_final_month(self):
        assert censoring.censored_months("win_rate", "2025-12-01") == []
        assert censoring.excluded_months("win_rate", "2025-12-01") == ["2025-12-01"]
        assert censoring.excluded_months("win_rate", None) == []

    def test_text_names_the_range(self):
        assert censoring.tail_range_text("workflow_chain_under_utilization", "2025-12-01") == "2025-08 to 2025-12"
        assert "2025-08 to 2025-12" in censoring.tail_sentence("workflow_chain_under_utilization", "2025-12-01")
        assert censoring.card_tag("win_rate") is None
        assert "Last 5 months excluded" in censoring.card_tag("workflow_chain_under_utilization")


def _series_query(metric, dimensions=None, filters=None, grain="month", date_range=None):
    node = METRICS[metric]
    base = {"metric": {"key": metric, "name": node["name"], "formula": node["formula"],
                       "formula_note": node["formula_note"]}}
    months = pd.date_range("2025-03-01", "2025-12-01", freq="MS")
    rows = [{"period": d.strftime("%Y-%m-%d"), "value": 0.05 - 0.004 * i} for i, d in enumerate(months)]
    return dict(base, data=rows, warnings=[], sql="select 1", query={})


class TestAskAnswer:
    def _answer(self, key="workflow_chain_under_utilization"):
        parsed = {"raw_question": "q", "resolved_metric": key, "dimensions": [], "filters": {}, "grain": "month",
                  "secondary_metrics": [], "segment_subset": [], "suggestions": []}
        return A.build_answer(parsed, _series_query, METRICS, partial_month="2025-12-01")

    def test_headline_is_the_last_uncensored_month(self):
        a = self._answer()
        assert a["own"]["period"] == "2025-07-01" and a["own"]["headline_is_partial"] is False
        assert a["own"]["censored_months"][0] == "2025-08-01"
        assert a["own"]["censored_tag"] and a["own"]["censored_note"]
        assert a["own"]["newest_partial_label"] == "2025-12"

    def test_children_align_to_the_same_period_and_carry_the_tail_note(self):
        a = self._answer()
        assert a["children"], "workflow chain under-utilization has Layer-3 children"
        for c in a["children"]:
            assert c["period"] == "2025-07-01" and c["aligned"] is True
            assert "2025-08 to 2025-12" in c["tail_note"]

    def test_a_node_without_a_tail_headlines_the_month_before_the_final_month(self):
        a = self._answer("win_rate")
        assert a["own"]["period"] == "2025-11-01"
        assert a["own"]["censored_months"] == [] and a["own"]["censored_tag"] is None

    def test_data_table_flags_the_excluded_months(self):
        a = self._answer()
        rows = A.table_rows(a["own"]["result"], "pct", "month", "2025-12-01", censored=a["own"]["censored_months"])
        notes = {r["Period"]: r["Note"] for r in rows}
        assert notes["2025-07"] == "" and notes["2025-08"] == censoring.EXCLUDED_LABEL
        assert notes["2025-12"] == censoring.EXCLUDED_LABEL

    def test_without_a_censored_tail_the_final_month_reads_partial(self):
        a = self._answer("win_rate")
        rows = A.table_rows(a["own"]["result"], "pct", "month", "2025-12-01")
        assert {r["Period"]: r["Note"] for r in rows}["2025-12"] == "Partial month"

    def test_quarter_grain_skips_a_quarter_that_contains_a_censored_month(self):
        result = {"data": [{"period": "2025-04-01", "value": 0.05}, {"period": "2025-07-01", "value": 0.04},
                           {"period": "2025-10-01", "value": 0.01}]}
        excluded = censoring.excluded_months("workflow_chain_under_utilization", "2025-12-01")
        assert A.last_complete_period(result, "quarter", excluded) == "2025-04-01"
