#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Collect a read-only PCB-equipment company financial/valuation snapshot.

The collector calls only the project-approved Tushare/yfinance helpers and
writes an auditable cache.  It never opens or mutates research.db.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .company_financial_series_utils import (
        annotate_financial_series,
        fetch_company_financial_series,
    )
    from .market_snapshot_utils import fetch_company_market_snapshot, fetch_fx_rates
except ImportError:  # pragma: no cover - direct script compatibility
    from company_financial_series_utils import (
        annotate_financial_series,
        fetch_company_financial_series,
    )
    from market_snapshot_utils import fetch_company_market_snapshot, fetch_fx_rates


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "cache" / "pcb_equipment_research" / "company_financial_snapshot.json"
PROFILE_REQUIRED_PERIODS = ("2023", "2024", "2025", "2026Q1")


SPECIAL_COVERAGE_NOTES = {
    "kla": (
        "KLA 的 yfinance 序列只取得季度/财季列；截至2026-03-31的记录实际为"
        "FY2026Q3，未取得2023—2025三个完整财年损益，不能把该季度序列当作自然年全年。"
    ),
    "csun": (
        "志圣工业当前完整年度损益只覆盖2023—2024，2025仅取得部分季度且缺少"
        "2025全年与2026Q1可比损益；公司卡不得用行情财务分母日期冒充序列日期。"
    ),
    "ta_liang": (
        "大量科技取得2023—2025年度损益，但未取得2026Q1损益；公司卡最新完整"
        "展示期为2025-12-31。"
    ),
}


