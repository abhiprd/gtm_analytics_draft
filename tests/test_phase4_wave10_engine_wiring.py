"""Variance-diagnostic engine wired to the deal-funnel, workflow-chain and
consumption-utilization marts (and the account-health inputs): which nodes are
computable and rankable, which stay blocked and why, an independent recompute of
the series from the fact tables, the end-of-window censoring of the workflow-chain
series, a cross-artifact staleness guard between the marts and the tree, and the
semantic registry's mirror of the same nodes.

Reads data/acme_gtm.duckdb (built by `cd dbt && dbt build`); skipped when the
database is absent.

Run: python3 -m pytest tests/test_phase4_wave10_engine_wiring.py -v
"""
import dataclasses
import json
import os
import sys
from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB_PATH = os.path.join(ROOT, "data", "acme_gtm.duckdb")
REGISTRY_PATH = os.path.join(ROOT, "semantic", "metric_registry.json")

pytestmark = pytest.mark.skipif(
    not os.path.exists(DB_PATH), reason="dbt-built database not present; run `cd dbt && dbt build`")

from analytics import variance_diagnostic as vd  # noqa: E402

AS_OF_LATEST = date(2025, 11, 30)
AS_OF_MID = date(2025, 6, 30)

# node -> (layer, parent, computability)
FLIPPED = {
    "poc_pass_rate": (3, "win_rate", vd.PARTIAL),
    "loss_reason_mix": (3, "win_rate", vd.PARTIAL),
    "rep_capacity_ramp_mix": (3, "win_rate", vd.PARTIAL),
    "discount_rate_vs_list": (3, "avg_initial_commitment", vd.PARTIAL),
    "deal_size_trend_within_band": (3, "avg_initial_commitment", vd.PARTIAL),
    "overage_realization": (2, "expansion_consumption_revenue", vd.PARTIAL),
    "renewal_win_rate": (2, "contraction_churned_revenue", vd.COMPUTABLE),
    "workflow_chain_underutilization": (2, "contraction_churned_revenue", vd.PARTIAL),
    "ingestion_without_completion_rate": (3, "workflow_chain_underutilization", vd.COMPUTABLE),
    "mid_chain_abandonment": (3, "workflow_chain_underutilization", vd.PARTIAL),
    "full_vs_partial_chain_share": (3, "workflow_chain_underutilization", vd.PARTIAL),
    "usage_trend_account_relative": (3, "account_health_score", vd.PARTIAL),
    "support_ticket_volume_severity": (3, "account_health_score", vd.PARTIAL),
    "engagement_login_frequency": (3, "account_health_score", vd.COMPUTABLE),
    "am_sentiment_notes": (3, "account_health_score", vd.PARTIAL),
}

# The complete set of nodes still NOT_COMPUTABLE, so a node cannot flip (or be
# newly blocked) without this list, the docs and the data-gap catalog changing too.
STILL_BLOCKED = {
    "stage_to_stage_conversion", "account_health_score",
    "wallet_share_progression", "workflow_migration_rate", "am_touch_effectiveness",
    "existing_account_community_engagement",
    "marketing_sales_handoff_quality", "mql_response_sla", "mql_to_sal_acceptance_rate",
    "lead_recycling_rate", "brand_awareness", "branded_search_volume_trend",
    "direct_traffic_share", "share_of_voice", "time_to_first_integration",
    "quickstart_docs_engagement_rate", "account_specific_baseline_deviation",
    "cohort_comparison", "time_to_respond_churn_risk_flag", "loud_vs_silent_churn_mix",
    "cost_per_channel_activity", "expansion_revenue_drivers", "churn_reason_category",
}


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(DB_PATH, read_only=True)
    yield c
    c.close()


