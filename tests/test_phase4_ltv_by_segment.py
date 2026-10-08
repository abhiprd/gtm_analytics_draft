"""LTV by entry segment (analytics/ltv_by_segment.py).

  * Pure tests need no database: Kaplan-Meier and the constant-hazard tail on small known
    inputs, the LTV arithmetic against closed forms, the MRR-path scenarios, the log-rank test,
    the synthetic planted-hazard scenarios, the constants against the metric tree and the dbt
    var, the published text and the module's source-level rules.
  * Fresh-run tests need the dbt database: the tie-outs to retention_cohorts and to
    fact_revenue_monthly, the CAC input tie-outs, the no-look-ahead perturbation, the
    non-additive-overlay contract, a sweep of as-of dates, the committed reports against a fresh
    run at a float tolerance, and idempotent logging.

Run: python3 -m pytest tests/test_phase4_ltv_by_segment.py -v
"""
import json
import os
import re
import subprocess
import sys
from datetime import date

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from analytics import ltv_by_segment as L  # noqa: E402
from analytics import model_performance as mp  # noqa: E402

OUT = os.path.join(ROOT, "analytics", "outputs")
DB_PATH = os.path.join(ROOT, "data", "acme_gtm.duckdb")
CHECKPOINTS = ["2025-06-30", "2025-12-31"]
needs_db = pytest.mark.skipif(
    not os.path.exists(DB_PATH), reason="dbt-built database not present; run `cd dbt && dbt build`")


def _assert_equal_up_to_float_noise(got, exp, path="root", rel=1e-9, floor=1e-9):
    """Structural equality where floats match at a relative tolerance and an
    absolute floor and every other value matches exactly."""
    if isinstance(exp, dict):
        assert isinstance(got, dict) and set(got) == set(exp), f"{path}: keys differ"
        for k in exp:
            _assert_equal_up_to_float_noise(got[k], exp[k], f"{path}.{k}", rel, floor)
    elif isinstance(exp, (list, tuple)):
        assert isinstance(got, (list, tuple)) and len(got) == len(exp), f"{path}: length differs"
        for i, (g, e) in enumerate(zip(got, exp)):
            _assert_equal_up_to_float_noise(g, e, f"{path}[{i}]", rel, floor)
    elif isinstance(exp, float) and isinstance(got, (int, float)) and not isinstance(got, bool):
        assert got == pytest.approx(exp, rel=rel, abs=floor), f"{path}: {got!r} != {exp!r}"
    else:
        assert got == exp, f"{path}: {got!r} != {exp!r}"


def _committed(d):
    with open(os.path.join(OUT, f"ltv_by_segment_{d}.json")) as f:
        return json.load(f)


# --------------------------------------------------------------------------
# Constants: the tree's three inputs and the shared margin
# --------------------------------------------------------------------------

class TestConstants:
    def test_horizon_discount_rate_and_margin_are_the_trees(self):
        assert L.HORIZON_MONTHS == 60 and L.ANNUAL_DISCOUNT_RATE == 0.10 and L.GROSS_MARGIN == 0.80
        assert L.validation_tree_constants()["passed"]

    def test_margin_equals_the_dbt_var_and_mart_efficiency_carries_no_literal(self):
        check = L.validation_margin_constant_ties_to_dbt()
        assert check["passed"], check["detail"]
        with open(os.path.join(ROOT, "dbt", "models", "marts", "marts", "mart_efficiency.sql")) as f:
            sql = f.read()
        assert not re.search(r"\*\s*0\.8\b", sql) and 'var("consumption_gross_margin")' in sql

    def test_model_name_and_node_key(self):
        assert L._MODEL_NAME == "ltv_by_segment"
        assert L.NODE_KEY == "ltv_by_segment_acquisition_channel"

    def test_module_reads_only_the_marts_layer(self):
        with open(os.path.join(ROOT, "analytics", "ltv_by_segment.py")) as f:
            src = f.read()
        assert not re.search(r"\b(stg_|int_)\w+", src)
        assert "main_staging" not in src and "main_intermediate" not in src

    def test_acquisition_rep_roles_exclude_account_managers(self):
        roles = [r for rs in L.ACQUISITION_REP_TYPES.values() for r in rs]
        assert roles == ["ISR", "AE", "SE"] and not any(r.startswith("AM") for r in roles)


# --------------------------------------------------------------------------
# Survival
# --------------------------------------------------------------------------

