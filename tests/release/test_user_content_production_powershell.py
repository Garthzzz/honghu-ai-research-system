from __future__ import annotations

from pathlib import Path

from tools.release.direct_candidate import ALLOWED_MODULES


ROOT = Path(__file__).resolve().parents[2]


def test_immutable_release_contains_governance_and_allowlists_production_entrypoint() -> None:
    import json

    policy = json.loads((ROOT / "config/deployment_policy.json").read_text(encoding="utf-8"))
    assert "AGENTS.md" in policy["include_exact"]
    assert ALLOWED_MODULES["tools.release.user_content_production"] == "main"


def test_start_contract_uses_exact_python_two_ports_tls_and_pid_binding() -> None:
    text = (ROOT / "tools/release/Start-UserContentProductionViewer.ps1").read_text(
        encoding="utf-8"
    )
    assert "sys.version.split()[0]" in text
    assert "^3\\.10\\.\\d+$" in text
    assert 'print(".".join' not in text
    assert "-I', '-B', '-S'" in text
    assert "LockedSitePackages" in text
    assert "direct_candidate.py" in text
    assert "tools.release.user_content_production" in text
    assert "release AGENTS contract" in text
    assert "HttpPort = 8080" in text and "HttpsPort = 8443" in text
    assert "https://localhost:$HttpsPort/api/health" in text
    assert "listener PID mismatch" in text
    assert "postgresql_production" in text
    assert "--launch-id" in text
    assert "production_process.launch_id" in text
    assert "Get-CimInstance Win32_Process" in text
    assert "process identity mismatch" in text
    assert "UTF8Encoding" in text
    assert "SharedIdentityRouteConfig" in text
    assert "--shared-identity-route" in text
    assert "health.shared_identity.backend" in text
    assert "Get-NetTCPConnection -LocalPort ([int]$listener.port)" in text
    assert "$process = $listenerProcess" in text
    assert "outer launcher PID" in text
    assert "AddSeconds(90)" in text
    assert 'api/health" -TimeoutSec 8' in text


def test_stop_contract_refuses_pid_reuse_and_unknown_listener() -> None:
    text = (ROOT / "tools/release/Stop-UserContentProductionViewer.ps1").read_text(
        encoding="utf-8"
    )
    assert "refusing to stop reused PID" in text
    assert "recorded PID does not own port" in text
    assert "did not release" in text
    assert "Get-CimInstance Win32_Process" in text
    assert "executable_sha256" in text and "command_line_sha256" in text
    assert "process identity mismatch" in text
