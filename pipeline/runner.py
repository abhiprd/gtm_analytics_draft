"""Execution of a selected node list: resolve the interpreter, run each node
as a subprocess, time it, fail fast, and write a machine-readable manifest.

Run manifests are written under pipeline/runs/ (gitignored): they carry
wall-clock timestamps, durations and per-machine interpreter paths, all of
which differ on every run and would churn a tracked file. CI uploads the
directory as a build artifact instead.

Exit codes (shared with pipeline/cli.py):
  0  every selected node passed (or was skipped without --strict)
  1  a node failed; later nodes are reported not_run
  2  invalid invocation or DAG error (raised before anything runs)
  3  --strict and at least one node was skipped
"""
from __future__ import annotations

import glob as _glob
import json
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from .dag import Node, Selection

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIR = os.path.join(REPO_ROOT, "pipeline", "runs")

EXIT_OK = 0
EXIT_NODE_FAILED = 1
EXIT_USAGE = 2
EXIT_STRICT_SKIP = 3

_VENV_PYTHON = {
    "semantic": os.path.join(REPO_ROOT, "semantic", ".venv", "bin", "python"),
    "dashboard": os.path.join(REPO_ROOT, "dashboard", ".venv", "bin", "python"),
}

# Nodes that produce each required path, for an actionable precondition error.
_PRODUCER = {"data/acme_gtm.duckdb": "dbt_build"}


@dataclass
class NodeResult:
    name: str
    status: str  # passed | failed | skipped | not_run | planned
    seconds: float = 0.0
    exit_code: Optional[int] = None
    reason: str = ""
    log: str = ""
    argv: List[str] = field(default_factory=list)
    interpreter: str = "root"


def interpreter_path(kind: str) -> Optional[str]:
    """Absolute interpreter for a node, or None when its virtualenv is absent."""
    if kind == "root":
        return sys.executable
    path = _VENV_PYTHON[kind]
    return path if os.path.isfile(path) and os.access(path, os.X_OK) else None


def resolve_argv(node: Node, python: str) -> List[str]:
    """Substitute {python} and expand {glob:...} tokens."""
    out: List[str] = []
    for tok in node.argv:
        if tok == "{python}":
            out.append(python)
        elif tok.startswith("{glob:") and tok.endswith("}"):
            pattern = tok[len("{glob:"):-1]
            matches = sorted(os.path.relpath(p, REPO_ROOT)
                             for p in _glob.glob(os.path.join(REPO_ROOT, pattern)))
            if not matches:
                raise FileNotFoundError(f"{node.name}: glob {pattern!r} matched nothing")
            out.extend(matches)
        else:
            out.append(tok)
    return out


