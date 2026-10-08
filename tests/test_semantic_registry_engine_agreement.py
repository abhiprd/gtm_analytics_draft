"""Registry (semantic/metric_registry.json) versus the variance-diagnostic engine
(analytics/variance_diagnostic.py): the two must tell the same story about which
metric-tree nodes are computable.

Covers the 14 nodes wired to the deal-funnel, workflow-chain, utilization and
account-health marts, Activation and its children, and a sweep over every node the
two share, where each remaining difference is named with its reason. A new,
unexplained disagreement fails the sweep.

Reads data/acme_gtm.duckdb read-only; skipped when the database is absent.

Run: python3 -m pytest tests/test_semantic_registry_engine_agreement.py -v
"""
import json
import os
import re
import sys
from datetime import date

import duckdb
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB_PATH = os.path.join(ROOT, "data", "acme_gtm.duckdb")
REGISTRY_PATH = os.path.join(ROOT, "semantic", "metric_registry.json")

pytestmark = pytest.mark.skipif(
    not os.path.exists(DB_PATH), reason="dbt-built database not present; run `cd dbt && dbt build`")

from analytics import variance_diagnostic as vd  # noqa: E402

with open(REGISTRY_PATH, encoding="utf-8") as _f:
    REGISTRY = json.load(_f)
METRICS = REGISTRY["metrics"]

ENGINE_STATUS = {vd.COMPUTABLE: "full", vd.PARTIAL: "partial", vd.NOT_COMPUTABLE: "not_computable"}

# registry key -> engine key for the 14 nodes wired to the Wave 10 marts
WIRED = {
    "poc_pass_rate": "poc_pass_rate",
    "rep_capacity_ramp_mix": "rep_capacity_ramp_mix",
    "loss_reason_mix": "loss_reason_mix",
    "discount_rate_vs_list": "discount_rate_vs_list",
    "deal_size_trend_within_segment_band": "deal_size_trend_within_band",
    "renewal_win_rate": "renewal_win_rate",
    "workflow_chain_under_utilization": "workflow_chain_underutilization",
    "ingestion_without_completion_rate": "ingestion_without_completion_rate",
    "mid_chain_workflow_abandonment": "mid_chain_abandonment",
    "declining_share_of_full_chain_vs_partial_chain_runs": "full_vs_partial_chain_share",
    "overage_realization": "overage_realization",
    "support_ticket_volume_severity": "support_ticket_volume_severity",
    "engagement_login_frequency": "engagement_login_frequency",
    "am_sentiment_notes": "am_sentiment_notes",
}

# Differences that are intentional, with the reason. Engine key -> reason.
INTENTIONAL_DIFFERENCES = {
    "pipeline_generated": "computed by analytics/marketing_attribution.py from the lead panel, "
                          "not a mart_* column query_metric can serve",
    "organic_content": "leg of pipeline_generated, same reason",
    "paid": "leg of pipeline_generated, same reason",
    "community_events": "leg of pipeline_generated, same reason",
    "usage_trend_account_relative": "account-relative signal computed in the engine from "
                                    "mart_account_health, not a plain mart column",
    "cyclical_vs_structural_usage_dip": "needs a same-account-type cohort baseline no mart exposes; "
                                        "only the underlying usage signal exists",
}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _registry_key_for(engine_key, node):
    if engine_key in METRICS:
        return engine_key
    by_norm = {_norm(k): k for k in METRICS}
    if _norm(engine_key) in by_norm:
        return by_norm[_norm(engine_key)]
    for k, m in METRICS.items():
        if _norm(m["name"]) == _norm(node.label):
            return k
    return None


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(DB_PATH, read_only=True)
    yield c
    c.close()


class TestWiredNodes:
    @pytest.mark.parametrize("reg_key,eng_key", sorted(WIRED.items()))
    def test_registry_and_engine_agree(self, reg_key, eng_key):
        assert METRICS[reg_key]["computability"] == ENGINE_STATUS[vd.get_node(eng_key).computability]


