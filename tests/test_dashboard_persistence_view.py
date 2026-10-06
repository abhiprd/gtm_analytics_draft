"""Repeat-marker presentation (dashboard/lib/persistence_view.py): a chip only for a flagged
record, a plain streak line for a not-flagged one, a reason for a not-applicable one, and
nothing invented when a readout carries no record. Also exercised against the committed
readouts by key."""
import glob
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from dashboard.lib import persistence_view as P  # noqa: E402


def rec(**over):
    base = {
        "status": "flagged", "flagged": True, "threshold_months": 2,
        "threshold_status": "Proposed, not yet confirmed", "streak_months": 3,
        "driver_key": "renewal_win_rate", "driver_label": "Renewal win rate",
        "driver_direction": "adverse", "adverse_direction": "down", "first_month_of_streak": "2025-04-01",
        "streak_detail": [
            {"month": "2025-06-01", "deviation_pct": -0.2178, "baseline_n": 8},
            {"month": "2025-05-01", "deviation_pct": -0.0784, "baseline_n": 8},
            {"month": "2025-04-01", "deviation_pct": -0.0812, "baseline_n": 8},
        ],
        "streak_break": {"month": "2025-03-01", "reason": "driver_changed", "outlier_key": "x",
                         "outlier_label": "Cyclical/planned usage dip vs. structural churn"},
        "reason": None, "basis": "The same Layer-2 driver.",
        "note": "Renewal win rate has been the largest adverse Layer-2 outlier for 3 consecutive months, since 2025-04.",
        "status_display": "Flagged: 3 consecutive months",
    }
    base.update(over)
    return base


def not_flagged(n=1):
    return rec(status="not_flagged", flagged=False, streak_months=n, first_month_of_streak=None,
               streak_detail=[{"month": "2025-11-01", "deviation_pct": 0.05, "baseline_n": 8}][:n],
               streak_break=None, note="X is the largest adverse Layer-2 outlier this month; the streak is 1 month.")


def not_applicable(reason="single_candidate_read", note="Only one child has a value."):
    return rec(status="not_applicable", flagged=False, streak_months=None, driver_key=None,
               driver_label=None, streak_detail=[], streak_break=None, reason=reason, note=note,
               first_month_of_streak=None, adverse_direction=None, driver_direction=None)


class TestChip:
    def test_flagged_gets_repeat_chip_with_count(self):
        assert P.chip_text(rec()) == "Repeat: 3 consecutive months"
        assert P.chip_text(rec(streak_months=5)) == "Repeat: 5 consecutive months"

    def test_chip_never_says_trend_or_persistent(self):
        text = P.chip_text(rec()).lower()
        assert "trend" not in text and "persist" not in text

    @pytest.mark.parametrize("p", [not_flagged(0), not_flagged(1), not_applicable(), None, {}])
    def test_no_chip_unless_flagged(self, p):
        assert P.chip_text(p) is None

    def test_flagged_without_a_streak_count_gets_no_chip(self):
        assert P.chip_text(rec(streak_months=None)) is None


class TestLines:
    def test_not_flagged_line(self):
        assert P.streak_line(not_flagged(1)) == "Streak 1 of 2 months"
        assert P.streak_line(not_flagged(0)) == "Streak 0 of 2 months"

    def test_flagged_line_names_threshold(self):
        assert P.streak_line(rec()) == "Streak: 3 months (marker threshold: 2 months, proposed)"
        assert P.streak_line(rec(streak_months=1, threshold_months=1)) == "Streak: 1 month (marker threshold: 1 month, proposed)"

    def test_not_applicable_line_and_reason_from_the_note(self):
        assert P.streak_line(not_applicable()) == "Repeat marker: not applicable."
        assert P.reason_text(not_applicable()) == "Only one child has a value."

    @pytest.mark.parametrize("code", list(P.NOT_APPLICABLE_REASONS))
    def test_not_applicable_reason_falls_back_to_the_code_map(self, code):
        assert P.reason_text(not_applicable(code, note=None)) == P.NOT_APPLICABLE_REASONS[code]

    def test_unknown_reason_code_is_humanized_not_shown_raw(self):
        out = P.reason_text(not_applicable("some_new_code", note=None))
        assert out == "Some new code." and "_" not in out

    def test_reason_only_for_not_applicable(self):
        assert P.reason_text(rec()) is None and P.reason_text(None) is None


