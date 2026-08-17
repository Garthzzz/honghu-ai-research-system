from pathlib import Path

from tools.maintenance import build_stage5_evidence


def test_stage5_identity_file_set_exists_and_excludes_runtime_evidence():
    assert all((build_stage5_evidence.ROOT / item).is_file() for item in build_stage5_evidence.FILES)
    assert not any("runtime" in item and item.endswith(".json") for item in build_stage5_evidence.FILES)
    assert "tools/operations/task_credential_transfer.py" in build_stage5_evidence.FILES
    assert "tools/operations/task_enable_evidence.py" in build_stage5_evidence.FILES
    assert "tools/operations/task_service_preflight.py" in build_stage5_evidence.FILES
    assert "tools/operations/Collect-LocalDisabledTaskEvidence.ps1" in build_stage5_evidence.FILES
    assert "tools/operations/backup_credential_transfer.py" in build_stage5_evidence.FILES
    assert "tools/operations/stage5_recovery_cycle.py" in build_stage5_evidence.FILES
    assert "tools/operations/storage_identity_transition.py" in build_stage5_evidence.FILES
    assert "config/migration/stage5_storage_attestation_public.cer" in build_stage5_evidence.FILES
    assert "tools/operations/Collect-StorageIdentityTransitionEvidence.ps1" in build_stage5_evidence.FILES
    assert "tools/migration/stage4_recovery_set.py" in build_stage5_evidence.FILES
    assert "tools/operations/Provision-Stage5RecoveryMaintenance.ps1" in build_stage5_evidence.FILES
    assert "migrations/postgresql/0015_stage5_initial_overlay_revision.sql" in build_stage5_evidence.FILES
    assert "migrations/postgresql/0016_stage5_bounded_mutation_batch_result.sql" in build_stage5_evidence.FILES
    assert "migrations/postgresql/0017_stage5_set_based_sentiment_delete_batch.sql" in build_stage5_evidence.FILES
    assert "tools/operations/stage5_health.py" in build_stage5_evidence.FILES
    assert "tools/operations/stage5_sentiment_batch_rehearsal.py" in build_stage5_evidence.FILES
    assert not any(item.endswith((".json", ".dpapi")) and "credential" in item.casefold() for item in build_stage5_evidence.FILES)


def test_stage5_evidence_output_stays_in_ignored_cache():
    assert build_stage5_evidence.OUTPUT.is_relative_to(
        build_stage5_evidence.ROOT / "cache" / "git_bootstrap"
    )


def test_storage_transition_collector_requires_one_explicit_old_to_new_ipv4_move():
    collector = (
        build_stage5_evidence.ROOT
        / "tools/operations/Collect-StorageIdentityTransitionEvidence.ps1"
    ).read_text(encoding="utf-8")

    assert "[Parameter(Mandatory=$true)][string]$OldEndpointAddress" in collector
    assert "[Parameter(Mandatory=$true)][string]$NewEndpointAddress" in collector
    assert "[Net.IPAddress]::TryParse($OldEndpointAddress" in collector
    assert "[Net.IPAddress]::TryParse($NewEndpointAddress" in collector
    assert "AddressFamily]::InterNetwork" in collector
    assert "if ($OldEndpointAddress -eq $NewEndpointAddress)" in collector
    assert "$OldEndpointAddress = '" not in collector
    assert "$NewEndpointAddress = '" not in collector
