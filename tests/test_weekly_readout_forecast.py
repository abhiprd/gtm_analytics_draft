"""The weekly readout's forecast section (analytics/weekly_readout.py).

Three kinds of test live here, and the split matters:

  * JSON-only tests read the two committed readouts
    (analytics/outputs/weekly_readout_2025-06-30.json and 2025-11-30.json)
    and need no database: the section's contract, its rendering, and the
    executive-summary validator's handling of it.
  * Fresh-run tests (marked by the `fresh` fixtures) build the section from
    analytics/forecast.py against the dbt database and compare it with a
    second, independent run of that artifact. They compare a section built
    now with a run made now, never the committed JSON with a run made now,
    so a dbt rebuild's float noise cannot fail them. They run in the
    qa_marts gate, which has the database.
  * Selection tests exercise the as-of rule, including the two
    `unavailable` paths.
"""
import copy
import json
import os
import sys
from datetime import date, timedelta

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics import executive_summary as es  # noqa: E402
from analytics import forecast as fc  # noqa: E402
from analytics import weekly_readout as wr  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "analytics", "outputs")
DATES = ["2025-06-30", "2025-11-30"]


def _load(d):
    with open(os.path.join(OUT, "weekly_readout_%s.json" % d)) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def readouts():
    return {d: _load(d) for d in DATES}


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv(es.API_KEY_ENV, raising=False)


@pytest.fixture(scope="module")
def fresh_nov():
    """The section for the 2025-11-30 readout, built now from the forecast artifact."""
    return wr._forecast_section(date(2025, 11, 30))


def _unavailable_readout(readout, section):
    r = copy.deepcopy(readout)
    r["forecast"] = section
    return r


# --------------------------------------------------------------------------
# The committed readouts carry a real, traced section
# --------------------------------------------------------------------------

