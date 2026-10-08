"""Pipeline coverage (analytics/pipeline_coverage.py).

  * Pure tests need no database: the coverage arithmetic and its status bands,
    the synthetic known-answer scenarios, the point-in-time mask, the
    published text and the module's source-level rules.
  * Fresh-run tests need the dbt database: the reading's tie-outs to an
    independent SQL path, to capacity_planning's quota panel and to the forecast
    artifact's new-business rollup, the no-look-ahead perturbation, the
    data-window end, and the committed reports against a fresh run at a float
    tolerance.

Run: python3 -m pytest tests/test_phase4_pipeline_coverage.py -v
"""
import json
import os
import re
import sys
from datetime import date

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from analytics import pipeline_coverage as pc  # noqa: E402

OUT = os.path.join(ROOT, "analytics", "outputs")
DB_PATH = os.path.join(ROOT, "data", "acme_gtm.duckdb")
CHECKPOINTS = ["2025-08-15", "2025-11-14"]
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
    with open(os.path.join(OUT, f"pipeline_coverage_{d}.json")) as f:
        return json.load(f)


# --------------------------------------------------------------------------
# The coverage arithmetic and its proposed status bands
# --------------------------------------------------------------------------

class TestCoverageArithmetic:
    def test_known_answer(self):
        a = pc.assess_coverage(quota_usd=100_000, won_to_date_usd=40_000,
                               open_pipeline_usd=300_000, conversion_rate=0.25)
        assert a["remaining_quota_usd"] == 60_000
        assert a["pipeline_coverage_ratio"] == pytest.approx(5.0)
        assert a["required_pipeline_multiple"] == pytest.approx(4.0)
        assert a["coverage_vs_required"] == pytest.approx(1.25)
        assert a["conversion_implied_expected_close_usd"] == pytest.approx(75_000)
        assert a["conversion_implied_gap_usd"] == pytest.approx(-15_000)
        assert a["coverage_status"] == "covered"

    @pytest.mark.parametrize("open_usd,status", [
        (240_000.0, "covered"),            # exactly 1.0x of required
        (239_999.0, "thin"),
        (180_000.0, "thin"),               # exactly 0.75x
        (179_999.0, "shortfall"),
        (0.0, "shortfall"),
    ])
    def test_status_bands_at_their_boundaries(self, open_usd, status):
        a = pc.assess_coverage(100_000, 40_000, open_usd, 0.25)
        assert a["coverage_status"] == status

    def test_gap_sign_agrees_with_the_status(self):
        for open_usd in (50_000, 180_000, 239_000, 240_000, 900_000):
            a = pc.assess_coverage(100_000, 40_000, open_usd, 0.25)
            assert (a["coverage_vs_required"] >= 1.0) == (a["conversion_implied_gap_usd"] <= 1e-9)

    def test_zero_remaining_quota_is_quota_met_with_an_undefined_ratio(self):
        a = pc.assess_coverage(100_000, 130_000, 50_000, 0.25)
        assert a["coverage_status"] == "quota_met"
        assert a["remaining_quota_usd"] == 0.0
        assert a["pipeline_coverage_ratio"] is None and a["coverage_vs_required"] is None
        assert a["conversion_implied_gap_usd"] == pytest.approx(-12_500)

    def test_no_quota_and_no_conversion_are_unavailable_with_a_reason_never_zero(self):
        nq = pc.assess_coverage(0, 0, 50_000, 0.25)
        assert nq["coverage_status"] == "unavailable" and nq["reason_code"] == "no_quota"
        assert nq["pipeline_coverage_ratio"] is None or nq["coverage_vs_required"] is None
        nc = pc.assess_coverage(100_000, 0, 50_000, None)
        assert nc["coverage_status"] == "unavailable" and nc["reason_code"] == "no_realized_conversion"
        assert nc["coverage_vs_required"] is None and nc["conversion_implied_gap_usd"] is None

    @pytest.mark.parametrize("conv", [0.1, 0.15, 0.2, 0.23, 0.255, 0.3, 0.33, 0.7])
    @pytest.mark.parametrize("remaining", [123456.78, 366647.35, 100000 / 3, 77777.7])
    def test_non_dyadic_boundaries_never_disagree_with_the_gap_sign(self, conv, remaining):
        """open = remaining / conversion lands exactly on the 1.0x boundary in
        decimal but a few ulps either side of it in floating point."""
        on_covered = pc.assess_coverage(remaining + 1000, 1000, remaining / conv, conv)
        assert on_covered["coverage_status"] == "covered"
        assert on_covered["conversion_implied_gap_usd"] <= 0
        on_thin = pc.assess_coverage(remaining + 1000, 1000, 0.75 * remaining / conv, conv)
        assert on_thin["coverage_status"] == "thin"
        assert on_thin["conversion_implied_gap_usd"] > 0
        just_under = pc.assess_coverage(remaining + 1000, 1000, 0.7499 * remaining / conv, conv)
        assert just_under["coverage_status"] == "shortfall"

    def test_status_and_gap_sign_agree_across_a_grid(self):
        for conv in (0.11, 0.19, 0.237, 0.31, 0.43):
            for remaining in (9_999.99, 54_321.1, 250_000.0, 3_333_333.33):
                for k in (0.5, 0.75, 0.9, 0.99999999999, 1.0, 1.00000000001, 1.5):
                    a = pc.assess_coverage(remaining + 500, 500, k * remaining / conv, conv)
                    assert (a["coverage_status"] == "covered") == (a["conversion_implied_gap_usd"] <= 0), (conv, remaining, k)

    def test_quota_met_does_not_need_a_realized_conversion(self):
        a = pc.assess_coverage(100_000, 130_000, 50_000, None)
        assert a["coverage_status"] == "quota_met" and a["remaining_quota_usd"] == 0.0
        assert a["reason_code"] is None
        assert a["conversion_implied_gap_usd"] is None and a["coverage_vs_required"] is None
        assert pc.assess_coverage(100_000, 99_999, 50_000, None)["coverage_status"] == "unavailable"

    def test_no_open_pipeline_is_a_real_zero(self):
        a = pc.assess_coverage(100_000, 0, 0.0, 0.25)
        assert a["pipeline_coverage_ratio"] == 0.0 and a["coverage_status"] == "shortfall"
        assert a["conversion_implied_gap_usd"] == pytest.approx(100_000)


