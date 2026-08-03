from __future__ import annotations

"""Build the post-freeze external reconciliation for the copper B-track run.

This script is deliberately offline.  It verifies and reads the already frozen
independent model and the bounded market snapshot, then compares them with a
small, explicitly selected set of company reports published in the latest two
quarters.  It never mutates the frozen model or any SQLite database.
"""

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = (
    ROOT
    / "cache"
    / "copper_research"
    / "models"
    / "copper_independent_models_v2.json"
)
SNAPSHOT_PATH = (
    ROOT / "cache" / "copper_research" / "copper_financial_snapshot.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "cache"
    / "copper_research"
    / "models"
    / "copper_external_reconciliation_v2.json"
)

FY = (2026, 2027, 2028)
HKD_PER_USD = 7.80
FX_USD_CNY = 7.15


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 顶层必须是对象")
    return payload


def _finite(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} 必须是有限数")
    return number


def _median_by_year(
    reports: list[dict[str, Any]], field: str
) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for year in FY:
        values = [
            _finite(report[field][str(year)], f"{report['institution']} {field} {year}")
            for report in reports
            if report.get(field, {}).get(str(year)) is not None
        ]
        result[str(year)] = round(statistics.median(values), 4) if values else None
    return result


def _delta_pct(
    independent: dict[str, float], benchmark: dict[str, float | None]
) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for year in FY:
        key = str(year)
        reference = benchmark.get(key)
        result[key] = (
            round((independent[key] / reference - 1.0) * 100.0, 2)
            if reference not in (None, 0)
            else None
        )
    return result


