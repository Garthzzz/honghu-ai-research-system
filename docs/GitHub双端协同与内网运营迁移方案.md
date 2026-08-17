# 泓湖 AI 研究系统 GitHub—PostgreSQL—VM 运营迁移方案

> 状态：阶段 0—4 已获批准退出；Stage 4 九个数据切换单元均为 durable S3。用户已于 2026-08-16 授权 Stage 5 的七个任务、runner、checkpoint、恢复与监控迁移；实施进行中，尚未宣布 Stage 5 PASS。
> OpenSpec 权威变更：`openspec/changes/github-vm-dual-node-operations/`。
> 本文是便于团队阅读的总览；阶段、门槛和验收以该 change 的 `baseline.md`、`design.md`、`tasks.md` 和 capability specs 为准。

## 1. 为什么重写原方案

原方案把 VM 四套 SQLite 作为长期生产事实源，再为本地研究和 VM 运营建立：一致快照、request workspace、通用 change-set、前后值 hash、CAS、reverse change-set、冲突报告、用户内容 Git outbox 和事件回放。

这些机制并非逐项错误，但合在一起相当于自建一套 SQLite 跨机器复制和事件溯源平台。当前系统已经有多个进程、两个运行环境、人工写入、研究发布、财务模型和定时任务；中央 PostgreSQL 带来的单一事实源、事务、权限、schema migration、共享身份和标准恢复能力，已经有直接价值，不需要等数据量或用户数进一步放大。

因此长期方向改为：

> **受控 GitHub 应用仓库管理代码和正式规则；中央 PostgreSQL 管理 live 结构化数据；内部文件或对象存储管理 papers/evidence；本地 dev/test 与 VM production 分离。**

长期正常边界仍优先采用 private/公司治理仓库。用户已明确批准迁移实施和人工审核期间保持 public，便于核验 Actions、提交和阶段证据；该公开例外不允许新增数据库、papers、用户内容、凭据或其他敏感资产，也不使个人账号仓库自动成为 production authority。

SQLite 不立即下线，但只作为按业务切换单元迁移的现状。PostgreSQL 产生必须保留的新写入后，旧 SQLite 主要是冻结迁移基线、审计档案和有限修复材料，不再是默认无损回滚点。

截至 2026-08-16，`user_content_notes`、`shared_identity`、`financial_data`、`research_publication`、`dynamic_intelligence`、`operations_governance`、`investment_hypotheses`、`opportunity_lens` 与 `sentiment_analytics` 均为 S3/`postgresql_production`，所有 SQLite writer 均已 fenced。Production Viewer 以 `production_hybrid` 展示逐单元 authority；该名称表示应用仍有外置文件、兼容 projection 和未迁移 runner，不表示任何数据单元可回退 SQLite writer。最终 evidence 与 recovery identity 见 Stage 4 completion report 和 `BACKUP_REGISTRY.md`。

## 2. 目标架构

### GitHub 应用仓库

进入 Git：

- 应用代码和配置模板；
- database migration；
- 测试、CI、部署和恢复脚本；
- 团队 `AGENTS.md`；
- 活动 OpenSpec；
- 生产和审核依赖的 skills；
- 正式 SOP 和影响代码质量的项目规则。

不进入 Git：

- live PostgreSQL/SQLite 数据、WAL/SHM、日常 dump；
- backup、broadcast、runtime、日志；
- credentials、Cookie、browser profile；
- 个人 scratch、对话历史、一次性工作记忆；
- 未批准的 papers、用户内容和大文件。

### 中央 PostgreSQL

长期承载：

- 共享 company/security/industry 身份；
- A/B 研究和动态内容；
- Opportunity Lens；
- 财务、市场、预测和模型；
- 情绪与窗口数据；
- comment、thesis、hypothesis、Q6 等人工内容；
- 任务 ledger/checkpoint；
- revision、publication 和 audit。

优先一个 PostgreSQL instance、一个主要业务 database，按逻辑 schema、角色和 writer 分域。只有明确的容量、法规、权限或故障域证据才物理拆库；不机械复制成四个 PostgreSQL database。

### papers/evidence 与大文件

