# Stage 4/5 实施避雷与证据合同

> 状态：活动实施必读文档。用于后续 production migration、runner、恢复、发布和清理任务的设计与计划审查；不是完成报告，不是现场 evidence，也不表示 Stage 5 已通过。
>
> 使用规则：先重新查询 live 状态，再逐节对照本合同。任何设计或执行计划若未说明相关条目为何满足、为何不适用或由什么 evidence 验证，不得进入 production 执行。

## 1. 文档职责与事实等级

本文件沉淀 Stage 4/5 实施中已经反复暴露的通用风险，避免以后把同类问题再次当作 VM 特例修补。它只定义可复用合同，不冻结动态主机、IP、PID、commit、数据库行数、任务状态或恢复耗时。

判断顺序固定为：

1. live 代码、数据库、服务、任务和网络的只读采样；
2. exact commit、manifest、migration/config identity 和不可变 evidence；
3. 已批准 OpenSpec 合同；
4. 历史报告、日志和人工摘要。

证据必须区分：

- **observed fact**：现场命令、数据库查询、HTTP、Windows/PG 状态或真实恢复结果；
- **static guarantee**：代码或配置中没有某种 mutation 路径；
- **decision/approval**：明确的人类批准范围；
- **inference**：根据上述事实得到、但仍需注明边界的判断。

静态代码“没有修改命令”不能替代现场前后状态；文件存在、进程启动、任务为 `Ready` 或 API 返回 200 也不能单独证明业务健康。

## 2. Exact SHA、PR、CI 与部署身份

### 2.1 必须区分的身份

同一轮至少可能存在五个不同身份：

- implementation branch commit；
- pull request head commit；
- GitHub 为 PR 测试生成的临时 merge commit；
- 合并后的 main/governance commit；
- VM 实际部署的 release commit。

PR workflow 的 `GITHUB_SHA` 通常是临时 merge commit，只用于证明“head 与当前 base 可合并并通过测试”，不得作为 VM 部署 SHA。可部署身份必须是人工批准的 branch/main exact commit，并由同一 commit 的 push workflow、required jobs 和 exact-commit artifact 共同证明。

### 2.2 CI 绿色仍需核对什么

部署前必须核对：

- remote branch 与 PR head 是否仍是批准 SHA；
- push 与 pull_request 两类 run 是否都绑定正确 head；
- required jobs 的实际名称和结论；
- push artifact 中的 commit role、commit SHA、release manifest SHA 和 deploy eligibility；
- PR artifact 的 `pull_request_head_sha`，并明确其 workflow SHA 不可部署；
- workflow 是否因 outage、hold、filter、concurrency 或事件丢失而根本没有创建 run。

不能 rerun 旧 SHA、复用旧 artifact、push 空提交或修改无关文件来制造 identity 闭环。GitHub 事故与审批 hold 必须以 Status、Actions/Checks API 或 UI 现场事实确认，不能由“现象相似”推断成已证实根因。

### 2.3 不可变 release 的身份闭包

release manifest 应覆盖完整文件集合、逐文件大小/hash、总数和总大小。build、preflight、activate、launch、smoke、stop 和失败清理后都必须验证 exact file set；任意 `.pyc` 或额外文件均为污染。不得在 current 或运行中的 release 内原地删除/修补；未激活且无进程、pointer、evidence 引用的污染 release 才可整体 quarantine 后重建。

## 3. Windows Task Scheduler、身份与进程生命周期

### 3.1 `InteractiveToken` 不是生产 service identity

交互式用户可用于一次性、人工在场的 credential provision 或受控试跑，但不能据此证明非交互生产任务可运行。正式任务必须使用批准的 least-privilege principal，并证明：

- 不依赖桌面登录、用户 profile、`PATH` 或当前工作目录；
- 可读取 exact release、config、content 和 data；
- 只能写外置 runtime、lock、log 和被授权的业务对象；
- PostgreSQL `current_user`、role membership 与 task-scoped ACL 符合 manifest；
- Task XML、命令行、日志和 evidence 不含 credential。

WinVault/Credential Manager 项与 Windows 用户身份和 scope 绑定。一个交互用户创建的 CurrentUser credential 不会自动对另一个 task principal 可见；不能通过复制用户名、环境变量或凭据名称假定可用性。credential probe 必须在实际任务 principal 下执行，只记录 reference、provider、成功/失败和脱敏 identity。

### 3.2 PID 不是充分身份

