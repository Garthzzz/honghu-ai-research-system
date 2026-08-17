[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$StorageIdentity,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [string]$MountPoint = 'D:'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$volume = Get-BitLockerVolume -MountPoint $MountPoint -ErrorAction Stop
$enabled = (
    $volume.ProtectionStatus.ToString() -eq 'On' -and
    $volume.VolumeStatus.ToString() -in @('FullyEncrypted','EncryptionInProgress') -and
    [double]$volume.EncryptionPercentage -ge 100
)
if (-not $enabled) {
    throw 'The approved off-VM volume is not fully protected by BitLocker.'
}
$payload = [ordered]@{
    schema_version = 'honghu.storage_at_rest_encryption.v1'
    status = 'verified'
    verification_method = 'windows_bitlocker_volume_probe'
    storage_identity = $StorageIdentity.ToLowerInvariant()
    checked_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    volume_encryption_enabled = $true
}
$parent = Split-Path -Parent $OutputPath
if ($parent) { New-Item -ItemType Directory -Force $parent | Out-Null }
[IO.File]::WriteAllText(
    $OutputPath,
    (($payload | ConvertTo-Json -Depth 5) + [Environment]::NewLine),
    [Text.UTF8Encoding]::new($false)
)
$payload | ConvertTo-Json -Depth 5
