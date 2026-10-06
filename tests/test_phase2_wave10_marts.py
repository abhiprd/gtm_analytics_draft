"""Checks on the three dbt marts that expose already-present fact data:
mart_deal_funnel, mart_workflow_chain_health, mart_consumption_utilization.

Each mart is recomputed here independently from the fact tables in pandas
(never by re-running the mart's SQL) and compared column by column; the dbt
vars the marts read are checked against the Python modules they must equal;
and a determinism test rebuilds the three marts twice into a throwaway copy of
the database and compares them row for row, in physical order.

Reads data/acme_gtm.duckdb (built by `cd dbt && dbt build`); skipped when the
database or the marts are absent.

Run: python3 -m pytest tests/test_phase2_wave10_marts.py -v
"""
import hashlib
import os
import shutil
import subprocess
import sys

import duckdb
import numpy as np
import pandas as pd
import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB_PATH = os.path.join(ROOT, "data", "acme_gtm.duckdb")
DBT_DIR = os.path.join(ROOT, "dbt")
MARTS = ["mart_deal_funnel", "mart_workflow_chain_health", "mart_consumption_utilization"]
EXPECTED_SEGMENTS = {
    "mart_deal_funnel": {"Commercial", "Enterprise"},
    "mart_workflow_chain_health": {"SMB", "Commercial", "Enterprise"},
    "mart_consumption_utilization": {"Commercial", "Enterprise"},
}


def _project_vars():
    with open(os.path.join(DBT_DIR, "dbt_project.yml")) as fh:
        return yaml.safe_load(fh)["vars"]


@pytest.fixture(scope="module")
def con():
    if not os.path.exists(DB_PATH):
        pytest.skip("dbt-built database not present; run `cd dbt && dbt build`")
    c = duckdb.connect(DB_PATH, read_only=True)
    have = {r[0] for r in c.execute("select table_name from information_schema.tables").fetchall()}
    if not set(MARTS) <= have:
        pytest.skip("wave-10 marts not built; run `cd dbt && dbt build`")
    yield c
    c.close()


def _mart(con, name):
    df = con.execute(f"select * from main_marts.{name}").df()
    df["month"] = pd.to_datetime(df["month"])
    return df


def _close(a, b, tol=1e-6):
    a = pd.Series(a, dtype="float64").reset_index(drop=True)
    b = pd.Series(b, dtype="float64").reset_index(drop=True)
    both_nan = a.isna() & b.isna()
    ok = both_nan | ((a - b).abs() <= tol * np.maximum(1.0, b.abs()))
    return bool(ok.all())


# ---------------------------------------------------------------- dbt vars

class TestDbtVarsMatchPython:
    def test_acv_bands_equal_generator_config(self):
        from generators import config
        bands = _project_vars()["acv_bands"]
        assert set(bands) == set(config.ACV_RANGES)
        for seg, (lo, hi) in config.ACV_RANGES.items():
            assert (bands[seg]["floor"], bands[seg]["cap"]) == (lo, hi), seg

    def test_rep_ramp_window_equals_rep_productivity(self):
        from analytics import rep_productivity
        assert _project_vars()["rep_ramp_window_days"] == rep_productivity._RAMP_FULL_DAYS

    def test_workflow_threshold_equals_playbook_rule(self):
        from analytics import playbook_triggers
        rule = playbook_triggers.RULES["ingestion_without_completion"]
        assert _project_vars()["workflow_chain_completion_threshold"] == rule["completion_rate_threshold"]


# ------------------------------------------------------------------- grain

class TestGrainAndOrder:
    @pytest.mark.parametrize("name", MARTS)
    def test_grain_unique_and_segments(self, con, name):
        df = _mart(con, name)
        assert len(df) > 0
        assert not df.duplicated(["segment", "month"]).any()
        assert set(df["segment"]) == EXPECTED_SEGMENTS[name]
        assert df["month"].dt.day.eq(1).all()

    @pytest.mark.parametrize("name", MARTS)
    def test_physical_row_order_is_the_grain_order(self, con, name):
        df = con.execute(f"select segment, month from main_marts.{name}").df()
        assert df.equals(df.sort_values(["segment", "month"]).reset_index(drop=True))

    def test_deal_funnel_is_a_dense_monthly_spine(self, con):
        df = _mart(con, "mart_deal_funnel")
        for seg, g in df.groupby("segment"):
            expect = pd.date_range(g["month"].min(), g["month"].max(), freq="MS")
            assert list(g["month"]) == list(expect), seg
        assert df["month"].max() == pd.Timestamp("2025-12-01")


