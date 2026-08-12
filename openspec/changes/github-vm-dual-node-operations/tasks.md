# 泓湖 AI 研究系统迁移任务

> 状态说明：本文件是人工批准后的实施路线，不是自动执行队列。每阶段完成后必须 HALT；未经用户明确批准不得进入下一阶段。  
> 当前状态：阶段 0、阶段 1 已获用户批准退出；阶段 2 已于 2026-08-07 17:12:24 +08:00 以 `STAGE 2 PASS WITH HUMAN WAIVER` 完成人工终验并获准退出；阶段 3 已于 2026-08-11 14:25:45 +08:00 完成人工审查并获准退出。用户现已授权阶段 4 production PostgreSQL 基础设施、恢复能力以及各切换单元的 migration/S1 准备，但未授权任何单元进入 S2/S3、正式 PostgreSQL 业务写入、live SQLite 修改/迁移、计划任务迁移、production writer/backend、Viewer 或 runner 切换。
> 阶段 1 远端状态（2026-08-04）：失败 CI 的 Windows 8.3/规范长路径根因已修复；`main` 已创建并配置两个 required checks、严格更新、PR review gate、管理员同样受约束、禁止 force push/删除；阶段修订均通过受保护 PR 与 main Actions 验证，精确 commit/run 由 required job 的 runtime evidence 记录。用户明确要求仓库在迁移、实施和人工审核期间保持 public；这是一项当前运营指令，不改变“成为 production authority 前仍需公司治理”的 gate。

## 0. 阶段 0 启动时已确认的历史事实

- 两个 private GitHub repository 已由用户创建；此前只做过临时 tag push/delete 连通性验证。
- 阶段 0 审计时工作区尚未初始化 Git；阶段 1 已按授权建立安全 bootstrap，不能再把该历史事实当成当前状态。
- 阶段 0 未重新登录、重复测试远端或修改仓库；阶段 1 只使用既有 GCM 凭据推送批准的 bootstrap branch。
- 当前四套 SQLite 和 Viewer 可用；测试失败与七个任务异常状态按 `baseline.md` 原样保留。

## 1. 原百项计划的处置

| 原计划项 | 分类 | 新处置 |
|---|---|---|
| private 应用仓库、tracked allowlist、secret/path gate | 本阶段必须 | 阶段 1 |
| branch protection、CI、lockfile | 本阶段必须 | 阶段 1 |
| immutable release、`releases/current/runtime`、health、code rollback | 本阶段必须 | 阶段 2 |
| 四库日常 `ops-snapshot` 给本地开发使用 | 被 PostgreSQL 替代 | 不建设长期能力 |
| 通用 `research-change-set`、CAS、reverse change-set、冲突队列 | 被 PostgreSQL 替代 | 删除长期目标 |
| 四库一致 SQLite backup | 仅 SQLite 过渡期需要 | 用于冻结迁移基线和审计；PostgreSQL 有有效新写入后不再是默认回退点 |
| 用户内容 Git outbox/event/materializer/replay | 删除 | 默认不实施 |
| 用户内容 revision、soft delete、audit | 本阶段必须 | 阶段 3 试点或相应域迁移 |
| Opportunity/A/B staging、review、publisher、ledger | 本阶段必须 | 随域迁移保持 |
| SQLite migration ledger | 仅 SQLite 过渡期需要 | 用于确认源 schema；目标由 PostgreSQL migration history 接替 |
| 通用稳定 UUID 层 | 删除 | 不为 SQLite 双端 CAS 建设覆盖所有表的 UUID 系统 |
| 业务稳定身份与 legacy mapping | 本阶段必须 | 跨域、跨环境、可发布和需审计对象必须有稳定身份或明确映射，不强制统一 UUID |
| 任务 manifest、服务账户、运行锁、checkpoint、补漏 | 本阶段必须 | 阶段 5 |
| Viewer 身份、权限、CSRF、审计 | 后续强化，但生产写开放前必须 | 阶段 5 |
| PostgreSQL 只读副本、自动故障转移、容量自动扩缩 | 后续强化 | 基于实际恢复目标另立 change |
| GitHub 客户端加密灾备 | 后续强化/待合规 | 不作为 live 或唯一备份 |
| 广播包 | 仅过渡期需要 | 保留为冷备，完成空机恢复后再决定退出 |

