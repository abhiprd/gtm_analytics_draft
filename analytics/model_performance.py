"""Model-performance logging for Phase 4 analytics artifacts.

Upserts checkpoint rows into data/model_performance_history.csv -- the
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
    """Upserts one checkpoint row, keyed on (model_name, as_of_date,
    metric_name) -- the same composite key fact_model_performance_history
    is tested unique on. Re-running a build/backtest for a checkpoint that
    already has a row replaces its value rather than appending a
    duplicate; this isn't optional per-caller behavior, since a caller
    that forgets to check produces a real dbt test failure (this happened
    once already -- analytics-model-builder's first health-score run
    logged the same checkpoint twice before this upsert was added).
    """
    key = (model_name, as_of_date_.isoformat(), metric_name)
    rows = read_performance_history()
    rows = [r for r in rows if (r["model_name"], r["as_of_date"], r["metric_name"]) != key]
    rows.append({
        "model_name": model_name,
        "as_of_date": as_of_date_.isoformat(),
        "metric_name": metric_name,
        "metric_value": metric_value,
    })

    with open(_CSV_PATH, "w", newline="") as f:
        # lineterminator="\n": csv's default is "\r\n", which produced a
        # file with mixed line endings against a plain-"\n" header --
        # DuckDB's CSV dialect sniffer can't parse that mix. Every row
        # (header included) must use the same ending.
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(_COLUMNS)
        for r in rows:
            writer.writerow([r["model_name"], r["as_of_date"], r["metric_name"], r["metric_value"]])


def read_performance_history():
    """Full history as a list of dicts -- a thin convenience reader for
    Python callers (drift-monitor, analytics-model-validator) that don't
    need a DuckDB connection just to check a metric.
    """
    if not os.path.exists(_CSV_PATH):
        return []
    with open(_CSV_PATH, newline="") as f:
        return list(csv.DictReader(f))
