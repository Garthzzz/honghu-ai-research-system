# 阶段 4：PostgreSQL 切换准备与首单元实施设计

## 1. 本轮权限与结论边界

本轮只完成设计、非生产准备、隔离演练和证据构建。不得切换 production writer/backend，不得向 production PostgreSQL 写入正式业务数据，不得停止 SQLite writer，不得迁移计划任务或 production Viewer/runner，也不得进入任何 production cutover unit 的 S2/S3。

阶段 3 的 registry、authority matrix、target RPO/RTO 和 PostgreSQL dev/test 试点是输入，不是 production-ready 声明。任何实际切换都需要新的、仅针对一个 cutover unit 的人工授权。

## 2. Stage 4 入口事实

2026-08-11 对活动 live 根做了新的只读 drift check：

- 四套 SQLite schema 与 Stage 3 最终证据一致；四库检查前后文件 SHA256 不变。
- deployable 路径仍为 281 个、958 条 writer operation、388 个 transaction boundary；Git 外 live-only addendum 仍为 6 个路径、13 条 writer operation、4 个 transaction boundary。
- aggregate 仍为 287 个路径、971 条 writer operation、392 个 transaction boundary，134 张受审业务表仍有唯一 ownership。
- 只观察到研究、动态和 sentiment 普通行增长，没有 schema、writer path、事务边界或 ownership drift。
- `research.db.analyst_note` 仍为 0 行。

本轮新证据放在 Git 外 `cache/migration/stage4_entry/`；公开文档只记录结果和内容身份，不提交 live 数据、原始路径内容或数据库行。

## 3. 切换单元排序方法

排序不是按四个 SQLite 文件，也不是只按行数。每个生产单元同时评估：

1. 上游 dependency 是否已经有稳定身份或可验证只读映射；
2. writer operation 和完整 transaction boundary 数量；
3. 持续任务、人工写接口和 publisher 是否需要停写或共同切换；
4. 数据量、历史修订、不可重抓程度和 target RPO/RTO；
5. 是否已有 migration、幂等、revision/audit、对账和旁路恢复证据；
6. 切换失败后是否会造成跨后端伪事务、双 writer 或丢失不可重建写入。

非生产 fixture、reader transition、legacy one-shot 和跨域 bridge 不作为独立 production authority 排队；它们必须在依赖单元前被重构、并入共同切换边界或明确退役。

建议生产顺序如下：

| 顺序 | cutover unit | 主要理由与前置条件 |
|---:|---|---|
| 1 | `user_content_notes` | 当前 0 行、2 条实际 mutation path、无 scheduler，且已有 revision/audit 原型；但必须先修正字段兼容、稳定实体映射、API 幂等/软删除和人工写安全门禁。 |
| 2 | `shared_identity` | 是多数域的共同依赖，迁移后能消除跨环境自增 ID 风险；风险高，必须先完成 company/security/industry/theme 的稳定键和 legacy mapping。 |
| 3 | `financial_data` | writer/事务数量相对有限，但含 revision、模型和对账，需先处置 `financial_snapshot_bridge`，保护不可重建的内部模型 ledger。 |
| 4 | `research_publication` | 数据量中等但 writer/事务最多，必须保持 publication identity、expected revision、依赖簇原子性和发布 ledger。 |
| 5 | `dynamic_intelligence` | 有持续采集和窗口风险，需明确唯一 runner、checkpoint 和停机补漏；应在共享身份稳定后迁移。 |
| 6 | `operations_governance` | 依赖身份与动态，体量小但控制任务/抓取状态；authority control 不得混入普通 task state。 |
| 7 | `investment_hypotheses` | 行数少但同时依赖身份、研究和动态，属于不可重建人工内容，不能因体量小提前切。 |
| 8 | `opportunity_lens` | 依赖身份、研究、动态和财务，46 张表且有发布/审计语义，应在四个上游稳定后整体切换。 |
| 9 | `sentiment_analytics` | 约 225 万行、持续任务、窗口/聚合/retention 强耦合，恢复和补抓最复杂，最后迁移。 |

`identity_consolidation_bridge`、`financial_snapshot_bridge` 必须先分别归入相关单元的重构/共同切换决策；`legacy_migration_archive` 不成为未来 writer；`viewer_access_boundary` 只随所读单元切换 reader，不拥有业务表。

## 4. 首个 production cutover unit

首选 `user_content_notes`，但当前状态是“最适合继续准备”，不是“已经可生产切换”。选择依据：

- live 表为空，迁移基线和 reconciliation 清晰；
- 实际函数级写路径只有 create 与 delete，且没有计划任务；
- failure blast radius 可限制在 analyst note；
- Stage 3 已证明 PostgreSQL revision/audit/idempotency/side restore 基础机制；
- 它能先验证 authority state、writer fencing 和 S2/S3 语义，而不把高风险研究发布或 sentiment 当作第一个生产试验。

