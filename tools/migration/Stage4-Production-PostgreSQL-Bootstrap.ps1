[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CommitSha,
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$PostgreSQLArchive,
    [Parameter(Mandatory = $true)][string]$BootstrapPythonExe,
    [string]$ConfigPath = 'config\migration\stage4_production_postgresql_bootstrap.template.json',
    [string]$ProductionRoot = 'C:\industry_demo',
    [string]$InstallRoot = 'D:\honghu-postgresql',
    [string]$OffVmRoot = '',
    [string]$ExpectedOffVmStorageIdentity = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function ConvertTo-HonghuSecretHex {
    param([int]$ByteCount = 32)
    $bytes = New-Object byte[] $ByteCount
    # Windows PowerShell 5.1 runs on .NET Framework, where the static
    # RandomNumberGenerator.Fill API is unavailable.  Use the instance API so
    # the same CSPRNG contract works on both the VM and newer PowerShell/.NET.
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    return ([System.BitConverter]::ToString($bytes) -replace '-', '').ToLowerInvariant()
}

function Get-HonghuSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-HonghuJsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Value
    )
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force $parent | Out-Null
    $temp = "$Path.$([guid]::NewGuid().ToString('N')).tmp"
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $Path -Force
}

function Invoke-HonghuCredential {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('set', 'verify', 'delete')][string]$Action,
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][string]$Account,
        [string]$Password = ''
    )
    $payload = @{ action = $Action; service = $Service; account = $Account }
    if ($Action -eq 'set') { $payload.password = $Password }
    $json = $payload | ConvertTo-Json -Compress
    $helper = Join-Path $RepoRoot 'tools\migration\stage4_credential_helper.py'
    $result = $json | & $BootstrapPythonExe -I -B $helper
    if ($LASTEXITCODE -ne 0) { throw "Credential Manager $Action failed for $Service/$Account" }
    return $result | ConvertFrom-Json
}

function Invoke-HonghuPsql {
    param(
        [Parameter(Mandatory = $true)][string]$Psql,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Password,
        [Parameter(Mandatory = $true)][string]$Sql,
        [string[]]$Variables = @()
    )
    $oldPassword = $env:PGPASSWORD
    try {
        $env:PGPASSWORD = $Password
        $arguments = @('-X', '--set', 'ON_ERROR_STOP=1', '--host', '127.0.0.1', '--port', '55440', '--username', 'honghu_admin', '--dbname', $Database)
        foreach ($variable in $Variables) { $arguments += @('--set', $variable) }
        $output = $Sql | & $Psql @arguments 2>&1
        if ($LASTEXITCODE -ne 0) { throw "psql failed without changing application authority: $($output -join [Environment]::NewLine)" }
        return $output
    }
    finally {
        $env:PGPASSWORD = $oldPassword
    }

}

function Test-HonghuRoleCredential {
    param(
        [Parameter(Mandatory = $true)][string]$Psql,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$User,
        [Parameter(Mandatory = $true)][string]$Password
    )
    $oldPassword = $env:PGPASSWORD
    try {
        $env:PGPASSWORD = $Password
        # The production listener is intentionally IPv4-loopback only.  On
        # Windows, localhost may resolve to ::1 first and psql can fail without
        # reaching 127.0.0.1, so every lifecycle probe uses the exact reviewed
        # listener address rather than relying on resolver order.
        & $Psql -X --set ON_ERROR_STOP=1 --host 127.0.0.1 --port 55440 `
            --username $User --dbname $Database --no-password `
            --command 'SELECT 1;' 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    }
    finally { $env:PGPASSWORD = $oldPassword }
}

function Assert-HonghuAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Stage4 PostgreSQL bootstrap must run from an elevated PowerShell.'
    }
}