class TestCoverage:
    def test_computability_counts(self):
        from collections import Counter
        c = Counter(n.computability for n in vd._TREE.values())
        assert (len(vd._TREE), c[vd.COMPUTABLE], c[vd.PARTIAL], c[vd.NOT_COMPUTABLE]) == (71, 31, 17, 23)

    def test_every_blocked_node_is_the_expected_set(self):
        blocked = {k for k, n in vd._TREE.items() if n.computability == vd.NOT_COMPUTABLE}
        assert blocked == STILL_BLOCKED

    @pytest.mark.parametrize("key,spec", sorted(FLIPPED.items()))
    def test_flipped_node_has_its_real_layer_parent_and_status(self, key, spec):
        layer, parent, status = spec
        node = vd.get_node(key)
        assert (node.layer, node.parent_key, node.computability) == (layer, parent, status)
        assert node.gap_note, "a flipped node still states its definition and limits"

    def test_layer3_children_reachable_only_under_a_computable_layer2_parent(self):
        cov = vd._coverage_report().set_index("metric_key")
        assert bool(cov.loc["contraction_churned_revenue", "layer3_computable_reachable"])
        # Account health score's four computed inputs exist but sit under a blocked parent
        health_inputs = [k for k, n in vd._TREE.items() if n.parent_key == "account_health_score"]
        assert all(vd._TREE[k].computability != vd.NOT_COMPUTABLE for k in health_inputs)
        assert vd._TREE["account_health_score"].computability == vd.NOT_COMPUTABLE
        for c in vd.children_of("account_health_score"):
            assert "can never be reached" in c.gap_note

    def test_blocked_nodes_state_specific_reasons(self):
        vague = ("Same gap as the parent node", "closing the gap needs a new reporting table",
                 "Needs opportunity-level detail (stage history, loss reason, list price")
        for key in STILL_BLOCKED:
            note = vd.get_node(key).gap_note
            assert note and len(note) > 30, key
            assert not any(v in note for v in vague), f"{key} keeps a stale or vague reason"

    def test_stage_to_stage_conversion_is_blocked_as_degenerate(self, con):
        note = vd.get_node("stage_to_stage_conversion").gap_note
        assert "100%" in note and "every new-business deal logs every stage" in note
        # the claim, checked against the facts: every closed Commercial/Enterprise
        # new-business deal has a history row for every stage of its path
        bad = con.execute("""
            with o as (select opportunity_id, segment from main_marts.fact_opportunities
                       where opportunity_type = 'new_business' and segment in ('Commercial', 'Enterprise')),
            h as (select opportunity_id, count(distinct stage) n_stages
                  from main_marts.fact_opportunity_stage_history group by 1)
            select count(*) from o join h using (opportunity_id)
            where h.n_stages != case o.segment when 'Enterprise' then 5 else 4 end""").fetchone()[0]
        assert bad == 0

    def test_account_health_composite_has_no_monthly_history(self):
        note = vd.get_node("account_health_score").gap_note
        assert "single as-of date" in note and "monthly history" in note

    def test_wallet_share_and_dependents_are_blocked_on_the_denominator(self):
        for key in ("wallet_share_progression", "workflow_migration_rate",
                    "am_touch_effectiveness", "existing_account_community_engagement"):
            assert vd.get_node(key).computability == vd.NOT_COMPUTABLE
        assert "denominator" in vd.get_node("wallet_share_progression").gap_note
        assert "wallet_share_progression" in {k.key for k in vd.children_of("expansion_consumption_revenue")}


