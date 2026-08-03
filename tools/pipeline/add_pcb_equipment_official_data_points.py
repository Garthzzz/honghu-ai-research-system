#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Add the small, audited official-source supplement to PCB-equipment research.

The unified claims ingest is intentionally immutable after its first live load.
This adapter is idempotent and routes every new fact through ``write_data_point``.
It defaults to a read-only dry run; ``--apply`` is required to write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

try:
    from .db_writer import write_data_point
    from . import consensus_compute
except ImportError:
    from db_writer import write_data_point
    import consensus_compute


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "research.db"
DEFAULT_MANIFEST = ROOT / "cache" / "pcb_equipment_research" / "official_data_point_supplement.json"
KLA_10K_URL = "https://www.sec.gov/Archives/edgar/data/319201/000031920125000024/klac-20250630.htm"

SUPPLEMENT_SPECS = (
    {
        "metric": "KLA PCB and Component Inspection分部收入",
        "period": "FY2025（截至2025-06-30）",
        "unit": "亿美元",
        "value_num": 6.21721,
        "source_excerpt": (
            "KLA FY2025 10-K披露PCB与元件检测分部收入为621,721千美元；"
            "原文：FY2025 PCB and Component Inspection revenue: USD621,721 thousand."
        ),
        "extraction_method": "inferred",
        "as_of_date": "2025-06-30",
        "note": (
            "公式=621,721千美元÷100,000=6.21721亿美元；来源为KLA FY2025 10-K。"
            "分部同时包含component inspection及相关业务，不能等同纯PCB专用设备收入。"
        ),
    },
    {
        "metric": "KLA PCB与元件检测分部商誉及无形资产减值",
        "period": "FY2025第二财季（截至2024-12-31）",
        "unit": "亿美元",
        "value_num": 2.391,
        "source_excerpt": (
            "KLA FY2025 10-K称PCB业务长期预测继续恶化，并在FY2025第二财季对"
            "PCB and Component Inspection分部计提230.4百万美元商誉减值和"
            "8.7百万美元无形资产减值，合计239.1百万美元。"
        ),
        "extraction_method": "inferred",
        "as_of_date": "2024-12-31",
        "note": (
            "公式=(230.4+8.7)百万美元÷100=2.391亿美元；来源为KLA FY2025 10-K。"
            "这是KLA特定分部、产品组合和预测变化的反方证据，不能单独证明全球PCB设备市场收缩。"
        ),
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db_path = args.db.resolve()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    industry = conn.execute("SELECT id FROM industry WHERE name='PCB专用设备'").fetchone()
    source = conn.execute(
        "SELECT id FROM source WHERE COALESCE(source_url,url)=?", (KLA_10K_URL,)
    ).fetchone()
    company = conn.execute("SELECT id FROM company WHERE name='KLA'").fetchone()
    if not industry or not source or not company:
        raise RuntimeError("需要先建立PCB专用设备行业、KLA公司和KLA FY2025 10-K来源")

    existing_by_key = {}
    for spec in SUPPLEMENT_SPECS:
        row = conn.execute(
            """
            SELECT id FROM industry_data_point
            WHERE industry_id=? AND company_id=? AND source_id=? AND metric=? AND period=?
            """,
            (
                int(industry["id"]), int(company["id"]), int(source["id"]),
                spec["metric"], spec["period"],
            ),
        ).fetchone()
        existing_by_key[(spec["metric"], spec["period"])] = row
    before_count = conn.execute(
        "SELECT COUNT(*) FROM industry_data_point WHERE industry_id=?", (int(industry["id"]),)
    ).fetchone()[0]

    inserted_count = 0
    data_point_ids = {
        key: (int(row["id"]) if row else None)
        for key, row in existing_by_key.items()
    }
    if args.apply:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for spec in SUPPLEMENT_SPECS:
                key = (spec["metric"], spec["period"])
                dp_id = data_point_ids[key]
                if dp_id is None:
                    dp_id = write_data_point(
                        conn,
                        industry_id=int(industry["id"]),
                        company_id=int(company["id"]),
                        source_id=int(source["id"]),
                        **spec,
                    )
                    data_point_ids[key] = int(dp_id)
                    inserted_count += 1
                consensus_compute.recompute_after_insert(int(dp_id), conn=conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    after_count = conn.execute(
        "SELECT COUNT(*) FROM industry_data_point WHERE industry_id=?", (int(industry["id"]),)
    ).fetchone()[0]
    final_rows = []
    for spec in SUPPLEMENT_SPECS:
        key = (spec["metric"], spec["period"])
        dp_id = data_point_ids[key]
        final_row = conn.execute(
            """SELECT id,metric,period,value_num,unit,consensus_status,peer_count,
                      peer_median,peer_std,deviation_from_median
               FROM industry_data_point WHERE id=?""",
            (dp_id,),
        ).fetchone() if dp_id is not None else None
        final_rows.append({
            "data_point": dict(final_row) if final_row else None,
            "would_insert": dp_id is None,
            "already_existed": existing_by_key[key] is not None,
        })
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    if args.apply and after_count - before_count != inserted_count:
        raise RuntimeError("行业数据点计数变化与预期不一致")
    if fk:
        raise RuntimeError(f"foreign_key_check失败: {len(fk)}")

    manifest = {
        "schema_version": "pcb_equipment.official_data_point_supplement.v2",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "db": str(db_path),
        "mode": "apply" if args.apply else "dry_run",
        "industry_id": int(industry["id"]),
        "source_id": int(source["id"]),
        "company_id": int(company["id"]),
        "requested_data_point_count": len(SUPPLEMENT_SPECS),
        "inserted_count": inserted_count,
        "already_existed_count": sum(row is not None for row in existing_by_key.values()),
        "industry_data_point_count_before": before_count,
        "industry_data_point_count_after": after_count,
        "foreign_key_check_errors": len(fk),
        "data_points": final_rows,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["manifest_sha256"] = _sha256(args.manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
