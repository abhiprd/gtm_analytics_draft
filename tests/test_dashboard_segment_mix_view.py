"""Segment-mix card state (dashboard/lib/segment_mix_view.py): the headline and figures
come from the readout verbatim, percent-point changes carry 'pp' and no sign when they
round to zero, an unavailable section shows its reason and no figures, and a readout with
no section is absent rather than empty. Also exercised against the committed readouts."""
import copy
import glob
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from dashboard.lib import segment_mix_view as M  # noqa: E402

PATHS = sorted(glob.glob(os.path.join(REPO, "analytics", "outputs", "weekly_readout_*.json")))


def present_mix():
    return copy.deepcopy(json.load(open(PATHS[-1]))["segment_mix"])


def unavailable_mix():
    return {"status": "unavailable", "reason": "evaluation_month_is_truncated_final_month",
            "detail": "The evaluation month is the final month of the data window.",
            "evaluation_month": "2025-12-01", "basis": "b", "caveats": ["A caveat."],
            "note": "n", "headline": None}


class TestPercentPoints:
    def test_display_string_wins(self):
        assert M.format_pp(0.0203, "+2.0 pp") == "+2.0 pp"

    def test_value_only_is_formatted_with_pp(self):
        assert M.format_pp(0.0203) == "+2.0 pp"
        assert M.format_pp(-0.0522) == "-5.2 pp"

    def test_change_that_rounds_to_zero_is_unsigned(self):
        assert M.format_pp(0.00004) == "0.0 pp"
        assert M.format_pp(-0.00004) == "0.0 pp"
        assert M.format_pp(None, "-0.0 pp") == "0.0 pp"
        assert M.format_pp(None, "+0.0 pp") == "0.0 pp"

    def test_no_change_available(self):
        assert M.format_pp(None) is None
        assert M.format_pp(None, "n/a") is None
        assert M.format_pp(float("nan")) is None

    def test_display_without_unit_gets_pp(self):
        assert M.format_pp(None, "+2.0") == "+2.0 pp"

    def test_share_formatting(self):
        assert M.format_share(0.835) == "83.5%"
        assert M.format_share(0.835, "83.6%") == "83.6%"
        assert M.format_share(None, "n/a") is None


class TestPresent:
    def test_headline_is_verbatim(self):
        mix = present_mix()
        assert M.state(mix)["headline"] == mix["headline"]

    def test_cards_are_upmarket_plus_one_per_pair(self):
        mix = present_mix()
        cards = M.state(mix)["cards"]
        assert len(cards) == 1 + len(mix["migration"])
        assert cards[0]["value_display"] == mix["upmarket_share"]["mrr_share_display"]
        assert cards[0]["variance_display"] == mix["upmarket_share"]["change_vs_12m_ago_display"]
        for card, pair in zip(cards[1:], mix["migration"]):
            assert card["label"] == pair["pair_label"]
            assert card["value_display"] == pair["velocity_trailing_12m_display"]
            assert card["variance_display"] == pair["velocity_change_vs_year_ago_display"]
            assert pair["velocity_trailing_12m_year_ago_display"] in card["comparison_display"]

    def test_cards_are_neutral_and_carry_basis_and_no_layer(self):
        for c in M.state(present_mix())["cards"]:
            assert "favorable_direction" not in c and "is_ahead" not in c and "pillar" not in c
            assert any(line.startswith("Basis: ") for line in c["footer"])
            assert not any("Layer" in line for line in c["footer"])

    def test_migration_footer_has_graduated_share_and_trailing_basis(self):
        mix = present_mix()
        card = M.state(mix)["cards"][1]
        pair = mix["migration"][0]
        assert any(pair["graduated_share_of_source_mrr_trailing_12m_display"] in l and "SMB MRR" in l for l in card["footer"])
        assert f"Basis: Trailing 12 months to {mix['evaluation_month'][:7]}" in card["footer"]

    def test_rows_earliest_first_and_sum_to_one(self):
        rows = M.state(present_mix())["rows"]
        assert len(rows) == 2 and rows[0]["label"] < rows[1]["label"]
        for r in rows:
            assert sum(r["shares"].values()) == pytest.approx(1.0)
            assert list(r["shares"]) == ["SMB", "Commercial", "Enterprise"]

    def test_missing_year_ago_share_drops_the_comparison_row_and_change(self):
        mix = present_mix()
        for s in mix["segments"]:
            s["mrr_share_12m_ago"] = None
            s["share_change_vs_12m_ago"] = None
            s["share_change_vs_12m_ago_display"] = "n/a"
        up = mix["upmarket_share"]
        up["mrr_share_12m_ago"] = up["change_vs_12m_ago"] = None
        up["change_vs_12m_ago_display"] = "n/a"
        s = M.state(mix)
        assert len(s["rows"]) == 1 and s["change_line"] is None
        assert "variance_display" not in s["cards"][0]
        assert s["cards"][0]["comparison_display"] == M.NO_COMPARISON

    def test_pair_without_velocity_is_not_computable(self):
        mix = present_mix()
        p = mix["migration"][0]
        p["velocity_trailing_12m"] = None
        p["velocity_trailing_12m_display"] = "n/a"
        card = M.state(mix)["cards"][1]
        assert card["value_display"] == "Not computable" and "variance_display" not in card

    def test_notes_carry_the_section_caveats(self):
        mix = present_mix()
        notes = M.state(mix)["notes"]
        assert all(k in ("Scope", "Data gap") for k, _ in notes)
        texts = [t for _, t in notes]
        for c in mix["caveats"]:
            assert c in texts
        assert any("only moves accounts up" in t for t in texts)
        assert any("final month of the data window" in t for t in texts)

    def test_non_reconciling_section_adds_a_data_gap(self):
        mix = present_mix()
        mix["reconciliation"]["reconciles"] = False
        assert ("Data gap", "Graduated MRR does not reconcile to the growth bridge within tolerance.") in M.state(mix)["notes"]