def _selected_reports() -> dict[str, list[dict[str, Any]]]:
    """Latest-two-quarter reports used only after the independent model freeze."""
    return {
        "紫金矿业": [
            {
                "institution": "UBS",
                "published_date": "2026-07-09",
                "language": "英文",
                "source_ref": (
                    "papers/铜/2026-07-09_ubs equities_紫金矿业_"
                    "紫金矿业（601899）：速评紫金矿业集团- a.pdf"
                ),
                "revenue_bn": {
                    "2026": 535.521,
                    "2027": 620.101,
                    "2028": 664.027,
                },
                "net_income_bn": {
                    "2026": 91.585,
                    "2027": 96.949,
                    "2028": 101.974,
                },
                "target_price": 56.00,
                "target_currency": "CNY",
                "valuation_method": "分部估值",
            },
            {
                "institution": "Morgan Stanley",
                "published_date": "2026-07-10",
                "language": "英文",
                "source_ref": (
                    "papers/铜/2026-07-10_morgan stanley_紫金矿业_"
                    "紫金矿业（02899）：紫金矿业集团_亚太地区; "
                    "2026年上半年中期股息上调.pdf"
                ),
                "revenue_bn": {
                    "2026": 496.668,
                    "2027": 501.578,
                    "2028": 487.034,
                },
                "net_income_bn": {
                    "2026": 80.164,
                    "2027": 81.531,
                    "2028": 77.240,
                },
                "target_price": 55.00,
                "target_currency": "HKD",
                "valuation_method": "DCF，WACC 7.50%，长期收入增长率3.00%",
            },
            {
                "institution": "Citi",
                "published_date": "2026-07-05",
                "language": "英文",
                "source_ref": (
                    "papers/铜/2026-07-05_citi_紫金矿业_"
                    "紫金矿业（601899）：加入上行30天催化剂观察.pdf"
                ),
                "revenue_bn": {},
                "net_income_bn": {
                    "2026": 77.906,
                    "2027": 70.467,
                    "2028": 71.899,
                },
                "target_price": 46.60,
                "target_currency": "CNY",
                "valuation_method": (
                    "DCF，WACC 8.20%，永续增长率3.00%，另加卡莫阿每股价值"
                ),
            },
            {
                "institution": "中金公司",
                "published_date": "2026-07-15",
                "language": "中文",
                "source_ref": (
                    "papers/铜/2026-07-15_中金公司_紫金矿业_"
                    "紫金矿业（601899）：传统矿业巨头价值重塑，"
                    "全球锂业龙头呼之欲出.pdf"
                ),
                "revenue_bn": {
                    "2026": 589.666,
                    "2027": 634.105,
                },
                "net_income_bn": {
                    "2026": 78.838,
                    "2027": 100.421,
                },
                "target_price": 42.00,
                "target_currency": "CNY",
                "valuation_method": "市盈率法",
            },
        ],
        "洛阳钼业": [
            {
                "institution": "Citi",
                "published_date": "2026-06-10",
                "language": "英文",
                "source_ref": (
                    "papers/铜/2026-06-10_citi_洛阳钼业_"
                    "洛阳钼业（603993）：模型更新.pdf"
                ),
                "revenue_bn": {
                    "2026": 228.887,
                    "2027": 226.356,
                    "2028": 234.443,
                },
                "net_income_bn": {
                    "2026": 34.942,
                    "2027": 35.102,
                    "2028": 38.073,
                },
                "target_price": 25.50,
                "target_currency": "CNY",
                "valuation_method": "DCF，WACC 11.00%",
            },
            {
                "institution": "Morgan Stanley",
                "published_date": "2026-07-10",
                "language": "英文",
                "source_ref": (
                    "papers/铜/2026-07-10_morgan stanley_洛阳钼业_"
                    "洛阳钼业（03993）：2026年第二季度符合预期；"
                    "季度铜产量创历史新高.pdf"
                ),
                "revenue_bn": {},
                "net_income_bn": {
                    "2026": 31.606,
                    "2027": 33.490,
                    "2028": 35.140,
                },
                "target_price": 26.30,
                "target_currency": "HKD",
                "valuation_method": "DCF，WACC 10.70%，长期收入增长率2.00%",
            },
            {
                "institution": "UBS",
                "published_date": "2026-07-12",
                "language": "英文",
                "source_ref": (
                    "papers/铜/2026-07-12_ubs equities_洛阳钼业_"
                    "洛阳钼业（603993）：速评：cmoc.pdf"
                ),
                "revenue_bn": {
                    "2026": 337.316,
                    "2027": 351.580,
                    "2028": 361.228,
                },
                "net_income_bn": {
                    "2026": 32.714,
                    "2027": 34.049,
                    "2028": 35.128,
                },
                "target_price": 30.60,
                "target_currency": "CNY",
                "valuation_method": "市盈率法",
            },
            {
                "institution": "BofA Global Research",
                "published_date": "2026-07-11",
                "language": "英文",
                "source_ref": (
                    "papers/铜/2026-07-11_bofa global research_洛阳钼业_"
                    "洛阳钼业（03993）：尽管存在硫磺成本担忧，"
                    "第二季度盈利仍超预期；铜价与销量实现增长.pdf"
                ),
                "revenue_bn": {},
                "net_income_bn": {
                    "2026": 28.509,
                    "2027": 34.506,
                    "2028": 36.629,
                },
                "target_price": None,
                "target_currency": "HKD",
                "valuation_method": "综合盈利与现金流框架",
            },
        ],
        "五矿资源": [
            {
                "institution": "J.P. Morgan",
                "published_date": "2026-06-10",
                "language": "英文",
                "source_ref": (
                    "papers/铜/2026-06-10_jpmorgan_五矿资源_"
                    "五矿资源（01208）：mmg；专注铜业务，"
                    "具备强劲增长态势与去杠杆逻辑；首次覆盖给予增持评级.pdf"
                ),
                "revenue_bn": {
                    "2026": 8.888,
                    "2027": 9.042,
                    "2028": 9.768,
                },
                "net_income_bn": {
                    "2026": 1.611,
                    "2027": 1.650,
                    "2028": 1.822,
                },
                "ebitda_bn": {
                    "2026": 5.237,
                    "2027": 5.307,
                    "2028": 5.719,
                },
                "target_price": 13.00,
                "target_currency": "HKD",
                "valuation_method": "DCF，WACC 12.40%，永续增长率2.00%",
            },
            {
                "institution": "Morgan Stanley",
                "published_date": "2026-07-21",
                "language": "英文",
                "source_ref": (
                    "papers/铜/2026-07-21_morgan stanley_五矿资源_"
                    "五矿资源（01208）：2026年第二季度生产按计划推进；"
                    "各矿山下调c1成本指引.pdf"
                ),
                "revenue_bn": {
                    "2026": 8.892,
                    "2027": 8.518,
                    "2028": 8.526,
                },
                "net_income_bn": {},
                "ebitda_bn": {
                    "2026": 5.700,
                    "2027": 5.310,
                    "2028": 5.249,
                },
                "eps_usd": {
                    "2026": 0.12,
                    "2027": 0.12,
                    "2028": 0.12,
                },
                "target_price": 11.70,
                "target_currency": "HKD",
                "valuation_method": "DCF，股权成本约10.00%，长期增长率2.00%",
            },
            {
                "institution": "Jefferies",
                "published_date": "2026-07-22",
                "language": "英文",
                "source_ref": (
                    "papers/铜/2026-07-22_jefferies_五矿资源_"
                    "五矿资源（01208）：成本趋于下降，生产指引保持不变.pdf"
                ),
                "revenue_bn": {},
                "net_income_bn": {},
                "ebitda_bn": {
                    "2026": 5.6106,
                    "2027": 5.3845,
                    "2028": 6.073,
                },
                "eps_usd": {
                    "2026": 0.12,
                    "2027": 0.11,
                },
                "target_price": 10.00,
                "target_currency": "HKD",
                "valuation_method": "矿山净现值法",
            },
            {
                "institution": "Citi",
                "published_date": "2026-07-21",
                "language": "英文",
                "source_ref": (
                    "papers/铜/2026-07-21_citi_五矿资源_"
                    "五矿资源（01208）：mmg（1208.hk）；"
                    "2026年第二季度运营表现强劲，las bambas铜矿c1成本超预期，"
                    "维持首选评级.pdf"
                ),
                "revenue_bn": {},
                "net_income_bn": {},
                "target_price": 11.20,
                "target_currency": "HKD",
                "valuation_method": "产量、成本与净现值综合",
            },
        ],
    }


