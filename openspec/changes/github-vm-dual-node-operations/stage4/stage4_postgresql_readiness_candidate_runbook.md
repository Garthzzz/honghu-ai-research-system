# Stage 4 PostgreSQL readiness candidate 现场手册

## 目的与禁止边界

本手册只验证 `user_content_notes` 首个 cutover unit 的 production-readiness，不授予 production authority。执行前后，应用路由必须保持 `S0/sqlite_transition`；不得连接 8080 Viewer 到 PostgreSQL，不得停止 SQLite writer，不得修改计划任务，也不得进入 S2/S3。

候选使用 VM 上独立目录、loopback 端口 `55434`、合成数据库和临时角色。候选进程结束后不会保留监听；凭据仅暂存 Windows Credential Manager，并在成功或失败清理路径撤销。

## 现场前置输入

人工执行时必须明确填写：

- 已通过 push/PR required CI 的 readiness commit 完整 SHA；
- 独立 checkout：`D:\honghu-stage4-readiness-bootstrap`；
- 候选根：`D:\honghu-postgresql-readiness-candidate`，必须不存在或为空；
- Python 3.10：`C:\ProgramData\miniconda3\envs\quant\python.exe`；
- PostgreSQL 17.10 Windows binaries：`postgresql-17.10-2-windows-x64-binaries.zip`；
- archive SHA256：`ef9b1e5e23d2e8a83914ba13d9dc536a72210fba53fd1808ff1f7e06bb22b106`；
- 下载来源：`https://get.enterprisedb.com/postgresql/postgresql-17.10-2-windows-x64-binaries.zip`；
- 真正位于另一台主机或公司批准对象存储上的 off-VM 目标及稳定 host identity。

没有独立 off-VM 位置时，可以完成本地候选演练，但结果必须保持 `engineering_partial`，不得冒充 production-ready。

## 只读预检

在管理员 PowerShell 中先检查，不安装服务、不改防火墙：

```powershell
$ErrorActionPreference = 'Stop'
$CommitSha = '<FULL_READINESS_COMMIT_SHA>'
$Repo = 'D:\honghu-stage4-readiness-bootstrap'
$Candidate = 'D:\honghu-postgresql-readiness-candidate'
$Python = 'C:\ProgramData\miniconda3\envs\quant\python.exe'
$Archive = 'D:\honghu-stage4-assets\postgresql-17.10-2-windows-x64-binaries.zip'

if ((git -C $Repo rev-parse HEAD).Trim().ToLowerInvariant() -ne $CommitSha) {
    throw 'checkout 不是已批准的 readiness commit'
}
& $Python -c "import sys; assert sys.version_info[:2] == (3,10)"
if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne
    'ef9b1e5e23d2e8a83914ba13d9dc536a72210fba53fd1808ff1f7e06bb22b106') {
    throw 'PostgreSQL archive identity 不匹配'
}
$route = Get-Content -Raw (Join-Path $Repo 'config\migration\user_content_backend_route.json') |
    ConvertFrom-Json
if ($route.authority_state -ne 'S0' -or $route.backend -ne 'sqlite_transition' -or
    -not $route.sqlite_writer_enabled -or $route.production_postgresql_enabled) {
    throw '活动路由不再是 S0/sqlite_transition'
}
foreach ($port in 55434,55435) {
    if (@(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).Count) {
        throw "候选端口 $port 已被占用"
    }
}
if (-not (Invoke-RestMethod 'http://127.0.0.1:8080/api/health' -TimeoutSec 10).ok) {
    throw '原 8080 不健康，停止候选子任务'
}
```

## 隔离环境与执行

解压 archive 到候选资产目录，确认 `pgsql\bin\postgres.exe` 存在。用 hash-pinned lockfile 建立独立环境，不修改现有 `quant` 环境：

```powershell
$Venv = Join-Path $Candidate 'python-env'
& $Python -m venv $Venv
& (Join-Path $Venv 'Scripts\python.exe') -m pip install `
    --disable-pip-version-check --require-hashes `
    -r (Join-Path $Repo 'requirements.lock.txt')

$ConfigSha = (Get-FileHash `
    (Join-Path $Repo 'config\migration\user_content_backend_route.json') `
    -Algorithm SHA256).Hash.ToLowerInvariant()

& (Join-Path $Venv 'Scripts\python.exe') `
    -m tools.migration.stage4_candidate_recovery_rehearsal `
    --root $Repo `
    --bin-dir (Join-Path $Candidate 'assets\pgsql\bin') `
    --candidate-root (Join-Path $Candidate 'runtime') `
    --host 127.0.0.1 `
    --port 55434 `
    --environment-id 'vm-production-readiness-candidate' `
    --candidate-id 'stage4-user-content-notes-vm' `
    --commit-sha $CommitSha `
    --config-sha256 $ConfigSha `
    --live-data-root 'C:\industry_demo\data' `
    --output-dir (Join-Path $Candidate 'evidence') `
    --source-archive $Archive `
    --source-url 'https://get.enterprisedb.com/postgresql/postgresql-17.10-2-windows-x64-binaries.zip' `
    --off-vm-root '<APPROVED_OFF_VM_PATH>' `
    --off-vm-host-id '<APPROVED_DERIVED_STORAGE_IDENTITY_SHA256>'
```

`--off-vm-root` 必须是另一故障域；本机另一个盘符不成立。`--off-vm-host-id`
传入的是事先批准的 endpoint-derived storage identity SHA256，执行器仍会从 UNC
server/share、DNS 与存储卷身份独立探测并比对，不能用调用方自由文本冒充异机身份。
若暂无该条件，省略最后两个参数，并接受 `engineering_partial`。恢复证据必须同时包含
`recovery_set_manifest.json`；bundle 构建时通过 `--recovery-set-manifest` 显式纳入并校验。

## 结果判定与清理

现场 evidence 必须留在 Git 外。检查 `postgresql_topology.json`、`recovery.json` 和 `authority_rehearsal.json`，并用 Stage 4 bundle verifier 交叉校验。任何失败都保留原始 evidence，不手改 JSON，不手动把 false 改成 true。

执行程序会在 `finally` 中停止候选 cluster、停止 restore cluster并撤销临时 Credential Manager 项。执行后必须只读确认：

```powershell
Get-NetTCPConnection -LocalPort 55434,55435 -State Listen -ErrorAction SilentlyContinue
(Invoke-RestMethod 'http://127.0.0.1:8080/api/health' -TimeoutSec 10).ok
Get-Content -Raw (Join-Path $Repo 'config\migration\user_content_backend_route.json')
```

预期为候选端口无 listener、8080 正常、路由仍为 S0。候选失败、端口残留、route drift、需要 VM reboot 或 live SQLite 哈希变化时立即停止并保留证据，不得继续 production cutover。
