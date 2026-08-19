[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$Manifest
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-TextSha256([string]$Value) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    return ([BitConverter]::ToString(
        [Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    )).Replace('-','').ToLowerInvariant()
}

if (-not (Test-Path -LiteralPath $Manifest -PathType Leaf)) {
    throw 'The exact-release production task manifest is required.'
}
$manifestPayload = Get-Content -Raw -LiteralPath $Manifest | ConvertFrom-Json
$definitions = @($manifestPayload.tasks)
if (
    $manifestPayload.schema_version -ne 'honghu.production_task_manifest.v1' -or
    $definitions.Count -ne 11
) { throw 'The reviewed eleven-task manifest is invalid.' }

$hostName = $env:COMPUTERNAME.ToUpperInvariant()
if ($hostName -ne ([string]$manifestPayload.legacy_runner_host).ToUpperInvariant()) {
    throw 'This host is not the reviewed legacy runner host.'
}
$machineGuid = Get-ItemPropertyValue `
    -Path 'HKLM:\SOFTWARE\Microsoft\Cryptography' -Name MachineGuid
$hostIdentity = Get-TextSha256 "$hostName|$machineGuid"
$machineGuid = $null

$processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
$observed = @()
$matchedProcesses = @()
foreach ($definition in $definitions) {
    $name = [string]$definition.task_id
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        $expectedAbsent = ([string]$definition.legacy_principal -eq 'not_applicable_new_task')
        $observed += [ordered]@{
            task_id=$name; present=$false; enabled=$false; state='Absent'
            principal=$null; definition_sha256=$null
            expected_definition_sha256=[string]$definition.legacy_definition_sha256
            legacy_absence_expected=$expectedAbsent
            definition_matches_manifest=$expectedAbsent
        }
        continue
    }
    $xml = Export-ScheduledTask -TaskName $name
    $definitionSha = Get-TextSha256 $xml
    $principal = [string]$task.Principal.UserId
    $observed += [ordered]@{
        task_id=$name
        present=$true
        enabled=[bool]$task.Settings.Enabled
        state=$task.State.ToString()
        principal=$principal
        legacy_absence_expected=$false
        definition_sha256=$definitionSha
        expected_definition_sha256=[string]$definition.legacy_definition_sha256
        definition_matches_manifest=(
            $definitionSha -eq [string]$definition.legacy_definition_sha256 -and
            $principal -eq [string]$definition.legacy_principal
        )
    }

    foreach ($action in @($task.Actions)) {
        $execute = [Environment]::ExpandEnvironmentVariables([string]$action.Execute)
        $arguments = [string]$action.Arguments
        $signature = $null
        if ($arguments -match '(?i)([A-Z]:\\[^\"]+?\.py)') {
            $signature = [string]$Matches[1]
        } elseif ($arguments -match '(?i)-m\s+([A-Za-z0-9_.]+)') {
            $signature = [string]$Matches[1]
        }
        if (-not $execute -or -not $signature) { continue }
        foreach ($process in $processes) {
            $processExe = [string]$process.ExecutablePath
            $commandLine = [string]$process.CommandLine
            if (
                $processExe -and $commandLine -and
                $processExe.Equals($execute,[StringComparison]::OrdinalIgnoreCase) -and
                $commandLine.IndexOf($signature,[StringComparison]::OrdinalIgnoreCase) -ge 0
            ) {
                $matchedProcesses += [ordered]@{
                    task_id=$name
                    pid=[int]$process.ProcessId
                    creation_date=[string]$process.CreationDate
                    executable_path_sha256=Get-TextSha256 $processExe.ToLowerInvariant()
                    command_line_sha256=Get-TextSha256 $commandLine
                }
            }
        }
    }
}

$payload = [ordered]@{
    schema_version='honghu.local_task_disabled_evidence.v2'
    checked_at=(Get-Date).ToUniversalTime().ToString('o')
    source_host=$hostName
    source_host_identity_sha256=$hostIdentity
    machine_guid_recorded=$false
    manifest_sha256=(Get-FileHash -LiteralPath $Manifest -Algorithm SHA256).Hash.ToLowerInvariant()
    # Git stores this script with LF while Windows worktrees normally use CRLF.
    # Bind the reviewed source, not the checkout-specific newline encoding.
    collector_sha256=Get-TextSha256 (([IO.File]::ReadAllText($PSCommandPath)).Replace("`r`n","`n").Replace("`r","`n"))
    tasks=@($observed)
    all_present=(@($observed | Where-Object { -not $_.present }).Count -eq 0)
    all_legacy_tasks_safe=(@($observed | Where-Object { -not $_.definition_matches_manifest }).Count -eq 0)
    all_disabled=(@($observed | Where-Object { $_.enabled -or ($_.state -ne 'Disabled' -and -not $_.legacy_absence_expected) }).Count -eq 0)
    all_definitions_match=(@($observed | Where-Object { -not $_.definition_matches_manifest }).Count -eq 0)
    legacy_runner_process_count=$matchedProcesses.Count
    legacy_runner_processes=@($matchedProcesses)
    secrets_recorded=$false
}
$parent = Split-Path -Parent $Output
if ($parent) { New-Item -ItemType Directory -Force $parent | Out-Null }
$encoding = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
    $Output,(($payload | ConvertTo-Json -Depth 10)+[Environment]::NewLine),$encoding
)
$payload | ConvertTo-Json -Depth 10
