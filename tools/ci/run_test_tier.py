from __future__ import annotations

"""Run the explicit clean-clone test tier without hiding its exclusions."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "config" / "ci_test_tiers.json"


def load_core_ignores(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "honghu.ci_test_tiers.v1":
        raise ValueError("unsupported CI test-tier manifest")
    values = payload.get("core", {}).get("ignore_modules")
    if not isinstance(values, list) or not values:
        raise ValueError("core.ignore_modules must be a non-empty list")
    ignores: list[str] = []
    for value in values:
        rel = Path(str(value)).as_posix()
        if not rel.startswith("tests/") or not rel.endswith(".py") or ".." in Path(rel).parts:
            raise ValueError(f"unsafe ignored test path: {rel}")
        if not (ROOT / rel).is_file():
            raise FileNotFoundError(f"ignored test module does not exist: {rel}")
        ignores.append(rel)
    if len(ignores) != len(set(ignores)):
        raise ValueError("duplicate ignored test module")
    return sorted(ignores)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("pytest_args", nargs="*")
    args = parser.parse_args(argv)
    ignores = load_core_ignores(args.manifest.resolve())
    command = [sys.executable, "-m", "pytest", "-q"]
    if args.collect_only:
        command.append("--collect-only")
    command.extend(f"--ignore={path}" for path in ignores)
    command.extend(args.pytest_args)
    print(
        json.dumps(
            {
                "tier": "core",
                "excluded_governed_artifact_modules": len(ignores),
                "manifest": args.manifest.resolve().as_posix(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