class TestCommittedSection:
    @pytest.mark.parametrize("d", DATES)
    def test_forecast_is_present_not_a_placeholder(self, readouts, d):
        f = readouts[d]["forecast"]
        assert f["status"] == "present"
        assert "not_yet_built" not in json.dumps(f)
        assert "reason" not in f and "detail" not in f

    @pytest.mark.parametrize("d", DATES)
    def test_contract_keys(self, readouts, d):
        f = readouts[d]["forecast"]
        assert set(f) == {
            "status", "forecast_as_of_date", "period", "call_to_quarter_end_days", "grain",
            "selection", "lens_labels", "lens_definitions", "segments",
            "segments_without_open_deals", "divergence_threshold",
            "divergence_threshold_status", "ml_lens", "plan_comparison",
            "data_window_note", "caveats", "note"}
        assert set(f["lens_labels"]) == {"bottoms_up_rep", "bottoms_up_manager", "ml",
                                         "cro_adjusted"}
        assert set(f["selection"]) == {"rule", "reporting_period_end", "forecast_call_date",
                                       "call_cadence"}

    @pytest.mark.parametrize("d", DATES)
    def test_every_segment_row_carries_all_four_lenses_and_the_artifacts_flag(self, readouts, d):
        for r in readouts[d]["forecast"]["segments"]:
            assert r["segment"] in ("Commercial", "Enterprise")
            for lens in ("bottoms_up_rep", "bottoms_up_manager", "ml", "cro_adjusted"):
                assert isinstance(r[lens], float)
                assert r[lens + "_display"].startswith("$")
            assert isinstance(r["diverges_materially"], bool)
            assert r["lenses_computable"] == 4
            assert r["widest_pair"] and r["widest_pair_display"]

    def test_november_selects_the_last_friday_call_of_the_month(self, readouts):
        f = readouts["2025-11-30"]["forecast"]
        assert f["forecast_as_of_date"] == "2025-11-28"
        assert date.fromisoformat(f["forecast_as_of_date"]).weekday() == 4  # a Friday
        assert f["period"] == "2025-Q4"
        assert f["call_to_quarter_end_days"] == 33
        assert f["selection"]["reporting_period_end"] == "2025-11-30"
        assert [r["segment"] for r in f["segments"]] == ["Commercial", "Enterprise"]
        assert f["segments_without_open_deals"] == []

    def test_june_is_a_quarter_end_call_and_says_so(self, readouts):
        f = readouts["2025-06-30"]["forecast"]
        assert f["forecast_as_of_date"] == "2025-06-27"
        assert f["period"] == "2025-Q2"
        assert f["call_to_quarter_end_days"] == 3
        assert [r["segment"] for r in f["segments"]] == ["Commercial"]
        assert f["segments_without_open_deals"] == ["Enterprise"]
        r = f["segments"][0]
        assert r["open_deals"] == 2
        # the late-quarter CRO override swamps a nearly exhausted pipeline; the
        # artifact's own flag fires and the caveat explaining it is carried
        assert r["diverges_materially"] is True and r["cro_adjusted"] > r["open_pipeline_amount"]
        assert any("final days" in c for c in f["caveats"])

    @pytest.mark.parametrize("d", DATES)
    def test_the_forecast_call_is_never_after_the_period_end(self, readouts, d):
        r = readouts[d]
        assert r["forecast"]["forecast_as_of_date"] <= r["header"]["reporting_period_end"]

    @pytest.mark.parametrize("d", DATES)
    def test_caveats_threshold_and_plan_statement_are_the_artifacts_own(self, readouts, d):
        f = readouts[d]["forecast"]
        assert f["caveats"] == list(fc.FORECAST_CAVEATS)
        assert f["divergence_threshold"] == fc._DIVERGENCE_THRESHOLD == 0.25
        assert "proposed, not yet confirmed" in f["divergence_threshold_status"]
        assert f["lens_definitions"] == fc.LENS_DEFINITIONS
        assert f["plan_comparison"]["status"] == "not_available"
        assert "No plan or quota" in f["plan_comparison"]["reason"]

    @pytest.mark.parametrize("d", DATES)
    def test_ml_lens_context_is_carried_with_its_target_and_baseline(self, readouts, d):
        ml = readouts[d]["forecast"]["ml_lens"]
        assert ml["computable"] is True
        assert ml["auc_target_range"] == [0.70, 0.85]
        assert ml["n_train"] > 0 and ml["n_test"] > 0
        assert ml["auc_ratio_vs_leak_proof_baseline"] == pytest.approx(
            ml["auc_holdout"] / ml["manager_lookup_baseline_auc"])
        assert ml["calibration_gap_target"] == 0.05

    def test_junes_ml_ceiling_breach_is_reported_not_hidden(self, readouts):
        ml = readouts["2025-06-30"]["forecast"]["ml_lens"]
        assert ml["meets_auc_target"] is False and ml["ml_targets_passed"] is False

    @pytest.mark.parametrize("d", DATES)
    def test_provenance_names_the_forecast_artifact(self, readouts, d):
        src = {s["section"]: s for s in readouts[d]["provenance"]["sources"]}
        assert src["forecast"]["artifact"] == "analytics/forecast.py"
        assert "run_forecast" in src["forecast"]["entry_point"]
        assert "playbook_triggers" in src

    @pytest.mark.parametrize("d", DATES)
    def test_the_summary_slot_is_unchanged_in_behaviour(self, readouts, d):
        s = readouts[d]["executive_summary"]
        assert s["status"] == "not_generated" and s["reason"] in ("no_api_key",
                                                                 "stale_summary_no_api_key")
        assert s["statements"] == [] and s["prompt_version"] == es.PROMPT_VERSION
        assert s["input_hash"] == es.compute_input_hash(readouts[d])


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

