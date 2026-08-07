Set-StrictMode -Version Latest

function Get-HonghuTextSha256 {
    param([Parameter(Mandatory = $true)][string]$Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-HonghuOptionalProperty {
    param(
        $InputObject,
        [Parameter(Mandatory = $true)][string]$Name,
        $Default = $null
    )
    if ($null -eq $InputObject) { return $Default }
    if ($InputObject -is [System.Collections.IDictionary]) {
        if ($InputObject.Contains($Name)) { return $InputObject[$Name] }
        return $Default
    }
    $property = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    try { return $property.Value } catch { return $Default }
}

function Test-HonghuOptionalProperty {
    param(
        $InputObject,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($null -eq $InputObject) { return $false }
    if ($InputObject -is [System.Collections.IDictionary]) { return $InputObject.Contains($Name) }
    return ($null -ne $InputObject.PSObject.Properties[$Name])
}

function ConvertTo-HonghuFullPathOrNull {
    param($Value)
    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) { return $null }
    try { return [System.IO.Path]::GetFullPath([string]$Value) } catch { return $null }
}

function Get-HonghuListenerPids {
    param([Parameter(Mandatory = $true)][int]$Port)
    try {
        return [ordered]@{
            query_succeeded = $true
            pids = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop |
                Select-Object -ExpandProperty OwningProcess -Unique | Sort-Object)
            error = $null
        }
    }
    catch {
        # Get-NetTCPConnection reports "not found" by exception when there is no
        # listener on some Windows builds.  A second wildcard query distinguishes
        # an empty result from a provider/permission failure.
        try {
            $all = @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
                Where-Object { [int](Get-HonghuOptionalProperty $_ "LocalPort" -1) -eq $Port } |
                Select-Object -ExpandProperty OwningProcess -Unique | Sort-Object)
            return [ordered]@{ query_succeeded = $true; pids = $all; error = $null }
        }
        catch {
            return [ordered]@{ query_succeeded = $false; pids = @(); error = $_.Exception.Message }
        }
    }
}

function Get-HonghuCandidateHealthIdentity {
    param([Parameter(Mandatory = $true)][int]$Port)
    try {
        $body = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3 -ErrorAction Stop
        $candidate = Get-HonghuOptionalProperty $body "candidate_process"
        $release = Get-HonghuOptionalProperty $body "release"
        return [ordered]@{
            reachable = $true
            ok = [bool](Get-HonghuOptionalProperty $body "ok" $false)
            viewer_mode = Get-HonghuOptionalProperty $body "viewer_mode"
            pid = Get-HonghuOptionalProperty $candidate "pid"
            launch_id = Get-HonghuOptionalProperty $candidate "launch_id"
            commit_sha = Get-HonghuOptionalProperty $release "commit_sha"
            error = $null
        }
    }
    catch {
        return [ordered]@{
            reachable = $false; ok = $false; viewer_mode = $null; pid = $null
            launch_id = $null; commit_sha = $null; error = $_.Exception.Message
        }
    }
}

function Get-HonghuCandidateProcessObservation {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][int]$Port
    )
    $process = $null
    $processQuery = [ordered]@{ query_succeeded = $true; found = $false; error = $null }
    try {
        $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        $processQuery.found = ($null -ne $process)
    }
    catch {
        $processQuery.query_succeeded = $false
        $processQuery.error = $_.Exception.Message
    }

    $cim = $null
    $cimQuery = [ordered]@{ query_succeeded = $true; found = $false; error = $null }
    try {
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
        $cimQuery.found = ($null -ne $cim)
    }
    catch {
        $cimQuery.query_succeeded = $false
        $cimQuery.error = $_.Exception.Message
    }

    $startTime = $null
    $processPath = $null
    if ($null -ne $process) {
        try {
            $start = Get-HonghuOptionalProperty $process "StartTime"
            if ($null -ne $start) { $startTime = $start.ToUniversalTime().ToString("o") }
        }
        catch {}
        $processPath = ConvertTo-HonghuFullPathOrNull (Get-HonghuOptionalProperty $process "Path")
    }
    $cimPath = ConvertTo-HonghuFullPathOrNull (Get-HonghuOptionalProperty $cim "ExecutablePath")
    $commandLine = Get-HonghuOptionalProperty $cim "CommandLine"
    $commandHash = $null
    if (-not [string]::IsNullOrWhiteSpace([string]$commandLine)) {
        $commandHash = Get-HonghuTextSha256 ([string]$commandLine)
    }
    $path = if (-not [string]::IsNullOrWhiteSpace($processPath)) { $processPath } else { $cimPath }
    $listeners = Get-HonghuListenerPids -Port $Port
    $health = Get-HonghuCandidateHealthIdentity -Port $Port
    return [ordered]@{
        pid = $ProcessId
        port = $Port
        process_query = $processQuery
        cim_query = $cimQuery
        process_found = [bool]($processQuery.found -or $cimQuery.found)
        start_time_utc = $startTime
        executable_path = $path
        executable_path_sources = [ordered]@{ get_process = $processPath; cim = $cimPath }
        command_line_sha256 = $commandHash
        command_line = if ($null -eq $commandLine) { $null } else { [string]$commandLine }
        listener = $listeners
        candidate_health = $health
    }
}