LISTED_ENTITIES: list[dict[str, Any]] = [
    {"key": "hans_cnc", "name": "大族数控", "ticker": "301200.SZ", "market": "A股", "scope": "独立上市主体；与大族激光分别披露"},
    {"key": "hans_laser", "name": "大族激光", "ticker": "002008.SZ", "market": "A股", "scope": "集团合并口径；不能替代大族数控财务"},
    {"key": "dongwei", "name": "东威科技", "ticker": "688700.SH", "market": "A股", "scope": "独立上市主体"},
    {"key": "cfmee", "name": "芯碁微装", "ticker": "688630.SH", "market": "A股", "scope": "A股合并口径；H股身份另行说明但不重复计数"},
    {"key": "zhengye", "name": "正业科技", "ticker": "300410.SZ", "market": "A股", "scope": "多业务集团，PCB设备分部未必单列"},
    {"key": "tianzhun", "name": "天准科技", "ticker": "688003.SH", "market": "A股", "scope": "机器视觉多业务集团"},
    {"key": "inno_laser", "name": "英诺激光", "ticker": "301021.SZ", "market": "A股", "scope": "激光器与激光装备多业务口径"},
    {"key": "yanmade", "name": "燕麦科技", "ticker": "688312.SH", "market": "A股", "scope": "自动化测试设备口径，以FPC为主"},
    {"key": "juzitech", "name": "矩子科技", "ticker": "300802.SZ", "market": "A股", "scope": "机器视觉设备多业务口径"},
    {"key": "gage", "name": "凯格精机", "ticker": "301338.SZ", "market": "A股", "scope": "精密自动化设备多业务口径"},
    {"key": "ta_liang", "name": "大量科技", "ticker": "3167.TW", "market": "其他", "scope": "中国台湾上市主体"},
    {"key": "csun", "name": "志圣工业", "ticker": "2467.TW", "market": "其他", "scope": "中国台湾上市主体"},
    {"key": "mitsubishi_electric", "name": "三菱电机", "ticker": "6503.T", "market": "其他", "scope": "集团财务；PCB激光钻孔非独立分部"},
    {"key": "screen", "name": "SCREEN Holdings", "ticker": "7735.T", "market": "其他", "scope": "集团财务；PCB设备所在PE Solutions分部"},
    {"key": "jcu", "name": "JCU", "ticker": "4975.T", "market": "其他", "scope": "化学品为主并含设备，非纯PCB设备公司"},
    {"key": "nidec", "name": "Nidec", "ticker": "6594.T", "market": "其他", "scope": "Nidec Advance Technology并表；子公司不独立披露"},
    {"key": "amada", "name": "AMADA", "ticker": "6113.T", "market": "其他", "scope": "2025年收购Via Mechanics；集团财务"},
    {"key": "lpkf", "name": "LPKF", "ticker": "LPK.DE", "market": "其他", "scope": "德国上市主体；PCB业务偏原型与激光细分"},
    {"key": "kla", "name": "KLA", "ticker": "KLAC", "market": "美股", "scope": "Orbotech并表；PCB业务在PCB & Component Inspection分部"},
    {"key": "mks", "name": "MKS Instruments", "ticker": "MKSI", "market": "美股", "scope": "ESI品牌并表；不重复计算ESI"},
    {"key": "cohu", "name": "Cohu", "ticker": "COHU", "market": "美股", "scope": "2021年出售atg，当前不属于PCB设备可比组"},
    {"key": "camtek", "name": "Camtek", "ticker": "CAMT", "market": "美股", "scope": "2017年出售PCB业务；当前半导体检测公司"},
    {"key": "mycronic", "name": "Mycronic", "ticker": "MYCR.ST", "market": "其他", "scope": "2021年从Cohu收购atg L&M并表"},
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _amount_available(row: dict[str, Any], field: str) -> bool:
    value = row.get(field)
    return isinstance(value, dict) and any(
        value.get(key) is not None
        for key in ("local_raw", "local_yi", "cny_yi", "usd_yi")
    )


def _iso_end_date(value: Any) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())[:8]
    if len(digits) != 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def _company_coverage(company: dict[str, Any]) -> dict[str, Any]:
    financial = company.get("financial_series") or {}
    periods = financial.get("periods") or []
    by_period = {str(row.get("period")): row for row in periods}
    complete = [
        period
        for period in PROFILE_REQUIRED_PERIODS
        if period in by_period
        and _amount_available(by_period[period], "revenue")
        and _amount_available(by_period[period], "net_income")
    ]
    missing = [period for period in PROFILE_REQUIRED_PERIODS if period not in complete]
    displayed = [
        period
        for period in PROFILE_REQUIRED_PERIODS
        if period in by_period
        and (
            _amount_available(by_period[period], "revenue")
            or _amount_available(by_period[period], "net_income")
        )
    ]
    dated_displayed = [
        (str(by_period[period].get("end_date") or ""), period)
        for period in displayed
        if str(by_period[period].get("end_date") or "")
    ]
    latest_end, latest_period = max(dated_displayed, default=("", ""))
    annual_metric_period = next(
        (
            period
            for period in ("2025", "2024", "2023")
            if period in by_period
            and any(
                by_period[period].get(field) is not None
                for field in ("gross_margin", "net_margin", "rd_ratio")
            )
        ),
        None,
    )
    annual_metric_row = by_period.get(annual_metric_period or "", {})
    note = (
        f"目标公司卡要求2023、2024、2025及2026Q1四期损益；当前完整覆盖"
        f"{len(complete)}/4期"
        + (f"（{ '、'.join(complete) }）" if complete else "")
        + (f"，缺少{ '、'.join(missing) }" if missing else "，无缺期")
        + "。"
    )
    special = SPECIAL_COVERAGE_NOTES.get(str(company.get("key")))
    if special:
        note += special
    if latest_end:
        note += f"本轮页面可实际展示的最新损益序列截至{_iso_end_date(latest_end)}。"
    else:
        note += "本轮没有可展示的目标期损益序列。"
    return {
        "profile_required_periods": list(PROFILE_REQUIRED_PERIODS),
        "complete_profit_and_loss_periods": complete,
        "missing_profit_and_loss_periods": missing,
        "displayed_profit_and_loss_periods": displayed,
        "complete_profit_and_loss": not missing,
        "latest_displayed_series_period": latest_period or None,
        "latest_displayed_series_date": _iso_end_date(latest_end),
        "profile_metric_period": annual_metric_period,
        "profile_metric_end_date": _iso_end_date(annual_metric_row.get("end_date")),
        "profile_metric_fields": [
            field
            for field in (
                "gross_margin",
                "net_margin",
                "operating_cash_flow",
                "rd_expense",
                "rd_ratio",
                "capex",
            )
            if (
                _amount_available(annual_metric_row, field)
                if field in {"operating_cash_flow", "rd_expense", "capex"}
                else annual_metric_row.get(field) is not None
            )
        ],
        "company_note": note,
    }


