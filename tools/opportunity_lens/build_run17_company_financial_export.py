from __future__ import annotations

"""把Run17八家设备公司冻结模型同步到financial.db公司页。"""

import hashlib
import json
from pathlib import Path
from typing import Any

from tools.financial.opportunity_profile_export import EXPORT_SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "cache" / "research_runs" / "cxmt_dram_equipment_run17" / "workpapers"
MODEL_PATH = RUN_DIR / "listed_supplier_independent_operating_models_frozen.json"
RECON_PATH = RUN_DIR / "listed_supplier_external_reconciliation_and_valuation.json"
OUTPUT = ROOT / "opportunity_lens" / "research_outputs" / "20260802_cxmt_dram_equipment_run17" / "company_financial_profile_export_v1.json"

COMPANY_IDS = {
    "北方华创": 424, "中微公司": 425, "拓荆科技": 426, "盛美上海": 441,
    "华海清科": 427, "精智达": 553, "京仪装备": 676, "长川科技": 435,
}


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _cxmt_boundary(row: dict[str, Any]) -> str:
    if row["company"] in {"北方华创", "中微公司", "长川科技"}:
        return (
            "只有未来取得长鑫具名订单并完成交付验收，才可能形成集团增量收入；"
            "当前公开资料没有形成该闭环，基准模型不计入长鑫收入"
        )
    return str(row["cxmt_sensitivity_only"]["direction"])


def _input(name: str, value: Any, unit: str, period: str, ref: str, method: str, input_type: str = "expert_assumption") -> dict[str, Any]:
    return {
        "input_name": name,
        "value_num": float(value) if isinstance(value, (int, float)) else None,
        "value_text": None if isinstance(value, (int, float)) else str(value),
        "unit": unit,
        "period_or_as_of_date": period,
        "source_ref": ref,
        "input_type": input_type,
        "formula_or_method": method,
        "sensitivity_note": "收入增速、净利率、现金转换、资本开支与估值倍数均按公司分别设置。",
        "limitation_note": "未来数值是研究情景；长鑫客户收入客观不可量化，未进入基准单点。",
    }


def _output(name: str, value: Any, unit: str, period: str, formula: str, conclusion: str, low: float | None = None, high: float | None = None) -> dict[str, Any]:
    is_numeric = isinstance(value, (int, float))
    if value is None:
        value_text = None
        if low is not None and high is not None:
            substitution = f"Run17区间={low}—{high}{unit}"
        else:
            substitution = "本项不输出单点值"
    else:
        value_text = None if is_numeric else str(value)
        substitution = f"Run17基准={value}{unit}"
    return {
        "output_name": name,
        "value_num": float(value) if is_numeric else None,
        "value_text": value_text,
        "range_low": low,
        "range_high": high,
        "unit": unit,
        "period_or_as_of_date": period,
        "formula": formula,
        "substitution": substitution,
        "dependency_group": "Run17长鑫设备供应链独立模型",
        "conclusion": conclusion,
    }


