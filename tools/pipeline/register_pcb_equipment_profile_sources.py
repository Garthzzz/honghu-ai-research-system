#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Register official company/profile sources for the PCB-equipment package.

This adapter deliberately registers sources only.  It never writes
``industry_data_point`` and therefore cannot duplicate the 1,064 facts already
loaded through the unified B-track ingest entry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    from .ingest_research import normalize_date, register_source, source_key
    from .pcb_equipment_research_data import INDUSTRY_NAME, SOURCES
except ImportError:
    from ingest_research import normalize_date, register_source, source_key
    from pcb_equipment_research_data import INDUSTRY_NAME, SOURCES


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "research.db"
SOURCE_MAP_PATH = ROOT / "cache" / "db_queue" / "pcb_equipment_b_20260719_source_map.json"
OUTPUT_PATH = ROOT / "cache" / "pcb_equipment_research" / "profile_source_registration.json"


def _source_payload(spec) -> dict:
    payload = {
        "title": spec.title,
        "publisher": spec.publisher,
        "publish_date": spec.publish_date,
        "source_type": spec.source_type,
        "quality_tier": spec.quality_tier,
        "is_primary_source": spec.primary,
        "source_subtype": spec.source_subtype,
        "value_layer": spec.value_layer,
        "source_credibility": "verified_primary" if spec.primary else "verified_supporting",
        "language": spec.language,
        "note": spec.note,
        "fetch_timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "content_snapshot_path": spec.snapshot_path,
    }
    if spec.file_path:
        payload["source_file"] = spec.file_path
        payload["fetch_method"] = spec.fetch_method or "pdf_local"
    else:
        payload["source_url"] = spec.url
        payload["fetch_method"] = spec.fetch_method or "web_fetch"
        payload["domain"] = urlparse(spec.url or "").netloc or None
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--source-map", type=Path, default=SOURCE_MAP_PATH,
                        help="读取既有统一ingest来源映射")
    parser.add_argument("--source-map-output", type=Path,
                        help="可选：将本次补充后的来源映射写到独立文件；默认覆盖--source-map")
    parser.add_argument("--manifest", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    db_path = args.db.resolve()
    source_map_path = args.source_map.resolve()
    source_map_output = (args.source_map_output or args.source_map).resolve()
    manifest_path = args.manifest.resolve()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    industry = conn.execute("SELECT id FROM industry WHERE name=?", (INDUSTRY_NAME,)).fetchone()
    if not industry:
        raise RuntimeError(f"行业尚未建档: {INDUSTRY_NAME}")
    mapping = json.loads(source_map_path.read_text(encoding="utf-8")) if source_map_path.is_file() else {}
    rows = conn.execute("SELECT id,file_path,COALESCE(source_url,url) AS source_url FROM source").fetchall()
    by_path = {str(row["file_path"]): int(row["id"]) for row in rows if row["file_path"]}
    by_url = {str(row["source_url"]): int(row["id"]) for row in rows if row["source_url"]}
    created = 0
    reused = 0
    registered: dict[str, int] = {}
    conn.execute("BEGIN IMMEDIATE")
    try:
        for spec in SOURCES:
            payload = _source_payload(spec)
            key = source_key(payload)
            source_id, is_new = register_source(
                conn,
                source=payload,
                key=key,
                industry_id=int(industry["id"]),
                papers_subdir="PCB设备",
                by_path=by_path,
                by_url=by_url,
            )
            mapping[key.text()] = source_id
            registered[spec.key] = source_id
            # The first ingest intentionally remains immutable.  Corrected
            # official-page metadata is reconciled on the reused source row so
            # Viewer citations show publication date separately from access time.
            conn.execute(
                """
                UPDATE source SET title=?,publisher=?,publish_date=?,source_type=?,
                  quality_tier=?,value_layer=?,source_subtype=?,is_primary_source=?,
                  language=?,note=?,fetch_method=?
                WHERE id=?
                """,
                (
                    spec.title, spec.publisher, normalize_date(spec.publish_date), spec.source_type,
                    spec.quality_tier, spec.value_layer, spec.source_subtype, int(spec.primary),
                    spec.language, spec.note, payload["fetch_method"], source_id,
                ),
            )
            created += int(is_new)
            reused += int(not is_new)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    source_map_output.parent.mkdir(parents=True, exist_ok=True)
    source_map_output.write_text(json.dumps(mapping, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    output = {
        "industry": INDUSTRY_NAME,
        "industry_id": int(industry["id"]),
        "db": str(db_path),
        "created": created,
        "reused": reused,
        "registered": registered,
        "source_map": str(source_map_output.relative_to(ROOT)).replace("\\", "/"),
        "source_map_sha256": _sha256(source_map_output),
        "note": "仅注册来源并关联行业，未写入 industry_data_point。",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
