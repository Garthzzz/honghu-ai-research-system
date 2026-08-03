from __future__ import annotations

"""Build the auditable lithium-battery supply/demand model ledger.

The model keeps deployment, shipment, production, sales and nameplate capacity
as separate measures.  It interpolates only between disclosed anchors and marks
all scenario multipliers as internal research assumptions.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_industry_supply_demand_v1.json"
)


def _sha(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _ev_path() -> tuple[float, list[dict[str, Any]]]:
    start = 1.2
    end = 3.0
    years = 5
    cagr = (end / start) ** (1 / years) - 1
    rows = []
    for year in range(2025, 2031):
        value = start * (1 + cagr) ** (year - 2025)
        rows.append(
            {
                "year": year,
                "evBatteryDeploymentTwh": round(value, 4),
                "identity": (
                    "IEA事实锚"
                    if year in {2025, 2030}
                    else "在2025与2030 IEA事实/预测锚之间的等复合增速插值"
                ),
            }
        )
    return cagr, rows


def _storage_path() -> list[dict[str, Any]]:
    # 2026 is InfoLink's cell-shipment forecast.  Later growth rates are
    # internal research assumptions and never presented as external forecasts.
    growth = {2027: 0.25, 2028: 0.20, 2029: 0.18, 2030: 0.15}
    value = 0.897
    rows = [
        {
            "year": 2026,
            "storageCellShipmentTwh": value,
            "identity": "InfoLink 2026年全球储能电芯出货预测",
        }
    ]
    for year in range(2027, 2031):
        value *= 1 + growth[year]
        rows.append(
            {
                "year": year,
                "storageCellShipmentTwh": round(value, 4),
                "growthAssumptionPct": growth[year] * 100,
                "identity": "内部基准情景假设",
            }
        )
    return rows


def build(output: Path) -> dict[str, Any]:
    ev_cagr, ev_path = _ev_path()
    storage_path = _storage_path()
    payload: dict[str, Any] = {
        "schemaVersion": "lithium_battery.industry_supply_demand.v1",
        "asOfDate": "2026-07-28",
        "researchRunRef": "lithium_battery_b_20260728",
        "question": (
            "全球和中国动力、储能电池需求如何增长，名义产能经投产、认证、"
            "利用率、良率、产品和区域资格折算后，何时形成紧张或过剩？"
        ),
        "measurementContract": {
            "deployment": "车辆或项目实际部署的电量，不含供应链库存。",
            "shipment": "电芯厂向客户发出的产品，可能含库存和交付时点差。",
            "production": "当期生产量，不等于销售或终端使用。",
            "sales": "行业统计销售口径，含国内、出口及不同应用。",
            "nameplateCapacity": "设计或名义产能，不等于合格可销售产量。",
            "effectiveSupplyFormula": (
                "有效供给＝名义产能×已投产比例×客户认证比例×利用率×良率"
                "×产品适配比例×区域合规比例"
            ),
        },
        "observedAnchors": [
            {
                "metric": "全球锂离子电池部署",
                "period": "2025",
                "value": 1.5,
                "unit": "TWh，下限",
                "sourceRef": "iea_ev_batteries_2026",
            },
            {
                "metric": "全球电动车电池部署",
                "period": "2025",
                "value": 1.2,
                "unit": "TWh",
                "sourceRef": "iea_ev_batteries_2026",
            },
            {
                "metric": "全球电动车电池部署",
                "period": "2030 CPS/STEPS",
                "value": 3.0,
                "unit": "TWh，约值",
                "sourceRef": "iea_ev_batteries_2026",
            },
            {
                "metric": "全球锂离子电池名义产能",
                "period": "2025年末",
                "value": 4.0,
                "unit": "TWh，下限",
                "sourceRef": "iea_ev_batteries_2026",
            },
            {
                "metric": "全球储能电芯出货",
                "period": "2026Q1",
                "value": 0.20552,
                "unit": "TWh",
                "sourceRef": "infolink_ess_2026q1",
            },
            {
                "metric": "全球储能电芯出货",
                "period": "2026全年预测",
                "value": 0.897,
                "unit": "TWh",
                "sourceRef": "infolink_ess_2026q1",
            },
        ],
        "demandModel": {
            "evFormula": (
                "EV电池部署＝Σ（各地区×车型销量×平均带电量）；公开模型使用"
                "IEA 2025与2030锚进行中间年份插值，不把插值伪装成外部预测。"
            ),
            "evAnchorCagrPct": round(ev_cagr * 100, 4),
            "evPath": ev_path,
            "storageFormula": (
                "储能电芯需求＝新增储能功率×平均时长÷系统效率＋替换、"
                "安全冗余和供应链库存变化。"
            ),
            "storageShipmentPath": storage_path,
            "nonAdditivityWarning": (
                "EV是终端部署口径，储能是电芯出货口径；二者不得直接相加成"
                "全球终端电池需求。储能路径用于供应商排产与景气分析。"
            ),
        },
        "chinaFlowBridge2026H1": {
            "productionGwh": 1068.9,
            "salesGwh": 979.4,
            "productionMinusSalesGwh": 89.5,
            "powerSalesGwh": 661.3,
            "storageSalesGwh": 318.1,
            "exportsGwh": 181.3,
            "domesticPowerInstallationGwh": 335.6,
            "formula": (
                "产量＝国内动力交付＋国内储能交付＋出口＋库存变化＋在途、"
                "样品及统计差异"
            ),
            "boundary": (
                "89.5GWh只是当期产销差，不等于期末库存；产量减国内动力装车"
                "更不能解释成过剩，因为遗漏储能、出口和其他流向。"
            ),
            "sourceRef": "fastmarkets_cabia_2026h1",
        },
        "scenarioContract": {
            "probabilitiesAssigned": False,
            "scenarios": [
                {
                    "name": "需求强、供给有序",
                    "evVsAnchor": "高于IEA插值路径",
                    "storageVsBase": "高于内部基准路径",
                    "effectiveSupply": "按客户和订单节奏投放",
                    "financialTransmission": (
                        "ASP降幅较小，利用率和单Wh利润提高，头部与已有合格"
                        "储能产能的公司自由现金流上修。"
                    ),
                },
                {
                    "name": "基准",
                    "evVsAnchor": "沿IEA插值路径",
                    "storageVsBase": "沿内部基准路径",
                    "effectiveSupply": "头部高利用率、部分新厂爬坡",
                    "financialTransmission": (
                        "行业收入增长，利润向高利用率、合格产品与合规地区集中。"
                    ),
                },
                {
                    "name": "需求弱、产能集中释放",
                    "evVsAnchor": "低于IEA插值路径",
                    "storageVsBase": "项目融资或并网导致低于基准",
                    "effectiveSupply": "多地项目同时投产",
                    "financialTransmission": (
                        "ASP、利用率和ROE同步下降，负自由现金流与高融资依赖"
                        "公司的下行更大。"
                    ),
                },
            ],
        },
        "monitoring": [
            "区域EV销量、车型结构和平均带电量",
            "全球储能电芯出货、项目装机、并网和回款",
            "中国产量、销量、装车、出口、库存和应收",
            "公司产能利用率、良率、折旧和资本开支",
            "不同规格电芯ASP、材料成本和分部毛利",
            "海外项目客户、资格、实际产量与融资",
        ],
        "limitations": [
            "全球名义产能为下限锚，不构造缺乏来源的逐年全球产能单点。",
            "储能2027—2030增速是内部情景假设，不是InfoLink或IEA预测。",
            "EV部署和储能电芯出货口径不同，公开输出不得直接相加。",
            "有效供给折算项在公司缺少公开数据时使用范围或项目状态，不默认100%。",
            "模型输出描述供需方向与财务传导，不给主观概率或伪精确市场规模。",
        ],
    }
    payload["contentSha256"] = _sha(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build(args.output.resolve())
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "evYears": len(payload["demandModel"]["evPath"]),
                "storageYears": len(
                    payload["demandModel"]["storageShipmentPath"]
                ),
                "contentSha256": payload["contentSha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
