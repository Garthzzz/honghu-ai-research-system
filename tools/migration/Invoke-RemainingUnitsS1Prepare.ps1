[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$CommitSha,
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [string]$ProductionRoot = 'C:\industry_demo',
    [string]$InstallRoot = 'D:\honghu-postgresql',
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
    if (-not (Test-Path -LiteralPath $path)) { throw "required S1 input missing: $path" }
}
if ((git -C $RepoRoot rev-parse HEAD).Trim().ToLowerInvariant() -ne $CommitSha) {
    throw 'reviewed repository does not match the exact approved commit'
}

$RuntimeRoot = Join-Path $InstallRoot 'runtime'
$SharedEvidence = Join-Path $RuntimeRoot 'evidence\shared-identity-final'
$Runtime = Join-Path $SharedEvidence 'postgresql_runtime_release_bound.json'
$SharedS3 = Join-Path $SharedEvidence 'shared_identity_s3.json'
$EvidenceRoot = Join-Path $RuntimeRoot 'evidence\remaining-units-s1'
$SnapshotRoot = Join-Path $EvidenceRoot 'unit-snapshots'
$Registry = Join-Path $RepoRoot 'config\migration\cutover_unit_registry.json'
$Route = Join-Path $RepoRoot 'config\migration\financial_data_backend_route.json'
$Decision = Join-Path $RepoRoot 'config\migration\stage4_remaining_cutover_decision.json'
foreach ($path in @($Runtime,$SharedS3,$Registry,$Route,$Decision)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "S1 prerequisite missing: $path" }
}
$shared = Get-Content -Raw -LiteralPath $SharedS3 | ConvertFrom-Json
if ($shared.authority_state -ne 'S3' -or $shared.authoritative_backend -ne 'postgresql_production') {
    throw 'shared_identity is not durable PostgreSQL S3'
}
$decision = Get-Content -Raw -LiteralPath $Decision | ConvertFrom-Json
$approvalReference = [string]$decision.approval_reference
if ([string]::IsNullOrWhiteSpace($approvalReference)) { throw 'batch approval reference is absent' }
New-Item -ItemType Directory -Force -Path $EvidenceRoot,$SnapshotRoot | Out-Null

$units = @(
    'financial_data',
    'research_publication',
    'dynamic_intelligence',
    'operations_governance',
    'investment_hypotheses',
    'opportunity_lens',
    'sentiment_analytics'
)
$prepareArgs = @(
    '--source-data-root',(Join-Path $ProductionRoot 'data'),
    '--registry',$Registry,'--route',$Route,'--runtime',$Runtime,
    '--application-commit-sha',$CommitSha,'--work-root',$SnapshotRoot
)
foreach ($unit in $units) { $prepareArgs += @('--unit',$unit) }
Invoke-Isolated 'tools.migration.stage4_prepare_units' $prepareArgs

$preparation = Get-Content -Raw -LiteralPath (Join-Path $SnapshotRoot 'all_unit_preparation.json') | ConvertFrom-Json
if (@($preparation.failures).Count -ne 0 -or @($preparation.units).Count -ne $units.Count) {
    throw 'one or more remaining-unit staging reconciliations failed'
}

$financialOutput = Join-Path $EvidenceRoot 'financial_data_s1.json'
Invoke-Isolated 'tools.migration.stage4_financial_data_s1' @(
    '--runtime',$Runtime,'--application-commit-sha',$CommitSha,
    '--actor','principal:codex','--approval-reference',$approvalReference,
    '--output',$financialOutput
)

$genericUnits = @(
    'research_publication','dynamic_intelligence','operations_governance',
    'investment_hypotheses','opportunity_lens','sentiment_analytics'
)
$evidence = @()
$financial = Get-Content -Raw -LiteralPath $financialOutput | ConvertFrom-Json
$evidence += $financial
foreach ($unit in $genericUnits) {
    $output = Join-Path $EvidenceRoot ($unit + '_s1.json')
    Invoke-Isolated 'tools.migration.stage4_generic_unit_s1' @(
        '--runtime',$Runtime,'--unit',$unit,'--application-commit-sha',$CommitSha,
        '--actor','principal:codex','--approval-reference',$approvalReference,'--output',$output
    )
    $evidence += (Get-Content -Raw -LiteralPath $output | ConvertFrom-Json)
}

foreach ($item in $evidence) {
    if ($item.application_commit_sha -ne $CommitSha -or
        $item.authority_state -ne 'S1' -or
        $item.authoritative_backend -ne 'sqlite_transition' -or
        [bool]$item.formal_business_data) {
        throw "invalid S1 evidence for $($item.cutover_unit)"
    }
}
$summary = [ordered]@{
    schema_version = 'honghu.remaining_units_s1_preparation.v1'
    status = 'pass'
    completed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    application_commit_sha = $CommitSha
    approval_reference = $approvalReference
    units = @($evidence | ForEach-Object {
        [ordered]@{
            cutover_unit = $_.cutover_unit
            state = $_.authority_state
            backend = $_.authoritative_backend
            source_row_count = $_.source_row_count
            target_row_count = $_.target_row_count
            evidence_sha256 = $_.evidence_sha256
        }
    })
    sqlite_authority_unchanged = $true
    production_writer_changed = $false
    s2_s3_entered = $false
}
[IO.File]::WriteAllText(
    (Join-Path $EvidenceRoot 'remaining_units_s1.json'),
    (($summary | ConvertTo-Json -Depth 12) + "`n"),
    [Text.UTF8Encoding]::new($false)
)
$summary | ConvertTo-Json -Depth 12
