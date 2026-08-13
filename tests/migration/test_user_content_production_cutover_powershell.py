from pathlib import Path

from tools.migration.stage4_isolated_entry import ALLOWED_MODULES


ROOT = Path(__file__).resolve().parents[2]


def test_cutover_orders_all_hard_gates_before_s2_and_s3() -> None:
    script = (
        ROOT / "tools" / "migration" / "Invoke-UserContentProductionCutover.ps1"
    ).read_text(encoding="utf-8")
    recovery_guard = script.index("recovery.status -ne 'pass'")
    s1_guard = script.index("s1Evidence.state -ne 'S1'")
    security_guard = script.index("securityEvidence.status -ne 'pass'")
    release_verify = script.index("'verify','--release-dir'")
    fence = script.index("Invoke-UserContentWriterFence.ps1")
    approval = script.index("stage4_user_content_approval")
    s2 = script.index("'enter-s2'")
    first = script.index("'first-mutation'")
    s3 = script.index("'reconcile-s3'")
    assert recovery_guard < fence
    assert s1_guard < fence
    assert security_guard < fence
    assert release_verify < fence
    assert fence < approval < s2 < first < s3
    assert script.count("Start-UserContentProductionViewer.ps1") == 2
    assert "Stop-UserContentProductionViewer.ps1" in script
    assert "authority_state = 'S3'" in script
    assert "authoritative_backend = 'postgresql_production'" in script
    assert "sqlite_writer_fenced = $true" in script
    assert "security_provision.json" in script
    assert "security provision evidence does not authorize production authentication" in script
    assert "(Join-Path $StateRoot 'user-content-tls') $CommitSha" in script
    assert "-PythonExe $PythonExe -RepoRoot $RepoRoot -ReleaseDir $Release" in script


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


def test_every_isolated_module_used_by_cutover_is_allowlisted() -> None:
    script = (
        ROOT / "tools" / "migration" / "Invoke-UserContentProductionCutover.ps1"
    ).read_text(encoding="utf-8")
    import re

    invoked = set(re.findall(r"Invoke-Isolated\s+'([^']+)'", script))
    assert invoked
    assert invoked <= set(ALLOWED_MODULES)
