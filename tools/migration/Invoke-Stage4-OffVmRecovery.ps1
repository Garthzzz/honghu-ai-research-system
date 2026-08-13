[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$BootstrapPythonExe,
    [Parameter(Mandatory = $true)][string]$RuntimePath,
    [Parameter(Mandatory = $true)][string]$BinDir,
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$CommitSha,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [Parameter(Mandatory = $true)][ValidatePattern('^\\\\')][string]$OffVmRoot,
    [Parameter(Mandatory = $true)][string]$SmbUser,
    [Parameter(Mandatory = $true)][string]$CredentialBlobPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-JsonNoBom([string]$Path, [hashtable]$Payload) {
    $json = $Payload | ConvertTo-Json -Depth 8
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path)) | Out-Null
    [IO.File]::WriteAllText($Path, $json + "`n", [Text.UTF8Encoding]::new($false))
}

foreach ($required in @(
    $RepoRoot,
    $BootstrapPythonExe,
    $RuntimePath,
    $BinDir,
    $InstallRoot,
    $CredentialBlobPath
)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required recovery input is missing: $required"
    }
}
[IO.Directory]::CreateDirectory($OutputDir) | Out-Null

Add-Type -AssemblyName System.Security
$protected = [IO.File]::ReadAllBytes($CredentialBlobPath)
$plainBytes = $null
$password = $null
$driveCreated = $false
$startedAt = (Get-Date).ToUniversalTime().ToString('o')

try {
    $plainBytes = [System.Security.Cryptography.ProtectedData]::Unprotect(
        $protected,
        $null,
        [System.Security.Cryptography.DataProtectionScope]::LocalMachine
    )
    $password = [Text.Encoding]::UTF8.GetString($plainBytes)
    if ([string]::IsNullOrWhiteSpace($password)) {
        throw 'Off-VM SMB credential decrypted to an empty value.'
    }
    $credential = New-Object Management.Automation.PSCredential(
        $SmbUser,
        (ConvertTo-SecureString $password -AsPlainText -Force)
    )
    Remove-PSDrive H4Recovery -Force -ErrorAction SilentlyContinue
    New-PSDrive `
        -Name H4Recovery `
        -PSProvider FileSystem `
        -Root $OffVmRoot `
        -Credential $credential `
        -Scope Global | Out-Null
    $driveCreated = $true

    if (-not (Test-Path -LiteralPath $OffVmRoot -PathType Container)) {
        throw 'Authenticated off-VM recovery share is not reachable.'
    }
    $shareName = ([Uri]($OffVmRoot -replace '^\\\\', 'file://')).Segments[1].TrimEnd('/')
    $smb = Get-SmbConnection -ErrorAction Stop |
        Where-Object { $_.ShareName -eq $shareName } |
        Select-Object -First 1
    if ($null -eq $smb -or -not [bool]$smb.Encrypted) {
        throw 'Off-VM SMB session is absent or not encrypted.'
    }

    $verifierStdout = Join-Path $OutputDir 'production_recovery.stdout.log'
    $verifierStderr = Join-Path $OutputDir 'production_recovery.stderr.log'
    $priorErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $BootstrapPythonExe -I -B `
        (Join-Path $RepoRoot 'tools\migration\stage4_isolated_entry.py') `
        --repo-root $RepoRoot `
        --module tools.migration.stage4_production_recovery `
        -- `
        --repo-root $RepoRoot `
        --runtime $RuntimePath `
        --bin-dir $BinDir `
        --install-root $InstallRoot `
        --commit-sha $CommitSha `
        --output-dir $OutputDir `
        --off-vm-root $OffVmRoot 1> $verifierStdout 2> $verifierStderr
    $verifierExitCode = $LASTEXITCODE
    $ErrorActionPreference = $priorErrorAction
    if ($verifierExitCode -ne 0) {
        $tail = @(
            Get-Content -LiteralPath $verifierStderr -Tail 20 -ErrorAction SilentlyContinue
        ) -join ' | '
        throw "Off-VM recovery verifier exited with code ${verifierExitCode}: $tail"
    }

    Write-JsonNoBom (Join-Path $OutputDir 'offvm_recovery_wrapper.json') ([ordered]@{
        schema_version = 'honghu.stage4_offvm_recovery_wrapper.v1'
        status = 'pass'
        started_at_utc = $startedAt
        completed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        application_commit_sha = $CommitSha
        smb_encrypted = $true
        credential_source = 'dpapi_local_machine_blob_with_restricted_acl'
        secret_recorded = $false
    })
} catch {
    Write-JsonNoBom (Join-Path $OutputDir 'offvm_recovery_wrapper.failure.json') ([ordered]@{
        schema_version = 'honghu.stage4_offvm_recovery_wrapper_failure.v1'
        status = 'failed'
        started_at_utc = $startedAt
        failed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        application_commit_sha = $CommitSha
        error_type = $_.Exception.GetType().FullName
        error = $_.Exception.Message
        secret_recorded = $false
    })
    throw
} finally {
    if ($driveCreated) {
        Remove-PSDrive H4Recovery -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $plainBytes) {
        [Array]::Clear($plainBytes, 0, $plainBytes.Length)
    }
    $password = $null
}
