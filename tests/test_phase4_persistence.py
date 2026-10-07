"""Variance-diagnostic engine: the persistence flag (analytics/variance_diagnostic.py,
compute_persistence and its validation suite).

Three kinds of test live here, and the split matters:

  * Pure tests drive compute_persistence() with hand-built month-by-month
    histories (no database): the known-streak scenarios, the adverse-direction
    table, mutation checks that prove each scenario is not vacuous, and the
    lazy-read and no-look-ahead behaviour of the series provider.
  * Engine tests run the real engine against the dbt database: every drill-down
    carries a persistence record that tracks its own Layer-2 outlier, the
    truncated final month is excluded, and a full engine run (prior months
    rebuilt from the marts as of their own month) equals the profile that cuts
    one build.
  * Profile tests check the real-data selectivity numbers recorded in
    docs/acme-corp-analytics-methods.md, and the seeded permutation null.

Run: python3 -m pytest tests/test_phase4_persistence.py -v
"""
import dataclasses
import os
import sys
from datetime import date

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from analytics import variance_diagnostic as vd  # noqa: E402

DB_PATH = os.path.join(ROOT, "data", "acme_gtm.duckdb")
needs_db = pytest.mark.skipif(
    not os.path.exists(DB_PATH), reason="dbt-built database not present; run `cd dbt && dbt build`")

AS_OF_LATEST = date(2025, 11, 30)
AS_OF_MID = date(2025, 6, 30)
MONTH = vd._SYNTHETIC_MONTH


def _scenarios():
    return {s["name"]: s for s in vd._persistence_scenarios()}


def _run(name, **kw):
    s = dict(_scenarios()[name])
    s.update(kw)
    return vd.run_persistence_scenario(s)


# --------------------------------------------------------------------------
# The adverse-direction table: the sign of each Layer-2 child's effect on its parent
# --------------------------------------------------------------------------

# node -> direction of movement that hurts its Layer-1 parent, written out by hand
# from the tree's arithmetic (not read back from the table under test)
EXPECTED_ADVERSE = {
    # New logo revenue (higher is better) is the product of its three children
    "pipeline_generated": "down", "win_rate": "down", "avg_initial_commitment": "down",
    # Activation (time, lower is better): more completed onboarding shortens it, so a
    # fall in completion is what hurts
    "onboarding_completion_rate": "down",
    "overage_realization": "down",
    # Contraction + churned revenue (lower is better)
    "cyclical_vs_structural_usage_dip": "up", "workflow_chain_underutilization": "up",
    "renewal_win_rate": "down",
    # Efficiency
    "sm_cost": "up",                               # Magic number divides by cost
    "cac_by_channel": "up",                        # payback (lower is better) rises with CAC
    "utilized_vs_committed_action_volume": "down",  # and falls with margin
    "am_touchpoint_volume": "up", "automated_action_volume": "down",  # touches per Action
    "am_cost_by_segment": "up",                    # AM efficiency divides by AM cost
    # Durability (higher is better): 1 + expansion - contraction - churn
    "nrr_expansion_rate": "down", "nrr_contraction_rate": "up", "nrr_churn_rate": "up",
    "grr_contraction_rate": "up", "grr_churn_rate": "up",
    "tenure_at_churn": None,
}


