param(
    [string]$CandidateRoot = "C:\honghu-ai-research-candidate"
)

$ErrorActionPreference = "Stop"
$helper = Join-Path $PSScriptRoot "CandidateProcess.ps1"
. $helper
$recordPath = Join-Path ([System.IO.Path]::GetFullPath($CandidateRoot)) "runtime\viewer_candidate_process.json"
$result = Stop-HonghuVerifiedCandidate -RecordPath $recordPath
$result | ConvertTo-Json -Depth 5
