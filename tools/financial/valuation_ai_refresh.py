from __future__ import annotations

"""Create monthly AI valuation candidates from the platform's frozen models.

The task does not invent a fixed PE shortcut.  It reads the same reviewed
multi-method model ledger used by company detail pages, freezes the selected
inputs/outputs and provenance, and appends candidates without publishing them.
"""

import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    load_postgres_runtime_catalog,
)
from tools.financial.read_models import company_bundle
from tools.financial.valuation_tracker import (
    ValuationTrackerRepository,
    canonical_json,
)


MODEL_NAME = "honghu-existing-multi-method-valuation-v1"
PROMPT_CONTRACT = """按公司详情页现有财务与估值体系复核：经营、盈利、现金流、股东回报、行业与市场变化；仅使用已冻结且有来源的模型输出，至少两种适用估值方法；以各方法上界的中位数作为候选市值天花板。不得用统一固定PE，不得覆盖人工版本；证据不足时不生成。"""
PROMPT_SHA256 = hashlib.sha256(PROMPT_CONTRACT.encode("utf-8")).hexdigest()


def _repo(path: Path) -> ValuationTrackerRepository:
    catalog = load_postgres_runtime_catalog(path)
    return ValuationTrackerRepository(
        build_catalog_connection_factory(catalog, role="reader"),
        build_catalog_connection_factory(catalog, role="writer_financial_data"),
    )


_EQUITY_VALUE_NAMES = ("目标市值", "股权价值", "股权现金流价值")
_REJECTED_OUTPUT_NAMES = ("每股", "目标价", "EPS", "净利润", "收入", "营收", "自由现金流")
_CURRENCY_ALIASES = {
    "CNY": ("人民币", "CNY"),
    "HKD": ("港元", "HKD"),
    "USD": ("美元", "USD"),
    "JPY": ("日元", "JPY"),
    "EUR": ("欧元", "EUR"),
}


def _equity_value_currency(output_name: str, unit: str) -> str | None:
    """Accept only explicitly-currency-denominated whole-equity values in 亿元."""
    name = str(output_name or "").strip()
    if not any(token in name for token in _EQUITY_VALUE_NAMES):
        return None
    if any(token.lower() in name.lower() for token in _REJECTED_OUTPUT_NAMES):
        return None
    normalized = re.sub(r"[\s（）()_-]", "", str(unit or "").upper())
    if "亿" not in normalized or any(token in normalized for token in ("/股", "每股", "倍", "%")):
        return None
    matches = [
        currency
        for currency, aliases in _CURRENCY_ALIASES.items()
        if any(alias.upper() in normalized for alias in aliases)
    ]
    return matches[0] if len(matches) == 1 else None


def _summary(bundle: dict[str, Any]) -> dict[str, Any]:
    for run in bundle.get("valuation_model_runs") or []:
        assumptions = run.get("assumptions") or {}
        detail = assumptions.get("company_detail_summary") or {}
        if detail:
            return detail
    return {}


