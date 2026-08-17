[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ReleaseDir,
    [Parameter(Mandatory=$true)][string]$SitePackages,
    [string]$RuntimeCatalog = 'D:\honghu-postgresql\runtime\postgresql_runtime.json',
    [string]$RuntimeDir = 'D:\honghu-stage5-runtime',
    [string]$DataRoot = 'C:\industry_demo\data',
    [string]$ContentRoot = 'C:\industry_demo',
    [string]$LocalUser = 'HonghuTaskRunner'
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
    if ($Value.Contains('"')) { throw 'Provisioning argument contains an unsafe quote.' }
    return '"' + $Value + '"'
}
function Assert-Administrator {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Task runner provisioning requires elevated PowerShell.'
    }
}

Assert-Administrator
$computer = $env:COMPUTERNAME
if ($computer -ne 'DESKTOP-VGD07J4') { throw 'Task runner provisioning is bound to the reviewed VM.' }
foreach ($path in @($ReleaseDir,$SitePackages,$RuntimeCatalog,$DataRoot,$ContentRoot)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required provisioning path is absent: $path" }
}
$existingEnabled = @(Get-ScheduledTask -TaskName 'IndustryDemo_*' -ErrorAction SilentlyContinue | Where-Object { $_.Settings.Enabled })
if ($existingEnabled.Count -gt 0) { throw 'Refusing credential rotation while a production task is enabled.' }

$plain = New-Secret
$secure = ConvertTo-SecureString $plain -AsPlainText -Force
$account = Get-LocalUser -Name $LocalUser -ErrorAction SilentlyContinue
if ($null -eq $account) {
    New-LocalUser -Name $LocalUser -Password $secure -AccountNeverExpires -PasswordNeverExpires `
        -UserMayNotChangePassword `
        -Description 'Honghu PostgreSQL task runner' | Out-Null
} else {
    Set-LocalUser -Name $LocalUser -Password $secure -AccountNeverExpires -PasswordNeverExpires $true
}
if ((Get-LocalGroupMember -Group 'Administrators' -ErrorAction SilentlyContinue).Name -contains "$computer\$LocalUser") {
    throw 'Dedicated task runner must not be a local administrator.'
}
$credential = New-Object Management.Automation.PSCredential("$computer\$LocalUser", $secure)
$python = 'C:\ProgramData\miniconda3\envs\quant\python.exe'
$bootstrap = Join-Path $ReleaseDir 'tools\release\direct_candidate.py'
$manifest = Join-Path $ReleaseDir 'config\operations\production_tasks.json'
$registry = Join-Path $ReleaseDir 'config\migration\cutover_unit_registry.json'
$migrationEvidence = Join-Path $RuntimeDir 'evidence\stage5_migration_application.json'
$servicePreflightEvidence = Join-Path $RuntimeDir 'evidence\production_task_service_preflight.json'
foreach ($path in @($bootstrap,$manifest,$registry,(Join-Path $ReleaseDir 'RELEASE_MANIFEST.json'))) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Exact-release task dependency is absent: $path"
    }
}
foreach ($directory in @(
    $RuntimeDir,
    (Join-Path $RuntimeDir 'locks'),
    (Join-Path $RuntimeDir 'task_logs'),
    (Join-Path $RuntimeDir 'evidence'),
    (Join-Path $RuntimeDir 'credential-transfer')
)) {
    New-Item -ItemType Directory -Force $directory | Out-Null
    & icacls.exe $directory "/grant:r" "$computer\$LocalUser`:(OI)(CI)(M)" 'SYSTEM:(F)' 'Administrators:(F)' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Task runtime ACL failed: $directory" }
}
$readOnlyRoots = @(
    $ReleaseDir,
    $SitePackages,
    $DataRoot,
    $ContentRoot,
    (Split-Path -Parent $RuntimeCatalog)
)
foreach ($readOnlyRoot in $readOnlyRoots) {
    if (-not (Test-Path -LiteralPath $readOnlyRoot -PathType Container)) {
        throw "Read-only task root absent: $readOnlyRoot"
    }
    # Authenticated Users has Modify on several inherited project roots.  A
    # generic (W) deny also blocks Python script reads on Windows, so fence
    # only create/write-data and append/add-subdirectory for this principal.
    & icacls.exe $readOnlyRoot '/remove:d' "$computer\$LocalUser" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Old task deny ACL removal failed: $readOnlyRoot" }
    & icacls.exe $readOnlyRoot '/deny' "$computer\$LocalUser`:(OI)(CI)(WD,AD)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Read-only task ACL failed: $readOnlyRoot" }
}

# Expand the control-plane schema and bind disabled definitions before any
# service-account task can be registered.  This does not run a business task.
& $python -I -B -S $bootstrap --site-packages $SitePackages `
    --module tools.migration.stage4_apply_postgresql_migrations `
    --repo-root $ReleaseDir --runtime $RuntimeCatalog `
    --migration '0013_stage5_task_operations.sql' `
    --migration '0014_stage5_delegated_unit_writers.sql' `
    --migration '0015_stage5_initial_overlay_revision.sql' `
    --migration '0016_stage5_bounded_mutation_batch_result.sql' `
    --migration '0017_stage5_set_based_sentiment_delete_batch.sql' `
    --migration '0018_stage5_recovery_checkpoint_read_grant.sql' `
    --output $migrationEvidence | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Stage5 expand migration application failed.' }
& $python -I -B -S $bootstrap --site-packages $SitePackages `
    --module tools.operations.task_runner register `
    --manifest $manifest --postgres-runtime-catalog $RuntimeCatalog `
    --release-dir $ReleaseDir | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Disabled production task definition registration failed.' }