class TestAdverseDirectionTable:
    def test_every_computable_layer2_node_has_the_hand_derived_direction(self):
        for key, expected in EXPECTED_ADVERSE.items():
            assert vd.adverse_direction(key) == expected, key

    def test_the_table_covers_exactly_the_ranking_eligible_computable_layer2_nodes(self):
        needed = {n.key for n in vd._TREE.values()
                  if n.layer == 2 and n.is_ranking_sibling
                  and n.computability != vd.NOT_COMPUTABLE}
        assert needed == set(vd._EFFECT_ON_PARENT) == set(EXPECTED_ADVERSE)

    def test_a_node_missing_from_the_table_fails_the_integrity_check(self, monkeypatch):
        trimmed = dict(vd._EFFECT_ON_PARENT)
        trimmed.pop("win_rate")
        monkeypatch.setattr(vd, "_EFFECT_ON_PARENT", trimmed)
        with pytest.raises(ValueError, match="out of step with the tree"):
            vd._verify_persistence_table()

    def test_a_stale_entry_fails_the_integrity_check(self, monkeypatch):
        monkeypatch.setattr(vd, "_EFFECT_ON_PARENT", {**vd._EFFECT_ON_PARENT, "ghost_node": +1})
        with pytest.raises(ValueError, match="out of step with the tree"):
            vd._verify_persistence_table()

    def test_direction_is_read_at_layer_2_only(self):
        with pytest.raises(ValueError, match="persistence is read at Layer 2"):
            vd.adverse_direction("nrr")
        with pytest.raises(ValueError):
            vd.adverse_direction("poc_pass_rate")

    def test_the_same_effect_flips_with_the_parents_favorable_direction(self):
        # a child that raises its parent: adverse is down when the parent should rise,
        # up when the parent should fall
        assert vd._TREE["new_logo_consumption_revenue"].favorable_direction == "higher"
        assert vd._TREE["consumption_payback"].favorable_direction == "lower"
        assert vd.adverse_direction("win_rate") == "down"
        assert vd.adverse_direction("cac_by_channel") == "up"


# --------------------------------------------------------------------------
# The known-streak scenarios
# --------------------------------------------------------------------------

