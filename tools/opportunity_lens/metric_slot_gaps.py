from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


USABLE_SLOT_STATUSES = frozenset(
    {
        "available",
        "available_with_grade_unknown",
        "available_text_only",
        "calculated",
        "stale_but_usable",
    }
)

# V0.8.1 中这两个槽只解释背景，不进入覆盖率。旧库没有单独保存
# slot_role，因此读取既有 run 时还要用稳定的 slot key 排除它们。
CONTEXT_SLOT_KEYS = frozenset({"price_source_quality", "planned_or_rumored_capacity"})


def _slot_key(slot: Mapping[str, Any]) -> str:
    return str(slot.get("slot_code") or slot.get("slot_key") or "").strip()


def is_missing_scoring_slot(slot: Mapping[str, Any]) -> bool:
    """Return whether a slot is a genuine score-blocking evidence gap."""

    key = _slot_key(slot)
    if str(slot.get("slot_role") or "").strip() == "context" or key in CONTEXT_SLOT_KEYS:
        return False
    if str(slot.get("scoring_eligibility") or "core_eligible") in {
        "background_only",
        "early_signal_only",
        "reference_only",
    }:
        return False
    status = str(slot.get("value_status") or "").strip()
    if status == "not_applicable":
        return False
    if status not in USABLE_SLOT_STATUSES:
        return True
    # 可用的核心槽必须形成槽分；否则仍不能进入覆盖率和因子计算。
    return slot.get("slot_score") is None


def missing_metric_slot_labels(slots: Sequence[Mapping[str, Any]]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for slot in slots:
        if not is_missing_scoring_slot(slot):
            continue
        label = str(
            slot.get("slot_label")
            or slot.get("metric_name")
            or _slot_key(slot)
            or "未命名研究指标"
        ).strip()
        if label and label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def summarize_missing_metric_slots(
    slots: Sequence[Mapping[str, Any]],
    *,
    max_labels: int = 5,
) -> str | None:
    labels = missing_metric_slot_labels(slots)
    if not labels:
        return None
    limit = max(1, int(max_labels))
    shown = "、".join(labels[:limit])
    suffix = f"等{len(labels)}项指标" if len(labels) > limit else ""
    return f"缺少可直接复算的{shown}{suffix}。"

