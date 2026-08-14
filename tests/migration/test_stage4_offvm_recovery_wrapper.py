from __future__ import annotations

from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "migration"
    / "Invoke-Stage4-OffVmRecovery.ps1"
)


def test_offvm_wrapper_keeps_secrets_out_of_process_arguments() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "ProtectedData]::Unprotect" in text
    assert "CredentialBlobPath" in text
    assert "--off-vm-root" in text
    assert "--expected-off-vm-storage-identity" not in text
    assert "net use" not in text.casefold()
    assert "PGPASSWORD" not in text
    assert "secret_recorded = $false" in text


def test_offvm_wrapper_requires_encrypted_smb_and_isolated_entry() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Get-SmbConnection" in text
    assert "-not [bool]$smb.Encrypted" in text
    assert "stage4_isolated_entry.py" in text
    assert "tools.migration.stage4_production_recovery" in text
    assert "production_recovery.stderr.log" in text
    assert "Remove-PSDrive H4Recovery" in text


def test_offvm_wrapper_forwards_every_required_authority_unit() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "[string[]]$RequiredAuthorityUnit" in text
    assert "@('--required-authority-unit', $unit)" in text
    assert "@authorityArgs" in text
    assert "required_authority_units =" in text
    assert "At least one required authority unit is required." in text