$transfer = Join-Path $RuntimeDir 'credential-transfer\task-role-credentials.dpapi'
New-Item -ItemType Directory -Force (Split-Path -Parent $transfer) | Out-Null

# Export from the interactive operator vault.  The file is DPAPI LocalMachine
# encrypted before it touches disk and then receives a service-account-only ACL.
& $python -I -B -S $bootstrap --site-packages $SitePackages `
    --module tools.operations.task_credential_transfer export `
    --catalog $RuntimeCatalog --output $transfer | Out-Null
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $transfer -PathType Leaf)) {
    throw 'Reviewed task-role credential export failed.'
}
& icacls.exe $transfer '/inheritance:r' "/grant:r" "$computer\$LocalUser`:(M)" 'SYSTEM:(F)' 'Administrators:(F)' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Credential transfer ACL failed.' }

$bootstrapTask = 'HonghuStage5_CredentialBootstrap'
$values = @(
    '-I','-B','-S',$bootstrap,'--site-packages',$SitePackages,
    '--module','tools.operations.task_service_preflight',
    '--credential-transfer',$transfer,
    '--release-dir',$ReleaseDir,
    '--locked-site-packages',$SitePackages,
    '--manifest',$manifest,
    '--runtime-catalog',$RuntimeCatalog,
    '--registry',$registry,
    '--runtime-dir',$RuntimeDir,
    '--data-root',$DataRoot,
    '--content-root',$ContentRoot,
    '--expected-principal',"$computer\$LocalUser",
    '--output',$servicePreflightEvidence
)
$arguments = ($values | ForEach-Object { Quote-Arg ([string]$_) }) -join ' '
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $ReleaseDir
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
try {
    Register-ScheduledTask -TaskName $bootstrapTask -Action $action -Settings $settings `
        -User "$computer\$LocalUser" -Password $plain -RunLevel Limited -Force | Out-Null
    Start-ScheduledTask -TaskName $bootstrapTask
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 2
        $state = (Get-ScheduledTask -TaskName $bootstrapTask).State
    } while ($state -eq 'Running' -and (Get-Date) -lt $deadline)
    $info = Get-ScheduledTaskInfo -TaskName $bootstrapTask
    if (
        $state -eq 'Running' -or $info.LastTaskResult -ne 0 -or
        (Test-Path -LiteralPath $transfer) -or
        -not (Test-Path -LiteralPath $servicePreflightEvidence -PathType Leaf)
    ) {
        throw "Service-account access/credential/PostgreSQL preflight failed: state=$state result=$($info.LastTaskResult)"
    }
    $servicePreflight = Get-Content -Raw -LiteralPath $servicePreflightEvidence | ConvertFrom-Json
    $releaseIdentity = Get-Content -Raw -LiteralPath (Join-Path $ReleaseDir 'RELEASE_MANIFEST.json') | ConvertFrom-Json
    $manifestSha = (Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant()
    if (
        $servicePreflight.schema_version -ne 'honghu.production_task_service_preflight.v1' -or
        -not [bool]$servicePreflight.overall_verified -or
        [bool]$servicePreflight.secret_recorded -or
        $servicePreflight.application_commit_sha -ne $releaseIdentity.commit_sha -or
        $servicePreflight.task_manifest_sha256 -ne $manifestSha -or
        $servicePreflight.principal -ne "$computer\$LocalUser" -or
        -not [bool]$servicePreflight.access_verified -or
        -not [bool]$servicePreflight.postgresql_roles_verified -or
        @($servicePreflight.postgresql_roles).Count -ne 4
    ) {
        throw 'Service-account preflight evidence does not match the exact release contract.'
    }
} finally {
    Unregister-ScheduledTask -TaskName $bootstrapTask -Confirm:$false -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $transfer) { Remove-Item -LiteralPath $transfer -Force }
}

& (Join-Path $ReleaseDir 'tools\operations\Install-ProductionTasks.ps1') `
    -Mode InstallDisabled -ReleaseDir $ReleaseDir -SitePackages $SitePackages `
    -RuntimeCatalog $RuntimeCatalog -RuntimeDir $RuntimeDir `
    -DataRoot $DataRoot -ContentRoot $ContentRoot -TaskCredential $credential `
    -Manifest $manifest -Registry $registry
if ($LASTEXITCODE -ne 0) { throw 'Disabled production task installation failed.' }

[ordered]@{
    schema_version='honghu.production_task_service_account.v1'
    checked_at=(Get-Date).ToUniversalTime().ToString('o')
    principal="$computer\$LocalUser"
    local_administrator=$false
    credential_store='Windows Credential Manager under dedicated principal'
    credential_roles=4
    encrypted_transfer_removed=$true
    service_account_preflight_verified=$true
    service_account_preflight_sha256=(Get-FileHash -LiteralPath $servicePreflightEvidence -Algorithm SHA256).Hash.ToLowerInvariant()
    tasks_installed_disabled=7
    secret_recorded=$false
} | ConvertTo-Json -Depth 8

$plain = $null