function Invoke-HonghuFailedBootstrapCleanup {
    param(
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$LaunchId,
        [Parameter(Mandatory = $true)][string]$CommitSha,
        [string[]]$CredentialEntries = @()
    )
    $result = [ordered]@{
        attempted = $true
        launch_id = $LaunchId
        service_removed = $false
        listener_released = $false
        credentials_removed = @()
        quarantine_path = $null
        reasons = @()
    }
    $identityPath = Join-Path $InstallRoot 'runtime\bootstrap_install_identity.json'
    if (-not (Test-Path -LiteralPath $identityPath -PathType Leaf)) {
        throw 'Refusing failed-bootstrap cleanup without an install identity.'
    }
    $identity = Get-Content -Raw -LiteralPath $identityPath | ConvertFrom-Json
    if ($identity.launch_id -ne $LaunchId -or $identity.commit_sha -ne $CommitSha -or $identity.completed -eq $true) {
        throw 'Refusing failed-bootstrap cleanup for a foreign or completed install.'
    }
    $expectedData = [System.IO.Path]::GetFullPath((Join-Path $InstallRoot 'data'))
    $service = Get-CimInstance Win32_Service -Filter "Name='HonghuPostgreSQL17'" -ErrorAction SilentlyContinue
    if ($null -ne $service) {
        if ([string]$service.PathName -notlike "*$expectedData*") {
            throw 'Refusing to remove a PostgreSQL service whose data path is outside this launch.'
        }
        if ($service.State -ne 'Stopped') {
            Stop-Service -Name 'HonghuPostgreSQL17' -Force -ErrorAction Stop
            $deadline = (Get-Date).AddSeconds(60)
            do {
                Start-Sleep -Milliseconds 500
                $service = Get-CimInstance Win32_Service -Filter "Name='HonghuPostgreSQL17'" -ErrorAction SilentlyContinue
            } until ($null -eq $service -or $service.State -eq 'Stopped' -or (Get-Date) -gt $deadline)
            if ($null -ne $service -and $service.State -ne 'Stopped') {
                throw 'Failed-bootstrap PostgreSQL service did not stop.'
            }
        }
        & sc.exe delete HonghuPostgreSQL17 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Failed-bootstrap PostgreSQL service could not be deleted.' }
        $deadline = (Get-Date).AddSeconds(60)
        do {
            Start-Sleep -Milliseconds 500
            $service = Get-Service -Name 'HonghuPostgreSQL17' -ErrorAction SilentlyContinue
        } until ($null -eq $service -or (Get-Date) -gt $deadline)
        if ($null -ne $service) { throw 'Failed-bootstrap PostgreSQL service deletion was not observed.' }
    }
    $result.service_removed = $true
    if (@(Get-NetTCPConnection -LocalPort 55440 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) {
        throw 'Refusing to quarantine failed bootstrap while port 55440 still has a listener.'
    }
    $result.listener_released = $true
    foreach ($entry in $CredentialEntries) {
        $parts = $entry -split '\|', 2
        try {
            Invoke-HonghuCredential -Action delete -Service $parts[0] -Account $parts[1] | Out-Null
            $result.credentials_removed += $entry
        }
        catch {
            $result.reasons += "credential cleanup failed for $entry"
        }
    }
    $quarantine = "$InstallRoot.failed.$LaunchId"
    if (Test-Path -LiteralPath $quarantine) {
        throw 'Failed-bootstrap quarantine destination already exists.'
    }
    Move-Item -LiteralPath $InstallRoot -Destination $quarantine
    $result.quarantine_path = $quarantine
    return $result
}

$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$PostgreSQLArchive = (Resolve-Path -LiteralPath $PostgreSQLArchive).Path
$BootstrapPythonExe = (Resolve-Path -LiteralPath $BootstrapPythonExe).Path
$BootstrapBasePythonExe = $BootstrapPythonExe
if (-not [System.IO.Path]::IsPathRooted($ConfigPath)) { $ConfigPath = Join-Path $RepoRoot $ConfigPath }
$ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path
$RuntimeRoot = Join-Path $InstallRoot 'runtime'
$EvidenceRoot = Join-Path $RuntimeRoot 'evidence'
$PrimaryEvidencePath = Join-Path $EvidenceRoot 'bootstrap_primary.json'
$FinalEvidencePath = Join-Path $EvidenceRoot 'bootstrap_final.json'
$RuntimeConfigPath = Join-Path $RuntimeRoot 'postgresql_runtime.json'
$InstallIdentityPath = Join-Path $RuntimeRoot 'bootstrap_install_identity.json'
$LaunchId = [guid]::NewGuid().ToString('N')
$CleanupRequired = $false
$StagingRoot = $null
$CredentialEntries = New-Object System.Collections.Generic.List[string]

# A completed, exact-identity install is re-entered only through read-only
# verification.  A partial or foreign install remains fail-closed.
$existingService = Get-Service -Name 'HonghuPostgreSQL17' -ErrorAction SilentlyContinue
if ($null -ne $existingService -or (Test-Path -LiteralPath $InstallRoot)) {
    if (-not (Test-Path -LiteralPath $InstallIdentityPath -PathType Leaf)) {
        throw 'Existing Stage 4 install has no auditable completion identity.'
    }
    $existingIdentity = Get-Content -Raw -LiteralPath $InstallIdentityPath | ConvertFrom-Json
    if ($existingIdentity.completed -ne $true -or $existingIdentity.commit_sha -ne $CommitSha) {
        throw 'Existing Stage 4 install is partial, foreign, or belongs to another commit.'
    }
    $completedPython = [string]$existingIdentity.python_runtime_executable
    if (-not $completedPython -or -not (Test-Path -LiteralPath $completedPython -PathType Leaf)) {
        throw 'Completed Stage 4 install has no verified isolated Python runtime.'
    }
    $BootstrapPythonExe = (Resolve-Path -LiteralPath $completedPython).Path
    Assert-HonghuAdministrator
    if ((git -C $RepoRoot rev-parse HEAD).Trim().ToLowerInvariant() -ne $CommitSha) {
        throw 'Repo checkout is not the completed install commit.'
    }
    $resumeInput = Join-Path $EvidenceRoot 'bootstrap_resume_input_identity.json'
    & $BootstrapPythonExe -I -B (Join-Path $RepoRoot 'tools\migration\stage4_production_bootstrap_contract.py') `
        --config $ConfigPath --repo-root $RepoRoot --commit-sha $CommitSha `
        --archive $PostgreSQLArchive --output $resumeInput
    if ($LASTEXITCODE -ne 0) { throw 'Completed-install input identity verification failed.' }
    if ((Get-HonghuSha256 $ConfigPath) -ne $existingIdentity.bootstrap_config_sha256 -or
        (Get-HonghuSha256 $PostgreSQLArchive) -ne $existingIdentity.postgresql_archive_sha256) {
        throw 'Completed-install archive/config identity changed.'
    }
    $resumeRuntimeVerification = Join-Path $EvidenceRoot ("python_runtime_resume_verify-{0}.json" -f $LaunchId)
    & $BootstrapPythonExe -I -B (Join-Path $RepoRoot 'tools\release\runtime_environment.py') `
        --lockfile (Join-Path $RepoRoot 'requirements.lock.txt') |
        Set-Content -LiteralPath $resumeRuntimeVerification -Encoding UTF8
    if ($LASTEXITCODE -ne 0) { throw 'Completed-install isolated Python runtime verification failed.' }
    $resumeVerify = Join-Path $EvidenceRoot ("production_postgresql_resume_verify-{0}.json" -f $LaunchId)
    & $BootstrapPythonExe -I -B (Join-Path $RepoRoot 'tools\migration\stage4_isolated_entry.py') `
        --repo-root $RepoRoot --module tools.migration.stage4_production_verify `
        --repo-root $RepoRoot --runtime $RuntimeConfigPath `
        --application-commit-sha $CommitSha --output $resumeVerify
    if ($LASTEXITCODE -ne 0) { throw 'Completed-install production verification failed.' }
    [ordered]@{
        ok = $true
        status = 'completed_install_verified'
        commit_sha = $CommitSha
        service_name = 'HonghuPostgreSQL17'
        production_authority = 'sqlite_transition'
        s2_or_s3_entered = $false
        verification_evidence = $resumeVerify
    } | ConvertTo-Json -Depth 8
    exit 0
}

# A fresh launch records pre-install failures outside InstallRoot.  InstallRoot
# must remain absent until host/archive checks pass and an auditable install
# identity can be written.  Once that identity exists, the evidence is moved
# under the owned runtime tree.
$PreInstallEvidenceRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("honghu-stage4-preflight-{0}" -f $LaunchId)
$EvidenceRoot = $PreInstallEvidenceRoot
$PrimaryEvidencePath = Join-Path $EvidenceRoot 'bootstrap_primary.json'
$FinalEvidencePath = Join-Path $EvidenceRoot 'bootstrap_final.json'

$primary = [ordered]@{
    schema_version = 'honghu.stage4_production_postgresql_bootstrap_evidence.v1'
    started_at = (Get-Date).ToUniversalTime().ToString('o')
    commit_sha = $CommitSha
    status = 'running'
    phases = @()
    blockers = @()
    production_authority_changed = $false
    s2_or_s3_entered = $false
    formal_business_mutation_written = $false
    launch_id = $LaunchId
}

try {
    Assert-HonghuAdministrator
    if ((git -C $RepoRoot rev-parse HEAD).Trim().ToLowerInvariant() -ne $CommitSha) { throw 'Repo checkout is not the approved exact commit.' }
    if (git -C $RepoRoot status --porcelain) { throw 'Repo checkout is dirty.' }
    & $BootstrapPythonExe -c "import sys; assert sys.version_info[:2] == (3,10)"
    if ($LASTEXITCODE -ne 0) { throw 'Bootstrap Python is not 3.10.' }

    New-Item -ItemType Directory -Force $EvidenceRoot | Out-Null
    $InputIdentityPath = Join-Path $EvidenceRoot 'bootstrap_input_identity.json'
    & $BootstrapPythonExe -I -B (Join-Path $RepoRoot 'tools\migration\stage4_production_bootstrap_contract.py') `
        --config $ConfigPath --repo-root $RepoRoot --commit-sha $CommitSha `
        --archive $PostgreSQLArchive --output $InputIdentityPath
    if ($LASTEXITCODE -ne 0) { throw 'Bootstrap contract preflight failed.' }
    $inputIdentity = Get-Content -Raw -LiteralPath $InputIdentityPath | ConvertFrom-Json
    $bootstrapConfig = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
    if ([System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\') -ne [System.IO.Path]::GetFullPath($bootstrapConfig.postgresql.install_root).TrimEnd('\')) {
        throw 'InstallRoot differs from the reviewed bootstrap configuration.'
    }
    if ([System.IO.Path]::GetFullPath($ProductionRoot).TrimEnd('\') -ne [System.IO.Path]::GetFullPath($bootstrapConfig.source.production_root).TrimEnd('\')) {
        throw 'ProductionRoot differs from the reviewed bootstrap configuration.'
    }
    $primary.phases += @{ name = 'contract_preflight'; result = 'pass'; identity = $inputIdentity.input_identity_sha256 }

    $route = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot 'config\migration\user_content_backend_route.json') | ConvertFrom-Json
    $health = Invoke-RestMethod 'http://127.0.0.1:8080/api/health' -TimeoutSec 10
    if (-not $health.ok) { throw 'Existing production Viewer 8080 is not healthy.' }
    foreach ($port in 55440, 55441) {
        if (@(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).Count -gt 0) {
            throw "Approved PostgreSQL port $port is already in use."
        }
    }
    $drive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($InstallRoot).Substring(0, 1))
    $liveDatabaseBytes = [int64]0
    foreach ($databaseName in 'research.db','financial.db','opportunity_lens.db','sentiment.db') {
        $databasePath = Join-Path (Join-Path $ProductionRoot 'data') $databaseName
        if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) {
            throw "Required live SQLite source is missing: $databaseName"
        }
        $liveDatabaseBytes += (Get-Item -LiteralPath $databasePath).Length
    }
    $requiredFreeBytes = [Math]::Max([int64](20GB), [int64](10 * $liveDatabaseBytes + (Get-Item -LiteralPath $PostgreSQLArchive).Length))
    if ($drive.Free -lt $requiredFreeBytes) {
        throw "PostgreSQL target free space is below the reviewed staging/backup/restore envelope: $requiredFreeBytes bytes."
    }
    $service = Get-Service -Name 'HonghuPostgreSQL17' -ErrorAction SilentlyContinue
    if ($null -ne $service) { throw 'HonghuPostgreSQL17 already exists; use the audited resume/verify path rather than reinstalling.' }
    if (Test-Path -LiteralPath $InstallRoot) {
        $existing = @(Get-ChildItem -LiteralPath $InstallRoot -Force -ErrorAction SilentlyContinue)
        if ($existing.Count -gt 0) { throw 'InstallRoot is not empty and has no verified completed bootstrap identity.' }
    }
    $primary.phases += @{ name = 'host_preflight'; result = 'pass'; viewer_8080 = $true; free_bytes = [int64]$drive.Free; required_free_bytes = $requiredFreeBytes; live_sqlite_bytes = $liveDatabaseBytes }
    Write-HonghuJsonAtomic -Path $PrimaryEvidencePath -Value $primary

    $StagingRoot = "$InstallRoot.staging.$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Force $StagingRoot | Out-Null
    Expand-Archive -LiteralPath $PostgreSQLArchive -DestinationPath $StagingRoot -Force
    $PgRoot = Join-Path $StagingRoot 'pgsql'
    $Bin = Join-Path $PgRoot 'bin'
    foreach ($name in 'postgres.exe','initdb.exe','pg_ctl.exe','psql.exe','pg_basebackup.exe','pg_controldata.exe') {
        if (-not (Test-Path -LiteralPath (Join-Path $Bin $name) -PathType Leaf)) { throw "Approved PostgreSQL archive lacks $name" }
    }
    $versionText = (& (Join-Path $Bin 'postgres.exe') --version | Out-String).Trim()
    if ($versionText -notmatch 'PostgreSQL\) 17\.10$') { throw "Unexpected PostgreSQL binary version: $versionText" }
    New-Item -ItemType Directory -Force $InstallRoot | Out-Null
    $CleanupRequired = $true
    $InstallIdentity = [ordered]@{
        schema_version = 'honghu.stage4_postgresql_install_identity.v1'
        launch_id = $LaunchId
        commit_sha = $CommitSha
        bootstrap_config_sha256 = Get-HonghuSha256 $ConfigPath
        postgresql_archive_sha256 = Get-HonghuSha256 $PostgreSQLArchive
        python_lock_sha256 = Get-HonghuSha256 (Join-Path $RepoRoot 'requirements.lock.txt')
        python_runtime_executable = (Join-Path $InstallRoot 'python-env\Scripts\python.exe')
        created_at = (Get-Date).ToUniversalTime().ToString('o')
        completed = $false
    }
    Write-HonghuJsonAtomic -Path $InstallIdentityPath -Value $InstallIdentity
    $FinalInstallEvidenceRoot = Join-Path $RuntimeRoot 'evidence'
    New-Item -ItemType Directory -Force $FinalInstallEvidenceRoot | Out-Null
    foreach ($preInstallEvidence in @(Get-ChildItem -LiteralPath $PreInstallEvidenceRoot -File -ErrorAction SilentlyContinue)) {
        Move-Item -LiteralPath $preInstallEvidence.FullName -Destination (Join-Path $FinalInstallEvidenceRoot $preInstallEvidence.Name) -Force
    }
    Remove-Item -LiteralPath $PreInstallEvidenceRoot -Recurse -Force -ErrorAction SilentlyContinue
    $EvidenceRoot = $FinalInstallEvidenceRoot
    $PrimaryEvidencePath = Join-Path $EvidenceRoot 'bootstrap_primary.json'
    $FinalEvidencePath = Join-Path $EvidenceRoot 'bootstrap_final.json'
    Write-HonghuJsonAtomic -Path $PrimaryEvidencePath -Value $primary
    Move-Item -LiteralPath $PgRoot -Destination (Join-Path $InstallRoot 'pgsql')
    Remove-Item -LiteralPath $StagingRoot -Recurse -Force
    $PgRoot = Join-Path $InstallRoot 'pgsql'
    $Bin = Join-Path $PgRoot 'bin'
    $DataDir = Join-Path $InstallRoot 'data'
    $WalDir = Join-Path $InstallRoot 'wal'
    $WalArchive = Join-Path $InstallRoot 'wal-archive'
    $BackupRoot = Join-Path $InstallRoot 'backup'
    New-Item -ItemType Directory -Force $WalDir, $WalArchive, $BackupRoot, $RuntimeRoot | Out-Null

    # The pre-existing quant interpreter is only a trusted Python 3.10
    # bootstrap. Never add packages to it. All Stage 4 modules run in a
    # hash-pinned environment owned by this exact installation.
    $PythonEnv = Join-Path $InstallRoot 'python-env'
    $ExecutionPythonExe = Join-Path $PythonEnv 'Scripts\python.exe'
    & $BootstrapBasePythonExe -I -B -m venv $PythonEnv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ExecutionPythonExe -PathType Leaf)) {
        throw 'Failed to create the isolated Stage 4 Python environment.'
    }
    & $ExecutionPythonExe -I -B -m pip install --disable-pip-version-check `
        --require-hashes --requirement (Join-Path $RepoRoot 'requirements.lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Hash-pinned Stage 4 Python environment installation failed.' }
    $PythonRuntimeEvidence = Join-Path $EvidenceRoot 'python_runtime_verification.json'
    & $ExecutionPythonExe -I -B (Join-Path $RepoRoot 'tools\release\runtime_environment.py') `
        --lockfile (Join-Path $RepoRoot 'requirements.lock.txt') |
        Set-Content -LiteralPath $PythonRuntimeEvidence -Encoding UTF8
    if ($LASTEXITCODE -ne 0) { throw 'Isolated Stage 4 Python runtime verification failed.' }
    $BootstrapPythonExe = (Resolve-Path -LiteralPath $ExecutionPythonExe).Path
    $primary.phases += @{
        name = 'isolated_python_runtime'
        result = 'pass'
        executable = $BootstrapPythonExe
        lock_sha256 = Get-HonghuSha256 (Join-Path $RepoRoot 'requirements.lock.txt')
        evidence_sha256 = Get-HonghuSha256 $PythonRuntimeEvidence
    }
    Write-HonghuJsonAtomic -Path $PrimaryEvidencePath -Value $primary

    $adminPassword = ConvertTo-HonghuSecretHex
    $passwordFile = Join-Path $RuntimeRoot ("initdb-{0}.pw" -f [guid]::NewGuid().ToString('N'))
    try {
        Set-Content -LiteralPath $passwordFile -Value $adminPassword -NoNewline -Encoding ascii
        # Never inherit the Windows host's legacy code-page locale.  The
        # PostgreSQL 17 builtin provider gives a portable UTF-8 contract.
        # Capture native stderr and judge the command by its exit code so a
        # localized warning cannot become a PowerShell terminating error.
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $initdbOutput = & (Join-Path $Bin 'initdb.exe') `
                --pgdata $DataDir --waldir $WalDir --username honghu_admin `
                --auth-host scram-sha-256 --auth-local scram-sha-256 `
                --encoding $bootstrapConfig.postgresql.encoding `
                --locale-provider $bootstrapConfig.postgresql.locale_provider `
                --builtin-locale $bootstrapConfig.postgresql.builtin_locale `
                --text-search-config $bootstrapConfig.postgresql.text_search_config `
                --data-checksums --pwfile $passwordFile 2>&1
            $initdbExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($initdbExitCode -ne 0) { throw 'initdb failed.' }
        $primary.phases += @{
            name = 'cluster_initialization_contract'
            result = 'pass'
            encoding = $bootstrapConfig.postgresql.encoding
            locale_provider = $bootstrapConfig.postgresql.locale_provider
            builtin_locale = $bootstrapConfig.postgresql.builtin_locale
            text_search_config = $bootstrapConfig.postgresql.text_search_config
            data_checksums = [bool]$bootstrapConfig.postgresql.data_checksums
            native_exit_code = $initdbExitCode
            native_output_recorded = $false
        }
        Write-HonghuJsonAtomic -Path $PrimaryEvidencePath -Value $primary
    }
    finally {
        if (Test-Path -LiteralPath $passwordFile) { Remove-Item -LiteralPath $passwordFile -Force }
    }

    $TlsDir = Join-Path $InstallRoot 'tls'
    New-Item -ItemType Directory -Force $TlsDir | Out-Null
    $TlsEvidencePath = Join-Path $EvidenceRoot 'tls_certificate.json'
    & $BootstrapPythonExe -I -B (Join-Path $RepoRoot 'tools\migration\stage4_tls_certificate.py') `
        --output-dir $TlsDir --evidence $TlsEvidencePath --valid-days 825
    if ($LASTEXITCODE -ne 0) { throw 'TLS certificate generation failed.' }
    $primary.phases += @{
        name = 'tls_certificate_generation'
        result = 'pass'
        evidence_sha256 = Get-HonghuSha256 $TlsEvidencePath
        private_key_recorded = $false
    }
    Write-HonghuJsonAtomic -Path $PrimaryEvidencePath -Value $primary

    $ArchiveCommand = Join-Path $RuntimeRoot 'archive_wal.cmd'
    "@echo off`r`nif exist `"$WalArchive\%~nx1`" exit /b 0`r`ncopy /b /y `"%~1`" `"$WalArchive\%~nx1`" >nul`r`n" | Set-Content -LiteralPath $ArchiveCommand -Encoding ascii
    Add-Content -LiteralPath (Join-Path $DataDir 'postgresql.conf') -Encoding ascii -Value @"

# Honghu Stage 4 production bootstrap; application authority remains SQLite.
listen_addresses = '127.0.0.1'
port = 55440
ssl = on
ssl_cert_file = '$((Join-Path $TlsDir 'server.crt') -replace '\\','/')'
ssl_key_file = '$((Join-Path $TlsDir 'server.key') -replace '\\','/')'
password_encryption = 'scram-sha-256'
wal_level = 'replica'
archive_mode = on
archive_command = '"$($ArchiveCommand -replace '\\','\\\\')" "%p"'
max_wal_senders = 5
logging_collector = on
log_directory = '$((Join-Path $InstallRoot 'logs') -replace '\\','/')'
log_filename = 'postgresql-%Y-%m-%d.log'
"@
    @"
hostssl all all 127.0.0.1/32 scram-sha-256
hostssl replication honghu_backup 127.0.0.1/32 scram-sha-256
"@ | Set-Content -LiteralPath (Join-Path $DataDir 'pg_hba.conf') -Encoding ascii
    New-Item -ItemType Directory -Force (Join-Path $InstallRoot 'logs') | Out-Null
    & icacls $InstallRoot /grant '*S-1-5-20:(OI)(CI)M' /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'NetworkService filesystem ACL failed.' }
    $ServerKeyPath = Join-Path $TlsDir 'server.key'
    & icacls $ServerKeyPath /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' '*S-1-5-20:R' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'TLS private-key ACL restriction failed.' }
    $primary.phases += @{
        name = 'tls_private_key_acl'
        result = 'pass'
        inheritance_removed = $true
        system_full_control = $true
        administrators_full_control = $true
        network_service_read_only = $true
    }
    Write-HonghuJsonAtomic -Path $PrimaryEvidencePath -Value $primary

    & (Join-Path $Bin 'pg_ctl.exe') register -N 'HonghuPostgreSQL17' -D $DataDir -S auto -U 'NT AUTHORITY\NetworkService'
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL Windows service registration failed.' }
    & sc.exe failure HonghuPostgreSQL17 reset= 86400 actions= restart/5000/restart/15000/none/0 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL Windows service recovery policy failed.' }
    & sc.exe failureflag HonghuPostgreSQL17 1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL Windows service failure flag failed.' }
    Start-Service -Name 'HonghuPostgreSQL17'
    $deadline = (Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Milliseconds 500
        $listener = @(Get-NetTCPConnection -LocalPort 55440 -State Listen -ErrorAction SilentlyContinue)
    } until ($listener.Count -gt 0 -or (Get-Date) -gt $deadline)
    if ($listener.Count -eq 0) { throw 'PostgreSQL service did not bind the approved port.' }

    Stop-Service -Name 'HonghuPostgreSQL17'
    $deadline = (Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Milliseconds 500
        $listener = @(Get-NetTCPConnection -LocalPort 55440 -State Listen -ErrorAction SilentlyContinue)
    } until ($listener.Count -eq 0 -or (Get-Date) -gt $deadline)
    if ($listener.Count -ne 0) { throw 'PostgreSQL service did not stop cleanly.' }
    Start-Service -Name 'HonghuPostgreSQL17'
    $deadline = (Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Milliseconds 500
        $listener = @(Get-NetTCPConnection -LocalPort 55440 -State Listen -ErrorAction SilentlyContinue)
    } until ($listener.Count -gt 0 -or (Get-Date) -gt $deadline)
    if ($listener.Count -eq 0) { throw 'PostgreSQL service did not restart after a normal stop.' }

    $postmasterPidPath = Join-Path $DataDir 'postmaster.pid'
    if (-not (Test-Path -LiteralPath $postmasterPidPath -PathType Leaf)) {
        throw 'PostgreSQL postmaster identity file is missing.'
    }
    $crashPid = [int](Get-Content -LiteralPath $postmasterPidPath -TotalCount 1)
    $listenerPids = @($listener | ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
    $serviceProcess = Get-CimInstance Win32_Service -Filter "Name='HonghuPostgreSQL17'"
    $crashProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$crashPid"
    if ($null -eq $crashProcess -or -not [string]$crashProcess.ExecutablePath -or
        [System.IO.Path]::GetFullPath([string]$crashProcess.ExecutablePath) -ne [System.IO.Path]::GetFullPath((Join-Path $Bin 'postgres.exe')) -or
        [string]$crashProcess.CommandLine -notlike "*$DataDir*" -or
        $listenerPids -notcontains $crashPid -or
        $null -eq $serviceProcess -or [int]$crashProcess.ParentProcessId -ne [int]$serviceProcess.ProcessId) {
        throw 'PostgreSQL postmaster/service identity is not safe for crash-recovery rehearsal.'
    }
    $crashStartedAt = Get-Date
    Stop-Process -Id $crashPid -Force
    $deadline = (Get-Date).AddSeconds(60)
    $crashStopped = $false
    do {
        Start-Sleep -Seconds 1
        $crashListener = @(Get-NetTCPConnection -LocalPort 55440 -State Listen -ErrorAction SilentlyContinue)
        $crashService = Get-Service -Name 'HonghuPostgreSQL17' -ErrorAction SilentlyContinue
        $crashStopped = ($crashListener.Count -eq 0 -and $null -ne $crashService -and $crashService.Status -eq 'Stopped')
    } until ($crashStopped -or (Get-Date) -gt $deadline)
    if (-not $crashStopped) {
        throw 'PostgreSQL postmaster crash was not reflected as a stopped service.'
    }

    # pg_ctl runservice deliberately reports SERVICE_STOPPED/S_OK when the
    # postmaster exits, so SCM failure actions do not automatically restart
    # this failure mode.  Verify actual database crash recovery through an
    # explicit, observable service start; monitoring/operator response is part
    # of the pre-S2 service contract and no high-availability claim is made.
    Start-Service -Name 'HonghuPostgreSQL17'
    $deadline = (Get-Date).AddSeconds(90)
    $recoveredListener = @()
    $recoveredPid = $null
    do {
        Start-Sleep -Seconds 1
        $recoveredListener = @(Get-NetTCPConnection -LocalPort 55440 -State Listen -ErrorAction SilentlyContinue)
        if (Test-Path -LiteralPath $postmasterPidPath -PathType Leaf) {
            $candidatePid = [int](Get-Content -LiteralPath $postmasterPidPath -TotalCount 1)
            if ($candidatePid -ne $crashPid -and (Get-Process -Id $candidatePid -ErrorAction SilentlyContinue)) {
                $recoveredPid = $candidatePid
            }
        }
    } until (($recoveredListener.Count -gt 0 -and $null -ne $recoveredPid) -or (Get-Date) -gt $deadline)
    if ($recoveredListener.Count -eq 0 -or $null -eq $recoveredPid) {
        throw 'PostgreSQL did not complete crash recovery after explicit service restart.'
    }
    Invoke-HonghuPsql -Psql (Join-Path $Bin 'psql.exe') -Database postgres -Password $adminPassword -Sql 'SELECT 1;' | Out-Null
    $primary.phases += @{
        name = 'service_lifecycle'
        result = 'pass'
        automatic_startup = $true
        normal_restart = $true
        service_host_failure_actions_configured = $true
        postmaster_crash_detected_as_service_stopped = $true
        postmaster_crash_automatic_restart = $false
        crash_recovery = $true
        recovery_start_trigger = 'explicit_start_service_after_detected_postmaster_crash'
        monitoring_or_operator_start_required = $true
        crash_recovery_seconds = [math]::Round(((Get-Date) - $crashStartedAt).TotalSeconds, 3)
        old_pid = $crashPid
        recovered_pid = $recoveredPid
    }
    Write-HonghuJsonAtomic -Path $PrimaryEvidencePath -Value $primary

    $roleNames = [ordered]@{
        migration = 'honghu_migration'
        reader = 'honghu_viewer_reader'
        controller = 'honghu_controller'
        audit_reader = 'honghu_audit_reader'
        backup = 'honghu_backup'
    }
    foreach ($unit in 'user_content_notes','shared_identity','financial_data','research_publication','dynamic_intelligence','operations_governance','investment_hypotheses','opportunity_lens','sentiment_analytics') {
        $roleNames["writer_$unit"] = "honghu_writer_$unit"
    }
    $rolePasswords = @{}
    foreach ($entry in $roleNames.GetEnumerator()) { $rolePasswords[$entry.Key] = ConvertTo-HonghuSecretHex }
    $roleSql = New-Object System.Collections.Generic.List[string]
    foreach ($entry in $roleNames.GetEnumerator()) {
        $attributes = if ($entry.Key -eq 'backup') { 'LOGIN REPLICATION NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT' } else { 'LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT' }
        $roleSql.Add(('DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=''{0}'') THEN CREATE ROLE {0} {1} PASSWORD ''{2}''; ELSE ALTER ROLE {0} PASSWORD ''{2}''; END IF; END $$;' -f $entry.Value, $attributes, $rolePasswords[$entry.Key]))
    }
    $roleSql.Add("SELECT 'roles-created';")
    Invoke-HonghuPsql -Psql (Join-Path $Bin 'psql.exe') -Database postgres -Password $adminPassword -Sql ($roleSql -join "`n") | Out-Null
    Invoke-HonghuPsql -Psql (Join-Path $Bin 'psql.exe') -Database postgres -Password $adminPassword -Sql "SELECT 'CREATE DATABASE honghu_research' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='honghu_research')\gexec" | Out-Null

    $auditOldPassword = $rolePasswords['audit_reader']
    if (-not (Test-HonghuRoleCredential -Psql (Join-Path $Bin 'psql.exe') -Database 'honghu_research' -User $roleNames['audit_reader'] -Password $auditOldPassword)) {
        throw 'Initial audit-reader credential probe failed.'
    }
    $auditNewPassword = ConvertTo-HonghuSecretHex
    Invoke-HonghuPsql -Psql (Join-Path $Bin 'psql.exe') -Database postgres -Password $adminPassword -Sql ("ALTER ROLE {0} PASSWORD '{1}';" -f $roleNames['audit_reader'], $auditNewPassword) | Out-Null
    if (Test-HonghuRoleCredential -Psql (Join-Path $Bin 'psql.exe') -Database 'honghu_research' -User $roleNames['audit_reader'] -Password $auditOldPassword) {
        throw 'Rotated audit-reader credential remained valid.'
    }
    if (-not (Test-HonghuRoleCredential -Psql (Join-Path $Bin 'psql.exe') -Database 'honghu_research' -User $roleNames['audit_reader'] -Password $auditNewPassword)) {
        throw 'Rotated audit-reader credential is not usable.'
    }
    $rolePasswords['audit_reader'] = $auditNewPassword
    $probePassword = ConvertTo-HonghuSecretHex
    Invoke-HonghuPsql -Psql (Join-Path $Bin 'psql.exe') -Database postgres -Password $adminPassword -Sql ("CREATE ROLE honghu_bootstrap_credential_probe LOGIN PASSWORD '{0}';" -f $probePassword) | Out-Null
    if (-not (Test-HonghuRoleCredential -Psql (Join-Path $Bin 'psql.exe') -Database 'honghu_research' -User 'honghu_bootstrap_credential_probe' -Password $probePassword)) {
        throw 'Disposable credential probe did not authenticate.'
    }
    Invoke-HonghuPsql -Psql (Join-Path $Bin 'psql.exe') -Database postgres -Password $adminPassword -Sql 'ALTER ROLE honghu_bootstrap_credential_probe NOLOGIN;' | Out-Null
    if (Test-HonghuRoleCredential -Psql (Join-Path $Bin 'psql.exe') -Database 'honghu_research' -User 'honghu_bootstrap_credential_probe' -Password $probePassword) {
        throw 'Revoked disposable credential remained valid.'
    }
    Invoke-HonghuPsql -Psql (Join-Path $Bin 'psql.exe') -Database postgres -Password $adminPassword -Sql 'DROP ROLE honghu_bootstrap_credential_probe;' | Out-Null
    $primary.phases += @{ name = 'credential_lifecycle'; result = 'pass'; create = $true; rotate_old_rejected = $true; rotate_new_accepted = $true; revoke_rejected = $true; secret_values_recorded = $false }

    Invoke-HonghuCredential -Action set -Service 'honghu.postgresql.admin.v1' -Account 'honghu_admin' -Password $adminPassword | Out-Null
    $CredentialEntries.Add('honghu.postgresql.admin.v1|honghu_admin')
    foreach ($entry in $roleNames.GetEnumerator()) {
        Invoke-HonghuCredential -Action set -Service ("honghu.postgresql.{0}.v1" -f $entry.Key) -Account $entry.Value -Password $rolePasswords[$entry.Key] | Out-Null
        $CredentialEntries.Add(("honghu.postgresql.{0}.v1|{1}" -f $entry.Key, $entry.Value))
    }

    foreach ($migration in '0001_user_content_notes_expand.sql','0002_user_content_notes_cutover_expand.sql','0003_stage4_migration_staging.sql') {
        $path = Join-Path $RepoRoot "migrations\postgresql\$migration"
        $sha = Get-HonghuSha256 -Path $path
        $sql = Get-Content -Raw -LiteralPath $path
        Invoke-HonghuPsql -Psql (Join-Path $Bin 'psql.exe') -Database 'honghu_research' -Password $adminPassword -Sql $sql -Variables @("migration_sha256=$sha") | Out-Null
    }
    $grantPath = Join-Path $RepoRoot 'migrations\postgresql\0002_user_content_notes_role_grants.sql'
    Invoke-HonghuPsql -Psql (Join-Path $Bin 'psql.exe') -Database 'honghu_research' -Password $adminPassword -Sql (Get-Content -Raw $grantPath) -Variables @(
        'writer_role=honghu_writer_user_content_notes',
        'reader_role=honghu_viewer_reader',
        'controller_role=honghu_controller',
        'audit_reader_role=honghu_audit_reader'
    ) | Out-Null
    $migrationGrantPath = Join-Path $RepoRoot 'migrations\postgresql\0003_stage4_migration_role_grants.sql'
    Invoke-HonghuPsql -Psql (Join-Path $Bin 'psql.exe') -Database 'honghu_research' -Password $adminPassword -Sql (Get-Content -Raw $migrationGrantPath) -Variables @(
        'migration_role=honghu_migration'
    ) | Out-Null

    $RuntimeConfig = [ordered]@{
        schema_version = 'honghu.postgresql_production_runtime.v1'
        environment_id = 'production'
        application_commit_sha = $CommitSha
        host = '127.0.0.1'
        port = 55440
        dbname = 'honghu_research'
        sslmode = 'verify-full'
        sslrootcert = (Join-Path $TlsDir 'root.crt')
        service_name = 'HonghuPostgreSQL17'
        application_route = 'sqlite_transition'
        cluster_contract = @{
            encoding = $bootstrapConfig.postgresql.encoding
            locale_provider = $bootstrapConfig.postgresql.locale_provider
            builtin_locale = $bootstrapConfig.postgresql.builtin_locale
            text_search_config = $bootstrapConfig.postgresql.text_search_config
            data_checksums = [bool]$bootstrapConfig.postgresql.data_checksums
        }
        credential_owner_principal = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        credential_scope = 'stage4_operator_and_migration_only'
        break_glass = @{
            user = 'honghu_admin'
            credential_service = 'honghu.postgresql.admin.v1'
            credential_account = 'honghu_admin'
            routine_application_use = $false
        }
        roles = @{}
    }
    foreach ($entry in $roleNames.GetEnumerator()) {
        $RuntimeConfig.roles[$entry.Key] = @{
            user = $entry.Value
            credential_service = ("honghu.postgresql.{0}.v1" -f $entry.Key)
            credential_account = $entry.Value
        }
    }
    Write-HonghuJsonAtomic -Path $RuntimeConfigPath -Value $RuntimeConfig

    $IsolatedEntry = Join-Path $RepoRoot 'tools\migration\stage4_isolated_entry.py'
    $MappingRoot = Join-Path $RuntimeRoot 'identity-mapping'
    New-Item -ItemType Directory -Force $MappingRoot | Out-Null
    $MappingPath = Join-Path $MappingRoot 'identity_mapping_manifest.json'
    $MappingCrosscheckPath = Join-Path $MappingRoot 'identity_mapping_crosscheck.json'
    $MappingArgs = @(
        '-I','-B',$IsolatedEntry,
        '--repo-root',$RepoRoot,
        '--module','tools.migration.stage4_identity_mapping',
        '--database',(Join-Path $ProductionRoot 'data\research.db'),
        '--output',$MappingPath,
        '--alias-approvals',(Join-Path $RepoRoot 'config\migration\stage4_identity_mapping_approvals.json')
    )
    $MappingCrosscheckArgs = @(
        '-I','-B',$IsolatedEntry,
        '--repo-root',$RepoRoot,
        '--module','tools.migration.stage4_identity_mapping_crosscheck',
        '--mapping',$MappingPath,
        '--source-data-root',(Join-Path $ProductionRoot 'data'),
        '--output',$MappingCrosscheckPath
    )
    $oldPythonPath = $env:PYTHONPATH
    $oldNoUserSite = $env:PYTHONNOUSERSITE
    try {
        $env:PYTHONPATH = $null
        $env:PYTHONNOUSERSITE = '1'
        Push-Location $RepoRoot
        & $BootstrapPythonExe @MappingArgs
        if ($LASTEXITCODE -ne 0) { throw 'Identity mapping freeze failed.' }
        & $BootstrapPythonExe @MappingCrosscheckArgs
        if ($LASTEXITCODE -ne 0) { throw 'Identity mapping crosscheck failed.' }
    }
    finally {
        Pop-Location
        $env:PYTHONPATH = $oldPythonPath
        $env:PYTHONNOUSERSITE = $oldNoUserSite
    }
    $primary.phases += @{ name = 'identity_mapping_freeze'; result = 'pass'; manifest_sha256 = Get-HonghuSha256 $MappingPath; crosscheck_sha256 = Get-HonghuSha256 $MappingCrosscheckPath; cutover_level_approved = $false }

    $RecoveryArgs = @(
        '-I','-B',$IsolatedEntry,
        '--repo-root',$RepoRoot,
        '--module','tools.migration.stage4_production_recovery',
        '--repo-root',$RepoRoot,
        '--runtime',$RuntimeConfigPath,
        '--bin-dir',$Bin,
        '--install-root',$InstallRoot,
        '--commit-sha',$CommitSha,
        '--output-dir',(Join-Path $EvidenceRoot 'recovery')
    )
    if ($OffVmRoot) { $RecoveryArgs += @('--off-vm-root',$OffVmRoot) }
    if ($ExpectedOffVmStorageIdentity) { $RecoveryArgs += @('--expected-off-vm-storage-identity',$ExpectedOffVmStorageIdentity) }
    try {
        $env:PYTHONPATH = $null
        $env:PYTHONNOUSERSITE = '1'
        Push-Location $RepoRoot
        & $BootstrapPythonExe @RecoveryArgs
        if ($LASTEXITCODE -ne 0) { throw 'Production backup/WAL/restore rehearsal failed.' }
    }
    finally {
        Pop-Location
        $env:PYTHONPATH = $oldPythonPath
        $env:PYTHONNOUSERSITE = $oldNoUserSite
    }

    $PreparationRoot = Join-Path $RuntimeRoot 's1-preparation'
    $PreparationArgs = @(
        '-I','-B',$IsolatedEntry,
        '--repo-root',$RepoRoot,
        '--module','tools.migration.stage4_prepare_units',
        '--source-data-root',(Join-Path $ProductionRoot 'data'),
        '--registry',(Join-Path $RepoRoot 'config\migration\cutover_unit_registry.json'),
        '--route',(Join-Path $RepoRoot 'config\migration\user_content_backend_route.json'),
        '--runtime',$RuntimeConfigPath,
        '--application-commit-sha',$CommitSha,
        '--work-root',$PreparationRoot
    )
    try {
        $env:PYTHONPATH = $null
        $env:PYTHONNOUSERSITE = '1'
        Push-Location $RepoRoot
        & $BootstrapPythonExe @PreparationArgs
        if ($LASTEXITCODE -ne 0) { throw 'Stage 4 all-unit S0/S1 preparation failed.' }
    }
    finally {
        Pop-Location
        $env:PYTHONPATH = $oldPythonPath
        $env:PYTHONNOUSERSITE = $oldNoUserSite
    }

    $ProductionVerifyPath = Join-Path $EvidenceRoot 'production_postgresql_verification.json'
    $VerificationArgs = @(
        '-I','-B',$IsolatedEntry,
        '--repo-root',$RepoRoot,
        '--module','tools.migration.stage4_production_verify',
        '--repo-root',$RepoRoot,
        '--runtime',$RuntimeConfigPath,
        '--application-commit-sha',$CommitSha,
        '--output',$ProductionVerifyPath
    )
    try {
        $env:PYTHONPATH = $null
        $env:PYTHONNOUSERSITE = '1'
        Push-Location $RepoRoot
        & $BootstrapPythonExe @VerificationArgs
        if ($LASTEXITCODE -ne 0) { throw 'Production PostgreSQL evidence verification failed.' }
    }
    finally {
        Pop-Location
        $env:PYTHONPATH = $oldPythonPath
        $env:PYTHONNOUSERSITE = $oldNoUserSite
    }

    $primary.status = 'pass'
    $primary.completed_at = (Get-Date).ToUniversalTime().ToString('o')
    $primary.phases += @{ name = 'postgresql_service'; result = 'pass'; version = $versionText; port = 55440 }
    $primary.phases += @{ name = 'tls_roles_credentials_migrations'; result = 'pass'; role_count = $roleNames.Count }
    $primary.phases += @{ name = 'backup_wal_restore'; result = 'pass'; evidence = 'recovery' }
    $primary.phases += @{ name = 'all_unit_s0_s1_preparation'; result = 'pass'; evidence = 'runtime/s1-preparation/all_unit_preparation.json' }
    $primary.phases += @{ name = 'production_evidence_verification'; result = 'pass'; evidence_sha256 = Get-HonghuSha256 $ProductionVerifyPath }
    $serviceEvidence = Get-CimInstance Win32_Service -Filter "Name='HonghuPostgreSQL17'"
    $listenerEvidence = @(Get-NetTCPConnection -LocalPort 55440 -State Listen -ErrorAction Stop)
    if ($null -eq $serviceEvidence -or $serviceEvidence.State -ne 'Running' -or $serviceEvidence.StartMode -ne 'Auto' -or
        $serviceEvidence.StartName -ne 'NT AUTHORITY\NetworkService' -or [string]$serviceEvidence.PathName -notlike "*$DataDir*") {
        throw 'PostgreSQL Windows service identity/lifecycle contract mismatch.'
    }
    $listenerProcess = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f [int]$listenerEvidence[0].OwningProcess)
    if ($null -eq $listenerProcess -or -not [string]$listenerProcess.ExecutablePath -or
        [System.IO.Path]::GetFullPath([string]$listenerProcess.ExecutablePath) -ne [System.IO.Path]::GetFullPath((Join-Path $Bin 'postgres.exe'))) {
        throw 'PostgreSQL listener executable identity mismatch.'
    }
    $primary.phases += @{ name = 'windows_service_identity'; result = 'pass'; state = $serviceEvidence.State; start_mode = $serviceEvidence.StartMode; start_name = $serviceEvidence.StartName; path_name = [string]$serviceEvidence.PathName; listener_pid = [int]$listenerEvidence[0].OwningProcess; executable_sha256 = Get-HonghuSha256 ([string]$listenerProcess.ExecutablePath) }
    $RepositoryGovernancePath = Join-Path $EvidenceRoot 'repository_governance.json'
    $GovernanceArgs = @(
        '-I','-B',$IsolatedEntry,
        '--repo-root',$RepoRoot,
        '--module','tools.migration.stage4_repository_governance',
        '--repository','Garthzzz/honghu-ai-research-system',
        '--commit-sha',$CommitSha,
        '--output',$RepositoryGovernancePath
    )
    try {
        $env:PYTHONPATH = $null
        $env:PYTHONNOUSERSITE = '1'
        Push-Location $RepoRoot
        & $BootstrapPythonExe @GovernanceArgs
        if ($LASTEXITCODE -ne 0) { throw 'Read-only repository governance collection failed.' }
    }
    finally {
        Pop-Location
        $env:PYTHONPATH = $oldPythonPath
        $env:PYTHONNOUSERSITE = $oldNoUserSite
    }
    $HumanDecisionsPath = Join-Path $EvidenceRoot 'human_decisions.json'
    Copy-Item -LiteralPath (Join-Path $RepoRoot 'config\migration\stage4_human_decisions.template.json') -Destination $HumanDecisionsPath -Force
    $primary.phases += @{ name = 'repository_governance_collection'; result = 'pass'; production_authority_approved = $false; evidence_sha256 = Get-HonghuSha256 $RepositoryGovernancePath }
    $primary.phases += @{ name = 'credential_owner_boundary'; result = 'pass'; owner_principal = $RuntimeConfig.credential_owner_principal; application_service_principal_provisioned = $false; s2_blocker = $true }
    Write-HonghuJsonAtomic -Path $PrimaryEvidencePath -Value $primary
}
catch {
    $primary.status = 'failed'
    $primary.primary_failure = $_.Exception.Message
    $primary.failed_at = (Get-Date).ToUniversalTime().ToString('o')
    Write-HonghuJsonAtomic -Path $PrimaryEvidencePath -Value $primary
    throw
}
finally {
    $preInstallRecovery = $null
    if (-not $CleanupRequired -and $primary.status -eq 'failed' -and
        $null -ne $StagingRoot -and (Test-Path -LiteralPath $StagingRoot -PathType Container)) {
        $preInstallRecoveryPath = Join-Path $PreInstallEvidenceRoot 'preinstall_staging_quarantine.json'
        try {
            if ($null -ne (Get-Service -Name 'HonghuPostgreSQL17' -ErrorAction SilentlyContinue)) {
                throw 'Pre-install staging cannot be quarantined while the service exists.'
            }
            if (@(Get-NetTCPConnection -LocalPort 55440 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) {
                throw 'Pre-install staging cannot be quarantined while port 55440 is listening.'
            }
            & $BootstrapBasePythonExe -I -B (Join-Path $RepoRoot 'tools\migration\stage4_preinstall_quarantine.py') `
                --install-root $InstallRoot --staging-root $StagingRoot `
                --launch-id $LaunchId --primary-failure $primary.primary_failure `
                --output $preInstallRecoveryPath | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Pre-install staging quarantine helper failed.' }
            $preInstallRecovery = Get-Content -Raw -LiteralPath $preInstallRecoveryPath | ConvertFrom-Json
        }
        catch {
            $preInstallRecovery = [ordered]@{
                schema_version = 'honghu.stage4_preinstall_quarantine_failure.v1'
                checked_at = (Get-Date).ToUniversalTime().ToString('o')
                launch_id = $LaunchId
                staging_root = $StagingRoot
                primary_failure = $primary.primary_failure
                recovery_failure = $_.Exception.Message
                manual_inspection_required = $true
            }
            Write-HonghuJsonAtomic -Path $preInstallRecoveryPath -Value $preInstallRecovery
        }
    }
    $final = [ordered]@{
        schema_version = 'honghu.stage4_production_postgresql_bootstrap_final.v1'
        checked_at = (Get-Date).ToUniversalTime().ToString('o')
        primary_evidence_sha256 = if (Test-Path $PrimaryEvidencePath) { Get-HonghuSha256 $PrimaryEvidencePath } else { $null }
        service = if (Get-Service -Name 'HonghuPostgreSQL17' -ErrorAction SilentlyContinue) { (Get-Service -Name 'HonghuPostgreSQL17').Status.ToString() } else { 'absent' }
        listener_55440 = (@(Get-NetTCPConnection -LocalPort 55440 -State Listen -ErrorAction SilentlyContinue).Count -gt 0)
        viewer_8080_ok = $false
        route_backend = $null
        route_state = $null
        production_authority_changed = $false
        s2_or_s3_entered = $false
        preinstall_staging_recovery = $preInstallRecovery
    }
    try { $final.viewer_8080_ok = [bool](Invoke-RestMethod 'http://127.0.0.1:8080/api/health' -TimeoutSec 10).ok } catch {}
    try {
        $finalRoute = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot 'config\migration\user_content_backend_route.json') | ConvertFrom-Json
        $final.route_backend = $finalRoute.backend
        $final.route_state = $finalRoute.authority_state
        $final.production_authority_changed = ($finalRoute.backend -ne 'sqlite_transition')
        $final.s2_or_s3_entered = ($finalRoute.authority_state -in @('S2','S3','S4'))
    } catch {}
    Write-HonghuJsonAtomic -Path $FinalEvidencePath -Value $final
    if ($CleanupRequired -and $primary.status -eq 'failed') {
        try {
            $cleanup = Invoke-HonghuFailedBootstrapCleanup `
                -InstallRoot $InstallRoot -LaunchId $LaunchId -CommitSha $CommitSha `
                -CredentialEntries @($CredentialEntries)
            $quarantineEvidence = Join-Path $cleanup.quarantine_path 'runtime\evidence\bootstrap_cleanup.json'
            Write-HonghuJsonAtomic -Path $quarantineEvidence -Value $cleanup
        }
        catch {
            $cleanupFailure = [ordered]@{
                schema_version = 'honghu.stage4_bootstrap_cleanup_failure.v1'
                checked_at = (Get-Date).ToUniversalTime().ToString('o')
                launch_id = $LaunchId
                primary_failure = $primary.primary_failure
                cleanup_failure = $_.Exception.Message
                manual_inspection_required = $true
            }
            Write-HonghuJsonAtomic -Path (Join-Path $EvidenceRoot 'bootstrap_cleanup_failure.json') -Value $cleanupFailure
        }
    }
}

try {
    $BundleRoot = Join-Path $EvidenceRoot ("execution-bundle-{0}" -f $CommitSha)
    $BundleArgs = @(
    '-I','-B',(Join-Path $RepoRoot 'tools\migration\stage4_isolated_entry.py'),
    '--repo-root',$RepoRoot,
    '--module','tools.migration.stage4_execution_bundle',
    '--output-root',$BundleRoot,
    '--environment-id','production',
    '--application-commit-sha',$CommitSha,
    '--bootstrap-config-sha256',(Get-HonghuSha256 $ConfigPath),
    '--artifact',("bootstrap_input={0}" -f (Join-Path $EvidenceRoot 'bootstrap_input_identity.json')),
    '--artifact',("bootstrap_primary={0}" -f $PrimaryEvidencePath),
    '--artifact',("bootstrap_final={0}" -f $FinalEvidencePath),
    '--artifact',("runtime_config={0}" -f $RuntimeConfigPath),
    '--artifact',("production_postgresql_verification={0}" -f (Join-Path $EvidenceRoot 'production_postgresql_verification.json')),
    '--artifact',("production_recovery={0}" -f (Join-Path $EvidenceRoot 'recovery\production_recovery.json')),
    '--artifact',("recovery_set_manifest={0}" -f (Join-Path $EvidenceRoot 'recovery\recovery_set_manifest.copy.json')),
    '--artifact',("all_unit_preparation={0}" -f (Join-Path $RuntimeRoot 's1-preparation\all_unit_preparation.json')),
    '--artifact',("identity_mapping_manifest={0}" -f (Join-Path $RuntimeRoot 'identity-mapping\identity_mapping_manifest.json')),
    '--artifact',("identity_mapping_crosscheck={0}" -f (Join-Path $RuntimeRoot 'identity-mapping\identity_mapping_crosscheck.json')),
    '--artifact',("repository_governance={0}" -f (Join-Path $EvidenceRoot 'repository_governance.json')),
    '--artifact',("target_rpo_rto={0}" -f (Join-Path $RepoRoot 'config\migration\target_rpo_rto_proposal.json')),
    '--artifact',("human_decisions={0}" -f (Join-Path $EvidenceRoot 'human_decisions.json'))
    )
    & $BootstrapPythonExe @BundleArgs
    if ($LASTEXITCODE -ne 0) { throw 'Final Stage 4 execution evidence bundle failed.' }
    $ReadinessPath = Join-Path $BundleRoot 'execution_readiness.json'
    & $BootstrapPythonExe -I -B (Join-Path $RepoRoot 'tools\migration\stage4_isolated_entry.py') `
        --repo-root $RepoRoot --module tools.migration.stage4_execution_readiness `
        --repo-root $RepoRoot --evidence-root $BundleRoot `
        --bundle (Join-Path $BundleRoot 'execution_bundle.json') --output $ReadinessPath
    $ReadinessExitCode = $LASTEXITCODE
    $Readiness = Get-Content -Raw -LiteralPath $ReadinessPath | ConvertFrom-Json
    if ($ReadinessExitCode -notin @(0,2)) { throw 'Final readiness verifier did not produce a governed result.' }

    $InstallIdentity.completed = $true
    $InstallIdentity.completed_at = (Get-Date).ToUniversalTime().ToString('o')
    $InstallIdentity.execution_bundle_sha256 = Get-HonghuSha256 (Join-Path $BundleRoot 'execution_bundle.json')
    $InstallIdentity.readiness_evidence_sha256 = Get-HonghuSha256 $ReadinessPath
    Write-HonghuJsonAtomic -Path $InstallIdentityPath -Value $InstallIdentity
    $CleanupRequired = $false

    [ordered]@{
        ok = $true
        service_name = 'HonghuPostgreSQL17'
        runtime_config = $RuntimeConfigPath
        primary_evidence = $PrimaryEvidencePath
        final_evidence = $FinalEvidencePath
        application_authority = 'sqlite_transition'
        cutover_state = 'S0_or_S1_only'
        readiness_status = $Readiness.status
        readiness_evidence = $ReadinessPath
    } | ConvertTo-Json -Depth 8
}
catch {
    $primary.status = 'failed'
    $primary.primary_failure = $_.Exception.Message
    $primary.failed_at = (Get-Date).ToUniversalTime().ToString('o')
    $primary.failure_phase = 'evidence_bundle_or_readiness'
    Write-HonghuJsonAtomic -Path $PrimaryEvidencePath -Value $primary
    try {
        $cleanup = Invoke-HonghuFailedBootstrapCleanup `
            -InstallRoot $InstallRoot -LaunchId $LaunchId -CommitSha $CommitSha `
            -CredentialEntries @($CredentialEntries)
        $quarantineEvidence = Join-Path $cleanup.quarantine_path 'runtime\evidence\bootstrap_cleanup.json'
        Write-HonghuJsonAtomic -Path $quarantineEvidence -Value $cleanup
    }
    catch {
        $cleanupFailure = [ordered]@{
            schema_version = 'honghu.stage4_bootstrap_cleanup_failure.v1'
            checked_at = (Get-Date).ToUniversalTime().ToString('o')
            launch_id = $LaunchId
            primary_failure = $primary.primary_failure
            cleanup_failure = $_.Exception.Message
            manual_inspection_required = $true
        }
        Write-HonghuJsonAtomic -Path (Join-Path $EvidenceRoot 'bootstrap_cleanup_failure.json') -Value $cleanupFailure
    }
    throw
}
