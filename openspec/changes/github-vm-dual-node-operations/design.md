# 泓湖 AI 研究系统 GitHub—PostgreSQL—VM 运营迁移设计

## 1. 设计状态与边界

本设计替代原先“VM 长期持有四套 SQLite，本地用快照和 change-set 合并”的目标架构。它仍处于人工审查阶段，只描述目标、边界、阶段和验收，不授权实施。

本轮不做：Git 初始化或远端操作、PostgreSQL 安装、live schema/data 修改、任务迁移、VM 部署、生产配置变更、资料上传或备份清理。

## 2. 审计事实与问题定义

### 2.1 系统已经有多个写入者

当前写入不仅来自 Viewer，还来自研究 ingest、Opportunity Lens 发布、财务模型、动态调度、情绪窗口和人工内容。VM 偶尔关机不会让 PostgreSQL 失去价值；真正需要解决的是：

- 哪个系统保存最新结构化事实；
- 多个进程如何共享身份和事务；
- schema 如何受控演进；
- 停机窗口如何补漏；
- 用户内容如何保留 revision 和 audit；
- 本地开发如何不依赖生产 VM 在线。

### 2.2 SQLite 文件限制正在驱动过度工程

原方案中的四库 maintenance lock、一致快照、稳定业务键、前后值 hash、通用 change-set、CAS、reverse change-set、冲突队列、内容 Git outbox 和空库回放分别合理，但组合后是在自建离线复制和事件溯源系统。除研究发布、revision、运行 checkpoint 等确有业务意义的机制外，不应为长期合并两套 SQLite 分叉继续建设。

### 2.3 PostgreSQL 的价值不是数据库体量

本项目选择 PostgreSQL 的依据是中央事务、共享最新数据、角色权限、schema migration、跨域查询、revision/audit、标准备份和未来节点扩展，不是因为百万级记录本身超过 SQLite 容量。

## 3. 架构决策

### 决策 A：长期目标是 GitHub + 中央 PostgreSQL + 独立 artifact 存储

```text
本地开发/研究工作站
  ├─ Git clone / branch / test / push
  ├─ 本地 Viewer
  └─ 独立 dev/test PostgreSQL
             │
             ├──────── private GitHub application repository
             │          code/config template/migration/test/rules/SOP
             │
VM production
  ├─ immutable application release by commit SHA
  ├─ Viewer
  └─ scheduled/continuous jobs
             │
             └──────── central production PostgreSQL
                         structured live data / revision / audit / operations

内部文件或对象存储
  └─ papers / evidence / approved large artifacts / manifests

VM 外备份位置
  └─ PostgreSQL backup + restore-tested recovery material
```

四个组件职责不得混写：

| 组件 | 管理内容 | 明确不管理 |
|---|---|---|
| GitHub 应用仓库 | 代码、配置模板、migration、测试、部署/恢复脚本、正式项目规则 | live rows、数据库文件、凭据、个人 scratch、未批准资料 |
| PostgreSQL | live 结构化数据、共享身份、revision、audit、运行状态、发布 ledger | PDF 原件、浏览器 profile、Git 历史 |
| 内部文件/对象存储 | papers、evidence、大文件、内容哈希与生命周期 | 应用事务和 live row 合并 |
| 本地 dev/test | 本地开发、页面验证、回归、迁移演练 | 未经授权写 production |

### 决策 B：一个主要 database，逻辑分域优先

目标形态优先是一个 PostgreSQL instance、一个主要业务 database。逻辑 schema 可围绕下列职责划分，但名称不是实现合同：

- 共享主体与证券/行业身份；
- A/B 研究与动态内容；
- 情绪与市场窗口；
- Opportunity Lens；
- 财务、市场和模型；
- 人工用户内容；
- 任务运行与操作状态；
- 审计和发布记录。

共享 company/security/industry 身份应只有一个权威定义，其他域通过受控关系引用。访问权限按 schema、角色和 writer 分配，避免任何任务账户拥有全库任意写权限。

只有出现以下证据时才考虑物理拆 database/server：

- 明确且持续的容量或 I/O 隔离需求；
- 法规或权限要求不能用 schema/role 满足；
- 独立故障域或扩容生命周期；
- 可接受跨库查询、身份同步和事务成本。

不得因为当前有四个 SQLite 文件就机械建立四个 PostgreSQL database。

### 决策 C：SQLite 是迁移状态，回退能力取决于切换后的写入状态

迁移不按“四个 SQLite 文件逐个导入”理解，而按具备完整事务和业务语义的 `cutover unit`（切换单元）推进。一个切换单元可以包含多个表、一个 writer、相关 reader、任务、页面、publisher 和共享身份依赖；它不必等于一个文件、一个 schema 或一张表。