def normalize_snapshot_payload(
    payload: dict[str, Any],
    *,
    input_sha256: str | None = None,
) -> dict[str, Any]:
    """Upgrade a frozen snapshot without calling providers or mutating it."""

    result = copy.deepcopy(payload)
    legacy = str(result.get("schema_version") or "").endswith(".v1")
    for company in result.get("companies") or []:
        financial = company.get("financial_series") or {
            "source": "none",
            "currency": "CNY" if company.get("market") == "A股" else "USD",
            "periods": [],
        }
        annotate_financial_series(financial, legacy_snapshot=legacy)
        coverage = dict(financial.get("coverage") or {})
        coverage.update(_company_coverage({**company, "financial_series": financial}))
        financial["coverage"] = coverage
        company["financial_series"] = financial
    result["schema_version"] = "pcb_equipment.company_financial_snapshot.v2"
    result["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    result["financial_contract"] = {
        "version": "pcb_financial_comparability.v2",
        "net_income_yoy": (
            "provider原值仅保留溯源；只有本期及上年同期净利润均为正、且冻结展示"
            "输入不存在高舍入敏感性时才生成可比较增长率。"
        ),
        "currency": "海外金额同时保留原币、人民币亿元和美元亿元。",
        "net_margin": "同期间归母/可归属净利润÷营业收入重新计算。",
        "gross_margin": "保留报表/provider毛利率字段并标注期间及口径。",
    }
    if input_sha256:
        result["normalized_from"] = {
            "sha256": input_sha256,
            "mode": "offline_frozen_snapshot_upgrade_no_provider_calls",
        }
    return result


def collect(output: Path, *, input_snapshot: Path | None = None) -> dict[str, Any]:
    if input_snapshot is not None:
        input_snapshot = input_snapshot.resolve()
        if input_snapshot == output.resolve():
            raise ValueError("离线升级必须写入不同的暂存文件，不能覆盖冻结输入。")
        input_sha = _sha256(input_snapshot)
        payload = normalize_snapshot_payload(
            json.loads(input_snapshot.read_text(encoding="utf-8")),
            input_sha256=input_sha,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            relative = output.relative_to(ROOT)
        except ValueError:
            relative = output
        payload["output_path"] = str(relative).replace("\\", "/")
        payload["sha256"] = _sha256(output)
        return payload

    fx = fetch_fx_rates(allow_fallback=False)
    rows: list[dict[str, Any]] = []
    for entity in LISTED_ENTITIES:
        ticker = entity["ticker"]
        market = fetch_company_market_snapshot(ticker, fx=fx)
        financial = fetch_company_financial_series(ticker, fx=fx)
        company = {**entity, "market_snapshot": market, "financial_series": financial}
        coverage = dict(financial.get("coverage") or {})
        coverage.update(_company_coverage(company))
        financial["coverage"] = coverage
        rows.append(company)
        print(
            f"[{len(rows):02d}/{len(LISTED_ENTITIES):02d}] {entity['name']} "
            f"market={'error' if market.get('error') else 'ok'} "
            f"periods={len(financial.get('periods') or [])}"
        )
    payload = {
        "schema_version": "pcb_equipment.company_financial_snapshot.v2",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "providers": ["Tushare", "Yahoo Finance/yfinance"],
        "policy": "A股优先Tushare，其他市场使用yfinance；未调用Wind或Akshare；本文件不写数据库。",
        "fx_to_cny": fx,
        "companies": rows,
        "financial_contract": {
            "version": "pcb_financial_comparability.v2",
            "net_income_yoy": "provider原值仅保留溯源，不直接作为增长率。",
            "currency": "海外金额同时保留原币、人民币亿元和美元亿元。",
            "net_margin": "同期间归母/可归属净利润÷营业收入重新计算。",
            "gross_margin": "保留报表/provider毛利率字段并标注期间及口径。",
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["output_path"] = str(output.relative_to(ROOT)).replace("\\", "/")
    payload["sha256"] = _sha256(output)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--input-snapshot",
        type=Path,
        help="离线升级冻结 snapshot；提供时不调用 Tushare/yfinance。",
    )
    args = parser.parse_args()
    result = collect(
        args.output.resolve(),
        input_snapshot=args.input_snapshot.resolve() if args.input_snapshot else None,
    )
    print(json.dumps({"output": result["output_path"], "sha256": result["sha256"], "count": len(result["companies"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
