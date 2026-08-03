from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping


SQ_MM_PER_SQ_IN = 25.4**2


def _finite(value: Any, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是有限数值") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} 必须是有限数值")
    return number


def _ratio(value: Any, *, name: str, upper: float = 1.0) -> float:
    number = _finite(value, name=name)
    if not 0 <= number <= upper:
        raise ValueError(f"{name} 必须位于 0 到 {upper} 之间")
    return number


def wafer_area_square_inches(diameter_mm: float) -> float:
    """Return geometric wafer area in square inches."""
    diameter = _finite(diameter_mm, name="diameter_mm")
    if diameter <= 0:
        raise ValueError("diameter_mm 必须大于 0")
    radius_mm = diameter / 2
    return math.pi * radius_mm**2 / SQ_MM_PER_SQ_IN


def msi_to_million_wafers(msi: float, *, diameter_mm: float) -> float:
    """Convert million square inches to million wafers of one diameter."""
    area = wafer_area_square_inches(diameter_mm)
    return _finite(msi, name="msi") / area


def msi_to_average_wspm(msi: float, *, diameter_mm: float) -> float:
    """Convert annual MSI shipments to the equivalent average monthly starts."""
    return msi_to_million_wafers(msi, diameter_mm=diameter_mm) * 1_000_000 / 12


def native_wspm_to_300mm_equivalent(wspm: float, *, diameter_mm: float) -> float:
    """Area-equivalent monthly starts, preserving native starts outside this helper."""
    starts = _finite(wspm, name="wspm")
    if starts < 0:
        raise ValueError("wspm 不能为负数")
    return starts * (float(diameter_mm) / 300.0) ** 2


def extrapolate_msi(
    anchor_msi: float,
    annual_growth: Mapping[int | str, float],
    *,
    anchor_year: int,
) -> dict[int, float]:
    """Extend an observed/forecast anchor using explicit analyst scenario rates."""
    values = {int(anchor_year): _finite(anchor_msi, name="anchor_msi")}
    previous = values[int(anchor_year)]
    for raw_year, raw_growth in sorted(annual_growth.items(), key=lambda item: int(item[0])):
        year = int(raw_year)
        if year <= anchor_year:
            raise ValueError("外推年份必须晚于锚点年份")
        if year != max(values) + 1:
            raise ValueError("外推年份必须连续")
        growth = _ratio(raw_growth, name=f"growth[{year}]", upper=1.0)
        previous *= 1 + growth
        values[year] = previous
    return values


def calculate_project_demand(
    projects: Iterable[Mapping[str, Any]],
    *,
    years: Iterable[int],
) -> dict[str, Any]:
    """Calculate effective substrate procurement from disclosed nominal WSPM.

    WSPM is treated as input wafer starts. Manufacturing yield is deliberately not
    multiplied into demand. Any purchase timing adjustment must be supplied as a
    separately named inventory/procurement coefficient and is capped at 0.75-1.25.
    """
    ordered_years = sorted({int(year) for year in years})
    totals_native = {year: 0.0 for year in ordered_years}
    totals_300eq = {year: 0.0 for year in ordered_years}
    by_project: list[dict[str, Any]] = []

    for index, project in enumerate(projects):
        name = str(project.get("project_name") or "").strip()
        if not name:
            raise ValueError(f"projects[{index}].project_name 不能为空")
        nominal_wspm = _finite(project.get("nominal_wspm"), name=f"{name}.nominal_wspm")
        if nominal_wspm < 0:
            raise ValueError(f"{name}.nominal_wspm 不能为负数")
        diameter = _finite(project.get("diameter_mm"), name=f"{name}.diameter_mm")
        if diameter not in {150.0, 200.0, 300.0}:
            raise ValueError(f"{name}.diameter_mm 仅接受 150/200/300")
        ramp = project.get("ramp_by_year") or {}
        utilization = project.get("utilization_by_year") or {}
        procurement = project.get("procurement_adjustment_by_year") or {}
        rows: list[dict[str, Any]] = []
        for year in ordered_years:
            ramp_ratio = _ratio(ramp.get(str(year), ramp.get(year, 0.0)), name=f"{name}.ramp[{year}]")
            utilization_ratio = _ratio(
                utilization.get(str(year), utilization.get(year, 0.0)),
                name=f"{name}.utilization[{year}]",
            )
            procurement_ratio = _finite(
                procurement.get(str(year), procurement.get(year, 1.0)),
                name=f"{name}.procurement_adjustment[{year}]",
            )
            if not 0.75 <= procurement_ratio <= 1.25:
                raise ValueError(f"{name}.procurement_adjustment[{year}] 必须位于 0.75 到 1.25")
            annual_native = nominal_wspm * 12 * ramp_ratio * utilization_ratio * procurement_ratio
            annual_300eq = native_wspm_to_300mm_equivalent(
                annual_native,
                diameter_mm=diameter,
            )
            totals_native[year] += annual_native
            totals_300eq[year] += annual_300eq
            rows.append(
                {
                    "year": year,
                    "annual_native_wafers": annual_native,
                    "annual_300mm_equivalent_wafers": annual_300eq,
                    "ramp_ratio": ramp_ratio,
                    "utilization_ratio": utilization_ratio,
                    "procurement_adjustment": procurement_ratio,
                }
            )
        by_project.append(
            {
                "project_name": name,
                "diameter_mm": diameter,
                "nominal_wspm": nominal_wspm,
                "annual_results": rows,
            }
        )

    return {
        "years": ordered_years,
        "by_project": by_project,
        "totals_native_wafers": totals_native,
        "totals_300mm_equivalent_wafers": totals_300eq,
        "method_note": (
            "年度采购量=名义月产能×12×当年爬坡比例×利用率×采购/库存时点修正；"
            "WSPM已经表示投入晶圆，因此未再乘制造良率。"
        ),
    }