class TestSurvival:
    def test_kaplan_meier_known_answer(self):
        # four accounts, as-of age 3 for all; last_age 1, 2, 3, 3: churn after age 1 and after age 2
        cur = L.km_curve([1, 2, 3, 3], [3, 3, 3, 3])
        assert list(cur["at_risk"]) == [4, 4, 3] and list(cur["events"]) == [0, 1, 1]
        assert cur["S"] == pytest.approx([1.0, 1.0, 0.75, 0.5])

    def test_censored_accounts_leave_the_at_risk_set_without_counting_as_churn(self):
        # account 2 is only 1 month old: at risk for the 0->1 transition only
        cur = L.km_curve([5, 1, 5], [5, 1, 5])
        assert cur["at_risk"][0] == 3 and cur["events"][0] == 0
        assert cur["at_risk"][1] == 2 and cur["events"][1] == 0

    def test_survival_is_monotone_non_increasing(self):
        rng = np.random.default_rng(3)
        max_age = rng.integers(0, 60, 500)
        last = np.minimum(rng.integers(0, 80, 500), max_age)
        S = L.km_curve(last, max_age)["S"]
        S = S[~np.isnan(S)]
        assert np.all(np.diff(S) <= 1e-12)

    def test_wilson_interval_contains_the_rate_and_widens_with_less_data(self):
        lo, hi = L.wilson_interval(10, 1000)
        assert lo < 0.01 < hi
        lo2, hi2 = L.wilson_interval(1, 100)
        assert (hi2 - lo2) > (hi - lo)
        assert L.wilson_interval(0, 500)[0] == 0.0 and L.wilson_interval(0, 500)[1] > 0

    def test_observed_through_stops_at_the_minimum_at_risk(self):
        acc, rev = L._synthetic_frames(3000, np.full(200, 0.02), 40, lambda a: 100.0, seed=1)
        la, ma = L.account_state(acc, rev, 1200)
        ret = L.project_retention(L.km_curve(la, ma))
        assert ret["status"] == "present" and ret["observed_through"] <= 39
        n = L.km_curve(la, ma)["at_risk"]
        assert n[ret["observed_through"] - 1] >= L.MIN_AT_RISK

    def test_tail_hazard_is_events_over_exposure_in_the_last_12_transitions(self):
        acc, rev = L._synthetic_frames(3000, np.full(200, 0.02), 40, lambda a: 100.0, seed=1)
        la, ma = L.account_state(acc, rev, 1200)
        cur = L.km_curve(la, ma)
        ret = L.project_retention(cur)
        a = ret["observed_through"]
        expect = cur["events"][a - 12:a].sum() / cur["at_risk"][a - 12:a].sum()
        assert ret["tail"]["monthly_hazard"] == pytest.approx(expect)
        assert ret["central"][a + 1] == pytest.approx(ret["central"][a] * (1 - expect))

    def test_band_brackets_the_central_curve_everywhere(self):
        acc, rev = L._synthetic_frames(3000, np.full(200, 0.02), 40, lambda a: 100.0, seed=2)
        la, ma = L.account_state(acc, rev, 1200)
        ret = L.project_retention(L.km_curve(la, ma))
        assert np.all(ret["low"] <= ret["central"] + 1e-12) and np.all(ret["central"] <= ret["high"] + 1e-12)

    def test_too_few_accounts_is_unavailable_with_a_reason(self):
        acc, rev = L._synthetic_frames(10, np.full(200, 0.02), 40, lambda a: 100.0, seed=1)
        la, ma = L.account_state(acc, rev, 1200)
        ret = L.project_retention(L.km_curve(la, ma))
        assert ret["status"] == "unavailable" and ret["reason_code"] == "insufficient_at_risk"

    def test_a_history_shorter_than_the_tail_window_is_unavailable(self):
        acc, rev = L._synthetic_frames(20000, np.full(200, 0.02), 8, lambda a: 100.0, seed=1)
        la, ma = L.account_state(acc, rev, 1200)
        ret = L.project_retention(L.km_curve(la, ma))
        assert ret["status"] == "unavailable" and ret["reason_code"] == "insufficient_observed_history"


# --------------------------------------------------------------------------
# LTV arithmetic
# --------------------------------------------------------------------------

class TestLtvArithmetic:
    def test_month_zero_is_undiscounted_and_month_twelve_is_one_discount_year(self):
        d = L.discount_factors()
        assert d[0] == 1.0 and d[12] == pytest.approx(1 / 1.10) and d[24] == pytest.approx(1 / 1.21)

    def test_known_answer(self):
        S = np.ones(61)
        m = np.full(60, 100.0)
        assert L.ltv_value(S, m) == pytest.approx(100.0 * 0.8 * L.discount_factors().sum())

    def test_linear_in_margin_and_in_mrr_and_survival(self):
        S = np.linspace(1, 0.4, 61)
        m = np.linspace(100, 300, 60)
        base = L.ltv_value(S, m)
        assert L.ltv_value(S, m, margin=0.4) == pytest.approx(base / 2)
        assert L.ltv_value(S, 2 * m) == pytest.approx(2 * base)
        assert L.ltv_value(0.5 * S, m) == pytest.approx(base / 2)

    def test_undiscounted_is_larger(self):
        S = np.full(61, 0.9)
        m = np.full(60, 50.0)
        assert L.ltv_value(S, m, annual_rate=0.0) > L.ltv_value(S, m)

    def test_ltv_uses_only_the_first_sixty_ages(self):
        S = np.ones(61)
        S2 = S.copy()
        S2[60] = 0.0
        m = np.full(60, 10.0)
        assert L.ltv_value(S, m) == L.ltv_value(S2, m)

    def test_evidence_grades(self):
        assert L.evidence_grade(1784) == "point" and L.evidence_grade(44) == "range" and L.evidence_grade(5) == "directional"


