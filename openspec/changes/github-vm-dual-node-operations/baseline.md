# 泓湖 AI 研究系统 GitHub—PostgreSQL—VM 运营迁移基线

> 首次审计：2026-08-03（北京时间）  
> 第二轮复核：2026-08-03（北京时间）  
> 第三轮合同复核：2026-08-03（北京时间）  
> 审计对象：`D:\quant\industry_demo` 本地活动工作区  
> 审计性质：只读代码、schema、测试、任务和文档审计；未初始化 Git、未连接或修改远端、未修改 live 数据库、未迁移任务、未部署 VM

## 1. 事实、推论与决策分层

为避免未来把会变化的技术事实和架构决定混为一谈，本基线统一使用三类标签：

| 类型 | 含义 | 本轮示例 |
|---|---|---|
| **Observed fact** | 只读命令、schema、代码或既有测试直接观察到的事实 | 约 124 个生产 Python 文件直接调用 `sqlite3.connect()`；六个文件包含 `ATTACH`；七个本地计划任务仍存在异常结果 |
| **Architectural inference** | 由事实推导、未来可被新证据修正的判断 | 当前迁移单位不能简单等于四个 SQLite 文件；共享身份和跨库事务需要先画依赖图 |
| **Proposed decision** | 需要人工批准或已在本 change 中确认的架构选择 | GitHub + 中央 PostgreSQL 是长期方向；SQLite 只作为逐步迁移期现状 |

**Observed fact**：现有项目已经不是单机 Viewer 加四个静态数据库，而是由本地研究开发、VM Viewer 候选、七个持续或定时任务、A/B/C 研究发布、财务模型更新和人工内容写入共同组成的多进程系统。

**Architectural inference**：继续把四套 SQLite 当成长期跨节点事实源，会迫使项目自行建设快照、变更集、冲突合并和事件回放；这些机制的复杂度接近自建数据库复制系统。另一方面，四个文件内部又混合多个业务域，不能反过来把“逐域迁移”机械理解成逐文件导入。

**Proposed decision**：private GitHub 应用仓库 + 中央 PostgreSQL 是长期目标，SQLite 是受控迁移期现状。旧 SQLite 在 PostgreSQL 尚无切换后有效新写入时可以参与直接撤回判断；一旦 PostgreSQL 已产生必须保留的新写入，旧 SQLite 只作为冻结迁移基线、审计档案和有限修复材料，不是默认 production rollback target。

阶段 0 当前仍是“方向原则确认、实施未批准”。任何 Git bootstrap、生产部署或数据切换仍需后续独立人工批准。

## 2. 工具、仓库与工作区状态

| 项目 | 当前事实 | 本轮判断 |
|---|---|---|
| Git | `2.53.0.windows.2` | 可用 |
| Git LFS | `3.7.1` | 可用；不得用于 live 数据库或频繁数据库备份 |
| GitHub CLI | 未安装 | 非阻塞；可使用 Git Credential Manager |
| 项目 Git 元数据 | 当前工作区不存在 `.git` | 本轮继续保持未初始化 |
| 远端仓库 | 两个 private repository 已由用户创建；此前仅完成临时 tag push/delete 连通性验证；当前 owner 是个人账号 `Garthzzz` | 本轮未连接；应用仓库可用于批准后的 bootstrap，但未满足 production authority 的公司控制门槛；内容仓库标记为 `RESERVED-UNUSED` |
| Python | 当前 shell 为 `D:\conda\python.exe`（3.13.12）；本地推荐 `quant` 环境为 `D:\conda\envs\quant\python.exe`（3.10.20）；`restart_viewer.bat` 默认环境名为 `industry`，本机只读枚举未发现该环境 | 三者不是等价环境；当前能运行不能证明干净机器可重建，阶段 1 必须审计实际依赖并建立 lockfile 与显式解释器合同 |
| SQLite | Python 内置 `3.51.1` | 当前 live 库完整；仍需迁移期一致基线。直接回退只适用于 PostgreSQL 尚无必须保留新写入的受控状态 |
| PostgreSQL | 尚未安装或配置为本项目生产服务 | 本轮只定义目标和迁移门槛，不实施 |

当前 `.gitignore` 只能作为辅助排除规则，不能替代 tracked allowlist、staged inventory、secret/path gate 和部署闭包。`papers/`、必要 evidence/cache、数据库、backup、broadcast、runtime 和 secrets 的边界仍需显式定义。

## 3. 文件与部署体量

首次审计统计如下；这些数字是审计快照，不是永久事实。