# --------------------------------------------------------- mart_deal_funnel

@pytest.fixture(scope="module")
def opps(con):
    o = con.execute("select * from main_marts.fact_opportunities").df()
    o["close_date"] = pd.to_datetime(o["close_date"])
    o["created_date"] = pd.to_datetime(o["created_date"])
    o["month"] = o["close_date"].dt.to_period("M").dt.to_timestamp()
    return o


class TestDealFunnel:
    def test_counts_and_loss_reasons_match_facts(self, con, opps):
        mart = _mart(con, "mart_deal_funnel").set_index(["segment", "month"])
        nb = opps[(opps.opportunity_type == "new_business") & opps.segment.isin(["Commercial", "Enterprise"])]
        exp = pd.DataFrame({
            "new_business_won_count": nb[nb.is_won].groupby(["segment", "month"]).size(),
            "new_business_lost_count": nb[~nb.is_won].groupby(["segment", "month"]).size(),
        })
        for reason in ["competitive", "no_decision", "price", "other"]:
            exp[f"lost_{reason}_count"] = nb[~nb.is_won & (nb.loss_reason == reason)].groupby(["segment", "month"]).size()
        exp = exp.reindex(mart.index).fillna(0)
        for c in exp.columns:
            assert (mart[c].astype(float) == exp[c]).all(), c
        lost = ["lost_competitive_count", "lost_no_decision_count", "lost_price_count", "lost_other_count"]
        assert (mart[lost].sum(axis=1) == mart["new_business_lost_count"]).all()

    def test_totals_equal_fact_totals(self, con, opps):
        mart = _mart(con, "mart_deal_funnel")
        nb = opps[(opps.opportunity_type == "new_business") & opps.segment.isin(["Commercial", "Enterprise"])]
        assert mart.new_business_won_count.sum() == nb.is_won.sum()
        assert mart.new_business_lost_count.sum() == (~nb.is_won).sum()
        assert mart.lost_competitive_count.sum() + mart.lost_no_decision_count.sum() \
            + mart.lost_price_count.sum() + mart.lost_other_count.sum() == (~nb.is_won).sum()
        # Every lost reason is one of the four accepted values (nothing falls out of the sum).
        assert nb[~nb.is_won].loss_reason.isin(["competitive", "no_decision", "price", "other"]).all()

    def test_reconciles_to_growth_bridge(self, con):
        f = _mart(con, "mart_deal_funnel")
        g = _mart(con, "mart_growth_bridge")
        g = g[g.segment.isin(["Commercial", "Enterprise"])]
        m = g.merge(f, on=["segment", "month"], how="left", suffixes=("_g", "_f"))
        active = m[(m.new_business_won_count_g.fillna(0) + m.new_business_lost_count_g.fillna(0)) > 0]
        assert active.new_business_won_count_f.notna().all()
        assert (active.new_business_won_count_g == active.new_business_won_count_f).all()
        assert (active.new_business_lost_count_g == active.new_business_lost_count_f).all()
        assert f.new_business_won_count.sum() == g.new_business_won_count.sum()
        assert f.new_business_lost_count.sum() == g.new_business_lost_count.sum()

    def test_amounts_discount_and_band_shares(self, con, opps):
        from generators import config
        mart = _mart(con, "mart_deal_funnel").set_index(["segment", "month"])
        won = opps[(opps.opportunity_type == "new_business") & opps.is_won
                   & opps.segment.isin(["Commercial", "Enterprise"])].copy()
        lo = won.segment.map(lambda s: config.ACV_RANGES[s][0])
        hi = won.segment.map(lambda s: config.ACV_RANGES[s][1])
        won["at_floor"] = won.amount <= lo
        won["at_cap"] = won.amount >= hi
        grp = won.groupby(["segment", "month"])
        exp = pd.DataFrame({
            "won_amount_sum": grp.amount.sum(),
            "won_list_price_sum": grp.list_price.sum(),
            "share_won_at_band_floor": grp.at_floor.mean(),
            "share_won_at_band_cap": grp.at_cap.mean(),
        })
        exp["avg_discount_rate_won"] = 1 - exp.won_amount_sum / exp.won_list_price_sum
        exp = exp.reindex(mart.index)
        for c in exp.columns:
            got = mart[c].astype(float)
            if c in ("won_amount_sum", "won_list_price_sum"):
                assert _close(got, exp[c].fillna(0), 1e-9), c
            else:
                assert _close(got, exp[c], 1e-9), c
        d = mart["avg_discount_rate_won"].dropna()
        assert ((d >= 0) & (d < 1)).all()
        # Month with no wins: sums are zero and the rate/shares are NULL, not zero.
        nowin = mart[mart.new_business_won_count == 0]
        assert len(nowin) > 0
        assert nowin.avg_discount_rate_won.isna().all() and nowin.share_won_at_band_floor.isna().all()

    def test_poc_pass_plus_fail_is_enterprise_closed_with_outcome(self, con, opps):
        mart = _mart(con, "mart_deal_funnel")
        ent = mart[mart.segment == "Enterprise"]
        com = mart[mart.segment == "Commercial"]
        assert com.poc_pass_count.isna().all() and com.poc_fail_count.isna().all()
        nb = opps[(opps.opportunity_type == "new_business") & (opps.segment == "Enterprise")]
        assert set(nb.poc_outcome.dropna()) <= {"pass", "fail"}
        with_outcome = nb.dropna(subset=["poc_outcome"])
        assert ent.poc_pass_count.sum() + ent.poc_fail_count.sum() == len(with_outcome)
        assert ent.poc_pass_count.sum() == (with_outcome.poc_outcome == "pass").sum()
        per_month = with_outcome.groupby("month").size().reindex(ent.month).fillna(0).to_numpy()
        assert ((ent.poc_pass_count + ent.poc_fail_count).to_numpy() == per_month).all()

    def test_stage_regression_matches_an_independent_rank_check(self, con, opps):
        """Order-based regression (a stage ranked below an earlier one) computed in
        pandas; the mart detects the same set as repeated stages."""
        sh = con.execute(
            "select opportunity_id, stage, entered_date, stage_sequence "
            "from main_marts.fact_opportunity_stage_history").df()
        rank = {"SAL": 0, "SQO": 1, "POC": 2, "Proposal/Negotiation": 3}
        nb = opps[(opps.opportunity_type == "new_business") & opps.segment.isin(["Commercial", "Enterprise"])]
        sh = sh[sh.opportunity_id.isin(nb.opportunity_id) & sh.stage.isin(rank)].copy()
        sh["r"] = sh.stage.map(rank)
        # Order-independent form of "a rank appears after a higher rank": the same
        # stage entered twice is the only way this data re-enters an earlier stage.
        dup = sh.groupby(["opportunity_id", "stage"]).size()
        regressed_ids = set(dup[dup > 1].index.get_level_values(0))
        sh = sh.sort_values(["opportunity_id", "entered_date", "stage_sequence"])
        order_based = set()
        for oid, g in sh.groupby("opportunity_id"):
            r = g.r.to_numpy()
            if (np.maximum.accumulate(r) != r).any():
                order_based.add(oid)
        assert order_based == regressed_ids  # same-day ties never hide a re-entry here
        mart = _mart(con, "mart_deal_funnel")
        exp = nb[nb.opportunity_id.isin(regressed_ids)].groupby(["segment", "month"]).size()
        got = mart.set_index(["segment", "month"]).stage_regression_count
        assert got.sum() == len(regressed_ids)
        assert (got.reindex(exp.index) == exp).all()

    def test_an_opportunity_repeating_two_stages_counts_once_and_does_not_fan_out(self):
        """The stage_regression CTE, run on a synthetic history in which opportunity 'a'
        repeats two different stages: one row for it (not one per repeated stage), so
        the left join that follows cannot duplicate its deal in any count."""
        import duckdb
        import os
        import re
        sql = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "dbt", "models", "marts", "marts", "mart_deal_funnel.sql")).read()
        cte = re.search(r"stage_regression as \((.*?)\n\),", sql, re.S).group(1)
        cte = cte.replace("{{ ref('fact_opportunity_stage_history') }}", "stage_history")
        mem = duckdb.connect(":memory:")
        mem.execute("create table stage_history as select * from (values "
                    "('a','SAL'),('a','SAL'),('a','SQO'),('a','SQO'),('a','POC'),"
                    "('b','SAL'),('b','SAL'),('c','SAL'),('c','SQO')) t(opportunity_id, stage)")
        mem.execute("create table new_business as select * from (values ('a'),('b'),('c')) t(opportunity_id)")
        got = mem.execute(cte).df()
        assert sorted(got.opportunity_id) == ["a", "b"]  # a once, b once, c never

    def test_days_in_stage_match_stage_history(self, con, opps):
        sh = con.execute("select opportunity_id, stage, days_in_stage from main_marts.fact_opportunity_stage_history").df()
        nb = opps[(opps.opportunity_type == "new_business") & opps.segment.isin(["Commercial", "Enterprise"])]
        mart = _mart(con, "mart_deal_funnel").set_index(["segment", "month"])
        for stage, col in [("SAL", "avg_days_in_sal"), ("SQO", "avg_days_in_sqo"),
                           ("POC", "avg_days_in_poc"), ("Proposal/Negotiation", "avg_days_in_proposal")]:
            per_opp = sh[sh.stage == stage].groupby("opportunity_id").days_in_stage.sum().rename("d")
            m = nb.join(per_opp, on="opportunity_id").dropna(subset=["d"])
            exp = m.groupby(["segment", "month"]).d.mean().reindex(mart.index)
            assert _close(mart[col], exp, 1e-9), col
        assert mart.xs("Commercial", level="segment").avg_days_in_poc.isna().all()

    def test_ramping_counts_use_owner_hire_date_and_the_ramp_window(self, con, opps):
        from analytics import rep_productivity
        hire = con.execute("select rep_id, min(hire_date) h, max(hire_date) h2 from main_marts.dim_reps group by 1").df()
        assert (hire.h == hire.h2).all()  # hire_date is static per rep across capacity periods
        nb = opps[(opps.opportunity_type == "new_business") & opps.segment.isin(["Commercial", "Enterprise"])]
        nb = nb.merge(hire[["rep_id", "h"]], on="rep_id", how="left")
        assert nb.h.notna().all()
        ramping = (nb.created_date - pd.to_datetime(nb.h)).dt.days < rep_productivity._RAMP_FULL_DAYS
        nb = nb.assign(ramping=ramping)
        mart = _mart(con, "mart_deal_funnel").set_index(["segment", "month"])
        closed = nb[nb.ramping].groupby(["segment", "month"]).size().reindex(mart.index).fillna(0)
        won = nb[nb.ramping & nb.is_won].groupby(["segment", "month"]).size().reindex(mart.index).fillna(0)
        assert (mart.closed_by_ramping_rep_count == closed).all()
        assert (mart.won_by_ramping_rep_count == won).all()
        assert (mart.won_by_ramping_rep_count <= mart.closed_by_ramping_rep_count).all()

    def test_renewals_kept_separate(self, con, opps):
        mart = _mart(con, "mart_deal_funnel").set_index(["segment", "month"])
        rn = opps[(opps.opportunity_type == "renewal") & opps.segment.isin(["Commercial", "Enterprise"])]
        won = rn[rn.is_won].groupby(["segment", "month"]).size().reindex(mart.index).fillna(0)
        lost = rn[~rn.is_won].groupby(["segment", "month"]).size().reindex(mart.index).fillna(0)
        assert (mart.renewal_won_count == won).all()
        assert (mart.renewal_lost_count == lost).all()
        assert mart.renewal_won_count.sum() == len(rn[rn.is_won])