切换单元必须具有唯一 ownership：每个可写对象、生产 writer 和不可拆分的完整事务边界恰好由一个 owning cutover unit 管理，其他单元只能声明 dependency，不能重复声明 ownership。共享 company/security/industry 身份可以形成独立基础单元，也可以依据依赖与事务审计纳入一个更大的共同单元，但不得由多个单元分别声称拥有同一写对象或事务边界。同一对象不得同时处于两个冲突的 S0—S4 状态。

这里的 `writer` 是可审计的 domain mutation path、write endpoint、writer operation 或 transaction contract，不等同于整个 Python 进程、Viewer 应用或任务进程。必须分别记录 process/runner、database role、writer operation、transaction boundary 与 owning cutover unit；同一进程可以包含属于不同切换单元的多条写路径，不能仅因共用进程就被迫合并为一个过大的切换单元。阶段 1 只建立 operation 级静态基线，正式 cutover unit registry 仍留在阶段 3 经依赖与事务审计后建立。

阶段 3 必须建立版本化的 cutover unit registry，记录 owning unit、包含对象、依赖对象、reader/writer/runner、当前状态、责任人和边界变更历史，并执行 ownership 重叠与冲突检查。authoritative-backend matrix 必须能唯一回答“某个对象当前由哪个 unit、哪个后端、哪个 writer 管理”。切换单元边界的增删或合并必须经过人工复核，迁移脚本不得自行漂移边界。

每个切换单元必须显式处于下列状态之一：

| 状态 | 权威 writer | SQLite 的角色 | 可用恢复动作 |
|---|---|---|---|
| S0：尚未迁移 | SQLite | live 事实源 | 继续现有生产路径 |
| S1：PostgreSQL 已准备/影子读取 | SQLite | 唯一 live 事实源 | 放弃 PostgreSQL 试点，不影响生产 |
| S2：PostgreSQL writer 已启用，但经审计确认尚无必须保留的新写入 | PostgreSQL | 冻结的切换基线 | 在关闭 PostgreSQL writer并核验无新写入后，才可能直接恢复 SQLite writer |
| S3：PostgreSQL 已产生必须保留的新写入 | PostgreSQL | 迁移基线、审计档案和有限数据修复材料 | 以前向修复、保持 PostgreSQL 数据的兼容代码回滚、旁路恢复后选择性修复，或另行批准的显式反向迁移处理 |
| S4：PostgreSQL 稳定运行 | PostgreSQL | 按批准的保留策略归档 | 使用 PostgreSQL 备份、恢复和发布审计体系 |

S3 以后，“旧文件仍在”不等于可以无损回滚。此时不得直接把生产 writer 指回旧 SQLite；确需反向迁移时，必须把 PostgreSQL 切换后的有效写入完整纳入对账和迁移计划，并单独批准。旧 SQLite 主要用于证明迁移基线、追溯旧口径和提取有限修复材料。

S2 不是普通生产运行状态，而是短时间、受控的切换栅栏。S2 只有一个已指定的生产 writer 后端：PostgreSQL；SQLite writer 已停止，文件保持冻结。这里“PostgreSQL writer 已启用”表示路由、角色和连接已经能够接受写入，但普通生产业务仍被栅栏阻断，只允许通过 PostgreSQL 执行、具有独立身份、可与业务数据区分且不产生正式业务效果的验证写。每次进入 S2 必须记录：cutover epoch 或等价切换标识、SQLite 最后一条权威业务水位、PostgreSQL 第一条正式业务 commit 水位、writer 路由状态、验证写清单、uncertain response 以及操作者、时间和证据。

第一条必须保留的正式业务写入一经提交，该 unit 立即进入 S3。若数据库可能已经提交、但调用方没有收到成功响应，必须按稳定业务身份、幂等键或 ledger 查询提交结果；在不能证明“未提交”前，保守按 S3 处理。S2 不得持续成为数小时或数日的日常状态；直接恢复 SQLite writer 只有在 PostgreSQL writer 已停写、源末水位与目标审计共同证明没有必须保留的新写入，并经人工批准时才成立。S2→S3 及任何回退都必须写入审计 ledger，不得靠口头判断。

不建立长期双写。默认路径是一次迁移、增量追平、短维护窗口切换和 shadow read 对账。若试点确需短期 shadow write，必须单独证明必要性、定义幂等和失败一致性、限定到期日，并确保它不成为两个可独立接受生产写入的事实源。

### 决策 C.1：混合迁移期使用显式权威后端，不使用静默回退

阶段 3 必须先形成数据域依赖图、读写路径清单、跨域事务图、`ATTACH` 依赖、页面/API/任务/publisher 依赖、cutover unit registry 和 ownership/dependency 关系。对每个切换单元持续维护权威后端矩阵，至少说明其 owning objects、dependencies、reader、writer、runner、状态、稳定身份映射和迁移责任，并自动发现 ownership 重叠但不自动修改单元边界。

