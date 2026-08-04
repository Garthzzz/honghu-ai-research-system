# 阶段 2 VM 只读候选人工执行手册

> 本手册只用于用户批准后的 18080 并行候选。它不切换 8080、不修改计划任务、不迁移数据库、不合并 PR，也不授权阶段 3。执行前必须把 `<GREEN_FULL_SHA>` 和 `<PYTHON310_EXE>` 替换为人工核验后的真实值。

## 1. 在 VM PowerShell 中确认解释器

```powershell
Get-Command python -All | Select-Object Source
py -0p

$BootstrapPython = '<PYTHON310_EXE>'
if (-not (Test-Path -LiteralPath $BootstrapPython -PathType Leaf)) {
    throw '没有找到指定的 Python 解释器。'
}
& $BootstrapPython -c "import sys; print(sys.executable); print(sys.version)"
```

输出必须是明确的 Python 3.10 绝对路径。若 VM 没有 Python 3.10，立即停止；不能让脚本从 PATH 静默选用 base、`quant`、`industry` 或其他解释器，也不能在本轮改动生产任务环境。

## 2. 取得固定提交的部署脚本

```powershell
$CommitSha = '<GREEN_FULL_SHA>'
$BootstrapRoot = 'C:\honghu-phase2-bootstrap'
$Repository = 'https://github.com/Garthzzz/honghu-ai-research-system'

if (-not (Test-Path -LiteralPath (Join-Path $BootstrapRoot '.git') -PathType Container)) {
    if (Test-Path -LiteralPath $BootstrapRoot) {
        throw 'bootstrap 路径已存在但不是 Git clone，请人工检查，不要覆盖。'
    }
    git clone --filter=blob:none --no-checkout $Repository $BootstrapRoot
    if ($LASTEXITCODE -ne 0) { throw 'bootstrap clone 失败。' }
}

$dirty = @(git -C $BootstrapRoot status --porcelain)
if ($dirty.Count -gt 0) { throw 'bootstrap clone 有未提交修改，拒绝覆盖。' }
git -C $BootstrapRoot fetch --no-tags origin $CommitSha
if ($LASTEXITCODE -ne 0) { throw '无法取得指定提交。' }
git -C $BootstrapRoot checkout --detach $CommitSha
if ($LASTEXITCODE -ne 0) { throw '无法检出指定提交。' }
$Resolved = (git -C $BootstrapRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($Resolved -ne $CommitSha.ToLowerInvariant()) { throw '检出提交与批准提交不一致。' }
```

不得把分支名、`main` 或 PR workflow 的临时 merge commit 当部署身份；必须使用 push workflow artifact 中 `eligible_as_vm_candidate_sha=true` 的完整 40 位分支头 SHA，并确认 PR workflow 的 `pull_request_head_sha` 与它相同、两套 workflow 的两个 job 均绿色。

## 3. 启动独立候选

```powershell
& (Join-Path $BootstrapRoot 'tools\release\Deploy-ReadonlyCandidate.ps1') `
  -CommitSha $CommitSha `
  -BootstrapPythonExe $BootstrapPython `
  -CandidateRoot 'C:\honghu-ai-research-candidate' `
  -ExistingProductionRoot 'C:\industry_demo' `
  -Port 18080
```

脚本会在候选根建立 lockfile 绑定的隔离 venv，构建 exact-commit release，执行 preflight，启动由记录 PID 直接持有的 18080 listener，运行代表性只读 smoke，并比较计划任务定义和生产 8080/current 的前后状态。任何后启动失败都应身份核验后回收候选进程，并恢复此前的候选指针。

脚本成功只说明 VM 本机检查通过。证据文件位于：

```text
C:\honghu-ai-research-candidate\runtime\vm_readonly_candidate_evidence.json
```

必须人工确认 `ok=true`、`requested_commit_sha` 与批准 SHA 一致、代表性 smoke 全部通过、任务定义和生产 8080/current 的前后证据一致。`unverified` 中的内网客户端可达性仍需下一步补证。

## 4. 从另一台内网客户端验收

在不是候选 VM 的内网机器上执行：

```powershell
$ExpectedCommit = '<GREEN_FULL_SHA>'
$candidate = Invoke-RestMethod 'http://10.5.1.240:18080/api/health' -TimeoutSec 20
$production = Invoke-RestMethod 'http://10.5.1.240:8080/api/health' -TimeoutSec 20
if (-not $candidate.ok -or $candidate.viewer_mode -ne 'readonly_candidate') {
    throw '18080 候选健康状态不正确。'
}
if ($candidate.release.commit_sha -ne $ExpectedCommit) {
    throw '18080 运行的提交与批准提交不一致。'
}
if (-not $production.ok) { throw '原 8080 生产 Viewer 不可达。' }
$candidate | ConvertTo-Json -Depth 8
$production | ConvertTo-Json -Depth 8
```

这一步只证明预期网络范围内的可达性和服务身份。它不能替代 VM 本机的任务/8080 前后状态、数据库只读 smoke 或进程身份记录。

## 5. 安全停止候选

```powershell
& (Join-Path $BootstrapRoot 'tools\release\Stop-ReadonlyCandidate.ps1') `
  -CandidateRoot 'C:\honghu-ai-research-candidate'
```

停止脚本会核对 PID、启动时间、解释器、命令行 hash、launch id、commit 和端口。身份不一致时会拒绝误停，不得改用裸 `Stop-Process <旧PID>` 绕过保护。

## 6. 人工 HALT

把 VM evidence、内网客户端输出和执行时间交回审查。用户明确批准前：不合并 PR #3，不切换 8080，不配置生产 deploy credential，不修改计划任务，不进入阶段 3。
