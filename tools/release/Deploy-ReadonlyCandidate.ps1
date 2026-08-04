param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$CommitSha,
    [Parameter(Mandatory = $true)]
    [string]$BootstrapPythonExe,
    [string]$Repository = "https://github.com/Garthzzz/honghu-ai-research-system",
    [string]$CandidateRoot = "C:\honghu-ai-research-candidate",
    [string]$ExistingProductionRoot = "C:\industry_demo",
    [int]$Port = 18080
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "CandidateProcess.ps1")

function Quote-HonghuArgument {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ($Value.Contains('"')) { throw "Command argument contains a quote and is unsafe." }
    return '"' + $Value + '"'
}

function Get-HonghuScheduledTaskSnapshot {
    try {
        $rows = New-Object System.Collections.Generic.List[string]
        $tasks = @(Get-ScheduledTask -ErrorAction Stop | Sort-Object TaskPath, TaskName)
        foreach ($task in $tasks) {
            $xml = Export-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -ErrorAction Stop
            $rows.Add("$($task.TaskPath)$($task.TaskName)`n$xml")
        }
        return [ordered]@{
            verified = $true
            task_count = $tasks.Count
            definitions_sha256 = Get-HonghuTextSha256 ($rows -join "`n---TASK---`n")
            error = $null
        }
    }
    catch {
        return [ordered]@{ verified = $false; task_count = $null; definitions_sha256 = $null; error = $_.Exception.Message }
    }
}

function Get-HonghuFileIdentity {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ exists = $false; sha256 = $null }
    }
    return [ordered]@{
        exists = $true
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Get-HonghuProductionState {
    param([Parameter(Mandatory = $true)][string]$Root)
    $health = [ordered]@{ reachable = $false; status = $null; identity_sha256 = $null; error = $null }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8080/api/health" -TimeoutSec 10
        $body = $response.Content | ConvertFrom-Json
        $identity = [ordered]@{
            viewer_mode = $body.viewer_mode
            release_version = $body.release_version
            release_manifest_sha256 = $body.release_manifest_sha256
            app_sha256 = $body.app_sha256
        } | ConvertTo-Json -Compress
        $health = [ordered]@{
            reachable = $true
            status = [int]$response.StatusCode
            identity_sha256 = Get-HonghuTextSha256 $identity
            error = $null
        }
    }
    catch {
        $health.error = $_.Exception.Message
    }
    $listeners = @()
    try {
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess -Unique | Sort-Object)
    }
    catch {}
    return [ordered]@{
        health = $health
        listener_pids = $listeners
        current_pointer = Get-HonghuFileIdentity (Join-Path $Root "current")
        broadcast_manifest = Get-HonghuFileIdentity (Join-Path $Root "BROADCAST_MANIFEST.json")
    }
}

function Test-HonghuProductionUnchanged {
    param($Before, $After)
    $reasons = New-Object System.Collections.Generic.List[string]
    if (-not $Before.health.reachable) { $reasons.Add("production 8080 was not reachable before candidate deployment") }
    if (-not $After.health.reachable) { $reasons.Add("production 8080 was not reachable after candidate deployment") }
    if ($Before.health.identity_sha256 -ne $After.health.identity_sha256) { $reasons.Add("production 8080 stable identity changed") }
    if (($Before.listener_pids -join ',') -ne ($After.listener_pids -join ',')) { $reasons.Add("production 8080 listener PID set changed") }
    if ($Before.current_pointer.exists -ne $After.current_pointer.exists -or $Before.current_pointer.sha256 -ne $After.current_pointer.sha256) {
        $reasons.Add("production current pointer changed")
    }
    if ($Before.broadcast_manifest.exists -ne $After.broadcast_manifest.exists -or $Before.broadcast_manifest.sha256 -ne $After.broadcast_manifest.sha256) {
        $reasons.Add("production broadcast manifest changed")
    }
    return [ordered]@{ verified = ($reasons.Count -eq 0); reasons = @($reasons) }
}

