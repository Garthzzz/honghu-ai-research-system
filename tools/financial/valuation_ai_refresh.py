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


MODEL_NAME = "honghu-existing-multi-method-valuation-v2"
PROMPT_CONTRACT = """按公司详情页与行业计算器的既有财务估值体系复核经营、盈利、现金流、股东回报、行业与市场变化；仅使用已冻结且有来源的适用模型，至少两种方法。估值下限取各方法下限中位数，基准估值取各方法中点中位数，估值上限取各方法上限中位数；不得用统一固定PE，不得覆盖人工版本。每期必须冻结输入、方法、来源与变化原因；证据不足时不生成。"""
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
    if currency == "USD" and expected_currency == "HKD":
        previous_input = (member.get("latest_ai_version") or {}).get("frozen_input") or {}
        fx = previous_input.get("fx_usd_hkd")
        if not fx or float(fx) <= 0:
            return None
        compatible = [
            {
                **method,
                "source_currency": "USD",
                "currency": "HKD",
                "low": float(method["low"]) * float(fx),
                "high": float(method["high"]) * float(fx),
                "conversion": f"USD估值×{float(fx):.4f} HKD/USD",
            }
            for method in compatible
        ]
        currency = "HKD"
    if currency != expected_currency:
        return None
    lower = median(method["low"] for method in compatible)
    base = median((method["low"] + method["high"]) / 2 for method in compatible)
    upper = median(method["high"] for method in compatible)
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
    # A frozen model output without an external reconciliation is not a new
    # monthly AI valuation.  Keep it out of the candidate batch rather than
    # letting the database reject the entire run or weakening provenance.
    if (
        len(dedup_sources) < 2
        or not any(
            source.get("source_type") == "model_reconciliation"
            for source in dedup_sources
        )
    ):
        return None
    previous = member.get("latest_ai_version") or {}
    prior = previous.get("base_value") or previous.get("ceiling_value")
    if prior and previous.get("currency") == currency:
        pct = (base / float(prior) - 1) * 100
        reason = f"基准估值相对上一期变化{pct:+.2f}%；本期重新读取最新冻结模型、经营事实与外部对账。"
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
        "lower_value": round(float(lower), 8),
        "base_value": round(float(base), 8),
        "upper_value": round(float(upper), 8),
        "ceiling_value": round(float(upper), 8),
        "currency": currency,
        "expected_net_profit": None,
        "method_summary": f"复用公司详情页{len(compatible)}种冻结估值方法；分别取方法下限、中点和上限的中位数形成估值区间，不采用统一固定PE。",
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
                + "亿元；估值区间仍由适用的冻结多方法模型决定。"
            )
        },
        "sources": dedup_sources,
        "frozen_input": frozen_input,
    }
    return candidate


def _review_existing_version(member: dict[str, Any]) -> dict[str, Any] | None:
    """Create a new monthly review from the last complete reviewed version.

    This path serves companies whose full financial model has not yet been
    promoted into ``valuation_model_runs``.  It never invents a fixed multiple:
    it verifies the prior version's named methods and frozen aggregation, freezes
    the newest Wind market snapshot, and states explicitly when reviewed
    operating inputs did not change.
    """
    previous = member.get("latest_ai_version") or {}
    methods = previous.get("valuation_methods") or []
    sources = previous.get("sources") or []
    normalized = []
    for method in methods:
        try:
            low = float(method["low"])
            high = float(method["high"])
            base = float(method.get("base", (low + high) / 2))
        except (KeyError, TypeError, ValueError):
            continue
        if low <= 0 or not low <= base <= high:
            continue
        normalized.append({**method, "low": low, "base": base, "high": high})
    if len(normalized) < 2 or len(sources) < 2:
        return None
    try:
        lower = float(previous["lower_value"])
        base = float(previous["base_value"])
        upper = float(previous["upper_value"])
    except (KeyError, TypeError, ValueError):
        return None
    if lower <= 0 or not lower <= base <= upper:
        return None
    market = member.get("market_snapshot") or {}
    frozen_input = {
        "review_type": "monthly_review_of_last_complete_model",
        "previous_version_id": previous.get("version_id"),
        "previous_input_sha256": previous.get("input_sha256"),
        "previous_output_sha256": previous.get("output_sha256"),
        "valuation_methods": normalized,
        "latest_market_snapshot": market,
        "review_conclusion": "reviewed_inputs_unchanged",
    }
    return {
        "member_id": member["member_id"],
        "company_id": member["company_id"],
        "security_id": member["security_id"],
        "target_year": previous.get("target_year"),
        "lower_value": round(lower, 8),
        "base_value": round(base, 8),
        "upper_value": round(upper, 8),
        "ceiling_value": round(upper, 8),
        "currency": previous.get("currency"),
        "expected_net_profit": previous.get("expected_net_profit"),
        "method_summary": (
            "复核上一期完整多方法模型及最新 Wind 行情；各方法的经营、盈利、"
            "现金流与股东回报输入未出现经审核的变化，因此按原冻结聚合规则复算的区间不变。"
        ),
        "change_reason": (
            "基准估值较上一期变化+0.00%；最新股价和总市值只改变市场相对位置，"
            "未发现经审核且足以改写模型输入的新事实，故不机械调整内在价值。"
        ),
        "operating_context": previous.get("operating_context") or {},
        "profit_context": previous.get("profit_context") or {},
        "cash_flow_context": previous.get("cash_flow_context") or {},
        "shareholder_return_context": previous.get("shareholder_return_context") or {},
        "valuation_methods": normalized,
        "market_context": {
            "summary": (
                f"本期复核 Wind 最新股价 {market.get('share_price_value', '暂无')}、"
                f"总市值 {market.get('market_cap_value', '暂无')}；行情变化不直接作为估值输入。"
            )
        },
        "sources": sources,
        "frozen_input": frozen_input,
    }


def run(*, valuation_date: date | None = None) -> dict[str, Any]:
    runtime = Path(os.environ["HONGHU_POSTGRES_RUNTIME_CONFIG"])
    repo = _repo(runtime)
    as_of = valuation_date or date.today()
    window = as_of.strftime("%Y-%m")
    idempotency_key = f"monthly-ai:{window}"
    committed = repo.committed_task_result(
        "record_ai_candidates_v2", idempotency_key
    )
    if committed is not None:
        committed["automatic_publish"] = False
        return committed
    members = repo.watchlist()
    candidates = []
    skipped = []
    for member in members:
        bundle = company_bundle(int(member["company_id"]))
        candidate = _candidate(member, bundle) if bundle else None
        if candidate is None:
            candidate = _review_existing_version(member)
        if candidate is None:
            skipped.append({
                "member_id": member["member_id"],
                "company_id": member["company_id"],
                "security_id": member["security_id"],
                "reason": "不足两种同币种、具备外部对账的适用估值方法",
            })
            continue
        candidates.append(candidate)
    actor = str(os.environ.get("HONGHU_AUDIT_ACTOR") or "HonghuTaskRunner")
    if not candidates:
        result = repo.record_ai_no_candidates(
            as_of, skipped, prompt_sha256=PROMPT_SHA256,
            model_name=MODEL_NAME, actor=actor,
            idempotency_key=f"{idempotency_key}:no-candidate",
        )
        result["skipped"] = skipped
        result["prompt_contract_sha256"] = PROMPT_SHA256
        result["automatic_publish"] = False
        return result
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
