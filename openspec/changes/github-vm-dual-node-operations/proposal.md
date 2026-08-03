## Why

泓湖 AI 研究系统已经由本地研究工作站、VM Viewer、七个定时任务、A/B/C 研究发布、财务模型、动态/情绪流水线和人工内容共同组成。继续把四套 SQLite 作为长期跨节点事实源，需要自建快照、change-set、CAS、冲突合并、事件回放和双端恢复；这会重复实现中央事务数据库已经提供的能力，并把真正需要的研究发布、审计和任务补漏埋在同步基础设施中。

本变更重新确定迁移方向：先用 private GitHub 应用仓库建立安全、可审核、可重复的代码交付，再逐步把结构化 live data 迁移到中央 PostgreSQL。SQLite 保持当前生产可用状态并按 cutover unit 迁移；PostgreSQL 产生切换后有效新写入后，旧 SQLite 只作为迁移基线、审计档案和有限修复材料，不得被描述成可无损退回的 production rollback target。

## What Changes

- 将 private `honghu-ai-research-system` 定义为代码、配置模板、database migration、测试、部署/恢复脚本、活动 OpenSpec、团队 `AGENTS.md`、生产和审核依赖 skills 及正式 SOP 的权威版本库；live rows、数据库文件、WAL/SHM、backup、runtime、credentials、个人 scratch 和未批准大文件不得进入普通 Git 历史。
- 将中央 PostgreSQL 定义为长期结构化生产数据的单一事实源。优先使用一个 PostgreSQL instance 和一个主要业务 database，以逻辑 schema、共享主体身份、角色和 writer 权限分域；只有明确的容量、权限、故障域或独立扩容证据才物理拆库。
- 将四套 SQLite 明确定义为受控过渡状态。迁移单位是具有完整业务事务语义的 cutover unit，不一定等于文件、schema 或表；每个可写对象、writer 和完整事务边界只能有一个 owning unit，其他 unit 只能声明 dependency。混合期必须显式记录每个 unit 的 authoritative backend、reader、writer、runner、S0—S4 状态和依赖，禁止重叠 ownership、自动后端回退和跨两种存储的伪事务。
- 删除通用 `ops-snapshot`、`research-change-set`、跨机器 CAS/reverse change-set 和长期双写目标，但保留研究 publisher 和人工内容更新本身需要的稳定发布身份、expected/base revision、幂等、stale conflict、依赖簇原子事务和 ledger；禁止静默 last-write-wins。
- 将 comment、thesis、hypothesis、Q6 等人工内容纳入 PostgreSQL revision、soft delete、audit 和标准备份，不再默认建立“每次编辑即 push Git”的第二套实时内容数据库。已创建的内容仓库明确标记为 `RESERVED-UNUSED`；未来加密灾备另行评估职责明确的 backup repository。
- 保留 VM pull-based immutable release、明确 commit SHA、`releases/current/runtime` 分离、preflight、health、部署 ledger 和代码级回滚。schema 采用 expand–migrate/backfill–application transition–contract；code-only rollback 仅在数据库仍兼容旧代码时成立，破坏性 contract 必须在后续独立批准的 release 中执行。
- 明确保留本地开发：本地可 pull、修改、运行测试、启动 Viewer、浏览页面并 commit/push；使用独立 dev/test PostgreSQL 或明确只读的 production 连接，不依赖 VM 持续在线。
- 建立统一数据访问边界、SQLite 依赖 inventory、跨域事务图和 PostgreSQL dev/test migration，再按风险和 cutover unit 迁移。S2 只作为有切换 epoch、源末水位、目标首条正式提交水位和 uncertain-response 审计的短时栅栏；无法证明没有必须保留的新写入时按 S3 处理。数据后端 `SQLite→PostgreSQL` 与任务主机 `本地→VM` 是两条独立迁移轴；任何本地 runner 连接 production PostgreSQL 的中间态都必须有唯一 runner、受限凭据、checkpoint、责任人和明确退出条件。
- 将稳定身份重新定位为业务合同：跨域、跨环境、可发布或需审计对象必须有稳定业务身份或 legacy mapping；数据库内部仍可使用 surrogate key，不要求一律 UUID。
- 明确备份边界：GitHub 不是 live DB 或唯一备份；生产数据需 VM 外或公司内部异机备份和真实 restore test。一个 database 多逻辑域发生局部错误时，默认把备份恢复到旁路隔离环境并选择性修复，不用整库原地时间回退连带覆盖其他域。
- 在 production 数据切换前，先按人工内容、正式发布、财务、动态/KOL/情绪、papers/evidence 和可再生派生物批准 target RPO/RTO，并据此决定 PostgreSQL 共置/独立、备份频率、连续归档、只读副本或故障转移；迁移最终验收再以整库、单域旁路和空机恢复演练记录 measured RPO/RTO。基于当前体量和可接受停机，共置是可接受的初期生产候选，但不得称为高可用。
- 当前应用仓库属于个人账号，可在批准后用于安全 bootstrap；成为 production authority 前必须满足公司控制、2FA、共同管理/交接、branch protection、最小权限和公司控制的 deploy credential。内容仓库明确为 `RESERVED-UNUSED`，不得获得生产凭据或保存 live/backup 数据。
- 保留广播包作为迁移期冷备和应急路径，直到 Git release、PostgreSQL 数据恢复和空机恢复分别通过验收。

