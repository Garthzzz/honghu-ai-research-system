#!/usr/bin/env python
"""Weekly recruitment refresh: scrape, then classify, with fail-closed exit."""
from __future__ import annotations

import subprocess
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PYTHON = sys.executable
BEIJING = timezone(timedelta(hours=8))


def run(script: str) -> bool:
    print(f"\n=== {script} ===")
    base = os.environ.get("HONGHU_OPERATION_ID", "").strip()
    environment = dict(os.environ)
    if base:
        environment["HONGHU_OPERATION_ID"] = f"{base}:step:{Path(script).stem}"
    bootstrap = os.environ.get("HONGHU_RELEASE_BOOTSTRAP", "").strip()
    site_packages = os.environ.get("HONGHU_LOCKED_SITE_PACKAGES", "").strip()
    if not bootstrap or not site_packages:
        raise RuntimeError("exact-release child bootstrap contract is unavailable")
    module = f"tools.sentiment.{Path(script).stem}"
    completed = subprocess.run(
        [
            PYTHON, "-I", "-B", "-S", bootstrap,
            "--site-packages", site_packages,
            "--module", "tools.operations.task_child",
            "--task-module", module,
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5400,
        env=environment,
    )
    print((completed.stdout or "")[-1500:])
    if completed.returncode != 0:
        print("ERR:", (completed.stderr or "")[-400:])
    return completed.returncode == 0


def main() -> int:
    current = datetime.now(BEIJING)
    if current.weekday() >= 5:
        return 0

    from tools.data_platform.run_domain_operation import install_operation_context

    iso_year, iso_week, _ = current.isocalendar()
    install_operation_context(
        cutover_unit="sentiment_analytics",
        operation_scope="recruit_weekly",
        logical_window=f"{iso_year}-W{iso_week:02d}",
    )
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    scraped = run("recruit_scrape.py")
    classified = run("recruit_classify.py") if scraped else False
    if not scraped or not classified:
        print("\nrecruit weekly failed")
        return 2
    print("\nrecruit weekly complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