class TestMrrPaths:
    def test_recent_window_older_window_and_flat_hold(self):
        growth = lambda a: 100.0 * (1.0 + 0.04 * a)
        acc, rev = L._synthetic_frames(15000, np.full(200, 0.01), 71, growth, seed=5, recent_level=1.5)
        paths = L.mrr_path_scenarios(acc, rev, 1200)
        rf, of = paths["recent_flat"], paths["older_flat"]
        assert rf["values"][12] == pytest.approx(150.0 * 1.48) and of["values"][12] == pytest.approx(100.0 * 1.48)
        a = rf["direct_through"]
        assert a < 59 and np.all(rf["values"][a:] == rf["values"][a])

    def test_chain_extends_growth_past_the_recent_window_and_never_below_flat_for_a_growing_path(self):
        growth = lambda a: 100.0 * (1.0 + 0.04 * a)
        acc, rev = L._synthetic_frames(15000, np.full(200, 0.01), 71, growth, seed=5)
        paths = L.mrr_path_scenarios(acc, rev, 1200)
        assert paths["recent_chain"]["values"][59] > paths["recent_flat"]["values"][59]
        a = paths["recent_flat"]["direct_through"]
        assert paths["recent_chain"]["values"][a] == paths["recent_flat"]["values"][a]

    def test_no_recent_accounts_gives_no_path(self):
        acc, rev = L._synthetic_frames(500, np.full(200, 0.01), 71, lambda a: 100.0, seed=5)
        old_only = rev[rev["m0"] < 1200 - 80]
        assert L.mrr_path_scenarios(acc, old_only, 1200) == {}


# --------------------------------------------------------------------------
# Synthetic planted-hazard scenarios
# --------------------------------------------------------------------------

class TestSyntheticScenarios:
    def test_every_known_answer_scenario_matches(self):
        out = L.run_synthetic_scenarios()
        assert out["n_passed"] == out["n_scenarios"], [s for s in out["scenarios"] if not s["passed"]]

    def test_the_named_scenarios_exist(self):
        names = {s["name"] for s in L.run_synthetic_scenarios()["scenarios"]}
        assert {"constant_hazard_fully_observed", "constant_hazard_tail_extrapolated",
                "hazard_rise_beyond_window_is_missed_as_the_rule_predicts",
                "hazard_change_inside_observed_window_is_tracked",
                "annual_renewal_cliffs_survive_a_constant_monthly_tail",
                "zero_churn_constant_mrr_equals_the_closed_form_discounted_sum",
                "under_sampled_segment_is_unavailable_with_a_reason"} <= names

    def test_expected_values_do_not_use_the_modules_own_ltv_arithmetic(self):
        import ast
        import inspect
        import textwrap
        called = set()
        for fn in (L._independent_ltv, L._closed_form):
            for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(fn)))):
                if isinstance(node, ast.Call):
                    f = node.func
                    called.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
        assert not called & {"ltv_value", "ltv_terms", "discount_factors", "evaluate_ltv"}, called

    def test_scenarios_are_reproducible(self):
        a, b = L.run_synthetic_scenarios(), L.run_synthetic_scenarios()
        assert a == b


# --------------------------------------------------------------------------
# Channel
# --------------------------------------------------------------------------

class TestChannelTest:
    def test_identical_groups_do_not_differ(self):
        rng = np.random.default_rng(1)
        max_age = rng.integers(10, 60, 4000)
        last = np.minimum(rng.geometric(0.02, 4000) - 1, max_age)
        t = L.logrank_test(last[:2000], max_age[:2000], last[2000:], max_age[2000:])
        assert t["p_value"] > 0.05

    def test_clearly_different_hazards_are_detected(self):
        rng = np.random.default_rng(2)
        max_age = rng.integers(20, 60, 2000)
        a = np.minimum(rng.geometric(0.01, 2000) - 1, max_age)
        b = np.minimum(rng.geometric(0.06, 2000) - 1, max_age)
        assert L.logrank_test(a, max_age, b, max_age)["p_value"] < 1e-6

    def test_symmetric_in_the_two_groups(self):
        rng = np.random.default_rng(3)
        max_age = rng.integers(20, 60, 800)
        a = np.minimum(rng.geometric(0.02, 800) - 1, max_age)
        b = np.minimum(rng.geometric(0.03, 800) - 1, max_age)
        assert L.logrank_test(a, max_age, b, max_age)["p_value"] == pytest.approx(
            L.logrank_test(b, max_age, a, max_age)["p_value"])


class TestAsOfDate:
    @pytest.mark.parametrize("d,expected", [
        (date(2025, 12, 31), date(2025, 12, 31)), (date(2025, 12, 30), date(2025, 11, 30)),
        (date(2025, 3, 1), date(2025, 2, 28)), (date(2024, 3, 1), date(2024, 2, 29)),
        (date(2025, 1, 15), date(2024, 12, 31)), (date(2026, 6, 30), date(2026, 6, 30))])
    def test_last_complete_month_end(self, d, expected):
        assert L.last_complete_month_end(d) == expected

    def test_month_index_round_trip(self):
        assert L.index_to_month_end(L._as_of_index(date(2025, 2, 28))) == date(2025, 2, 28)
        assert L.index_to_month_end(2024 * 12 + 12) == date(2024, 12, 31)


