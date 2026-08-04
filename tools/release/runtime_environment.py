from __future__ import annotations

"""Verify the isolated Python environment used by a read-only candidate."""

import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")


def lockfile_pins(path: str | Path) -> dict[str, str]:
    lock = Path(path).resolve()
    pins: dict[str, str] = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        match = PIN_RE.match(line.strip())
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    if not pins:
        raise ValueError(f"lockfile has no exact pins: {lock}")
    return pins


def verify_runtime(
    lockfile: str | Path,
    *,
    required_python: tuple[int, int] = (3, 10),
) -> dict[str, Any]:
    lock = Path(lockfile).resolve()
    failures: list[str] = []
    if sys.version_info[:2] != required_python:
        failures.append(
            f"Python {required_python[0]}.{required_python[1]} required; "
            f"found {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )
    pins = lockfile_pins(lock)
    installed: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = str(distribution.metadata.get("Name") or "").lower().replace("_", "-")
        if name:
            installed[name] = distribution.version
    mismatches: list[dict[str, str | None]] = []
    for name, expected in sorted(pins.items()):
        actual = installed.get(name)
        if actual != expected:
            mismatches.append({"package": name, "expected": expected, "actual": actual})
    if mismatches:
        failures.append(f"{len(mismatches)} locked package(s) are missing or mismatched")
    pip_check = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if pip_check.returncode:
        failures.append("pip check failed")
    return {
        "schema_version": "honghu.python_runtime_verification.v1",
        "ok": not failures,
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "python_executable": str(Path(sys.executable).resolve()),
        "lockfile_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "locked_package_count": len(pins),
        "mismatches": mismatches[:50],
        "pip_check": {
            "ok": pip_check.returncode == 0,
            "summary": pip_check.stdout.strip()[:1000],
        },
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lockfile", type=Path, required=True)
    args = parser.parse_args(argv)
    result = verify_runtime(args.lockfile)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
