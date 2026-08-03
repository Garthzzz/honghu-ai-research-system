from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo


SCHEMA_VERSION = "industry_demo.project_backup.v1"
BEIJING = ZoneInfo("Asia/Shanghai")
LIVE_DATABASES = (
    "data/research.db",
    "data/sentiment.db",
    "data/opportunity_lens.db",
    "data/financial.db",
)
SKIP_PREFIXES = (
    "backup/",
    "broadcast_packages/",
    "cache/broadcast_validation/",
    "cache/cache_bundle_validation_",
    "cache/installer_e2e_",
    "cache/installer_hotfix_validation_",
    "cache/installer_lock_simulation/",
    "cache/paper_path_hotfix_validation_",
    "cache/package_dependency_audit_",
    "cache/tar_safe_test_",
    "cache/tarv",
    "cache/v15",
    "cache/zip_safe_test_",
    "tools/dynamic/secrets/",
    ".pytest_cache/",
)
SKIP_PARTS = {"__pycache__"}
SKIP_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".db-wal",
    ".db-shm",
    ".db-journal",
    ".sqlite-wal",
    ".sqlite-shm",
    ".sqlite-journal",
    ".lock",
)
SKIP_FILES = {
    "cache/viewer_debug.log",
}
STORE_SUFFIXES = {
    ".7z",
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".webp",
    ".xlsx",
    ".zip",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _filesystem_path(path: Path) -> Path:
    """Return a Windows extended-length path without changing archive names."""
    if os.name != "nt":
        return path
    raw = os.fspath(path)
    if raw.startswith("\\\\?\\"):
        return path
    if raw.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + raw[2:])
    if Path(raw).is_absolute():
        return Path("\\\\?\\" + raw)
    return path


def _sqlite_snapshot(source: Path, target: Path) -> dict[str, object]:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_uri = source.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as source_conn:
        with closing(sqlite3.connect(target)) as target_conn:
            source_conn.backup(target_conn)
            target_conn.commit()
    with closing(sqlite3.connect(target)) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_issues = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        table_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    if integrity != "ok" or foreign_key_issues:
        raise RuntimeError(
            f"SQLite 快照校验失败: {source} integrity={integrity} "
            f"foreign_key_issues={foreign_key_issues}"
        )
    return {
        "path": source.relative_to(source.parents[1]).as_posix(),
        "size": target.stat().st_size,
        "sha256": _sha256_file(target),
        "integrity_check": integrity,
        "foreign_key_issues": foreign_key_issues,
        "table_count": table_count,
    }


def _should_skip(relative: str) -> bool:
    relative = relative.replace("\\", "/")
    if relative in LIVE_DATABASES or relative in SKIP_FILES:
        return True
    if any(relative.startswith(prefix) for prefix in SKIP_PREFIXES):
        return True
    if any(part in SKIP_PARTS for part in Path(relative).parts):
        return True
    return relative.lower().endswith(SKIP_SUFFIXES)


def _project_files(root: Path) -> Iterable[tuple[str, Path]]:
    for directory, dirnames, filenames in os.walk(root):
        directory_path = Path(directory)
        relative_directory = directory_path.relative_to(root).as_posix()
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not _should_skip(
                f"{relative_directory}/{name}/"
                if relative_directory != "."
                else f"{name}/"
            )
        )
        for name in sorted(filenames):
            source = directory_path / name
            relative = source.relative_to(root).as_posix()
            if not _should_skip(relative):
                yield relative, source


def _zip_info(relative: str, source: Path) -> zipfile.ZipInfo:
    stat = source.stat()
    modified = datetime.fromtimestamp(stat.st_mtime)
    year = min(max(modified.year, 1980), 2107)
    info = zipfile.ZipInfo(
        relative,
        (
            year,
            modified.month,
            modified.day,
            modified.hour,
            modified.minute,
            modified.second,
        ),
    )
    info.compress_type = (
        zipfile.ZIP_STORED
        if source.suffix.lower() in STORE_SUFFIXES
        else zipfile.ZIP_DEFLATED
    )
    info.external_attr = (stat.st_mode & 0xFFFF) << 16
    return info


def _copy_to_zip(
    archive: zipfile.ZipFile,
    relative: str,
    source: Path,
) -> dict[str, object]:
    digest = hashlib.sha256()
    size = 0
    filesystem_source = _filesystem_path(source)
    info = _zip_info(relative, filesystem_source)
    with (
        filesystem_source.open("rb") as source_handle,
        archive.open(info, "w") as target_handle,
    ):
        while True:
            chunk = source_handle.read(1024 * 1024)
            if not chunk:
                break
            target_handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return {"path": relative, "size": size, "sha256": digest.hexdigest()}


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _install_latest(payload: Path, backup_root: Path) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    latest = backup_root / "latest"
    next_path = backup_root / ".next"
    previous = backup_root / ".previous"
    for transient in (next_path, previous):
        if transient.exists():
            shutil.rmtree(transient)
    shutil.move(str(payload), str(next_path))
    if latest.exists():
        latest.rename(previous)
    next_path.rename(latest)
    if previous.exists():
        shutil.rmtree(previous)
    return latest