def equipment_intensity_per_100k_wspm(
    intensity_rmb_per_annual_wafer: float,
) -> float:
    """Return CNY 100m required for each 100k WSPM at disclosed intensity."""
    intensity = _finite(
        intensity_rmb_per_annual_wafer,
        name="intensity_rmb_per_annual_wafer",
    )
    if intensity < 0:
        raise ValueError("设备投资强度不能为负数")
    annual_wafers = 100_000 * 12
    return intensity * annual_wafers / 100_000_000


def calculate_equipment_pool(
    capacity_projects: Iterable[Mapping[str, Any]],
    *,
    intensity_by_process: Mapping[str, Mapping[str, float]],
) -> list[dict[str, Any]]:
    """Estimate project equipment bands without fabricating machine counts.

    The output remains a process-level budget estimate. It does not allocate the
    budget to suppliers unless a separate, evidenced SAM/SOM step is provided.
    """
    output: list[dict[str, Any]] = []
    for index, project in enumerate(capacity_projects):
        name = str(project.get("project_name") or "").strip()
        process = str(project.get("process_type") or "").strip()
        if not name or not process:
            raise ValueError(f"capacity_projects[{index}] 缺少 project_name/process_type")
        monthly_capacity = _finite(project.get("incremental_wspm"), name=f"{name}.incremental_wspm")
        if monthly_capacity < 0:
            raise ValueError(f"{name}.incremental_wspm 不能为负数")
        parameters = intensity_by_process.get(process)
        if not parameters:
            raise ValueError(f"{name} 的工艺 {process!r} 没有投资强度")
        low = _finite(parameters.get("low"), name=f"{process}.low")
        base = _finite(parameters.get("base"), name=f"{process}.base")
        high = _finite(parameters.get("high"), name=f"{process}.high")
        if not 0 <= low <= base <= high:
            raise ValueError(f"{process} 投资强度必须满足 0 <= low <= base <= high")
        annualized = monthly_capacity * 12
        budget = {
            "low": annualized * low / 100_000_000,
            "base": annualized * base / 100_000_000,
            "high": annualized * high / 100_000_000,
        }
        row: dict[str, Any] = {
            "project_name": name,
            "process_type": process,
            "incremental_wspm": monthly_capacity,
            "equipment_budget_rmb_100m": budget,
        }
        if "conditional_execution_switch" in project:
            switch = _finite(
                project.get("conditional_execution_switch"),
                name=f"{name}.conditional_execution_switch",
            )
            if switch not in {0.0, 1.0}:
                raise ValueError(f"{name}.conditional_execution_switch 只能为0或1")
            row["conditional_execution_switch"] = int(switch)
            row["conditional_budget_rmb_100m"] = {
                scenario: value * switch for scenario, value in budget.items()
            }
        else:
            # 兼容已有调用。新研究若只是“项目完整建设/不建设”的条件情景，
            # 必须使用 conditional_execution_switch，不能把 1.0 伪装成概率。
            risk = _ratio(
                project.get("execution_probability", 1.0),
                name=f"{name}.execution_probability",
            )
            row["execution_probability"] = risk
            row["risk_adjusted_budget_rmb_100m"] = {
                scenario: value * risk for scenario, value in budget.items()
            }
        output.append(row)
    return output


