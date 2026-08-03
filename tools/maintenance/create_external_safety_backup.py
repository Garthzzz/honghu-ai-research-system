from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable
from zoneinfo import ZoneInfo

from tools.maintenance import refresh_project_backup as backup
from tools.maintenance.project_artifacts import (
    normalize_feature_retirement_spec,
    read_feature_retirement_spec,
)


BEIJING = ZoneInfo("Asia/Shanghai")
SCHEMA_VERSION = "industry_demo.external_safety_backup.v1"


def create_external_safety_backup(
    root: Path,
    output_dir: Path,
    *,
    reason: str,
    mirror_paths: Iterable[str] | None = None,
) -> dict[str, object]:
    root = root.resolve()
    output_dir = output_dir.resolve()
    if "industry_demo" not in root.name.lower():
        raise ValueError("项目根目录名必须包含 industry_demo")
    if "industry_demo" not in output_dir.as_posix().lower():
        raise ValueError("外部安全副本路径必须包含 industry_demo")
    if root in output_dir.parents or output_dir == root:
        raise ValueError("外部安全副本不能位于项目目录内")

    output_dir.mkdir(parents=True, exist_ok=True)
    snapshots = output_dir / "sqlite_snapshots"
    archive_path = output_dir / "industry_demo_external_safety.zip"
    manifest_path = output_dir / "backup_manifest.json"
    created_at = datetime.now(BEIJING).isoformat()

    database_results: list[dict[str, object]] = []
    snapshot_sources: dict[str, Path] = {}
    for relative in backup.LIVE_DATABASES:
        source = root / relative
        target = snapshots / relative
        result = backup._sqlite_snapshot(source, target)
        result["path"] = relative
        database_results.append(result)
        snapshot_sources[relative] = target

    sources = dict(backup._project_files(root))
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
            records.append(backup._copy_to_zip(archive, relative, sources[relative]))
        embedded = {
            "schema_version": SCHEMA_VERSION,
            "created_at": created_at,
            "reason": reason,
            "files": records,
            "databases": database_results,
        }
        archive.writestr(
            "BACKUP_CONTENT_MANIFEST.json",
            json.dumps(embedded, ensure_ascii=False, indent=2) + "\n",
        )

    expected_members = {str(record["path"]) for record in records}
    expected_members.add("BACKUP_CONTENT_MANIFEST.json")
    with zipfile.ZipFile(archive_path, "r") as archive:
        corrupt = archive.testzip()
        actual_members = set(archive.namelist())
        embedded_check = json.loads(archive.read("BACKUP_CONTENT_MANIFEST.json"))
    if corrupt:
        raise RuntimeError(f"ZIP CRC 校验失败: {corrupt}")
    if actual_members != expected_members:
        raise RuntimeError(
            f"ZIP 成员清单不一致: expected={len(expected_members)} "
            f"actual={len(actual_members)}"
        )
    if embedded_check["files"] != records:
        raise RuntimeError("ZIP 内嵌文件清单与创建清单不一致")

    mirrored_records: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for raw_relative in mirror_paths or []:
        relative_path = PurePosixPath(str(raw_relative))
        relative = relative_path.as_posix()
        if (
            relative in seen_paths
            or relative_path.is_absolute()
            or not relative_path.parts
            or any(part in {"", ".", ".."} for part in relative_path.parts)
        ):
            raise ValueError(f"非法或重复的镜像路径: {raw_relative}")
        seen_paths.add(relative)
        source = root.joinpath(*relative_path.parts).resolve()
        target = output_dir.joinpath(*relative_path.parts).resolve()
        if (
            root not in source.parents
            or output_dir not in target.parents
            or source.is_symlink()
            or not source.is_file()
            or target.exists()
        ):
            raise ValueError(
                f"镜像路径越界、不存在、为链接或目标已存在: {relative}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        source_hash = backup._sha256_file(source)
        target_hash = backup._sha256_file(target)
        if (
            source.stat().st_size != target.stat().st_size
            or source_hash != target_hash
        ):
            raise RuntimeError(f"外部 exact-path 镜像校验失败: {relative}")
        mirrored_records.append(
            {
                "path": relative,
                "size": source.stat().st_size,
                "sha256": source_hash,
            }
        )

    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": created_at,
        "reason": reason,
        "archive": archive_path.name,
        "archive_size": archive_path.stat().st_size,
        "archive_sha256": backup._sha256_file(archive_path),
        "file_count": len(records),
        "zip_crc": "ok",
        "member_set": "ok",
        "databases": database_results,
        "mirrored_file_count": len(mirrored_records),
        "mirrored_bytes": sum(
            int(record["size"]) for record in mirrored_records
        ),
        "mirrored_files": mirrored_records,
    }
    backup._write_json(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="为大规模迁移创建项目外事务一致安全副本"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument(
        "--mirror-spec",
        type=Path,
        help="可选：把 feature retirement spec 的 exact files 镜像到外部目录",
    )
    args = parser.parse_args()
    mirror_paths: list[str] = []
    if args.mirror_spec:
        raw_spec = read_feature_retirement_spec(
            args.mirror_spec,
            root=args.root,
        )
        normalized_spec = normalize_feature_retirement_spec(
            raw_spec,
            root=args.root,
        )
        mirror_paths = list(normalized_spec["paths"])
    result = create_external_safety_backup(
        args.root,
        args.output_dir,
        reason=args.reason,
        mirror_paths=mirror_paths,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
