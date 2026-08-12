from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from tools.migration.stage4_production_bootstrap_contract import (
    BootstrapContractError,
    load_and_validate_config,
    validate_inputs,
)
from tools.migration.stage4_production_recovery import _required_wal_names


ROOT = Path(__file__).resolve().parents[2]


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    archive = tmp_path / "postgresql.zip"
    archive.write_bytes(b"approved archive fixture")
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    config = json.loads(
        (ROOT / "config/migration/stage4_production_postgresql_bootstrap.template.json").read_text(
            encoding="utf-8"
        )
    )
    config["postgresql"]["archive_sha256"] = archive_sha
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    repo = tmp_path / "repo"
    route = repo / "config/migration/user_content_backend_route.json"
    route.parent.mkdir(parents=True)
    route.write_text(
        json.dumps(
            {
                "cutover_unit": "user_content_notes",
                "authority_state": "S0",
                "backend": "sqlite_transition",
                "sqlite_writer_enabled": True,
                "production_postgresql_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    return config_path, archive, repo


def test_bootstrap_contract_binds_archive_route_and_commit(tmp_path: Path) -> None:
    config, archive, repo = _fixture(tmp_path)
    result = validate_inputs(
        config_path=config,
        repo_root=repo,
        commit_sha="a" * 40,
        archive_path=archive,
    )
    assert result["authority_state"] == "S0"
    assert result["authoritative_backend"] == "sqlite_transition"
    assert len(result["input_identity_sha256"]) == 64


def test_bootstrap_contract_rejects_route_escalation(tmp_path: Path) -> None:
    config, archive, repo = _fixture(tmp_path)
    route = repo / "config/migration/user_content_backend_route.json"
    payload = json.loads(route.read_text(encoding="utf-8"))
    payload.update(authority_state="S2", backend="postgresql_production")
    route.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BootstrapContractError, match="outside S0/S1"):
        validate_inputs(
            config_path=config,
            repo_root=repo,
            commit_sha="a" * 40,
            archive_path=archive,
        )


def test_bootstrap_contract_rejects_broader_network(tmp_path: Path) -> None:
    config, _, _ = _fixture(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["postgresql"]["host"] = "0.0.0.0"
    config.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BootstrapContractError, match="loopback-only"):
        load_and_validate_config(config)


def test_bootstrap_contract_rejects_archive_tamper(tmp_path: Path) -> None:
    config, archive, repo = _fixture(tmp_path)
    archive.write_bytes(b"tampered")
    with pytest.raises(BootstrapContractError, match="archive hash mismatch"):
        validate_inputs(
            config_path=config,
            repo_root=repo,
            commit_sha="a" * 40,
            archive_path=archive,
        )


def test_bootstrap_script_is_single_entry_and_preserves_authority() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "production_authority_changed = $false" in source
    assert "s2_or_s3_entered = $false" in source
    assert "user_content_backend_route.json" in source
    assert "stage4_production_recovery" in source
    assert "Stop-Process -Id $crashPid -Force" in source
    assert "PostgreSQLArchive" in source
    assert "DownloadFile" not in source
    assert "Invoke-WebRequest" not in source
    assert "stage4_prepare_units" in source
    assert "stage4_isolated_entry.py" in source


def test_bootstrap_keeps_quant_pristine_and_uses_hash_pinned_isolated_python() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "$BootstrapBasePythonExe = $BootstrapPythonExe" in source
    assert "-m venv $PythonEnv" in source
    assert "--require-hashes --requirement" in source
    assert "tools\\release\\runtime_environment.py" in source
    assert "python_runtime_executable" in source
    assert "Completed-install isolated Python runtime verification failed." in source


def test_bootstrap_does_not_require_postgresql_archive_openssl() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    archive_requirements = source.split(
        "foreach ($name in ", 1
    )[1].split(") {", 1)[0]
    assert "openssl.exe" not in archive_requirements
    assert "stage4_tls_certificate.py" in source
    assert "tls_certificate.json" in source
    assert "private_key_recorded = $false" in source
    assert "tls_private_key_acl" in source
    assert "/inheritance:r /grant:r" in source
    assert "'*S-1-5-20:R'" in source


def test_bootstrap_secret_rng_is_windows_powershell_compatible() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "RandomNumberGenerator]::Fill" not in source
    assert "RandomNumberGenerator]::Create()" in source
    assert "$rng.GetBytes($bytes)" in source
    assert "$rng.Dispose()" in source

    # Exercise the exact .NET instance API under the same Windows PowerShell
    # host family used by the production-readiness VM.  The generated value is
    # deliberately not emitted by the command or the test report.
    command = (
        "$bytes=New-Object byte[] 32;"
        "$rng=[System.Security.Cryptography.RandomNumberGenerator]::Create();"
        "try{$rng.GetBytes($bytes)}finally{$rng.Dispose()};"
        "if($bytes.Length -ne 32){exit 2};"
        "if(($bytes | Where-Object {$_ -ne 0}).Count -eq 0){exit 3}"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_preinstall_failure_uses_owned_quarantine_contract() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "$StagingRoot = $null" in source
    assert "stage4_preinstall_quarantine.py" in source
    assert "Pre-install staging cannot be quarantined while the service exists." in source
    assert "Pre-install staging cannot be quarantined while port 55440 is listening." in source
    assert "preinstall_staging_recovery = $preInstallRecovery" in source


def test_fresh_bootstrap_does_not_pollute_install_root_before_identity() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "honghu-stage4-preflight-{0}" in source
    assert "$FinalInstallEvidenceRoot = Join-Path $RuntimeRoot 'evidence'" in source
    identity_write = source.index(
        "Write-HonghuJsonAtomic -Path $InstallIdentityPath -Value $InstallIdentity"
    )
    evidence_promotion = source.index(
        "$FinalInstallEvidenceRoot = Join-Path $RuntimeRoot 'evidence'"
    )
    assert identity_write < evidence_promotion


def test_required_wal_range_is_complete_and_bounded() -> None:
    assert _required_wal_names(
        "000000010000000000000001", "000000010000000000000003"
    ) == [
        "000000010000000000000001",
        "000000010000000000000002",
        "000000010000000000000003",
    ]
    with pytest.raises(Exception, match="timeline"):
        _required_wal_names(
            "000000010000000000000001", "000000020000000000000001"
        )


def test_required_wal_range_handles_postgresql_log_segment_rollover() -> None:
    assert _required_wal_names(
        "0000000100000000000000FF",
        "000000010000000100000001",
        16 * 1024 * 1024,
    ) == [
        "0000000100000000000000FF",
        "000000010000000100000000",
        "000000010000000100000001",
    ]
    with pytest.raises(Exception, match="cluster geometry"):
        _required_wal_names(
            "000000010000000000000100",
            "000000010000000100000000",
            16 * 1024 * 1024,
        )