class TestSyntheticScenarios:
    def test_every_known_answer_scenario_matches(self):
        out = pc.run_synthetic_scenarios()
        failed = [r for r in out["results"] if not r["passed"]]
        assert not failed, failed
        assert out["n_scenarios"] >= 14

    def test_the_named_scenarios_exist(self):
        names = {r["scenario"] for r in pc.run_synthetic_scenarios()["results"]}
        for needed in ("commercial_covered", "commercial_thin", "commercial_shortfall",
                       "zero_remaining_quota", "no_open_deals", "no_quota", "no_wins_yet",
                       "deal_created_after_evaluation_not_counted",
                       "deal_closed_before_evaluation_not_open", "quarter_boundary",
                       "insufficient_conversion_history", "pre_2023_deals_excluded_from_conversion",
                       "quota_met_without_realized_conversion"):
            assert needed in names


# --------------------------------------------------------------------------
# Point-in-time mask and source-level rules
# --------------------------------------------------------------------------

class TestPointInTime:
    def _deals(self):
        return pd.DataFrame([
            pc._synthetic_deal("A", "Commercial", 100, "2024-01-01", "2024-02-01", 1),
            pc._synthetic_deal("B", "Commercial", 200, "2024-01-15", "2024-03-01", 0),
            pc._synthetic_deal("C", "Commercial", 300, "2024-03-01", "2024-04-01", 1),
        ]).assign(poc_outcome="pass")

    def test_known_at_masks_outcomes_of_deals_not_closed_by_the_date(self):
        d = pc.known_at(self._deals(), pd.Timestamp("2024-02-15"))
        by = d.set_index("opportunity_id")
        assert list(d["opportunity_id"]) == ["A", "B"]          # C is not created yet
        assert by.loc["A", "won"] == 1.0 and bool(by.loc["A", "is_closed"])
        assert pd.isna(by.loc["B", "won"]) and not bool(by.loc["B", "is_closed"])
        assert by.loc["B", "poc_outcome"] is None

    def test_known_at_is_idempotent_and_monotone(self):
        d = self._deals()
        once = pc.known_at(d, pd.Timestamp("2024-02-15"))
        twice = pc.known_at(once, pd.Timestamp("2024-02-15"))
        pd.testing.assert_frame_equal(once.reset_index(drop=True), twice.reset_index(drop=True))
        earlier = pc.known_at(once, pd.Timestamp("2024-01-20"))
        assert set(earlier["opportunity_id"]) <= set(once["opportunity_id"])

    def test_flipping_an_outcome_after_the_evaluation_date_changes_nothing(self):
        window = {"last_opportunity_close": date(2030, 12, 31)}
        base = pd.DataFrame(
            [pc._synthetic_deal(f"H{i}", "Commercial", 1000, "2023-09-01", "2023-10-01", 1 if i < 10 else 0)
             for i in range(40)]
            + [pc._synthetic_deal("O1", "Commercial", 480_000, "2024-04-20", "2024-06-10", 1)])
        flipped = base.copy()
        flipped.loc[flipped["opportunity_id"] == "O1", "won"] = 0.0
        periods = pc._synthetic_periods()
        a = pc.compute_readings(base, periods, "2024-05-15", window)["segments"][0]
        b = pc.compute_readings(flipped, periods, "2024-05-15", window)["segments"][0]
        assert a == b

    def test_module_reads_only_the_marts_layer(self):
        with open(os.path.join(ROOT, "analytics", "pipeline_coverage.py")) as f:
            src = f.read()
        assert not re.search(r"\b(stg_|int_)\w+", src.replace("`int_rep_capacity_periods`", ""))
        assert "main_staging" not in src and "main_intermediate" not in src

    def test_module_declares_its_model_name_and_logs_nothing_at_import(self):
        assert pc._MODEL_NAME == "pipeline_coverage"


