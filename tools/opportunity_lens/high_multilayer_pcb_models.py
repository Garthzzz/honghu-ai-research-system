from __future__ import annotations

"""Auditable supply-demand calculations for the >=18-layer PCB research."""

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping


YEARS = tuple(range(2026, 2031))
SCENARIO_ORDER = ("conservative", "base", "optimistic")
SCENARIO_CHINA_SHARE_BAND = {
    "conservative": "low",
    "base": "base",
    "optimistic": "high",
}


def _interpolate(start: float, end: float, year: int) -> float:
    return start + (end - start) * ((year - 2026) / 4.0)


def _finite(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def calculate(inputs: Mapping[str, Any]) -> dict[str, Any]:
    scenarios = inputs["scenarios"]
    if tuple(scenarios) != SCENARIO_ORDER:
        raise ValueError("scenarios must be conservative, base and optimistic in order")
    mix_endpoints = inputs["architecture_mix_endpoints"]
    area_endpoints = inputs["strict_area_m2_per_server_endpoint"]
    architectures = tuple(mix_endpoints["2026"])
    if set(architectures) != set(mix_endpoints["2030"]):
        raise ValueError("architecture endpoint keys differ")
    for endpoint in ("2026", "2030"):
        if abs(sum(float(v) for v in mix_endpoints[endpoint].values()) - 1.0) > 1e-9:
            raise ValueError(f"architecture mix for {endpoint} must sum to one")
        if set(area_endpoints[endpoint]) != set(architectures):
            raise ValueError(f"area endpoint keys differ for {endpoint}")

    yearly_architecture: dict[str, Any] = {}
    for year in YEARS:
        mix = {
            key: _interpolate(
                _finite(mix_endpoints["2026"][key], f"mix.{key}.2026"),
                _finite(mix_endpoints["2030"][key], f"mix.{key}.2030"),
                year,
            )
            for key in architectures
        }
        area = {
            key: _interpolate(
                _finite(area_endpoints["2026"][key], f"area.{key}.2026"),
                _finite(area_endpoints["2030"][key], f"area.{key}.2030"),
                year,
            )
            for key in architectures
        }
        weighted_area = sum(mix[key] * area[key] for key in architectures)
        yearly_architecture[str(year)] = {
            "mix": {key: round(value, 6) for key, value in mix.items()},
            "strict_area_m2_per_server": {key: round(value, 6) for key, value in area.items()},
            "weighted_strict_area_m2_per_server": round(weighted_area, 6),
        }

    result_scenarios: dict[str, Any] = {}
    for scenario_key in SCENARIO_ORDER:
        specification = scenarios[scenario_key]
        china_share_band = SCENARIO_CHINA_SHARE_BAND[scenario_key]
        if china_share_band not in inputs["china_end_demand_share"]:
            raise ValueError(f"missing china demand share band: {china_share_band}")
        units = _finite(inputs["ai_server_anchor"]["units_million"], "anchor units")
        rows = []
        for year in YEARS:
            year_key = str(year)
            units *= 1.0 + _finite(
                specification["annual_unit_growth"][year_key],
                f"{scenario_key}.{year}.growth",
            )
            effective_area = (
                yearly_architecture[year_key]["weighted_strict_area_m2_per_server"]
                * _finite(specification["area_multiplier"], f"{scenario_key}.area_multiplier")
            )
            demand_area_million_m2 = units * effective_area
            asp = (
                _finite(inputs["strict_asp_usd_per_m2"][year_key], f"asp.{year}")
                * _finite(specification["asp_multiplier"], f"{scenario_key}.asp_multiplier")
            )
            demand_value = demand_area_million_m2 * asp / 1000.0
            market_reference = _finite(
                inputs["noncomparable_22plus_market_reference_usd_bn"][year_key],
                f"noncomparable market reference.{year}",
            )
            china_share = _finite(
                inputs["china_end_demand_share"][china_share_band][year_key],
                f"china share.{china_share_band}.{year}",
            )
            rows.append(
                {
                    "year": year,
                    "ai_server_units_million": round(units, 4),
                    "weighted_strict_area_m2_per_server": round(effective_area, 4),
                    "strict_demand_area_million_m2": round(demand_area_million_m2, 4),
                    "strict_plus_local_hdi_area_million_m2": round(
                        demand_area_million_m2
                        * _finite(inputs["local_hdi_composite_multiplier"], "HDI multiplier"),
                        4,
                    ),
                    "blended_asp_usd_per_m2": round(asp, 2),
                    "bottom_up_demand_usd_bn": round(demand_value, 4),
                    "noncomparable_22plus_market_reference_usd_bn": round(market_reference, 4),
                    "china_end_demand_share_assumption": round(china_share, 4),
                    "china_end_demand_usd_bn": round(demand_value * china_share, 4),
                    "overseas_end_demand_usd_bn": round(demand_value * (1.0 - china_share), 4),
                }
            )
        result_scenarios[scenario_key] = {
            "label": specification["label"],
            "china_end_demand_share_band": china_share_band,
            "rows": rows,
        }

    base_rows = result_scenarios["base"]["rows"]
    base_anchor_area = _finite(
        base_rows[0]["strict_demand_area_million_m2"],
        "conditional supply anchor area",
    )
    conditional_supply_paths: dict[str, Any] = {}
    for path_key, path_specification in inputs["conditional_qualified_supply_area_growth"].items():
        annual_growth = _finite(path_specification["annual_growth"], f"supply path.{path_key}")
        rows = []
        for index, demand_row in enumerate(base_rows):
            supply_area = base_anchor_area * ((1.0 + annual_growth) ** index)
            demand_area = _finite(
                demand_row["strict_demand_area_million_m2"],
                f"base demand area.{demand_row['year']}",
            )
            balance = supply_area - demand_area
            rows.append(
                {
                    "year": demand_row["year"],
                    "base_demand_area_million_m2": round(demand_area, 4),
                    "conditional_supply_area_million_m2": round(supply_area, 4),
                    "conditional_supply_minus_demand_area_million_m2": round(balance, 4),
                    "conditional_supply_demand_ratio": round(supply_area / demand_area, 4),
                }
            )
        conditional_supply_paths[path_key] = {
            "label": path_specification["label"],
            "annual_growth": annual_growth,
            "anchor_rule": "假设2026年完成认证的有效供给面积恰好等于基准需求面积；不是实际供给统计",
            "rows": rows,
        }

    required_supply_area_cagr = (
        (base_rows[-1]["strict_demand_area_million_m2"] / base_anchor_area)
        ** (1.0 / (len(YEARS) - 1))
        - 1.0
    )
    cross_check = {
        "scenario_ordering_2030": (
            result_scenarios["conservative"]["rows"][-1]["bottom_up_demand_usd_bn"]
            < result_scenarios["base"]["rows"][-1]["bottom_up_demand_usd_bn"]
            < result_scenarios["optimistic"]["rows"][-1]["bottom_up_demand_usd_bn"]
        ),
        "base_required_effective_supply_area_cagr_2026_2030": round(required_supply_area_cagr, 6),
        "noncomparable_22plus_market_reference_used_as_supply_denominator": False,
        "conditional_supply_anchor_is_observed": False,
    }
    if not cross_check["scenario_ordering_2030"]:
        raise ValueError(f"cross-check failed: {cross_check}")
    return {
        "schema_version": "high_multilayer_pcb_supply_demand_outputs.v1",
        "as_of_date": inputs["as_of_date"],
        "scope": inputs["scope"],
        "yearly_architecture": yearly_architecture,
        "scenarios": result_scenarios,
        "conditional_supply_paths": conditional_supply_paths,
        "cross_check": cross_check,
        "assumption_status": inputs["assumption_status"],
        "method_note": (
            "节点数乘以各架构中18层以上刚性板的有效面积，再乘以校准后单价，得到AI服务器需求；"
            "由于公开资料没有同口径的18层以上有效供给面积，供给部分只计算一个条件门槛：假设2026年供需平衡，"
            "有效供给面积此后至少需要以多快速度增长才能追上基准需求。CIC的22层以上全应用市场与本研究的18层以上AI需求集合不一致，"
            "只作为口径冲突背景，不参与供给、缺口、价格或毛利计算。"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    inputs = json.loads(args.inputs.read_text(encoding="utf-8"))
    outputs = calculate(inputs)
    text = json.dumps(outputs, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
