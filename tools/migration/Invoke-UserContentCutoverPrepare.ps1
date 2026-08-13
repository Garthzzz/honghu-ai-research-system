[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$CommitSha,
    [Parameter(Mandatory = $true)][string]$RepoRoot,
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

& (Join-Path $RepoRoot 'tools\migration\Invoke-UserContentCutoverPreflight.ps1') `
    -CommitSha $CommitSha -RepoRoot $RepoRoot -ProductionRoot $ProductionRoot `
    -InstallRoot $InstallRoot -ReleaseRoot $ReleaseRoot -PythonExe $PythonExe | Out-Null

$StateRoot = Join-Path $InstallRoot 'runtime'
$EvidenceRoot = Join-Path $StateRoot 'evidence\user-content-final'
$RuntimeSource = Join-Path $StateRoot 'postgresql_runtime.json'
$RuntimeBound = Join-Path $EvidenceRoot 'postgresql_runtime_release_bound.json'
$ViewerRuntime = Join-Path $EvidenceRoot 'postgresql_viewer_runtime.json'
$Registry = Join-Path $RepoRoot 'config\migration\cutover_unit_registry.json'
$Route = Join-Path $RepoRoot 'config\migration\user_content_backend_route.json'
$Mapping = Join-Path $EvidenceRoot 'identity_mapping.json'
$MappingApproval = Join-Path $EvidenceRoot 'mapping_approval.json'
$SnapshotRoot = Join-Path $EvidenceRoot 'unit-snapshot'
$S1 = Join-Path $EvidenceRoot 'user_content_s1.json'
$TlsRoot = Join-Path $StateRoot 'user-content-tls'
$TlsEvidence = Join-Path $EvidenceRoot 'user_content_tls.json'

New-Item -ItemType Directory -Force -Path $EvidenceRoot,$SnapshotRoot | Out-Null
Invoke-Isolated 'tools.migration.stage4_runtime_release_binding' @(
    '--source',$RuntimeSource,'--application-commit-sha',$CommitSha,'--output',$RuntimeBound
)
Invoke-Isolated 'tools.migration.stage4_user_content_runtime' @(
    '--source',$RuntimeBound,'--output',$ViewerRuntime
)
Invoke-Isolated 'tools.migration.stage4_identity_mapping' @(
    '--database',(Join-Path $ProductionRoot 'data\research.db'),
    '--output',$Mapping,
    '--alias-approvals',(Join-Path $RepoRoot 'config\migration\stage4_identity_mapping_approvals.json')
)
Invoke-Isolated 'tools.migration.stage4_user_content_approval' @(
    'mapping','--mapping',$Mapping,
    '--decision',(Join-Path $RepoRoot 'config\migration\stage4_user_content_cutover_decision.json'),
    '--output',$MappingApproval
)
Invoke-Isolated 'tools.migration.stage4_prepare_units' @(
    '--source-data-root',(Join-Path $ProductionRoot 'data'),
    '--registry',$Registry,'--route',$Route,'--runtime',$RuntimeBound,
    '--application-commit-sha',$CommitSha,'--work-root',$SnapshotRoot,
    '--unit','user_content_notes'
)
$Preparation = Get-Content -Raw -LiteralPath (Join-Path $SnapshotRoot 'all_unit_preparation.json') | ConvertFrom-Json
$Unit = @($Preparation.units | Where-Object {$_.cutover_unit -eq 'user_content_notes'})
if ($Unit.Count -ne 1 -or $Unit[0].status -ne 'staging_reconciled_s0_s1_preparation') {
    throw 'user_content_notes staging reconciliation is incomplete'
}
Invoke-Isolated 'tools.migration.stage4_user_content_s1' @(
    '--runtime',$RuntimeBound,'--route',$Route,'--registry',$Registry,
    '--snapshot-id',([string]$Unit[0].snapshot_id),'--mapping',$Mapping,
    '--mapping-approval',$MappingApproval,'--actor','principal:codex','--output',$S1
)

if (-not (Test-Path -LiteralPath (Join-Path $TlsRoot 'server.crt'))) {
    $HostName = [Environment]::MachineName
    Invoke-Isolated 'tools.migration.stage4_tls_certificate' @(
        '--output-dir',$TlsRoot,'--evidence',$TlsEvidence,
        '--common-name',$HostName,'--san-dns',$HostName,'--san-dns','localhost',
        '--san-ip','127.0.0.1','--san-ip','10.5.1.240'
    )
}

$result = [ordered]@{
    schema_version = 'honghu.user_content_cutover_prepare.v1'
    status = 'pass'
    completed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    application_commit_sha = $CommitSha
    snapshot_id = [string]$Unit[0].snapshot_id
    s1_evidence = $S1
    mapping = $Mapping
    mapping_approval = $MappingApproval
    runtime = $RuntimeBound
    viewer_runtime = $ViewerRuntime
    tls_root = $TlsRoot
    authority_state = 'S1'
    authoritative_backend = 'sqlite_transition'
    production_viewer_modified = $false
    live_sqlite_modified = $false
}
[IO.File]::WriteAllText(
    (Join-Path $EvidenceRoot 'cutover_prepare.json'),
    (($result | ConvertTo-Json -Depth 12) + "`n"),
    [Text.UTF8Encoding]::new($false)
)
$result | ConvertTo-Json -Depth 12
