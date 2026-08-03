#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Deterministic evidence, calculation and financial audit for copper B-track.

The audit is deliberately read-only for all SQLite databases.  It recomputes
model hashes and core arithmetic instead of accepting the producer's status
field, then binds the result to the browser audit and current database state.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache" / "copper_research"
CLAIMS = ROOT / "cache" / "claims" / "copper_b_20260726_01_core_claims.json"
SUPPLY = CACHE / "models" / "copper_supply_demand_model_v1.json"
FINANCIAL = CACHE / "models" / "copper_independent_models_v2.json"
RECONCILIATION = CACHE / "models" / "copper_external_reconciliation_v2.json"
SNAPSHOT = CACHE / "copper_financial_snapshot.json"
BROWSER = CACHE / "browser_audit" / "browser_audit.json"
REFERENCE_WORKBOOK = ROOT / "碳酸锂标的估值测算20260606.xlsx"
OUTPUT = CACHE / "deterministic_research_audit.json"
RESEARCH_DB = ROOT / "data" / "research.db"
FINANCIAL_DB = ROOT / "data" / "financial.db"
COMPANY_IDS = (634, 635, 636)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _write(payload: dict[str, Any]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(OUTPUT)


def audit() -> dict[str, Any]:
    required = (
        CLAIMS,
        SUPPLY,
        FINANCIAL,
        RECONCILIATION,
        SNAPSHOT,
        BROWSER,
        REFERENCE_WORKBOOK,
    )
    missing = [
        str(path.relative_to(ROOT)).replace("\\", "/")
        for path in required
        if not path.is_file()
    ]
    if missing:
        raise FileNotFoundError(f"确定性审计缺少产物: {missing}")

    issues: list[str] = []
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: Any) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        if not passed:
            issues.append(f"{name}: {detail}")

    claims = _json(CLAIMS)
    sources = claims.get("sources") or []
    data_points = claims.get("data_points") or []
    accounting = (claims.get("meta") or {}).get("evidence_accounting") or {}
    channels = Counter(str(row.get("source_channel")) for row in sources)
    independence_keys = {
        str(row.get("independence_key"))
        for row in sources
        if row.get("independence_key")
    }
    check("平行观测达到门槛", len(data_points) >= 100, len(data_points))
    check(
        "观测与事实计数对账",
        len(data_points) == accounting.get("observation_count")
        and int(accounting.get("parallel_research_fact_count") or 0) == 159,
        {
            "observations": len(data_points),
            "ledger_observations": accounting.get("observation_count"),
            "parallel_facts": accounting.get("parallel_research_fact_count"),
        },
    )
    check(
        "研报与网络双通道",
        channels.get("report", 0) >= 1 and channels.get("web", 0) >= 1,
        dict(channels),
    )
    check(
        "独立证据组登记",
        len(independence_keys)
        == int(accounting.get("registered_source_independent_evidence_group_count") or 0),
        {
            "computed": len(independence_keys),
            "registered": accounting.get(
                "registered_source_independent_evidence_group_count"
            ),
        },
    )

    supply = _json(SUPPLY)
    supply_without_hash = {
        key: value for key, value in supply.items() if key != "content_sha256"
    }
    check(
        "供需模型内容哈希",
        supply.get("content_sha256") == _canonical_hash(supply_without_hash),
        supply.get("content_sha256"),
    )
    balance_errors: list[dict[str, Any]] = []
    for row in supply.get("base_series") or []:
        expected = round(
            float(row["refined_supply_mt"]) - float(row["refined_usage_mt"]), 3
        )
        if abs(expected - float(row["refined_balance_mt"])) > 0.001:
            balance_errors.append(
                {
                    "series": "base",
                    "year": row["year"],
                    "expected": expected,
                    "actual": row["refined_balance_mt"],
                }
            )
    for scenario, rows in (supply.get("scenarios") or {}).items():
        for row in rows:
            expected = round(
                float(row["refined_supply_mt"]) - float(row["refined_usage_mt"]), 3
            )
            if abs(expected - float(row["refined_balance_mt"])) > 0.001:
                balance_errors.append(
                    {
                        "series": scenario,
                        "year": row["year"],
                        "expected": expected,
                        "actual": row["refined_balance_mt"],
                    }
                )
    check("精炼铜平衡量反算", not balance_errors, balance_errors[:5])

    scenarios = supply.get("scenarios") or {}
    loose = {row["year"]: row for row in scenarios.get("供应宽松情景", [])}
    base = {row["year"]: row for row in scenarios.get("基准情景", [])}
    tight = {row["year"]: row for row in scenarios.get("供应受限情景", [])}
    hierarchy = all(
        year in base
        and year in tight
        and float(loose[year]["refined_balance_mt"])
        >= float(base[year]["refined_balance_mt"])
        >= float(tight[year]["refined_balance_mt"])
        for year in loose
    )
    check(
        "供需情景方向一致",
        hierarchy and set(loose) == set(base) == set(tight) == {2028, 2029, 2030},
        {
            "wide": {year: row["refined_balance_mt"] for year, row in loose.items()},
            "base": {year: row["refined_balance_mt"] for year, row in base.items()},
            "restricted": {
                year: row["refined_balance_mt"] for year, row in tight.items()
            },
        },
    )

    model = _json(FINANCIAL)
    workbook_contract = (model.get("inputs") or {}).get("reference_workbook") or {}
    check(
        "参考工作簿与冻结模型绑定",
        model.get("schema_version") == "copper.independent_model.freeze.v2"
        and workbook_contract.get("sha256") == _file_hash(REFERENCE_WORKBOOK)
        and int(workbook_contract.get("sheet_count") or 0) == 14
        and int(workbook_contract.get("formula_count") or 0) > 100,
        {
            "schema_version": model.get("schema_version"),
            "workbook_sha256": workbook_contract.get("sha256"),
            "actual_sha256": _file_hash(REFERENCE_WORKBOOK),
            "sheet_count": workbook_contract.get("sheet_count"),
            "formula_count": workbook_contract.get("formula_count"),
        },
    )
    check(
        "独立模型输入哈希",
        model.get("input_sha256") == _canonical_hash(model.get("inputs")),
        model.get("input_sha256"),
    )
    check(
        "独立模型输出哈希",
        model.get("output_sha256") == _canonical_hash(model.get("outputs")),
        model.get("output_sha256"),
    )
    companies = (model.get("outputs") or {}).get("companies") or []
    check(
        "三家公司独立建模",
        {row.get("ticker") for row in companies}
        == {"601899.SH", "603993.SH", "1208.HK"},
        [row.get("ticker") for row in companies],
    )
    company_model_issues: list[str] = []
    for company in companies:
        scenario_rows = company.get("scenarios") or {}
        if set(scenario_rows) != {"下行情景", "基准情景", "上行情景"}:
            company_model_issues.append(f"{company.get('company')}: 情景不完整")
            continue
        for index, year in enumerate((2026, 2027, 2028)):
            by_scenario = {
                name: rows[index]
                for name, rows in scenario_rows.items()
                if len(rows) > index
            }
            profit_key = (
                "attributable_net_income_usd_bn"
                if company.get("ticker") == "1208.HK"
                else "attributable_net_income_rmb_bn"
            )
            if (
                set(by_scenario) != {"下行情景", "基准情景", "上行情景"}
                or any(row.get("year") != year for row in by_scenario.values())
                or not (
                    float(by_scenario["下行情景"][profit_key])
                    <= float(by_scenario["基准情景"][profit_key])
                    <= float(by_scenario["上行情景"][profit_key])
                )
            ):
                company_model_issues.append(
                    f"{company.get('company')} {year}: 利润情景方向错误"
                )
        valuation = company.get("valuation") or {}
        pe = valuation.get("normalized_pe") or {}
        pb = valuation.get("pb_roe") or {}
        dcf = valuation.get("fcfe_dcf") or {}
        value_pairs = [
            (pe.get("equity_value_low_rmb_bn", pe.get("equity_value_low_usd_bn")),
             pe.get("equity_value_high_rmb_bn", pe.get("equity_value_high_usd_bn"))),
            (pb.get("equity_value_low_rmb_bn", pb.get("equity_value_low_usd_bn")),
             pb.get("equity_value_high_rmb_bn", pb.get("equity_value_high_usd_bn"))),
        ]
        if any(
            not (_finite(low) and _finite(high) and 0 < float(low) <= float(high))
            for low, high in value_pairs
        ):
            company_model_issues.append(f"{company.get('company')}: 估值区间错误")
        if not (
            _finite(dcf.get("equity_value"))
            and float(dcf["equity_value"]) > 0
            and 0 < float(dcf.get("terminal_value_share") or 0) < 0.90
        ):
            company_model_issues.append(f"{company.get('company')}: DCF终值异常")
        commodity = valuation.get("workbook_style_commodity_bridge") or {}
        price_rows = commodity.get("price_sensitivity") or []
        profit_key = (
            "attributable_net_income_usd_bn"
            if company.get("ticker") == "1208.HK"
            else "attributable_net_income_rmb_bn"
        )
        if (
            len(price_rows) != 6
            or [row.get("copper_price_usd_t") for row in price_rows]
            != [8000.0, 9500.0, 11000.0, 11500.0, 12500.0, 14500.0]
            or any(
                float(price_rows[index][profit_key])
                >= float(price_rows[index + 1][profit_key])
                for index in range(max(0, len(price_rows) - 1))
            )
        ):
            company_model_issues.append(
                f"{company.get('company')}: 铜价—利润矩阵错误"
            )
    check("公司情景与估值数值合理性", not company_model_issues, company_model_issues)

    snapshot = _json(SNAPSHOT)
    check(
        "财务快照内容哈希",
        snapshot.get("content_sha256")
        == _canonical_hash(
            {key: value for key, value in snapshot.items() if key != "content_sha256"}
        ),
        snapshot.get("content_sha256"),
    )
    reconciliation = _json(RECONCILIATION)
    check(
        "外部对账内容哈希",
        reconciliation.get("content_sha256")
        == _canonical_hash(
            {
                key: value
                for key, value in reconciliation.items()
                if key != "content_sha256"
            }
        ),
        reconciliation.get("content_sha256"),
    )
    check(
        "冻结模型与外部对账绑定",
        reconciliation.get("frozen_model_input_sha256") == model.get("input_sha256")
        and reconciliation.get("frozen_model_output_sha256")
        == model.get("output_sha256")
        and reconciliation.get("financial_snapshot_sha256")
        == snapshot.get("content_sha256"),
        {
            "model_input": reconciliation.get("frozen_model_input_sha256"),
            "model_output": reconciliation.get("frozen_model_output_sha256"),
            "snapshot": reconciliation.get("financial_snapshot_sha256"),
        },
    )
    report_issues: list[str] = []
    for company, row in (reconciliation.get("companies") or {}).items():
        reports = row.get("selected_reports") or []
        if not reports:
            report_issues.append(f"{company}: 无近期卖方报告")
        for report in reports:
            published_date = str(
                report.get("published_date") or report.get("date") or ""
            )
            if published_date < "2026-04-01":
                report_issues.append(
                    f"{company}: {report.get('institution')} {published_date or '日期缺失'} 超出最近两季度"
                )
    check("公司预测仅用最近两个季度研报", not report_issues, report_issues)
    diagnostic_issues: list[str] = []
    for company, row in (reconciliation.get("companies") or {}).items():
        diagnostic = row.get("workbook_style_resource_diagnostic") or {}
        if diagnostic.get("role") != "当前市场隐含诊断，不是独立目标价值":
            diagnostic_issues.append(f"{company}: 市场隐含诊断角色错误")
        if company == "五矿资源":
            if not (
                _finite(diagnostic.get("current_group_implied_pe"))
                and _finite(
                    diagnostic.get(
                        "unit_group_value_wan_rmb_per_attributable_t"
                    )
                )
            ):
                diagnostic_issues.append(f"{company}: 集团资源诊断缺失")
        else:
            resource_values = (
                diagnostic.get("resource_implied_equity_value_range_bn") or []
            )
            resource_pe = diagnostic.get("resource_implied_pe_range") or []
            if not (
                len(resource_values) == 2
                and len(resource_pe) == 2
                and 0 <= float(resource_values[0]) <= float(resource_values[1])
                and 0 <= float(resource_pe[0]) <= float(resource_pe[1])
            ):
                diagnostic_issues.append(f"{company}: 资源隐含估值区间错误")
    check(
        "工作簿式市场隐含估值诊断",
        not diagnostic_issues,
        diagnostic_issues,
    )

    with _readonly(RESEARCH_DB) as conn:
        integrity = conn.execute("pragma integrity_check").fetchone()[0]
        foreign_keys = conn.execute("pragma foreign_key_check").fetchall()
        research_counts = {
            "data_points": conn.execute(
                "select count(*) from industry_data_point where industry_id=26"
            ).fetchone()[0],
            "sources": conn.execute(
                """select count(distinct source_id) from source_entity
                    where entity_type='industry' and entity_id=26"""
            ).fetchone()[0],
            "companies": conn.execute(
                "select count(*) from company_industry where industry_id=26"
            ).fetchone()[0],
        }
    check(
        "research.db一致性与铜行业入库",
        integrity == "ok"
        and not foreign_keys
        and research_counts == {"data_points": 183, "sources": 43, "companies": 3},
        {
            "integrity": integrity,
            "foreign_keys": foreign_keys[:5],
            **research_counts,
        },
    )

    with _readonly(FINANCIAL_DB) as conn:
        integrity = conn.execute("pragma integrity_check").fetchone()[0]
        foreign_keys = conn.execute("pragma foreign_key_check").fetchall()
        company_observations = {
            int(company_id): conn.execute(
                """select count(*) from financial_observation o
                    join financial_security_company_link l on l.security_id=o.security_id
                   where l.research_company_id=?""",
                (company_id,),
            ).fetchone()[0]
            for company_id in COMPANY_IDS
        }
        model_runs = conn.execute(
            """select count(*) from financial_model_run
                where research_run_ref='copper_b_20260726'
                  and status<>'superseded'"""
        ).fetchone()[0]
        reconciliations = conn.execute(
            """select count(*) from financial_reconciliation r
                join financial_model_run m on m.id=r.model_run_id
               where m.research_run_ref='copper_b_20260726'
                 and m.status<>'superseded'"""
        ).fetchone()[0]
        band_counts = {
            int(company_id): dict(
                conn.execute(
                    """select o.metric_name,count(*) from financial_observation o
                        join financial_security_company_link l on l.security_id=o.security_id
                       where l.research_company_id=?
                         and o.metric_name in ('close','pb','pe_ttm')
                       group by o.metric_name""",
                    (company_id,),
                ).fetchall()
            )
            for company_id in COMPANY_IDS
        }
    check(
        "financial.db一致性与公司模型入库",
        integrity == "ok"
        and not foreign_keys
        and all(value > 0 for value in company_observations.values())
        and model_runs == 15
        and reconciliations == 9
        and all(
            band_counts[company_id].get(metric, 0) >= 60
            for company_id in (634, 635)
            for metric in ("close", "pb", "pe_ttm")
        )
        and all(
            band_counts[636].get(metric, 0) >= 1
            for metric in ("close", "pb", "pe_ttm")
        ),
        {
            "integrity": integrity,
            "foreign_keys": foreign_keys[:5],
            "company_observations": company_observations,
            "model_runs": model_runs,
            "reconciliations": reconciliations,
            "band_counts": band_counts,
        },
    )

    browser = _json(BROWSER)
    check(
        "桌面与移动端浏览器审计",
        browser.get("status") == "GREEN"
        and int(browser.get("route_count") or 0) == 30
        and not browser.get("issues"),
        {
            "status": browser.get("status"),
            "route_count": browser.get("route_count"),
            "issues": browser.get("issues"),
        },
    )

    payload = {
        "schema_version": "copper.deterministic_research_audit.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "GREEN" if not issues else "RED",
        "artifact_hashes": {
            str(path.relative_to(ROOT)).replace("\\", "/"): _file_hash(path)
            for path in required
        },
        "checks": checks,
        "issues": issues,
    }
    _write(payload)
    return payload


def main() -> None:
    result = audit()
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "status": result["status"],
                "checks": len(result["checks"]),
                "issues": result["issues"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if result["issues"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