- 任一时刻每个切换单元只有一个权威 writer；
- PostgreSQL 连接或事务失败时，应用不得静默改写 SQLite；
- shadow read 只用于对账，不产生第二个权威结果；
- 一个必须共同成功的业务操作不得拆到 SQLite 和 PostgreSQL 分别提交后再假定原子性；
- 共享身份、跨域 publisher 或任务若无法在单一事务边界内安全运行，必须纳入同一切换单元，或在切换前重构为有明确失败语义的业务流程。

### 决策 D：不把用户内容 Git 仓库作为实时数据库

comment、投资观点、信心等级、交易假说和研究 request 可能比公开 PDF 更敏感。中央 PostgreSQL 已能提供事务、revision、soft delete、audit 和标准备份，因此每次编辑再写 Git 会增加：

- 两个事实源；
- outbox 与 push/rebase 失败状态；
- 文本合并和权限冲突；
- 敏感内容上云审批面；
- replay/materializer 的长期维护。

默认设计是 PostgreSQL 记录当前值和不可变修订，审计记录主体、操作、时间和必要上下文；删除采用 soft delete；备份与恢复纳入数据库体系。需要可移植性时，提供受控、可校验的导出，不要求每次编辑 push。

已创建且实际 slug 以 `-` 开头的内容仓库明确标记为 **`RESERVED-UNUSED`**：保持空置，不配置生产凭据，不承载 live 内容、数据库备份或发布权威，也不进入部署依赖。未来如需 GitHub 加密灾备，应重新评估职责明确的独立 backup repository，不默认复用该仓库。本轮不对远端做删除、重命名或 archive 操作。

### 决策 E：研究发布治理保留

以下机制在 PostgreSQL 下仍然必要，因为它们表达业务语义，而不是 SQLite 限制：

- draft/staging 与 published 分离；
- producer-reviewer loop；
- 证据、计算、财务、写作、浏览器和 final review；
- artifact/input/output hash；
- publication ledger；
- 唯一 publication/release identity、受控 publisher 和幂等提交；
- 更新既有对象时的 expected revision、base version 或等价并发条件；
- stale update 冲突检测，明确禁止静默 last-write-wins；
- 一个业务依赖簇的事务原子性；
- retry、重放和部分失败后的恢复语义；
- revision 与历史版本。

Opportunity Lens 现有 staging/reviewer/publication 结构应作为迁移合同之一。A/B 和财务域也应保留各自规范 writer，不允许改成任意 SQL 上传接口。

这些条件是研究发布本身的领域治理，不是恢复已删除的通用 SQLite change-set/CAS。人工 comment、thesis、hypothesis 等更新同样需要稳定对象身份、expected revision 或等价冲突条件以及 revision/audit，不能因为 PostgreSQL 提供事务就继续静默覆盖旧版本。

## 4. 目标数据权威与写权限

### 4.1 生产权威

迁移完成后：

- PostgreSQL 是所有 live 结构化数据的唯一生产事实源；
- Git commit 决定运行代码和 migration 版本，不决定数据库行的当前值；
- papers/evidence 的原件由批准的文件系统或对象存储权威保存，数据库只保存身份、元数据、哈希和定位；
- audit 和 backup 可以重建或追溯数据，但不与主表竞争“当前值”。

### 4.2 写入角色

实施时应按职责建立最小权限角色，而不是共享一个全能连接：

- Viewer read-only；
- Viewer user-content writer；
- research ingest/publisher；
- Opportunity staging/publisher；
- financial writer；
- dynamic/sentiment job writers；
- migration operator；
- backup/monitoring。

具体角色名和表级授权由实施阶段代码审计决定。关键原则是：读取页面不获得发布权限，抓取任务不获得用户内容写权限，应用运行账户不自动获得 schema migration 权限。

### 4.3 稳定身份与旧 ID 映射

删除面向 SQLite 双端合并的“通用 UUID 层”，不等于业务对象可以只依赖某个 SQLite 文件里的自增整数。下列跨域、跨环境、可发布或需审计的对象必须有稳定、可验证的业务身份或明确映射合同：

- company、security、industry；
- research publication object；
- Opportunity Lens run、entity、source；
- financial security、model、revision；
- user-content object、revision；
- papers、evidence、artifact；
- migration source-to-target mapping；
- task、window、checkpoint。

实现可以继续使用数据库内部 surrogate key，也不要求所有对象一律改成 UUID；但必须保存 `legacy database/table/id → 稳定身份 → PostgreSQL 目标对象` 的可复核映射，避免跨环境引用依赖单个 SQLite 自增 ID。身份策略属于切换单元验收内容。

