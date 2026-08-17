from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.migration.stage4_generic_unit_s1 import (
    DEPENDENCIES,
    GenericUnitS1Error,
    _validate_dependency_states,
)


def test_all_remaining_generic_units_have_reviewed_dependencies() -> None:
    assert set(DEPENDENCIES) == {
        "financial_data",
        "research_publication",
        "dynamic_intelligence",
        "operations_governance",
        "investment_hypotheses",
        "opportunity_lens",
        "sentiment_analytics",
    }
    assert all("shared_identity" in dependencies for dependencies in DEPENDENCIES.values())
    assert DEPENDENCIES["dynamic_intelligence"] == (
        "shared_identity",
        "research_publication",
    )


def test_dynamic_source_reads_are_owned_by_research_publication_dependency() -> None:
    root = Path(__file__).resolve().parents[2]
    ownership = json.loads(
        (root / "config/migration/table_ownership.json").read_text(encoding="utf-8")
    )
    registry = json.loads(
        (root / "config/migration/cutover_unit_registry.json").read_text(encoding="utf-8")
    )
    expected = ["shared_identity", "research_publication"]
    assert ownership["units"]["dynamic_intelligence"]["dependencies"] == expected
    assert registry["units"]["dynamic_intelligence"]["dependencies"] == expected
    assert "source" in ownership["units"]["research_publication"]["objects"]["research.db"]
    assert "source" not in ownership["units"]["dynamic_intelligence"]["objects"]["research.db"]


def test_financial_release_binding_uses_generic_immutable_snapshot_contract() -> None:
    _validate_dependency_states(
        "financial_data",
        {"shared_identity": ("S3", "postgresql_production")},
    )


def test_shared_identity_dependency_must_be_formal_postgresql() -> None:
    with pytest.raises(GenericUnitS1Error, match="PostgreSQL-authoritative"):
        _validate_dependency_states(
            "research_publication",
            {"shared_identity": ("S1", "sqlite_transition")},
        )


def test_nonformal_upstream_s1_is_allowed_only_on_sqlite_authority() -> None:
    _validate_dependency_states(
        "operations_governance",
        {
            "shared_identity": ("S3", "postgresql_production"),
            "dynamic_intelligence": ("S1", "sqlite_transition"),
        },
    )
    with pytest.raises(GenericUnitS1Error, match="invalid authoritative backend"):
        _validate_dependency_states(
            "operations_governance",
            {
                "shared_identity": ("S3", "postgresql_production"),
                "dynamic_intelligence": ("S1", "postgresql_production"),
            },
        )


def test_missing_or_s0_dependency_fails_closed() -> None:
    with pytest.raises(GenericUnitS1Error, match="incomplete"):
        _validate_dependency_states("sentiment_analytics", {})
    with pytest.raises(GenericUnitS1Error, match="not migration-ready"):
        _validate_dependency_states(
            "sentiment_analytics",
            {
                "shared_identity": ("S3", "postgresql_production"),
                "dynamic_intelligence": ("S0", "sqlite_transition"),
            },
        )