def _candidate(member: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any] | None:
    methods: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    seen_run_keys: set[str] = set()
    for run in bundle.get("valuation_model_runs") or []:
        if run.get("status") not in {"frozen_independent", "reconciled", "reviewed"}:
            continue
        run_key = str(run.get("run_key") or "").strip()
        run_id = run.get("id")
        if not run_key or run_id is None or run_key in seen_run_keys:
            continue
        eligible_outputs = []
        for output in run.get("outputs") or []:
            low, high = output.get("range_low"), output.get("range_high")
            currency = _equity_value_currency(output.get("output_name"), output.get("unit"))
            if low is None or high is None or currency is None:
                continue
            try:
                low_value, high_value = float(low), float(high)
            except (TypeError, ValueError):
                continue
            if low_value <= 0 or high_value < low_value:
                continue
            eligible_outputs.append({
                "name": run.get("model_name") or output.get("output_name"),
                "output_name": output.get("output_name"),
                "run_key": run_key,
                "run_id": run_id,
                "low": low_value,
                "high": high_value,
                "currency": currency,
                "unit": output.get("unit"),
                "formula": output.get("formula"),
                "substitution": output.get("substitution"),
                "model_status": run.get("status"),
                "valuation_date": run.get("valuation_date"),
            })
        if len(eligible_outputs) != 1:
            continue
        methods.append(eligible_outputs[0])
        seen_run_keys.add(run_key)
        for reconciliation in run.get("reconciliations") or []:
            title = reconciliation.get("benchmark_source_label") or reconciliation.get("benchmark_name")
            if title:
                sources.append({
                    "title": title,
                    "source_type": "model_reconciliation",
                    "model_run_id": run.get("id"),
                    "source_ref": reconciliation.get("benchmark_source_ref"),
                    "reconciled_at": reconciliation.get("reconciled_at"),
                })
    by_currency: dict[str, list[dict[str, Any]]] = {}
    for method in methods:
        by_currency.setdefault(method["currency"], []).append(method)
    compatible = max(by_currency.values(), key=len, default=[])
    if len(compatible) < 2:
        return None
    currency = compatible[0]["currency"]
    expected_currency = "HKD" if member.get("market") == "香港" else "CNY"
    if currency != expected_currency:
        return None
    ceiling = median(method["high"] for method in compatible)
    detail = _summary(bundle)
    metrics = bundle.get("current_metrics") or {}
    historical = bundle.get("historical_table") or []
    forecasts = bundle.get("forecast_table") or []
    frozen_input = {
        "company_id": member["company_id"],
        "security_id": member["security_id"],
        "model_methods": compatible,
        "current_metrics": metrics,
        "historical_table": historical,
        "forecast_table": forecasts,
        "detail_summary": detail,
        "market_snapshot": member.get("market_snapshot"),
    }
    source_keys = set()
    dedup_sources = []
    for source in sources + [
        {"title": "financial.db 冻结输入、输出与模型账本", "source_type": "financial_model_ledger"},
    ]:
        key = canonical_json(source)
        if key not in source_keys:
            source_keys.add(key)
            dedup_sources.append(source)
    previous = member.get("latest_ai_version") or {}
    prior = previous.get("ceiling_value")
    if prior and previous.get("currency") == currency:
        pct = (ceiling / float(prior) - 1) * 100
        reason = f"相对上一期候选变化{pct:+.2f}%；本期重新读取最新冻结模型、经营事实与外部对账。"
    else:
        reason = "首次形成可比 AI 候选；已重新读取最新冻结模型、经营事实与外部对账。"
    candidate = {
        "member_id": member["member_id"],
        "company_id": member["company_id"],
        "security_id": member["security_id"],
        "target_year": max(
            [int(str(method.get("valuation_date") or "0")[:4]) for method in compatible if str(method.get("valuation_date") or "")[:4].isdigit()]
            or [date.today().year + 1]
        ),
        "ceiling_value": round(float(ceiling), 8),
        "currency": currency,
        "expected_net_profit": None,
        "method_summary": f"复用公司详情页{len(compatible)}种冻结估值方法；取各适用方法上界的中位数作为候选天花板，不采用统一固定PE。",
        "change_reason": reason,
        "operating_context": {"summary": detail.get("operating_analysis") or "以公司详情页最新经营数据与冻结模型为准。"},
        "profit_context": {"summary": detail.get("future_view") or "复核 FY1—FY3 盈利与模型输入。"},
        "cash_flow_context": {"summary": detail.get("valuation_analysis") or "现金流方法与利润方法共同参与估值。"},
        "shareholder_return_context": {"summary": detail.get("buy_point_analysis") or "结合分红、回购与资本开支边界。"},
        "valuation_methods": compatible,
        "market_context": {
            "summary": detail.get("difference_causes") or detail.get("risk_trigger")
            or (
                "已复核当前市值快照："
                + str((member.get("market_snapshot") or {}).get("market_cap_value") or "暂无")
                + " " + str((member.get("market_snapshot") or {}).get("currency") or "")
                + "亿元；估值天花板仍由适用的冻结多方法模型决定。"
            )
        },
        "sources": dedup_sources,
        "frozen_input": frozen_input,
    }
    return candidate


def run(*, valuation_date: date | None = None) -> dict[str, Any]:
    runtime = Path(os.environ["HONGHU_POSTGRES_RUNTIME_CONFIG"])
    repo = _repo(runtime)
    as_of = valuation_date or date.today()
    window = as_of.strftime("%Y-%m")
    idempotency_key = f"monthly-ai:{window}"
    committed = repo.committed_task_result(
        "record_ai_candidates_v1", idempotency_key
    )
    if committed is not None:
        committed["automatic_publish"] = False
        return committed
    members = repo.watchlist()
    candidates = []
    skipped = []
    for member in members:
        bundle = company_bundle(int(member["company_id"]))
        if not bundle:
            skipped.append({"company_id": member["company_id"], "reason": "无公司财务模型"})
            continue
        candidate = _candidate(member, bundle)
        if candidate is None:
            skipped.append({"company_id": member["company_id"], "reason": "不足两种同币种适用估值方法"})
            continue
        candidates.append(candidate)
    if not candidates:
        raise RuntimeError(f"no company passed the multi-method valuation gate: {skipped}")
    actor = str(os.environ.get("HONGHU_AUDIT_ACTOR") or "HonghuTaskRunner")
    result = repo.record_ai_candidates(
        as_of, candidates, prompt_sha256=PROMPT_SHA256, model_name=MODEL_NAME,
        actor=actor, idempotency_key=idempotency_key,
    )
    result["skipped"] = skipped
    result["prompt_contract_sha256"] = PROMPT_SHA256
    result["automatic_publish"] = False
    return result


def main() -> int:
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