function Get-HonghuCandidateProcessSnapshot {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [int]$Port = 18080
    )
    $observation = Get-HonghuCandidateProcessObservation -ProcessId $ProcessId -Port $Port
    if (-not $observation.process_found) { return $null }
    return $observation
}

function Test-HonghuCandidateProcessIdentity {
    param(
        [Parameter(Mandatory = $true)]$Record,
        [Parameter(Mandatory = $true)]$Snapshot,
        [switch]$RequireStopAuthority
    )
    $reasons = New-Object System.Collections.Generic.List[string]
    $matched = New-Object System.Collections.Generic.List[string]
    $unavailable = New-Object System.Collections.Generic.List[string]
    $recordPid = [int](Get-HonghuOptionalProperty $Record "pid" -1)
    $snapshotPid = [int](Get-HonghuOptionalProperty $Snapshot "pid" -2)
    if ($recordPid -ne $snapshotPid) { $reasons.Add("pid mismatch") } else { $matched.Add("pid") }

    $recordStart = [string](Get-HonghuOptionalProperty $Record "start_time_utc")
    $snapshotStart = [string](Get-HonghuOptionalProperty $Snapshot "start_time_utc")
    if ([string]::IsNullOrWhiteSpace($snapshotStart)) { $unavailable.Add("start_time") }
    elseif ($recordStart -ne $snapshotStart) { $reasons.Add("start time mismatch") }
    else { $matched.Add("start_time") }

    $recordPath = ConvertTo-HonghuFullPathOrNull (Get-HonghuOptionalProperty $Record "executable_path")
    $snapshotPath = ConvertTo-HonghuFullPathOrNull (Get-HonghuOptionalProperty $Snapshot "executable_path")
    if ([string]::IsNullOrWhiteSpace($snapshotPath)) { $unavailable.Add("executable_path") }
    elseif ([string]::IsNullOrWhiteSpace($recordPath) -or $recordPath -ne $snapshotPath) { $reasons.Add("executable mismatch") }
    else { $matched.Add("executable_path") }

    $recordCommandHash = [string](Get-HonghuOptionalProperty $Record "command_line_sha256")
    $snapshotCommandHash = [string](Get-HonghuOptionalProperty $Snapshot "command_line_sha256")
    if ([string]::IsNullOrWhiteSpace($snapshotCommandHash)) { $unavailable.Add("command_line") }
    elseif ([string]::IsNullOrWhiteSpace($recordCommandHash) -or $recordCommandHash -ne $snapshotCommandHash) { $reasons.Add("command line mismatch") }
    else { $matched.Add("command_line") }

    $commandLine = [string](Get-HonghuOptionalProperty $Snapshot "command_line")
    if (-not [string]::IsNullOrWhiteSpace($commandLine)) {
        $requiredTokens = @(
            "tools.release.cli", "serve-readonly-candidate",
            [string](Get-HonghuOptionalProperty $Record "launch_id"),
            [string](Get-HonghuOptionalProperty $Record "commit_sha"),
            [string](Get-HonghuOptionalProperty $Record "port")
        )
        foreach ($token in $requiredTokens) {
            if ([string]::IsNullOrWhiteSpace($token) -or -not $commandLine.Contains($token)) {
                $reasons.Add("command line missing expected candidate token")
                break
            }
        }
    }

    $listener = Get-HonghuOptionalProperty $Snapshot "listener"
    $listenerSucceeded = [bool](Get-HonghuOptionalProperty $listener "query_succeeded" $false)
    $listenerPids = @(Get-HonghuOptionalProperty $listener "pids" @())
    if ($listenerSucceeded -and $listenerPids -contains $recordPid) { $matched.Add("listener_owner") }
    elseif (-not $listenerSucceeded) { $unavailable.Add("listener_query") }

    $health = Get-HonghuOptionalProperty $Snapshot "candidate_health"
    $healthExact = (
        [bool](Get-HonghuOptionalProperty $health "reachable" $false) -and
        [bool](Get-HonghuOptionalProperty $health "ok" $false) -and
        [string](Get-HonghuOptionalProperty $health "viewer_mode") -eq "readonly_candidate" -and
        [int](Get-HonghuOptionalProperty $health "pid" -1) -eq $recordPid -and
        [string](Get-HonghuOptionalProperty $health "launch_id") -eq [string](Get-HonghuOptionalProperty $Record "launch_id") -and
        [string](Get-HonghuOptionalProperty $health "commit_sha") -eq [string](Get-HonghuOptionalProperty $Record "commit_sha")
    )
    if ($healthExact) { $matched.Add("candidate_health") }

    if ($RequireStopAuthority -and $reasons.Count -eq 0) {
        $hasCoreIdentity = ($matched -contains "start_time") -and (
            ($matched -contains "command_line") -or ($matched -contains "executable_path")
        )
        $hasRuntimeAuthority = ($matched -contains "listener_owner") -or ($matched -contains "candidate_health") -or ($matched -contains "command_line")
        if (-not $hasCoreIdentity -or -not $hasRuntimeAuthority) {
            $reasons.Add("insufficient independent evidence to stop candidate safely")
        }
    }
    return [ordered]@{
        ok = ($reasons.Count -eq 0)
        reasons = @($reasons)
        matched_evidence = @($matched)
        unavailable_evidence = @($unavailable)
    }
}

