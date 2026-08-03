from __future__ import annotations

"""冻结锂电池独立模型与外部预测、市场市值的对账记录。

本脚本只读 ``financial.db``，把本研究 run 已存在的对账结果固化为可哈希
JSON；不新增或修改任何财务观测。
"""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "financial.db"
OUT_PATH = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_external_reconciliation_v1.json"
)
RUN_REF = "lithium_battery_b_20260728"
AS_OF_DATE = "2026-07-28"


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def build() -> dict[str, Any]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        runs = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id,run_key,security_id,skill_name,model_name,model_role,
                       status,forecast_start,forecast_end,valuation_date,
                       independent_before_consensus,input_hash,output_hash,frozen_at
                  FROM financial_model_run
                 WHERE research_run_ref=?
                 ORDER BY security_id,id
                """,
                (RUN_REF,),
            )
        ]
        run_ids = [int(row["id"]) for row in runs]
        if not run_ids:
            raise RuntimeError(f"没有找到研究 run：{RUN_REF}")
        placeholders = ",".join("?" for _ in run_ids)
        rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT id,model_run_id,benchmark_type,benchmark_source_ref,
                       metric_name,period,independent_value,benchmark_value,
                       unit,difference_value,difference_pct,decomposition_json,
                       conclusion,reconciled_at
                  FROM financial_reconciliation
                 WHERE model_run_id IN ({placeholders})
                 ORDER BY model_run_id,benchmark_type,metric_name,period
                """,
                tuple(run_ids),
            )
        ]
    finally:
        conn.close()

    for row in rows:
        raw = row.pop("decomposition_json", "{}")
        try:
            row["decomposition"] = json.loads(raw or "{}")
        except json.JSONDecodeError:
            row["decomposition"] = {"raw": raw}
    payload: dict[str, Any] = {
        "schemaVersion": "lithium_battery.external_reconciliation.v1",
        "researchRunRef": RUN_REF,
        "asOfDate": AS_OF_DATE,
        "sequenceContract": (
            "独立模型已先冻结；本文件只复制之后形成的卖方预测和当前市值对账，"
            "不回写独立模型参数。"
        ),
        "modelRuns": runs,
        "reconciliations": rows,
        "summary": {
            "modelRunCount": len(runs),
            "reconciliationCount": len(rows),
            "consensusCount": sum(
                row["benchmark_type"] == "consensus" for row in rows
            ),
            "marketImpliedCount": sum(
                row["benchmark_type"] == "market_implied" for row in rows
            ),
        },
    }
    payload["contentSha256"] = "sha256:" + hashlib.sha256(
        _canonical_bytes(payload)
    ).hexdigest()
    return payload


def main() -> None:
    payload = build()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUT_PATH.relative_to(ROOT)).replace("\\", "/"),
                "summary": payload["summary"],
                "contentSha256": payload["contentSha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