class TestScenarios:
    def test_every_scenario_passes(self):
        results = vd.run_persistence_scenarios()
        assert len(results) == 16
        assert [r["name"] for r in results if not r["passed"]] == []

    def test_the_named_cases_are_all_present(self):
        assert set(_scenarios()) == {
            "streak_of_one_is_not_flagged", "streak_of_exactly_two_is_flagged",
            "streak_of_three_is_flagged_with_its_first_month", "driver_change_resets_the_streak",
            "missing_month_breaks_the_streak", "favorable_outlier_is_not_an_adverse_streak",
            "direction_follows_the_parents_favorable_direction", "tie_at_top_ends_the_streak",
            "additive_share_branch_ranks_by_absolute_deviation",
            "single_candidate_branch_is_not_applicable",
            "truncated_final_month_is_not_applicable", "no_outlier_is_not_applicable",
            "undirected_driver_is_not_applicable", "streak_stops_at_the_start_of_history",
            "sibling_without_a_full_baseline_is_not_ranked", "future_months_are_never_read"}

    @pytest.mark.parametrize("name,streak,flagged", [
        ("streak_of_one_is_not_flagged", 1, False),
        ("streak_of_exactly_two_is_flagged", 2, True),
        ("streak_of_three_is_flagged_with_its_first_month", 3, True),
        ("driver_change_resets_the_streak", 2, True),
        ("missing_month_breaks_the_streak", 1, False),
        ("favorable_outlier_is_not_an_adverse_streak", 0, False),
        ("tie_at_top_ends_the_streak", 1, False),
        ("additive_share_branch_ranks_by_absolute_deviation", 2, True),
        ("streak_stops_at_the_start_of_history", 4, True),
    ])
    def test_streak_and_flag(self, name, streak, flagged):
        rec = _run(name)["record"]
        assert rec["streak_months"] == streak and rec["flagged"] is flagged
        assert rec["status"] == ("flagged" if flagged else "not_flagged")

    def test_the_first_month_of_the_streak_is_named(self):
        rec = _run("streak_of_three_is_flagged_with_its_first_month")["record"]
        assert rec["first_month_of_streak"] == (MONTH - pd.DateOffset(months=2)).date().isoformat()
        assert [d["month"] for d in rec["streak_detail"]] == [
            (MONTH - pd.DateOffset(months=i)).date().isoformat() for i in range(3)]

    def test_a_change_of_driver_resets_rather_than_bridges(self):
        rec = _run("driver_change_resets_the_streak")["record"]
        # adverse again three months back, but the streak ended at the other driver
        assert rec["streak_months"] == 2
        assert rec["streak_break"]["reason"] == "driver_changed"
        assert rec["streak_break"]["outlier_key"] == "utilized_vs_committed_action_volume"
        assert rec["streak_break"]["month"] == (MONTH - pd.DateOffset(months=2)).date().isoformat()

    def test_a_missing_month_is_a_month_with_no_comparison(self):
        rec = _run("missing_month_breaks_the_streak")["record"]
        assert rec["streak_break"]["reason"] == "no_sibling_comparison"

    def test_a_favorable_move_is_reported_as_favorable_with_no_streak(self):
        rec = _run("favorable_outlier_is_not_an_adverse_streak")["record"]
        assert rec["driver_direction"] == "favorable" and rec["streak_months"] == 0
        assert "favorable direction" in rec["note"]

    def test_the_additive_branch_is_ranked_on_its_own_basis(self, monkeypatch):
        # ranked by absolute deviation, contraction persists; ranked by % deviation
        # churn would be the top outlier every month and contraction's streak is 0
        assert _run("additive_share_branch_ranks_by_absolute_deviation")["passed"]
        relative = dataclasses.replace(vd._TREE["nrr"], sibling_comparison_basis="relative_deviation")
        monkeypatch.setitem(vd._TREE, "nrr", relative)
        s = _scenarios()["additive_share_branch_ranks_by_absolute_deviation"]
        with pytest.raises(ValueError, match="not the top-ranked sibling"):
            vd.compute_persistence(s["parent_key"], s["driver_key"], MONTH,
                                   vd._cut_provider(s["series"]))

    def test_the_not_applicable_records_carry_a_reason_and_no_streak(self):
        for name, reason in (
                ("single_candidate_branch_is_not_applicable", "single_candidate_read"),
                ("truncated_final_month_is_not_applicable", "truncated_final_month"),
                ("no_outlier_is_not_applicable", "no_layer2_outlier"),
                ("undirected_driver_is_not_applicable", "no_adverse_direction_defined")):
            rec = _run(name)["record"]
            assert rec["status"] == "not_applicable" and rec["reason"] == reason, name
            assert rec["streak_months"] is None and rec["flagged"] is False
            assert rec["first_month_of_streak"] is None and rec["streak_detail"] == []
            assert rec["note"]

    def test_a_single_candidate_with_a_long_run_is_still_not_a_streak(self):
        # four straight adverse-looking months from a lone sibling: trivially persistent,
        # so not reported as persistence
        rec = _run("single_candidate_branch_is_not_applicable")["record"]
        assert rec["status"] == "not_applicable" and rec["streak_months"] is None

    def test_the_streak_stops_at_the_start_of_the_data_not_at_a_change_of_driver(self):
        rec = _run("streak_stops_at_the_start_of_history")["record"]
        assert rec["streak_break"]["reason"] == "start_of_history"


class TestScenariosAreNotVacuous:
    """Each scenario fails when the rule it pins is broken."""

    def test_flipping_the_sign_of_a_childs_effect_turns_a_flagged_streak_into_none(
            self, monkeypatch):
        monkeypatch.setitem(vd._EFFECT_ON_PARENT, "cac_by_channel", -1)
        assert not _run("streak_of_exactly_two_is_flagged")["passed"]
        rec = _run("streak_of_exactly_two_is_flagged")["record"]
        assert rec["streak_months"] == 0 and rec["driver_direction"] == "favorable"

    def test_a_threshold_of_three_unflags_a_streak_of_two(self):
        s = _scenarios()["streak_of_exactly_two_is_flagged"]
        rec = vd.compute_persistence(s["parent_key"], s["driver_key"], MONTH,
                                     vd._cut_provider(s["series"]), k=3)
        assert rec["streak_months"] == 2 and rec["status"] == "not_flagged"
        assert rec["threshold_months"] == 3

    def test_ignoring_ties_lets_a_tied_month_extend_the_streak(self, monkeypatch):
        monkeypatch.setattr(vd, "_top_two_tied", lambda parent_key, scored: False)
        assert not _run("tie_at_top_ends_the_streak")["passed"]

    def test_a_streak_that_bridged_drivers_would_be_longer(self, monkeypatch):
        # without the driver check the four adverse CAC months and the margin month in between
        # would not reset: simulate by asking for the margin leg as the driver
        s = _scenarios()["driver_change_resets_the_streak"]
        rec = vd.compute_persistence(s["parent_key"], "cac_by_channel", MONTH,
                                     vd._cut_provider(s["series"]))
        assert rec["streak_months"] == 2 != 4

    def test_the_provider_is_cut_to_the_month_so_a_leaky_provider_changes_nothing(self):
        s = _scenarios()["future_months_are_never_read"]
        leaked = vd.compute_persistence(s["parent_key"], s["driver_key"], MONTH,
                                        vd._cut_provider(s["series"]))
        cut = {k: v[v.index <= MONTH] for k, v in s["series"].items()}
        clean = vd.compute_persistence(s["parent_key"], s["driver_key"], MONTH,
                                       vd._cut_provider(cut))
        assert leaked == clean and leaked["streak_months"] == 2
        assert max(s["series"]["cac_by_channel"].index) > MONTH  # the future was really there


