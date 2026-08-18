[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$LockedSitePackages,
    [Parameter(Mandatory = $true)][string]$ReleaseDir,
    [Parameter(Mandatory = $true)][string]$ExpectedCommit,
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$ContentRoot,
    [Parameter(Mandatory = $true)][string]$StateRoot,
    [string]$RouteConfig = '',
    [string]$PostgresConfig = '',
    [string]$IdentityMapping = '',
    [string]$PostgresRuntimeCatalog = '',
    [string]$CutoverUnitRegistry = '',
    [Parameter(Mandatory = $true)][string]$SecurityConfig,
    [Parameter(Mandatory = $true)][string]$TlsCertificate,
    [Parameter(Mandatory = $true)][string]$TlsPrivateKey,
    [string]$SharedIdentityRouteConfig = '',
    [string]$SharedIdentityPostgresConfig = '',
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

function Resolve-RequiredDirectory([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
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
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($Record.pid)" -ErrorAction Stop
    if (-not $cim -or -not $cim.ExecutablePath -or -not $cim.CommandLine) {
        throw "refusing to stop PID without complete process identity $($Record.pid)"
    }
    $actualExecutable = (Get-FileHash -LiteralPath ([string]$cim.ExecutablePath) -Algorithm SHA256).Hash.ToLowerInvariant()
    $actualCommand = ([BitConverter]::ToString(
        [Security.Cryptography.SHA256]::Create().ComputeHash(
            [Text.Encoding]::UTF8.GetBytes([string]$cim.CommandLine)
        )
    ).Replace('-','').ToLowerInvariant())
    if ($actualExecutable -ne [string]$Record.executable_sha256 -or $actualCommand -ne [string]$Record.command_line_sha256) {
        throw "refusing to stop process identity mismatch $($Record.pid)"
    }
    Stop-Process -Id ([int]$Record.pid) -Force
    $process.WaitForExit(10000) | Out-Null
}

$PythonExe = Resolve-RequiredFile $PythonExe 'Python'
$LockedSitePackages = Resolve-RequiredDirectory $LockedSitePackages 'locked site-packages'
$ReleaseDir = (Resolve-Path -LiteralPath $ReleaseDir).Path
$Launcher = Resolve-RequiredFile (Join-Path $ReleaseDir 'tools\release\direct_candidate.py') 'isolated production launcher'
$AgentsContract = Resolve-RequiredFile (Join-Path $ReleaseDir 'AGENTS.md') 'release AGENTS contract'
$TlsCertificate = Resolve-RequiredFile $TlsCertificate 'TLS certificate'
$TlsPrivateKey = Resolve-RequiredFile $TlsPrivateKey 'TLS private key'
$CommonMode = [bool]$PostgresRuntimeCatalog -or [bool]$CutoverUnitRegistry
if ([bool]$PostgresRuntimeCatalog -ne [bool]$CutoverUnitRegistry) {
    throw 'PostgreSQL runtime catalog and cutover-unit registry must be supplied together'
}
if ($CommonMode) {
    if ($RouteConfig -or $PostgresConfig -or $IdentityMapping -or
        $SharedIdentityRouteConfig -or $SharedIdentityPostgresConfig) {
        throw 'common authority matrix cannot be combined with per-unit inputs'
    }
    $PostgresRuntimeCatalog = Resolve-RequiredFile $PostgresRuntimeCatalog 'PostgreSQL runtime catalog'
    $CutoverUnitRegistry = Resolve-RequiredFile $CutoverUnitRegistry 'cutover-unit registry'
} else {
    foreach ($item in @(
        @($RouteConfig, 'route'), @($PostgresConfig, 'PostgreSQL runtime'),
        @($IdentityMapping, 'identity mapping')
    )) {
        Resolve-RequiredFile $item[0] $item[1] | Out-Null
    }
}
Resolve-RequiredFile $SecurityConfig 'security configuration' | Out-Null
if ([bool]$SharedIdentityRouteConfig -ne [bool]$SharedIdentityPostgresConfig) {
    throw 'shared identity route and PostgreSQL runtime must be supplied together'
}
if ($SharedIdentityRouteConfig) {
    $SharedIdentityRouteConfig = Resolve-RequiredFile $SharedIdentityRouteConfig 'shared identity route'
    $SharedIdentityPostgresConfig = Resolve-RequiredFile $SharedIdentityPostgresConfig 'shared identity PostgreSQL runtime'
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

$versionOutput = @(& $PythonExe -I -B -c 'import sys;print(sys.version.split()[0])' 2>&1)
$version = (($versionOutput | ForEach-Object { [string]$_ }) -join '').Trim()
if ($LASTEXITCODE -ne 0 -or $version -notmatch '^3\.10\.\d+$') {
    throw "approved Python 3.10 is required, got $version"
}

$Runtime = Join-Path $StateRoot 'user-content-production'
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
$RecordPath = Join-Path $Runtime 'viewer_processes.json'
if (Test-Path -LiteralPath $RecordPath) {
    throw 'existing production Viewer process record must be reconciled before start'
}

$common = @(
    '-I', '-B', '-S', $Launcher,
    '--site-packages', $LockedSitePackages,
    '--module', 'tools.release.user_content_production',
    '--release-dir', $ReleaseDir,
    '--expected-commit', $ExpectedCommit,
    '--data-root', $DataRoot,
    '--content-root', $ContentRoot,
    '--state-root', $StateRoot,
    '--security-config', $SecurityConfig,
    '--host', '0.0.0.0'
)
if ($CommonMode) {
    $common += @(
        '--postgres-runtime-catalog', $PostgresRuntimeCatalog,
        '--cutover-unit-registry', $CutoverUnitRegistry
    )
} else {
    $common += @(
        '--route-config', $RouteConfig,
        '--postgres-config', $PostgresConfig,
        '--identity-mapping', $IdentityMapping
    )
}
if (-not $CommonMode -and $SharedIdentityRouteConfig) {
    $common += @(
        '--shared-identity-route', $SharedIdentityRouteConfig,
        '--shared-identity-postgres-config', $SharedIdentityPostgresConfig
    )
}
$records = @()
try {
    foreach ($listener in @(
        [ordered]@{ name='http'; port=$HttpPort; tls=$false },
        [ordered]@{ name='https'; port=$HttpsPort; tls=$true }
    )) {
        $arguments = @($common) + @('--port', [string]$listener.port)
        $launchId = [guid]::NewGuid().ToString('N')
        $arguments += @('--launch-id', $launchId)
        if ($listener.tls) {
            $arguments += @('--tls', '--tls-cert', $TlsCertificate, '--tls-key', $TlsPrivateKey)
        }
        $argumentString = ($arguments | ForEach-Object { Quote-Argument ([string]$_) }) -join ' '
        $process = Start-Process -FilePath $PythonExe -ArgumentList $argumentString `
            -WorkingDirectory $ReleaseDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $Runtime "$($listener.name).stdout.log") `
            -RedirectStandardError (Join-Path $Runtime "$($listener.name).stderr.log")
        Start-Sleep -Milliseconds 400
        $launcherProcess = $process
        $listenerProcess = $null
        # Production performs all PostgreSQL projection warmups before binding
        # the port.  Large sentiment/financial projections can legitimately
        # take longer than 20 seconds after a process restart.
        $listenerDeadline = (Get-Date).AddSeconds(120)
        do {
            $bound = @(Get-NetTCPConnection -LocalPort ([int]$listener.port) -State Listen -ErrorAction SilentlyContinue)
            $listenerPids = @($bound | Select-Object -ExpandProperty OwningProcess -Unique)
            if ($listenerPids.Count -eq 1) {
                $listenerProcess = Get-Process -Id ([int]$listenerPids[0]) -ErrorAction SilentlyContinue
            }
            if ($null -eq $listenerProcess) { Start-Sleep -Milliseconds 250 }
        } while ($null -eq $listenerProcess -and (Get-Date) -lt $listenerDeadline)
        if ($null -eq $listenerProcess) {
            $launcherProcess.Refresh()
            if ($launcherProcess.HasExited) { throw "$($listener.name) Viewer exited during start" }
            throw "$($listener.name) listener process was not established"
        }
        # A Windows venv launcher may spawn the base interpreter.  The
        # listener PID, not the outer launcher PID, is the durable process
        # identity exposed by health and used by fail-safe cleanup.
        $process = $listenerProcess
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)" -ErrorAction Stop
        if (-not $cim -or -not $cim.ExecutablePath -or -not $cim.CommandLine) {
            throw "$($listener.name) Viewer process identity is incomplete"
        }
        $records += [ordered]@{
            name = $listener.name
            port = $listener.port
            tls = $listener.tls
            pid = $process.Id
            start_time_utc = $process.StartTime.ToUniversalTime().ToString('o')
            launch_id = $launchId
            executable_sha256 = (Get-FileHash -LiteralPath ([string]$cim.ExecutablePath) -Algorithm SHA256).Hash.ToLowerInvariant()
            command_line_sha256 = ([BitConverter]::ToString(
                [Security.Cryptography.SHA256]::Create().ComputeHash(
                    [Text.Encoding]::UTF8.GetBytes([string]$cim.CommandLine)
                )
            ).Replace('-','').ToLowerInvariant())
        }
    }
    $deadline = (Get-Date).AddSeconds(90)
    do {
        $httpReady = $false
        $httpsReady = $false
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$HttpPort/api/health" -TimeoutSec 8
            $httpRecord = @($records | Where-Object {$_.name -eq 'http'})[0]
            $httpReady = [bool](
                $health.ok -and
                $health.user_content.backend -eq 'postgresql_production' -and
                (-not $CommonMode -or $health.viewer_mode -eq 'production_hybrid') -and
                (-not ($CommonMode -or $SharedIdentityRouteConfig) -or $health.shared_identity.backend -eq 'postgresql_production') -and
                $health.release.commit_sha -eq $ExpectedCommit -and
                [int]$health.production_process.pid -eq [int]$httpRecord.pid -and
                $health.production_process.launch_id -eq $httpRecord.launch_id
            )
        } catch {}
        try {
            $probe = @'
import json, ssl, sys, urllib.request
ctx=ssl.create_default_context(cafile=sys.argv[1])
with urllib.request.urlopen(sys.argv[2], context=ctx, timeout=3) as r:
    p=json.load(r)
assert p['ok'] and p['user_content']['backend']=='postgresql_production'
if len(sys.argv) > 6 and sys.argv[6] in {'shared','common'}:
    assert p['shared_identity']['backend']=='postgresql_production'
if len(sys.argv) > 6 and sys.argv[6] == 'common':
    assert p['viewer_mode']=='production_hybrid' and len(p['backend_matrix'])==9
assert p['release']['commit_sha']==sys.argv[3]
assert int(p['production_process']['pid'])==int(sys.argv[4])
assert p['production_process']['launch_id']==sys.argv[5]
'@
            $httpsRecord = @($records | Where-Object {$_.name -eq 'https'})[0]
            $sharedProbe = if ($CommonMode) { 'common' } elseif ($SharedIdentityRouteConfig) { 'shared' } else { 'none' }
            & $PythonExe -I -B -c $probe $TlsCertificate "https://localhost:$HttpsPort/api/health" $ExpectedCommit $httpsRecord.pid $httpsRecord.launch_id $sharedProbe
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
        authority_contract_sha256 = if ($CommonMode) {
            (Get-FileHash -LiteralPath $CutoverUnitRegistry -Algorithm SHA256).Hash.ToLowerInvariant()
        } else {
            (Get-FileHash -LiteralPath $RouteConfig -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        authority_contract_type = if ($CommonMode) { 'cutover_unit_registry' } else { 'legacy_unit_route' }
        created_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        processes = $records
    }
    [IO.File]::WriteAllText(
        $RecordPath,
        (($payload | ConvertTo-Json -Depth 8) + "`n"),
        [Text.UTF8Encoding]::new($false)
    )
    $payload | ConvertTo-Json -Depth 8
} catch {
    foreach ($record in @($records)) {
        try { Stop-OwnedProcess $record } catch {}
    }
    throw
}
