[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ReleaseDir,
    [Parameter(Mandatory=$true)][string]$BootstrapPythonExe,
    [Parameter(Mandatory=$true)][string]$SitePackages,
    [Parameter(Mandatory=$true)][string]$RuntimeCatalog,
    [Parameter(Mandatory=$true)][string]$SourceArchive,
    [Parameter(Mandatory=$true)][ValidatePattern('^\\\\')][string]$OffVmRoot,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedStorageIdentity,
    [Parameter(Mandatory=$true)][string]$AtRestEncryptionEvidence,
    [Parameter(Mandatory=$true)][string]$InitialRecoveryBoundary,
    [Parameter(Mandatory=$true)][string]$SmbUser,
    [Parameter(Mandatory=$true)][string]$CredentialBlobPath,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [ValidateRange(3600,604800)][int]$MaxFullScrubAgeSeconds = 86400
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

foreach ($path in @($ReleaseDir,$BootstrapPythonExe,$SitePackages,$RuntimeCatalog,$SourceArchive,$AtRestEncryptionEvidence,$InitialRecoveryBoundary,$CredentialBlobPath)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required recovery input is absent: $path" }
}
$bootstrap = Join-Path $ReleaseDir 'tools\release\direct_candidate.py'
if (-not (Test-Path -LiteralPath $bootstrap -PathType Leaf)) { throw 'Exact-release bootstrap is absent.' }

Add-Type -AssemblyName System.Security
$protected = [IO.File]::ReadAllBytes($CredentialBlobPath)
$plainBytes = $null
$password = $null
$mapped = $false
try {
    $plainBytes = [Security.Cryptography.ProtectedData]::Unprotect(
        $protected, $null, [Security.Cryptography.DataProtectionScope]::LocalMachine
    )
    $password = [Text.Encoding]::UTF8.GetString($plainBytes)
    if ([string]::IsNullOrWhiteSpace($password)) { throw 'SMB credential is empty.' }
    $credential = [Management.Automation.PSCredential]::new(
        $SmbUser, (ConvertTo-SecureString $password -AsPlainText -Force)
    )
    Remove-SmbMapping -RemotePath $OffVmRoot -Force -UpdateProfile:$false `
        -ErrorAction SilentlyContinue | Out-Null
    New-SmbMapping -RemotePath $OffVmRoot -Credential $credential `
        -RequirePrivacy $true -Persistent $false | Out-Null
    $mapped = $true
    if (-not (Test-Path -LiteralPath $OffVmRoot -PathType Container)) {
        throw 'Approved off-VM recovery share is unreachable.'
    }
    $destination = Join-Path $OffVmRoot 'honghu-postgresql\stage5-continuous-wal'
    New-Item -ItemType Directory -Force $destination | Out-Null
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $json = & $BootstrapPythonExe -I -B -S $bootstrap `
            --site-packages $SitePackages `
            --module tools.operations.stage5_recovery_cycle `
            --runtime-catalog $RuntimeCatalog `
            --source-archive $SourceArchive `
            --destination $destination `
            --expected-storage-identity $ExpectedStorageIdentity `
            --at-rest-encryption-evidence $AtRestEncryptionEvidence `
            --initial-recovery-boundary $InitialRecoveryBoundary `
            --archive-only `
            --max-archive-age-seconds 900 `
            --max-full-scrub-age-seconds $MaxFullScrubAgeSeconds 2>&1 | Out-String
        $pythonExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    if ($pythonExitCode -ne 0) {
        throw "Stage5 continuous WAL recovery cycle failed: $($json.Trim())"
    }
    $result = $json | ConvertFrom-Json
    if ($result.status -ne 'pass' -or $result.storage_identity -ne $ExpectedStorageIdentity) {
        throw 'Stage5 recovery cycle returned mismatched evidence.'
    }
    $parent = Split-Path -Parent $OutputPath
    if ($parent) { New-Item -ItemType Directory -Force $parent | Out-Null }
    [IO.File]::WriteAllText(
        $OutputPath,
        (($result | ConvertTo-Json -Depth 10) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )
    $result | ConvertTo-Json -Depth 10
} finally {
    if ($mapped) {
        Remove-SmbMapping -RemotePath $OffVmRoot -Force -UpdateProfile:$false `
            -ErrorAction SilentlyContinue | Out-Null
    }
    if ($null -ne $plainBytes) { [Array]::Clear($plainBytes,0,$plainBytes.Length) }
    $password = $null
}