### 4.1 Stage 3 原型不能直接生产使用

人工函数级审计发现：

- SQLite `analyst_note.q_number` 是 `TEXT`，实际语义允许 `Q0`—`Q6`；原 PostgreSQL migration 0001 使用 `integer`，存在真实兼容缺口。
- SQLite API 以自增 `id` 返回和删除，PostgreSQL 原型以 `note_key`、revision 和 soft delete 治理，两侧公开合同尚未衔接。
- 当前 create 没有 idempotency key / expected revision；delete 是硬删除。
- `entity_id` 是当前 SQLite 域内 ID，不能直接当作跨环境长期稳定身份。
- 当前 mutation endpoint 的身份认证、CSRF 和最小权限不能因迁移而被默认视为已满足。

因此 0001 只作为已执行过的 dev/test expand 原型保留。生产前用新的 additive migration 修正兼容合同；不得改写已登记 migration，也不得用空表掩盖 schema 错误。具体兼容方向不是修改 live SQLite：PostgreSQL 新增文本型 `q_label` 并把旧整数列保留为过渡兼容字段；nullable title、legacy note id 和原始时间文本也通过向后兼容字段/迁移规则处理，待后续独立 contract release 再删除旧结构。

### 4.2 首单元目标合同

目标 writer operation 包括：create/update note、soft delete note；read list/get 与 writer 同时切到同一 authoritative backend，禁止写 PostgreSQL 后从 SQLite 读取旧结果。

每条 note 必须具有：

- 稳定 `note_key`；
- 可验证的稳定 entity identity 或 legacy mapping；
- 文本型 Q 标签兼容合同；
- revision、soft delete、mutation audit；
- idempotency key、request hash 和 deterministic retry；
- expected/base revision 和 stale conflict；
- legacy numeric id 的受控兼容映射，而不是把 SQLite 自增 ID 当长期业务身份。

### 4.3 共享身份依赖

`user_content_notes` 可以早于完整 `shared_identity` 切换，但不能无约束引用可变 SQLite 自增 ID。S1 前必须冻结并验证 note 可引用的 company/industry/theme 身份映射：

- 映射是首单元的只读 dependency snapshot，不宣称接管共享身份 authority；
- 映射来源、legacy database/table/id、stable key 和校验水位可审计；
- create/update 只能引用已验证映射；缺失或冲突必须 fail-closed；
- dependency identity 在首单元切换窗口内发生不兼容变更时停止切换，不能跨 SQLite/PostgreSQL 分别提交后假定原子性。

## 5. S0—S4 与 writer fencing

| 状态 | 权威与允许动作 | 放弃、恢复和证据 |
|---|---|---|
| S0 | SQLite 是唯一 authority；PG 只允许离线 schema/migration/rehearsal。 | 可删除非生产试验库；不影响 live。 |
| S1 | production PG 结构、权限、备份、映射和基线已准备；SQLite 仍是唯一 writer。只允许离线 backfill/shadow read，不允许业务 shadow write。 | 可放弃 PG 候选；记录 migration/backfill evidence。 |
| S2 | 短时切换栅栏：SQLite mutation path 已显式 fenced，PG writer 已启用但只允许有分类标记的 verification write；记录 cutover epoch、SQLite final watermark。 | 只有停写核验、PG 审计、水位和人工批准共同证明没有必须保留的新写入时，才能恢复 SQLite writer。uncertain response 一律按 S3。 |
| S3 | 第一条必须保留的正式 PG 业务 commit 已持久化并记录 first formal watermark；PG 是唯一 authority。 | 旧 SQLite 仅是迁移基线/审计材料。故障走 PG 前向修复、兼容应用回滚或旁路恢复后选择性修复，不得静默回写 SQLite。 |
| S4 | 观察期通过，旧 SQLite mutation path 被移除或永久 fenced，旧文件保留为标记清楚的审计档案。 | 任何反向迁移是新的显式 migration，不是“把旧文件切回来”。 |

authority transition 的 acknowledgement 必须和 audit ledger 同等持久；无法证明 S2 没有新 commit 时按 S3。应用连接失败不得自动 fallback SQLite。

每次状态变更必须记录 operator、人工批准引用、expected state/revision、writer identity、原因和证据 identity。所谓 acknowledgement 是调用方确认状态事务已提交且对应 audit revision 可读，不是某个人可以批准丢数据；任何已 acknowledgement 的 authority transition 都不允许丢失。S2 首条正式业务写和 S2→S3 authority revision 必须在同一 PostgreSQL 事务内提交，调用方只有在事务成功返回后才 acknowledgement；响应不确定时以幂等 operation identity 查询和重放对账，不根据客户端异常推断回滚。

Writer fence 必须作用于可审计 mutation operation，而不是粗暴按整个 Flask 进程判断。一个进程可以同时包含不同单元的 read/write path；首单元只切 analyst-note 的 repository/route，不迫使其他 Viewer 数据域一并切换。