## 阶段 0：架构审查与人工批准

**目标**：把长期目标从 SQLite 双端同步改为 GitHub + 中央 PostgreSQL，并让 baseline、proposal、design、tasks 和 specs 一致。  
**非目标**：任何实现或生产操作。  
**前置条件**：只读代码、schema、测试和任务审计。  
**回滚点**：文档 diff；不影响 live 系统。

- [x] [本阶段必须] 复核四库职责、写入者、SQLite 方言耦合和 Viewer 写接口。
- [x] [本阶段必须] 保留真实测试失败、任务状态和 `analyst_note=0` 等事实。
- [x] [本阶段必须] 重写 baseline、proposal、design、tasks 和 capability specs。
- [x] [本阶段必须] 修订直接冲突的迁移总说明和内容仓库定位。
- [x] [架构决策] 内容仓库标记为 `RESERVED-UNUSED`：保持空置、无生产凭据、不作为 live/backup authority；未来备份用途另行评估，不在本轮操作远端。
- [x] [本阶段必须] 完成本次不超过三轮的脱敏 DeepSeek 反驳审查并追加记录接受/拒绝。
- [x] [HALT] 用户已于 2026-08-03 21:12:55 +08:00 完成人工审查并批准阶段 0 退出。批准人：用户；批准范围仅为阶段 1 的安全 Git 接入、版本边界、测试基线、依赖锁和 CI；未批准 PostgreSQL、VM、数据库或任务实施；下一人工 HALT 位于阶段 1 结束。

**退出条件**：OpenSpec 严格校验通过；文档不存在长期四库同步、通用 SQLite CAS 或用户内容实时 Git 复制的相互矛盾；用户明确批准。

**建议结论**：第三轮合同校验通过后，可建议用户批准阶段 0 退出，但不得自行勾选上面的 HALT。该批准只开放阶段 1 的 allowlist、扫描、staged inventory、安全 Git bootstrap、测试修复、lockfile、CI 和受保护 main 准备，不授权任何 PostgreSQL production、生产数据访问层改造、数据库/runner 切换、VM production deploy、人工写接口或 production authority。

**禁止事项**：初始化/push Git、连接远端、安装 PostgreSQL、修改 live DB、迁移任务、部署 VM。

## 阶段 1：安全 Git bootstrap 与 CI

**目标**：先建立安全可审核的代码历史，再在 feature branch 修复基线。  
**非目标**：VM 生产部署、数据库迁移和任务切换。  
**前置条件**：阶段 0 人工批准。  
**回滚点**：尚未部署时停止 bootstrap；不改变生产数据和任务。

- [x] [本阶段必须] 生成 tracked allowlist、ignore policy 和 staged inventory；逐项排除 live DB、WAL/SHM、backup、broadcast、runtime、临时 cache、secrets、个人上下文和未批准大文件。
- [x] [本阶段必须] 明确 `AGENTS.md`、活动 OpenSpec、生产/审核 skills、正式 context、migration、测试和 SOP 的 tracked 边界；阶段 1 的 writer inventory 按可审计的 mutation path/write endpoint/writer operation/transaction contract 记录，不把整个进程等同于一个 writer，也不在本阶段构建 cutover unit registry。
- [x] [本阶段必须] 运行 secret/path/credential/Windows-path gate；首次 staged inventory 已保存审查摘要，完整本地报告保持在 Git 外。
- [x] [本阶段必须] 建立 bootstrap commit/branch；已知测试债务在首个 commit 中如实保留，随后在隔离 clone 中修复。
- [x] [本阶段必须] 在 Git 历史中修复 import-time stdout 副作用和仍活动的 V2 builder 契约失败；受控研究产物测试与 clean-clone core 明确分层。
- [x] [本阶段必须] 建立 Python 3.10 hash-pinned lockfile、标准测试入口、CI workflow 和两个 required-check 候选。
- [x] [本阶段必须] 已准备 main 的 CI、required-check 名称和治理边界，并明确 bootstrap branch、main merge 和 deployable commit 的不同门槛。
- [x] [人工 GitHub gate] 已在 bootstrap 修复提交两个远端 job 真实绿色后创建 `main`；GitHub API 回读确认默认分支为 `main`，required checks 为 `boundary-and-contracts`、`python-clean-environment`，strict update、PR review gate、管理员约束和 conversation resolution 已启用，force push 与 branch deletion 已禁止。该仓库仍只是 bootstrap/development source，不是 production authority，也不授权 VM deployment。
- [ ] [production gate] 应用仓库在成为 production authority 前，完成公司资产归属或经批准例外、第二位公司管理员/交接、强制 2FA、账号恢复、branch protection、最小权限和公司控制的 VM deploy credential。
- [x] [HALT] 用户已于 2026-08-04 05:31:09 +08:00 完成人工复核并批准阶段 1 退出。批准人：用户；批准范围仅为阶段 2 的 immutable release、本地 dev/test 边界、health/preflight、代码级 rollback 和不切换生产的 VM 只读并行候选；未批准 PostgreSQL production、live SQLite 修改、计划任务迁移、现有生产 Viewer 切换或 production authority；下一人工 HALT 位于阶段 2 结束。