## 5. 开发、测试与生产工作流

### 5.1 本地开发必须独立可用

迁移后仍支持完整本地流程：

```text
pull → local branch → local migration/test data → local Viewer/browser
     → tests/review → commit/push → CI → reviewed merge
     → VM deploy explicit commit
```

本地默认连接独立 dev/test PostgreSQL。测试数据可来自最小 fixture、脱敏样本或经批准的 production backup 恢复副本。VM 关机或 production PostgreSQL 不可达时，本地仍应能开发和验证页面。

本地访问 production 只允许明确的 read-only 角色和网络边界；本地开发脚本不得自动回退到 production writer。

### 5.2 环境分离

| 环境 | 数据目的 | 允许操作 |
|---|---|---|
| local dev | 快速开发和页面查看 | 可重置、可用小型 fixture |
| test/CI | 自动测试和 migration 验证 | 临时、隔离、可重复创建 |
| migration rehearsal | 用生产备份副本演练计数、性能和回滚 | 只在批准的数据环境执行 |
| production | Viewer、任务和真实用户内容 | 最小权限、受控 migration、完整审计 |

不能用 SQLite dev 通过、PostgreSQL prod 执行的长期“双方言最低公分母”替代真实 PostgreSQL 测试。SQLite 只在迁移兼容测试中保留。

## 6. Git 与 release 设计

### 6.1 安全初始 Git 历史的门槛

建立 bootstrap commit 只要求：

- tracked allowlist 和 ignore policy；
- secret/path/credential 扫描；
- live DB、WAL/SHM、backup、broadcast、runtime、个人上下文、临时 cache 和未批准大文件被排除；
- 首次 staged inventory 由人工审查；
- private repository 和访问权限确认。

已知测试失败可以在 bootstrap branch 中如实记录并修复。它们不应迫使修复过程继续发生在无版本历史的目录里。

当前应用仓库属于个人账号 `Garthzzz`。这不阻止经人工批准后的安全 bootstrap 和开发分支使用，但该仓库在完成公司控制权治理前不具备 production authority。生产部署 gate 至少要求：公司资产归属或经批准的临时例外、第二位公司管理员或可执行交接机制、强制 2FA、账号恢复方案、branch protection、最小权限，以及由公司控制的 VM deploy credential。个人账号可用性不得成为生产代码供应链的唯一恢复条件。

### 6.2 受保护 main 与生产部署是更高门槛

合入受保护 main 前，标准测试入口和活动路径 required checks 必须通过；仍维护的 legacy 路径必须修复或明确拆出，不得静默忽略。

生产 VM 部署还需：

- 可重建 Python 环境和 lockfile；
- deployment allowlist/manifest；
- 明确 full commit SHA；
- immutable `releases/<sha>`；
- `current` 原子切换；
- `runtime`、secrets 和数据独立；
- preflight、health 和只读 smoke；
- code-only rollback 和 deployment ledger。

应用 rollback 不回滚数据库或用户内容。`current` 切回旧应用只有在数据库 schema 仍与旧代码兼容时才成立；不得默认所有数据库错误都能通过应用版本回滚解决。

PostgreSQL schema 演进采用 expand–migrate–transition–contract：

1. **expand**：先增加向后兼容的结构；
2. **migrate/backfill**：迁移历史数据并验证计数、关系和业务不变量；
3. **application transition**：在明确兼容窗口内切换 reader/writer，并允许新旧代码按合同运行；
4. **contract**：在后续独立批准的 release 中删除旧结构或收紧约束。

破坏性 migration 不得与依赖它的新代码组成一次不可逆发布。每个 migration 必须声明兼容范围、是否 forward-only、备份、验证和恢复策略；code-only rollback 只能在兼容声明仍成立时使用。

## 7. 任务运行、VM 停机与补漏

VM 偶尔正常或异常关机是预期运行条件。设计不要求停机期间仍抓取，但要求恢复后知道漏了什么。

迁移必须把两条轴分开记录：

```text
数据存储轴：SQLite → PostgreSQL
执行节点轴：本地 Task Scheduler → VM Task Scheduler
```

文档中的切换术语必须带对象：`application release switch` 只指 `current` 的代码版本切换；`data-backend cutover` 只指某个 cutover unit 的权威后端与 writer 切换；`runner-host cutover` 只指任务唯一执行主机切换；`final production migration acceptance` 才指全部获批范围的最终验收。不得用无主语的“生产切换”混淆这四件事。

