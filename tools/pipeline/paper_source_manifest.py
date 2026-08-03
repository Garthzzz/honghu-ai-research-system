from __future__ import annotations

"""Downloaded-report provenance shared by A/B ingest and C-track producers."""

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


SCHEMA_VERSION = "research.paper_source_manifest.v1"
MANIFEST_DIRNAME = "_source_manifests"
_REQUIRED_ENTRY_FIELDS = {
    "relative_path",
    "sha256",
    "title",
    "publisher",
    "publish_date",
    "source_url",
    "report_scope",
    "publisher_origin",
    "fetch_method",
    "independence_key",
}
_SOURCE_IDENTITY_FIELDS = {
    "relative_path",
    "sha256",
    "title",
    "publisher",
    "publish_date",
    "source_url",
    "report_scope",
    "publisher_origin",
    "independence_key",
}


def hash_file(path: Path) -> str:
    """计算文件 SHA256。

    Args:
        path: 本机文件路径；按 bytes 读取。

    Returns:
        64 位小写十六进制 SHA256。
    """

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """原子写入 UTF-8 JSON，不产生半份 manifest。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _canonical_relative_path(value: str, *, project_root: Path) -> str:
    """规范化为项目相对 papers 路径并阻止越界。"""

    root = project_root.resolve()
    raw = Path(str(value or "").strip())
    path = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    papers_root = (root / "papers").resolve()
    if papers_root not in path.parents:
        raise ValueError(f"研报来源必须位于 papers/: {path}")
    return path.relative_to(root).as_posix()


def validate_manifest(payload: dict[str, Any], *, project_root: Path) -> dict[str, Any]:
    """校验来源 manifest 结构、路径和文件哈希。

    Args:
        payload: ``research.paper_source_manifest.v1`` JSON 对象。
        project_root: 项目根目录。

    Returns:
        路径已规范化的深拷贝式字典。
    """

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"不支持的 paper source manifest: {payload.get('schema_version')}")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("paper source manifest entries 必须是数组")
    normalized: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, raw in enumerate(entries, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"entries[{index}] 必须是对象")
        missing = sorted(field for field in _REQUIRED_ENTRY_FIELDS if not raw.get(field))
        if missing:
            raise ValueError(f"entries[{index}] 缺少字段: {missing}")
        entry = dict(raw)
        relative = _canonical_relative_path(entry["relative_path"], project_root=project_root)
        if relative in seen_paths:
            raise ValueError(f"manifest 重复 relative_path: {relative}")
        seen_paths.add(relative)
        source_path = (project_root / relative).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        actual_hash = hash_file(source_path)
        if str(entry["sha256"]).lower() != actual_hash:
            raise ValueError(f"研报哈希不一致: {relative}")
        scope = str(entry["report_scope"]).strip().lower()
        if scope not in {"company", "industry"}:
            raise ValueError(f"非法 report_scope: {scope}")
        origin = str(entry["publisher_origin"]).strip().lower()
        if origin not in {"domestic", "foreign"}:
            raise ValueError(f"非法 publisher_origin: {origin}")
        entry["relative_path"] = relative
        entry["report_scope"] = scope
        entry["publisher_origin"] = origin
        entry["sha256"] = actual_hash
        normalized.append(entry)
    result = dict(payload)
    result["entries"] = normalized
    return result


def write_manifest(
    path: Path,
    *,
    project_root: Path,
    payload: dict[str, Any],
) -> Path:
    """校验并原子保存来源 manifest。

    Args:
        path: ``papers/<行业>/_source_manifests`` 下的 JSON 路径。
        project_root: 项目根目录。
        payload: 完整 manifest；entry 路径以项目相对路径表示。

    Returns:
        已写入的绝对路径。
    """

    root = project_root.resolve()
    target = path.resolve()
    papers_root = (root / "papers").resolve()
    if papers_root not in target.parents or MANIFEST_DIRNAME not in target.parts:
        raise ValueError(f"来源 manifest 必须写入 papers 下的 {MANIFEST_DIRNAME}: {target}")
    validated = validate_manifest(payload, project_root=root)
    _atomic_write_json(target, validated)
    return target


def load_manifests(papers_dir: Path, *, project_root: Path) -> dict[str, dict[str, Any]]:
    """加载一个行业资料夹的来源清单。

    Args:
        papers_dir: ``papers/<行业>`` 目录。
        project_root: 项目根目录。

    Returns:
        ``项目相对 PDF 路径 -> 来源元数据``；重复路径且元数据冲突时失败。
    """

    directory = (papers_dir / MANIFEST_DIRNAME).resolve()
    if not directory.is_dir():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        payload = validate_manifest(
            json.loads(path.read_text(encoding="utf-8")),
            project_root=project_root,
        )
        for entry in payload["entries"]:
            relative = entry["relative_path"]
            existing = rows.get(relative)
            if existing is not None:
                conflicts = sorted(
                    field
                    for field in _SOURCE_IDENTITY_FIELDS
                    if existing.get(field) != entry.get(field)
                )
                if conflicts:
                    raise ValueError(
                        f"研报来源 manifest 冲突: {relative}; fields={conflicts}"
                    )
                merged = dict(existing)
                for key, value in entry.items():
                    if merged.get(key) in (None, "", [], {}):
                        merged[key] = value
                rows[relative] = merged
            else:
                rows[relative] = entry
    return rows


def _source_relative_path(
    source_file: str,
    *,
    papers_subdir: str,
    project_root: Path,
) -> str:
    raw = Path(str(source_file or "").strip())
    if raw.is_absolute():
        candidate = raw.resolve()
    elif raw.parts and raw.parts[0].lower() == "papers":
        candidate = (project_root / raw).resolve()
    else:
        candidate = (project_root / "papers" / papers_subdir / raw).resolve()
    return candidate.relative_to(project_root.resolve()).as_posix()


def enrich_claim_sources(
    documents: Iterable[dict[str, Any]],
    *,
    papers_subdir: str,
    project_root: Path,
) -> int:
    """用下载清单补齐 claims 中引用的研报来源字段。

    Args:
        documents: A/B claims 文档；仅修改其 ``sources`` 对象。
        papers_subdir: 当前行业 papers 子目录名。
        project_root: 项目根目录。

    Returns:
        成功补充的 source 数量。已有显式字段优先，不被清单覆盖。
    """

    manifest_rows = load_manifests(
        project_root / "papers" / papers_subdir,
        project_root=project_root,
    )
    enriched = 0
    if not manifest_rows:
        return enriched
    for document in documents:
        for source in document.get("sources", []):
            if not isinstance(source, dict) or not source.get("source_file"):
                continue
            relative = _source_relative_path(
                str(source["source_file"]),
                papers_subdir=papers_subdir,
                project_root=project_root,
            )
            entry = manifest_rows.get(relative)
            if entry is None:
                continue
            defaults = {
                "title": entry["title"],
                "publisher": entry["publisher"],
                "publish_date": entry["publish_date"],
                "source_url": entry["source_url"],
                "source_type": entry.get("source_type") or "卖方深度",
                "value_layer": entry.get("value_layer") or "深度框架",
                "quality_tier": int(entry.get("quality_tier") or 2),
                "is_primary_source": False,
                "fetch_method": entry["fetch_method"],
                "fetch_timestamp": entry.get("downloaded_at_utc"),
                "source_credibility": entry.get("source_credibility") or "sell_side_secondary",
                "source_subtype": (
                    f"{entry['publisher_origin']}_sell_side_{entry['report_scope']}_report"
                ),
                "domain": "r.datayes.com",
                "source_channel": "report",
                "language": entry.get("language") or "zh",
            }
            for key, value in defaults.items():
                if source.get(key) in (None, ""):
                    source[key] = value
            enriched += 1
    return enriched


def opportunity_source_from_manifest(
    entry: dict[str, Any],
    *,
    project_root: Path,
    ref: str,
    excerpt: str,
    excerpt_zh: str | None = None,
    title_zh: str | None = None,
) -> dict[str, Any]:
    """把已下载研报转换为 C 轨待核验 source，而不是直接认证为证据。

    producer 必须提供本轮实际使用的原文摘录；英文材料还必须提供中文译意。
    转换时再次核验本地文件和 SHA256，返回 ``source_review_status=pending``，
    后续仍需 evidence reviewer。
    """

    source_ref = str(ref or "").strip()
    original_excerpt = str(excerpt or "").strip()
    if not source_ref or not original_excerpt:
        raise ValueError("C 轨来源转换必须提供 ref 和本轮实际引用的 excerpt")
    relative = _canonical_relative_path(
        str(entry.get("relative_path") or ""),
        project_root=project_root,
    )
    source_path = (project_root.resolve() / relative).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    actual_hash = hash_file(source_path)
    if actual_hash != str(entry.get("sha256") or "").lower():
        raise ValueError(f"C 轨来源文件哈希不一致: {relative}")
    language = str(entry.get("language") or "zh").strip().lower()
    chinese_excerpt = str(excerpt_zh or "").strip()
    if language.startswith("en") and not chinese_excerpt:
        raise ValueError("英文研报进入 C 轨前必须提供 excerpt_zh")
    title = str(entry.get("title") or "").strip()
    chinese_title = str(title_zh or title).strip()
    return {
        "ref": source_ref,
        "title": title,
        "title_zh": chinese_title,
        "publisher": str(entry.get("publisher") or "").strip(),
        "publish_date": str(entry.get("publish_date") or "").strip(),
        "url": str(entry.get("source_url") or "").strip(),
        "local_path": str(source_path),
        "source_tier": "B",
        "source_review_status": "pending",
        "excerpt": original_excerpt,
        "excerpt_zh": chinese_excerpt or original_excerpt,
        "language": language,
        "source_channel": "report",
        "independence_key": str(entry.get("independence_key") or "").strip(),
        "independence_rationale": str(
            entry.get("independence_rationale")
            or "按底层券商、报告标题和发布日期去重；聚合入口不计作独立发布方。"
        ).strip(),
        "document_sha256": actual_hash,
        "aggregator": str(entry.get("aggregator") or "萝卜投研").strip(),
    }