def skip_reason(node: Node) -> Optional[str]:
    """Why a node cannot run on this machine, or None. A missing virtualenv
    is an explicit skip, never a silent pass."""
    if node.interpreter != "root" and interpreter_path(node.interpreter) is None:
        rel = os.path.relpath(_VENV_PYTHON[node.interpreter], REPO_ROOT)
        return f"venv missing: {rel} (see {node.interpreter}/README.md)"
    return None


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                              text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _tail(path: str, n: int = 25) -> str:
    try:
        with open(path, errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError:
        return ""


def describe(node: Node) -> Dict[str, object]:
    """Planning view of one node: what `plan` prints and records."""
    reason = skip_reason(node)
    py = interpreter_path(node.interpreter)
    try:
        argv = resolve_argv(node, py or "<" + node.interpreter + " python>")
    except FileNotFoundError as e:
        argv = [str(e)]
    return {
        "name": node.name, "kind": node.kind, "deps": list(node.deps),
        "interpreter": node.interpreter, "cwd": node.cwd, "argv": argv,
        "as_of": list(node.as_of), "mutates": list(node.mutates),
        "opt_in": node.opt_in, "will_skip": reason,
        "description": node.description,
    }


def execute(selection: Selection, *, strict: bool = False, runs_dir: str = RUNS_DIR,
            out=None) -> int:
    """Run `selection` in order, stop at the first failure, write the
    manifest, and return the process exit code."""
    out = out or sys.stdout
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_dir = os.path.join(runs_dir, run_id)
    os.makedirs(log_dir, exist_ok=True)
    started = time.time()
    results: List[NodeResult] = []
    failed: Optional[NodeResult] = None

    def say(msg: str) -> None:
        print(msg, file=out, flush=True)

    total = len(selection.order)
    say(f"pipeline run {run_id}: {total} node(s), profile={selection.profile}"
        f"{', with generators' if selection.with_generators else ''}")

    for i, node in enumerate(selection.order, 1):
        tag = f"[{i}/{total}] {node.name}"
        if failed is not None:
            results.append(NodeResult(node.name, "not_run",
                                      reason=f"upstream failure: {failed.name}",
                                      interpreter=node.interpreter))
            continue
        reason = skip_reason(node)
        if reason:
            results.append(NodeResult(node.name, "skipped", reason=reason,
                                      interpreter=node.interpreter))
            say(f"{tag}  SKIPPED  {reason}")
            continue
        python = interpreter_path(node.interpreter)
        log_path = os.path.join(log_dir, f"{node.name}.log")
        res = NodeResult(node.name, "failed", log=os.path.relpath(log_path, REPO_ROOT),
                         interpreter=node.interpreter)
        try:
            argv = resolve_argv(node, python)
        except FileNotFoundError as e:
            res.reason = str(e)
            results.append(res)
            failed = res
            say(f"{tag}  FAILED   {res.reason}")
            continue
        res.argv = argv
        missing = [p for p in node.requires if not os.path.exists(os.path.join(REPO_ROOT, p))]
        if missing:
            producer = _PRODUCER.get(missing[0])
            res.reason = (f"precondition: {missing[0]} missing"
                          + (f" (produced by node {producer})" if producer else ""))
            results.append(res)
            failed = res
            say(f"{tag}  FAILED   {res.reason}")
            continue

        say(f"{tag}  running ...")
        t0 = time.time()
        env = dict(os.environ)
        try:
            with open(log_path, "w") as logf:
                proc = subprocess.run(argv, cwd=os.path.join(REPO_ROOT, node.cwd),
                                      stdout=logf, stderr=subprocess.STDOUT, env=env,
                                      timeout=node.timeout_s)
            res.exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            res.exit_code = None
            res.reason = f"timed out after {node.timeout_s}s"
        except OSError as e:
            res.reason = f"could not start: {e}"
        res.seconds = round(time.time() - t0, 2)

        if not res.reason and res.exit_code == 0:
            hit = _matches_fail_pattern(log_path, node.fail_patterns, node.expected_fail)
            if hit:
                res.reason = f"output reported a failed check: {hit.strip()[:160]}"
            else:
                res.status = "passed"
        elif not res.reason:
            res.reason = f"exit code {res.exit_code}"

        results.append(res)
        if res.status == "passed":
            say(f"{tag}  passed   {res.seconds:.1f}s")
        else:
            failed = res
            say(f"{tag}  FAILED   {res.seconds:.1f}s  {res.reason}")
            tail = _tail(log_path)
            if tail:
                say(f"--- last lines of {res.log} ---\n{tail.rstrip()}\n--- end ---")

    skipped = [r for r in results if r.status == "skipped"]
    code = EXIT_OK
    if failed is not None:
        code = EXIT_NODE_FAILED
    elif strict and skipped:
        code = EXIT_STRICT_SKIP

    manifest = {
        "run_id": run_id,
        "started_at_utc": datetime.fromtimestamp(started, timezone.utc).isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.time() - started, 2),
        "exit_code": code,
        "profile": selection.profile,
        "with_generators": selection.with_generators,
        "only": list(selection.only), "from": list(selection.from_),
        "with_deps": selection.with_deps, "strict": strict,
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "python": sys.version.split()[0], "platform": platform.platform(),
        "counts": {s: sum(1 for r in results if r.status == s)
                   for s in ("passed", "failed", "skipped", "not_run")},
        "nodes": [r.__dict__ for r in results],
    }
    manifest_path = os.path.join(runs_dir, f"{run_id}.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(runs_dir, "latest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    c = manifest["counts"]
    say("")
    say(f"summary: {c['passed']} passed, {c['failed']} failed, {c['skipped']} skipped, "
        f"{c['not_run']} not run in {manifest['duration_seconds']:.1f}s "
        f"-> {os.path.relpath(manifest_path, REPO_ROOT)}")
    if failed is not None:
        say(f"FAILED NODE: {failed.name} -- {failed.reason} (log: {failed.log})")
        not_run = [r.name for r in results if r.status == "not_run"]
        if not_run:
            say(f"not run: {', '.join(not_run)}")
    for r in skipped:
        say(f"SKIPPED: {r.name} -- {r.reason}")
    if code == EXIT_STRICT_SKIP:
        say("--strict: skipped nodes are treated as failures")
    return code


def _matches_fail_pattern(path: str, patterns: Sequence[str],
                          expected: Sequence[str] = ()) -> Optional[str]:
    """First output line matching a fail pattern that is not a documented,
    expected finding."""
    if not patterns:
        return None
    compiled = [re.compile(p) for p in patterns]
    allowed = [re.compile(p) for p in expected]
    with open(path, errors="replace") as f:
        for line in f:
            if any(c.search(line) for c in compiled) and not any(a.search(line) for a in allowed):
                return line
    return None
