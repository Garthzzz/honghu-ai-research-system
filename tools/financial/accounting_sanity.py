from __future__ import annotations

"""Accounting sanity rules shared by financial-data producers and import gates."""

from typing import Any, Iterable, Mapping


def _annual_year(row: Mapping[str, Any]) -> int | None:
    if str(row.get("fact_type") or "") != "actual":
        return None
    raw_year = row.get("fiscal_year")
    if raw_year is None:
        period_end = str(row.get("period_end") or "")
        if len(period_end) >= 4 and period_end[:4].isdigit():
            raw_year = period_end[:4]
    try:
        year = int(raw_year)
    except (TypeError, ValueError):
        return None
    fiscal_period = str(row.get("fiscal_period") or "").upper()
    period_end = str(row.get("period_end") or "")
    if fiscal_period not in {"FY", "Q4"} and not period_end.endswith("-12-31"):
        return None
    return year


def annual_roe_sanity_reasons(
    observations: Iterable[Mapping[str, Any]],
) -> dict[int, str]:
    """Identify annual ROE values whose equity denominator is not meaningful.

    Parent equity (``book_value``) is preferred when present; otherwise total
    equity is a conservative proxy.  If either opening or closing equity is
    non-positive, a conventional annual ROE is not comparable because its
    denominator crosses or remains below zero.  An absolute supplier value over
    500% is also held back as a near-zero-denominator warning unless a filing
    override explicitly marks the period applicable.
    """

    rows = [dict(row) for row in observations]
    parent_equity: dict[int, float] = {}
    total_equity: dict[int, float] = {}
    roe_rows: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        year = _annual_year(row)
        if year is None or row.get("quality_status") == "superseded":
            continue
        metric = str(row.get("metric_name") or "")
        value = row.get("value_num")
        if metric in {"book_value", "total_equity"} and value is not None:
            target = parent_equity if metric == "book_value" else total_equity
            target[year] = float(value)
        elif metric == "roe":
            roe_rows.setdefault(year, []).append(row)

    equity = dict(total_equity)
    equity.update(parent_equity)
    reasons: dict[int, str] = {}
    for year, annual_rows in roe_rows.items():
        closing = equity.get(year)
        opening = equity.get(year - 1)
        reason_parts: list[str] = []
        if closing is not None and closing <= 0:
            reason_parts.append("期末权益非正")
        if opening is not None and opening <= 0:
            reason_parts.append("期初权益非正")
        numeric_values = [
            abs(float(row["value_num"]))
            for row in annual_rows
            if row.get("value_num") is not None
        ]
        if numeric_values and max(numeric_values) > 500:
            reason_parts.append("供应商ROE绝对值超过500%，表明平均权益分母接近零")
        if reason_parts:
            reasons[year] = "；".join(dict.fromkeys(reason_parts))
    return reasons


def normalize_nonmeaningful_annual_roe(
    observations: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return observations with non-meaningful annual ROE marked not applicable.

    The supplier number is retained in the formula/audit trail and the raw
    source snapshot.  It is deliberately removed from ``value_num`` so public
    histories, averages and PB-return regressions cannot consume it.
    """

    normalized = [dict(row) for row in observations]
    reasons = annual_roe_sanity_reasons(normalized)
    for row in normalized:
        year = _annual_year(row)
        if (
            year not in reasons
            or str(row.get("metric_name") or "") != "roe"
            or row.get("quality_status") == "superseded"
        ):
            continue
        raw_value = row.get("value_num")
        existing_formula = str(row.get("formula") or "").strip()
        audit_formula = (
            f"供应商原始ROE={raw_value}%；{reasons[year]}。"
            "该比例不进入历史均值、趋势图或PB—ROE回归。"
        )
        row["value_num"] = None
        row["value_text"] = "不适用"
        row["quality_status"] = "not_applicable"
        row["formula"] = (
            f"{existing_formula}；{audit_formula}" if existing_formula else audit_formula
        )
        input_refs = list(row.get("input_refs") or [])
        input_refs.append(f"accounting_sanity:annual_roe:{year}")
        row["input_refs"] = input_refs
    return normalized