class TestSeriesAreComputedAndRankable:
    @pytest.mark.parametrize("parent", [
        "win_rate", "avg_initial_commitment", "expansion_consumption_revenue",
        "contraction_churned_revenue", "workflow_chain_underutilization", "account_health_score"])
    def test_every_flipped_child_of_the_parent_has_a_series_and_is_rankable(self, parent, con):
        series = vd._build_child_series(parent, AS_OF_MID, con)
        expected = {k for k, (_, p, _) in FLIPPED.items() if p == parent}
        assert expected <= set(series), f"missing series: {expected - set(series)}"
        evaluation_month = vd._evaluation_month(AS_OF_MID)
        ranked = vd._with_signal(parent, vd.rank_siblings(parent, series, evaluation_month))
        for key in expected:
            row = ranked[ranked["metric_key"] == key]
            assert len(row) == 1, f"{key} did not rank under {parent}"
            assert np.isfinite(row.iloc[0]["deviation_pct"]) and row.iloc[0]["baseline_n"] >= 3
            assert int(row.iloc[0]["layer"]) == vd.get_node(key).layer

    def test_blocked_children_have_no_series(self, con):
        assert "stage_to_stage_conversion" not in vd._build_child_series("win_rate", AS_OF_MID, con)
        assert vd._build_child_series("renewal_win_rate", AS_OF_MID, con) == {}

    def test_layer2_and_layer3_series_are_distinct_and_separately_rankable(self, con):
        l2 = vd._build_child_series("contraction_churned_revenue", AS_OF_MID, con)
        l3 = vd._build_child_series("workflow_chain_underutilization", AS_OF_MID, con)
        parent = l2["workflow_chain_underutilization"].dropna()
        for key, child in l3.items():
            child = child.dropna()
            common = parent.index.intersection(child.index)
            assert len(common) > 24
            assert not np.allclose(parent.loc[common], child.loc[common]), (
                f"{key} equals its Layer-2 parent -- the two could not be ranked as separate evidence")
        # win rate (Layer 2, growth bridge) and its Layer-3 leaves are different series too
        top = vd._build_child_series("new_logo_consumption_revenue", AS_OF_MID, con)
        leaves = vd._build_child_series("win_rate", AS_OF_MID, con)
        assert "win_rate" in top and not set(top) & set(leaves)

    def test_win_rate_layer2_ties_to_the_deal_funnel_mart(self, con):
        top = vd._build_child_series("new_logo_consumption_revenue", AS_OF_LATEST, con)["win_rate"]
        f = con.execute("""select month, sum(new_business_won_count) w, sum(new_business_lost_count) l
                           from main_marts.mart_deal_funnel where month <= '2025-11-30' group by 1""").df()
        f["month"] = pd.to_datetime(f["month"])
        f = f.set_index("month")
        direct = (f["w"] / (f["w"] + f["l"]).replace(0, np.nan)).dropna()
        # blank before the first month with a logged lost deal: earlier months are wins only
        # and read a fake 100%
        first_loss = f.index[f["l"] > 0].min()
        assert first_loss == pd.Timestamp("2023-01-01")
        assert (direct[direct.index < first_loss] == 1.0).all()
        direct = direct[direct.index >= first_loss]
        common = top.dropna().index.intersection(direct.index)
        assert len(common) == len(direct) == len(top.dropna())
        assert np.allclose(top.loc[common], direct.loc[common], atol=1e-12)


