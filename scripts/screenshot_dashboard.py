#!/usr/bin/env python3
"""Capture a screenshot of the running quant-desk dashboard for visual verification.

The dashboard is a fetch()-driven single page, so a plain HTTP GET only returns the
empty shell — you need a real browser to render the panels. This drives headless
Chromium (Playwright), waits for the API-backed panels to populate, and writes a PNG.

Playwright is intentionally NOT a project dependency (it would pollute the trading
venv's requirements). It lives in an isolated tooling venv; run this script with that
interpreter:

    ~/.qd-tools/bin/python scripts/screenshot_dashboard.py
    ~/.qd-tools/bin/python scripts/screenshot_dashboard.py --selector '#gate' -o /tmp/gate.png

One-time setup of the tooling venv:

    python3 -m venv ~/.qd-tools && ~/.qd-tools/bin/pip install playwright
    ~/.qd-tools/bin/playwright install chromium
"""
from __future__ import annotations

import argparse
import sys


def capture(url: str, out: str, selector: str | None, width: int, height: int,
            settle_ms: int) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright not found — run this with the tooling venv: "
                 "~/.qd-tools/bin/python (see module docstring for setup)")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height},
                                device_scale_factor=2)
        page.goto(url, wait_until="networkidle", timeout=20000)
        page.wait_for_timeout(settle_ms)  # let the fetch()-driven panels render
        target = page.query_selector(selector) if selector else None
        if target is not None:
            target.screenshot(path=out)                 # element crop
        else:
            page.screenshot(path=out, full_page=True)   # whole page
        browser.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Screenshot the quant-desk dashboard.")
    ap.add_argument("--url", default="http://127.0.0.1:8800/", help="dashboard URL")
    ap.add_argument("-o", "--out", default="/tmp/qd_dashboard.png", help="output PNG path")
    ap.add_argument("--selector", default=None,
                    help="CSS selector to crop to (e.g. '#gate'); default = full page")
    ap.add_argument("--width", type=int, default=1400)
    ap.add_argument("--height", type=int, default=2200)
    ap.add_argument("--settle-ms", type=int, default=1200,
                    help="ms to wait after load for client-side panels to render")
    a = ap.parse_args()
    path = capture(a.url, a.out, a.selector, a.width, a.height, a.settle_ms)
    print(f"screenshot written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
