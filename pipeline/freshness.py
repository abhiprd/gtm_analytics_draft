"""Freshness contract: load pipeline/freshness_contract.json, read each
artifact's evidence off disk, and report fresh / stale / missing.

Stdlib only (duckdb is imported lazily, and only for the dbt-marts
evidence). See pipeline/README.md for what each field means and how the
SLAs were derived.

Staleness of one artifact = (basis date) - (latest evidence date), in days,
floored at 0 (evidence newer than the basis is fresh, not negative). The
artifact is stale when that exceeds `max_staleness_days`, and missing when
no evidence exists at all. Every evidence source of an artifact is checked;
the artifact takes its worst state.

Basis dates, derived from the reference date R (`--as-of`, default: the
dataset horizon in dbt_project.yml, not wall-clock today):
  horizon              R itself.
  last_complete_month  the last day of the month before R's month. Used by
                       artifacts that evaluate a whole month and so can only
                       be run once it has closed -- and whose canonical
                       checkpoint is the last representative month, because
                       the simulation's final month carries an end-of-window
                       truncation artifact.
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .common import DB_PATH, REPO_ROOT, dataset_horizon, parse_date

CONTRACT_PATH = os.path.join(REPO_ROOT, "pipeline", "freshness_contract.json")

FRESH, STALE, MISSING = "fresh", "stale", "missing"

# A contract's SLA may not be tighter than the cadence it promises: an
# artifact refreshed monthly cannot be held to a 7-day staleness limit.
CADENCE_MIN_DAYS = {"per_build": 0, "weekly": 7, "monthly": 28, "quarterly": 89,
                    "event_driven": 0}
BASES = ("horizon", "last_complete_month")
EVIDENCE_TYPES = ("perf_log", "output_files", "csv_max", "duckdb_max", "json_field",
                  "registry_current")
KINDS = ("analytics", "raw_data", "dbt_marts", "log", "semantic_registry", "dashboard_input")
REQUIRED_FIELDS = ("name", "kind", "owner", "cadence", "basis", "max_staleness_days",
                   "depends_on", "evidence", "fresh_means", "sla_rationale")

_DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")


class ContractError(ValueError):
    """The contract file itself is malformed."""


# --------------------------------------------------------------------------
# contract loading and validation
# --------------------------------------------------------------------------

def load_contract(path: str = CONTRACT_PATH) -> Dict[str, Any]:
    with open(path) as f:
        contract = json.load(f)
    validate_contract(contract)
    return contract


def validate_contract(contract: Dict[str, Any]) -> None:
    artifacts = contract.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ContractError("contract has no artifacts")
    names = [a.get("name") for a in artifacts]
    if len(set(names)) != len(names):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise ContractError(f"duplicate artifact name(s): {dupes}")
    for a in artifacts:
        for k in REQUIRED_FIELDS:
            if k not in a:
                raise ContractError(f"{a.get('name')}: missing field {k!r}")
        if a["kind"] not in KINDS:
            raise ContractError(f"{a['name']}: unknown kind {a['kind']!r}")
        if a["cadence"] not in CADENCE_MIN_DAYS:
            raise ContractError(f"{a['name']}: unknown cadence {a['cadence']!r}")
        if a["basis"] not in BASES:
            raise ContractError(f"{a['name']}: unknown basis {a['basis']!r}")
        sla = a["max_staleness_days"]
        if not isinstance(sla, int) or sla < 0:
            raise ContractError(f"{a['name']}: max_staleness_days must be a non-negative integer")
        if sla < CADENCE_MIN_DAYS[a["cadence"]]:
            raise ContractError(
                f"{a['name']}: SLA {sla}d is tighter than its {a['cadence']} cadence "
                f"({CADENCE_MIN_DAYS[a['cadence']]}d)")
        if not a["evidence"]:
            raise ContractError(f"{a['name']}: no evidence sources")
        for ev in a["evidence"]:
            if ev.get("type") not in EVIDENCE_TYPES:
                raise ContractError(f"{a['name']}: unknown evidence type {ev.get('type')!r}")
        for field_ in ("owner", "fresh_means", "sla_rationale"):
            if not str(a[field_]).strip():
                raise ContractError(f"{a['name']}: empty {field_}")
    known = set(names)
    for a in artifacts:
        for d in a["depends_on"]:
            if d not in known:
                raise ContractError(f"{a['name']}: depends_on unknown artifact {d!r}")


# --------------------------------------------------------------------------
# reference dates
# --------------------------------------------------------------------------

def basis_date(basis: str, reference: date) -> date:
    if basis == "horizon":
        return reference
    if basis == "last_complete_month":
        return reference.replace(day=1) - timedelta(days=1)
    raise ContractError(f"unknown basis {basis!r}")


# --------------------------------------------------------------------------
# evidence readers: each returns (latest_date | None, detail)
# --------------------------------------------------------------------------

def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value.date() if hasattr(value, "date") else value
    text = str(value).strip()
    return parse_date(text[:10]) if text else None


def _read_perf_log(spec: Dict[str, Any], root: str):
    path = os.path.join(root, spec.get("path", "data/model_performance_history.csv"))
    if not os.path.exists(path):
        return None, f"{os.path.relpath(path, root)} not found"
    latest, n = None, 0
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row["model_name"] == spec["model_name"]:
                d = _to_date(row["as_of_date"])
                n += 1
                latest = d if latest is None or d > latest else latest
    if latest is None:
        return None, f"no rows for model_name={spec['model_name']!r}"
    return latest, f"{n} logged metrics for {spec['model_name']}"


def _read_output_files(spec: Dict[str, Any], root: str):
    files = sorted(glob.glob(os.path.join(root, spec["glob"])))
    latest, latest_file = None, None
    for p in files:
        m = _DATE_IN_NAME.search(os.path.basename(p))
        if m and os.path.getsize(p) > 0:
            d = parse_date(m.group(1))
            if latest is None or d > latest:
                latest, latest_file = d, p
    if latest is None:
        return None, f"no non-empty files matching {spec['glob']}"
    return latest, os.path.relpath(latest_file, root)


def _read_csv_max(spec: Dict[str, Any], root: str):
    path = os.path.join(root, spec["path"])
    if not os.path.exists(path):
        return None, f"{spec['path']} not found"
    latest = None
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            d = _to_date(row.get(spec["column"]))
            if d is not None and (latest is None or d > latest):
                latest = d
    if latest is None:
        return None, f"{spec['path']} has no values in column {spec['column']!r}"
    return latest, f"max({spec['path']}:{spec['column']})"


def _read_duckdb_max(spec: Dict[str, Any], root: str):
    path = os.path.join(root, spec.get("db", "data/acme_gtm.duckdb"))
    if not os.path.exists(path):
        return None, "data/acme_gtm.duckdb not found (run the dbt_build node)"
    import duckdb
    con = duckdb.connect(path, read_only=True)
    try:
        value = con.execute(
            f"select max({spec['column']}) from {spec['table']}").fetchone()[0]
    except duckdb.Error as e:
        return None, f"{spec['table']}.{spec['column']}: {str(e).splitlines()[0]}"
    finally:
        con.close()
    return _to_date(value), f"max({spec['table']}.{spec['column']})"


def _read_json_field(spec: Dict[str, Any], root: str):
    path = os.path.join(root, spec["path"])
    if not os.path.exists(path):
        return None, f"{spec['path']} not found"
    with open(path) as f:
        node: Any = json.load(f)
    for part in spec["field"].split("."):
        if not isinstance(node, dict) or part not in node:
            return None, f"{spec['path']} has no field {spec['field']!r}"
        node = node[part]
    return _to_date(node), f"{spec['path']}:{spec['field']}"


_READERS = {
    "perf_log": _read_perf_log, "output_files": _read_output_files,
    "csv_max": _read_csv_max, "duckdb_max": _read_duckdb_max,
    "json_field": _read_json_field,
}


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------

@dataclass
class EvidenceResult:
    source: str
    latest: Optional[date]
    staleness_days: Optional[int]
    state: str
    detail: str = ""


@dataclass
class ArtifactResult:
    name: str
    kind: str
    cadence: str
    sla_days: int
    basis: str
    basis_date: date
    state: str
    worst_staleness_days: Optional[int]
    evidence: List[EvidenceResult] = field(default_factory=list)


def _evidence_label(spec: Dict[str, Any]) -> str:
    return spec.get("label") or spec.get("model_name") or spec.get("glob") or \
        spec.get("path") or spec.get("table") or spec["type"]


def evaluate_artifact(artifact: Dict[str, Any], reference: date,
                      root: Optional[str] = None, registry_check=None) -> ArtifactResult:
    root = root or REPO_ROOT
    basis = basis_date(artifact["basis"], reference)
    sla = artifact["max_staleness_days"]
    results: List[EvidenceResult] = []
    for spec in artifact["evidence"]:
        label = _evidence_label(spec)
        if spec["type"] == "registry_current":
            report = (registry_check or _default_registry_check)()
            results.append(EvidenceResult(
                label, None, 0 if report.passed else None,
                FRESH if report.passed else STALE,
                "; ".join(report.info + report.warnings
                          + [f"{f.name}: {f.detail}" for f in report.findings])))
            continue
        try:
            latest, detail = _READERS[spec["type"]](spec, root)
        except Exception as e:  # unreadable evidence is missing evidence
            latest, detail = None, f"{type(e).__name__}: {e}"
        if latest is None:
            results.append(EvidenceResult(label, None, None, MISSING, detail))
            continue
        stale_days = max(0, (basis - latest).days)
        results.append(EvidenceResult(
            label, latest, stale_days, STALE if stale_days > sla else FRESH, detail))
    states = [r.state for r in results]
    state = MISSING if MISSING in states else STALE if STALE in states else FRESH
    days = [r.staleness_days for r in results if r.staleness_days is not None]
    return ArtifactResult(artifact["name"], artifact["kind"], artifact["cadence"], sla,
                          artifact["basis"], basis, state, max(days) if days else None,
                          results)


def _default_registry_check():
    from . import gate
    return gate.check_registry()


def evaluate(contract: Dict[str, Any], reference: date, root: Optional[str] = None,
             only: Optional[List[str]] = None, registry_check=None) -> List[ArtifactResult]:
    arts = contract["artifacts"]
    if only:
        unknown = set(only) - {a["name"] for a in arts}
        if unknown:
            raise ContractError(f"unknown artifact(s): {sorted(unknown)}")
        arts = [a for a in arts if a["name"] in only]
    return [evaluate_artifact(a, reference, root, registry_check) for a in arts]


def exit_code(results: List[ArtifactResult]) -> int:
    return 0 if all(r.state == FRESH for r in results) else 1


def render(results: List[ArtifactResult], reference: date) -> str:
    w = max(len(r.name) for r in results)
    lines = [f"freshness as of {reference.isoformat()} "
             f"({sum(r.state == FRESH for r in results)} fresh, "
             f"{sum(r.state == STALE for r in results)} stale, "
             f"{sum(r.state == MISSING for r in results)} missing "
             f"of {len(results)})",
             f"{'artifact'.ljust(w)}  state    age/SLA (days)  oldest evidence"]
    for r in results:
        age = "-" if r.worst_staleness_days is None else str(r.worst_staleness_days)
        dates = [e.latest.isoformat() for e in r.evidence if e.latest]
        lines.append(f"{r.name.ljust(w)}  {r.state.upper().ljust(7)}  "
                     f"{(age + '/' + str(r.sla_days)).ljust(14)}  "
                     f"{min(dates) if dates else '-'}")
        if r.state != FRESH:
            for e in r.evidence:
                if e.state != FRESH:
                    lines.append(f"{' ' * w}    -> {e.state}: {e.source}: {e.detail}")
    return "\n".join(lines)


def to_json(results: List[ArtifactResult], reference: date) -> Dict[str, Any]:
    return {
        "reference_date": reference.isoformat(),
        "ok": exit_code(results) == 0,
        "artifacts": [{
            "name": r.name, "kind": r.kind, "cadence": r.cadence, "state": r.state,
            "sla_days": r.sla_days, "basis": r.basis, "basis_date": r.basis_date.isoformat(),
            "worst_staleness_days": r.worst_staleness_days,
            "evidence": [{"source": e.source, "state": e.state,
                          "latest": e.latest.isoformat() if e.latest else None,
                          "staleness_days": e.staleness_days, "detail": e.detail}
                         for e in r.evidence],
        } for r in results],
    }


def default_reference() -> date:
    return dataset_horizon()
