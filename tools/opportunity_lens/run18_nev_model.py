from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "cache" / "research_runs" / "20260803_nev_production_inventory_run18"
AGENT_DIR = RUN_DIR / "agent_outputs"
OUTPUT_DIR = (
    ROOT
    / "opportunity_lens"
    / "research_outputs"
    / "20260803_nev_production_inventory_run18"
)
OUTPUT_PATH = OUTPUT_DIR / "nev_three_method_model_v1.json"

METHOD_INPUTS = {
    "industry_total": AGENT_DIR / "industry_total.json",
    "brand_bottom_up": AGENT_DIR / "brand_bottomup.json",
    "upstream_leading": AGENT_DIR / "upstream_leading.json",
}

# 权重只用于把三条独立建模口径压缩为一个可执行区间，不用于改变各自结果。
# 行业总量法能直接闭合产、批、零、出口和库存，权重最高；品牌法覆盖约88%的
# 生产主体但公司口径更易错配；上游法有较好同期回测，但提前一月能力较弱。
METHOD_WEIGHTS = {
    "industry_total": 0.45,
    "brand_bottom_up": 0.30,
    "upstream_leading": 0.25,
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decimal(value: float | int | str | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _round(value: float | Decimal, digits: int = 1) -> float:
    quantum = Decimal("1").scaleb(-digits)
    rounded = float(_decimal(value).quantize(quantum, rounding=ROUND_HALF_UP))
    return 0.0 if rounded == 0 else rounded


MONTHS = ("2026-08", "2026-09", "2026-10")

# 下列百分点是研究假设，不是企业公开指引。它们把公司6月可观察的国内交付/
# 中国工厂出口结构延伸到未来三个月；正文必须同时展示这些输入和误差范围。
EXPORT_SHARE_ADJUSTMENT_PP = {
    1: (0.0, 1.0, 1.0),
    2: (0.0, 1.0, 1.0),
    3: (0.0, -1.0, -2.0),
    4: (0.0, 1.0, 1.0),
    5: (-2.0, 4.0, 1.0),
    6: (0.0, 1.0, 2.0),
    7: (-1.0, -1.0, -1.0),
    8: (0.0, 1.0, 1.0),
    9: (0.0, 0.0, 0.0),
    10: (0.0, 1.0, 1.0),
    11: (0.0, 0.0, 0.0),
    12: (0.0, 0.0, 0.0),
    13: (0.0, 0.0, 0.0),
    14: (0.0, 0.0, 0.0),
    15: (0.0, 0.0, 0.0),
}

FALLBACK_EXPORT_SHARE = {
    9: 0.005,
    10: 0.040,
    12: 0.005,
    14: 0.010,
    15: 0.010,
}

INVENTORY_RATE = {
    1: (0.02, 0.00, -0.01),
    2: (0.01, 0.00, 0.00),
    3: (0.00, -0.01, -0.01),
    4: (0.02, 0.00, 0.00),
    5: (0.01, -0.04, 0.02),
    6: (0.01, 0.00, 0.00),
    7: (0.02, 0.00, 0.00),
    8: (0.00, 0.00, 0.00),
    9: (0.00, 0.00, 0.00),
    10: (0.02, -0.01, 0.00),
    11: (0.01, 0.00, 0.00),
    12: (0.02, 0.00, 0.00),
    13: (0.00, 0.00, 0.00),
    14: (0.00, 0.00, 0.00),
    15: (0.01, 0.00, 0.00),
}


def _base_export_share(company: dict[str, Any]) -> tuple[float, str]:
    domestic = company.get("june_domestic_retail_k")
    exports = company.get("june_china_factory_export_k_cpca")
    wholesale = float(company["june_2026_wholesale_k"])
    if domestic is not None and exports is not None and float(domestic) + float(exports) > 0:
        return float(exports) / (float(domestic) + float(exports)), "6月国内零售与中国工厂出口归一"
    if exports is not None and wholesale > 0:
        return min(float(exports) / wholesale, 0.75), "6月中国工厂出口占厂商批发"
    return FALLBACK_EXPORT_SHARE.get(int(company["rank"]), 0.01), "公开出口缺口下的宽口径研究假设"


def _company_bridge(brand: dict[str, Any]) -> dict[str, Any]:
    industry_by_month = {row["month"]: row for row in brand["industry_forecast"]}
    june_industry = 148.1
    seasonality = {
        month: float(industry_by_month[month]["production_k"]["base"]) / 10.0 / june_industry
        for month in MONTHS
    }
    rows: list[dict[str, Any]] = []
    for company in brand["companies"]:
        rank = int(company["rank"])
        wholesale_10k = float(company["june_2026_wholesale_k"]) / 10.0
        base_export_share, export_basis = _base_export_share(company)
        month_rows: list[dict[str, Any]] = []
        for month_index, month in enumerate(MONTHS):
            raw = company["forecast_k"][month]
            production = {
                "low": float(raw["low"]) / 10.0,
                "point": (float(raw["low"]) + float(raw["high"])) / 20.0,
                "high": float(raw["high"]) / 10.0,
            }
            s = seasonality[month]
            n = 0.0
            r = {band: (value - n) / (wholesale_10k * s) for band, value in production.items()}
            export_share = max(
                0.0,
                min(0.75, base_export_share + EXPORT_SHARE_ADJUSTMENT_PP[rank][month_index] / 100.0),
            )
            inventory_rate = INVENTORY_RATE[rank][month_index]
            point_export = production["point"] * export_share
            point_inventory = production["point"] * inventory_rate
            point_domestic = production["point"] - point_export - point_inventory
            export_uncertainty = 0.04 if rank == 5 else 0.02
            inventory_uncertainty = 0.02
            domestic_candidates: list[float] = []
            for p in (production["low"], production["high"]):
                for e in (max(0.0, export_share - export_uncertainty), min(0.80, export_share + export_uncertainty)):
                    for inv in (inventory_rate - inventory_uncertainty, inventory_rate + inventory_uncertainty):
                        domestic_candidates.append(p * (1.0 - e - inv))
            export_low = production["low"] * max(0.0, export_share - export_uncertainty)
            export_high = production["high"] * min(0.80, export_share + export_uncertainty)
            inventory_low = min(
                production["low"] * (inventory_rate - inventory_uncertainty),
                production["high"] * (inventory_rate - inventory_uncertainty),
            )
            inventory_high = max(
                production["low"] * (inventory_rate + inventory_uncertainty),
                production["high"] * (inventory_rate + inventory_uncertainty),
            )
            production_display = {
                band: _round(value) for band, value in production.items()
            }
            point_export_display = _round(point_export)
            point_inventory_display = _round(point_inventory)
            # 公开中值先分别冻结产量、出口和库存，再把内销作为严格残差，确保
            # 读者按表逐行复算时 P=D+E+I 在一位小数展示精度下仍完全闭合。
            point_domestic_display = _round(
                _decimal(production_display["point"])
                - _decimal(point_export_display)
                - _decimal(point_inventory_display)
            )
            month_rows.append(
                {
                    "month": month,
                    "formula_inputs": {
                        "june_wholesale_10k": _round(wholesale_10k, 4),
                        "seasonal_factor": _round(s, 4),
                        "company_adjustment_r": {band: _round(value, 4) for band, value in r.items()},
                        "event_increment_n_10k": n,
                        "export_share_pct": _round(export_share * 100.0, 1),
                        "inventory_rate_pct": _round(inventory_rate * 100.0, 1),
                    },
                    "production_10k": production_display,
                    "domestic_sales_10k": {
                        "low": _round(max(0.0, min(domestic_candidates))),
                        "point": point_domestic_display,
                        "high": _round(max(domestic_candidates)),
                    },
                    "china_factory_export_10k": {
                        "low": _round(export_low),
                        "point": point_export_display,
                        "high": _round(export_high),
                    },
                    "inventory_change_10k": {
                        "low": _round(inventory_low),
                        "point": point_inventory_display,
                        "high": _round(inventory_high),
                    },
                }
            )
        rows.append(
            {
                "rank": rank,
                "entity": company["entity"],
                "ownership_class": company["ownership_class"],
                "evidence_ids": list(company.get("evidence_ids") or []),
                "june_wholesale_10k": _round(wholesale_10k, 4),
                "june_domestic_10k": (
                    _round(float(company["june_domestic_retail_k"]) / 10.0, 4)
                    if company.get("june_domestic_retail_k") is not None
                    else None
                ),
                "june_export_10k": (
                    _round(float(company["june_china_factory_export_k_cpca"]) / 10.0, 4)
                    if company.get("june_china_factory_export_k_cpca") is not None
                    else None
                ),
                "export_share_basis": export_basis,
                "months": month_rows,
            }
        )

    totals: list[dict[str, Any]] = []
    for month in MONTHS:
        industry_row = industry_by_month[month]
        company_months = [next(item for item in row["months"] if item["month"] == month) for row in rows]
        company_sums = {
            field: _round(sum(float(item[field]["point"]) for item in company_months))
            for field in ("production_10k", "domestic_sales_10k", "china_factory_export_10k", "inventory_change_10k")
        }
        target = {
            "production_10k": float(industry_row["production_k"]["base"]) / 10.0,
            "domestic_sales_10k": float(industry_row["domestic_retail_k"]["base"]) / 10.0,
            "china_factory_export_10k": float(industry_row["china_factory_export_k"]["base"]) / 10.0,
            "inventory_change_10k": float(industry_row["inventory_change_k"]["base"]) / 10.0,
        }
        tail = {field: _round(target[field] - company_sums[field]) for field in target}
        totals.append({"month": month, "top15_point_10k": company_sums, "unidentified_tail_point_10k": tail, "brand_method_point_10k": target})
    return {
        "formula": "P(i,m)=W(i,6月)×S(m)×R(i,m)+N(i,m)",
        "seasonal_factor_by_month": {month: _round(value, 4) for month, value in seasonality.items()},
        "parameter_status": "S来自品牌法行业总量相对6月的季节比；R是逐公司证据约束的研究判断；N本轮均为0，未把未经证实的新增产线单列为确定增量。",
        "range_rule": "产量沿用逐公司上下限；出口份额通常±2个百分点、特斯拉±4个百分点，库存率±2个百分点；内销为产量减出口减库存的角点范围。",
        "companies": rows,
        "totals": totals,
    }


def _ownership_bridge(company_bridge: dict[str, Any]) -> list[dict[str, Any]]:
    # 6月批发榜第16—20位均有明确数值；这里仅用于把外资独资、外国品牌合资
    # 和无法识别的长尾拆开，不把这些主体扩展成主模型公司池。
    additional_top20 = {
        "2026-08": {"chinese": 6.2, "foreign_jv": 2.6},
        "2026-09": {"chinese": 6.7, "foreign_jv": 2.8},
        "2026-10": {"chinese": 7.2, "foreign_jv": 3.0},
    }
    result: list[dict[str, Any]] = []
    for month in MONTHS:
        company_rows = [
            (row, next(item for item in row["months"] if item["month"] == month))
            for row in company_bridge["companies"]
        ]
        identified_chinese = sum(
            item["production_10k"]["point"]
            for row, item in company_rows
            if int(row["rank"]) not in {5, 7}
        ) + additional_top20[month]["chinese"]
        # 上汽通用五菱是中外合资法人，但五菱/宝骏属于中国品牌体系；按用户要求
        # 它不与“外国品牌合资”混写，并在补充口径中保留，同时单列便于做所有权敏感性。
        chinese_brand_jv = next(
            item["production_10k"]["point"]
            for row, item in company_rows
            if int(row["rank"]) == 7
        )
        foreign_wholly = next(
            item["production_10k"]["point"] for row, item in company_rows if int(row["rank"]) == 5
        )
        foreign_jv = additional_top20[month]["foreign_jv"]
        total_row = next(item for item in company_bridge["totals"] if item["month"] == month)
        total = total_row["brand_method_point_10k"]["production_10k"]
        unidentified = (
            total - identified_chinese - chinese_brand_jv - foreign_wholly - foreign_jv
        )
        supplemental_low = identified_chinese + chinese_brand_jv
        supplemental_high = supplemental_low + unidentified
        result.append(
            {
                "month": month,
                "brand_total_10k": _round(total),
                "identified_chinese_system_10k": _round(identified_chinese),
                "identified_chinese_brand_jv_10k": _round(chinese_brand_jv),
                "identified_foreign_brand_jv_10k": _round(foreign_jv),
                "foreign_wholly_owned_10k": _round(foreign_wholly),
                "unidentified_tail_10k": _round(unidentified),
                "supplemental_chinese_scope_10k": {
                    "low": _round(supplemental_low),
                    "point": _round((supplemental_low + supplemental_high) / 2.0),
                    "high": _round(supplemental_high),
                },
            }
        )
    return result


def _method_forecasts(
    industry: dict[str, Any], brand: dict[str, Any], upstream: dict[str, Any]
) -> dict[str, dict[str, dict[str, float]]]:
    rows: dict[str, dict[str, dict[str, float]]] = {}
    for row in industry["forecasts"]:
        rows.setdefault(row["month"], {})["industry_total"] = {
            "low": float(row["production"]["low"]),
            "point": float(row["production"]["point"]),
            "high": float(row["production"]["high"]),
        }
    for row in brand["industry_forecast"]:
        rows.setdefault(row["month"], {})["brand_bottom_up"] = {
            "low": float(row["production_k"]["low"]) / 10.0,
            "point": float(row["production_k"]["base"]) / 10.0,
            "high": float(row["production_k"]["high"]) / 10.0,
        }
    for row in _upstream_forecast_bridge(upstream):
        rows.setdefault(row["month"], {})["upstream_leading"] = {
            "low": float(row["production_10k"]["low"]),
            "point": float(row["production_10k"]["point"]),
            "high": float(row["production_10k"]["high"]),
        }
    return rows


def _industry_forecast_bridge(industry: dict[str, Any]) -> list[dict[str, Any]]:
    history = {row["month"]: row for row in industry["monthly_observations"]}
    july_point = float(industry["july_2026_high_frequency"]["working_estimate"]["production"]["point"])
    seasonal = {
        "2026-08": float(history["2025-08"]["production"]) / float(history["2025-07"]["production"]),
        "2026-09": float(history["2025-09"]["production"]) / float(history["2025-08"]["production"]),
        "2026-10": float(history["2025-10"]["production"]) / float(history["2025-09"]["production"]),
    }
    previous = july_point
    result: list[dict[str, Any]] = []
    forecasts = {row["month"]: row for row in industry["forecasts"]}
    for month in MONTHS:
        raw_seasonal = previous * seasonal[month]
        point = float(forecasts[month]["production"]["point"])
        result.append(
            {
                "month": month,
                "previous_month_point_10k": _round(previous),
                "same_period_seasonal_factor": _round(seasonal[month], 4),
                "raw_seasonal_point_10k": _round(raw_seasonal),
                "demand_export_inventory_adjustment_10k": _round(point - raw_seasonal),
                "production_10k": {
                    band: _round(float(forecasts[month]["production"][band]))
                    for band in ("low", "point", "high")
                },
                "retail_10k": {
                    band: _round(float(forecasts[month]["retail"][band]))
                    for band in ("low", "point", "high")
                },
                "export_10k": {
                    band: _round(float(forecasts[month]["export"][band]))
                    for band in ("low", "point", "high")
                },
                "inventory_10k": {
                    band: _round(float(forecasts[month]["system_inventory_flow"][band]))
                    for band in ("low", "point", "high")
                },
            }
        )
        previous = point
    return result


def _upstream_forecast_bridge(upstream: dict[str, Any]) -> list[dict[str, Any]]:
    intercept = 30.8279
    slope = 1.48028
    rmse = float(upstream["model"]["backtest"]["leave_one_out_rmse_10k"])
    result: list[dict[str, Any]] = []
    for row in upstream["forecast"]:
        battery_low = float(row["battery_installation_assumption_gwh"]["low"])
        battery_high = float(row["battery_installation_assumption_gwh"]["high"])
        battery_point = (float(row["central_10k_units"]) - intercept) / slope
        raw_low = intercept + slope * battery_low
        raw_point = intercept + slope * battery_point
        raw_high = intercept + slope * battery_high
        result.append(
            {
                "month": row["month"],
                "battery_installation_gwh": {
                    "low": _round(battery_low),
                    "point": _round(battery_point, 3),
                    "high": _round(battery_high),
                },
                "regression_output_before_error_10k": {
                    "low": _round(raw_low),
                    "point": _round(raw_point),
                    "high": _round(raw_high),
                },
                "error_extension_10k": _round(rmse, 2),
                "production_10k": {
                    "low": _round(raw_low - rmse, 0),
                    "point": _round(raw_point, 0),
                    "high": _round(raw_high + rmse, 0),
                },
                "rule": "上下界=回归对应装车量边界±逐月留一RMSE；中值由中心装车量代入回归。",
            }
        )
    return result


def _weighted_ensemble(
    forecasts: dict[str, dict[str, dict[str, float]]],
    industry: dict[str, Any],
) -> list[dict[str, Any]]:
    industry_by_month = {row["month"]: row for row in industry["forecasts"]}
    results: list[dict[str, Any]] = []
    previous_point = _decimal(
        industry["july_2026_high_frequency"]["working_estimate"]["production"]["point"]
    )
    history_by_month = {row["month"]: row for row in industry["monthly_observations"]}
    for month in sorted(forecasts):
        methods = forecasts[month]
        for required in METHOD_WEIGHTS:
            if required not in methods:
                raise ValueError(f"{month} 缺少独立方法 {required}")
        production = {
            band: sum(
                (
                    _decimal(METHOD_WEIGHTS[key]) * _decimal(methods[key][band])
                    for key in METHOD_WEIGHTS
                ),
                Decimal("0"),
            )
            for band in ("low", "point", "high")
        }
        industry_row = industry_by_month[month]
        retail = {key: _decimal(value) for key, value in industry_row["retail"].items()}
        exports = {key: _decimal(value) for key, value in industry_row["export"].items()}
        wholesale = {key: _decimal(value) for key, value in industry_row["wholesale"].items()}
        inventory_point = production["point"] - retail["point"] - exports["point"]
        # 库存区间使用三项边界的可行组合；它反映口径和预测误差，不是统计置信区间。
        inventory_low = production["low"] - retail["high"] - exports["high"]
        inventory_high = production["high"] - retail["low"] - exports["low"]
        comparable_month = f"2025-{month[-2:]}"
        yoy_base = history_by_month.get(comparable_month, {}).get("production")
        results.append(
            {
                "month": month,
                # 合成与库存桥保留两位小数，避免各分项先舍入后破坏恒等式；
                # 公开结论可以再按整万辆展示，但冻结账本必须严格闭合。
                "production_10k": {key: _round(value, 2) for key, value in production.items()},
                "wholesale_10k": {key: _round(value, 2) for key, value in wholesale.items()},
                "domestic_retail_10k": {key: _round(value, 2) for key, value in retail.items()},
                "china_factory_export_10k": {key: _round(value, 2) for key, value in exports.items()},
                "system_inventory_flow_10k": {
                    "low": _round(inventory_low, 2),
                    "point": _round(inventory_point, 2),
                    "high": _round(inventory_high, 2),
                },
                "mom_pct": _round(
                    (production["point"] / previous_point - Decimal("1")) * Decimal("100")
                ),
                "yoy_pct": (
                    _round(
                        (production["point"] / _decimal(yoy_base) - Decimal("1"))
                        * Decimal("100")
                    )
                    if yoy_base
                    else None
                ),
                "method_inputs_10k": {
                    key: {band: _round(value) for band, value in methods[key].items()}
                    for key in METHOD_WEIGHTS
                },
                "method_union_10k": {
                    "low": _round(min(value["low"] for value in methods.values())),
                    "high": _round(max(value["high"] for value in methods.values())),
                },
            }
        )
        previous_point = production["point"]
    return results


def _checks(
    method_forecasts: dict[str, dict[str, dict[str, float]]],
    ensemble: list[dict[str, Any]],
    industry: dict[str, Any],
    company_bridge: dict[str, Any],
    ownership_bridge: list[dict[str, Any]],
    upstream_bridge: list[dict[str, Any]],
) -> dict[str, Any]:
    weight_sum = sum(METHOD_WEIGHTS.values())
    balance_errors = []
    for row in ensemble:
        observed = (
            float(row["production_10k"]["point"])
            - float(row["domestic_retail_10k"]["point"])
            - float(row["china_factory_export_10k"]["point"])
        )
        balance_errors.append(abs(observed - float(row["system_inventory_flow_10k"]["point"])))
    historical_errors = []
    for row in industry["monthly_observations"]:
        expected = float(row["production"]) - float(row["retail"]) - float(row["export"])
        historical_errors.append(abs(expected - float(row["system_inventory_flow"])))
    ordered = [row["month"] for row in ensemble]
    company_balance_errors = []
    for company in company_bridge["companies"]:
        for row in company["months"]:
            observed = (
                float(row["production_10k"]["point"])
                - float(row["domestic_sales_10k"]["point"])
                - float(row["china_factory_export_10k"]["point"])
            )
            company_balance_errors.append(
                abs(observed - float(row["inventory_change_10k"]["point"]))
            )
    ownership_balance_errors = []
    for row in ownership_bridge:
        parts = (
            float(row["identified_chinese_system_10k"])
            + float(row["identified_chinese_brand_jv_10k"])
            + float(row["identified_foreign_brand_jv_10k"])
            + float(row["foreign_wholly_owned_10k"])
            + float(row["unidentified_tail_10k"])
        )
        ownership_balance_errors.append(abs(parts - float(row["brand_total_10k"])))
    upstream_formula_errors = []
    upstream_interval_errors = []
    for row in upstream_bridge:
        battery = row["battery_installation_gwh"]
        raw = row["regression_output_before_error_10k"]
        for bound in ("low", "point", "high"):
            expected = 30.8279 + 1.48028 * float(battery[bound])
            upstream_formula_errors.append(abs(expected - float(raw[bound])))
        upstream_interval_errors.extend(
            [
                abs(
                    float(row["production_10k"]["low"])
                    - (float(raw["low"]) - float(row["error_extension_10k"]))
                ),
                abs(
                    float(row["production_10k"]["high"])
                    - (float(raw["high"]) + float(row["error_extension_10k"]))
                ),
            ]
        )
    return {
        "method_weight_sum": _round(weight_sum, 6),
        "method_weight_sum_pass": abs(weight_sum - 1.0) < 1e-12,
        "three_methods_each_month_pass": all(
            set(methods) == set(METHOD_WEIGHTS) for methods in method_forecasts.values()
        ),
        "months_order_pass": ordered == ["2026-08", "2026-09", "2026-10"],
        "forecast_balance_max_error_10k": _round(max(balance_errors), 6),
        "forecast_balance_pass": max(balance_errors) <= 0.11,
        "history_balance_max_error_10k": _round(max(historical_errors), 6),
        "history_balance_pass": max(historical_errors) <= 0.11,
        "company_point_balance_max_error_10k": _round(max(company_balance_errors), 6),
        "company_point_balance_pass": max(company_balance_errors) <= 1e-9,
        "ownership_reconciliation_max_error_10k": _round(max(ownership_balance_errors), 6),
        "ownership_reconciliation_pass": max(ownership_balance_errors) <= 0.11,
        "upstream_regression_max_error_10k": _round(max(upstream_formula_errors), 6),
        "upstream_regression_pass": max(upstream_formula_errors) <= 0.11,
        "upstream_interval_rounding_max_error_10k": _round(max(upstream_interval_errors), 6),
        "upstream_interval_rounding_pass": max(upstream_interval_errors) <= 0.51,
        "interval_order_pass": all(
            row["production_10k"]["low"]
            <= row["production_10k"]["point"]
            <= row["production_10k"]["high"]
            for row in ensemble
        ),
    }


def build_model() -> dict[str, Any]:
    industry = _read_json(METHOD_INPUTS["industry_total"])
    brand = _read_json(METHOD_INPUTS["brand_bottom_up"])
    upstream = _read_json(METHOD_INPUTS["upstream_leading"])
    industry_bridge = _industry_forecast_bridge(industry)
    company_bridge = _company_bridge(brand)
    ownership_bridge = _ownership_bridge(company_bridge)
    upstream_bridge = _upstream_forecast_bridge(upstream)
    forecasts = _method_forecasts(industry, brand, upstream)
    ensemble = _weighted_ensemble(forecasts, industry)
    checks = _checks(
        forecasts,
        ensemble,
        industry,
        company_bridge,
        ownership_bridge,
        upstream_bridge,
    )
    if not all(value for key, value in checks.items() if key.endswith("_pass")):
        raise ValueError(f"Run18 模型复算未通过: {checks}")
    return {
        "schema_version": "opportunity_lens.nev_three_method_model.v1",
        "research_cutoff": "2026-08-03T12:00:00+08:00",
        "scope": {
            "primary": "中国境内工厂生产的新能源乘用车，含自主、合资、特斯拉上海及中国工厂出口，排除进口和海外工厂本地产量",
            "supplement": "剔除外企及外国品牌合资体系后的中国企业/自主品牌生产口径",
            "vehicle_type": "纯电动、插电式混合动力和增程式乘用车",
        },
        "input_artifacts": {
            key: {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _sha256(path),
            }
            for key, path in METHOD_INPUTS.items()
        },
        "method_weights": METHOD_WEIGHTS,
        "method_dependence_note": "三种口径分别建模和复算，但共享乘联分会历史总量、6月厂商基线或整车产量序列，不是统计学意义上的独立样本。",
        "weight_rationale": {
            "industry_total": "直接闭合产量、批发、国内零售、出口和库存，且12个月口径一致，给予45%。",
            "brand_bottom_up": "覆盖6月主要生产主体约87.82%，但集团、品牌和工厂归属仍有错配风险，给予30%。",
            "upstream_leading": "动力电池装车与整车产量同期相关性高、回测较好，但提前一月信号弱，给予25%。",
        },
        "formulae": {
            "ensemble": "综合产量 = 45%×行业总量法 + 30%×品牌/工厂法 + 25%×动力电池校准法",
            "inventory": "生产体系库存变化 = 中国境内产量 - 国内零售 - 中国工厂出口",
            "manufacturer_inventory": "厂商库存变化 = 产量 - 厂商批发",
            "channel_inventory": "渠道库存变化 = 国内批发 - 国内零售，其中国内批发约等于厂商批发减中国工厂出口",
        },
        "industry_forecast_bridge": industry_bridge,
        "brand_company_bridge": company_bridge,
        "ownership_bridge": ownership_bridge,
        "upstream_forecast_bridge": upstream_bridge,
        "history_12m": industry["monthly_observations"],
        "july_2026_high_frequency": industry["july_2026_high_frequency"],
        "method_forecasts": forecasts,
        "ensemble_forecast": ensemble,
        "autonomous_supplement": [
            {
                "month": row["month"],
                "production_10k": row["supplemental_chinese_scope_10k"],
                "share_of_brand_method_point_pct": _round(
                    row["supplemental_chinese_scope_10k"]["point"] / row["brand_total_10k"] * 100.0
                ),
                "share_of_total_point_pct": _round(
                    row["supplemental_chinese_scope_10k"]["point"]
                    / next(item["production_10k"]["point"] for item in ensemble if item["month"] == row["month"])
                    * 100.0
                ),
                "brand_denominator": "品牌/工厂法中国生产总量",
                "total_denominator": "三法加权中国境内总产量；仅为兼容指标，公开正文不与品牌法分母混写",
            }
            for row in ownership_bridge
        ],
        "brand_coverage": brand["coverage"],
        "upstream_model_diagnostics": upstream["model"],
        "upstream_concentration": upstream["concentration"],
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 Run18 新能源汽车三口径冻结模型")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    payload = build_model()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output), "sha256": _sha256(args.output), "checks": payload["checks"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
