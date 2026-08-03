from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from .project_artifacts import (
        FEATURE_RETIREMENT_CLASSIFICATION,
        SECRET_PREFIX,
        _file_stat,
        _io_path,
        _is_regular_file,
        feature_retirement_active_references,
        feature_retirement_forbidden_reason,
        normalize_feature_retirement_spec,
        protected_reasons,
        sha256_file,
    )
except ImportError:  # Support direct execution: python tools/maintenance/<script>.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.maintenance.project_artifacts import (
        FEATURE_RETIREMENT_CLASSIFICATION,
        SECRET_PREFIX,
        _file_stat,
        _io_path,
        _is_regular_file,
        feature_retirement_active_references,
        feature_retirement_forbidden_reason,
        normalize_feature_retirement_spec,
        protected_reasons,
        sha256_file,
    )


ALLOWED_ACTIONS = {
    "delete_redundant",
    "retain_verbatim_history",
    "distill_then_delete",
    FEATURE_RETIREMENT_CLASSIFICATION,
}
RETIREMENT_SPEC_FIELDS = {"schema_version", "authorization", "batch", "reason", "paths"}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "project.artifact_inventory.v1":
        raise ValueError("不支持的 cleanup manifest schema")
    if not isinstance(payload.get("records"), list):
        raise ValueError("cleanup manifest 缺少 records")
    return payload


def _selected_records(payload: dict[str, Any], batches: set[str]) -> list[dict[str, Any]]:
    return [
        record for record in payload["records"]
        if record.get("classification") in ALLOWED_ACTIONS and record.get("batch") in batches
    ]


def _validate_retirement_authorization(
    payload: dict[str, Any],
    *,
    root: Path,
    batches: set[str],
    authorized_batches: set[str],
) -> dict[str, Any] | None:
    """Bind exact manifest records to the user spec and a second CLI confirmation."""
    unexpected_authorizations = sorted(authorized_batches - batches)
    if unexpected_authorizations:
        raise ValueError(
            "feature retirement 二次授权未在 --batch 中选中: "
            + ", ".join(unexpected_authorizations)
        )

    all_records = [
        record
        for record in payload["records"]
        if record.get("classification") == FEATURE_RETIREMENT_CLASSIFICATION
    ]
    selected_records = [record for record in all_records if record.get("batch") in batches]
    if not selected_records:
        if authorized_batches:
            raise ValueError("feature retirement 二次授权没有对应的 manifest 记录")
        return None

    selected_batches = {str(record.get("batch") or "") for record in selected_records}
    missing_authorizations = sorted(selected_batches - authorized_batches)
    if missing_authorizations:
        raise ValueError(
            "feature retirement 需要显式 --authorize-feature-retirement 二次授权: "
            + ", ".join(missing_authorizations)
        )

    raw_meta = payload.get("feature_retirement")
    if not isinstance(raw_meta, dict):
        raise ValueError("feature retirement manifest 缺少授权 spec")
    expected_meta_fields = RETIREMENT_SPEC_FIELDS | {"spec_hash"}
    if set(raw_meta) != expected_meta_fields:
        raise ValueError("feature retirement manifest spec 字段不完整或含未授权字段")
    normalized = normalize_feature_retirement_spec(
        {key: raw_meta[key] for key in RETIREMENT_SPEC_FIELDS},
        root=root,
    )
    if raw_meta.get("spec_hash") != normalized["spec_hash"]:
        raise ValueError("feature retirement spec hash 不一致")
    if selected_batches != {normalized["batch"]}:
        raise ValueError("feature retirement 所选 batch 与授权 spec 不一致")

    spec_paths = set(normalized["paths"])
    record_paths = [str(record.get("path") or "") for record in all_records]
    if len(record_paths) != len(set(record_paths)) or set(record_paths) != spec_paths:
        raise ValueError("feature retirement manifest 记录必须与 spec exact paths 完全一致")
    for record in all_records:
        rel = str(record.get("path") or "")
        if record.get("batch") != normalized["batch"]:
            raise ValueError(f"feature retirement record batch 不一致: {rel}")
        if record.get("retirement_spec_hash") != normalized["spec_hash"]:
            raise ValueError(f"feature retirement record spec hash 不一致: {rel}")
        active_references = record.get("active_references")
        if not isinstance(active_references, list):
            raise ValueError(f"feature retirement active_references 格式不合法: {rel}")
        if active_references:
            raise ValueError(
                f"feature retirement 候选仍被活动文本引用: {rel} <- "
                + ", ".join(str(item) for item in active_references[:8])
            )
        peer_references = record.get("retirement_peer_references")
        if not isinstance(peer_references, list) or any(ref not in spec_paths for ref in peer_references):
            raise ValueError(f"feature retirement peer references 越出授权集合: {rel}")

    current_references = feature_retirement_active_references(root, normalized["paths"])
    referenced = {rel: refs for rel, refs in current_references.items() if refs}
    if referenced:
        raise ValueError(
            "feature retirement 当前活动文本仍引用候选: "
            + json.dumps(referenced, ensure_ascii=False)
        )
    return normalized


