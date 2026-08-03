param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$CommitSha,
    [string]$Repository = "https://github.com/Garthzzz/honghu-ai-research-system",
    [string]$CandidateRoot = "C:\honghu-ai-research-candidate",
    [string]$ExistingProductionRoot = "C:\industry_demo",
    [string]$Python = "python",
    [int]$Port = 18080
)

$ErrorActionPreference = "Stop"
$candidate = [System.IO.Path]::GetFullPath($CandidateRoot)
$production = [System.IO.Path]::GetFullPath($ExistingProductionRoot)
if ($candidate -eq $production -or $candidate.StartsWith($production + "\")) {
    throw "候选目录不得等于或位于现有生产目录内。"
}
if ($Port -eq 8080) {
    throw "只读候选不得占用现有生产端口 8080。"
}
if (-not (Test-Path -LiteralPath (Join-Path $production "data") -PathType Container)) {
    throw "现有生产 data 目录不存在：$production"
}

$source = Join-Path $candidate "source"
$runtime = Join-Path $candidate "runtime"
New-Item -ItemType Directory -Force $candidate, $runtime | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $source ".git") -PathType Container)) {
    git clone --filter=blob:none --no-checkout $Repository $source
    if ($LASTEXITCODE -ne 0) { throw "候选代码 clone 失败。" }
}
git -C $source fetch --no-tags origin $CommitSha
if ($LASTEXITCODE -ne 0) { throw "无法获取指定 commit。" }
git -C $source checkout --detach $CommitSha
if ($LASTEXITCODE -ne 0) { throw "无法检出指定 commit。" }
$resolved = (git -C $source rev-parse HEAD).Trim().ToLowerInvariant()
if ($resolved -ne $CommitSha.ToLowerInvariant()) {
    throw "检出的 commit 与请求不一致。"
}

Push-Location $source
try {
    & $Python -m tools.release.cli build `
        --repo-root $source `
        --deploy-root $candidate `
        --commit $resolved
    if ($LASTEXITCODE -ne 0) { throw "immutable release 构建失败。" }

    $release = Join-Path (Join-Path $candidate "releases") $resolved
    & $Python -m tools.release.cli preflight `
        --release-dir $release `
        --data-root (Join-Path $production "data") `
        --content-root $production `
        --state-root $runtime
    if ($LASTEXITCODE -ne 0) { throw "只读候选 preflight 失败。" }

    & $Python -m tools.release.cli activate `
        --deploy-root $candidate `
        --commit $resolved `
        --data-root (Join-Path $production "data") `
        --actor "phase2-vm-candidate"
    if ($LASTEXITCODE -ne 0) { throw "候选 current 激活失败。" }
}
finally {
    Pop-Location
}

$existingPid = Join-Path $runtime "viewer_candidate.pid"
if (Test-Path -LiteralPath $existingPid) {
    $oldPid = [int](Get-Content -LiteralPath $existingPid -Raw)
    Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
}
$stdout = Join-Path $runtime "viewer_candidate.stdout.log"
$stderr = Join-Path $runtime "viewer_candidate.stderr.log"
$arguments = @(
    "-m", "tools.release.cli", "serve-readonly-candidate",
    "--deploy-root", $candidate,
    "--data-root", (Join-Path $production "data"),
    "--content-root", $production,
    "--state-root", $runtime,
    "--host", "0.0.0.0",
    "--port", [string]$Port
)
$process = Start-Process -FilePath $Python -ArgumentList $arguments `
    -WorkingDirectory $release -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$process.Id | Set-Content -LiteralPath $existingPid -Encoding ascii

$healthUri = "http://127.0.0.1:$Port/api/health"
$ready = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri $healthUri -TimeoutSec 2
        if ($health.ok -and $health.viewer_mode -eq "readonly_candidate" -and
            $health.release.commit_sha -eq $resolved) {
            $ready = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 1
}
if (-not $ready) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    throw "候选服务未在 30 秒内通过 release health。"
}

$toolsResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/tools" -TimeoutSec 15
if ($toolsResponse.StatusCode -ne 200) { throw "只读 GET smoke 失败。" }
$blockedStatus = 0
try {
    $blocked = Invoke-WebRequest -UseBasicParsing -Method POST `
        -Uri "http://127.0.0.1:$Port/api/analyst_note" `
        -ContentType "application/json" -Body "{}" -TimeoutSec 10
    $blockedStatus = [int]$blocked.StatusCode
}
catch {
    if ($null -ne $_.Exception.Response) {
        $blockedStatus = [int]$_.Exception.Response.StatusCode
    }
}
if ($blockedStatus -ne 403) { throw "写方法门禁未返回 403。" }

$evidence = [ordered]@{
    schema_version = "honghu.vm_readonly_candidate_evidence.v1"
    verified_at = (Get-Date).ToString("o")
    commit_sha = $resolved
    candidate_port = $Port
    production_port_untouched = 8080
    health_ok = $true
    tools_get_status = $toolsResponse.StatusCode
    post_block_status = $blockedStatus
    scheduled_tasks_modified = $false
    production_current_switched = $false
    database_access = "read_only"
}
$evidence | ConvertTo-Json -Depth 5 | Set-Content `
    -LiteralPath (Join-Path $runtime "vm_readonly_candidate_evidence.json") `
    -Encoding utf8
Write-Host "只读并行候选已启动：http://127.0.0.1:$Port/"
Write-Host "生产 8080、计划任务和数据库均未切换。"