启动与停止必须联合核对 PID、启动时间、可执行文件、命令行 hash、launch id、exact commit、manifest、端口 listener 和 health identity。单独保存 PID 会遇到外层 CLI 与真正 listener 分离、子进程残留和 PID 复用。

Windows Job Object 的 kill-on-close 必须在 child launch 前建立并绑定，保证超时、异常、父进程退出和 smoke 失败都能回收整个 process tree。对现有记录的停止必须 fail-safe：可选 CIM 属性缺失不能直接导致永久无法清理，但身份冲突、PID/port 仍在或无法证明归属时也不得误杀。

### 3.3 Scheduled Task 状态不等于业务健康

`Ready`、`Running`、`LastTaskResult=0` 只说明调度器/进程层状态。业务健康还需要 ledger、logical window、checkpoint、source audit、last-success 和 data freshness。安装必须 disabled-first；启用前的本地旧 runner evidence 应至少绑定：

- 采集时间与 freshness 上限；
- source host 的可验证身份；
- 七个受管任务 definition identity/hash；
- 本地任务均 Disabled；
- 没有旧 runner/process 的现场证据；
- collector 与 evidence schema/hash identity。

陈旧、来源不明、字段不全或调用方可自由填写的“Disabled=true”不得通过 VM enable gate。

## 4. PostgreSQL authority、幂等与大批量原子性

### 4.1 Authority 不变量

每个 cutover unit 在任一时刻只能有一个 authoritative backend、一个 owning writer operation 和一个完整事务边界。S3 后 PostgreSQL 失败只能失败、暂停或重试，绝不能 silent fallback SQLite、dual write 或 shadow write。旧 SQLite 只作 migration baseline/audit，不是 production rollback target。

tracked/static default route 与 live authoritative backend 是两个概念。health 和 recovery 必须读取并验证 live authority-control state，不能因仓库默认配置仍写 `sqlite_transition` 就误判生产已回退，也不能因顶层写着 `production_postgresql` 就宣称所有单元都已迁移。

### 4.2 幂等与 uncertain response

一次逻辑 mutation 在结果明确前必须保持同一 operation/publication identity；响应丢失后先按该 identity 查询或精确重放，不得生成新 key。create、update、delete 都要同时保持：

- expected/base revision 或等价条件；
- stale update 显式冲突；
- writer fence 与 authority revision；
- stable actor/principal；
- 同 identity、同 payload 精确 replay；
- 同 identity、不同 payload fail-closed。

无法证明 transaction 未提交时，按已提交的保守路径对账，不能乐观恢复 SQLite writer。

### 4.3 大 batch 的性能不能削弱原子性

逐行在循环中反复拼接大型 JSON 数组会产生 O(n²) 内存/时间成本。大批量 API 可以返回 bounded summary（request identity、mutation count、watermark），但不能因此删除逐行 revision/audit/idempotency 或拆散事务。

一个逻辑 batch 即使被客户端分 chunk，也必须在同一 PostgreSQL transaction 内完成，或者把每个 chunk 明确定义为独立业务 operation；不得在多个 transaction 提交后声称整体原子。适合 set-based SQL 的清理/状态迁移应优先在服务端集合执行，同时保留 authority、ACL、ownership、duplicate 和 row-fence 检查。

最低真实 PostgreSQL rehearsal 应覆盖：

- exact replay 不增加行、revision 或 audit；
- same key/different payload 冲突；
- wrong writer、wrong authority state、ownership collision 拒绝；
- 多 chunk 的晚期失败为 zero partial commit；
- mixed row-fenced/合法行不产生部分成功；
- 大批量耗时和返回体保持有界。

## 5. Immutable release 与 runtime path 闭包

immutable release 只放 tracked code、migration、template、static 和可复现工具。以下内容必须外置并由显式参数传入：

- live data/database；
- content/papers/evidence；
- runtime state、locks、logs、checkpoints；
- credentials、private keys 和 machine-local config；
- backup/WAL/recovery evidence。

所有 Python 子进程使用明确的 Python 3.10 绝对路径、hash-pinned environment、隔离 import（按入口使用 `-I -B -S`）并清除不受信任的 `PYTHONPATH`。不得从 `PATH` 猜解释器，也不得认为 base、quant、历史环境名等价。

跨平台实现要提前测试 Windows 的 BOM/`utf-8-sig`、8.3 path identity、大小写和 packaging 名称规范化；distribution name 的点、连字符、下划线和大小写应按标准 canonicalization 比较，不能为单个包硬编码例外。

