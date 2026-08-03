"""比亚迪/立讯进入高速光模块市场的可复算概率与财务情景模型。

模型刻意把三类输入分开：

1. 进入概率区间：来自历史基准率和逐里程碑证据更新；
2. 产业情景：需求、正常技术降价、供给和新增竞争压力；
3. 公司传导：份额、额外 ASP 压力、毛利率、资本开支和营运资本。

本模块不内置研究结论或隐藏数据库写入。调用方必须提供完整配置，并把配置、
随机种子和输出一并保存，才能把结果作为 Opportunity Lens 的计算底稿。
"""

from __future__ import annotations

import copy
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np


SCENARIOS = ("A", "B", "C", "D", "E", "F", "G")
ENTRY_SCENARIOS = ("A", "B", "C", "D", "E", "F")
ARCHITECTURE_STATES = ("P", "H", "C")
DAMAGE_STATES = ("mild", "material", "severe")
SCENARIO_LABELS = {
    "A": "两家均未形成有意义规模",
    "B": "立讯进入、比亚迪仍处研发或区域供货",
    "C": "比亚迪进入、立讯影响有限",
    "D": "两家均进入但主要局限中国客户",
    "E": "至少一家进入全球头部客户并成为第二供应商",
    "F": "两家均进入全球客户并显著冲击行业",
    "G": "LPO/CPO 等架构变化主导价值链重分配",
}

ENTRY_SCENARIO_LABELS = {
    "A": "两家均未形成有意义规模",
    "B": "仅立讯形成有意义进入，未闭环全球头部客户",
    "C": "仅比亚迪形成有意义进入，未闭环全球头部客户",
    "D": "两家均进入，均未闭环全球头部客户",
    "E": "只有一家进入全球头部客户",
    "F": "两家均进入全球头部客户",
}

ARCHITECTURE_LABELS = {
    "P": "传统可插拔主导",
    "H": "可插拔与 LPO/LRO 混合",
    "C": "CPO/optical-engine 形成增量价值链迁移",
}

PROBABILITY_V2_SCHEMA = "byd_luxshare_probability.v2"
FINANCIAL_V2_SCHEMA = "byd_luxshare_financial.v2"


def _require_probability(value: float, name: str) -> float:
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} 必须在 0~1：{number}")
    return number


def _range3(value: Any, name: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} 必须是 [low, mode, high]")
    low, mode, high = (_require_probability(float(x), name) for x in value)
    if not low <= mode <= high:
        raise ValueError(f"{name} 必须满足 low <= mode <= high")
    return low, mode, high


def _bounded_range3(
    value: Any,
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} 必须是 [low, mode, high]")
    low, mode, high = (float(x) for x in value)
    if not minimum <= low <= mode <= high <= maximum:
        raise ValueError(
            f"{name} 必须满足 {minimum} <= low <= mode <= high <= {maximum}"
        )
    return low, mode, high


def _triangular(rng: np.random.Generator, value: Any, size: int, name: str) -> np.ndarray:
    low, mode, high = _range3(value, name)
    if math.isclose(low, high):
        return np.full(size, low, dtype=float)
    return rng.triangular(low, mode, high, size=size)


def joint_bernoulli_probabilities(
    p_by: float,
    p_lux: float,
    frechet_lambda: float | None = None,
    *,
    rho: float | None = None,
) -> dict[str, float]:
    """用 Fréchet 边界插值构造具有精确边际概率的二元联合分布。

    ``frechet_lambda`` 不是 Pearson 相关系数，而是从独立分布向可行
    Fréchet 边界移动的比例。``rho`` 仅作为旧调用的兼容别名保留。
    这比把两家公司简单相乘更透明，也避免在证据高度共因时制造虚假精度。
    """

    p_by = _require_probability(p_by, "p_by")
    p_lux = _require_probability(p_lux, "p_lux")
    if frechet_lambda is None:
        if rho is None:
            raise TypeError("缺少 frechet_lambda（旧别名 rho 仍可用）")
        frechet_lambda = rho
    elif rho is not None and not math.isclose(float(frechet_lambda), float(rho)):
        raise ValueError("frechet_lambda 与兼容字段 rho 不一致")
    frechet_lambda = float(frechet_lambda)
    if not -1.0 <= frechet_lambda <= 1.0:
        raise ValueError("frechet_lambda 必须在 -1~1")
    independent = p_by * p_lux
    lower = max(0.0, p_by + p_lux - 1.0)
    upper = min(p_by, p_lux)
    if frechet_lambda >= 0:
        both = independent + frechet_lambda * (upper - independent)
    else:
        both = independent + (-frechet_lambda) * (lower - independent)
    result = {
        "both": both,
        "byd_only": p_by - both,
        "luxshare_only": p_lux - both,
        "neither": 1.0 - p_by - p_lux + both,
    }
    if any(value < -1e-12 for value in result.values()):
        raise AssertionError(f"联合概率出现负数：{result}")
    return {key: max(0.0, float(value)) for key, value in result.items()}


def _joint_bernoulli_arrays(
    p_by: np.ndarray,
    p_lux: np.ndarray,
    frechet_lambda: np.ndarray,
) -> dict[str, np.ndarray]:
    """向量化 Fréchet 联合分布，供 V2 外层参数 Monte Carlo 使用。"""

    independent = p_by * p_lux
    lower = np.maximum(0.0, p_by + p_lux - 1.0)
    upper = np.minimum(p_by, p_lux)
    anchor = np.clip(independent, lower, upper)
    both = np.where(
        frechet_lambda >= 0,
        anchor + frechet_lambda * (upper - anchor),
        anchor + (-frechet_lambda) * (lower - anchor),
    )
    return {
        "both": both,
        "byd_only": p_by - both,
        "luxshare_only": p_lux - both,
        "neither": 1.0 - p_by - p_lux + both,
    }


