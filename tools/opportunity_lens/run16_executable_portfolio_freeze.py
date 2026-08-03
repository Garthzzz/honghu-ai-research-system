from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = (
    ROOT
    / "opportunity_lens"
    / "research_outputs"
    / "20260801_ai_app_full_chain_portfolio_run16"
    / "financial_artifacts"
    / "run16_independent_financial_portfolios.json"
)
DEFAULT_OUTPUT = DEFAULT_INPUT.with_name("run16_current_executable_portfolios.json")

ARTIFACT_VERSION = "opportunity_lens.run16_executable_portfolio.v1"
RULE_VERSION = "run16.current_execution_gate.v1"
PORTFOLIO_TYPES = ("concentrated", "balanced", "risk_diversified")
SCOPES = ("applications", "full_chain")
UPPER_CORE_VALUATION_GATE_PCT = 25.0


class ExecutablePortfolioFreezeError(ValueError):
    """Raised when the independent model cannot produce a valid frozen basket."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def content_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _finite(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise ExecutablePortfolioFreezeError(f"{label} 缺少有限数值")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutablePortfolioFreezeError(f"{label} 不是数值：{value!r}") from exc
    if not math.isfinite(number):
        raise ExecutablePortfolioFreezeError(f"{label} 不是有限数值")
    return number


def _portfolio_by_key(
    model: Mapping[str, Any], scope: str, kind: str
) -> Mapping[str, Any]:
    found = [
        row
        for row in model.get("portfolios", [])
        if row.get("scope") == scope and row.get("portfolio_type") == kind
    ]
    if len(found) != 1:
        raise ExecutablePortfolioFreezeError(f"组合定位不唯一：{scope}.{kind}")
    return found[0]


def _calculated_valuation_range(
    company: Mapping[str, Any],
) -> tuple[float | None, float | None]:
    lows: list[float] = []
    highs: list[float] = []
    for method in company.get("valuation_methods", []):
        if method.get("status") != "calculated":
            continue
        if method.get("method") != "Forward PE" and method.get("role") not in {
            "核心",
            "有效参考",
        }:
            continue
        if method.get("equity_value_low_100m_cny") is None:
            continue
        lows.append(_finite(method["equity_value_low_100m_cny"], "valuation.low"))
        highs.append(_finite(method["equity_value_high_100m_cny"], "valuation.high"))
    return (min(lows), max(highs)) if lows else (None, None)


def _current_execution_gate(company: Mapping[str, Any]) -> dict[str, Any]:
    low, high = _calculated_valuation_range(company)
    market_cap = company.get("baseline", {}).get("market", {}).get(
        "market_cap_100m_cny"
    )
    fcf_values = [
        company.get("scenarios", {}).get("base", {}).get(str(year), {}).get(
            "fcf_100m_cny"
        )
        for year in (2026, 2027, 2028)
    ]
    valid_fcf = all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        for value in fcf_values
    )
    nonnegative_fcf = bool(valid_fcf) and all(
        float(value) >= 0 for value in fcf_values
    ) and any(float(value) > 0 for value in fcf_values)
    common = {
        "positive_fcf_2026_2028": nonnegative_fcf,
        "base_fcf_2026_2028_100m_cny": [
            round(float(value), 2) if isinstance(value, (int, float)) else None
            for value in fcf_values
        ],
    }
    if (
        low is None
        or high is None
        or not isinstance(market_cap, (int, float))
        or isinstance(market_cap, bool)
        or not math.isfinite(float(market_cap))
        or float(market_cap) <= 0
    ):
        return {
            **common,
            "eligible_now": False,
            "action": "暂不配置",
            "reason": "缺少可复算的核心估值区间或当前市值",
            "upside_to_high_pct": None,
        }
    upside = (float(high) / float(market_cap) - 1.0) * 100.0
    if nonnegative_fcf and upside >= UPPER_CORE_VALUATION_GATE_PCT:
        action = "当前可配置"
        reason = (
            "2026—2028年基准自由现金流均不为负，核心估值上沿相对当前市值"
            f"留有{upside:.2f}%空间"
        )
        eligible = True
    elif nonnegative_fcf and upside >= 10.0:
        action = "择价观察"
        reason = (
            f"现金流门槛通过，但核心估值上沿相对当前市值仅留{upside:.2f}%空间，"
            "尚未达到25%的当前配置门槛"
        )
        eligible = False
    elif nonnegative_fcf and upside >= 0.0:
        action = "不追高"
        reason = f"现金流门槛通过，但核心估值上沿相对当前市值仅留{upside:.2f}%空间"
        eligible = False
    else:
        action = "当前回避"
        reason = (
            "2026—2028年自由现金流门槛未通过"
            if not nonnegative_fcf
            else f"核心估值上沿相对当前市值仅为{upside:.2f}%"
        )
        eligible = False
    return {
        **common,
        "eligible_now": eligible,
        "action": action,
        "reason": reason,
        "upside_to_high_pct": round(upside, 2),
        "valuation_low_100m_cny": round(float(low), 2),
        "valuation_high_100m_cny": round(float(high), 2),
        "market_cap_100m_cny": round(float(market_cap), 2),
    }


def _build_executable_portfolio(
    model: Mapping[str, Any],
    gates: Mapping[str, Mapping[str, Any]],
    scope: str,
    kind: str,
) -> dict[str, Any]:
    source = deepcopy(_portfolio_by_key(model, scope, kind))
    candidate_policy = deepcopy(source.get("policy", {}))
    retained = [
        row
        for row in source.get("holdings", [])
        if gates.get(str(row.get("ticker")), {}).get("eligible_now")
    ]
    excluded = [
        {
            "ticker": row["ticker"],
            "name": row["name"],
            "former_weight_pct": row["weight_pct"],
            **gates[row["ticker"]],
        }
        for row in source.get("holdings", [])
        if not gates.get(str(row.get("ticker")), {}).get("eligible_now")
    ]
    for row in retained:
        row["candidate_weight_pct"] = row.get("weight_pct")
        # These diagnostics were calculated for the pre-gate candidate basket.
        # Keeping them on a surviving holding would make them look current after
        # rejected names have moved to cash.
        row.pop("risk_contribution_pct", None)
        row.pop("weight_sensitivity", None)
    weight_rule = (
        "通过门槛者保留冻结候选权重；未通过者权重转为现金，不向剩余股票再分配"
    )
    if kind == "concentrated" and retained:
        cap = _finite(
            candidate_policy.get("max_weight_pct"),
            "executable.concentrated.max_weight_pct",
        )
        executable_weight = min(cap, 75.0 / len(retained))
        for row in retained:
            row["weight_pct"] = round(executable_weight, 2)
        weight_rule = (
            "高确信度方案将股票仓位限制在75%以内，并对通过门槛的原方向候选"
            f"等权配置{executable_weight:.2f}%（单股上限{cap:.2f}%），"
            "剩余资金留作现金；未通过者不替补"
        )

    retained_tickers = {str(row["ticker"]) for row in retained}
    equity_weight = round(
        sum(_finite(row["weight_pct"], "executable.weight") for row in retained),
        2,
    )
    cash_weight = round(100.0 - equity_weight, 2)
    if retained and equity_weight > 0:
        normalized = [
            _finite(row["weight_pct"], "executable.weight") / equity_weight
            for row in retained
        ]
        effective_n = 1.0 / sum(weight * weight for weight in normalized)
    else:
        effective_n = 0.0
    diagnostics = [
        row
        for row in source.get("correlation_diagnostics", [])
        if str(row.get("left")) in retained_tickers
        and str(row.get("right")) in retained_tickers
    ]
    direction_weights: dict[str, float] = {}
    for row in retained:
        direction = str(row.get("direction") or "其他")
        direction_weights[direction] = round(
            direction_weights.get(direction, 0.0)
            + _finite(row["weight_pct"], "executable.direction_weight"),
            2,
        )
    rolling_threshold = candidate_policy.get("rolling_60d_diagnostic_threshold")
    rolling_breach_count = (
        sum(
            1
            for row in diagnostics
            if row.get("rolling_60d_peak") is not None
            and rolling_threshold is not None
            and float(row["rolling_60d_peak"]) > float(rolling_threshold)
        )
        if len(retained) >= 2
        else None
    )
    max_direction = candidate_policy.get("max_direction_weight_pct")
    direction_violations = [
        {
            "direction": direction,
            "weight_pct": weight,
            "limit_pct": float(max_direction),
        }
        for direction, weight in direction_weights.items()
        if max_direction is not None and weight > float(max_direction) + 1e-9
    ]
    execution_policy = {
        "anchor_mix": deepcopy(candidate_policy.get("anchor_mix", {})),
        "score_weights": deepcopy(candidate_policy.get("score_weights", {})),
        "active_tilt_strength": candidate_policy.get("active_tilt_strength"),
        "active_tilt_min": candidate_policy.get("active_tilt_min"),
        "active_tilt_max": candidate_policy.get("active_tilt_max"),
        "max_weight_pct": candidate_policy.get("max_weight_pct"),
        "max_direction_weight_pct": candidate_policy.get(
            "max_direction_weight_pct"
        ),
        "max_pair_correlation": candidate_policy.get("max_pair_correlation"),
        "min_overlap_days": candidate_policy.get("min_overlap_days"),
        "correlation_window_days": candidate_policy.get(
            "correlation_window_days"
        ),
        "rolling_60d_diagnostic_threshold": rolling_threshold,
        "cash_weight_pct": cash_weight,
        "minimum_holding_count_after_current_gate": None,
        "maximum_equity_weight_pct": 75.0 if kind == "concentrated" else 100.0,
    }
    return {
        "scope": scope,
        "portfolio_type": kind,
        "status": "current_executable",
        "conviction_theme": source.get("conviction_theme"),
        "policy": execution_policy,
        "candidate_policy": candidate_policy,
        "holdings": retained,
        "cash_weight_pct": cash_weight,
        "effective_number_of_holdings": round(effective_n, 2),
        "top3_weight_pct": round(
            sum(
                sorted(
                    (
                        _finite(row["weight_pct"], "executable.top3")
                        for row in retained
                    ),
                    reverse=True,
                )[:3]
            ),
            2,
        ),
        "direction_weight_pct": direction_weights,
        "direction_concentration_violations": direction_violations,
        "correlation_diagnostics": diagnostics,
        "highest_observed_pair_correlation": max(
            (
                float(row["correlation"])
                for row in diagnostics
                if row.get("sufficient_history")
                and row.get("correlation") is not None
            ),
            default=None,
        ),
        "rolling_60d_correlation_diagnostic_threshold": rolling_threshold,
        "rolling_60d_breach_count": rolling_breach_count,
        "excluded_by_current_gate": excluded,
        "execution_gate": {
            "minimum_upside_to_core_high_pct": UPPER_CORE_VALUATION_GATE_PCT,
            "requires_nonnegative_base_fcf_2026_2028": True,
            "weight_rule": weight_rule,
        },
        "limitations": [
            "当前可执行权重使用2026年7月30日市场估值快照；组合形成于2026年8月2日。",
            "25%门槛只约束核心估值上沿，不代表整个估值区间均有25%安全边际。",
            "候选组合的风险贡献、权重敏感性和容量诊断不冒充门槛处理后的当前诊断；"
            "执行层仅保留能够在当前持仓上重新计算的字段。",
        ],
    }


def _build_stress_tests(
    model: Mapping[str, Any], portfolios: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    frozen: list[dict[str, Any]] = []
    by_key = {
        (str(row["scope"]), str(row["portfolio_type"])): row for row in portfolios
    }
    for stress in model.get("stress_tests", []):
        company_results = stress.get("company_results", {})
        results: list[dict[str, Any]] = []
        for scope in SCOPES:
            for kind in PORTFOLIO_TYPES:
                portfolio = by_key[(scope, kind)]
                weighted_profit = 0.0
                profit_coverage_weight = 0.0
                weighted_valuation = 0.0
                valuation_coverage_weight = 0.0
                for holding in portfolio.get("holdings", []):
                    result = company_results.get(holding["ticker"], {})
                    weight = _finite(holding["weight_pct"], "stress.weight") / 100.0
                    profit = result.get("fy2027_parent_net_income_change_pct")
                    if profit is not None:
                        profit_coverage_weight += weight
                        weighted_profit += weight * _finite(
                            profit, "stress.company_profit"
                        )
                    valuation = result.get("valuation_proxy_change_pct")
                    if valuation is not None:
                        valuation_coverage_weight += weight
                        weighted_valuation += weight * _finite(
                            valuation, "stress.company_valuation"
                        )
                results.append(
                    {
                        "scope": scope,
                        "portfolio_type": kind,
                        "weighted_fy2027_profit_change_pct": round(
                            weighted_profit, 2
                        ),
                        "profit_equity_weight_coverage_pct": round(
                            profit_coverage_weight * 100.0, 2
                        ),
                        "weighted_valuation_proxy_change_pct": (
                            round(
                                weighted_valuation / valuation_coverage_weight, 2
                            )
                            if valuation_coverage_weight > 0
                            else None
                        ),
                        "valuation_proxy_equity_weight_coverage_pct": round(
                            valuation_coverage_weight * 100.0, 2
                        ),
                        "limitation": (
                            "归母净利润变化按股票权重汇总并把现金视为零冲击；"
                            "估值代理只在可估值的权益仓内归一。结果不是历史回测，"
                            "也不把情景概率乘入估值。"
                        ),
                    }
                )
        frozen.append(
            {
                "name": stress["name"],
                "description": stress.get("description"),
                "input_shocks": stress.get("input_shocks"),
                "portfolio_results": results,
            }
        )
    return frozen


def _sanity_checks(
    model: Mapping[str, Any],
    gates: Mapping[str, Mapping[str, Any]],
    portfolios: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    expected = {(scope, kind) for scope in SCOPES for kind in PORTFOLIO_TYPES}
    actual = {
        (str(row.get("scope")), str(row.get("portfolio_type")))
        for row in portfolios
    }
    checks.append(
        {
            "check": "six_portfolios_present",
            "passed": actual == expected,
            "observed": sorted([list(key) for key in actual]),
        }
    )
    for portfolio in portfolios:
        key = f"{portfolio['scope']}.{portfolio['portfolio_type']}"
        total = _finite(portfolio["cash_weight_pct"], f"{key}.cash") + sum(
            _finite(row["weight_pct"], f"{key}.holding")
            for row in portfolio["holdings"]
        )
        held_ineligible = [
            row["ticker"]
            for row in portfolio["holdings"]
            if not gates[row["ticker"]]["eligible_now"]
        ]
        pair_rows_for_single = (
            portfolio.get("correlation_diagnostics", [])
            if len(portfolio["holdings"]) <= 1
            else []
        )
        max_single = max(
            (float(row["weight_pct"]) for row in portfolio["holdings"]),
            default=0.0,
        )
        stale_top_level_fields = sorted(
            field
            for field in (
                "candidate_pool",
                "cash_capacity_adjustment",
                "correlation_pruning",
                "portfolio_risk_diagnostics",
                "requested_cash_weight_pct",
                "weight_sensitivity",
            )
            if field in portfolio
        )
        stale_holding_fields = sorted(
            {
                field
                for row in portfolio["holdings"]
                for field in ("risk_contribution_pct", "weight_sensitivity")
                if field in row
            }
        )
        checks.extend(
            [
                {
                    "check": f"{key}.weights_sum_to_100",
                    "passed": abs(total - 100.0) <= 0.02,
                    "observed": round(total, 4),
                },
                {
                    "check": f"{key}.holds_only_eligible_names",
                    "passed": not held_ineligible,
                    "observed": held_ineligible,
                },
                {
                    "check": f"{key}.single_name_limit",
                    "passed": max_single <= 25.0 + 1e-9,
                    "observed": max_single,
                },
                {
                    "check": f"{key}.single_stock_correlation_is_not_applicable",
                    "passed": not pair_rows_for_single
                    and (
                        len(portfolio["holdings"]) > 1
                        or portfolio.get("rolling_60d_breach_count") is None
                    ),
                    "observed": {
                        "pair_rows": len(pair_rows_for_single),
                        "rolling_breach_count": portfolio.get(
                            "rolling_60d_breach_count"
                        ),
                    },
                },
                {
                    "check": f"{key}.no_pre_gate_diagnostics_masquerade_as_current",
                    "passed": not stale_top_level_fields
                    and not stale_holding_fields,
                    "observed": {
                        "top_level": stale_top_level_fields,
                        "holding": stale_holding_fields,
                    },
                },
                {
                    "check": f"{key}.policy_cash_matches_executable_cash",
                    "passed": abs(
                        _finite(
                            portfolio.get("policy", {}).get("cash_weight_pct"),
                            f"{key}.policy.cash_weight_pct",
                        )
                        - float(portfolio["cash_weight_pct"])
                    )
                    <= 1e-9,
                    "observed": portfolio.get("policy", {}).get(
                        "cash_weight_pct"
                    ),
                },
            ]
        )
        if portfolio["portfolio_type"] == "concentrated":
            equity_weight = 100.0 - float(portfolio["cash_weight_pct"])
            checks.append(
                {
                    "check": f"{key}.concentrated_equity_cap",
                    "passed": equity_weight <= 75.0 + 1e-9,
                    "observed": round(equity_weight, 2),
                }
            )
    failed = [row for row in checks if row["passed"] is not True]
    if failed:
        raise ExecutablePortfolioFreezeError(
            "Run16 可执行组合确定性检查失败：" + json.dumps(failed, ensure_ascii=False)
        )
    return checks


def build_executable_artifact(
    model: Mapping[str, Any], independent_model_path: Path
) -> dict[str, Any]:
    if model.get("independent_before_consensus") is not True:
        raise ExecutablePortfolioFreezeError("输入不是独立预测冻结模型")
    if model.get("external_consensus_read") is not False:
        raise ExecutablePortfolioFreezeError("输入模型已读取外部一致预期")
    companies = model.get("companies")
    if not isinstance(companies, dict) or not companies:
        raise ExecutablePortfolioFreezeError("输入模型缺少公司模型")

    gates = {
        ticker: {
            "ticker": ticker,
            "name": company.get("name"),
            **_current_execution_gate(company),
        }
        for ticker, company in companies.items()
    }
    portfolios = [
        _build_executable_portfolio(model, gates, scope, kind)
        for scope in SCOPES
        for kind in PORTFOLIO_TYPES
    ]
    stress_tests = _build_stress_tests(model, portfolios)
    checks = _sanity_checks(model, gates, portfolios)
    artifact: dict[str, Any] = {
        "artifact_version": ARTIFACT_VERSION,
        "rule_version": RULE_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of_date": model.get("as_of_date"),
        "input_independent_model": {
            "path": str(independent_model_path.resolve()),
            "file_sha256": file_sha256(independent_model_path),
            "declared_output_hash": model.get("output_hash"),
        },
        "execution_rules": {
            "company_gate": (
                "2026—2028年基准自由现金流均不为负且至少一年为正，并且核心估值"
                "上沿相对当前市值至少高25%"
            ),
            "upper_core_valuation_upside_gate_pct": UPPER_CORE_VALUATION_GATE_PCT,
            "balanced_and_defensive_weight_rule": (
                "通过门槛者保留冻结候选权重；未通过者的原权重转为现金，不向剩余股票再分配"
            ),
            "high_conviction_weight_rule": (
                "只在通过门槛的原高确信度候选中等权；股票仓位不超过75%，单股不超过25%"
            ),
            "correlation_rule": (
                "245个交易日相关性用于硬约束；60日、120日和滚动60日峰值仅作诊断；"
                "单一股票仓位的两两相关性为不适用，不记为0"
            ),
            "stress_profit_formula": (
                "组合归母净利润变化＝股票权重×公司利润变化之和；现金冲击按0计"
            ),
            "stress_valuation_formula": (
                "组合估值代理变化＝可估值股票权重×公司估值变化之和÷可估值股票权重之和"
            ),
        },
        "company_gates": gates,
        "portfolios": portfolios,
        "stress_tests": stress_tests,
        "sanity": {"verdict": "GREEN", "checks": checks},
    }
    artifact["output_hash"] = content_sha256(artifact)
    return artifact


def validate_executable_artifact(
    artifact: Mapping[str, Any],
    model: Mapping[str, Any],
    independent_model_path: Path,
) -> None:
    if artifact.get("artifact_version") != ARTIFACT_VERSION:
        raise ExecutablePortfolioFreezeError("Run16 可执行组合 artifact_version 不正确")
    binding = artifact.get("input_independent_model")
    if not isinstance(binding, Mapping):
        raise ExecutablePortfolioFreezeError("Run16 可执行组合缺少独立模型绑定")
    if binding.get("file_sha256") != file_sha256(independent_model_path):
        raise ExecutablePortfolioFreezeError("Run16 可执行组合绑定的独立模型文件哈希不一致")
    if binding.get("declared_output_hash") != model.get("output_hash"):
        raise ExecutablePortfolioFreezeError("Run16 可执行组合绑定的独立模型内容哈希不一致")
    declared = str(artifact.get("output_hash") or "")
    unhashed = deepcopy(dict(artifact))
    unhashed.pop("output_hash", None)
    if declared != content_sha256(unhashed):
        raise ExecutablePortfolioFreezeError("Run16 可执行组合内容哈希校验失败")
    if artifact.get("sanity", {}).get("verdict") != "GREEN":
        raise ExecutablePortfolioFreezeError("Run16 可执行组合确定性检查未通过")
    gates = artifact.get("company_gates")
    portfolios = artifact.get("portfolios")
    if not isinstance(gates, Mapping) or not isinstance(portfolios, list):
        raise ExecutablePortfolioFreezeError("Run16 可执行组合缺少门槛或组合结果")
    rebuilt = build_executable_artifact(model, independent_model_path)
    for field in ("company_gates", "portfolios", "stress_tests", "execution_rules"):
        if artifact.get(field) != rebuilt.get(field):
            raise ExecutablePortfolioFreezeError(f"Run16 可执行组合 {field} 无法独立复算")


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze Run16 current executable portfolios")
    parser.add_argument("--independent-model", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    input_path = args.independent_model.resolve()
    output_path = args.output.resolve()
    if not input_path.is_file():
        raise ExecutablePortfolioFreezeError(f"输入模型不存在：{input_path}")
    model = json.loads(input_path.read_text(encoding="utf-8"))
    if args.validate_only:
        if not output_path.is_file():
            raise ExecutablePortfolioFreezeError(f"冻结产物不存在：{output_path}")
        artifact = json.loads(output_path.read_text(encoding="utf-8"))
        validate_executable_artifact(artifact, model, input_path)
    else:
        artifact = build_executable_artifact(model, input_path)
        _atomic_write_json(output_path, artifact)
        validate_executable_artifact(artifact, model, input_path)
    print(
        json.dumps(
            {
                "artifact": str(output_path),
                "file_sha256": file_sha256(output_path),
                "output_hash": artifact["output_hash"],
                "portfolio_count": len(artifact["portfolios"]),
                "sanity": artifact["sanity"]["verdict"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
