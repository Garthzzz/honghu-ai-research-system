from __future__ import annotations

"""Quarantine an owned pre-install PostgreSQL extraction after a failed launch."""

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PreinstallQuarantineError(RuntimeError):
    pass


def _tree_identity(root: Path) -> tuple[int, int, str]:
    records: list[tuple[str, int]] = []
    total_bytes = 0
    for path in sorted((item for item in root.rglob("*") if item.is_file())):
        size = path.stat().st_size
        total_bytes += size
        records.append((path.relative_to(root).as_posix(), size))
    digest = hashlib.sha256(
        json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return len(records), total_bytes, digest


def quarantine_preinstall_staging(
    *,
    install_root: Path,
    staging_root: Path,
    launch_id: str,
    primary_failure: str,
    output_path: Path,
) -> dict[str, Any]:
    install_root = install_root.resolve(strict=False)
    staging_root = staging_root.resolve(strict=True)
    output_path = output_path.resolve(strict=False)
    if not re.fullmatch(r"[0-9a-fA-F]{32}", launch_id):
        raise PreinstallQuarantineError("launch id is not a 32-hex identity")
    if install_root.exists():
        raise PreinstallQuarantineError("install root exists; pre-install recovery is not allowed")
    expected_pattern = re.compile(
        rf"^{re.escape(install_root.name)}\.staging\.[0-9a-fA-F]{{32}}$"
    )
    if staging_root.parent != install_root.parent or not expected_pattern.fullmatch(
        staging_root.name
    ):
        raise PreinstallQuarantineError("staging root is outside the owned install sibling boundary")
    if not staging_root.is_dir():
        raise PreinstallQuarantineError("staging root is not a directory")
    quarantine = install_root.with_name(f"{install_root.name}.preinstall.failed.{launch_id}")
    if quarantine.exists():
        raise PreinstallQuarantineError("pre-install quarantine destination already exists")
    if output_path == staging_root or staging_root in output_path.parents:
        raise PreinstallQuarantineError("quarantine evidence cannot be stored inside staging")

    file_count, total_bytes, file_set_sha256 = _tree_identity(staging_root)
    os.replace(staging_root, quarantine)
    evidence: dict[str, Any] = {
        "schema_version": "honghu.stage4_preinstall_quarantine.v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "launch_id": launch_id.lower(),
        "primary_failure": primary_failure,
        "original_staging_root": str(staging_root),
        "quarantine_path": str(quarantine),
        "file_count": file_count,
        "total_bytes": total_bytes,
        "file_set_sha256": file_set_sha256,
        "install_root_absent": not install_root.exists(),
        "reusable_as_install": False,
        "manual_inspection_or_bounded_cleanup_required": True,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--launch-id", required=True)
    parser.add_argument("--primary-failure", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = quarantine_preinstall_staging(
        install_root=args.install_root,
        staging_root=args.staging_root,
        launch_id=args.launch_id,
        primary_failure=args.primary_failure,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
