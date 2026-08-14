from __future__ import annotations

from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "migration"
    / "Invoke-RemainingUnitsS1Prepare.ps1"
)


def test_remaining_s1_runner_keeps_authority_on_sqlite_and_orders_dependencies() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "shared_identity is not durable PostgreSQL S3" in text
    assert text.index("'financial_data'") < text.index("'research_publication'")
    assert text.index("'research_publication'") < text.index("'dynamic_intelligence'")
    assert text.index("'dynamic_intelligence'") < text.index("'operations_governance'")
    assert "tools.migration.stage4_prepare_units" in text
    assert "tools.migration.stage4_financial_data_s1" in text
    assert "tools.migration.stage4_generic_unit_s1" in text
    assert "authoritative_backend -ne 'sqlite_transition'" in text
    assert "s2_s3_entered = $false" in text


def test_remaining_s1_runner_has_no_production_transition_or_task_mutation() -> None:
    text = SCRIPT.read_text(encoding="utf-8").casefold()
    assert "transition_cutover_unit" not in text
    assert "start-scheduledtask" not in text
    assert "stop-scheduledtask" not in text
    assert "set-scheduledtask" not in text
    assert "unregister-scheduledtask" not in text
