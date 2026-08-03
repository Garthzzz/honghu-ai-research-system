#!/usr/bin/env python
"""Build a content-addressed audit bundle for the PCB-equipment research."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "research.db"
DEFAULT_OUTPUT = ROOT / "cache" / "pcb_equipment_research" / "final_bundle_manifest.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
    }


def fact_count(path: Path) -> tuple[int, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    points = payload.get("data_points") or []
    identities = {
        (
            point.get("source_ref"), point.get("company"), point.get("metric"),
            point.get("unit"), point.get("scope_key"),
        )
        for point in points
    }
    return len(points), len(identities)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    db_path = args.db.resolve()

    immutable = ROOT / "cache" / "claims" / "pcb_equipment_b_20260719_01_full_claims.json"
    corrected = ROOT / "cache" / "pcb_equipment_research" / "pcb_equipment_corrected_claims_v3.json"
    raw_snapshot = ROOT / "cache" / "pcb_equipment_research" / "company_financial_snapshot.json"
    snapshot = ROOT / "cache" / "pcb_equipment_research" / "staging_financial_contract" / "company_financial_snapshot_v2.json"
    producer = ROOT / "cache" / "pcb_equipment_research" / "producer_manifest.json"
    ledger = ROOT / "cache" / "pcb_equipment_research" / "calculation_ledger.json"
    source_registration = ROOT / "cache" / "pcb_equipment_research" / "profile_source_registration.json"
    source_map = ROOT / "cache" / "db_queue" / "pcb_equipment_b_20260719_source_map.json"

    documents = sorted((ROOT / "docs" / "industries").glob("PCB专用设备*.md"))
    charts = sorted((ROOT / "tools" / "viewer" / "static" / "generated" / "pcb_equipment").glob("*.png"))
    supporting = [
        ROOT / "cache" / "research_runs" / "pcb_equipment_b_20260719" / "brief.json",
        ROOT / "cache" / "pcb_equipment_research" / "pcb_equipment_v3_candidate_dry_run_manifest.json",
        ROOT / "cache" / "pcb_equipment_research" / "pcb_equipment_v3_candidate_apply_manifest.json",
        ROOT / "cache" / "pcb_equipment_research" / "pcb_equipment_official_supplement_v2_candidate_apply.json",
        ROOT / "cache" / "pcb_equipment_research" / "application_manifest.json",
        ROOT / "cache" / "pcb_equipment_research" / "pdf_extraction_index.json",
        ROOT / "cache" / "pcb_equipment_research" / "workflow_request.json",
    ]
    supporting = [path for path in supporting if path.is_file()]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        counts = {
            "industry_data_points": conn.execute(
                "SELECT COUNT(*) FROM industry_data_point WHERE industry_id=23"
            ).fetchone()[0],
            "company_profiles": conn.execute(
                "SELECT COUNT(*) FROM company_profile WHERE industry_id=23"
            ).fetchone()[0],
            "company_links": conn.execute(
                "SELECT COUNT(*) FROM company_industry WHERE industry_id=23"
            ).fetchone()[0],
            "sub_market_shares": conn.execute(
                "SELECT COUNT(*) FROM company_sub_market_share WHERE industry_id=23"
            ).fetchone()[0],
            "profiles_with_events": conn.execute(
                """SELECT COUNT(*) FROM company_profile WHERE industry_id=23
                   AND recent_events IS NOT NULL AND recent_events NOT IN ('','[]')"""
            ).fetchone()[0],
            "selected_table_flags": conn.execute(
                """SELECT COALESCE(SUM(COALESCE(in_global_table,0)+COALESCE(in_china_table,0)
                   +COALESCE(is_china_tech_leader,0)),0) FROM company_profile WHERE industry_id=23"""
            ).fetchone()[0],
            "industry_relations": conn.execute(
                "SELECT COUNT(*) FROM industry_relation WHERE upstream_id=23"
            ).fetchone()[0],
        }
        share_rows = [dict(row) for row in conn.execute(
            """SELECT c.name AS company,s.geo,s.sub_market,s.share,s.share_as_of,s.rank,s.source_ids
               FROM company_sub_market_share s JOIN company c ON c.id=s.company_id
               WHERE s.industry_id=23 ORDER BY s.geo,s.sub_market,c.name"""
        )]
        supplements = [dict(row) for row in conn.execute(
            """SELECT id,source_id,company_id,metric,period,value_num,unit,extraction_method,note
               FROM industry_data_point WHERE industry_id=23 AND source_id=702
               AND metric IN (
                 'KLA PCB and Component Inspection分部收入',
                 'KLA PCB与元件检测分部商誉及无形资产减值'
               ) ORDER BY id"""
        )]
        registered_ids = sorted(set(json.loads(source_map.read_text(encoding="utf-8")).values()))
        placeholders = ",".join("?" for _ in registered_ids)
        source_metadata = [dict(row) for row in conn.execute(
            f"""SELECT id,title,publisher,language,fetch_method,note FROM source
                WHERE id IN ({placeholders}) ORDER BY id""",
            registered_ids,
        )]
    finally:
        conn.close()

    immutable_count, immutable_facts = fact_count(immutable)
    corrected_count, corrected_facts = fact_count(corrected)
    payload: dict[str, Any] = {
        "schema_version": "pcb_equipment.final_bundle.v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "industry": {"id": 23, "name": "PCB专用设备", "track": "b"},
        "database": {
            **artifact(db_path),
            "integrity_check": integrity,
            "foreign_key_violations": foreign_keys,
            "counts": counts,
            "supplemental_data_points": supplements,
            "sub_market_share_rows": share_rows,
        },
        "claims_contract": {
            "immutable": {**artifact(immutable), "data_point_count": immutable_count, "fact_count": immutable_facts},
            "corrected": {**artifact(corrected), "data_point_count": corrected_count, "fact_count": corrected_facts},
            "controlled_supplement_count": len(supplements),
            "final_database_data_point_count": counts["industry_data_points"],
        },
        "financial_snapshots": {
            "provider_frozen_input": artifact(raw_snapshot),
            "normalized_public_contract": artifact(snapshot),
        },
        "producer_manifest": artifact(producer),
        "calculation_ledger": artifact(ledger),
        "source_registration": artifact(source_registration),
        "source_map": artifact(source_map),
        "source_metadata": source_metadata,
        "documents": [artifact(path) for path in documents],
        "charts": [artifact(path) for path in charts],
        "supporting_manifests": [artifact(path) for path in supporting],
        "limitations": [
            "公开资料不足以建立18层以上高多层PCB专用设备的独立全球市场规模。",
            "4.886亿元仅为没有产能分母的示意设备篮子，不是标准产线、完整BOM或采购预算。",
            "CR10、HHI、完整客户型号与逐项目设备清单客观不可得，相关要求按完成受限记录。",
            "海外集团与PCB设备子品牌缺少独立分部财务时，只展示集团财务参照，不归因到PCB设备。",
        ],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["bundle_content_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "file_sha256": sha256(output), **payload["database"]["counts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
