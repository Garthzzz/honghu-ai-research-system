from __future__ import annotations

import json
import re
from typing import Any, Mapping


_TEXT_ONLY_UNITS = {
    "文本",
    "模块用量",
    "案例",
    "产品定位",
    "材料口径",
    "技术要求",
    "客户部署",
    "阶段",
    "平台规格",
    "复合时间序列",
    "定性",
    "事实",
    "qualitative",
    "多指标",
}

_COMPOSITE_FIELD_LABELS = {
    "capacity_wafers_per_year": "年产能（片/年）",
    "utilization_pct": "产能利用率",
    "sales_wafers": "销量（片）",
    "average_price_rmb_per_wafer": "平均售价（元/片）",
}


def _number_text(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")


def _unit_already_expressed(value_text: str, unit: str) -> bool:
    text = re.sub(r"\s+", "", str(value_text or ""))
    normalized_unit = re.sub(r"\s+", "", str(unit or ""))
    if not text or not normalized_unit:
        return False
    if normalized_unit in text:
        return True

    # Financial snapshots often use a qualified unit such as
    # “亿元人民币，比例除外”.  When every amount in the prose already carries
    # the primary unit, appending the full qualifier duplicates the currency.
    primary_unit = re.split(r"[，,、]", normalized_unit, maxsplit=1)[0]
    if primary_unit and primary_unit != normalized_unit and primary_unit in text:
        return True

    # A compound unit describes alternative display currencies.  If the text
    # already spells out either currency with its own value, appending the raw
    # compound label would produce strings such as “……亿美元亿元人民币/亿美元”.
    unit_parts = [part for part in re.split(r"[/／]", normalized_unit) if part]
    if len(unit_parts) > 1 and any(part in text for part in unit_parts):
        return True

    if normalized_unit == "倍" and "倍" in text:
        return True
    if normalized_unit in {"%", "％"} and ("%" in text or "％" in text):
        return True
    return False


def _with_unit(value: Any, unit: str | None) -> str:
    text = _number_text(value) if isinstance(value, (int, float)) else str(value or "")
    unit_text = str(unit or "")
    if not text or not unit_text or unit_text in _TEXT_ONLY_UNITS:
        return text
    if _unit_already_expressed(text, unit_text):
        return text
    separator = " " if re.match(r"^[A-Za-z]", unit_text) else ""
    return f"{text}{separator}{unit_text}"


def _humanize_composite_text(value_text: str) -> str:
    text = str(value_text or "").strip()
    if "=" not in text:
        return text
    pieces: list[str] = []
    for part in re.split(r"[；;]", text):
        if "=" not in part:
            pieces.append(part.strip())
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            pieces.append(part.strip())
            continue
        label = _COMPOSITE_FIELD_LABELS.get(key)
        if not label:
            label = key.replace("_", " ").strip()
        if key.endswith("_pct") and value and not _unit_already_expressed(value, "%"):
            value = f"{value}%"
        pieces.append(f"{label} {value}".strip())
    return "；".join(piece for piece in pieces if piece)


def _observation_value(observation: Mapping[str, Any], unit: str) -> str:
    if observation.get("value_num") is not None:
        return _with_unit(observation["value_num"], observation.get("unit") or unit)
    if observation.get("value") is not None:
        return _with_unit(observation["value"], observation.get("unit") or unit)
    value_text = _humanize_composite_text(str(observation.get("value_text") or ""))
    return _with_unit(value_text, observation.get("unit") or unit)


def _time_series_display(payload: Mapping[str, Any], fallback_unit: str, max_observations: int) -> str:
    unit = str(payload.get("unit") or fallback_unit or "")
    observations = [item for item in (payload.get("observations") or []) if isinstance(item, Mapping)]
    rows: list[str] = []
    for observation in observations:
        period = str(observation.get("period") or "").strip()
        value = _observation_value(observation, unit)
        if period and value:
            rows.append(f"{period}：{value}")
        elif value:
            rows.append(value)

    if rows:
        if max_observations > 0 and len(rows) > max_observations:
            head_count = max(1, max_observations // 2)
            tail_count = max(1, max_observations - head_count)
            visible = rows[:head_count] + [f"……共{len(rows)}期……"] + rows[-tail_count:]
            return "；".join(visible)
        return "；".join(rows)

    latest = payload.get("latest") if isinstance(payload.get("latest"), Mapping) else {}
    latest_value = _observation_value(latest, unit) if latest else ""
    latest_period = str((latest or {}).get("period") or payload.get("period_end") or "").strip()
    if latest_value:
        return f"{latest_period}：{latest_value}" if latest_period else latest_value

    start = str(payload.get("period_start") or "").strip()
    end = str(payload.get("period_end") or "").strip()
    period = "—".join(item for item in (start, end) if item)
    return f"{period}同源时间序列" if period else "同源时间序列"


def format_data_point_value(row: Mapping[str, Any] | None, *, max_observations: int = 8) -> str:
    """Return a public, human-readable value without leaking structured JSON."""

    if not row:
        return ""
    unit = str(row.get("unit") or "")
    if row.get("value_num") is not None:
        return _with_unit(row["value_num"], unit)

    raw_value = row.get("value_text")
    if raw_value is None:
        return ""
    value_text = str(raw_value)
    try:
        payload = json.loads(value_text)
    except (json.JSONDecodeError, TypeError):
        payload = None

    if isinstance(payload, Mapping) and payload.get("kind") == "time_series_data_point":
        return _time_series_display(payload, unit, max_observations)
    if isinstance(payload, (Mapping, list)):
        return "结构化数据，详见引用原文"

    return _with_unit(_humanize_composite_text(value_text), unit)