**退出条件**：干净 clone 可恢复正式开发/审核规则；活动测试稳定通过；main 受保护；仓库历史不含禁止资产。仓库控制权 gate 可以不阻止安全 bootstrap，但未关闭前禁止 production deploy。

**禁止事项**：在 VM 活动目录直接 pull、部署 production、提交任何 live data。

## 阶段 2：可重复 release 与本地开发边界

**目标**：建立可重复应用交付和不依赖 VM 在线的本地开发流程。  
**非目标**：开启 VM 写接口、迁移任务或切换数据库。  
**前置条件**：阶段 1 通过。  
**回滚点**：继续使用当前 Viewer 启动与广播冷备；数据库不变。

- [x] [本阶段必须] 定义 deployment allowlist/manifest，区分 Git tracked closure 与运行所需 artifact closure。
- [x] [本阶段必须] 建立 immutable `releases/<sha>`、`current` 原子切换、`runtime`/secrets/data 外置和 deployment ledger。
- [x] [本阶段必须] 将 commit SHA、manifest hash、database schema version 暴露给 health/preflight 审计，但不得泄露凭据。
- [x] [本阶段必须] 验证 preflight、read-only smoke 和 code-only rollback；应用回滚不得改数据库或人工内容。
- [x] [本阶段必须] 定义 migration compatibility 声明，验证 code-only rollback 只在旧代码仍兼容当前 schema 时成立；forward-only migration 必须显式标记。
- [x] [本阶段必须] 修复候选进程生命周期：listener-owning PID 使用启动时间、解释器、命令行 hash、launch id、commit 和端口联合验证；重复部署及所有已识别失败路径执行身份核验后的清理，不使用裸 PID。
- [x] [本阶段必须] 将 VM evidence 从写死声明改为部署前/后实测，分开记录静态保证、生产 8080/current、计划任务定义、候选进程、只读合同、代表性 smoke 和仍未验证的内网客户端可达性。
- [x] [本阶段必须] 要求显式 Python 3.10 bootstrap 路径，在候选根按 lockfile 建立隔离环境；不得从 PATH 猜测解释器或修改现有生产任务环境。
- [x] [本阶段必须] 修复外置 content/state 路径并建立代表性读取闭包；schema compatibility 收窄并增强为对象、列、版本和只读探针门禁，完整 fingerprint 仅作诊断。
- [x] [本阶段必须] 依据生产事实区分外置内容的 required/optional 合同：`docs/industries` 与 `papers` 继续 fail-closed，`docs/themes` 作为数据库主题页的可选 Markdown 增强；缺失状态进入 preflight/evidence，并由数据库-only 主题路由 smoke 验证。
- [x] [本阶段必须] 关闭 immutable release bytecode 污染与同 SHA 重试缺口：所有项目 Python 子进程使用隔离导入并禁止 bytecode；build、preflight、activate、launch、smoke、stop/失败清理均复核 manifest；仅对非 current、非运行引用的失效 release 做整目录可审计 quarantine/rebuild，并保留逐次失败 evidence。
- [x] [本阶段必须] 修复 VM legacy health、候选进程与 evidence 生命周期兼容：8080 的 HTTP 可达性、可用身份字段和字段缺失分开记录并使用有界硬权威身份 quorum；listener PID 漂移保留为运行时 warning，不替代 release/app/manifest/current/broadcast 与 listener 存在性的硬门禁；pre/post/recovery 使用同一比较语义并拒绝候选 PID 出现在 8080。CIM/Get-Process 可选属性不再由 StrictMode 误判；stale record 只有在双进程源、端口和健康探针共同证明候选不存在时才归档收口；原始 gate state/comparison/reasons、主失败、cleanup/pointer recovery 和 post-cleanup/final-state 分区持久化，后续采样不得覆盖原 gate。
- [x] [本阶段必须] 建立本地 dev/test 数据库配置合同和最小 fixture；本地 Viewer、测试和浏览器验证不依赖 VM 在线。
- [x] [本阶段必须] 已在 VM 对验收基准 SHA `e2c324763f4b8ee5fd712623000126114d09c594` 完成只读并行候选部署：exact release、74 个锁定包、四库只读/schema probe、16 项代表性 smoke、403 mutation gate、immutable manifest、production 8080 authority、跨机器 LAN 18080 和最终 cleanup 均通过；POST/DELETE、自动任务和 migration 保持禁用。Scheduled Tasks 的全 VM aggregate definitions hash 自动门禁判为 tooling failure，按现场只读证据接受人工 waiver；该 waiver 不豁免任何真实安全条件。
- [x] [仅过渡期需要] 保留可验证广播包作为冷备，不继续把它发展成主发布通道。
- [x] [HALT] 用户已于 2026-08-07 17:12:24 +08:00 完成人工终验并批准阶段 2 以 `STAGE 2 PASS WITH HUMAN WAIVER` 退出。批准人：用户；waiver 仅针对无法区分 Windows 系统任务变化与项目任务变化的全 VM Scheduled Tasks aggregate hash；批准范围允许合并已验收 PR #3、完成独立 governance PR 后进入阶段 3，未授权 production PostgreSQL、live SQLite 修改/迁移、任务迁移、production Viewer/writer 切换或阶段 4。验收结束时 candidate PID 不存在、18080 已释放、candidate current 不存在、8080 正常。

