"""log_performance() upserts in place: re-running a checkpoint neither
duplicates its rows nor moves them, so re-running an artifact over
unchanged inputs leaves data/model_performance_history.csv byte-identical.
Runs against a temp copy of the log, never the real one.
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics import model_performance as mp  # noqa: E402


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "model_performance_history.csv"
    monkeypatch.setattr(mp, "_CSV_PATH", str(path))
    return path


def _seed(d1=date(2025, 6, 30), d2=date(2025, 12, 31)):
    mp.log_performance("a", d1, "m1", 1.0)
    mp.log_performance("b", d1, "m1", 2.0)
    mp.log_performance("a", d2, "m1", 3.0)
    mp.log_performance("a", d2, "m2", 4.0)


def test_rerunning_a_checkpoint_with_the_same_values_is_byte_identical(log):
    _seed()
    before = log.read_bytes()
    _seed()
    assert log.read_bytes() == before


def test_rerun_replaces_the_value_without_moving_or_duplicating_the_row(log):
    _seed()
    mp.log_performance("a", date(2025, 6, 30), "m1", 9.5)
    rows = mp.read_performance_history()
    assert [(r["model_name"], r["as_of_date"], r["metric_name"], r["metric_value"]) for r in rows] == [
        ("a", "2025-06-30", "m1", "9.5"), ("b", "2025-06-30", "m1", "2.0"),
        ("a", "2025-12-31", "m1", "3.0"), ("a", "2025-12-31", "m2", "4.0")]


def test_new_checkpoint_appends(log):
    _seed()
    mp.log_performance("c", date(2025, 12, 31), "m1", 5.0)
    assert mp.read_performance_history()[-1]["model_name"] == "c"
    assert len(mp.read_performance_history()) == 5


def test_preexisting_duplicates_collapse_to_the_first_position(log):
    log.write_text("model_name,as_of_date,metric_name,metric_value\n"
                   "a,2025-06-30,m1,1.0\nb,2025-06-30,m1,2.0\na,2025-06-30,m1,1.5\n")
    mp.log_performance("a", date(2025, 6, 30), "m1", 7.0)
    rows = mp.read_performance_history()
    assert [(r["model_name"], r["metric_value"]) for r in rows] == [("a", "7.0"), ("b", "2.0")]