使用批准的内部文件系统或对象存储。数据库保存元数据、SHA256 和定位，应用 Git 保存必要 manifest；不把 PDF 塞进数据库，也不默认上传 GitHub。

### 本地与 VM

- 本地：pull、开发、测试、启动 Viewer、浏览器验证、commit/push；使用独立 dev/test PostgreSQL，不依赖 VM 在线。
- VM：按明确 commit SHA 拉取和部署 immutable release，运行 production Viewer 和批准的任务。
- production PostgreSQL：初期可与 Viewer/任务 VM 共置，也可独立部署；选择由数据分类后的 RPO/RTO、隔离、维护和资源条件决定。共置不是高可用，但在具备自动启动、crash recovery、VM 外备份和空机恢复时可以成为当前 production 拓扑。

## 3. 不再建设的长期能力

- 本地与 VM 的四库日常 `ops-snapshot` 同步；
- 通用 `research-change-set`、before/after hash、跨机器 CAS；
- reverse change-set 和通用 SQLite 冲突合并；
- comment 等每次编辑 push Git；
- Git event materializer 和空库事件回放；
- 长期 SQLite/PostgreSQL 双写；
- GitHub 作为 live 数据库或唯一备份。

迁移窗口仍可使用一致 SQLite backup、源目标对账和 shadow read，但它们不是日常运营协议。只有 PostgreSQL writer 尚未产生必须保留的新写入时，才可能在停写和核验后直接恢复 SQLite writer。

## 4. 迁移后仍保留的业务能力

- 研究 staging、review、publisher 和 publication ledger；
- 唯一 publication/release id、幂等提交、expected/base revision、stale conflict 和依赖簇事务原子性；
- evidence、calculation、financial、writing、browser 和 final review；
- financial revision、reconciliation 和模型运行账本；
- 用户内容 revision、soft delete 和 audit；
- 任务 manifest、运行锁、checkpoint、错过窗口补跑和新鲜度；
- immutable release、preflight、health、commit SHA 和 code-only rollback；
- secret/path gate、artifact manifest、异地备份和 restore test。

这些能力解决的是研究质量、并发冲突、用户内容治理、任务幂等和可恢复性，迁移 PostgreSQL 后仍有价值。删除通用 SQLite CAS 不等于允许 publisher 或 comment 静默 last-write-wins。

## 5. Git 接入的三个不同门槛

### 安全 bootstrap commit

只要求 tracked allowlist、secret/path gate、禁止资产排除、首次 staged inventory 人工审查和仓库可见性/权限获得明确批准。已知测试债务可以在 bootstrap branch 内修复；当前 public 审核例外必须配套每阶段暴露复核。

### 合入受保护 main

要求标准测试入口稳定、活动 required checks 通过、依赖可重建、branch protection 生效。不得把活动失败路径永久隐藏。

### VM production 部署

还要求 immutable release、deployment manifest、preflight/health、只读 smoke、runtime 分离、明确 commit SHA 和 code-only rollback。候选 listener 必须绑定可核验的进程身份，Python 环境必须由明确的 3.10 解释器在候选根按 lockfile 重建；所有导入项目代码的子进程都必须隔离 `PYTHONPATH/PYTHONHOME` 并禁止写 bytecode，且在 build、preflight、activate、launch、smoke、stop 或失败清理后复核同一 manifest。相同 SHA 的失效但未激活目录只能整体进入可审计 quarantine 后重建，current 或运行引用的 release 不得自动清理。计划任务和生产 8080/current 要采集部署前后状态，不能用脚本声明替代实测。只读 smoke 应覆盖四库、外置文档、计算器和静态资源，并把 VM 本机与内网客户端可达性分开记录。code-only rollback 只有在当前 backend 通过旧 release 声明的对象、列、版本和只读探针合同时成立；仅计算 schema fingerprint 不是完整兼容证明，forward-only migration 需要单独恢复策略。数据库 migration 和任务切换另有独立批准。

当前应用仓库属于个人账号 `Garthzzz`。它可以在批准后用于安全 bootstrap 和开发，但成为 production authority 前必须完成公司资产归属或正式例外、第二位公司管理员/交接、强制 2FA、账号恢复、branch protection、最小权限和公司控制的 VM deploy credential。