def refresh_backup(
    root: Path,
    *,
    version: str,
    reason: str,
    staging_parent: Path | None = None,
) -> dict[str, object]:
    root = root.resolve()
    if not root.is_dir() or "industry_demo" not in root.name.lower():
        raise ValueError("项目根目录名必须包含 industry_demo")
    missing = [relative for relative in LIVE_DATABASES if not (root / relative).is_file()]
    if missing:
        raise FileNotFoundError(f"缺少 live SQLite: {missing}")

    created_at = datetime.now(BEIJING)
    stamp = created_at.strftime("%Y%m%d_%H%M%S")
    staging_parent = (staging_parent or root.parent).resolve()
    staging = staging_parent / f"{root.name}_backup_build_{stamp}"
    if staging.exists():
        raise FileExistsError(staging)
    payload = staging / "payload"
    snapshots = staging / "sqlite_snapshots"
    payload.mkdir(parents=True)
    archive_path = payload / "industry_demo_latest.zip"

    try:
        database_results: list[dict[str, object]] = []
        snapshot_sources: dict[str, Path] = {}
        for relative in LIVE_DATABASES:
            source = root / relative
            target = snapshots / relative
            result = _sqlite_snapshot(source, target)
            result["path"] = relative
            database_results.append(result)
            snapshot_sources[relative] = target

        sources = dict(_project_files(root))
        sources.update(snapshot_sources)
        records: list[dict[str, object]] = []
        with zipfile.ZipFile(
            archive_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for relative in sorted(sources):
                records.append(_copy_to_zip(archive, relative, sources[relative]))
            content_manifest = {
                "schema_version": SCHEMA_VERSION,
                "created_at": created_at.isoformat(),
                "version": version,
                "reason": reason,
                "files": records,
                "databases": database_results,
            }
            archive.writestr(
                "BACKUP_CONTENT_MANIFEST.json",
                json.dumps(content_manifest, ensure_ascii=False, indent=2) + "\n",
            )

        expected_members = {record["path"] for record in records}
        expected_members.add("BACKUP_CONTENT_MANIFEST.json")
        with zipfile.ZipFile(archive_path, "r") as archive:
            corrupt = archive.testzip()
            actual_members = set(archive.namelist())
            embedded = json.loads(archive.read("BACKUP_CONTENT_MANIFEST.json"))
        if corrupt:
            raise RuntimeError(f"ZIP CRC 校验失败: {corrupt}")
        if actual_members != expected_members or embedded["files"] != records:
            raise RuntimeError("ZIP 成员或内嵌清单不一致")

        archive_sha256 = _sha256_file(archive_path)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_at": created_at.isoformat(),
            "version": version,
            "reason": reason,
            "source_root": str(root),
            "archive": archive_path.name,
            "archive_size": archive_path.stat().st_size,
            "archive_sha256": archive_sha256,
            "file_count": len(records),
            "source_bytes": sum(int(record["size"]) for record in records),
            "databases": database_results,
            "excluded": [
                "backup/（避免递归备份）",
                "tools/dynamic/secrets/（密钥、cookie、storage state 从不读取或复制）",
                "SQLite WAL/SHM/journal（live DB 改用 backup API 一致快照）",
                "__pycache__、.pytest_cache、pyc/pyo、运行时 lock 与 "
                "viewer_debug.log（可再生成）",
            ],
            "verification": {
                "zip_crc": "ok",
                "member_set_matches": True,
                "embedded_manifest_matches": True,
            },
        }
        _write_json(payload / "backup_manifest.json", manifest)
        (payload / "BACKUP_INFO.md").write_text(
            "# Industry Demo 最新备份\n\n"
            f"- 版本：{version}\n"
            f"- 创建时间：{created_at.strftime('%Y-%m-%d %H:%M:%S')}（北京时间）\n"
            f"- 创建原因：{reason}\n"
            f"- 内容：{len(records):,} 个文件，四套 live SQLite "
            "均为 backup API 一致快照。\n"
            f"- 归档 SHA256：`{archive_sha256}`\n"
            "- 恢复边界：不含 secrets、WAL/SHM、字节码和一次性调试日志。"
            "恢复前应停止 Viewer 与全部计划任务，且不得从旧环境拼接 WAL/SHM。\n",
            encoding="utf-8",
        )

        latest = _install_latest(payload, root / "backup")
        installed_manifest = json.loads(
            (latest / "backup_manifest.json").read_text(encoding="utf-8")
        )
        installed_archive = latest / installed_manifest["archive"]
        if _sha256_file(installed_archive) != installed_manifest["archive_sha256"]:
            raise RuntimeError("安装后的备份归档 SHA256 不一致")
        shutil.rmtree(staging)
        installed_manifest["installed_path"] = str(latest)
        return installed_manifest
    except Exception:
        # 失败现场留在名称包含 industry_demo 的 staging 目录，旧 latest 不受影响。
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="原子刷新项目内唯一 latest 备份")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--version", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    result = refresh_backup(args.root, version=args.version, reason=args.reason)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