def build() -> dict[str, Any]:
    model = _read(MODEL_PATH)
    recon = _read(RECON_PATH)
    recon_by_name = {row["company"]: row for row in recon["companies"]}
    companies = []
    model_sha = _sha(MODEL_PATH)
    recon_sha = _sha(RECON_PATH)
    for row in model["models"]:
        name = row["company"]
        ticker = row["ticker"]
        market = ticker.split(".")[-1]
        valuation = recon_by_name[name]
        actual = row["actual_2025"]
        assumptions = row["assumptions"]
        cxmt_boundary = _cxmt_boundary(row)
        financial_key = f"ol17:{ticker}:independent_financial_bridge:v4"
        valuation_key = f"ol17:{ticker}:valuation_diagnostic:v4"
        prior_financial_key = f"ol17:{ticker}:independent_financial_bridge:v3"
        prior_valuation_key = f"ol17:{ticker}:valuation_diagnostic:v3"
        inputs = [
            _input("FY2025营业收入", actual["revenue"], "亿元人民币", "2025", f"{model_sha}#models.{ticker}.actual_2025.revenue", "公司2025年实际值作为收入桥起点。", "direct_fact"),
            _input("FY2025归母净利润", actual.get("net_income_parent_db", actual.get("net_income_parent")), "亿元人民币", "2025", f"{model_sha}#models.{ticker}.actual_2025.net_income", "公司2025年实际值作为利润桥起点。", "direct_fact"),
            _input("FY2025经营现金流", actual["operating_cash_flow"], "亿元人民币", "2025", f"{model_sha}#models.{ticker}.actual_2025.ocf", "公司2025年经营现金流。", "direct_fact"),
            _input("长鑫收入边界", cxmt_boundary, "文字", "2026—2028", f"{model_sha}#models.{ticker}.cxmt_sensitivity", "长鑫只作敏感性，不作为基准收入单点。"),
        ]
        outputs = []
        for year in (2026, 2027, 2028):
            forecast = row["forecast"][str(year)]
            outputs.extend([
                _output(f"{year}年营业收入", forecast["revenue"], "亿元人民币", str(year), "上年收入×(1+公司特定收入增速)", "独立集团预测，不是长鑫收入或外部一致预期。"),
                _output(f"{year}年归母净利润", forecast["net_income"], "亿元人民币", str(year), "收入×公司特定归母净利率", "独立集团预测。"),
                _output(f"{year}年经营现金流", forecast["operating_cash_flow"], "亿元人民币", str(year), "归母净利润×现金转换率", "独立集团预测。"),
                _output(f"{year}年资本开支", forecast["capex"], "亿元人民币", str(year), "公司特定资本开支假设", "独立集团预测。"),
                _output(f"{year}年自由现金流", forecast["free_cash_flow"], "亿元人民币", str(year), "经营现金流−资本开支", "独立集团预测。"),
            ])
        reconciliations = []
        primary = valuation["external_reconciliation"]["primary"]
        for idx, year in enumerate((2026, 2027, 2028)):
            for metric, benchmark in (("revenue", primary["revenue"][idx]), ("net_income", primary["net_income"][idx])):
                if benchmark is None:
                    continue
                independent = valuation["independent_forecast"][str(year)][metric]
                reconciliations.append({
                    "benchmark_type": "consensus",
                    "benchmark_source_ref": f"{recon_sha}#companies.{ticker}.external_reconciliation.primary.{year}.{metric}",
                    "metric_name": metric,
                    "period": str(year),
                    "independent_value": independent,
                    "benchmark_value": benchmark,
                    "unit": "亿元人民币",
                    "decomposition": {"difference_pct": round((independent / benchmark - 1) * 100, 2)},
                    "conclusion": f"{name}FY{year}独立{metric}与{primary['name']}（{primary.get('date') or primary.get('as_of') or '日期未标注'}）逐项对账；不合并底层卖方重复计权。",
                })
        val = valuation["valuation"]
        is_ps = val["method"] == "FY1 PS诊断"
        valuation_year = 2027 if str(val["method"]).startswith("FY2") else 2026
        valuation_metric = "revenue" if is_ps else "net_income"
        valuation_inputs = [
            _input(
                f"FY{valuation_year}独立营业收入" if is_ps else f"FY{valuation_year}独立归母净利润",
                valuation["independent_forecast"][str(valuation_year)][valuation_metric],
                "亿元人民币",
                str(valuation_year),
                f"{model_sha}#models.{ticker}.forecast.{valuation_year}.{valuation_metric}",
                "PS估值使用独立FY1收入。" if is_ps else f"PE估值使用独立FY{valuation_year - 2025}利润。",
                "derived_fact",
            ),
            _input("估值倍数下限", val["multiple_range"][0], "倍", valuation["market_as_of"], f"{recon_sha}#companies.{ticker}.valuation.multiple_low", val["multiple_basis"]),
            _input("估值倍数上限", val["multiple_range"][1], "倍", valuation["market_as_of"], f"{recon_sha}#companies.{ticker}.valuation.multiple_high", val["multiple_basis"]),
            _input("当前总市值", valuation["market_cap"], "亿元人民币", valuation["market_as_of"], f"{recon_sha}#companies.{ticker}.market_cap", "市场数据时点值。", "direct_fact"),
        ]
        valuation_outputs = [
            _output("独立估值区间", None, "亿元人民币", valuation["market_as_of"], f"FY{valuation_year - 2025}{'收入' if is_ps else '净利润'}×适用倍数", val["conclusion"], val["value_range"][0], val["value_range"][1]),
            _output("相对当前市值区间", None, "%", valuation["market_as_of"], "估值区间÷当前市值−1", "用于判断估值安全边际，不是收益承诺。", val["relative_to_market_pct"][0], val["relative_to_market_pct"][1]),
        ]
        if is_ps:
            implied = val["market_implied_fy1_revenue_at_multiple_range"]
            valuation_outputs.extend([
                _output("参考市值对应的前瞻PS", val["market_forward_ps"], "倍", valuation["market_as_of"], "参考市值÷FY1独立营业收入", "精智达利润基数和确认波动较大，因此使用PS而不是PE作为主诊断。"),
                _output("参考市值隐含FY1收入区间", None, "亿元人民币", valuation["market_as_of"], "参考市值÷PS倍数区间", "8—12倍PS下需要的FY1收入，区间顺序按低估值倍数对应高收入。", min(implied), max(implied)),
            ])
        else:
            valuation_outputs.append(
                _output("参考市值对应的前瞻PE", val.get("market_forward_pe"), "倍", valuation["market_as_of"], f"参考市值÷FY{valuation_year - 2025}独立归母净利润", "用于反向诊断市场已计入的盈利和估值持续期。")
            )
        companies.append({
            "research_company_id": COMPANY_IDS[name],
            "security": {"canonical_name": name, "ticker": ticker, "market": market, "listing_status": "listed", "reporting_currency": "CNY", "identity_status": "verified"},
            "source_snapshots": [
                {"key": "independent_model", "provider": "internal_model", "source_channel": "internal_calculation", "source_ref": f"opportunity_lens:cxmt_dram_equipment:20260802:independent:{ticker}", "title": f"{ticker} Run17独立FY1—FY3财务模型", "publisher": "Industry Demo独立研究", "as_of_date": "2026-08-02", "fetched_at": None, "content_hash": model_sha, "raw_snapshot_path": _rel(MODEL_PATH), "metadata": {"independent_before_consensus": True, "cxmt_revenue_not_quantified": True}},
                {"key": "external_reconciliation", "provider": "internal_model", "source_channel": "internal_calculation", "source_ref": f"opportunity_lens:cxmt_dram_equipment:20260802:reconciliation:{ticker}", "title": f"{ticker} Run17外部预测与估值对账", "publisher": "Industry Demo独立研究", "as_of_date": "2026-08-02", "fetched_at": None, "content_hash": recon_sha, "raw_snapshot_path": _rel(RECON_PATH), "metadata": {"wind_and_sell_side_kept_separate": True}},
            ],
            "model_runs": [
                {"run_key": financial_key, "supersedes_run_keys": [prior_financial_key], "skill_name": "company_financial_modeling", "model_name": f"Run17 {name}独立FY1—FY3集团财务桥", "model_role": "primary", "forecast_start": "2026", "forecast_end": "2028", "valuation_date": "2026-08-02", "assumptions": {"model_level": row["model_level"], "independent_before_consensus": True, "revenue_growth_pct": assumptions["revenue_growth_pct"], "net_margin_pct": assumptions["net_margin_pct"], "cash_conversion_pct": assumptions["cash_conversion_pct_of_net_income"], "cxmt_rule": cxmt_boundary}, "limitations": "集团模型；长鑫分设备订单、价值量、交付验收和收入份额不可得。", "finalization": "independent", "inputs": inputs, "outputs": outputs, "reconciliations": reconciliations},
                {"run_key": valuation_key, "supersedes_run_keys": [prior_valuation_key], "skill_name": "company_valuation_modeling", "model_name": f"Run17 {name}适用估值与市场隐含诊断", "model_role": "diagnostic", "forecast_start": str(valuation_year), "forecast_end": str(valuation_year), "valuation_date": valuation["market_as_of"], "assumptions": {"method": val["method"], "multiple_basis": val["multiple_basis"]}, "limitations": "估值区间是情景，不做机械多模型平均；市场市值时点并非八家公司严格同日。", "finalization": "reviewed", "inputs": valuation_inputs, "outputs": valuation_outputs, "reconciliations": []},
            ],
            "observations": [],
        })
    return {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "research_run_ref": "opportunity_lens:cxmt_dram_equipment_supply_chain:20260802:run17",
        "as_of_date": "2026-08-02",
        "source_artifacts": [{"path": _rel(MODEL_PATH), "sha256": model_sha}, {"path": _rel(RECON_PATH), "sha256": recon_sha}],
        "companies": companies,
    }


def main() -> int:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "companies": len(payload["companies"]), "model_runs": sum(len(row["model_runs"]) for row in payload["companies"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
