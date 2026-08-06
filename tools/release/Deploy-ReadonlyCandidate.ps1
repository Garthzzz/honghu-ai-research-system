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

# Every Python child is isolated from caller-controlled import roots.  ``-I``
# is still supplied explicitly to each invocation; these environment controls
# are defense in depth and apply only to this PowerShell process and children.
$inheritedPythonPathPresent = Test-Path Env:PYTHONPATH
$inheritedPythonHomePresent = Test-Path Env:PYTHONHOME
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONNOUSERSITE = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Quote-HonghuArgument {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ($Value.Contains('"')) { throw "Command argument contains a quote and is unsafe." }
    return '"' + $Value + '"'
}

function Get-HonghuExactReleaseVerification {
    param(
        [Parameter(Mandatory = $true)][string]$Interpreter,
        [Parameter(Mandatory = $true)][string]$Bootstrap,
        [Parameter(Mandatory = $true)][string]$SitePackages,
        [Parameter(Mandatory = $true)][string]$ReleasePath,
        [Parameter(Mandatory = $true)][string]$Stage
    )
    $text = (& $Interpreter -I -B -S $Bootstrap --site-packages $SitePackages --module "tools.release.cli" verify --release-dir $ReleasePath | Out-String)
    if ($LASTEXITCODE -ne 0) { throw "Exact release verification failed after $Stage." }
    $payload = $text | ConvertFrom-Json
    return [ordered]@{
        ok = $true
        stage = $Stage
        commit_sha = [string]$payload.commit_sha
        manifest_sha256 = [string]$payload.manifest_sha256
        file_count = [int]$payload.file_count
        verified_at = (Get-Date).ToUniversalTime().ToString("o")
    }
}