content closure 要区分 required 与 optional/conditional。required 缺失严格失败；optional 缺失必须在 preflight/evidence 记录并由降级路径测试，不能创建空目录或伪内容冒充存在。所有数据库中的相对路径都应从外置 content root 解析，不得悄悄回到 release root。

## 6. Controlled trial 与正式任务

controlled trial 只证明一个 exact release、exact manifest、明确 logical window 和 disabled task 下的业务路径。它不等于 recurring runner 已获授权，也不得修改正式 schedule 或伪造 freshness。

试跑合同至少包含：

- `allow_disabled` 只能由受控入口显式开启；
- task、logical window、业务日期/slot、actor、commit 和 manifest 被记录；
- 试跑前后核对 authority、runner uniqueness、checkpoint 和业务结果；
- idempotent replay 与失败分类通过；
- 试跑结束后任务仍 Disabled，除非另一个 enable gate 明确通过。

对有时段约束的 Retail 类任务，同日试跑也只能在工作日且当前业务时区严格晚于 manifest 已审核 trigger 后执行；未来窗口、周末、触发前或普通 production 调用不得借 `allow_disabled` 放宽。某个 producer 的兼容 retry 只能匹配可验证的 exact legacy error，不得成为捕获所有异常后继续的通用降级。

正式启用前还必须验证 installed Task XML、principal/run level、execute/arguments/workdir、period、exact SHA/manifest、local Disabled v2 evidence 和首次 health PASS。启用逻辑所有 precheck 应位于同一 fail-closed `try` 中；任何失败先禁用任务，再保存主失败与 cleanup evidence。

## 7. Recovery：从恢复集到真实连续 RPO/RTO

### 7.1 三种时间指标不得混用

- **target RPO/RTO**：切换前批准的业务目标；
- **recovery-set target gap**：某一已验证 recovery set 的 durable target 与 recovered watermark 之差；
- **continuous production RPO / full-system RTO**：故障发生时实际丢失窗口，以及从空机、凭据、应用、任务、checkpoint 和业务补抓恢复到可运行状态的总耗时。

某次 sentinel 的极小 target gap 不能宣传为系统任意时刻 RPO；数据库 restore elapsed 也不包含空机重建、credential injection、Viewer/tasks、校验和补抓。

### 7.2 Off-VM recovery set 合同

同一 VM 的另一盘符不是 off-VM。完整恢复集至少包括：

- base backup；
- 达到 target 所需的连续 WAL/incremental artifacts；
- target watermark 与 base 后 sentinel；
- manifest 和逐 artifact hashes；
- source、storage host、failure-domain identity；
- schema/migration/authority/config identity。

restore 必须只使用异机保存的 recovery set。缺 WAL、gap、篡改、sentinel 未出现、copy identity 不符、same-host 冒充或恢复过程中偷读本机 archive 都必须失败。

### 7.3 SMB、动态 IP 与 storage transition

SMB 地址可能随 VPN/网络变化；不能把某个 IP 字符串或 caller 提供的 `host_id` 当作故障域证明。remote storage identity 应由目标主机上的受信 collector 产生，绑定机器身份、共享边界、at-rest 状态、采集时间、manifest/artifact anchor 和签名。source 与 remote identity 相同必须失败。

storage endpoint 变化应生成一次显式 transition evidence，至少绑定 old/new storage identity、上一份 recovery manifest/artifact identity、新 endpoint 的现场 probe、过期窗口和批准范围。禁止二次跳转自动继承信任。执行 copy/restore 前后重算 hash，防止验证与使用之间的 TOCTOU。

### 7.4 DPAPI、at-rest 与 restore 权限

WinVault/DPAPI、证书私钥和 PostgreSQL credential 的可见性由 Windows principal、user/machine scope 和 ACL 决定。不得把 secret 本身放入 backup manifest、Git、argv、log 或 evidence；恢复合同保存的是 credential reference、重新注入步骤和验证结果。

at-rest evidence 不能接受调用方自由填写的 MachineGuid、BitLocker 状态或共享 identity。应使用主机绑定 collector，canonical payload 由非导出私钥签名，verifier 只信任 pinned public certificate，并验证算法、强度、用途、有效期、payload hash 和签名。private-key existence 或 `secrets_recorded=false` 不能替代实际加密状态 probe。

恢复实例的 Windows/PG service principal 必须拥有 data/WAL/restore 目录所需权限且不超出边界。whole、side-domain、authority-control、task checkpoint 与 empty-machine restore 分开验证；数据库可连接不代表 authority/runner 可以恢复。