class TestSeriesMatchTheFactTables:
    """Each Layer-2/3 series recomputed straight from the fact tables, not from the
    marts the engine reads."""

    def _opps(self, con):
        o = con.execute("""select opportunity_type, segment, is_won, loss_reason, poc_outcome, amount, list_price,
                                  date_trunc('month', close_date) m
                           from main_marts.fact_opportunities
                           where segment in ('Commercial', 'Enterprise') and close_date <= date '2025-11-30'""").df()
        o["m"] = pd.to_datetime(o["m"])
        return o

    def test_loss_reason_mix_poc_pass_rate_discount_and_renewal_win_rate(self, con):
        o = self._opps(con)
        nb = o[o["opportunity_type"] == "new_business"]
        lost = nb[~nb["is_won"]]
        loss = (lost.groupby("m")["loss_reason"].apply(lambda s: (s == "competitive").mean()))
        l3 = vd._build_child_series("win_rate", AS_OF_LATEST, con)
        assert np.allclose(l3["loss_reason_mix"], loss.loc[l3["loss_reason_mix"].index], atol=1e-12)

        ent = nb[(nb["segment"] == "Enterprise") & nb["poc_outcome"].notna()]
        n = ent.groupby("m").size()
        poc = (ent["poc_outcome"] == "pass").groupby(ent["m"]).mean()[n >= vd._MIN_POC_OUTCOMES_PER_MONTH]
        assert set(l3["poc_pass_rate"].index) == set(poc.index)
        assert np.allclose(l3["poc_pass_rate"], poc.loc[l3["poc_pass_rate"].index], atol=1e-12)

        won = nb[nb["is_won"]]
        g = won.groupby("m")[["amount", "list_price"]].sum()
        disc = 1 - g["amount"] / g["list_price"]
        l3b = vd._build_child_series("avg_initial_commitment", AS_OF_LATEST, con)
        assert np.allclose(l3b["discount_rate_vs_list"], disc.loc[l3b["discount_rate_vs_list"].index], atol=1e-9)

        ren = o[o["opportunity_type"] == "renewal"]
        rwr = ren.groupby("m")["is_won"].mean()
        l2 = vd._build_child_series("contraction_churned_revenue", AS_OF_LATEST, con)["renewal_win_rate"]
        assert np.allclose(l2, rwr.loc[l2.index], atol=1e-12)

    def test_overage_share_of_mrr_ties_to_the_revenue_and_commitment_facts(self, con):
        df = con.execute("""
            select date_trunc('month', c.month) m,
                   sum(r.mrr * greatest(c.utilized_actions_monthly - c.committed_actions_monthly, 0)
                       / greatest(c.committed_actions_monthly, c.utilized_actions_monthly))
                       filter (where c.committed_actions_monthly > 0) as ovg,
                   sum(r.mrr) total
            from main_marts.fact_committed_vs_utilized_monthly c
            join main_marts.fact_revenue_monthly r on r.account_id = c.account_id and r.month = c.month
            where c.segment in ('Commercial', 'Enterprise') and c.month <= date '2025-11-30'
            group by 1""").df()
        df["m"] = pd.to_datetime(df["m"])
        direct = (df.set_index("m")["ovg"] / df.set_index("m")["total"]).dropna()
        s = vd._build_child_series("expansion_consumption_revenue", AS_OF_LATEST, con)["overage_realization"]
        common = s.index.intersection(direct.index)
        assert len(common) >= 60
        assert np.allclose(s.loc[common], direct.loc[common], atol=1e-9)

    def test_overage_realization_rate_is_constant_so_the_series_is_dollars(self, con):
        # billed MRR per Action billed (the larger of committed and utilized) is one
        # constant price per account, so every overage Action is billed
        n_off = con.execute("""
            with p as (
                select c.account_id,
                       r.mrr / greatest(c.committed_actions_monthly, c.utilized_actions_monthly) price
                from main_marts.fact_committed_vs_utilized_monthly c
                join main_marts.fact_revenue_monthly r on r.account_id = c.account_id and r.month = c.month
                where c.committed_actions_monthly > 0 and c.segment in ('Commercial', 'Enterprise'))
            select count(*) from (select account_id from p group by 1
                                  having max(price) - min(price) > 1e-6 * max(price))""").fetchone()[0]
        assert n_off == 0, "billed MRR per Action is not constant per account: realization is no longer 100% by construction"
        assert "100% on every account-month" in vd.get_node("overage_realization").gap_note

    def test_workflow_chain_series_match_the_chain_facts(self, con):
        w = con.execute("""
            select date_trunc('month', month) m, count(*) n,
                   sum((full_chain_completion_rate < 0.70)::int) as n_partial,
                   sum(upstream_actions) up, sum(downstream_actions) down
            from main_marts.fact_workflow_chain_events where month <= date '2025-06-30' group by 1""").df()
        w["m"] = pd.to_datetime(w["m"])
        w = w.set_index("m")
        l2 = vd._build_child_series("contraction_churned_revenue", AS_OF_MID, con)["workflow_chain_underutilization"]
        l3 = vd._build_child_series("workflow_chain_underutilization", AS_OF_MID, con)
        assert np.allclose(l2, (w["n_partial"] / w["n"]).loc[l2.index], atol=1e-12)
        assert np.allclose(l3["ingestion_without_completion_rate"],
                           (1 - w["down"] / w["up"]).loc[l3["ingestion_without_completion_rate"].index], atol=1e-12)
        assert np.allclose(l3["full_vs_partial_chain_share"], 1 - l2.loc[l3["full_vs_partial_chain_share"].index], atol=1e-12)
        assert (l3["mid_chain_abandonment"] <= l2.loc[l3["mid_chain_abandonment"].index] + 1e-12).all()


