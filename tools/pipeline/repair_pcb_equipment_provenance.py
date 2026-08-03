#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Safely repair existing PCB-equipment data points from a corrected claims bundle.

The repair contract is deliberately narrow:

* The old and corrected claims files are compared position by position.
* Every old claim must match exactly one existing ``industry_data_point`` row by
  all persisted claim fields (including resolved source/company foreign keys).
* Only existing rows for ``industry_id=23`` are changed, and the only database
  DML issued by this program is ``UPDATE industry_data_point``.
* The default mode is a read-only dry-run.  It copies the database into memory,
  executes the complete transaction there, validates the corrected target, and
  rolls the transaction back.
* A real write requires both ``--apply`` and ``--manifest``.  All updates run in
  one ``BEGIN IMMEDIATE`` transaction and are committed only after row-count,
  identity, target-state, and foreign-key checks pass.

Top-level source metadata is audited but intentionally not written here.  It is
owned by the separate source-registration repair.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "research.db"
DEFAULT_OLD_CLAIMS = (
    ROOT / "cache" / "claims" / "pcb_equipment_b_20260719_01_full_claims.json"
)
DEFAULT_NEW_CLAIMS = (
    ROOT
    / "cache"
    / "pcb_equipment_research"
    / "pcb_equipment_corrected_claims_v3.json"
)
DEFAULT_SOURCE_MAP = (
    ROOT / "cache" / "db_queue" / "pcb_equipment_b_20260719_source_map.json"
)

INDUSTRY_ID = 23
EXPECTED_INDUSTRY_NAME = "PCB专用设备"
EXPECTED_DATA_POINT_COUNT = 1064
EXPECTED_CHANGED_POSITION_COUNT = 940
EXPECTED_OLD_SHA256 = (
    "177878d33d79af352bb1667e7d03f5fdeb31eb60f50a461f24044ea18367eb94"
)
EXPECTED_NEW_SHA256 = (
    "d0abc2d6ca4293cd81113bac56422019675c3744d91248dd0bb548be0f53979d"
)
EXPECTED_FIELD_DIFF_COUNTS = {
    "as_of_date": 135,
    "extraction_method": 318,
    "metric": 56,
    "note": 925,
    "period": 22,
    "scope_key": 30,
    "source_excerpt": 527,
    "unit": 22,
    "value_num": 171,
    "value_text": 22,
}
EXPECTED_OLD_FACT_COUNT = 459
EXPECTED_NEW_FACT_COUNT = 471

CLAIM_FIELDS = (
    "source_ref",
    "company",
    "metric",
    "period",
    "as_of_date",
    "value_num",
    "value_text",
    "unit",
    "is_forecast",
    "sentiment",
    "extraction_method",
    "scope_key",
    "source_excerpt",
    "note",
)

# Persisted claim fields. source_ref and company resolve to the two foreign keys;
# scope_key remains an input/audit identity because the live table has no column
# for it.
CLAIM_TO_DB_FIELD = {
    "source_ref": "source_id",
    "company": "company_id",
    "metric": "metric",
    "period": "period",
    "as_of_date": "as_of_date",
    "value_num": "value_num",
    "value_text": "value_text",
    "unit": "unit",
    "is_forecast": "is_forecast",
    "sentiment": "sentiment",
    "extraction_method": "extraction_method",
    "source_excerpt": "source_excerpt",
    "note": "note",
}

PERSISTED_CLAIM_FIELDS = (
    "source_id",
    "company_id",
    "metric",
    "period",
    "as_of_date",
    "value_num",
    "value_text",
    "unit",
    "is_forecast",
    "sentiment",
    "extraction_method",
    "source_excerpt",
    "note",
)

CONSENSUS_FIELDS = (
    "consensus_status",
    "peer_count",
    "peer_median",
    "peer_std",
    "deviation_from_median",
)

SELECT_FIELDS = (
    "id",
    "industry_id",
    *PERSISTED_CLAIM_FIELDS,
    *CONSENSUS_FIELDS,
    "created_at",
    "last_verified_at",
)

UPDATE_ORDER = (
    "source_id",
    "company_id",
    "metric",
    "period",
    "as_of_date",
    "value_num",
    "value_text",
    "unit",
    "is_forecast",
    "sentiment",
    "extraction_method",
    "source_excerpt",
    "note",
    *CONSENSUS_FIELDS,
)

ALLOWED_EXTRACTION_METHODS = {"pdf_direct", "web_fetch", "inferred"}