def _independent_series(
    company: dict[str, Any], field: str
) -> dict[str, float]:
    rows = company["scenarios"]["基准情景"]
    return {
        str(row["year"]): _finite(row[field], f"{company['company']} {field}")
        for row in rows
    }


def _wind_consensus(
    snapshot: dict[str, Any], ticker: str
) -> dict[str, dict[str, float]]:
    row = snapshot["wind"]["consensus_fy1_fy3"]["rows"][ticker]
    return {
        "revenue_bn": {
            str(year): round(
                _finite(row[f"west_sales_fy{offset}"], "Wind收入") / 1e9, 4
            )
            for offset, year in enumerate(FY, start=1)
        },
        "net_income_bn": {
            str(year): round(
                _finite(row[f"west_netprofit_fy{offset}"], "Wind净利润") / 1e9,
                4,
            )
            for offset, year in enumerate(FY, start=1)
        },
        "eps": {
            str(year): _finite(row[f"west_eps_fy{offset}"], "Wind EPS")
            for offset, year in enumerate(FY, start=1)
        },
        "roe_pct": {
            str(year): _finite(row[f"west_avgroe_fy{offset}"], "Wind ROE")
            for offset, year in enumerate(FY, start=1)
        },
    }


def _workbook_style_resource_diagnostic(
    *,
    company: dict[str, Any],
    current_market_cap: float,
) -> dict[str, Any]:
    """Apply the workbook's decomposition only after the independent freeze.

    The result diagnoses what the current market price implies.  It is not a
    fourth independent target-value method.
    """
    company_name = company["company"]
    bridge = company["valuation"]["workbook_style_commodity_bridge"]
    price_grid = bridge["price_sensitivity"]
    base_row = next(
        row for row in price_grid if row["copper_price_usd_t"] == 11500.0
    )

    if company_name in {"紫金矿业", "洛阳钼业"}:
        residual = _finite(
            base_row["non_copper_corporate_residual_rmb_bn"],
            f"{company_name}非铜及公司层残余",
        )
        attributable_copper_kt = _finite(
            bridge.get(
                "attributable_copper_kt",
                bridge.get("attributable_copper_kt_proxy"),
            ),
            f"{company_name}权益铜产量",
        )
        residual_multiple = (
            (10.0, 13.0) if company_name == "紫金矿业" else (8.0, 11.0)
        )
        other_value_low = residual * residual_multiple[0]
        other_value_high = residual * residual_multiple[1]
        resource_value_low = max(0.0, current_market_cap - other_value_high)
        resource_value_high = max(0.0, current_market_cap - other_value_low)
        base_resource_profit = _finite(
            base_row["copper_after_tax_profit_proxy_rmb_bn"],
            f"{company_name}权益铜税后利润代理",
        )
        rows = []
        for row in price_grid:
            resource_profit = _finite(
                row["copper_after_tax_profit_proxy_rmb_bn"],
                f"{company_name}价格矩阵资源利润",
            )
            total_profit = _finite(
                row["attributable_net_income_rmb_bn"],
                f"{company_name}价格矩阵归母利润",
            )
            rows.append(
                {
                    "copper_price_usd_t": row["copper_price_usd_t"],
                    "resource_profit_proxy_rmb_bn": resource_profit,
                    "group_net_income_rmb_bn": total_profit,
                    "current_group_implied_pe": (
                        round(current_market_cap / total_profit, 2)
                        if total_profit > 0
                        else None
                    ),
                    "resource_implied_pe_low": (
                        round(resource_value_low / resource_profit, 2)
                        if resource_profit > 0
                        else None
                    ),
                    "resource_implied_pe_high": (
                        round(resource_value_high / resource_profit, 2)
                        if resource_profit > 0
                        else None
                    ),
                }
            )
        return {
            "role": "当前市场隐含诊断，不是独立目标价值",
            "currency": "CNY",
            "year": 2027,
            "current_market_cap_bn": round(current_market_cap, 3),
            "attributable_copper_kt": round(attributable_copper_kt, 1),
            "base_copper_price_usd_t": 11500.0,
            "base_resource_profit_proxy_bn": round(base_resource_profit, 3),
            "non_copper_corporate_residual_profit_bn": round(residual, 3),
            "residual_profit_multiple_range": list(residual_multiple),
            "non_copper_corporate_value_range_bn": [
                round(other_value_low, 3),
                round(other_value_high, 3),
            ],
            "resource_implied_equity_value_range_bn": [
                round(resource_value_low, 3),
                round(resource_value_high, 3),
            ],
            "resource_implied_pe_range": [
                round(resource_value_low / base_resource_profit, 2),
                round(resource_value_high / base_resource_profit, 2),
            ],
            "unit_resource_value_wan_rmb_per_attributable_t_range": [
                round(resource_value_low / attributable_copper_kt * 100.0, 2),
                round(resource_value_high / attributable_copper_kt * 100.0, 2),
            ],
            "price_sensitivity": rows,
            "formula": (
                "非铜及公司层价值＝2027年非铜及公司层残余利润×适用倍数；"
                "资源业务隐含市值＝当前总市值－非铜及公司层价值；"
                "资源业务隐含PE＝资源业务隐含市值÷权益铜税后利润代理；"
                "单位权益产量市值＝资源业务隐含市值÷2027年权益铜产量。"
            ),
            "limitations": (
                "非铜及公司层残余是合并利润桥的剩余项，不等于经审计分部利润；"
                "其倍数是估值假设，因此这里只用于识别当前价格押注，不加入独立"
                "估值区间。"
            ),
        }

    attributable_copper_kt = _finite(
        bridge["attributable_copper_kt"], "五矿资源权益铜产量"
    )
    rows = []
    for row in price_grid:
        total_profit = _finite(
            row["attributable_net_income_usd_bn"], "五矿资源价格矩阵归母利润"
        )
        rows.append(
            {
                "copper_price_usd_t": row["copper_price_usd_t"],
                "copper_after_tax_profit_proxy_usd_bn": row[
                    "copper_after_tax_profit_proxy_usd_bn"
                ],
                "group_net_income_usd_bn": total_profit,
                "current_group_implied_pe": (
                    round(current_market_cap / total_profit, 2)
                    if total_profit > 0
                    else None
                ),
            }
        )
    base_group_profit = _finite(
        base_row["attributable_net_income_usd_bn"], "五矿资源基准归母利润"
    )
    return {
        "role": "当前市场隐含诊断，不是独立目标价值",
        "currency": "USD",
        "year": 2027,
        "current_market_cap_usd_bn_proxy": round(current_market_cap, 3),
        "attributable_copper_kt": round(attributable_copper_kt, 1),
        "base_copper_price_usd_t": 11500.0,
        "base_group_net_income_usd_bn": round(base_group_profit, 4),
        "current_group_implied_pe": round(
            current_market_cap / base_group_profit, 2
        ),
        "unit_group_value_wan_rmb_per_attributable_t": round(
            current_market_cap
            / attributable_copper_kt
            * FX_USD_CNY
            * 100.0,
            2,
        ),
        "price_sensitivity": rows,
        "formula": (
            "集团隐含PE＝当前美元折算市值÷2027年归母利润；"
            "单位权益产量市值＝当前美元折算市值×美元兑人民币÷2027年权益铜产量。"
        ),
        "limitations": (
            "五矿资源是资源主导集团，权益铜税后利润代理高于集团归母利润，差额"
            "主要包含利息、总部费用、少数股东和其他金属，不能被资本化成正的"
            "其他业务价值；因此不伪造资源业务SOTP，只保留集团与单位产量诊断。"
        ),
    }


