from pathlib import Path

from tools.maintenance import build_stage5_evidence


def test_stage5_identity_file_set_exists_and_excludes_runtime_evidence():
    assert all((build_stage5_evidence.ROOT / item).is_file() for item in build_stage5_evidence.FILES)
    assert not any("runtime" in item and item.endswith(".json") for item in build_stage5_evidence.FILES)
    assert "tools/operations/task_credential_transfer.py" in build_stage5_evidence.FILES
    assert not any(item.endswith((".json", ".dpapi")) and "credential" in item.casefold() for item in build_stage5_evidence.FILES)


def test_stage5_evidence_output_stays_in_ignored_cache():
    assert build_stage5_evidence.OUTPUT.is_relative_to(
        build_stage5_evidence.ROOT / "cache" / "git_bootstrap"
    )