$candidate = [System.IO.Path]::GetFullPath($CandidateRoot).TrimEnd('\')
$production = [System.IO.Path]::GetFullPath($ExistingProductionRoot).TrimEnd('\')
$bootstrapPython = [System.IO.Path]::GetFullPath($BootstrapPythonExe)
if (-not [System.IO.Path]::IsPathRooted($BootstrapPythonExe) -or -not (Test-Path -LiteralPath $bootstrapPython -PathType Leaf)) {
    throw "BootstrapPythonExe must be an existing absolute python.exe path."
}
if ($candidate -eq $production -or $candidate.StartsWith($production + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "CandidateRoot must be outside ExistingProductionRoot."
}
if ($Port -eq 8080) { throw "The read-only candidate cannot use production port 8080." }
if (-not (Test-Path -LiteralPath (Join-Path $production "data") -PathType Container)) {
    throw "Production data directory does not exist: $production"
}

$source = Join-Path $candidate "source"
$runtime = Join-Path $candidate "runtime"
$recordPath = Join-Path $runtime "viewer_candidate_process.json"
$evidencePath = Join-Path $runtime "vm_readonly_candidate_evidence.json"
New-Item -ItemType Directory -Force $candidate, $runtime | Out-Null

$pythonVersion = (& $bootstrapPython -c "import json,sys; print(json.dumps({'version':list(sys.version_info[:3]),'executable':sys.executable}))") | ConvertFrom-Json
if ([int]$pythonVersion.version[0] -ne 3 -or [int]$pythonVersion.version[1] -ne 10) {
    throw "BootstrapPythonExe must be Python 3.10; found $($pythonVersion.version -join '.')."
}
if ([System.IO.Path]::GetFullPath([string]$pythonVersion.executable) -ne $bootstrapPython) {
    throw "BootstrapPythonExe resolved to an unexpected interpreter."
}

$preTasks = Get-HonghuScheduledTaskSnapshot
$preProduction = Get-HonghuProductionState -Root $production
$evidence = [ordered]@{
    schema_version = "honghu.vm_readonly_candidate_evidence.v2"
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    requested_commit_sha = $CommitSha.ToLowerInvariant()
    candidate_port = $Port
    static_guarantees = [ordered]@{
        candidate_root_separate_from_production = $true
        candidate_port_not_8080 = $true
        deployment_script_contains_no_task_mutation = $true
        database_authority_not_switched = $true
    }
    pre_state = [ordered]@{ scheduled_tasks = $preTasks; production = $preProduction }
    observed = [ordered]@{}
    post_state = $null
    unverified = @("LAN client reachability must be tested from a separate intranet client")
    ok = $false
    error = $null
}

$launched = $false
$completed = $false
$launchedRecord = $null
$candidateActivated = $false
$previousCandidateCommit = $null
try {
    if (-not (Test-Path -LiteralPath (Join-Path $source ".git") -PathType Container)) {
        git clone --filter=blob:none --no-checkout $Repository $source
        if ($LASTEXITCODE -ne 0) { throw "Candidate source clone failed." }
    }
    git -C $source fetch --no-tags origin $CommitSha
    if ($LASTEXITCODE -ne 0) { throw "Cannot fetch the requested commit." }
    git -C $source checkout --detach $CommitSha
    if ($LASTEXITCODE -ne 0) { throw "Cannot check out the requested commit." }
    $resolved = (git -C $source rev-parse HEAD).Trim().ToLowerInvariant()
    if ($resolved -ne $CommitSha.ToLowerInvariant()) { throw "Checked out commit differs from the request." }

    $lockPath = Join-Path $source "requirements.lock.txt"
    $lockHash = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $venvRoot = Join-Path (Join-Path $candidate "python-envs") $lockHash.Substring(0, 16)
    $venvPython = Join-Path $venvRoot "Scripts\python.exe"
    $venvMarker = Join-Path $venvRoot "honghu-runtime.json"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        if (Test-Path -LiteralPath $venvRoot) { throw "Candidate venv directory exists but is incomplete: $venvRoot" }
        $venvStaging = "$venvRoot.staging-$PID-$([guid]::NewGuid().ToString('N'))"
        $stagingPython = Join-Path $venvStaging "Scripts\python.exe"
        & $bootstrapPython -m venv $venvStaging
        if ($LASTEXITCODE -ne 0) { throw "Candidate virtual environment creation failed." }
        & $stagingPython -m pip install --disable-pip-version-check --require-hashes -r $lockPath
        if ($LASTEXITCODE -ne 0) { throw "Locked candidate dependency installation failed." }
        [ordered]@{
            schema_version = "honghu.candidate_python_environment.v1"
            lockfile_sha256 = $lockHash
            bootstrap_python = $bootstrapPython
            created_at = (Get-Date).ToUniversalTime().ToString("o")
        } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $venvStaging "honghu-runtime.json") -Encoding UTF8
        Move-Item -LiteralPath $venvStaging -Destination $venvRoot -ErrorAction Stop
    }
    if (-not (Test-Path -LiteralPath $venvMarker -PathType Leaf)) { throw "Candidate venv identity marker is missing." }
    $marker = Get-Content -LiteralPath $venvMarker -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$marker.lockfile_sha256 -ne $lockHash) { throw "Candidate venv lockfile identity mismatch." }
    & $venvPython (Join-Path $source "tools\release\runtime_environment.py") --lockfile $lockPath
    if ($LASTEXITCODE -ne 0) { throw "Candidate Python runtime verification failed." }

    Push-Location $source
    try {
        & $venvPython -m tools.release.cli build --repo-root $source --deploy-root $candidate --commit $resolved
        if ($LASTEXITCODE -ne 0) { throw "Immutable release build failed." }
        $release = Join-Path (Join-Path $candidate "releases") $resolved
        $preflightPath = Join-Path $runtime "candidate_preflight.json"
        & $venvPython -m tools.release.cli preflight --release-dir $release --data-root (Join-Path $production "data") --content-root $production --state-root $runtime --output $preflightPath
        if ($LASTEXITCODE -ne 0) { throw "Read-only candidate preflight failed." }
        $preflightSha = (Get-FileHash -LiteralPath $preflightPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    finally { Pop-Location }

    $priorStop = Stop-HonghuVerifiedCandidate -RecordPath $recordPath
    $evidence.observed.prior_candidate_cleanup = $priorStop
    $portOwner = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if ($portOwner.Count -gt 0) { throw "Candidate port $Port is already owned by an untracked process." }

    $candidateCurrentPath = Join-Path $candidate "current"
    if (Test-Path -LiteralPath $candidateCurrentPath -PathType Leaf) {
        $previousPointer = Get-Content -LiteralPath $candidateCurrentPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $previousCandidateCommit = [string]$previousPointer.commit_sha
    }

    Push-Location $source
    try {
        & $venvPython -m tools.release.cli activate --deploy-root $candidate --commit $resolved --data-root (Join-Path $production "data") --actor "phase2-vm-candidate"
        if ($LASTEXITCODE -ne 0) { throw "Candidate current activation failed." }
        $candidateActivated = $true
    }
    finally { Pop-Location }

    $launchId = [guid]::NewGuid().ToString("N")
    $arguments = @(
        "-B", "-m", "tools.release.cli", "serve-readonly-candidate",
        "--deploy-root", $candidate,
        "--data-root", (Join-Path $production "data"),
        "--content-root", $production,
        "--state-root", $runtime,
        "--host", "0.0.0.0",
        "--port", [string]$Port,
        "--launch-id", $launchId,
        "--expected-commit", $resolved,
        "--preflight-report", $preflightPath,
        "--preflight-report-sha256", $preflightSha
    )
    $argumentString = ($arguments | ForEach-Object { Quote-HonghuArgument ([string]$_) }) -join " "
    $stdout = Join-Path $runtime "viewer_candidate.stdout.log"
    $stderr = Join-Path $runtime "viewer_candidate.stderr.log"
    $process = Start-Process -FilePath $venvPython -ArgumentList $argumentString -WorkingDirectory $release -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $launched = $true
    Start-Sleep -Milliseconds 250
    $snapshot = Get-HonghuCandidateProcessSnapshot -ProcessId $process.Id
    if ($null -eq $snapshot) { throw "Candidate process exited before identity capture." }
    $record = [ordered]@{
        schema_version = "honghu.candidate_process_identity.v1"
        pid = $snapshot.pid
        start_time_utc = $snapshot.start_time_utc
        executable_path = $snapshot.executable_path
        command_line_sha256 = $snapshot.command_line_sha256
        launch_id = $launchId
        commit_sha = $resolved
        manifest_sha256 = (Get-Content -LiteralPath (Join-Path $release "RELEASE_MANIFEST.sha256") -Raw).Trim()
        port = $Port
        candidate_root = $candidate
        created_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    $launchedRecord = $record
    $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $recordPath -Encoding UTF8
    $identity = Test-HonghuCandidateProcessIdentity -Record $record -Snapshot $snapshot
    if (-not $identity.ok) { throw "Candidate process identity verification failed." }

    $ready = $false
    for ($attempt = 1; $attempt -le 45; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
            if ($health.ok -and $health.viewer_mode -eq "readonly_candidate" -and $health.release.commit_sha -eq $resolved -and [int]$health.candidate_process.pid -eq $process.Id -and $health.candidate_process.launch_id -eq $launchId) {
                $ready = $true
                break
            }
        }
        catch {}
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "Candidate did not pass process-bound health within 45 seconds." }

    $smokePath = Join-Path $runtime "representative_readonly_smoke.json"
    Push-Location $release
    try {
        & $venvPython -m tools.release.readonly_smoke --base-url "http://127.0.0.1:$Port" --data-root (Join-Path $production "data") --content-root $production --expected-commit $resolved --expected-launch-id $launchId --expected-pid $process.Id --output $smokePath
        if ($LASTEXITCODE -ne 0) { throw "Representative read-only smoke failed." }
    }
    finally { Pop-Location }
    $smoke = Get-Content -LiteralPath $smokePath -Raw -Encoding UTF8 | ConvertFrom-Json

    $postTasks = Get-HonghuScheduledTaskSnapshot
    $postProduction = Get-HonghuProductionState -Root $production
    $taskUnchanged = [ordered]@{
        verified = ($preTasks.verified -and $postTasks.verified -and $preTasks.definitions_sha256 -eq $postTasks.definitions_sha256)
        reason = if (-not $preTasks.verified -or -not $postTasks.verified) { "scheduled task definitions could not be read" } elseif ($preTasks.definitions_sha256 -ne $postTasks.definitions_sha256) { "scheduled task definitions changed" } else { $null }
    }
    $productionUnchanged = Test-HonghuProductionUnchanged -Before $preProduction -After $postProduction
    if (-not $taskUnchanged.verified) { throw "Scheduled task before/after evidence is not stable." }
    if (-not $productionUnchanged.verified) { throw "Production 8080/current evidence is not stable." }

    $evidence.observed.process_identity = $record
    $evidence.observed.process_identity_verified = $identity
    $evidence.observed.python_runtime = Get-Content -LiteralPath $venvMarker -Raw -Encoding UTF8 | ConvertFrom-Json
    $evidence.observed.representative_smoke = $smoke
    $evidence.observed.scheduled_tasks_unchanged = $taskUnchanged
    $evidence.observed.production_8080_and_pointer_unchanged = $productionUnchanged
    $evidence.post_state = [ordered]@{ scheduled_tasks = $postTasks; production = $postProduction }
    $evidence.completed_at = (Get-Date).ToUniversalTime().ToString("o")
    $evidence.ok = $true
    $completed = $true
}
catch {
    $evidence.error = $_.Exception.Message
    if ($launched) {
        try {
            if (Test-Path -LiteralPath $recordPath -PathType Leaf) {
                $evidence.observed.failure_cleanup = Stop-HonghuVerifiedCandidate -RecordPath $recordPath
            }
            elseif ($null -ne $launchedRecord) {
                $currentSnapshot = Get-HonghuCandidateProcessSnapshot -ProcessId ([int]$launchedRecord.pid)
                if ($null -ne $currentSnapshot) {
                    $cleanupIdentity = Test-HonghuCandidateProcessIdentity -Record $launchedRecord -Snapshot $currentSnapshot
                    if (-not $cleanupIdentity.ok) { throw "Unrecorded candidate process identity mismatch during failure cleanup." }
                    Stop-Process -Id ([int]$launchedRecord.pid) -Force -ErrorAction Stop
                    try { Wait-Process -Id ([int]$launchedRecord.pid) -Timeout 15 -ErrorAction SilentlyContinue } catch {}
                }
                $evidence.observed.failure_cleanup = [ordered]@{ ok = $true; status = "verified-unrecorded-candidate-stopped" }
            }
            else {
                throw "Candidate launched but no verifiable process identity was captured. Manual port/PID inspection is required."
            }
        }
        catch { $evidence.observed.failure_cleanup = [ordered]@{ ok = $false; error = $_.Exception.Message } }
    }
    if ($candidateActivated) {
        try {
            if (-not [string]::IsNullOrWhiteSpace($previousCandidateCommit)) {
                Push-Location $source
                try {
                    & $venvPython -m tools.release.cli rollback --deploy-root $candidate --data-root (Join-Path $production "data") --actor "phase2-vm-candidate-failure" --target-commit $previousCandidateCommit
                    if ($LASTEXITCODE -ne 0) { throw "Candidate pointer rollback command failed." }
                }
                finally { Pop-Location }
                $evidence.observed.failure_pointer_recovery = [ordered]@{ ok = $true; restored_commit = $previousCandidateCommit }
            }
            else {
                Remove-Item -LiteralPath (Join-Path $candidate "current") -Force -ErrorAction Stop
                $evidence.observed.failure_pointer_recovery = [ordered]@{ ok = $true; restored_state = "no-current" }
            }
        }
        catch { $evidence.observed.failure_pointer_recovery = [ordered]@{ ok = $false; error = $_.Exception.Message } }
    }
    $evidence.post_state = [ordered]@{
        scheduled_tasks = Get-HonghuScheduledTaskSnapshot
        production = Get-HonghuProductionState -Root $production
    }
    $evidence.completed_at = (Get-Date).ToUniversalTime().ToString("o")
    $evidence | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $evidencePath -Encoding UTF8
    throw
}

if ($completed) {
    $evidence | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $evidencePath -Encoding UTF8
    Write-Host "Read-only candidate is running at http://127.0.0.1:$Port/"
    Write-Host "VM-local evidence: $evidencePath"
    Write-Host "LAN-client reachability is intentionally still unverified."
}
