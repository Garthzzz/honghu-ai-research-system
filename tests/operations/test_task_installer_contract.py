import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_installer_is_exact_release_disabled_first_and_noninteractive():
    text = (ROOT / "tools/operations/Install-ProductionTasks.ps1").read_text(encoding="utf-8")
    assert "InstallDisabled" in text
    assert "LogonType>Password" in text
    assert "RunLevel>LeastPrivilege" in text
    assert "direct_candidate.py" in text
    assert "--site-packages" in text
    assert "tools.operations.task_runner" in text
    assert "'--'," in text
    assert "Disable-ScheduledTask" in text
    assert "LocalDisabledEvidence" in text
    assert "TrialEvidence" in text
    assert "tools.operations.task_enable_evidence" in text
    assert "collector-script" in text
    assert "Interactive" not in text
    assert "sqlite_transition" not in text
    assert "research.db" not in text
    assert "sentiment.db" not in text
    verifier = (ROOT / "tools/operations/task_enable_evidence.py").read_text(
        encoding="utf-8"
    )
    assert "business_checkpoint_after_sha256" in verifier
    assert "local_disabled_evidence_max_age_seconds" in verifier
    assert "legacy_runner_process_count" in verifier


def test_service_account_provisioning_keeps_secrets_out_of_arguments_and_evidence():
    text = (ROOT / "tools/operations/Provision-ProductionTaskRunner.ps1").read_text(encoding="utf-8")
    assert "HonghuTaskRunner" in text
    assert "local_administrator=$false" in text
    assert "task_credential_transfer" in text
    assert "DPAPI LocalMachine" in text
    assert "encrypted_transfer_removed=$true" in text
    assert "secret_recorded=$false" in text
    assert "tools.operations.task_service_preflight" in text
    assert "'--locked-site-packages',$SitePackages" in text
    assert "service_account_preflight_verified=$true" in text
    assert "postgresql_roles_verified" in text
    assert "Password =" not in text
    assert "'/remove:d'" in text
    assert "'/deny'" in text
    assert "(OI)(CI)(WD,AD)" in text
    assert "Read-only task ACL failed" in text


def test_service_account_description_respects_windows_48_character_limit():
    text = (ROOT / "tools/operations/Provision-ProductionTaskRunner.ps1").read_text(
        encoding="utf-8"
    )
    descriptions = re.findall(r"-Description '([^']+)'", text)
    assert descriptions
    assert all(len(value) <= 48 for value in descriptions)


def test_provisioner_uses_real_isolated_migration_cli_contract():
    text = (ROOT / "tools/operations/Provision-ProductionTaskRunner.ps1").read_text(
        encoding="utf-8"
    )
    assert "--module tools.migration.stage4_apply_postgresql_migrations" in text
    assert "-I -B -S $bootstrap --site-packages $SitePackages" in text
    assert "--repo-root $ReleaseDir --runtime $RuntimeCatalog" in text
    assert "--migration '0013_stage5_task_operations.sql'" in text
    assert "--migration '0014_stage5_delegated_unit_writers.sql'" in text
    assert "--migration '0015_stage5_initial_overlay_revision.sql'" in text
    assert "--migration '0016_stage5_bounded_mutation_batch_result.sql'" in text
    assert "--migration '0017_stage5_set_based_sentiment_delete_batch.sql'" in text
    assert "--output $migrationEvidence" in text
    assert "--migrations-dir" not in text
    assert "--evidence $migrationEvidence" not in text


def test_credential_transfer_is_role_allowlisted_and_deletes_transfer():
    text = (ROOT / "tools/operations/task_credential_transfer.py").read_text(encoding="utf-8")
    assert "TASK_ROLES" in text
    assert "writer_operations_governance" in text
    assert "writer_dynamic_intelligence" in text
    assert "writer_sentiment_analytics" in text
    assert "CRYPTPROTECT_LOCAL_MACHINE" in text
    assert "source.unlink()" in text
    provisioner = (ROOT / "tools/operations/Provision-ProductionTaskRunner.ps1").read_text(
        encoding="utf-8"
    )
    assert "$LocalUser`:(M)" in provisioner


def test_local_disabled_evidence_reads_scheduler_without_mutating_tasks():
    text = (ROOT / "tools/operations/Collect-LocalDisabledTaskEvidence.ps1").read_text(
        encoding="utf-8"
    )
    assert "Get-ScheduledTask" in text
    assert "Export-ScheduledTask" in text
    assert "definition_sha256" in text
    assert "legacy_runner_process_count" in text
    assert "source_host_identity_sha256" in text
    assert "checked_at" in text
    assert "collector_sha256" in text
    assert "MachineGuid" in text
    assert "machine_guid_recorded=$false" in text
    assert "Enable-ScheduledTask" not in text
    assert "Disable-ScheduledTask" not in text
    assert "Register-ScheduledTask" not in text
