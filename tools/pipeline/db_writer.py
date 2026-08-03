#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A/B 轨结构化数据点的唯一写入接口。

研究抽取、迁移封装和专题构建器不得直接 INSERT `industry_data_point`。
本模块统一保证：

1. 每个新 data_point 插入后自动触发 consensus_compute.recompute_after_insert
2. source.key_arguments 写入时做 JSON 校验
3. 自动填充 created_at / 默认值
4. 新数据字段、有限数值、外键和 extraction_method 契约校验
5. 批量失败时通过 savepoint 原子回滚

接口:
- write_data_point(conn, industry_id, metric, period, value_num/value_text, unit,
                   source_id, source_excerpt, ...)
- write_key_arguments(conn, source_id, args_list)   # list of {claim, sentiment, dimension}
- bulk_write_data_points(conn, items)              # 批量
活动契约见 `config/research_workflow.yaml`。
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# import sibling: consensus_compute
sys.path.insert(0, str(Path(__file__).resolve().parent))
import consensus_compute  # noqa: E402

ROOT    = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "research.db"


def get_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


VALID_EXTRACTION_METHODS = ("pdf_direct", "web_fetch", "template_estimate", "inferred", "unknown")
VALID_NEW_EXTRACTION_METHODS = ("pdf_direct", "web_fetch", "inferred")


class DataPointWriteError(ValueError):
    """Raised when a new A/B data point violates the canonical write contract."""


def _require_existing_reference(
    conn: sqlite3.Connection,
    table: str,
    object_id: int | None,
    *,
    required: bool = True,
) -> None:
    if object_id is None:
        if required:
            raise DataPointWriteError(f"write_data_point: {table}_id 必填")
        return
    if conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (object_id,)).fetchone() is None:
        raise DataPointWriteError(f"write_data_point: {table}_id={object_id} 不存在")