class TestRendering:
    @pytest.mark.parametrize("d", DATES)
    def test_committed_markdown_matches_its_structured_payload(self, readouts, d):
        md = wr.render_markdown(readouts[d])
        checks = {c["name"]: c for c in wr.verify_rendered_document(md, readouts[d])}
        for name in ("forecast_section_rendered_per_status",
                     "forecast_rendered_values_match_structured_payload"):
            assert checks[name]["passed"], checks[name]["detail"]
        assert all(c["passed"] for c in checks.values()), \
            [c for c in checks.values() if not c["passed"]]

    @pytest.mark.parametrize("d", DATES)
    def test_committed_file_is_the_current_rendering(self, readouts, d):
        with open(os.path.join(OUT, "weekly_readout_%s.md" % d)) as f:
            assert f.read() == wr.render_markdown(readouts[d])

    def test_the_rendered_section_shows_call_date_lenses_caveats_and_no_plan_claim(self, readouts):
        md = wr.render_markdown(readouts["2025-11-30"])
        sec = md.split("## Forecast")[1].split("## Watchlist")[0]
        r = readouts["2025-11-30"]["forecast"]["segments"][0]
        assert "**Forecast call:** 2025-11-28" in sec and "covering 2025-Q4" in sec
        assert r["bottoms_up_manager_display"] in sec and r["cro_adjusted_display"] in sec
        assert "Versus plan or quota:** not available" in sec
        assert "Forecast caveats:" in sec and "not_yet_built" not in md
        assert "$-" not in sec  # negative overrides render as -$183.9K, not $-183.9K

    def test_a_wrong_rendered_lens_value_is_caught(self, readouts):
        r = copy.deepcopy(readouts["2025-11-30"])
        md = wr.render_markdown(r)
        r["forecast"]["segments"][0]["bottoms_up_manager_display"] = "$9.99M"
        checks = {c["name"]: c for c in wr.verify_rendered_document(md, r)}
        assert not checks["forecast_rendered_values_match_structured_payload"]["passed"]

    def test_a_dropped_caveat_is_caught(self, readouts):
        r = copy.deepcopy(readouts["2025-11-30"])
        md = wr.render_markdown(r).replace("- " + r["forecast"]["caveats"][1], "")
        checks = {c["name"]: c for c in wr.verify_rendered_document(md, r)}
        assert not checks["forecast_rendered_values_match_structured_payload"]["passed"]

    def test_a_missing_forecast_heading_is_caught(self, readouts):
        r = copy.deepcopy(readouts["2025-11-30"])
        md = wr.render_markdown(r).replace("## Forecast", "## Outlook")
        checks = {c["name"]: c for c in wr.verify_rendered_document(md, r)}
        assert not checks["forecast_section_rendered_per_status"]["passed"]


# --------------------------------------------------------------------------
# As-of selection and the two unavailable paths
# --------------------------------------------------------------------------