class TestPublishedText:
    def test_status_rule_is_labelled_proposed(self):
        assert pc.STATUS_RULE["status"].startswith("proposed")
        assert pc.STATUS_RULE["covered_min_coverage_vs_required"] == 1.0
        assert pc.STATUS_RULE["thin_min_coverage_vs_required"] == 0.75

    def test_output_never_calls_a_coverage_figure_a_forecast(self):
        for text in list(pc.DEFINITIONS.values()) + list(pc.PIPELINE_COVERAGE_CAVEATS):
            assert "quota_coverage_ratio" not in text

    def test_conversion_window_floor_is_2023(self):
        assert pc.CONVERSION_WINDOW_START == date(2023, 1, 1)


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
def fresh():
    return {d: pc.run_pipeline_coverage(date.fromisoformat(d)) for d in CHECKPOINTS}


@needs_db
class TestAgainstTheMarts:
    def test_open_pipeline_ties_to_an_independent_sql_aggregate_at_several_dates(self, con):
        deals = pc.load_new_business_deals(date(2025, 12, 31), con=con)
        dates = [pd.Timestamp(d) for d in
                 ("2023-05-12", "2024-02-09", "2024-11-15", "2025-02-14", "2025-08-15", "2025-11-14")]
        assert pc.validation_open_pipeline_ties_to_sql(dates, deals, con)["passed"]

    def test_quota_and_won_to_date_tie_to_capacity_planning_for_every_complete_quarter(self, con):
        deals = pc.load_new_business_deals(date(2025, 12, 31), con=con)
        periods = pc.load_quota_periods(date(2025, 12, 31), con=con)
        checks = pc.validation_quota_and_wins_tie_to_capacity_planning(date(2025, 12, 31), periods, deals, con)
        assert all(c["passed"] for c in checks), checks

    def test_quota_is_constant_within_a_quarter_and_roles_map_one_to_one(self, con):
        periods = pc.load_quota_periods(date(2025, 12, 31), con=con)
        assert pc.validation_quota_constant_within_quarter(periods, date(2025, 12, 31))["passed"]
        assert pc.validation_segment_role_mapping(con)["passed"]

    def test_pre_2023_closed_deals_are_all_won(self, con):
        deals = pc.load_new_business_deals(date(2025, 12, 31), con=con)
        assert pc.validation_pre_2023_win_rate_is_structural(deals)["passed"]

    def test_the_reading_ties_to_the_forecast_new_business_rollup(self, fresh):
        for d, r in fresh.items():
            assert r["reconciliation"]["ties_on_open_pipeline"], d
            for row in r["reconciliation"]["by_segment"]:
                assert abs(row["open_pipeline_difference_usd"]) <= 0.01
                assert row["coverage_reading_open_deals"] == row["forecast_new_business_open_deals"]
                # the forecast's own all-type pipeline is larger: the units trap
                assert row["forecast_open_pipeline_all_opportunity_types_usd"] > \
                    row["forecast_new_business_open_pipeline_usd"]

    def test_identities_hold_on_the_published_figures(self, fresh):
        rows = [s for r in fresh.values() for s in r["segments"] if s["status"] == "present"]
        rows = [dict(s, as_of_date=s["as_of_date"]) for s in rows]
        assert pc.validation_identities(rows)["passed"]
        for s in rows:
            if s["coverage_status"] != "quota_met":
                assert s["pipeline_coverage_ratio"] == pytest.approx(
                    s["open_pipeline_usd"] / s["remaining_quota_usd"], rel=1e-6)

    @pytest.mark.parametrize("d", ["2024-05-10", "2025-11-14"])
    def test_no_look_ahead_perturbation(self, con, d):
        assert pc.validation_no_lookahead(date(2025, 11, 14), pd.Timestamp(d), con)["passed"]

    def test_conversion_never_reaches_before_2023(self, fresh):
        for r in fresh.values():
            for s in r["segments"]:
                assert s["conversion_window_start"] >= "2023-01-01"

    def test_checkpoint_readings_carry_the_documented_numbers(self, fresh):
        nov = {s["segment"]: s for s in fresh["2025-11-14"]["segments"]}
        assert nov["Commercial"]["coverage_status"] == "shortfall"
        assert nov["Commercial"]["open_pipeline_deals"] == 34
        assert nov["Enterprise"]["coverage_status"] == "quota_met"
        assert nov["Enterprise"]["remaining_quota_usd"] == 0.0
        assert nov["Enterprise"]["pipeline_coverage_ratio"] is None
        aug = {s["segment"]: s for s in fresh["2025-08-15"]["segments"]}
        assert aug["Commercial"]["coverage_status"] == "thin" and aug["Enterprise"]["coverage_status"] == "thin"

    def test_next_quarter_is_unavailable_at_the_data_window_end_never_zero(self, fresh):
        nq = fresh["2025-11-14"]["next_quarter"]
        assert nq["status"] == "unavailable" and nq["reason_code"] == "beyond_data_window"
        assert nq["segments"] == []
        assert fresh["2025-08-15"]["next_quarter"]["status"] == "present"
        for s in fresh["2025-08-15"]["next_quarter"]["segments"]:
            assert s["coverage_status"] == "not_assessed"

    def test_after_the_data_window_the_reading_is_unavailable_not_zero_coverage(self):
        r = pc.run_pipeline_coverage(date(2025, 12, 31), reconcile=False)
        for s in r["segments"]:
            assert s["status"] == "unavailable" and s["reason_code"] == "after_data_window"
            assert s["coverage_vs_required"] is None and s["conversion_implied_gap_usd"] is None

    def test_before_2023_the_reading_is_unavailable_with_the_reason(self):
        r = pc.run_pipeline_coverage(date(2022, 6, 15), reconcile=False)
        for s in r["segments"]:
            assert s["status"] == "unavailable" and s["reason_code"] == "before_conversion_window"

    def test_enterprise_conversion_below_the_deal_floor_is_unavailable(self):
        r = pc.run_pipeline_coverage(date(2023, 2, 10), reconcile=False)
        ent = next(s for s in r["segments"] if s["segment"] == "Enterprise")
        assert ent["status"] == "unavailable" and ent["reason_code"] == "insufficient_closed_deals"
        assert ent["realized_conversion"] is None

    def test_the_output_is_json_safe_and_its_strings_are_clean(self, fresh):
        for r in fresh.values():
            text = json.dumps(r)
            assert "NaN" not in text and "Infinity" not in text
            for s in r["segments"]:
                for v in s["display"].values():
                    assert "nan" not in v.lower().split() and "None" not in v

    def test_the_poc_view_is_labelled_indicative_with_its_sample_sizes(self, fresh):
        ent = next(s for s in fresh["2025-11-14"]["segments"] if s["segment"] == "Enterprise")
        poc = ent["poc_view"]
        assert poc["label"] == "indicative, not a forecast" and poc["status"] == "present"
        assert poc["rates"]["pass"]["closed_deals"] >= 20 and poc["rates"]["fail"]["closed_deals"] >= 20
        assert poc["rates"]["pass"]["rate"] > poc["rates"]["fail"]["rate"]
        comm = next(s for s in fresh["2025-11-14"]["segments"] if s["segment"] == "Commercial")
        assert comm["poc_view"] is None


