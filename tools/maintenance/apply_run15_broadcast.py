from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


SOURCE_ROOT = Path(__file__).resolve().parents[2]
BEIJING = ZoneInfo("Asia/Shanghai")
COPY_DIRECTORIES = ("docs", "tools", "papers", "opportunity_lens", "config")
ROOT_FILES = ("restart_viewer.bat", "requirements.txt")
TARGET_DATABASES = ("data/opportunity_lens.db", "data/financial.db")
ALL_DATABASES = (
    "data/research.db",
    "data/sentiment.db",
    "data/opportunity_lens.db",
    "data/financial.db",
)
RUN15_PACK = (
    "opportunity_lens/research_outputs/"
    "20260725_chint_pv_profit_quality_run15/run15_pack_stage.json"
)
RUN15_EXPORTS = (
    "opportunity_lens/research_outputs/"
    "20260725_chint_pv_profit_quality_run15/company_financial_profile_export_v1.json",
    "opportunity_lens/research_outputs/"
    "20260725_chint_pv_profit_quality_run15/company_financial_profile_export_bridge_v1.json",
)
SKIP_PARTS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".db-wal",
    ".db-shm",
    ".db-journal",
    ".lock",
)


def _sqlite_snapshot(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    uri = source.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as source_conn:
        with closing(sqlite3.connect(target)) as target_conn:
            source_conn.backup(target_conn)
            target_conn.commit()
    with closing(sqlite3.connect(target)) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    if integrity != "ok" or foreign_keys:
        raise RuntimeError(
            f"目标库回退快照校验失败: {source}; "
            f"integrity={integrity}, foreign_key_issues={len(foreign_keys)}"
        )


def _skip(relative: Path) -> bool:
    return (
        any(part in SKIP_PARTS for part in relative.parts)
        or relative.as_posix().startswith("tools/dynamic/secrets/")
        or relative.as_posix().lower().endswith(SKIP_SUFFIXES)
    )


def _copy_payload(source_root: Path, target_root: Path) -> int:
    copied = 0
    for directory_name in COPY_DIRECTORIES:
        source_directory = source_root / directory_name
        if not source_directory.is_dir():
            raise FileNotFoundError(source_directory)
        for current, dirnames, filenames in os.walk(source_directory):
            current_path = Path(current)
            relative_directory = current_path.relative_to(source_root)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if not _skip(relative_directory / name)
            )
            target_directory = target_root / relative_directory
            target_directory.mkdir(parents=True, exist_ok=True)
            for name in sorted(filenames):
                relative = relative_directory / name
                if _skip(relative):
                    continue
                shutil.copy2(current_path / name, target_root / relative)
                copied += 1
    for relative in ROOT_FILES:
        source = source_root / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, target_root / relative)
        copied += 1
    return copied


def _run(target_root: Path, *arguments: str) -> dict[str, object]:
    command = [sys.executable, *arguments]
    completed = subprocess.run(
        command,
        cwd=target_root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    result = {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if completed.returncode != 0:
        raise RuntimeError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def validate(source_root: Path, target_root: Path) -> dict[str, object]:
    source_root = source_root.resolve()
    target_root = target_root.resolve()
    if source_root == target_root:
        raise ValueError("广播包源目录与内网目标目录不能相同")
    if not target_root.is_dir():
        raise FileNotFoundError(target_root)
    missing_source = [
        relative
        for relative in (*COPY_DIRECTORIES, *ROOT_FILES, RUN15_PACK, *RUN15_EXPORTS)
        if not (source_root / relative).exists()
    ]
    missing_target = [
        relative for relative in ALL_DATABASES if not (target_root / relative).is_file()
    ]
    if missing_source or missing_target:
        raise FileNotFoundError(
            f"广播安装闭包不完整: source={missing_source}, target={missing_target}"
        )
    return {
        "source_root": str(source_root),
        "target_root": str(target_root),
        "source_files_ready": True,
        "target_live_databases_preserved": list(ALL_DATABASES),
    }


def apply(source_root: Path, target_root: Path) -> dict[str, object]:
    summary = validate(source_root, target_root)
    source_root = source_root.resolve()
    target_root = target_root.resolve()
    stamp = datetime.now(BEIJING).strftime("%Y%m%d_%H%M%S")
    rollback = (target_root / "cache" / f"run15_deploy_rollback_{stamp}").resolve()
    cache_root = (target_root / "cache").resolve()
    if cache_root not in rollback.parents:
        raise RuntimeError(f"回退目录越界: {rollback}")
    if rollback.exists():
        raise FileExistsError(rollback)

    for relative in TARGET_DATABASES:
        _sqlite_snapshot(target_root / relative, rollback / relative)

    copied_files = _copy_payload(source_root, target_root)
    commands: list[dict[str, object]] = []
    commands.append(
        _run(
            target_root,
            "-m",
            "tools.opportunity_lens.manual_run_loader",
            RUN15_PACK,
            "--replace",
            "--frozen-broadcast-install",
        )
    )
    for export in RUN15_EXPORTS:
        commands.append(
            _run(
                target_root,
                "-m",
                "tools.financial.opportunity_profile_export",
                export,
            )
        )
    commands.append(
        _run(
            target_root,
            "tools/viewer/preflight.py",
            "--root",
            str(target_root),
        )
    )
    receipt = {
        "schema_version": "industry_demo.run15_broadcast_install.v1",
        "installed_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
        **summary,
        "copied_file_count": copied_files,
        "overwritten_live_databases": [],
        "incrementally_updated_databases": list(TARGET_DATABASES),
        "rollback_snapshots": str(rollback),
        "commands": commands,
    }
    receipt_path = target_root / "cache" / f"run15_broadcast_install_{stamp}.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    receipt["receipt_path"] = str(receipt_path)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="把 Run15 广播包增量安装到现有内网 Industry Demo"
    )
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        result = validate(args.source_root, args.target_root)
    else:
        result = apply(args.source_root, args.target_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
