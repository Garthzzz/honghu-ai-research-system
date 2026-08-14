from __future__ import annotations

import pytest

from tools.migration.stage4_financial_data_s1 import (
    FinancialDataS1Error,
    _stable_key,
    _validate_references,
)


def test_financial_stable_keys_prefer_business_operation_keys() -> None:
    assert _stable_key(
        "financial_observation", "3", {"observation_key": "sha256:abc"}
    ) == "financial:observation:sha256:abc"
    assert _stable_key(
        "financial_model_run", "9", {"run_key": "model:fy2028"}
    ) == "financial:model-run:model:fy2028"
    assert _stable_key("financial_model_input", "4", {}) == "financial:financial_model_input:4"


def test_financial_reference_validation_is_fail_closed() -> None:
    rows = [
        {"table": "financial_source_snapshot", "legacy_id": "1", "payload": {}},
        {"table": "financial_model_run", "legacy_id": "2", "payload": {"security_id": 7}},
        {
            "table": "financial_observation",
            "legacy_id": "3",
            "payload": {"security_id": 7, "source_snapshot_id": 1, "model_run_id": 2},
        },
        {"table": "financial_model_input", "legacy_id": "4", "payload": {"model_run_id": 2}},
        {"table": "financial_model_output", "legacy_id": "5", "payload": {"model_run_id": 2}},
        {"table": "financial_reconciliation", "legacy_id": "6", "payload": {"model_run_id": 2}},
        {"table": "financial_observation_revision", "legacy_id": "7", "payload": {"observation_id": 3}},
        {"table": "financial_schema_meta", "legacy_id": "schema_version", "payload": {}},
    ]
    _validate_references(rows, {"7"})
    with pytest.raises(FinancialDataS1Error, match="unmapped reference"):
        _validate_references(rows, set())
    rows[-2]["payload"]["observation_id"] = 999
    with pytest.raises(FinancialDataS1Error, match="unmapped reference"):
        _validate_references(rows, {"7"})


def test_financial_expand_migration_keeps_shared_identity_dependency_external() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    sql = (root / "migrations/postgresql/0008_financial_data_expand.sql").read_text(
        encoding="utf-8"
    )
    assert "financial_data.legacy_record" in sql
    assert "shared_identity_snapshot_id" in sql
    assert "CREATE TABLE IF NOT EXISTS financial_data.financial_security" not in sql
    assert "formal_business_data=false" in sql
    assert "S2" in sql  # only the state contract; no production transition function exists
    assert "transition_financial" not in sql
