[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$CommitSha,
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$RecoveryEvidence,
    [Parameter(Mandatory = $true)][string]$SourceDataRoot,
    [string]$ProductionRoot = 'C:\industry_demo',
    [string]$InstallRoot = 'D:\honghu-postgresql',
    [string]$ReleaseRoot = 'D:\honghu-user-content-production',
    [string]$PythonExe = 'C:\ProgramData\miniconda3\envs\quant\python.exe'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Isolated([string]$Module, [string[]]$Arguments) {
    & $PythonExe -I -B (Join-Path $RepoRoot 'tools\migration\stage4_isolated_entry.py') `
        --repo-root $RepoRoot --module $Module -- @Arguments
    if ($LASTEXITCODE -ne 0) { throw "isolated module failed: $Module" }
}

$RuntimeRoot = Join-Path $InstallRoot 'runtime'
$EvidenceRoot = Join-Path $RuntimeRoot 'evidence\shared-identity-final'
$UserEvidenceRoot = Join-Path $RuntimeRoot 'evidence\user-content-final'
$SnapshotRoot = Join-Path $EvidenceRoot 'unit-snapshot'
$S1 = Join-Path $EvidenceRoot 'shared_identity_s1.json'
$Runtime = Join-Path $EvidenceRoot 'postgresql_runtime_release_bound.json'
$SharedRuntime = Join-Path $EvidenceRoot 'postgresql_shared_identity_runtime.json'
$Mapping = Join-Path $EvidenceRoot 'identity_mapping.json'
$Decision = Join-Path $RepoRoot 'config\migration\stage4_remaining_cutover_decision.json'
$Intent = Join-Path $EvidenceRoot 'shared_identity_cutover_intent.json'
$Route = Join-Path $EvidenceRoot 'shared_identity_runtime_route.json'
$S3 = Join-Path $EvidenceRoot 'shared_identity_s3.json'
$FailureAuthority = Join-Path $EvidenceRoot 'shared_identity_failure_authority.json'
$FinalSnapshotRoot = Join-Path $EvidenceRoot 'final-source-check'
$Release = Join-Path (Join-Path $ReleaseRoot 'releases') $CommitSha
$UserRoute = Join-Path $UserEvidenceRoot 'user_content_runtime_route.json'
$UserRuntime = Join-Path $UserEvidenceRoot 'postgresql_viewer_runtime.json'
$UserMapping = Join-Path $UserEvidenceRoot 'identity_mapping.json'
$Security = Join-Path $RepoRoot 'config\migration\user_content_security_production.json'
$TlsRoot = Join-Path (Join-Path $RuntimeRoot 'user-content-tls') $CommitSha
if (-not (Test-Path -LiteralPath (Join-Path $TlsRoot 'server.crt'))) {
    # The certificate from the already-approved user-content release remains
    # the transport authority; a release-specific copy is not invented here.
    $priorTls = Get-ChildItem (Join-Path $RuntimeRoot 'user-content-tls') -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName 'server.crt') } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $priorTls) { throw 'approved production TLS material is absent' }
    $TlsRoot = $priorTls.FullName
}
foreach ($path in @($S1,$Runtime,$SharedRuntime,$Mapping,$Decision,$RecoveryEvidence,$UserRoute,$UserRuntime,$UserMapping,$Security,(Join-Path $Release 'RELEASE_MANIFEST.json'),(Join-Path $TlsRoot 'server.crt'),(Join-Path $TlsRoot 'server.key'))) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "cutover input missing: $path" }
}

# Capture the exact currently serving release before the maintenance fence.  A
# failure before the authority controller is invoked is still an S1 abandon,
# so the already-approved user-content release may be restored.  Once the
# controller is invoked the response may be uncertain and recovery is
# forward-only; the old release must not be revived blindly.
$priorHealth = Invoke-RestMethod 'http://127.0.0.1:8080/api/health' -TimeoutSec 15
if (-not [bool]$priorHealth.ok -or $priorHealth.user_content.authority_state -ne 'S3' -or
    $priorHealth.user_content.backend -ne 'postgresql_production') {
    throw 'existing production Viewer is not the approved user-content S3 authority'
}
$PriorCommit = [string]$priorHealth.release.commit_sha
$PriorRelease = Join-Path (Join-Path $ReleaseRoot 'releases') $PriorCommit
if ($PriorCommit -notmatch '^[0-9a-f]{40}$' -or
    -not (Test-Path -LiteralPath (Join-Path $PriorRelease 'RELEASE_MANIFEST.json') -PathType Leaf)) {
    throw 'existing production Viewer release identity is not recoverable'
}

function Start-PriorUserContentViewer {
    & (Join-Path $RepoRoot 'tools\release\Start-UserContentProductionViewer.ps1') `
        -PythonExe $PythonExe -LockedSitePackages (Join-Path $InstallRoot 'python-env\Lib\site-packages') `
        -ReleaseDir $PriorRelease -ExpectedCommit $PriorCommit `
        -DataRoot (Join-Path $ProductionRoot 'data') -ContentRoot $ProductionRoot `
        -StateRoot $RuntimeRoot -RouteConfig $UserRoute -PostgresConfig $UserRuntime `
        -IdentityMapping $UserMapping -SecurityConfig $Security `
        -TlsCertificate (Join-Path $TlsRoot 'server.crt') `
        -TlsPrivateKey (Join-Path $TlsRoot 'server.key') -HttpPort 8080 -HttpsPort 8443 | Out-Null
}
$s1Value = Get-Content -Raw -Encoding UTF8 -LiteralPath $S1 | ConvertFrom-Json
$recoveryValue = Get-Content -Raw -Encoding UTF8 -LiteralPath $RecoveryEvidence | ConvertFrom-Json
if ($s1Value.application_commit_sha -ne $CommitSha -or $recoveryValue.application_commit_sha -ne $CommitSha -or
    $recoveryValue.status -ne 'pass' -or -not [bool]$recoveryValue.off_vm_verified -or
    $recoveryValue.authority_snapshots.shared_identity.state -ne 'S1') {
    throw 'exact-commit S1/off-VM recovery evidence does not authorize shared_identity cutover'
}

$viewerStopped = $false
$authorityTransitionInvoked = $false
try {
    # Stop only the reviewed production Viewer lifecycle.  Production tasks are
    # neither modified nor migrated.  With 8080 stopped, rebuild a read-only
    # final source identity and require it to equal the S1 watermark before
    # authority can leave SQLite.
    & (Join-Path $RepoRoot 'tools\release\Stop-UserContentProductionViewer.ps1') `
        -StateRoot $RuntimeRoot | Out-Null
    $viewerStopped = $true
    if (@(Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) {
        throw 'production Viewer 8080 did not stop for shared_identity writer fence'
    }
    New-Item -ItemType Directory -Force -Path $FinalSnapshotRoot | Out-Null
    Invoke-Isolated 'tools.migration.stage4_unit_s1' @(
        'build','--unit','shared_identity','--source-data-root',$SourceDataRoot,
        '--registry',(Join-Path $RepoRoot 'config\migration\cutover_unit_registry.json'),
        '--application-commit-sha',$CommitSha,'--output-dir',$FinalSnapshotRoot,'--manifest-only'
    )
    $finalManifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $FinalSnapshotRoot 'shared_identity.snapshot.json') | ConvertFrom-Json
    if ([string]$finalManifest.source_identity_sha256 -ne [string]$s1Value.source_identity_sha256 -or
        [int64]$finalManifest.reconciliation.source_row_count -ne [int64]$s1Value.source_row_count -or
        [string]$finalManifest.reconciliation.source_content_sha256 -ne [string]$s1Value.source_content_sha256) {
        throw 'shared_identity source drifted after S1; SQLite remains authoritative and cutover is aborted'
    }

    $authorityTransitionInvoked = $true
    Invoke-Isolated 'tools.migration.stage4_shared_identity_cutover' @(
        '--runtime',$Runtime,'--mapping',$Mapping,'--decision',$Decision,
        '--s1-evidence',$S1,'--recovery-evidence',$RecoveryEvidence,
        '--data-root',(Join-Path $ProductionRoot 'data'),
        '--writer-identity','honghu_writer_shared_identity','--actor','principal:codex',
        '--intent',$Intent,'--route-output',$Route,'--output',$S3
    )
    & (Join-Path $RepoRoot 'tools\release\Start-UserContentProductionViewer.ps1') `
        -PythonExe $PythonExe -LockedSitePackages (Join-Path $InstallRoot 'python-env\Lib\site-packages') `
        -ReleaseDir $Release -ExpectedCommit $CommitSha `
        -DataRoot (Join-Path $ProductionRoot 'data') -ContentRoot $ProductionRoot `
        -StateRoot $RuntimeRoot -RouteConfig $UserRoute -PostgresConfig $UserRuntime `
        -IdentityMapping $UserMapping -SecurityConfig $Security `
        -SharedIdentityRouteConfig $Route -SharedIdentityPostgresConfig $SharedRuntime `
        -TlsCertificate (Join-Path $TlsRoot 'server.crt') `
        -TlsPrivateKey (Join-Path $TlsRoot 'server.key') -HttpPort 8080 -HttpsPort 8443 | Out-Null
    $health = Invoke-RestMethod 'http://127.0.0.1:8080/api/health' -TimeoutSec 15
    if (-not [bool]$health.ok -or $health.user_content.authority_state -ne 'S3' -or
        $health.shared_identity.authority_state -ne 'S3' -or
        $health.shared_identity.backend -ne 'postgresql_production') {
        throw 'production Viewer did not load both durable S3 authorities'
    }
    [ordered]@{
        schema_version = 'honghu.shared_identity_production_cutover.v1'
        status = 'pass'
        completed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        application_commit_sha = $CommitSha
        authority_state = 'S3'
        authoritative_backend = 'postgresql_production'
        s1_evidence = $S1
        recovery_evidence = $RecoveryEvidence
        s3_evidence = $S3
        sqlite_writer_fenced = $true
        user_content_authority_unchanged = $true
        production_tasks_modified = $false
    } | ConvertTo-Json -Depth 12
} catch {
    $primaryFailure = $_
    $safeS1Abandon = -not $authorityTransitionInvoked
    if ($viewerStopped -and $authorityTransitionInvoked) {
        # The controller call may have failed before or after commit.  Only a
        # newly observed durable S1 row permits the prior exact release to
        # return.  An unavailable probe or S2/S3 state remains fail-closed and
        # requires forward repair.
        try {
            Invoke-Isolated 'tools.migration.stage4_authority_control' @(
                '--runtime',$Runtime,'--unit','shared_identity','--allow-s2','--output',$FailureAuthority
            )
            $failureAuthorityValue = Get-Content -Raw -Encoding UTF8 -LiteralPath $FailureAuthority | ConvertFrom-Json
            $safeS1Abandon = $failureAuthorityValue.authority.state -eq 'S1'
        } catch { $safeS1Abandon = $false }
    }
    if ($viewerStopped -and $safeS1Abandon -and
        @(Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue).Count -eq 0) {
        # Durable authority is proven still S1, so this remains an S1 abandon.
        # Restore only the captured exact user-content release; this is not a
        # SQLite fallback and does not alter shared_identity authority.
        try { Start-PriorUserContentViewer } catch {
            throw "shared_identity S1 abandon failed to restore prior Viewer; primary=$($primaryFailure.Exception.Message); recovery=$($_.Exception.Message)"
        }
    }
    # Never revive a stale SQLite identity writer after an uncertain authority
    # commit.  The durable authority ledger and intent remain available for a
    # same-identity reconciliation run.
    throw $primaryFailure
}