def build() -> dict[str, Any]:
    model = _read_json(MODEL_PATH)
    snapshot = _read_json(SNAPSHOT_PATH)
    reports = _selected_reports()
    model_companies = {
        company["company"]: company for company in model["outputs"]["companies"]
    }

    if model["output_sha256"] != _sha256(model["outputs"]):
        raise ValueError("冻结模型输出哈希不匹配，停止外部对账")
    if snapshot.get("content_sha256") != _sha256(
        {key: value for key, value in snapshot.items() if key != "content_sha256"}
    ):
        raise ValueError("市场快照哈希不匹配，停止外部对账")

    result: dict[str, Any] = {}
    for company_name, ticker, field in (
        ("紫金矿业", "601899.SH", "revenue_rmb_bn"),
        ("洛阳钼业", "603993.SH", "revenue_rmb_bn"),
        ("五矿资源", "1208.HK", "revenue_usd_bn"),
    ):
        company = model_companies[company_name]
        independent_revenue = _independent_series(company, field)
        independent_income = _independent_series(
            company,
            "attributable_net_income_rmb_bn"
            if company_name != "五矿资源"
            else "attributable_net_income_usd_bn",
        )
        seller_revenue = _median_by_year(reports[company_name], "revenue_bn")
        seller_income = _median_by_year(reports[company_name], "net_income_bn")
        reconciliation: dict[str, Any] = {
            "ticker": ticker,
            "currency": company["currency"],
            "independent_base": {
                "revenue_bn": independent_revenue,
                "net_income_bn": independent_income,
            },
            "selected_reports": reports[company_name],
            "seller_median": {
                "revenue_bn": seller_revenue,
                "net_income_bn": seller_income,
            },
            "independent_vs_seller_median_pct": {
                "revenue": _delta_pct(independent_revenue, seller_revenue),
                "net_income": _delta_pct(independent_income, seller_income),
            },
        }
        if company_name != "五矿资源":
            wind = _wind_consensus(snapshot, ticker)
            current = snapshot["wind"]["current"][ticker]
            reconciliation["wind_consensus"] = wind
            reconciliation["independent_vs_wind_pct"] = {
                "revenue": _delta_pct(independent_revenue, wind["revenue_bn"]),
                "net_income": _delta_pct(
                    independent_income, wind["net_income_bn"]
                ),
            }
            reconciliation["current_market"] = {
                "as_of": current["trade_date"],
                "price": current["price"],
                "market_cap_bn": round(current["market_cap_cny"] / 10.0, 4),
                "market_cap_currency": "CNY",
                "pe_ttm": current["pe_ttm"],
                "pe_forward": current["pe_forward"],
                "pb": current["pb"],
                "roe_pct": current["roe"],
                "roa_pct": current["roa"],
            }
        else:
            info = snapshot["yfinance"]["info"]
            market_cap_hkd_bn = _finite(info["marketCap"], "五矿资源市值") / 1e9
            reconciliation["current_market"] = {
                "as_of": snapshot["accessed_at_utc"],
                "price_hkd": info["currentPrice"],
                "market_cap_hkd_bn": round(market_cap_hkd_bn, 4),
                "market_cap_usd_bn_proxy": round(
                    market_cap_hkd_bn / HKD_PER_USD, 4
                ),
                "hkd_per_usd_assumption": HKD_PER_USD,
                "pe_ttm": info["trailingPE"],
                "pe_forward": info["forwardPE"],
                "pb": info["priceToBook"],
                "roe_pct": round(_finite(info["returnOnEquity"], "五矿资源ROE") * 100, 2),
                "roa_pct": round(_finite(info["returnOnAssets"], "五矿资源ROA") * 100, 2),
                "excluded_provider_fields": {
                    "price_to_sales": "市值为港元、收入为美元，供应商直接倍数存在币种错配",
                    "enterprise_to_ebitda": "企业价值为港元、EBITDA为美元，供应商直接倍数存在币种错配",
                },
            }

        valuation = company["valuation"]
        if company_name != "五矿资源":
            current_cap = reconciliation["current_market"]["market_cap_bn"]
            pe = valuation["normalized_pe"]
            pb = valuation["pb_roe"]
            dcf = valuation["fcfe_dcf"]
            reconciliation["valuation_vs_market"] = {
                "current_market_cap_bn": current_cap,
                "normalized_pe_range_bn": [
                    pe["equity_value_low_rmb_bn"],
                    pe["equity_value_high_rmb_bn"],
                ],
                "pb_roe_range_bn": [
                    pb["equity_value_low_rmb_bn"],
                    pb["equity_value_high_rmb_bn"],
                ],
                "fcfe_dcf_range_bn": [
                    dcf["equity_value_low"],
                    dcf["equity_value_high"],
                ],
            }
        else:
            current_cap = reconciliation["current_market"]["market_cap_usd_bn_proxy"]
            pe = valuation["normalized_pe"]
            pb = valuation["pb_roe"]
            dcf = valuation["fcfe_dcf"]
            reconciliation["valuation_vs_market"] = {
                "current_market_cap_usd_bn_proxy": current_cap,
                "normalized_pe_range_usd_bn": [
                    pe["equity_value_low_usd_bn"],
                    pe["equity_value_high_usd_bn"],
                ],
                "pb_roe_range_usd_bn": [
                    pb["equity_value_low_usd_bn"],
                    pb["equity_value_high_usd_bn"],
                ],
                "fcfe_dcf_range_usd_bn": [
                    dcf["equity_value_low"],
                    dcf["equity_value_high"],
                ],
                "seller_target_price_hkd": {
                    report["institution"]: report["target_price"]
                    for report in reports[company_name]
                    if report["target_price"] is not None
                    and report["target_currency"] == "HKD"
                },
            }
        reconciliation["workbook_style_resource_diagnostic"] = (
            _workbook_style_resource_diagnostic(
                company=company,
                current_market_cap=current_cap,
            )
        )
        result[company_name] = reconciliation

    result["紫金矿业"]["interpretation"] = [
        "独立模型2026年利润接近Wind一致预期，但低于UBS的高金铜价与扩张假设；2027年开始低于Wind，核心分歧是铜金价格正常化、卡莫阿恢复和锂业务爬坡。",
        "正常化市盈率下限较当前市值高约4.75%，DCF下限较当前市值低约1.41%，且当前市值位于PB—ROE区间；只能判断存在有限余量，不能再写成三种方法均显著低估。",
        "按参考工作簿的资源拆分框架，当前价格还可被解释为非铜及公司层残余与权益铜资源价值的组合；该结果依赖残余利润倍数，只用于检查市场押注，不替代三种独立估值。",
    ]
    result["洛阳钼业"]["interpretation"] = [
        "独立模型FY1利润接近Wind和机构中位数，FY2—FY3略高，主要来自KFM二期与较高铜产量兑现；硫磺、电力、钴配额和刚果（金）税费是向下修正变量。",
        "机构收入差异远大于利润差异，主要是IXM贸易收入采用总额或经营口径不同；因此利润和现金流比营业收入更适合横向对账。",
        "当前市值位于正常化PE区间上部，但已高于PB—ROE和DCF上限；估值需要利润持续、现金转换与KFM二期同时兑现。",
        "资源拆分诊断显示当前市值的大部分仍由铜钴资源利润解释；但TFM与KFM成本、权益和税费公开口径不足，单位权益产量市值只能作为同口径近似。",
    ]
    result["五矿资源"]["interpretation"] = [
        "独立模型利润明显低于J.P. Morgan，原因是对2027年铜价、少数股东分配和税后转化更保守；Morgan Stanley与Jefferies只披露了四舍五入EPS，不把它伪装成精确归母利润。",
        "当前折算美元市值高于独立模型三种方法的上限，但卖方目标价仍普遍高于现价；分歧本质是高铜价持续时间、Las Bambas成本、Khoemacau爬坡和去杠杆速度。",
        "工作簿式拆分在五矿资源上不能机械成立：权益铜利润代理与集团归母利润之间存在负残余，因此只展示集团隐含PE和单位权益产量市值，不虚构正的其他业务价值。",
    ]

    payload: dict[str, Any] = {
        "schema_version": "copper.external_reconciliation.v2",
        "research_run_ref": "copper_b_20260726_workbook_revision",
        "as_of_date": "2026-07-26",
        "frozen_model_path": str(MODEL_PATH.relative_to(ROOT)).replace("\\", "/"),
        "frozen_model_input_sha256": model["input_sha256"],
        "frozen_model_output_sha256": model["output_sha256"],
        "financial_snapshot_path": str(SNAPSHOT_PATH.relative_to(ROOT)).replace(
            "\\", "/"
        ),
        "financial_snapshot_sha256": snapshot["content_sha256"],
        "selection_policy": (
            "公司财务建模只使用2026-04-01以后、即最近两个季度发布的公司报告；"
            "中文与英文报告同级，A/H同一机构同一预测只计一次。"
        ),
        "companies": result,
        "limitations": [
            "卖方中位数只描述所选近期报告，不是全市场抽样统计。",
            "不同机构对贸易收入、少数股东、商品价格和目标价期限的口径不同，不能只比较单一数字。",
            "资源业务隐含估值来自当前市值减去残余业务估值，是市场诊断而非新的独立目标价；残余利润和倍数均须单独解释。",
            "外部对账不修改冻结模型；如发现事实错误，必须另建带变更原因的新版本。",
        ],
    }
    payload["content_sha256"] = _sha256(payload)
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
                "output": str(args.output.resolve()),
                "sha256": payload["content_sha256"],
                "companies": list(payload["companies"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
