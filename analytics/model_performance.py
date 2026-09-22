"""Model-performance logging for Phase 4 analytics artifacts.

Appends checkpoint rows to data/model_performance_history.csv -- the
version-controlled source of truth for fact_model_performance_history
(dbt reads this CSV as an external source; see dbt/models/staging/
_sources.yml). Never write directly into data/acme_gtm.duckdb -- that
file is gitignored and gets rebuilt from scratch, so anything written
only there is lost on the next clean `dbt build`.

Used by analytics-model-builder (build-time), analytics-model-validator
(build-time check), and drift-monitor (recurring backtests) -- any Phase 4
code computing a model's accuracy/error metric against its stated target
in docs/acme-corp-analytics-methods.md logs it here.
"""
import csv
import os
from datetime import date

_CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "model_performance_history.csv")
_COLUMNS = ["model_name", "as_of_date", "metric_name", "metric_value"]


def log_performance(model_name: str, as_of_date_: date, metric_name: str, metric_value: float) -> None:
    """Appends one checkpoint row. Idempotency is the caller's job -- if
    re-running a backtest for an (as_of_date, metric_name) pair that
    already has a row, decide whether to skip or intentionally duplicate;
    this function always appends.
    """
    is_new_file = not os.path.exists(_CSV_PATH)
    with open(_CSV_PATH, "a", newline="") as f:
        # lineterminator="\n": csv's default is "\r\n", which produced a
        # file with mixed line endings against the plain-"\n" header this
        # file starts with -- DuckDB's CSV dialect sniffer can't parse
        # that mix. Every row (header included) must use the same ending.
        writer = csv.writer(f, lineterminator="\n")
        if is_new_file:
            writer.writerow(_COLUMNS)
        writer.writerow([model_name, as_of_date_.isoformat(), metric_name, metric_value])


def read_performance_history():
    """Full history as a list of dicts -- a thin convenience reader for
    Python callers (drift-monitor, analytics-model-validator) that don't
    need a DuckDB connection just to check a metric.
    """
    if not os.path.exists(_CSV_PATH):
        return []
    with open(_CSV_PATH, newline="") as f:
        return list(csv.DictReader(f))