class TestComputePersistenceGuards:
    def test_the_driver_must_be_the_top_ranked_sibling(self):
        s = _scenarios()["streak_of_one_is_not_flagged"]
        with pytest.raises(ValueError, match="not the top-ranked sibling"):
            vd.compute_persistence(s["parent_key"], "utilized_vs_committed_action_volume",
                                   MONTH, vd._cut_provider(s["series"]))

    def test_the_driver_must_be_a_layer_2_child_of_the_parent(self):
        s = _scenarios()["streak_of_one_is_not_flagged"]
        with pytest.raises(ValueError, match="not a Layer-2 child"):
            vd.compute_persistence(s["parent_key"], "win_rate", MONTH,
                                   vd._cut_provider(s["series"]))
        with pytest.raises(ValueError, match="persistence heads at Layer 1"):
            vd.compute_persistence("win_rate", "poc_pass_rate", MONTH, vd._cut_provider({}))

    def test_prior_months_are_read_lazily_newest_first_and_only_to_the_break(self):
        s = _scenarios()["streak_of_exactly_two_is_flagged"]
        asked = []

        def provider(month):
            asked.append(month)
            return {k: v[v.index <= month] for k, v in s["series"].items()}

        vd.compute_persistence(s["parent_key"], s["driver_key"], MONTH, provider)
        # the evaluation month, then one prior month in the streak, then the month that broke it
        assert asked == [MONTH, MONTH - pd.DateOffset(months=1), MONTH - pd.DateOffset(months=2)]

    def test_a_record_is_deterministic(self):
        s = _scenarios()["driver_change_resets_the_streak"]
        a = vd.compute_persistence(s["parent_key"], s["driver_key"], MONTH, vd._cut_provider(s["series"]))
        b = vd.compute_persistence(s["parent_key"], s["driver_key"], MONTH, vd._cut_provider(s["series"]))
        assert a == b

    def test_a_drilldown_rejects_a_persistence_record_for_another_driver(self):
        rec = _run("streak_of_one_is_not_flagged")["record"]
        with pytest.raises(ValueError, match="own Layer-2 outlier"):
            vd.Drilldown(layer1_key="consumption_payback",
                         layer2_key="utilized_vs_committed_action_volume", layer3_keys=[],
                         layer1_variance_pct=0.0, layer1_mechanism="x",
                         sibling_ranking=pd.DataFrame(), sibling_coverage={},
                         layer3_status=vd.L3_NO_COMPUTABLE_DATA, layer3_evidence=pd.DataFrame(),
                         branch_max_depth_in_tree=2, persistence=rec)

    def test_a_drilldown_rejects_a_flag_that_disagrees_with_the_status(self):
        rec = dict(_run("streak_of_one_is_not_flagged")["record"], flagged=True)
        with pytest.raises(ValueError, match="flagged disagrees"):
            vd.Drilldown(layer1_key="consumption_payback", layer2_key="cac_by_channel",
                         layer3_keys=[], layer1_variance_pct=0.0, layer1_mechanism="x",
                         sibling_ranking=pd.DataFrame(), sibling_coverage={},
                         layer3_status=vd.L3_BRANCH_DEPTH_2, layer3_evidence=pd.DataFrame(),
                         branch_max_depth_in_tree=2, persistence=rec)

    def test_the_threshold_constant_is_two_and_documented_as_proposed(self):
        assert vd.K_PERSISTENCE == 2
        src = open(os.path.join(ROOT, "analytics", "variance_diagnostic.py")).read()
        i = src.index("K_PERSISTENCE = 2")
        assert "PROPOSED, NOT YET CONFIRMED" in src[i - 900:i]
        assert vd.PERSISTENCE_THRESHOLD_STATUS == "Proposed, not yet confirmed"