# -------------------------------------------- mart_workflow_chain_health

class TestWorkflowChainHealth:
    @pytest.fixture(scope="class")
    def joined(self, con):
        w = con.execute("select account_id, month, upstream_actions, downstream_actions, "
                        "full_chain_completion_rate from main_marts.fact_workflow_chain_events").df()
        u = con.execute("select account_id, month, segment from main_marts.fact_usage_monthly").df()
        return w, u

    def test_join_to_usage_is_one_to_one_with_no_unjoined_account_months(self, joined):
        w, u = joined
        assert not w.duplicated(["account_id", "month"]).any()
        assert not u.duplicated(["account_id", "month"]).any()
        m = w.merge(u, on=["account_id", "month"], how="outer", indicator=True)
        assert (m["_merge"] == "both").all()

    def test_matches_recomputation_from_the_facts(self, con, joined):
        w, u = joined
        thr = _project_vars()["workflow_chain_completion_threshold"]
        d = w.merge(u, on=["account_id", "month"])
        d["month"] = pd.to_datetime(d["month"])
        d["partial"] = d.full_chain_completion_rate < thr
        d = d.sort_values(["account_id", "month"])
        prev_month_partial = d.groupby("account_id").partial.shift(1)
        prev_month = d.groupby("account_id").month.shift(1)
        adjacent = (d.month - prev_month) == (d.month - (d.month - pd.offsets.MonthBegin(1)))
        d["sustained"] = d.partial & prev_month_partial.eq(True) & adjacent
        g = d.groupby(["segment", "month"])
        exp = pd.DataFrame({
            "upstream_actions_sum": g.upstream_actions.sum(),
            "downstream_actions_sum": g.downstream_actions.sum(),
            "accounts_with_chain": g.size(),
            "partial_chain_account_count": g.partial.sum(),
            "sustained_partial_account_count": g.sustained.sum(),
        })
        exp["full_chain_account_count"] = exp.accounts_with_chain - exp.partial_chain_account_count
        exp["ingestion_without_completion_rate"] = 1 - exp.downstream_actions_sum / exp.upstream_actions_sum
        mart = _mart(con, "mart_workflow_chain_health").set_index(["segment", "month"])
        assert len(mart) == len(exp)
        exp = exp.reindex(mart.index)
        for c in exp.columns:
            assert _close(mart[c], exp[c], 1e-9), c

    def test_mart_sums_equal_fact_sums_per_month(self, con, joined):
        w, _ = joined
        mart = _mart(con, "mart_workflow_chain_health").groupby("month")[
            ["upstream_actions_sum", "downstream_actions_sum", "accounts_with_chain"]].sum()
        w["month"] = pd.to_datetime(w["month"])
        f = w.groupby("month").agg(upstream_actions_sum=("upstream_actions", "sum"),
                                   downstream_actions_sum=("downstream_actions", "sum"),
                                   accounts_with_chain=("account_id", "size"))
        assert (mart.index == f.index).all()
        assert (mart.to_numpy() == f.to_numpy()).all()

    def test_partition_and_bounds(self, con):
        m = _mart(con, "mart_workflow_chain_health")
        assert (m.partial_chain_account_count + m.full_chain_account_count == m.accounts_with_chain).all()
        assert (m.sustained_partial_account_count <= m.partial_chain_account_count).all()
        assert (m.downstream_actions_sum <= m.upstream_actions_sum).all()
        assert m.ingestion_without_completion_rate.between(0, 1).all()


