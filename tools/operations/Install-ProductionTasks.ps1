[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('Plan','InstallDisabled','Enable','Disable','Status')][string]$Mode,
    [string]$ReleaseDir,
    [string]$SitePackages,
    [string]$RuntimeCatalog = 'D:\honghu-postgresql\runtime\postgresql_runtime.json',
    [string]$Registry = '',
    [string]$RuntimeDir = 'D:\honghu-stage5-runtime',
    [string]$DataRoot = 'C:\industry_demo\data',
    [string]$ContentRoot = 'C:\industry_demo',
    [string]$Manifest = '',
    [System.Management.Automation.PSCredential]$TaskCredential,
    [string]$TaskName = '',
    [string]$LocalDisabledEvidence = '',
    [string]$TrialEvidence = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-JsonNoBom([string]$Path, [object]$Value) {
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force $parent | Out-Null }
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, (($Value | ConvertTo-Json -Depth 16) + [Environment]::NewLine), $encoding)
}

function Escape-Xml([string]$Value) {
    return [Security.SecurityElement]::Escape($Value)
}

function Quote-Arg([string]$Value) {
    if ($Value.Contains('"')) { throw 'Task argument contains an unsafe quote.' }
    return '"' + $Value + '"'
}

function Get-TaskArguments([string]$TaskId) {
    $bootstrap = Join-Path $ReleaseDir 'tools\release\direct_candidate.py'
    $values = @(
        '-I','-B','-S',$bootstrap,
        '--site-packages',$SitePackages,
        '--module','tools.operations.task_runner',
        'run','--manifest',$Manifest,
        '--postgres-runtime-catalog',$RuntimeCatalog,
        '--cutover-unit-registry',$Registry,
        '--release-dir',$ReleaseDir,
        '--runtime-dir',$RuntimeDir,
        '--data-root',$DataRoot,
        '--content-root',$ContentRoot,
        '--site-packages',$SitePackages,
        '--task',$TaskId
    )
    return (($values | ForEach-Object { Quote-Arg ([string]$_) }) -join ' ')
}

function Get-TriggerXml([object]$Schedule) {
    $today = (Get-Date).ToString('yyyy-MM-dd')
    $days = '<Monday/><Tuesday/><Wednesday/><Thursday/><Friday/>'
    if ($Schedule.kind -eq 'weekday_interval') {
        return "<CalendarTrigger><StartBoundary>${today}T$($Schedule.start):00</StartBoundary><Enabled>true</Enabled><Repetition><Interval>PT$($Schedule.minutes)M</Interval><Duration>PT12H</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek>$days</DaysOfWeek></ScheduleByWeek></CalendarTrigger>"
    }
    if ($Schedule.kind -eq 'weekdays_at') {
        return "<CalendarTrigger><StartBoundary>${today}T$($Schedule.at):00</StartBoundary><Enabled>true</Enabled><ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek>$days</DaysOfWeek></ScheduleByWeek></CalendarTrigger>"
    }
    if ($Schedule.kind -eq 'weekly_at' -and $Schedule.weekday -eq 'Monday') {
        return "<CalendarTrigger><StartBoundary>${today}T$($Schedule.at):00</StartBoundary><Enabled>true</Enabled><ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek><Monday/></DaysOfWeek></ScheduleByWeek></CalendarTrigger>"
    }
    throw "Unsupported reviewed schedule for $($Schedule.kind)."
}

function Get-TaskXml([object]$Definition, [string]$User, [bool]$Enabled) {
    $python = (Get-Item 'C:\ProgramData\miniconda3\envs\quant\python.exe').FullName
    $arguments = Get-TaskArguments $Definition.task_id
    $trigger = Get-TriggerXml $Definition.schedule
    $enabledText = if ($Enabled) { 'true' } else { 'false' }
    return @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Honghu exact-release PostgreSQL production task; no SQLite fallback.</Description></RegistrationInfo>
  <Triggers>$trigger</Triggers>
  <Principals><Principal id="Author"><UserId>$(Escape-Xml $User)</UserId><LogonType>Password</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable><Enabled>$enabledText</Enabled><Hidden>false</Hidden><ExecutionTimeLimit>PT$([int][Math]::Ceiling([int]$Definition.execution_timeout_seconds / 3600))H</ExecutionTimeLimit><Priority>7</Priority></Settings>
  <Actions Context="Author"><Exec><Command>$(Escape-Xml $python)</Command><Arguments>$(Escape-Xml $arguments)</Arguments><WorkingDirectory>$(Escape-Xml $ReleaseDir)</WorkingDirectory></Exec></Actions>
</Task>
"@
}