class AuditError(RuntimeError):
    """Raised when a safety invariant or reconciliation check fails."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"无法读取 JSON：{path}: {exc}") from exc


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _open_read_only(path: Path) -> sqlite3.Connection:
    # Path.as_uri gives SQLite a correct Windows drive-letter URI.
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _open_read_write(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path.resolve()))
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _open_memory_copy(path: Path) -> tuple[sqlite3.Connection, dict[str, Any]]:
    source = _open_read_only(path)
    try:
        source_snapshot = _database_snapshot(source)
        memory = sqlite3.connect(":memory:")
        memory.row_factory = sqlite3.Row
        memory.isolation_level = None
        source.backup(memory)
    finally:
        source.close()
    memory.execute("PRAGMA foreign_keys=ON")
    memory_snapshot = _database_snapshot(memory)
    if source_snapshot != memory_snapshot:
        memory.close()
        raise AuditError("内存副本与只读源库快照不一致")
    return memory, source_snapshot


def _install_update_only_authorizer(conn: sqlite3.Connection) -> None:
    """Make the UPDATE-only contract executable, not merely conventional."""

    def authorize(
        action: int,
        object_name: str | None,
        _column_or_detail: str | None,
        _database_name: str | None,
        _trigger_name: str | None,
    ) -> int:
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_DELETE):
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_UPDATE and object_name != "industry_data_point":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(authorize)


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuditError(f"{label} 必须是 JSON object")
    return value


def _validate_claim_bundle(
    bundle: Any, *, label: str, expected_sha256: str, actual_sha256: str
) -> dict[str, Any]:
    document = dict(_require_mapping(bundle, label))
    if actual_sha256.lower() != expected_sha256.lower():
        raise AuditError(
            f"{label} SHA256 不匹配：expected={expected_sha256}, actual={actual_sha256}"
        )
    expected_top_level = {"meta", "sources", "data_points", "key_arguments"}
    if set(document) != expected_top_level:
        raise AuditError(
            f"{label} 顶层字段变化：expected={sorted(expected_top_level)}, "
            f"actual={sorted(document)}"
        )
    meta = _require_mapping(document["meta"], f"{label}.meta")
    if meta.get("industry") != EXPECTED_INDUSTRY_NAME:
        raise AuditError(
            f"{label}.meta.industry={meta.get('industry')!r}，预期 {EXPECTED_INDUSTRY_NAME!r}"
        )
    sources = document["sources"]
    data_points = document["data_points"]
    if not isinstance(sources, list) or not isinstance(data_points, list):
        raise AuditError(f"{label}.sources/data_points 必须是数组")
    if len(data_points) != EXPECTED_DATA_POINT_COUNT:
        raise AuditError(
            f"{label} 数据点数={len(data_points)}，预期 {EXPECTED_DATA_POINT_COUNT}"
        )

    source_refs: set[str] = set()
    for index, source in enumerate(sources):
        source = _require_mapping(source, f"{label}.sources[{index}]")
        source_ref = source.get("source_ref")
        if not isinstance(source_ref, str) or not source_ref:
            raise AuditError(f"{label}.sources[{index}].source_ref 无效")
        if source_ref in source_refs:
            raise AuditError(f"{label} 存在重复 source_ref：{source_ref}")
        source_refs.add(source_ref)

    for index, data_point in enumerate(data_points):
        data_point = _require_mapping(data_point, f"{label}.data_points[{index}]")
        if set(data_point) != set(CLAIM_FIELDS):
            raise AuditError(
                f"{label}.data_points[{index}] 字段变化："
                f"missing={sorted(set(CLAIM_FIELDS) - set(data_point))}, "
                f"extra={sorted(set(data_point) - set(CLAIM_FIELDS))}"
            )
        if data_point["source_ref"] not in source_refs:
            raise AuditError(
                f"{label}.data_points[{index}] 引用未声明来源："
                f"{data_point['source_ref']!r}"
            )
        for field in ("metric", "period", "unit", "sentiment", "source_excerpt"):
            if not isinstance(data_point[field], str) or not data_point[field]:
                raise AuditError(
                    f"{label}.data_points[{index}].{field} 必须是非空字符串"
                )
        method = data_point["extraction_method"]
        if method not in ALLOWED_EXTRACTION_METHODS:
            raise AuditError(
                f"{label}.data_points[{index}].extraction_method={method!r} 不允许"
            )
        forecast = data_point["is_forecast"]
        if not isinstance(forecast, (bool, int)) or int(forecast) not in (0, 1):
            raise AuditError(
                f"{label}.data_points[{index}].is_forecast={forecast!r} 无效"
            )
        value_num = data_point["value_num"]
        if value_num is not None:
            if isinstance(value_num, bool) or not isinstance(value_num, (int, float)):
                raise AuditError(
                    f"{label}.data_points[{index}].value_num={value_num!r} 不是数值"
                )
            if not math.isfinite(float(value_num)):
                raise AuditError(
                    f"{label}.data_points[{index}].value_num 不是有限数值"
                )
        company = data_point["company"]
        if company is not None and (not isinstance(company, str) or not company):
            raise AuditError(f"{label}.data_points[{index}].company 无效")
        scope_key = data_point["scope_key"]
        if not isinstance(scope_key, str) or not scope_key:
            raise AuditError(f"{label}.data_points[{index}].scope_key 无效")
    return document


def _source_locator(source: Mapping[str, Any]) -> str:
    source_file = source.get("source_file")
    source_url = source.get("source_url")
    if source_file:
        return f"file:{str(source_file).replace(chr(92), '/')}"
    if source_url:
        return f"url:{source_url}"
    raise AuditError(f"来源 {source.get('source_ref')!r} 缺少 source_file/source_url")


def _source_metadata_delta(
    old_sources: Sequence[Mapping[str, Any]],
    new_sources: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    old_by_ref = {source["source_ref"]: dict(source) for source in old_sources}
    new_by_ref = {source["source_ref"]: dict(source) for source in new_sources}
    added = [new_by_ref[ref] for ref in sorted(set(new_by_ref) - set(old_by_ref))]
    removed = [old_by_ref[ref] for ref in sorted(set(old_by_ref) - set(new_by_ref))]
    modified: list[dict[str, Any]] = []
    for ref in sorted(set(old_by_ref) & set(new_by_ref)):
        old = old_by_ref[ref]
        new = new_by_ref[ref]
        changes = {
            field: {"old": old.get(field), "new": new.get(field)}
            for field in sorted(set(old) | set(new))
            if old.get(field) != new.get(field)
        }
        if changes:
            modified.append({"source_ref": ref, "changed_fields": changes})
    return {
        "owner": "separate_source_registration_script",
        "written_by_this_script": False,
        "reason": "本脚本仅更新既有 industry_data_point；source metadata 独立注册。",
        "old_source_count": len(old_sources),
        "new_source_count": len(new_sources),
        "added_count": len(added),
        "removed_count": len(removed),
        "modified_existing_count": len(modified),
        "added": added,
        "removed": removed,
        "modified_existing": modified,
    }


def _claim_delta(
    old_points: Sequence[Mapping[str, Any]],
    new_points: Sequence[Mapping[str, Any]],
) -> tuple[list[int], dict[str, int]]:
    if len(old_points) != len(new_points):
        raise AuditError(
            f"claims 长度不同：old={len(old_points)}, new={len(new_points)}"
        )
    changed_positions: list[int] = []
    field_counts: Counter[str] = Counter()
    for index, (old, new) in enumerate(zip(old_points, new_points)):
        changed = [field for field in CLAIM_FIELDS if old.get(field) != new.get(field)]
        if changed:
            changed_positions.append(index)
            field_counts.update(changed)
    actual_counts = dict(sorted(field_counts.items()))
    if len(changed_positions) != EXPECTED_CHANGED_POSITION_COUNT:
        raise AuditError(
            f"变更位置数={len(changed_positions)}，预期 {EXPECTED_CHANGED_POSITION_COUNT}"
        )
    if actual_counts != EXPECTED_FIELD_DIFF_COUNTS:
        raise AuditError(
            "逐字段差异计数不匹配："
            f"expected={EXPECTED_FIELD_DIFF_COUNTS}, actual={actual_counts}"
        )
    return changed_positions, actual_counts


def _fact_count(points: Sequence[Mapping[str, Any]]) -> int:
    return len(
        {
            (
                point.get("source_ref"),
                point.get("company"),
                point.get("metric"),
                point.get("unit"),
                point.get("scope_key"),
            )
            for point in points
        }
    )


def _build_source_ref_map(
    conn: sqlite3.Connection,
    old_bundle: Mapping[str, Any],
    new_bundle: Mapping[str, Any],
    raw_source_map: Any,
) -> dict[str, int]:
    if not isinstance(raw_source_map, Mapping):
        raise AuditError("source map 必须是 JSON object")
    source_map: dict[str, int] = {}
    for locator, source_id in raw_source_map.items():
        if not isinstance(locator, str) or not isinstance(source_id, int):
            raise AuditError(f"source map 项无效：{locator!r} -> {source_id!r}")
        source_map[locator.replace(chr(92), "/")] = source_id

    # Source registration is a separate operation.  Resolve only references that
    # are actually persisted by a data point; newly declared but unused sources
    # must not make this UPDATE-only repair depend on source-registration order.
    required_refs = {
        point["source_ref"]
        for bundle in (old_bundle, new_bundle)
        for point in bundle["data_points"]
    }
    all_sources: dict[str, Mapping[str, Any]] = {}
    for label, sources in (
        ("old", old_bundle["sources"]),
        ("new", new_bundle["sources"]),
    ):
        for source in sources:
            ref = source["source_ref"]
            if ref not in required_refs:
                continue
            if ref in all_sources:
                previous_locator = _source_locator(all_sources[ref])
                current_locator = _source_locator(source)
                if previous_locator != current_locator:
                    raise AuditError(
                        f"同一 source_ref 的定位变化：{ref}: "
                        f"{previous_locator!r} -> {current_locator!r} ({label})"
                    )
            else:
                all_sources[ref] = source

    missing_definitions = required_refs - set(all_sources)
    if missing_definitions:
        raise AuditError(
            f"data_points 引用的来源没有 metadata 定义：{sorted(missing_definitions)}"
        )

    result: dict[str, int] = {}
    for ref, source in all_sources.items():
        locator = _source_locator(source)
        source_id = source_map.get(locator)
        if source_id is None:
            raise AuditError(f"source map 未找到 {ref!r} 的定位：{locator!r}")
        row = conn.execute(
            "SELECT id, file_path, url, source_url FROM source WHERE id=?",
            (source_id,),
        ).fetchone()
        if row is None:
            raise AuditError(f"source_id={source_id} 不存在（source_ref={ref}）")
        if locator.startswith("file:"):
            expected = locator[5:]
            actual = (row["file_path"] or "").replace(chr(92), "/")
            if actual != expected:
                raise AuditError(
                    f"source_id={source_id} 文件定位不一致：{actual!r} != {expected!r}"
                )
        else:
            expected = locator[4:]
            if expected not in {row["source_url"], row["url"]}:
                raise AuditError(
                    f"source_id={source_id} URL 定位不一致："
                    f"source_url={row['source_url']!r}, url={row['url']!r}, "
                    f"expected={expected!r}"
                )
        result[ref] = source_id
    return result


def _company_name_map(conn: sqlite3.Connection) -> dict[str, int]:
    grouped: defaultdict[str, list[int]] = defaultdict(list)
    for row in conn.execute("SELECT id, name FROM company"):
        grouped[row["name"]].append(row["id"])
    duplicates = {name: ids for name, ids in grouped.items() if len(ids) != 1}
    if duplicates:
        raise AuditError(f"company.name 非唯一：{duplicates}")
    return {name: ids[0] for name, ids in grouped.items()}


def _claim_state(
    point: Mapping[str, Any],
    source_ref_map: Mapping[str, int],
    company_name_map: Mapping[str, int],
) -> dict[str, Any]:
    source_ref = point["source_ref"]
    if source_ref not in source_ref_map:
        raise AuditError(f"无法解析 source_ref={source_ref!r}")
    company = point.get("company")
    if company is None:
        company_id = None
    else:
        company_id = company_name_map.get(company)
        if company_id is None:
            raise AuditError(f"无法解析 company={company!r}")
    return {
        "source_id": source_ref_map[source_ref],
        "company_id": company_id,
        "metric": point["metric"],
        "period": point["period"],
        "as_of_date": point.get("as_of_date"),
        "value_num": point.get("value_num"),
        "value_text": point.get("value_text"),
        "unit": point["unit"],
        "is_forecast": int(point["is_forecast"]),
        "sentiment": point["sentiment"],
        "extraction_method": point["extraction_method"],
        "source_excerpt": point["source_excerpt"],
        "note": point.get("note"),
    }


def _consensus_state(point: Mapping[str, Any]) -> dict[str, Any]:
    """Keep per-row consensus internally consistent without touching peer tables.

    This run's claims represent independent facts (scope_key is part of fact
    identity), while scope_key is not persisted in the legacy peer-group schema.
    Therefore the repair preserves the ingest-time singleton convention instead
    of merging same-date rows that have different scopes.
    """

    value_num = point.get("value_num")
    if value_num is None:
        return {
            "consensus_status": "unevaluated",
            "peer_count": 0,
            "peer_median": None,
            "peer_std": None,
            "deviation_from_median": None,
        }
    numeric = float(value_num)
    return {
        "consensus_status": "孤证",
        "peer_count": 1,
        "peer_median": numeric,
        "peer_std": 0.0,
        "deviation_from_median": 0.0,
    }


def _values_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(
            float(left), float(right), rel_tol=1e-12, abs_tol=1e-12
        )
    return left == right


def _state_equal(row: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return all(_values_equal(row[field], value) for field, value in expected.items())


def _row_values(row: Mapping[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    return {field: row[field] for field in fields}


def _claim_key(point: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_ref": point.get("source_ref"),
        "company": point.get("company"),
        "scope_key": point.get("scope_key"),
        "metric": point.get("metric"),
        "period": point.get("period"),
        "as_of_date": point.get("as_of_date"),
        "unit": point.get("unit"),
    }


def _database_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    industry = conn.execute(
        "SELECT id, name FROM industry WHERE id=?", (INDUSTRY_ID,)
    ).fetchone()
    if industry is None or industry["name"] != EXPECTED_INDUSTRY_NAME:
        raise AuditError(
            f"industry_id={INDUSTRY_ID} 不存在或名称不匹配："
            f"{None if industry is None else industry['name']!r}"
        )
    target_rows = [
        dict(row)
        for row in conn.execute(
            f"SELECT {', '.join(SELECT_FIELDS)} "
            "FROM industry_data_point WHERE industry_id=? ORDER BY id",
            (INDUSTRY_ID,),
        )
    ]
    if len(target_rows) != EXPECTED_DATA_POINT_COUNT:
        raise AuditError(
            f"industry_id={INDUSTRY_ID} 行数={len(target_rows)}，"
            f"预期 {EXPECTED_DATA_POINT_COUNT}"
        )
    target_ids = [row["id"] for row in target_rows]
    global_ids = [
        row[0]
        for row in conn.execute("SELECT id FROM industry_data_point ORDER BY id")
    ]
    return {
        "industry_id": INDUSTRY_ID,
        "industry_name": industry["name"],
        "target_row_count": len(target_rows),
        "target_id_sha256": _json_hash(target_ids),
        "target_content_sha256": _json_hash(target_rows),
        "global_row_count": len(global_ids),
        "global_id_sha256": _json_hash(global_ids),
        "extraction_method_distribution": dict(
            sorted(Counter(row["extraction_method"] for row in target_rows).items())
        ),
        "consensus_status_distribution": dict(
            sorted(Counter(row["consensus_status"] for row in target_rows).items())
        ),
    }


def _foreign_key_violations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {
            "table": row[0],
            "rowid": row[1],
            "parent": row[2],
            "fk_index": row[3],
        }
        for row in conn.execute("PRAGMA foreign_key_check")
    ]


def _prepare_plan(
    conn: sqlite3.Connection,
    old_bundle: Mapping[str, Any],
    new_bundle: Mapping[str, Any],
    source_map: Any,
    changed_positions: Sequence[int],
) -> tuple[list[dict[str, Any]], dict[int, int], dict[str, Any]]:
    source_ref_map = _build_source_ref_map(conn, old_bundle, new_bundle, source_map)
    company_name_map = _company_name_map(conn)
    old_points = old_bundle["data_points"]
    new_points = new_bundle["data_points"]

    rows = [
        dict(row)
        for row in conn.execute(
            f"SELECT {', '.join(SELECT_FIELDS)} "
            "FROM industry_data_point WHERE industry_id=? ORDER BY id",
            (INDUSTRY_ID,),
        )
    ]
    grouped: defaultdict[tuple[int, int | None], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["source_id"], row["company_id"])].append(row)

    position_to_id: dict[int, int] = {}
    used_ids: set[int] = set()
    old_states: list[dict[str, Any]] = []
    new_states: list[dict[str, Any]] = []
    for index, (old_point, new_point) in enumerate(zip(old_points, new_points)):
        old_state = _claim_state(old_point, source_ref_map, company_name_map)
        new_state = _claim_state(new_point, source_ref_map, company_name_map)
        old_states.append(old_state)
        new_states.append(new_state)
        candidates = [
            row
            for row in grouped[(old_state["source_id"], old_state["company_id"])]
            if _state_equal(row, old_state)
        ]
        if len(candidates) != 1:
            raise AuditError(
                f"旧 claim 位置 {index} 未能全字段唯一匹配："
                f"candidate_count={len(candidates)}, key={_claim_key(old_point)}"
            )
        row_id = candidates[0]["id"]
        if row_id in used_ids:
            raise AuditError(f"DB 行 id={row_id} 被多个旧 claim 重复匹配")
        used_ids.add(row_id)
        position_to_id[index] = row_id

        expected_consensus = _consensus_state(old_point)
        if not _state_equal(candidates[0], expected_consensus):
            raise AuditError(
                f"旧 claim 位置 {index} 的共识派生字段不一致："
                f"id={row_id}, expected={expected_consensus}, "
                f"actual={_row_values(candidates[0], CONSENSUS_FIELDS)}"
            )

    if len(used_ids) != EXPECTED_DATA_POINT_COUNT:
        raise AuditError(
            f"旧 claims 仅唯一覆盖 {len(used_ids)} 行，预期 {EXPECTED_DATA_POINT_COUNT}"
        )
    db_ids = {row["id"] for row in rows}
    if used_ids != db_ids:
        raise AuditError(
            "旧 claims 与 DB 行集合不是一一对应："
            f"unmatched_db_ids={sorted(db_ids - used_ids)[:20]}"
        )

    changed_set = set(changed_positions)
    patches: list[dict[str, Any]] = []
    for index in changed_positions:
        old_point = old_points[index]
        new_point = new_points[index]
        row_id = position_to_id[index]
        current = next(row for row in rows if row["id"] == row_id)
        old_state = old_states[index]
        target_state = dict(new_states[index])
        target_state.update(_consensus_state(new_point))

        claim_changes = {
            field: {"old": old_point.get(field), "new": new_point.get(field)}
            for field in CLAIM_FIELDS
            if old_point.get(field) != new_point.get(field)
        }
        db_changes: dict[str, dict[str, Any]] = {}
        for field in UPDATE_ORDER:
            target_value = target_state[field]
            if not _values_equal(current[field], target_value):
                reason = (
                    "claim_delta"
                    if field in CLAIM_TO_DB_FIELD.values()
                    else "derived_consensus_invariant"
                )
                db_changes[field] = {
                    "old": current[field],
                    "new": target_value,
                    "reason": reason,
                }
        if not db_changes:
            raise AuditError(
                f"位置 {index} 只有不可持久化差异，无法生成 UPDATE：{claim_changes}"
            )
        patches.append(
            {
                "position": index,
                "data_point_id": row_id,
                "old_claim_key": _claim_key(old_point),
                "new_claim_key": _claim_key(new_point),
                "changed_claim_fields": claim_changes,
                "non_persisted_claim_changes": {
                    field: change
                    for field, change in claim_changes.items()
                    if field not in CLAIM_TO_DB_FIELD
                },
                "db_field_changes": db_changes,
                "old_persisted_state": _row_values(
                    current, (*PERSISTED_CLAIM_FIELDS, *CONSENSUS_FIELDS)
                ),
                "new_persisted_state": target_state,
            }
        )

    if len(patches) != EXPECTED_CHANGED_POSITION_COUNT:
        raise AuditError(
            f"UPDATE 计划={len(patches)} 行，预期 {EXPECTED_CHANGED_POSITION_COUNT}"
        )
    if {patch["position"] for patch in patches} != changed_set:
        raise AuditError("UPDATE 计划位置集合与 claims 差异位置集合不一致")
    plan_audit = {
        "old_claim_match_count": len(position_to_id),
        "old_claim_unique_match_count": len(used_ids),
        "old_claim_unmatched_count": 0,
        "old_claim_ambiguous_count": 0,
        "db_unmatched_row_count": 0,
        "planned_update_count": len(patches),
        "planned_update_id_sha256": _json_hash(
            sorted(patch["data_point_id"] for patch in patches)
        ),
        "source_ref_resolution_count": len(source_ref_map),
        "company_resolution_count": len(company_name_map),
    }
    return patches, position_to_id, plan_audit


def _assert_current_patch_state(
    conn: sqlite3.Connection, patch: Mapping[str, Any]
) -> None:
    row = conn.execute(
        f"SELECT {', '.join((*PERSISTED_CLAIM_FIELDS, *CONSENSUS_FIELDS))} "
        "FROM industry_data_point WHERE id=? AND industry_id=?",
        (patch["data_point_id"], INDUSTRY_ID),
    ).fetchone()
    if row is None:
        raise AuditError(
            f"UPDATE 前行消失：id={patch['data_point_id']}, industry_id={INDUSTRY_ID}"
        )
    expected = patch["old_persisted_state"]
    if not _state_equal(row, expected):
        differences = {
            field: {"expected": value, "actual": row[field]}
            for field, value in expected.items()
            if not _values_equal(row[field], value)
        }
        raise AuditError(
            f"UPDATE 前 old-state guard 失败：id={patch['data_point_id']}, "
            f"differences={differences}"
        )


def _execute_patches(
    conn: sqlite3.Connection, patches: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    total_changes_before = conn.total_changes
    updated_ids: list[int] = []
    update_field_counts: Counter[str] = Counter()
    for patch in patches:
        _assert_current_patch_state(conn, patch)
        changes = patch["db_field_changes"]
        columns = [field for field in UPDATE_ORDER if field in changes]
        if not columns:
            raise AuditError(f"id={patch['data_point_id']} 没有可执行 UPDATE 字段")
        assignments = ", ".join(f"{field}=?" for field in columns)
        values = [changes[field]["new"] for field in columns]
        cursor = conn.execute(
            f"UPDATE industry_data_point SET {assignments} "
            "WHERE id=? AND industry_id=?",
            (*values, patch["data_point_id"], INDUSTRY_ID),
        )
        if cursor.rowcount != 1:
            raise AuditError(
                f"id={patch['data_point_id']} UPDATE rowcount={cursor.rowcount}，预期 1"
            )
        updated_ids.append(patch["data_point_id"])
        update_field_counts.update(columns)
    total_changes = conn.total_changes - total_changes_before
    if total_changes != len(patches):
        raise AuditError(
            f"SQLite total_changes={total_changes}，预期 {len(patches)}"
        )
    return {
        "update_statement_count": len(patches),
        "updated_row_count": len(set(updated_ids)),
        "updated_id_sha256": _json_hash(sorted(updated_ids)),
        "sqlite_total_changes": total_changes,
        "db_update_field_counts": dict(sorted(update_field_counts.items())),
    }


def _verify_corrected_target(
    conn: sqlite3.Connection,
    new_bundle: Mapping[str, Any],
    position_to_id: Mapping[int, int],
    source_map: Any,
    old_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    source_ref_map = _build_source_ref_map(conn, old_bundle, new_bundle, source_map)
    company_name_map = _company_name_map(conn)
    matched_ids: set[int] = set()
    for index, point in enumerate(new_bundle["data_points"]):
        row_id = position_to_id[index]
        row = conn.execute(
            f"SELECT {', '.join((*PERSISTED_CLAIM_FIELDS, *CONSENSUS_FIELDS))} "
            "FROM industry_data_point WHERE id=? AND industry_id=?",
            (row_id, INDUSTRY_ID),
        ).fetchone()
        if row is None:
            raise AuditError(f"目标校验时行不存在：id={row_id}")
        expected = _claim_state(point, source_ref_map, company_name_map)
        expected.update(_consensus_state(point))
        if not _state_equal(row, expected):
            differences = {
                field: {"expected": value, "actual": row[field]}
                for field, value in expected.items()
                if not _values_equal(row[field], value)
            }
            raise AuditError(
                f"corrected claim 位置 {index} 目标校验失败："
                f"id={row_id}, differences={differences}"
            )
        matched_ids.add(row_id)
    if len(matched_ids) != EXPECTED_DATA_POINT_COUNT:
        raise AuditError(
            f"corrected claims 仅覆盖 {len(matched_ids)} 个唯一 DB id"
        )
    return {
        "corrected_claim_match_count": EXPECTED_DATA_POINT_COUNT,
        "corrected_claim_unique_match_count": len(matched_ids),
        "corrected_claim_unmatched_count": 0,
        "corrected_claim_ambiguous_count": 0,
    }


def _assert_identity_preserved(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> None:
    invariant_fields = (
        "target_row_count",
        "target_id_sha256",
        "global_row_count",
        "global_id_sha256",
    )
    changed = {
        field: {"before": before[field], "after": after[field]}
        for field in invariant_fields
        if before[field] != after[field]
    }
    if changed:
        raise AuditError(f"UPDATE 改变了行数或 ID 集合：{changed}")


def _run_dry(
    db_path: Path,
    old_bundle: Mapping[str, Any],
    new_bundle: Mapping[str, Any],
    source_map: Any,
    changed_positions: Sequence[int],
) -> dict[str, Any]:
    conn, live_before = _open_memory_copy(db_path)
    try:
        _install_update_only_authorizer(conn)
        before = _database_snapshot(conn)
        before_fk = _foreign_key_violations(conn)
        if before_fk:
            raise AuditError(f"dry-run 基线已有 foreign_key_check 异常：{before_fk}")
        patches, position_to_id, plan_audit = _prepare_plan(
            conn, old_bundle, new_bundle, source_map, changed_positions
        )
        conn.execute("BEGIN IMMEDIATE")
        try:
            execution = _execute_patches(conn, patches)
            target = _verify_corrected_target(
                conn, new_bundle, position_to_id, source_map, old_bundle
            )
            staged_after = _database_snapshot(conn)
            _assert_identity_preserved(before, staged_after)
            after_fk = _foreign_key_violations(conn)
            if after_fk:
                raise AuditError(f"dry-run 后 foreign_key_check 异常：{after_fk}")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("ROLLBACK")
        rolled_back = _database_snapshot(conn)
        if rolled_back != before:
            raise AuditError("dry-run 回滚后内存副本未恢复到基线")
    finally:
        conn.close()

    live_after_conn = _open_read_only(db_path)
    try:
        live_after = _database_snapshot(live_after_conn)
    finally:
        live_after_conn.close()
    if live_after != live_before:
        raise AuditError("dry-run 期间 live DB 快照发生变化")
    return {
        "before": before,
        "staged_after": staged_after,
        "live_after_rollback": live_after,
        "foreign_key_check_before": before_fk,
        "foreign_key_check_after": after_fk,
        "plan": plan_audit,
        "execution": execution,
        "target_verification": target,
        "transaction": {
            "mode": "memory_copy",
            "begin": "BEGIN IMMEDIATE",
            "result": "rolled_back_after_successful_validation",
            "live_database_written": False,
        },
        "patches": patches,
    }


def _run_apply(
    db_path: Path,
    old_bundle: Mapping[str, Any],
    new_bundle: Mapping[str, Any],
    source_map: Any,
    changed_positions: Sequence[int],
) -> dict[str, Any]:
    conn = _open_read_write(db_path)
    committed = False
    try:
        _install_update_only_authorizer(conn)
        conn.execute("BEGIN IMMEDIATE")
        before = _database_snapshot(conn)
        before_fk = _foreign_key_violations(conn)
        if before_fk:
            raise AuditError(f"apply 基线已有 foreign_key_check 异常：{before_fk}")
        patches, position_to_id, plan_audit = _prepare_plan(
            conn, old_bundle, new_bundle, source_map, changed_positions
        )
        execution = _execute_patches(conn, patches)
        target = _verify_corrected_target(
            conn, new_bundle, position_to_id, source_map, old_bundle
        )
        staged_after = _database_snapshot(conn)
        _assert_identity_preserved(before, staged_after)
        after_fk = _foreign_key_violations(conn)
        if after_fk:
            raise AuditError(f"apply 后 foreign_key_check 异常：{after_fk}")
        conn.execute("COMMIT")
        committed = True
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    verification_conn = _open_read_only(db_path)
    try:
        persisted_after = _database_snapshot(verification_conn)
        persisted_target = _verify_corrected_target(
            verification_conn,
            new_bundle,
            position_to_id,
            source_map,
            old_bundle,
        )
        persisted_fk = _foreign_key_violations(verification_conn)
    finally:
        verification_conn.close()
    if not committed or persisted_after != staged_after:
        raise AuditError("commit 后只读复核与事务内目标快照不一致")
    if persisted_fk:
        raise AuditError(f"commit 后 foreign_key_check 异常：{persisted_fk}")
    return {
        "before": before,
        "staged_after": staged_after,
        "persisted_after": persisted_after,
        "foreign_key_check_before": before_fk,
        "foreign_key_check_after": persisted_fk,
        "plan": plan_audit,
        "execution": execution,
        "target_verification": persisted_target,
        "transaction": {
            "mode": "database_write",
            "begin": "BEGIN IMMEDIATE",
            "result": "committed_after_successful_validation",
            "live_database_written": True,
        },
        "patches": patches,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "逐位置比较 PCB 设备 old/new claims，并全字段唯一匹配后仅 UPDATE 既有数据点"
        )
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="目标 SQLite DB")
    parser.add_argument(
        "--old-claims", type=Path, default=DEFAULT_OLD_CLAIMS, help="旧 claims JSON"
    )
    parser.add_argument(
        "--new-claims", type=Path, default=DEFAULT_NEW_CLAIMS, help="修正后 claims JSON"
    )
    parser.add_argument(
        "--source-map", type=Path, default=DEFAULT_SOURCE_MAP, help="source locator -> id"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="审计 manifest 路径；dry-run 可选，--apply 必填",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="显式执行事务；不传时只在内存副本演练并回滚",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    db_path = _resolve(args.db)
    old_path = _resolve(args.old_claims)
    new_path = _resolve(args.new_claims)
    source_map_path = _resolve(args.source_map)
    manifest_path = _resolve(args.manifest) if args.manifest else None

    if args.apply and manifest_path is None:
        print("ERROR: --apply 必须同时指定 --manifest", file=sys.stderr)
        return 2
    for label, path in (
        ("db", db_path),
        ("old claims", old_path),
        ("new claims", new_path),
        ("source map", source_map_path),
    ):
        if not path.is_file():
            print(f"ERROR: {label} 不存在：{path}", file=sys.stderr)
            return 2

    audit: dict[str, Any] = {
        "schema_version": "pcb_equipment.provenance_repair_manifest.v2",
        "started_at": _utc_now(),
        "status": "preflight",
        "mode": "apply" if args.apply else "dry_run",
        "contract": {
            "industry_id": INDUSTRY_ID,
            "industry_name": EXPECTED_INDUSTRY_NAME,
            "database_dml": "UPDATE industry_data_point only",
            "sqlite_authorizer_enforced": True,
            "insert_count": 0,
            "delete_count": 0,
            "default_is_read_only": True,
            "apply_requires_explicit_flag": True,
            "source_metadata_written": False,
        },
        "inputs": {
            "database": str(db_path),
            "old_claims": str(old_path),
            "new_claims": str(new_path),
            "source_map": str(source_map_path),
        },
    }
    if args.apply and manifest_path is not None:
        # Establish a durable audit destination before any database write begins.
        _write_json_atomic(manifest_path, audit)

    try:
        old_sha = _sha256_file(old_path)
        new_sha = _sha256_file(new_path)
        source_map_sha = _sha256_file(source_map_path)
        old_bundle = _validate_claim_bundle(
            _load_json(old_path),
            label="old claims",
            expected_sha256=EXPECTED_OLD_SHA256,
            actual_sha256=old_sha,
        )
        new_bundle = _validate_claim_bundle(
            _load_json(new_path),
            label="corrected claims",
            expected_sha256=EXPECTED_NEW_SHA256,
            actual_sha256=new_sha,
        )
        source_map = _load_json(source_map_path)
        changed_positions, field_counts = _claim_delta(
            old_bundle["data_points"], new_bundle["data_points"]
        )
        old_fact_count = _fact_count(old_bundle["data_points"])
        new_fact_count = _fact_count(new_bundle["data_points"])
        if (old_fact_count, new_fact_count) != (
            EXPECTED_OLD_FACT_COUNT,
            EXPECTED_NEW_FACT_COUNT,
        ):
            raise AuditError(
                f"事实身份计数不匹配：old={old_fact_count}, new={new_fact_count}"
            )

        audit["inputs"].update(
            {
                "old_claims_sha256": old_sha,
                "new_claims_sha256": new_sha,
                "source_map_sha256": source_map_sha,
                "old_data_point_count": len(old_bundle["data_points"]),
                "new_data_point_count": len(new_bundle["data_points"]),
            }
        )
        audit["claims_delta"] = {
            "position_alignment": True,
            "changed_position_count": len(changed_positions),
            "changed_position_sha256": _json_hash(changed_positions),
            "field_diff_counts": field_counts,
            "old_fact_count_with_scope_key": old_fact_count,
            "new_fact_count_with_scope_key": new_fact_count,
            "scope_key_persisted_in_legacy_table": False,
        }
        audit["excluded_source_metadata_delta"] = _source_metadata_delta(
            old_bundle["sources"], new_bundle["sources"]
        )

        result = (
            _run_apply(
                db_path,
                old_bundle,
                new_bundle,
                source_map,
                changed_positions,
            )
            if args.apply
            else _run_dry(
                db_path,
                old_bundle,
                new_bundle,
                source_map,
                changed_positions,
            )
        )
        audit.update(result)
        audit["status"] = "committed" if args.apply else "dry_run_validated"
        audit["completed_at"] = _utc_now()
        audit["checks"] = {
            "old_claims_sha256_pinned": True,
            "new_claims_sha256_pinned": True,
            "old_claims_full_field_unique_match": True,
            "corrected_claims_full_target_match": True,
            "target_row_count_preserved": True,
            "target_id_set_preserved": True,
            "global_row_count_preserved": True,
            "global_id_set_preserved": True,
            "foreign_key_check_empty": True,
            "insert_count": 0,
            "delete_count": 0,
            "source_metadata_untouched": True,
            "sqlite_update_only_authorizer_enforced": True,
        }
        if manifest_path is not None:
            _write_json_atomic(manifest_path, audit)
        summary = {
            "status": audit["status"],
            "mode": audit["mode"],
            "database": str(db_path),
            "changed_positions": audit["claims_delta"]["changed_position_count"],
            "updated_rows": audit["execution"]["updated_row_count"],
            "target_rows": audit["target_verification"][
                "corrected_claim_unique_match_count"
            ],
            "foreign_key_violations": len(audit["foreign_key_check_after"]),
            "transaction": audit["transaction"]["result"],
            "manifest": str(manifest_path) if manifest_path else None,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        audit["status"] = "failed"
        audit["completed_at"] = _utc_now()
        audit["error"] = {"type": type(exc).__name__, "message": str(exc)}
        if manifest_path is not None:
            try:
                _write_json_atomic(manifest_path, audit)
            except Exception as manifest_exc:  # preserve the primary failure
                print(
                    f"ERROR: manifest 写入也失败：{manifest_exc}", file=sys.stderr
                )
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
