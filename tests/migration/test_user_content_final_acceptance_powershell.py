from pathlib import Path

from tools.migration.stage4_isolated_entry import ALLOWED_MODULES


ROOT = Path(__file__).resolve().parents[2]


def test_final_acceptance_runs_cutover_then_bounded_stress() -> None:
    script = (
        ROOT / "tools" / "migration" / "Invoke-UserContentFinalAcceptance.ps1"
    ).read_text(encoding="utf-8")
    cutover = script.index("Invoke-UserContentProductionCutover.ps1")
    stress = script.index("'stress','--base-url'")
    health = script.index("final local health is not durable S3")
    assert cutover < stress < health
    assert "'--concurrency','12','--mutation-count','64'" in script
    assert "independent_lan_and_browser_acceptance" in script
    assert ALLOWED_MODULES["tools.migration.stage4_user_content_acceptance"] == "main"


def test_final_acceptance_never_touches_sqlite_or_tasks() -> None:
    script = (
        ROOT / "tools" / "migration" / "Invoke-UserContentFinalAcceptance.ps1"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "sqlite3.connect",
        "Register-ScheduledTask",
        "Set-ScheduledTask",
        "Disable-ScheduledTask",
        "Enable-ScheduledTask",
        "Stop-Service",
    ):
        assert forbidden not in script