**退出条件**：明确 commit 可重复部署；本地 dev/test 独立；VM 只读候选可回滚且不影响 live 系统。

## 阶段 3：依赖建模、数据访问层、PostgreSQL dev/test 与切换单元试点

**目标**：在不碰 production 的前提下先弄清真实事务边界，建立 PostgreSQL migration 和一个可验证的低风险切换单元试点。  
**非目标**：四域生产迁移、长期双方言或通用同步器。  
**前置条件**：阶段 2 通过；用户决定 PostgreSQL 试验环境。  
**回滚点**：销毁 dev/test 试点，live SQLite 不变。

- [x] [本阶段必须] 建立机器可读 SQLite dependency inventory，至少记录文件路径、所属数据域、读/写属性、SQLite 专属语义、`ATTACH` 依赖、关联页面/API/任务/publisher、候选切换单元、权威后端和迁移状态；持续更新而不是只生成一次统计数字。
- [x] [本阶段必须] 产出并人工审查数据域依赖图、read/write 路径清单、跨域事务图、`ATTACH` 替代边界、共享身份依赖，以及必须共同成功的业务操作。
- [x] [本阶段必须] 建立版本化 cutover unit registry 和 authoritative-backend matrix：每个可写对象、writer 和完整事务边界只能有一个 owning unit，其他 unit 只能声明 dependency；登记每个 unit 的包含/依赖对象、S0—S4 状态、责任人和边界变更历史，执行 ownership 重叠/冲突检查。共享身份是否单独成基础 unit 由依赖与事务审计决定，迁移脚本不得自动漂移边界。
- [x] [本阶段必须] 明确不得把一次业务事务拆到 SQLite/PostgreSQL 分别提交；无法安全拆分的 reader、writer、任务、页面和 publisher 必须共同切换或先重构边界。
- [x] [本阶段必须] 设计统一连接、事务、repository/writer 和 migration 边界；业务代码不再新增直接 SQLite 文件依赖。
- [x] [本阶段必须] 建立 PostgreSQL dev/test 和可重复 migration/fixture 流程；测试直接使用 PostgreSQL 语义。
- [x] [本阶段必须] 定义主要 database 的逻辑域、共享身份、role/writer 权限和审计边界；物理拆库必须有证据。
- [x] [本阶段必须] 定义稳定业务身份与 legacy mapping 合同；保存 SQLite database/table/id 到稳定身份和 PostgreSQL 目标对象的可验证映射，允许内部 surrogate key，不强制全局 UUID。
- [x] [本阶段必须] 建立 expand–migrate/backfill–application transition–contract migration 合同；破坏性 contract 必须放在后续独立批准 release，每个 migration 说明 compatibility、backup、verification 和 recovery strategy。
- [x] [本阶段必须] 用户已于 2026-08-11 14:25:45 +08:00 批准 `target_rpo_rto_proposal.v2`：migration/cutover authority control 与五类业务/资料恢复目标正式成为后续设计门槛；这是 target 批准，不代表 measured SLA 已达到，也不授权 production 数据切换。
- [x] [本阶段必须] 选择一个低风险切换单元试点。选择需比较数据量、共享身份、写复杂度、已有 ledger、对账和恢复；不得未经审计固定顺序。
- [x] [本阶段必须] 为试点验证计数、主外键、业务不变量、revision/audit、性能和恢复；publisher/user-content 更新必须测试稳定 release id、幂等重试、expected/base revision、stale conflict、禁止 silent last-write-wins 和依赖簇原子性。
- [x] [本阶段必须] 明确用户内容受控导出格式以满足可移植性，但不建立实时 Git 复制。
- [x] [HALT] 用户已于 2026-08-11 14:25:45 +08:00 完成人工审查并批准阶段 3 退出。批准依据包括 final live drift PASS、两层 inventory/aggregate manifest、PostgreSQL dev/test pilot、最终 evidence identity `2b58252a84161996e3b9c81cf2e1cfe5f28bd30865be85d6d15acac14b5511c6`，以及 PR #5 head `736d7d3e4c535dff9dc465256dedd1deb2db7716` 的 push/PR required CI 全绿；未授权任何阶段 4 production 操作，下一人工 HALT 位于阶段 4 授权前。