class TestPublishedText:
    def test_status_is_labelled_proposed_everywhere(self):
        assert L.STATUS_RULE["status"].startswith("proposed")

    def test_caveats_state_the_load_bearing_limits(self):
        text = " ".join(L.LTV_CAVEATS)
        for needle in ("no detectable retention or revenue difference", "not decision-grade", "Pre-2023", "22 and 6",
                       "MRR path", "floor on cost"):
            assert needle in text

    def test_text_is_plain_ascii(self):
        for t in list(L.LTV_CAVEATS) + list(L.DEFINITIONS.values()):
            assert t.isascii(), t


# --------------------------------------------------------------------------
# Fresh runs against the dbt database
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def con():
    import duckdb
    c = duckdb.connect(DB_PATH, read_only=True)
    yield c
    c.close()


@pytest.fixture(scope="module")
def fresh(con):
    return {d: L.run_ltv(date.fromisoformat(d), con=con) for d in CHECKPOINTS}


@pytest.fixture(scope="module")
def frames(con):
    return L.load_frames(date(2025, 12, 31), con)


def _seg(reading, name):
    return next(s for s in reading["segments"] if s["entry_segment"] == name)


@needs_db
class TestAgainstTheMarts:
    def test_survival_counts_tie_to_retention_cohorts_exactly(self, frames, con):
        assert L.validation_counts_tie_to_retention_cohorts(frames, date(2025, 12, 31), con)["passed"]

    def test_oldest_cohort_revenue_ties_to_fact_revenue_monthly(self, frames, con):
        c = L.validation_oldest_cohort_revenue_identity(frames, date(2025, 12, 31), con)
        assert c["passed"], c["detail"]

    def test_account_rows_start_at_signup_and_are_contiguous(self, frames):
        assert L.validation_data_integrity(frames)["passed"]

    def test_cac_inputs_tie(self, frames, con):
        cac = L.compute_cac(frames["accounts"], frames["spend"], frames["rep_cost"], frames["wins"])
        checks = L.validation_cac_inputs_tie(frames, cac, con)
        assert len(checks) == 5 and all(c["passed"] for c in checks), checks

    def test_the_node_stays_a_non_additive_overlay_with_no_children(self, fresh):
        assert L.validation_node_is_non_additive_overlay(fresh["2025-12-31"])["passed"]
        r = fresh["2025-12-31"]
        assert r["non_additive"] is True and "children" not in r and r["node"] == L.NODE_KEY

    def test_channel_is_not_claimed_as_a_retention_signal(self, fresh):
        r = fresh["2025-12-31"]
        assert L.validation_channel_not_claimed_as_retention_signal(r)["passed"]
        cut = {c["channel"]: c for c in r["smb_channel_cut"]}
        assert cut["self_serve"]["ltv_central_usd"] == cut["inbound_marketing"]["ltv_central_usd"]
        assert r["channel_retention_tests"]["SMB"]["significant_at_5pct"] is False
        assert cut["self_serve"]["ltv_to_cac_marketing_only"] > 10 * cut["inbound_marketing"]["ltv_to_cac_marketing_only"]

    @pytest.mark.parametrize("t", [date(2025, 12, 31), date(2023, 6, 30)])
    def test_no_look_ahead_perturbation(self, con, t):
        c = L.validation_no_lookahead(t, con)
        assert c["passed"], c["detail"]

    def test_a_mid_month_date_reads_the_last_complete_month(self, con):
        a, b = L.run_ltv(date(2025, 6, 17), con=con), L.run_ltv(date(2025, 5, 31), con=con)
        assert a["data_through"] == "2025-05-31"
        assert {k: v for k, v in a.items() if k != "as_of_date"} == {k: v for k, v in b.items() if k != "as_of_date"}

    def test_backtest_fit_equals_a_direct_reading_at_the_origin(self, frames, con):
        assert L.validation_backtest_fit_equals_direct_reading(frames, date(2025, 12, 31), con)["passed"]

    def test_checkpoint_readings_carry_the_documented_numbers(self, fresh):
        r = fresh["2025-12-31"]
        smb, com, ent = _seg(r, "SMB"), _seg(r, "Commercial"), _seg(r, "Enterprise")
        assert smb["retention"]["checkpoints"]["60"]["central"] == pytest.approx(0.422003, abs=1e-5)
        assert smb["retention"]["checkpoints"]["60"]["kind"] == "observed"
        assert com["retention"]["observed_through_month"] == 49 and ent["retention"]["observed_through_month"] == 28
        assert smb["ltv"]["central_usd"] == pytest.approx(15758.16, abs=0.5)
        assert com["ltv"]["central_usd"] == pytest.approx(223055.76, abs=0.5)
        assert ent["ltv"]["central_usd"] == pytest.approx(1143280.05, abs=0.5)
        assert (smb["evidence_grade"], com["evidence_grade"], ent["evidence_grade"]) == ("point", "range", "directional")
        assert smb["cac"]["marketing_only_cac_usd"] == pytest.approx(453.67, abs=0.01)
        assert com["cac"]["rep_loaded_cac_usd"] == pytest.approx(31831.25, abs=0.01)
        assert ent["cac"]["rep_loaded_cac_usd"] == pytest.approx(338938.54, abs=0.01)

    def test_ranges_bracket_the_central_value_and_shares_are_proportions(self, fresh):
        for d in CHECKPOINTS:
            for s in fresh[d]["segments"]:
                if s["status"] != "present":
                    continue
                L_ = s["ltv"]
                assert L_["low_usd"] <= L_["central_usd"] <= L_["high_usd"]
                assert 0 <= L_["observed_share"] <= 1 and L_["observed_share"] + L_["projected_share"] == pytest.approx(1.0)
                q = s["ltv_to_cac"]
                if "rep_loaded" in q:
                    assert q["rep_loaded"]["low"] <= q["rep_loaded"]["central"] <= q["rep_loaded"]["high"]

    def test_marketing_only_ratio_is_never_decision_grade_for_commercial_or_enterprise(self, fresh):
        for name in ("Commercial", "Enterprise"):
            q = _seg(fresh["2025-12-31"], name)["ltv_to_cac"]
            assert q["marketing_only_decision_grade"] is False and q["rep_loaded_decision_grade"] is False
            assert q["marketing_only"]["central"] > 10 * q["rep_loaded"]["central"]

    def test_smb_has_no_reps_so_rep_loaded_equals_marketing_only(self, fresh):
        smb = _seg(fresh["2025-12-31"], "SMB")
        assert smb["cac"]["rep_cost_usd"] == 0 and smb["cac"]["rep_acquisition_roles"] == []
        assert smb["ltv_to_cac"]["rep_loaded"]["central"] == smb["ltv_to_cac"]["marketing_only"]["central"]

    def test_commercial_and_enterprise_channels_are_suppressed_with_a_reason(self, fresh):
        cells = fresh["2025-12-31"]["channel_cells_not_shown"]
        assert {"Commercial", "Enterprise"} <= {c["entry_segment"] for c in cells}
        assert all(c["reason"] for c in cells)
        assert {c["channel"] for c in fresh["2025-12-31"]["smb_channel_cut"]} == {"self_serve", "inbound_marketing"}

    def test_pre_2023_dates_have_no_cac_and_are_not_zero(self, con):
        r = L.run_ltv(date(2022, 12, 31), con=con)
        assert r["cac_status"] == "unavailable" and r["cac_reason"]
        assert all(s.get("cac") is None for s in r["segments"])
        assert all(s.get("ltv_to_cac", {}) == {} for s in r["segments"])

    def test_enterprise_is_unavailable_before_it_has_the_accounts(self, con):
        r = L.run_ltv(date(2023, 6, 30), con=con)
        ent = _seg(r, "Enterprise")
        assert ent["status"] == "unavailable" and ent["reason_code"] in ("insufficient_at_risk", "insufficient_observed_history")
        assert ent["reason"] and "ltv" not in ent

    def test_output_is_json_safe(self, fresh):
        text = json.dumps(fresh["2025-12-31"])
        assert "NaN" not in text and "Infinity" not in text
        assert json.loads(text) == fresh["2025-12-31"]

    def test_display_strings_are_plain_and_say_what_they_must(self, fresh):
        for s in fresh["2025-12-31"]["segments"]:
            d = s["display"]
            assert d["summary"].isascii() and "nan" not in d["summary"].lower()
        smb = _seg(fresh["2025-12-31"], "SMB")["display"]["summary"]
        assert "floor on cost" in smb and "moves up a segment" in smb
        com = _seg(fresh["2025-12-31"], "Commercial")["display"]["summary"]
        assert "not decision-grade" in com
        ent = _seg(fresh["2025-12-31"], "Enterprise")["display"]["summary"]
        assert "directional only" in ent

    def test_every_as_of_date_returns_a_reading_never_an_exception(self, con):
        for d in [date(2019, 12, 31), date(2020, 1, 20), date(2020, 6, 30), date(2021, 3, 15), date(2022, 12, 31),
                  date(2023, 1, 31), date(2024, 7, 4), date(2025, 12, 31), date(2026, 6, 30)]:
            r = L.run_ltv(d, con=con)
            assert len(r["segments"]) == 3
            for s in r["segments"]:
                assert s["status"] in ("present", "unavailable")
                if s["status"] == "unavailable":
                    assert s["reason_code"] and s["reason"]


