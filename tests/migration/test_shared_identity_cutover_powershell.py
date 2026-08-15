from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_shared_identity_prepare_is_s1_only_and_exact_release_bound() -> None:
    text = (ROOT / "tools/migration/Invoke-SharedIdentityCutoverPrepare.ps1").read_text(
        encoding="utf-8"
    )
    assert "stage4_apply_postgresql_migrations" in text
    assert "stage4_shared_identity_s1" in text
    assert "writer_shared_identity" in text
    assert "ApprovedMappingPath" in text
    assert "SourceDataRoot" in text
    assert "stage4_identity_mapping_equivalence" in text
    assert "identity_mapping_candidate.json" in text
    assert "source_snapshot.snapshot_identity_sha256" in text
    assert "fallback_requires_human -ne 0" in text
    assert "authority_transition_performed = $false" in text
    assert "live_sqlite_modified = $false" in text
    assert "Get-Content -Raw -LiteralPath" not in text
    assert "Get-Content -Raw -Encoding UTF8" in text


def test_shared_identity_cutover_stops_viewer_rechecks_source_and_never_falls_back() -> None:
    text = (ROOT / "tools/migration/Invoke-SharedIdentityProductionCutover.ps1").read_text(
        encoding="utf-8"
    )
    assert "Stop-UserContentProductionViewer.ps1" in text
    assert "--manifest-only" in text
    assert "stage4_shared_identity_cutover" in text
    assert "SharedIdentityRouteConfig" in text
    assert "production_tasks_modified = $false" in text
    assert "Never revive a stale SQLite identity writer" in text
    assert "$authorityTransitionInvoked = $false" in text
    assert "$authorityTransitionInvoked = $true" in text
    assert "Start-PriorUserContentViewer" in text
    assert "tools.migration.stage4_authority_control" in text
    assert "--role','migration'" in text
    assert "D:\\honghu-postgresql\\python-env\\Scripts\\python.exe" in text
    assert "$failureAuthorityValue.authority.state -eq 'S1'" in text
    assert "Durable authority is proven still S1" in text
    assert "shared_identity S1 abandon failed to restore prior Viewer" in text
    assert "[Parameter(Mandatory = $true)][string]$SourceDataRoot" in text
    assert "Get-Content -Raw -LiteralPath" not in text
    assert "Get-Content -Raw -Encoding UTF8" in text