def _joint_subset_arrays(
    p_first: np.ndarray,
    p_second: np.ndarray,
    p_superset: np.ndarray,
    frechet_lambda: np.ndarray,
    *,
    minimum_both: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """在共同上位事件内连接两个可重叠子事件。

    这里用于“中国有意义进入”和“全球头部客户进入”：两者都必须先满足
    ``meaningful_entry``，但可以重叠。独立基准按上位事件内条件独立计算，
    Fréchet 下界同时受 ``union <= p_superset`` 约束，避免把地域并集算得比
    总进入概率更大。
    """

    safe_superset = np.maximum(p_superset, 1e-15)
    independent = np.where(
        p_superset > 0,
        p_first * p_second / safe_superset,
        0.0,
    )
    lower = np.maximum(0.0, p_first + p_second - p_superset)
    if minimum_both is not None:
        lower = np.maximum(lower, minimum_both)
    upper = np.minimum(p_first, p_second)
    if np.any(lower > upper + 1e-12):
        raise AssertionError("子事件交集下界超过Fréchet上界")
    anchor = np.clip(independent, lower, upper)
    both = np.where(
        frechet_lambda >= 0,
        anchor + frechet_lambda * (upper - anchor),
        anchor + (-frechet_lambda) * (lower - anchor),
    )
    first_only = p_first - both
    second_only = p_second - both
    unidentified_within_superset = p_superset - p_first - p_second + both
    no_superset = 1.0 - p_superset
    return {
        "both": np.maximum(0.0, both),
        "first_only": np.maximum(0.0, first_only),
        "second_only": np.maximum(0.0, second_only),
        "unidentified_within_superset": np.maximum(
            0.0, unidentified_within_superset
        ),
        "no_superset": np.maximum(0.0, no_superset),
    }


def _triangular_ppf(u: np.ndarray, value: Any, name: str) -> np.ndarray:
    """三角分布逆 CDF；共享 ``u`` 可形成跨期限一致的参数路径。"""

    low, mode, high = _range3(value, name)
    if math.isclose(low, high):
        return np.full_like(u, low, dtype=float)
    width = high - low
    split = (mode - low) / width
    left = low + np.sqrt(np.maximum(0.0, u * width * (mode - low)))
    right = high - np.sqrt(np.maximum(0.0, (1.0 - u) * width * (high - mode)))
    return np.where(u < split, left, right)


def _bounded_triangular_ppf(
    u: np.ndarray,
    value: Any,
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> np.ndarray:
    low, mode, high = _bounded_range3(
        value, name, minimum=minimum, maximum=maximum
    )
    if math.isclose(low, high):
        return np.full_like(u, low, dtype=float)
    width = high - low
    split = (mode - low) / width
    left = low + np.sqrt(np.maximum(0.0, u * width * (mode - low)))
    right = high - np.sqrt(np.maximum(0.0, (1.0 - u) * width * (high - mode)))
    return np.where(u < split, left, right)


def _draw_monotone_horizon_pair(
    rng: np.random.Generator,
    three_year: Any,
    five_year: Any,
    samples: int,
    name: str,
) -> tuple[np.ndarray, np.ndarray]:
    """以共享 quantile 抽取 3y/5y 参数，并强制累计概率路径不下降。"""

    three_range = _range3(three_year, f"{name}.3y")
    five_range = _range3(five_year, f"{name}.5y")
    if any(three > five for three, five in zip(three_range, five_range)):
        raise ValueError(f"{name} 必须逐项满足 3y <= 5y")
    quantile = rng.random(samples)
    p3 = _triangular_ppf(quantile, three_range, f"{name}.3y")
    p5_raw = _triangular_ppf(quantile, five_range, f"{name}.5y")
    p5 = np.maximum(p3, p5_raw)
    return p3, p5


def _probability_summary(values: np.ndarray) -> dict[str, float]:
    """认识不确定性摘要和外层 Monte Carlo 数值积分误差。"""

    p10, median, p90 = np.quantile(values, [0.1, 0.5, 0.9])
    standard_error = (
        float(np.std(values, ddof=1) / math.sqrt(len(values))) if len(values) > 1 else 0.0
    )
    return {
        "mean": round(float(np.mean(values)), 8),
        "p10": round(float(p10), 8),
        "median": round(float(median), 8),
        "p90": round(float(p90), 8),
        "outer_mc_standard_error": round(standard_error, 10),
    }


def _draw_joint_category(
    rng: np.random.Generator,
    p_by: np.ndarray,
    p_lux: np.ndarray,
    rho: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    independent = p_by * p_lux
    lower = np.maximum(0.0, p_by + p_lux - 1.0)
    upper = np.minimum(p_by, p_lux)
    both = np.where(
        rho >= 0,
        independent + rho * (upper - independent),
        independent + (-rho) * (lower - independent),
    )
    by_only = p_by - both
    lux_only = p_lux - both
    u = rng.random(len(p_by))
    by_event = u < (both + by_only)
    lux_event = (u < both) | ((u >= both + by_only) & (u < both + by_only + lux_only))
    return by_event, lux_event


def _draw_conditional_global(
    rng: np.random.Generator,
    by_event: np.ndarray,
    lux_event: np.ndarray,
    q_by: np.ndarray,
    q_lux: np.ndarray,
    rho: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    by_global = np.zeros(len(by_event), dtype=bool)
    lux_global = np.zeros(len(by_event), dtype=bool)
    both_active = by_event & lux_event
    single_by = by_event & ~lux_event
    single_lux = lux_event & ~by_event
    by_global[single_by] = rng.random(single_by.sum()) < q_by[single_by]
    lux_global[single_lux] = rng.random(single_lux.sum()) < q_lux[single_lux]
    if both_active.any():
        indices = np.flatnonzero(both_active)
        b, l = _draw_joint_category(rng, q_by[indices], q_lux[indices], rho[indices])
        by_global[indices] = b
        lux_global[indices] = l
    return by_global, lux_global


def _simulate_probability_tree_v1(
    config: dict[str, Any],
    *,
    samples: int = 100_000,
    seed: int = 20260718,
) -> dict[str, Any]:
    """旧版事件抽样器；仅为既有配置兼容保留。"""

    if samples < 10_000:
        raise ValueError("正式研究至少使用 10,000 次抽样")
    rng = np.random.default_rng(seed)
    entrants = config["entrants"]
    rho = _triangular(rng, config["entry_dependence"], samples, "entry_dependence")
    global_rho = _triangular(rng, config["global_dependence"], samples, "global_dependence")
    severe_if_both_global = _triangular(
        rng,
        config["severe_if_both_global"],
        samples,
        "severe_if_both_global",
    )

    horizon_results: dict[str, Any] = {}
    for horizon in ("3y", "5y"):
        architecture_key = f"architecture_override_{horizon}"
        architecture_input = config.get(architecture_key, config.get("architecture_override"))
        if architecture_input is None:
            raise ValueError(
                f"缺少 {architecture_key}；也未提供兼容字段 architecture_override"
            )
        architecture = _triangular(
            rng,
            architecture_input,
            samples,
            architecture_key,
        )
        p_by = _triangular(rng, entrants["byd"][horizon], samples, f"byd.{horizon}")
        p_lux = _triangular(rng, entrants["luxshare"][horizon], samples, f"luxshare.{horizon}")
        q_by = _triangular(
            rng,
            entrants["byd"][f"global_given_entry_{horizon}"],
            samples,
            f"byd.global_given_entry_{horizon}",
        )
        q_lux = _triangular(
            rng,
            entrants["luxshare"][f"global_given_entry_{horizon}"],
            samples,
            f"luxshare.global_given_entry_{horizon}",
        )
        by_event, lux_event = _draw_joint_category(rng, p_by, p_lux, rho)
        by_global, lux_global = _draw_conditional_global(
            rng, by_event, lux_event, q_by, q_lux, global_rho
        )
        architecture_event = rng.random(samples) < architecture
        severe_event = rng.random(samples) < severe_if_both_global

        scenario = np.full(samples, "A", dtype="<U1")
        scenario[lux_event & ~by_event] = "B"
        scenario[by_event & ~lux_event] = "C"
        scenario[by_event & lux_event] = "D"
        scenario[(by_global | lux_global)] = "E"
        scenario[by_global & lux_global & severe_event] = "F"
        scenario[architecture_event] = "G"

        counts = {code: float(np.mean(scenario == code)) for code in SCENARIOS}
        horizon_results[horizon] = {
            "marginal_probability": {
                "byd_meaningful_entry": float(by_event.mean()),
                "luxshare_meaningful_entry": float(lux_event.mean()),
                "at_least_one_entry": float((by_event | lux_event).mean()),
                "both_entry": float((by_event & lux_event).mean()),
                "byd_global_entry": float(by_global.mean()),
                "luxshare_global_entry": float(lux_global.mean()),
                "at_least_one_global_entry": float((by_global | lux_global).mean()),
            },
            "scenario_probability": counts,
            "epistemic_input_summary": {
                "byd_entry_probability": _summary(p_by),
                "luxshare_entry_probability": _summary(p_lux),
                "entry_dependence": _summary(rho),
                "architecture_override": _summary(architecture),
            },
        }
    return {"samples": samples, "seed": seed, "horizons": horizon_results}


def _validate_probability_v2_contract(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("schema_version") != PROBABILITY_V2_SCHEMA:
        raise ValueError(f"V2 概率配置必须声明 schema_version={PROBABILITY_V2_SCHEMA}")
    contract = config.get("event_contract")
    if not isinstance(contract, dict):
        raise ValueError("V2 概率配置缺少 event_contract")
    for field in ("version", "as_of_date", "horizons"):
        if not contract.get(field):
            raise ValueError(f"event_contract 缺少 {field}")
    for definition in (
        "meaningful_entry",
        "china_entry",
        "global_entry",
        "deterioration",
    ):
        if not contract.get(definition):
            raise ValueError(f"event_contract 缺少 {definition} 定义")
    try:
        as_of = date.fromisoformat(str(contract["as_of_date"]))
        horizon_3y = date.fromisoformat(str(contract["horizons"]["3y"]))
        horizon_5y = date.fromisoformat(str(contract["horizons"]["5y"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("event_contract 日期必须是 ISO YYYY-MM-DD，且包含 3y/5y") from exc
    if not as_of < horizon_3y < horizon_5y:
        raise ValueError("event_contract 必须满足 as_of_date < 3y < 5y")
    entrants = config.get("entrants")
    if not isinstance(entrants, dict):
        raise ValueError("V2 概率配置缺少 entrants")
    for entrant in ("byd", "luxshare"):
        payload = entrants.get(entrant)
        if not isinstance(payload, dict):
            raise ValueError(f"entrants 缺少 {entrant}")
        for field in (
            "3y",
            "5y",
            "china_given_entry_3y",
            "china_given_entry_5y",
            "global_given_entry_3y",
            "global_given_entry_5y",
        ):
            if field not in payload:
                raise ValueError(f"entrants.{entrant} 缺少 {field}")
    return contract


def _get_frechet_ranges(
    config: dict[str, Any],
) -> tuple[Any, Any, Any, Any, list[str]]:
    warnings: list[str] = []
    explicit = config.get("frechet_dependence_lambda")
    if isinstance(explicit, dict):
        if "china" not in explicit or "geography_overlap" not in explicit:
            raise ValueError(
                "V2 地域模型要求 frechet_dependence_lambda 同时提供 "
                "entry/global/china/geography_overlap"
            )
        return (
            explicit["entry"],
            explicit["global"],
            explicit["china"],
            explicit["geography_overlap"],
            warnings,
        )
    if "entry_frechet_lambda" in config and "global_frechet_lambda" in config:
        raise ValueError("旧版双 lambda 配置不能表达独立中国事件，请迁移到显式四 lambda 配置")
    if "entry_dependence" in config and "global_dependence" in config:
        warnings.append(
            "使用旧字段 entry_dependence/global_dependence；其语义已固定为 Fréchet lambda，"
            "不是 Pearson correlation。"
        )
        raise ValueError("旧版 dependence 配置不能表达独立中国事件，请迁移到显式四 lambda 配置")
    raise ValueError(
        "缺少 frechet_dependence_lambda={entry/global/china/geography_overlap:[...]}"
    )


def _draw_v2_architecture_paths(
    config: dict[str, Any],
    rng: np.random.Generator,
    samples: int,
) -> tuple[dict[str, dict[str, np.ndarray]], str, list[str]]:
    warnings: list[str] = []
    architecture = config.get("architecture")
    if isinstance(architecture, dict):
        hybrid = architecture.get("hybrid_probability", architecture.get("H"))
        cpo = architecture.get(
            "cpo_incremental_risk_probability", architecture.get("C")
        )
        if not isinstance(hybrid, dict) or not isinstance(cpo, dict):
            raise ValueError(
                "architecture 必须提供 hybrid_probability 与 "
                "cpo_incremental_risk_probability 的 3y/5y 区间"
            )
        h3_input, h5_input = hybrid["3y"], hybrid["5y"]
        c3_input, c5_input = cpo["3y"], cpo["5y"]
        source = "explicit_v2_architecture_pressure_bands"
    else:
        c3_input = config.get("architecture_override_3y", config.get("architecture_override"))
        c5_input = config.get("architecture_override_5y", config.get("architecture_override"))
        if c3_input is None or c5_input is None:
            raise ValueError("V2 缺少 architecture 配置")
        h3_input = [0.0, 0.0, 0.0]
        h5_input = [0.0, 0.0, 0.0]
        source = "legacy_architecture_override_mapped_to_C"
        warnings.append(
            "旧 architecture_override 已映射为正交 C 状态，H 状态为 0；正式配置应显式给出 P/H/C。"
        )

    if _range3(h3_input, "architecture.H.3y")[2] + _range3(
        c3_input, "architecture.C.3y"
    )[2] > 1.0:
        raise ValueError("architecture 3y 的 H.high + C.high 不得超过 1")
    if _range3(h5_input, "architecture.H.5y")[2] + _range3(
        c5_input, "architecture.C.5y"
    )[2] > 1.0:
        raise ValueError("architecture 5y 的 H.high + C.high 不得超过 1")

    h3, h5 = _draw_monotone_horizon_pair(
        rng, h3_input, h5_input, samples, "architecture.H"
    )
    c3, c5 = _draw_monotone_horizon_pair(
        rng, c3_input, c5_input, samples, "architecture.C"
    )
    paths: dict[str, dict[str, np.ndarray]] = {}
    for horizon, hybrid_draw, cpo_draw in (
        ("3y", h3, c3),
        ("5y", h5, c5),
    ):
        conventional = 1.0 - hybrid_draw - cpo_draw
        if float(np.min(conventional)) < -1e-12:
            raise ValueError(f"architecture {horizon} 出现 H+C>1")
        paths[horizon] = {
            "P": np.maximum(0.0, conventional),
            "H": hybrid_draw,
            "C": cpo_draw,
        }
    return paths, source, warnings


def _default_damage_pressure_bands() -> dict[str, dict[str, dict[str, Any]]]:
    """结构化专家压力带；是可替换假设，不是经验发生率。"""

    return {
        "3y": {
            "B": {"mild": [0.55, 0.65, 0.75], "severe": [0.02, 0.06, 0.12]},
            "C": {"mild": [0.55, 0.65, 0.75], "severe": [0.02, 0.06, 0.12]},
            "D": {"mild": [0.45, 0.55, 0.65], "severe": [0.05, 0.10, 0.18]},
            "E": {"mild": [0.30, 0.40, 0.50], "severe": [0.10, 0.18, 0.28]},
            "F": {"mild": [0.15, 0.25, 0.35], "severe": [0.20, 0.35, 0.50]},
        },
        "5y": {
            "B": {"mild": [0.45, 0.55, 0.65], "severe": [0.05, 0.10, 0.15]},
            "C": {"mild": [0.45, 0.55, 0.65], "severe": [0.05, 0.10, 0.15]},
            "D": {"mild": [0.35, 0.45, 0.55], "severe": [0.08, 0.15, 0.22]},
            "E": {"mild": [0.20, 0.30, 0.40], "severe": [0.15, 0.27, 0.40]},
            "F": {"mild": [0.10, 0.18, 0.25], "severe": [0.30, 0.45, 0.58]},
        },
    }


def _draw_damage_pressure_bands(
    config: dict[str, Any],
    rng: np.random.Generator,
    samples: int,
) -> tuple[dict[str, dict[str, dict[str, np.ndarray]]], str]:
    configured = config.get("deterioration_pressure_bands")
    bands = configured if isinstance(configured, dict) else _default_damage_pressure_bands()
    source = (
        "explicit_structured_pressure_bands"
        if isinstance(configured, dict)
        else "builtin_structured_pressure_bands_v1"
    )
    draws: dict[str, dict[str, dict[str, np.ndarray]]] = {}
    for horizon in ("3y", "5y"):
        horizon_bands = bands.get(horizon)
        if not isinstance(horizon_bands, dict):
            raise ValueError(f"deterioration_pressure_bands 缺少 {horizon}")
        draws[horizon] = {}
        for state in ENTRY_SCENARIOS[1:]:
            state_band = horizon_bands.get(state)
            if not isinstance(state_band, dict):
                raise ValueError(
                    f"deterioration_pressure_bands.{horizon} 缺少状态 {state}"
                )
            mild_range = _range3(state_band["mild"], f"damage.{horizon}.{state}.mild")
            severe_range = _range3(
                state_band["severe"], f"damage.{horizon}.{state}.severe"
            )
            if mild_range[2] + severe_range[2] > 1.0:
                raise ValueError(
                    f"damage.{horizon}.{state} 的 mild.high + severe.high 不得超过 1"
                )
            mild = _triangular_ppf(
                rng.random(samples), mild_range, f"damage.{horizon}.{state}.mild"
            )
            severe = _triangular_ppf(
                rng.random(samples), severe_range, f"damage.{horizon}.{state}.severe"
            )
            draws[horizon][state] = {
                "mild": mild,
                "material": 1.0 - mild - severe,
                "severe": severe,
            }
    return draws, source


def _conditional_damage_outputs(
    entry_states: dict[str, np.ndarray],
    damage_draws: dict[str, dict[str, np.ndarray]],
) -> dict[str, Any]:
    by_state = {
        state: {
            damage: _probability_summary(damage_draws[state][damage])
            for damage in DAMAGE_STATES
        }
        for state in ENTRY_SCENARIOS[1:]
    }

    def aggregate(states: tuple[str, ...]) -> dict[str, dict[str, float]]:
        denominator = sum(entry_states[state] for state in states)
        result: dict[str, dict[str, float]] = {}
        for damage in DAMAGE_STATES:
            numerator = sum(
                entry_states[state] * damage_draws[state][damage] for state in states
            )
            conditional = np.divide(
                numerator,
                denominator,
                out=np.zeros_like(numerator),
                where=denominator > 0,
            )
            result[damage] = _probability_summary(conditional)
        return result

    joint_with_entry = {
        damage: _probability_summary(
            sum(
                entry_states[state] * damage_draws[state][damage]
                for state in ENTRY_SCENARIOS[1:]
            )
        )
        for damage in DAMAGE_STATES
    }
    return {
        "notice": (
            "按进入状态设定的结构化专家压力带，不是经验发生率；material 为 "
            "1-mild-severe，三类在每条参数路径上严格和为 1。"
        ),
        "by_entry_state": by_state,
        "conditional_on_at_least_one_entry": aggregate(ENTRY_SCENARIOS[1:]),
        "conditional_on_at_least_one_global_entry": aggregate(("E", "F")),
        "conditional_on_both_global_entry": aggregate(("F",)),
        "unconditional_joint_with_entry": joint_with_entry,
    }


def _simulate_probability_tree_v2(
    config: dict[str, Any],
    *,
    samples: int = 100_000,
    seed: int = 20260718,
) -> dict[str, Any]:
    """V2：外层参数 Monte Carlo + 内层解析 A—F 联合状态。"""

    if samples < 10_000:
        raise ValueError("正式研究至少使用 10,000 次外层参数抽样")
    contract = _validate_probability_v2_contract(config)
    entrants = config["entrants"]
    rng = np.random.default_rng(seed)

    parameter_paths: dict[str, dict[str, dict[str, np.ndarray]]] = {
        "3y": {},
        "5y": {},
    }
    for entrant in ("byd", "luxshare"):
        p3, p5 = _draw_monotone_horizon_pair(
            rng,
            entrants[entrant]["3y"],
            entrants[entrant]["5y"],
            samples,
            f"entrants.{entrant}.entry",
        )
        q3, q5 = _draw_monotone_horizon_pair(
            rng,
            entrants[entrant]["global_given_entry_3y"],
            entrants[entrant]["global_given_entry_5y"],
            samples,
            f"entrants.{entrant}.global_given_entry",
        )
        china3, china5 = _draw_monotone_horizon_pair(
            rng,
            entrants[entrant]["china_given_entry_3y"],
            entrants[entrant]["china_given_entry_5y"],
            samples,
            f"entrants.{entrant}.china_given_entry",
        )
        parameter_paths["3y"][entrant] = {
            "entry": p3,
            "china_given_entry": china3,
            "global_given_entry": q3,
        }
        parameter_paths["5y"][entrant] = {
            "entry": p5,
            "china_given_entry": china5,
            "global_given_entry": q5,
        }

    (
        entry_lambda_input,
        global_lambda_input,
        china_lambda_input,
        geography_overlap_lambda_input,
        warnings,
    ) = _get_frechet_ranges(config)
    entry_lambda = _bounded_triangular_ppf(
        rng.random(samples),
        entry_lambda_input,
        "frechet_dependence_lambda.entry",
        minimum=-1.0,
        maximum=1.0,
    )
    global_lambda = _bounded_triangular_ppf(
        rng.random(samples),
        global_lambda_input,
        "frechet_dependence_lambda.global",
        minimum=-1.0,
        maximum=1.0,
    )
    china_lambda = _bounded_triangular_ppf(
        rng.random(samples),
        china_lambda_input,
        "frechet_dependence_lambda.china",
        minimum=-1.0,
        maximum=1.0,
    )
    geography_overlap_lambda = _bounded_triangular_ppf(
        rng.random(samples),
        geography_overlap_lambda_input,
        "frechet_dependence_lambda.geography_overlap",
        minimum=-1.0,
        maximum=1.0,
    )
    architecture_paths, architecture_source, architecture_warnings = (
        _draw_v2_architecture_paths(config, rng, samples)
    )
    warnings.extend(architecture_warnings)
    damage_paths, damage_source = _draw_damage_pressure_bands(config, rng, samples)

    horizon_results: dict[str, Any] = {}
    max_standard_error = 0.0
    max_probability_sum_error = 0.0
    geography_set_invariant_audit: dict[str, dict[str, float]] = {}
    for horizon in ("3y", "5y"):
        byd = parameter_paths[horizon]["byd"]
        lux = parameter_paths[horizon]["luxshare"]
        entry_joint = _joint_bernoulli_arrays(
            byd["entry"], lux["entry"], entry_lambda
        )
        global_joint = _joint_bernoulli_arrays(
            byd["global_given_entry"],
            lux["global_given_entry"],
            global_lambda,
        )
        china_joint = _joint_bernoulli_arrays(
            byd["china_given_entry"],
            lux["china_given_entry"],
            china_lambda,
        )
        byd_china_entry = byd["entry"] * byd["china_given_entry"]
        lux_china_entry = lux["entry"] * lux["china_given_entry"]
        byd_global_entry = byd["entry"] * byd["global_given_entry"]
        lux_global_entry = lux["entry"] * lux["global_given_entry"]
        both_china_entry = entry_joint["both"] * china_joint["both"]
        both_global_entry = entry_joint["both"] * global_joint["both"]
        china_entry_joint = {
            "both": both_china_entry,
            "byd_only": byd_china_entry - both_china_entry,
            "luxshare_only": lux_china_entry - both_china_entry,
            "neither": 1.0
            - byd_china_entry
            - lux_china_entry
            + both_china_entry,
        }
        global_entry_joint = {
            "both": both_global_entry,
            "byd_only": byd_global_entry - both_global_entry,
            "luxshare_only": lux_global_entry - both_global_entry,
            "neither": 1.0
            - byd_global_entry
            - lux_global_entry
            + both_global_entry,
        }
        at_least_one_entry = 1.0 - entry_joint["neither"]
        at_least_one_china_entry = 1.0 - china_entry_joint["neither"]
        at_least_one_global_entry = 1.0 - global_entry_joint["neither"]
        company_geography = {
            "byd": _joint_subset_arrays(
                byd_china_entry,
                byd_global_entry,
                byd["entry"],
                geography_overlap_lambda,
            ),
            "luxshare": _joint_subset_arrays(
                lux_china_entry,
                lux_global_entry,
                lux["entry"],
                geography_overlap_lambda,
            ),
        }
        # 系统“中国且全球”事件必须包含任一家公司的“中国且全球”事件。
        # 两层若分别套同一 Fréchet λ 而不加该集合约束，极少数参数样本会
        # 出现系统交集小于单公司交集的逻辑违例。
        system_geography = _joint_subset_arrays(
            at_least_one_china_entry,
            at_least_one_global_entry,
            at_least_one_entry,
            geography_overlap_lambda,
            minimum_both=np.maximum(
                company_geography["byd"]["both"],
                company_geography["luxshare"]["both"],
            ),
        )
        geography_set_invariant_audit[horizon] = {
            "min_system_both_minus_byd_both": round(
                float(
                    np.min(
                        system_geography["both"]
                        - company_geography["byd"]["both"]
                    )
                ),
                12,
            ),
            "min_system_both_minus_luxshare_both": round(
                float(
                    np.min(
                        system_geography["both"]
                        - company_geography["luxshare"]["both"]
                    )
                ),
                12,
            ),
        }
        entry_states = {
            "A": entry_joint["neither"],
            "B": entry_joint["luxshare_only"]
            * (1.0 - lux["global_given_entry"]),
            "C": entry_joint["byd_only"] * (1.0 - byd["global_given_entry"]),
            "D": entry_joint["both"] * global_joint["neither"],
            "E": (
                entry_joint["luxshare_only"] * lux["global_given_entry"]
                + entry_joint["byd_only"] * byd["global_given_entry"]
                + entry_joint["both"]
                * (global_joint["byd_only"] + global_joint["luxshare_only"])
            ),
            "F": entry_joint["both"] * global_joint["both"],
        }
        scenario_sum = sum(entry_states.values())
        architecture_sum = sum(architecture_paths[horizon].values())
        max_probability_sum_error = max(
            max_probability_sum_error,
            float(np.max(np.abs(scenario_sum - 1.0))),
            float(np.max(np.abs(architecture_sum - 1.0))),
            float(np.max(np.abs(sum(china_entry_joint.values()) - 1.0))),
            float(np.max(np.abs(sum(global_entry_joint.values()) - 1.0))),
            float(np.max(np.abs(sum(system_geography.values()) - 1.0))),
            *(
                float(np.max(np.abs(sum(states.values()) - 1.0)))
                for states in company_geography.values()
            ),
        )

        marginal_arrays = {
            "byd_meaningful_entry": byd["entry"],
            "luxshare_meaningful_entry": lux["entry"],
            "at_least_one_entry": at_least_one_entry,
            "both_entry": entry_joint["both"],
            "byd_china_entry": byd_china_entry,
            "luxshare_china_entry": lux_china_entry,
            "at_least_one_china_entry": at_least_one_china_entry,
            "both_china_entry": china_entry_joint["both"],
            "byd_global_entry": byd_global_entry,
            "luxshare_global_entry": lux_global_entry,
            "at_least_one_global_entry": at_least_one_global_entry,
            "both_global_entry": global_entry_joint["both"],
            "china_only_system_entry": system_geography["first_only"],
            "global_only_system_entry": system_geography["second_only"],
            "china_and_global_system_entry": system_geography["both"],
            "geography_unidentified_entry": system_geography[
                "unidentified_within_superset"
            ],
        }
        scenario_summaries = {
            state: _probability_summary(values) for state, values in entry_states.items()
        }
        marginal_summaries = {
            name: _probability_summary(values)
            for name, values in marginal_arrays.items()
        }
        architecture_summaries = {
            state: _probability_summary(values)
            for state, values in architecture_paths[horizon].items()
        }
        china_joint_summaries = {
            state: _probability_summary(values)
            for state, values in china_entry_joint.items()
        }
        global_joint_summaries = {
            state: _probability_summary(values)
            for state, values in global_entry_joint.items()
        }
        system_geography_summaries = {
            state: _probability_summary(values)
            for state, values in system_geography.items()
        }
        company_geography_summaries = {
            company: {
                state: _probability_summary(values)
                for state, values in states.items()
            }
            for company, states in company_geography.items()
        }
        damage_outputs = _conditional_damage_outputs(
            entry_states, damage_paths[horizon]
        )
        for summary in (
            *scenario_summaries.values(),
            *marginal_summaries.values(),
            *architecture_summaries.values(),
            *china_joint_summaries.values(),
            *global_joint_summaries.values(),
            *system_geography_summaries.values(),
            *(
                summary
                for company in company_geography_summaries.values()
                for summary in company.values()
            ),
        ):
            max_standard_error = max(
                max_standard_error, summary["outer_mc_standard_error"]
            )
        for value in damage_outputs.values():
            if not isinstance(value, dict):
                continue
            for nested in value.values():
                if isinstance(nested, dict) and "outer_mc_standard_error" in nested:
                    max_standard_error = max(
                        max_standard_error,
                        nested["outer_mc_standard_error"],
                    )
                elif isinstance(nested, dict):
                    for summary in nested.values():
                        if isinstance(summary, dict) and "outer_mc_standard_error" in summary:
                            max_standard_error = max(
                                max_standard_error,
                                summary["outer_mc_standard_error"],
                            )
        horizon_results[horizon] = {
            "horizon_date": contract["horizons"][horizon],
            "marginal_probability": {
                name: summary["mean"] for name, summary in marginal_summaries.items()
            },
            "marginal_probability_summary": marginal_summaries,
            "scenario_probability": {
                state: summary["mean"] for state, summary in scenario_summaries.items()
            },
            "entry_state_probability": {
                state: summary["mean"] for state, summary in scenario_summaries.items()
            },
            "entry_state_probability_summary": scenario_summaries,
            "china_entry_joint_probability": {
                state: summary["mean"]
                for state, summary in china_joint_summaries.items()
            },
            "china_entry_joint_probability_summary": china_joint_summaries,
            "global_entry_joint_probability": {
                state: summary["mean"]
                for state, summary in global_joint_summaries.items()
            },
            "global_entry_joint_probability_summary": global_joint_summaries,
            "geography_scope_probability": {
                "china_only": system_geography_summaries["first_only"]["mean"],
                "global_only": system_geography_summaries["second_only"]["mean"],
                "china_and_global": system_geography_summaries["both"]["mean"],
                "entry_route_unidentified": system_geography_summaries[
                    "unidentified_within_superset"
                ]["mean"],
                "no_meaningful_entry": system_geography_summaries["no_superset"][
                    "mean"
                ],
            },
            "geography_scope_probability_summary": {
                "china_only": system_geography_summaries["first_only"],
                "global_only": system_geography_summaries["second_only"],
                "china_and_global": system_geography_summaries["both"],
                "entry_route_unidentified": system_geography_summaries[
                    "unidentified_within_superset"
                ],
                "no_meaningful_entry": system_geography_summaries["no_superset"],
            },
            "company_geography_probability": {
                company: {
                    "china_only": summaries["first_only"]["mean"],
                    "global_only": summaries["second_only"]["mean"],
                    "china_and_global": summaries["both"]["mean"],
                    "entry_route_unidentified": summaries[
                        "unidentified_within_superset"
                    ]["mean"],
                    "no_meaningful_entry": summaries["no_superset"]["mean"],
                }
                for company, summaries in company_geography_summaries.items()
            },
            "company_geography_probability_summary": {
                company: {
                    "china_only": summaries["first_only"],
                    "global_only": summaries["second_only"],
                    "china_and_global": summaries["both"],
                    "entry_route_unidentified": summaries[
                        "unidentified_within_superset"
                    ],
                    "no_meaningful_entry": summaries["no_superset"],
                }
                for company, summaries in company_geography_summaries.items()
            },
            "architecture_probability": {
                state: summary["mean"] for state, summary in architecture_summaries.items()
            },
            "architecture_probability_summary": architecture_summaries,
            "incremental_risk_labels": {
                "G": {
                    "meaning": (
                        "CPO/optical-engine 相对基础路径形成增量价值链迁移；"
                        "这是正交标签，不覆盖 A—F。"
                    ),
                    "probability": architecture_summaries["C"]["mean"],
                    "probability_summary": architecture_summaries["C"],
                    "underlying_entry_states_preserved": True,
                }
            },
            "conditional_deterioration_probability": damage_outputs,
            "epistemic_input_summary": {
                "byd_entry_probability": _probability_summary(byd["entry"]),
                "luxshare_entry_probability": _probability_summary(lux["entry"]),
                "byd_china_given_entry": _probability_summary(
                    byd["china_given_entry"]
                ),
                "luxshare_china_given_entry": _probability_summary(
                    lux["china_given_entry"]
                ),
                "byd_global_given_entry": _probability_summary(
                    byd["global_given_entry"]
                ),
                "luxshare_global_given_entry": _probability_summary(
                    lux["global_given_entry"]
                ),
                "frechet_entry_lambda": _probability_summary(entry_lambda),
                "frechet_global_lambda": _probability_summary(global_lambda),
                "frechet_china_lambda": _probability_summary(china_lambda),
                "frechet_geography_overlap_lambda": _probability_summary(
                    geography_overlap_lambda
                ),
            },
        }

    monotonicity = {
        "byd_entry_min_5y_minus_3y": round(
            float(
                np.min(
                    parameter_paths["5y"]["byd"]["entry"]
                    - parameter_paths["3y"]["byd"]["entry"]
                )
            ),
            10,
        ),
        "luxshare_entry_min_5y_minus_3y": round(
            float(
                np.min(
                    parameter_paths["5y"]["luxshare"]["entry"]
                    - parameter_paths["3y"]["luxshare"]["entry"]
                )
            ),
            10,
        ),
        "byd_china_given_entry_min_5y_minus_3y": round(
            float(
                np.min(
                    parameter_paths["5y"]["byd"]["china_given_entry"]
                    - parameter_paths["3y"]["byd"]["china_given_entry"]
                )
            ),
            10,
        ),
        "luxshare_china_given_entry_min_5y_minus_3y": round(
            float(
                np.min(
                    parameter_paths["5y"]["luxshare"]["china_given_entry"]
                    - parameter_paths["3y"]["luxshare"]["china_given_entry"]
                )
            ),
            10,
        ),
        "byd_global_given_entry_min_5y_minus_3y": round(
            float(
                np.min(
                    parameter_paths["5y"]["byd"]["global_given_entry"]
                    - parameter_paths["3y"]["byd"]["global_given_entry"]
                )
            ),
            10,
        ),
        "luxshare_global_given_entry_min_5y_minus_3y": round(
            float(
                np.min(
                    parameter_paths["5y"]["luxshare"]["global_given_entry"]
                    - parameter_paths["3y"]["luxshare"]["global_given_entry"]
                )
            ),
            10,
        ),
    }
    return {
        "schema_version": PROBABILITY_V2_SCHEMA,
        "event_contract": contract,
        "outer_parameter_samples": samples,
        "seed": seed,
        "method": "outer_parameter_monte_carlo_inner_analytic_frechet_joint",
        "dependence_semantics": (
            "lambda=0 为独立；正值向 Fréchet 同向上界移动；负值向下界移动；"
            "不是 Pearson correlation。"
        ),
        "architecture_dimension": {
            "states": ARCHITECTURE_LABELS,
            "source": architecture_source,
            "orthogonal_to_entry_state": True,
        },
        "geography_dimension": {
            "china_event": contract["china_entry"],
            "global_event": contract["global_entry"],
            "overlap_allowed": True,
            "subset_of_meaningful_entry": True,
            "unidentified_route_retained": True,
            "notice": (
                "未闭环全球头部客户不自动等于中国进入；中国和全球事件分别建模，"
                "并保留两者重叠、其他地区/未识别路径。"
            ),
        },
        "deterioration_pressure_band_source": damage_source,
        "warnings": warnings,
        "monotonic_parameter_path_audit": monotonicity,
        "geography_set_invariant_audit": geography_set_invariant_audit,
        "numerical_convergence": {
            "outer_samples": samples,
            "max_reported_mean_standard_error": round(max_standard_error, 10),
            "max_probability_sum_abs_error": round(max_probability_sum_error, 14),
        },
        "horizons": horizon_results,
    }


def simulate_probability_tree(
    config: dict[str, Any],
    *,
    samples: int = 100_000,
    seed: int = 20260718,
) -> dict[str, Any]:
    """按 schema_version 路由；无版本配置保持旧 V1 行为。"""

    if config.get("schema_version") == PROBABILITY_V2_SCHEMA:
        return _simulate_probability_tree_v2(config, samples=samples, seed=seed)
    return _simulate_probability_tree_v1(config, samples=samples, seed=seed)


def _summary(values: np.ndarray) -> dict[str, float]:
    p10, median, p90 = np.quantile(values, [0.1, 0.5, 0.9])
    return {
        "mean": round(float(values.mean()), 6),
        "p10": round(float(p10), 6),
        "median": round(float(median), 6),
        "p90": round(float(p90), 6),
    }


def calculate_market_outlook(config: dict[str, Any]) -> dict[str, Any]:
    """计算各速率市场收入、供需比和正常/额外 ASP 降价，避免混为一谈。"""

    years = [int(year) for year in config["years"]]
    rows: list[dict[str, Any]] = []
    for index, year in enumerate(years):
        total_ports = 0.0
        market_revenue_usd_bn = 0.0
        segment_rows: list[dict[str, Any]] = []
        for segment, values in config["segments"].items():
            shipments = float(values["shipments_million"][index])
            asp = float(values["normal_asp_usd"][index])
            total_ports += shipments
            revenue = shipments * asp / 1000.0
            market_revenue_usd_bn += revenue
            segment_rows.append(
                {
                    "segment": segment,
                    "shipments_million": shipments,
                    "normal_asp_usd": asp,
                    "revenue_usd_bn": round(revenue, 4),
                }
            )
        supply = float(config["qualified_supply_million"][index])
        ratio = supply / total_ports if total_ports else None
        rows.append(
            {
                "year": year,
                "segments": segment_rows,
                "total_ports_million": round(total_ports, 4),
                "normal_market_revenue_usd_bn": round(market_revenue_usd_bn, 4),
                "qualified_supply_million": supply,
                "qualified_supply_demand_ratio": round(ratio, 4) if ratio is not None else None,
                "lpo_lro_share_pct": float(config["lpo_lro_share_pct"][index]),
                "cpo_share_pct": float(config["cpo_share_pct"][index]),
            }
        )
    result = {
        "years": years,
        "rows": rows,
        "input_status": config.get("input_status", {}),
        "parameter_registry": copy.deepcopy(
            config.get("parameter_registry", [])
        ),
        "product_specification_use_boundary": copy.deepcopy(
            config.get("product_specification_use_boundary", {})
        ),
    }
    sensitivity_cases = config.get("sensitivity_cases")
    if isinstance(sensitivity_cases, dict):
        rendered_cases: dict[str, Any] = {}
        for case_key, case in sensitivity_cases.items():
            override = case.get("override") if isinstance(case, dict) else None
            if not isinstance(override, dict):
                raise ValueError(f"market.sensitivity_cases.{case_key} 缺少 override")
            case_config = copy.deepcopy(config)
            case_config.pop("sensitivity_cases", None)
            for key, value in override.items():
                case_config[key] = copy.deepcopy(value)
            case_output = calculate_market_outlook(case_config)
            rendered_cases[case_key] = {
                "label": case.get("label", case_key),
                "rationale": case.get("rationale"),
                "rows": case_output["rows"],
            }
        result["sensitivity_cases"] = rendered_cases
    return result


def _year_value(value: Any, year: int) -> float:
    if isinstance(value, dict):
        if str(year) in value:
            return float(value[str(year)])
        if year in value:
            return float(value[year])
        raise KeyError(f"缺少 {year} 年输入")
    return float(value)


def terminal_value(fcf: float, wacc: float, perpetual_growth: float) -> float:
    if not math.isfinite(float(fcf)) or fcf <= 0:
        raise ValueError("Gordon持续经营终值要求正常化自由现金流为正")
    if not 0 < perpetual_growth < wacc < 1:
        raise ValueError("终值必须满足 0 < g < WACC < 1")
    return fcf * (1.0 + perpetual_growth) / (wacc - perpetual_growth)


def _calculate_financial_scenarios_v1(
    config: dict[str, Any],
    scenario_probability: dict[str, float],
) -> dict[str, Any]:
    """旧版财务压力测试；为既有配置兼容保留。"""

    probability = {code: float(scenario_probability.get(code, 0.0)) for code in SCENARIOS}
    if not math.isclose(sum(probability.values()), 1.0, rel_tol=0, abs_tol=1e-6):
        raise ValueError(f"情景概率之和必须为 1，当前 {sum(probability.values())}")
    years = [int(year) for year in config["years"]]
    wacc = float(config["terminal"]["wacc"])
    growth = float(config["terminal"]["perpetual_growth"])
    pass_through = float(config.get("gross_to_net_pass_through", 0.72))
    result: dict[str, Any] = {"years": years, "scenario_probability": probability, "companies": {}}

    for company_key, company in config["companies"].items():
        scenario_rows: dict[str, list[dict[str, Any]]] = {}
        terminal_by_scenario: dict[str, float] = {}
        for scenario in SCENARIOS:
            shock = company["scenario_shocks"][scenario]
            rows: list[dict[str, Any]] = []
            for year in years:
                base = company["baseline"][str(year)]
                share_loss = _year_value(shock["share_loss_pct"], year) / 100.0
                extra_asp = _year_value(shock["extra_asp_pressure_pct"], year) / 100.0
                gross_shock = _year_value(shock["gross_margin_shock_ppt"], year)
                extra_capex = _year_value(shock["extra_capex_pct_revenue"], year)
                working_capital = _year_value(shock["working_capital_drag_pct_revenue"], year)
                fixed_cost_drag = _year_value(shock.get("fixed_cost_drag_ppt", 0.0), year)
                revenue = float(base["revenue_cny_yi"]) * (1.0 - share_loss) * (1.0 - extra_asp)
                gross_margin = float(base["gross_margin_pct"]) - gross_shock
                net_margin = float(base["net_margin_pct"]) - gross_shock * pass_through - fixed_cost_drag
                fcf_margin = (
                    float(base["fcf_margin_pct"])
                    - gross_shock * pass_through
                    - extra_capex
                    - working_capital
                )
                rows.append(
                    {
                        "year": year,
                        "revenue_cny_yi": round(revenue, 2),
                        "gross_margin_pct": round(gross_margin, 2),
                        "net_margin_pct": round(net_margin, 2),
                        "net_income_cny_yi": round(revenue * net_margin / 100.0, 2),
                        "fcf_margin_pct": round(fcf_margin, 2),
                        "fcf_cny_yi": round(revenue * fcf_margin / 100.0, 2),
                        "share_loss_pct": round(share_loss * 100.0, 2),
                        "extra_asp_pressure_pct": round(extra_asp * 100.0, 2),
                    }
                )
            scenario_rows[scenario] = rows
            terminal_by_scenario[scenario] = round(
                terminal_value(rows[-1]["fcf_cny_yi"], wacc, growth), 2
            )

        weighted_rows: list[dict[str, Any]] = []
        for row_index, year in enumerate(years):
            weighted_row: dict[str, Any] = {"year": year}
            for field in (
                "revenue_cny_yi",
                "gross_margin_pct",
                "net_margin_pct",
                "net_income_cny_yi",
                "fcf_margin_pct",
                "fcf_cny_yi",
            ):
                weighted_row[field] = round(
                    sum(
                        probability[code] * scenario_rows[code][row_index][field]
                        for code in SCENARIOS
                    ),
                    2,
                )
            weighted_rows.append(weighted_row)
        terminal_sensitivity: list[dict[str, Any]] = []
        expected_fcf_2031 = weighted_rows[-1]["fcf_cny_yi"]
        for sensitivity_wacc in config["terminal"]["sensitivity_wacc"]:
            for sensitivity_growth in config["terminal"]["sensitivity_growth"]:
                terminal_sensitivity.append(
                    {
                        "wacc": float(sensitivity_wacc),
                        "perpetual_growth": float(sensitivity_growth),
                        "terminal_value_cny_yi": round(
                            terminal_value(
                                expected_fcf_2031,
                                float(sensitivity_wacc),
                                float(sensitivity_growth),
                            ),
                            2,
                        ),
                    }
                )
        result["companies"][company_key] = {
            "display_name": company["display_name"],
            "scenario_rows": scenario_rows,
            "probability_weighted_rows": weighted_rows,
            "terminal_value_by_scenario_cny_yi": terminal_by_scenario,
            "probability_weighted_terminal_value_cny_yi": round(
                sum(probability[code] * terminal_by_scenario[code] for code in SCENARIOS), 2
            ),
            "terminal_sensitivity": terminal_sensitivity,
        }
    return result


def _coerce_probability_map(
    probability: dict[str, Any],
    states: tuple[str, ...],
    name: str,
) -> dict[str, float]:
    result: dict[str, float] = {}
    for state in states:
        raw = probability.get(state, 0.0)
        if isinstance(raw, dict):
            raw = raw.get("mean")
        result[state] = float(raw)
        _require_probability(result[state], f"{name}.{state}")
    total = sum(result.values())
    if not math.isclose(total, 1.0, rel_tol=0, abs_tol=1e-6):
        raise ValueError(f"{name} 概率之和必须为 1，当前 {total}")
    return result


def _neutral_financial_shock() -> dict[str, float]:
    return {
        "share_loss_pct": 0.0,
        "extra_asp_pressure_pct": 0.0,
        "gross_margin_shock_ppt": 0.0,
        "fixed_cost_drag_ppt": 0.0,
        "maintenance_capex_increment_pct_revenue": 0.0,
        "normalized_working_capital_drag_pct_revenue": 0.0,
        "normalized_other_fcf_drag_ppt": 0.0,
        "expansion_capex_pct_revenue": 0.0,
        "working_capital_change_pct_revenue": 0.0,
        "expansion_capex_cny_yi": 0.0,
        "working_capital_change_cny_yi": 0.0,
    }


def _shock_year_value(
    shock: dict[str, Any],
    field: str,
    year: int,
    *,
    aliases: tuple[str, ...] = (),
) -> float:
    if field in shock:
        return _year_value(shock[field], year)
    for alias in aliases:
        if alias in shock:
            return _year_value(shock[alias], year)
    return 0.0


def _combined_v2_shock(
    entry_shock: dict[str, Any],
    architecture_shock: dict[str, Any],
    year: int,
) -> dict[str, float]:
    result: dict[str, float] = {}
    field_aliases = {
        "expansion_capex_pct_revenue": ("extra_capex_pct_revenue",),
        "working_capital_change_pct_revenue": (
            "working_capital_drag_pct_revenue",
        ),
    }
    for field in _neutral_financial_shock():
        aliases = field_aliases.get(field, ())
        result[field] = _shock_year_value(
            entry_shock, field, year, aliases=aliases
        ) + _shock_year_value(architecture_shock, field, year, aliases=aliases)
    return result


def _discount_year_fraction(valuation_date: date, cashflow_date: date) -> float:
    if cashflow_date <= valuation_date:
        raise ValueError("现金流/终值日期必须晚于 valuation_date")
    return (cashflow_date - valuation_date).days / 365.25


def _sustainable_terminal_value(
    normalized_fcf: float,
    wacc: float,
    perpetual_growth: float,
) -> tuple[bool, float, str | None]:
    """只在正常化自由现金流为正时使用 Gordon 永续增长公式。

    非正现金流意味着稳定持续经营前提不成立。此时主模型把终值记为 0，
    并显式标记为不适用；重组、再融资和清算回收需要另建模型，不能用
    一个负的 Gordon 结果代替。
    """

    if not math.isfinite(float(normalized_fcf)):
        raise ValueError("正常化自由现金流必须是有限数")
    if normalized_fcf <= 0:
        return (
            False,
            0.0,
            "2031年正常化自由现金流小于或等于0，稳定持续经营终值不适用",
        )
    return True, terminal_value(normalized_fcf, wacc, perpetual_growth), None


def _identical_cash_input_audit(
    *,
    entry_shocks: dict[str, Any],
    architecture_shocks: dict[str, Any],
    years: list[int],
) -> list[dict[str, Any]]:
    """识别扩产资本开支与营运资本完全相同的输入序列。

    该记录只解释重复输出的来源，不把相同输入当作独立证据，也不改变
    任何计算结果。
    """

    findings: list[dict[str, Any]] = []
    for dimension, states, shocks in (
        ("entry_state", ENTRY_SCENARIOS, entry_shocks),
        ("architecture_state", ARCHITECTURE_STATES, architecture_shocks),
    ):
        for state in states:
            shock = shocks.get(state, _neutral_financial_shock())
            capex = [
                _shock_year_value(
                    shock,
                    "expansion_capex_pct_revenue",
                    year,
                    aliases=("extra_capex_pct_revenue",),
                )
                for year in years
            ]
            working_capital = [
                _shock_year_value(
                    shock,
                    "working_capital_change_pct_revenue",
                    year,
                    aliases=("working_capital_drag_pct_revenue",),
                )
                for year in years
            ]
            if any(abs(value) > 1e-12 for value in capex) and all(
                math.isclose(left, right, rel_tol=0, abs_tol=1e-12)
                for left, right in zip(capex, working_capital)
            ):
                findings.append(
                    {
                        "dimension": dimension,
                        "state": state,
                        "years": list(years),
                        "identical_input_series_pct_revenue": capex,
                        "fields": [
                            "expansion_capex_pct_revenue",
                            "working_capital_change_pct_revenue",
                        ],
                        "interpretation": (
                            "两列重复来自配置中的相同输入序列，不是计算器复制结果；"
                            "取得独立的设备投资和营运资本证据前，不应把两列视为独立估计。"
                        ),
                    }
                )
    return findings


def _interpolate_probability_schedule(
    *,
    years: list[int],
    start_year: int,
    first_horizon_year: int,
    second_horizon_year: int,
    start_probability: dict[str, float],
    first_horizon_probability: dict[str, Any],
    second_horizon_probability: dict[str, Any],
    states: tuple[str, ...],
    name: str,
    non_event_state: str | None = None,
) -> dict[str, dict[str, float]]:
    """把累计 3 年/5 年状态概率转成逐年权重，避免用 5 年终局权重回填整条路径。"""

    if not start_year < first_horizon_year < second_horizon_year:
        raise ValueError(f"{name} 概率期限必须满足起点 < 第一锚点 < 第二锚点")
    start = _coerce_probability_map(start_probability, states, f"{name}.start")
    first = _coerce_probability_map(
        first_horizon_probability, states, f"{name}.first_horizon"
    )
    second = _coerce_probability_map(
        second_horizon_probability, states, f"{name}.second_horizon"
    )
    schedule: dict[str, dict[str, float]] = {}
    for year in years:
        if year <= start_year:
            current = dict(start)
        elif year <= first_horizon_year:
            fraction = (year - start_year) / (first_horizon_year - start_year)
            current = {
                state: start[state] + fraction * (first[state] - start[state])
                for state in states
            }
        elif year <= second_horizon_year:
            fraction = (year - first_horizon_year) / (
                second_horizon_year - first_horizon_year
            )
            current = {
                state: first[state] + fraction * (second[state] - first[state])
                for state in states
            }
        else:
            current = dict(second)
        total = sum(current.values())
        if not math.isclose(total, 1.0, abs_tol=1e-7):
            raise ValueError(f"{name}.{year} 概率和不为1：{total}")
        schedule[str(year)] = {state: value / total for state, value in current.items()}
    if non_event_state is not None:
        if non_event_state not in states:
            raise ValueError(f"{name}.non_event_state 不在状态集合中")
        cumulative_event_probability = [
            1.0 - schedule[str(year)][non_event_state] for year in years
        ]
        if any(
            later + 1e-10 < earlier
            for earlier, later in zip(
                cumulative_event_probability,
                cumulative_event_probability[1:],
            )
        ):
            raise ValueError(f"{name} 累计事件概率随时间下降")
    return schedule


def _probability_weighted_financial_row(
    *,
    cross_rows: dict[str, list[dict[str, Any]]],
    row_index: int,
    year: int,
    entry_probability: dict[str, float],
    architecture_probability: dict[str, float],
) -> dict[str, Any]:
    """先加权金额再计算利润率，避免把 E[率] 误写成合并口径利润率。"""

    weighted_amounts = {
        field: 0.0
        for field in (
            "revenue_cny_yi",
            "net_income_cny_yi",
            "normalized_fcf_cny_yi",
            "expansion_capex_cny_yi",
            "working_capital_change_cny_yi",
            "fcf_cny_yi",
            "discounted_fcf_cny_yi",
        )
    }
    weighted_gross_profit = 0.0
    for entry in ENTRY_SCENARIOS:
        for architecture in ARCHITECTURE_STATES:
            weight = entry_probability[entry] * architecture_probability[architecture]
            row = cross_rows[f"{entry}|{architecture}"][row_index]
            for field in weighted_amounts:
                weighted_amounts[field] += weight * float(row[field])
            weighted_gross_profit += weight * float(
                row.get(
                    "gross_profit_cny_yi",
                    float(row["revenue_cny_yi"])
                    * float(row["gross_margin_pct"])
                    / 100.0,
                )
            )
    revenue = weighted_amounts["revenue_cny_yi"]
    if revenue <= 0:
        raise ValueError(f"{year} 概率加权收入必须为正")
    return {
        "year": year,
        "revenue_cny_yi": round(revenue, 2),
        "gross_profit_cny_yi": round(weighted_gross_profit, 2),
        "gross_margin_pct": round(weighted_gross_profit / revenue * 100.0, 2),
        "net_margin_pct": round(
            weighted_amounts["net_income_cny_yi"] / revenue * 100.0, 2
        ),
        "net_income_cny_yi": round(weighted_amounts["net_income_cny_yi"], 2),
        "normalized_fcf_margin_pct": round(
            weighted_amounts["normalized_fcf_cny_yi"] / revenue * 100.0, 2
        ),
        "normalized_fcf_cny_yi": round(
            weighted_amounts["normalized_fcf_cny_yi"], 2
        ),
        "expansion_capex_cny_yi": round(
            weighted_amounts["expansion_capex_cny_yi"], 2
        ),
        "working_capital_change_cny_yi": round(
            weighted_amounts["working_capital_change_cny_yi"], 2
        ),
        "fcf_cny_yi": round(weighted_amounts["fcf_cny_yi"], 2),
        "fcf_margin_pct": round(
            weighted_amounts["fcf_cny_yi"] / revenue * 100.0, 2
        ),
        "discounted_fcf_cny_yi": round(
            weighted_amounts["discounted_fcf_cny_yi"], 2
        ),
    }


def _conditional_financial_summary_after_entry(
    *,
    cross_rows: dict[str, list[dict[str, Any]]],
    terminal_by_cross_state: dict[str, float],
    discounted_terminal_by_cross_state: dict[str, float],
    entry_probability: dict[str, float],
    architecture_probability: dict[str, float],
    year: int,
) -> dict[str, Any]:
    """排除“无有意义进入”后重新归一，回答进入已经发生时的财务影响。"""

    entry_denominator = sum(
        float(entry_probability[state]) for state in ENTRY_SCENARIOS if state != "A"
    )
    if not 0.0 < entry_denominator <= 1.0:
        raise ValueError("至少一家进入的条件概率分母必须在 (0, 1] 内")
    conditional_entry_probability = {
        state: (
            0.0
            if state == "A"
            else float(entry_probability[state]) / entry_denominator
        )
        for state in ENTRY_SCENARIOS
    }
    reference_rows = cross_rows["A|P"]
    try:
        row_index = next(
            index for index, row in enumerate(reference_rows) if int(row["year"]) == year
        )
    except StopIteration as exc:
        raise ValueError(f"条件财务汇总缺少 {year} 年参考路径") from exc
    conditional_row = _probability_weighted_financial_row(
        cross_rows=cross_rows,
        row_index=row_index,
        year=year,
        entry_probability=conditional_entry_probability,
        architecture_probability=architecture_probability,
    )
    reference_row = reference_rows[row_index]
    conditional_terminal = sum(
        conditional_entry_probability[entry]
        * architecture_probability[architecture]
        * float(terminal_by_cross_state[f"{entry}|{architecture}"])
        for entry in ENTRY_SCENARIOS
        for architecture in ARCHITECTURE_STATES
    )
    conditional_discounted_terminal = sum(
        conditional_entry_probability[entry]
        * architecture_probability[architecture]
        * float(discounted_terminal_by_cross_state[f"{entry}|{architecture}"])
        for entry in ENTRY_SCENARIOS
        for architecture in ARCHITECTURE_STATES
    )
    reference_terminal = float(terminal_by_cross_state["A|P"])
    reference_discounted_terminal = float(
        discounted_terminal_by_cross_state["A|P"]
    )

    def loss_pct(reference: float, conditioned: float) -> float:
        if reference <= 0:
            raise ValueError("条件财务汇总的参考值必须为正")
        return round((1.0 - conditioned / reference) * 100.0, 2)

    return {
        "year": year,
        "entry_probability_denominator": round(entry_denominator, 10),
        "reference_row": copy.deepcopy(reference_row),
        "row": conditional_row,
        "reference_terminal_value_cny_yi": round(reference_terminal, 2),
        "terminal_value_cny_yi": round(conditional_terminal, 2),
        "reference_discounted_terminal_value_cny_yi": round(
            reference_discounted_terminal, 2
        ),
        "discounted_terminal_value_cny_yi": round(
            conditional_discounted_terminal, 2
        ),
        "loss_vs_reference_pct": {
            "revenue": loss_pct(
                float(reference_row["revenue_cny_yi"]),
                float(conditional_row["revenue_cny_yi"]),
            ),
            "net_income": loss_pct(
                float(reference_row["net_income_cny_yi"]),
                float(conditional_row["net_income_cny_yi"]),
            ),
            "normalized_fcf": loss_pct(
                float(reference_row["normalized_fcf_cny_yi"]),
                float(conditional_row["normalized_fcf_cny_yi"]),
            ),
            "fcf": loss_pct(
                float(reference_row["fcf_cny_yi"]),
                float(conditional_row["fcf_cny_yi"]),
            ),
            "terminal": loss_pct(reference_terminal, conditional_terminal),
            "discounted_terminal": loss_pct(
                reference_discounted_terminal, conditional_discounted_terminal
            ),
        },
        "method": (
            "排除无有意义进入状态A，将其余进入状态与三种架构的联合概率重新归一，"
            "再对同一年度的收入、净利润、现金流和正常化终值逐路径加权。"
        ),
    }


def _calculate_financial_scenarios_v2(
    config: dict[str, Any],
    entry_state_probability: dict[str, Any],
    architecture_probability: dict[str, Any],
    annual_entry_state_probability: dict[str, dict[str, Any]] | None = None,
    annual_architecture_probability: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """V2：正交叠加 A—F 与 P/H/C，并以 normalized FCF 计算折现终值。"""

    if config.get("schema_version") != FINANCIAL_V2_SCHEMA:
        raise ValueError(f"V2 财务配置必须声明 schema_version={FINANCIAL_V2_SCHEMA}")
    entry_probability = _coerce_probability_map(
        entry_state_probability, ENTRY_SCENARIOS, "entry_state_probability"
    )
    architecture_probability = _coerce_probability_map(
        architecture_probability, ARCHITECTURE_STATES, "architecture_probability"
    )
    years = [int(year) for year in config["years"]]
    if years != sorted(set(years)):
        raise ValueError("financial.years 必须严格递增且不重复")
    try:
        valuation_date = date.fromisoformat(str(config["valuation_date"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("V2 财务配置必须提供 ISO valuation_date") from exc
    terminal_config = config["terminal"]
    terminal_date = date.fromisoformat(
        str(terminal_config.get("terminal_date", f"{years[-1]}-12-31"))
    )
    wacc = float(terminal_config["wacc"])
    growth = float(terminal_config["perpetual_growth"])
    terminal_years = _discount_year_fraction(valuation_date, terminal_date)
    pass_through = float(config.get("gross_to_net_pass_through", 0.72))
    annual_entry_probability = {
        str(year): _coerce_probability_map(
            (annual_entry_state_probability or {}).get(str(year), entry_probability),
            ENTRY_SCENARIOS,
            f"annual_entry_state_probability.{year}",
        )
        for year in years
    }
    annual_architecture_probability = {
        str(year): _coerce_probability_map(
            (annual_architecture_probability or {}).get(
                str(year), architecture_probability
            ),
            ARCHITECTURE_STATES,
            f"annual_architecture_probability.{year}",
        )
        for year in years
    }
    result: dict[str, Any] = {
        "schema_version": FINANCIAL_V2_SCHEMA,
        "valuation_date": valuation_date.isoformat(),
        "terminal_date": terminal_date.isoformat(),
        "years": years,
        "entry_state_probability": entry_probability,
        "architecture_probability": architecture_probability,
        "annual_probability_schedule": {
            "entry_state_probability": annual_entry_probability,
            "architecture_probability": annual_architecture_probability,
            "method": (
                "2026使用尚未达到有意义进入/架构迁移的起点；2027—2029线性走向3年累计概率，"
                "2030—2031线性走向5年累计概率。它是透明的年度时点插值，不是新增事实。"
            ),
        },
        "cross_state_probability": {
            f"{entry}|{architecture}": round(
                entry_probability[entry] * architecture_probability[architecture], 10
            )
            for entry in ENTRY_SCENARIOS
            for architecture in ARCHITECTURE_STATES
        },
        "orthogonal_dimensions": True,
        "terminal_policy": {
            "uses_normalized_fcf": True,
            "expansion_capex_terminalized": False,
            "working_capital_change_terminalized": False,
            "discounted_to_valuation_date": True,
            "positive_normalized_fcf_required": True,
            "nonpositive_normalized_fcf_treatment": (
                "terminal_not_applicable_and_value_set_to_zero"
            ),
            "signed_gordon_value_is_primary": False,
            "zero_floor_sensitivity_is_reported": False,
            "negative_terminal_interpretation": (
                "2031年正常化自由现金流小于或等于0时不调用Gordon公式，"
                "持续经营终值标记为不适用并在本压力测试中计0；"
                "重组、再融资或清算回收需要单独建模。"
            ),
            "liquidation_recovery_or_recapitalization_modeled": False,
        },
        "operating_assumptions": {
            "gross_to_net_pass_through": pass_through,
            "gross_to_net_pass_through_formula": (
                "net_margin_shock_ppt = gross_margin_shock_ppt × "
                "gross_to_net_pass_through + fixed_cost_drag_ppt"
            ),
            "terminal_wacc": wacc,
            "terminal_perpetual_growth": growth,
            "valuation_date": valuation_date.isoformat(),
            "terminal_date": terminal_date.isoformat(),
            "epistemic_status": "scenario_assumption_not_observed_fact",
        },
        "parameter_registry": copy.deepcopy(
            config.get("parameter_registry", [])
        ),
        "requested_field_coverage": copy.deepcopy(
            config.get("requested_field_coverage", [])
        ),
        "companies": {},
    }

    for company_key, company in config["companies"].items():
        high_speed_exposure_share = float(
            company.get("high_speed_revenue_exposure_share", 1.0)
        )
        if not 0.0 <= high_speed_exposure_share <= 1.0:
            raise ValueError(
                f"{company_key}.high_speed_revenue_exposure_share 必须在[0,1]"
            )
        entry_shocks = company.get("entry_state_shocks", company.get("scenario_shocks"))
        if not isinstance(entry_shocks, dict):
            raise ValueError(f"{company_key} 缺少 entry_state_shocks")
        architecture_shocks = company.get("architecture_shocks", {})
        cross_rows: dict[str, list[dict[str, Any]]] = {}
        terminal_by_cross_state: dict[str, float] = {}
        discounted_terminal_by_cross_state: dict[str, float] = {}
        terminal_applicable_by_cross_state: dict[str, bool] = {}
        terminal_inapplicable_reason_by_cross_state: dict[str, str | None] = {}
        zero_floor_terminal_by_cross_state: dict[str, float] = {}
        discounted_zero_floor_terminal_by_cross_state: dict[str, float] = {}
        nonpositive_terminal_states: list[dict[str, Any]] = []
        for entry_state in ENTRY_SCENARIOS:
            entry_shock = entry_shocks.get(entry_state, _neutral_financial_shock())
            for architecture_state in ARCHITECTURE_STATES:
                architecture_shock = architecture_shocks.get(
                    architecture_state, _neutral_financial_shock()
                )
                cross_key = f"{entry_state}|{architecture_state}"
                rows: list[dict[str, Any]] = []
                for year in years:
                    base = company["baseline"][str(year)]
                    shock = _combined_v2_shock(entry_shock, architecture_shock, year)
                    share_loss = shock["share_loss_pct"] / 100.0
                    extra_asp = shock["extra_asp_pressure_pct"] / 100.0
                    if not 0.0 <= share_loss < 1.0 or not 0.0 <= extra_asp < 1.0:
                        raise ValueError(
                            f"{company_key}.{cross_key}.{year} share/ASP shock 必须在 [0,100)"
                        )
                    base_revenue = float(base["revenue_cny_yi"])
                    exposed_revenue = base_revenue * high_speed_exposure_share
                    non_exposed_revenue = base_revenue - exposed_revenue
                    shocked_exposed_revenue = (
                        exposed_revenue
                        * (1.0 - share_loss)
                        * (1.0 - extra_asp)
                    )
                    revenue = non_exposed_revenue + shocked_exposed_revenue
                    base_gross_margin = float(base["gross_margin_pct"])
                    exposed_gross_margin = (
                        base_gross_margin - shock["gross_margin_shock_ppt"]
                    )
                    gross_profit = (
                        non_exposed_revenue * base_gross_margin / 100.0
                        + shocked_exposed_revenue
                        * exposed_gross_margin
                        / 100.0
                    )
                    gross_margin = gross_profit / revenue * 100.0
                    base_net_margin = float(base["net_margin_pct"])
                    exposed_net_margin = (
                        base_net_margin
                        - shock["gross_margin_shock_ppt"] * pass_through
                        - shock["fixed_cost_drag_ppt"]
                    )
                    net_income = (
                        non_exposed_revenue * base_net_margin / 100.0
                        + shocked_exposed_revenue * exposed_net_margin / 100.0
                    )
                    net_margin = net_income / revenue * 100.0
                    base_normalized_fcf_margin = float(
                        base.get("normalized_fcf_margin_pct", base["fcf_margin_pct"])
                    )
                    exposed_normalized_fcf_margin = (
                        base_normalized_fcf_margin
                        - shock["gross_margin_shock_ppt"] * pass_through
                        - shock["fixed_cost_drag_ppt"]
                        - shock["maintenance_capex_increment_pct_revenue"]
                        - shock["normalized_working_capital_drag_pct_revenue"]
                        - shock["normalized_other_fcf_drag_ppt"]
                    )
                    expansion_capex = (
                        shocked_exposed_revenue
                        * shock["expansion_capex_pct_revenue"]
                        / 100.0
                        + shock["expansion_capex_cny_yi"]
                        * high_speed_exposure_share
                    )
                    working_capital_change = (
                        shocked_exposed_revenue
                        * shock["working_capital_change_pct_revenue"]
                        / 100.0
                        + shock["working_capital_change_cny_yi"]
                        * high_speed_exposure_share
                    )
                    normalized_fcf = (
                        non_exposed_revenue
                        * base_normalized_fcf_margin
                        / 100.0
                        + shocked_exposed_revenue
                        * exposed_normalized_fcf_margin
                        / 100.0
                    )
                    normalized_fcf_margin = normalized_fcf / revenue * 100.0
                    annual_fcf = normalized_fcf - expansion_capex - working_capital_change
                    cashflow_date = date(year, 12, 31)
                    discount_years = _discount_year_fraction(valuation_date, cashflow_date)
                    discounted_fcf = annual_fcf / ((1.0 + wacc) ** discount_years)
                    rows.append(
                        {
                            "year": year,
                            "revenue_cny_yi": round(revenue, 2),
                            "gross_profit_cny_yi": round(gross_profit, 6),
                            "gross_margin_pct": round(gross_margin, 2),
                            "net_margin_pct": round(net_margin, 2),
                            "net_income_cny_yi": round(net_income, 2),
                            "normalized_fcf_margin_pct": round(
                                normalized_fcf_margin, 2
                            ),
                            "normalized_fcf_cny_yi": round(normalized_fcf, 2),
                            "expansion_capex_cny_yi": round(expansion_capex, 2),
                            "working_capital_change_cny_yi": round(
                                working_capital_change, 2
                            ),
                            "fcf_cny_yi": round(annual_fcf, 2),
                            "discounted_fcf_cny_yi": round(discounted_fcf, 2),
                            "share_loss_pct": round(
                                share_loss * high_speed_exposure_share * 100.0,
                                2,
                            ),
                            "extra_asp_pressure_pct": round(
                                extra_asp * high_speed_exposure_share * 100.0,
                                2,
                            ),
                            "exposed_segment_share_loss_pct": round(
                                share_loss * 100.0, 2
                            ),
                            "exposed_segment_extra_asp_pressure_pct": round(
                                extra_asp * 100.0, 2
                            ),
                            "gross_margin_shock_ppt": round(
                                shock["gross_margin_shock_ppt"], 2
                            ),
                            "expansion_capex_pct_revenue": round(
                                shock["expansion_capex_pct_revenue"], 3
                            ),
                            "working_capital_change_pct_revenue": round(
                                shock["working_capital_change_pct_revenue"], 3
                            ),
                            "fixed_cost_drag_ppt": round(
                                shock["fixed_cost_drag_ppt"], 2
                            ),
                            "high_speed_revenue_exposure_share_pct": round(
                                high_speed_exposure_share * 100.0, 2
                            ),
                        }
                    )
                cross_rows[cross_key] = rows
                normalized_terminal_fcf = rows[-1]["normalized_fcf_cny_yi"]
                terminal_applicable, raw_terminal, inapplicable_reason = (
                    _sustainable_terminal_value(
                    normalized_terminal_fcf, wacc, growth
                    )
                )
                terminal_applicable_by_cross_state[cross_key] = (
                    terminal_applicable
                )
                terminal_inapplicable_reason_by_cross_state[cross_key] = (
                    inapplicable_reason
                )
                terminal_by_cross_state[cross_key] = round(raw_terminal, 2)
                discounted_terminal_by_cross_state[cross_key] = round(
                    raw_terminal / ((1.0 + wacc) ** terminal_years), 2
                )
                # 兼容旧内部消费者：zero_floor 字段保留为主结果的等值别名，
                # 不再代表另一套可公开比较的估值方法。
                zero_floor_terminal_by_cross_state[cross_key] = round(raw_terminal, 2)
                discounted_zero_floor_terminal_by_cross_state[cross_key] = round(
                    raw_terminal / ((1.0 + wacc) ** terminal_years), 2
                )
                if not terminal_applicable:
                    nonpositive_terminal_states.append(
                        {
                            "cross_state": cross_key,
                            "normalized_terminal_fcf_cny_yi": normalized_terminal_fcf,
                            "terminal_value_applicable": False,
                            "terminal_value_cny_yi": 0.0,
                            "reason": inapplicable_reason,
                            # 旧内部报告器仍按数值格式化以下字段；二者均映射到
                            # 新主结果0，不再保存或展示负Gordon终值。
                            "signed_terminal_value_cny_yi": 0.0,
                            "zero_floor_terminal_value_cny_yi": 0.0,
                            "joint_probability": round(
                                entry_probability[entry_state]
                                * architecture_probability[architecture_state],
                                10,
                            ),
                        }
                    )

        weighted_rows: list[dict[str, Any]] = []
        for row_index, year in enumerate(years):
            weighted_rows.append(
                _probability_weighted_financial_row(
                    cross_rows=cross_rows,
                    row_index=row_index,
                    year=year,
                    entry_probability=annual_entry_probability[str(year)],
                    architecture_probability=annual_architecture_probability[
                        str(year)
                    ],
                )
            )

        terminal_sensitivity: list[dict[str, Any]] = []
        for sensitivity_wacc in terminal_config["sensitivity_wacc"]:
            for sensitivity_growth in terminal_config["sensitivity_growth"]:
                sensitivity_wacc = float(sensitivity_wacc)
                sensitivity_growth = float(sensitivity_growth)
                terminal_sensitivity_value = 0.0
                discounted_terminal_sensitivity_value = 0.0
                inapplicable_state_count = 0
                inapplicable_probability = 0.0
                discount_factor = (1.0 + sensitivity_wacc) ** terminal_years
                for entry in ENTRY_SCENARIOS:
                    for architecture in ARCHITECTURE_STATES:
                        probability_weight = (
                            entry_probability[entry]
                            * architecture_probability[architecture]
                        )
                        state_fcf = cross_rows[f"{entry}|{architecture}"][-1][
                            "normalized_fcf_cny_yi"
                        ]
                        state_applicable, raw_state_terminal, _ = (
                            _sustainable_terminal_value(
                                state_fcf,
                                sensitivity_wacc,
                                sensitivity_growth,
                            )
                        )
                        state_terminal = round(raw_state_terminal, 2)
                        terminal_sensitivity_value += (
                            probability_weight * state_terminal
                        )
                        discounted_terminal_sensitivity_value += probability_weight * round(
                            raw_state_terminal / discount_factor, 2
                        )
                        if not state_applicable:
                            inapplicable_state_count += 1
                            inapplicable_probability += probability_weight
                terminal_sensitivity.append(
                    {
                        "wacc": sensitivity_wacc,
                        "perpetual_growth": sensitivity_growth,
                        "aggregation_method": (
                            "state_level_positive_normalized_fcf_only_gordon_"
                            "then_probability_weight;nonpositive_states_"
                            "marked_not_applicable_and_counted_as_zero"
                        ),
                        "terminal_value_cny_yi": round(
                            terminal_sensitivity_value, 2
                        ),
                        "discounted_terminal_value_cny_yi": round(
                            discounted_terminal_sensitivity_value, 2
                        ),
                        "not_applicable_state_count": inapplicable_state_count,
                        "not_applicable_probability": round(
                            inapplicable_probability, 10
                        ),
                        # 以下三项为旧内部消费者的等值兼容别名。
                        "terminal_value_zero_floor_cny_yi": round(
                            terminal_sensitivity_value, 2
                        ),
                        "discounted_terminal_value_zero_floor_cny_yi": round(
                            discounted_terminal_sensitivity_value, 2
                        ),
                        "terminal_zero_floor_uplift_cny_yi": 0.0,
                        "discounted_terminal_zero_floor_uplift_cny_yi": 0.0,
                    }
                )
        probability_weighted_terminal = sum(
            entry_probability[entry]
            * architecture_probability[architecture]
            * terminal_by_cross_state[f"{entry}|{architecture}"]
            for entry in ENTRY_SCENARIOS
            for architecture in ARCHITECTURE_STATES
        )
        probability_weighted_zero_floor_terminal = sum(
            entry_probability[entry]
            * architecture_probability[architecture]
            * zero_floor_terminal_by_cross_state[f"{entry}|{architecture}"]
            for entry in ENTRY_SCENARIOS
            for architecture in ARCHITECTURE_STATES
        )
        probability_weighted_discounted_terminal = sum(
            entry_probability[entry]
            * architecture_probability[architecture]
            * discounted_terminal_by_cross_state[f"{entry}|{architecture}"]
            for entry in ENTRY_SCENARIOS
            for architecture in ARCHITECTURE_STATES
        )
        probability_weighted_discounted_zero_floor_terminal = sum(
            entry_probability[entry]
            * architecture_probability[architecture]
            * discounted_zero_floor_terminal_by_cross_state[
                f"{entry}|{architecture}"
            ]
            for entry in ENTRY_SCENARIOS
            for architecture in ARCHITECTURE_STATES
        )
        if not math.isclose(
            probability_weighted_terminal,
            probability_weighted_zero_floor_terminal,
            rel_tol=0,
            abs_tol=1e-9,
        ) or not math.isclose(
            probability_weighted_discounted_terminal,
            probability_weighted_discounted_zero_floor_terminal,
            rel_tol=0,
            abs_tol=1e-9,
        ):
            raise AssertionError("终值兼容别名与主结果不一致")
        valuation_year = valuation_date.year
        baseline_post_valuation_year_fcf_pv = sum(
            row["discounted_fcf_cny_yi"]
            for row in cross_rows["A|P"]
            if int(row["year"]) > valuation_year
        )
        weighted_post_valuation_year_fcf_pv = sum(
            row["discounted_fcf_cny_yi"]
            for row in weighted_rows
            if int(row["year"]) > valuation_year
        )
        baseline_operating_value_proxy = (
            baseline_post_valuation_year_fcf_pv
            + discounted_terminal_by_cross_state["A|P"]
        )
        weighted_operating_value_proxy = (
            weighted_post_valuation_year_fcf_pv
            + probability_weighted_discounted_terminal
        )
        weighted_zero_floor_operating_value_proxy = (
            weighted_post_valuation_year_fcf_pv
            + probability_weighted_discounted_zero_floor_terminal
        )
        entry_only_operating_value_proxy = sum(
            annual_entry_probability[str(row["year"])][entry]
            * row["discounted_fcf_cny_yi"]
            for entry in ENTRY_SCENARIOS
            for row in cross_rows[f"{entry}|P"]
            if int(row["year"]) > valuation_year
        ) + sum(
            entry_probability[entry]
            * discounted_terminal_by_cross_state[f"{entry}|P"]
            for entry in ENTRY_SCENARIOS
        )
        architecture_only_operating_value_proxy = sum(
            annual_architecture_probability[str(row["year"])][architecture]
            * row["discounted_fcf_cny_yi"]
            for architecture in ARCHITECTURE_STATES
            for row in cross_rows[f"A|{architecture}"]
            if int(row["year"]) > valuation_year
        ) + sum(
            architecture_probability[architecture]
            * discounted_terminal_by_cross_state[f"A|{architecture}"]
            for architecture in ARCHITECTURE_STATES
        )
        valuation_anchor = company.get("valuation_anchor") or {}
        market_cap = valuation_anchor.get("market_cap_cny_yi")
        valuation_bridge: dict[str, Any] = {
            "valuation_anchor": valuation_anchor,
            "proxy_definition": (
                "2027—2031概率加权折现实际FCF + 概率加权折现2031正常化终值；"
                "排除完整2026年FCF，避免把估值日前已发生现金流重复计入。"
            ),
            "stub_2026_status": (
                "not_modeled_missing_valuation_date_net_debt_and_ytd_actual_fcf_bridge"
            ),
            "baseline_no_entry_operating_value_proxy_cny_yi": round(
                baseline_operating_value_proxy, 2
            ),
            "probability_weighted_operating_value_proxy_cny_yi": round(
                weighted_operating_value_proxy, 2
            ),
            "probability_weighted_zero_floor_operating_value_proxy_cny_yi": round(
                weighted_zero_floor_operating_value_proxy, 2
            ),
            "entry_only_discount_vs_A_P_pct": round(
                (
                    entry_only_operating_value_proxy
                    / max(baseline_operating_value_proxy, 1e-12)
                    - 1.0
                )
                * 100.0,
                2,
            ),
            "architecture_only_discount_vs_A_P_pct": round(
                (
                    architecture_only_operating_value_proxy
                    / max(baseline_operating_value_proxy, 1e-12)
                    - 1.0
                )
                * 100.0,
                2,
            ),
            "combined_entry_and_architecture_discount_vs_A_P_pct": round(
                (
                    weighted_operating_value_proxy
                    / max(baseline_operating_value_proxy, 1e-12)
                    - 1.0
                )
                * 100.0,
                2,
            ),
            "decomposition_note": (
                "entry_only固定架构P并按A—F概率加权；architecture_only固定无进入A并按P/H/C概率加权；"
                "combined为A—F×P/H/C交叉联合结果，交互项使三者不可简单相加。"
            ),
            "comparability_status": (
                "diagnostic_only_not_equity_fair_value_missing_net_cash_debt_"
                "minority_interest_other_assets_and_2026_stub"
            ),
            "reverse_dcf_status": (
                "limited_unadjusted_market_cap_as_enterprise_value_diagnostic_only"
                if isinstance(market_cap, (int, float)) and math.isfinite(float(market_cap))
                else "blocked_missing_market_cap"
            ),
            "required_equity_bridge_inputs": [
                "valuation_date_net_cash_or_net_debt",
                "minority_interest",
                "non_operating_assets_and_other_business_value",
                "post_valuation_date_2026_stub_fcf",
                "diluted_share_count_and_corporate_actions",
            ],
        }
        if isinstance(market_cap, (int, float)) and math.isfinite(float(market_cap)):
            market_cap = float(market_cap)
            base_discount_factor = (1.0 + wacc) ** terminal_years
            implied_discounted_terminal = (
                market_cap - weighted_post_valuation_year_fcf_pv
            )
            implied_terminal = implied_discounted_terminal * base_discount_factor
            implied_normalized_fcf = (
                implied_terminal * (wacc - growth) / (1.0 + growth)
            )
            modeled_normalized_fcf = weighted_rows[-1][
                "normalized_fcf_cny_yi"
            ]
            valuation_bridge.update(
                {
                    "current_equity_market_cap_cny_yi": round(market_cap, 2),
                    "operating_value_proxy_to_market_cap_pct": round(
                        weighted_operating_value_proxy / market_cap * 100.0, 2
                    ),
                    "unadjusted_market_cap_as_ev_implied_2031_normalized_fcf_cny_yi": round(
                        implied_normalized_fcf, 2
                    ),
                    "modeled_probability_weighted_2031_normalized_fcf_cny_yi": round(
                        modeled_normalized_fcf, 2
                    ),
                    "unadjusted_implied_to_modeled_2031_fcf_multiple": round(
                        implied_normalized_fcf
                        / max(modeled_normalized_fcf, 1e-12),
                        2,
                    ),
                    "reverse_dcf_formula": (
                        "[(current equity market cap - PV of 2027—2031 FCF) × "
                        "(1+WACC)^terminal_years] × (WACC-g)/(1+g); "
                        "market cap is used as an unadjusted EV proxy solely to expose the missing bridge."
                    ),
                }
            )
        baseline_revenue_sensitivity_outputs: dict[str, Any] = {}
        for case_name, revenue_path in company.get(
            "baseline_revenue_sensitivity", {}
        ).items():
            if len(revenue_path) != len(years):
                raise ValueError(
                    f"{company_key}.baseline_revenue_sensitivity.{case_name} 长度错误"
                )
            sensitivity_cross_rows: dict[str, list[dict[str, Any]]] = {}
            sensitivity_terminal_by_state: dict[str, float] = {}
            sensitivity_terminal_applicable_by_state: dict[str, bool] = {}
            sensitivity_floor_terminal_by_state: dict[str, float] = {}
            sensitivity_discounted_terminal_by_state: dict[str, float] = {}
            sensitivity_discounted_floor_terminal_by_state: dict[
                str, float
            ] = {}
            for entry_state in ENTRY_SCENARIOS:
                entry_shock = entry_shocks.get(
                    entry_state, _neutral_financial_shock()
                )
                for architecture_state in ARCHITECTURE_STATES:
                    architecture_shock = architecture_shocks.get(
                        architecture_state, _neutral_financial_shock()
                    )
                    cross_key = f"{entry_state}|{architecture_state}"
                    state_rows: list[dict[str, Any]] = []
                    for index, year in enumerate(years):
                        sensitivity_base_revenue = float(revenue_path[index])
                        if (
                            not math.isfinite(sensitivity_base_revenue)
                            or sensitivity_base_revenue <= 0
                        ):
                            raise ValueError(
                                f"{company_key}.baseline_revenue_sensitivity."
                                f"{case_name}.{year} 必须是正的有限值"
                            )
                        base = company["baseline"][str(year)]
                        shock = _combined_v2_shock(
                            entry_shock, architecture_shock, year
                        )
                        share_loss = shock["share_loss_pct"] / 100.0
                        extra_asp = shock["extra_asp_pressure_pct"] / 100.0
                        if (
                            not 0.0 <= share_loss < 1.0
                            or not 0.0 <= extra_asp < 1.0
                        ):
                            raise ValueError(
                                f"{company_key}.{cross_key}.{year} "
                                "share/ASP shock 必须在 [0,100)"
                            )
                        exposed_revenue = (
                            sensitivity_base_revenue
                            * high_speed_exposure_share
                        )
                        non_exposed_revenue = (
                            sensitivity_base_revenue - exposed_revenue
                        )
                        shocked_exposed_revenue = (
                            exposed_revenue
                            * (1.0 - share_loss)
                            * (1.0 - extra_asp)
                        )
                        revenue = non_exposed_revenue + shocked_exposed_revenue
                        base_gross_margin = float(base["gross_margin_pct"])
                        exposed_gross_margin = (
                            base_gross_margin
                            - shock["gross_margin_shock_ppt"]
                        )
                        gross_profit = (
                            non_exposed_revenue
                            * base_gross_margin
                            / 100.0
                            + shocked_exposed_revenue
                            * exposed_gross_margin
                            / 100.0
                        )
                        gross_margin = gross_profit / revenue * 100.0
                        base_net_margin = float(base["net_margin_pct"])
                        exposed_net_margin = (
                            base_net_margin
                            - shock["gross_margin_shock_ppt"]
                            * pass_through
                            - shock["fixed_cost_drag_ppt"]
                        )
                        net_income = (
                            non_exposed_revenue * base_net_margin / 100.0
                            + shocked_exposed_revenue
                            * exposed_net_margin
                            / 100.0
                        )
                        net_margin = net_income / revenue * 100.0
                        base_normalized_fcf_margin = float(
                            base.get(
                                "normalized_fcf_margin_pct",
                                base["fcf_margin_pct"],
                            )
                        )
                        exposed_normalized_fcf_margin = (
                            base_normalized_fcf_margin
                            - shock["gross_margin_shock_ppt"]
                            * pass_through
                            - shock["fixed_cost_drag_ppt"]
                            - shock[
                                "maintenance_capex_increment_pct_revenue"
                            ]
                            - shock[
                                "normalized_working_capital_drag_pct_revenue"
                            ]
                            - shock["normalized_other_fcf_drag_ppt"]
                        )
                        expansion_capex = (
                            shocked_exposed_revenue
                            * shock["expansion_capex_pct_revenue"]
                            / 100.0
                            + shock["expansion_capex_cny_yi"]
                            * high_speed_exposure_share
                        )
                        working_capital_change = (
                            shocked_exposed_revenue
                            * shock["working_capital_change_pct_revenue"]
                            / 100.0
                            + shock["working_capital_change_cny_yi"]
                            * high_speed_exposure_share
                        )
                        normalized_fcf = (
                            non_exposed_revenue
                            * base_normalized_fcf_margin
                            / 100.0
                            + shocked_exposed_revenue
                            * exposed_normalized_fcf_margin
                            / 100.0
                        )
                        normalized_fcf_margin = (
                            normalized_fcf / revenue * 100.0
                        )
                        annual_fcf = (
                            normalized_fcf
                            - expansion_capex
                            - working_capital_change
                        )
                        cashflow_date = date(year, 12, 31)
                        discount_years = _discount_year_fraction(
                            valuation_date, cashflow_date
                        )
                        discounted_fcf = annual_fcf / (
                            (1.0 + wacc) ** discount_years
                        )
                        state_rows.append(
                            {
                                "year": year,
                                "revenue_cny_yi": round(revenue, 2),
                                "gross_profit_cny_yi": round(
                                    gross_profit, 6
                                ),
                                "gross_margin_pct": round(
                                    gross_margin, 2
                                ),
                                "net_margin_pct": round(net_margin, 2),
                                "net_income_cny_yi": round(net_income, 2),
                                "normalized_fcf_margin_pct": round(
                                    normalized_fcf_margin, 2
                                ),
                                "normalized_fcf_cny_yi": round(
                                    normalized_fcf, 2
                                ),
                                "expansion_capex_cny_yi": round(
                                    expansion_capex, 2
                                ),
                                "working_capital_change_cny_yi": round(
                                    working_capital_change, 2
                                ),
                                "fcf_cny_yi": round(annual_fcf, 2),
                                "discounted_fcf_cny_yi": round(
                                    discounted_fcf, 2
                                ),
                            }
                        )
                    sensitivity_cross_rows[cross_key] = state_rows
                    state_applicable, raw_state_terminal, _ = (
                        _sustainable_terminal_value(
                            state_rows[-1]["normalized_fcf_cny_yi"],
                            wacc,
                            growth,
                        )
                    )
                    sensitivity_terminal_applicable_by_state[cross_key] = (
                        state_applicable
                    )
                    state_terminal = round(raw_state_terminal, 2)
                    sensitivity_terminal_by_state[cross_key] = state_terminal
                    sensitivity_floor_terminal_by_state[
                        cross_key
                    ] = state_terminal
                    sensitivity_discounted_terminal_by_state[
                        cross_key
                    ] = round(
                        raw_state_terminal
                        / ((1.0 + wacc) ** terminal_years),
                        2,
                    )
                    sensitivity_discounted_floor_terminal_by_state[
                        cross_key
                    ] = round(
                        raw_state_terminal / ((1.0 + wacc) ** terminal_years),
                        2,
                    )

            sensitivity_rows: list[dict[str, Any]] = []
            for row_index, year in enumerate(years):
                sensitivity_row = _probability_weighted_financial_row(
                    cross_rows=sensitivity_cross_rows,
                    row_index=row_index,
                    year=year,
                    entry_probability=annual_entry_probability[str(year)],
                    architecture_probability=annual_architecture_probability[
                        str(year)
                    ],
                )
                sensitivity_row["actual_fcf_cny_yi"] = sensitivity_row[
                    "fcf_cny_yi"
                ]
                sensitivity_row[
                    "discounted_actual_fcf_cny_yi"
                ] = sensitivity_row["discounted_fcf_cny_yi"]
                sensitivity_rows.append(sensitivity_row)

            signed_terminal_case = sum(
                entry_probability[entry]
                * architecture_probability[architecture]
                * sensitivity_terminal_by_state[f"{entry}|{architecture}"]
                for entry in ENTRY_SCENARIOS
                for architecture in ARCHITECTURE_STATES
            )
            floor_terminal_case = sum(
                entry_probability[entry]
                * architecture_probability[architecture]
                * sensitivity_floor_terminal_by_state[
                    f"{entry}|{architecture}"
                ]
                for entry in ENTRY_SCENARIOS
                for architecture in ARCHITECTURE_STATES
            )
            discounted_signed_case = sum(
                entry_probability[entry]
                * architecture_probability[architecture]
                * sensitivity_discounted_terminal_by_state[
                    f"{entry}|{architecture}"
                ]
                for entry in ENTRY_SCENARIOS
                for architecture in ARCHITECTURE_STATES
            )
            discounted_floor_case = sum(
                entry_probability[entry]
                * architecture_probability[architecture]
                * sensitivity_discounted_floor_terminal_by_state[
                    f"{entry}|{architecture}"
                ]
                for entry in ENTRY_SCENARIOS
                for architecture in ARCHITECTURE_STATES
            )
            not_applicable_probability_case = sum(
                entry_probability[entry]
                * architecture_probability[architecture]
                for entry in ENTRY_SCENARIOS
                for architecture in ARCHITECTURE_STATES
                if not sensitivity_terminal_applicable_by_state[
                    f"{entry}|{architecture}"
                ]
            )
            post_valuation_year_fcf_pv_case = sum(
                row["discounted_actual_fcf_cny_yi"]
                for row in sensitivity_rows
                if int(row["year"]) > valuation_year
            )
            baseline_revenue_sensitivity_outputs[case_name] = {
                "method": (
                    "逐年使用从3年累计概率走向5年累计概率的状态权重，margin和百分比shock保持不变；"
                    "按每年low/base/high收入路径逐交叉状态重算全部金额字段；"
                    "固定金额capex/营运资本冲击保持原额，不随收入缩放；"
                    "2031年正常化自由现金流为正才计算持续经营终值，否则标记不适用并计0。"
                ),
                "rows": sensitivity_rows,
                "terminal_not_applicable_probability": round(
                    not_applicable_probability_case, 10
                ),
                "probability_weighted_terminal_value_cny_yi": round(
                    signed_terminal_case, 2
                ),
                "probability_weighted_terminal_value_zero_floor_cny_yi": round(
                    floor_terminal_case, 2
                ),
                "probability_weighted_discounted_terminal_value_cny_yi": round(
                    discounted_signed_case, 2
                ),
                "probability_weighted_discounted_terminal_value_zero_floor_cny_yi": round(
                    discounted_floor_case, 2
                ),
                "probability_weighted_operating_value_proxy_cny_yi": round(
                    post_valuation_year_fcf_pv_case + discounted_signed_case, 2
                ),
                "probability_weighted_zero_floor_operating_value_proxy_cny_yi": round(
                    post_valuation_year_fcf_pv_case + discounted_floor_case, 2
                ),
            }
        conditional_after_entry = _conditional_financial_summary_after_entry(
            cross_rows=cross_rows,
            terminal_by_cross_state=terminal_by_cross_state,
            discounted_terminal_by_cross_state=discounted_terminal_by_cross_state,
            entry_probability=entry_probability,
            architecture_probability=architecture_probability,
            year=years[-1],
        )
        result["companies"][company_key] = {
            "display_name": company["display_name"],
            "high_speed_revenue_exposure_share": high_speed_exposure_share,
            "high_speed_revenue_exposure_note": (
                "竞争份额、额外降价、毛利和现金流冲击只作用于设定的800G+暴露收入；"
                "暴露比例没有直接披露时必须做范围敏感性，100%仅表示全收入暴露上限。"
            ),
            "risk_multiplier": company.get("risk_multiplier"),
            "risk_multiplier_rationale": company.get(
                "risk_multiplier_rationale"
            ),
            "baseline": copy.deepcopy(company["baseline"]),
            "baseline_revenue_sensitivity": company.get(
                "baseline_revenue_sensitivity", {}
            ),
            "cross_state_rows": cross_rows,
            "probability_weighted_rows": weighted_rows,
            "conditional_on_at_least_one_entry_2031": conditional_after_entry,
            "terminal_value_applicable_by_cross_state": (
                terminal_applicable_by_cross_state
            ),
            "terminal_value_inapplicable_reason_by_cross_state": (
                terminal_inapplicable_reason_by_cross_state
            ),
            "terminal_value_by_cross_state_cny_yi": terminal_by_cross_state,
            "discounted_terminal_value_by_cross_state_cny_yi": (
                discounted_terminal_by_cross_state
            ),
            "terminal_value_zero_floor_by_cross_state_cny_yi": (
                zero_floor_terminal_by_cross_state
            ),
            "discounted_terminal_value_zero_floor_by_cross_state_cny_yi": (
                discounted_zero_floor_terminal_by_cross_state
            ),
            "nonpositive_terminal_states": nonpositive_terminal_states,
            # 旧内部消费者的兼容别名；新代码使用 nonpositive_terminal_states。
            "negative_terminal_states": nonpositive_terminal_states,
            "probability_weighted_terminal_value_cny_yi": round(
                probability_weighted_terminal, 2
            ),
            "probability_weighted_terminal_value_zero_floor_cny_yi": round(
                probability_weighted_zero_floor_terminal, 2
            ),
            "probability_weighted_terminal_zero_floor_uplift_cny_yi": round(
                probability_weighted_zero_floor_terminal
                - probability_weighted_terminal,
                2,
            ),
            "probability_weighted_discounted_terminal_value_cny_yi": round(
                probability_weighted_discounted_terminal, 2
            ),
            "probability_weighted_discounted_terminal_value_zero_floor_cny_yi": round(
                probability_weighted_discounted_zero_floor_terminal, 2
            ),
            "probability_weighted_discounted_terminal_zero_floor_uplift_cny_yi": round(
                probability_weighted_discounted_zero_floor_terminal
                - probability_weighted_discounted_terminal,
                2,
            ),
            "terminal_sensitivity": terminal_sensitivity,
            "valuation_bridge": valuation_bridge,
            "input_repetition_audit": _identical_cash_input_audit(
                entry_shocks=entry_shocks,
                architecture_shocks=architecture_shocks,
                years=years,
            ),
            "baseline_revenue_sensitivity_outputs": (
                baseline_revenue_sensitivity_outputs
            ),
        }
    return result


def calculate_financial_scenarios(
    config: dict[str, Any],
    scenario_probability: dict[str, Any],
    architecture_probability: dict[str, Any] | None = None,
    annual_scenario_probability: dict[str, dict[str, Any]] | None = None,
    annual_architecture_probability: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """按 schema_version 路由财务模型；旧调用签名继续可用。"""

    if config.get("schema_version") == FINANCIAL_V2_SCHEMA:
        if architecture_probability is None:
            raise ValueError("V2 财务模型必须提供正交 architecture_probability")
        return _calculate_financial_scenarios_v2(
            config,
            scenario_probability,
            architecture_probability,
            annual_scenario_probability,
            annual_architecture_probability,
        )
    if (
        architecture_probability is not None
        or annual_scenario_probability is not None
        or annual_architecture_probability is not None
    ):
        raise ValueError("V1 财务配置不接受 architecture_probability")
    return _calculate_financial_scenarios_v1(config, scenario_probability)


def _default_deterioration_thresholds() -> dict[str, Any]:
    common = {
        "material_any": {
            "actual_fcf_loss_pct": 10.0,
            "net_income_loss_pct": 10.0,
            "gross_margin_loss_ppt": 2.0,
            "share_loss_pct": 5.0,
            "extra_asp_pressure_pct": 4.0,
            "terminal_loss_pct": 10.0,
        },
        "severe_all": {
            "actual_fcf_loss_pct": 20.0,
            "net_income_loss_pct": 20.0,
            "gross_margin_loss_ppt": 5.0,
            "terminal_loss_pct": 25.0,
            "persistent_years": 2,
        },
        "severe_share_or_asp": {
            "share_loss_pct": 10.0,
            "extra_asp_pressure_pct": 7.0,
        },
    }
    return {
        horizon: {
            section: dict(values) for section, values in common.items()
        }
        for horizon in ("3y", "5y")
    }


def _classify_financial_deterioration_aggregate_legacy(
    financial: dict[str, Any],
    probability: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    """用可复算经营阈值给 A—F × P/H/C 交叉状态分类。

    这是 reduced-form 财务压力测试的事后分类，不把专家压力带伪装成
    经验发生率。3年取2029年正常化经营结果，5年取2031年并加入终值；
    进入状态概率与架构概率保持正交后再聚合。
    """

    year_by_horizon = {"3y": 2029, "5y": 2031}
    output: dict[str, Any] = {
        "method": "reduced_form_cross_state_threshold_classification.v1",
        "thresholds": thresholds,
        "horizons": {},
    }
    companies = financial["companies"]
    for horizon, year in year_by_horizon.items():
        if horizon not in thresholds:
            raise ValueError(f"deterioration_thresholds 缺少 {horizon}")
        rule = thresholds[horizon]
        state_probability = probability["horizons"][horizon][
            "scenario_probability"
        ]
        architecture_probability = probability["horizons"][horizon][
            "architecture_probability"
        ]
        cross_rows: list[dict[str, Any]] = []
        severity_probability = {state: 0.0 for state in DAMAGE_STATES}
        entry_denominator = sum(
            state_probability[state] for state in ENTRY_SCENARIOS[1:]
        )
        for entry_state in ENTRY_SCENARIOS:
            for architecture_state in ARCHITECTURE_STATES:
                cross_key = f"{entry_state}|{architecture_state}"
                fcf_base_total = 0.0
                fcf_cross_total = 0.0
                terminal_base_total = 0.0
                terminal_cross_total = 0.0
                revenue_weight_total = 0.0
                gross_loss_weighted = 0.0
                share_loss_weighted = 0.0
                asp_pressure_weighted = 0.0
                company_detail: dict[str, Any] = {}
                for company_key, company in companies.items():
                    base_rows = company["cross_state_rows"]["A|P"]
                    candidate_rows = company["cross_state_rows"][cross_key]
                    base = next(row for row in base_rows if row["year"] == year)
                    candidate = next(
                        row for row in candidate_rows if row["year"] == year
                    )
                    base_fcf = float(base["normalized_fcf_cny_yi"])
                    candidate_fcf = float(candidate["normalized_fcf_cny_yi"])
                    base_revenue = max(float(base["revenue_cny_yi"]), 0.0)
                    fcf_base_total += base_fcf
                    fcf_cross_total += candidate_fcf
                    revenue_weight_total += base_revenue
                    gross_loss_weighted += base_revenue * (
                        float(base["gross_margin_pct"])
                        - float(candidate["gross_margin_pct"])
                    )
                    share_loss_weighted += base_revenue * float(
                        candidate["share_loss_pct"]
                    )
                    asp_pressure_weighted += base_revenue * float(
                        candidate["extra_asp_pressure_pct"]
                    )
                    base_terminal = float(
                        company["terminal_value_by_cross_state_cny_yi"]["A|P"]
                    )
                    candidate_terminal = float(
                        company["terminal_value_by_cross_state_cny_yi"][cross_key]
                    )
                    terminal_base_total += base_terminal
                    terminal_cross_total += candidate_terminal
                    company_detail[company_key] = {
                        "normalized_fcf_loss_pct": round(
                            100.0
                            * (base_fcf - candidate_fcf)
                            / max(abs(base_fcf), 1e-9),
                            4,
                        ),
                        "terminal_loss_pct": round(
                            100.0
                            * (base_terminal - candidate_terminal)
                            / max(abs(base_terminal), 1e-9),
                            4,
                        ),
                    }
                normalized_fcf_loss_pct = 100.0 * (
                    fcf_base_total - fcf_cross_total
                ) / max(abs(fcf_base_total), 1e-9)
                terminal_loss_pct = 100.0 * (
                    terminal_base_total - terminal_cross_total
                ) / max(abs(terminal_base_total), 1e-9)
                gross_margin_loss_ppt = gross_loss_weighted / max(
                    revenue_weight_total, 1e-9
                )
                share_loss_pct = share_loss_weighted / max(
                    revenue_weight_total, 1e-9
                )
                extra_asp_pressure_pct = asp_pressure_weighted / max(
                    revenue_weight_total, 1e-9
                )

                severe = entry_state != "A" and (
                    normalized_fcf_loss_pct
                    >= float(rule["severe_all"]["normalized_fcf_loss_pct"])
                    and gross_margin_loss_ppt
                    >= float(rule["severe_all"]["gross_margin_loss_ppt"])
                    and (
                        horizon != "5y"
                        or terminal_loss_pct
                        >= float(rule["severe_all"]["terminal_loss_pct"])
                    )
                    and (
                        share_loss_pct
                        >= float(rule["severe_share_or_asp"]["share_loss_pct"])
                        or extra_asp_pressure_pct
                        >= float(
                            rule["severe_share_or_asp"][
                                "extra_asp_pressure_pct"
                            ]
                        )
                    )
                )
                material = entry_state != "A" and any(
                    (
                        normalized_fcf_loss_pct
                        >= float(rule["material_any"]["normalized_fcf_loss_pct"]),
                        gross_margin_loss_ppt
                        >= float(rule["material_any"]["gross_margin_loss_ppt"]),
                        share_loss_pct
                        >= float(rule["material_any"]["share_loss_pct"]),
                        extra_asp_pressure_pct
                        >= float(
                            rule["material_any"]["extra_asp_pressure_pct"]
                        ),
                        horizon == "5y"
                        and terminal_loss_pct
                        >= float(rule["material_any"]["terminal_loss_pct"]),
                    )
                )
                severity = "severe" if severe else "material" if material else "mild"
                joint_probability = (
                    state_probability[entry_state]
                    * architecture_probability[architecture_state]
                )
                if entry_state != "A":
                    severity_probability[severity] += joint_probability
                cross_rows.append(
                    {
                        "entry_state": entry_state,
                        "architecture_state": architecture_state,
                        "classification": "not_applicable_no_entry"
                        if entry_state == "A"
                        else severity,
                        "joint_probability": round(joint_probability, 8),
                        "normalized_fcf_loss_pct": round(
                            normalized_fcf_loss_pct, 4
                        ),
                        "terminal_loss_pct": round(terminal_loss_pct, 4),
                        "gross_margin_loss_ppt": round(
                            gross_margin_loss_ppt, 4
                        ),
                        "share_loss_pct": round(share_loss_pct, 4),
                        "extra_asp_pressure_pct": round(
                            extra_asp_pressure_pct, 4
                        ),
                        "company_detail": company_detail,
                    }
                )
        conditional = {
            severity: round(
                probability_value / max(entry_denominator, 1e-12), 8
            )
            for severity, probability_value in severity_probability.items()
        }
        output["horizons"][horizon] = {
            "measurement_year": year,
            "conditional_on_at_least_one_entry": conditional,
            "unconditional_joint_with_entry": {
                severity: round(value, 8)
                for severity, value in severity_probability.items()
            },
            "entry_probability_denominator": round(entry_denominator, 8),
            "probability_sum_error": round(
                abs(sum(conditional.values()) - 1.0), 10
            ),
            "cross_state_classification": cross_rows,
            "notice": (
                "由A—F×P/H/C reduced-form财务路径按显式经营阈值分类；"
                "不是历史频率。3年不使用终值门槛，5年同时要求正常化FCF、"
                "毛利、终值和份额/额外ASP条件。"
            ),
        }
    return output


def classify_financial_deterioration(
    financial: dict[str, Any],
    probability: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    """按公司复算经营损伤，再聚合为行业代理。

    3年窗口使用2029年；5年窗口使用2029—2031年平均净利润/实际FCF、
    2031正常化终值和持续受损年数。`industry_worst_incumbent` 是两家龙头
    中较严重者，只作保守行业代理；公司结果始终单列，避免相互抵消。
    """

    evaluation_years = {"3y": [2029], "5y": [2029, 2030, 2031]}
    severity_rank = {"mild": 0, "material": 1, "severe": 2}
    output: dict[str, Any] = {
        "method": "company_level_reduced_form_threshold_classification.v2",
        "thresholds": thresholds,
        "aggregation_policy": (
            "公司分别分类；industry_worst_incumbent取两家中更严重者，"
            "并另报both_incumbents_severe，绝不以公司间平均抵消损伤。"
        ),
        "horizons": {},
    }

    def loss_pct(base: float, candidate: float) -> float:
        return 100.0 * (base - candidate) / max(abs(base), 1e-9)

    for horizon, years in evaluation_years.items():
        if horizon not in thresholds:
            raise ValueError(f"deterioration_thresholds 缺少 {horizon}")
        rule = thresholds[horizon]
        entry_probability = probability["horizons"][horizon][
            "scenario_probability"
        ]
        architecture_probability = probability["horizons"][horizon][
            "architecture_probability"
        ]
        denominator = sum(entry_probability[state] for state in ENTRY_SCENARIOS[1:])
        company_joint = {
            key: {severity: 0.0 for severity in DAMAGE_STATES}
            for key in financial["companies"]
        }
        industry_joint = {severity: 0.0 for severity in DAMAGE_STATES}
        both_severe_joint = 0.0
        long_term_company_joint = {
            key: 0.0 for key in financial["companies"]
        }
        at_least_one_long_term_joint = 0.0
        both_long_term_joint = 0.0
        cross_rows: list[dict[str, Any]] = []

        for entry_state in ENTRY_SCENARIOS:
            for architecture_state in ARCHITECTURE_STATES:
                cross_key = f"{entry_state}|{architecture_state}"
                joint_probability = (
                    entry_probability[entry_state]
                    * architecture_probability[architecture_state]
                )
                company_detail: dict[str, Any] = {}
                company_severities: list[str] = []
                company_long_term_damage: list[bool] = []
                for company_key, company in financial["companies"].items():
                    base_by_year = {
                        row["year"]: row
                        for row in company["cross_state_rows"]["A|P"]
                    }
                    candidate_by_year = {
                        row["year"]: row
                        for row in company["cross_state_rows"][cross_key]
                    }
                    base_rows = [base_by_year[year] for year in years]
                    candidate_rows = [candidate_by_year[year] for year in years]
                    base_actual_fcf = sum(float(row["fcf_cny_yi"]) for row in base_rows)
                    candidate_actual_fcf = sum(
                        float(row["fcf_cny_yi"]) for row in candidate_rows
                    )
                    base_net_income = sum(
                        float(row["net_income_cny_yi"]) for row in base_rows
                    )
                    candidate_net_income = sum(
                        float(row["net_income_cny_yi"]) for row in candidate_rows
                    )
                    revenue_weight = sum(
                        max(float(row["revenue_cny_yi"]), 0.0) for row in base_rows
                    )
                    gross_margin_loss = sum(
                        max(float(base["revenue_cny_yi"]), 0.0)
                        * (
                            float(base["gross_margin_pct"])
                            - float(candidate["gross_margin_pct"])
                        )
                        for base, candidate in zip(base_rows, candidate_rows)
                    ) / max(revenue_weight, 1e-9)
                    share_loss = sum(
                        max(float(base["revenue_cny_yi"]), 0.0)
                        * float(candidate["share_loss_pct"])
                        for base, candidate in zip(base_rows, candidate_rows)
                    ) / max(revenue_weight, 1e-9)
                    asp_pressure = sum(
                        max(float(base["revenue_cny_yi"]), 0.0)
                        * float(candidate["extra_asp_pressure_pct"])
                        for base, candidate in zip(base_rows, candidate_rows)
                    ) / max(revenue_weight, 1e-9)
                    base_terminal = float(
                        company["terminal_value_by_cross_state_cny_yi"]["A|P"]
                    )
                    candidate_terminal = float(
                        company["terminal_value_by_cross_state_cny_yi"][cross_key]
                    )
                    actual_fcf_loss = loss_pct(
                        base_actual_fcf, candidate_actual_fcf
                    )
                    net_income_loss = loss_pct(
                        base_net_income, candidate_net_income
                    )
                    terminal_loss = loss_pct(base_terminal, candidate_terminal)
                    persistent_years = sum(
                        loss_pct(
                            float(base["fcf_cny_yi"]),
                            float(candidate["fcf_cny_yi"]),
                        )
                        >= float(rule["severe_all"]["actual_fcf_loss_pct"])
                        for base, candidate in zip(base_rows, candidate_rows)
                    )
                    severe = entry_state != "A" and (
                        actual_fcf_loss
                        >= float(rule["severe_all"]["actual_fcf_loss_pct"])
                        and net_income_loss
                        >= float(rule["severe_all"]["net_income_loss_pct"])
                        and gross_margin_loss
                        >= float(rule["severe_all"]["gross_margin_loss_ppt"])
                        and persistent_years
                        >= int(rule["severe_all"]["persistent_years"])
                        and (
                            horizon != "5y"
                            or terminal_loss
                            >= float(rule["severe_all"]["terminal_loss_pct"])
                        )
                        and (
                            share_loss
                            >= float(
                                rule["severe_share_or_asp"]["share_loss_pct"]
                            )
                            or asp_pressure
                            >= float(
                                rule["severe_share_or_asp"][
                                    "extra_asp_pressure_pct"
                                ]
                            )
                        )
                    )
                    material = entry_state != "A" and any(
                        (
                            actual_fcf_loss
                            >= float(
                                rule["material_any"]["actual_fcf_loss_pct"]
                            ),
                            net_income_loss
                            >= float(
                                rule["material_any"]["net_income_loss_pct"]
                            ),
                            gross_margin_loss
                            >= float(
                                rule["material_any"]["gross_margin_loss_ppt"]
                            ),
                            share_loss
                            >= float(rule["material_any"]["share_loss_pct"]),
                            asp_pressure
                            >= float(
                                rule["material_any"][
                                    "extra_asp_pressure_pct"
                                ]
                            ),
                            horizon == "5y"
                            and terminal_loss
                            >= float(
                                rule["material_any"]["terminal_loss_pct"]
                            ),
                        )
                    )
                    severity = (
                        "not_applicable_no_entry"
                        if entry_state == "A"
                        else "severe"
                        if severe
                        else "material"
                        if material
                        else "mild"
                    )
                    long_term_damage = (
                        horizon == "5y"
                        and entry_state != "A"
                        and actual_fcf_loss >= 15.0
                        and net_income_loss >= 15.0
                        and terminal_loss >= 20.0
                    )
                    if entry_state != "A":
                        company_joint[company_key][severity] += joint_probability
                        company_severities.append(severity)
                        company_long_term_damage.append(long_term_damage)
                        if long_term_damage:
                            long_term_company_joint[company_key] += joint_probability
                    company_detail[company_key] = {
                        "display_name": company["display_name"],
                        "classification": severity,
                        "evaluation_years": years,
                        "actual_fcf_loss_pct": round(actual_fcf_loss, 4),
                        "net_income_loss_pct": round(net_income_loss, 4),
                        "terminal_loss_pct": round(terminal_loss, 4),
                        "gross_margin_loss_ppt": round(gross_margin_loss, 4),
                        "share_loss_pct": round(share_loss, 4),
                        "extra_asp_pressure_pct": round(asp_pressure, 4),
                        "persistent_severe_fcf_loss_years": persistent_years,
                        "long_term_significant_damage": long_term_damage,
                    }
                if entry_state == "A":
                    industry_classification = "not_applicable_no_entry"
                else:
                    industry_classification = max(
                        company_severities, key=lambda value: severity_rank[value]
                    )
                    industry_joint[industry_classification] += joint_probability
                    if all(value == "severe" for value in company_severities):
                        both_severe_joint += joint_probability
                    if horizon == "5y" and any(company_long_term_damage):
                        at_least_one_long_term_joint += joint_probability
                    if horizon == "5y" and all(company_long_term_damage):
                        both_long_term_joint += joint_probability
                cross_rows.append(
                    {
                        "entry_state": entry_state,
                        "architecture_state": architecture_state,
                        "joint_probability": round(joint_probability, 8),
                        "industry_worst_incumbent_classification": (
                            industry_classification
                        ),
                        "company_detail": company_detail,
                    }
                )

        def conditional(values: dict[str, float]) -> dict[str, float]:
            return {
                key: round(value / max(denominator, 1e-12), 8)
                for key, value in values.items()
            }

        industry_conditional = conditional(industry_joint)
        company_conditional = {
            key: conditional(values) for key, values in company_joint.items()
        }
        output["horizons"][horizon] = {
            "evaluation_years": years,
            "conditional_on_at_least_one_entry": industry_conditional,
            "conditional_by_company": company_conditional,
            "both_incumbents_severe_conditional": round(
                both_severe_joint / max(denominator, 1e-12), 8
            ),
            "long_term_significant_damage": {
                "definition": (
                    "2029—2031平均实际FCF和净利润均较A|P低至少15%，"
                    "且2031正常化终值低至少20%。"
                ),
                "conditional_by_company": {
                    key: round(value / max(denominator, 1e-12), 8)
                    for key, value in long_term_company_joint.items()
                },
                "unconditional_by_company": {
                    key: round(value, 8)
                    for key, value in long_term_company_joint.items()
                },
                "at_least_one_incumbent_conditional": round(
                    at_least_one_long_term_joint / max(denominator, 1e-12), 8
                ),
                "both_incumbents_conditional": round(
                    both_long_term_joint / max(denominator, 1e-12), 8
                ),
                "at_least_one_incumbent_unconditional": round(
                    at_least_one_long_term_joint, 8
                ),
                "both_incumbents_unconditional": round(
                    both_long_term_joint, 8
                ),
            }
            if horizon == "5y"
            else {"status": "not_applicable_before_2029_2031_window"},
            "unconditional_joint_with_entry": {
                key: round(value, 8) for key, value in industry_joint.items()
            },
            "entry_probability_denominator": round(denominator, 8),
            "probability_sum_error": round(
                abs(sum(industry_conditional.values()) - 1.0), 10
            ),
            "cross_state_classification": cross_rows,
            "notice": (
                "A—F×P/H/C reduced-form路径按公司分类；5年使用2029—2031平均"
                "净利润和实际FCF、持续受损年数及2031正常化终值，3年使用2029年。"
                "industry_worst_incumbent是保守代理，不是历史频率。"
            ),
        }
    return output


def run_probability_sensitivity(
    probability_config: dict[str, Any],
    base_probability: dict[str, Any],
    *,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    """执行事件阈值、qualification时滞与依赖结构的显式压力测试。"""

    cases = probability_config.get("sensitivity_cases")
    if not isinstance(cases, dict) or not cases:
        return {"status": "not_configured", "cases": {}}

    def merge(target: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(target)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    inner_samples = max(20_000, min(50_000, samples // 2))
    output_cases: dict[str, Any] = {}
    base_comparison_config = copy.deepcopy(probability_config)
    base_comparison_config.pop("sensitivity_cases", None)
    base_comparison = simulate_probability_tree(
        base_comparison_config,
        samples=inner_samples,
        seed=seed,
    )
    base_metrics = {
        horizon: {
            **base_comparison["horizons"][horizon]["marginal_probability"],
            "architecture_c_probability": base_comparison["horizons"][horizon][
                "architecture_probability"
            ]["C"],
        }
        for horizon in ("3y", "5y")
    }
    for case_key, case in cases.items():
        override = case.get("override") if isinstance(case, dict) else None
        if not isinstance(override, dict):
            raise ValueError(f"sensitivity_cases.{case_key} 缺少 override")
        case_config = merge(probability_config, override)
        case_config.pop("sensitivity_cases", None)
        case_result = simulate_probability_tree(
            case_config,
            samples=inner_samples,
            seed=seed,
        )
        horizons: dict[str, Any] = {}
        for horizon in ("3y", "5y"):
            marginal = case_result["horizons"][horizon]["marginal_probability"]
            selected = dict(marginal)
            selected["architecture_c_probability"] = case_result["horizons"][
                horizon
            ]["architecture_probability"]["C"]
            horizons[horizon] = {
                **selected,
                "delta_vs_base": {
                    metric: round(selected[metric] - base_metrics[horizon][metric], 8)
                    for metric in selected
                },
            }
        output_cases[case_key] = {
            "label": case.get("label", case_key),
            "rationale": case.get("rationale"),
            "event_definition_delta": case.get("event_definition_delta"),
            "horizons": horizons,
        }
    return {
        "status": "executed",
        "samples_per_case": inner_samples,
        "seed_policy": "common_random_numbers_same_seed_and_sample_count",
        "comparison_method": (
            "base与每个反事实均以相同样本数、相同seed重算；未变参数共享随机路径，"
            "delta不混入不同seed的Monte Carlo噪声。"
        ),
        "cases": output_cases,
    }


def _wilson_score_interval(
    successes: int,
    sample_size: int,
    *,
    z: float = 1.96,
) -> list[float]:
    """Return a reproducible Wilson score interval for a binary case ledger."""

    if sample_size <= 0 or not 0 <= successes <= sample_size:
        raise ValueError("Wilson区间要求0<=successes<=sample_size且sample_size>0")
    p = successes / sample_size
    denominator = 1.0 + z * z / sample_size
    center = (p + z * z / (2.0 * sample_size)) / denominator
    half = (
        z
        * math.sqrt(
            p * (1.0 - p) / sample_size
            + z * z / (4.0 * sample_size * sample_size)
        )
        / denominator
    )
    return [round(center - half, 8), round(center + half, 8)]


def _validate_historical_case_ledger(bridge: dict[str, Any]) -> None:
    """Fail closed unless both historical anchors reproduce from one 9-case ledger."""

    ledger = bridge.get("historical_case_ledger")
    if not isinstance(ledger, list) or len(ledger) != 9:
        raise ValueError("prior_update_bridge.historical_case_ledger 必须恰有9个案例")
    required_text = (
        "case_id",
        "case_name",
        "entry_path",
        "outcome_as_of",
        "classification",
        "classification_rationale",
    )
    flag_names = ("strict_full_stack_success", "broad_adjacency_success")
    case_ids: list[str] = []
    all_refs: list[str] = []
    for index, row in enumerate(ledger):
        if not isinstance(row, dict):
            raise ValueError(f"historical_case_ledger[{index}] 不是对象")
        for field in required_text:
            if not str(row.get(field) or "").strip():
                raise ValueError(f"historical_case_ledger[{index}] 缺少 {field}")
        case_id = str(row["case_id"]).strip()
        if case_id in case_ids:
            raise ValueError(f"historical_case_ledger case_id重复：{case_id}")
        case_ids.append(case_id)
        for field in flag_names:
            value = row.get(field)
            if isinstance(value, bool):
                value = int(value)
            if not isinstance(value, int) or value not in (0, 1):
                raise ValueError(f"{case_id}.{field} 必须为0或1")
        refs = row.get("source_refs")
        if not isinstance(refs, list) or not refs or not all(
            isinstance(ref, str) and ref.strip() for ref in refs
        ):
            raise ValueError(f"{case_id}.source_refs 必须是非空引用列表")
        for ref in refs:
            clean_ref = ref.strip()
            if clean_ref not in all_refs:
                all_refs.append(clean_ref)

    anchors = bridge.get("historical_anchors")
    if not isinstance(anchors, dict):
        raise ValueError("prior_update_bridge 缺少 historical_anchors")
    expected_flags = {
        "complete_module_success": "strict_full_stack_success",
        "adjacent_or_complete_success": "broad_adjacency_success",
    }
    for anchor_name, flag_name in expected_flags.items():
        anchor = anchors.get(anchor_name)
        if not isinstance(anchor, dict):
            raise ValueError(f"historical_anchors 缺少 {anchor_name}")
        if anchor.get("success_flag") != flag_name:
            raise ValueError(f"{anchor_name}.success_flag 与案例账本口径不一致")
        successes = sum(int(row[flag_name]) for row in ledger)
        sample_size = len(ledger)
        if int(anchor.get("successes", -1)) != successes:
            raise ValueError(f"{anchor_name}.successes 无法从案例账本复算")
        if int(anchor.get("sample_size", -1)) != sample_size:
            raise ValueError(f"{anchor_name}.sample_size 无法从案例账本复算")
        expected_rate = successes / sample_size
        if not math.isclose(
            float(anchor.get("descriptive_rate", -1.0)),
            expected_rate,
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise ValueError(f"{anchor_name}.descriptive_rate 无法从案例账本复算")
        interval = anchor.get("wilson_95_interval")
        expected_interval = _wilson_score_interval(successes, sample_size)
        if not isinstance(interval, list) or len(interval) != 2 or any(
            not math.isclose(float(actual), expected, rel_tol=0, abs_tol=1e-8)
            for actual, expected in zip(interval, expected_interval)
        ):
            raise ValueError(f"{anchor_name}.wilson_95_interval 复算不一致")
        if anchor.get("case_ids") != case_ids:
            raise ValueError(f"{anchor_name}.case_ids 未完整绑定同一案例账本")
        if anchor.get("source_refs") != all_refs:
            raise ValueError(f"{anchor_name}.source_refs 未覆盖全部逐例来源")


def _validate_prior_update_bridge(
    probability_config: dict[str, Any],
) -> dict[str, Any]:
    """校验工作先验到公司概率输入的逐组更新账本。

    这不是把专家判断伪装成贝叶斯后验。合同只要求每个加减项有证据组、
    方向和可复核理由，并且百分点评分桥精确回到模型使用的三角分布众数。
    """

    bridge = copy.deepcopy(probability_config.get("prior_update_bridge"))
    if not isinstance(bridge, dict):
        raise ValueError("V2 概率配置缺少 prior_update_bridge")
    if bridge.get("update_method") != "additive_percentage_point_expert_elicitation":
        raise ValueError("prior_update_bridge.update_method 必须明确为百分点评议法")

    _validate_historical_case_ledger(bridge)

    priors = bridge.get("working_priors")
    company_updates = bridge.get("company_updates")
    if not isinstance(priors, dict) or not isinstance(company_updates, dict):
        raise ValueError("prior_update_bridge 缺少 working_priors/company_updates")

    entrants = probability_config["entrants"]
    reconciliation: dict[str, Any] = {}
    for horizon in ("3y", "5y"):
        prior = priors.get(horizon)
        if not isinstance(prior, dict):
            raise ValueError(f"working_priors 缺少 {horizon}")
        prior_mode = _require_probability(
            float(prior.get("mode")), f"working_priors.{horizon}.mode"
        )
        support = _range3(
            prior.get("support"), f"working_priors.{horizon}.support"
        )
        if not support[0] <= prior_mode <= support[2]:
            raise ValueError(f"working_priors.{horizon}.mode 不在 support 内")

        reconciliation[horizon] = {}
        for company in ("byd", "luxshare"):
            company_payload = company_updates.get(company)
            if not isinstance(company_payload, dict):
                raise ValueError(f"company_updates 缺少 {company}")
            updates = company_payload.get("updates")
            if not isinstance(updates, list) or not updates:
                raise ValueError(f"company_updates.{company}.updates 为空")
            update_ids: set[str] = set()
            delta_pp_total = 0.0
            for index, update in enumerate(updates):
                if not isinstance(update, dict):
                    raise ValueError(
                        f"company_updates.{company}.updates[{index}] 不是对象"
                    )
                update_id = str(update.get("update_id") or "").strip()
                if not update_id or update_id in update_ids:
                    raise ValueError(
                        f"company_updates.{company}.updates[{index}] update_id 缺失或重复"
                    )
                update_ids.add(update_id)
                deltas = update.get("delta_percentage_points")
                if not isinstance(deltas, dict) or horizon not in deltas:
                    raise ValueError(f"{company}/{update_id} 缺少 {horizon} delta")
                delta = float(deltas[horizon])
                if not math.isfinite(delta):
                    raise ValueError(f"{company}/{update_id}/{horizon} delta 非有限数")
                direction = str(update.get("direction") or "").strip()
                if (delta > 0 and direction != "up") or (
                    delta < 0 and direction != "down"
                ) or (delta == 0 and direction != "neutral"):
                    raise ValueError(f"{company}/{update_id}/{horizon} 方向与 delta 不一致")
                refs = update.get("evidence_source_refs")
                claim_ids = update.get("claim_ids")
                if not isinstance(refs, list) or not refs or not all(
                    isinstance(ref, str) and ref.strip() for ref in refs
                ):
                    raise ValueError(f"{company}/{update_id} 缺少证据引用")
                if not isinstance(claim_ids, list) or not claim_ids:
                    raise ValueError(f"{company}/{update_id} 缺少 claim 映射")
                if not str(update.get("rationale") or "").strip():
                    raise ValueError(f"{company}/{update_id} 缺少更新理由")
                delta_pp_total += delta

            posterior = company_payload.get("posterior", {}).get(horizon)
            if not isinstance(posterior, dict):
                raise ValueError(f"company_updates.{company}.posterior 缺少 {horizon}")
            posterior_mode = _require_probability(
                float(posterior.get("mode")),
                f"company_updates.{company}.posterior.{horizon}.mode",
            )
            triangle = _range3(
                posterior.get("triangle"),
                f"company_updates.{company}.posterior.{horizon}.triangle",
            )
            configured_triangle = _range3(
                entrants[company][horizon], f"entrants.{company}.{horizon}"
            )
            if any(
                not math.isclose(left, right, rel_tol=0, abs_tol=1e-12)
                for left, right in zip(triangle, configured_triangle)
            ):
                raise ValueError(
                    f"{company}/{horizon} 更新桥 triangle 与 entrants 输入不一致"
                )
            if not math.isclose(posterior_mode, triangle[1], rel_tol=0, abs_tol=1e-12):
                raise ValueError(f"{company}/{horizon} posterior mode 不是三角众数")
            reconstructed = prior_mode + delta_pp_total / 100.0
            error = reconstructed - posterior_mode
            if not math.isclose(error, 0.0, rel_tol=0, abs_tol=1e-12):
                raise ValueError(
                    f"{company}/{horizon} prior+delta 无法回到 posterior：误差 {error}"
                )
            reconciliation[horizon][company] = {
                "prior_mode": round(prior_mode, 8),
                "delta_percentage_points_total": round(delta_pp_total, 8),
                "posterior_mode": round(posterior_mode, 8),
                "posterior_triangle": [round(value, 8) for value in triangle],
                "reconciliation_error": round(error, 12),
            }

    bridge["reconciliation"] = reconciliation
    bridge["validation_status"] = "reconciled_to_probability_input_modes"
    return bridge


def _exposure_sensitivity_summary(
    *,
    financial_config: dict[str, Any],
    terminal_entry_probability: dict[str, Any],
    terminal_architecture_probability: dict[str, Any],
    annual_entry_probability: dict[str, dict[str, Any]],
    annual_architecture_probability: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """给公开财务分析提供暴露范围；不把未披露的800G+收入占比伪装成事实。"""

    output: dict[str, Any] = {
        "status": "scenario_range_not_observed_exposure_share",
        "cases": {},
        "interpretation": (
            "50%/75%/100%分别表示公司收入中一半、四分之三或全部直接承受800G+份额、"
            "额外降价和相关现金流冲击；它们是边界敏感性，不是公司披露的业务占比。"
        ),
    }
    for exposure_share in (0.50, 0.75, 1.00):
        case_config = copy.deepcopy(financial_config)
        for company in case_config["companies"].values():
            company["high_speed_revenue_exposure_share"] = exposure_share
        case = calculate_financial_scenarios(
            case_config,
            terminal_entry_probability,
            terminal_architecture_probability,
            annual_entry_probability,
            annual_architecture_probability,
        )
        companies: dict[str, Any] = {}
        for company_key, company in case["companies"].items():
            baseline = company["cross_state_rows"]["A|P"][-1]
            weighted = company["probability_weighted_rows"][-1]
            baseline_value = company["valuation_bridge"][
                "baseline_no_entry_operating_value_proxy_cny_yi"
            ]
            weighted_value = company["valuation_bridge"][
                "probability_weighted_operating_value_proxy_cny_yi"
            ]

            def loss_pct(weighted_value_: float, baseline_value_: float) -> float:
                return round(
                    (1.0 - float(weighted_value_) / max(float(baseline_value_), 1e-12))
                    * 100.0,
                    2,
                )

            companies[company_key] = {
                "display_name": company["display_name"],
                "2031_baseline_revenue_cny_yi": baseline["revenue_cny_yi"],
                "2031_weighted_revenue_cny_yi": weighted["revenue_cny_yi"],
                "2031_revenue_loss_pct": loss_pct(
                    weighted["revenue_cny_yi"], baseline["revenue_cny_yi"]
                ),
                "2031_baseline_net_income_cny_yi": baseline["net_income_cny_yi"],
                "2031_weighted_net_income_cny_yi": weighted["net_income_cny_yi"],
                "2031_net_income_loss_pct": loss_pct(
                    weighted["net_income_cny_yi"], baseline["net_income_cny_yi"]
                ),
                "2031_baseline_actual_fcf_cny_yi": baseline["fcf_cny_yi"],
                "2031_weighted_actual_fcf_cny_yi": weighted["fcf_cny_yi"],
                "2031_actual_fcf_loss_pct": loss_pct(
                    weighted["fcf_cny_yi"], baseline["fcf_cny_yi"]
                ),
                "2031_weighted_gross_margin_pct": weighted["gross_margin_pct"],
                "operating_value_proxy_loss_pct": loss_pct(
                    weighted_value, baseline_value
                ),
            }
        output["cases"][f"exposure_{int(exposure_share * 100)}pct"] = {
            "exposure_share": exposure_share,
            "display_label": (
                "全公司收入均受影响（上限压力）"
                if math.isclose(exposure_share, 1.0)
                else f"公司收入中{int(exposure_share * 100)}%受影响"
            ),
            "is_full_company_revenue_exposure_upper_bound": math.isclose(
                exposure_share, 1.0
            ),
            "companies": companies,
        }
    for company_key in financial_config["companies"]:
        for loss_field in (
            "2031_revenue_loss_pct",
            "2031_net_income_loss_pct",
            "2031_actual_fcf_loss_pct",
        ):
            values = [
                output["cases"][case]["companies"][company_key][loss_field]
                for case in (
                    "exposure_50pct",
                    "exposure_75pct",
                    "exposure_100pct",
                )
            ]
            if any(
                later + 0.02 < earlier
                for earlier, later in zip(values, values[1:])
            ):
                raise AssertionError(
                    f"{company_key}.{loss_field} 未随暴露比例单调增加：{values}"
                )
    return output


def build_model(config: dict[str, Any], *, samples: int = 100_000, seed: int = 20260718) -> dict[str, Any]:
    probability = simulate_probability_tree(config["probability"], samples=samples, seed=seed)
    probability["prior_update_bridge"] = _validate_prior_update_bridge(
        config["probability"]
    )
    probability_sensitivity = run_probability_sensitivity(
        config["probability"], probability, samples=samples, seed=seed
    )
    market = calculate_market_outlook(config["market"])
    five_year_scenarios = probability["horizons"]["5y"]["scenario_probability"]
    probability_is_v2 = probability.get("schema_version") == PROBABILITY_V2_SCHEMA
    financial_is_v2 = config["financial"].get("schema_version") == FINANCIAL_V2_SCHEMA
    if probability_is_v2 != financial_is_v2:
        raise ValueError(
            "正式模型要求 probability 与 financial 同时使用 V2；旧配置则两者都不声明 V2。"
        )
    if probability_is_v2:
        financial_years = [int(year) for year in config["financial"]["years"]]
        start_year = date.fromisoformat(
            str(config["financial"]["valuation_date"])
        ).year
        first_horizon_year = date.fromisoformat(
            str(probability["horizons"]["3y"]["horizon_date"])
        ).year
        second_horizon_year = date.fromisoformat(
            str(probability["horizons"]["5y"]["horizon_date"])
        ).year
        annual_entry_probability = _interpolate_probability_schedule(
            years=financial_years,
            start_year=start_year,
            first_horizon_year=first_horizon_year,
            second_horizon_year=second_horizon_year,
            start_probability={
                state: 1.0 if state == "A" else 0.0 for state in ENTRY_SCENARIOS
            },
            first_horizon_probability=probability["horizons"]["3y"][
                "scenario_probability"
            ],
            second_horizon_probability=probability["horizons"]["5y"][
                "scenario_probability"
            ],
            states=ENTRY_SCENARIOS,
            name="annual_entry_state_probability",
            non_event_state="A",
        )
        architecture_probability = probability["horizons"]["5y"][
            "architecture_probability"
        ]
        annual_architecture_probability = _interpolate_probability_schedule(
            years=financial_years,
            start_year=start_year,
            first_horizon_year=first_horizon_year,
            second_horizon_year=second_horizon_year,
            start_probability={
                state: 1.0 if state == "P" else 0.0
                for state in ARCHITECTURE_STATES
            },
            first_horizon_probability=probability["horizons"]["3y"][
                "architecture_probability"
            ],
            second_horizon_probability=architecture_probability,
            states=ARCHITECTURE_STATES,
            name="annual_architecture_probability",
            non_event_state="P",
        )
        financial = calculate_financial_scenarios(
            config["financial"],
            five_year_scenarios,
            architecture_probability,
            annual_entry_probability,
            annual_architecture_probability,
        )
        financial["exposure_sensitivity"] = _exposure_sensitivity_summary(
            financial_config=config["financial"],
            terminal_entry_probability=five_year_scenarios,
            terminal_architecture_probability=architecture_probability,
            annual_entry_probability=annual_entry_probability,
            annual_architecture_probability=annual_architecture_probability,
        )
        financial["public_use_boundary"] = (
            "主模型默认100%公司收入暴露，只能作为全收入受冲击上限；公开分析必须同时展示"
            "50%—100%暴露敏感性，且在公司披露800G+收入占比前不得称为中心预测或股权公允价值。"
        )
        financial["geography_transmission_policy"] = {
            "status": "partial_reduced_form",
            "transmitted_dimensions": [
                "A-F total meaningful-entry state",
                "whether one or both entrants close a global-head-customer event",
                "P/H/C architecture state",
            ],
            "diagnostic_only_dimensions": [
                "company-specific China entry",
                "system China-only/global-only/China-and-global route",
                "entry_route_unidentified",
            ],
            "notice": (
                "中国/全球概率矩阵用于地域诊断；财务冲击仍按A-F×P/H/C reduced-form传导。"
                "B/C/D表示未闭环全球头部客户的较低冲击，不是中国专属损失；"
                "当前没有将中国事件或未识别路径映射为独立收入、份额和毛利shock。"
            ),
        }
        damage_classification = classify_financial_deterioration(
            financial,
            probability,
            config["probability"].get(
                "deterioration_thresholds",
                _default_deterioration_thresholds(),
            ),
        )
        for horizon in ("3y", "5y"):
            probability["horizons"][horizon][
                "financial_threshold_deterioration"
            ] = damage_classification["horizons"][horizon]
        model_version = "byd_luxshare_optical_competition.v2"
    else:
        financial = calculate_financial_scenarios(
            config["financial"], five_year_scenarios
        )
        model_version = "byd_luxshare_optical_competition.v1"
        damage_classification = None
    return {
        "model_version": model_version,
        "as_of_date": config["as_of_date"],
        "input_provenance": config.get("input_provenance", []),
        "probability": probability,
        "probability_sensitivity": probability_sensitivity,
        "market": market,
        "financial": financial,
        "damage_classification": damage_classification,
    }


def write_plotly_dashboard(model: dict[str, Any], output_path: Path) -> None:
    """生成独立 HTML 计算看板；图表不改变模型结果。"""

    import plotly.graph_objects as go
    import plotly.io as pio
    from plotly.subplots import make_subplots

    five = model["probability"]["horizons"]["5y"]
    scenario_probability = five["scenario_probability"]
    scenario_codes = list(scenario_probability)
    scenario_labels = (
        ENTRY_SCENARIO_LABELS
        if set(scenario_codes) == set(ENTRY_SCENARIOS)
        else SCENARIO_LABELS
    )
    palette = ["#64748b", "#2563eb", "#0f766e", "#d97706", "#dc2626", "#7f1d1d", "#7c3aed"]
    scenario_fig = go.Figure(
        go.Bar(
            x=[scenario_labels[code] for code in scenario_codes],
            y=[scenario_probability[code] * 100 for code in scenario_codes],
            marker_color=palette[: len(scenario_codes)],
            hovertemplate="%{x}<br>概率 %{y:.1f}%<extra></extra>",
        )
    )
    scenario_fig.update_layout(
        title="未来5年进入高速光模块业务与架构变化的工作判断",
        yaxis_title="模型工作概率（%）",
        xaxis_tickangle=-25,
        template="plotly_white",
    )
    if "architecture_probability" in five:
        architecture = five["architecture_probability"]
        scenario_fig.add_trace(
            go.Bar(
                x=[f"架构：{ARCHITECTURE_LABELS[state]}" for state in ARCHITECTURE_STATES],
                y=[architecture[state] * 100 for state in ARCHITECTURE_STATES],
                name="光互联架构变化",
                marker_color=["#94a3b8", "#8b5cf6", "#581c87"],
                hovertemplate="%{x}<br>概率 %{y:.1f}%<extra></extra>",
            )
        )

    geography_labels = {
        "byd_china_entry": "比亚迪：中国",
        "byd_global_entry": "比亚迪：全球头部",
        "luxshare_china_entry": "立讯：中国",
        "luxshare_global_entry": "立讯：全球头部",
        "at_least_one_china_entry": "至少一家：中国",
        "at_least_one_global_entry": "至少一家：全球头部",
        "both_china_entry": "两家同时：中国",
        "both_global_entry": "两家同时：全球头部",
    }
    geography_fig = go.Figure()
    for horizon, color in (("3y", "#2563eb"), ("5y", "#d97706")):
        summary = model["probability"]["horizons"][horizon][
            "marginal_probability_summary"
        ]
        keys = list(geography_labels)
        means = [summary[key]["mean"] * 100 for key in keys]
        geography_fig.add_trace(
            go.Bar(
                x=[geography_labels[key] for key in keys],
                y=means,
                name="未来3年" if horizon == "3y" else "未来5年",
                marker_color=color,
                hovertemplate=(
                    "%{x}<br>根据当前公开证据形成的工作概率 %{y:.1f}%"
                    "<extra></extra>"
                ),
            )
        )
    geography_fig.update_layout(
        title="比亚迪和立讯未来3年、5年形成有意义进入的概率判断",
        yaxis_title="模型工作概率（%）",
        barmode="group",
        xaxis_tickangle=-25,
        template="plotly_white",
        legend_orientation="h",
    )

    market_rows = model["market"]["rows"]
    market_fig = make_subplots(specs=[[{"secondary_y": True}]])
    market_fig.add_trace(
        go.Bar(
            x=[row["year"] for row in market_rows],
            y=[row["normal_market_revenue_usd_bn"] for row in market_rows],
            name="正常技术降价后的市场收入",
            marker_color="#2563eb",
        ),
        secondary_y=False,
    )
    market_fig.add_trace(
        go.Scatter(
            x=[row["year"] for row in market_rows],
            y=[row["qualified_supply_demand_ratio"] for row in market_rows],
            name="合格供给/需求",
            mode="lines+markers",
            line={"color": "#dc2626", "width": 3},
        ),
        secondary_y=True,
    )
    market_fig.update_yaxes(title_text="市场收入（十亿美元）", secondary_y=False)
    market_fig.update_yaxes(title_text="合格供给/需求（倍）", secondary_y=True)
    market_fig.update_layout(title="2026—2031 需求与合格供给", template="plotly_white")

    financial_fig = go.Figure()
    for company in model["financial"]["companies"].values():
        rows = company["probability_weighted_rows"]
        financial_fig.add_trace(
            go.Scatter(
                x=[row["year"] for row in rows],
                y=[row["fcf_cny_yi"] for row in rows],
                name=f"{company['display_name']} 按年度风险权重估算的自由现金流",
                mode="lines+markers",
            )
        )
    financial_fig.update_layout(
        title="全公司收入均受竞争影响时的自由现金流上限压力测试",
        xaxis_title="年份",
        yaxis_title="亿元人民币",
        template="plotly_white",
        hovermode="x unified",
    )

    terminal_fig = go.Figure()
    for company in model["financial"]["companies"].values():
        rows = company["terminal_sensitivity"]
        waccs = sorted({row["wacc"] for row in rows})
        growths = sorted({row["perpetual_growth"] for row in rows})
        matrix = [
            [
                next(
                    row["terminal_value_cny_yi"]
                    for row in rows
                    if row["wacc"] == wacc and row["perpetual_growth"] == growth
                )
                for growth in growths
            ]
            for wacc in waccs
        ]
        terminal_fig.add_trace(
            go.Heatmap(
                z=matrix,
                x=[f"长期增速 {growth:.0%}" for growth in growths],
                y=[f"折现率 {wacc:.0%}" for wacc in waccs],
                name=company["display_name"],
                visible=True if not terminal_fig.data else "legendonly",
                hovertemplate="%{y}<br>%{x}<br>终值 %{z:.0f} 亿元<extra></extra>",
            )
        )
    terminal_fig.update_layout(
        title="2031年正常化自由现金流为正时的持续经营终值敏感性",
        template="plotly_white",
    )

    dashboard_sections = (
        ("比亚迪和立讯未来3年、5年形成有意义进入的概率判断", geography_fig),
        ("未来5年进入高速光模块业务与架构变化的工作判断", scenario_fig),
        ("2026—2031 需求与合格供给", market_fig),
        ("全公司收入均受竞争影响时的自由现金流上限压力测试", financial_fig),
        ("2031年正常化自由现金流为正时的持续经营终值敏感性", terminal_fig),
    )
    divs = []
    for index, (section_title, figure) in enumerate(dashboard_sections):
        divs.append(
            "<h2>"
            + section_title
            + "</h2>"
            + pio.to_html(
                figure,
                full_html=False,
                include_plotlyjs=True if index == 0 else False,
                config={"displaylogo": False, "responsive": True},
            )
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>比亚迪与立讯光模块竞争风险模型</title>"
        "<style>body{font-family:system-ui,-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;"
        "max-width:1500px;margin:0 auto;padding:24px;background:#f8fafc}"
        ".chart{background:white;margin:0 0 20px;padding:12px;border:1px solid #e2e8f0;"
        "border-radius:12px}h1{font-size:26px;margin:0 0 8px}"
        ".scope{color:#475569;line-height:1.7;margin:0 0 20px}</style></head><body>"
        "<h1>比亚迪与立讯进入高速光模块业务：概率与财务压力测试</h1>"
        "<p class='scope'>概率是依据当前公开证据形成的结构化工作判断，不是历史频率。"
        "财务图默认假设现有龙头全部收入都承受高速光模块竞争冲击，因此只表示上限压力；"
        "正常化自由现金流小于或等于零的情景不计算持续经营终值。</p>"
        + "".join(f"<div class='chart'>{div}</div>" for div in divs)
        + "</body></html>",
        encoding="utf-8",
    )


def write_model_artifacts(config: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    model = build_model(
        config,
        samples=int(config.get("samples", 100_000)),
        seed=int(config.get("seed", 20260718)),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "model_inputs.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    (output_dir / "model_outputs.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    write_plotly_dashboard(model, output_dir / "competition_model_dashboard.html")
    return model


__all__ = [
    "ARCHITECTURE_LABELS",
    "ARCHITECTURE_STATES",
    "DAMAGE_STATES",
    "ENTRY_SCENARIO_LABELS",
    "ENTRY_SCENARIOS",
    "FINANCIAL_V2_SCHEMA",
    "PROBABILITY_V2_SCHEMA",
    "SCENARIOS",
    "SCENARIO_LABELS",
    "build_model",
    "calculate_financial_scenarios",
    "calculate_market_outlook",
    "classify_financial_deterioration",
    "joint_bernoulli_probabilities",
    "simulate_probability_tree",
    "run_probability_sensitivity",
    "terminal_value",
    "write_model_artifacts",
    "write_plotly_dashboard",
]
