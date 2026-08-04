# Viewer Windows 内网部署

> 当前状态：本文首先记录现有广播包和 SQLite Viewer 生产流程；阶段 2 另行建立 Git exact-commit immutable release 和只读并行候选，但不切换现有生产 Viewer。PostgreSQL 仍未实施。不得把广播包误称为新架构发布，也不得把旧 SQLite 文件视为 PostgreSQL 产生新写入后的无损回滚点。目标设计见 `openspec/changes/github-vm-dual-node-operations/`。

## 当前部署闭包

Viewer 在 2026-07 工作流重构后会在导入 Opportunity Lens 时读取 `config/research_workflow.yaml`。因此完整部署必须同步以下六个目录：

- `data/`
- `docs/`
- `tools/`
- `papers/`
- `opportunity_lens/`
- `config/`

同时同步项目根目录的 `restart_viewer.bat`。旧的“五目录”集合缺少 `config/`，会在 Flask 监听端口前触发 `FileNotFoundError`。

交互图使用项目内 `tools/viewer/static/vendor/plotly.min.js`，不依赖公网 CDN。部署时不得只复制模板而遗漏该静态文件；预检会把缺失 Plotly 运行时视为失败。

碳酸锂和铜矿计算器的冻结模型属于正式运行输入，位于：

- `config/lithium_calculator_models/lithium_company_independent_models_v1.json`
- `config/lithium_calculator_models/lithium_external_reconciliation_v1.json`
- `config/lithium_calculator_project_ledger.json`
- `config/copper_calculator_models/copper_calculator_model_v1.json`

它们随 `config/` 一并部署。标准广播包还会自动扫描配置和四套 live 数据库，只纳入仍被引用的研究证据、审计闭包及活动财务模型等必要 `cache/` 文件，并在 `cache/REQUIRED_CACHE_BUNDLE_MANIFEST.json` 记录逐文件清单；不要求同步浏览器截图、整包解压验收副本或整个临时 `cache/`。Viewer 在一个兼容周期内仍可读取旧 `cache/lithium_research/models/`，但启动预检只认可正式路径，防止健康检查通过而计算器单独返回 404。`/tools` 是工具选择页，具体入口为 `/tools/lithium-calculator` 和 `/tools/copper-calculator`。

## 启动

### 当前环境事实与目标环境合同

下表区分 2026-08-03 第三轮只读审计事实、当前兼容入口和未来目标；环境名相似不代表依赖等价。

| 层次 | 当前事实或目标 | 使用边界 |
|---|---|---|
| 当前审计 shell | `D:\conda\python.exe`，Python 3.13.12 | 只说明本轮命令实际解释器，不是 production 环境权威 |
| 当前本地推荐环境 | `quant`，已核验为 `D:\conda\envs\quant\python.exe`，Python 3.10.20 | 阶段 1 前继续作为已知可用的本地模块启动入口 |
| 当前广播脚本默认值 | `restart_viewer.bat` 默认 `VIEWER_CONDA_ENV=industry`；本机 Conda 枚举未发现该环境，VM 是否存在必须在目标机实测 | 默认值是脚本配置，不等于本地或 VM 环境已经正确；可以显式覆盖环境名或 Python 路径 |
| 当前任务解释器 | 七个任务动作混用 base 与 `quant` | 说明现有环境未统一，不得把任务能启动当作依赖一致 |
| 目标 production 环境 | 阶段 1/2 由正式 lockfile、显式解释器路径/身份和 clean-clone 构建证据共同定义 | 部署不得在声明环境缺失或实际解释器不符时静默选择其他 Python |

`quant`、`industry` 与 base 环境不得视为等价。阶段 1 必须审计当前真实依赖来源，建立正式 lockfile，并确定本地、CI 与 production 的解释器合同；阶段 1 完成前，下述命令只属于兼容启动方式。

本地研发环境推荐从项目根目录用模块方式启动，避免 Python 把脚本所在的 `tools/viewer` 误当成导入根目录：

```bat
conda activate quant
cd /d D:\quant\industry_demo
python -m tools.viewer.app
```

`python tools/viewer/app.py` 也已经作为兼容入口修复并通过实测；新命令更能明确表达项目包边界，因此作为日常推荐方式。

