# 可重复 release、只读候选与本地开发

## 1. 边界

阶段 2 把代码版本和运行输入拆开。应用 release 只来自一个 Git full commit SHA，并由 `config/deployment_policy.json` 选择文件；数据库、papers/evidence、备份、用户内容、浏览器状态和 secrets 不进入 Git 或 release。

```text
<deploy-root>/
├─ releases/<full-sha>/        exact-commit immutable code
├─ current                     原子替换的 JSON 指针，不是可变代码目录
└─ runtime/                    日志、PID、deployment ledger 与候选证据

外部权威
├─ data-root/                  四套迁移期 SQLite；候选仅 mode=ro/query_only
└─ content-root/               docs/industries、papers 与获批研究内容
```

`current` 使用同目录临时文件加 `os.replace` 切换。Windows 目录 junction 的删除后重建不被伪称为原子操作，因此这里由指针文件承担权威版本选择，进程启动时先解析并复核 release manifest。

## 2. 构建与验证 exact-commit release

在隔离 clone 中执行：

```powershell
$sha = git rev-parse HEAD
python -m tools.release.cli build `
  --repo-root . `
  --deploy-root D:\honghu-release-sandbox `
  --commit $sha

python -m tools.release.cli verify `
  --release-dir D:\honghu-release-sandbox\releases\$sha
```

构建器使用 `git ls-tree` 与 `git show` 读取 commit 对象，不从 dirty working tree 复制。manifest 记录每个文件的大小和 SHA256、deployment policy、schema compatibility、外部运行闭包和明确的禁止资产声明；文件增删或内容篡改会使验证失败。

## 3. schema compatibility 与代码回滚

当前合同是 `sqlite-transition`，只读核对四库所需表、`PRAGMA user_version` 和 schema fingerprint。`config/release_schema_compatibility.json` 明确当前没有获批的 forward-only migration。

```powershell
python -m tools.release.cli preflight `
  --release-dir <release> `
  --data-root <data-root> `
  --content-root <content-root> `
  --state-root <deploy-root>\runtime

python -m tools.release.cli activate `
  --deploy-root <deploy-root> `
  --commit <full-sha> `
  --data-root <data-root> `
  --actor <审计身份>

python -m tools.release.cli rollback `
  --deploy-root <deploy-root> `
  --data-root <data-root> `
  --actor <审计身份>
```

rollback 只切 `current`，不改数据库、不恢复用户内容。只有目标 release 的 backend 与 required-table contract 仍兼容时才允许。未来出现破坏性或 forward-only migration 后，必须按 expand–migrate–transition–contract 的独立批准方案处理，不能宣称 code-only rollback 能修数据库。

## 4. 本地离线开发

本地 fixture 是合成空库，不含任何生产记录，也不依赖 VM 在线：

```powershell
python -m tools.release.dev_fixture D:\honghu-local-fixture

$env:HONGHU_DATA_ROOT="D:\honghu-local-fixture\data"
$env:HONGHU_CONTENT_ROOT="D:\honghu-local-fixture\content"
$env:HONGHU_STATE_ROOT="D:\honghu-local-fixture\state"
$env:HONGHU_VIEWER_MODE="readonly_candidate"
python -m flask --app tools.viewer.app:app run --host=127.0.0.1 --port=18080
```

该最小 fixture 只保证 release health、工具入口和只读门禁可测试，不伪装成完整研究内容验收。涉及真实行业页面的本地验证，使用另行批准的脱敏/只读开发数据，而不是自动连接 production。

## 5. VM 只读候选

VM 上以管理员审核过的 Python 环境运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File tools\release\Deploy-ReadonlyCandidate.ps1 `
  -CommitSha <full-sha> `
  -Python <明确的python.exe路径>
```

脚本固定在独立候选根与端口运行，验证 `/api/health`、`/tools` 和 POST=403，并把结果写入候选 `runtime/vm_readonly_candidate_evidence.json`。它不修改生产 `current`、8080、SQLite、计划任务或 VM deploy credential。候选成功不等于 production deployment，也不授予个人账号仓库 production authority。

## 6. 旧广播包定位

广播包继续作为 SQLite 过渡期冷备。它包含数据快照和研究 artifact，职责与 Git release 不同；不得把广播包文件清单当 deployment allowlist，也不继续把“整目录覆盖”发展成 Git 主发布流程。