function Test-HonghuCandidateRecordContract {
    param([Parameter(Mandatory = $true)]$Record)
    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($name in @("pid", "start_time_utc", "launch_id", "commit_sha", "manifest_sha256", "port", "candidate_root")) {
        $value = Get-HonghuOptionalProperty $Record $name
        if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) { $missing.Add($name) }
    }
    if (
        [string]::IsNullOrWhiteSpace([string](Get-HonghuOptionalProperty $Record "executable_path")) -and
        [string]::IsNullOrWhiteSpace([string](Get-HonghuOptionalProperty $Record "command_line_sha256"))
    ) {
        $missing.Add("executable_path_or_command_line_sha256")
    }
    return [ordered]@{ ok = ($missing.Count -eq 0); missing = @($missing) }
}

function Archive-HonghuStaleCandidateRecord {
    param(
        [Parameter(Mandatory = $true)][string]$RecordPath,
        [Parameter(Mandatory = $true)]$Record,
        [Parameter(Mandatory = $true)]$Observation
    )
    $runtime = Split-Path -Parent $RecordPath
    $archiveRoot = Join-Path $runtime "stale_process_records"
    New-Item -ItemType Directory -Force $archiveRoot | Out-Null
    $raw = Get-Content -LiteralPath $RecordPath -Raw -Encoding UTF8
    $recordHash = Get-HonghuTextSha256 $raw
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmss.fffffffZ")
    $archivePath = Join-Path $archiveRoot "viewer_candidate_process.$stamp.$($recordHash.Substring(0, 12)).json"
    $envelope = [ordered]@{
        schema_version = "honghu.stale_candidate_process_record.v1"
        reconciled_at = (Get-Date).ToUniversalTime().ToString("o")
        reason = "recorded PID absent from both process sources and recorded port has no listener"
        original_record_sha256 = $recordHash
        original_identity = $Record
        observation = $Observation
    }
    $envelope | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $archivePath -Encoding UTF8
    if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) { throw "Stale record archive was not created." }
    Remove-Item -LiteralPath $RecordPath -Force -ErrorAction Stop
    return [ordered]@{
        ok = $true
        status = "stale-record-archived"
        pid = [int](Get-HonghuOptionalProperty $Record "pid")
        port = [int](Get-HonghuOptionalProperty $Record "port")
        reason = $envelope.reason
        archive_path = $archivePath
        original_record_sha256 = $recordHash
        observation = $Observation
    }
}

