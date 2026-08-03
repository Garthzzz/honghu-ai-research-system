from __future__ import annotations

import sqlite3
from pathlib import Path

from .constants import RESEARCH_DB_PATH, SENTIMENT_DB_PATH
from .display_annotations import chinese_translation, freshness_warning, source_original_text
from .display_labels import display_label
from .state_registry import AB_URI_TABLES
from .validators import ValidationError, validate_uri

AB_DB_PATHS = {
    "research": RESEARCH_DB_PATH,
    "sentiment": SENTIMENT_DB_PATH,
}

SAFE_COLUMNS = {
    ("research", "source"): [
        "id", "title", "source_type", "publisher", "publish_date",
        "quality_tier", "source_url", "file_path", "source_credibility",
    ],
    ("research", "industry_data_point"): [
        "id", "industry_id", "company_id", "metric", "period", "as_of_date",
        "value_num", "value_text", "unit", "source_id", "source_excerpt",
        "extraction_method",
    ],
    ("research", "company"): [
        "id", "name", "ticker", "market", "listing_status",
    ],
    ("sentiment", "stock_kline"): [
        "id", "ticker", "trade_date", "open", "high", "low", "close", "volume",
    ],
    ("sentiment", "senti_post"): [
        "id", "company_id", "ticker", "platform", "post_time", "text", "sentiment",
    ],
}


def _format_value(record: dict) -> str:
    if record.get("value_num") is not None:
        return f"{record.get('value_num')} {record.get('unit') or ''}".strip()
    return f"{record.get('value_text') or ''} {record.get('unit') or ''}".strip()


def _annotate_record(record: dict | None, linked_source: dict | None = None) -> None:
    if not record:
        return
    source_date = linked_source.get("publish_date") if linked_source else record.get("publish_date")
    record["freshness_warning"] = freshness_warning(record.get("period"), record.get("as_of_date"), source_date, record.get("source_excerpt"))
    record["title_zh"] = chinese_translation(record.get("title"))
    record["source_excerpt_zh"] = chinese_translation(record.get("source_excerpt"))
    record["source_excerpt_display"] = source_original_text(record.get("source_excerpt"))
    if record.get("extraction_method"):
        record["extraction_method_display"] = display_label(record.get("extraction_method"))
    if linked_source:
        linked_source["freshness_warning"] = freshness_warning(linked_source.get("publish_date"))
        linked_source["title_zh"] = chinese_translation(linked_source.get("title"))


def _human_explanation(object_type: str, table: str, record: dict | None, linked_source: dict | None = None) -> dict | None:
    if not record:
        return None
    if table == "industry_data_point":
        source_title = linked_source.get("title") if linked_source else None
        source_publisher = linked_source.get("publisher") if linked_source else None
        source_date = linked_source.get("publish_date") if linked_source else None
        plain_steps = [
            f"指标：{record.get('metric')}",
            f"期间：{record.get('period') or record.get('as_of_date') or '未标明'}",
            f"数值：{_format_value(record)}",
            f"来源标题：{source_title or '未找到关联来源'}",
            f"发布方和时间：{source_publisher or '未标明'}，{source_date or '未标明'}",
            f"抽取方式：{display_label(record.get('extraction_method'))}",
            f"原文摘录：{record.get('source_excerpt_display') or record.get('source_excerpt') or '未提供'}",
        ]
        title_zh = chinese_translation(source_title)
        excerpt_zh = chinese_translation(record.get("source_excerpt"))
        stale = freshness_warning(record.get("period"), record.get("as_of_date"), source_date, record.get("source_excerpt"))
        if title_zh:
            plain_steps.append(f"中文标题：{title_zh}")
        if excerpt_zh:
            plain_steps.append(f"原文摘录中文译意：{excerpt_zh}")
        if stale:
            plain_steps.append(stale)
        return {
            "headline": f"A/B 行研数据点：{record.get('metric')}" if record.get("metric") else "A/B 行研数据点",
            "plain_steps": plain_steps,
            "json_guide": [
                "这里展示的是 A/B 行研库数据点的只读快照。",
                "引用原文是判断该数字是否可信的第一层依据。",
                "抽取方式说明数字来自 PDF、网页或可复算推断。",
            ],
        }
    if table == "source":
        plain_steps = [
            f"标题：{record.get('title')}",
            f"发布方：{record.get('publisher') or '未标明'}",
            f"发布日期：{record.get('publish_date') or '未标明'}",
            f"可信度：{record.get('source_credibility') or record.get('quality_tier') or '未标明'}",
            f"原始资料定位：{'已登记，可通过来源详情打开' if record.get('source_url') or record.get('file_path') else '未登记'}",
        ]
        title_zh = chinese_translation(record.get("title"))
        stale = freshness_warning(record.get("publish_date"))
        if title_zh:
            plain_steps.append(f"中文标题：{title_zh}")
        if stale:
            plain_steps.append(stale)
        return {
            "headline": record.get("title") or "A/B 行研来源",
            "plain_steps": plain_steps,
            "json_guide": [
                "这里展示的是 A/B 行研来源的只读快照。",
                "来源等级和可信度用于判断该材料能否支撑当前结论。",
            ],
        }
    return {
        "headline": "A/B 行研库只读证据",
        "plain_steps": ["该对象来自 A/B 行研库，Opportunity Lens 只读引用，不会回写。"],
        "json_guide": ["内部对象类型和定位信息保留在 API，不在页面直接展示。"],
    }


