[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$CommitSha,
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$RecoveryEvidence,
    [string]$SecurityProvisionEvidence = '',
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

$StateRoot = Join-Path $InstallRoot 'runtime'
$EvidenceRoot = Join-Path $StateRoot 'evidence\user-content-final'
$Mapping = Join-Path $EvidenceRoot 'identity_mapping.json'
$MappingApproval = Join-Path $EvidenceRoot 'mapping_approval.json'
$S1 = Join-Path $EvidenceRoot 'user_content_s1.json'
$Runtime = Join-Path $EvidenceRoot 'postgresql_runtime_release_bound.json'
$ViewerRuntime = Join-Path $EvidenceRoot 'postgresql_viewer_runtime.json'
$Security = Join-Path $RepoRoot 'config\migration\user_content_security_production.json'
$Decision = Join-Path $RepoRoot 'config\migration\stage4_user_content_cutover_decision.json'
$Release = Join-Path (Join-Path $ReleaseRoot 'releases') $CommitSha
$Route = Join-Path $EvidenceRoot 'user_content_runtime_route.json'
$Fence = Join-Path $EvidenceRoot 'writer_fence.json'
$Approval = Join-Path $EvidenceRoot 'cutover_approval.json'
$S2 = Join-Path $EvidenceRoot 'user_content_s2.json'
$S3 = Join-Path $EvidenceRoot 'user_content_s3.json'
$FirstMutation = Join-Path $EvidenceRoot 'first_mutation.json'
$TlsRoot = Join-Path (Join-Path $StateRoot 'user-content-tls') $CommitSha
if (-not $SecurityProvisionEvidence) {
    $SecurityProvisionEvidence = Join-Path $EvidenceRoot 'security_provision.json'
}

foreach ($path in @(
    $Mapping,$MappingApproval,$S1,$Runtime,$ViewerRuntime,$Security,$Decision,
    $RecoveryEvidence,$SecurityProvisionEvidence,(Join-Path $Release 'RELEASE_MANIFEST.json'),
    (Join-Path $TlsRoot 'server.crt'),(Join-Path $TlsRoot 'server.key')
)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "cutover evidence is missing before writer fence: $path"
    }
}
$recovery = Get-Content -Raw -LiteralPath $RecoveryEvidence | ConvertFrom-Json
$s1Evidence = Get-Content -Raw -LiteralPath $S1 | ConvertFrom-Json
$securityEvidence = Get-Content -Raw -LiteralPath $SecurityProvisionEvidence | ConvertFrom-Json
$securityConfigSha = (Get-FileHash -LiteralPath $Security -Algorithm SHA256).Hash.ToLowerInvariant()
if ($recovery.status -ne 'pass' -or -not [bool]$recovery.off_vm_verified -or
    $recovery.application_commit_sha -ne $CommitSha) {
    throw 'recovery evidence does not authorize this exact release'
}
if ($s1Evidence.state -ne 'S1' -or $s1Evidence.authoritative_backend -ne 'sqlite_transition' -or
    $s1Evidence.application_commit_sha -ne $CommitSha) {
    throw 'S1 evidence does not authorize this exact release'
}
if ($securityEvidence.status -ne 'pass' -or
    $securityEvidence.security_config_sha256 -ne $securityConfigSha -or
    -not [bool]$securityEvidence.create_verified -or
    -not [bool]$securityEvidence.rotate_new_accepted -or
    -not [bool]$securityEvidence.rotate_old_rejected -or
    -not [bool]$securityEvidence.revoke_rejected -or
    -not [bool]$securityEvidence.sealed_envelope_removed -or
    [bool]$securityEvidence.secret_values_recorded -or
    [bool]$securityEvidence.password_hashes_recorded) {
    throw 'security provision evidence does not authorize production authentication'
}
Invoke-Isolated 'tools.release.cli' @('verify','--release-dir',$Release)

# No authority-changing operation occurs before all immutable inputs above pass.
& (Join-Path $RepoRoot 'tools\migration\Invoke-UserContentWriterFence.ps1') `
    -PythonExe $PythonExe -RepoRoot $RepoRoot -ReleaseDir $Release -ExistingProductionRoot $ProductionRoot `
    -StateRoot $StateRoot -OutputPath $Fence -Port 8080 | Out-Null