function Stop-HonghuVerifiedCandidate {
    param([Parameter(Mandatory = $true)][string]$RecordPath)
    if (-not (Test-Path -LiteralPath $RecordPath -PathType Leaf)) {
        return [ordered]@{ ok = $true; status = "no-record"; reasons = @("candidate process record absent") }
    }
    $record = Get-Content -LiteralPath $RecordPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $contract = Test-HonghuCandidateRecordContract -Record $record
    if (-not $contract.ok) {
        throw "Existing candidate process record is incomplete ($($contract.missing -join ', ')); refusing automatic cleanup."
    }
    $candidatePid = [int](Get-HonghuOptionalProperty $record "pid")
    $port = [int](Get-HonghuOptionalProperty $record "port")
    $observation = Get-HonghuCandidateProcessObservation -ProcessId $candidatePid -Port $port
    if (-not $observation.process_found) {
        $knownAbsent = (
            [bool]$observation.process_query.query_succeeded -and
            [bool]$observation.cim_query.query_succeeded -and
            [bool]$observation.listener.query_succeeded -and
            @($observation.listener.pids).Count -eq 0 -and
            -not [bool]$observation.candidate_health.reachable
        )
        if (-not $knownAbsent) {
            throw "Candidate process absence or port release cannot be proven; refusing stale-record cleanup."
        }
        return Archive-HonghuStaleCandidateRecord -RecordPath $RecordPath -Record $record -Observation $observation
    }
    if (-not [bool]$observation.listener.query_succeeded) {
        throw "Candidate listener ownership cannot be queried; refusing to stop PID $candidatePid."
    }
    $conflictingListeners = @($observation.listener.pids | Where-Object { [int]$_ -ne $candidatePid })
    if ($conflictingListeners.Count -gt 0) {
        throw "Candidate port $port is owned by a conflicting PID; refusing cleanup."
    }
    $identity = Test-HonghuCandidateProcessIdentity -Record $record -Snapshot $observation -RequireStopAuthority
    if (-not $identity.ok) {
        throw "Refusing to stop PID ${candidatePid}: candidate identity failed ($($identity.reasons -join ', '))."
    }
    Stop-Process -Id $candidatePid -Force -ErrorAction Stop
    try { Wait-Process -Id $candidatePid -Timeout 15 -ErrorAction SilentlyContinue } catch {}
    $remaining = Get-HonghuCandidateProcessObservation -ProcessId $candidatePid -Port $port
    if ($remaining.process_found -and [string]$remaining.start_time_utc -eq [string](Get-HonghuOptionalProperty $record "start_time_utc")) {
        throw "Candidate PID $candidatePid still exists after stop."
    }
    if (-not [bool]$remaining.listener.query_succeeded -or @($remaining.listener.pids).Count -gt 0) {
        throw "Candidate port $port is not proven released after stop."
    }
    Remove-Item -LiteralPath $RecordPath -Force
    return [ordered]@{
        ok = $true; status = "verified-candidate-stopped"; pid = $candidatePid; port = $port
        identity = $identity; post_stop_observation = $remaining
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
    $identityNames = @("viewer_mode", "release_version", "release_manifest_sha256", "app_sha256")
    $health = [ordered]@{
        reachable = $false; status = $null; payload_parsed = $false
        present_identity_fields = @(); missing_identity_fields = @($identityNames)
        identity = [ordered]@{}; identity_sha256 = $null
        transport_error = $null; payload_error = $null
    }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8080/api/health" -TimeoutSec 10 -ErrorAction Stop
        $health.reachable = $true
        $health.status = [int](Get-HonghuOptionalProperty $response "StatusCode" 0)
        try {
            $body = [string](Get-HonghuOptionalProperty $response "Content") | ConvertFrom-Json
            $health.payload_parsed = $true
            $present = New-Object System.Collections.Generic.List[string]
            $missing = New-Object System.Collections.Generic.List[string]
            $identity = [ordered]@{}
            foreach ($name in $identityNames) {
                if (Test-HonghuOptionalProperty $body $name) {
                    $present.Add($name)
                    $identity[$name] = Get-HonghuOptionalProperty $body $name
                }
                else { $missing.Add($name) }
            }
            $health.present_identity_fields = @($present)
            $health.missing_identity_fields = @($missing)
            $health.identity = $identity
            $health.identity_sha256 = Get-HonghuTextSha256 ($identity | ConvertTo-Json -Compress)
        }
        catch { $health.payload_error = $_.Exception.Message }
    }
    catch { $health.transport_error = $_.Exception.Message }
    $listeners = Get-HonghuListenerPids -Port 8080
    return [ordered]@{
        health = $health
        listener = $listeners
        listener_pids = @($listeners.pids)
        current_pointer = Get-HonghuFileIdentity (Join-Path $Root "current")
        broadcast_manifest = Get-HonghuFileIdentity (Join-Path $Root "BROADCAST_MANIFEST.json")
    }
}