默认目标目录仍可使用 `C:\industry_demo`，但脚本现在以自身所在目录作为项目根，不再写死部署盘符。默认激活 Conda 环境 `industry`，监听 `0.0.0.0:8080`。

```bat
cd /d C:\industry_demo
restart_viewer.bat
```

环境名或端口不同时，在同一个命令窗口先设置变量：

```bat
set VIEWER_CONDA_ENV=实际环境名
set VIEWER_PORT=8080
restart_viewer.bat
```

不用 Conda 时可以显式指定 Python：

```bat
set VIEWER_SKIP_CONDA=1
set VIEWER_PYTHON=C:\Python311\python.exe
restart_viewer.bat
```

## 预检与日志

脚本在关闭旧进程前先执行只读预检，检查六目录部署闭包、四个 SQLite 数据库（`research.db`、`sentiment.db`、`opportunity_lens.db`、`financial.db`）关键表、Python 依赖及 Flask 包导入。也可单独运行：

```bat
python tools\viewer\preflight.py --root C:\industry_demo
```

预检日志写入 `cache\viewer_preflight.log`，服务日志写入 `cache\viewer.log`。启动成功以 `http://127.0.0.1:8080/api/health` 返回 `ok=true` 为准，不再只凭端口存在判定。

首次配置新环境时，可从项目根目录的 `requirements.txt` 安装兼容依赖。它当前只是兼容安装入口，不是可重复环境的权威 lockfile；阶段 1 建立正式 lockfile 后，以 lockfile 为依赖权威。脚本不会自动联网安装或修改 Conda 环境，也不得在环境名不一致时自行猜测另一个解释器。

## 数据库传输

不要在源库仍有写入进程时只复制单个 `.db` 文件。应先停止写入任务，或使用 SQLite backup API 生成一致性快照，再传输快照；否则 WAL 中尚未 checkpoint 的数据可能遗漏。部署脚本只读检查目标库，不会修改数据库。

## 阶段 2：只读并行候选，不替换现有生产

阶段 2 的候选目录、端口和状态与当前 `C:\industry_demo` 分离：

- 代码：`C:\honghu-ai-research-candidate\releases\<full-sha>`；
- 原子指针：`C:\honghu-ai-research-candidate\current`；
- 可变状态：`C:\honghu-ai-research-candidate\runtime`；
- 候选端口：默认 `18080`，不得使用生产 `8080`；
- 数据和研究内容：只读引用现有生产根目录，不复制、不迁移、不改变权威；
- HTTP：GET/HEAD/OPTIONS 可用，POST/PUT/PATCH/DELETE 全局返回 403；
- 计划任务：不安装、不禁用、不迁移。

候选部署入口为 `tools/release/Deploy-ReadonlyCandidate.ps1`。它要求显式的 Python 3.10 绝对路径，在候选根内按 lockfile 建立隔离环境；不从 PATH 猜测 `python`，也不修改现有任务环境。候选进程直接持有 18080，并以 PID、启动时间、解释器、命令行 hash、launch id、commit 和端口核验身份；重复部署、停止和失败路径不得只相信一个裸 PID。

脚本从明确的 full commit SHA 构建 manifest 驱动 release，执行对象/列/只读探针级 SQLite 合同检查，并对首页、行业、公司、情绪、Opportunity Lens、外置 PDF、计算器和静态资源做代表性 smoke。任务定义和生产 8080/current 在部署前后分别采集后比较；无法采集的事项标为未验证，不写死成功结论。该脚本只用于人工批准的 Phase 2 候选，不会修改 `restart_viewer.bat`、生产端口或现有任务。VM 本机通过后仍须从另一台内网客户端单独验证 18080 可达。

release 不包含 `data/`、`papers/`、backup、broadcast、cache、凭据或用户内容。运行闭包分为 tracked code closure 与 external runtime closure；数据库相对 `file_path` 必须从外置 content root 解析，计算器的正式冻结模型来自 release 内 tracked config，旧 cache 回退只能从外置 state root 解析。缺少外部权威时 preflight 必须失败，不能把 live 文件复制进 Git release 充数。完整操作和本地开发命令见 `docs/RELEASE_AND_LOCAL_DEVELOPMENT.md`。