def connect_ab(db_key: str) -> sqlite3.Connection:
    path = Path(AB_DB_PATHS[db_key])
    if not path.exists():
        raise FileNotFoundError(path)
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def resolve_ab_uri(ref: str) -> dict:
    scheme, object_type, ident = validate_uri(ref)
    if scheme != "ab":
        raise ValidationError(f"not an ab URI: {ref}")
    db_key, table = AB_URI_TABLES[object_type]
    cols = SAFE_COLUMNS[(db_key, table)]
    col_sql = ", ".join(cols)
    conn = None
    try:
        conn = connect_ab(db_key)
        row = conn.execute(f"SELECT {col_sql} FROM {table} WHERE id=?", (ident,)).fetchone()
    except FileNotFoundError:
        return {
            "uri": ref,
            "scheme": "ab",
            "database": db_key,
            "object_type": object_type,
            "id": ident,
            "found": False,
            "error": "A/B 数据库文件不可用",
        }
    except sqlite3.Error as exc:
        return {
            "uri": ref,
            "scheme": "ab",
            "database": db_key,
            "object_type": object_type,
            "id": ident,
            "found": False,
            "error": str(exc),
        }
    finally:
        if conn is not None:
            conn.close()
    if not row:
        return {
            "uri": ref,
            "scheme": "ab",
            "database": db_key,
            "object_type": object_type,
            "id": ident,
            "found": False,
            "record": None,
        }
    record = {k: row[k] for k in row.keys()}
    linked_source = None
    deep_link = None
    if table == "industry_data_point" and record.get("source_id"):
        try:
            conn = connect_ab(db_key)
            src_row = conn.execute(
                "SELECT id, title, source_type, publisher, publish_date, quality_tier, source_url, file_path, source_credibility FROM source WHERE id=?",
                (record["source_id"],),
            ).fetchone()
            if src_row:
                linked_source = {k: src_row[k] for k in src_row.keys()}
                deep_link = f"/source/{record['source_id']}?hl={record['id']}"
        except sqlite3.Error:
            linked_source = None
        finally:
            if conn is not None:
                conn.close()
    elif table == "source":
        deep_link = f"/source/{record['id']}"
    _annotate_record(record, linked_source=linked_source)
    return {
        "uri": ref,
        "scheme": "ab",
        "database": db_key,
        "object_type": object_type,
        "canonical_object_type": f"{db_key}.{table}",
        "id": ident,
        "found": True,
        "record": record,
        "linked_source": linked_source,
        "deep_link": deep_link,
        "read_only": True,
        "human_explanation": _human_explanation(object_type, table, record, linked_source=linked_source),
    }


def ab_row_counts() -> dict[str, dict[str, int | str]]:
    out: dict[str, dict[str, int | str]] = {}
    for (db_key, table), _cols in SAFE_COLUMNS.items():
        key = f"{db_key}.{table}"
        conn = None
        try:
            conn = connect_ab(db_key)
            out[key] = {"count": int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])}
        except Exception as exc:
            out[key] = {"error": str(exc)}
        finally:
            if conn is not None:
                conn.close()
    return out