function Test-HonghuProductionUnchanged {
    param($Before, $After)
    $reasons = New-Object System.Collections.Generic.List[string]
    $fieldComparisons = [ordered]@{}
    if (-not [bool]$Before.health.reachable) { $reasons.Add("production 8080 was not reachable before candidate deployment") }
    if (-not [bool]$After.health.reachable) { $reasons.Add("production 8080 was not reachable after candidate deployment") }
    if ([bool]$Before.health.reachable -and -not [bool]$Before.health.payload_parsed) { $reasons.Add("production 8080 health payload was not parseable before candidate deployment") }
    if ([bool]$After.health.reachable -and -not [bool]$After.health.payload_parsed) { $reasons.Add("production 8080 health payload was not parseable after candidate deployment") }
    if ([bool]$Before.health.reachable -and ([int]$Before.health.status -lt 200 -or [int]$Before.health.status -ge 300)) { $reasons.Add("production 8080 returned a non-success status before candidate deployment") }
    if ([bool]$After.health.reachable -and ([int]$After.health.status -lt 200 -or [int]$After.health.status -ge 300)) { $reasons.Add("production 8080 returned a non-success status after candidate deployment") }

    $identityNames = @("viewer_mode", "release_version", "release_manifest_sha256", "app_sha256")
    foreach ($name in $identityNames) {
        $beforePresent = Test-HonghuOptionalProperty $Before.health.identity $name
        $afterPresent = Test-HonghuOptionalProperty $After.health.identity $name
        $beforeValue = Get-HonghuOptionalProperty $Before.health.identity $name
        $afterValue = Get-HonghuOptionalProperty $After.health.identity $name
        $same = ($beforePresent -eq $afterPresent) -and ((-not $beforePresent) -or ([string]$beforeValue -eq [string]$afterValue))
        $fieldComparisons[$name] = [ordered]@{
            before_present = $beforePresent; after_present = $afterPresent
            before_value = $beforeValue; after_value = $afterValue; stable = $same
        }
        if (-not $same) { $reasons.Add("production 8080 identity field changed: $name") }
    }
    if (-not [bool]$Before.listener.query_succeeded) { $reasons.Add("production 8080 listener query failed before candidate deployment") }
    if (-not [bool]$After.listener.query_succeeded) { $reasons.Add("production 8080 listener query failed after candidate deployment") }
    if ((@($Before.listener_pids) -join ',') -ne (@($After.listener_pids) -join ',')) { $reasons.Add("production 8080 listener PID set changed") }
    if ($Before.current_pointer.exists -ne $After.current_pointer.exists -or $Before.current_pointer.sha256 -ne $After.current_pointer.sha256) { $reasons.Add("production current pointer changed") }
    if ($Before.broadcast_manifest.exists -ne $After.broadcast_manifest.exists -or $Before.broadcast_manifest.sha256 -ne $After.broadcast_manifest.sha256) { $reasons.Add("production broadcast manifest changed") }
    return [ordered]@{
        verified = ($reasons.Count -eq 0)
        reasons = @($reasons)
        health_reachability = [ordered]@{ before = [bool]$Before.health.reachable; after = [bool]$After.health.reachable }
        identity_fields = $fieldComparisons
        listener_pids = [ordered]@{ before = @($Before.listener_pids); after = @($After.listener_pids) }
        current_pointer_stable = ($Before.current_pointer.exists -eq $After.current_pointer.exists -and $Before.current_pointer.sha256 -eq $After.current_pointer.sha256)
        broadcast_manifest_stable = ($Before.broadcast_manifest.exists -eq $After.broadcast_manifest.exists -and $Before.broadcast_manifest.sha256 -eq $After.broadcast_manifest.sha256)
    }
}