## 8. Health、freshness 与告警

统一 health 至少交叉验证：

- Viewer endpoint 与 exact release；
- PostgreSQL service/version/connectivity；
- 9/9 authority、writer fence 和 schema compatibility；
- 七任务 installed identity、unique runner、ledger/checkpoint；
- data freshness 与 missed-window/catch-up；
- backup freshness、WAL continuity、last verified restore；
- disk capacity、runtime/recovery retention。

输出中必须把 `process_alive`、`last_run_success` 和 `data_fresh` 分开。任务进程在、任务返回零、数据仍旧陈旧时，整体应为 degraded/failed，而不是 PASS。

如果尚无获批外发告警通道，最低能力是 Git 外机器可读状态、明确 reasons 和非零退出码；不得把“生成了 health JSON”说成通知已经送达。健康任务应使用 exact release、least-privilege principal、外置输出、single-instance policy，并在 recovery/authority evidence 过期时 fail-closed。

## 9. 网络、VPN 与远程执行

每次远程 production 操作前先核对目标 `hostname`、执行 principal、SSH/WinRM listener 和现有 Viewer health。VPN 切换可能改变来源地址、防火墙命中和 SMB route；Git 文档和脚本不得把临时客户端 IP 当永久可信身份。

网络 evidence 应区分：

- 声明的 endpoint；
- 连接时实际观察的 source/remote endpoint；
- TLS/server/storage identity；
- firewall allowlist 与测试时间；
- localhost、VM 本机和另一台 LAN client 的不同验证范围。

非交互 task principal 不一定继承交互用户的 SMB session、mapped drive 或 VPN profile。恢复与备份应使用显式 UNC/endpoint、受控 credential reference 和主机身份验证，不能依赖资源管理器中“看得到盘符”。网络中断必须让任务暂停/失败，绝不能触发 SQLite fallback。

## 10. 清理必须使用引用集

不得按目录名、年龄或“failed”字符串直接递归删除。清理顺序固定为：

1. `project_artifacts.py` 生成显式 inventory/manifest；
2. 汇总 process、service、current pointer、task definition、release manifest、recovery catalog 和 evidence 引用；
3. `apply_project_cleanup.py` 或对应受限工具 dry-run；
4. 人工核对 `pending_review`；
5. apply 后重新验证 release、Viewer、PG、tasks、backup/WAL 和 restore identity；
6. 验收完成后原子刷新 `backup/latest`，再对项目外旧副本运行 prune dry-run/apply。

必须保留：当前 production exact release、当前 Viewer/任务引用的 release、批准的 schema-compatible rollback release、运行时 catalog/credential reference、当前 WAL recovery chain、最后成功 restore、合同要求保留的两份最新验证集、authority/task/evidence ledger 和仍有审计价值的 SQLite baseline。

failed/quarantine/旧 release/旧 WAL/test 目录只有在“无进程、无 current、无 task、无 manifest/catalog、无恢复链、无审计引用”全部成立时才可清理。清理 evidence 要记录 manifest hash、实际删除项、跳过原因、释放空间和清理后核验，不能覆盖原失败 evidence。

## 11. Evidence schema、hash、时间与状态

每份 machine-readable evidence 至少应有：

```text
schema_version
evidence_id / attempt_id
subject / scope / environment
checked_at_utc
collector / actor / host identity（脱敏且可验证）
exact_commit_sha
release_manifest_sha256
config_or_migration_sha256
input_artifacts[] {path_role, sha256, size}
observed
status
reasons[]
primary_failure
cleanup
cleanup_failure
evidence_identity_sha256
secrets_recorded=false
```

状态使用 `pass`、`failed`、`blocked`、`in_progress`、`not_applicable` 等明确枚举，不用一个 boolean 概括复杂结论。`blocked` 必须说明缺少的外部条件；`not_applicable` 必须说明合同依据。

hash identity 应对排除自身 identity 字段后的 canonical JSON 计算，明确编码、key ordering 和时间格式。时间统一保存 UTC ISO-8601，并同时记录 freshness/expiry contract；不能只保留本地显示时间或文件 mtime。

原始 gate 的 pre-state、gate-time post-state、comparison、reasons 和 primary failure 一旦产生即不可变。cleanup 后状态放到独立 `post_cleanup`/`final_state`，不得覆盖原 comparison；主失败与 cleanup failure 分开保存。

证据文件按 attempt/version 追加，不静默覆盖。报告只引用 evidence identity/hash，原始 database、WAL、credential、private key、Cookie、用户内容和未批准资料保持 Git 外。

