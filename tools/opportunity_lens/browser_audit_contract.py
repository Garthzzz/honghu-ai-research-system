from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .artifact_freeze import (
    ArtifactFreeze,
    ArtifactFreezeError,
    build_artifact_freeze,
    canonical_json,
    normalize_sha256,
    sha256_bytes,
    sha256_text,
)
from .constants import (
    EARLY_SIGNAL_RULE_VERSION,
    EVIDENCE_POLICY_VERSION,
    INTAKE_CONTRACT_VERSION,
    RESEARCH_WORKFLOW_CONTRACT_VERSION,
    ROOT,
)


BROWSER_AUDIT_SCHEMA_VERSION = "opportunity_lens.browser_visual_audit.v2"
BROWSER_AUDIT_SCRIPT_VERSION = "opportunity_lens.playwright_table_audit.v3"
BROWSER_AUDIT_MANIFEST_TYPE = "browser_visual_audit"
EVIDENCE_DRAWER_RULE_VERSION = "opportunity_lens.human_evidence_drawer.v1"
REQUIRED_VIEWPORTS = ("desktop", "mobile")
GEOMETRY_KEYS = (
    "left",
    "right",
    "top",
    "bottom",
    "width",
    "height",
    "container_left",
    "container_right",
)
EVIDENCE_DATE_FIELD_LABELS = frozenset(
    {"发布日期", "事件/版本日期", "访问日期", "期间/时点"}
)
_RAW_ISO_DATE_RE = re.compile(
    r"\b(?:19|20)\d{2}-\d{2}(?:-\d{2})?(?:/(?:19|20)\d{2}-\d{2}(?:-\d{2})?)?\b"
)
_RAW_MACHINE_DATE_ENUM_RE = re.compile(
    r"\b(?:current_at_fetch|current_at_access|current_page|(?:19|20)\d{2}-(?:spring|campus-cycle)|campus-cycle)\b",
    re.IGNORECASE,
)


@dataclass
class BrowserAuditValidation:
    valid: bool
    issues: list[str] = field(default_factory=list)
    manifest_hash: str | None = None
    manifest: dict[str, Any] | None = None
    freeze: ArtifactFreeze | None = None


def browser_audit_manifest_hash(manifest: dict[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_hash", None)
    return sha256_text(canonical_json(payload))


def expected_public_routes(conn: sqlite3.Connection, run_id: int) -> list[str]:
    """当前 run 在 viewer 中必须完成浏览器审计的公开路由。"""
    routes = [
        "/opportunity-lens",
        "/opportunity-lens/request-generator",
        f"/opportunity-lens/run/{run_id}",
        f"/opportunity-lens/run/{run_id}/entities",
    ]
    entity_ids = [
        int(row[0])
        for row in conn.execute(
            "SELECT DISTINCT entity_id FROM opportunity_entity_maturation WHERE run_id=? ORDER BY entity_id",
            (run_id,),
        ).fetchall()
    ]
    target_ids = [
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM opportunity_entity_investment_target WHERE run_id=? ORDER BY id",
            (run_id,),
        ).fetchall()
    ]
    factor_score_ids = [
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM opportunity_factor_score WHERE run_id=? ORDER BY id",
            (run_id,),
        ).fetchall()
    ]
    metric_slot_ids = [
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM opportunity_metric_slot WHERE run_id=? ORDER BY id",
            (run_id,),
        ).fetchall()
    ]
    routes.extend(f"/opportunity-lens/entity/{entity_id}" for entity_id in entity_ids)
    routes.extend(f"/opportunity-lens/target/{target_id}" for target_id in target_ids)
    routes.extend(f"/opportunity-lens/factor/{factor_score_id}" for factor_score_id in factor_score_ids)
    routes.extend(f"/opportunity-lens/metric-slot/{metric_slot_id}" for metric_slot_id in metric_slot_ids)
    routes.extend(
        (
            f"/opportunity-lens/run/{run_id}/audit",
            f"/opportunity-lens/run/{run_id}/supplement",
            f"/opportunity-lens/run/{run_id}/export",
        )
    )
    return routes


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def detect_raw_machine_date_fragments(date_fields: Any, drawer_text: Any) -> list[str]:
    """只把展示字段中的 ISO 日期视为机器格式；原文摘录可忠实保留 ISO 日期。"""
    matches: list[str] = []
    if isinstance(date_fields, list):
        for field in date_fields:
            if not isinstance(field, dict):
                continue
            label = str(field.get("label") or "").strip()
            if label not in EVIDENCE_DATE_FIELD_LABELS:
                continue
            matches.extend(_RAW_ISO_DATE_RE.findall(str(field.get("value") or "")))
    # 枚举值无论出现在哪里都是实现字段泄露，不属于需要忠实保留的原文日期。
    matches.extend(_RAW_MACHINE_DATE_ENUM_RE.findall(str(drawer_text or "")))
    return list(dict.fromkeys(matches))