数据库后端切换决定数据权威，任务主机切换只决定唯一 runner 在哪里运行，不应再次改变数据权威。允许存在“任务仍由本地唯一 runner 执行，但已经连接 production PostgreSQL”的受控中间状态；它不是长期目标。每个此类状态必须记录任务身份、临时 owner、开始时间、当前唯一 runner、production 数据库角色与权限、网络和凭据管理方式、checkpoint 水位、暂不能迁到 VM 的原因、退出条件、下一个人工 HALT 点、迁到 VM 的前置事项，以及长期未满足退出条件时的升级处置。

若采用该中间状态，本地任务只能获得该任务所需的受限生产角色、受控网络访问和连续 checkpoint，且 VM 对应任务保持 disabled；本地断线或数据库不可达只能令任务失败或等待，不得触发 SQLite 回退。VM runner 启用前必须证明本地 runner 已停止；切换完成后应撤销不再需要的本地 production 写角色、凭据和网络访问。若不采用，则该任务 runner 必须与其切换单元在同一维护窗口共同切换，不能让已迁移的数据域失去持续 writer。

每个任务需要统一 manifest，至少定义：

- 任务身份、owner domain 和启停状态；
- 计划窗口、时区、工作日/周末政策；
- checkpoint 或 last successful window；
- 幂等键和单实例锁；
- 可补抓范围、最大回看范围和不可补来源；
- 失败分类、重试边界和运行审计；
- 数据新鲜度目标。

开机恢复流程应先启动 PostgreSQL，再启动 Viewer 和任务 runner；runner 根据 ledger 识别漏窗，按任务规则补跑，不把“任务进程已启动”误报为“数据已经追平”。

对不可补抓来源，系统应记录缺口和影响，不伪造完整。任何任务切换都必须先在 VM disabled 安装和手工真实试跑，再停本地、确认 checkpoint、启 VM，并验证不会双跑。任务主机切换失败时只恢复唯一 runner；不得因此把 S3/S4 数据权威改回旧 SQLite。权威后端、唯一 runner 和最后成功窗口必须分别审计。

## 8. 备份、恢复与 GitHub 的定位

### 8.1 生产备份

生产 PostgreSQL 需要：

- 与 VM 故障域分离的备份副本；
- 与 schema/migration 版本关联的恢复材料；
- 加密、访问控制和保留策略；
- 定期真实 restore test，而不是只验证备份文件存在；
- VM 整体损坏后的空机恢复路径。

具体采用逻辑备份、物理备份、连续归档或组合，由部署拓扑、恢复目标和基础设施能力在实施阶段决定，不在本设计写死。

### 8.2 Target RPO/RTO 是切换前输入，Measured RPO/RTO 是最终验收证据

本设计不预设精确分钟，但 production topology 和备份方案批准前必须按数据类别确定可接受数据丢失和恢复时间等级：

| 数据类别 | 丢失容忍原则 | 恢复优先级与可恢复性 |
|---|---|---|
| comment、thesis、hypothesis 等人工内容 | 几乎不可接受已确认修订丢失 | 高；依赖 revision/audit 与数据库备份，通常不可补抓 |
| 正式研究结果、review 与 publication ledger | 几乎不可接受已发布状态或审计链丢失 | 高；需恢复发布一致性和幂等身份 |
| 共享身份、migration mapping、task/checkpoint | 极低容忍 | 高；丢失会阻断跨域引用或造成重复/漏抓 |
| 财务观测、模型、研究结构化数据 | 低容忍，必须保留 as-of 和 revision | 中高；部分可重取，但重建成本和口径风险高 |
| 动态新闻、KOL、公告、情绪窗口 | 按来源和窗口区分 | 不可补抓来源和已删除 raw 对应的永久聚合优先；可补抓部分允许重建 |
| papers/evidence 元数据及原件 | 低容忍 | 原链接可能消失，原件和哈希需独立保护 |
| 可重复生成的派生 cache | 可接受重建 | 低；以依赖闭包和重建时间决定 |

阶段 3 结束或阶段 4 开始前，必须按上述类别批准 **target RPO/RTO**：可接受的数据损失、可接受的恢复时间、哪些数据可补抓、哪些不可补抓，以及哪些目标会触发连续归档/PITR、更高频备份、独立主机、额外副本或更短恢复路径。没有获批 target RPO/RTO，不得执行 production 数据切换。

每个 cutover unit 必须声明它包含或依赖哪些数据类别，并逐类满足对应 target RPO/RTO；不能用该 unit 中较宽松的数据类别覆盖较严格类别，也不能把当前 SQLite `backup/latest` 计作未来 PostgreSQL 目标已经满足的证据。

阶段 4 必须按目标为每个切换单元设计并演练备份、切换和恢复路径。阶段 5 再通过整库灾难恢复、单域旁路恢复和空机恢复测量 **measured RPO/RTO**，记录实际可恢复时间点、实际耗时、未恢复数据、补抓耗时和选择性修复耗时。未完成测量或实际结果未达到目标，不得宣布生产迁移最终验收。

