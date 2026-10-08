"""Key-dtype alignment in analytics/forecast.py's point-in-time feature builder.

Before the first forecast submission the submissions frame is empty, and an empty DuckDB result
arrives as object dtype while the deal frame's `opportunity_id` carries the string dtype.
pandas 2 merges across the two; pandas 3 raises MergeError. `_align_key_dtype` casts the right
frame's key to the evaluation frame's dtype before each `merge_asof`.

  * Pure-pandas tests need no database: the helper on empty, populated and already-aligned
    frames, and a `merge_asof` reproduction of the failing shape.
  * Database tests build the point-in-time features at dates with no submission yet and at
    dates with many, on the interpreter running the suite.
  * The subprocess test runs the same call under the dashboard environment (Python 3.12,
    pandas 3) and is skipped when that environment is absent.

Run: python3 -m pytest tests/test_phase4_forecast_key_dtype.py -v
"""
import json
import os
import subprocess
import sys
from datetime import date

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from analytics import forecast as fc  # noqa: E402

DB_PATH = os.path.join(ROOT, "data", "acme_gtm.duckdb")
needs_db = pytest.mark.skipif(
    not os.path.exists(DB_PATH), reason="dbt-built database not present; run `cd dbt && dbt build`")
DASHBOARD_PY = os.path.join(ROOT, "dashboard", ".venv", "bin", "python")


def _left(ids):
    return pd.DataFrame({
        "opportunity_id": pd.Series(ids, dtype="string"),
        "eval_date": pd.to_datetime(["2023-01-03"] * len(ids)).astype("datetime64[ns]"),
    })


def _right_empty_object():
    """The shape DuckDB hands back for a query with no rows."""
    return pd.DataFrame({
        "opportunity_id": pd.Series([], dtype="object"),
        "snapshot_date": pd.to_datetime(pd.Series([], dtype="object")).astype("datetime64[ns]"),
        "rep_forecast_rank": pd.Series([], dtype="float64"),
    })


class TestHelper:
    def test_an_empty_object_key_is_cast_to_the_left_frames_dtype(self):
        left = _left(["opp_1", "opp_2"])
        out = fc._align_key_dtype(_right_empty_object(), left, "opportunity_id")
        assert out["opportunity_id"].dtype == left["opportunity_id"].dtype
        assert len(out) == 0

    def test_the_empty_frame_merges_and_leaves_every_deal_unmatched(self):
        left = _left(["opp_1", "opp_2"])
        right = fc._align_key_dtype(_right_empty_object(), left, "opportunity_id")
        merged = pd.merge_asof(left, right, left_on="eval_date", right_on="snapshot_date",
                               by="opportunity_id", direction="backward")
        assert list(merged["opportunity_id"]) == ["opp_1", "opp_2"]
        assert merged["rep_forecast_rank"].isna().all()
        assert merged["snapshot_date"].isna().all()

    def test_a_populated_key_of_the_same_dtype_is_returned_untouched(self):
        left = _left(["opp_1"])
        right = pd.DataFrame({
            "opportunity_id": pd.Series(["opp_1"], dtype="string"),
            "snapshot_date": pd.to_datetime(["2023-01-02"]).astype("datetime64[ns]"),
            "rep_forecast_rank": [3.0],
        })
        out = fc._align_key_dtype(right, left, "opportunity_id")
        assert out is right
        merged = pd.merge_asof(left, out, left_on="eval_date", right_on="snapshot_date",
                               by="opportunity_id", direction="backward")
        assert merged["rep_forecast_rank"].iloc[0] == 3.0

    def test_values_survive_the_cast(self):
        left = _left(["opp_1"])
        right = pd.DataFrame({
            "opportunity_id": pd.Series(["opp_1", "opp_9"], dtype="object"),
            "snapshot_date": pd.to_datetime(["2023-01-02", "2023-01-01"]).astype("datetime64[ns]"),
            "rep_forecast_rank": [3.0, 7.0],
        })
        out = fc._align_key_dtype(right, left, "opportunity_id")
        assert list(out["opportunity_id"]) == ["opp_1", "opp_9"]
        assert list(out["rep_forecast_rank"]) == [3.0, 7.0]
        assert right["opportunity_id"].dtype == object, "the caller's frame must not be mutated"

    def test_the_failing_shape_is_a_real_error_only_without_the_alignment(self):
        """On pandas 3 the unaligned merge raises; on pandas 2 it does not. Either way the
        aligned merge works, which is the property the fix is for."""
        left = _left(["opp_1"])
        right = _right_empty_object()
        if int(pd.__version__.split(".")[0]) >= 3:
            with pytest.raises(pd.errors.MergeError):
                pd.merge_asof(left, right, left_on="eval_date", right_on="snapshot_date",
                              by="opportunity_id", direction="backward")
        aligned = fc._align_key_dtype(right, left, "opportunity_id")
        pd.merge_asof(left, aligned, left_on="eval_date", right_on="snapshot_date",
                      by="opportunity_id", direction="backward")