# ----------------------------------------- mart_consumption_utilization

class TestConsumptionUtilization:
    @pytest.fixture(scope="class")
    def acct(self, con):
        d = con.execute(
            "select c.account_id, c.month, c.segment, c.committed_actions_monthly c, c.utilized_actions_monthly u, r.mrr "
            "from main_marts.fact_committed_vs_utilized_monthly c "
            "join main_marts.fact_revenue_monthly r using (account_id, month)").df()
        d["month"] = pd.to_datetime(d["month"])
        return d

    def test_join_is_one_to_one(self, con):
        n_c = con.execute("select count(*) from main_marts.fact_committed_vs_utilized_monthly").fetchone()[0]
        n_r = con.execute("select count(*) from main_marts.fact_revenue_monthly").fetchone()[0]
        n_j = con.execute("select count(*) from main_marts.fact_committed_vs_utilized_monthly c "
                          "join main_marts.fact_revenue_monthly r using (account_id, month)").fetchone()[0]
        assert n_c == n_r == n_j

    def test_matches_recomputation_from_the_facts(self, con, acct):
        d = acct[acct.segment.isin(["Commercial", "Enterprise"])].copy()
        d["has"] = d.c > 0
        d["over"] = np.where(d.has, np.maximum(d.u - d.c, 0), 0.0)
        d["over_mrr"] = np.where(d.has, d.mrr * d.over / np.maximum(d.c, d.u), 0.0)
        d["c0"] = np.where(d.has, d.c, 0.0)
        d["u0"] = np.where(d.has, d.u, 0.0)
        d["is_over"] = d.has & (d.u > d.c)
        g = d.groupby(["segment", "month"])
        exp = pd.DataFrame({
            "committed_actions_sum": g.c0.sum(), "utilized_actions_sum": g.u0.sum(),
            "overage_actions_sum": g.over.sum(), "overage_mrr": g.over_mrr.sum(),
            "total_mrr": g.mrr.sum(), "accounts_over_commit_count": g.is_over.sum(),
            "accounts_with_commitment_count": g.has.sum(),
        })
        exp["overage_share_of_mrr"] = exp.overage_mrr / exp.total_mrr
        mart = _mart(con, "mart_consumption_utilization").set_index(["segment", "month"])
        assert len(mart) == len(exp)
        exp = exp.reindex(mart.index)
        for c in exp.columns:
            assert _close(mart[c], exp[c], 1e-9), c

    def test_total_mrr_reconciles_with_fact_revenue_and_overage_is_bounded(self, con):
        m = _mart(con, "mart_consumption_utilization")
        r = con.execute("select sum(mrr) from main_marts.fact_revenue_monthly "
                        "where segment in ('Commercial','Enterprise')").fetchone()[0]
        assert abs(m.total_mrr.sum() - r) < 0.01
        assert (m.overage_mrr >= 0).all() and (m.overage_mrr <= m.total_mrr + 1e-6).all()
        assert m.overage_share_of_mrr.between(0, 1).all()
        assert (m.overage_actions_sum >= 0).all()
        assert (m.accounts_over_commit_count <= m.accounts_with_commitment_count).all()