**退出条件**：inventory、依赖/事务图、cutover unit registry、唯一 ownership/dependency、重叠检查、权威后端、稳定身份和 migration compatibility 均通过人工审查；target RPO/RTO 已批准；试点在 dev/test 完整通过；没有 live 变更；证明数据访问层不是简单 SQL 字符串替换。

## 阶段 4：按切换单元迁移 PostgreSQL 与生产后端切换

**目标**：按完整业务事务边界将唯一生产事实源切换到 PostgreSQL，并显式记录 S0–S4 状态。  
**非目标**：一次性迁移全部四库、无期限双写或四个 PostgreSQL database 的机械复制。  
**前置条件**：阶段 3 通过；target RPO/RTO、生产拓扑、备份位置和维护窗口获批。  
**回滚/恢复边界**：S1 可放弃试点；S2 是短时切换栅栏，只有 PostgreSQL writer 已停写且水位、审计和人工批准共同证明尚无必须保留的新写入，才可恢复 SQLite writer；无法证明时按 S3。S3/S4 的旧 SQLite 仅作迁移基线、审计和有限修复材料，不是无损 production rollback target。

- [x] [本阶段必须] 按共享身份、事务依赖、写入复杂度、数据量、停机容忍和现有 ledger 确定切换单元顺序；`sentiment` 默认靠后但以 inventory 审计为准。2026-08-11 已形成 `stage4_cutover_sequence.v1`，首单元为 `user_content_notes`；该完成项只冻结顺序，不授权生产切换。
- [x] [Stage 4 readiness 准备] `user_content_notes` identity mapping 已改为一个显式 query-only SQLite transaction 内的一致快照；snapshot identity 来自事务内 schema/content watermarks，数据库文件哈希仅作诊断。已生成 774 条 mapping 的 Git 外审批包和 Git 内脱敏摘要；最终 cutover-level mapping approval 仍由用户决定。
- [x] [Stage 4 readiness 准备] readiness preflight 已改为读取 typed evidence 本体并校验 hash、subject、时效、交叉引用、S0 route、应用 rehearsal、PostgreSQL topology/TLS/ACL/credential、backup/WAL/restore、repository governance 和 cutover decision；伪 boolean/hash、篡改、跨环境、过期及同主机冒充 off-VM 均 fail-closed。
- [x] [Stage 4 readiness 准备] 浏览器 uncertain mutation identity 已跨 reload/tab 持久化并绑定可信 principal/payload；跨 tab 原生互斥、长 pending、精确 replay、principal/payload 变化 fail-closed 已有执行测试。没有重构数据库既有 idempotency、revision 或 authority 合同。
- [x] [Stage 4 readiness 准备] 本机隔离 PostgreSQL 17.10 候选已真实完成 TLS、角色 ACL、Credential Manager 创建/轮换/撤销、服务启停/crash recovery、base backup+WAL、整库恢复、逻辑旁路恢复和 authority-control migration/adapter/side restore；候选不使用 production 端口，live SQLite 前后不变。该证据明确不是 VM 或 off-VM 证据。
- [ ] [Stage 4 readiness blocker] `honghu-vm` SSH 通道已于 2026-08-12 验证并用于 exact-package 执行，不再是 blocker；但 Windows OpenSSH 非交互登录实测无法访问调用用户的 Windows Credential Manager（WinError 1312，`cmdkey` 同样失败），因此正式凭据注入需要在 VM 交互桌面运行同一 exact bootstrap。另一故障域 off-VM copy/restore 仍无现场证据，不得用同 VM 盘符替代。两项均不得用布尔声明或伪 hash 关闭。
- [ ] [本阶段必须] 每个切换单元进入 S2 前先完成该 unit 所需的 VM 外 backup、migration rehearsal、增量追平、权限和按 target RPO/RTO 设计的真实恢复路径验证，并冻结 owning unit、dependency、权威后端、唯一 writer/reader/runner 清单；不得机械推迟到阶段 5，阶段 5 只做整体任务迁移、空机恢复和 measured RPO/RTO 收口。
- [ ] [本阶段必须] 每个切换单元执行源目标计数、关系、时间序列、状态机、稳定身份映射和业务不变量对账；验证相关页面、API、publisher 和写路径。
- [ ] [本阶段必须] 在短维护窗口切换唯一 writer；优先 shadow read。进入 S2 时 PostgreSQL 是唯一指定 writer、SQLite writer 已停止并冻结；记录 cutover epoch、SQLite 最终权威业务水位、PostgreSQL 首条正式业务 commit 水位、验证写、uncertain response、操作者和证据。首条必须保留的正式写提交即进入 S3，无法证明未提交的 uncertain response 按 S3。任何连接失败不得静默回写 SQLite；未经独立批准不得 shadow write。
- [ ] [本阶段必须] 保留研究 staging/reviewer/publisher、financial revision/reconciliation、用户内容 revision/audit 和任务 ledger；验证 publication/release identity、幂等 retry、expected revision、stale conflict 和依赖簇事务原子性。
- [ ] [本阶段必须] 分别记录数据后端和任务执行节点。允许本地唯一 runner 在受限权限下暂连 production PostgreSQL，但必须登记任务、临时 owner、开始时间、唯一 runner、数据库角色/权限、网络/凭据、checkpoint、暂留原因、退出条件、下一 HALT、VM 前置和逾期升级方式；本地断线不得触发 SQLite 回退。若不采用，该 runner 与切换单元同窗切换。任何状态均不得双 runner。
- [ ] [仅 SQLite 过渡期需要] 生成切换单元对应的一致 SQLite 基线和 migration manifest；禁止作为日常开发同步源，并在 S3 后标明“不可直接恢复生产 writer”。
- [ ] [本阶段必须] 演练 S1 放弃、S2 在停写与水位证明下的回退、S2 uncertain response 按 S3 收口，以及 S3 后 PostgreSQL 前向修复/兼容代码回滚/旁路恢复选择性修复；不得用同一“rollback”标签混淆这些动作。
- [ ] [本阶段必须] 对单域逻辑错误将备份恢复到旁路环境，选择性提取并审计修复；禁止为单域错误原地回退整个 production database。
- [ ] [本阶段必须] 稳定观察期后把旧 SQLite 标记为迁移基线与审计档案；删除应用写入口，不立即删除文件。
- [ ] [HALT] 每完成一个切换单元即提交对账、性能、身份映射、并发、故障与恢复证据，等待下一个单元批准。

