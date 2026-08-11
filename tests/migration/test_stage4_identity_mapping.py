from __future__ import annotations

import sqlite3

import pytest

from tools.migration.stage4_identity_mapping import (
    IdentityMappingError,
    IdentityMappingResolver,
    build_identity_mapping,
)


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


def test_mapping_uses_business_identity_and_hierarchy(tmp_path) -> None:
    path = tmp_path / "research.db"
    _database(path)
    result = build_identity_mapping(path)
    assert result["collision_count"] == 0
    assert len(result["mappings"]) == 2 + 2 * 2 + 1
    keys = {item["stable_key"] for item in result["mappings"]}
    assert "company:ticker:000001.SZ" in keys
    assert "industry:path:上游/材料" in keys
    assert "industry_q:path:上游/材料" in keys
    assert "theme:id:ai_theme" in keys
    fallback = next(
        item for item in result["mappings"] if item["legacy_id"] == "2" and item["entity_type"] == "company"
    )
    assert fallback["basis"] == "normalized_name_and_market_fallback"
    assert len(result["manifest_sha256"]) == 64
    resolver = IdentityMappingResolver(result)
    assert resolver.resolve("company", 1) == "company:ticker:000001.SZ"
    with pytest.raises(IdentityMappingError, match="unmapped"):
        resolver.resolve("company", 999)


def test_duplicate_legacy_aliases_share_one_auditable_stable_identity(tmp_path) -> None:
    path = tmp_path / "research.db"
    _database(path, duplicate_ticker=True)
    result = build_identity_mapping(path)
    assert result["collision_count"] == 0
    assert result["alias_group_count"] == 1
    assert result["alias_groups"] == [
        {
            "entity_type": "company",
            "stable_key": "company:ticker:000001.SZ",
            "legacy_ids": ["1", "2"],
        }
    ]
    resolver = IdentityMappingResolver(result)
    assert resolver.resolve("company", 1) == resolver.resolve("company", 2)


def test_industry_parent_cycle_fails_closed(tmp_path) -> None:
    path = tmp_path / "research.db"
    _database(path, cycle=True)
    with pytest.raises(IdentityMappingError, match="cycle"):
        build_identity_mapping(path)