def write_data_point(
    conn: sqlite3.Connection,
    *,
    industry_id: int,
    metric: str,
    period: str,
    unit: str,
    source_id: int,
    source_excerpt: str,
    extraction_method: str,
    value_num: Optional[float] = None,
    value_text: Optional[str] = None,
    is_forecast: int = 0,
    as_of_date: Optional[str] = None,
    sentiment: str = "不适用",
    note: Optional[str] = None,
    company_id: Optional[int] = None,
    auto_consensus: bool = True,
    allow_legacy_method: bool = False,
    consensus_failure_policy: str = "raise",
) -> int:
    """插入一条 data_point + 自动重算 consensus(默认开启)。
    返回新 data_point.id。

    必填:industry_id / metric / period / unit / source_id / source_excerpt /
          extraction_method / (value_num OR value_text)

    新数据 extraction_method 枚举:
    - pdf_direct: 直接读 PDF 抽出的数据
    - web_fetch: web 搜索 / fetch 抽出
    - inferred: 从已有数据计算得出(YoY 等)

    `template_estimate` 和 `unknown` 只给显式 legacy migration 使用；常规调用会拒绝。
    """
    metric = str(metric or "").strip()
    period = str(period or "").strip()
    unit = str(unit or "").strip()
    source_excerpt = str(source_excerpt or "").strip()
    extraction_method = str(extraction_method or "").strip()
    if not metric:
        raise DataPointWriteError("write_data_point: metric 必填")
    if not period and not str(as_of_date or "").strip():
        raise DataPointWriteError("write_data_point: period 或 as_of_date 至少一个必填")
    if value_num is None and (not value_text or not value_text.strip()):
        raise DataPointWriteError("write_data_point: value_num 与 value_text 至少一个必填")
    if isinstance(value_num, bool) or (value_num is not None and not math.isfinite(float(value_num))):
        raise DataPointWriteError("write_data_point: value_num 必须是有限数值")
    if not source_excerpt:
        raise DataPointWriteError("write_data_point: source_excerpt 必填")
    if not unit:
        raise DataPointWriteError("write_data_point: unit 必填")
    if sentiment not in ("看涨", "看跌", "中性", "不适用"):
        raise DataPointWriteError(f"write_data_point: sentiment 非法值 {sentiment!r}")
    if extraction_method not in VALID_EXTRACTION_METHODS:
        raise DataPointWriteError(
            f"write_data_point: extraction_method 必须是 {VALID_EXTRACTION_METHODS} 之一,"
            f"得到 {extraction_method!r}"
        )
    if extraction_method not in VALID_NEW_EXTRACTION_METHODS and not allow_legacy_method:
        raise DataPointWriteError(
            f"write_data_point: 新数据禁止 extraction_method={extraction_method!r}; "
            "unknown/template_estimate 只能在显式 legacy migration 中使用"
        )
    if extraction_method == "inferred" and not str(note or "").strip():
        raise DataPointWriteError("write_data_point: inferred 数据点必须在 note 写明公式或计算口径")
    if consensus_failure_policy not in {"raise", "warn"}:
        raise DataPointWriteError("consensus_failure_policy 只能是 raise 或 warn")
    _require_existing_reference(conn, "industry", industry_id)
    _require_existing_reference(conn, "source", source_id)
    _require_existing_reference(conn, "company", company_id, required=False)
    # as_of_date fallback to period
    if not as_of_date:
        as_of_date = period

    cur = conn.execute("""
        INSERT INTO industry_data_point
            (industry_id, metric, period, value_num, value_text, unit, is_forecast,
             as_of_date, sentiment, source_id, source_excerpt, note, company_id,
             extraction_method)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (industry_id, metric, period, value_num, value_text, unit,
          int(bool(is_forecast)), as_of_date, sentiment, source_id, source_excerpt, note, company_id,
          extraction_method))
    new_id = cur.lastrowid

    if auto_consensus and value_num is not None:
        try:
            consensus_compute.recompute_after_insert(new_id, conn=conn)
        except Exception as exc:
            if consensus_failure_policy == "warn":
                print(f"[WARN] consensus 重算失败 dp_id={new_id}: {exc}", file=sys.stderr)
            else:
                raise RuntimeError(f"consensus 重算失败，数据点未获完整治理: dp_id={new_id}") from exc

    return new_id


def bulk_write_data_points(
    conn: sqlite3.Connection,
    items: Iterable[Dict[str, Any]],
    auto_consensus: bool = True,
    consensus_failure_policy: str = "raise",
) -> List[int]:
    """批量插入 data_point。每个 item 是 dict,字段同 write_data_point 参数。
    全部插入完才统一跑一次 consensus 全量重算(更高效)。
    """
    if consensus_failure_policy not in {"raise", "warn"}:
        raise DataPointWriteError("consensus_failure_policy 只能是 raise 或 warn")
    ids: List[int] = []
    savepoint = "bulk_write_data_points"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        for item in items:
            item2 = dict(item)
            item2["auto_consensus"] = False
            ids.append(write_data_point(conn, **item2))
        if auto_consensus and ids:
            seen = set()
            for dp_id in ids:
                row = conn.execute(
                    "SELECT industry_id, metric FROM industry_data_point WHERE id=?",
                    (dp_id,),
                ).fetchone()
                if row:
                    seen.add((row["industry_id"], row["metric"]))
            for ind_id, metric in seen:
                try:
                    consensus_compute.recompute_metric(ind_id, metric, conn=conn)
                except Exception as exc:
                    if consensus_failure_policy == "warn":
                        print(f"[WARN] consensus 重算失败 ind={ind_id} metric={metric}: {exc}", file=sys.stderr)
                    else:
                        raise RuntimeError(
                            f"consensus 重算失败，批量数据点已回滚: industry={ind_id}, metric={metric}"
                        ) from exc
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return ids
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise


def write_key_arguments(
    conn: sqlite3.Connection,
    source_id: int,
    args_list: List[Dict[str, Any]],
    merge: bool = True,
) -> int:
    """写 source.key_arguments(JSON 数组,每项 {claim, sentiment, dimension})。
    merge=True 则与已有合并(按 claim 文本去重);False 则覆盖。
    返回最终条目数。
    """
    if not isinstance(args_list, list):
        raise TypeError("args_list 必须是 list")
    # 校验每项有 claim 字段
    cleaned: List[Dict[str, Any]] = []
    for a in args_list:
        if not isinstance(a, dict):
            raise TypeError(f"key_arguments item 必须是 dict,得到 {type(a)}")
        if "claim" not in a or not str(a["claim"]).strip():
            raise ValueError("key_arguments item 必须有非空 claim 字段")
        cleaned.append({
            "claim": str(a["claim"]).strip(),
            "sentiment": a.get("sentiment", "中性"),
            "dimension": a.get("dimension", ""),
        })

    if merge:
        cur = conn.execute("SELECT key_arguments FROM source WHERE id=?", (source_id,))
        row = cur.fetchone()
        existing: List[Dict[str, Any]] = []
        if row and row["key_arguments"]:
            try:
                existing = json.loads(row["key_arguments"])
                if not isinstance(existing, list):
                    existing = []
            except json.JSONDecodeError:
                existing = []
        seen_claims = {e.get("claim") for e in existing if isinstance(e, dict)}
        for a in cleaned:
            if a["claim"] not in seen_claims:
                existing.append(a)
                seen_claims.add(a["claim"])
        final = existing
    else:
        final = cleaned

    conn.execute(
        "UPDATE source SET key_arguments=? WHERE id=?",
        (json.dumps(final, ensure_ascii=False), source_id)
    )
    return len(final)


def update_source_value_layer(conn: sqlite3.Connection, source_id: int, value_layer: str) -> None:
    """更新 source.value_layer。"""
    if value_layer not in ("深度框架", "双层", "最新数据", "主题专项", "公司专项", "信息流"):
        raise ValueError(f"非法 value_layer: {value_layer!r}")
    conn.execute("UPDATE source SET value_layer=? WHERE id=?", (value_layer, source_id))


# ── CLI 自检 ────────────────────────────────────────
if __name__ == "__main__":
    # 简单的接口可用性验证,不实际写库
    print("db_writer module loaded OK")
    print("functions:", [f for f in dir() if f.startswith("write_") or f.startswith("bulk_") or f.startswith("update_")])
