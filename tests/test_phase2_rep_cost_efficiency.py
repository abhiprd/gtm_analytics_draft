"""Checks on the dbt-built cost side of the Efficiency pillar: Magic Number and
AM Efficiency are computed values, not structural NULLs, and the variance
engine and semantic registry treat them as computable.

Reads data/acme_gtm.duckdb (built by `cd dbt && dbt build`); skipped when the
database or the cost columns are absent. The plausibility band below is a wide
sanity bound on the annual blended ratio, not a tuned target: the values the
model produces are reported as they fall, and the level-comparability caveat on
the variance engine's magic_number / am_efficiency nodes says how to read them.

Run: python3 -m pytest tests/test_phase2_rep_cost_efficiency.py -v
"""
import json
import os
from datetime import date

import duckdb
import pandas as pd
import pytest

DB_PATH = "data/acme_gtm.duckdb"
REGISTRY_PATH = "semantic/metric_registry.json"


@pytest.fixture(scope="module")
def con():
    if not os.path.exists(DB_PATH):
        pytest.skip("dbt-built database not present; run `cd dbt && dbt build`")
    c = duckdb.connect(DB_PATH, read_only=True)
    cols = {r[0] for r in c.execute(
        "select column_name from information_schema.columns where table_name = 'mart_efficiency'").fetchall()}
    if "sm_cost" not in cols:
        pytest.skip("mart_efficiency has no cost columns; rebuild the dbt project")
    yield c
    c.close()


@pytest.fixture(scope="module")
def eff(con):
    df = con.execute("select * from main_marts.mart_efficiency").df()
    df["month"] = pd.to_datetime(df["month"])
    return df


class TestMartEfficiencyCostSide:
    def test_magic_number_defined_for_commercial_and_enterprise_from_2023_02(self, eff):
        d = eff[eff["segment"].isin(["Commercial", "Enterprise"]) & (eff["month"] >= "2023-02-01")]
        assert len(d) > 0
        assert d["magic_number"].notna().all()
        assert (d["magic_number_sm_cost"] > 0).all()

    def test_magic_number_denominator_is_prior_month_sm_cost(self, eff):
        prior = eff.assign(month=eff["month"] + pd.DateOffset(months=1))[["segment", "month", "sm_cost"]]
        m = eff.merge(prior, on=["segment", "month"], how="left", suffixes=("", "_prior"))
        m = m[m["magic_number_sm_cost"].notna()]
        assert ((m["magic_number_sm_cost"] - m["sm_cost_prior"]).abs() < 1e-6).all()

    def test_sm_cost_is_rep_cost_plus_marketing_spend(self, eff):
        d = eff[eff["sm_cost"].notna()]
        assert ((d["sm_cost"] - d["rep_fully_loaded_cost"] - d["marketing_spend_allocated"].fillna(0)).abs() < 1e-6).all()

    def test_am_efficiency_defined_wherever_an_am_exists(self, eff):
        d = eff[(eff["am_cost"] > 0) & (eff["month"] >= "2023-01-01")]
        assert len(d) > 0 and d["am_efficiency"].notna().all()
        assert ((d["am_efficiency"] - d["am_expansion_arr"] / 12.0 / d["am_cost"]).abs() < 1e-9).all()

    def test_smb_has_no_rep_or_am_cost(self, eff):
        smb = eff[eff["segment"] == "SMB"]
        assert (smb["rep_fully_loaded_cost"] == 0).all() and (smb["am_cost"] == 0).all()
        assert smb["am_efficiency"].isna().all()

    def test_ramping_reps_add_cost_before_production(self, con):
        ramp_share = con.execute(
            "select sum(monthly_ramping_cost_usd) / sum(monthly_fully_loaded_cost_usd) "
            "from main_marts.fact_rep_monthly_cost where month >= '2023-01-01'").fetchone()[0]
        assert 0.0 < ramp_share < 0.5

    def test_annual_blended_ratios_inside_a_wide_plausibility_band(self, eff):
        d = eff[eff["segment"].isin(["Commercial", "Enterprise"]) & (eff["month"] >= "2023-02-01")]
        d = d.assign(year=d["month"].dt.year)
        g = d.groupby("year").agg(nn=("net_new_arr", "sum"), sm=("magic_number_sm_cost", "sum"),
                                  ex=("am_expansion_arr", "sum"), am=("am_cost", "sum"))
        magic = g["nn"] / g["sm"]
        am_eff = (g["ex"] / 12.0) / g["am"]
        assert magic.between(0.2, 5.0).all(), magic.to_dict()
        assert am_eff.between(0.2, 5.0).all(), am_eff.to_dict()


class TestVarianceEngineTreatsCostMetricsAsComputable:
    def test_layer1_cost_nodes_are_computable_and_caveated(self):
        from analytics import variance_diagnostic as vd
        for key in ("magic_number", "am_efficiency"):
            node = vd.get_node(key)
            assert node.computability == vd.COMPUTABLE
            assert node.plan_comparability == vd.CAVEATED
            assert node.plan_comparability_note

    def test_s_and_m_cost_branch_computability(self):
        from analytics import variance_diagnostic as vd
        assert vd.get_node("sm_cost").computability == vd.COMPUTABLE
        assert vd.get_node("rep_fully_loaded_cost").computability == vd.COMPUTABLE
        assert vd.get_node("am_cost_by_segment").computability == vd.COMPUTABLE
        assert vd.get_node("marketing_spend_allocation_by_channel").computability == vd.PARTIAL
        assert vd.get_node("cost_per_channel_activity").computability == vd.NOT_COMPUTABLE
        assert vd.get_node("expansion_revenue_drivers").computability == vd.NOT_COMPUTABLE

    def test_scorecard_has_a_real_actual_and_variance_for_both(self, con):
        from analytics import variance_diagnostic as vd
        sc = vd.compute_layer1_scorecard(date(2025, 11, 30))
        for key in ("magic_number", "am_efficiency"):
            row = sc[sc["metric_key"] == key].iloc[0]
            assert row["mechanism"] == "plan_diff"
            assert pd.notna(row["actual"]) and pd.notna(row["plan"]) and pd.notna(row["variance_pct"])

    def test_plan_and_actual_share_a_basis_at_2024_01_onward(self):
        """No plan-against-a-void: for every month from the first full
        trailing window, both the plan and the actual exist."""
        from analytics import variance_diagnostic as vd
        actuals = vd.blend_layer1_actuals(date(2025, 11, 30))
        plan = vd.load_plan(date(2025, 11, 30)).pivot(index="month", columns="layer1_metric", values="plan_value")
        window = actuals.loc["2024-01-01":"2025-11-01"]
        for key in ("magic_number", "am_efficiency"):
            assert window[key].notna().all()
            assert plan.loc[window.index, key].notna().all()

    def test_synthetic_scenarios_still_pass(self):
        from analytics import variance_diagnostic as vd
        assert all(s["passed"] for s in vd.run_synthetic_scenarios())


class TestSemanticRegistry:
    def test_cost_metrics_are_registered_computable(self):
        with open(REGISTRY_PATH) as f:
            metrics = json.load(f)["metrics"]
        for key in ("magic_number", "am_efficiency"):
            assert metrics[key]["computable"] is True
            assert metrics[key]["query"]["aggregation"] == "ratio"
        for key in ("s_m_cost", "rep_fully_loaded_cost_incl_ramp", "am_cost_by_segment"):
            assert metrics[key]["computable"] is True
        assert metrics["cost_per_channel_activity"]["computable"] is False
