#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Deterministic release audit for the lithium-battery B-track package."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from tools.financial.read_models import company_bundle


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache" / "lithium_battery_research"
MODELS = CACHE / "models"
DOCS = ROOT / "docs" / "industries"
RESEARCH_DB = ROOT / "data" / "research.db"
FINANCIAL_DB = ROOT / "data" / "financial.db"
OUTPUT = CACHE / "reviews" / "release_review.json"
COMPANY_IDS = (254, 414, 661, 662, 663, 664, 665, 666, 667)
DOCUMENTS = (
    "锂电池.md",
    "锂电池_Q0_历史发展.md",
    "锂电池_Q1_竞争格局.md",
    "锂电池_Q2_市场空间.md",
    "锂电池_Q3_公司壁垒.md",
    "锂电池_Q4_行业特征.md",
    "锂电池_Q5_综述.md",
    "锂电池_Q6_政策与地缘政治.md",
    "锂电池_公司透视.md",
    "锂电池_估值对比.md",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit() -> dict[str, Any]:
    apply_audit = _load(CACHE / "lithium_battery_apply_audit.json")
    prepare_audit = _load(CACHE / "research_prepare_audit.json")
    browser_audit = _load(CACHE / "browser_audit" / "browser_audit.json")
    model = _load(MODELS / "battery_independent_models_v1.json")
    policy = _load(MODELS / "battery_policy_scenarios_v1.json")
    supply_demand = _load(
        MODELS / "battery_industry_supply_demand_v1.json"
    )
    reconciliation = _load(
        MODELS / "battery_external_reconciliation_v1.json"
    )

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, evidence: Any) -> None:
        checks.append({"check": name, "passed": bool(passed), "evidence": evidence})

    with sqlite3.connect(RESEARCH_DB) as conn:
        data_points = conn.execute(
            "SELECT COUNT(*) FROM industry_data_point WHERE industry_id=29"
        ).fetchone()[0]
        profiles = conn.execute(
            "SELECT COUNT(*) FROM company_profile WHERE industry_id=29"
        ).fetchone()[0]
        valid_source_ids = {
            int(row[0]) for row in conn.execute("SELECT id FROM source")
        }
    expected_points = int(prepare_audit.get("observation_count") or 0)
    expected_facts = int(
        prepare_audit.get("parallel_research_fact_count") or 0
    )
    check(
        "研究数据点与公司画像",
        data_points == expected_points == 229
        and expected_facts == 215
        and profiles == 9,
        {
            "data_points": data_points,
            "expected_data_points": expected_points,
            "company_profiles": profiles,
            "parallel_research_fact_count": expected_facts,
        },
    )
    check(
        "来源双通道",
        apply_audit.get("source_channel_counts") == {"report": 22, "web": 36}
        and prepare_audit.get("report_source_count") == 9
        and prepare_audit.get("web_source_count") == 29,
        {
            "registered": apply_audit.get("source_channel_counts"),
            "used_report": prepare_audit.get("report_source_count"),
            "used_web": prepare_audit.get("web_source_count"),
        },
    )

    cited: set[int] = set()
    document_results: list[dict[str, Any]] = []
    forbidden = re.compile(
        r"canonical|intake|字段完成度|参数 owner|本节专属边界|决策验证债",
        flags=re.IGNORECASE,
    )
    for name in DOCUMENTS:
        path = DOCS / name
        text = path.read_text(encoding="utf-8")
        refs = {int(value) for value in re.findall(r"\^src:(\d+)", text)}
        cited.update(refs)
        document_results.append({
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha256(path),
            "four_sections": all(
                label in text
                for label in ("问题", "研究方法与数据", "研究与分析", "总结")
            ),
            "forbidden_production_terms": sorted(set(forbidden.findall(text))),
            "citation_count": len(refs),
        })
    check(
        "公开正文结构与生产术语",
        all(
            row["four_sections"] and not row["forbidden_production_terms"]
            for row in document_results
        ),
        document_results,
    )
    check(
        "公开引用可解析",
        bool(cited) and cited <= valid_source_ids,
        {"citation_count": len(cited), "unknown": sorted(cited - valid_source_ids)},
    )
    q_depth = {}
    q_minimums = {
        "Q0": (8, 6500),
        "Q1": (10, 7500),
        "Q2": (10, 6500),
        "Q3": (11, 8000),
        "Q4": (11, 7000),
        "Q5": (11, 5500),
        "Q6": (15, 13000),
    }
    for q, (minimum_questions, minimum_chars) in q_minimums.items():
        path = next(DOCS.glob(f"锂电池_{q}_*.md"))
        text = path.read_text(encoding="utf-8")
        question_count = len(
            re.findall(r"^##\s+\d+\.\s+问题", text, flags=re.MULTILINE)
        )
        q_depth[q] = {
            "questions": question_count,
            "characters": len(text),
            "minimum_questions": minimum_questions,
            "minimum_characters": minimum_chars,
        }
    check(
        "Q0至Q6研究广度与深度",
        all(
            row["questions"] >= row["minimum_questions"]
            and row["characters"] >= row["minimum_characters"]
            for row in q_depth.values()
        ),
        q_depth,
    )

    companies = list(model.get("companies") or [])
    calculation_failures: list[str] = []
    for company in companies:
        for forecast in company.get("forecast") or []:
            revenue = sum(float(row["revenue"]) for row in forecast["segments"])
            gross_profit = sum(
                float(row["grossProfit"]) for row in forecast["segments"]
            )
            if abs(float(forecast["revenue"]) - revenue) > 1e-8:
                calculation_failures.append(
                    f"{company['company']} {forecast['year']} revenue"
                )
            if abs(float(forecast["grossProfit"]) - gross_profit) > 1e-8:
                calculation_failures.append(
                    f"{company['company']} {forecast['year']} gross_profit"
                )
        for method in company.get("valuationMethods") or []:
            if method.get("method") not in {"正常化市盈率", "PB—ROE"}:
                continue
            expected_low = float(method["basisValue"]) * float(
                method["lowParameter"]
            )
            expected_high = float(method["basisValue"]) * float(
                method["highParameter"]
            )
            if abs(float(method["valueLow"]) - expected_low) > 1e-8:
                calculation_failures.append(
                    f"{company['company']} {method['method']} low"
                )
            if abs(float(method["valueHigh"]) - expected_high) > 1e-8:
                calculation_failures.append(
                    f"{company['company']} {method['method']} high"
                )
    check(
        "九家公司经营与估值复算",
        len(companies) == 9 and not calculation_failures,
        {"company_count": len(companies), "failures": calculation_failures},
    )

    unit = policy.get("unitSensitivities") or {}
    consumption = unit.get(
        "chinaConsumptionTaxGrossPerRmb10bnEligibleRevenue", {}
    )
    rebate = unit.get(
        "chinaExportRebateLossPerRmb10bnEligibleExportRevenue", {}
    )
    check(
        "政策量纲反算",
        (
            abs(float(consumption.get("2026") or 0) - (2 / 3)) < 1e-8
            and abs(float(consumption.get("2027") or 0) - (8 / 3)) < 1e-8
            and consumption.get("2028") == 4.0
            and rebate.get("2026") == 2.25
            and rebate.get("2027") == 9.0
            and rebate.get("2028") == 9.0
        ),
        {"consumption_tax": consumption, "export_rebate_loss": rebate},
    )
    ev_path = (
        supply_demand.get("demandModel", {}).get("evPath") or []
    )
    china_bridge = supply_demand.get("chinaFlowBridge2026H1") or {}
    check(
        "供需模型口径与反算",
        (
            len(ev_path) == 6
            and ev_path[0].get("year") == 2025
            and ev_path[0].get("evBatteryDeploymentTwh") == 1.2
            and ev_path[-1].get("year") == 2030
            and ev_path[-1].get("evBatteryDeploymentTwh") == 3.0
            and abs(
                float(china_bridge.get("productionGwh") or 0)
                - float(china_bridge.get("salesGwh") or 0)
                - float(china_bridge.get("productionMinusSalesGwh") or 0)
            )
            < 1e-8
            and "不得直接相加"
            in supply_demand.get("demandModel", {}).get(
                "nonAdditivityWarning", ""
            )
        ),
        {
            "ev_path": ev_path,
            "china_bridge": china_bridge,
            "contentSha256": supply_demand.get("contentSha256"),
        },
    )
    check(
        "政策与地缘覆盖",
        len(policy.get("policies") or []) == 16
        and len(policy.get("politicalOutlook") or []) >= 6,
        {
            "policy_count": len(policy.get("policies") or []),
            "outlook_count": len(policy.get("politicalOutlook") or []),
            "contentSha256": policy.get("contentSha256"),
        },
    )
    check(
        "外部对账",
        len(reconciliation.get("modelRuns") or []) == 18
        and len(reconciliation.get("reconciliations") or []) > 0,
        {
            "model_runs": len(reconciliation.get("modelRuns") or []),
            "reconciliations": len(reconciliation.get("reconciliations") or []),
        },
    )

    company_page_results: list[dict[str, Any]] = []
    for company_id in COMPANY_IDS:
        bundle = company_bundle(company_id, db_path=FINANCIAL_DB)
        framework = (bundle or {}).get("valuation_framework") or {}
        asset_return = (bundle or {}).get("asset_return") or {}
        company_page_results.append({
            "company_id": company_id,
            "has_bundle": bundle is not None,
            "model_run_key": framework.get("model_run_key"),
            "pb_framework_ready": bool(
                framework.get("price_exposure")
                and framework.get("profit_driver")
                and framework.get("cycle_sensitivity")
                not in {None, "尚未完成专项判断"}
            ),
            "pb_band_status": (
                asset_return.get("pb_price_band_availability") or {}
            ).get("status"),
        })
    check(
        "公司页模型与PB Band",
        all(
            row["has_bundle"]
            and row["pb_framework_ready"]
            and row["pb_band_status"] == "ready"
            and str(row["model_run_key"]).startswith(
                "lithium_battery_b_20260728:"
            )
            for row in company_page_results
        ),
        company_page_results,
    )
    check(
        "桌面与移动浏览器",
        browser_audit.get("status") == "GREEN"
        and browser_audit.get("route_count") == 44
        and not browser_audit.get("issues"),
        {
            "status": browser_audit.get("status"),
            "route_count": browser_audit.get("route_count"),
            "issues": browser_audit.get("issues"),
            "sha256": _sha256(
                CACHE / "browser_audit" / "browser_audit.json"
            ),
        },
    )

    failed = [row for row in checks if not row["passed"]]
    payload = {
        "schema_version": "lithium_battery.release_review.v1",
        "research_run_ref": "lithium_battery_b_20260728",
        "status": "GREEN" if not failed else "RED",
        "checks": checks,
        "failed_checks": [row["check"] for row in failed],
        "scope": (
            "确定性复核覆盖数据点、双搜索通道、引用、正文结构、公司经营与估值"
            "复算、政策量纲、外部对账、公司页模型路由和桌面/移动浏览器。"
        ),
        "boundary": (
            "本文件是确定性自审记录，不冒充独立研究员或用户的最终审稿。"
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    payload = audit()
    print(json.dumps({
        "output": str(OUTPUT),
        "status": payload["status"],
        "failed_checks": payload["failed_checks"],
    }, ensure_ascii=False, indent=2))
    if payload["status"] != "GREEN":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
