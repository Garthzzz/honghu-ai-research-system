from __future__ import annotations

import sqlite3

from tools.migration.stage4_identity_mapping import build_identity_mapping
from tools.migration.stage4_identity_mapping_equivalence import (
    compare_identity_mappings,
)


def _database(path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE company(id INTEGER PRIMARY KEY,name TEXT,ticker TEXT,market TEXT);
        CREATE TABLE industry(id INTEGER PRIMARY KEY,name TEXT,parent_id INTEGER);
        CREATE TABLE theme(id TEXT PRIMARY KEY,name TEXT);
        INSERT INTO company VALUES(1,'Apple','AAPL','us');
        INSERT INTO industry VALUES(1,'AI',NULL);
        INSERT INTO theme VALUES('ai','AI');
        """
    )
    connection.commit()
    connection.close()


def test_physical_copy_diagnostics_do_not_invalidate_business_mapping(tmp_path) -> None:
    source = tmp_path / "source.db"
    candidate = tmp_path / "transfer" / "research.db"
    candidate.parent.mkdir()
    _database(source)
    source_mapping = build_identity_mapping(source, alias_approvals=None)

    with sqlite3.connect(source) as source_connection, sqlite3.connect(
        candidate
    ) as target_connection:
        source_connection.backup(target_connection)
    with sqlite3.connect(candidate) as connection:
        current = int(connection.execute("PRAGMA schema_version").fetchone()[0])
        connection.execute(f"PRAGMA schema_version={current + 100}")
    candidate_mapping = build_identity_mapping(candidate, alias_approvals=None)

    assert source_mapping["manifest_sha256"] != candidate_mapping["manifest_sha256"]
    assert (
        source_mapping["source_snapshot"]["snapshot_identity_sha256"]
        != candidate_mapping["source_snapshot"]["snapshot_identity_sha256"]
    )
    result = compare_identity_mappings(source_mapping, candidate_mapping)
    assert result["status"] == "pass"
    assert result["semantic_equivalent"] is True
    assert result["differing_sections"] == []
    assert result["approval_contract"]["candidate_equivalence_does_not_grant_human_approval"] is True


def test_real_source_or_mapping_drift_remains_fail_closed(tmp_path) -> None:
    source = tmp_path / "source.db"
    candidate = tmp_path / "candidate.db"
    _database(source)
    _database(candidate)
    approved = build_identity_mapping(source, alias_approvals=None)

    with sqlite3.connect(candidate) as connection:
        connection.execute("UPDATE company SET name='Apple Changed' WHERE id=1")
        connection.commit()
    changed = build_identity_mapping(candidate, alias_approvals=None)
    result = compare_identity_mappings(approved, changed)

    assert result["status"] == "fail"
    assert result["semantic_equivalent"] is False
    assert "source_tables" in result["differing_sections"]
    assert "mappings" in result["differing_sections"]


def test_real_table_schema_drift_remains_fail_closed(tmp_path) -> None:
    source = tmp_path / "source.db"
    candidate = tmp_path / "candidate.db"
    _database(source)
    _database(candidate)
    approved = build_identity_mapping(source, alias_approvals=None)

    with sqlite3.connect(candidate) as connection:
        connection.execute("ALTER TABLE theme ADD COLUMN description TEXT")
        connection.commit()
    changed = build_identity_mapping(candidate, alias_approvals=None)
    result = compare_identity_mappings(approved, changed)

    assert result["semantic_equivalent"] is False
    assert "source_tables" in result["differing_sections"]