| 路径 | 文件数 | 约占用 |
|---|---:|---:|
| `data/` | 7 | 0.937 GiB |
| `docs/` | 215 | 0.005 GiB |
| `tools/` | 1,055 | 0.124 GiB |
| `papers/` | 2,033 | 3.715 GiB |
| `opportunity_lens/` | 357 | 0.049 GiB |
| `config/` | 7 | 0.001 GiB |
| `cache/` | 25,463 | 6.025 GiB |
| `backup/` | 3 | 8.969 GiB |
| `broadcast_packages/` | 3 | 5.396 GiB |
| `archive/` | 164 | 0.185 GiB |

直接提交整个目录会把 live DB、备份、广播包和运行 cache 带入永久历史。干净 clone 应恢复正式开发和审核规则，但不应复制生产数据或个人工作记忆。

## 4. 四套 SQLite 的事实与代码耦合

首次审计使用只读 URI、`query_only`、完整性和外键检查，四库均通过。动态行数会变化；本次复核没有修改数据库。

| 数据库 | 主要职责 | 首次审计状态 | 本次代码审计结论 |
|---|---|---|---|
| `research.db` | A/B 行研、身份、动态内容、人工研究内容 | WAL、完整性 ok | 同时承载共享身份、动态任务和 Viewer 人工写入；不是单一写者 |
| `sentiment.db` | 情绪、窗口、K 线和供应链镜像 | WAL、完整性 ok | 体量最大、窗口补漏与运行状态最复杂，不适合作为首个 PostgreSQL 试点 |
| `opportunity_lens.db` | C 轨研究、证据、审核和发布 | DELETE、完整性 ok | 已有 staging、review、publication ledger，迁移后仍有独立业务价值 |
| `financial.db` | 结构化财务、市场、预测、模型和修订 | DELETE、完整性 ok | 已有 revision、reconciliation 和 model ledger，但须结合共享身份和跨库 writer 定义切换单元 |

**Observed fact**：本次只读检索发现，`tools/` 下约 **124 个生产 Python 文件**直接调用 `sqlite3.connect()`；六个文件出现 `ATTACH`，27 个文件出现 `BEGIN IMMEDIATE`，33 个文件使用 SQLite conflict syntax。常见耦合包括：

- `PRAGMA`、WAL 和 busy timeout；
- `ATTACH` 跨库只读或写入；
- `BEGIN IMMEDIATE`；
- `INSERT OR IGNORE/REPLACE`；
- `sqlite_master`、`lastrowid`、`rowid`、`AUTOINCREMENT`；
- `?` 参数占位和 SQLite 日期函数；
- 硬编码 `data/*.db` 文件路径。

