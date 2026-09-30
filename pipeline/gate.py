"""Enforcement point for the governance checks: runs them and converts
their result into an exit code.

analytics/data_quality_governance.py already computes the metric-tree
identity checks, the marts data-quality checks and the CLAUDE.md invariant
checks, but its entrypoint prints a verdict and exits 0 either way. This
module is the thing a build fails on.

Two independent checks, selectable with `--check`:

  identity  Re-runs data_quality_governance.run_build_time_validation with
            log=False and write_report=False (read-only: no tracked file
            changes) and fails on any failed metric-tree edge, marts
            data-quality check, or invariant, or if the module's own
            synthetic self-check (does it still catch a known-broken case?)
            no longer passes.
  registry  semantic/metric_registry.json is current against
            docs/acme-corp-gtm-metric-tree.md. The registry stamps the
            tree's SHA-256, but build_registry.py only rewrites the file
            when the *parsed* content changes, so a prose-only tree edit
            legitimately leaves the stamp behind. Staleness is therefore
            determined by content: if the stamp differs, the tree is re-parsed
            with build_registry.build_registry() and the file is stale only
            when the regenerated content hash differs. A stamp that lags
            behind identical content is reported as a warning (and fails
            under --strict-stamp).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from .common import DB_PATH, REPO_ROOT, dataset_horizon

TREE_PATH = os.path.join(REPO_ROOT, "docs", "acme-corp-gtm-metric-tree.md")
REGISTRY_PATH = os.path.join(REPO_ROOT, "semantic", "metric_registry.json")
BUILD_REGISTRY_PATH = os.path.join(REPO_ROOT, "semantic", "build_registry.py")

REGENERATE_HINT = "regenerate with: semantic/.venv/bin/python semantic/build_registry.py"


@dataclass
class Finding:
    family: str
    name: str
    detail: str = ""


@dataclass
class GateReport:
    check: str
    findings: List[Finding] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings


# --------------------------------------------------------------------------
# identity (governance module)
# --------------------------------------------------------------------------

def run_governance(as_of: date) -> Dict[str, Any]:
    """The governance module's own end-to-end run, read-only."""
    from analytics import data_quality_governance as dqg
    return dqg.run_build_time_validation(as_of, log=False, write_report=False)


def _failed_rows(df) -> List[str]:
    """Names of failing rows in one of the governance module's per-check
    DataFrames (`passed` column plus a label column)."""
    if df is None or len(df) == 0:
        return []
    bad = df[~df["passed"].astype(bool)]
    label = next((c for c in ("check", "name", "check_name", "table", "scenario")
                  if c in bad.columns), None)
    return [str(r[label]) if label else str(i) for i, r in bad.iterrows()]


def judge_governance(result: Dict[str, Any]) -> GateReport:
    """Turn a run_build_time_validation result into a verdict. Pure, so a
    deliberately broken result can be unit-tested without touching data."""
    report = GateReport("identity")
    tree = result["metric_tree_integrity"]
    for e in tree["computed_edges"]:
        if not e["result"]["passed"]:
            report.findings.append(Finding(
                "metric_tree_identity", e["edge_id"],
                f"{e['parent']}: {e['formula']} (max_abs_diff={e['result'].get('max_abs_diff')})"))
    dq = result["marts_data_quality"]
    for key in ("referential_integrity", "completeness", "distributional_sanity",
                "volume_sufficiency"):
        for name in _failed_rows(dq.get(key)):
            report.findings.append(Finding(f"marts_data_quality/{key}", name))
    inv = result["invariant_governance"]["checks"]
    for name, chk in inv.items():
        if not chk["passed"]:
            report.findings.append(Finding("invariant", name, str(chk.get("detail", ""))[:200]))
    syn = result["synthetic_validation"]
    if not syn["all_pass"]:
        for r in syn["results"]:
            if not r["matches_expectation"]:
                report.findings.append(Finding(
                    "synthetic_self_check", r["scenario"],
                    "governance module no longer catches a known-broken case"))
    s = result["summary"]
    report.info.append(
        f"{s['checks_passed']} of {s['checks_total']} governance checks pass; "
        f"{tree['edges_checked']} metric-tree edges checked "
        f"({tree['edges_not_computable']} not computable, "
        f"{tree['edges_validated_elsewhere']} validated elsewhere); "
        f"synthetic self-check {syn['n_scenarios']} scenarios")
    return report