# ------------------------------------------------------------ determinism

def _digest(db_path, mart):
    c = duckdb.connect(db_path, read_only=True)
    try:
        rows = c.execute(f"select * from main_marts.{mart}").fetchall()  # physical order
    finally:
        c.close()
    return hashlib.sha256(repr(rows).encode()).hexdigest(), len(rows)


def test_three_marts_are_identical_across_two_consecutive_builds(tmp_path):
    """Rebuild the marts twice into a throwaway copy of the database (the real
    file is never written) and compare them row for row in stored order."""
    if not os.path.exists(DB_PATH):
        pytest.skip("dbt-built database not present")
    tmp_db = str(tmp_path / "copy.duckdb")
    shutil.copy(DB_PATH, tmp_db)
    profiles = tmp_path / "profiles.yml"
    profiles.write_text(
        "acme_gtm:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n"
        f"      path: \"{tmp_db}\"\n      threads: 4\n")
    cmd = [sys.executable, "-W", "ignore", "-c",
           "import sys; from dbt.cli.main import cli; sys.exit(cli())",
           "run", "--profiles-dir", str(tmp_path), "--select", *MARTS]
    digests = []
    for _ in range(2):
        proc = subprocess.run(cmd, cwd=DBT_DIR, capture_output=True, text=True, timeout=600)
        assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
        digests.append({m: _digest(tmp_db, m) for m in MARTS})
    assert digests[0] == digests[1]
    for m in MARTS:
        assert digests[0][m] == _digest(DB_PATH, m), f"{m}: rebuild differs from the committed build"