function Save-HonghuEvidenceDocument {
    param(
        [Parameter(Mandatory = $true)]$Evidence,
        [Parameter(Mandatory = $true)][string]$AttemptPath,
        [Parameter(Mandatory = $true)][string]$LatestPath
    )
    $json = $Evidence | ConvertTo-Json -Depth 20
    $json | Set-Content -LiteralPath $AttemptPath -Encoding UTF8
    $json | Set-Content -LiteralPath $LatestPath -Encoding UTF8
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
$attemptId = "$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmss.fffffffZ'))-$([guid]::NewGuid().ToString('N').Substring(0, 12))"
$attemptEvidencePath = Join-Path $runtime "vm_readonly_candidate_evidence.$attemptId.json"
$priorEvidenceArchive = $null
if (Test-Path -LiteralPath $evidencePath -PathType Leaf) {
    $historyRoot = Join-Path $runtime "evidence_history"
    New-Item -ItemType Directory -Force $historyRoot | Out-Null
    $priorHash = (Get-FileHash -LiteralPath $evidencePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $priorEvidenceArchive = Join-Path $historyRoot "vm_readonly_candidate_evidence.$attemptId.$($priorHash.Substring(0, 12)).json"
    Copy-Item -LiteralPath $evidencePath -Destination $priorEvidenceArchive -ErrorAction Stop
}

$pythonVersion = (& $bootstrapPython -I -B -c "import json,sys; print(json.dumps({'version':list(sys.version_info[:3]),'executable':sys.executable}))") | ConvertFrom-Json
if ([int]$pythonVersion.version[0] -ne 3 -or [int]$pythonVersion.version[1] -ne 10) {
    throw "BootstrapPythonExe must be Python 3.10; found $($pythonVersion.version -join '.')."
}
if ([System.IO.Path]::GetFullPath([string]$pythonVersion.executable) -ne $bootstrapPython) {
    throw "BootstrapPythonExe resolved to an unexpected interpreter."
}

$preTasks = Get-HonghuScheduledTaskSnapshot
$preProduction = Get-HonghuProductionState -Root $production
$evidence = [ordered]@{
    schema_version = "honghu.vm_readonly_candidate_evidence.v4"
    attempt_id = $attemptId
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    requested_commit_sha = $CommitSha.ToLowerInvariant()
    candidate_port = $Port
    static_guarantees = [ordered]@{
        candidate_root_separate_from_production = $true
        candidate_port_not_8080 = $true
        deployment_script_contains_no_task_mutation = $true
        database_authority_not_switched = $true
        python_isolated_mode_required = $true
        bytecode_writes_disabled = $true
    }
    pre_state = [ordered]@{ scheduled_tasks = $preTasks; production = $preProduction }
    observed = [ordered]@{
        prior_evidence_archive = $priorEvidenceArchive
        python_import_environment = [ordered]@{
            inherited_pythonpath_was_present = $inheritedPythonPathPresent
            inherited_pythonhome_was_present = $inheritedPythonHomePresent
            pythonpath_removed_for_children = -not (Test-Path Env:PYTHONPATH)
            pythonhome_removed_for_children = -not (Test-Path Env:PYTHONHOME)
            isolated_flag = "-I"
            dont_write_bytecode_flag = "-B"
        }
    }
    post_state = $null
    unverified = @("LAN client reachability must be tested from a separate intranet client")
    ok = $false
    error = $null
    failure = [ordered]@{ primary = $null; cleanup = $null; pointer_recovery = $null }
}

$launched = $false
$completed = $false
$launchedRecord = $null
$candidateActivated = $false
$previousCandidateCommit = $null
$release = $null
$releaseIntegrity = [ordered]@{}
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
        & $bootstrapPython -I -B -m venv $venvStaging
        if ($LASTEXITCODE -ne 0) { throw "Candidate virtual environment creation failed." }
        & $stagingPython -I -B -m pip install --disable-pip-version-check --require-hashes -r $lockPath
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
    $runtimeVerificationText = (& $venvPython -I -B (Join-Path $source "tools\release\runtime_environment.py") --lockfile $lockPath | Out-String)
    if ($LASTEXITCODE -ne 0) { throw "Candidate Python runtime verification failed." }
    try {
        $runtimeVerification = $runtimeVerificationText | ConvertFrom-Json
    }
    catch {
        throw "Candidate Python runtime verification did not return valid JSON."
    }
    if (-not $runtimeVerification.ok) { throw "Candidate Python runtime verification reported failure." }
    $listenerPython = [string]$runtimeVerification.base_python_executable
    $lockedSitePackages = [string]$runtimeVerification.site_packages
    if (-not (Test-Path -LiteralPath $listenerPython -PathType Leaf)) { throw "Candidate listener base Python is missing." }
    if (-not (Test-Path -LiteralPath $lockedSitePackages -PathType Container)) { throw "Candidate locked site-packages directory is missing." }
    $sourceBootstrap = Join-Path $source "tools\release\direct_candidate.py"
    if (-not (Test-Path -LiteralPath $sourceBootstrap -PathType Leaf)) { throw "Candidate source bootstrap is missing." }

    # A prior listener must be identity-checked and stopped before an existing
    # release can be considered for reuse or quarantine.  The builder still
    # refuses to quarantine anything referenced by current or by a remaining
    # process record.
    $priorRecordedCommit = $null
    if (Test-Path -LiteralPath $recordPath -PathType Leaf) {
        try {
            $priorRecordForProtection = Get-Content -LiteralPath $recordPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $priorRecordedCommit = [string]$priorRecordForProtection.commit_sha
        }
        catch {
            throw "Existing candidate process record is unreadable; refusing deployment."
        }
    }
    $priorRecordCommitIdentity = $priorRecordedCommit
    $priorStop = Stop-HonghuVerifiedCandidate -RecordPath $recordPath
    if ([string](Get-HonghuOptionalProperty $priorStop "status") -eq "stale-record-archived") {
        # The process/port absence proof has converted the old record into an
        # audit archive, so it no longer protects the release from an otherwise
        # valid inactive-release quarantine decision in this same attempt.
        $priorRecordedCommit = $null
    }
    $evidence.observed.prior_candidate_cleanup = $priorStop
    $evidence.observed.prior_candidate_release_protection = [ordered]@{
        recorded_commit_sha = $priorRecordCommitIdentity
        active_protection_commit_sha = $priorRecordedCommit
        automatic_quarantine_allowed_for_requested_sha = (
            [string]::IsNullOrWhiteSpace($priorRecordedCommit) -or
            $priorRecordedCommit.ToLowerInvariant() -ne $resolved
        )
    }
    $portOwner = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if ($portOwner.Count -gt 0) { throw "Candidate port $Port is already owned by an untracked process." }

    Push-Location $source
    try {
        $buildArguments = @(
            "-I", "-B", "-S", $sourceBootstrap,
            "--site-packages", $lockedSitePackages,
            "--module", "tools.release.cli",
            "build", "--repo-root", $source,
            "--deploy-root", $candidate,
            "--commit", $resolved
        )
        if ([string]::IsNullOrWhiteSpace($priorRecordedCommit) -or $priorRecordedCommit.ToLowerInvariant() -ne $resolved) {
            $buildArguments += "--quarantine-invalid-inactive"
        }
        $buildText = (& $listenerPython @buildArguments | Out-String)
        if ($LASTEXITCODE -ne 0) { throw "Immutable release build failed." }
        $release = Join-Path (Join-Path $candidate "releases") $resolved
        $buildResult = $buildText | ConvertFrom-Json
        $buildQuarantineRecord = $null
        if ($buildResult.PSObject.Properties.Name -contains "quarantine_record") {
            $buildQuarantineRecord = $buildResult.quarantine_record
        }
        $evidence.observed.release_build = [ordered]@{
            disposition = [string]$buildResult.build_disposition
            quarantine_record = $buildQuarantineRecord
        }
        $releaseIntegrity.after_build = Get-HonghuExactReleaseVerification -Interpreter $listenerPython -Bootstrap $sourceBootstrap -SitePackages $lockedSitePackages -ReleasePath $release -Stage "build"
        $preflightPath = Join-Path $runtime "candidate_preflight.json"
        & $listenerPython -I -B -S $sourceBootstrap --site-packages $lockedSitePackages --module "tools.release.cli" preflight --release-dir $release --data-root (Join-Path $production "data") --content-root $production --state-root $runtime --output $preflightPath
        if ($LASTEXITCODE -ne 0) { throw "Read-only candidate preflight failed." }
        $releaseIntegrity.after_preflight = Get-HonghuExactReleaseVerification -Interpreter $listenerPython -Bootstrap $sourceBootstrap -SitePackages $lockedSitePackages -ReleasePath $release -Stage "preflight"
        $preflightSha = (Get-FileHash -LiteralPath $preflightPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    finally { Pop-Location }

    $candidateCurrentPath = Join-Path $candidate "current"
    if (Test-Path -LiteralPath $candidateCurrentPath -PathType Leaf) {
        $previousPointer = Get-Content -LiteralPath $candidateCurrentPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $previousCandidateCommit = [string]$previousPointer.commit_sha
    }

    Push-Location $source
    try {
        & $listenerPython -I -B -S $sourceBootstrap --site-packages $lockedSitePackages --module "tools.release.cli" activate --deploy-root $candidate --commit $resolved --data-root (Join-Path $production "data") --actor "phase2-vm-candidate"
        if ($LASTEXITCODE -ne 0) { throw "Candidate current activation failed." }
        $candidateActivated = $true
        $releaseIntegrity.after_activate = Get-HonghuExactReleaseVerification -Interpreter $listenerPython -Bootstrap $sourceBootstrap -SitePackages $lockedSitePackages -ReleasePath $release -Stage "activate"
    }
    finally { Pop-Location }

    $launchId = [guid]::NewGuid().ToString("N")
    $listenerBootstrap = Join-Path $release "tools\release\direct_candidate.py"
    if (-not (Test-Path -LiteralPath $listenerBootstrap -PathType Leaf)) { throw "Candidate direct listener bootstrap is missing." }
    $arguments = @(
        "-I", "-B", "-S", $listenerBootstrap,
        "--site-packages", $lockedSitePackages,
        "--module", "tools.release.cli",
        "serve-readonly-candidate",
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
    $process = Start-Process -FilePath $listenerPython -ArgumentList $argumentString -WorkingDirectory $release -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $launched = $true
    Start-Sleep -Milliseconds 250
    $snapshot = Get-HonghuCandidateProcessSnapshot -ProcessId $process.Id -Port $Port
    if ($null -eq $snapshot) { throw "Candidate process exited before identity capture." }
    $record = [ordered]@{
        schema_version = "honghu.candidate_process_identity.v1"
        pid = $snapshot.pid
        start_time_utc = $snapshot.start_time_utc
        executable_path = $snapshot.executable_path
        locked_site_packages = $lockedSitePackages
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
            $healthRelease = Get-HonghuOptionalProperty $health "release"
            $healthProcess = Get-HonghuOptionalProperty $health "candidate_process"
            if (
                [bool](Get-HonghuOptionalProperty $health "ok" $false) -and
                [string](Get-HonghuOptionalProperty $health "viewer_mode") -eq "readonly_candidate" -and
                [string](Get-HonghuOptionalProperty $healthRelease "commit_sha") -eq $resolved -and
                [int](Get-HonghuOptionalProperty $healthProcess "pid" -1) -eq $process.Id -and
                [string](Get-HonghuOptionalProperty $healthProcess "launch_id") -eq $launchId
            ) {
                $ready = $true
                break
            }
        }
        catch {}
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "Candidate did not pass process-bound health within 45 seconds." }
    $releaseIntegrity.after_launch = Get-HonghuExactReleaseVerification -Interpreter $listenerPython -Bootstrap $sourceBootstrap -SitePackages $lockedSitePackages -ReleasePath $release -Stage "launch"

    $smokePath = Join-Path $runtime "representative_readonly_smoke.json"
    Push-Location $release
    try {
        & $listenerPython -I -B -S $listenerBootstrap --site-packages $lockedSitePackages --module "tools.release.readonly_smoke" --base-url "http://127.0.0.1:$Port" --data-root (Join-Path $production "data") --content-root $production --expected-commit $resolved --expected-launch-id $launchId --expected-pid $process.Id --output $smokePath
        if ($LASTEXITCODE -ne 0) { throw "Representative read-only smoke failed." }
    }
    finally { Pop-Location }
    $releaseIntegrity.after_smoke = Get-HonghuExactReleaseVerification -Interpreter $listenerPython -Bootstrap $sourceBootstrap -SitePackages $lockedSitePackages -ReleasePath $release -Stage "smoke"
    $smoke = Get-Content -LiteralPath $smokePath -Raw -Encoding UTF8 | ConvertFrom-Json

    $postTasks = Get-HonghuScheduledTaskSnapshot
    $postProduction = Get-HonghuProductionState -Root $production
    $taskUnchanged = [ordered]@{
        verified = ($preTasks.verified -and $postTasks.verified -and $preTasks.definitions_sha256 -eq $postTasks.definitions_sha256)
        reason = if (-not $preTasks.verified -or -not $postTasks.verified) { "scheduled task definitions could not be read" } elseif ($preTasks.definitions_sha256 -ne $postTasks.definitions_sha256) { "scheduled task definitions changed" } else { $null }
    }
    $productionUnchanged = Test-HonghuProductionUnchanged -Before $preProduction -After $postProduction
    $evidence.observed.process_identity = $record
    $evidence.observed.process_identity_verified = $identity
    $evidence.observed.python_environment = Get-Content -LiteralPath $venvMarker -Raw -Encoding UTF8 | ConvertFrom-Json
    $evidence.observed.python_runtime = $runtimeVerification
    $evidence.observed.representative_smoke = $smoke
    $evidence.observed.immutable_release_integrity = $releaseIntegrity
    $evidence.observed.scheduled_tasks_unchanged = $taskUnchanged
    $evidence.observed.production_8080_and_pointer_unchanged = $productionUnchanged
    $evidence.post_state = [ordered]@{ scheduled_tasks = $postTasks; production = $postProduction }
    if (-not $taskUnchanged.verified) { throw "Scheduled task before/after evidence is not stable." }
    if (-not $productionUnchanged.verified) { throw "Production 8080/current evidence is not stable." }
    $evidence.completed_at = (Get-Date).ToUniversalTime().ToString("o")
    $evidence.ok = $true
    $completed = $true
}
catch {
    $primaryFailure = $_
    $evidence.error = $primaryFailure.Exception.Message
    $evidence.failure.primary = [ordered]@{
        message = $primaryFailure.Exception.Message
        category = [string]$primaryFailure.CategoryInfo.Category
        fully_qualified_error_id = [string]$primaryFailure.FullyQualifiedErrorId
    }
    if ($launched) {
        try {
            if (Test-Path -LiteralPath $recordPath -PathType Leaf) {
                $evidence.observed.failure_cleanup = Stop-HonghuVerifiedCandidate -RecordPath $recordPath
            }
            elseif ($null -ne $launchedRecord) {
                $cleanupIdentity = $null
                $currentSnapshot = Get-HonghuCandidateProcessSnapshot -ProcessId ([int]$launchedRecord.pid) -Port ([int]$launchedRecord.port)
                if ($null -ne $currentSnapshot) {
                    $cleanupIdentity = Test-HonghuCandidateProcessIdentity -Record $launchedRecord -Snapshot $currentSnapshot -RequireStopAuthority
                    if (-not $cleanupIdentity.ok) { throw "Unrecorded candidate process identity mismatch during failure cleanup." }
                    Stop-Process -Id ([int]$launchedRecord.pid) -Force -ErrorAction Stop
                    try { Wait-Process -Id ([int]$launchedRecord.pid) -Timeout 15 -ErrorAction SilentlyContinue } catch {}
                }
                $evidence.observed.failure_cleanup = [ordered]@{ ok = $true; status = "verified-unrecorded-candidate-stopped"; identity = $cleanupIdentity }
            }
            else {
                throw "Candidate launched but no verifiable process identity was captured. Manual port/PID inspection is required."
            }
        }
        catch { $evidence.observed.failure_cleanup = [ordered]@{ ok = $false; error = $_.Exception.Message } }
        $evidence.failure.cleanup = $evidence.observed.failure_cleanup
    }
    if ($candidateActivated) {
        try {
            if (-not [string]::IsNullOrWhiteSpace($previousCandidateCommit)) {
                Push-Location $source
                try {
                    & $listenerPython -I -B -S $sourceBootstrap --site-packages $lockedSitePackages --module "tools.release.cli" rollback --deploy-root $candidate --data-root (Join-Path $production "data") --actor "phase2-vm-candidate-failure" --target-commit $previousCandidateCommit
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
        $evidence.failure.pointer_recovery = $evidence.observed.failure_pointer_recovery
    }
    if ($null -ne $release -and (Test-Path -LiteralPath $release -PathType Container)) {
        try {
            $releaseIntegrity.after_failure_cleanup = Get-HonghuExactReleaseVerification -Interpreter $listenerPython -Bootstrap $sourceBootstrap -SitePackages $lockedSitePackages -ReleasePath $release -Stage "failure-cleanup"
        }
        catch {
            $releaseIntegrity.after_failure_cleanup = [ordered]@{
                ok = $false
                stage = "failure-cleanup"
                error = $_.Exception.Message
            }
        }
        $evidence.observed.immutable_release_integrity = $releaseIntegrity
    }
    $failurePostTasks = Get-HonghuScheduledTaskSnapshot
    $failurePostProduction = Get-HonghuProductionState -Root $production
    $failureTaskComparison = [ordered]@{
        verified = ($preTasks.verified -and $failurePostTasks.verified -and $preTasks.definitions_sha256 -eq $failurePostTasks.definitions_sha256)
        reason = if (-not $preTasks.verified -or -not $failurePostTasks.verified) { "scheduled task definitions could not be read" } elseif ($preTasks.definitions_sha256 -ne $failurePostTasks.definitions_sha256) { "scheduled task definitions changed" } else { $null }
    }
    $failureProductionComparison = Test-HonghuProductionUnchanged -Before $preProduction -After $failurePostProduction
    $evidence.observed.scheduled_tasks_unchanged = $failureTaskComparison
    $evidence.observed.production_8080_and_pointer_unchanged = $failureProductionComparison
    $evidence.post_state = [ordered]@{ scheduled_tasks = $failurePostTasks; production = $failurePostProduction }
    $evidence.completed_at = (Get-Date).ToUniversalTime().ToString("o")
    Save-HonghuEvidenceDocument -Evidence $evidence -AttemptPath $attemptEvidencePath -LatestPath $evidencePath
    throw $primaryFailure
}

if ($completed) {
    Save-HonghuEvidenceDocument -Evidence $evidence -AttemptPath $attemptEvidencePath -LatestPath $evidencePath
    Write-Host "Read-only candidate is running at http://127.0.0.1:$Port/"
    Write-Host "VM-local evidence: $evidencePath"
    Write-Host "LAN-client reachability is intentionally still unverified."
}