def allocate_order_recognition(
    equipment_budget_rmb_100m: float,
    annual_weights: Mapping[int | str, float],
) -> dict[int, float]:
    """Allocate a fixed budget over order/delivery/acceptance years.

    Timing weights only distribute the budget; they never change equipment count
    or total market size.
    """
    budget = _finite(equipment_budget_rmb_100m, name="equipment_budget_rmb_100m")
    if budget < 0:
        raise ValueError("equipment_budget_rmb_100m 不能为负数")
    weights = {int(year): _ratio(value, name=f"annual_weights[{year}]") for year, value in annual_weights.items()}
    if not math.isclose(sum(weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("annual_weights 合计必须为 1")
    return {year: budget * weight for year, weight in sorted(weights.items())}


def calculate_equipment_scenarios(
    projects: Iterable[Mapping[str, Any]],
    *,
    years: Iterable[int],
) -> dict[str, Any]:
    """Aggregate project-level low/base/high equipment budgets and timing.

    Every project supplies an explicit amount for each scenario and one set of
    annual installation weights.  The function only propagates those inputs: it
    does not infer supplier share, order value, revenue recognition or profit.
    """
    ordered_years = sorted({int(year) for year in years})
    if not ordered_years:
        raise ValueError("years 不能为空")
    scenario_names = ("low", "base", "high")
    scenario_totals = {name: 0.0 for name in scenario_names}
    annual_totals = {
        year: {name: 0.0 for name in scenario_names}
        for year in ordered_years
    }
    by_project: list[dict[str, Any]] = []

    for index, project in enumerate(projects):
        name = str(project.get("project_name") or "").strip()
        if not name:
            raise ValueError(f"projects[{index}].project_name 不能为空")
        raw_amounts = project.get("scenario_amounts_rmb_100m") or {}
        amounts = {
            scenario: _finite(raw_amounts.get(scenario), name=f"{name}.{scenario}")
            for scenario in scenario_names
        }
        if not 0 <= amounts["low"] <= amounts["base"] <= amounts["high"]:
            raise ValueError(f"{name} 的情景金额必须满足 0 <= low <= base <= high")

        raw_weights = project.get("annual_weights") or {}
        weights = {
            int(year): _ratio(
                raw_weights.get(str(year), raw_weights.get(year, 0.0)),
                name=f"{name}.annual_weights[{year}]",
            )
            for year in ordered_years
        }
        if not math.isclose(sum(weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(f"{name}.annual_weights 合计必须为 1")

        annual_by_scenario: dict[str, dict[int, float]] = {}
        for scenario in scenario_names:
            allocation = allocate_order_recognition(amounts[scenario], weights)
            annual_by_scenario[scenario] = allocation
            scenario_totals[scenario] += amounts[scenario]
            for year, value in allocation.items():
                annual_totals[year][scenario] += value
        by_project.append(
            {
                "project_name": name,
                "scenario_amounts_rmb_100m": amounts,
                "annual_weights": weights,
                "annual_amounts_rmb_100m": annual_by_scenario,
            }
        )

    return {
        "scenarios_rmb_100m": scenario_totals,
        "annual_totals_rmb_100m": [
            {"year": year, **annual_totals[year]}
            for year in ordered_years
        ],
        "by_project": by_project,
        "method_note": (
            "先按项目计算低、中、高三种尚未发生的设备投入，再按明确的安装时点权重分配到年度；"
            "年度分配不改变项目总额，也不代表设备商订单、收入或利润。"
        ),
    }


def _demand_unit_reverse_checks(
    *,
    projects: Sequence[Mapping[str, Any]],
    aggregate_scenarios: Mapping[str, Mapping[str, Mapping[str, Any]]],
    anchor_2028: float,
) -> list[dict[str, Any]]:
    """Recalculate unit conversions from frozen project inputs, not code constants."""
    projects_by_id = {str(project["project_id"]): project for project in projects}
    checks: list[dict[str, Any]] = []
    agrate = projects_by_id.get("P029")
    if agrate and isinstance(agrate.get("capacity_derivation"), Mapping):
        raw = agrate["capacity_derivation"]
        start = _finite(raw.get("baseline_wafers_per_week"), name="P029.baseline_wafers_per_week")
        target = _finite(raw.get("target_wafers_per_week"), name="P029.target_wafers_per_week")
        weeks = _finite(raw.get("weeks_per_year"), name="P029.weeks_per_year")
        months = _finite(raw.get("months_per_year"), name="P029.months_per_year")
        result = round((target - start) * weeks / months)
        expected = round(_finite(agrate.get("nameplate_incremental_wspm"), name="P029.nameplate_incremental_wspm"))
        checks.append(
            {
                "check": "ST Agrate周产能转月产能",
                "formula": f"({target:g}-{start:g})×{weeks:g}÷{months:g}",
                "result": result,
                "expected": expected,
                "pass": result == expected,
            }
        )
    for project_id, project in projects_by_id.items():
        raw = project.get("capacity_derivation")
        if not isinstance(raw, Mapping) or raw.get("annual_wafers") is None:
            continue
        annual = _finite(raw.get("annual_wafers"), name=f"{project_id}.annual_wafers")
        months = _finite(raw.get("months_per_year"), name=f"{project_id}.months_per_year")
        result = annual / months
        expected = _finite(
            project.get("nameplate_incremental_wspm"),
            name=f"{project_id}.nameplate_incremental_wspm",
        )
        checks.append(
            {
                "check": f"{project['name']}年产能转月产能",
                "formula": f"{annual:g}÷{months:g}",
                "result": result,
                "expected": expected,
                "pass": math.isclose(result, expected),
            }
        )
    area_ratio = (300 / 200) ** 2
    checks.extend(
        [
            {
                "check": "300毫米对200毫米面积比",
                "formula": "(300÷200)^2",
                "result": area_ratio,
                "expected": 2.25,
                "pass": math.isclose(area_ratio, 2.25),
            },
            {
                "check": "300毫米2028公开锚点",
                "formula": "模型路径2028值",
                "result": aggregate_scenarios["base"]["2028"]["300mm_capacity_wspm"],
                "expected": round(anchor_2028),
                "pass": aggregate_scenarios["base"]["2028"]["300mm_capacity_wspm"] == round(anchor_2028),
            },
        ]
    )
    return checks


def calculate_wafer_demand_scenarios(
    inputs: Mapping[str, Any],
    *,
    total_project_count: int,
) -> dict[str, Any]:
    """Rebuild the demand model from its frozen, human-readable inputs.

    Aggregate installed capacity and bottom-up project procurement answer
    different questions and remain separate.  A yearly change in installed
    capacity is reported as an annualized run-rate, not as actual procurement
    booked during that calendar year.
    """
    scenarios = ("downside", "base", "upside")
    years = [int(year) for year in inputs.get("years") or range(2026, 2031)]
    if years != sorted(years) or not years:
        raise ValueError("demand model years 必须是非空升序列表")
    aggregate_inputs = inputs.get("public_aggregate_inputs") or {}
    post = inputs.get("post_2028_assumptions") or {}
    conversions = inputs.get("aggregate_conversion_assumptions") or {}
    prime_range = conversions.get("prime_wafer_procurement_range") or {}
    project_ramp = inputs.get("project_ramp_assumptions") or {}
    official_200_assumptions = inputs.get("official_200mm_model_assumptions") or {}
    backtest_inputs = inputs.get("forecast_backtest_inputs") or {}
    source_refs = inputs.get("source_refs_by_output") or {}

    anchor_2028 = _finite(
        aggregate_inputs.get("global_300mm_wspm_2028"),
        name="global_300mm_wspm_2028",
    )
    anchor_cagr = _ratio(
        aggregate_inputs.get("global_300mm_cagr_2024_2028"),
        name="global_300mm_cagr_2024_2028",
    )
    growth_2026 = _ratio(
        aggregate_inputs.get("current_300mm_growth_2026"),
        name="current_300mm_growth_2026",
    )
    growth_2027_2029 = _ratio(
        aggregate_inputs.get("current_300mm_growth_2027_2029"),
        name="current_300mm_growth_2027_2029",
    )
    inferred_2024 = anchor_2028 / ((1 + anchor_cagr) ** 4)
    common_path = {
        2024: inferred_2024,
        2025: inferred_2024 * (1 + anchor_cagr),
    }
    common_path[2026] = common_path[2025] * (1 + growth_2026)
    common_path[2027] = common_path[2026] * (1 + growth_2027_2029)
    common_path[2028] = anchor_2028
    implied_2028_growth = anchor_2028 / common_path[2027] - 1
    if abs(implied_2028_growth - growth_2027_2029) > 0.005:
        raise ValueError("300毫米2028锚点与2026—2029公开增速方向不一致")

    device_utilization = _ratio(
        conversions.get("device_utilization"),
        name="aggregate_conversion_assumptions.device_utilization",
    )
    range_parameters: dict[str, dict[str, float]] = {}
    for bound in ("low", "high"):
        raw_bound = prime_range.get(bound) or {}
        range_parameters[bound] = {
            "utilization": _ratio(
                raw_bound.get("utilization"),
                name=f"prime_wafer_procurement_range.{bound}.utilization",
            ),
            "process_input_factor": _finite(
                raw_bound.get("process_input_factor"),
                name=f"prime_wafer_procurement_range.{bound}.process_input_factor",
            ),
            "inventory_factor": _finite(
                raw_bound.get("inventory_factor"),
                name=f"prime_wafer_procurement_range.{bound}.inventory_factor",
            ),
        }

    aggregate_scenarios: dict[str, dict[str, Any]] = {}
    for scenario in scenarios:
        path = dict(common_path)
        growth_2029 = _ratio(
            (post.get("global_300mm_growth_2029") or {}).get(scenario),
            name=f"global_300mm_growth_2029.{scenario}",
        )
        growth_2030 = _ratio(
            (post.get("global_300mm_growth_2030") or {}).get(scenario),
            name=f"global_300mm_growth_2030.{scenario}",
        )
        if scenario == "base" and abs(growth_2029 - growth_2027_2029) > 1e-12:
            raise ValueError("300毫米2029基准增速必须与当前SEMI约7%方向一致")
        path[2029] = path[2028] * (1 + growth_2029)
        path[2030] = path[2029] * (1 + growth_2030)
        result: dict[str, Any] = {}
        previous = path[2025]
        for year in years:
            incremental = max(path[year] - previous, 0.0)
            if year == 2028:
                input_type = "SEMI公开绝对锚点"
            elif year <= 2027:
                input_type = "按SEMI 2028锚点、2024—2028复合增速及当前增速方向推算"
            elif year == 2029:
                input_type = "SEMI约7%方向与情景敏感性"
            else:
                input_type = "研究情景假设"
            lower = range_parameters["low"]
            upper = range_parameters["high"]
            result[str(year)] = {
                "300mm_capacity_wspm": round(path[year]),
                "incremental_installed_wspm_vs_previous_year": round(incremental),
                "annualized_device_wafer_start_run_rate": round(
                    incremental * 12 * device_utilization
                ),
                "device_utilization_assumption": device_utilization,
                "annualized_prime_wafer_procurement_run_rate_range": [
                    round(
                        incremental
                        * 12
                        * lower["utilization"]
                        * lower["process_input_factor"]
                        * lower["inventory_factor"]
                    ),
                    round(
                        incremental
                        * 12
                        * upper["utilization"]
                        * upper["process_input_factor"]
                        * upper["inventory_factor"]
                    ),
                ],
                "input_type": input_type,
            }
            previous = path[year]
        aggregate_scenarios[scenario] = result
    aggregate = {
        "source_ids": list(source_refs.get("aggregate_300mm") or []),
        "inferred_2024_300mm_wspm": round(inferred_2024),
        "inference_formula": f"{anchor_2028:g} ÷ (1 + {anchor_cagr:g})^4",
        "intermediate_year_disclosure": (
            "2026—2027绝对值是按SEMI 2028年锚点、2024—2028年复合增速和当前约7%增速方向推算，"
            "不是SEMI逐年直接披露的绝对值。"
        ),
        "inferred_2024_to_2028_incremental_wspm": round(anchor_2028 - inferred_2024),
        "inferred_2024_to_2028_incremental_nameplate_wafers_per_year": round(
            (anchor_2028 - inferred_2024) * 12
        ),
        "conversion_assumptions": conversions,
        "scenarios": aggregate_scenarios,
    }

    projects = list(inputs.get("bottom_up_disclosed_increment_projects") or [])
    inventory_factors = inputs.get("inventory_factors") or {}
    process_factors = inputs.get("process_input_factors") or {}
    initial_shares = project_ramp.get("year_end_nameplate_share_at_production_year") or {}
    operating_utilizations = project_ramp.get("operating_utilization_of_installed_capacity") or {}
    bottom_up: dict[str, Any] = {}

    def _year_end_share(year: int, *, production_year: int, full_capacity_year: int, initial: float) -> float:
        if year < production_year:
            return 0.0
        if full_capacity_year <= production_year or year >= full_capacity_year:
            return 1.0
        elapsed = year - production_year
        duration = full_capacity_year - production_year
        return initial + (1.0 - initial) * elapsed / duration

    for scenario in scenarios:
        initial_share = _ratio(
            initial_shares.get(scenario),
            name=f"year_end_nameplate_share_at_production_year.{scenario}",
        )
        operating_utilization = _ratio(
            operating_utilizations.get(scenario),
            name=f"operating_utilization_of_installed_capacity.{scenario}",
        )
        inventory = _finite(
            inventory_factors.get(scenario),
            name=f"inventory_factors.{scenario}",
        )
        annual: dict[int, dict[str, float]] = {
            year: {"mature_logic_300mm": 0.0, "analog_power_300mm": 0.0, "total": 0.0}
            for year in years
        }
        by_project: list[dict[str, Any]] = []
        for project in projects:
            segment = str(project["segment"])
            process_factor = _finite(
                process_factors.get(segment),
                name=f"process_input_factors.{segment}",
            )
            nameplate = _finite(
                project.get("nameplate_incremental_wspm"),
                name=f"{project.get('project_id')}.nameplate_incremental_wspm",
            )
            production_year_by_scenario = project.get("production_year_by_scenario") or {}
            production_year = int(
                production_year_by_scenario.get(scenario, project.get("production_year"))
            )
            full_capacity_year = int(project["full_capacity_year"])
            if full_capacity_year < production_year:
                raise ValueError(f"{project.get('project_id')} 满产年份早于投产年份")
            project_rows: list[dict[str, Any]] = []
            for year in years:
                prior_share = _year_end_share(
                    year - 1,
                    production_year=production_year,
                    full_capacity_year=full_capacity_year,
                    initial=initial_share,
                )
                year_end_share = _year_end_share(
                    year,
                    production_year=production_year,
                    full_capacity_year=full_capacity_year,
                    initial=initial_share,
                )
                average_installed_share = (prior_share + year_end_share) / 2
                effective_utilization = average_installed_share * operating_utilization
                procurement = nameplate * 12 * effective_utilization * process_factor * inventory
                if segment not in annual[year]:
                    annual[year][segment] = 0.0
                annual[year][segment] += procurement
                annual[year]["total"] += procurement
                project_rows.append(
                    {
                        "year": year,
                        "year_end_nameplate_share": round(year_end_share, 4),
                        "annual_average_installed_nameplate_share": round(average_installed_share, 4),
                        "operating_utilization_of_installed_capacity": operating_utilization,
                        "effective_annual_average_nameplate_utilization": round(effective_utilization, 4),
                        "annual_average_ramp_utilization": round(effective_utilization, 4),
                        "annual_prime_wafer_procurement": round(procurement),
                    }
                )
            by_project.append(
                {
                    "project_id": project["project_id"],
                    "name": project["name"],
                    "production_year_used": production_year,
                    "full_capacity_year": full_capacity_year,
                    "annual": project_rows,
                }
            )
        bottom_up[scenario] = {
            "ramp_assumptions": {
                "year_end_share_in_production_year": initial_share,
                "operating_utilization_of_installed_capacity": operating_utilization,
                "annual_average_method": "年初与年末已安装名义能力比例的平均值，再乘已安装能力的运行利用率",
            },
            "by_project": by_project,
            "by_year": [
                {
                    "year": year,
                    "mature_logic_300mm": round(annual[year].get("mature_logic_300mm", 0.0)),
                    "analog_power_300mm": round(annual[year].get("analog_power_300mm", 0.0)),
                    "total_prime_wafers": round(annual[year]["total"]),
                }
                for year in years
            ],
        }

    base_200 = {
        2026: _finite(
            aggregate_inputs.get("current_200mm_wspm_2026"),
            name="current_200mm_wspm_2026",
        )
    }
    for year in (2027, 2028, 2029):
        growth = _ratio(
            aggregate_inputs.get(f"current_200mm_growth_{year}"),
            name=f"current_200mm_growth_{year}",
        )
        base_200[year] = base_200[year - 1] * (1 + growth)
    growth_200_2030 = official_200_assumptions.get("growth_2030") or {}
    utilization_200 = _ratio(
        official_200_assumptions.get("utilization"),
        name="official_200mm_model_assumptions.utilization",
    )
    process_200 = _finite(
        official_200_assumptions.get("process_input_factor"),
        name="official_200mm_model_assumptions.process_input_factor",
    )
    growth_200_2026 = _ratio(
        aggregate_inputs.get("current_200mm_growth_2026"),
        name="current_200mm_growth_2026",
    )
    official_200: dict[str, Any] = {}
    for scenario in scenarios:
        path = dict(base_200)
        path[2030] = path[2029] * (
            1 + _ratio(growth_200_2030.get(scenario), name=f"growth_2030.{scenario}")
        )
        previous = path[2026] / (1 + growth_200_2026)
        rows: list[dict[str, Any]] = []
        for year in years:
            incremental = path[year] - previous
            rows.append(
                {
                    "year": year,
                    "installed_200mm_wspm": round(path[year]),
                    "incremental_installed_wspm_vs_previous_year": round(incremental),
                    "annualized_prime_wafer_run_rate_from_new_capacity": round(
                        max(incremental, 0.0) * 12 * utilization_200 * process_200
                    ),
                    "input_type": "SEMI当前预测" if year <= 2029 else "研究情景假设",
                }
            )
            previous = path[year]
        official_200[scenario] = rows

    total_8in_2025 = _finite(
        aggregate_inputs.get("global_total_8in_eq_wspm_2025"),
        name="global_total_8in_eq_wspm_2025",
    )
    total_capacity = {2025: total_8in_2025}
    for year in (2026, 2027):
        growth = _ratio(
            aggregate_inputs.get(f"global_total_capacity_growth_{year}"),
            name=f"global_total_capacity_growth_{year}",
        )
        total_capacity[year] = total_capacity[year - 1] * (1 + growth)
    residual_scenarios: dict[str, Any] = {}
    for scenario in scenarios:
        total_path = dict(total_capacity)
        residual_growth = _ratio(
            (post.get("total_8in_equivalent_growth_2028_2030") or {}).get(scenario),
            name=f"total_8in_equivalent_growth_2028_2030.{scenario}",
        )
        for year in (2028, 2029, 2030):
            total_path[year] = total_path[year - 1] * (1 + residual_growth)
        capacity_300 = {
            year: float(aggregate_scenarios[scenario][str(year)]["300mm_capacity_wspm"])
            for year in years
        }
        capacity_300[2025] = common_path[2025]
        residual_scenarios[scenario] = [
            {
                "year": year,
                "total_8in_equivalent_wspm": round(total_path[year]),
                "300mm_wspm": round(capacity_300[year]),
                "300mm_converted_to_8in_equivalent_wspm": round(capacity_300[year] * 2.25),
                "at_most_200mm_family_residual_8in_equivalent_wspm": round(
                    max(total_path[year] - capacity_300[year] * 2.25, 0.0)
                ),
            }
            for year in range(2025, 2031)
        ]

    same_window_projects = [
        project
        for project in projects
        if int(project.get("full_capacity_year") or project["production_year"]) <= 2028
    ]
    same_window_wspm = sum(
        _finite(project["nameplate_incremental_wspm"], name="same_window_project_wspm")
        for project in same_window_projects
    )
    global_increment = float(aggregate["inferred_2024_to_2028_incremental_wspm"])
    forecast_msi = _finite(
        backtest_inputs.get("forecast_msi"),
        name="forecast_backtest_inputs.forecast_msi",
    )
    actual_msi = _finite(
        backtest_inputs.get("actual_msi"),
        name="forecast_backtest_inputs.actual_msi",
    )
    if actual_msi <= 0:
        raise ValueError("forecast_backtest_inputs.actual_msi 必须为正")
    forecast_error = (forecast_msi / actual_msi - 1) * 100
    memory_2026 = aggregate_inputs.get("memory_300mm_wspm_2026")
    memory_2027 = aggregate_inputs.get("memory_300mm_wspm_2027")
    if (memory_2026 is None) != (memory_2027 is None):
        raise ValueError("存储产能锚点必须同时提供2026年和2027年")
    if memory_2026 is not None:
        memory_anchor: dict[str, Any] = {
            "global_memory_300mm_wspm_2026": round(
                _finite(memory_2026, name="memory_300mm_wspm_2026")
            ),
            "global_memory_300mm_wspm_2027": round(
                _finite(memory_2027, name="memory_300mm_wspm_2027")
            ),
            "interpretation": (
                "这是SEMI披露的全球300毫米存储晶圆厂装机产能，覆盖存储整体，"
                "不能进一步拆成DRAM、HBM和NAND的原生硅片采购量。"
            ),
        }
    else:
        memory_anchor = {
            "global_installed_capacity_growth_2026": aggregate_inputs.get(
                "global_total_capacity_growth_2026"
            ),
            "global_installed_capacity_growth_2027": aggregate_inputs.get(
                "global_total_capacity_growth_2027"
            ),
            "interpretation": (
                "现有输入没有可核验的存储绝对月产能，因而不输出未经支持的存储片数。"
            ),
        }

    shipment_msi_2028 = aggregate_inputs.get("silicon_300mm_shipments_msi_2028")
    public_balance_proxy: dict[str, Any]
    if shipment_msi_2028 is not None:
        equivalent_wspm = msi_to_average_wspm(
            _finite(shipment_msi_2028, name="silicon_300mm_shipments_msi_2028"),
            diameter_mm=300,
        )
        public_balance_proxy = {
            "year": 2028,
            "silicon_300mm_shipments_msi_lower_bound": float(shipment_msi_2028),
            "equivalent_average_300mm_wafers_per_month_lower_bound": round(equivalent_wspm),
            "device_fab_installed_300mm_wspm": round(anchor_2028),
            "shipment_to_installed_capacity_ratio_lower_bound_pct": round(
                equivalent_wspm / anchor_2028 * 100,
                2,
            ),
            "formula": (
                "年度300毫米出货面积 ÷ 单片300毫米几何面积 ÷ 12个月；再除以晶圆厂装机月产能"
            ),
            "boundary": (
                "这是硅片出货与下游装机的利用强度代理，不是硅片厂供给能力，也不是供需缺口。"
                "公开资料没有按供应商、尺寸和年份拆分的全球有效供给产能，不能据此伪造绝对缺口。"
            ),
        }
    else:
        public_balance_proxy = {
            "status": "not_computed",
            "reason": "未提供同口径的300毫米硅片出货面积锚点。",
        }
    return {
        "model_id": str(inputs.get("model_id") or "silicon_wafer_demand"),
        "aggregate_300mm": aggregate,
        "bottom_up_disclosed_wspm_subset": bottom_up,
        "official_200mm_capacity": {
            "source_ids": list(source_refs.get("official_200mm_capacity") or []),
            "method": "2026年770万片/月及2027—2029年增速来自SEMI；2030为0%/2%/4%研究情景。",
            "scope": "纯200毫米器件厂装机产能；不与总8英寸等效余量相加。",
            "conversion_assumptions": official_200_assumptions,
            "scenarios": official_200,
        },
        "at_most_200mm_family_residual": {
            "method": "总8英寸等效产能减去300毫米产能×2.25",
            "boundary": "只作面积口径交叉检查，包含更小尺寸，不能称为纯200毫米月产能。",
            "scenarios": residual_scenarios,
        },
        "soi_quantification_status": {
            "status": "not_quantified",
            "reason": "公开资料没有全球SOI月产能、出货或统一价格基线；具名合作只能确认应用方向，不能校准增长率。",
        },
        "memory_and_product_mix": {
            "public_anchor": memory_anchor,
            "dram_hbm": "HBM堆叠层数不再次乘入月产能；项目证据只确认高规格DRAM硅片需求方向。",
            "nand": "NAND位增长可能由层数和现有洁净室吸收，不能直接等同硅片面积增长。",
            "advanced_logic": (
                "7纳米及以下公开锚点由2024年"
                f"{round(_finite(aggregate_inputs.get('advanced_le_7nm_wspm_2024'), name='advanced_le_7nm_wspm_2024') / 10_000):g}万片/月增至2028年"
                f"{round(_finite(aggregate_inputs.get('advanced_le_7nm_wspm_2028'), name='advanced_le_7nm_wspm_2028') / 10_000):g}万片/月。"
            ),
            "mature_logic_and_analog": "UMC、ST Agrate与ESMC是少数可直接复算净增月产能的项目。",
            "source_ids": list(source_refs.get("memory_and_product_mix") or []),
        },
        "public_supply_demand_proxy": public_balance_proxy,
        "forecast_backtest": {
            "semi_2025_forecast_msi": forecast_msi,
            "semi_2025_actual_msi": actual_msi,
            "forecast_above_actual_pct": round(forecast_error, 2),
            "use": "单年预测误差用于提醒项目延期、利用率和库存会改变结果。",
            "source_ids": list(backtest_inputs.get("source_ids") or []),
        },
        "coverage_warning": {
            "same_window_end_year": 2028,
            "same_window_disclosed_projects": len(same_window_projects),
            "total_projects_in_ledger": int(total_project_count),
            "same_window_disclosed_incremental_nameplate_wspm": round(same_window_wspm),
            "global_2024_to_2028_incremental_nameplate_wspm": round(global_increment),
            "same_window_disclosed_share_of_global_increment_pct": round(
                same_window_wspm / global_increment * 100,
                2,
            ),
            "excluded_from_same_window_project_ids": [
                str(project["project_id"])
                for project in projects
                if project not in same_window_projects
            ],
            "interpretation": (
                "只比较2028年前达到公开目标产能的项目与全球2024—2028装机增量；"
                "这个比例只说明可量化项目覆盖范围是公开资料下限。乘入爬坡、运行利用率、"
                "工艺投入和库存参数后的采购片数属于情景结果，不能视为已实现采购的最低值。"
            ),
        },
        "unit_reverse_checks": _demand_unit_reverse_checks(
            projects=projects,
            aggregate_scenarios=aggregate_scenarios,
            anchor_2028=anchor_2028,
        ),
    }


def validate_tam_sam_som(*, tam: float, sam: float, som: float) -> dict[str, float]:
    values = {
        "tam": _finite(tam, name="tam"),
        "sam": _finite(sam, name="sam"),
        "som": _finite(som, name="som"),
    }
    if not 0 <= values["som"] <= values["sam"] <= values["tam"]:
        raise ValueError("市场规模必须满足 0 <= SOM <= SAM <= TAM")
    return values


def build_model_outputs(inputs: Mapping[str, Any]) -> dict[str, Any]:
    semi = inputs.get("semi_msi") or {}
    semi_outputs: dict[str, Any] = {}
    for scenario, configuration in (semi.get("scenarios") or {}).items():
        anchor_year = int(configuration["anchor_year"])
        series = extrapolate_msi(
            configuration["anchor_msi"],
            configuration.get("annual_growth") or {},
            anchor_year=anchor_year,
        )
        semi_outputs[str(scenario)] = [
            {
                "year": year,
                "msi": value,
                "million_300mm_equivalent_wafers": msi_to_million_wafers(value, diameter_mm=300),
                "average_300mm_equivalent_wspm": msi_to_average_wspm(value, diameter_mm=300),
            }
            for year, value in sorted(series.items())
        ]

    demand = calculate_project_demand(
        inputs.get("fab_projects") or [],
        years=inputs.get("years") or [],
    )
    equipment = calculate_equipment_pool(
        inputs.get("wafer_capacity_projects") or [],
        intensity_by_process=inputs.get("equipment_intensity_by_process") or {},
    )
    intensity_examples = {
        key: {
            bound: equipment_intensity_per_100k_wspm(value)
            for bound, value in parameters.items()
            if bound in {"low", "base", "high"}
        }
        for key, parameters in (inputs.get("equipment_intensity_by_process") or {}).items()
    }
    return {
        "semi_area_scenarios": semi_outputs,
        "project_demand": demand,
        "equipment_project_pool": equipment,
        "equipment_budget_per_100k_wspm_rmb_100m": intensity_examples,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="复算硅片需求与硅片制造设备情景")
    parser.add_argument("inputs", type=Path)
    parser.add_argument("outputs", type=Path)
    args = parser.parse_args()
    inputs = json.loads(args.inputs.read_text(encoding="utf-8"))
    _write_json(args.outputs, build_model_outputs(inputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
