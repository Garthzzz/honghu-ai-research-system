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

foreach ($path in @($RepoRoot,$ProductionRoot,$InstallRoot,$PythonExe)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "required prepare input missing: $path" }
}
if ((git -C $RepoRoot rev-parse HEAD).Trim().ToLowerInvariant() -ne $CommitSha) {
    throw 'reviewed repository does not match the exact approved commit'
}

$RuntimeRoot = Join-Path $InstallRoot 'runtime'
$EvidenceRoot = Join-Path $RuntimeRoot 'evidence\shared-identity-final'
$SnapshotRoot = Join-Path $EvidenceRoot 'unit-snapshot'
$RuntimeSource = Join-Path $RuntimeRoot 'postgresql_runtime.json'
$RuntimeBound = Join-Path $EvidenceRoot 'postgresql_runtime_release_bound.json'
$SharedRuntime = Join-Path $EvidenceRoot 'postgresql_shared_identity_runtime.json'
$MigrationEvidence = Join-Path $EvidenceRoot 'postgresql_migrations.json'
$Mapping = Join-Path $EvidenceRoot 'identity_mapping.json'
$Crosscheck = Join-Path $EvidenceRoot 'identity_mapping_crosscheck.json'
$S1 = Join-Path $EvidenceRoot 'shared_identity_s1.json'
$Registry = Join-Path $RepoRoot 'config\migration\cutover_unit_registry.json'
$Route = Join-Path $RepoRoot 'config\migration\shared_identity_backend_route.json'
$Decision = Join-Path $RepoRoot 'config\migration\stage4_remaining_cutover_decision.json'
$Release = Join-Path (Join-Path $ReleaseRoot 'releases') $CommitSha
New-Item -ItemType Directory -Force -Path $EvidenceRoot,$SnapshotRoot | Out-Null

Invoke-Isolated 'tools.release.cli' @(
    'build','--repo-root',$RepoRoot,'--deploy-root',$ReleaseRoot,
    '--commit',$CommitSha,'--quarantine-invalid-inactive'
)
Invoke-Isolated 'tools.migration.stage4_runtime_release_binding' @(
    '--source',$RuntimeSource,'--application-commit-sha',$CommitSha,'--output',$RuntimeBound
)
Invoke-Isolated 'tools.migration.stage4_user_content_runtime' @(
    '--source',$RuntimeBound,'--writer-role','writer_shared_identity','--output',$SharedRuntime
)
Invoke-Isolated 'tools.migration.stage4_apply_postgresql_migrations' @(
    '--repo-root',$RepoRoot,'--runtime',$RuntimeBound,'--output',$MigrationEvidence
)
Invoke-Isolated 'tools.migration.stage4_identity_mapping' @(
    '--database',(Join-Path $ProductionRoot 'data\research.db'),
    '--output',$Mapping,
    '--alias-approvals',(Join-Path $RepoRoot 'config\migration\stage4_identity_mapping_approvals.json')
)
Invoke-Isolated 'tools.migration.stage4_identity_mapping_crosscheck' @(
    '--mapping',$Mapping,'--source-data-root',(Join-Path $ProductionRoot 'data'),
    '--output',$Crosscheck
)
$mappingValue = Get-Content -Raw -Encoding UTF8 -LiteralPath $Mapping | ConvertFrom-Json
$decisionValue = Get-Content -Raw -Encoding UTF8 -LiteralPath $Decision | ConvertFrom-Json
$approved = $decisionValue.shared_identity_mapping_approval
if (-not [bool]$approved.cutover_level_approved -or
    [string]$approved.mapping_manifest_sha256 -ne [string]$mappingValue.manifest_sha256 -or
    [string]$approved.mapping_snapshot_identity_sha256 -ne [string]$mappingValue.snapshot_identity_sha256) {
    throw 'live shared identity mapping drifted from the user-approved bundle'
}

Invoke-Isolated 'tools.migration.stage4_prepare_units' @(
    '--source-data-root',(Join-Path $ProductionRoot 'data'),
    '--registry',$Registry,'--route',$Route,'--runtime',$RuntimeBound,
    '--application-commit-sha',$CommitSha,'--work-root',$SnapshotRoot,
    '--unit','shared_identity'
)
$preparation = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $SnapshotRoot 'all_unit_preparation.json') | ConvertFrom-Json
$unit = @($preparation.units | Where-Object {$_.cutover_unit -eq 'shared_identity'})
if ($unit.Count -ne 1 -or $unit[0].status -ne 'staging_reconciled_s0_s1_preparation') {
    throw 'shared_identity staging reconciliation is incomplete'
}
Invoke-Isolated 'tools.migration.stage4_shared_identity_s1' @(
    '--runtime',$RuntimeBound,'--mapping',$Mapping,'--actor','principal:codex',
    '--approval-reference',([string]$decisionValue.approval_reference),'--output',$S1
)
$s1Value = Get-Content -Raw -Encoding UTF8 -LiteralPath $S1 | ConvertFrom-Json
if ($s1Value.authority_state -ne 'S1' -or $s1Value.authoritative_backend -ne 'sqlite_transition' -or
    [int64]$s1Value.source_row_count -ne [int64]$s1Value.target_row_count -or
    [string]$s1Value.application_commit_sha -ne $CommitSha) {
    throw 'shared_identity formal S1 evidence is incomplete'
}

$result = [ordered]@{
    schema_version = 'honghu.shared_identity_cutover_prepare.v1'
    status = 'pass'
    completed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    application_commit_sha = $CommitSha
    authority_state = 'S1'
    authoritative_backend = 'sqlite_transition'
    snapshot_id = [string]$s1Value.source_snapshot_id
    source_row_count = [int64]$s1Value.source_row_count
    target_row_count = [int64]$s1Value.target_row_count
    mapping_manifest_sha256 = [string]$mappingValue.manifest_sha256
    s1_evidence = $S1
    runtime = $RuntimeBound
    shared_runtime = $SharedRuntime
    release = $Release
    production_viewer_modified = $false
    live_sqlite_modified = $false
    authority_transition_performed = $false
}
[IO.File]::WriteAllText(
    (Join-Path $EvidenceRoot 'cutover_prepare.json'),
    (($result | ConvertTo-Json -Depth 12) + "`n"),
    [Text.UTF8Encoding]::new($false)
)
$result | ConvertTo-Json -Depth 12
