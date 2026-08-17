[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ReleaseDir,
    [Parameter(Mandatory=$true)][string]$BootstrapPythonExe,
    [Parameter(Mandatory=$true)][string]$SitePackages,
    [Parameter(Mandatory=$true)][string]$SourceHostIdentityEvidence,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# This is one reviewed endpoint move, not a general alias allowlist.  The
# physical host/share/volume facts below are always probed by this collector;
# callers cannot supply MachineGuid, volume identity, share path or encryption
# booleans.
$ApprovedCollectorHost = 'WIN-G7VO0DD37CE'
$ApprovedShareName = 'HonghuPgRecovery'
$ApprovedLocalRoot = 'D:\quant\industry_demo_backup_package\postgresql_recovery'
$OldEndpointAddress = '10.212.134.201'
$NewEndpointAddress = '10.5.10.74'
$AuthorizationReference = 'user-stage5-full-execution-authorization-2026-08-16'
$PinnedCertificateSha256 = 'f4dac3e071441e68e860bb05aabec95b39594ca1186171eeb4147a1b265c1dc7'

function Get-Sha256Text([string]$Value) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString(
            $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))
        ) -replace '-','').ToLowerInvariant()
    } finally { $sha.Dispose() }
}
function Resolve-ExactPath([string]$Path) {
    return [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path).TrimEnd('\')
}

if ($env:COMPUTERNAME.ToUpperInvariant() -ne $ApprovedCollectorHost) {
    throw 'Storage transition evidence must be collected locally on WIN-G7VO0DD37CE.'
}
foreach ($path in @($ReleaseDir,$BootstrapPythonExe,$SitePackages,$SourceHostIdentityEvidence)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required collector input is absent: $path" }
}
$bootstrap = Join-Path $ReleaseDir 'tools\release\direct_candidate.py'
if (-not (Test-Path -LiteralPath $bootstrap -PathType Leaf)) {
    throw 'Exact-release Python bootstrap is absent.'
}
$publicCertificatePath = Join-Path $ReleaseDir 'config\migration\stage5_storage_attestation_public.cer'
if (-not (Test-Path -LiteralPath $publicCertificatePath -PathType Leaf)) {
    throw 'Exact-release storage-attestation public certificate is absent.'
}
$publicCertificateSha = (Get-FileHash -LiteralPath $publicCertificatePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($publicCertificateSha -ne $PinnedCertificateSha256) {
    throw 'Storage-attestation public certificate differs from the pinned trust root.'
}
$publicCertificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new($publicCertificatePath)
if ($publicCertificate.Subject -notmatch '(^|,\s*)CN=HonghuStage5StorageAttestation(,|$)') {
    throw 'Storage-attestation certificate subject is invalid.'
}
$certificateThumbprint = $publicCertificate.Thumbprint.ToLowerInvariant()
$signingCertificate = Get-ChildItem -LiteralPath ("Cert:\CurrentUser\My\" + $publicCertificate.Thumbprint) -ErrorAction Stop
if (-not $signingCertificate.HasPrivateKey) {
    throw 'CurrentUser storage-attestation certificate has no private key.'
}
if ((Get-Sha256Text ([Convert]::ToBase64String($signingCertificate.RawData))) -ne
    (Get-Sha256Text ([Convert]::ToBase64String($publicCertificate.RawData)))) {
    throw 'CurrentUser signing certificate differs from the exact-release public certificate.'
}

$share = Get-SmbShare -Name $ApprovedShareName -ErrorAction Stop
$sharePath = Resolve-ExactPath $share.Path
$approvedPath = Resolve-ExactPath $ApprovedLocalRoot
if ($sharePath -ne $approvedPath) {
    throw 'HonghuPgRecovery does not map to the approved backup_package root.'
}
if ($share.EncryptData -ne $true) {
    throw 'HonghuPgRecovery does not require SMB encryption.'
}
$uncRoot = "\\$NewEndpointAddress\$ApprovedShareName"
if (-not (Test-Path -LiteralPath $uncRoot -PathType Container)) {
    throw 'The new UNC endpoint is not live from the backup host.'
}

$drive = [IO.Path]::GetPathRoot($approvedPath).TrimEnd('\')
$logicalDisk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$drive'" -ErrorAction Stop
if ($null -eq $logicalDisk -or [string]::IsNullOrWhiteSpace($logicalDisk.VolumeSerialNumber)) {
    throw 'Cannot read the approved backup volume identity.'
}
$volumeSerial = $logicalDisk.VolumeSerialNumber.ToLowerInvariant()
$filesystem = ([string]$logicalDisk.FileSystem).ToUpperInvariant()
if ($filesystem -ne 'NTFS') { throw 'Approved backup volume filesystem changed.' }

$bitlocker = Get-BitLockerVolume -MountPoint $drive -ErrorAction Stop
$protectionStatus = $bitlocker.ProtectionStatus.ToString()
$volumeStatus = $bitlocker.VolumeStatus.ToString()
$encryptionPercentage = [double]$bitlocker.EncryptionPercentage
if (
    $protectionStatus -ne 'On' -or
    $volumeStatus -ne 'FullyEncrypted' -or
    $encryptionPercentage -ne 100.0
) { throw 'Approved backup volume is not fully protected by BitLocker.' }

$machineGuid = [string](Get-ItemPropertyValue `
    -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Cryptography' `
    -Name MachineGuid `
    -ErrorAction Stop)
if ([string]::IsNullOrWhiteSpace($machineGuid)) { throw 'Backup-host MachineGuid is absent.' }
$machineGuidSha = Get-Sha256Text $machineGuid.Trim().ToLowerInvariant()
$machineGuid = $null

$sourceEvidence = Get-Content -Raw -LiteralPath $SourceHostIdentityEvidence -Encoding UTF8 |
    ConvertFrom-Json
if (
    $sourceEvidence.schema_version -ne 'honghu.stage5_source_host_identity.v1' -or
    $sourceEvidence.verified -ne $true -or
    $sourceEvidence.verification_method -ne 'windows_registry_machineguid_sha256' -or
    $sourceEvidence.host_name.ToString().ToLowerInvariant() -ne 'desktop-vgd07j4' -or
    $sourceEvidence.machine_guid_sha256 -notmatch '^[0-9a-f]{64}$' -or
    $sourceEvidence.evidence_identity_sha256 -notmatch '^[0-9a-f]{64}$'
) { throw 'Source-host identity evidence is invalid.' }
if ($sourceEvidence.machine_guid_sha256 -eq $machineGuidSha) {
    throw 'Backup host and PostgreSQL source VM have the same MachineGuid.'
}

$walRoot = Join-Path $approvedPath 'honghu-postgresql\stage5-continuous-wal'
$pointerPath = Join-Path $walRoot 'latest_verified_wal_manifest.json'
if (-not (Test-Path -LiteralPath $pointerPath -PathType Leaf)) {
    throw 'Prior verified WAL pointer is absent.'
}
$pointer = Get-Content -Raw -LiteralPath $pointerPath -Encoding UTF8 | ConvertFrom-Json
if (
    $pointer.schema_version -ne 'honghu.stage5_offvm_wal_pointer.v1' -or
    $pointer.manifest_path -notmatch '^manifests/[0-9a-f]{64}\.json$' -or
    $pointer.manifest_identity_sha256 -notmatch '^[0-9a-f]{64}$'
) { throw 'Prior verified WAL pointer is invalid.' }
$manifestPath = Join-Path $walRoot ($pointer.manifest_path -replace '/','\')
$manifest = Get-Content -Raw -LiteralPath $manifestPath -Encoding UTF8 | ConvertFrom-Json
if ($manifest.manifest_identity_sha256 -ne $pointer.manifest_identity_sha256) {
    throw 'Prior pointer and manifest identity differ.'
}
if ($manifest.storage_identity -notmatch '^[0-9a-f]{64}$') {
    throw 'Prior manifest storage identity is invalid.'
}
if ($manifest.initial_recovery_boundary.evidence_identity_sha256 -notmatch '^[0-9a-f]{64}$') {
    throw 'Prior manifest has no verified first-required WAL boundary.'
}
if ($manifest.at_rest_encryption.verified -ne $true -or
    $manifest.at_rest_encryption.evidence_identity_sha256 -notmatch '^[0-9a-f]{64}$') {
    throw 'Prior manifest has no verified at-rest identity.'
}

$verifiedArtifacts = @()
foreach ($item in @($manifest.artifacts)) {
    if ($item.name -notmatch '^[0-9A-F]{24}$' -or $item.sha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'Prior manifest contains an unsafe WAL artifact identity.'
    }
    $artifactPath = Join-Path (Join-Path $walRoot 'wal') $item.name
    if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
        throw "Prior WAL artifact is absent: $($item.name)"
    }
    $file = Get-Item -LiteralPath $artifactPath
    $hash = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ([int64]$item.size -ne [int64]$file.Length -or $hash -ne $item.sha256) {
        throw "Prior WAL artifact hash differs: $($item.name)"
    }
    $verifiedArtifacts += [ordered]@{
        name = [string]$item.name
        size = [int64]$file.Length
        sha256 = $hash
    }
}
if ($verifiedArtifacts.Count -ne [int]$manifest.artifact_count -or $verifiedArtifacts.Count -le 0) {
    throw 'Prior WAL artifact count is invalid.'
}

$checkedAt = (Get-Date).ToUniversalTime()
$collectorSha = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
$facts = [ordered]@{
    schema_version = 'honghu.stage5_storage_transition_collector_facts.v1'
    authorization_reference = $AuthorizationReference
    approved_at_utc = $checkedAt.AddMilliseconds(1).ToString('o')
    collector = [ordered]@{
        schema_version = 'honghu.stage5_storage_transition_collector.v1'
        collector_script_sha256 = $collectorSha
        host_name = $env:COMPUTERNAME.ToLowerInvariant()
        checked_at_utc = $checkedAt.ToString('o')
        share_name = $ApprovedShareName.ToLowerInvariant()
        share_local_path = $sharePath
        approved_backup_root = $approvedPath
        share_local_path_verified = $true
        unc_live_probe_path = $uncRoot
        unc_live_probe_verified = $true
        smb_transport_encryption_required = $true
        machine_guid_sha256 = $machineGuidSha
        volume_serial = $volumeSerial
        filesystem = $filesystem
        bitlocker = [ordered]@{
            protection_status = $protectionStatus
            volume_status = $volumeStatus
            encryption_percentage = $encryptionPercentage
            verified = $true
        }
        artifact_hashes_verified = $true
    }
    source_host_identity_evidence = $sourceEvidence
    source_machine_guid_sha256 = $sourceEvidence.machine_guid_sha256
    old_endpoint_core = [ordered]@{
        kind = 'windows_unc'
        server = $OldEndpointAddress
        share = $ApprovedShareName.ToLowerInvariant()
        resolved_addresses = @($OldEndpointAddress)
        volume_serial = $volumeSerial
        filesystem = $filesystem
    }
    new_endpoint_core = [ordered]@{
        kind = 'windows_unc'
        server = $NewEndpointAddress
        share = $ApprovedShareName.ToLowerInvariant()
        resolved_addresses = @($NewEndpointAddress)
        volume_serial = $volumeSerial
        filesystem = $filesystem
    }
    old_storage_identity = $manifest.storage_identity
    new_storage_identity = $null
    prior_pointer_sha256 = (Get-FileHash -LiteralPath $pointerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    prior_manifest_identity_sha256 = $manifest.manifest_identity_sha256
    prior_manifest_file_sha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    prior_manifest = $manifest
    prior_artifacts = $verifiedArtifacts
    prior_artifacts_identity_sha256 = $null
    prior_artifact_count = $verifiedArtifacts.Count
    initial_boundary_evidence_identity_sha256 = $manifest.initial_recovery_boundary.evidence_identity_sha256
    old_at_rest_evidence_identity_sha256 = $manifest.at_rest_encryption.evidence_identity_sha256
    artifact_anchor_identity_sha256 = $null
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$factsPath = Join-Path $OutputDirectory '.storage_transition_collector_facts.tmp.json'
$payloadPath = Join-Path $OutputDirectory '.storage_transition_signed_payload.tmp.json'
$atRestPath = Join-Path $OutputDirectory 'storage_at_rest_new_endpoint.json'
$transitionPath = Join-Path $OutputDirectory 'storage_identity_transition.json'
$payloadBytes = $null
$signatureBytes = $null
try {
    [IO.File]::WriteAllText(
        $factsPath,
        (($facts | ConvertTo-Json -Depth 20) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )
    & $BootstrapPythonExe -I -B -S $bootstrap `
        --site-packages $SitePackages `
        --module tools.operations.storage_identity_transition `
        --collector-facts $factsPath `
        --canonical-payload-output $payloadPath
    if ($LASTEXITCODE -ne 0) { throw 'Canonical collector payload generation failed.' }
    $payloadBytes = [IO.File]::ReadAllBytes($payloadPath)
    $rsa = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($signingCertificate)
    if ($null -eq $rsa -or $rsa.KeySize -lt 3072) {
        throw 'Storage-attestation private key is not RSA-3072 or stronger.'
    }
    try {
        $signatureBytes = $rsa.SignData(
            $payloadBytes,
            [Security.Cryptography.HashAlgorithmName]::SHA256,
            [Security.Cryptography.RSASignaturePadding]::Pss
        )
    } finally { $rsa.Dispose() }
    $facts['collector_signature'] = [ordered]@{
        schema_version = 'honghu.stage5_storage_transition_signature.v1'
        algorithm = 'rsa-pss-sha256'
        certificate_sha256 = $publicCertificateSha
        certificate_thumbprint = $certificateThumbprint
        signed_payload_sha256 = (Get-FileHash -LiteralPath $payloadPath -Algorithm SHA256).Hash.ToLowerInvariant()
        signed_payload_base64 = [Convert]::ToBase64String($payloadBytes)
        signature_base64 = [Convert]::ToBase64String($signatureBytes)
    }
    [IO.File]::WriteAllText(
        $factsPath,
        (($facts | ConvertTo-Json -Depth 20) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )
    & $BootstrapPythonExe -I -B -S $bootstrap `
        --site-packages $SitePackages `
        --module tools.operations.storage_identity_transition `
        --collector-facts $factsPath `
        --at-rest-output $atRestPath `
        --transition-output $transitionPath
    if ($LASTEXITCODE -ne 0) { throw 'Storage-transition evidence sealing failed.' }
} finally {
    Remove-Item -LiteralPath $factsPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $payloadPath -Force -ErrorAction SilentlyContinue
    if ($null -ne $payloadBytes) { [Array]::Clear($payloadBytes,0,$payloadBytes.Length) }
    if ($null -ne $signatureBytes) { [Array]::Clear($signatureBytes,0,$signatureBytes.Length) }
}

[ordered]@{
    schema_version = 'honghu.stage5_storage_transition_collection_result.v1'
    collector_host = $env:COMPUTERNAME.ToLowerInvariant()
    collector_script_sha256 = $collectorSha
    transition_path = $transitionPath
    transition_file_sha256 = (Get-FileHash -LiteralPath $transitionPath -Algorithm SHA256).Hash.ToLowerInvariant()
    at_rest_path = $atRestPath
    at_rest_file_sha256 = (Get-FileHash -LiteralPath $atRestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    raw_machine_guid_recorded = $false
    secret_recorded = $false
} | ConvertTo-Json -Depth 6