function Test-HonghuProductionStateUsable {
    param([Parameter(Mandatory = $true)]$State)
    $reasons = New-Object System.Collections.Generic.List[string]
    if (-not [bool](Get-HonghuOptionalProperty $State.health "reachable" $false)) {
        $reasons.Add("production health is not reachable")
    }
    if (
        [bool](Get-HonghuOptionalProperty $State.health "reachable" $false) -and
        -not [bool](Get-HonghuOptionalProperty $State.health "payload_parsed" $false)
    ) {
        $reasons.Add("production health payload is not parseable")
    }
    $status = [int](Get-HonghuOptionalProperty $State.health "status" 0)
    if (
        [bool](Get-HonghuOptionalProperty $State.health "reachable" $false) -and
        ($status -lt 200 -or $status -ge 300)
    ) {
        $reasons.Add("production health returned a non-success status")
    }
    if (-not [bool](Get-HonghuOptionalProperty $State.listener "query_succeeded" $false)) {
        $reasons.Add("production listener query failed")
    }
    return [ordered]@{ usable = ($reasons.Count -eq 0); reasons = @($reasons) }
}

function Get-HonghuProductionStateWindow {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [ValidateRange(2, 10)][int]$Attempts = 3,
        [ValidateRange(2, 10)][int]$RequiredUsableSamples = 2,
        [ValidateRange(0, 5000)][int]$DelayMilliseconds = 500
    )
    if ($RequiredUsableSamples -gt $Attempts) {
        throw "RequiredUsableSamples cannot exceed Attempts."
    }

    $samples = New-Object System.Collections.Generic.List[object]
    $usableSamples = New-Object System.Collections.Generic.List[object]
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $state = Get-HonghuProductionState -Root $Root
        $assessment = Test-HonghuProductionStateUsable -State $state
        $entry = [ordered]@{
            attempt = $attempt
            sampled_at = (Get-Date).ToUniversalTime().ToString("o")
            usable = [bool]$assessment.usable
            usability_reasons = @($assessment.reasons)
            state = $state
        }
        $samples.Add($entry)
        if ($assessment.usable) { $usableSamples.Add($entry) }
        if ($attempt -lt $Attempts -and $DelayMilliseconds -gt 0) {
            Start-Sleep -Milliseconds $DelayMilliseconds
        }
    }

    $reasons = New-Object System.Collections.Generic.List[string]
    $warnings = New-Object System.Collections.Generic.List[string]
    $comparisons = New-Object System.Collections.Generic.List[object]
    if ($usableSamples.Count -lt $RequiredUsableSamples) {
        $reasons.Add("only $($usableSamples.Count) of $Attempts production samples were usable; $RequiredUsableSamples required")
    }
    elseif ($usableSamples.Count -lt $Attempts) {
        $warnings.Add("$($Attempts - $usableSamples.Count) transient production sample(s) were unusable but retained in evidence")
    }

    if ($usableSamples.Count -gt 0) {
        $reference = $usableSamples[0]
        for ($index = 1; $index -lt $usableSamples.Count; $index++) {
            $candidate = $usableSamples[$index]
            $comparison = Test-HonghuProductionUnchanged -Before $reference.state -After $candidate.state
            $comparisons.Add([ordered]@{
                reference_attempt = [int]$reference.attempt
                candidate_attempt = [int]$candidate.attempt
                comparison = $comparison
            })
            if (-not $comparison.verified) {
                $reasons.Add("production samples $($reference.attempt) and $($candidate.attempt) conflict: $(@($comparison.reasons) -join '; ')")
            }
        }
    }

    $selectedEntry = if ($usableSamples.Count -gt 0) { $usableSamples[$usableSamples.Count - 1] } else { $samples[$samples.Count - 1] }
    return [ordered]@{
        schema_version = "honghu.production_state_window.v1"
        verified = ($reasons.Count -eq 0)
        attempt_count = $Attempts
        required_usable_samples = $RequiredUsableSamples
        usable_sample_count = $usableSamples.Count
        selected_attempt = [int]$selectedEntry.attempt
        selected_state = $selectedEntry.state
        samples = $samples.ToArray()
        intra_window_comparisons = $comparisons.ToArray()
        reasons = @($reasons)
        warnings = @($warnings)
    }
}