**退出条件**：该切换单元 PostgreSQL 是唯一 writer；权威后端和唯一 runner 明确；旧 SQLite 角色与当前状态一致；备份可恢复；无未解释数据差异或并发覆盖。

## 阶段 5：任务迁移、生产安全与恢复强化

**目标**：将对应任务安全迁至 VM，并完成用户写入、监控、备份和空机恢复的生产门槛。  
**非目标**：一次切七个任务或过早建设高可用集群。  
**前置条件**：相关切换单元的数据后端已切换且稳定；对应任务的生产数据库权限和 runner 状态获批。  
**回滚点**：逐任务停 VM、恢复原 runner；保持唯一 writer、唯一 runner 和 checkpoint 连续，任务主机回滚不得改变数据后端权威。

- [ ] [本阶段必须] 统一七个任务 manifest、服务账户、固定环境、单实例锁、checkpoint/ledger、失败分类和数据新鲜度。
- [ ] [本阶段必须] 为 VM 正常/异常关机定义自动启动顺序、漏窗识别、可补抓范围、不可补缺口记录和追平状态。
- [ ] [本阶段必须] 按“VM disabled 安装→人工真实试跑→停本地→启 VM→观察→本地保持 disabled”逐任务切换。
- [ ] [本阶段必须] 对采用“本地 runner 先连接 production PostgreSQL”的中间状态复核阶段 4 登记项和退出条件；VM 启用前证明本地已停止，切换完成后撤销不再需要的本地 production 写角色、凭据和网络访问。长期不能退出时必须在人工 HALT 升级处置，不得默认为长期架构。
- [ ] [本阶段必须] 修复当前失败/未正常完成任务，不能把迁移当成掩盖历史失败的方法。
- [ ] [本阶段必须] 在开放人工写接口前完成身份、最小权限、CSRF、revision、soft delete 和 audit。
- [ ] [本阶段必须] 复核生产控制是否符合阶段 3 已批准的 target RPO/RTO；若目标变化，返回对应设计 gate 重新批准，不在阶段 5 静默改写目标。
- [ ] [本阶段必须] 建立 VM 外备份并完成整库灾难恢复、旁路单域逻辑恢复和空机真实 restore test；记录实际可恢复时间点、恢复耗时、未恢复数据、补抓耗时和选择性修复耗时，形成 measured RPO/RTO 并与目标逐类对账。
- [ ] [本阶段必须] 建立 Viewer、database、task、artifact 和 backup 健康/告警；区分进程存活和数据新鲜。
- [ ] [后续强化] 基于实际恢复目标评估 PostgreSQL 物理分离、只读副本、连续归档和自动故障转移，另立 change 后实施。
- [ ] [后续强化] 经合规批准后，评估客户端加密的低频 GitHub Release 灾备；不得替代内部备份。
- [ ] [HALT] 提交任务观察、权限审计、restore test、空机恢复和最终生产迁移验收报告，等待人工验收。

**退出条件**：任务不双跑；临时本地 production 写权限已按合同撤销；停机后可识别并处理缺口；用户内容可审计；VM 整体损坏可恢复；measured RPO/RTO 达到 target；生产运行证据完整。

## 全程禁止事项

- 不把 live PostgreSQL dump、SQLite、WAL/SHM 或用户内容提交应用 Git。
- 不通过拆小请求、临时脚本或未审计同步器绕过阶段门槛。
- 不让本地和 VM 同一生产任务同时启用。
- 不在没有唯一 writer、唯一 runner、切换状态和恢复证据时切换数据。
- 不把 PostgreSQL 已产生有效新写入后的旧 SQLite 称为无损回滚点。
- 不让应用在 PostgreSQL 失败时静默自动回退 SQLite。
- 不把一个业务事务拆到 SQLite/PostgreSQL 分别提交后声称原子完成。
- 不把备份文件存在、任务进程启动或页面能打开等同于迁移成功。
- 不在任何 HALT 点自动继续。
