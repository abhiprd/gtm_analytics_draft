"""The Digest's ranked "What changed" bar (dashboard/lib/whatchanged_view.py): order,
judgment color, the caveated rule, labels and the table-view twin, on the committed readouts."""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from dashboard.lib import verdict, whatchanged_view as W  # noqa: E402

OUT = os.path.join(REPO, "analytics", "outputs")


def readout(d):
    with open(os.path.join(OUT, f"weekly_readout_{d}.json")) as f:
        return json.load(f)


def rows_for(d):
    r = readout(d)
    caveated = {x["metric_key"] for x in r["layer1_scorecard"]["rows"] if verdict.is_caveated(x)}
    return r, W.rows(r["drilldowns"]["entries"], caveated)


@pytest.mark.parametrize("d", ["2025-06-30", "2025-11-30"])
class TestCommittedReadouts:
    def test_one_row_per_drilldown_ranked_by_absolute_gap(self, d):
        r, rs = rows_for(d)
        assert len(rs) == r["drilldowns"]["count"]
        gaps = [abs(x["gap"]) for x in rs]
        assert gaps == sorted(gaps, reverse=True)
        assert [x["rank"] for x in rs] == list(range(1, len(rs) + 1))

    def test_caveated_rows_are_neutral_whatever_their_status(self, d):
        r, rs = rows_for(d)
        caveated = {x["metric_key"] for x in r["layer1_scorecard"]["rows"] if verdict.is_caveated(x)}
        for x in rs:
            if x["metric_key"] in caveated:
                assert x["kind"] == W.NEUTRAL and x["caveated"]
            else:
                assert x["kind"] in (W.FAVORABLE, W.UNFAVORABLE)

    def test_judged_bars_carry_a_status_word_and_neutral_bars_do_not(self, d):
        _, rs = rows_for(d)
        for x in rs:
            if x["kind"] == W.FAVORABLE:
                assert x["bar_label"] == f'{x["gap_display"]} Ahead'
            elif x["kind"] == W.UNFAVORABLE:
                assert x["bar_label"] == f'{x["gap_display"]} Behind'
            else:
                assert x["bar_label"] == x["gap_display"]

    def test_the_bar_direction_matches_the_displayed_sign(self, d):
        _, rs = rows_for(d)
        for x in rs:
            assert (x["gap"] > 0) == x["gap_display"].startswith("+"), x["metric_key"]

    def test_table_twin_has_every_value_the_chart_shows(self, d):
        _, rs = rows_for(d)
        table = W.table_rows(rs)
        assert [t["Metric"] for t in table] == [x["label"] for x in rs]
        assert [t["Gap"] for t in table] == [x["gap_display"] for x in rs]
        assert all(t["Layer-2 outlier"] for t in table)

    def test_axis_names_the_plan_basis(self, d):
        _, rs = rows_for(d)
        assert W.axis_title(rs) == W.AXIS_TITLE_PLAN


def entry(key, gap, status, mechanism="plan_diff"):
    return {"layer1": {"metric_key": key, "label": key, "pillar": "growth", "layer": 1, "variance_pct": gap,
                       "variance_display": "n/a" if gap is None else f"{gap * 100:+.1f}%", "status": status, "mechanism": mechanism},
            "layer2_outlier": None, "persistence": None}


def test_an_entry_without_a_numeric_gap_is_left_out():
    e = entry("a", None, "Ahead")
    assert W.rows([e], set()) == []


def test_a_non_plan_mechanism_changes_the_axis_title():
    rs = W.rows([entry("a", 0.2, "Ahead", mechanism="trailing_baseline")], set())
    assert W.axis_title(rs) == W.AXIS_TITLE_OTHER


def test_caveat_note_counts_marked_tiles_and_is_absent_when_there_are_none():
    assert W.caveat_note(0, 11) is None
    assert "7 of 11 tiles" in W.caveat_note(7, 11)


# ---------------------------------------------------------------------------
# Figure spec (dashboard/lib/whatchanged_figure.py)
# ---------------------------------------------------------------------------
from dashboard.lib import whatchanged_figure as F  # noqa: E402
from dashboard import tokens as T  # noqa: E402


@pytest.mark.parametrize("d", ["2025-06-30", "2025-11-30"])
class TestFigureSpec:
    def fig(self, d):
        _, rs = rows_for(d)
        return rs, F.figure(rs)

    def test_bars_are_at_most_24px_thick_with_a_4px_rounded_end(self, d):
        rs, fig = self.fig(d)
        bar = fig.data[0]
        assert bar.type == "bar" and bar.orientation == "h"
        assert bar.width * F.ROW_PX <= 24
        assert bar.marker.cornerradius == 4 == T.RADIUS_MARK
        assert (bar.marker.line.width or 0) == 0  # no border drawn around a mark
        assert fig.layout.height == F.ROW_PX * len(rs) + 56

    def test_bar_colors_follow_the_judgment_and_caveated_bars_are_gray(self, d):
        rs, fig = self.fig(d)
        assert list(fig.data[0].marker.color) == [F.BAR_COLOR[r["kind"]] for r in rs]
        assert {F.BAR_COLOR[W.NEUTRAL]} == {c for r, c in zip(rs, fig.data[0].marker.color) if r["caveated"]}

    def test_labels_are_the_bar_labels_placed_right_of_each_bars_end(self, d):
        rs, fig = self.fig(d)
        labels = fig.data[1]
        assert list(labels.text) == [r["bar_label"] for r in rs]
        for r, x in zip(rs, labels.x):
            assert x > max(r["gap"], 0.0)  # clear of the bar end; a negative bar's label clears the zero line
        assert labels.textposition == "middle right"

    def test_axis_leaves_room_for_the_longest_label_and_names_the_basis(self, d):
        rs, fig = self.fig(d)
        lo, hi = fig.layout.xaxis.range
        gaps = [r["gap"] for r in rs]
        assert lo < min(gaps + [0.0]) and hi > max(gaps)
        assert (hi - max(gaps)) / (max(gaps + [0.0]) - min(gaps + [0.0])) >= F.RIGHT_PAD - 1e-9
        assert fig.layout.xaxis.title.text == W.AXIS_TITLE_PLAN
        assert fig.layout.xaxis.zeroline is True

    def test_largest_gap_on_top_no_legend_solid_hairline_grid(self, d):
        rs, fig = self.fig(d)
        assert fig.layout.yaxis.autorange == "reversed"
        assert fig.layout.showlegend is False
        assert fig.layout.xaxis.gridcolor == T.GRID_LINE and (fig.layout.xaxis.griddash in (None, "solid"))