if (-not $ReleaseDir) { throw 'ReleaseDir is required.' }
if (-not $SitePackages) { throw 'SitePackages is required.' }
if (-not $Manifest) { $Manifest = Join-Path $ReleaseDir 'config\operations\production_tasks.json' }
if (-not $Registry) { $Registry = Join-Path $ReleaseDir 'config\migration\cutover_unit_registry.json' }
foreach ($path in @($ReleaseDir,$SitePackages,$RuntimeCatalog,$Registry,$Manifest)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required task deployment path is absent: $path" }
}
$payload = Get-Content -Raw -LiteralPath $Manifest | ConvertFrom-Json
$tasks = @($payload.tasks)
if ($payload.schema_version -ne 'honghu.production_task_manifest.v1' -or $tasks.Count -ne 7) {
    throw 'Production task manifest is not the reviewed seven-task contract.'
}
if ($payload.runner_host -ne $env:COMPUTERNAME) { throw 'Manifest runner host mismatch.' }

if ($Mode -eq 'Plan') {
    [ordered]@{ mode='plan'; task_count=7; enabled=$false; runner_host=$env:COMPUTERNAME } | ConvertTo-Json
    exit 0
}
if ($Mode -eq 'InstallDisabled') {
    if ($null -eq $TaskCredential) { throw 'InstallDisabled requires a non-interactive task credential.' }
    $user = $TaskCredential.UserName
    if ($user -notmatch 'HonghuTaskRunner$') { throw 'Task principal is not the dedicated HonghuTaskRunner account.' }
    $plain = $TaskCredential.GetNetworkCredential().Password
    $registered = @()
    try {
        foreach ($definition in $tasks) {
            $xml = Get-TaskXml $definition $user $false
            Register-ScheduledTask -TaskName $definition.task_id -Xml $xml -User $user -Password $plain -Force | Out-Null
            Disable-ScheduledTask -TaskName $definition.task_id | Out-Null
            $registered += $definition.task_id
        }
    }
    catch {
        foreach ($name in $registered) { Disable-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue | Out-Null }
        throw
    }
} elseif ($Mode -in @('Enable','Disable')) {
    if (-not $TaskName -or $TaskName -notin @($tasks.task_id)) { throw 'A reviewed TaskName is required.' }
    if ($Mode -eq 'Enable') {
        foreach ($path in @($LocalDisabledEvidence,$TrialEvidence)) {
            if (-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
                throw 'Enable requires local-disabled and controlled-trial evidence.'
            }
        }
        $localEvidence = Get-Content -Raw -LiteralPath $LocalDisabledEvidence | ConvertFrom-Json
        $trial = Get-Content -Raw -LiteralPath $TrialEvidence | ConvertFrom-Json
        $manifestSha = (Get-FileHash $Manifest -Algorithm SHA256).Hash.ToLowerInvariant()
        $releaseIdentity = Get-Content -Raw -LiteralPath (Join-Path $ReleaseDir 'RELEASE_MANIFEST.json') | ConvertFrom-Json
        $localTask = @($localEvidence.tasks | Where-Object { $_.task_id -eq $TaskName })
        if (
            $localEvidence.schema_version -ne 'honghu.local_task_disabled_evidence.v1' -or
            $localEvidence.host -eq $env:COMPUTERNAME -or
            $localTask.Count -ne 1 -or
            -not [bool]$localTask[0].present -or
            [bool]$localTask[0].enabled
        ) { throw 'Local unique-runner disabled evidence is invalid.' }
        if (
            $trial.schema_version -ne 'honghu.production_task_run.v1' -or
            $trial.task_id -ne $TaskName -or
            $trial.status -notin @('succeeded','skipped') -or
            $trial.application_commit_sha -ne $releaseIdentity.commit_sha -or
            $trial.manifest_sha256 -ne $manifestSha -or
            -not $trial.business_checkpoint_after_sha256
        ) { throw 'Controlled production task trial evidence is invalid.' }
        $current = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        if ([bool]$current.Settings.Enabled) { throw 'Task is already enabled; idempotent enable requires manual review.' }
        Enable-ScheduledTask -TaskName $TaskName | Out-Null
    }
    else { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
}

$observed = foreach ($definition in $tasks) {
    $task = Get-ScheduledTask -TaskName $definition.task_id -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        [ordered]@{ task_id=$definition.task_id; present=$false }
        continue
    }
    $xml = Export-ScheduledTask -TaskName $definition.task_id
    [ordered]@{
        task_id=$definition.task_id; present=$true; state=$task.State.ToString()
        enabled=[bool]$task.Settings.Enabled; principal=$task.Principal.UserId
        logon_type=$task.Principal.LogonType.ToString()
        definition_sha256=([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($xml))).Replace('-','').ToLowerInvariant())
    }
}
$evidence = [ordered]@{
    schema_version='honghu.production_task_installation.v1'
    checked_at=(Get-Date).ToUniversalTime().ToString('o')
    mode=$Mode; host=$env:COMPUTERNAME; manifest_sha256=(Get-FileHash $Manifest -Algorithm SHA256).Hash.ToLowerInvariant()
    release_dir=$ReleaseDir; service_account_expected=$true
    tasks=@($observed); all_present=(@($observed | Where-Object { -not $_.present }).Count -eq 0)
}
Write-JsonNoBom (Join-Path $RuntimeDir 'evidence\production_task_installation.json') $evidence
$evidence | ConvertTo-Json -Depth 10