### 8.3 整库灾难恢复与单域逻辑恢复必须区分

整台 VM、磁盘或主要 database 丢失时，使用整库灾难恢复路径。若只是某个 schema、publisher、任务或用户操作造成逻辑错误，不得默认把整个 production database 原地回退到旧时间点，因为这会同时抹去其他域之后的有效写入。

单域逻辑恢复优先将备份或时间点副本恢复到旁路实例/隔离环境，验证受影响对象后选择性提取、对账并修复 production；publication/revision/audit 和稳定身份用于限定修复范围。具体工具在实施阶段决定，但任何选择性修复都必须留下审批和审计记录。

### 8.4 GitHub 不是数据库备份系统

- live data 不进入应用仓库；
- 不把日常 dump commit 到 Git 历史；
- Git LFS 不作为频繁变化数据库备份默认方案；
- 合规允许时，可以把客户端加密的低频灾备放到独立 private backup repository 的 Release assets；
- 加密密钥不得和备份同处；
- GitHub 灾备不能替代公司内部或 VM 外备份。

### 8.5 PostgreSQL 与 Viewer/任务 VM 的物理位置

基于当前数据规模、低用户/吞吐、VM 偶尔停机可接受以及团队尚无 PostgreSQL 运维经验，PostgreSQL 与 Viewer/任务 VM 初期共置是可接受的 production 候选，而不只是被预先判定为临时方案。共置不等于高可用，必须具备 VM 外备份、自动启动、正常关机与 crash recovery 验证、资源监控和空机 restore test。

是否物理拆分由 RPO/RTO 和可测触发条件决定，包括：数据库必须独立于 Viewer 停机、需要独立维护窗口或安全隔离、资源争用持续影响任务/查询、出现多个应用节点，或容量与恢复目标无法由共置满足。独立部署同样需要网络、账号、防火墙、证书和恢复运维成本，不能仅以“更像生产”作为理由。

## 9. Artifact、项目规则与敏感边界

### 9.1 应进入应用 Git 的正式资产

- 团队共享 `AGENTS.md`；
- 活动 OpenSpec 和 main specs；
- 生产/审核真正依赖的 skills；
- database migration 和 schema 合同；
- 测试、CI、deployment/recovery 工具；
- 正式配置模板和 SOP；
- 影响 Codex 行为和代码质量的稳定上下文。

### 9.2 不进入应用 Git

- `tools/dynamic/secrets/**`、Cookie、browser profile、token；
- live DB、WAL/SHM、runtime、logs、backup、broadcast；
- 个人 scratch、对话历史和一次性工作记忆；
- 未脱敏 debug output；
- 未经合规批准的 papers、用户内容和数据库导出。

`codex_context/` 和 `skills/` 不能按目录一刀切：正式、活动、团队共享的内容进入 Git；动态快照、个人记忆和历史留档不进入部署闭包或按独立规则管理。

## 10. 分阶段迁移

### 阶段 0：架构批准

目标：确认目标架构、资料边界、迁移原则、待评估的 RPO/RTO 输入和生产仓库治理门槛。  
退出：用户批准 proposal/design/tasks/specs。  
禁止：任何实施。

第三轮合同和语义校验通过后，本设计可以建议用户批准阶段 0 退出，但不会自行批准或勾选 HALT。该批准只开放阶段 1 的 tracked allowlist、secret/path gate、staged inventory、安全 Git bootstrap、测试基线修复、lockfile、CI 和受保护 main 准备；不开放 PostgreSQL production、生产数据访问层改造、数据库/runner 切换、VM production deploy、人工写接口或 production authority。

### 阶段 1：安全 Git、CI 与版本边界

目标：在不带生产数据和 secrets 的前提下建立可审核代码历史；让后续修复发生在 feature branch。  
退出：bootstrap inventory 通过人工审查；CI 能稳定运行；活动 required checks 通过；main 受保护。安全 bootstrap 可以在个人 private 仓库中进行，但该仓库成为 production authority 前必须关闭公司控制权 gate。  
回滚：删除未发布的本地 bootstrap 元数据或停止远端接入，不影响 live 系统。  
禁止：VM 生产部署、数据迁移、任务切换。

### 阶段 2：可重复 release 与本地开发基线

目标：建立 immutable release、本地 dev/test 工作流、部署 manifest 和只读 VM 并行验证。  
退出：干净环境可重建；本地 Viewer 不依赖 VM；VM 候选 release 只读运行；deployment ledger 和 schema compatibility 声明能区分可回滚应用版本与 forward-only migration。  
回滚：切回现有广播包/启动路径；不触碰数据库。  
禁止：开放 VM 写接口、迁移任务或数据库。

