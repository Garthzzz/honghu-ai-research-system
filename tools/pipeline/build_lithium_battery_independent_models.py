from __future__ import annotations

"""Build nine independent FY1-FY3 battery-company operating models.

Only official actuals, the audited quarterly workbook extract and explicit
industry/operating assumptions are read here.  Wind consensus and sell-side
forecasts are deliberately excluded and are joined only by the separate
reconciliation builder after this artifact has been frozen.
"""

import argparse
import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_financial_snapshot_v1.json"
)
WORKBOOK_EXTRACT = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_quarterly_workbook_extract_v1.json"
)
FILING_MANIFEST = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "sources"
    / "company_filing_manifest_v1.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_independent_models_v1.json"
)
RESEARCH_DB = ROOT / "data" / "research.db"

YEARS = (2026, 2027, 2028)


def _battery(
    name: str,
    volume: tuple[float, float, float],
    asp: tuple[float, float, float],
    margin: tuple[float, float, float],
    note: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "battery_gwh",
        "volume": dict(zip(map(str, YEARS), volume, strict=True)),
        "asp": dict(zip(map(str, YEARS), asp, strict=True)),
        "grossMargin": dict(zip(map(str, YEARS), margin, strict=True)),
        "formula": "分部收入（亿元）＝出货量（GWh）×不含税均价（元/Wh）×10",
        "note": note,
    }


def _vehicle(
    name: str,
    volume: tuple[float, float, float],
    asp: tuple[float, float, float],
    margin: tuple[float, float, float],
    note: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "vehicle_million_units",
        "volume": dict(zip(map(str, YEARS), volume, strict=True)),
        "asp": dict(zip(map(str, YEARS), asp, strict=True)),
        "grossMargin": dict(zip(map(str, YEARS), margin, strict=True)),
        "formula": "分部收入（亿元）＝销量（百万辆）×单车收入（元）÷100",
        "note": note,
    }


def _other(
    name: str,
    revenue: tuple[float, float, float],
    margin: tuple[float, float, float],
    note: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "revenue_rmb_100m",
        "revenue": dict(zip(map(str, YEARS), revenue, strict=True)),
        "grossMargin": dict(zip(map(str, YEARS), margin, strict=True)),
        "formula": "分部收入直接采用亿元人民币输入",
        "note": note,
    }