## 12. 并行、增量与独立测试策略

可以并行：不同 worktree 的代码/文档、只读 inventory、独立 reviewer、互不依赖的 CI/静态检查。必须串行：同一 cutover unit 的 authority transition、同一 task 的 enable/disable、共享 recovery catalog/retention mutation 和 production cleanup。

推荐验证层次：

1. 设计时把不变量写成可执行 contract；
2. unit/static tests 覆盖输入、身份、错误分支与 fail-closed；
3. isolated PostgreSQL/Windows rehearsal 覆盖真实事务、权限、进程和文件语义；
4. exact commit 的 push/PR CI；
5. VM disabled preflight 与 controlled trial；
6. production 前后 evidence、cleanup 和独立 reviewer；
7. 修复完成后重新设计一组不同于原失败路径的终验测试。

小修先跑定向回归，再跑 full core、compile、OpenSpec strict、tracked/secret/path boundary、SQLite ratchet 和 required CI。禁止用 skip、永久 xfail、删测试、放宽合同或旧 artifact 掩盖失败。

大数据 baseline 已验证后优先用 watermark/delta catch-up；普通新增行不触发全量重跑。只有 schema、writer、transaction boundary、ownership 或 identity mapping drift 才重新打开设计。性能测试必须包含真实规模或可解释的放大模型，同时确认优化没有破坏事务与审计。

## 13. 决策门槛与禁止事项

四类门槛不得混用：

| 门槛 | 证明内容 | 不自动授权 |
|---|---|---|
| merge gate | PR head、required CI、review、boundary | VM 部署 |
| deploy gate | 人工批准 exact SHA、push artifact、immutable preflight | task enable / backend cutover |
| production enable/cutover gate | authority、unique writer/runner、recovery、现场前后 evidence | 阶段 PASS |
| stage exit gate | 所有任务观察、恢复、measured RPO/RTO、治理与用户批准 | 下一阶段扩张 |

repository governance exception 存续期间只允许 `CI green → 用户人工批准 exact SHA → immutable VM deploy`，禁止 main merge 后无人审核自动上线。公司归属/例外、第二管理员、2FA/恢复、正式 reviewer、公司 deploy credential 和 maintenance window 等人类事项必须真实关闭或继续列为 exception，不能由代码生成 PASS。

任何情况下均禁止：

- PostgreSQL 失败后 silent fallback SQLite；
- dual writer、dual runner 或未声明 shadow write；
- 把 PR 临时 merge SHA 部署到 VM；
- 在 current/运行 release 内原地修补；
- 把同机盘符、调用方字符串或伪造 hash 当 off-VM/主机证据；
- 把任务启动、备份存在、页面可开或一次 restore 当成全系统健康；
- 把 secret、private key、live DB/WAL、用户内容或 papers 提交 public Git；
- 为过 gate 删除 evidence、跳过测试或修改 live SQLite；
- 在人工 HALT、批准范围或 recovery gate 之外继续扩张。

## 14. 后续任务规划必填清单

每个 Stage 4/5 后续 design/plan 在进入实现前必须回答：

1. **身份**：批准的 exact SHA、manifest、migration/config、PR/push CI 如何绑定？
2. **authority**：哪个 unit、writer operation、transaction boundary 和 live backend 是唯一权威？
3. **runner**：实际 principal、task definition、lock、checkpoint 与旧 runner 停止证据是什么？
4. **paths**：哪些属于 immutable release，哪些是外置 data/content/runtime/credential/recovery？
5. **mutation**：operation identity、revision、uncertain response、大 batch 原子性如何验证？
6. **recovery**：target、recovery-set gap、continuous RPO、full RTO 分别是什么；恢复集是否真在独立故障域？
7. **health**：process、last-success、checkpoint、data freshness 和 alert delivery 如何区分？
8. **network**：VPN/SMB/remote host 的现场身份和动态 endpoint 如何验证？
9. **evidence**：schema、hash、UTC 时间、freshness、主失败与 cleanup 如何保存？
10. **tests**：定向、真实 rehearsal、CI、VM、终验和独立 reviewer 分别覆盖什么？
11. **cleanup**：引用集、保留集、dry-run、apply 和清理后核验是什么？
12. **approval**：当前只批准 merge、deploy、enable/cutover 还是 stage exit；哪些操作仍明确禁止？

任一问题没有可复核答案时，计划必须把它列为 blocker 或显式非目标，不得用“后续补充”默认为 production 可接受。