@needs_db
class TestBacktest:
    def test_smb_backtest_is_within_the_proposed_rule(self, frames):
        acc, rev = frames["accounts"], frames["revenue"]
        b = L.backtest_segment(acc[acc["entry_segment"] == "SMB"], rev[rev["entry_segment"] == "SMB"],
                               L._as_of_index(date(2025, 12, 31)))
        assert b["status"] == "present" and b["origin"] == "2022-12-31"
        assert b["max_abs_gap_pp"] < L.SMB_GAP_PP_LIMIT and b["all_realized_in_band"]
        assert [r["age"] for r in b["retention_rows"]] == [36, 42, 48, 54, 60]
        assert b["retention_rows"][-1]["n_at_risk_realized"] >= 200
        assert all(r["realized_identity_max_abs_diff_usd"] < 1e-6 for r in b["ltv_rows"])

    def test_the_backtest_uses_only_data_through_the_origin_for_the_fit(self, frames):
        acc, rev = frames["accounts"], frames["revenue"]
        a = acc[acc["entry_segment"] == "SMB"]
        r = rev[rev["entry_segment"] == "SMB"]
        origin = L._as_of_index(date(2025, 12, 31)) - 36
        clean = L.fit_segment(a, r, origin)
        mutated = r.copy()
        mutated.loc[mutated["r_idx"] > origin, "mrr"] *= 9
        mutated.loc[mutated["r_idx"] > origin, "mrr_in_entry"] *= 9
        again = L.fit_segment(a, mutated, origin)
        assert clean["ltv"]["central"] == again["ltv"]["central"]
        assert np.array_equal(clean["retention"]["central"], again["retention"]["central"])

    def test_enterprise_cannot_be_backtested_and_says_so(self, frames):
        acc, rev = frames["accounts"], frames["revenue"]
        b = L.backtest_segment(acc[acc["entry_segment"] == "Enterprise"], rev[rev["entry_segment"] == "Enterprise"],
                               L._as_of_index(date(2025, 12, 31)))
        assert b["status"] == "unavailable" and b["reason"]
        d = L.drift_assessment({"Enterprise": b}, 23)
        assert d["Enterprise"]["flag"] is None and d["Enterprise"]["backtestable"] is False

    def test_the_drift_rule_flags_a_planted_gap(self):
        row = lambda age, gap, inb: {"age": age, "gap_pp": gap, "in_band": inb}
        ok = {"SMB": {"status": "present", "retention_rows": [row(48, 1.0, True), row(60, -2.0, True)]}}
        assert L.drift_assessment(ok, 0)["SMB"]["flag"] is False
        wide = {"SMB": {"status": "present", "retention_rows": [row(48, 1.0, True), row(60, -6.5, True)]}}
        assert L.drift_assessment(wide, 0)["SMB"]["flag"] is True
        outside = {"SMB": {"status": "present", "retention_rows": [row(48, 1.0, False), row(60, -2.0, True)]}}
        assert L.drift_assessment(outside, 0)["SMB"]["flag"] is True