## 6. 数据迁移原则

1. 先生成机器可读 SQLite dependency inventory，覆盖路径、域、读写、SQLite 专属语义、`ATTACH`、页面/API/任务/publisher 和迁移状态。
2. 形成数据域依赖图、读写路径、跨域事务图、共享身份和必须共同成功的业务操作。
3. 以完整业务事务语义定义 `cutover unit`，而不是按 SQLite 文件、schema 或表机械迁移。
4. 建立 cutover unit registry：每个可写对象、writer 和完整事务边界只能有一个 owning unit，其他 unit 只登记 dependency；共享身份按依赖与事务审计决定单独成基础 unit 或纳入共同 unit。authoritative-backend matrix 必须唯一给出对象、owning unit、S0—S4 状态、后端和 writer，重叠 ownership 必须阻断切换，边界变化必须人工复核。
5. 建立统一连接/事务边界、稳定业务身份与 legacy ID mapping、PostgreSQL dev/test 和可重复 migration。
6. 采用 expand→migrate/backfill→application transition→后续独立 contract；破坏性 migration 不与首次依赖它的代码做一次不可逆发布。
7. 每个切换单元做 rehearsal、源目标不变量、publisher 并发/幂等、shadow read、权限、性能和恢复验证，再在短维护窗口切换。
8. 一个业务事务不得在 SQLite/PostgreSQL 两边分别提交后声称原子完成；不能安全拆分的依赖必须共同切换。

切换状态分为：SQLite 权威；PostgreSQL 准备但 SQLite 仍权威；PostgreSQL 已启用且尚无必须保留新写入；PostgreSQL 已产生有效新写入；PostgreSQL 稳定。第三种状态（S2）只是短时切换栅栏，不是日常运行状态：PostgreSQL 是唯一指定 writer，SQLite writer 已停止并冻结；普通业务仍被阻断，只允许可区分、无正式业务效果的 PostgreSQL 验证写。必须记录 cutover epoch、SQLite 最终权威业务水位、PostgreSQL 首条正式业务 commit 水位、验证写和 uncertain response。首条必须保留的正式写提交即进入 S3；数据库可能已提交但响应不确定时，按稳定身份/幂等键查账，无法证明未提交就按 S3。只有停写、水位与审计证明无新写入并获人工批准，S2 才可能退回 SQLite；S3/S4 不能。此后优先前向修复、保持 PostgreSQL 数据的兼容代码回滚，或将 PostgreSQL 备份恢复到旁路环境后选择性修复。

排序通常会把 `sentiment` 放在后面，因为其体量、窗口状态、补漏和 retention 最复杂。`analyst_note` 当前为空，适合测试新的用户内容模型；Opportunity 和 financial 已有较成熟 ledger，可作为后续候选。最终顺序必须由切换单元和事务依赖审计决定。

## 7. 用户内容

用户内容默认进入 PostgreSQL：当前值 + revision + soft delete + audit。需要可移植性时做受控导出，导出应带版本、范围、时间和完整性信息。

独立内容 Git 仓库不再是默认实时数据库。已创建、实际 slug 以 `-` 开头的仓库明确标记为 `RESERVED-UNUSED`：保持空置、无生产凭据、不承载 live 内容或备份。未来若需要 GitHub 加密灾备，应重新评估职责明确的 backup repository，而不是默认复用它。

## 8. VM 停机与任务补漏

VM 停机期间生产可以暂停，但恢复后不能假定数据完整。每个任务必须知道：

- 上次成功的逻辑窗口；
- 哪些窗口漏跑；
- 哪些来源可补、补多久；
- 哪些来源不可补；
- 重试和幂等边界；
- 当前是“进程运行”还是“数据已追平”。

任务逐个迁移：VM disabled 安装、受控真实试跑、再次证明本地同名任务 Disabled、启用唯一 VM runner、观察并保持本地 Disabled。Stage 5 启动时本地七任务虽已 Disabled，但每次 VM 启用前仍须重新采集现场证据；不得本地和 VM 双跑。

