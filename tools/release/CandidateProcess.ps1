Set-StrictMode -Version Latest

function Get-HonghuTextSha256 {
    param([Parameter(Mandatory = $true)][string]$Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-HonghuCandidateProcessSnapshot {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
    $path = $process.Path
    if ([string]::IsNullOrWhiteSpace($path)) { $path = $cim.ExecutablePath }
    return [ordered]@{
        pid = $ProcessId
        start_time_utc = $process.StartTime.ToUniversalTime().ToString("o")
        executable_path = [System.IO.Path]::GetFullPath($path)
        command_line_sha256 = Get-HonghuTextSha256 ([string]$cim.CommandLine)
        command_line = [string]$cim.CommandLine
    }
}

function Test-HonghuCandidateProcessIdentity {
    param(
        [Parameter(Mandatory = $true)]$Record,
        [Parameter(Mandatory = $true)]$Snapshot
    )
    $reasons = New-Object System.Collections.Generic.List[string]
    if ([int]$Record.pid -ne [int]$Snapshot.pid) { $reasons.Add("pid mismatch") }
    if ([string]$Record.start_time_utc -ne [string]$Snapshot.start_time_utc) { $reasons.Add("start time mismatch") }
    if ([System.IO.Path]::GetFullPath([string]$Record.executable_path) -ne [System.IO.Path]::GetFullPath([string]$Snapshot.executable_path)) {
        $reasons.Add("executable mismatch")
    }
    if ([string]$Record.command_line_sha256 -ne [string]$Snapshot.command_line_sha256) { $reasons.Add("command line mismatch") }
    $requiredTokens = @(
        "tools.release.cli",
        "serve-readonly-candidate",
        [string]$Record.launch_id,
        [string]$Record.commit_sha,
        [string]$Record.port
    )
    foreach ($token in $requiredTokens) {
        if (-not ([string]$Snapshot.command_line).Contains($token)) {
            $reasons.Add("command line missing expected candidate token")
            break
        }
    }
    return [ordered]@{ ok = ($reasons.Count -eq 0); reasons = @($reasons) }
}

function Stop-HonghuVerifiedCandidate {
    param([Parameter(Mandatory = $true)][string]$RecordPath)
    if (-not (Test-Path -LiteralPath $RecordPath -PathType Leaf)) {
        return [ordered]@{ ok = $true; status = "no-record" }
    }
    $record = Get-Content -LiteralPath $RecordPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $snapshot = Get-HonghuCandidateProcessSnapshot -ProcessId ([int]$record.pid)
    if ($null -eq $snapshot) {
        Remove-Item -LiteralPath $RecordPath -Force
        return [ordered]@{ ok = $true; status = "stale-record-removed"; pid = [int]$record.pid }
    }
    $identity = Test-HonghuCandidateProcessIdentity -Record $record -Snapshot $snapshot
    if (-not $identity.ok) {
        throw "Refusing to stop PID $($record.pid): candidate identity failed ($($identity.reasons -join ', '))."
    }
    Stop-Process -Id ([int]$record.pid) -Force -ErrorAction Stop
    try { Wait-Process -Id ([int]$record.pid) -Timeout 15 -ErrorAction SilentlyContinue } catch {}
    $remaining = Get-HonghuCandidateProcessSnapshot -ProcessId ([int]$record.pid)
    if ($null -ne $remaining -and [string]$remaining.start_time_utc -eq [string]$record.start_time_utc) {
        throw "Candidate PID $($record.pid) still exists after stop."
    }
    Remove-Item -LiteralPath $RecordPath -Force
    return [ordered]@{ ok = $true; status = "verified-candidate-stopped"; pid = [int]$record.pid }
}