## Capabilities

### New Capabilities

- `application-release-deployment`: 安全 Git bootstrap、受保护 main、可重复构建、immutable release、原子切换和代码回滚。
- `central-postgresql-data-platform`: 中央 PostgreSQL 权威、cutover unit、混合期权威矩阵、稳定身份、数据访问层、dev/test/prod 隔离和逐步切换。
- `research-publication-governance`: 研究暂存、审核、稳定发布身份、expected revision、幂等、事务原子性和 publication ledger。
- `user-content-governance`: 人工内容 revision、soft delete、audit、权限和备份；不依赖 Git 实时复制。
- `vm-automation-operations`: 任务 manifest、服务账户、单实例运行、checkpoint、停机补漏、切换和运行健康。
- `artifact-and-secret-boundaries`: 代码、项目规则、papers/evidence、必要 cache、数据库、备份、个人上下文和 secrets 的分类与门禁。
- `backup-recovery-security`: 切换前 target RPO/RTO、最终验收 measured RPO/RTO、整库灾难恢复、单域旁路恢复、PostgreSQL 与迁移期 SQLite 备份、跨故障域保留和恢复演练。

### Retired Capability Directions

- `runtime-data-synchronization` 的长期四库快照、通用 change-set/CAS 和双端 SQLite 合并目标被 `central-postgresql-data-platform` 替代；只保留迁移窗口内的一致快照和对账。
- `user-content-replication` 的 Git outbox/event/materializer/replay 目标被 `user-content-governance` 替代；内容仓库不再是实时事实源。

## Impact

- 未来实施将影响 Git/CI、依赖锁、部署 manifest、Viewer 和任务的数据访问方式、database migration、用户内容模型、备份恢复和 Windows 任务运行边界。
- 长期数据权威从四个 SQLite 文件迁移到中央 PostgreSQL；迁移必须按 cutover unit 可对账、可恢复、无双 writer。这里的 recovery 不承诺 PostgreSQL 产生新写入后可以直接退回旧 SQLite。
- A/B/C 研究语义、财务数据来源政策、公司身份规范和 Viewer 信息架构不因数据库选择而改变。
- `papers/evidence` 继续与代码和结构化数据库分离；其实际存储由资料合规和内部基础设施决定。
- 本提案不授权本轮初始化 Git、连接远端、安装 PostgreSQL、修改数据库、迁移任务或部署 VM。

### 阶段 1 授权边界

用户已在第三轮合同一致性校验后批准阶段 0 退出。该批准只开放阶段 1 的安全 Git bootstrap、测试基线修复、lockfile、CI 和受保护 main 准备，不包含 PostgreSQL production、数据或任务切换、VM production deploy、人工写接口或 production authority 授予；后续阶段仍须分别人工批准。