数据存储切换和任务主机切换是两条独立轴。允许任务暂由本地唯一 runner 连接 production PostgreSQL，但这必须是有退出条件的迁移状态，并登记任务、临时 owner、开始时间、唯一 runner、角色权限、网络/凭据、checkpoint、暂留原因、退出条件、下一 HALT、VM 前置和逾期升级。断线不触发 SQLite 回退；VM 启用前先证明本地已停止，完成后撤销不再需要的本地生产写权限。如果不批准本地连接，则 runner 与对应切换单元同窗切换。任务主机回退不得把已经有新数据的 PostgreSQL 权威改回旧 SQLite。

为避免误实施，文档统一区分：应用 release 切换、cutover unit 数据后端切换、任务 runner 主机切换，以及最终生产迁移验收。未带对象的“生产切换”不得作为操作授权或回滚依据。

## 9. 备份与恢复

- production PostgreSQL 备份必须离开 Viewer/task VM 故障域；
- 备份需定期真实 restore test；
- VM 整体损坏后可用 Git release、database backup、artifact manifest 和 secrets 重建；
- GitHub 可选存客户端加密的第三份低频灾备，但不是 live 或唯一备份；
- 广播包继续作为过渡冷备，直到新恢复路径通过真实验收。

备份设计先按数据类别批准 target RPO/RTO：人工内容、正式研究发布/ledger、共享身份和 checkpoint 几乎不可接受丢失；财务与研究数据需要保留 as-of/revision；动态、KOL 和情绪要区分可补抓与不可补抓窗口；papers/evidence 原件可能无法再次取得。目标决定是否需要 PITR、备份频率和物理拆分。Stage 4 已验证的 `0.007s` 是固定 recovery-set target gap，`8.047s` 是该数据库 target 的 restore elapsed，不代表任意连续生产故障的全系统 RPO/RTO。Stage 5 最终验收必须使用故障前已异机持久化的 base/WAL，通过整库、单域旁路和 clean/isolated 空机恢复记录实际 recoverable watermark、恢复耗时、缺失数据、补抓和选择性修复时间；未达到目标不得宣布迁移完成。

整库灾难恢复与单域逻辑修复分开。单个域出错时，优先把备份恢复到旁路实例，按稳定身份选择性提取、对账并修复 production；不因一个域的问题原地回退整个主要 database，避免抹掉其他域的新写入。

具体备份工具、分片、保留天数和高可用拓扑在实施审计后决定，不在当前架构稿写死。

## 10. 阶段与 HALT

1. 架构审查与批准；
2. 安全 Git bootstrap 与 CI；
3. 可重复 release 与本地开发基线；
4. 依赖/事务建模、PostgreSQL dev/test 与低风险切换单元试点；
5. 按切换单元 production PostgreSQL 迁移；
6. 逐任务切换、生产安全、监控和恢复强化。

每阶段结束必须提交 evidence 并由用户人工验收。Stage 5 已获连续实施授权，不因普通任务里程碑逐项 HALT，但完成前不得自行宣布 PASS，也不得扩张到 HA、replica、CDC 或自动故障转移。

## 11. 当前待用户/公司治理关闭

1. 公司资产归属，或个人账号继续托管的正式例外；
2. 第二位公司管理员、2FA、账号恢复与交接；
3. production reviewer gate 与公司控制、可轮换/撤销的 VM deploy credential；
4. Stage 5 全系统 measured RPO/RTO、空机恢复和七任务现场 evidence 的最终人工验收。

在上述 repository governance 完全关闭前，临时发布模式固定为 `CI green → 用户人工批准 exact SHA → VM immutable deploy`，禁止 main merge 后无人审核自动上线。内容仓库保持 `RESERVED-UNUSED`；Stage 5 工程可在已批准边界内继续，但不得把待决项伪装成已完成。

第三轮合同一致性通过后，方案可以建议人工批准阶段 0 退出，但不会自行批准。阶段 1 只允许 tracked allowlist、secret/path gate、staged inventory、安全 Git bootstrap、测试基线修复、lockfile、CI 和受保护 main 的准备；不允许 PostgreSQL production、生产数据访问层改造、数据库或 runner 切换、VM production deploy、人工写接口开放，也不自动让个人账号仓库成为 production authority。