class TestWorkflowChainCensoring:
    def test_partial_chains_exist_only_in_the_months_before_a_churn(self, con):
        from generators import config
        max_lead = con.execute("""
            select max(date_diff('month', a.month, a.churn_month))
            from main_marts.fact_workflow_chain_events w
            join main_marts.mart_account_health a using (account_id, month)
            where w.full_chain_completion_rate < 0.70""").fetchone()[0]
        n_never_churned = con.execute("""
            select count(*) from main_marts.fact_workflow_chain_events w
            join main_marts.mart_account_health a using (account_id, month)
            where w.full_chain_completion_rate < 0.70 and not a.is_eventually_churned""").fetchone()[0]
        assert max_lead == config.DECLINE_MONTHS_BEFORE_CHURN == vd._WORKFLOW_CHAIN_DECLINE_MONTHS
        # the churn-truncation month adds one more blanked month
        assert vd._WORKFLOW_CHAIN_PRECHURN_MONTHS == config.DECLINE_MONTHS_BEFORE_CHURN + 1
        assert n_never_churned == 0

    def test_the_last_months_of_the_window_are_blank_and_earlier_months_are_not(self, con):
        last = pd.Timestamp(con.execute(
            "select max(month) from main_marts.mart_workflow_chain_health").fetchone()[0])
        full = vd._build_child_series("contraction_churned_revenue", date(2025, 12, 31), con)
        s = full["workflow_chain_underutilization"]
        assert s.index.max() == last - pd.DateOffset(months=vd._WORKFLOW_CHAIN_PRECHURN_MONTHS)
        for key, leaf in vd._build_child_series("workflow_chain_underutilization", date(2025, 12, 31), con).items():
            assert leaf.index.max() == s.index.max(), key
        # an as_of_date before the tail is unaffected
        mid = vd._build_child_series("contraction_churned_revenue", AS_OF_MID, con)["workflow_chain_underutilization"]
        assert mid.index.max() == vd._evaluation_month(AS_OF_MID)

    def test_the_cut_is_where_the_partial_share_stops_falling_for_want_of_churners(self, con):
        # churn events in the final month are truncated (about 5% of a normal month), so
        # the partial share is clean only up to final month - (DECLINE + 1)
        churn = con.execute(
            "select churn_month, count(distinct account_id) n from main_marts.mart_account_health "
            "where churn_month is not null group by 1 order by 1").df()
        churn["churn_month"] = pd.to_datetime(churn["churn_month"])
        normal = churn[(churn["churn_month"] >= "2025-01-01") & (churn["churn_month"] < "2025-12-01")]["n"].median()
        final = churn[churn["churn_month"] == churn["churn_month"].max()]["n"].iloc[0]
        assert final < 0.1 * normal
        share = con.execute(
            "select month, sum(partial_chain_account_count)/sum(accounts_with_chain) sh "
            "from main_marts.mart_workflow_chain_health group by 1 order by 1").df()
        share["month"] = pd.to_datetime(share["month"])
        s = share.set_index("month")["sh"]
        last = s.index.max()
        cut = last - pd.DateOffset(months=vd._WORKFLOW_CHAIN_PRECHURN_MONTHS)
        trailing_clean = s[(s.index <= cut) & (s.index > cut - pd.DateOffset(months=6))]
        first_blank = s[cut + pd.DateOffset(months=1)]
        assert first_blank < 0.9 * trailing_clean.min()   # the first blanked month is already deflated
        assert s[cut] > 0.9 * trailing_clean.min()        # the last kept month is not

    def test_the_final_evaluation_month_does_not_rank_the_censored_series(self):
        result = vd.run_diagnostic(AS_OF_LATEST, include_watchlist=False)
        dd = {d.layer1_key: d for d in result["drilldowns"]}
        assert "contraction_churned_revenue" in dd
        cov = dd["contraction_churned_revenue"].sibling_coverage
        missing = {m["metric_key"] for m in cov["missing_siblings"]}
        assert "workflow_chain_underutilization" in missing
        assert dd["contraction_churned_revenue"].layer2_key != "workflow_chain_underutilization"


class TestDrilldownDepth:
    def test_expansion_branch_is_a_single_candidate_read_to_a_depth_two_leaf(self):
        result = vd.run_diagnostic(AS_OF_LATEST, include_watchlist=False)
        dd = {d.layer1_key: d for d in result["drilldowns"]}["expansion_consumption_revenue"]
        assert dd.layer2_key == "overage_realization"
        assert dd.sibling_coverage["is_genuine_sibling_comparison"] is False
        assert dd.layer3_status == vd.L3_BRANCH_DEPTH_2 and dd.layer3_keys == []
        assert {m["metric_key"] for m in dd.sibling_coverage["missing_siblings"]} == {"wallet_share_progression"}

    def test_every_emitted_layer_label_is_read_off_the_tree(self):
        for as_of in (AS_OF_MID, AS_OF_LATEST):
            for d in vd.run_diagnostic(as_of, include_watchlist=False)["drilldowns"]:
                emitted = d.to_dict()
                assert emitted["layer1"]["layer"] == 1
                if emitted["layer2_outlier"]:
                    assert emitted["layer2_outlier"]["layer"] == 2
                for leaf in emitted["layer3_evidence"]:
                    assert leaf["layer"] == 3 and leaf["parent_key"] == d.layer2_key
                for rec in d.layer3_evidence.to_dict(orient="records") if len(d.layer3_evidence) else []:
                    assert rec["layer"] == 3

    def test_win_rate_branch_surfaces_real_layer3_evidence(self):
        d = {x.layer1_key: x for x in vd.run_diagnostic(AS_OF_MID, include_watchlist=False)["drilldowns"]}
        nl = d["new_logo_consumption_revenue"]
        assert nl.layer2_key == "win_rate" and nl.layer3_status == vd.L3_SURFACED
        assert set(nl.layer3_keys) <= {"poc_pass_rate", "loss_reason_mix", "rep_capacity_ramp_mix"}

    def test_synthetic_scenarios_all_pass_including_the_new_branches(self):
        results = {r["name"]: r for r in vd.run_synthetic_scenarios()}
        assert len(results) == 7 and all(r["passed"] for r in results.values()), [
            (n, r["failures"]) for n, r in results.items() if not r["passed"]]
        assert "contraction_workflow_chain_branch_with_layer3" in results
        assert "expansion_overage_single_candidate_depth_2_leaf" in results