class TestActivationBranch:
    def test_the_series_is_exactly_zero_in_every_segment_month(self, con):
        rows = con.execute(
            "select segment, count(activation_ttfa_months_avg), "
            "min(activation_ttfa_months_avg), max(activation_ttfa_months_avg) "
            "from main_marts.mart_growth_bridge group by 1").fetchall()
        assert {r[0] for r in rows} == {"SMB", "Commercial", "Enterprise"}
        for segment, n, lo, hi in rows:
            assert n > 0 and lo == 0 and hi == 0, segment
        # a month with no signups in a segment has no TTFA at all (null), never a nonzero value
        assert con.execute(
            "select count(*) from main_marts.mart_growth_bridge "
            "where signup_cohort_size > 0 and activation_ttfa_months_avg is null").fetchone()[0] == 0

    def test_the_engine_reports_activation_not_computable(self):
        card = vd.compute_layer1_scorecard(date(2025, 11, 30))
        row = card[card["metric_key"] == "activation"].iloc[0]
        assert row["status"] == "Not computable" and row["mechanism"] == "trailing_baseline"
        assert row["actual"] == 0.0 and row["trailing_baseline"] == 0.0

    def test_registry_marks_activation_partial_and_still_queryable(self):
        node = METRICS["activation"]
        assert node["computability"] == "partial" and node["computable"] is True
        assert node["source_mart"] == "mart_growth_bridge"
        assert "identically 0" in node["gap_note"] and "no variance can be computed" in node["gap_note"]
        assert node["queryable_segments"] == ["SMB", "Commercial", "Enterprise"]

    def test_onboarding_completion_rate_agrees_with_the_engine(self):
        assert vd.get_node("onboarding_completion_rate").computability == vd.PARTIAL
        assert METRICS["onboarding_completion_rate"]["computability"] == "partial"

    @pytest.mark.parametrize("reg_key,eng_key", [
        ("time_to_first_integration_first_successful_run", "time_to_first_integration"),
        ("quickstart_docs_content_engagement_rate", "quickstart_docs_engagement_rate"),
    ])
    def test_not_computable_children_agree(self, reg_key, eng_key):
        assert vd.get_node(eng_key).computability == vd.NOT_COMPUTABLE
        assert METRICS[reg_key]["computability"] == "not_computable"
        assert METRICS[reg_key]["computable"] is False and METRICS[reg_key]["gap_note"]

    def test_the_branch_hierarchy_matches(self):
        reg_children = METRICS["activation"]["children"]
        eng_children = [k for k, n in vd._TREE.items() if n.parent_key == "activation"]
        assert len(reg_children) == len(eng_children) == 3
        assert all(METRICS[c]["parent"] == "activation" for c in reg_children)


class TestFullSweep:
    def test_every_difference_is_documented(self):
        unexplained, seen = [], set()
        for eng_key, node in vd._TREE.items():
            reg_key = _registry_key_for(eng_key, node)
            if reg_key is None:
                continue
            if eng_key == "activation":
                continue  # compared on the engine's readout outcome in TestActivationBranch
            if ENGINE_STATUS[node.computability] != METRICS[reg_key]["computability"]:
                if eng_key in INTENTIONAL_DIFFERENCES:
                    seen.add(eng_key)
                else:
                    unexplained.append((eng_key, node.computability, METRICS[reg_key]["computability"]))
        assert unexplained == []
        # an intentional difference that no longer exists is stale and should be removed
        assert seen == set(INTENTIONAL_DIFFERENCES)

    def test_every_intentional_difference_is_a_registry_non_computable_node_with_a_note(self):
        for eng_key in INTENTIONAL_DIFFERENCES:
            node = vd.get_node(eng_key)
            reg = METRICS[_registry_key_for(eng_key, node)]
            assert reg["computable"] is False and reg["gap_note"]

    def test_a_computable_registry_node_is_never_not_computable_in_the_engine(self):
        for eng_key, node in vd._TREE.items():
            reg_key = _registry_key_for(eng_key, node)
            if reg_key and METRICS[reg_key]["computable"] and eng_key != "activation":
                assert node.computability != vd.NOT_COMPUTABLE, eng_key
