import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_recovery_maintenance_is_exact_release_least_privilege_and_five_minute():
    source = (ROOT / "tools" / "operations" / "Provision-Stage5RecoveryMaintenance.ps1").read_text(encoding="utf-8")
    assert "HonghuBackupRunner" in source
    assert "RunLevel>LeastPrivilege" in source
    assert "PT5M" in source
    assert "<Enabled>false</Enabled>" in source
    assert "Enable-ScheduledTask" in source
    assert "LastTaskResult -ne 0" in source
    assert source.count("LastRunTime -gt $before.LastRunTime") == 2
    assert source.count("-not $ran") >= 4
    assert "-PasswordNeverExpires $true" in source
    assert "-UserMayChangePassword $false" in source
    assert "ExpectedStorageIdentity" in source
    assert "AtRestEncryptionEvidence" in source
    assert "InitialRecoveryBoundary" in source
    assert "Password $plain" in source
    assert "secret_recorded=$false" in source


def test_recovery_service_account_description_respects_windows_limit():
    source = (
        ROOT / "tools" / "operations" / "Provision-Stage5RecoveryMaintenance.ps1"
    ).read_text(encoding="utf-8")
    descriptions = re.findall(r"-Description '([^']+)'", source)
    assert descriptions
    assert all(len(value) <= 48 for value in descriptions)


def test_recovery_wrapper_requires_encrypted_smb_and_never_carries_password_argument():
    source = (ROOT / "tools" / "operations" / "Invoke-Stage5-ContinuousRecovery.ps1").read_text(encoding="utf-8")
    assert "ProtectedData]::Unprotect" in source
    assert "Get-SmbConnection" in source
    assert "[bool]$smb.Encrypted" in source
    assert "stage5_recovery_cycle" in source
    assert "--at-rest-encryption-evidence" in source
    assert "--initial-recovery-boundary" in source
    assert "-Password" not in source


def test_backup_transfer_is_role_allowlisted_and_deletes_source():
    source = (ROOT / "tools" / "operations" / "backup_credential_transfer.py").read_text(encoding="utf-8")
    assert 'ROLE = "backup"' in source
    assert "CRYPTPROTECT_LOCAL_MACHINE" in source
    assert "source.unlink()" in source
    assert "build_catalog_connection_factory(catalog, role=ROLE)" in source