def _validate_geometry(value: Any, path: str, issues: list[str], *, require_visible: bool) -> None:
    if not isinstance(value, dict):
        issues.append(f"{path} 缺少几何对象")
        return
    for key in GEOMETRY_KEYS:
        if not _finite_number(value.get(key)):
            issues.append(f"{path}.{key} 必须是有限数值")
    visibility_ok = value.get("fully_visible") is True and value.get("clipped") is False
    bounds_ok = True
    if all(_finite_number(value.get(key)) for key in ("left", "right", "container_left", "container_right")):
        if float(value["left"]) < float(value["container_left"]) - 1.5:
            bounds_ok = False
        if float(value["right"]) > float(value["container_right"]) + 1.5:
            bounds_ok = False
    if require_visible and (not visibility_ok or not bounds_ok):
        issues.append(f"{path} 未完整位于局部容器")


def _validate_edge(value: Any, path: str, issues: list[str], *, right: bool) -> None:
    if not isinstance(value, dict):
        issues.append(f"{path} 缺失")
        return
    scroll_left = value.get("scroll_left")
    max_scroll_left = value.get("max_scroll_left")
    if not _finite_number(scroll_left) or not _finite_number(max_scroll_left):
        issues.append(f"{path} 缺少有效 scroll_left/max_scroll_left")
    elif right:
        if abs(float(scroll_left) - float(max_scroll_left)) > 3 or value.get("reached") is not True:
            issues.append(f"{path} 未确认滚动到最右端")
    elif abs(float(scroll_left)) > 1.5:
        issues.append(f"{path} 没有从最左端开始")
    container = value.get("container_geometry")
    if not isinstance(container, dict):
        issues.append(f"{path}.container_geometry 缺失")
    else:
        for key in ("left", "right", "top", "bottom", "width", "height"):
            if not _finite_number(container.get(key)):
                issues.append(f"{path}.container_geometry.{key} 必须是有限数值")


