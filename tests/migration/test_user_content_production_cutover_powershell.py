from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_cutover_orders_all_hard_gates_before_s2_and_s3() -> None:
    script = (
        ROOT / "tools" / "migration" / "Invoke-UserContentProductionCutover.ps1"
    ).read_text(encoding="utf-8")
    recovery_guard = script.index("recovery.status -ne 'pass'")
    s1_guard = script.index("s1Evidence.state -ne 'S1'")
    fence = script.index("Invoke-UserContentWriterFence.ps1")
    approval = script.index("stage4_user_content_approval")
    s2 = script.index("'enter-s2'")
    first = script.index("'first-mutation'")
    s3 = script.index("'reconcile-s3'")
    assert recovery_guard < fence
    assert s1_guard < fence
    assert fence < approval < s2 < first < s3
    assert script.count("Start-UserContentProductionViewer.ps1") == 2
    assert "Stop-UserContentProductionViewer.ps1" in script
    assert "authority_state = 'S3'" in script
    assert "authoritative_backend = 'postgresql_production'" in script
    assert "sqlite_writer_fenced = $true" in script


def test_cutover_does_not_modify_sqlite_or_scheduled_tasks() -> None:
    script = (
        ROOT / "tools" / "migration" / "Invoke-UserContentProductionCutover.ps1"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "sqlite3.connect",
        "INSERT INTO analyst_note",
        "UPDATE analyst_note",
        "Register-ScheduledTask",
        "Set-ScheduledTask",
        "Disable-ScheduledTask",
        "Enable-ScheduledTask",
        "Stop-Service",
    ):
        assert forbidden not in script
