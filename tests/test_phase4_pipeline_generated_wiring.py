"""Pipeline generated in the variance-diagnostic engine: computability markings,
the New-logo drill-down that walks through it, and a cross-artifact consistency
guard against analytics/marketing_attribution.py.

analytics/marketing_attribution.py computes and validates Pipeline generated
and its organic / paid / community legs from fact_leads and
fact_campaign_engagement_events. The engine's tree must agree with that: a node
another shipped artifact already computes cannot be marked NOT_COMPUTABLE.

Reads data/acme_gtm.duckdb (built by `cd dbt && dbt build`); skipped when the
database is absent.

Run: python3 -m pytest tests/test_phase4_pipeline_generated_wiring.py -v
"""
import dataclasses
import json
import os
import sys
from datetime import date

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = "data/acme_gtm.duckdb"
REGISTRY_PATH = "semantic/metric_registry.json"

pytestmark = pytest.mark.skipif(
    not os.path.exists(DB_PATH), reason="dbt-built database not present; run `cd dbt && dbt build`")

from analytics import marketing_attribution as ma  # noqa: E402
from analytics import variance_diagnostic as vd  # noqa: E402

PIPELINE_KEYS = ("pipeline_generated", "organic_content", "paid", "community_events")
HANDOFF_KEYS = ("marketing_sales_handoff_quality", "mql_response_sla",
                "mql_to_sal_acceptance_rate", "lead_recycling_rate")
STALE_PHRASE = "No mart_* table exposes leads"

AS_OF_LATEST = date(2025, 11, 30)
AS_OF_MID = date(2025, 6, 30)
# A month where New logo breaches the threshold and Pipeline generated is the
# genuine Layer-2 outlier, so the Layer-3 channel walk is exercised on real data.
AS_OF_PIPELINE_OUTLIER = date(2024, 8, 31)


class TestTreeMarkings:
    @pytest.mark.parametrize("key", PIPELINE_KEYS)
    def test_pipeline_nodes_are_computable(self, key):
        assert vd.get_node(key).computability == vd.COMPUTABLE

    def test_pipeline_layers_and_parents_are_real(self):
        assert vd.get_node("pipeline_generated").layer == 2
        assert vd.get_node("pipeline_generated").parent_key == "new_logo_consumption_revenue"
        for key in PIPELINE_KEYS[1:]:
            assert vd.get_node(key).layer == 3
            assert vd.get_node(key).parent_key == "pipeline_generated"

    def test_channel_legs_are_additive_components_of_the_parent(self):
        assert vd.get_node("pipeline_generated").sibling_comparison_basis == "additive_share"

    @pytest.mark.parametrize("key", HANDOFF_KEYS)
    def test_handoff_nodes_stay_blocked_with_a_specific_reason(self, key):
        node = vd.get_node(key)
        assert node.computability == vd.NOT_COMPUTABLE
        assert STALE_PHRASE not in node.gap_note
        assert "MQL" in node.gap_note or "lead" in node.gap_note.lower()

    def test_non_additive_nodes_stay_out_of_the_ranking(self):
        ranked = {n.key for n in vd.ranking_siblings_of("new_logo_consumption_revenue")}
        assert ranked == {"pipeline_generated", "win_rate", "avg_initial_commitment"}
        assert not vd.get_node("marketing_sales_handoff_quality").is_ranking_sibling
        assert not vd.get_node("brand_awareness").is_ranking_sibling

    def test_tree_depth_invariants_still_hold(self):
        vd._verify_tree_integrity()
        assert vd.branch_max_depth("new_logo_consumption_revenue") == 3
        for two_deep in ("consumption_payback", "onboarding_cs_efficiency",
                         "activation", "logo_retention"):
            assert vd.branch_max_depth(two_deep) == 2


class TestNewLogoDecomposition:
    @pytest.mark.parametrize("as_of", [AS_OF_LATEST, AS_OF_MID])
    def test_pipeline_generated_competes_among_true_siblings(self, as_of):
        con = vd._connect()
        try:
            series = vd._build_child_series("new_logo_consumption_revenue", as_of, con)
        finally:
            con.close()
        assert set(series) == {"pipeline_generated", "win_rate", "avg_initial_commitment"}
        month = vd._evaluation_month(as_of)
        ranked = vd.rank_siblings("new_logo_consumption_revenue", series, month)
        row = ranked[ranked["metric_key"] == "pipeline_generated"].iloc[0]
        assert row["layer"] == 2 and row["parent_key"] == "new_logo_consumption_revenue"
        assert pd.notna(row["deviation_pct"]) and row["baseline_n"] == vd._TRAILING_BASELINE_MONTHS
        cov = vd._sibling_coverage("new_logo_consumption_revenue", vd._with_signal(
            "new_logo_consumption_revenue", ranked))
        assert cov["eligible_siblings"] == 3 and cov["computable_siblings"] == 3
        assert cov["missing_siblings"] == []

    @pytest.mark.parametrize("as_of", [AS_OF_LATEST, AS_OF_MID])
    def test_channel_legs_sum_to_pipeline_generated_exactly(self, as_of):
        recon = vd.reconcile_pipeline_generated_branch(as_of)
        assert recon["months_checked"] > 0
        assert recon["max_abs_diff_children_to_parent"] <= 1e-9
        assert recon["attribution_tie_out"]["reconciles"]
        assert recon["reconciles"]

    def test_layer3_channel_walk_on_a_real_outlier_month(self):
        result = vd.run_diagnostic(AS_OF_PIPELINE_OUTLIER, include_watchlist=False)
        nl = [d for d in result["drilldowns"] if d.layer1_key == "new_logo_consumption_revenue"]
        assert len(nl) == 1
        dd = nl[0]
        assert dd.layer2_key == "pipeline_generated"
        assert dd.layer3_status == vd.L3_SURFACED
        assert dd.layer3_keys and set(dd.layer3_keys) <= {"organic_content", "paid", "community_events"}
        emitted = dd.to_dict()
        assert emitted["layer2_outlier"]["layer"] == 2
        assert all(leaf["layer"] == 3 and leaf["parent_key"] == "pipeline_generated"
                   for leaf in emitted["layer3_evidence"])
        assert vd.PIPELINE_GENERATED_SCOPE_NOTE in dd.notes
        # additive-share basis: the leaf ranking is by absolute lead-count deviation
        assert set(dd.layer3_evidence["comparison_basis"]) == {"additive_share"}

    def test_no_new_logo_product_is_asserted(self):
        """Pipeline generated counts inbound leads company-wide; Win rate and Avg
        initial commitment are rep-sold Commercial/Enterprise. The engine ranks
        the three but never multiplies them (the governance edge stays
        NOT_COMPUTABLE for the same reason)."""
        from analytics import data_quality_governance as dqg
        edge = next(e for e in dqg._METRIC_TREE_EDGES_STATIC
                    if e["edge_id"] == "new_logo_equals_pipeline_x_winrate_x_commitment")
        assert edge["status"] == "NOT_COMPUTABLE"


