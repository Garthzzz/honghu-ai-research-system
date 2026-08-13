from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tools.migration.stage4_identity_mapping_crosscheck import build_crosscheck


def _write_database(path: Path, sql: str) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(sql)
    connection.commit()
    connection.close()


def test_crosscheck_compresses_safe_fallback_and_retains_real_ambiguity(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _write_database(
        data / "research.db",
        """
        CREATE TABLE company(id INTEGER PRIMARY KEY,name TEXT,ticker TEXT,market TEXT,listing_status TEXT);
        INSERT INTO company VALUES(1,'PrivateCo',NULL,NULL,'private');
        INSERT INTO company VALUES(2,'ListedNoTicker',NULL,'us','us');
        """,
    )
    _write_database(
        data / "financial.db",
        """
        CREATE TABLE financial_security(
          research_company_id INTEGER,canonical_name TEXT,ticker TEXT,market TEXT,
          listing_status TEXT,identity_status TEXT
        );
        INSERT INTO financial_security VALUES(1,'PrivateCo',NULL,NULL,'private','verified');
        INSERT INTO financial_security VALUES(2,'ListedNoTicker',NULL,'us','us','verified');
        """,
    )
    _write_database(
        data / "sentiment.db",
        "CREATE TABLE company_alias(company_id INTEGER,ticker TEXT,alias TEXT,alias_type TEXT);",
    )
    mapping = {
        "schema_version": "honghu.user_content_identity_mapping.v3",
        "manifest_sha256": "a" * 64,
        "mappings": [
            {
                "entity_type": "company",
                "legacy_id": str(identifier),
                "basis": "normalized_name_and_market_fallback",
                "stable_key": f"company:name-market:{identifier}",
                "source_evidence_identity": "b" * 64,
            }
            for identifier in (1, 2)
        ],
        "alias_groups": [],
        "identity_override_count": 0,
    }
    mapping_path = tmp_path / "mapping.json"
    output_path = tmp_path / "result.json"
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")

    result = build_crosscheck(
        mapping_path=mapping_path,
        source_data_root=data,
        output_path=output_path,
    )

    assert result["counts"]["fallback_machine_crosschecked"] == 1
    assert result["counts"]["fallback_requires_human"] == 1
    assert result["manual_review_items"][0]["legacy_id"] == "2"
    assert result["approval_contract"]["codex_may_not_approve_final_mapping"] is True
