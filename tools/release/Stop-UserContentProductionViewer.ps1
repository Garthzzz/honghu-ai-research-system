[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$StateRoot)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$RecordPath = Join-Path $StateRoot 'user-content-production\viewer_processes.json'
if (-not (Test-Path -LiteralPath $RecordPath -PathType Leaf)) {
    [ordered]@{ok=$true;status='no-record'} | ConvertTo-Json
    exit 0
}
$record = Get-Content -Raw -LiteralPath $RecordPath | ConvertFrom-Json
if ($record.schema_version -ne 'honghu.user_content_viewer_processes.v1') {
    throw 'unsupported production Viewer process record'
}
foreach ($entry in @($record.processes)) {
    $process = Get-Process -Id ([int]$entry.pid) -ErrorAction SilentlyContinue
    $listeners = @(Get-NetTCPConnection -LocalPort ([int]$entry.port) -State Listen -ErrorAction SilentlyContinue)
    if ($null -eq $process) {
        if ($listeners.Count -gt 0) { throw "stale PID but port $($entry.port) still listens" }
        continue
    }
    if ($process.StartTime.ToUniversalTime().ToString('o') -ne [string]$entry.start_time_utc) {
        throw "refusing to stop reused PID $($entry.pid)"
    }
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($entry.pid)" -ErrorAction Stop
    if (-not $cim -or -not $cim.ExecutablePath -or -not $cim.CommandLine) {
        throw "refusing to stop PID without complete process identity $($entry.pid)"
    }
    $actualExecutable = (Get-FileHash -LiteralPath ([string]$cim.ExecutablePath) -Algorithm SHA256).Hash.ToLowerInvariant()
    $actualCommand = ([BitConverter]::ToString(
        [Security.Cryptography.SHA256]::Create().ComputeHash(
            [Text.Encoding]::UTF8.GetBytes([string]$cim.CommandLine)
        )
    ).Replace('-','').ToLowerInvariant())
    if ($actualExecutable -ne [string]$entry.executable_sha256 -or $actualCommand -ne [string]$entry.command_line_sha256) {
        throw "refusing to stop process identity mismatch $($entry.pid)"
    }
    if (@($listeners.OwningProcess | Sort-Object -Unique) -notcontains [int]$entry.pid) {
        throw "recorded PID does not own port $($entry.port)"
    }
    Stop-Process -Id ([int]$entry.pid) -Force
    $process.WaitForExit(10000) | Out-Null
}
foreach ($entry in @($record.processes)) {
    if (@(Get-NetTCPConnection -LocalPort ([int]$entry.port) -State Listen -ErrorAction SilentlyContinue).Count -gt 0) {
        throw "port $($entry.port) did not release"
    }
}
$archive = "$RecordPath.stopped.$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))"
Move-Item -LiteralPath $RecordPath -Destination $archive
[ordered]@{ok=$true;status='stopped';record_archive=$archive} | ConvertTo-Json
