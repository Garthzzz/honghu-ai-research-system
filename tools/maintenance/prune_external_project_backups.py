from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.maintenance.refresh_project_backup import _filesystem_path


SCHEMA_VERSION = "industry_demo.external_backup_prune.v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with _filesystem_path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_latest_backup(root: Path) -> dict[str, Any]:
    latest = root / "backup" / "latest"
    manifest_path = latest / "backup_manifest.json"
    info_path = latest / "BACKUP_INFO.md"
    if not manifest_path.is_file() or not info_path.is_file():
        raise FileNotFoundError("项目内 backup/latest 缺少 manifest 或版本说明")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive_name = str(manifest.get("archive") or "")
    if not archive_name or Path(archive_name).name != archive_name:
        raise ValueError("备份 manifest 的 archive 不是安全文件名")
    archive = latest / archive_name
    if not archive.is_file():
        raise FileNotFoundError(archive)
    expected_size = int(manifest.get("archive_size") or -1)
    if archive.stat().st_size != expected_size:
        raise ValueError("项目内 latest 归档大小与 manifest 不一致")
    actual_sha256 = _sha256_file(archive)
    if actual_sha256 != manifest.get("archive_sha256"):
        raise ValueError("项目内 latest 归档 SHA256 与 manifest 不一致")
    databases = manifest.get("databases") or []
    if len(databases) != 4 or any(
        row.get("integrity_check") != "ok" or int(row.get("foreign_key_issues", -1)) != 0
        for row in databases
    ):
        raise ValueError("项目内 latest 未记录四套通过校验的 SQLite 快照")
    with zipfile.ZipFile(_filesystem_path(archive), "r") as handle:
        corrupt = handle.testzip()
        names = set(handle.namelist())
    if corrupt or "BACKUP_CONTENT_MANIFEST.json" not in names:
        raise ValueError(f"项目内 latest ZIP 校验失败: {corrupt}")
    return {
        "path": str(latest),
        "version": manifest.get("version"),
        "archive_size": expected_size,
        "archive_sha256": actual_sha256,
        "zip_crc": "ok",
        "database_count": len(databases),
    }


def external_backup_candidates(root: Path) -> list[Path]:
    root = root.resolve()
    parent = root.parent.resolve()
    pattern = re.compile(
        rf"^{re.escape(root.name)}_.*(?:backup|rollback|cleanup_safety).*$",
        re.IGNORECASE,
    )
    candidates: list[Path] = []
    for path in parent.iterdir():
        if not path.is_dir() or path.is_symlink() or not pattern.fullmatch(path.name):
            continue
        resolved = path.resolve()
        if resolved == root or resolved.parent != parent:
            continue
        # PostgreSQL off-VM recovery storage is governed by its own manifest,
        # retention boundary and restore evidence.  It must never be treated as
        # an ordinary disposable project backup merely because its directory
        # name contains ``backup``.
        if (resolved / "postgresql_recovery").is_dir():
            continue
        candidates.append(resolved)
    return sorted(candidates, key=lambda path: path.name.lower())


def _directory_size(path: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for directory, _, filenames in os.walk(_filesystem_path(path)):
        for name in filenames:
            candidate = Path(directory) / name
            try:
                total += candidate.stat().st_size
                files += 1
            except FileNotFoundError:
                continue
    return files, total


def _remove_readonly(function, path: str, exc_info) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def prune_external_backups(root: Path, *, apply: bool = False) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir() or "industry_demo" not in root.name.lower():
        raise ValueError("项目根目录名必须包含 industry_demo")
    verified = verify_latest_backup(root)
    candidates = external_backup_candidates(root)
    planned: list[dict[str, Any]] = []
    for candidate in candidates:
        files, size = _directory_size(candidate)
        planned.append({"path": str(candidate), "files": files, "bytes": size})

    removed: list[dict[str, Any]] = []
    if apply:
        current = {path.resolve() for path in external_backup_candidates(root)}
        expected = {Path(row["path"]).resolve() for row in planned}
        if current != expected:
            raise RuntimeError("apply 前外部备份目录集合发生变化")
        for row in planned:
            candidate = Path(row["path"]).resolve()
            if candidate.parent != root.parent or candidate == root or candidate.is_symlink():
                raise ValueError(f"拒绝越界删除: {candidate}")
            # Python 3.10/3.11 expose ``onerror``; ``onexc`` was added later.
            # The callback signature used here is compatible with ``onerror``.
            shutil.rmtree(_filesystem_path(candidate), onerror=_remove_readonly)
            removed.append(row)
        remaining = external_backup_candidates(root)
        if remaining:
            raise RuntimeError(f"仍有未清理的外部备份: {remaining}")

    return {
        "schema_version": SCHEMA_VERSION,
        "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "apply" if apply else "dry_run",
        "root": str(root),
        "latest_backup": verified,
        "planned_count": len(planned),
        "planned_files": sum(int(row["files"]) for row in planned),
        "planned_bytes": sum(int(row["bytes"]) for row in planned),
        "planned": planned,
        "removed_count": len(removed),
        "removed_bytes": sum(int(row["bytes"]) for row in removed),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="验证项目内 latest 后，仅清理 D:\\quant 直属的旧 industry_demo backup/rollback"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    result = prune_external_backups(args.root, apply=args.apply)
    if args.result:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
