from __future__ import annotations

import sqlite3
import json
import threading

import pytest

from tools.migration.stage4_identity_mapping import (
    IdentityMappingError,
    IdentityMappingResolver,
    build_identity_mapping,
)
from tools.migration import stage4_identity_mapping as mapping_module
from tools.migration.stage4_isolated_entry import main as isolated_entry_main


def _database(path, *, duplicate_ticker: bool = False, cycle: bool = False):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE company(id INTEGER PRIMARY KEY, name TEXT, ticker TEXT, market TEXT);
        CREATE TABLE industry(id INTEGER PRIMARY KEY, name TEXT, parent_id INTEGER);
        CREATE TABLE theme(id TEXT PRIMARY KEY, name TEXT);
        """
    )
    conn.execute("INSERT INTO company VALUES(1,'甲公司','000001.SZ','A股')")
    conn.execute(
        "INSERT INTO company VALUES(2,'乙公司',?, 'A股')",
        ("000001.SZ" if duplicate_ticker else None,),
    )
    conn.execute("INSERT INTO industry VALUES(10,'上游',NULL)")
    conn.execute("INSERT INTO industry VALUES(11,'材料',10)")
    if cycle:
        conn.execute("UPDATE industry SET parent_id=11 WHERE id=10")
    conn.execute("INSERT INTO theme VALUES('ai_theme','AI 主题')")
    conn.commit()
    conn.close()


def _alias_approvals(path, *, legacy_ids=("1", "2")):
    path.write_text(
        json.dumps(
            {
                "schema_version": "honghu.identity_mapping_approvals.v2",
                "identity_overrides": [],
                "aliases": [
                    {
                        "entity_type": "company",
                        "stable_key": "company:security:000001.SZ:venue:shenzhen",
                        "legacy_ids": list(legacy_ids),
                        "approval_reference": "human-review-1",
                        "approved_by": "user",
                        "rationale": "fixture 中两个 legacy id 已人工确认为同一证券主体",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_mapping_uses_business_identity_and_hierarchy(tmp_path) -> None:
    path = tmp_path / "research.db"
    _database(path)
    result = build_identity_mapping(path)
    assert result["collision_count"] == 0
    assert len(result["mappings"]) == 2 + 2 * 2 + 1
    keys = {item["stable_key"] for item in result["mappings"]}
    assert "company:security:000001.SZ:venue:shenzhen" in keys
    assert "industry:path:上游/材料" in keys
    assert "industry_q:path:上游/材料" in keys
    assert "theme:id:ai_theme" in keys
    fallback = next(
        item for item in result["mappings"] if item["legacy_id"] == "2" and item["entity_type"] == "company"
    )
    assert fallback["basis"] == "normalized_name_and_market_fallback"
    assert result["schema_version"] == "honghu.user_content_identity_mapping.v3"
    assert result["source_snapshot"]["transaction_contract"] == {
        "mode": "explicit_read_transaction",
        "query_only": True,
        "tables_read_in_one_snapshot": ["company", "industry", "theme"],
    }
    assert len(result["source_snapshot"]["snapshot_identity_sha256"]) == 64
    assert (
        result["source_snapshot"]["database_file_diagnostics"]["role"]
        == "diagnostic_only_not_transaction_snapshot_identity"
    )
    assert len(result["manifest_sha256"]) == 64
    resolver = IdentityMappingResolver(result)
    assert resolver.resolve("company", 1) == "company:security:000001.SZ:venue:shenzhen"
    with pytest.raises(IdentityMappingError, match="unmapped"):
        resolver.resolve("company", 999)


def test_isolated_entry_forwards_identity_mapping_arguments(tmp_path) -> None:
    database = tmp_path / "research.db"
    output = tmp_path / "identity-mapping.json"
    approvals = tmp_path / "identity-approvals.json"
    _database(database)
    approvals.write_text(
        json.dumps(
            {
                "schema_version": "honghu.identity_mapping_approvals.v2",
                "identity_overrides": [],
                "aliases": [],
            }
        ),
        encoding="utf-8",
    )

    exit_code = isolated_entry_main(
        [
            "--repo-root",
            str(mapping_module.ROOT),
            "--module",
            "tools.migration.stage4_identity_mapping",
            "--",
            "--database",
            str(database),
            "--output",
            str(output),
            "--alias-approvals",
            str(approvals),
        ]
    )

    assert exit_code == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema_version"] == "honghu.user_content_identity_mapping.v3"
    assert len(result["mappings"]) == 7
    assert len(result["source_snapshot"]["snapshot_identity_sha256"]) == 64


def test_duplicate_legacy_aliases_share_one_auditable_stable_identity(tmp_path) -> None:
    path = tmp_path / "research.db"
    _database(path, duplicate_ticker=True)
    approvals = _alias_approvals(tmp_path / "aliases.json")
    result = build_identity_mapping(path, alias_approvals=approvals)
    assert result["collision_count"] == 0
    assert result["unapproved_alias_count"] == 0
    assert result["alias_approval_count"] == 1
    assert result["alias_group_count"] == 1
    assert result["alias_groups"] == [
        {
            "entity_type": "company",
            "stable_key": "company:security:000001.SZ:venue:shenzhen",
            "legacy_ids": ["1", "2"],
            "approval_reference": "human-review-1",
            "approved_by": "user",
            "rationale": "fixture 中两个 legacy id 已人工确认为同一证券主体",
            "approval_file_sha256": result["alias_groups"][0]["approval_file_sha256"],
        }
    ]
    resolver = IdentityMappingResolver(result)
    assert resolver.resolve("company", 1) == resolver.resolve("company", 2)


def test_approved_alias_can_qualify_a_tickerless_historical_name(tmp_path) -> None:
    path = tmp_path / "research.db"
    _database(path)
    approvals = _alias_approvals(tmp_path / "aliases.json")
    result = build_identity_mapping(path, alias_approvals=approvals)
    records = {
        item["legacy_id"]: item
        for item in result["mappings"]
        if item["entity_type"] == "company"
    }
    assert records["2"]["stable_key"] == records["1"]["stable_key"]
    assert records["2"]["identity_components"] == {
        "ticker": "000001.SZ",
        "venue": "shenzhen",
        "venue_basis": "approved_alias_security_identity",
        "market": "a股",
    }


def test_identity_override_can_qualify_a_tickerless_historical_entity(tmp_path) -> None:
    path = tmp_path / "research.db"
    _database(path)
    approvals = tmp_path / "overrides.json"
    approvals.write_text(
        json.dumps(
            {
                "schema_version": "honghu.identity_mapping_approvals.v2",
                "identity_overrides": [
                    {
                        "entity_type": "company",
                        "legacy_id": "2",
                        "ticker": "HIST",
                        "venue": "us",
                        "approval_reference": "user-approved-historical-security",
                        "approved_by": "user",
                        "rationale": "fixture historical entity retained under its former security identity",
                    }
                ],
                "aliases": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = build_identity_mapping(path, alias_approvals=approvals)
    record = next(
        item
        for item in result["mappings"]
        if item["entity_type"] == "company" and item["legacy_id"] == "2"
    )
    assert record["stable_key"] == "company:security:HIST:venue:us"
    assert record["identity_components"]["venue_basis"] == "approved_identity_override"


def test_duplicate_ticker_is_not_silently_treated_as_alias(tmp_path) -> None:
    path = tmp_path / "research.db"
    _database(path, duplicate_ticker=True)
    with pytest.raises(IdentityMappingError, match="explicitly approved alias"):
        build_identity_mapping(path)


def test_bare_ticker_uses_market_or_listing_venue(tmp_path) -> None:
    path = tmp_path / "research.db"
    _database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE company SET ticker='AAPL', market='美股' WHERE id=1")
        conn.execute("UPDATE company SET ticker='AAPL', market='港股' WHERE id=2")
    result = build_identity_mapping(path)
    company_keys = {
        item["legacy_id"]: item["stable_key"]
        for item in result["mappings"]
        if item["entity_type"] == "company"
    }
    assert company_keys == {
        "1": "company:security:AAPL:venue:us",
        "2": "company:security:AAPL:venue:hong-kong",
    }


def test_industry_parent_cycle_fails_closed(tmp_path) -> None:
    path = tmp_path / "research.db"
    _database(path, cycle=True)
    with pytest.raises(IdentityMappingError, match="cycle"):
        build_identity_mapping(path)


def test_all_identity_tables_are_bound_to_one_wal_snapshot(tmp_path, monkeypatch) -> None:
    path = tmp_path / "research.db"
    _database(path)
    with sqlite3.connect(path) as setup:
        setup.execute("PRAGMA journal_mode=WAL")

    company_read = threading.Event()
    writer_done = threading.Event()
    original = mapping_module._table_rows

    def intercepted(conn, table):
        rows = original(conn, table)
        if table == "company":
            company_read.set()
            assert writer_done.wait(timeout=5)
        return rows

    def writer():
        assert company_read.wait(timeout=5)
        with sqlite3.connect(path, timeout=5) as connection:
            connection.execute("INSERT INTO industry VALUES(12,'later identity',NULL)")
            connection.commit()
        writer_done.set()

    monkeypatch.setattr(mapping_module, "_table_rows", intercepted)
    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    result = build_identity_mapping(path)
    thread.join(timeout=5)
    assert not thread.is_alive()

    mapped_industries = {
        item["legacy_id"]
        for item in result["mappings"]
        if item["entity_type"] == "industry"
    }
    assert mapped_industries == {"10", "11"}
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM industry").fetchone()[0] == 3
