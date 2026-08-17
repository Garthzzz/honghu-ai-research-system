[CmdletBinding()]
param(
    [ValidateSet('DryRun', 'Apply')]
    [string]$Mode = 'DryRun',
    [Parameter(Mandatory = $true)]
    [string]$ResultPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$targets = @(
    [pscustomobject]@{
        Path = 'D:\quant\honghu-postgresql-devtest\downloads'
        Parent = 'D:\quant\honghu-postgresql-devtest'
        Role = 'stale_postgresql_download'
    },
    [pscustomobject]@{
        Path = 'D:\quant\honghu-postgresql-devtest\pgsql-incomplete-20260807180349'
        Parent = 'D:\quant\honghu-postgresql-devtest'
        Role = 'failed_incomplete_postgresql_install'
    },
    [pscustomobject]@{
        Path = 'D:\honghu-stage4-execution'
        Parent = 'D:\'
        Role = 'superseded_local_stage4_execution'
    },
    [pscustomobject]@{
        Path = 'D:\quant\industry_demo_stage5_runtime'
        Parent = 'D:\quant'
        Role = 'completed_git_external_stage5_working_area'
    }
)

function Get-TreeShape([string]$Path) {
    [long]$bytes = 0
    [long]$files = 0
    Get-ChildItem -LiteralPath $Path -File -Recurse -Force -ErrorAction Stop |
        ForEach-Object {
            $bytes += $_.Length
            $files += 1
        }
    return [pscustomobject]@{ files = $files; bytes = $bytes }
}

function Get-References([string]$Path) {
    $needle = [regex]::Escape($Path)
    $references = [System.Collections.Generic.List[object]]::new()
    Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object {
            ([string]$_.ExecutablePath -match $needle) -or
            ([string]$_.CommandLine -match $needle)
        } |
        ForEach-Object {
            $references.Add([pscustomobject]@{
                kind = 'process'
                identity = [string]$_.ProcessId
            })
        }
    Get-CimInstance Win32_Service -ErrorAction Stop |
        Where-Object { [string]$_.PathName -match $needle } |
        ForEach-Object {
            $references.Add([pscustomobject]@{
                kind = 'service'
                identity = [string]$_.Name
            })
        }
    foreach ($task in Get-ScheduledTask -ErrorAction Stop) {
        foreach ($action in $task.Actions) {
            $execute = if ($action.PSObject.Properties['Execute']) {
                [string]$action.Execute
            } else { '' }
            $arguments = if ($action.PSObject.Properties['Arguments']) {
                [string]$action.Arguments
            } else { '' }
            $workingDirectory = if ($action.PSObject.Properties['WorkingDirectory']) {
                [string]$action.WorkingDirectory
            } else { '' }
            $actionText = @(
                $execute,
                $arguments,
                $workingDirectory
            ) -join ' '
            if ($actionText -match $needle) {
                $references.Add([pscustomobject]@{
                    kind = 'scheduled_task'
                    identity = [string]$task.TaskName
                })
            }
        }
    }
    return @($references)
}

$protectedPgsql = 'D:\quant\honghu-postgresql-devtest\pgsql'
$protectedCluster = 'D:\quant\honghu-postgresql-devtest\cluster-17'
if (-not (Test-Path -LiteralPath $protectedPgsql -PathType Container)) {
    throw 'protected devtest pgsql directory is missing'
}
if (-not (Test-Path -LiteralPath $protectedCluster -PathType Container)) {
    throw 'protected devtest cluster directory is missing'
}
$postgresProcesses = @(
    Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object {
            [string]$_.ExecutablePath -like "$protectedPgsql\bin\postgres.exe"
        }
)
if ($postgresProcesses.Count -lt 1) {
    throw 'protected devtest PostgreSQL is not running'
}

$planned = [System.Collections.Generic.List[object]]::new()
foreach ($target in $targets) {
    if (-not (Test-Path -LiteralPath $target.Path)) {
        $planned.Add([pscustomobject]@{
            path = $target.Path
            role = $target.Role
            status = 'already_absent'
            files = 0
            bytes = 0
        })
        continue
    }
    $item = Get-Item -LiteralPath $target.Path -Force -ErrorAction Stop
    if (-not $item.PSIsContainer) {
        throw "cleanup target is not a directory: $($target.Path)"
    }
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "cleanup target is a reparse point: $($target.Path)"
    }
    if ($item.FullName -ne $target.Path -or $item.Parent.FullName -ne $target.Parent) {
        throw "cleanup target boundary mismatch: $($item.FullName)"
    }
    $references = @(Get-References $target.Path)
    if ($references.Count -ne 0) {
        throw "cleanup target has active references: $($target.Path)"
    }
    $shape = Get-TreeShape $target.Path
    $planned.Add([pscustomobject]@{
        path = $target.Path
        role = $target.Role
        status = 'planned'
        files = $shape.files
        bytes = $shape.bytes
    })
}

$removed = [System.Collections.Generic.List[object]]::new()
if ($Mode -eq 'Apply') {
    foreach ($target in $planned | Where-Object status -eq 'planned') {
        Remove-Item -LiteralPath $target.path -Recurse -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $target.path) {
            throw "cleanup target remains after apply: $($target.path)"
        }
        $removed.Add($target)
    }
}

if (-not (Test-Path -LiteralPath $protectedPgsql -PathType Container) -or
    -not (Test-Path -LiteralPath $protectedCluster -PathType Container)) {
    throw 'protected devtest PostgreSQL paths changed during cleanup'
}
$postgresAfter = @(
    Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object {
            [string]$_.ExecutablePath -like "$protectedPgsql\bin\postgres.exe"
        }
)
if ($postgresAfter.Count -lt 1) {
    throw 'protected devtest PostgreSQL stopped during cleanup'
}

[long]$plannedBytes = 0
foreach ($entry in $planned) { $plannedBytes += [long]$entry.bytes }
[long]$removedBytes = 0
foreach ($entry in $removed) { $removedBytes += [long]$entry.bytes }

$result = [ordered]@{
    schema_version = 'honghu.local_stage_artifact_prune.v1'
    mode = $Mode.ToLowerInvariant()
    status = 'pass'
    checked_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    planned = @($planned)
    planned_bytes = $plannedBytes
    removed = @($removed)
    removed_bytes = $removedBytes
    protected = [ordered]@{
        pgsql = $protectedPgsql
        cluster = $protectedCluster
        postgres_process_count = $postgresAfter.Count
    }
    secret_recorded = $false
}
$resultParent = Split-Path -Parent $ResultPath
if (-not (Test-Path -LiteralPath $resultParent)) {
    New-Item -ItemType Directory -Path $resultParent -Force | Out-Null
}
$temporary = $ResultPath + '.tmp'
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding utf8
Move-Item -LiteralPath $temporary -Destination $ResultPath -Force
$result | ConvertTo-Json -Depth 8