class TestNotes:
    def test_notes_are_plain_language_with_no_identifiers(self):
        import re
        for name in _scenarios():
            rec = _run(name)["record"]
            note = rec["note"]
            assert not re.search(r"\b[a-z]+_[a-z0-9_]+\b", note), (name, note)
            assert not re.search(r"\b(?:will|may|might|could|would|because)\b", note), (name, note)

    def test_a_flagged_note_states_the_length_and_the_first_month(self):
        rec = _run("streak_of_three_is_flagged_with_its_first_month")["record"]
        assert "for 3 consecutive months" in rec["note"]
        assert rec["first_month_of_streak"][:7] in rec["note"]


# --------------------------------------------------------------------------
# The real engine
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def runs():
    return {d: vd.run_diagnostic(d, include_watchlist=False) for d in (AS_OF_MID, AS_OF_LATEST)}


@needs_db
class TestEngineDrilldowns:
    @pytest.mark.parametrize("d", [AS_OF_MID, AS_OF_LATEST])
    def test_every_drilldown_carries_a_record_that_tracks_its_own_outlier(self, runs, d):
        assert runs[d]["drilldowns"]
        for dd in runs[d]["drilldowns"]:
            p = dd.persistence
            assert p is not None and p["driver_key"] == dd.layer2_key
            assert p["flagged"] == (p["status"] == "flagged")
            assert dd.to_dict()["persistence"] == p
            if p["status"] == "not_applicable":
                assert p["reason"] and p["streak_months"] is None
            else:
                assert isinstance(p["streak_months"], int) and p["reason"] is None

    @pytest.mark.parametrize("d", [AS_OF_MID, AS_OF_LATEST])
    def test_single_candidate_branches_are_not_applicable(self, runs, d):
        for dd in runs[d]["drilldowns"]:
            if not dd.sibling_coverage["is_genuine_sibling_comparison"]:
                assert dd.persistence["status"] == "not_applicable"
                assert dd.persistence["reason"] == "single_candidate_read"

    def test_the_committed_checkpoint_values_at_2025_06_30(self, runs):
        by = {dd.layer1_key: dd.persistence for dd in runs[AS_OF_MID]["drilldowns"]}
        assert (by["contraction_churned_revenue"]["driver_key"],
                by["contraction_churned_revenue"]["streak_months"]) == ("renewal_win_rate", 3)
        assert by["contraction_churned_revenue"]["flagged"]
        assert by["nrr"]["streak_months"] == 5 and by["nrr"]["flagged"]
        assert by["grr"]["streak_months"] == 2 and by["grr"]["flagged"]
        assert by["new_logo_consumption_revenue"]["streak_months"] == 0
        assert by["expansion_consumption_revenue"]["status"] == "not_applicable"

    def test_the_committed_checkpoint_values_at_2025_11_30(self, runs):
        by = {dd.layer1_key: dd.persistence for dd in runs[AS_OF_LATEST]["drilldowns"]}
        assert not any(p["flagged"] for p in by.values())
        assert by["nrr"]["streak_months"] == 1 and by["grr"]["streak_months"] == 1
        assert by["nrr"]["streak_break"]["reason"] == "not_adverse"

    def test_the_truncated_final_month_is_excluded(self):
        run = vd.run_diagnostic(date(2025, 12, 31), include_watchlist=False)
        assert run["data_window"]["evaluation_month_is_last_month_in_window"]
        assert run["drilldowns"]
        for dd in run["drilldowns"]:
            assert dd.persistence["status"] == "not_applicable"
            assert dd.persistence["reason"] in ("truncated_final_month", "no_layer2_outlier")

    def test_a_drilldown_with_no_outlier_is_not_applicable(self):
        rec = vd.compute_persistence("nrr", None, pd.Timestamp("2025-06-01"), lambda m: {})
        assert rec["status"] == "not_applicable" and rec["reason"] == "no_layer2_outlier"


