"""Render a dashboard page and save a full-page screenshot to a PNG.

Usage: dashboard/.venv/bin/python dashboard/scripts/screenshot.py <url> <out_path.png> [--width 1280] [--wait 1500]

The Streamlit dev server must already be running (this script does not
start one). Meant to be called from Bash by dashboard-page-builder /
dashboard-visual-qa, since neither agent has a dedicated browser tool --
this is the "check for a scripts/ or tools/ directory before building a
new render harness" render harness dashboard-design-conventions.md
Section [process] points to.
"""
import argparse
import sys

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("out_path")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--wait", type=int, default=1500, help="ms to wait after load for Streamlit to finish rendering")
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        page.goto(args.url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(args.wait)
        page.screenshot(path=args.out_path, full_page=True)
        browser.close()

    print(f"Saved {args.out_path}")


if __name__ == "__main__":
    sys.exit(main())
