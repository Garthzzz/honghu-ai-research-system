[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ReleaseDir,
    [Parameter(Mandatory=$true)][string]$SitePackages,
    [Parameter(Mandatory=$true)][ValidatePattern('^\\\\')][string]$OffVmRoot,
    [Parameter(Mandatory=$true)][string]$SmbUser,
    [Parameter(Mandatory=$true)][string]$CredentialBlobPath,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedStorageIdentity,
    [Parameter(Mandatory=$true)][string]$AtRestEncryptionEvidence,
    [Parameter(Mandatory=$true)][string]$InitialRecoveryBoundary,
    [string]$RuntimeCatalog = 'D:\honghu-postgresql\runtime\postgresql_runtime.json',
    [string]$SourceArchive = 'D:\honghu-postgresql\wal-archive',
    [string]$RuntimeDir = 'D:\honghu-stage5-runtime',
    [string]$LocalUser = 'HonghuBackupRunner'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function New-Secret([int]$Bytes=32) {
    $raw = New-Object byte[] $Bytes
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($raw) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($raw) -replace '-','') + 'aA1!'
}
function Quote-Arg([string]$Value) {
    if ($Value.Contains('"')) { throw 'Recovery task argument contains an unsafe quote.' }
    return '"' + $Value + '"'
}
function Assert-Administrator {
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Recovery maintenance provisioning requires elevated PowerShell.'
    }
}

Assert-Administrator
if ($env:COMPUTERNAME -ne 'DESKTOP-VGD07J4') { throw 'Recovery runner is bound to the reviewed VM.' }
foreach ($path in @($ReleaseDir,$SitePackages,$RuntimeCatalog,$SourceArchive,$CredentialBlobPath,$AtRestEncryptionEvidence,$InitialRecoveryBoundary)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required recovery path is absent: $path" }
}
$python = 'C:\ProgramData\miniconda3\envs\quant\python.exe'
$bootstrap = Join-Path $ReleaseDir 'tools\release\direct_candidate.py'
$plain = New-Secret
$secure = ConvertTo-SecureString $plain -AsPlainText -Force
$account = Get-LocalUser -Name $LocalUser -ErrorAction SilentlyContinue
if ($null -eq $account) {
    New-LocalUser -Name $LocalUser -Password $secure -AccountNeverExpires -PasswordNeverExpires `
        -UserMayNotChangePassword -Description 'Honghu off-VM recovery runner' | Out-Null
} else {
    Set-LocalUser -Name $LocalUser -Password $secure -AccountNeverExpires `
        -PasswordNeverExpires $true -UserMayChangePassword $false
}
$principalName = "$env:COMPUTERNAME\$LocalUser"
if ((Get-LocalGroupMember -Group 'Administrators' -ErrorAction SilentlyContinue).Name -contains $principalName) {
    throw 'Dedicated recovery runner must not be a local administrator.'
}
& icacls.exe $CredentialBlobPath "/grant:r" "$principalName`:(R)" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'SMB credential blob ACL failed.' }
$taskName = 'HonghuStage5_ContinuousWalOffVm'
$output = Join-Path $RuntimeDir 'recovery\continuous_wal_latest.json'
$wrapper = Join-Path $ReleaseDir 'tools\operations\Invoke-Stage5-ContinuousRecovery.ps1'
$powershell = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
$values = @(
    '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$wrapper,
    '-ReleaseDir',$ReleaseDir,'-BootstrapPythonExe',$python,'-SitePackages',$SitePackages,
    '-RuntimeCatalog',$RuntimeCatalog,'-SourceArchive',$SourceArchive,'-OffVmRoot',$OffVmRoot,
    '-ExpectedStorageIdentity',$ExpectedStorageIdentity,'-AtRestEncryptionEvidence',$AtRestEncryptionEvidence,
    '-InitialRecoveryBoundary',$InitialRecoveryBoundary,
    '-SmbUser',$SmbUser,'-CredentialBlobPath',$CredentialBlobPath,'-OutputPath',$output
)
$argumentString = ($values | ForEach-Object { Quote-Arg ([string]$_) }) -join ' '
$start = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Honghu exact-release five-minute off-VM WAL recovery cycle.</Description></RegistrationInfo>
  <Triggers><TimeTrigger><StartBoundary>$start</StartBoundary><Enabled>true</Enabled><Repetition><Interval>PT5M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition></TimeTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>$principalName</UserId><LogonType>Password</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable><Enabled>false</Enabled><ExecutionTimeLimit>PT15M</ExecutionTimeLimit></Settings>
  <Actions Context="Author"><Exec><Command>$powershell</Command><Arguments>$([Security.SecurityElement]::Escape($argumentString))</Arguments><WorkingDirectory>$ReleaseDir</WorkingDirectory></Exec></Actions>
</Task>
"@
Register-ScheduledTask -TaskName $taskName -Xml $xml -User $principalName -Password $plain -Force | Out-Null
Enable-ScheduledTask $taskName | Out-Null
$before=Get-ScheduledTaskInfo $taskName
Start-ScheduledTask $taskName
$deadline=(Get-Date).AddMinutes(15)
do {
    Start-Sleep -Seconds 3
    $state=(Get-ScheduledTask $taskName).State
    $info=Get-ScheduledTaskInfo $taskName
    $ran=($info.LastRunTime -gt $before.LastRunTime)
} while(((-not $ran) -or $state -eq 'Running') -and (Get-Date) -lt $deadline)
if (-not $ran -or $state -eq 'Running' -or $info.LastTaskResult -ne 0 -or -not (Test-Path $output -PathType Leaf)) {
    Disable-ScheduledTask $taskName | Out-Null
    throw "Initial continuous recovery cycle failed: state=$state result=$($info.LastTaskResult)"
}
[ordered]@{
    schema_version='honghu.stage5_recovery_maintenance.v1'
    task_name=$taskName
    principal=$principalName
    local_administrator=$false
    database_credential_required=$false
    database_business_write_possible=$false
    archive_timeout_required=$true
    maximum_archive_age_seconds=900
    execution_time_limit_minutes=15
    enabled=$true
    interval_minutes=5
    output_path=$output
    expected_storage_identity=$ExpectedStorageIdentity
    secret_recorded=$false
} | ConvertTo-Json -Depth 8
$plain=$null