class TestSelection:
    def test_latest_call_is_on_or_before_the_date_and_a_friday(self):
        assert fc.latest_forecast_call_date(date(2025, 11, 28)) == date(2025, 11, 28)
        assert fc.latest_forecast_call_date(date(2025, 11, 29)) == date(2025, 11, 28)
        assert fc.latest_forecast_call_date(date(2025, 11, 27)) == date(2025, 11, 21)
        assert fc.latest_forecast_call_date(date(2025, 11, 30)).weekday() == 4

    def test_no_call_before_the_first_snapshot(self):
        assert fc.latest_forecast_call_date(date(2022, 12, 31)) is None

    def test_a_mid_month_as_of_selects_from_the_evaluation_month_end_not_the_as_of(self):
        # as_of 2025-11-14 evaluates October, whose last call is 2025-10-31; the section
        # must be anchored to that period end, so nothing after it is read
        sec = wr._forecast_section(date(2025, 10, 31))
        assert sec["status"] == "present" and sec["forecast_as_of_date"] == "2025-10-31"
        assert sec["period"] == "2025-Q4"

    def test_no_call_available_is_unavailable_with_a_specific_reason(self):
        sec = wr._forecast_section(date(2023, 1, 5))
        assert sec["status"] == "unavailable"
        assert sec["reason"] == wr.REASON_NO_FORECAST_CALL
        assert sec["forecast_as_of_date"] is None and "2023-01-05" in sec["detail"]
        assert "segments" not in sec and "ml_lens" not in sec
        assert sec["caveats"] == list(fc.FORECAST_CAVEATS)
        ok, detail = wr._verify_forecast_trace(sec, "2023-01-05")
        assert ok, detail

    def test_a_call_with_no_open_deals_in_its_quarter_is_unavailable(self):
        call = date(2025, 11, 28)
        stub = {"as_of_date": call, "period": "2025-Q4", "reconciliation": pd.DataFrame(),
                "model": {"computable": False, "reason": "n/a"},
                "data_window": {"note": "n"}}
        sec = wr._forecast_section(date(2025, 11, 30), stub)
        assert sec["status"] == "unavailable"
        assert sec["reason"] == wr.REASON_NO_OPEN_DEALS
        assert sec["forecast_as_of_date"] == "2025-11-28" and "2025-Q4" in sec["detail"]
        assert "segments" not in sec

    def test_a_run_for_a_different_call_is_refused(self):
        stub = {"as_of_date": date(2025, 11, 14), "period": "2025-Q4",
                "reconciliation": pd.DataFrame(), "model": {}, "data_window": {"note": ""}}
        with pytest.raises(ValueError, match="2025-11-14"):
            wr._forecast_section(date(2025, 11, 30), stub)

    def test_an_unavailable_section_renders_its_reason_and_no_figures(self, readouts):
        sec = wr._forecast_section(date(2023, 1, 5))
        r = _unavailable_readout(readouts["2025-11-30"], sec)
        md = wr.render_markdown(r)
        part = md.split("## Forecast")[1].split("## Watchlist")[0]
        assert "**Status: unavailable (no_forecast_call_on_or_before_period_end).**" in part
        assert "Forecast call:" not in part and "| Segment |" not in part
        checks = {c["name"]: c for c in wr.verify_rendered_document(md, r)}
        assert checks["forecast_section_rendered_per_status"]["passed"]
        assert checks["forecast_rendered_values_match_structured_payload"]["passed"]

    def test_the_status_check_accepts_the_honest_states(self, readouts):
        assert wr._forecast_status_problem(readouts["2025-11-30"]["forecast"], "2025-11-30") is None
        assert wr._forecast_status_problem(wr._forecast_section(date(2023, 1, 5)),
                                           "2023-01-05") is None

    def test_the_status_check_rejects_not_yet_built_a_vague_unavailable_and_leakage(
            self, readouts):
        good = readouts["2025-11-30"]["forecast"]
        assert "neither present nor unavailable" in wr._forecast_status_problem(
            {"status": "not_yet_built", "note": "x"}, "2025-11-30")
        assert wr._forecast_status_problem({"status": "unavailable"}, "2025-11-30")
        unavailable_with_figures = dict(wr._forecast_section(date(2023, 1, 5)), segments=[])
        assert "no forecast figures" in wr._forecast_status_problem(
            unavailable_with_figures, "2023-01-05")
        assert "after the period end" in wr._forecast_status_problem(
            dict(good, forecast_as_of_date="2025-12-05"), "2025-11-30")


# --------------------------------------------------------------------------
# Trace exactness against a fresh run of analytics/forecast.py
# --------------------------------------------------------------------------