@needs_db
class TestNoLookAhead:
    def test_a_full_engine_run_equals_the_profile_that_cuts_one_build(self):
        """The engine rebuilds each prior month from the marts as of that month's end;
        the profile builds once at a later date and cuts. Equal records on every
        drill-down mean the cut is a faithful stand-in for rebuilding."""
        checked = vd.verify_persistence_asof_equivalence(
            [date(2023, 6, 30), date(2024, 9, 30), date(2025, 6, 30)])
        assert len(checked) >= 15
        assert [c for c in checked if not c["same"]] == []

    def test_the_series_a_prior_month_sees_are_the_marts_as_of_that_month(self):
        con = vd._connect()
        try:
            month = pd.Timestamp("2025-06-01")
            full = vd._build_child_series("contraction_churned_revenue", AS_OF_LATEST, con)
            asof = vd._asof_series_provider("contraction_churned_revenue", full,
                                            pd.Timestamp("2025-11-01"), con)(month)
        finally:
            con.close()
        for key, s in asof.items():
            assert s.index.max() <= month, key
            pd.testing.assert_series_equal(s, full[key][full[key].index <= month],
                                           check_names=False)


# --------------------------------------------------------------------------
# Real-data selectivity and stability
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def profile():
    return vd.measure_persistence_selectivity(AS_OF_LATEST)


@needs_db
class TestSelectivity:
    def test_the_profile_covers_every_branch_and_month_from_2023_01_to_2025_11(self, profile):
        assert profile["month"].min() == pd.Timestamp("2023-01-01")
        assert profile["month"].max() == pd.Timestamp("2025-11-01")
        assert set(profile["layer1_key"]) == {
            "new_logo_consumption_revenue", "activation", "expansion_consumption_revenue",
            "contraction_churned_revenue", "magic_number", "consumption_payback",
            "onboarding_cs_efficiency", "am_efficiency", "nrr", "grr", "logo_retention"}

    def test_single_candidate_branches_are_never_eligible(self, profile):
        for key in ("activation", "expansion_consumption_revenue", "magic_number",
                    "am_efficiency", "logo_retention"):
            assert not profile[profile["layer1_key"] == key]["eligible"].any(), key

    def test_the_flag_fires_often_enough_to_mean_something_and_not_so_often_it_saturates(
            self, profile):
        summary = vd.summarize_persistence_selectivity(profile)
        assert summary["eligible_branch_months"] == 202
        assert summary["flagged_branch_months"] == 38
        assert 0.02 < summary["flag_rate"] < 0.60
        assert 0.02 < summary["flag_rate_breached"] < 0.60
        assert set(summary["per_branch"]) == {
            "new_logo_consumption_revenue", "contraction_churned_revenue",
            "consumption_payback", "onboarding_cs_efficiency", "nrr", "grr"}

    def test_stability_numbers_are_reported(self, profile):
        summary = vd.summarize_persistence_selectivity(profile)
        assert 0.0 < summary["flag_flips_per_transition"] < 1.0
        assert 0.0 < summary["p_flagged_given_flagged_previous_month"] < 1.0
        assert summary["flagged_runs"] == 20 and summary["mean_flagged_run_months"] > 1.0
        assert sum(summary["streak_distribution"].values()) == summary["eligible_branch_months"]

    def test_a_flag_never_exists_without_a_streak_at_the_threshold(self, profile):
        elig = profile[profile["eligible"]]
        assert (elig["flagged"] == (elig["streak_months"] >= vd.K_PERSISTENCE)).all()

    def test_a_looser_threshold_flags_at_least_as_many_months(self):
        k3 = vd.measure_persistence_selectivity(AS_OF_LATEST, k=3)
        k2 = vd.measure_persistence_selectivity(AS_OF_LATEST, k=2)
        assert k3["flagged"].sum() <= k2["flagged"].sum()
        assert k3["flagged"].sum() < k2["flagged"].sum()  # and the threshold bites

    def test_the_permutation_null_is_seeded_and_reproducible(self):
        a = vd.persistence_permutation_null(AS_OF_LATEST, n_permutations=1, seed=42)
        b = vd.persistence_permutation_null(AS_OF_LATEST, n_permutations=1, seed=42)
        c = vd.persistence_permutation_null(AS_OF_LATEST, n_permutations=1, seed=7)
        assert a == b
        assert a["null_mean"] != c["null_mean"]
        assert a["observed_flag_rate"] == pytest.approx(38 / 202)

    def test_build_time_validation_runs_the_scenarios_and_logs_the_profile(self, tmp_path,
                                                                          monkeypatch):
        import analytics.model_performance as mp
        monkeypatch.setattr(mp, "_CSV_PATH", str(tmp_path / "perf.csv"))
        out = vd.run_build_time_validation(AS_OF_LATEST)
        assert all(s["passed"] for s in out["persistence_scenarios"])
        rows = {r["metric_name"]: float(r["metric_value"]) for r in mp.read_performance_history()
                if r["model_name"] == "variance_diagnostic_engine"}
        assert rows["persistence_scenarios_total"] == rows["persistence_scenarios_passed"] == 16.0
        assert rows["persistence_eligible_branch_months"] == 202.0
        assert rows["persistence_flag_rate"] == pytest.approx(38 / 202)


