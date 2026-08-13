[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$CommitSha,
    [Parameter(Mandatory = $true)][string]$RepoRoot,
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

$EvidenceRoot = Join-Path $InstallRoot 'runtime\evidence\user-content-final'
$RecoveryEvidence = Join-Path $EvidenceRoot 'production_recovery.json'
$TlsRoot = Join-Path (Join-Path (Join-Path $InstallRoot 'runtime') 'user-content-tls') $CommitSha
$Stress = Join-Path $EvidenceRoot 'vm_multi_client_stress.json'

& (Join-Path $RepoRoot 'tools\migration\Invoke-UserContentProductionCutover.ps1') `
    -CommitSha $CommitSha -RepoRoot $RepoRoot -RecoveryEvidence $RecoveryEvidence `
    -InstallRoot $InstallRoot -ReleaseRoot $ReleaseRoot -PythonExe $PythonExe | Out-Null

Invoke-Isolated 'tools.migration.stage4_user_content_acceptance' @(
    'stress','--base-url','https://localhost:8443',
    '--http-base-url','http://127.0.0.1:8080',
    '--ca-certificate',(Join-Path $TlsRoot 'server.crt'),'--expected-commit',$CommitSha,
    '--principal','research-operator',
    '--credential-service','honghu.viewer.user-content.v1',
    '--credential-account','research-operator',
    '--readonly-principal','research-auditor',
    '--readonly-credential-service','honghu.viewer.user-content.v1',
    '--readonly-credential-account','research-auditor',
    '--client-identity','vm-local-post-cutover-stress',
    '--concurrency','12','--mutation-count','64','--output',$Stress
)

$health = Invoke-RestMethod 'http://127.0.0.1:8080/api/health' -TimeoutSec 10
if (-not [bool]$health.ok -or $health.user_content.authority_state -ne 'S3') {
    throw 'final local health is not durable S3'
}
[ordered]@{
    schema_version = 'honghu.user_content_final_acceptance.v1'
    status = 'pass'
    completed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    application_commit_sha = $CommitSha
    authority_state = 'S3'
    stress_evidence = $Stress
    next_step = 'independent_lan_and_browser_acceptance'
} | ConvertTo-Json -Depth 8
