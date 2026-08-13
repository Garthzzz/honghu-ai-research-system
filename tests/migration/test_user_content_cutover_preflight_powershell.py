from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_preflight_is_read_only_and_fail_closed() -> None:
    script = (
        ROOT / "tools" / "migration" / "Invoke-UserContentCutoverPreflight.ps1"
    ).read_text(encoding="utf-8")
    required = (
        "git -C $RepoRoot rev-parse HEAD",
        "status --porcelain --untracked-files=no",
        "sys.version.split()[0]",
        "^3\\.10\\.\\d+$",
        "HonghuPostgreSQL17",
        "Get-NetTCPConnection -LocalPort 55440",
        "http://127.0.0.1:8080/api/health",
        "mode=ro",
        "sqlite_transition",
        "authority_changed = $false",
        "live_sqlite_modified = $false",
    )
    for fragment in required:
        assert fragment in script
    forbidden = (
        "Stop-Process",
        "Stop-Service",
        "Set-Content",
        "Invoke-Sqlcmd",
        "sqlite3.connect(r'file:$($research.Replace('\\','/'))')",
    )
    for fragment in forbidden:
        assert fragment not in script
    assert 'print(".".join' not in script
