"""Smoke check for the dashboard, run by dashboard/.venv's interpreter.

Renders the home page and every page under dashboard/pages/ headless with
Streamlit's AppTest harness and fails if any page raises. This checks that
the pages still run against the current marts and readout JSON, not how they
look (dashboard-visual-qa owns that).
"""
import glob
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASHBOARD = os.path.join(REPO_ROOT, "dashboard")


def main() -> int:
    from streamlit.testing.v1 import AppTest

    os.chdir(REPO_ROOT)
    pages = sorted(glob.glob(os.path.join(DASHBOARD, "pages", "*.py")))
    failures = 0

    def check(label: str, at) -> None:
        nonlocal failures
        errors = [str(e.value) for e in at.exception]
        if errors:
            failures += 1
            print(f"[FAIL] {label}: {errors[0][:300]}")
        elif len(at.main) == 0:
            failures += 1
            print(f"[FAIL] {label}: rendered no elements")
        else:
            print(f"[PASS] {label}: {len(at.main)} top-level elements")

    # Pages are driven through the entrypoint (as Streamlit does), because
    # the Digest links to its sibling pages by path relative to app.py.
    at = AppTest.from_file(os.path.join(DASHBOARD, "app.py"), default_timeout=180).run()
    check("dashboard/app.py", at)
    for path in pages:
        rel = os.path.relpath(path, DASHBOARD)
        check(f"dashboard/{rel}", at.switch_page(rel).run())
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