class TestStalenessGuardAgainstTheMarts:
    """The cross-artifact case: a node a new mart column already feeds must not be
    marked NOT_COMPUTABLE, and no mart column may sit unaccounted for."""

    def test_no_mapped_node_is_blocked(self):
        assert vd.stale_markings_against_wave10_marts() == []

    def test_every_mapped_node_exists_and_is_computable_or_partial(self):
        for mart, cols in vd.WAVE10_MART_NODE_MAP.items():
            for col, nodes in cols.items():
                for key in nodes:
                    assert key in vd._TREE, f"{mart}.{col} maps to unknown node {key}"
                    assert vd.get_node(key).computability in (vd.COMPUTABLE, vd.PARTIAL)

    @pytest.mark.parametrize("key", sorted({n for m in vd.WAVE10_MART_NODE_MAP.values()
                                            for ns in m.values() for n in ns}))
    def test_guard_fails_if_a_fed_node_is_re_marked_not_computable(self, key, monkeypatch):
        monkeypatch.setitem(vd._TREE, key, dataclasses.replace(
            vd._TREE[key], computability=vd.NOT_COMPUTABLE, gap_note="re-marked for the guard test"))
        assert key in vd.stale_markings_against_wave10_marts()

    def test_guard_fails_if_a_fed_node_is_missing_from_the_tree(self, monkeypatch):
        monkeypatch.delitem(vd._TREE, "poc_pass_rate")
        assert "poc_pass_rate" in vd.stale_markings_against_wave10_marts()

    @pytest.mark.parametrize("mart", sorted(vd.WAVE10_MART_NODE_MAP))
    def test_every_mart_column_is_mapped_or_has_a_stated_reason(self, mart, con):
        cols = {r[0] for r in con.execute(f"describe main_marts.{mart}").fetchall()} - {"segment", "month"}
        mapped = set(vd.WAVE10_MART_NODE_MAP[mart])
        unused = set(vd.WAVE10_MART_UNUSED_COLUMNS[mart])
        assert not mapped & unused
        assert mapped | unused == cols, (
            f"{mart}: unaccounted {sorted(cols - mapped - unused)}, listed but absent "
            f"{sorted((mapped | unused) - cols)}")
        assert all(len(r) > 20 for r in vd.WAVE10_MART_UNUSED_COLUMNS[mart].values())

    def test_build_time_validation_reports_the_guard(self):
        out = vd.run_build_time_validation(AS_OF_LATEST, log=False)
        assert out["stale_markings_wave10_marts"] == []


