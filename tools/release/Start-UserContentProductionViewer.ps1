[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$ReleaseDir,
    [Parameter(Mandatory = $true)][string]$ExpectedCommit,
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$ContentRoot,
    [Parameter(Mandatory = $true)][string]$StateRoot,
    [Parameter(Mandatory = $true)][string]$RouteConfig,
    [Parameter(Mandatory = $true)][string]$PostgresConfig,
    [Parameter(Mandatory = $true)][string]$IdentityMapping,
    [Parameter(Mandatory = $true)][string]$SecurityConfig,
    [Parameter(Mandatory = $true)][string]$TlsCertificate,
    [Parameter(Mandatory = $true)][string]$TlsPrivateKey,
    [int]$HttpPort = 8080,
    [int]$HttpsPort = 8443
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Resolve-RequiredFile([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label missing: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Quote-Argument([string]$Value) {
    if ($Value.Contains('"')) { throw 'unsafe quote in process argument' }
    return '"' + $Value + '"'
}

function Stop-OwnedProcess([object]$Record) {
    if ($null -eq $Record) { return }
    $process = Get-Process -Id ([int]$Record.pid) -ErrorAction SilentlyContinue
    if ($null -eq $process) { return }
    $actualStart = $process.StartTime.ToUniversalTime().ToString('o')
    if ($actualStart -ne [string]$Record.start_time_utc) {
        throw "refusing to stop reused PID $($Record.pid)"
    }
    Stop-Process -Id ([int]$Record.pid) -Force
    $process.WaitForExit(10000) | Out-Null
}

$PythonExe = Resolve-RequiredFile $PythonExe 'Python'
$ReleaseDir = (Resolve-Path -LiteralPath $ReleaseDir).Path
$Launcher = Resolve-RequiredFile (Join-Path $ReleaseDir 'tools\release\user_content_production.py') 'production launcher'
$TlsCertificate = Resolve-RequiredFile $TlsCertificate 'TLS certificate'
$TlsPrivateKey = Resolve-RequiredFile $TlsPrivateKey 'TLS private key'
foreach ($item in @(
    @($RouteConfig, 'route'), @($PostgresConfig, 'PostgreSQL runtime'),
    @($IdentityMapping, 'identity mapping'), @($SecurityConfig, 'security configuration')
)) {
    Resolve-RequiredFile $item[0] $item[1] | Out-Null
}
foreach ($directory in @($DataRoot, $ContentRoot, $StateRoot)) {
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        throw "runtime directory missing: $directory"
    }
}
foreach ($port in @($HttpPort, $HttpsPort)) {
    if (@(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).Count -gt 0) {
        throw "port $port is already listening"
    }
}

$version = (& $PythonExe -I -B -c 'import sys; print(".".join(map(str,sys.version_info[:3])))').Trim()
if ($LASTEXITCODE -ne 0 -or -not $version.StartsWith('3.10.')) {
    throw "approved Python 3.10 is required, got $version"
}

$Runtime = Join-Path $StateRoot 'user-content-production'
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
$RecordPath = Join-Path $Runtime 'viewer_processes.json'
if (Test-Path -LiteralPath $RecordPath) {
    throw 'existing production Viewer process record must be reconciled before start'
}

$common = @(
    '-I', '-B', $Launcher,
    '--release-dir', $ReleaseDir,
    '--expected-commit', $ExpectedCommit,
    '--data-root', $DataRoot,
    '--content-root', $ContentRoot,
    '--state-root', $StateRoot,
    '--route-config', $RouteConfig,
    '--postgres-config', $PostgresConfig,
    '--identity-mapping', $IdentityMapping,
    '--security-config', $SecurityConfig,
    '--host', '0.0.0.0'
)
$records = @()
try {
    foreach ($listener in @(
        [ordered]@{ name='http'; port=$HttpPort; tls=$false },
        [ordered]@{ name='https'; port=$HttpsPort; tls=$true }
    )) {
        $arguments = @($common) + @('--port', [string]$listener.port)
        if ($listener.tls) {
            $arguments += @('--tls', '--tls-cert', $TlsCertificate, '--tls-key', $TlsPrivateKey)
        }
        $argumentString = ($arguments | ForEach-Object { Quote-Argument ([string]$_) }) -join ' '
        $process = Start-Process -FilePath $PythonExe -ArgumentList $argumentString `
            -WorkingDirectory $ReleaseDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $Runtime "$($listener.name).stdout.log") `
            -RedirectStandardError (Join-Path $Runtime "$($listener.name).stderr.log")
        Start-Sleep -Milliseconds 400
        $process.Refresh()
        if ($process.HasExited) { throw "$($listener.name) Viewer exited during start" }
        $records += [ordered]@{
            name = $listener.name
            port = $listener.port
            tls = $listener.tls
            pid = $process.Id
            start_time_utc = $process.StartTime.ToUniversalTime().ToString('o')
            executable_sha256 = (Get-FileHash -LiteralPath $PythonExe -Algorithm SHA256).Hash.ToLowerInvariant()
            command_line_sha256 = ([BitConverter]::ToString(
                [Security.Cryptography.SHA256]::Create().ComputeHash(
                    [Text.Encoding]::UTF8.GetBytes($argumentString)
                )
            ).Replace('-','').ToLowerInvariant())
        }
    }
    $deadline = (Get-Date).AddSeconds(45)
    do {
        $httpReady = $false
        $httpsReady = $false
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$HttpPort/api/health" -TimeoutSec 2
            $httpReady = [bool]($health.ok -and $health.user_content.backend -eq 'postgresql_production')
        } catch {}
        try {
            $probe = @'
import json, ssl, sys, urllib.request
ctx=ssl.create_default_context(cafile=sys.argv[1])
with urllib.request.urlopen(sys.argv[2], context=ctx, timeout=3) as r:
    p=json.load(r)
assert p['ok'] and p['user_content']['backend']=='postgresql_production'
'@
            & $PythonExe -I -B -c $probe $TlsCertificate "https://localhost:$HttpsPort/api/health"
            $httpsReady = ($LASTEXITCODE -eq 0)
        } catch {}
        if (-not ($httpReady -and $httpsReady)) { Start-Sleep -Seconds 1 }
    } while ((Get-Date) -lt $deadline -and -not ($httpReady -and $httpsReady))
    if (-not ($httpReady -and $httpsReady)) { throw 'production Viewer health did not become ready' }
    foreach ($record in $records) {
        $listeners = @(Get-NetTCPConnection -LocalPort ([int]$record.port) -State Listen -ErrorAction Stop)
        if ($listeners.Count -lt 1 -or @($listeners.OwningProcess | Sort-Object -Unique) -notcontains [int]$record.pid) {
            throw "listener PID mismatch on port $($record.port)"
        }
    }
    $payload = [ordered]@{
        schema_version = 'honghu.user_content_viewer_processes.v1'
        commit_sha = $ExpectedCommit
        route_sha256 = (Get-FileHash -LiteralPath $RouteConfig -Algorithm SHA256).Hash.ToLowerInvariant()
        created_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        processes = $records
    }
    $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $RecordPath -Encoding UTF8
    $payload | ConvertTo-Json -Depth 8
} catch {
    foreach ($record in @($records)) {
        try { Stop-OwnedProcess $record } catch {}
    }
    throw
}
