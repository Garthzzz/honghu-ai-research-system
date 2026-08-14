from __future__ import annotations

import json

import pytest

from tools.migration.stage4_identity_mapping import IdentityMappingResolver
from tools.migration.stage4_shared_identity_s1 import (
    SharedIdentityS1Error,
    _record_kind,
    _stable_key,
)


class _Mapping:
    def resolve(self, entity_type: str, legacy_id: str) -> str:
        return f"{entity_type}:stable:{legacy_id}"


def test_shared_identity_stable_keys_use_approved_entity_mapping() -> None:
    mapping = _Mapping()
    assert _stable_key(
        source_database="research.db",
        source_table="company",
        legacy_id="1",
        source_key="source-1",
        payload={"id": 1},
        mapping=mapping,  # type: ignore[arg-type]
    ) == "company:stable:1"
    assert _stable_key(
        source_database="financial.db",
        source_table="financial_security",
        legacy_id="9",
        source_key="source-9",
        payload={"id": 9, "research_company_id": 1},
        mapping=mapping,  # type: ignore[arg-type]
    ) == "company:stable:1"


def test_shared_identity_relationships_are_stable_and_table_scoped() -> None:
    mapping = _Mapping()
    first = _stable_key(
        source_database="research.db",
        source_table="company_industry",
        legacy_id="7",
        source_key="source-key",
        payload={"id": 7},
        mapping=mapping,  # type: ignore[arg-type]
    )
    second = _stable_key(
        source_database="research.db",
        source_table="theme_company",
        legacy_id="7",
        source_key="source-key",
        payload={"id": 7},
        mapping=mapping,  # type: ignore[arg-type]
    )
    assert first != second
    assert _record_kind("company_profile") == "profile"
    assert _record_kind("company_identity_alias") == "mapping"


def test_researcher_without_name_fails_closed() -> None:
    with pytest.raises(SharedIdentityS1Error, match="no stable name"):
        _stable_key(
            source_database="research.db",
            source_table="researcher",
            legacy_id="1",
            source_key="source-1",
            payload={"id": 1, "name": ""},
            mapping=_Mapping(),  # type: ignore[arg-type]
        )


def test_migration_contains_formal_schema_and_s1_only_controller() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    sql = (root / "migrations/postgresql/0005_shared_identity_expand.sql").read_text(
        encoding="utf-8"
    )
    assert "shared_identity.legacy_record" in sql
    assert "prepare_cutover_unit_authority_s1" in sql
    assert "ABSENT->S0 or S0->S1" in sql
    assert "transition_cutover_unit" in sql
    assert "S2" not in sql.split("CREATE OR REPLACE FUNCTION operations.prepare_cutover_unit_authority_s1", 1)[1].split("$$;", 1)[0]