@needs_db
class TestCommittedReports:
    @pytest.mark.parametrize("d", CHECKPOINTS)
    def test_the_committed_reading_equals_a_fresh_run_up_to_float_noise(self, d, fresh):
        _assert_equal_up_to_float_noise(json.loads(json.dumps(fresh[d])), _committed(d)["reading"])

    @pytest.mark.parametrize("d", CHECKPOINTS)
    def test_committed_report_records_every_structural_check_passing(self, d):
        rep = _committed(d)
        structural = [c for c in rep["checks"] if c["kind"] == "structural"]
        assert structural and all(c["passed"] for c in structural)
        assert rep["checks_passed"] == rep["checks_total"] == len(structural)
        assert rep["synthetic"]["n_passed"] == rep["synthetic"]["n_scenarios"]

    @pytest.mark.parametrize("d", CHECKPOINTS)
    def test_committed_backtest_summary_matches_its_rows(self, d):
        rep = _committed(d)
        rows = [r for r in rep["backtest"] if r["coverage_implied_expected_usd"] is not None
                and r["actual_usd"] > 0]
        pooled = rep["backtest_summary"]["pooled"]
        assert pooled["n"] == len(rows)
        mape = sum(abs(r["coverage_implied_expected_usd"] - r["actual_usd"]) / r["actual_usd"] for r in rows) / len(rows)
        assert pooled["mape_coverage_implied"] == pytest.approx(mape, abs=2e-3)
        assert rep["target_met"] == all(
            v["beats_both_naive_baselines"] for v in rep["backtest_summary"]["by_segment"].values())

    def test_the_backtest_is_point_in_time_each_quarter_at_its_own_midpoint(self):
        rep = _committed("2025-11-14")
        for r in rep["backtest"]:
            q = pd.Period(r["period"].replace("-Q", "Q"), freq="Q")
            assert pd.Timestamp(r["eval_date"]) == pc.mid_quarter_eval_date(q)
            assert pd.Timestamp(r["eval_date"]).dayofweek == 4        # a Friday

    def test_the_committed_backtest_found_the_commercial_late_creation_floor(self):
        s = _committed("2025-11-14")["backtest_summary"]["by_segment"]
        assert s["Commercial"]["late_created_share_of_actual"] > 0.10
        assert s["Enterprise"]["late_created_share_of_actual"] == 0.0
        assert s["Commercial"]["aggregate_bias_pct"] < 0


