[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$PythonExe = "",
    [string]$EventAt = "10:30",
    [string]$RetentionAt = "21:00"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $PythonExe) {
    $PythonExe = (Get-Command python -ErrorAction Stop).Source
}

$TickScript = Join-Path $PSScriptRoot "retail_window_tick.py"
$EventScript = Join-Path $PSScriptRoot "event_ingest.py"
$EventPythonExe = Join-Path (Split-Path $PythonExe) "pythonw.exe"
if (-not (Test-Path $EventPythonExe)) {
    $EventPythonExe = $PythonExe
}
$TaskSpecs = @(
    @{ Name = "IndustryDemo_Retail_Preopen"; At = "10:00"; Slot = "preopen" },
    @{ Name = "IndustryDemo_Retail_Morning"; At = "14:00"; Slot = "morning" },
    @{ Name = "IndustryDemo_Retail_Afternoon"; At = "17:00"; Slot = "afternoon" }
)

$Mode = if ($Apply) { "APPLY" } else { "DRY-RUN" }
Write-Output ("Project root: {0}" -f $Root)
Write-Output ("Python: {0}" -f $PythonExe)
Write-Output ("Mode: {0}" -f $Mode)
foreach ($Spec in $TaskSpecs) {
    Write-Output ("Plan {0}: Monday-Friday {1} -> --slot {2}" -f $Spec.Name, $Spec.At, $Spec.Slot)
}
Write-Output ("Plan IndustryDemo_EventIngest: Monday-Friday {0} -> event_ingest.py" -f $EventAt)
Write-Output ("Plan IndustryDemo_SentimentRetention: Monday-Friday {0} -> sealed raw retention" -f $RetentionAt)
Write-Output 'Any stale IndustryDemo_SentiTick task is removed only after all new tasks succeed.'

if (-not $Apply) {
    Write-Output "No system changes made. To apply: .\install_retail_window_tasks.ps1 -Apply"
    exit 0
}

$RetailSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) `
    -MultipleInstances IgnoreNew
$EventSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) `
    -MultipleInstances IgnoreNew
$MaintenanceSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

$Registered = New-Object System.Collections.Generic.List[string]
try {
    # Register event cadence first. The legacy combined tick is disabled last.
    $EventArguments = '"{0}" --all --max-llm 600 --per-stock 30' -f $EventScript
    $EventAction = New-ScheduledTaskAction `
        -Execute $EventPythonExe `
        -Argument $EventArguments `
        -WorkingDirectory $Root
    $EventTrigger = New-ScheduledTaskTrigger `
        -Weekly `
        -WeeksInterval 1 `
        -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
        -At $EventAt
    Register-ScheduledTask `
        -TaskName "IndustryDemo_EventIngest" `
        -Action $EventAction `
        -Trigger $EventTrigger `
        -Settings $EventSettings `
        -Principal $Principal `
        -Description ("Weekdays {0} event and announcement ingest; weekends silent; no missed-run night catch-up" -f $EventAt) `
        -Force | Out-Null
    $Registered.Add("IndustryDemo_EventIngest")

    foreach ($Spec in $TaskSpecs) {
        $TickArguments = '"{0}" --slot {1}' -f $TickScript, $Spec.Slot
        $Action = New-ScheduledTaskAction `
            -Execute $PythonExe `
            -Argument $TickArguments `
            -WorkingDirectory $Root
        $Trigger = New-ScheduledTaskTrigger `
            -Weekly `
            -WeeksInterval 1 `
            -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
            -At $Spec.At
        Register-ScheduledTask `
            -TaskName $Spec.Name `
            -Action $Action `
            -Trigger $Trigger `
            -Settings $RetailSettings `
            -Principal $Principal `
            -Description "Retail sentiment V2 market window $($Spec.Slot); weekdays only" `
            -Force | Out-Null
        $Registered.Add($Spec.Name)
    }

    $RetentionAction = New-ScheduledTaskAction `
        -Execute $PythonExe `
        -Argument '-m tools.maintenance.sentiment_retention --apply' `
        -WorkingDirectory $Root
    $RetentionTrigger = New-ScheduledTaskTrigger `
        -Weekly `
        -WeeksInterval 1 `
        -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
        -At $RetentionAt
    Register-ScheduledTask `
        -TaskName "IndustryDemo_SentimentRetention" `
        -Action $RetentionAction `
        -Trigger $RetentionTrigger `
        -Settings $MaintenanceSettings `
        -Principal $Principal `
        -Description "Weekday logical purge for sealed sentiment raw older than 14 days; no external requests" `
        -Force | Out-Null
    $Registered.Add("IndustryDemo_SentimentRetention")

    $Legacy = Get-ScheduledTask -TaskName "IndustryDemo_SentiTick" -ErrorAction SilentlyContinue
    if ($Legacy) {
        Unregister-ScheduledTask -TaskName "IndustryDemo_SentiTick" -Confirm:$false
        Write-Output 'Removed stale IndustryDemo_SentiTick after the replacement tasks succeeded.'
    }
}
catch {
    Write-Error ("Task installation incomplete. Registered: {0}. Error: {1}" -f ($Registered -join ', '), $_.Exception.Message)
    exit 2
}

Write-Output ("Installation complete: {0}" -f ($Registered -join ', '))
exit 0
