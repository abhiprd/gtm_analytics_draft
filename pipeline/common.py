"""Shared paths and the dataset's reference date (stdlib only)."""
from __future__ import annotations

import os
import re
from datetime import date

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DBT_PROJECT = os.path.join(REPO_ROOT, "dbt", "dbt_project.yml")
DB_PATH = os.path.join(REPO_ROOT, "data", "acme_gtm.duckdb")


def parse_date(text: str) -> date:
    """YYYY-MM-DD -> date, with a message that names the bad input."""
    try:
        return date.fromisoformat(text.strip())
    except ValueError as e:
        raise ValueError(f"not an ISO date (YYYY-MM-DD): {text!r}") from e


def dataset_horizon() -> date:
    """The dataset's final day: dbt_project.yml's `analysis_as_of_date` var,
    the one place the project already states it. Wall-clock today() would
    measure a frozen simulation against time it never simulated."""
    with open(DBT_PROJECT) as f:
        m = re.search(r'^\s*analysis_as_of_date:\s*["\']?(\d{4}-\d{2}-\d{2})', f.read(), re.M)
    if not m:
        raise RuntimeError("dbt/dbt_project.yml has no analysis_as_of_date var")
    return parse_date(m.group(1))