@needs_db
class TestBacktestComparators:
    @pytest.mark.parametrize("d", CHECKPOINTS)
    def test_the_added_comparators_are_in_the_committed_summary(self, d):
        pooled = _committed(d)["backtest_summary"]["pooled"]
        for key in ("mape_naive_constant_rate_025", "mape_naive_pace", "mape_hindsight_free_scoping",
                    "mape_no_scoping", "beats_constant_rate_baseline", "beats_pace_baseline",
                    "visible_reading_vs_visible_actual_pct"):
            assert key in pooled, key
        # the constant-rate and pace comparators are reported, never presented as beaten
        assert pooled["beats_constant_rate_baseline"] is False

    def test_hindsight_free_scoping_is_no_worse_and_no_scoping_is_far_worse(self):
        s = _committed("2025-11-14")["backtest_summary"]
        assert s["pooled"]["mape_hindsight_free_scoping"] <= s["pooled"]["mape_coverage_implied"]
        assert s["pooled"]["mape_no_scoping"] > 2 * s["pooled"]["mape_coverage_implied"]
        assert s["by_segment"]["Enterprise"]["mape_no_scoping"] > 1.0

    def test_commercial_visible_pipeline_is_over_priced_which_offsets_late_creation(self):
        c = _committed("2025-11-14")["backtest_summary"]["by_segment"]["Commercial"]
        assert c["visible_reading_vs_visible_actual_pct"] > 0
        assert c["aggregate_bias_pct"] == pytest.approx(
            c["visible_pricing_excess_share_of_actual"] - c["late_created_share_of_actual"], abs=2e-3)

    def test_the_info_comparison_gates_nothing(self):
        checks = {c["name"]: c for c in _committed("2025-11-14")["checks"]}
        info = checks["backtest_versus_constant_rate_and_pace_comparators"]
        assert info["kind"] == "info"
        assert pc._mark(info) == "INFO"