function New-HonghuScheduledTaskComparison {
    param(
        [Parameter(Mandatory = $true)]$Before,
        [Parameter(Mandatory = $true)]$After
    )
    return [ordered]@{
        verified = ($Before.verified -and $After.verified -and $Before.definitions_sha256 -eq $After.definitions_sha256)
        reason = if (-not $Before.verified -or -not $After.verified) { "scheduled task definitions could not be read" } elseif ($Before.definitions_sha256 -ne $After.definitions_sha256) { "scheduled task definitions changed" } else { $null }
    }
}

function New-HonghuProductionWindowComparison {
    param(
        [Parameter(Mandatory = $true)]$Before,
        [Parameter(Mandatory = $true)]$AfterWindow
    )
    $comparison = Test-HonghuProductionUnchanged -Before $Before -After $AfterWindow.selected_state
    $reasons = New-Object System.Collections.Generic.List[string]
    foreach ($reason in @($comparison.reasons)) { $reasons.Add([string]$reason) }
    if (-not [bool]$AfterWindow.verified) {
        foreach ($reason in @($AfterWindow.reasons)) {
            $reasons.Add("production sampling window is not stable: $reason")
        }
    }
    $comparison.verified = ($reasons.Count -eq 0)
    $comparison.reasons = @($reasons)
    $comparison.sampling_window_verified = [bool]$AfterWindow.verified
    $comparison.sampling_window_reasons = @($AfterWindow.reasons)
    return $comparison
}

function Set-HonghuCandidateGateEvidence {
    param(
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Evidence,
        [Parameter(Mandatory = $true)]$PostTasks,
        [Parameter(Mandatory = $true)]$PostProductionWindow,
        [Parameter(Mandatory = $true)]$TaskComparison,
        [Parameter(Mandatory = $true)]$ProductionComparison
    )
    $existing = Get-HonghuOptionalProperty $Evidence "gate"
    if ([bool](Get-HonghuOptionalProperty $existing "evaluated" $false)) {
        throw "Candidate gate evidence is immutable once evaluated."
    }
    $postState = [ordered]@{
        scheduled_tasks = $PostTasks
        production = $PostProductionWindow.selected_state
        production_sampling = $PostProductionWindow
    }
    $Evidence["gate"] = [ordered]@{
        evaluated = $true
        captured_at = (Get-Date).ToUniversalTime().ToString("o")
        post_state = $postState
        comparisons = [ordered]@{
            scheduled_tasks_unchanged = $TaskComparison
            production_8080_and_pointer_unchanged = $ProductionComparison
        }
    }
    # Compatibility aliases always point at the original gate and are never
    # rewritten by cleanup/final-state sampling.
    $Evidence["post_state"] = $postState
    $Evidence["observed"]["scheduled_tasks_unchanged"] = $TaskComparison
    $Evidence["observed"]["production_8080_and_pointer_unchanged"] = $ProductionComparison
}

function Set-HonghuCandidateRecoveryEvidence {
    param(
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Evidence,
        [Parameter(Mandatory = $true)]$PostCleanupTasks,
        [Parameter(Mandatory = $true)]$PostCleanupProductionWindow,
        [Parameter(Mandatory = $true)]$TaskComparison,
        [Parameter(Mandatory = $true)]$ProductionComparison
    )
    $existing = Get-HonghuOptionalProperty $Evidence "recovery"
    if ([bool](Get-HonghuOptionalProperty $existing "captured" $false)) {
        throw "Candidate recovery evidence is immutable once captured."
    }
    $postCleanupState = [ordered]@{
        scheduled_tasks = $PostCleanupTasks
        production = $PostCleanupProductionWindow.selected_state
        production_sampling = $PostCleanupProductionWindow
    }
    $recovery = [ordered]@{
        captured = $true
        captured_at = (Get-Date).ToUniversalTime().ToString("o")
        post_cleanup_state = $postCleanupState
        comparisons_to_pre = [ordered]@{
            scheduled_tasks_unchanged = $TaskComparison
            production_8080_and_pointer_unchanged = $ProductionComparison
        }
    }
    $Evidence["recovery"] = $recovery
    $Evidence["observed"]["post_cleanup_state"] = $postCleanupState
    $Evidence["observed"]["post_cleanup_comparisons"] = $recovery.comparisons_to_pre
}
