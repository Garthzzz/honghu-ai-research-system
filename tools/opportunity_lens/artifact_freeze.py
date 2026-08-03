from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from tools.research_core.manifest import is_sha256_hash

from .constants import ROOT, RUN_PACK_SCHEMA_VERSION


ARTIFACT_FREEZE_VERSION = "opportunity_lens.artifact_freeze.v1"
VIEWER_BUNDLE_SUFFIXES = frozenset({".py", ".html", ".css", ".js"})
VIEWER_RUNTIME_DEPENDENCIES = (
    "tools/opportunity_lens/read_models.py",
    "tools/opportunity_lens/api_models.py",
    "tools/opportunity_lens/constants.py",
    "tools/opportunity_lens/db.py",
    "tools/opportunity_lens/display_annotations.py",
    "tools/opportunity_lens/display_labels.py",
    "tools/opportunity_lens/evidence_resolver.py",
    "tools/opportunity_lens/factor_dictionary.py",
    "tools/opportunity_lens/flags.py",
    "tools/opportunity_lens/score_trace.py",
    "tools/opportunity_lens/validators.py",
)


class ArtifactFreezeError(ValueError):
    """当前 run 无法形成可核验的产物冻结指纹。"""


@dataclass(frozen=True)
class ArtifactFreeze:
    run_id: int
    pack_hash: str
    ui_bundle_hash: str
    browser_input_hash: str
    ui_file_count: int
    pack_schema_version: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "freeze_version": ARTIFACT_FREEZE_VERSION,
            "run_id": self.run_id,
            "pack_hash": self.pack_hash,
            "ui_bundle_hash": self.ui_bundle_hash,
            "browser_input_hash": self.browser_input_hash,
            "ui_file_count": self.ui_file_count,
            "pack_schema_version": self.pack_schema_version,
        }


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def normalize_sha256(value: Any, *, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) == 64 and all(character in "0123456789abcdef" for character in text):
        text = f"sha256:{text}"
    if not is_sha256_hash(text):
        raise ArtifactFreezeError(f"{field} 不是合法 SHA256: {value!r}")
    return text