## 6. Migration 与 reconciliation

### 6.1 Expand 和 backfill

- additive migration 建立 authority state/audit、水位、稳定身份映射和兼容 note contract；破坏性 contract 放在后续独立 release。
- 既有 0001 migration SHA 保持不变；新的 0002 只增加 authority/audit/mapping/兼容列与 v2 operation，旧函数在 application transition 窗口内保留但不授予 production writer。
- S0 初始化 authority row；迁移角色直写 backfill，业务 writer 在 S0/S1 被数据库侧拒绝。
- S1→S2 要求 expected revision、cutover epoch、SQLite final watermark、批准引用和唯一 writer identity；verification 只写控制面验证 ledger，不写业务 note。
- S2 的首个 formal note mutation 在同一事务内写业务 row、idempotency/audit 和 S3 authority revision；S3/S4 后才允许后续业务 mutation。
- S1 backfill 从一致 SQLite 基线读取；当前 0 行仍必须执行 source/target count、字段类型和空集证明，不能跳过。
- 如果正式窗口前出现新 SQLite note，先重新基线并迁移全部行；保留 legacy id mapping、时间和文本，不把本地时间字符串无依据解释为其他时区。

### 6.2 对账门禁

至少验证：

- source/target active/deleted/count；
- 每行稳定 key 和 legacy mapping 唯一性；
- entity mapping 完整性；
- q label、nullable title/q、author/default、created/updated 时间语义；
- revision/audit/idempotency invariant；
- create/update/delete/list API 兼容；
- stale update、duplicate retry、uncertain response；
- viewer read 与 mutation endpoint 都只命中 matrix 指定 backend。

对账证据绑定 cutover unit registry identity、migration SHA、source baseline、target snapshot、应用 commit 和 cutover epoch。

## 7. Production PostgreSQL 前置条件

### 7.1 拓扑

首期允许 PostgreSQL 与 Viewer/任务 VM 共置，原因是当前规模和可接受停机边界不足以证明必须新增主机；共置不等于高可用。是否拆分由已批准 target RPO/RTO、资源测量、维护隔离和恢复演练结果触发。

实际 production 前必须确认：

- 固定受支持版本、数据目录、磁盘余量、内存/IO 基线和自动启动/crash recovery；
- 监听范围和防火墙最小化；需要跨主机连接时使用受控网络与传输保护；
- 一个主要业务 database，按 schema/role 分域，不机械复制四个 SQLite database；
- migration、unit writer、viewer read、audit/backup 分离角色；应用角色无 DDL，首单元 writer 无跨单元写权限；
- 凭据不进入 Git、命令行日志或 release，轮换和撤销可执行；
- 当前个人账号仓库尚未满足 production authority 公司治理 gate，因此 production release authority 必须在真实切换授权前单独关闭。

### 7.2 备份和恢复

- authority control：零 acknowledged loss；未持久化/未复制到合格恢复介质前不得 acknowledgement。
- analyst note：目标 RPO 不超过 5 分钟、RTO 不超过 4 小时；这是 target，不是已达 SLA。
- production 切换前必须完成 VM 外备份、可恢复的基础备份与增量/WAL 方案、恢复凭据隔离，以及真实 restore rehearsal。
- 同时演练整库恢复和旁路单域恢复；单域逻辑错误不得原地把整个 database 回退到旧时间点。
- 恢复后必须先验证 authority state，再开放任何 production writer。
- 当前目标不要求凭空增加 HA 节点；若共置拓扑的实测恢复无法达到目标 RPO/RTO，才由证据触发独立数据库主机、额外副本或其他拓扑变更的单独设计。

## 8. 监控与退出门槛

首单元监控至少覆盖：authority state/epoch、唯一 writer、write success/conflict/idempotent retry、stale conflict、audit gap、mapping conflict、read error、PG connection exhaustion、backup/WAL freshness、last verified restore 和 SQLite fence 状态。监控失败不得触发 SQLite fallback。

申请实际 production 执行授权前必须全部满足：

1. Stage 4 非生产演练覆盖 S1 放弃、S2 安全撤回、S2 uncertain→S3、S3 前向修复/兼容代码回滚/旁路选择性恢复；
2. 字段兼容、稳定 identity mapping、API revision/idempotency/soft delete 和 writer fence 代码已实现但保持 production disabled；
3. production topology、角色、凭据、off-VM backup 和恢复演练有现场证据；
4. repository production authority gate 与人工写入口安全 gate 已关闭，或在授权中明确先保持 mutation endpoint disabled；
5. live drift 在窗口前再次通过；
6. 用户单独批准首单元、维护窗口和 S2 进入。

在这些前置条件没有现场证据前，本设计只能建议继续准备，不能申请或执行 production cutover。
