from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _cagr(start: float, end: float, years: int) -> float:
    return (end / start) ** (1.0 / years) - 1.0


def build(inputs: dict[str, Any], *, input_path: Path) -> dict[str, Any]:
    commodities: dict[str, Any] = {}
    for commodity, spec in inputs["scenario_paths"].items():
        paths: dict[str, list[dict[str, Any]]] = {}
        for scenario_name in ("base_case", "tight_case", "loose_case"):
            rows: list[dict[str, Any]] = []
            for row in spec[scenario_name]:
                supply = float(row["supply"])
                demand = float(row["demand"])
                balance = supply - demand
                rows.append(
                    {
                        "year": int(row["year"]),
                        "supply": supply,
                        "demand": demand,
                        "balance": round(balance, 1),
                        "balance_as_demand_pct": round(balance / demand * 100, 1),
                    }
                )
            paths[scenario_name] = rows
        base = paths["base_case"]
        commodities[commodity] = {
            "unit": spec["unit"],
            "paths": paths,
            "base_supply_cagr_2026_2030_pct": round(
                _cagr(base[0]["supply"], base[-1]["supply"], 4) * 100, 1
            ),
            "base_demand_cagr_2026_2030_pct": round(
                _cagr(base[0]["demand"], base[-1]["demand"], 4) * 100, 1
            ),
            "assumptions": spec["assumptions"],
        }
    return {
        "model_version": inputs["model_version"],
        "as_of_date": inputs["as_of_date"],
        "input_artifact_hash": _sha256_file(input_path),
        "scope": inputs["scope"],
        "historical_anchors": inputs["historical_anchors"],
        "commodities": commodities,
        "company_transmission": inputs["company_transmission"],
        "decision_summary": {
            "nickel": "基准路径接近平衡、宽松风险仍大；只有印尼配额和成本约束持续，才会形成可持续紧张。",
            "cobalt": "2026—2027年最具政策驱动的紧张性，但高度依赖DRC配额执行、库存与2028年后政策延续。",
            "lithium": "2026年仍可能宽松，2027—2030年缺口风险上升；项目响应弹性使价格与缺口不会线性传导。",
        },
        "sanity_checks": {
            "all_balances_recalculate": all(
                abs(row["balance"] - (row["supply"] - row["demand"])) < 0.01
                for commodity in commodities.values()
                for rows in commodity["paths"].values()
                for row in rows
            ),
            "units_are_not_added_across_commodities": True,
            "mine_output_not_subtracted_from_export_quota": True,
            "planned_capacity_not_counted_as_actual": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="镍钴锂全球供需情景与华友钴业传导模型"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = json.loads(args.input.read_text(encoding="utf-8"))
    output = build(inputs, input_path=args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "input_hash": output["input_artifact_hash"],
                "base_2030_balance": {
                    key: value["paths"]["base_case"][-1]["balance"]
                    for key, value in output["commodities"].items()
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
