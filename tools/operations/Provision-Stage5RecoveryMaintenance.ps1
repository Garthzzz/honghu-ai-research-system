[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ReleaseDir,
    [Parameter(Mandatory=$true)][string]$SitePackages,
    [Parameter(Mandatory=$true)][ValidatePattern('^\\\\')][string]$OffVmRoot,
    [Parameter(Mandatory=$true)][string]$SmbUser,
    [Parameter(Mandatory=$true)][string]$CredentialBlobPath,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedStorageIdentity,
    [Parameter(Mandatory=$true)][string]$AtRestEncryptionEvidence,
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
foreach ($path in @($ReleaseDir,$SitePackages,$RuntimeCatalog,$SourceArchive,$CredentialBlobPath,$AtRestEncryptionEvidence)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required recovery path is absent: $path" }
}
$python = 'C:\ProgramData\miniconda3\envs\quant\python.exe'
$bootstrap = Join-Path $ReleaseDir 'tools\release\direct_candidate.py'
$plain = New-Secret
$secure = ConvertTo-SecureString $plain -AsPlainText -Force
$account = Get-LocalUser -Name $LocalUser -ErrorAction SilentlyContinue
if ($null -eq $account) {
    New-LocalUser -Name $LocalUser -Password $secure -AccountNeverExpires -PasswordNeverExpires `
        -UserMayNotChangePassword -Description 'Honghu least-privilege off-VM recovery runner' | Out-Null
} else {
    Set-LocalUser -Name $LocalUser -Password $secure -AccountNeverExpires -PasswordNeverExpires
}
$principalName = "$env:COMPUTERNAME\$LocalUser"
if ((Get-LocalGroupMember -Group 'Administrators' -ErrorAction SilentlyContinue).Name -contains $principalName) {
    throw 'Dedicated recovery runner must not be a local administrator.'
}
$credential = [Management.Automation.PSCredential]::new($principalName,$secure)

$transfer = Join-Path $RuntimeDir 'credential-transfer\backup-role.dpapi'
New-Item -ItemType Directory -Force (Split-Path -Parent $transfer) | Out-Null
& $python -I -B -S $bootstrap --site-packages $SitePackages `
    --module tools.operations.backup_credential_transfer export `
    --catalog $RuntimeCatalog --output $transfer | Out-Null
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $transfer -PathType Leaf)) {
    throw 'Backup-role credential export failed.'
}
& icacls.exe $transfer '/inheritance:r' "/grant:r" "$principalName`:(R)" 'SYSTEM:(F)' 'Administrators:(F)' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Backup credential transfer ACL failed.' }
& icacls.exe $CredentialBlobPath "/grant:r" "$principalName`:(R)" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'SMB credential blob ACL failed.' }

$credentialTask = 'HonghuStage5_BackupCredentialBootstrap'
$credentialArgs = @(
    '-I','-B','-S',$bootstrap,'--site-packages',$SitePackages,
    '--module','tools.operations.backup_credential_transfer','import',
    '--source',$transfer,'--catalog',$RuntimeCatalog
) | ForEach-Object { Quote-Arg ([string]$_) }
$bootstrapAction = New-ScheduledTaskAction -Execute $python -Argument ($credentialArgs -join ' ') -WorkingDirectory $ReleaseDir
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
try {
    Register-ScheduledTask -TaskName $credentialTask -Action $bootstrapAction -Settings $settings `
        -User $principalName -Password $plain -RunLevel Limited -Force | Out-Null
    Start-ScheduledTask -TaskName $credentialTask
    $deadline = (Get-Date).AddMinutes(3)
    do { Start-Sleep -Seconds 2; $state=(Get-ScheduledTask $credentialTask).State } `
        while($state -eq 'Running' -and (Get-Date) -lt $deadline)
    $info = Get-ScheduledTaskInfo $credentialTask
    if ($state -eq 'Running' -or $info.LastTaskResult -ne 0 -or (Test-Path $transfer)) {
        throw "Backup credential bootstrap failed: state=$state result=$($info.LastTaskResult)"
    }
} finally {
    Unregister-ScheduledTask $credentialTask -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item $transfer -Force -ErrorAction SilentlyContinue
}

$taskName = 'HonghuStage5_ContinuousWalOffVm'
$output = Join-Path $RuntimeDir 'recovery\continuous_wal_latest.json'
$wrapper = Join-Path $ReleaseDir 'tools\operations\Invoke-Stage5-ContinuousRecovery.ps1'
$powershell = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
$values = @(
    '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$wrapper,
    '-ReleaseDir',$ReleaseDir,'-BootstrapPythonExe',$python,'-SitePackages',$SitePackages,
    '-RuntimeCatalog',$RuntimeCatalog,'-SourceArchive',$SourceArchive,'-OffVmRoot',$OffVmRoot,
    '-ExpectedStorageIdentity',$ExpectedStorageIdentity,'-AtRestEncryptionEvidence',$AtRestEncryptionEvidence,
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
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable><Enabled>false</Enabled><ExecutionTimeLimit>PT4M</ExecutionTimeLimit></Settings>
  <Actions Context="Author"><Exec><Command>$powershell</Command><Arguments>$([Security.SecurityElement]::Escape($argumentString))</Arguments><WorkingDirectory>$ReleaseDir</WorkingDirectory></Exec></Actions>
</Task>
"@
Register-ScheduledTask -TaskName $taskName -Xml $xml -User $principalName -Password $plain -Force | Out-Null
Enable-ScheduledTask $taskName | Out-Null
Start-ScheduledTask $taskName
$deadline=(Get-Date).AddMinutes(4)
do { Start-Sleep -Seconds 3; $state=(Get-ScheduledTask $taskName).State } `
    while($state -eq 'Running' -and (Get-Date) -lt $deadline)
$info=Get-ScheduledTaskInfo $taskName
if ($state -eq 'Running' -or $info.LastTaskResult -ne 0 -or -not (Test-Path $output -PathType Leaf)) {
    Disable-ScheduledTask $taskName | Out-Null
    throw "Initial continuous recovery cycle failed: state=$state result=$($info.LastTaskResult)"
}
[ordered]@{
    schema_version='honghu.stage5_recovery_maintenance.v1'
    task_name=$taskName
    principal=$principalName
    local_administrator=$false
    enabled=$true
    interval_minutes=5
    output_path=$output
    expected_storage_identity=$ExpectedStorageIdentity
    secret_recorded=$false
} | ConvertTo-Json -Depth 8
$plain=$null
