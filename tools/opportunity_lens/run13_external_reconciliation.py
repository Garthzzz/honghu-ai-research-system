from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COMPANIES = ("innolight", "eoptolink", "luxshare", "byd")
PAYOUT_ASSUMPTIONS = {
    "innolight": 0.10,
    "eoptolink": 0.10,
    "luxshare": 0.10,
    "byd": 0.30,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _wind_market(security: dict[str, Any]) -> dict[str, Any]:
    wind = security.get("wind") or {}
    snapshot = wind.get("snapshot") if wind.get("status") == "ok" else None
    if not snapshot:
        raise ValueError(f"Run13 v4需要成功的Wind小型市场快照：{security.get('identity')}")
    return {
        "as_of": snapshot["trade_date"],
        "price_cny": snapshot["price"],
        "market_cap_cny_100m": snapshot["market_cap_cny"],
        "pe_ttm": snapshot["pe_ttm"],
        "pe_forward_12m": snapshot["pe_forward"],
        "pb": snapshot["pb"],
        "ps_ttm": snapshot["ps_ttm"],
        "ev_ebitda": snapshot["ev_ebitda"],
        "roe_ttm_pct": snapshot["roe"],
        "roa_ttm_pct": snapshot["roa"],
        "eps_ttm_cny": snapshot["eps_ttm"],
        "bps_latest_cny": snapshot["bps_mrq"],
    }


def _wind_consensus(snapshot: dict[str, Any], ticker: str) -> dict[str, Any]:
    rows = snapshot["wind_consensus_fy1_fy3"]["rows"]
    row = rows.get(ticker)
    if not row:
        raise ValueError(f"Wind一致预期缺少{ticker}")
    years: list[dict[str, float | int]] = []
    for horizon in (1, 2, 3):
        sales = row.get(f"west_sales_fy{horizon}")
        net_profit = row.get(f"west_netprofit_fy{horizon}")
        eps = row.get(f"west_eps_fy{horizon}")
        roe = row.get(f"west_avgroe_fy{horizon}")
        if None in (sales, net_profit, eps, roe):
            raise ValueError(f"Wind一致预期{ticker} FY{horizon}存在空字段")
        years.append(
            {
                "fiscal_year": 2025 + horizon,
                "revenue_cny_100m": _round(float(sales) / 1e8),
                "parent_net_income_cny_100m": _round(float(net_profit) / 1e8),
                "eps_cny": _round(float(eps), 4),
                "average_roe_pct": _round(float(roe)),
            }
        )
    return {
        "as_of": "2026-07-22",
        "source": "Wind FY1—FY3一致预期",
        "years": years,
    }


def _wind_actual(snapshot: dict[str, Any], ticker: str) -> dict[str, Any]:
    row = snapshot["wind_historical_fy2025"]["rows"].get(ticker)
    if not row:
        raise ValueError(f"Wind 2025财务缺少{ticker}")
    money_fields = (
        "oper_rev",
        "np_belongto_parcomsh",
        "net_cash_flows_oper_act",
        "cash_pay_acq_const_fiolta",
        "tot_assets",
        "tot_equity",
    )
    result = {
        field: (_round(float(row[field]) / 1e8) if row.get(field) is not None else None)
        for field in money_fields
    }
    result.update(
        {
            "roe_pct": row.get("roe"),
            "roa_pct": row.get("roa2"),
            "gross_margin_pct": row.get("grossprofitmargin"),
            "net_margin_pct": row.get("netprofitmargin"),
        }
    )
    return result


def _pb_return_diagnostic(
    company: str,
    market: dict[str, Any],
    consensus: dict[str, Any],
    actual: dict[str, Any],
) -> dict[str, Any]:
    market_cap = float(market["market_cap_cny_100m"])
    current_pb = float(market["pb"])
    implied_current_book = market_cap / current_pb
    payout = PAYOUT_ASSUMPTIONS[company]
    running_book = implied_current_book
    bridge = []
    for forecast in consensus["years"]:
        running_book += float(forecast["parent_net_income_cny_100m"]) * (1 - payout)
        bridge.append(
            {
                "fiscal_year": forecast["fiscal_year"],
                "forecast_parent_net_income_cny_100m": forecast["parent_net_income_cny_100m"],
                "forecast_average_roe_pct": forecast["average_roe_pct"],
                "retention_assumption_pct": _round((1 - payout) * 100),
                "bridged_parent_book_value_cny_100m": _round(running_book),
                "static_market_cap_pb": _round(market_cap / running_book),
            }
        )
    multiplier = (
        float(actual["tot_assets"]) / float(actual["tot_equity"])
        if actual.get("tot_assets") and actual.get("tot_equity")
        else None
    )
    return {
        "current": {
            "pb": _round(current_pb),
            "roe_ttm_pct": _round(market["roe_ttm_pct"]),
            "roa_ttm_pct": _round(market["roa_ttm_pct"]),
            "equity_multiplier_2025": _round(multiplier) if multiplier else None,
        },
        "static_market_cap_retained_earnings_bridge": bridge,
        "bridge_boundary": (
            "未来PB不是Wind直接预测。这里固定2026年7月22日市值，只把Wind归母净利润"
            "按假设留存率累加到当前PB隐含净资产；不含股权融资、回购、汇兑、其他综合收益、"
            "少数股东和资产重估，因此只用于判断当前PB需要怎样的ROE与留存路径。"
        ),
        "roa_boundary": (
            "Wind当前代理没有FY1—FY3 ROA。正文只用TTM ROA和2025权益乘数判断ROE来自"
            "资产效率还是杠杆，不把缺少资产负债桥的ROA外推伪装成供应商预测。"
        ),
    }


def _valuation_reconciliation(
    company: str,
    model: dict[str, Any],
    market: dict[str, Any],
) -> dict[str, Any]:
    rows = model["baseline"][company]
    market_cap = float(market["market_cap_cny_100m"])
    center = model["independent_valuation_diagnostics"][company]["cash_flow_sensitivity_grid"][
        "回报要求11%__长期增长3%"
    ]["cash_flow_value_before_balance_sheet_bridge_cny_100m"]
    required_return = 0.11
    terminal_exponent = 5.44
    remaining_2026_fraction = 162 / 365
    exponents = [0.44, 1.44, 2.44, 3.44, 4.44, 5.44]
    pv_explicit_cash_flow = sum(
        float(row["free_cash_flow_cny_100m"])
        * (remaining_2026_fraction if index == 0 else 1.0)
        / ((1 + required_return) ** exponents[index])
        for index, row in enumerate(rows)
    )
    required_terminal_value_2031 = (
        market_cap - pv_explicit_cash_flow
    ) * ((1 + required_return) ** terminal_exponent)
    return {
        "market_implied_forward_pe_on_independent_model": {
            str(row["year"]): _round(market_cap / float(row["net_income_cny_100m"]))
            for row in rows
        },
        "discounted_reverse_terminal_pe": {
            "valuation_date": "2026-07-22",
            "required_return_pct": 11.0,
            "years_to_terminal": terminal_exponent,
            "pv_explicit_2026_2031_fcf_cny_100m": _round(pv_explicit_cash_flow),
            "required_2031_net_income_cny_100m": {
                "25倍": _round(required_terminal_value_2031 / 25),
                "35倍": _round(required_terminal_value_2031 / 35),
                "45倍": _round(required_terminal_value_2031 / 45),
            },
            "terminal_pe_required_for_independent_2031_net_income": _round(
                required_terminal_value_2031 / float(rows[-1]["net_income_cny_100m"])
            ),
        },
        "cash_flow_sensitivity_value_cny_100m": center,
        "market_cap_divided_by_cash_flow_sensitivity": _round(market_cap / float(center)),
        "method_boundary": (
            "市盈率用于解释市场要求，现金流结果因三表和净现金桥不完整只作情景比较；"
            "PB—ROE/PB—ROA另作资本回报诊断，不与PE或现金流机械平均。"
        ),
    }


def build(model_path: Path, snapshot_path: Path) -> dict[str, Any]:
    model = json.loads(model_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if model.get("external_consensus_inputs_present") is not False:
        raise ValueError("独立模型必须明确不含外部一致预期输入")
    model_time = datetime.fromisoformat(str(model["generated_at_utc"]))
    snapshot_time = datetime.fromisoformat(str(snapshot["accessed_at_utc"]))
    if model_time.tzinfo is None or snapshot_time.tzinfo is None or model_time >= snapshot_time:
        raise ValueError("顺序控制失败：独立模型必须早于外部财务与一致预期快照")

    external: dict[str, Any] = {}
    comparison: dict[str, Any] = {}
    valuation: dict[str, Any] = {}
    pb_return: dict[str, Any] = {}
    for company in COMPANIES:
        identity = snapshot["securities"][company]["identity"]
        ticker = identity["ts_code"]
        market = _wind_market(snapshot["securities"][company])
        consensus = _wind_consensus(snapshot, ticker)
        actual = _wind_actual(snapshot, ticker)
        external[company] = {
            "identity": identity,
            "market": market,
            "actual_fy2025": actual,
            "consensus": consensus,
        }
        pb_return[company] = _pb_return_diagnostic(company, market, consensus, actual)

        if company in model["baseline"]:
            independent_rows = model["baseline"][company][:3]
        else:
            group = model["entrant_group_baseline_non_external_fact"][company]
            independent_rows = [
                {
                    "year": 2026 + index,
                    "revenue_cny_100m": group["revenue_cny_100m"][index],
                    "net_income_cny_100m": group["parent_net_income_cny_100m"][index],
                }
                for index in range(3)
            ]
        comparison[company] = []
        for independent, benchmark in zip(independent_rows, consensus["years"]):
            comparison[company].append(
                {
                    "fiscal_year": benchmark["fiscal_year"],
                    "independent_revenue_cny_100m": independent["revenue_cny_100m"],
                    "wind_consensus_revenue_cny_100m": benchmark["revenue_cny_100m"],
                    "revenue_difference_pct": _round(
                        (
                            float(independent["revenue_cny_100m"])
                            / float(benchmark["revenue_cny_100m"])
                            - 1
                        )
                        * 100
                    ),
                    "independent_parent_net_income_cny_100m": independent["net_income_cny_100m"],
                    "wind_consensus_parent_net_income_cny_100m": benchmark["parent_net_income_cny_100m"],
                    "net_income_difference_pct": _round(
                        (
                            float(independent["net_income_cny_100m"])
                            / float(benchmark["parent_net_income_cny_100m"])
                            - 1
                        )
                        * 100
                    ),
                    "static_market_cap_consensus_pe": _round(
                        float(market["market_cap_cny_100m"])
                        / float(benchmark["parent_net_income_cny_100m"])
                    ),
                }
            )
        if company in model["baseline"]:
            valuation[company] = _valuation_reconciliation(company, model, market)

    return {
        "reconciliation_version": "run13.external_reconciliation.v4",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "sequence_control": {
            "status": "PASS",
            "method": (
                "先冻结四家公司不含市场价格和一致预期的独立经营路径，再读取四证券、"
                "窄字段的Wind 2025财务、当前估值和FY1—FY3一致预期，最后对账；"
                "外部数据不回写独立基线。"
            ),
            "independent_model_generated_at_utc": model["generated_at_utc"],
            "external_snapshot_accessed_at_utc": snapshot["accessed_at_utc"],
        },
        "independent_model_file_sha256": _sha256(model_path),
        "raw_financial_snapshot_file_sha256": _sha256(snapshot_path),
        "raw_snapshot_scope": snapshot["scope_note"],
        "external_benchmarks": external,
        "comparison": comparison,
        "pb_roe_pb_roa_diagnostics": pb_return,
        "incumbent_valuation_reconciliation": valuation,
        "difference_diagnosis": [
            "中际旭创和新易盛的Wind一致预期显著高于独立保守路径，差异集中在1.6T放量、产能、利润率和高回报持续时间。",
            "立讯精密与比亚迪的集团盈利主要由原有业务决定；光模块即使成功，也必须先穿过分部规模、净利率、营运资金和非全资归属，不能把项目收入直接等同集团归母利润。",
            "PB—ROE/PB—ROA显示两家光模块龙头的高PB主要依赖极高资产回报持续，而立讯和比亚迪的ROE受更高权益乘数和低利润率业务结构影响；四家公司不能用同一PB阈值横比。",
            "未来ROA和未来PB不是当前Wind代理直接预测字段；留存收益桥和资产回报诊断均明确标注为内部计算，不伪装成供应商一致预期。",
        ],
        "change_log": [],
        "decision": (
            "保留独立模型，采用Wind作为FY1—FY3外部对账主源；正文同时列明独立预测、"
            "Wind一致预期、静态市值下PE/PB诊断及其口径边界。"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build(args.model, args.snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "model_sha256": payload["independent_model_file_sha256"],
                "snapshot_sha256": payload["raw_financial_snapshot_file_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