@needs_db
class TestCommittedReports:
    @pytest.mark.parametrize("d", CHECKPOINTS)
    def test_the_committed_reading_equals_a_fresh_run_up_to_float_noise(self, d, fresh):
        got = json.loads(json.dumps(L._rounded(fresh[d])))
        _assert_equal_up_to_float_noise(got, _committed(d)["reading"])

    @pytest.mark.parametrize("d", CHECKPOINTS)
    def test_committed_report_records_every_structural_check_passing(self, d):
        rep = _committed(d)
        structural = [c for c in rep["checks"] if c["kind"] == "structural"]
        assert structural and all(c["passed"] for c in structural)
        assert rep["checks_passed"] == rep["checks_total"] == len(structural)
        assert rep["synthetic"]["n_passed"] == rep["synthetic"]["n_scenarios"]
        assert rep["target_met"] is True

    @pytest.mark.parametrize("d", CHECKPOINTS)
    def test_committed_backtest_equals_a_fresh_backtest(self, d, frames):
        as_of = date.fromisoformat(d)
        fr = frames if d == "2025-12-31" else None
        if fr is None:
            import duckdb
            c = duckdb.connect(DB_PATH, read_only=True)
            try:
                fr = L.load_frames(as_of, c)
            finally:
                c.close()
        acc, rev = fr["accounts"], fr["revenue"]
        fresh_bt = L.backtest_segment(acc[acc["entry_segment"] == "SMB"], rev[rev["entry_segment"] == "SMB"],
                                      L._as_of_index(as_of))
        got = json.loads(json.dumps(L._rounded(L._jsonable(fresh_bt))))
        _assert_equal_up_to_float_noise(got, _committed(d)["backtest"]["SMB"])

    def test_committed_markdown_matches_the_committed_json(self):
        for d in CHECKPOINTS:
            with open(os.path.join(OUT, f"ltv_by_segment_{d}.md")) as f:
                md = f.read()
            assert md == L.render_markdown(_committed(d))

    def test_the_two_checkpoints_cover_the_contract(self):
        with open(os.path.join(ROOT, "pipeline", "freshness_contract.json")) as f:
            entry = next(a for a in json.load(f)["artifacts"] if a["name"] == "ltv_by_segment")
        assert entry["entrypoint_as_of"] == CHECKPOINTS
        for d in CHECKPOINTS:
            assert os.path.exists(os.path.join(OUT, f"ltv_by_segment_{d}.json"))