class TestUnavailableAndAbsent:
    def test_unavailable_shows_reason_and_no_figures(self):
        s = M.state(unavailable_mix())
        assert s["kind"] == "unavailable"
        assert s["reason_text"] == "The evaluation month is the final month of the data window."
        assert "cards" not in s and "rows" not in s and "headline" not in s
        assert s["evaluation_month"] == "2025-12"

    def test_unavailable_without_detail_maps_the_code(self):
        mix = unavailable_mix()
        del mix["detail"]
        assert "truncated" in M.state(mix)["reason_text"]
        mix["reason"] = "unmapped_code"
        assert "_" not in M.state(mix)["reason_text"]

    def test_unavailable_still_carries_the_caveat_notes(self):
        assert ("Scope", "A caveat.") in M.state(unavailable_mix())["notes"]

    def test_absent_when_no_section(self):
        assert M.state(None)["kind"] == "absent"
        assert M.state({})["kind"] == "absent"

    def test_present_status_without_usable_figures_is_shown_as_unavailable(self):
        s = M.state({"status": "present", "evaluation_month": "2025-11-01", "segments": [], "migration": []})
        assert s["kind"] == "unavailable"


@pytest.mark.parametrize("path", PATHS)
def test_committed_readouts(path):
    mix = json.load(open(path))["segment_mix"]
    s = M.state(mix)
    assert s["kind"] == mix["status"]
    if mix["status"] == "present":
        assert s["headline"] == mix["headline"]
        assert len(s["cards"]) == 3


class TestWave10aQaFixes:
    @pytest.mark.parametrize("shares", [
        {"SMB": 0.12149514, "Commercial": 0.19149518, "Enterprise": 0.68700968},   # independent rounding: 99.9
        {"SMB": 0.1735, "Commercial": 0.1815, "Enterprise": 0.645},
        {"SMB": 0.3333, "Commercial": 0.3333, "Enterprise": 0.3334},
        {"SMB": 0.2005, "Commercial": 0.2005, "Enterprise": 0.599},
    ])
    def test_share_labels_sum_to_exactly_100(self, shares):
        out = M.share_labels(shares)
        assert round(sum(float(v.rstrip("%")) for v in out.values()), 1) == 100.0
        for k, v in shares.items():
            assert abs(float(out[k].rstrip("%")) - v * 100) < 0.1 + 1e-9

    def test_every_committed_bar_sums_to_100(self):
        for path in PATHS:
            mix = json.load(open(path))["segment_mix"]
            for row in M.stacked_rows(mix):
                assert round(sum(float(v.rstrip("%")) for v in row["labels"].values()), 1) == 100.0

    def test_partial_composition_is_rounded_independently(self):
        assert M.share_labels({"A": 0.123, "B": 0.456}) == {"A": "12.3%", "B": "45.6%"}

    def test_graduated_footer_says_it_is_a_flow_over_the_average_base(self):
        card = M.migration_card(present_mix(), present_mix()["migration"][0])
        line = next(f for f in card["footer"] if f.startswith("Graduated MRR"))
        assert "of average SMB MRR over the window" in line and "flow, not share of current MRR" in line

    def test_visible_line_explains_why_mrr_share_exceeds_account_share(self):
        lines = M.mrr_vs_account_lines(present_mix())
        assert len(lines) == 2
        assert "carry about 6.2x the MRR of the average SMB account" in lines[0]
        assert "exceeds the account migration rate (10.7%)" in lines[0]
        assert "59.8% of ending SMB MRR" in lines[0]

    def test_pair_without_the_multiple_gets_no_line(self):
        mix = present_mix()
        del mix["migration"][0]["migrating_account_mrr_multiple_trailing_12m"]
        assert len(M.mrr_vs_account_lines(mix)) == 1

    def test_upmarket_card_carries_the_total_mrr_share_of_graduations(self):
        footer = M.upmarket_card(present_mix())["footer"]
        assert any("SMB to Commercial graduations" in f and "7.3% of company ending MRR" in f for f in footer)

    def test_every_readout_caveat_reaches_the_notes_as_a_scope_line(self):
        mix = present_mix()
        scope = [t for k, t in M.notes(mix) if k == "Scope"]
        assert len(mix["caveats"]) == 6
        for caveat in mix["caveats"]:
            assert caveat in scope
