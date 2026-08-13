from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_prepare_stays_in_s1_and_uses_isolated_modules() -> None:
    script = (
        ROOT / "tools" / "migration" / "Invoke-UserContentCutoverPrepare.ps1"
    ).read_text(encoding="utf-8")
    for fragment in (
        "Invoke-UserContentCutoverPreflight.ps1",
        "stage4_isolated_entry.py",
        "stage4_runtime_release_binding",
        "stage4_user_content_runtime",
        "stage4_identity_mapping",
        "stage4_user_content_approval",
        "stage4_prepare_units",
        "stage4_user_content_s1",
        "staging_reconciled_s0_s1_preparation",
        "authority_state = 'S1'",
        "authoritative_backend = 'sqlite_transition'",
        "production_viewer_modified = $false",
        "live_sqlite_modified = $false",
    ):
        assert fragment in script
    for forbidden in (
        "enter-s2",
        "reconcile-s3",
        "Stop-Process",
        "Stop-Service",
        "Start-UserContentProductionViewer",
    ):
        assert forbidden not in script
