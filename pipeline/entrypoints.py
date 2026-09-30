"""Command-line adapters for analytics modules that have no `__main__` of
their own. The node's argv is `python3 -m pipeline.entrypoints NAME AS_OF`;
each adapter calls the module's existing importable functions and prints
`[FAIL]` for any failed check, the convention the runner watches for.
"""
from __future__ import annotations

import sys
from datetime import date

from .common import parse_date


def deal_diagnostics(as_of: date) -> int:
    """analytics/deal_diagnostics.py is a library module: fit and log the
    risk model at `as_of` (run_deal_diagnostics logs to the performance
    history), then run its build-time validation checks."""
    from analytics import deal_diagnostics as dd
    result = dd.run_deal_diagnostics(as_of)
    print(f"deal_diagnostics as of {as_of}: {len(result['scored_deals'])} open deals scored")
    checks = dd.run_build_time_validation(as_of)
    for c in checks:
        print(f"[{'PASS' if c['passed'] else 'FAIL'}] {c['name']}: {c['detail']}")
    return 0


ENTRYPOINTS = {"deal_diagnostics": deal_diagnostics}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] not in ENTRYPOINTS:
        print(f"usage: python3 -m pipeline.entrypoints {{{'|'.join(ENTRYPOINTS)}}} YYYY-MM-DD",
              file=sys.stderr)
        return 2
    return ENTRYPOINTS[argv[0]](parse_date(argv[1]))


if __name__ == "__main__":
    sys.exit(main())