def _latest_manual_pack_row(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id,manifest_json,workflow_contract_version,pack_schema_version,created_at
        FROM opportunity_run_manifest
        WHERE run_id=? AND manifest_type='manual_research_pack'
        ORDER BY id DESC LIMIT 1
        """,
        (run_id,),
    ).fetchone()


def latest_manual_pack_manifest(conn: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    row = _latest_manual_pack_row(conn, run_id)
    if row is None:
        raise ArtifactFreezeError("缺少 manual_research_pack manifest，无法确定当前研究包")
    try:
        payload = json.loads(row["manifest_json"])
    except (json.JSONDecodeError, TypeError) as exc:
        raise ArtifactFreezeError("manual_research_pack manifest_json 不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise ArtifactFreezeError("manual_research_pack manifest_json 顶层必须是对象")
    payload = dict(payload)
    payload["_manifest_row_id"] = int(row["id"])
    payload["_row_pack_schema_version"] = row["pack_schema_version"]
    return payload


def is_strict_v2_run(conn: sqlite3.Connection, run_id: int) -> bool:
    row = _latest_manual_pack_row(conn, run_id)
    if row is None:
        return False
    schema_version = str(row["pack_schema_version"] or "").strip()
    if schema_version == RUN_PACK_SCHEMA_VERSION:
        return True
    try:
        payload = json.loads(row["manifest_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return False
    return str(payload.get("pack_schema_version") or "").strip() == RUN_PACK_SCHEMA_VERSION


def current_pack_hash(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    project_root: str | Path = ROOT,
    verify_content_cache: bool = True,
) -> str:
    payload = latest_manual_pack_manifest(conn, run_id)
    pack_hash = normalize_sha256(payload.get("pack_hash"), field="manual_research_pack.pack_hash")
    content_cache = payload.get("content_cache")
    if not isinstance(content_cache, dict):
        if verify_content_cache:
            raise ArtifactFreezeError("manual_research_pack 缺少 content_cache，无法复核研究包内容")
        return pack_hash
    cached_hash = normalize_sha256(content_cache.get("hash"), field="content_cache.hash")
    if cached_hash != pack_hash:
        raise ArtifactFreezeError(
            f"研究包 hash 与内容缓存不一致: pack={pack_hash}, cache={cached_hash}"
        )
    if not verify_content_cache:
        return pack_hash
    raw_path = str(content_cache.get("path") or "").strip()
    if not raw_path:
        raise ArtifactFreezeError("content_cache.path 为空，无法复核研究包内容")
    cache_path = Path(raw_path)
    if not cache_path.is_absolute():
        cache_path = Path(project_root) / cache_path
    if not cache_path.is_file():
        raise ArtifactFreezeError(f"研究包内容缓存不存在: {cache_path}")
    actual_hash = sha256_bytes(cache_path.read_bytes())
    if actual_hash != pack_hash:
        raise ArtifactFreezeError(
            f"研究包内容缓存已改变: expected={pack_hash}, actual={actual_hash}"
        )
    return pack_hash


def viewer_bundle_files(project_root: str | Path = ROOT) -> list[Path]:
    root = Path(project_root).resolve()
    viewer_root = root / "tools" / "viewer"
    if not viewer_root.is_dir():
        raise ArtifactFreezeError(f"viewer 目录不存在: {viewer_root}")
    files = [
        path
        for path in viewer_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in VIEWER_BUNDLE_SUFFIXES
        and "__pycache__" not in path.parts
    ]
    files.extend(
        path
        for relative in VIEWER_RUNTIME_DEPENDENCIES
        if (path := root / relative).is_file()
    )
    if not files:
        raise ArtifactFreezeError("viewer bundle 没有可冻结的 .py/.html/.css/.js 文件")
    return sorted(set(files), key=lambda path: path.relative_to(root).as_posix())


def viewer_bundle_manifest(
    project_root: str | Path = ROOT,
    *,
    files: Iterable[Path] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    selected = list(files) if files is not None else viewer_bundle_files(root)
    records: list[dict[str, Any]] = []
    for path in sorted(selected, key=lambda item: item.resolve().relative_to(root).as_posix()):
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise ArtifactFreezeError(f"viewer bundle 文件不在项目根目录内: {resolved}") from exc
        records.append(
            {
                "path": relative,
                "size": resolved.stat().st_size,
                "sha256": sha256_bytes(resolved.read_bytes()),
            }
        )
    payload = {
        "bundle_version": ARTIFACT_FREEZE_VERSION,
        "files": records,
    }
    payload["ui_bundle_hash"] = sha256_text(canonical_json(payload))
    payload["ui_file_count"] = len(records)
    return payload


def browser_input_hash(pack_hash: str, ui_bundle_hash: str) -> str:
    normalized_pack = normalize_sha256(pack_hash, field="pack_hash")
    normalized_ui = normalize_sha256(ui_bundle_hash, field="ui_bundle_hash")
    return sha256_text(
        canonical_json(
            {
                "freeze_version": ARTIFACT_FREEZE_VERSION,
                "pack_hash": normalized_pack,
                "ui_bundle_hash": normalized_ui,
            }
        )
    )


def build_artifact_freeze(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    project_root: str | Path = ROOT,
    verify_content_cache: bool = True,
) -> ArtifactFreeze:
    payload = latest_manual_pack_manifest(conn, run_id)
    schema_version = str(
        payload.get("pack_schema_version")
        or payload.get("_row_pack_schema_version")
        or ""
    )
    pack = current_pack_hash(
        conn,
        run_id,
        project_root=project_root,
        verify_content_cache=verify_content_cache,
    )
    ui = viewer_bundle_manifest(project_root)
    return ArtifactFreeze(
        run_id=run_id,
        pack_hash=pack,
        ui_bundle_hash=ui["ui_bundle_hash"],
        browser_input_hash=browser_input_hash(pack, ui["ui_bundle_hash"]),
        ui_file_count=ui["ui_file_count"],
        pack_schema_version=schema_version,
    )


def review_input_hash_for_stage(
    conn: sqlite3.Connection,
    run_id: int,
    review_stage: str,
    *,
    project_root: str | Path = ROOT,
) -> str:
    """返回 reviewer 必须写入 input_artifact_hash 的当前值。"""
    freeze = build_artifact_freeze(conn, run_id, project_root=project_root)
    return freeze.browser_input_hash if review_stage == "browser" else freeze.pack_hash


def main() -> None:
    from .db import connect

    parser = argparse.ArgumentParser(description="读取 Opportunity Lens 当前研究包与 UI 冻结指纹")
    parser.add_argument("run_id", type=int)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "opportunity_lens.db")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    args = parser.parse_args()
    conn = connect(args.db, readonly=True)
    try:
        freeze = build_artifact_freeze(conn, args.run_id, project_root=args.project_root)
    finally:
        conn.close()
    print(json.dumps(freeze.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