@needs_db
class TestFeaturesBeforeTheFirstSubmission:
    def test_the_precondition_holds_no_submission_exists_at_the_early_date(self):
        data = fc.load_all(date(2023, 1, 3))
        assert len(data["submissions"]) == 0

    @pytest.mark.parametrize("d", [date(2023, 1, 3), date(2022, 6, 15)])
    def test_the_rollup_runs_where_no_submission_exists_yet(self, d):
        data = fc.load_all(d)
        roll = fc.bottoms_up_rollup(data, pd.Timestamp(d), d, lens="manager")
        assert "deals" in roll

    def test_submission_columns_are_empty_for_every_deal_before_the_first_call(self):
        d = date(2023, 1, 3)
        data = fc.load_all(d)
        population = fc.open_period_population(data, pd.Timestamp(d))
        assert len(population) > 0
        frame = fc.build_point_in_time_features(population, data)
        assert len(frame) == len(population)
        assert frame["rep_forecast_rank"].isna().all()
        assert frame["snapshot_date"].isna().all()

    def test_deals_with_submissions_still_pick_up_the_latest_one_on_or_before(self):
        d = date(2025, 11, 14)
        data = fc.load_all(d)
        population = fc.open_period_population(data, pd.Timestamp(d))
        frame = fc.build_point_in_time_features(population, data)
        assert frame["snapshot_date"].notna().any()
        assert (frame["snapshot_date"].dropna() <= pd.Timestamp(d)).all()


@needs_db
@pytest.mark.skipif(not os.path.exists(DASHBOARD_PY), reason="dashboard/.venv not present")
class TestDashboardInterpreter:
    CODE = """
import json, sys
sys.path.insert(0, %r)
from datetime import date
import pandas as pd
from analytics import forecast as fc
from analytics import pipeline_coverage as pc
out = {"pandas": pd.__version__}
for d in (date(2023, 1, 3), date(2022, 6, 15)):
    data = fc.load_all(d)
    roll = fc.bottoms_up_rollup(data, pd.Timestamp(d), d, lens="manager")
    out["rollup_" + d.isoformat()] = int(len(roll["deals"]))
    out["reconciliation_" + d.isoformat()] = pc.run_pipeline_coverage(d)["reconciliation"]["status"]
r = fc.run_forecast(date(2025, 11, 14))
out["forecast_rows"] = int(len(r["reconciliation"]))
print(json.dumps(out))
""" % ROOT

    def test_the_pandas_3_environment_builds_features_before_the_first_submission(self):
        proc = subprocess.run([DASHBOARD_PY, "-c", self.CODE], cwd=ROOT, capture_output=True,
                              text=True, timeout=600)
        assert proc.returncode == 0, proc.stderr[-1000:]
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        assert out["pandas"].split(".")[0] == "3"
        assert out["reconciliation_2023-01-03"] == "present"
        assert out["reconciliation_2022-06-15"] == "present"
        assert out["rollup_2023-01-03"] >= 0
        assert out["forecast_rows"] > 0
