from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools.migration.stage4_unit_s1 import (
    UnitSnapshotError,
    _backup_database,
    _sha,
    build_unit_snapshot,
    verify_snapshot,
)
from tools.migration.stage4_s1_loader import (
    Stage4LoadError,
    validate_sqlite_authority_route,
)


COMMIT = "a" * 40


def _database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE analyst_note(
            id INTEGER PRIMARY KEY,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            content TEXT NOT NULL,
            updated_at TEXT
        );
        INSERT INTO analyst_note VALUES(1, 'company', '7', 'alpha', '2026-08-12T00:00:00Z');
        """
    )
    connection.commit()
    connection.close()


def _registry(path: Path) -> None:
    payload = {
        "schema_version": "honghu.cutover_unit_registry.v1",
        "units": {
            "user_content_notes": {
                "objects": [
                    {"database": "research.db", "object": "analyst_note", "kind": "table"}
                ]
            }
        },
        "validation": {"passed": True},
        "registry_sha256": "b" * 64,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_and_verify_unit_snapshot(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _database(data / "research.db")
    registry = tmp_path / "registry.json"
    _registry(registry)
    output = tmp_path / "out"

    result = build_unit_snapshot(
        unit="user_content_notes",
        source_data_root=data,
        registry_path=registry,
        application_commit_sha=COMMIT,
        output_dir=output,
    )

    assert result["authority_contract"] == {
        "state": "S0_or_S1",
        "authoritative_backend": "sqlite_transition",
        "sqlite_writer_fenced": False,
        "postgresql_formal_business_writes": False,
        "silent_fallback": False,
        "dual_or_shadow_write": False,
    }
    assert result["reconciliation"]["source_row_count"] == 1
    assert result["database_file_identity_role"] == (
        "diagnostic_only_not_unit_business_identity"
    )
    checked = verify_snapshot(
        output / "user_content_notes.snapshot.json",
        output / "user_content_notes.rows.jsonl",
    )
    assert checked["ok"] is True
    assert checked["rows"]["row_count"] == 1


def test_snapshot_identity_is_idempotent_per_exact_release_and_distinct_across_releases(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _database(data / "research.db")
    registry = tmp_path / "registry.json"
    _registry(registry)

    first = build_unit_snapshot(
        unit="user_content_notes",
        source_data_root=data,
        registry_path=registry,
        application_commit_sha="a" * 40,
        output_dir=tmp_path / "first",
    )
    retry = build_unit_snapshot(
        unit="user_content_notes",
        source_data_root=data,
        registry_path=registry,
        application_commit_sha="a" * 40,
        output_dir=tmp_path / "retry",
    )
    newer_release = build_unit_snapshot(
        unit="user_content_notes",
        source_data_root=data,
        registry_path=registry,
        application_commit_sha="c" * 40,
        output_dir=tmp_path / "newer",
    )

    assert first["source_identity_sha256"] == retry["source_identity_sha256"]
    assert first["source_identity_sha256"] == newer_release["source_identity_sha256"]
    assert first["snapshot_id"] == retry["snapshot_id"]
    assert first["snapshot_id"] != newer_release["snapshot_id"]
    assert first["snapshot_id"].endswith(":" + "a" * 12)
    assert newer_release["snapshot_id"].endswith(":" + "c" * 12)


def test_unit_identity_ignores_unowned_rows_but_records_database_file_drift(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _database(data / "research.db")
    registry = tmp_path / "registry.json"
    _registry(registry)
    first = build_unit_snapshot(
        unit="user_content_notes",
        source_data_root=data,
        registry_path=registry,
        application_commit_sha=COMMIT,
        output_dir=tmp_path / "first",
    )
    with sqlite3.connect(data / "research.db") as connection:
        connection.execute("CREATE TABLE unrelated_dynamic(id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO unrelated_dynamic VALUES(1)")
    second = build_unit_snapshot(
        unit="user_content_notes",
        source_data_root=data,
        registry_path=registry,
        application_commit_sha=COMMIT,
        output_dir=tmp_path / "second",
    )

    assert first["source_identity_sha256"] == second["source_identity_sha256"]
    assert first["snapshot_id"] == second["snapshot_id"]
    assert (
        first["database_snapshot_evidence"]["research.db"]["snapshot_sha256"]
        != second["database_snapshot_evidence"]["research.db"]["snapshot_sha256"]
    )


def test_snapshot_verifier_rejects_tampered_row(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _database(data / "research.db")
    registry = tmp_path / "registry.json"
    _registry(registry)
    output = tmp_path / "out"
    build_unit_snapshot(
        unit="user_content_notes",
        source_data_root=data,
        registry_path=registry,
        application_commit_sha=COMMIT,
        output_dir=output,
    )
    rows = output / "user_content_notes.rows.jsonl"
    record = json.loads(rows.read_text(encoding="utf-8"))
    record["payload"]["content"] = "tampered"
    rows.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(UnitSnapshotError, match="payload hash mismatch"):
        verify_snapshot(output / "user_content_notes.snapshot.json", rows)


def test_prebuilt_snapshot_requires_matching_preverified_evidence(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _database(source / "research.db")
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    registry = tmp_path / "registry.json"
    _registry(registry)

    with pytest.raises(UnitSnapshotError, match="evidence is missing"):
        build_unit_snapshot(
            unit="user_content_notes",
            source_data_root=source,
            registry_path=registry,
            application_commit_sha=COMMIT,
            output_dir=tmp_path / "missing",
            source_is_consistent_snapshot=True,
        )

    evidence = _backup_database(source / "research.db", snapshot / "research.db")
    evidence["snapshot_sha256"] = "0" * 64
    with pytest.raises(UnitSnapshotError, match="identity is invalid"):
        build_unit_snapshot(
            unit="user_content_notes",
            source_data_root=snapshot,
            registry_path=registry,
            application_commit_sha=COMMIT,
            output_dir=tmp_path / "tampered",
            source_is_consistent_snapshot=True,
            preverified_database_evidence={"research.db": evidence},
        )


def test_snapshot_verifier_rejects_authority_escalation(tmp_path: Path) -> None:
    manifest = {
        "schema_version": "honghu.stage4_unit_snapshot.v1",
        "cutover_unit": "user_content_notes",
        "snapshot_id": "one",
        "authority_contract": {
            "authoritative_backend": "postgresql_production",
            "sqlite_writer_fenced": True,
            "postgresql_formal_business_writes": True,
            "silent_fallback": False,
            "dual_or_shadow_write": False,
        },
    }
    manifest["manifest_sha256"] = _sha(manifest)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(UnitSnapshotError, match="unsafe authority contract"):
        verify_snapshot(path)


def test_build_rejects_unvalidated_registry(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    _registry(registry)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["validation"]["passed"] = False
    registry.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(UnitSnapshotError, match="validation is not green"):
        build_unit_snapshot(
            unit="user_content_notes",
            source_data_root=tmp_path,
            registry_path=registry,
            application_commit_sha=COMMIT,
            output_dir=tmp_path / "out",
        )


def test_snapshot_preserves_duplicate_rows_without_primary_key(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    connection = sqlite3.connect(data / "research.db")
    connection.executescript(
        """
        CREATE TABLE analyst_note(content TEXT NOT NULL);
        INSERT INTO analyst_note VALUES('same'),('same');
        """
    )
    connection.commit()
    connection.close()
    registry = tmp_path / "registry.json"
    _registry(registry)
    output = tmp_path / "out"

    result = build_unit_snapshot(
        unit="user_content_notes",
        source_data_root=data,
        registry_path=registry,
        application_commit_sha=COMMIT,
        output_dir=output,
    )
    rows = [
        json.loads(line)
        for line in (output / "user_content_notes.rows.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]

    assert result["reconciliation"]["source_row_count"] == 2
    assert [row["source_ordinal"] for row in rows] == [1, 2]
    assert rows[0]["source_key"] != rows[1]["source_key"]
    assert verify_snapshot(
        output / "user_content_notes.snapshot.json",
        output / "user_content_notes.rows.jsonl",
    )["ok"] is True


def test_generic_staging_route_remains_sqlite_s0_and_fails_closed(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "units": {
                    "financial_data": {
                        "state": "S0",
                        "authoritative_backend": "sqlite_transition",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    route = tmp_path / "route.json"
    route.write_text("{}", encoding="utf-8")
    result = validate_sqlite_authority_route(
        cutover_unit="financial_data",
        route_path=route,
        registry_path=registry,
    )
    assert result["authority_state"] == "S0"
    assert result["production_postgresql_enabled"] is False

    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["units"]["financial_data"]["state"] = "S2"
    payload["units"]["financial_data"]["authoritative_backend"] = "postgresql_production"
    registry.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Stage4LoadError, match="outside S0/S1"):
        validate_sqlite_authority_route(
            cutover_unit="financial_data",
            route_path=route,
            registry_path=registry,
        )