class TestRegistryMirror:
    @pytest.fixture(scope="class")
    def registry(self):
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            return json.load(f)

    # registry key -> engine key where they differ
    MAPPED = {
        "poc_pass_rate": "poc_pass_rate", "rep_capacity_ramp_mix": "rep_capacity_ramp_mix",
        "loss_reason_mix": "loss_reason_mix", "discount_rate_vs_list": "discount_rate_vs_list",
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

    def test_registry_is_version_five_and_queryable_counts(self, registry):
        assert registry["registry_version"] >= 5
        assert sum(m["computable"] for m in registry["metrics"].values()) == 37

    @pytest.mark.parametrize("reg_key,eng_key", sorted(MAPPED.items()))
    def test_mapped_nodes_agree_with_the_engine(self, registry, reg_key, eng_key):
        m = registry["metrics"][reg_key]
        node = vd.get_node(eng_key)
        assert m["computable"] is True and m["source_mart"]
        assert m["layer"] == node.layer
        engine_status = {vd.COMPUTABLE: "full", vd.PARTIAL: "partial"}[node.computability]
        assert m["computability"] == engine_status
        assert m["queryable_dimensions"] == ["segment"]
        assert m["queryable_segments"] and set(m["queryable_segments"]) <= {"SMB", "Commercial", "Enterprise"}

    def test_segment_coverage_matches_each_marts_rows(self, registry, con):
        for key in self.MAPPED:
            m = registry["metrics"][key]
            have = {r[0] for r in con.execute(
                f"select distinct segment from main_marts.{m['source_mart']}").fetchall()}
            assert set(m["queryable_segments"]) <= have
        assert registry["metrics"]["poc_pass_rate"]["queryable_segments"] == ["Enterprise"]
        assert set(registry["metrics"]["overage_realization"]["queryable_segments"]) == {"Commercial", "Enterprise"}

    def test_blocked_registry_nodes_state_their_specific_reasons(self, registry):
        m = registry["metrics"]
        for key in ("stage_to_stage_conversion", "usage_trend", "account_health_score",
                    "loud_explicit_cancellation_vs_silent_non_renewal_mix", "churn_reason_category",
                    "wallet_share_progression"):
            assert m[key]["computable"] is False and m[key]["queryable_segments"] == []
            assert "fact_opportunities / fact_opportunity_stage_history -- fact_* tables outside" not in m[key]["gap_note"]
        assert "100%" in m["stage_to_stage_conversion"]["gap_note"]

    def test_non_additive_nodes_stay_non_additive(self, registry):
        for key in ("brand_awareness", "marketing_sales_handoff_quality", "ltv_by_segment_acquisition_channel"):
            assert registry["metrics"][key]["additive"] is False
        assert all(registry["metrics"][k]["additive"] for k in self.MAPPED)


class TestRipple:
    def test_data_gap_catalog_is_exactly_the_live_blocked_roots(self):
        from analytics import proxy_metric_health as pmh
        assert pmh.verify_data_gap_keys_are_live()["passed"]
        assert pmh.find_uncatalogued_gap_roots() == []
        closed = {"discount_rate_vs_list", "deal_size_trend_within_band", "loss_reason_mix", "poc_pass_rate",
                  "renewal_win_rate", "overage_realization", "workflow_chain_underutilization",
                  "rep_capacity_ramp_mix"}
        assert not closed & {r["node_key"] for r in pmh.DATA_GAP_ROOTS}
        assert len(pmh.DATA_GAP_ROOTS) == 14

    def test_freshness_contract_checks_the_new_marts(self):
        with open(os.path.join(ROOT, "pipeline", "freshness_contract.json"), encoding="utf-8") as f:
            contract = json.load(f)
        marts = next(a for a in contract["artifacts"] if a["name"] == "dbt_marts")
        tables = {e.get("table") for e in marts["evidence"]}
        assert {"main_marts.mart_deal_funnel", "main_marts.mart_workflow_chain_health",
                "main_marts.mart_consumption_utilization"} <= tables
        engine = next(a for a in contract["artifacts"] if a["name"] == "variance_diagnostic")
        assert "dbt_marts" in engine["depends_on"]


class TestGapNoteVoice:
    """Gap notes travel into the weekly readout and the dashboard verbatim, so every
    tree note obeys the readout's voice rules (no code identifiers, no hedges)."""

    def test_every_tree_gap_note_obeys_the_readout_voice_rules(self):
        import re
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        import test_readout_text_and_counts as voice
        problems = []
        for key, node in vd._TREE.items():
            text = node.gap_note
            if not text:
                continue
            for m in re.finditer(r"\b[A-Z]{4,}\b", text):
                if m.group(0) not in voice._ALLOWED_CAPS:
                    problems.append((key, "caps", m.group(0)))
            for rx, kind in ((voice._HEDGES, "hedge"), (voice._IMPERATIVE, "imperative"),
                             (voice._CODE, "code")):
                m = rx.search(text)
                if m:
                    problems.append((key, kind, m.group(0)))
        assert not problems, problems
