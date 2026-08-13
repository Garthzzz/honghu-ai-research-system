from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_start_contract_uses_exact_python_two_ports_tls_and_pid_binding() -> None:
    text = (ROOT / "tools/release/Start-UserContentProductionViewer.ps1").read_text(
        encoding="utf-8"
    )
    assert "StartsWith('3.10.')" in text
    assert "-I', '-B'" in text
    assert "HttpPort = 8080" in text and "HttpsPort = 8443" in text
    assert "https://localhost:$HttpsPort/api/health" in text
    assert "listener PID mismatch" in text
    assert "postgresql_production" in text


def test_stop_contract_refuses_pid_reuse_and_unknown_listener() -> None:
    text = (ROOT / "tools/release/Stop-UserContentProductionViewer.ps1").read_text(
        encoding="utf-8"
    )
    assert "refusing to stop reused PID" in text
    assert "recorded PID does not own port" in text
    assert "did not release" in text