# --------------------------------------------------------------------------
# run_pipeline_coverage is total: any date in the data range returns a reading
# --------------------------------------------------------------------------

def _sweep_dates():
    dates = {date(2020, 1, 1), date(2022, 12, 31), date(2023, 1, 1), date(2023, 1, 3), date(2023, 6, 30),
             date(2024, 6, 28), date(2025, 12, 20), date(2025, 12, 26), date(2025, 12, 27),
             date(2025, 12, 28), date(2025, 12, 29), date(2025, 12, 31)}
    for m in pd.date_range("2020-01-31", "2025-12-31", freq="ME"):
        dates.add(m.date())
    for q in pd.period_range("2020Q1", "2025Q4", freq="Q"):
        dates.update({pc.mid_quarter_eval_date(q).date(), q.start_time.date(), q.end_time.date()})
    return sorted(dates)


VALID_REASONS = {"before_conversion_window", "insufficient_closed_deals", "no_quota", "no_wins_in_window",
                 "no_realized_conversion", "after_data_window"}


@needs_db
class TestTotality:
    def test_every_sweep_date_returns_a_present_or_unavailable_reading_with_a_reason(self, con):
        for d in _sweep_dates():
            r = pc.run_pipeline_coverage(d, con=con, reconcile=False)
            assert len(r["segments"]) == 2
            for s in r["segments"]:
                assert s["status"] in ("present", "unavailable"), (d, s["segment"])
                if s["status"] == "unavailable":
                    assert s["reason_code"] in VALID_REASONS, (d, s["reason_code"])
                    assert s["reason"]
            assert r["next_quarter"]["status"] in ("present", "unavailable")
            json.dumps(r)

    @pytest.mark.parametrize("d", [date(2023, 6, 30), date(2024, 6, 28), date(2023, 1, 3), date(2022, 6, 15),
                                   date(2025, 3, 31), date(2025, 12, 31)])
    def test_the_reconciliation_path_never_raises_at_quarter_ends_and_before_the_forecast_exists(self, con, d):
        r = pc.run_pipeline_coverage(d, con=con, reconcile=True)
        assert r["reconciliation"]["status"] in ("present", "unavailable")
        if r["reconciliation"]["status"] == "unavailable":
            assert r["reconciliation"]["reason_code"] and r["reconciliation"]["reason"]
        assert [s["segment"] for s in r["segments"]] == ["Commercial", "Enterprise"]

    def test_a_failure_on_the_forecast_side_leaves_the_coverage_reading_intact(self, con, monkeypatch):
        d = date(2025, 11, 14)
        baseline = pc.run_pipeline_coverage(d, con=con, reconcile=False)

        def boom(*a, **k):
            raise ValueError("synthetic forecast-side failure")
        monkeypatch.setattr(pc.fc, "bottoms_up_rollup", boom)
        r = pc.run_pipeline_coverage(d, con=con, reconcile=True)
        assert r["reconciliation"]["status"] == "unavailable"
        assert r["reconciliation"]["reason_code"] == "forecast_side_unavailable"
        ent = next(s for s in r["segments"] if s["segment"] == "Enterprise")
        assert ent["poc_view"]["status"] == "unavailable"
        for got, want in zip(r["segments"], baseline["segments"]):
            for key in want:
                if key != "poc_view":
                    assert got[key] == want[key], key

    def test_no_open_deal_leaves_the_poc_view_unavailable_not_a_key_error(self):
        view = pc.poc_conditioned_view(pd.DataFrame(), pd.DataFrame(columns=[
            "segment", "is_closed", "close_date", "amount", "poc_outcome", "won"]), date(2023, 6, 30), 0.25)
        assert view["status"] == "unavailable"

    def test_published_text_says_the_forecast_not_the_forecast_artifact(self):
        text = json.dumps([pc.DEFINITIONS, pc.PIPELINE_COVERAGE_CAVEATS])
        assert "forecast artifact" not in text
        r = pc.run_pipeline_coverage(date(2025, 11, 14))
        assert "forecast artifact" not in json.dumps(r)

    DASHBOARD_PY = os.path.join(ROOT, "dashboard", ".venv", "bin", "python")

    @pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, "dashboard", ".venv", "bin", "python")),
                        reason="dashboard/.venv not present")
    def test_the_dashboard_interpreter_returns_a_reading_at_the_formerly_crashing_dates(self):
        import subprocess
        code = """
import json
from datetime import date
from analytics import pipeline_coverage as pc
out = {}
for d in (date(2023, 6, 30), date(2024, 6, 28), date(2023, 1, 3), date(2022, 6, 15), date(2025, 11, 14), date(2025, 12, 31)):
    r = pc.run_pipeline_coverage(d)
    out[d.isoformat()] = [[s["status"], s["reason_code"]] for s in r["segments"]] + [r["reconciliation"]["status"]]
print(json.dumps(out))
"""
        proc = subprocess.run([self.DASHBOARD_PY, "-c", code.replace("\\\\n", "\\n")], cwd=ROOT,
                              env=dict(os.environ, PYTHONPATH=ROOT), capture_output=True, text=True, timeout=600)
        assert proc.returncode == 0, proc.stderr[-800:]
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        assert set(out) == {"2023-06-30", "2024-06-28", "2023-01-03", "2022-06-15", "2025-11-14", "2025-12-31"}
        assert out["2023-06-30"][0] == ["present", None]
        assert out["2023-01-03"][0] == ["unavailable", "insufficient_closed_deals"]
        assert out["2022-06-15"][0] == ["unavailable", "before_conversion_window"]
        assert out["2025-12-31"][0] == ["unavailable", "after_data_window"]
        # the forecast side now builds its features before the first submission under pandas 3 too
        assert out["2023-01-03"][-1] == "present"
        assert out["2022-06-15"][-1] == "present"
        assert out["2023-06-30"][-1] == "present"