### 阶段 3：数据访问层、PostgreSQL dev/test 与试点

目标：把 SQLite 依赖、跨域事务和稳定身份变成可复核 inventory，定义切换单元与权威后端，建立统一数据访问边界和 expand–migrate–transition–contract 机制，在 dev/test 完成一个低耦合切换单元试点。  
排序依据：共享身份依赖、写入复杂度、数据量、现有 revision/ledger、可对账性和回滚难度。`analyst_note` 为空可作为用户内容模型试验；Opportunity/financial 具备较强 ledger；sentiment 默认不是首个试点。  
退出：机器可读 SQLite dependency inventory、数据域依赖图、读写路径、事务图、`ATTACH` 替代边界、页面/API/任务/publisher 依赖、cutover unit registry、唯一 ownership/dependency、重叠检查、authoritative backend 矩阵、稳定身份/legacy mapping 均经人工审查；target RPO/RTO 获批；试点 schema、权限、迁移、源目标对账、发布幂等与 stale conflict、关键读写和兼容/恢复演练通过。  
回滚：试点未切 production 前直接销毁 dev/test；不得修改 live SQLite。  
禁止：用一个通用同步器替代域级迁移，不得长期维护双数据库方言。

### 阶段 4：按切换单元生产迁移

目标：按经批准的切换单元迁移到 PostgreSQL，并为每个单元记录 S0–S4 状态、唯一权威 writer、reader 与 runner。  
每单元退出：完整备份、迁移 rehearsal、计数/关系/业务不变量对账、写入维护窗口、shadow read、稳定身份映射、publisher/user-content 并发测试、权限检查、性能、按 target RPO/RTO 验证恢复路径、S2 水位与 uncertain-response 证据、人工批准。  
回滚/恢复：S1 可放弃试点；S2 只有在 writer 已停写且水位、审计和人工批准共同证明没有必须保留的新写入后才可恢复 SQLite writer；无法证明时按 S3。S3/S4 不得直接回到旧 SQLite，使用 PostgreSQL 前向修复、兼容代码回滚、旁路恢复选择性修复或另行批准的显式反向迁移。不得同时开放两边写入。  
禁止：四域大爆炸、无期限双写、整库双向合并。

### 阶段 5：任务切换与生产强化

目标：在生产数据切换单元就绪后迁移唯一 runner，完善停机补漏、身份权限、CSRF、监控、告警、异地备份、单域逻辑恢复和空机恢复。  
退出：逐任务真实运行、checkpoint 连续、漏窗补跑、两端排他、临时本地 production 权限已按退出条件撤销、数据新鲜度、整库/单域/空机恢复 measured RPO/RTO 达到目标、运行手册通过。  
回滚：停 VM 对应任务并恢复原 runner；任务主机回滚不改变 PostgreSQL 数据权威。数据 writer 和 runner 均必须保持唯一。  
禁止：一次性切七个任务、仅凭 Task Scheduler 状态宣布成功。

每个阶段结束必须 HALT，提交证据和 diff，等待人工批准后才能进入下一阶段。

## 11. 原设计处置

| 原机制 | 处置 | 理由 |
|---|---|---|
| private 应用仓库、allowlist、secret/path gate | 保留 | 与数据库选型无关 |
| immutable release、commit SHA、preflight/health、code rollback | 保留 | 可重复部署核心能力 |
| 四库 maintenance lock + 一致快照 | 仅迁移期保留 | 用于形成冻结迁移基线和审计档案；S3 后不是默认 production rollback target |
| 本地 request workspace | 删除为通用同步能力 | 本地改用 dev/test PG；研究请求仍作为业务输入保留 |
| 通用跨机器 UUID 层 | 删除 | 不再为 Git/CAS 合并构建一套覆盖所有表的身份系统 |
| 业务稳定身份与 legacy mapping | 保留并强化 | 跨域、跨环境、发布和审计对象不能只依赖 SQLite 自增 ID |
| 前值/后值 hash、通用 change-set、CAS、reverse change-set | 被 PostgreSQL 和域级 publisher 替代 | 不再合并两个分叉事实源 |
| dependency cluster | 作为 cutover unit / publisher 事务边界保留 | 业务依赖仍存在，但不做通用文件复制协议 |
| 用户内容 transactional outbox + Git event repo | 删除默认目标 | PG revision/audit/backup 足以承担实时权威 |
| 用户内容 revision、soft delete、audit | 保留 | 独立业务和合规价值 |
| materialized snapshot / 空库 Git 事件回放 | 删除 | 改为标准数据库备份、恢复和受控导出 |
| 任务 ledger、checkpoint、运行锁 | 保留 | 停机补漏和防重复运行仍必要 |
| SQLite migration ledger | 迁移期保留 | 目标改为 PostgreSQL migration history |
| broadcast package | 过渡冷备 | 不再是长期发布路径 |
| Viewer 身份、权限、CSRF、审计 | 保留并分阶段实施 | 多用户写入的生产安全要求 |
| 高可用只读副本、自动故障转移 | 后续强化 | 需要基于真实恢复目标和基础设施决定 |