# --------------------------------------------------------------------------
# Early series: no fake 100% win rate, and a sibling needs a full baseline
# --------------------------------------------------------------------------

@needs_db
class TestEarlySeriesHandling:
    @pytest.fixture(scope="class")
    def series(self):
        con = vd._connect()
        try:
            yield {
                "l2": vd._build_child_series("new_logo_consumption_revenue", AS_OF_LATEST, con),
                "l3": vd._build_child_series("win_rate", AS_OF_LATEST, con),
                "before": vd._build_child_series("new_logo_consumption_revenue",
                                                 date(2022, 12, 31), con),
                "con": con,
            }
        finally:
            con.close()

    def test_win_rate_starts_at_the_first_month_with_a_logged_loss(self, series):
        con = vd._connect()
        try:
            first_loss = pd.Timestamp(con.execute(
                "select min(month) from main_marts.mart_growth_bridge "
                "where segment in ('Commercial', 'Enterprise') and new_business_lost_count > 0"
            ).fetchone()[0])
        finally:
            con.close()
        assert first_loss == pd.Timestamp("2023-01-01")
        assert series["l2"]["win_rate"].index.min() == first_loss
        assert series["l2"]["win_rate"].dropna().lt(1.0).all()  # no fake 100% anywhere

    def test_the_series_derived_from_closed_deals_start_there_too(self, series):
        assert series["l3"]["rep_capacity_ramp_mix"].index.min() == pd.Timestamp("2023-01-01")
        assert series["l3"]["loss_reason_mix"].index.min() == pd.Timestamp("2023-01-01")

    def test_the_other_new_logo_siblings_are_not_blanked(self, series):
        assert series["l2"]["avg_initial_commitment"].index.min() < pd.Timestamp("2022-01-01")
        assert series["l2"]["pipeline_generated"].index.min() < pd.Timestamp("2022-01-01")

    def test_with_no_loss_logged_as_of_the_date_the_series_is_empty(self, series):
        assert len(series["before"]["win_rate"]) == 0

    def test_the_helper_blanks_by_data_not_by_date(self):
        idx = pd.date_range("2024-01-01", periods=6, freq="MS")
        s = pd.Series([1.0] * 6, index=idx)
        lost = pd.Series([0, 0, 0, 2, 0, 1], index=idx)
        assert list(vd._from_first_logged_loss(s, lost).index) == list(idx[3:])
        assert len(vd._from_first_logged_loss(s, lost * 0)) == 0

    def test_win_rate_enters_a_ranking_only_with_eight_observations(self, series):
        ranked = {}
        for m in ("2023-02-01", "2023-08-01", "2023-09-01"):
            month = pd.Timestamp(m)
            r = vd.rank_siblings("new_logo_consumption_revenue",
                                 {k: v[v.index <= month] for k, v in series["l2"].items()},
                                 month)
            ranked[m] = r.set_index("metric_key").loc["win_rate"]
        assert ranked["2023-02-01"]["baseline_n"] == 1 and pd.isna(ranked["2023-02-01"]["deviation_pct"])
        assert ranked["2023-08-01"]["baseline_n"] == 7 and pd.isna(ranked["2023-08-01"]["deviation_pct"])
        assert ranked["2023-09-01"]["baseline_n"] == 8 and pd.notna(ranked["2023-09-01"]["deviation_pct"])

    def test_a_short_baseline_sibling_is_dropped_and_reported_missing(self):
        month = pd.Timestamp("2025-06-01")
        full = vd._synthetic_series(month, 100.0, 0.05, jitter=(0.01,) * 8)
        short = vd._synthetic_series(month, 100.0, 0.50, n_baseline=5)
        r = vd.rank_siblings("onboarding_cs_efficiency",
                             {"am_touchpoint_volume": short, "automated_action_volume": full}, month)
        scored = vd._with_signal("onboarding_cs_efficiency", r)
        assert list(scored["metric_key"]) == ["automated_action_volume"]
        cov = vd._sibling_coverage("onboarding_cs_efficiency", scored)
        assert cov["is_genuine_sibling_comparison"] is False
        assert [m["metric_key"] for m in cov["missing_siblings"]] == ["am_touchpoint_volume"]
        row = r.set_index("metric_key").loc["am_touchpoint_volume"]
        assert row["baseline_n"] == 5 and pd.notna(row["value"])  # visible, not ranked

    def test_the_consumption_payback_cac_leg_is_not_ranked_before_it_has_a_baseline(self, series):
        con = vd._connect()
        try:
            cp = vd._build_child_series("consumption_payback", AS_OF_LATEST, con)
        finally:
            con.close()
        first = cp["cac_by_channel"].index.min()
        month = first + pd.DateOffset(months=3)
        scored = vd._scored_read("consumption_payback", {k: v[v.index <= month] for k, v in cp.items()},
                                 month, 8)
        assert list(scored["metric_key"]) == ["utilized_vs_committed_action_volume"]

    def test_no_persistence_driver_is_win_rate_before_it_has_a_baseline(self):
        rows = vd.measure_persistence_selectivity(AS_OF_LATEST)
        wr_months = rows[(rows["driver_key"] == "win_rate")]["month"]
        assert len(wr_months) and wr_months.min() >= pd.Timestamp("2023-09-01")

    def test_the_workflow_chain_cut_is_the_decline_window_plus_the_truncated_month(self):
        from generators import config
        assert vd._WORKFLOW_CHAIN_DECLINE_MONTHS == config.DECLINE_MONTHS_BEFORE_CHURN
        assert vd._WORKFLOW_CHAIN_PRECHURN_MONTHS == config.DECLINE_MONTHS_BEFORE_CHURN + 1
        con = vd._connect()
        try:
            full = vd._build_child_series("contraction_churned_revenue", date(2025, 12, 31), con)
            last = pd.Timestamp(con.execute(
                "select max(month) from main_marts.mart_workflow_chain_health").fetchone()[0])
        finally:
            con.close()
        assert full["workflow_chain_underutilization"].index.max() == pd.Timestamp("2025-07-01")
        assert last == pd.Timestamp("2025-12-01")