CONFIG: dict[str, dict[str, Any]] = {
    "宁德时代": {
        "ticker": "300750.SZ",
        "modelType": "动力＋储能＋材料",
        "segments": [
            _battery(
                "动力电池系统",
                (570, 690, 800),
                (0.72, 0.69, 0.67),
                (0.255, 0.255, 0.250),
                "2026年以半年报收入、全球装机份额和产能利用率约束；后两年同时计入ASP下降和欧洲产能爬坡。",
            ),
            _battery(
                "储能电池系统",
                (220, 290, 360),
                (0.58, 0.55, 0.53),
                (0.250, 0.245, 0.240),
                "以2026年储能需求上修、500Ah+渗透和海外系统项目为基础，未把全部行业增长归给公司。",
            ),
            _other(
                "电池材料、回收及其他",
                (500, 540, 580),
                (0.30, 0.30, 0.29),
                "与公司半年报业务口径对账，不与动力和储能出货重复。",
            ),
        ],
        "opexRatio": (0.075, 0.074, 0.073),
        "otherPretax": (80, 75, 80),
        "taxRate": (0.12, 0.12, 0.12),
        "minority": (10, 11, 12),
        "cashConversion": (1.45, 1.40, 1.35),
        "capex": (520, 560, 590),
        "payoutRatio": (0.55, 0.50, 0.48),
        "valuation": {"pe": (18, 24), "ke": (0.085, 0.095), "g": (0.025, 0.03)},
    },
    "比亚迪": {
        "ticker": "002594.SZ",
        "modelType": "整车集团＋电池业务桥接",
        "segments": [
            _vehicle(
                "新能源汽车",
                (5.30, 6.15, 6.90),
                (125000, 126000, 127000),
                (0.190, 0.192, 0.193),
                "电池内部供应不重复计收入；整车销量与海外工厂节奏共同约束。",
            ),
            _other(
                "手机部件及组装",
                (1900, 2050, 2200),
                (0.085, 0.087, 0.088),
                "按集团披露口径保留，与电池行业利润分开。",
            ),
            _other(
                "外供电池、储能及其他",
                (800, 950, 1100),
                (0.180, 0.185, 0.190),
                "只计外供和可识别业务，不把集团内部刀片电池结算重复加入收入。",
            ),
        ],
        "opexRatio": (0.120, 0.119, 0.118),
        "otherPretax": (0, 5, 10),
        "taxRate": (0.22, 0.22, 0.22),
        "minority": (10, 12, 14),
        "cashConversion": (1.45, 1.40, 1.35),
        "capex": (1550, 1450, 1350),
        "payoutRatio": (0.28, 0.30, 0.32),
        "valuation": {"pe": (16, 22), "ke": (0.095, 0.105), "g": (0.025, 0.03)},
    },
    "国轩高科": {
        "ticker": "002074.SZ",
        "modelType": "动力＋储能＋海外扩产",
        "segments": [
            _battery(
                "动力电池",
                (92, 119, 148),
                (0.50, 0.48, 0.46),
                (0.165, 0.170, 0.175),
                "以2025年全球动力装机53.5GWh、2026年一季度收入和大众体系放量节奏为约束。",
            ),
            _battery(
                "储能电池",
                (28, 42, 58),
                (0.48, 0.46, 0.44),
                (0.155, 0.160, 0.165),
                "储能按独立出货建模，不以动力装机榜份额代替储能份额。",
            ),
            _other(
                "输配电及其他",
                (55, 60, 65),
                (0.20, 0.20, 0.20),
                "保留非电池业务以完成集团利润对账。",
            ),
        ],
        "opexRatio": (0.130, 0.127, 0.124),
        "otherPretax": (5, 4, 4),
        "taxRate": (0.15, 0.15, 0.15),
        "minority": (2, 3, 4),
        "cashConversion": (1.55, 1.45, 1.35),
        "capex": (105, 100, 90),
        "payoutRatio": (0.10, 0.12, 0.15),
        "valuation": {"pe": (16, 24), "ke": (0.105, 0.115), "g": (0.02, 0.025)},
    },
    "中创新航": {
        "ticker": "3931.HK",
        "modelType": "动力＋储能",
        "segments": [
            _battery(
                "动力电池",
                (88, 113, 139),
                (0.55, 0.52, 0.50),
                (0.155, 0.165, 0.175),
                "以2025年年报、2026年一季度报告和全球动力装机排名约束。",
            ),
            _battery(
                "储能电池",
                (20, 31, 44),
                (0.50, 0.47, 0.45),
                (0.145, 0.155, 0.165),
                "储能采用独立客户和项目节奏，避免把动力客户认证直接外推。",
            ),
            _other(
                "其他业务",
                (15, 18, 20),
                (0.20, 0.20, 0.20),
                "集团对账项。",
            ),
        ],
        "opexRatio": (0.090, 0.087, 0.084),
        "otherPretax": (2, 2, 3),
        "taxRate": (0.18, 0.18, 0.18),
        "minority": (1, 1, 2),
        "cashConversion": (1.35, 1.30, 1.25),
        "capex": (70, 75, 75),
        "payoutRatio": (0.10, 0.12, 0.15),
        "valuation": {"pe": (10, 16), "ke": (0.11, 0.12), "g": (0.02, 0.025)},
    },
    "亿纬锂能": {
        "ticker": "300014.SZ",
        "modelType": "动力＋储能＋消费＋投资收益",
        "segments": [
            _battery(
                "动力电池",
                (50, 65, 82),
                (0.65, 0.62, 0.59),
                (0.160, 0.165, 0.170),
                "以2025年报产品收入和2026年一季度出货增长约束。",
            ),
            _battery(
                "储能电池",
                (65, 88, 112),
                (0.55, 0.52, 0.49),
                (0.135, 0.145, 0.155),
                "储能价格传导滞后单独体现在毛利率，不以收入增速代替利润增速。",
            ),
            _other(
                "消费电池与锂原电池",
                (270, 295, 320),
                (0.245, 0.245, 0.245),
                "沿用2025年报分产品基数，避免只研究动储。",
            ),
        ],
        "opexRatio": (0.100, 0.098, 0.096),
        "otherPretax": (20, 22, 24),
        "taxRate": (0.18, 0.18, 0.18),
        "minority": (7, 8, 9),
        "cashConversion": (1.35, 1.30, 1.25),
        "capex": (120, 125, 125),
        "payoutRatio": (0.18, 0.20, 0.22),
        "valuation": {"pe": (15, 21), "ke": (0.10, 0.11), "g": (0.02, 0.025)},
    },
    "瑞浦兰钧": {
        "ticker": "0666.HK",
        "modelType": "储能＋动力双轮驱动",
        "segments": [
            _battery(
                "动力电池",
                (35, 44, 54),
                (0.55, 0.52, 0.49),
                (0.115, 0.125, 0.135),
                "2026年上半年盈利预告已经验证规模效应，但仍保留价格和客户集中折价。",
            ),
            _battery(
                "储能电池",
                (25, 36, 48),
                (0.50, 0.47, 0.45),
                (0.135, 0.145, 0.155),
                "储能按海外与大储订单扩张建模。",
            ),
            _other("其他", (5, 6, 7), (0.18, 0.18, 0.18), "集团对账项。"),
        ],
        "opexRatio": (0.058, 0.056, 0.054),
        "otherPretax": (1, 1, 1),
        "taxRate": (0.18, 0.18, 0.18),
        "minority": (4, 5, 6),
        "cashConversion": (1.25, 1.20, 1.18),
        "capex": (38, 42, 45),
        "payoutRatio": (0.08, 0.10, 0.12),
        "valuation": {"pe": (12, 18), "ke": (0.11, 0.12), "g": (0.02, 0.025)},
    },
    "欣旺达": {
        "ticker": "300207.SZ",
        "modelType": "消费电子＋动力＋储能",
        "segments": [
            _other(
                "消费类电池与结构件",
                (400, 425, 450),
                (0.145, 0.145, 0.145),
                "保留公司基本盘，不能把集团整体当成纯动力电池公司。",
            ),
            _battery(
                "动力电池",
                (35, 48, 62),
                (0.60, 0.57, 0.54),
                (0.105, 0.120, 0.135),
                "以2026年一季度动储出货和客户爬坡约束，盈利修复慢于收入。",
            ),
            _battery(
                "储能电池",
                (12, 19, 28),
                (0.54, 0.51, 0.48),
                (0.120, 0.130, 0.140),
                "储能单独建模。",
            ),
            _other("其他", (60, 65, 70), (0.16, 0.16, 0.16), "集团对账项。"),
        ],
        "opexRatio": (0.107, 0.104, 0.101),
        "otherPretax": (13, 12, 11),
        "taxRate": (0.18, 0.18, 0.18),
        "minority": (4, 5, 6),
        "cashConversion": (1.30, 1.25, 1.20),
        "capex": (90, 88, 85),
        "payoutRatio": (0.18, 0.20, 0.22),
        "valuation": {"pe": (12, 18), "ke": (0.105, 0.115), "g": (0.018, 0.023)},
    },
    "鹏辉能源": {
        "ticker": "300438.SZ",
        "modelType": "储能为主＋消费与小动力",
        "segments": [
            _battery(
                "储能电池",
                (32, 47, 63),
                (0.55, 0.52, 0.49),
                (0.185, 0.190, 0.195),
                "以2026年一季度收入、满产状态和扩产节奏为约束。",
            ),
            _other(
                "消费与小动力",
                (58, 64, 70),
                (0.18, 0.18, 0.18),
                "保留非储能业务，不将所有增长归因于大储。",
            ),
        ],
        "opexRatio": (0.080, 0.078, 0.076),
        "otherPretax": (1, 1, 1),
        "taxRate": (0.18, 0.18, 0.18),
        "minority": (1, 1, 1),
        "cashConversion": (1.20, 1.18, 1.15),
        "capex": (28, 32, 35),
        "payoutRatio": (0.15, 0.18, 0.20),
        "valuation": {"pe": (14, 20), "ke": (0.105, 0.115), "g": (0.02, 0.025)},
    },
    "孚能科技": {
        "ticker": "688567.SH",
        "modelType": "软包动力电池扭亏模型",
        "segments": [
            _battery(
                "动力电池",
                (13, 18, 25),
                (0.70, 0.68, 0.65),
                (0.120, 0.145, 0.165),
                "2026年以一季度1.667亿元收入、13.82%毛利率和产能爬坡反推；旧卖方预测不作当前输入。",
            ),
            _other(
                "其他与研发服务",
                (4, 5, 6),
                (0.25, 0.25, 0.25),
                "仅作集团对账，不给固态电池未兑现收入。",
            ),
        ],
        "opexRatio": (0.140, 0.120, 0.110),
        "otherPretax": (-2, -1, 0),
        "taxRate": (0.00, 0.15, 0.15),
        "minority": (0, 0, 0),
        "cashConversion": (0.0, 1.10, 1.15),
        "capex": (12, 15, 18),
        "payoutRatio": (0.0, 0.0, 0.0),
        "valuation": {
            "pe": (12, 18),
            "ps": (1.0, 1.5),
            "ke": (0.12, 0.13),
            "g": (0.015, 0.02),
        },
    },
}