def check_identity(as_of: date, runner=None) -> GateReport:
    if not os.path.exists(DB_PATH):
        r = GateReport("identity")
        r.findings.append(Finding("precondition", "marts_missing",
                                  "data/acme_gtm.duckdb not found; run the dbt_build node first"))
        return r
    return judge_governance((runner or run_governance)(as_of))


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

def _sha256_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return hashlib.sha256(f.read().encode("utf-8")).hexdigest()


def _load_build_registry(tree_path: str, build_path: str):
    spec = importlib.util.spec_from_file_location("_acme_build_registry", build_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._TREE_PATH = tree_path
    return mod


def check_registry(strict_stamp: bool = False, tree_path: str = TREE_PATH,
                   registry_path: str = REGISTRY_PATH,
                   build_path: str = BUILD_REGISTRY_PATH) -> GateReport:
    report = GateReport("registry")
    if not os.path.exists(registry_path):
        report.findings.append(Finding("registry", "missing", REGENERATE_HINT))
        return report
    with open(registry_path, encoding="utf-8") as f:
        registry = json.load(f)
    tree_sha = _sha256_text(tree_path)
    stamped = registry.get("source_tree_sha256")
    version = registry.get("registry_version")
    if stamped == tree_sha:
        report.info.append(f"registry v{version} is stamped with the current tree hash "
                           f"({tree_sha[:12]})")
        return report
    try:
        fresh = _load_build_registry(tree_path, build_path).build_registry()
    except Exception as e:  # the tree no longer parses into a valid registry
        report.findings.append(Finding(
            "registry", "tree_does_not_parse",
            f"tree hash {tree_sha[:12]} != stamp {str(stamped)[:12]} and the tree "
            f"no longer parses: {e}. {REGENERATE_HINT}"))
        return report
    if fresh["content_sha256"] == registry.get("content_sha256"):
        msg = (f"registry v{version} stamp {str(stamped)[:12]} lags the tree hash "
               f"{tree_sha[:12]}, but re-parsing the tree yields identical registry content")
        if strict_stamp:
            report.findings.append(Finding("registry", "stamp_lag", msg))
        else:
            report.warnings.append(msg)
        return report
    report.findings.append(Finding(
        "registry", "stale",
        f"registry v{version} no longer matches the tree: stamp {str(stamped)[:12]} vs "
        f"tree {tree_sha[:12]}, and the regenerated content differs. {REGENERATE_HINT}"))
    return report


# --------------------------------------------------------------------------
# presentation
# --------------------------------------------------------------------------

def render(report: GateReport) -> str:
    lines = [f"gate[{report.check}]: {'PASS' if report.passed else 'FAIL'}"]
    lines.extend(f"  {i}" for i in report.info)
    lines.extend(f"  warning: {w}" for w in report.warnings)
    for f in report.findings:
        lines.append(f"  FAIL [{f.family}] {f.name}" + (f" -- {f.detail}" if f.detail else ""))
    return "\n".join(lines)


def run_gate(check: str = "all", as_of: Optional[date] = None,
             strict_stamp: bool = False, out=None) -> int:
    """Run the selected checks, print each verdict, return 0/1."""
    import sys
    out = out or sys.stdout
    reports: List[GateReport] = []
    if check in ("identity", "all"):
        reports.append(check_identity(as_of or dataset_horizon()))
    if check in ("registry", "all"):
        reports.append(check_registry(strict_stamp=strict_stamp))
    for r in reports:
        print(render(r), file=out)
    return 0 if all(r.passed for r in reports) else 1
