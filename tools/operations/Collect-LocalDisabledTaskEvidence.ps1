[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Output
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$names = @(
    'IndustryDemo_DynamicTick','IndustryDemo_EventIngest','IndustryDemo_RecruitWeekly',
    'IndustryDemo_Retail_Preopen','IndustryDemo_Retail_Morning',
    'IndustryDemo_Retail_Afternoon','IndustryDemo_SentimentRetention'
)
$observed = foreach ($name in $names) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        [ordered]@{ task_id=$name; present=$false; enabled=$false; definition_sha256=$null }
        continue
    }
    $xml = Export-ScheduledTask -TaskName $name
    [ordered]@{
        task_id=$name
        present=$true
        enabled=[bool]$task.Settings.Enabled
        state=$task.State.ToString()
        definition_sha256=([BitConverter]::ToString(
            [Security.Cryptography.SHA256]::Create().ComputeHash(
                [Text.Encoding]::UTF8.GetBytes($xml)
            )
        ).Replace('-','').ToLowerInvariant())
    }
}
$payload = [ordered]@{
    schema_version='honghu.local_task_disabled_evidence.v1'
    checked_at=(Get-Date).ToUniversalTime().ToString('o')
    host=$env:COMPUTERNAME
    tasks=@($observed)
    all_present=(@($observed | Where-Object { -not $_.present }).Count -eq 0)
    all_disabled=(@($observed | Where-Object { $_.enabled }).Count -eq 0)
}
$parent = Split-Path -Parent $Output
if ($parent) { New-Item -ItemType Directory -Force $parent | Out-Null }
$encoding = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($Output,(($payload | ConvertTo-Json -Depth 8)+[Environment]::NewLine),$encoding)
$payload | ConvertTo-Json -Depth 8