class TestPointInTime:
    def test_flow_for_completed_months_does_not_change_with_a_later_as_of(self):
        early = ma.compute_pipeline_generated_flow(AS_OF_MID)
        late = ma.compute_pipeline_generated_flow(AS_OF_LATEST)
        cutoff = pd.Timestamp("2025-05-01")
        a = early[early["period"] <= cutoff].set_index(["period", "channel"])["pipeline_generated_flow"]
        b = late[late["period"] <= cutoff].set_index(["period", "channel"])["pipeline_generated_flow"]
        pd.testing.assert_series_equal(a.sort_index(), b.sort_index())

    def test_engine_series_never_extends_past_the_evaluation_month(self):
        con = vd._connect()
        try:
            series = vd._pipeline_generated_series(date(2025, 11, 15), con)
        finally:
            con.close()
        month = vd._evaluation_month(date(2025, 11, 15))
        assert month == pd.Timestamp("2025-10-01")
        for s in series.values():
            assert s.index.max() <= month


class TestCrossArtifactConsistency:
    """The cautionary case: an engine node marked NOT_COMPUTABLE while a
    different shipped artifact already computes and validates it."""

    def test_every_node_marketing_attribution_covers_is_computable_in_the_engine(self):
        pipeline = ma.compute_pipeline_generated(AS_OF_MID, period_grain="quarter")
        covered_channels = set(pipeline["channel"].unique())
        assert covered_channels == set(ma.PIPELINE_CHANNEL_TO_TREE_KEY), (
            "marketing_attribution emits a channel its PIPELINE_CHANNEL_TO_TREE_KEY does not map")
        for channel in covered_channels:
            key = ma.PIPELINE_CHANNEL_TO_TREE_KEY[channel]
            assert key in vd._TREE, f"{key} (covered by marketing_attribution) is missing from the tree"
            assert vd.get_node(key).computability != vd.NOT_COMPUTABLE, (
                f"{key} is marked NOT_COMPUTABLE but analytics/marketing_attribution.py "
                "computes and validates it")
        assert vd.stale_markings_against_attribution() == []

    def test_attribution_output_backing_the_claim_reconciles(self):
        panel = ma.build_lead_panel(AS_OF_MID)
        identity = ma.reconcile_pipeline_generated_identity(AS_OF_MID, panel=panel)
        flow = ma.reconcile_pipeline_generated_flow(AS_OF_MID, panel=panel)
        assert identity["reconciles"] and flow["reconciles"]

    def test_guard_fails_if_a_covered_node_is_re_marked_not_computable(self, monkeypatch):
        original = vd._TREE["paid"]
        monkeypatch.setitem(vd._TREE, "paid", dataclasses.replace(
            original, computability=vd.NOT_COMPUTABLE, gap_note="re-marked for the guard test"))
        assert vd.stale_markings_against_attribution() == ["paid"]

    def test_guard_fails_if_a_covered_node_is_missing_from_the_tree(self, monkeypatch):
        monkeypatch.delitem(vd._TREE, "community_events")
        assert "community_events" in vd.stale_markings_against_attribution()

    def test_governance_module_reports_no_stale_marking(self):
        from analytics import proxy_metric_health as pmh
        check = pmh.check_pipeline_generated_staleness()
        assert check["is_stale_marking"] is False
        assert check["stale_nodes"] == []
        assert check["dqg_edge_status"] == "VALIDATED_ELSEWHERE"
        assert "pipeline_generated" not in {r["node_key"] for r in pmh.DATA_GAP_ROOTS}


class TestSemanticRegistryMirror:
    def test_registry_notes_describe_the_current_state(self):
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            metrics = json.load(f)["metrics"]
        for key in ("pipeline_generated", "organic_content", "paid", "community_events"):
            note = metrics[key]["gap_note"]
            assert "marketing_attribution.py" in note and STALE_PHRASE not in note
        for key in ("marketing_sales_handoff_quality", "mql_response_sla",
                    "mql_sal_acceptance_rate", "lead_recycling_nurture_re_qualification_rate"):
            assert metrics[key]["computable"] is False
            assert STALE_PHRASE not in metrics[key]["gap_note"]
        assert metrics["marketing_sales_handoff_quality"]["additive"] is False
        assert metrics["brand_awareness"]["additive"] is False