@needs_db
class TestPersistence:
    def test_logging_is_idempotent_and_cites_the_proxy_hook_metrics(self, tmp_path, monkeypatch):
        path = tmp_path / "model_performance_history.csv"
        monkeypatch.setattr(mp, "_CSV_PATH", str(path))
        L.run_build_time_validation(date(2025, 12, 31), log=True, write_report=False)
        first = path.read_bytes()
        L.run_build_time_validation(date(2025, 12, 31), log=True, write_report=False)
        assert path.read_bytes() == first
        rows = mp.read_performance_history()
        assert {r["model_name"] for r in rows} == {"ltv_by_segment"}
        names = {r["metric_name"] for r in rows}
        from analytics import proxy_metric_health as pmh
        hook = next(h for h in pmh.DRIFT_HOOK_CATALOG if h["artifact"] == "ltv_by_segment")
        assert set(hook["persisted_metric_names"]) <= names
        assert {"ltv_central_usd_smb", "retention_month60_smb", "structural_checks_passed",
                "backtest_retention_max_abs_gap_pp_smb", "ltv_to_cac_entry_only_smb", "ltv_to_cac_entry_only_commercial",
                "ltv_to_cac_entry_only_enterprise", "ltv_to_cac_rep_loaded_commercial"} <= names
        vals = {r["metric_name"]: float(r["metric_value"]) for r in rows}
        assert vals["ltv_to_cac_entry_only_commercial"] < vals["ltv_to_cac_rep_loaded_commercial"] / 3
        assert vals["ltv_to_cac_entry_only_enterprise"] == vals["ltv_to_cac_rep_loaded_enterprise"]


@needs_db
class TestDashboardInterpreter:
    def test_the_python_312_pandas_3_environment_returns_the_same_reading(self, fresh):
        py = os.path.join(ROOT, "dashboard", ".venv", "bin", "python")
        if not os.path.exists(py):
            pytest.skip("dashboard/.venv not present")
        code = ("import sys, json; sys.path.insert(0, %r); from datetime import date; "
                "from analytics import ltv_by_segment as L; print(json.dumps(L.run_ltv(date(2025, 12, 31))))" % ROOT)
        out = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=300, check=True)
        _assert_equal_up_to_float_noise(json.loads(out.stdout.strip().splitlines()[-1]), json.loads(json.dumps(fresh["2025-12-31"])))


# --------------------------------------------------------------------------
# Mutation guards: the planted-answer scenarios must notice a wrong LTV formula
# --------------------------------------------------------------------------

class TestMutationGuards:
    EXACT = "exact_survival_times_growing_mrr_with_non_default_margin_and_rate"

    def _failed(self):
        out = L.run_synthetic_scenarios()
        return {s["name"] for s in out["scenarios"] if not s["passed"]}

    def test_unmutated_code_passes_every_scenario(self):
        assert self._failed() == set()

    def test_a_wrong_discount_exponent_is_caught(self, monkeypatch):
        monkeypatch.setattr(L, "discount_factors",
                            lambda H=L.HORIZON_MONTHS, annual_rate=L.ANNUAL_DISCOUNT_RATE: (1.0 + annual_rate) ** (-np.arange(H) / 11.0))
        failed = self._failed()
        assert self.EXACT in failed and "zero_churn_constant_mrr_equals_the_closed_form_discounted_sum" in failed

    def test_a_dropped_month_zero_is_caught(self, monkeypatch):
        orig = L.ltv_terms

        def mutated(S, m, *a, **k):
            t = np.array(orig(S, m, *a, **k))
            t[0] = 0.0
            return t
        monkeypatch.setattr(L, "ltv_terms", mutated)
        failed = self._failed()
        assert self.EXACT in failed and "zero_churn_constant_mrr_equals_the_closed_form_discounted_sum" in failed

    def test_a_wrong_margin_is_caught(self, monkeypatch):
        orig = L.ltv_terms
        monkeypatch.setattr(L, "ltv_terms", lambda S, m, margin=0.8, annual_rate=0.1, H=60: orig(S, m, 0.70, annual_rate, H))
        failed = self._failed()
        assert self.EXACT in failed and "non_default_margin_and_discount_rate_are_applied" in failed

    def test_a_one_age_misalignment_of_survival_and_mrr_is_caught(self, monkeypatch):
        orig = L.ltv_terms
        monkeypatch.setattr(L, "ltv_terms", lambda S, m, *a, **k: orig(np.asarray(S)[1:], m, *a, **k))
        assert self.EXACT in self._failed()


# --------------------------------------------------------------------------
# Channel revenue test, decision-grade rule, account-management cost sizing
# --------------------------------------------------------------------------

