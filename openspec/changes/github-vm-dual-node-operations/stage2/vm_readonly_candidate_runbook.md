# 阶段 2 VM 只读候选人工执行手册

> 本手册只用于用户批准后的 18080 并行候选。它不切换 8080、不修改计划任务、不迁移数据库、不合并 PR，也不授权阶段 3。执行前必须把 `<GREEN_FULL_SHA>` 和 `<PYTHON310_EXE>` 替换为人工核验后的真实值。

> 旧提交 `028572f7a1895636b6d8b46d3ff0d3019dd56309` 的 runtime verifier 存在 distribution 名称标准化缺陷，已经撤销 VM 验收资格。不得继续使用旧 checkout、旧 SHA 或手工修改 VM checkout 绕过；必须使用本次修复后同时通过 push/PR Actions 的新完整 SHA。
> 旧提交 `f6926410475cf5c646641f6d7056736abae1453d` 把可选的 `docs/themes` Markdown 增强误列为 required content，已经撤销 VM 验收资格。不得创建空目录或复制伪内容绕过；必须使用本次内容合同修复后的新完整 SHA。
> 旧提交 `97d01708737368a9f963f0e9d321c7c596f53efc` 的非 listener Python 调用仍会在 immutable release 内生成 bytecode；同 SHA 重试会因此在 build 阶段触发严格文件集合失败。该 SHA 已撤销验收资格，不得删除几个 `.pyc` 后继续使用。
> 第一轮 bytecode 修复提交 `a612fe83065d51f9e87e807b25e6fccee8f7880e` 又在 GitHub Windows runner 暴露 isolated mode 忽略 `PYTHONUTF8/PYTHONIOENCODING` 的问题，中文 smoke JSON 会被 `cp1252` 阻断。后续 bootstrap 已在进程内固定 UTF-8；仍应只使用最终 push artifact 明确标记为可部署的 SHA，不得退回该中间提交。
> 旧提交 `dd099faa6bcf7f1f120e8ce5166d6319812488ba` 在真实 VM 上完成启动与 16 项 smoke，但把 legacy 8080 health 缺少 `viewer_mode` 误报为不可达，并在失败清理时假定 CIM 一定返回 `ExecutablePath`。该 SHA 已撤销验收资格；不得手工删除旧 process record 或按旧 PID 杀进程。

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
$BootstrapRoot = 'D:\honghu-phase2-bootstrap'
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
  -CandidateRoot 'D:\honghu-ai-research-candidate' `
  -ExistingProductionRoot 'C:\industry_demo' `
  -Port 18080
```

脚本会在候选根建立 lockfile 绑定的隔离 venv并逐包核验，随后用该环境记录的 base Python 统一以 `-I -B -S` 调用项目代码，只显式加入已验证 venv 的 site-packages，并清除子进程继承的 `PYTHONPATH/PYTHONHOME`。由于 `-I` 会忽略 `PYTHONUTF8/PYTHONIOENCODING`，白名单 bootstrap 还会在导入项目代码前把 stdout/stderr 显式固定为 UTF-8 strict。这样既不会把 Windows venv redirector 当成服务进程，也不会把 bytecode 写进 immutable release、从调用者环境导入同名包，或因 VM/runner 代码页不同而损坏中文 evidence。脚本同时构建 exact-commit release、执行 preflight、运行代表性只读 smoke，并在 build、preflight、activate、launch 和 smoke 后逐次复核 manifest；确定性 CI 还会在 stop 后再次复核。任何后启动失败都应身份核验后回收候选进程，并恢复此前的候选指针。

每次执行都有唯一 attempt evidence；旧的 latest evidence 会复制到 `runtime/evidence_history/`，本次完整记录另存为 `vm_readonly_candidate_evidence.<attempt-id>.json`，不会因重试丢失。相同 SHA 的现有 release 若仍严格有效会直接复用；若已污染但既不是 `current`、也没有候选进程记录引用，脚本会把整个目录原子移动到 `runtime/release_quarantine/`，保存失败原因和文件集合指纹后重新构建。若污染目录仍是 `current`、仍被运行记录引用或引用状态无法证明，脚本必须停止并要求人工核验，不会自动删除、覆盖或局部修补。

脚本成功只说明 VM 本机检查通过。证据文件位于：

```text
D:\honghu-ai-research-candidate\runtime\vm_readonly_candidate_evidence.json
```

必须人工确认 `ok=true`、`requested_commit_sha` 与批准 SHA 一致、代表性 smoke 全部通过、任务定义和生产 8080/current 的前后证据一致。`unverified` 中的内网客户端可达性仍需下一步补证。

当前 VM 已知遗留的 `viewer_candidate_process.json` 记录 PID 5500，但两个进程查询均无结果且 18080 无监听。新流程会重新采集这三项事实并探测 candidate health；只有双进程源均确定不存在、端口查询成功且无 listener、candidate health 也不可达时，才把原记录连同 launch id、commit、manifest、观测和原因归档到 `runtime\stale_process_records\`，随后移除活动记录。任一查询权限不明、PID 存在、端口监听、health 可达或身份冲突都会停止部署并保留原记录，不会自动删记录或杀 PID。

`pre_state.production.health` 和 `post_state.production.health` 现在分别记录 HTTP 可达性、状态码、JSON 是否可解析、实际存在/缺失的身份字段及其值。旧 8080 没有 `viewer_mode` 只表示 legacy schema；只要前后都缺失且其他实际身份、listener、`current` 和广播 manifest 稳定，就不会再被误判为不可达。真正断连、字段出现/消失或值变化仍严格失败。

还必须确认 `observed.immutable_release_integrity` 中 build、preflight、activate、launch、smoke 的 `ok` 全为 `true`，commit、manifest hash 和文件数一致；`observed.release_build.disposition` 只能是新建、严格复用或“非活动失效目录整体隔离后重建”之一。出现 quarantine 时应保留其 record，不得删除隔离目录后伪装成首次成功。

其中 preflight 的 `runtime_closure.external_content_contract` 必须同时满足：`required_missing=[]`、`invalid_paths=[]`，而当前 VM 的 `optional_missing` 应如实包含 `docs/themes`。这表示主题 Markdown 增强不存在，并不表示主题内容不存在；16 项 smoke 中的 `theme-db-only` 必须从 `research.db` 读取真实主题并验证页面明确报告可选 Markdown 缺失。若 `docs/industries` 或 `papers` 缺失，preflight 仍必须失败，不能继续启动候选。

其中 `observed.python_runtime` 必须同时满足：`ok=true`、`locked_package_count=74`、`mismatches=[]`、`pip_check.ok=true`，并记录 `package_name_normalization=packaging.utils.canonicalize_name`。只看到安装日志或 venv marker 不等于 runtime verification 已通过。

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
  -CandidateRoot 'D:\honghu-ai-research-candidate'
```

停止脚本会综合核对 PID、启动时间、可取得的解释器/命令行、launch id、commit、candidate health 和 listener owner。CIM 单个可选属性缺失会进入 unavailable evidence，不会覆盖其他证据；身份冲突或证据不足仍拒绝误停。不得改用裸 `Stop-Process <旧PID>` 绕过保护。

## 6. 人工 HALT

把 VM evidence、内网客户端输出和执行时间交回审查。用户明确批准前：不合并 PR #3，不切换 8080，不配置生产 deploy credential，不修改计划任务，不进入阶段 3。
