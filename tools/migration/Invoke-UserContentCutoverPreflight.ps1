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

function Write-JsonNoBom([string]$Path, [object]$Value) {
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    [IO.File]::WriteAllText(
        $Path,
        (($Value | ConvertTo-Json -Depth 20) + "`n"),
        [Text.UTF8Encoding]::new($false)
    )
}

$requiredFiles = @(
    $PythonExe,
    (Join-Path $RepoRoot 'tools\migration\stage4_isolated_entry.py'),
    (Join-Path $RepoRoot 'tools\release\Start-UserContentProductionViewer.ps1'),
    (Join-Path $RepoRoot 'tools\migration\Invoke-UserContentWriterFence.ps1'),
    (Join-Path $RepoRoot 'config\migration\stage4_user_content_cutover_decision.json'),
    (Join-Path $RepoRoot 'config\migration\user_content_security_production.json'),
    (Join-Path $RepoRoot 'config\migration\cutover_unit_registry.json'),
    (Join-Path $RepoRoot 'config\migration\user_content_backend_route.json'),
    (Join-Path $InstallRoot 'runtime\postgresql_runtime.json')
)
foreach ($path in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "cutover preflight input is missing: $path"
    }
}
foreach ($path in @(
    $RepoRoot,
    $ProductionRoot,
    (Join-Path $ProductionRoot 'data'),
    (Join-Path $ProductionRoot 'docs\industries'),
    (Join-Path $ProductionRoot 'papers'),
    $InstallRoot
)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "cutover preflight directory is missing: $path"
    }
}

$resolvedCommit = (& git -C $RepoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $resolvedCommit -ne $CommitSha) {
    throw "repository checkout is not the approved commit: $resolvedCommit"
}
$dirty = @(& git -C $RepoRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) {
    throw 'repository checkout has tracked modifications'
}
$version = (& $PythonExe -I -B -c 'import sys; print(".".join(map(str,sys.version_info[:3])))').Trim()
if ($LASTEXITCODE -ne 0 -or -not $version.StartsWith('3.10.')) {
    throw "approved Python 3.10 is required, got $version"
}

$service = Get-CimInstance Win32_Service -Filter "Name='HonghuPostgreSQL17'"
if ($null -eq $service -or $service.State -ne 'Running') {
    throw 'HonghuPostgreSQL17 is not running'
}
if (@(Get-NetTCPConnection -LocalPort 55440 -State Listen -ErrorAction Stop).Count -ne 1) {
    throw 'PostgreSQL listener identity is not singular'
}
$health = Invoke-RestMethod 'http://127.0.0.1:8080/api/health' -TimeoutSec 10
if (-not [bool]$health.ok) { throw 'legacy Viewer 8080 is not healthy' }
$route = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot 'config\migration\user_content_backend_route.json') | ConvertFrom-Json
if ($route.authority_state -notin @('S0','S1') -or $route.backend -ne 'sqlite_transition') {
    throw 'tracked route is not the approved SQLite S0/S1 baseline'
}
$research = Join-Path $ProductionRoot 'data\research.db'
$count = (& $PythonExe -I -B -c "import sqlite3; c=sqlite3.connect(r'file:$($research.Replace('\','/'))?mode=ro',uri=True); print(c.execute('select count(*) from analyst_note').fetchone()[0]); c.close()").Trim()
if ($LASTEXITCODE -ne 0 -or $count -notmatch '^\d+$') {
    throw 'live analyst_note read-only probe failed'
}

$stateRoot = Join-Path $InstallRoot 'runtime'
$evidenceRoot = Join-Path $stateRoot 'evidence\user-content-final'
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
$release = Join-Path (Join-Path $ReleaseRoot 'releases') $CommitSha
$result = [ordered]@{
    schema_version = 'honghu.user_content_cutover_preflight.v1'
    status = 'pass'
    checked_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    application_commit_sha = $CommitSha
    repository_clean = $true
    python_version = $version
    postgresql_service = $service.State
    postgresql_listener_count = 1
    legacy_viewer_8080_ok = $true
    tracked_authority_state = $route.authority_state
    tracked_backend = $route.backend
    live_analyst_note_count = [int]$count
    release_root = $ReleaseRoot
    release_path = $release
    state_root = $stateRoot
    evidence_root = $evidenceRoot
    authority_changed = $false
    live_sqlite_modified = $false
}
Write-JsonNoBom (Join-Path $evidenceRoot 'cutover_preflight.json') $result
$result | ConvertTo-Json -Depth 20