Invoke-Isolated 'tools.migration.stage4_user_content_approval' @(
    'cutover','--mapping',$Mapping,'--decision',$Decision,'--output',$Approval,
    '--mapping-approval',$MappingApproval,'--s1-evidence',$S1,
    '--recovery-evidence',$RecoveryEvidence,'--fence-evidence',$Fence
)
Invoke-Isolated 'tools.migration.stage4_user_content_cutover' @(
    'enter-s2','--runtime',$Runtime,'--route-output',$Route,'--output',$S2,
    '--mapping',$Mapping,'--mapping-approval',$MappingApproval,'--s1-evidence',$S1,
    '--recovery-evidence',$RecoveryEvidence,'--fence-evidence',$Fence,
    '--cutover-approval',$Approval
)

& (Join-Path $RepoRoot 'tools\release\Start-UserContentProductionViewer.ps1') `
    -PythonExe $PythonExe -ReleaseDir $Release -ExpectedCommit $CommitSha `
    -DataRoot (Join-Path $ProductionRoot 'data') -ContentRoot $ProductionRoot `
    -StateRoot $StateRoot -RouteConfig $Route -PostgresConfig $ViewerRuntime `
    -IdentityMapping $Mapping -SecurityConfig $Security `
    -TlsCertificate (Join-Path $TlsRoot 'server.crt') `
    -TlsPrivateKey (Join-Path $TlsRoot 'server.key') -HttpPort 8080 -HttpsPort 8443 | Out-Null

Invoke-Isolated 'tools.migration.stage4_user_content_acceptance' @(
    'first-mutation','--base-url','https://localhost:8443',
    '--http-base-url','http://127.0.0.1:8080',
    '--ca-certificate',(Join-Path $TlsRoot 'server.crt'),'--expected-commit',$CommitSha,
    '--principal','research-operator','--credential-service','honghu.viewer.user-content.v1',
    '--credential-account','research-operator','--client-identity','vm-local-first-formal',
    '--output',$FirstMutation
)
Invoke-Isolated 'tools.migration.stage4_user_content_cutover' @(
    'reconcile-s3','--runtime',$Runtime,'--route-output',$Route,'--output',$S3,
    '--s2-evidence',$S2
)

# The first S2 listener is intentionally replaced so every subsequent request
# uses the durable S3 route loaded at process start.
& (Join-Path $RepoRoot 'tools\release\Stop-UserContentProductionViewer.ps1') `
    -StateRoot $StateRoot | Out-Null
& (Join-Path $RepoRoot 'tools\release\Start-UserContentProductionViewer.ps1') `
    -PythonExe $PythonExe -ReleaseDir $Release -ExpectedCommit $CommitSha `
    -DataRoot (Join-Path $ProductionRoot 'data') -ContentRoot $ProductionRoot `
    -StateRoot $StateRoot -RouteConfig $Route -PostgresConfig $ViewerRuntime `
    -IdentityMapping $Mapping -SecurityConfig $Security `
    -TlsCertificate (Join-Path $TlsRoot 'server.crt') `
    -TlsPrivateKey (Join-Path $TlsRoot 'server.key') -HttpPort 8080 -HttpsPort 8443 | Out-Null

$health = Invoke-RestMethod 'http://127.0.0.1:8080/api/health' -TimeoutSec 10
if (-not [bool]$health.ok -or $health.user_content.authority_state -ne 'S3' -or
    $health.user_content.backend -ne 'postgresql_production') {
    throw 'production Viewer did not restart on durable S3 authority'
}
[ordered]@{
    schema_version = 'honghu.user_content_production_cutover.v1'
    status = 'pass'
    completed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    application_commit_sha = $CommitSha
    authority_state = 'S3'
    authoritative_backend = 'postgresql_production'
    sqlite_writer_fenced = $true
    recovery_evidence = $RecoveryEvidence
    s1_evidence = $S1
    fence_evidence = $Fence
    s2_evidence = $S2
    first_mutation_evidence = $FirstMutation
    s3_evidence = $S3
} | ConvertTo-Json -Depth 12
