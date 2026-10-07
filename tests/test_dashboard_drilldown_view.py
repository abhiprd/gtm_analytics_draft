"""Drill-down ranking tables (dashboard/lib/drilldown_view.py): the caption states the basis the
rank was computed on, a row with no data shows a dash instead of a rank, and an additive-basis
table carries the absolute change it was ranked on. Also run against the committed readouts."""
import glob
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from dashboard.lib import drilldown_view as D  # noqa: E402

PATHS = sorted(glob.glob(os.path.join(REPO, "analytics", "outputs", "weekly_readout_*.json")))


def row(key="sm_cost", value=10.0, baseline=8.0, dev=0.25, absdev=2.0, rank=1, basis=D.BASIS_RELATIVE):
    return {"metric_key": key, "label": key, "value": value, "baseline": baseline, "deviation_pct": dev,
            "absolute_deviation": absdev, "rank": rank, "comparison_basis": basis, "deviation_display": "+25.0%"}


class TestRankDash:
    def test_a_row_with_data_shows_its_rank(self):
        assert D.rank_cell(row(rank=2)) == "2"

    def test_a_row_without_a_value_shows_a_dash(self):
        assert D.rank_cell(row(value=None, dev=None, absdev=None, rank=3)) == D.NO_RANK == "—"

    def test_a_row_with_a_value_but_no_baseline_shows_a_dash(self):
        assert D.rank_cell(row(dev=None, absdev=None, rank=3)) == "—"

    def test_additive_rows_are_judged_on_the_absolute_deviation(self):
        assert D.rank_cell(row(basis=D.BASIS_ADDITIVE, dev=None, absdev=1.0, rank=1)) == "1"
        assert D.rank_cell(row(basis=D.BASIS_ADDITIVE, dev=0.2, absdev=None, rank=1)) == "—"

    def test_nan_counts_as_missing(self):
        assert D.rank_cell(row(value=float("nan"))) == "—"


class TestCaption:
    def test_relative_basis(self):
        assert D.caption([row()], 3) == "Layer-3 drivers ranked by deviation from their own trailing baseline:"

    def test_additive_dollar_basis(self):
        text = D.caption([row(basis=D.BASIS_ADDITIVE)], 3)
        assert "absolute dollar change" in text and "deviation from" not in text

    def test_additive_rate_basis(self):
        text = D.caption([row(key="nrr_expansion_rate", basis=D.BASIS_ADDITIVE)], 2)
        assert "absolute change in percentage points" in text and text.startswith("Layer-2")

    def test_default_is_relative(self):
        assert D.basis_of([]) == D.BASIS_RELATIVE and D.basis_of([{"metric_key": "x"}]) == D.BASIS_RELATIVE


class TestTable:
    def test_additive_table_has_a_change_column_and_relative_does_not(self):
        add = D.table_dict([row(basis=D.BASIS_ADDITIVE, absdev=22600.0)], lambda r: r["label"])
        rel = D.table_dict([row()], lambda r: r["label"])
        assert add["Change vs baseline"] == ["+$22.6K"] and "Change vs baseline" not in rel
        assert list(add)[-1] == "Rank"

    def test_change_cell_units_and_signs(self):
        assert D.change_cell(row(key="nrr_expansion_rate", absdev=-0.0123)) == "-1.2 pp"
        assert D.change_cell(row(absdev=-13400.0)) == "-$13.4K"
        assert D.change_cell(row(absdev=None)) == "n/a"

    def test_all_cells_are_strings_in_the_rank_column(self):
        cols = D.table_dict([row(rank=1), row(value=None, dev=None, absdev=None, rank=2)], lambda r: r["label"])
        assert cols["Rank"] == ["1", "—"]


@pytest.mark.parametrize("path", PATHS)
def test_committed_readouts_use_the_basis_their_rows_carry(path):
    entries = json.load(open(path))["drilldowns"]["entries"]
    seen_additive = False
    for e in entries:
        for name in ("sibling_ranking", "layer3_ranking"):
            rows = e.get(name) or []
            if not rows:
                continue
            assert len({r["comparison_basis"] for r in rows}) == 1
            cap = D.caption(rows, 3)
            if rows[0]["comparison_basis"] == D.BASIS_ADDITIVE:
                seen_additive = True
                assert "absolute" in cap
            else:
                assert "deviation from their own trailing baseline" in cap
            ranks = [D.rank_cell(r) for r in rows]
            for r, cell in zip(rows, ranks):
                if r.get("value") is None:
                    assert cell == "—"
    assert seen_additive, "the readout has additive-basis branches (NRR, GRR, Magic number legs)"
