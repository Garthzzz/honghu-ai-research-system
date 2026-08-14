[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$ReleaseDir,
    [Parameter(Mandatory = $true)][string]$ExistingProductionRoot,
    [Parameter(Mandatory = $true)][string]$StateRoot,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [int]$Port = 8080
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot 'Stage4ScheduledTaskInspection.ps1')

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}

function Get-Sha256([object]$Value) {
    $json = $Value | ConvertTo-Json -Depth 30 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($json)
    return ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes))).Replace('-','').ToLowerInvariant()
}

foreach ($path in @(
    $PythonExe,
    (Join-Path $RepoRoot 'AGENTS.md'),
    (Join-Path $RepoRoot 'tools\migration\stage4_isolated_entry.py'),
    (Join-Path $ReleaseDir 'RELEASE_MANIFEST.json')
)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "required file missing: $path" }
}
$ResolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path.TrimEnd('\')
$ResolvedReleaseDir = (Resolve-Path -LiteralPath $ReleaseDir).Path.TrimEnd('\')
if ($ResolvedRepoRoot.Equals($ResolvedReleaseDir, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'reviewed repository root and immutable release directory must be distinct'
}
$ResearchDb = Join-Path $ExistingProductionRoot 'data\research.db'
if (-not (Test-Path -LiteralPath $ResearchDb -PathType Leaf)) { throw 'live research.db is missing' }
$Runtime = Join-Path $StateRoot 'user-content-cutover'
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
$Before = Join-Path $Runtime 'sqlite_watermark_before_stop.json'
$After = Join-Path $Runtime 'sqlite_watermark_after_stop.json'
$Windows = Join-Path $Runtime 'windows_writer_fence_observation.json'
$WindowsCore = Join-Path $Runtime 'windows_writer_fence_observation.unsealed.json'
$Dispatcher = Join-Path $RepoRoot 'tools\migration\stage4_isolated_entry.py'
$Module = 'tools.migration.stage4_user_content_writer_fence'

& $PythonExe -I -B $Dispatcher --repo-root $RepoRoot --module $Module -- capture --database $ResearchDb --output $Before
if ($LASTEXITCODE -ne 0) { throw 'pre-stop SQLite watermark failed' }

$health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 10
if (-not [bool]$health.ok) { throw 'legacy Viewer health is not successful before fence' }
$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop)
$pids = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
if ($pids.Count -lt 1) { throw 'legacy Viewer listener is absent before fence' }

$verified = @()
foreach ($pidValue in $pids) {
    $process = Get-Process -Id ([int]$pidValue) -ErrorAction Stop
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction Stop
    $commandLine = [string]$cim.CommandLine
    $executable = [string]$cim.ExecutablePath
    if (-not $commandLine -or -not $executable) { throw "legacy Viewer PID $pidValue lacks process identity" }
    $normalized = $commandLine.ToLowerInvariant()
    if (-not ($normalized.Contains('tools.viewer.app') -or $normalized.Contains('tools\viewer\app.py'))) {
        throw "port $Port is not owned by the approved legacy Viewer"
    }
    $verified += [ordered]@{
        pid = [int]$pidValue
        start_time_utc = $process.StartTime.ToUniversalTime().ToString('o')
        executable_sha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
        command_line_sha256 = Get-Sha256 $commandLine
    }
}

# A Windows service manager (NSSM in the current production topology) can
# immediately respawn a killed listener.  Bind every listener to its owning
# service ancestor when one exists; stopping only the leaf PID is not a writer
# fence.
$processByPid = @{}
Get-CimInstance Win32_Process -ErrorAction Stop | ForEach-Object {
    $processByPid[[int]$_.ProcessId] = $_
}
$serviceByPid = @{}
Get-CimInstance Win32_Service -ErrorAction Stop |
    Where-Object { [int]$_.ProcessId -gt 0 } |
    ForEach-Object { $serviceByPid[[int]$_.ProcessId] = $_ }
$serviceIdentitiesByName = @{}
$listenerServiceNames = @{}
foreach ($identity in $verified) {
    $currentPid = [int]$identity.pid
    $visited = @{}
    $owner = $null
    for ($depth = 0; $depth -lt 8 -and $currentPid -gt 0; $depth++) {
        if ($visited.ContainsKey($currentPid)) { break }
        $visited[$currentPid] = $true
        if ($serviceByPid.ContainsKey($currentPid)) {
            $owner = $serviceByPid[$currentPid]
            break
        }
        if (-not $processByPid.ContainsKey($currentPid)) { break }
        $currentPid = [int]$processByPid[$currentPid].ParentProcessId
    }
    if ($null -eq $owner) { continue }
    $managerPid = [int]$owner.ProcessId
    $managerProcess = Get-Process -Id $managerPid -ErrorAction Stop
    $managerCim = $processByPid[$managerPid]
    $managerExecutable = [string]$managerCim.ExecutablePath
    if (-not $managerExecutable -or -not (Test-Path -LiteralPath $managerExecutable -PathType Leaf)) {
        throw "legacy Viewer service manager PID $managerPid lacks executable identity"
    }
    $serviceName = [string]$owner.Name
    $listenerServiceNames[[int]$identity.pid] = $serviceName
    if (-not $serviceIdentitiesByName.ContainsKey($serviceName)) {
        $serviceIdentitiesByName[$serviceName] = [ordered]@{
            name = $serviceName
            display_name = [string]$owner.DisplayName
            original_start_mode = [string]$owner.StartMode
            start_name = [string]$owner.StartName
            service_path_sha256 = Get-Sha256 ([string]$owner.PathName)
            manager_pid = $managerPid
            manager_start_time_utc = $managerProcess.StartTime.ToUniversalTime().ToString('o')
            manager_executable_sha256 = (Get-FileHash -LiteralPath $managerExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
            listener_pids = @()
        }
    }
    $serviceIdentitiesByName[$serviceName].listener_pids += [int]$identity.pid
}
$serviceIdentities = @($serviceIdentitiesByName.Values)

# Query every task before stopping the only known live writer.  A task action
# capable of launching the Viewer/analyst-note route blocks the maintenance
# window; unrelated IndustryDemo collectors are retained and never modified.
$taskMatches = @()
$unsupportedRelevantActions = @()
$allTasks = @(Get-ScheduledTask -ErrorAction Stop)
foreach ($task in $allTasks) {
    $taskIdentity = (([string]$task.TaskPath) + ([string]$task.TaskName)).ToLowerInvariant()
    $taskIsRelevant = (
        $taskIdentity.Contains('industrydemo') -or
        $taskIdentity.Contains('honghu') -or
        $taskIdentity.Contains('analyst_note')
    )
    foreach ($action in @($task.Actions)) {
        $inspection = Get-HonghuScheduledTaskActionInspection -Action $action
        if (-not [bool]$inspection.has_execute_property) {
            if ($taskIsRelevant) {
                $unsupportedRelevantActions += [ordered]@{
                    task_path = [string]$task.TaskPath
                    task_name = [string]$task.TaskName
                    state = [string]$task.State
                    action_id = [string]$inspection.action_id
                    class_id = [string]$inspection.class_id
                }
            }
            continue
        }
        $actionText = [string]$inspection.searchable_text
        if ($actionText.Contains('tools.viewer.app') -or $actionText.Contains('restart_viewer') -or $actionText.Contains('analyst_note')) {
            if ([string]$task.State -ne 'Disabled') {
                $taskMatches += [ordered]@{task_path=$task.TaskPath;task_name=$task.TaskName;state=[string]$task.State}
            }
        }
    }
}
if ($unsupportedRelevantActions.Count -gt 0) {
    throw 'a relevant Scheduled Task has a non-Exec action that cannot be safely inspected'
}
if ($taskMatches.Count -gt 0) { throw 'an enabled Scheduled Task can launch the legacy analyst-note writer' }

$stoppedServiceNames = @()
try {
    foreach ($serviceIdentity in $serviceIdentities) {
        $service = Get-Service -Name ([string]$serviceIdentity.name) -ErrorAction Stop
        if ([string]$service.Status -ne 'Running') {
            throw "legacy Viewer service is not running before fence: $($serviceIdentity.name)"
        }
        Stop-Service -Name ([string]$serviceIdentity.name) -Force -ErrorAction Stop
        $deadline = (Get-Date).AddSeconds(20)
        do {
            Start-Sleep -Milliseconds 250
            $service = Get-Service -Name ([string]$serviceIdentity.name) -ErrorAction Stop
        } while ($service.Status -ne 'Stopped' -and (Get-Date) -lt $deadline)
        if ($service.Status -ne 'Stopped') {
            throw "legacy Viewer service did not stop: $($serviceIdentity.name)"
        }
        $stoppedServiceNames += [string]$serviceIdentity.name
    }
    foreach ($identity in $verified) {
        if ($listenerServiceNames.ContainsKey([int]$identity.pid)) { continue }
        $process = Get-Process -Id ([int]$identity.pid) -ErrorAction Stop
        if ($process.StartTime.ToUniversalTime().ToString('o') -ne [string]$identity.start_time_utc) {
            throw "legacy Viewer PID was reused before stop: $($identity.pid)"
        }
        Stop-Process -Id ([int]$identity.pid) -Force -ErrorAction Stop
        $process.WaitForExit(10000) | Out-Null
    }
    Start-Sleep -Seconds 2
    $afterListeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    $afterHealthReachable = $false
    try {
        Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 | Out-Null
        $afterHealthReachable = $true
    } catch {}

    $processMatches = @()
    $processQuery = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    foreach ($process in $processQuery) {
        $text = [string]$process.CommandLine
        if (-not $text) { continue }
        $normalized = $text.ToLowerInvariant()
        if ($normalized.Contains('tools.viewer.app') -or $normalized.Contains('tools\viewer\app.py')) {
            $processMatches += [ordered]@{pid=[int]$process.ProcessId;command_line_sha256=(Get-Sha256 $text)}
        }
    }

    $core = [ordered]@{
        schema_version = 'honghu.user_content_windows_fence.v1'
        captured_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        production_root_sha256 = Get-Sha256 ((Resolve-Path -LiteralPath $ExistingProductionRoot).Path.ToLowerInvariant())
        preflight_query_succeeded = $true
        legacy_health_was_reachable = $true
        legacy_listener_identity_verified = $true
        legacy_listener_stopped = $true
        legacy_service_fence_verified = $true
        post_stop_listener_absent = ($afterListeners.Count -eq 0)
        post_stop_health_unreachable = (-not $afterHealthReachable)
        scheduled_task_query_succeeded = $true
        process_query_succeeded = $true
        stopped_listener_pids = @($verified | ForEach-Object {[int]$_.pid})
        stopped_process_identities = $verified
        stopped_service_identities = $serviceIdentities
        scheduled_writer_matches = $taskMatches
        writer_process_matches = $processMatches
    }
    Write-Utf8NoBom $WindowsCore (($core | ConvertTo-Json -Depth 30) + "`n")
    & $PythonExe -I -B $Dispatcher --repo-root $RepoRoot --module $Module -- seal-windows --input $WindowsCore --output $Windows
    if ($LASTEXITCODE -ne 0) { throw 'Windows writer-fence observation sealing failed' }
    Remove-Item -LiteralPath $WindowsCore -Force

    & $PythonExe -I -B $Dispatcher --repo-root $RepoRoot --module $Module -- capture --database $ResearchDb --output $After
    if ($LASTEXITCODE -ne 0) { throw 'post-stop SQLite watermark failed' }
    & $PythonExe -I -B $Dispatcher --repo-root $RepoRoot --module $Module -- compile --before $Before --after $After --windows-observation $Windows --release-dir $ReleaseDir --expected-commit ((Split-Path -Leaf $ReleaseDir).ToLowerInvariant()) --output $OutputPath
    if ($LASTEXITCODE -ne 0) { throw 'writer-fence evidence compilation failed' }
}
catch {
    # S2 cannot have started inside this script.  Restore only the verified
    # service writer when the fence itself fails, then rethrow the primary
    # failure so no partial evidence can authorize a cutover.
    foreach ($serviceName in $stoppedServiceNames) {
        try { Start-Service -Name $serviceName -ErrorAction Stop } catch {}
    }
    if ($stoppedServiceNames.Count -gt 0) {
        $deadline = (Get-Date).AddSeconds(30)
        do {
            Start-Sleep -Milliseconds 500
            try {
                $restored = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
                if ([bool]$restored.ok) { break }
            } catch {}
        } while ((Get-Date) -lt $deadline)
    }
    throw
}
