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

当前合同是 `sqlite-transition`。门禁以 `mode=ro` 和 `query_only` 打开四库，核对代表性只读页面实际依赖的对象类型、必需列、`PRAGMA user_version` 和只读探针。完整 schema fingerprint 会记录在证据中，但阶段 2 只把它作为诊断值，不把“计算出指纹”误称为已经证明所有列、视图、索引、约束和未来写路径兼容。

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

rollback 只切候选 `current`，不改数据库、不恢复用户内容。只有目标 release 与同一 backend 仍通过声明的对象、列和只读探针合同时才允许。该合同支持阶段 2 的代表性只读候选和代码级回滚判断，不声称覆盖未声明的写路径或全部 schema 语义。未来出现破坏性或 forward-only migration 后，必须按 expand–migrate–transition–contract 的独立批准方案处理，不能宣称 code-only rollback 能修数据库。

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

VM 上必须显式提供一个真实存在的 Python 3.10 `python.exe` 作为 bootstrap 解释器。脚本不会从 PATH 猜测环境，也不会修改现有生产任务环境；它在候选根下按 `requirements.lock.txt` 的 SHA256 建立隔离 venv，以 `--require-hashes` 安装并逐包核验精确版本，再用这个 venv 构建和运行候选：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File tools\release\Deploy-ReadonlyCandidate.ps1 `
  -CommitSha <full-sha> `
  -BootstrapPythonExe <VM上明确的Python-3.10-python.exe绝对路径>
```

候选 Python 进程本身直接持有 18080 listener，不再由外层 CLI 启动无法追踪的 Flask 子进程。进程从启动参数起使用 `-B`，避免在 manifest 已验证后向 immutable release 写入 `__pycache__`。部署前的完整逐文件 preflight 会保存到 runtime，并以报告 SHA256、commit、manifest、schema contract 和四个 runtime root 绑定给候选进程；health 复用该启动快照，避免每次轮询重新散列数百个文件形成请求堆积。进程记录同时绑定 PID、启动时间、解释器、命令行 hash、launch id、commit、manifest 和端口；停止、重复部署及失败清理均先核验完整身份，发现 PID 复用或记录不匹配时拒绝误停。

脚本会实测而不是写死以下证据：计划任务定义的部署前后 hash、生产 8080 health/listener 和生产指针的部署前后状态、候选进程身份、四库只读 schema 合同，以及代表性路由 smoke。代表性路由覆盖首页、行业和估值、公司财务/情绪、Opportunity Lens、外置 PDF、三类计算器、静态资源及写方法 403。VM 本机 smoke 与内网其他客户端的 18080 可达性是两项独立证据；脚本完成后仍会把后者标成待人工验证。

候选只会改变独立候选根内的 `current`。任何启动或 smoke 失败都要验证并回收候选进程，恢复原候选指针（没有原指针则回到无 `current` 状态），并保存失败证据。脚本不修改生产 `current`、8080、SQLite、计划任务或 VM deploy credential。候选成功不等于 production deployment，也不授予个人账号仓库 production authority。

## 6. 旧广播包定位

广播包继续作为 SQLite 过渡期冷备。它包含数据快照和研究 artifact，职责与 Git release 不同；不得把广播包文件清单当 deployment allowlist，也不继续把“整目录覆盖”发展成 Git 主发布流程。