## 12. 风险与缓解

### 风险：124 个直接 SQLite 连接导致迁移面被低估

缓解：先建立机器可读依赖清单、事务图和访问层；按经审查的切换单元迁移；要求真实 PostgreSQL 测试，不做字符串替换式方言兼容。

### 风险：一个 database 的逻辑分域仍可能产生权限或性能耦合

缓解：先用 schema/role/资源监控隔离；只有出现可测证据时物理拆分，避免提前付出跨库成本。

### 风险：迁移期两个存储状态容易形成双写或伪事务

缓解：每个切换单元明确权威后端、唯一 writer、短维护窗口和 shadow read；禁止连接失败时静默回退；一个业务事务不得跨两边分别提交。

### 风险：把旧 SQLite 误当成 S3/S4 的无损回滚点

缓解：用 S0–S4 状态机区分 rollback、restore 和 forward fix；PostgreSQL 有新写入后，旧 SQLite 只作基线、审计和有限修复材料。

### 风险：schema 已破坏兼容后仍承诺 code-only rollback

缓解：采用 expand–migrate–transition–contract，破坏性 contract 单独批准；每个 migration 显式说明 compatibility 和 forward-only 边界。

### 风险：VM 与 PostgreSQL 共置造成同故障域

缓解：共置可以是当前 production 候选，但不宣称高可用；要求 VM 外备份、crash recovery 和空机 restore；达到 RPO/RTO、隔离、维护或资源触发条件时再拆分。

### 风险：应用仓库依赖个人账号形成生产供应链单点

缓解：允许安全 bootstrap，但把公司控制权、第二管理员/交接、2FA、恢复、branch protection、最小权限和公司 deploy credential 设为 production deployment gate。

### 风险：用户内容不进入 Git 后担心可移植性

缓解：提供受控、带版本和哈希的导出；以数据库 revision/audit 和恢复演练证明可恢复，不用第二套实时事实源换取“看得见的文件”。

### 风险：阶段太多导致迁移长期停在半成品

缓解：每阶段限定目标和非目标，明确退出条件；不得同时施工 Git、数据库、七任务、安全和灾备全部路径。

## 13. DeepSeek 交叉审核处置

三次人工架构审查中的 DeepSeek V4 Flash 脱敏调用与处置均保留在 `debate_summary.md`；本次第三轮小范围审查实际调用两轮后停止，未发送 secrets、数据库内容、论文原文、用户内容或个人信息。

- 第一轮错误地把项目解释为多 VM local-first 系统，建议 SQLite 继续做每节点事实源、Git 传 change-set；与实际单生产 VM、中央事实源目标和 Git 禁止承载 live rows 的边界冲突，因此拒绝。
- 第二轮在明确纠正后仍建议 SQLite dev 双轨、自动同步和未要求的 PostgreSQL 主从；继续违背“不长期双写、不发明节点、不扩张范围”，因此拒绝。
- 第一次审查接受的有效提醒是：PostgreSQL 与 Viewer/任务 VM 共置不能被描述为高可用，必须有 VM 外备份和恢复演练。本次审查进一步修正为：共置可作为当前 production 候选，是否拆分由 RPO/RTO 和可测条件决定，不预设独立主机必然是终局。
- 第三次审查拒绝了凭空设定 3/4 秒 RPO/RTO、异步复制、备用 VM 和分布式事务等假设；接受的最小改进是把 S2 明确成 PostgreSQL 单 writer、SQLite 停写冻结，并要求 cutover unit 逐类满足 target RPO/RTO。

最终设计由 Codex 基于 live 代码、schema 和任务边界独立负责，没有复制 DeepSeek 的方案。

## 14. 仍需人工决定

1. 各数据类别可接受的 RPO/RTO 等级，以及它们是否要求连续归档/PITR；
2. 基于 RPO/RTO、维护和安全隔离条件，production PostgreSQL 初期共置还是独立部署；
3. papers/evidence 的内部存储位置和资料上云审批边界；
4. 应用仓库转入公司 Organization，或在转移前采用何种经批准的公司控制权例外。

内容仓库不再是未决项，当前状态固定为 `RESERVED-UNUSED`。上述四项未决定不会阻止本轮文档审查，但会阻止对应 production gate 或实施阶段退出。
