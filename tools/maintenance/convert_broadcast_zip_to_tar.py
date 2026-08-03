from __future__ import annotations

"""Convert a verified viewer ZIP bundle to Windows-tar compatible ``.tar.gz``."""

import argparse
import hashlib
import json
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def convert(source: Path, target: Path) -> dict[str, object]:
    source = source.resolve()
    target = target.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(source) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise RuntimeError(f"ZIP CRC 校验失败：{bad_member}")
        members = archive.infolist()
        with tarfile.open(
            target,
            "w:gz",
            compresslevel=6,
            format=tarfile.PAX_FORMAT,
        ) as tar:
            for member in members:
                relative = Path(member.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise RuntimeError(f"拒绝不安全归档路径：{member.filename}")
                info = tarfile.TarInfo(member.filename.rstrip("/") or member.filename)
                info.mtime = datetime(
                    *member.date_time,
                    tzinfo=timezone.utc,
                ).timestamp()
                info.mode = (
                    (member.external_attr >> 16) & 0o777
                    or (0o755 if member.is_dir() else 0o644)
                )
                if member.is_dir():
                    info.type = tarfile.DIRTYPE
                    info.size = 0
                    tar.addfile(info)
                else:
                    info.size = member.file_size
                    with archive.open(member) as stream:
                        tar.addfile(info, stream)

    with tarfile.open(target, "r:gz") as archive:
        tar_members = archive.getmembers()
        unsafe = [
            member.name
            for member in tar_members
            if Path(member.name).is_absolute() or ".." in Path(member.name).parts
        ]
    if unsafe:
        raise RuntimeError(f"TAR 路径校验失败：{unsafe[:5]}")
    result = {
        "schema_version": "industry_demo.broadcast_tar_delivery.v1",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_zip": str(source),
        "source_zip_size": source.stat().st_size,
        "source_zip_sha256": _sha256(source),
        "file": str(target),
        "size": target.stat().st_size,
        "sha256": _sha256(target),
        "member_count": len(tar_members),
        "archive_test": "PASS",
        "windows_extract_command": (
            f'tar -xzf "{target.name}" -C C:\\industry_demo_update'
        ),
    }
    target.with_suffix(target.suffix + ".manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_zip", type=Path)
    parser.add_argument("target_tar_gz", type=Path)
    args = parser.parse_args()
    result = convert(args.source_zip, args.target_tar_gz)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