**Architectural inference**：不能把数据库迁移理解成“四个文件导入 PostgreSQL”。例如公司建档和财务刷新把 `research.db` 与 attached `financial.db` 的更新组织在同一 SQLite transaction scope 中；Viewer 和情绪公共层又会 attach `research.db` 做跨域读取。当前主库 `research.db` 使用 WAL，[SQLite 官方 `ATTACH` 语义](https://www.sqlite.org/lang_attach.html)不支持据此承诺主库与 attached 文件在主机崩溃时具有无条件的跨文件全局原子性。迁移前必须验证真实提交和故障语义，并把这些操作视为必须共同审计的业务事务边界。

阶段 3 必须产出可持续更新的机器可读依赖 inventory，至少记录：文件路径、所属域、reader/writer、SQLite 专属语义、`ATTACH` 来源与目标、涉及的页面/API/任务/publisher、候选 cutover unit、当前 authoritative backend 和迁移状态。还必须生成 cutover unit registry，唯一标明每个可写对象、writer 和完整事务边界的 owning unit、其他 unit 的 dependency、重叠冲突检查、S0—S4 状态和责任人。本轮只规定产物合同，不实施扫描工具。

## 5. 当前写入边界

代码审计确认至少存在以下独立写入路径：

1. A/B 统一 ingest 和数据点写入；
2. Opportunity Lens 暂存、审核、发布与补充研究；
3. financial 观测、修订、模型运行和对账；
4. 动态新闻、意见领袖、事件和调度状态；
5. 情绪原文、评分、窗口、聚合、补漏和 retention；
6. Viewer 中 comment、thesis、hypothesis、Q6、人工事件等写接口；
7. 公司身份和跨库财务映射工具。

部分工具通过 SQLite `ATTACH` 在 `research`、`financial` 或 `sentiment` 之间共享身份、查询，或把跨文件更新放入同一 transaction scope；这表达了应用希望共同成功的业务意图，但不应被写成在所有 journal mode 和崩溃点下都成立的跨文件强原子保证。公司、证券、行业、研究 run、financial observation/model、用户内容、artifact 和 task/window 等对象并不都具备跨环境稳定身份；现有不少关系仍依赖单个 SQLite 自增整数。

**Architectural inference**：一个主要 PostgreSQL database + 逻辑分域仍是合理起点，但迁移前必须为跨域、跨环境、可发布或需审计对象建立稳定业务身份或 legacy ID mapping。数据库内部可以继续使用 surrogate key，不能把所有对象强制改成 UUID，也不能把 SQLite 自增 ID 直接当作跨环境身份。

## 6. 用户内容现状

本次复核的 live schema 显示：

- `analyst_note` 当前为 0 行；
- `company_thesis` 当前为 0 行；
- `industry_thesis`、`hypothesis` 和 `hypothesis_update` 已有少量记录；
- 现有 `analyst_note` 使用整数主键，缺少 revision、soft delete 和完整 audit 合同。

`analyst_note=0` 是低风险建立新 PostgreSQL 用户内容模型的机会，不是继续为 SQLite 新建 Git outbox/事件复制系统的理由。已有 thesis/hypothesis 等内容仍必须在迁移时保留、对账，并具备 PostgreSQL 备份与选择性修复路径，不能因数量少而忽略。

## 7. Viewer 与部署基线

- 首次审计时本地 `0.0.0.0:8080` 正在监听，`/api/health` 返回 `ok=true`。
- `tools/viewer/preflight.py --root .` 通过。
- 当前运行版本没有 release manifest 或 commit 身份。
- 正式内网部署仍依赖全量广播包和 `restart_viewer.bat`。
- 广播包已具备必要 cache 引用闭包和 SQLite 一致快照能力，但它是过渡冷备，不是长期发布或数据同步协议。

Viewer 当前直接执行大量 SQLite 查询和部分写操作，且身份、权限和 CSRF 尚未形成完整生产合同。数据库访问层和写权限不能只改后台任务而遗漏 Viewer。

## 8. 自动任务基线

首次审计发现 7 个 `IndustryDemo_*` Windows 计划任务，全部使用 Interactive 登录类型。审计时状态和结果保持原记录：

| 任务 | 当前状态 | 最近结果（首次审计时） |
|---|---|---|
| DynamicTick | Ready | `0x00000000` |
| EventIngest | Ready | `0x00000000` |
| RecruitWeekly | Ready | `0x00000000` |
| Retail_Afternoon | Ready | `0x40010004` |
| Retail_Morning | Running | `0x00041301` |
| Retail_Preopen | Ready | `0x00000002` |
| SentimentRetention | Ready | `0x40010004` |

这些失败或未正常完成状态没有被美化或关闭。正式迁移仍需逐任务真实试跑、checkpoint/ledger、停机窗口识别和补跑策略。任何时刻不得在本地与 VM 同时启用同一生产任务。

第三轮只读复核时，七个任务仍全部为 `InteractiveToken`、用户为 `zhang`；状态均为 Ready，但最近结果已经变化：DynamicTick、EventIngest、RecruitWeekly 为 `0`，三个 Retail 任务为 `2`，SentimentRetention 为 `0x40010004`。这张复核记录不覆盖上表的首次审计事实，也不把 Ready 解释为任务成功；它证明任务状态会变化，迁移前必须重新采集机器可读现状。任务动作还混用 base 与 `quant` 环境，不能把现有安装说明中的非交互运行写成已经实现。

## 9. 测试基线

### 已通过

- `python -m compileall -q tools tests`：通过。
- `python -m tools.maintenance.audit_workflow_contract`：通过，无 findings。
- Viewer preflight：通过。
- `tests/maintenance`：7 passed。
- `tests/pipeline`：4 passed。
- `tests/sentiment`：96 passed，另有 6 subtests passed。
- `tests/research_workflow` 排除 stdout 副作用文件：234 passed，另有 26 subtests passed。
- `test_dynamic_weibo_bridge.py` 使用 `unittest` 独立执行：13 passed。
- `tests/opportunity_lens` 的活动主测试集：351 passed，另有 37 subtests passed。

### 未通过及原因

1. 标准 pytest 收集/报告会被旧动态模块的 import-time stdout 重建破坏。业务断言通过不等于 CI 可用；该副作用仍需修复。
2. 旧硅片设备/需求 run-pack 构建器存在 10 failed、14 setup errors，原因是未补 V2 `source_channel=report|web` 契约。不得降低活动合同或用永久 `xfail` 掩盖仍在维护的路径。

这些失败不阻止建立**安全初始 Git 历史**，但会阻止相应分支合入受保护生产 `main`，更不能带病部署生产 VM。

## 10. 阻塞项重新分级

| 门槛 | 必须先关闭 | 不属于该门槛的事项 |
|---|---|---|
| 安全 Git bootstrap 前 | tracked allowlist、secret/path 扫描、live DB/backup/runtime/cache/未批准大文件排除、首次 staged inventory 人工确认、private repository 与权限边界确认 | 全量测试修复、PostgreSQL、任务迁移、身份系统、完整灾备演练 |
| 首次 CI / 受保护 main 前 | 可重建依赖、标准测试入口、活动路径测试、branch protection、required checks、部署 manifest 校验 | VM 生产任务切换、全部 PostgreSQL 域迁移 |
| VM 只读并行部署前 | immutable release、runtime 分离、preflight/health、明确 commit SHA、只读连接与回滚验证 | 人工写接口开放、自动任务切换 |
| 自动任务切换前 | 服务账户、任务 manifest、单实例锁、checkpoint/ledger、停机补漏、真实试跑、本地与 VM 排他切换 | sentiment 等全部域已经迁移才可开始评估 |
| PostgreSQL cutover unit 切换前 | 机器可读依赖 inventory、cutover unit 唯一 ownership/dependency registry、读写/事务图、权威后端矩阵、稳定身份映射、dev/test migration、expand–migrate–contract 兼容计划、业务不变量对账、写入冻结、已批准 target RPO/RTO 和不同时间点恢复策略 | 其他无依赖 unit 同步切换 |
| 每个 production 数据切换前 | 与 target RPO/RTO 对应的生产备份和恢复路径演练、权限最小化、关键写路径与 publisher 并发测试、S2 水位与 uncertain-response 合同、可观测性、维护窗口、人工批准 | 未被 target RPO/RTO 要求触发的高可用强化 |
| 最终生产迁移验收前 | 整库、单域旁路和空机真实恢复演练；记录 measured RPO/RTO、未恢复数据及补抓/选择性修复耗时并证明达到目标 | 后续容量和自动故障转移强化 |
| 应用仓库成为 production authority 前 | 公司资产归属或正式例外、第二位公司管理员/交接、强制 2FA、branch protection、最小权限和公司控制的 VM deploy credential | 不阻止在安全边界内建立 bootstrap 历史 |
| 后续生产强化 | 更细粒度监控、容量规划、只读副本、自动故障转移、进一步安全治理 | 不应倒置为 Git 初始化阻塞 |

## 11. 架构方向与仍待决定事项

已经形成的方向：

- GitHub 管理代码、migration、测试、部署脚本、活动 OpenSpec、团队 `AGENTS.md`、生产/审核依赖的 skills 和正式 SOP；不管理 live rows。
- PostgreSQL 作为长期结构化数据单一事实源；优先一个主要业务 database 内逻辑分域。
- `papers`、evidence 和大文件使用内部文件或对象存储；Git 只保存获准的小文件和内容清单。
- 本地使用独立 dev/test PostgreSQL 或明确的 production 只读权限；本地开发不依赖 VM 在线。
- 用户内容默认进入 PostgreSQL revision/audit/soft-delete 和标准备份，不做每次编辑 Git push。

仍需用户在实施前决定的输入包括：

1. 各类数据可接受的数据损失和恢复时长等级（RPO/RTO），尤其是人工内容、正式 publication、财务模型、不可补抓动态/KOL、封存情绪聚合和 papers/evidence 原件；
2. 在上述目标下，生产 PostgreSQL 初期与 Viewer/任务 VM 共置还是独立部署；基于当前体量、停机容忍和运维经验，共置是可接受的生产候选，但不构成高可用；
3. `papers/evidence` 的批准存储位置及资料上云合规边界；
4. 应用仓库成为 production authority 前采用转入公司 Organization，还是公司共同控制和交接完备的正式例外；

已创建的内容仓库已经明确标记为 `RESERVED-UNUSED`，不再作为待定 live/backup 容器；若未来需要 GitHub 加密灾备，应另行评估职责明确的 backup repository。

第三轮合同关闭后可以建议用户人工批准阶段 0 退出并进入阶段 1，但本文件不代替该批准。阶段 1 仅允许 tracked allowlist、secret/path gate、staged inventory、安全 Git bootstrap、测试基线修复、lockfile、CI 和受保护 main 的准备；不授权 PostgreSQL production、数据访问层生产改造、数据库或 runner 切换、VM production deploy、人工写接口开放或仓库成为 production authority。

## 12. 本轮明确未执行

本轮没有初始化或 push Git，没有连接或修改 GitHub 远端，没有安装或启动 PostgreSQL，没有修改四套 live SQLite，没有迁移或停用计划任务，没有修改 VM、Viewer production 配置、papers、备份或广播包，也没有开始后续实施阶段。
