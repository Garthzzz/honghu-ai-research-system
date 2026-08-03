from __future__ import annotations

"""Build the deployable, browser-editable lithium-battery calculator model."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_independent_models_v1.json"
)
POLICY_SOURCE = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_policy_scenarios_v1.json"
)
SUPPLY_DEMAND_SOURCE = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_industry_supply_demand_v1.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "config"
    / "battery_calculator_models"
    / "battery_calculator_model_v1.json"
)


def _sha(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def build(output: Path) -> dict[str, Any]:
    independent = json.loads(SOURCE.read_text(encoding="utf-8"))
    policy = json.loads(POLICY_SOURCE.read_text(encoding="utf-8"))
    supply_demand = json.loads(
        SUPPLY_DEMAND_SOURCE.read_text(encoding="utf-8")
    )
    policy_by_company = {
        row["company"]: row for row in policy["companyExposures"]
    }
    consumption_rates = [
        next(
            item
            for item in policy["policies"]
            if item["policyId"] == "cn_battery_consumption_tax_2026"
        )["annualEquivalentRate"][str(year)]
        for year in (2026, 2027, 2028)
    ]
    rebate_rates = [
        next(
            item
            for item in policy["policies"]
            if item["policyId"] == "cn_export_vat_rebate_2026"
        )["annualEquivalentRate"][str(year)]
        for year in (2026, 2027, 2028)
    ]
    companies = independent["companies"]
    defaults = policy["calculatorDefaults"]
    for company in companies:
        company["policyProfile"] = policy_by_company[company["company"]]
        company["policyInputs"] = {
            "domesticEligibleRevenueShare": [0.0, 0.0, 0.0],
            "consumptionTaxRate": consumption_rates,
            "taxPassThrough": [defaults["taxPassThroughPct"] / 100] * 3,
            "upstreamTaxDeductible": [
                defaults["upstreamTaxDeductiblePct"] / 100
            ] * 3,
            "exportEligibleRevenueShare": [0.0, 0.0, 0.0],
            "exportRebateLossRate": rebate_rates,
            "exportPassThrough": [defaults["exportPassThroughPct"] / 100] * 3,
            "usDirectExportRevenueShare": [0.0, 0.0, 0.0],
            "usTariffRate": [defaults["usTariffPct"] / 100] * 3,
            "usSupplierAbsorption": [
                defaults["usSupplierAbsorptionPct"] / 100
            ] * 3,
            "euComplianceCapex": [0.0, 0.0, 0.0],
            "euInterestFreeLoanRmb100m": [0.0, 0.0, 0.0],
            "euAlternativeBorrowingRate": [
                defaults["euAlternativeBorrowingRatePct"] / 100
            ] * 3,
            "usLocalEligibleGwh": [0.0, 0.0, 0.0],
            "us45xCellUsdPerKwh": [defaults["us45xCellUsdPerKwh"]] * 3,
            "us45xModuleUsdPerKwh": [
                defaults["us45xModuleUsdPerKwh"]
            ] * 3,
            "us45xEligibility": [defaults["us45xEligibilityPct"] / 100] * 3,
            "us45xUtilization": [defaults["us45xUtilizationPct"] / 100] * 3,
            "usdCny": defaults["usdCny"],
        }
    payload: dict[str, Any] = {
        "schemaVersion": "battery_calculator.model.v1",
        "asOfDate": independent["as_of_date"],
        "researchRunRef": independent["research_run_ref"],
        "title": "锂电池业务、盈利、现金流与估值计算器",
        "formulaContract": {
            "batteryRevenue": "电池分部收入（亿元）＝出货量（GWh）×ASP（元/Wh）×10",
            "vehicleRevenue": "整车分部收入（亿元）＝销量（百万辆）×单车收入（元）÷100",
            "otherRevenue": "其他分部收入直接采用亿元人民币输入",
            "grossProfit": "分部毛利＝分部收入×分部毛利率",
            "netIncome": "归母净利润＝（毛利－经营费用＋税前其他收益）×（1－税率）－少数股东损益",
            "operatingCashFlow": "经营现金流＝归母净利润×现金转换率",
            "freeCashFlow": "自由现金流＝经营现金流－资本开支",
            "bookValue": "期末归母净资产＝期初归母净资产＋归母净利润－分红",
            "roe": "ROE＝归母净利润÷平均归母净资产",
            "peValue": "正常化市盈率估值＝指定年度归母净利润×目标市盈率",
            "pbValue": "PB估值＝指定年度期末归母净资产×目标PB",
            "consumptionTax": (
                "消费税现金影响＝收入×国内应税收入比例×全年等效税率"
                "×（1－转嫁率）×（1－已税投入抵扣率）"
            ),
            "exportRebate": (
                "出口退税减少＝收入×符合清单的出口收入比例×全年等效退税减少率"
                "×（1－转嫁率）"
            ),
            "usTariff": (
                "美国关税经济影响＝收入×美国直接出口比例×关税率×供应商承担比例"
            ),
            "us45x": (
                "45X抵免（亿元）＝合资格GWh×（电芯＋模组抵免美元/kWh）"
                "×美元兑人民币÷100×资格实现率×利用率"
            ),
            "euFinancing": (
                "欧盟无息贷款年度融资节约＝实际提款金额×替代市场融资利率"
            ),
        },
        "industryContext": {
            "globalEvBatteryJanMay2026": {
                "metric": "全球动力电池装机量",
                "period": "2026年1—5月",
                "totalGwh": 469.2,
                "cr3Pct": 63.3,
                "cr5Pct": 73.0,
                "leaders": [
                    {"company": "宁德时代", "sharePct": 40.2},
                    {"company": "比亚迪", "sharePct": 14.4},
                    {"company": "LG新能源", "sharePct": 8.7},
                    {"company": "中创新航", "sharePct": 5.1},
                    {"company": "国轩高科", "sharePct": 4.6},
                ],
                "source": "SNE Research 2026年1—5月全球动力电池装机统计",
            },
            "chinaEvBatteryH12026": {
                "metric": "中国动力电池装车量",
                "period": "2026年上半年",
                "totalGwh": 335.6,
                "cr3Pct": 69.37,
                "cr5Pct": 80.56,
                "leaders": [
                    {"company": "宁德时代", "sharePct": 46.04},
                    {"company": "比亚迪", "sharePct": 17.14},
                    {"company": "国轩高科", "sharePct": 6.19},
                    {"company": "中创新航", "sharePct": 6.18},
                    {"company": "亿纬锂能", "sharePct": 5.01},
                ],
                "source": "中国汽车动力电池产业创新联盟 2026年上半年装车数据",
            },
            "globalEssQ12026": {
                "metric": "全球储能电芯出货量",
                "period": "2026年一季度",
                "totalGwh": 205.52,
                "cr5Pct": 58.9,
                "cr10Pct": 85.2,
                "source": "InfoLink Consulting 2026年一季度储能电芯出货统计",
            },
            "boundary": "动力采用装机/装车口径，储能采用电芯出货口径；三组集中度不能混成同一排行榜。",
        },
        "companies": companies,
        "policyScenarioLedger": policy,
        "supplyDemandLedger": supply_demand,
        "scenarioContract": {
            "storage": "browser_local_storage_only",
            "immutableBaselines": ["AI基准情景", "市场一致预期情景"],
            "actions": ["保存", "复制", "重命名", "删除", "恢复默认", "并排比较"],
        },
        "limitations": [
            "研究员情景只保存在当前浏览器，不写回financial.db、research.db或冻结AI模型。",
            "新增分部自动进入公司收入、利润、现金流、ROE与估值汇总；删除分部同步移除下游计算。",
            "产能、客户和地区维度是研究标签，只有被启用且含经营参数的分部才进入财务计算。",
            "孚能科技处于扭亏阶段，PE只作诊断，收入倍数与现金消耗必须同时检查。",
            "政策模块默认不猜公司应税、出口清单或美国直供比例；输入为0时基线不受影响。",
            "政策调整结果与冻结经营基线并列展示，浏览器情景不会回写数据库。",
        ],
    }
    payload["contentSha256"] = _sha(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "output": str(output),
        "companies": len(payload["companies"]),
        "contentSha256": payload["contentSha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
