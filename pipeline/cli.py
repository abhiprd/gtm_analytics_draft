"""`python3 -m pipeline` command line.

  run              execute the DAG (default profile: verify the dataset on disk)
  plan             print what `run` would execute, in order, with no side effects
  gate             governance enforcement: nonzero exit on any failed check
  check-freshness  evaluate pipeline/freshness_contract.json against disk

Exit codes: 0 ok, 1 a node/check failed, 2 invalid invocation or DAG error,
3 --strict with skipped nodes.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import freshness, gate, runner
from .common import parse_date
from .dag import DagError, VALID_PROFILES, select
from .nodes import NODES


def _add_selection_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--profile", default="verify", choices=VALID_PROFILES,
                   help="named node set (default: verify -- the verify-the-world path; "
                        "ci: the fast subset CI runs; rebuild: the raw-data generators)")
    p.add_argument("--with-generators", action="store_true",
                   help="also regenerate data/raw (overwrites tracked files) before verifying")
    p.add_argument("--only", action="append", default=[], metavar="NODE",
                   help="run NODE and its required upstream (repeatable)")
    p.add_argument("--no-deps", action="store_true",
                   help="with --only: run exactly the named node(s), not their upstream")
    p.add_argument("--from", dest="from_", action="append", default=[], metavar="NODE",
                   help="run NODE and everything downstream of it (repeatable)")


def _selection(args):
    return select(NODES, profile=args.profile, with_generators=args.with_generators,
                  only=args.only, from_=args.from_, with_deps=not args.no_deps)


def _print_plan(selection, as_json: bool, out=None) -> None:
    out = out or sys.stdout
    rows = [runner.describe(n) for n in selection.order]
    if as_json:
        print(json.dumps({"profile": selection.profile,
                          "with_generators": selection.with_generators,
                          "nodes": rows}, indent=2), file=out)
        return
    print(f"plan: {len(rows)} node(s), profile={selection.profile}"
          f"{', with generators' if selection.with_generators else ''}", file=out)
    w = max(len(r["name"]) for r in rows)
    names = {r["name"] for r in rows}
    for i, r in enumerate(rows, 1):
        extra = []
        if r["as_of"]:
            extra.append("as_of " + ",".join(r["as_of"]))
        if r["interpreter"] != "root":
            extra.append(f"{r['interpreter']} venv")
        if r["will_skip"]:
            extra.append("WOULD SKIP: " + r["will_skip"])
        present = [d for d in r["deps"] if d in names]
        after = ", ".join(present) if len(present) <= 5 else f"{len(present)} upstream nodes"
        print(f"{i:>3}. {r['name'].ljust(w)}  {r['kind']:<10} after [{after}]"
              + (f"  ({'; '.join(extra)})" if extra else ""), file=out)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python3 -m pipeline", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="execute the DAG")
    _add_selection_args(run)
    run.add_argument("--dry-run", action="store_true", help="print the plan and exit; no side effects")
    run.add_argument("--strict", action="store_true",
                     help="treat skipped nodes (missing venv) as failures (exit 3)")

    plan = sub.add_parser("plan", help="print the execution order; no side effects")
    _add_selection_args(plan)
    plan.add_argument("--json", action="store_true", help="machine-readable plan")
    plan.add_argument("--all", action="store_true", help="list every node regardless of profile")

    g = sub.add_parser("gate", help="governance enforcement point")
    g.add_argument("--check", choices=("all", "identity", "registry"), default="all",
                   help="identity: metric-tree/marts/invariant checks; registry: "
                        "semantic registry vs the tree (default: both)")
    g.add_argument("--as-of", help="evaluation date (default: dataset horizon)")
    g.add_argument("--strict-stamp", action="store_true",
                   help="also fail when the registry's tree-hash stamp lags identical content")

    f = sub.add_parser("check-freshness", help="evaluate the freshness contract")
    f.add_argument("--as-of", help="reference date (default: dataset horizon in dbt_project.yml)")
    f.add_argument("--artifact", action="append", default=[], help="limit to one artifact (repeatable)")
    f.add_argument("--json", action="store_true", help="machine-readable result")
    f.add_argument("--contract", default=freshness.CONTRACT_PATH, help=argparse.SUPPRESS)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd in ("run", "plan"):
            if args.cmd == "plan" and args.all:
                from .dag import Selection, topological_order
                sel = Selection(tuple(topological_order(NODES)), "all", True)
            else:
                sel = _selection(args)
            if args.cmd == "plan" or args.dry_run:
                _print_plan(sel, getattr(args, "json", False))
                return 0
            return runner.execute(sel, strict=args.strict)
        if args.cmd == "gate":
            as_of = parse_date(args.as_of) if args.as_of else None
            return gate.run_gate(args.check, as_of, args.strict_stamp)
        if args.cmd == "check-freshness":
            ref = parse_date(args.as_of) if args.as_of else freshness.default_reference()
            contract = freshness.load_contract(args.contract)
            results = freshness.evaluate(contract, ref, only=args.artifact or None)
            if args.json:
                print(json.dumps(freshness.to_json(results, ref), indent=2))
            else:
                print(freshness.render(results, ref))
            return freshness.exit_code(results)
    except (DagError, freshness.ContractError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return runner.EXIT_USAGE
    return runner.EXIT_USAGE