class TestTraceExactness:
    def test_a_freshly_built_section_traces_exactly(self, fresh_nov):
        ok, detail = wr._verify_forecast_trace(fresh_nov, "2025-11-30")
        assert ok, detail

    def test_the_section_is_the_forecast_artifacts_run_and_the_dashboards_call(self, fresh_nov):
        # the dashboard page calls fc.run_forecast(as_of) in-process; for the same as-of the
        # readout section must carry identical numbers
        run = fc.run_forecast(date(2025, 11, 28))
        recon = run["reconciliation"].to_dict(orient="records")
        assert len(recon) == len(fresh_nov["segments"]) == 2
        for got, exp in zip(fresh_nov["segments"], recon):
            for lens in ("bottoms_up_rep", "bottoms_up_manager", "ml", "cro_adjusted"):
                assert got[lens] == exp[lens]
            assert got["lens_spread_pct"] == exp["lens_spread_pct"]
            assert got["diverges_materially"] == bool(exp["diverges_materially"])
        assert fresh_nov["ml_lens"]["auc_holdout"] == run["model"]["auc_holdout"]
        assert fresh_nov["data_window_note"] == run["data_window"]["note"]

    def test_the_artifact_is_deterministic_so_exact_equality_is_a_fair_bar(self):
        a = fc.run_forecast(date(2025, 11, 28))["reconciliation"]
        b = fc.run_forecast(date(2025, 11, 28))["reconciliation"]
        pd.testing.assert_frame_equal(a, b)

    @pytest.mark.parametrize("mutate,needle", [
        (lambda s: s["segments"][0].__setitem__("ml", s["segments"][0]["ml"] + 1.0), "ml"),
        (lambda s: s["segments"][1].__setitem__("cro_adjusted", 1.0), "cro_adjusted"),
        (lambda s: s["segments"][0].__setitem__("open_deals", 999), "open_deals"),
        (lambda s: s["segments"][0].__setitem__("diverges_materially", True),
         "diverges_materially"),
        (lambda s: s.__setitem__("forecast_as_of_date", "2025-11-21"), "forecast call"),
        (lambda s: s.__setitem__("period", "2025-Q3"), "period"),
        (lambda s: s["caveats"].pop(), "caveats"),
        (lambda s: s["ml_lens"].__setitem__("auc_holdout", 0.5), "ml_lens"),
        (lambda s: s.__setitem__("divergence_threshold", 0.5), "divergence_threshold"),
        (lambda s: s.__setitem__("data_window_note", "x"), "data_window_note"),
        (lambda s: s["segments"].pop(), "segment rows"),
    ])
    def test_any_tampered_field_fails_the_trace(self, fresh_nov, mutate, needle):
        tampered = copy.deepcopy(fresh_nov)
        mutate(tampered)
        ok, detail = wr._verify_forecast_trace(tampered, "2025-11-30")
        assert not ok and needle in detail

    def test_declaring_unavailable_when_a_forecast_exists_fails_the_trace(self):
        fake = wr._forecast_section(date(2023, 1, 5))
        ok, detail = wr._verify_forecast_trace(fake, "2025-11-30")
        assert not ok

    def test_claiming_present_when_no_call_exists_fails_the_trace(self, fresh_nov):
        ok, detail = wr._verify_forecast_trace(fresh_nov, "2023-01-05")
        assert not ok


# --------------------------------------------------------------------------
# Full build-time validation and the logged scalar
# --------------------------------------------------------------------------

class TestBuildTimeValidation:
    def test_validation_passes_logs_zero_unbuilt_sections_and_the_forecast_scalar(
            self, tmp_path, monkeypatch):
        logged = {}
        monkeypatch.setattr(wr, "log_performance",
                            lambda model, as_of, name, value: logged.__setitem__(name, value))
        out = wr.run_build_time_validation(date(2025, 11, 30), write=False, log=True,
                                           out_dir=str(tmp_path))
        names = {c["name"]: c for c in out["trace_checks"] + out["render_checks"]}
        assert out["checks_passed"] == out["checks_total"] == 33
        for n in ("forecast_section_is_built_and_declares_its_status",
                  "forecast_traces_exactly_to_a_fresh_run",
                  "forecast_section_rendered_per_status",
                  "forecast_rendered_values_match_structured_payload"):
            assert names[n]["passed"], names[n]
        assert "forecast_section_declares_not_yet_built" not in names
        assert "forecast_section_rendered_as_unbuilt" not in names
        assert logged["sections_not_yet_built"] == 0.0
        assert logged["forecast_section_available"] == 1.0
        assert out["readout"]["forecast"]["forecast_as_of_date"] == "2025-11-28"
