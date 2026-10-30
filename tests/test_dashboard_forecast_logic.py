"""Forecast display rules (dashboard/lib/forecast_logic.py)."""
import os
import sys
from datetime import date

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from dashboard.lib import forecast_logic as F  # noqa: E402


def seg(**over):
    base = dict(segment="Commercial", bottoms_up_rep=1000.0, bottoms_up_manager=1100.0, ml=1200.0,
                cro_adjusted=1300.0, open_pipeline_amount=5000.0)
    base.update(over)
    return base


class TestReadoutComparison:
    def test_identical_rows_produce_no_findings(self):
        assert F.compare_to_readout([seg()], [seg()], "2025-11-30") == []

    def test_ml_difference_within_one_percent_is_informational(self):
        f = F.compare_to_readout([seg(ml=1205.0)], [seg(ml=1200.0)], "2025-11-30")
        assert [x["severity"] for x in f] == ["info"]
        assert "ML lens differs by 0.4%" in f[0]["text"] and "rebuilds" in f[0]["text"]

    def test_ml_difference_beyond_one_percent_is_a_warning(self):
        f = F.compare_to_readout([seg(ml=1300.0)], [seg(ml=1200.0)], "2025-11-30")
        assert [x["severity"] for x in f] == ["warning"]

    def test_non_ml_lens_has_near_zero_tolerance(self):
        f = F.compare_to_readout([seg(bottoms_up_rep=1000.5)], [seg()], "2025-11-30")
        assert f == []                                    # under $1
        f = F.compare_to_readout([seg(bottoms_up_rep=1010.0)], [seg()], "2025-11-30")
        assert [x["severity"] for x in f] == ["warning"] and f[0]["lens"] == "bottoms_up_rep"

    def test_text_is_plain_language_with_formatted_values(self):
        f = F.compare_to_readout([seg(cro_adjusted=1500000.0)], [seg(cro_adjusted=1400000.0)], "2025-11-30")
        text = f[0]["text"]
        assert "$1.50M" in text and "$1.40M" in text and "CRO-adjusted" in text and "7.1%" in text
        assert "cro_adjusted" not in text and "1500000" not in text

    def test_missing_segments_are_warnings_both_ways(self):
        f = F.compare_to_readout([seg(segment="Enterprise")], [seg()], "2025-11-30")
        assert {x["severity"] for x in f} == {"warning"} and len(f) == 2

    def test_value_missing_on_one_side_is_a_warning(self):
        f = F.compare_to_readout([seg(ml=None)], [seg()], "2025-11-30")
        assert f and f[0]["severity"] == "warning" and "not computable" in f[0]["text"]


class TestAucPosition:
    @pytest.mark.parametrize("auc,pos", [(0.65, "below"), (0.70, "within"), (0.80, "within"),
                                         (0.85, "within"), (0.8578, "above")])
    def test_position(self, auc, pos):
        assert F.auc_position(auc, 0.70, 0.85) == pos

    def test_phrase_names_the_position(self):
        assert F.auc_statement(0.8578, 0.70, 0.85)[1] == "above the 0.70–0.85 target range"
        assert F.auc_statement(0.65, 0.70, 0.85)[1] == "below the 0.70–0.85 target range"
        assert F.auc_statement(0.8, 0.70, 0.85)[1] == "within the 0.70–0.85 target range"


class TestLateQuarter:
    def test_note_when_the_headline_exceeds_open_pipeline(self):
        row = seg(cro_adjusted=126785.5, open_pipeline_amount=38511.39)
        assert F.lens_exceeds_pipeline(row)
        note = F.late_quarter_note(row, 3)
        assert "$126.8K" not in note and "$38.5K" in note and "3.3x" in note and "3 days" in note

    def test_no_note_otherwise(self):
        assert F.late_quarter_note(seg(), 33) is None

    def test_days_to_quarter_end(self):
        assert F.days_to_quarter_end("2025-Q2", date(2025, 6, 27)) == 3
        assert F.days_to_quarter_end("2025-Q4", date(2025, 11, 28)) == 33
        assert F.days_to_quarter_end("garbage", date(2025, 11, 28)) is None


from dashboard.lib import formatting as fmt  # noqa: E402


class TestMonthsPrecision:
    @pytest.mark.parametrize("v,expected", [(1.64, "1.6"), (12.0, "12.0"), (0.06, "0.06"), (0.5, "0.50"),
                                            (0.004, "<0.01"), (0.0, "0.0"), (-0.3, "-0.30")])
    def test_months(self, v, expected):
        assert fmt.months(v) == expected

    def test_a_non_zero_value_never_prints_as_zero(self):
        for v in (0.0051, 0.01, 0.049, 0.06):
            assert fmt.months(v) not in ("0.0", "0.00")


# ---------------------------------------------------------------------------
# Lens dot plot axis
# ---------------------------------------------------------------------------
class TestLensAxis:
    def test_a_non_negative_quantity_never_gets_an_axis_below_zero(self):
        lo, hi = F.lens_axis([100_000.0, 3_000_000.0])
        assert lo == 0.0 and hi > 3_000_000.0

    def test_a_tight_cluster_gets_a_fitted_axis_that_does_not_start_at_zero(self):
        lo, hi = F.lens_axis([1.13e6, 1.32e6, 1.33e6, 1.36e6])
        assert 0 < lo < 1.13e6 and hi > 1.36e6

    def test_caption_follows_the_axis_actually_drawn(self):
        assert "starts at zero" in F.axis_caption(0.0)
        assert "does not start at zero" in F.axis_caption(1_072_500.0)
        assert "includes zero" in F.axis_caption(-112_500.0)

    def test_ticks_are_round_inside_the_range_and_use_one_k_m_casing(self):
        lo, hi = F.lens_axis([1.13e6, 1.32e6, 1.33e6, 1.36e6])
        ticks = F.nice_ticks(lo, hi)
        assert ticks and all(lo <= t <= hi for t in ticks)
        assert [F.fmt_usd(t) for t in ticks] == ["$1.10M", "$1.20M", "$1.30M", "$1.40M"]
        small = [F.fmt_usd(t) for t in F.nice_ticks(*F.lens_axis([120e3, 380e3]))]
        assert all(t.endswith("K") and "k" not in t for t in small)
