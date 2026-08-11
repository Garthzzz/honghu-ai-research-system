# Stage 4 加速执行设计

## 1. 授权与不可越过边界

用户于 2026-08-12 授权连续推进 Stage 4 production-readiness：允许修复并合并 PR #9、建立 production PostgreSQL 基础设施、把 cutover unit 推进到 S1 或 migration-ready，并建设生产备份、WAL 与恢复工具。该授权不包含任何 unit 进入 S2/S3，不包含 production writer/backend、Viewer 8080、计划任务或 runner 切换，也不允许停止 SQLite 正式 writer、双写、shadow write、silent fallback 或向 PostgreSQL 写入正式业务 mutation。

整个执行期间，tracked application route 必须保持 SQLite authority；production PostgreSQL 在 S1 只承载 migration schema、只读 source baseline 的 backfill、reconciliation 和可丢弃验证数据。任何无法证明属于迁移/验证的 PostgreSQL 写入均视为越权。

## 2. 执行工作流

### 2.1 PR #9 收口

先把 recovery evidence 从“本机 restore 后复制 base backup”改成完整 recovery-set 合同：

- recovery set 同时包含 base backup、到目标水位所需 WAL、manifest、逐 artifact hash、来源/目标/故障域身份和目标恢复水位；
- base backup 完成后提交稳定 sentinel，归档包含该提交的 WAL；
- off-VM restore 只从保存后的 recovery set 复制出可变 restore workspace，restore command 只指向该 recovery set 的 WAL；
- recovered sentinel、recovered LSN/时间和 target watermark 决定 measured RPO，真实计时决定 RTO；
- off-VM storage identity 必须从实际路径/存储端点派生并与来源主机/故障域比较，调用方字符串只可作期望值，不能单独构成证明；
- base/WAL 缺失、hash/manifest 篡改、sentinel 未恢复、same-host/fake-host/copy mismatch、本地 artifact 混用均 fail-closed。

最终 evidence identity 分开记录核心实现提交与最终 PR/governance head、tree、push/PR run 和 artifact hashes，避免用早期 CI 冒充最终 PR 身份。完成本地/真实 PostgreSQL/CI 验证后合并 PR #9。

### 2.2 Production PostgreSQL bootstrap

若没有 Codex 可用的 VM 安全执行通道，不把该外部条件扩散成所有工程的阻塞，而是生成一个幂等、fail-closed、一次启动的 `Stage4-Production-PostgreSQL-Bootstrap` 现场执行包。它负责：

1. preflight 生产端口、资源、磁盘、现有服务和禁止对象；
2. 校验固定 PostgreSQL 17.x binary 来源与 hash；
3. 安装正式 Windows service、data/WAL/archive 目录和自动启动；
4. 配置 TLS、最小监听范围和防火墙；
5. 创建一个主要 database、逻辑 schema 与 migration/reader/unit-writer/controller/audit/backup 角色；
6. 把随机生成的隔离凭据写入 Windows Credential Manager，验证 rotate/revoke/break-glass 合同且不写日志；
7. 验证 start/stop/crash recovery、容量、连接、WAL 和日志；
8. 建立 base backup、WAL archive、whole/side/authority restore 工具和 evidence；
9. 失败时保留 primary/cleanup evidence，不修改 8080、任务、SQLite route 或 production runner。

bootstrap 只建立数据库平台，不执行业务 backfill 或 S2。现场 evidence 原文、凭据、证书私钥、backup/WAL 保持 Git 外；Git 只保存脚本、测试、脱敏 identity 和 runbook。

## 3. S1 的统一语义

S1 的唯一 production authority/writer 仍是 SQLite。一个 unit 只有同时具备以下内容，才可标记为 S1：

- production PostgreSQL migration schema 与最小 ACL 已应用；
- 在一个一致 SQLite source snapshot 上完成 backfill；
- stable identity/legacy mapping、源/目标 watermark、计数、关系、状态机和业务不变量完成对账；
- 必需的 reader/adapter 只读或显式非正式连接验证通过；
- authority-control ledger 明确记录 S1、SQLite authority、PostgreSQL 非正式数据可放弃；
- migration、source、target 和 evidence identity 绑定同一 application/config 环境；
- 没有必须保留的正式 PostgreSQL mutation，也没有 SQLite writer fencing。

`user_content_notes` 是首个真实 S1 unit；即使 source 为空也执行空集 reconciliation。其他 unit 可在 production bootstrap 尚未现场执行时完成 migration-ready：schema、ACL、snapshot/backfill/reconciliation tooling、watermark/catch-up 和恢复合同齐备，但不得伪称已经在 production PostgreSQL 完成 S1。

## 4. Unit 推进策略

沿冻结顺序推进：

1. `user_content_notes`
2. `shared_identity`
3. `financial_data`
4. `research_publication`
5. `dynamic_intelligence`
6. `operations_governance`
7. `investment_hypotheses`
8. `opportunity_lens`
9. `sentiment_analytics`

每个 unit 使用专属 manifest 定义 owning tables/operations、dependencies、源 snapshot、stable mapping、迁移 schema、ACL、backfill、watermark、delta catch-up、reconciliation 与 recovery class。共享执行框架只提供一致快照、copy ledger、hash、水位和验证原语，不替代 unit-specific 业务不变量，不发展成长期 SQLite/PG 同步或双写。

普通行增长只触发基于稳定水位的增量追平；只有 schema、writer、transaction boundary 或 ownership drift 才重新打开设计审查。上游 dependency 未达到 S1 时，下游可以完成 migration-ready，但必须把未满足 dependency 明确保留为 blocker。

## 5. Identity mapping 收口

mapping 审核继续使用单一 query-only SQLite transaction snapshot。公司 mapping 分为：

- ticker+venue 高置信自动确认；
- 用户已明确批准的 alias；
- 证据可复核的 explicit override；
- name/market fallback。

fallback 通过 research、financial、sentiment/dynamic 只读身份、证券代码、市场和标准化名称交叉验证；能形成唯一证据链的升级为机器确定映射。只有冲突、缺 venue、跨主体同名或证据不一致项进入最终人工清单。Codex 不写 cutover-level approval。

## 6. Recovery 与最终 verifier

production recovery evidence 分别绑定：binary/service/host、TLS/network、roles/credentials、source baseline、target snapshot、base backup、WAL recovery set、whole restore、side restore、authority restore 和 off-VM storage identity。off-VM 必须是不同主机或经批准对象存储的可验证故障域；同机盘符永远失败。

最终 verifier 打开并复算 evidence 本体，交叉验证 application commit/tree、migration/config SHA、环境和有效时间、route、PostgreSQL host/service/system identifier、source/target watermarks、mapping、backup/WAL/restore、repository governance 和人工 cutover decisions。boolean、引用文本或伪 hash 不能变成 ready。

## 7. 终止条件

只有在全部可自主工程完成后才 HALT：

- 若 production PostgreSQL、真实 off-VM 恢复和全部首单元 S1 现场证据齐备，状态为 `READY FOR USER S2 DECISION`；
- 若安全 VM 执行通道、真实 off-VM failure domain 或必须由公司管理员完成的治理仍缺失，状态为 `PRODUCTION READINESS BLOCKED`，但必须先完成所有不依赖这些外部条件的 migration-ready 工程。