def _resolve_screenshot(project_root: Path, reference: Any) -> Path | None:
    raw = str(reference or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute() or candidate.suffix.lower() != ".png":
        return None
    resolved = (project_root / candidate).resolve()
    try:
        resolved.relative_to(project_root.resolve())
    except ValueError:
        return None
    return resolved


def _validate_screenshot(
    *,
    project_root: Path,
    reference: Any,
    digest_value: Any,
    path: str,
    issues: list[str],
    verify_screenshots: bool,
) -> None:
    try:
        digest = normalize_sha256(digest_value, field=f"{path}.screenshot_hash")
    except ArtifactFreezeError as exc:
        issues.append(str(exc))
        digest = None
    screenshot_path = _resolve_screenshot(project_root, reference)
    if screenshot_path is None:
        issues.append(f"{path}.screenshot_ref 必须是项目内相对 PNG 路径")
        return
    if not verify_screenshots:
        return
    if not screenshot_path.is_file():
        issues.append(f"{path} 截图不存在: {screenshot_path}")
        return
    screenshot_bytes = screenshot_path.read_bytes()
    if not screenshot_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        issues.append(f"{path} 截图不是有效 PNG 文件")
    if digest and sha256_bytes(screenshot_bytes) != digest:
        issues.append(f"{path} 截图 hash 校验失败")


def _validate_table(
    table: Any,
    path: str,
    issues: list[str],
    *,
    report_embedded_issues: bool,
    project_root: Path,
    verify_screenshots: bool,
) -> None:
    if not isinstance(table, dict):
        issues.append(f"{path} 必须是对象")
        return
    for key in ("index", "row_count", "column_count"):
        if not isinstance(table.get(key), int) or isinstance(table.get(key), bool) or table[key] < 0:
            issues.append(f"{path}.{key} 必须是非负整数")
    if table.get("keyboard_reachable") is not True:
        issues.append(f"{path}.keyboard_reachable 必须为 true")
    if report_embedded_issues and table.get("issues") != []:
        issue_count = len(table.get("issues")) if isinstance(table.get("issues"), list) else "非法"
        issues.append(f"{path}.issues 非空（{issue_count}）")
    _validate_edge(table.get("left_edge"), f"{path}.left_edge", issues, right=False)
    _validate_edge(table.get("right_edge"), f"{path}.right_edge", issues, right=True)
    _validate_screenshot(
        project_root=project_root,
        reference=table.get("right_edge_screenshot_ref"),
        digest_value=table.get("right_edge_screenshot_hash"),
        path=f"{path}.right_edge_screenshot",
        issues=issues,
        verify_screenshots=verify_screenshots,
    )
    rightmost = table.get("rightmost_column")
    if not isinstance(rightmost, dict):
        issues.append(f"{path}.rightmost_column 缺失")
        return
    if not str(rightmost.get("header_text") or "").strip():
        issues.append(f"{path}.rightmost_column.header_text 为空")
    _validate_geometry(
        rightmost.get("header_geometry"),
        f"{path}.rightmost_column.header_geometry",
        issues,
        require_visible=True,
    )
    cells = rightmost.get("cell_geometries")
    if not isinstance(cells, list):
        issues.append(f"{path}.rightmost_column.cell_geometries 必须是数组")
        return
    row_count = table.get("row_count")
    if isinstance(row_count, int) and len(cells) != row_count:
        issues.append(
            f"{path}.rightmost_column.cell_geometries 数量 {len(cells)} 与 row_count {row_count} 不一致"
        )
    for index, geometry in enumerate(cells):
        _validate_geometry(
            geometry,
            f"{path}.rightmost_column.cell_geometries[{index}]",
            issues,
            require_visible=True,
        )
def _validate_evidence_drawer(
    value: Any,
    path: str,
    issues: list[str],
    *,
    project_root: Path,
    verify_screenshots: bool,
) -> None:
    if not isinstance(value, dict):
        issues.append(f"{path} 缺少证据抽屉审计")
        return
    if value.get("content_rule_version") != EVIDENCE_DRAWER_RULE_VERSION:
        issues.append(f"{path}.content_rule_version 缺失或不匹配")
    counts: dict[str, int] = {}
    for key in ("button_count", "unique_reference_count", "tested_reference_count"):
        raw = value.get(key)
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
            issues.append(f"{path}.{key} 必须是非负整数")
        else:
            counts[key] = raw
    if counts.get("button_count", 0) < counts.get("unique_reference_count", 0):
        issues.append(f"{path}.button_count 不能少于 unique_reference_count")
    if counts.get("button_count", 0) > 0 and counts.get("unique_reference_count", 0) == 0:
        issues.append(f"{path} 存在证据按钮但没有识别到唯一证据引用")
    if counts.get("tested_reference_count") != counts.get("unique_reference_count"):
        issues.append(f"{path} 没有测试每一个唯一证据引用")
    if value.get("issues") != []:
        issue_count = len(value.get("issues")) if isinstance(value.get("issues"), list) else "非法"
        issues.append(f"{path}.issues 非空（{issue_count}）")
    items = value.get("items")
    if not isinstance(items, list):
        issues.append(f"{path}.items 必须是数组")
        items = []
    if counts.get("tested_reference_count") != len(items):
        issues.append(f"{path}.items 数量与 tested_reference_count 不一致")
    fingerprints: list[str] = []
    activation_keys: set[str] = set()
    for index, item in enumerate(items):
        item_path = f"{path}.items[{index}]"
        if not isinstance(item, dict):
            issues.append(f"{item_path} 必须是对象")
            continue
        leaked_fields = [
            key
            for key in ("reference", "ref", "source_ref", "evidence_ref", "evidence_ref_uri", "drawer_text")
            if key in item
        ]
        if leaked_fields:
            issues.append(f"{item_path} 不得保存原始引用或抽屉全文字段: {', '.join(leaked_fields)}")
        try:
            fingerprints.append(
                normalize_sha256(item.get("reference_hash"), field=f"{item_path}.reference_hash")
            )
        except ArtifactFreezeError as exc:
            issues.append(str(exc))
        key = item.get("activation_key")
        if key not in {"Enter", "Space"}:
            issues.append(f"{item_path}.activation_key 必须为 Enter 或 Space")
        else:
            activation_keys.add(key)
        if item.get("button_focused") is not True:
            issues.append(f"{item_path}.button_focused 必须为 true")
        if item.get("api_status") != 200:
            issues.append(f"{item_path}.api_status 必须为 200")
        if item.get("drawer_visible") is not True:
            issues.append(f"{item_path}.drawer_visible 必须为 true")
        overflow = item.get("drawer_horizontal_overflow_px")
        if not _finite_number(overflow) or float(overflow) > 3:
            issues.append(f"{item_path}.drawer_horizontal_overflow_px 必须不超过 3")
        if not str(item.get("headline") or "").strip():
            issues.append(f"{item_path}.headline 为空")
        for list_key in (
            "forbidden_fragments",
            "raw_machine_date_fragments",
            "raw_source_level_code_fragments",
        ):
            fragments = item.get(list_key)
            if not isinstance(fragments, list):
                issues.append(f"{item_path}.{list_key} 必须是数组")
            elif fragments:
                issues.append(f"{item_path}.{list_key} 非空")
        if item.get("raw_json_visible") is not False:
            issues.append(f"{item_path}.raw_json_visible 必须为 false")
        if item.get("human_content_checked") is not True:
            issues.append(f"{item_path}.human_content_checked 必须为 true")
        try:
            normalize_sha256(item.get("drawer_text_hash"), field=f"{item_path}.drawer_text_hash")
        except ArtifactFreezeError as exc:
            issues.append(str(exc))
        if item.get("issues") != []:
            issues.append(f"{item_path}.issues 非空")
    if len(fingerprints) != len(set(fingerprints)):
        issues.append(f"{path}.items 存在重复 reference_hash")
    if len(items) >= 2 and activation_keys != {"Enter", "Space"}:
        issues.append(f"{path} 至少两个证据引用时必须同时覆盖 Enter 与 Space")
    if counts.get("unique_reference_count", 0) > 0:
        _validate_screenshot(
            project_root=project_root,
            reference=value.get("drawer_screenshot_ref"),
            digest_value=value.get("drawer_screenshot_hash"),
            path=f"{path}.drawer",
            issues=issues,
            verify_screenshots=verify_screenshots,
        )


def validate_browser_visual_audit(
    manifest: Any,
    *,
    expected_freeze: ArtifactFreeze,
    project_root: str | Path = ROOT,
    verify_screenshots: bool = True,
    expected_routes: list[str] | None = None,
) -> BrowserAuditValidation:
    issues: list[str] = []
    if not isinstance(manifest, dict):
        return BrowserAuditValidation(False, ["browser audit manifest 顶层必须是对象"])
    if manifest.get("schema_version") != BROWSER_AUDIT_SCHEMA_VERSION:
        issues.append("browser audit schema_version 不匹配")
    if manifest.get("script_version") != BROWSER_AUDIT_SCRIPT_VERSION:
        issues.append("browser audit script_version 缺失或不匹配")
    if manifest.get("verdict") != "GREEN":
        issues.append("browser audit verdict 必须为 GREEN")
    if manifest.get("issues") != []:
        issue_count = len(manifest.get("issues")) if isinstance(manifest.get("issues"), list) else "非法"
        issues.append(f"browser audit 报告仍有 {issue_count} 个未解决问题")
    if manifest.get("run_id") != expected_freeze.run_id:
        issues.append("browser audit run_id 与当前 run 不一致")
    expected_hashes = {
        "pack_hash": expected_freeze.pack_hash,
        "ui_bundle_hash": expected_freeze.ui_bundle_hash,
        "browser_input_hash": expected_freeze.browser_input_hash,
    }
    for field_name, expected in expected_hashes.items():
        try:
            actual = normalize_sha256(manifest.get(field_name), field=field_name)
        except ArtifactFreezeError as exc:
            issues.append(str(exc))
            continue
        if actual != expected:
            issues.append(f"browser audit {field_name} 已过期: expected={expected}, actual={actual}")
    if manifest.get("ui_file_count") != expected_freeze.ui_file_count:
        issues.append("browser audit ui_file_count 与当前 viewer bundle 不一致")
    routes = manifest.get("routes")
    if not isinstance(routes, list) or not routes or any(not isinstance(route, str) or not route.startswith("/") for route in routes):
        issues.append("browser audit routes 必须是非空站内路由数组")
        routes = []
    elif len(set(routes)) != len(routes):
        issues.append("browser audit routes 不能重复")
    if expected_routes is not None:
        missing_routes = [route for route in expected_routes if route not in routes]
        if missing_routes:
            issues.append("browser audit 缺少当前 run 公开路由: " + ", ".join(missing_routes))
        unexpected_routes = [route for route in routes if route not in expected_routes]
        if unexpected_routes:
            issues.append("browser audit 包含非公开或非当前 run 路由: " + ", ".join(unexpected_routes))
    viewports = manifest.get("viewports")
    if not isinstance(viewports, dict):
        issues.append("browser audit viewports 必须是对象")
        viewports = {}
    root = Path(project_root).resolve()
    for viewport_name in REQUIRED_VIEWPORTS:
        viewport = viewports.get(viewport_name)
        viewport_path = f"viewports.{viewport_name}"
        if not isinstance(viewport, dict):
            issues.append(f"{viewport_path} 缺失")
            continue
        dimensions = viewport.get("viewport")
        if not isinstance(dimensions, dict) or any(
            not isinstance(dimensions.get(key), int) or dimensions[key] <= 0 for key in ("width", "height")
        ):
            issues.append(f"{viewport_path}.viewport 缺少有效 width/height")
        if viewport.get("issues") != []:
            issue_count = len(viewport.get("issues")) if isinstance(viewport.get("issues"), list) else "非法"
            issues.append(f"{viewport_path}.issues 非空（{issue_count}）")
        route_results = viewport.get("routes")
        if not isinstance(route_results, list):
            issues.append(f"{viewport_path}.routes 必须是数组")
            continue
        if viewport.get("route_count") != len(route_results):
            issues.append(f"{viewport_path}.route_count 与 routes 数量不一致")
        result_routes = [item.get("route") for item in route_results if isinstance(item, dict)]
        if result_routes != routes:
            issues.append(f"{viewport_path}.routes 与顶层 routes 不一致")
        for route_index, route_result in enumerate(route_results):
            route_path = f"{viewport_path}.routes[{route_index}]"
            if not isinstance(route_result, dict):
                issues.append(f"{route_path} 必须是对象")
                continue
            if route_result.get("status") != 200:
                issues.append(f"{route_path}.status 必须为 200")
            route_has_embedded_issues = route_result.get("issues") != []
            if route_has_embedded_issues:
                issue_count = len(route_result.get("issues")) if isinstance(route_result.get("issues"), list) else "非法"
                issues.append(f"{route_path}.issues 非空（{issue_count}）")
            overflow = route_result.get("global_overflow_px")
            if not _finite_number(overflow) or float(overflow) > 3:
                issues.append(f"{route_path}.global_overflow_px 必须不超过 3")
            tables = route_result.get("tables")
            if not isinstance(tables, list):
                issues.append(f"{route_path}.tables 必须是数组")
                tables = []
            if route_result.get("table_count") != len(tables):
                issues.append(f"{route_path}.table_count 与 tables 数量不一致")
            table_indexes: list[int] = []
            for table_index, table in enumerate(tables):
                _validate_table(
                    table,
                    f"{route_path}.tables[{table_index}]",
                    issues,
                    report_embedded_issues=not route_has_embedded_issues,
                    project_root=root,
                    verify_screenshots=verify_screenshots,
                )
                if isinstance(table, dict) and isinstance(table.get("index"), int):
                    table_indexes.append(table["index"])
            if len(table_indexes) != len(set(table_indexes)):
                issues.append(f"{route_path}.tables index 重复")
            _validate_evidence_drawer(
                route_result.get("evidence_drawer"),
                f"{route_path}.evidence_drawer",
                issues,
                project_root=root,
                verify_screenshots=verify_screenshots,
            )
            if route_result.get("screenshot_full_page") is not True:
                issues.append(f"{route_path}.screenshot_full_page 必须为 true")
            _validate_screenshot(
                project_root=root,
                reference=route_result.get("screenshot_ref"),
                digest_value=route_result.get("screenshot_hash"),
                path=f"{route_path}.full_page_screenshot",
                issues=issues,
                verify_screenshots=verify_screenshots,
            )
    digest = browser_audit_manifest_hash(manifest)
    embedded_hash = manifest.get("manifest_hash")
    if embedded_hash is not None:
        try:
            normalized = normalize_sha256(embedded_hash, field="manifest_hash")
            if normalized != digest:
                issues.append("browser audit manifest_hash 校验失败")
        except ArtifactFreezeError as exc:
            issues.append(str(exc))
    return BrowserAuditValidation(
        valid=not issues,
        issues=issues,
        manifest_hash=digest,
        manifest=dict(manifest),
        freeze=expected_freeze,
    )


def record_browser_visual_audit(
    conn: sqlite3.Connection,
    run_id: int,
    manifest: dict[str, Any],
    *,
    project_root: str | Path = ROOT,
    verify_screenshots: bool = True,
) -> str:
    freeze = build_artifact_freeze(conn, run_id, project_root=project_root)
    validation = validate_browser_visual_audit(
        manifest,
        expected_freeze=freeze,
        project_root=project_root,
        verify_screenshots=verify_screenshots,
        expected_routes=expected_public_routes(conn, run_id),
    )
    if not validation.valid:
        raise ValueError("browser visual audit 验证失败: " + "；".join(validation.issues))
    payload = dict(manifest)
    payload["manifest_hash"] = validation.manifest_hash
    conn.execute(
        """
        INSERT INTO opportunity_run_manifest(
          run_id,manifest_type,manifest_json,manifest_hash,
          intake_contract_version,evidence_policy_version,early_signal_rule_version,
          workflow_contract_version,pack_schema_version
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            BROWSER_AUDIT_MANIFEST_TYPE,
            canonical_json(payload),
            validation.manifest_hash,
            INTAKE_CONTRACT_VERSION,
            EVIDENCE_POLICY_VERSION,
            EARLY_SIGNAL_RULE_VERSION,
            RESEARCH_WORKFLOW_CONTRACT_VERSION,
            freeze.pack_schema_version,
        ),
    )
    return str(validation.manifest_hash)


def validate_latest_browser_visual_audit(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    project_root: str | Path = ROOT,
    verify_screenshots: bool = True,
) -> BrowserAuditValidation:
    try:
        freeze = build_artifact_freeze(conn, run_id, project_root=project_root)
    except ArtifactFreezeError as exc:
        return BrowserAuditValidation(False, [str(exc)])
    row = conn.execute(
        """
        SELECT id,manifest_json,manifest_hash
        FROM opportunity_run_manifest
        WHERE run_id=? AND manifest_type=?
        ORDER BY id DESC LIMIT 1
        """,
        (run_id, BROWSER_AUDIT_MANIFEST_TYPE),
    ).fetchone()
    if row is None:
        return BrowserAuditValidation(False, ["缺少 browser_visual_audit manifest"], freeze=freeze)
    try:
        manifest = json.loads(row["manifest_json"])
    except (json.JSONDecodeError, TypeError) as exc:
        return BrowserAuditValidation(False, [f"browser_visual_audit manifest_json 非法: {exc}"], freeze=freeze)
    validation = validate_browser_visual_audit(
        manifest,
        expected_freeze=freeze,
        project_root=project_root,
        verify_screenshots=verify_screenshots,
        expected_routes=expected_public_routes(conn, run_id),
    )
    if row["manifest_hash"] != validation.manifest_hash:
        validation.valid = False
        validation.issues.append("browser_visual_audit DB manifest_hash 校验失败")
    return validation


def main() -> None:
    from .db import connect

    parser = argparse.ArgumentParser(description="校验或写入 Opportunity Lens browser visual audit manifest")
    parser.add_argument("run_id", type=int)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "opportunity_lens.db")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    conn = connect(args.db, readonly=not args.record)
    try:
        freeze = build_artifact_freeze(conn, args.run_id, project_root=args.project_root)
        validation = validate_browser_visual_audit(
            manifest,
            expected_freeze=freeze,
            project_root=args.project_root,
            verify_screenshots=True,
            expected_routes=expected_public_routes(conn, args.run_id),
        )
        if args.record and validation.valid:
            record_browser_visual_audit(
                conn,
                args.run_id,
                manifest,
                project_root=args.project_root,
                verify_screenshots=True,
            )
            conn.commit()
    except Exception:
        if args.record:
            conn.rollback()
        raise
    finally:
        conn.close()
    print(json.dumps({
        "valid": validation.valid,
        "manifest_hash": validation.manifest_hash,
        "browser_input_hash": freeze.browser_input_hash,
        "issues": validation.issues,
        "recorded": bool(args.record and validation.valid),
    }, ensure_ascii=False, indent=2))
    if not validation.valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