def execute_cleanup(
    manifest_path: Path,
    *,
    batches: set[str],
    apply: bool = False,
    result_path: Path | None = None,
    authorized_retirement_batches: set[str] | None = None,
) -> dict[str, Any]:
    payload = _load_manifest(manifest_path)
    root = Path(payload["project_root"]).resolve()
    backup = Path(payload["backup_path"]).resolve()
    history_root = (root / "archive" / "project_history").resolve()
    if not root.is_dir() or not backup.is_dir() or _inside(backup, root):
        raise ValueError("project root 或外部 backup path 非法")
    authorized_retirement_batches = set(authorized_retirement_batches or set())
    retirement = _validate_retirement_authorization(
        payload,
        root=root,
        batches=batches,
        authorized_batches=authorized_retirement_batches,
    )
    records = _selected_records(payload, batches)
    planned: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for record in records:
        rel = str(record.get("path") or "")
        source_literal = root.joinpath(*PurePosixPath(rel).parts)
        source = source_literal.resolve()
        try:
            if not rel or not _inside(source, root):
                raise ValueError("源路径越出项目根目录")
            classification = record["classification"]
            is_retirement = classification == FEATURE_RETIREMENT_CLASSIFICATION
            if is_retirement and source_literal.is_symlink():
                raise ValueError("feature retirement 禁止 symlink")
            if rel.startswith(SECRET_PREFIX) or (protected_reasons(rel) and not is_retirement):
                raise ValueError("候选命中保护路径")
            if is_retirement:
                forbidden = feature_retirement_forbidden_reason(rel)
                if forbidden:
                    raise ValueError(f"feature retirement 禁止路径: {forbidden}")
            if not _is_regular_file(source):
                raise FileNotFoundError("源文件不存在")
            expected_hash = record.get("sha256")
            if not expected_hash or sha256_file(source) != expected_hash:
                raise ValueError("源文件 SHA256 与 manifest 不一致")
            recovery = record.get("recovery")
            recovery_path: Path | None = None
            if recovery != "regenerate":
                recovery_literal = Path(str(recovery or ""))
                if is_retirement and recovery_literal.is_symlink():
                    raise ValueError("feature retirement 备份不得是 symlink")
                recovery_path = recovery_literal.resolve()
                if not _inside(recovery_path, backup) or not _is_regular_file(recovery_path):
                    raise ValueError("外部备份恢复文件不存在或越界")
                if _file_stat(recovery_path).st_size != _file_stat(source).st_size:
                    raise ValueError("外部备份恢复文件大小不一致")
            if is_retirement:
                if retirement is None or recovery_path is None or recovery == "regenerate":
                    raise ValueError("feature retirement 必须有项目外 exact-path 备份")
                expected_recovery = backup.joinpath(*PurePosixPath(rel).parts).resolve()
                if recovery_path != expected_recovery:
                    raise ValueError("feature retirement 备份路径必须与项目 exact path 镜像一致")
                if sha256_file(recovery_path) != expected_hash:
                    raise ValueError("feature retirement 备份 SHA256 与源文件不一致")

            operation = "delete"
            target = None
            if classification == "retain_verbatim_history":
                target = (root / Path(str(record.get("target_path") or ""))).resolve()
                if not _inside(target, history_root):
                    raise ValueError("历史保留目标不在 archive/project_history 内")
                if target.exists():
                    raise FileExistsError("历史保留目标已存在")
                operation = "move"
            elif classification == "distill_then_delete":
                distilled_to = (root / Path(str(record.get("distilled_to") or ""))).resolve()
                if not _inside(distilled_to, history_root) or not distilled_to.is_file():
                    raise ValueError("尚未写入并确认历史提炼文件")
            planned_item = {
                "path": rel,
                "size": _file_stat(source).st_size,
                "sha256": expected_hash,
                "classification": classification,
                "batch": record.get("batch"),
                "operation": operation,
                "target": str(target) if target else None,
            }
            if is_retirement:
                planned_item["recovery"] = str(recovery_path)
            planned.append(planned_item)
        except (OSError, ValueError) as exc:
            errors.append({"path": rel, "error": str(exc)})

    if errors:
        raise ValueError("cleanup preflight 失败: " + json.dumps(errors[:30], ensure_ascii=False))

    completed: list[dict[str, Any]] = []
    if apply:
        for item in planned:
            source_literal = root.joinpath(*PurePosixPath(item["path"]).parts)
            source = source_literal.resolve()
            if not _is_regular_file(source) or sha256_file(source) != item["sha256"]:
                raise ValueError(f"apply 前文件发生变化: {item['path']}")
            if item["classification"] == FEATURE_RETIREMENT_CLASSIFICATION:
                recovery_path = Path(item["recovery"])
                if (
                    source_literal.is_symlink()
                    or recovery_path.is_symlink()
                    or not _is_regular_file(recovery_path)
                    or sha256_file(recovery_path) != item["sha256"]
                ):
                    raise ValueError(f"apply 前 feature retirement 恢复点发生变化: {item['path']}")
        for item in planned:
            source = root.joinpath(*PurePosixPath(item["path"]).parts).resolve()
            if item["operation"] == "move":
                target = Path(item["target"])
                if target.exists():
                    raise FileExistsError(f"apply 前历史目标已存在: {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                _io_path(source).replace(_io_path(target))
            else:
                _io_path(source).unlink()
            completed.append(item)
        if not any(item["classification"] == FEATURE_RETIREMENT_CLASSIFICATION for item in completed):
            _remove_empty_candidate_dirs(root, [item["path"] for item in completed])

    result = {
        "schema_version": "project.cleanup_result.v1",
        "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "apply" if apply else "dry_run",
        "manifest": str(manifest_path.resolve()),
        "batches": sorted(batches),
        "planned_count": len(planned),
        "planned_bytes": sum(item["size"] for item in planned),
        "completed_count": len(completed),
        "completed_bytes": sum(item["size"] for item in completed),
        "operations": completed if apply else planned,
    }
    if retirement:
        result["authorized_feature_retirement_batches"] = sorted(authorized_retirement_batches)
    if result_path:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _remove_empty_candidate_dirs(root: Path, relative_paths: list[str]) -> None:
    parents: set[Path] = set()
    for rel in relative_paths:
        parent = (root / Path(rel)).resolve().parent
        while parent != root and _inside(parent, root):
            parents.add(parent)
            parent = parent.parent
    for path in sorted(parents, key=lambda item: len(item.parts), reverse=True):
        try:
            _io_path(path).rmdir()
        except OSError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="按审核 manifest dry-run 或执行项目清理")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--batch", action="append", required=True)
    parser.add_argument(
        "--authorize-feature-retirement",
        action="append",
        default=[],
        help="二次确认一个已在 --batch 选中的 retire_* exact-path 功能退役批次",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    result = execute_cleanup(
        args.manifest,
        batches=set(args.batch),
        apply=args.apply,
        result_path=args.result,
        authorized_retirement_batches=set(args.authorize_feature_retirement),
    )
    print(json.dumps({key: value for key, value in result.items() if key != "operations"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