class TestAbsentAndState:
    def test_absent_record_has_no_chip_and_a_plain_line(self):
        s = P.state(None)
        assert s["kind"] == P.KIND_ABSENT and s["chip"] is None and s["rows"] == []
        assert s["line"] == "Repeat marker: not in this readout."

    def test_unknown_status_is_absent(self):
        assert P.state({"status": "something_else"})["kind"] == P.KIND_ABSENT

    def test_flagged_state(self):
        s = P.state(rec())
        assert s["kind"] == "flagged" and s["chip"] == "Repeat: 3 consecutive months"
        assert s["basis"] and s["adverse_direction"] == "Adverse direction for this driver: down."
        assert [r["Month"] for r in s["rows"]] == ["2025-04", "2025-05", "2025-06"]
        assert s["break_text"] == ("Month before the streak (2025-03): a different driver was the largest outlier, "
                                   "Cyclical/planned usage dip vs. structural churn.")

    def test_not_flagged_state_has_no_chip_and_no_break_text(self):
        s = P.state(not_flagged(1))
        assert s["chip"] is None and s["break_text"] is None and len(s["rows"]) == 1

    def test_not_applicable_state_uses_reason_as_note(self):
        s = P.state(not_applicable())
        assert s["chip"] is None and s["note"] == "Only one child has a value." and s["rows"] == []
        assert s["adverse_direction"] is None


class TestFormatting:
    def test_deviation_signed_and_zero_unsigned(self):
        assert P.deviation_text(-0.2178) == "-21.8%"
        assert P.deviation_text(0.025529) == "+2.6%"
        assert P.deviation_text(0.00001) == "0.0%"
        assert P.deviation_text(-0.00001) == "0.0%"
        assert P.deviation_text(None) == "n/a"

    def test_streak_rows_are_oldest_first_with_baseline_months(self):
        rows = P.streak_rows(rec())
        assert rows[0] == {"Month": "2025-04", "Deviation from own trailing baseline": "-8.1%", "Baseline months": 8}

    def test_cross_reference_prefix_is_removed_from_labels_and_notes(self):
        p = rec(note="See Growth: Expansion (share of starting revenue) has been the outlier.")
        assert P.note_text(p) == "Expansion (share of starting revenue) has been the outlier."
        assert P.clean_node_label("See Growth: Contraction (share of starting revenue)") == "Contraction (share of starting revenue)"
        assert P.clean_node_label("Renewal win rate") == "Renewal win rate"

    @pytest.mark.parametrize("reason,frag", [
        ("not_adverse", "not moving in the adverse direction"), ("tie_at_top", "tied"),
        ("no_sibling_comparison", "fewer than 2"), ("start_of_history", "no earlier months")])
    def test_every_break_reason_has_text(self, reason, frag):
        out = P.break_text(rec(streak_break={"month": "2025-01-01", "reason": reason}))
        assert frag in out and "2025-01" in out


class TestScopeNote:
    def test_threshold_comes_from_the_record(self):
        out = P.scope_note([{"persistence": rec()}])
        assert out == ("The repeat marker shows the same driver as the adverse outlier in consecutive months; "
                       "it does not establish a trend or a cause (threshold 2 months, proposed).")

    def test_no_note_when_no_entry_has_a_record(self):
        assert P.scope_note([{}, {"persistence": None}]) is None
        assert P.scope_note([]) is None

    def test_confirmed_threshold_is_not_called_proposed(self):
        out = P.scope_note([{"persistence": rec(threshold_status="Confirmed")}])
        assert "proposed" not in out and "confirmed" in out


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(REPO, "analytics", "outputs", "weekly_readout_*.json"))))
def test_committed_readouts_render_every_entry(path):
    readout = json.load(open(path))
    entries = readout["drilldowns"]["entries"]
    states = [P.state(e.get("persistence")) for e in entries]
    for e, s in zip(entries, states):
        status = (e.get("persistence") or {}).get("status")
        assert s["kind"] == status
        assert (s["chip"] is not None) == (status == "flagged")
        if status == "flagged":
            assert s["chip"] == f"Repeat: {e['persistence']['streak_months']} consecutive months"
        if status == "not_flagged":
            assert s["line"].startswith("Streak ") and " of 2 months" in s["line"]
        assert "See Growth" not in (s["note"] or "")


class TestWave10aQaFixes:
    def test_flagged_line_carries_the_proposed_status_locally(self):
        assert "marker threshold: 2 months, proposed" in P.streak_line(rec())

    def test_caveat_is_shown_for_a_record_that_carries_one(self):
        r = rec(caveat="Repeat marker: the same driver as the adverse outlier in consecutive months; not evidence of a trend or cause.")
        assert P.state(r)["caveat"].endswith("not evidence of a trend or cause.")
        assert P.state(rec())["caveat"] is None
        assert P.state(None)["caveat"] is None

    def test_basis_is_its_own_sentence_case_line(self):
        line = P.state(rec(basis="The same Layer-2 driver as the largest adverse outlier."))["basis_line"]
        assert line == "Basis: the same Layer-2 driver as the largest adverse outlier."
        assert P.basis_line(rec(basis="CPI is used.")) == "Basis: CPI is used."
        assert P.basis_line(rec(basis="")) is None

    def test_scope_notes_carry_the_chance_level_line(self):
        notes = P.scope_notes([{"persistence": rec()}])
        assert notes[0].startswith("The repeat marker shows the same driver")
        assert notes[1] == ("In aggregate the marker appears about as often on shuffled months as on real data; "
                            "it is a repeat marker, not evidence of a trend or cause.")
        assert P.scope_notes([{}]) == []