class TestMannWhitneyAndDecisionGrade:
    def test_mann_whitney_known_answer(self):
        t = L.mann_whitney([1, 2, 3], [4, 5, 6])
        assert t["u"] == 0 and t["p_value"] == pytest.approx(0.0495, abs=2e-4)

    def test_identical_samples_do_not_differ_and_the_test_is_symmetric(self):
        rng = np.random.default_rng(4)
        x, y = rng.lognormal(5, 1, 400), rng.lognormal(5, 1, 500)
        assert L.mann_whitney(x, y)["p_value"] > 0.05
        assert L.mann_whitney(x, y)["p_value"] == pytest.approx(L.mann_whitney(y, x)["p_value"])
        assert L.mann_whitney(x, y * 3)["p_value"] < 1e-6

    @pytest.mark.parametrize("grade,reps,loaded,post,rep_ok,mkt_ok", [
        ("point", False, True, 0.40, True, True),        # SMB-like with little graduation
        ("point", True, True, 0.40, True, False),        # reps are the cost: marketing-only never
        ("point", True, False, 0.40, False, False),      # reps exist, rep cost not loaded
        ("range", True, True, 0.10, False, False),
        ("directional", True, True, None, False, False),
        ("point", False, True, 0.60, False, False)])      # most of the value arrives after the move
    def test_decision_grade_rule(self, grade, reps, loaded, post, rep_ok, mkt_ok):
        d = L.decision_grade(grade, reps, loaded, post)
        assert d["rep_loaded"] is rep_ok and d["marketing_only"] is mkt_ok
        assert bool(d["unmet"]) == (not rep_ok)

    def test_netting_factor_formula(self):
        am = {"status": "present", "segments": {"Commercial": {"share_of_segment_revenue": 0.06},
                                                "Enterprise": {"share_of_segment_revenue": 0.04}}}
        assert L.am_netting_factor("Enterprise", 0.0, am) == pytest.approx((0.8 - 0.04) / 0.8)
        assert L.am_netting_factor("Commercial", 0.5, am) == pytest.approx((0.8 - (0.5 * 0.06 + 0.5 * 0.04)) / 0.8)
        assert L.am_netting_factor("SMB", 1.0, am) == pytest.approx((0.8 - 0.05) / 0.8)
        assert L.am_netting_factor("SMB", 0.5, {"status": "unavailable"}) is None


@needs_db
class TestGraduationChannelAndDecisionGradeOnTheMarts:
    def test_am_cost_is_a_small_share_of_revenue_and_does_not_explain_the_gap(self, fresh):
        r = fresh["2025-12-31"]
        am = r["am_cost_context"]["segments"]
        assert am["Commercial"]["share_of_segment_revenue"] == pytest.approx(0.0562, abs=5e-4)
        assert am["Enterprise"]["share_of_segment_revenue"] == pytest.approx(0.0545, abs=5e-4)
        assert am["Commercial"]["am_cost_usd"] == pytest.approx(1.672e6, rel=1e-3)
        com = _seg(r, "Commercial")
        rl = com["ltv_to_cac"]["rep_loaded"]
        assert rl["if_am_cost_netted"] == pytest.approx(6.5, abs=0.1)
        assert rl["if_am_cost_netted"] > 3 * rl["entry_segment_revenue_only"]
        g = com["graduation"]
        assert (g["accounts_moved_up"], g["accounts"]) == (38, 365) and g["share_of_accounts_moved_up"] == pytest.approx(0.104, abs=1e-3)
        assert "not that cost" in com["display"]["graduation"] and "6.5x" in com["display"]["graduation"]
        assert "not netted" not in com["display"]["summary"]

    def test_channel_revenue_is_tested_and_enterprise_is_stated_untested(self, fresh):
        r = fresh["2025-12-31"]
        t = r["channel_mrr_tests"]
        assert [x["age"] for x in t["SMB"]["rows"]] == [6, 12, 24, 36] and t["SMB"]["any_significant_at_5pct"] is False
        assert all(0.1 < x["p_value"] < 0.9 for x in t["SMB"]["rows"])
        assert t["Enterprise"]["status"] == "untested" and t["Commercial"]["status"] == "untested"
        f = r["channel_finding"]
        assert "no detectable difference in retention" in f and "absence of evidence" in f and "synthetic" in f
        assert "Enterprise is untested" in f and "3.9-point" in f and "settles" not in f

    def test_decision_grade_flags_follow_the_rule_and_smb_text_names_its_cac(self, fresh):
        r = fresh["2025-12-31"]
        for name in ("SMB", "Commercial", "Enterprise"):
            q = _seg(r, name)["ltv_to_cac"]
            grade = _seg(r, name)["evidence_grade"]
            has_reps = name != "SMB"
            post = None if name == "Enterprise" else _seg(r, name)["graduation"]["share_of_ltv_after_move"]
            d = L.decision_grade(grade, has_reps, True, post)
            assert q["rep_loaded_decision_grade"] is d["rep_loaded"] and q["marketing_only_decision_grade"] is d["marketing_only"]
            assert q["decision_grade_unmet_conditions"] == d["unmet"] and q["decision_grade_rule"] == L.DECISION_GRADE_RULE
        smb = _seg(r, "SMB")["display"]["ltv_to_cac"]
        assert "against marketing cost, which is the whole CAC for SMB" in smb and "rep-loaded" not in smb

    def test_the_am_cost_inputs_tie_to_the_facts(self, frames, con):
        cac = L.compute_cac(frames["accounts"], frames["spend"], frames["rep_cost"], frames["wins"])
        assert any(c["name"] == "am_cost_share_inputs_tie_to_the_facts" and c["passed"]
                   for c in L.validation_cac_inputs_tie(frames, cac, con))