def _sha(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _company_ids() -> dict[str, int]:
    conn = sqlite3.connect(RESEARCH_DB)
    try:
        rows = conn.execute(
            "SELECT id,name FROM company WHERE name IN (%s)"
            % ",".join("?" for _ in CONFIG),
            tuple(CONFIG),
        ).fetchall()
    finally:
        conn.close()
    result = {str(name): int(company_id) for company_id, name in rows}
    missing = sorted(set(CONFIG) - set(result))
    if missing:
        raise ValueError(f"缺少规范公司身份: {missing}")
    return result


def _annual_wind(snapshot: dict[str, Any], ticker: str) -> list[dict[str, Any]]:
    rows = []
    for year_text, batch in snapshot["wind"]["annual"].items():
        row = batch["rows"].get(ticker)
        if not row:
            continue
        rows.append(
            {
                "year": int(year_text),
                "revenue": (row.get("oper_rev") or 0) / 1e8,
                "netIncome": (row.get("np_belongto_parcomsh") or 0) / 1e8,
                "ocf": (row.get("net_cash_flows_oper_act") or 0) / 1e8,
                "capex": (row.get("cash_pay_acq_const_fiolta") or 0) / 1e8,
                "grossMarginPct": row.get("grossprofitmargin"),
                "netMarginPct": row.get("netprofitmargin"),
                "roePct": row.get("roe"),
                "roaPct": row.get("roa2"),
                "sourceRef": f"wind:annual:{ticker}:{year_text}",
            }
        )
    return rows


def _yf_statement_value(snapshot: dict[str, Any], table: str, row: str, year: int) -> float | None:
    values = ((snapshot.get(table) or {}).get("rows") or {}).get(row) or {}
    for raw_date, raw_value in values.items():
        if str(raw_date).startswith(str(year)) and isinstance(raw_value, (int, float)):
            return float(raw_value) / 1e8
    return None


def _annual_yf(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for year in range(2021, 2026):
        revenue = _yf_statement_value(snapshot, "income_stmt", "Total Revenue", year)
        net_income = _yf_statement_value(snapshot, "income_stmt", "Net Income", year)
        if revenue is None and net_income is None:
            continue
        result.append(
            {
                "year": year,
                "revenue": revenue,
                "netIncome": net_income,
                "ocf": _yf_statement_value(
                    snapshot, "cash_flow", "Operating Cash Flow", year
                ),
                "capex": abs(
                    _yf_statement_value(
                        snapshot, "cash_flow", "Capital Expenditure", year
                    )
                    or 0
                ),
                "sourceRef": f"yfinance:annual:{snapshot['ticker']}:{year}",
            }
        )
    return result


def _segment_revenue(segment: dict[str, Any], year: int) -> float:
    key = str(year)
    if segment["kind"] == "battery_gwh":
        return float(segment["volume"][key]) * float(segment["asp"][key]) * 10
    if segment["kind"] == "vehicle_million_units":
        return float(segment["volume"][key]) * float(segment["asp"][key]) / 100
    return float(segment["revenue"][key])


def _build_forecast(
    config: dict[str, Any],
    *,
    opening_equity: float,
    opening_assets: float,
) -> list[dict[str, Any]]:
    rows = []
    prior_equity = opening_equity
    prior_assets = opening_assets
    for index, year in enumerate(YEARS):
        segment_rows = []
        revenue = 0.0
        gross_profit = 0.0
        for segment in config["segments"]:
            segment_revenue = _segment_revenue(segment, year)
            margin = float(segment["grossMargin"][str(year)])
            segment_rows.append(
                {
                    "name": segment["name"],
                    "kind": segment["kind"],
                    "revenue": segment_revenue,
                    "grossMargin": margin,
                    "grossProfit": segment_revenue * margin,
                    "volume": (segment.get("volume") or {}).get(str(year)),
                    "asp": (segment.get("asp") or {}).get(str(year)),
                    "note": segment["note"],
                }
            )
            revenue += segment_revenue
            gross_profit += segment_revenue * margin
        opex = revenue * float(config["opexRatio"][index])
        other_pretax = float(config["otherPretax"][index])
        tax_rate = float(config["taxRate"][index])
        minority = float(config["minority"][index])
        pretax = gross_profit - opex + other_pretax
        net_income = pretax * (1 - tax_rate) - minority
        if net_income > 0:
            ocf = net_income * float(config["cashConversion"][index])
        else:
            ocf = float((0.0, 8.0, 14.0)[index])
        capex = float(config["capex"][index])
        fcf = ocf - capex
        dividends = max(0.0, net_income * float(config["payoutRatio"][index]))
        ending_equity = prior_equity + net_income - dividends
        average_equity = (prior_equity + ending_equity) / 2
        ending_assets = max(
            prior_assets + capex + max(revenue * 0.03, 0) - max(ocf * 0.25, 0),
            ending_equity * 1.4,
        )
        average_assets = (prior_assets + ending_assets) / 2
        rows.append(
            {
                "year": year,
                "segments": segment_rows,
                "revenue": revenue,
                "grossProfit": gross_profit,
                "grossMargin": gross_profit / revenue if revenue else None,
                "operatingExpenses": opex,
                "otherPretax": other_pretax,
                "pretaxProfit": pretax,
                "taxRate": tax_rate,
                "minorityInterest": minority,
                "netIncome": net_income,
                "ocf": ocf,
                "capex": capex,
                "freeCashFlow": fcf,
                "dividends": dividends,
                "endingEquity": ending_equity,
                "endingAssets": ending_assets,
                "roe": net_income / average_equity if average_equity else None,
                "roa": net_income / average_assets if average_assets else None,
                "formula": (
                    "收入＝各分部收入之和；归母净利润＝[毛利润－经营费用＋税前其他收益]"
                    "×（1－税率）－少数股东损益；自由现金流＝经营现金流－资本开支"
                ),
            }
        )
        prior_equity = ending_equity
        prior_assets = ending_assets
    return rows


def _valuation(
    config: dict[str, Any],
    forecast: list[dict[str, Any]],
    market_cap: float,
) -> list[dict[str, Any]]:
    fy2 = forecast[1]
    fy3 = forecast[2]
    pe_low, pe_high = config["valuation"]["pe"]
    methods = []
    if fy2["netIncome"] > 0:
        methods.append(
            {
                "method": "正常化市盈率",
                "role": "核心",
                "basisYear": fy2["year"],
                "basisValue": fy2["netIncome"],
                "lowParameter": pe_low,
                "highParameter": pe_high,
                "valueLow": fy2["netIncome"] * pe_low,
                "valueHigh": fy2["netIncome"] * pe_high,
                "formula": "股权价值＝正常化归母净利润×目标市盈率",
                "parameterBasis": "历史估值、盈利质量、周期位置与真正可比公司交叉约束。",
            }
        )
    elif config["valuation"].get("ps"):
        ps_low, ps_high = config["valuation"]["ps"]
        methods.append(
            {
                "method": "市销率",
                "role": "扭亏期参考",
                "basisYear": fy2["year"],
                "basisValue": fy2["revenue"],
                "lowParameter": ps_low,
                "highParameter": ps_high,
                "valueLow": fy2["revenue"] * ps_low,
                "valueHigh": fy2["revenue"] * ps_high,
                "formula": "股权价值参考＝收入×目标市销率",
                "parameterBasis": "只用于亏损期收入资产的参考，不替代盈利与现金流检验。",
            }
        )
    ke_low, ke_high = config["valuation"]["ke"]
    g_low, g_high = config["valuation"]["g"]
    normalized_roe = max(0.0, (fy2["roe"] + fy3["roe"]) / 2)
    pb_low = max(0.45, min(6.0, (normalized_roe - g_low) / (ke_high - g_low)))
    pb_high = max(0.55, min(6.5, (normalized_roe - g_high) / (ke_low - g_high)))
    pb_low, pb_high = sorted((pb_low, pb_high))
    methods.append(
        {
            "method": "PB—ROE",
            "role": "资产回报诊断",
            "basisYear": fy2["year"],
            "basisValue": fy2["endingEquity"],
            "lowParameter": pb_low,
            "highParameter": pb_high,
            "valueLow": fy2["endingEquity"] * pb_low,
            "valueHigh": fy2["endingEquity"] * pb_high,
            "formula": "合理PB＝（可持续ROE－长期增长率）÷（股权成本－长期增长率）",
            "parameterBasis": (
                f"FY2—FY3平均ROE约{normalized_roe:.2%}；股权成本"
                f"{ke_low:.1%}—{ke_high:.1%}，长期增长{g_low:.1%}—{g_high:.1%}。"
            ),
        }
    )
    methods.append(
        {
            "method": "当前市场隐含市盈率",
            "role": "反向诊断",
            "basisYear": fy2["year"],
            "basisValue": fy2["netIncome"],
            "lowParameter": None,
            "highParameter": None,
            "valueLow": market_cap,
            "valueHigh": market_cap,
            "formula": "市场隐含市盈率＝当前市值÷独立模型FY2归母净利润",
            "impliedMultiple": market_cap / fy2["netIncome"]
            if fy2["netIncome"] > 0
            else None,
            "parameterBasis": "市场快照只用于模型冻结后的反向诊断。",
        }
    )
    return methods


def build() -> dict[str, Any]:
    snapshot = _load(SNAPSHOT)
    workbook = _load(WORKBOOK_EXTRACT)
    filing_manifest = _load(FILING_MANIFEST)
    if snapshot["wind"].get("status") != "ok":
        raise ValueError("Wind actual snapshot is required")
    company_ids = _company_ids()
    fx_hk_cny = float(snapshot["fx"]["latest"]["close"])
    workbook_by_company = {
        row["company"]: row for row in workbook["companies"]
    }
    filings_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in filing_manifest.get("rows") or []:
        if row.get("status") != "downloaded":
            continue
        filings_by_ticker.setdefault(str(row["ticker"]), []).append(
            {
                "period": row["period"],
                "title": row["title"],
                "localPath": row["local_path"],
                "sha256": row["sha256"],
            }
        )
    shared_source_artifacts = {
        "structuredFinancialSnapshot": {
            "path": SNAPSHOT.relative_to(ROOT).as_posix(),
            "sha256": _file_sha(SNAPSHOT),
        },
        "workbookExtract": {
            "path": WORKBOOK_EXTRACT.relative_to(ROOT).as_posix(),
            "sha256": _file_sha(WORKBOOK_EXTRACT),
            "sourceWorkbookSha256": workbook["workbook_sha256"],
        },
        "companyFilingManifest": {
            "path": FILING_MANIFEST.relative_to(ROOT).as_posix(),
            "sha256": _file_sha(FILING_MANIFEST),
        },
    }
    companies = []
    for company, config in CONFIG.items():
        ticker = config["ticker"]
        if ticker in snapshot["wind"]["current"]:
            current = snapshot["wind"]["current"][ticker]
            market_cap = float(current["market_cap_cny"])
            current_pb = float(current["pb"]) if current.get("pb") else None
            history = _annual_wind(snapshot, ticker)
            opening_assets = float(
                snapshot["wind"]["annual"]["2025"]["rows"][ticker]["tot_assets"]
            ) / 1e8
        else:
            yf_row = snapshot["yfinance"][ticker]
            info = yf_row["info"]
            market_cap = float(info["marketCap"]) / 1e8 * fx_hk_cny
            current_pb = float(info["priceToBook"]) if info.get("priceToBook") else None
            history = _annual_yf(yf_row)
            opening_assets = (
                _yf_statement_value(yf_row, "balance_sheet", "Total Assets", 2025)
                or max(market_cap * 3, 1)
            )
        opening_equity = (
            market_cap / current_pb
            if current_pb and current_pb > 0
            else max(market_cap, 1)
        )
        forecast = _build_forecast(
            config,
            opening_equity=opening_equity,
            opening_assets=opening_assets,
        )
        valuation = _valuation(config, forecast, market_cap)
        inputs = {
            "segments": config["segments"],
            "opexRatio": config["opexRatio"],
            "otherPretax": config["otherPretax"],
            "taxRate": config["taxRate"],
            "minority": config["minority"],
            "cashConversion": config["cashConversion"],
            "capex": config["capex"],
            "payoutRatio": config["payoutRatio"],
            "openingEquity": opening_equity,
            "openingAssets": opening_assets,
        }
        source_artifacts = {
            **shared_source_artifacts,
            "companyFilings": filings_by_ticker.get(ticker, []),
        }
        companies.append(
            {
                "company": company,
                "companyId": company_ids[company],
                "ticker": ticker,
                "modelType": config["modelType"],
                "marketCapRmb100m": market_cap,
                "marketDate": snapshot["wind"]["trade_date"],
                "history": history,
                "inputs": inputs,
                "forecast": forecast,
                "valuationMethods": valuation,
                "workbookReference": {
                    "available": company in workbook_by_company,
                    "workbookSha256": workbook["workbook_sha256"],
                    "selectedSeriesCount": len(
                        (workbook_by_company.get(company) or {}).get("series") or []
                    ),
                    "role": (
                        "历史季度业务拆分和公式缺陷审计；不把工作簿预测缓存当作当前事实。"
                    ),
                },
                "sourceRefs": [
                    f"company_filing:{ticker}:2025A",
                    f"company_filing:{ticker}:latest_2026",
                    f"structured_actual:{ticker}:{snapshot['wind']['trade_date']}",
                    "battery_quarterly_workbook_extract_v1",
                    "industry_supply_demand_20260728",
                ],
                "limitations": [
                    "出货量和ASP属于研究区间中值，不能解释为公司指引。",
                    "产能只有在具备投产、客户和利用率证据时才进入出货量。",
                    "不同业务的利润率分别建模；集团非电池业务保留用于财务对账。",
                ],
                "sourceArtifacts": source_artifacts,
                "inputHash": _sha(
                    {"modelInputs": inputs, "sourceArtifacts": source_artifacts}
                ),
                "outputHash": _sha({"forecast": forecast, "valuation": valuation}),
            }
        )
    payload = {
        "schema_version": "lithium_battery.independent_models.v1",
        "research_run_ref": "lithium_battery_b_20260728",
        "as_of_date": snapshot["wind"]["trade_date"],
        "sequence_contract": (
            "本文件未读取Wind一致预期或卖方预测；先冻结本文件，外部预测只在单独对账文件中读取。"
        ),
        "model_formula": (
            "电池分部收入＝出货量×ASP×10；集团收入＝各分部收入之和；"
            "归母净利润＝[毛利润－经营费用＋税前其他收益]×（1－税率）－少数股东损益；"
            "自由现金流＝经营现金流－资本开支。"
        ),
        "sourceArtifacts": shared_source_artifacts,
        "companies": companies,
    }
    payload["contentSha256"] = _sha(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "companies": len(payload["companies"]),
                "contentSha256": payload["contentSha256"],
                "fy2026NetIncome": {
                    row["company"]: round(row["forecast"][0]["netIncome"], 2)
                    for row in payload["companies"]
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
