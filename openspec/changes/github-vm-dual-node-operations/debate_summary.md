# DeepSeek V4 Flash 架构交叉审核摘要

> 首次审查日期：2026-08-03  
> 首次审查轮次：2 轮；未进行第三轮，因为前两轮已显示同一前提偏差，继续扩张没有信息增量。  
> 数据边界：只发送脱敏架构摘要；未发送 key、Cookie、个人信息、数据库内容、论文原文或未批准材料。

## 第一次架构审查（保留原记录）

## 第一轮

DeepSeek 主张把系统定义为 local-first、多 VM 离线写架构，以每节点 SQLite 为事实源、Git 传输 change-set、PostgreSQL 作为汇聚查询库，并继续建设 outbox、CAS 和数据库文件/SQL 的 Git 回滚。

Codex 拒绝。项目事实是一个本地开发/研究工作站和一个生产 VM，本地不要求离线写入生产数据；Git 明确不得承载 live rows、SQLite、SQL 事件或数据库回滚。该建议会重新引入本次重构要删除的双事实源和自建复制系统。

## 第二轮

Codex 明确纠正节点、事实源和禁止事项后，DeepSeek 仍建议 SQLite dev 双轨、自动同步、通用方言适配以及未要求的 PostgreSQL 主从和 Docker 化。

Codex 再次拒绝。SQLite dev/PG prod 的长期双方言会让生产语义无法在开发期真实验证；自动同步违背唯一 writer 和不长期双写；主从、Docker 和固定周数没有来自当前代码、恢复目标或基础设施的证据，属于范围扩张。

## 第一次审查接受的意见

唯一接受的实质提醒是：如果 PostgreSQL 与 Viewer/任务 VM 共置，应用和数据库仍处于同一故障域，不能称为高可用。新版设计因此明确：

- 共置不能被描述为高可用；
- 共置切 production 前必须验证 VM 外备份、自动启动、正常关机、crash recovery 和空机 restore。

第二次人工架构审查进一步基于当前规模、可接受停机和运维经验修正了“必须长期独立”的倾向：共置可以是满足 RPO/RTO 后的 production 候选；只有恢复、隔离、维护、资源或多节点条件触发时才要求拆分。

## 相较第一稿的实质变化

- PostgreSQL 从“未来并发上升后的二期选项”改为明确长期目标；
- SQLite 从长期生产事实源改为迁移期状态；第三轮进一步纠正早期“只读回退候选”的宽泛措辞：S3/S4 只能作为迁移基线、审计档案和有限修复材料，不是默认 production rollback target；
- 删除长期四库 snapshot/change-set/CAS 和用户内容 Git 事件复制；
- 保留并强化研究 publisher、revision/audit、任务 checkpoint 和 restore test；
- 拆分 Git bootstrap、main、VM deployment、task cutover 和 database cutover 门槛；
- 增加本地独立 dev/test PostgreSQL 和 VM 停机补漏设计；
- 生产 PostgreSQL 共置/分离成为明确人工决策，而不是被默认隐藏。

最终方案由 Codex 基于 live 代码、schema、测试和任务配置独立负责，没有把 DeepSeek 输出直接复制到正式文档。

## 第二次架构审查（本轮追加）

> 日期：2026-08-03  
> 实际轮次：2 轮；未进行第三轮，因为两轮都没有提供超出 Codex 草案的有效架构增量。  
> 发送范围：仅包括 SQLite 回退状态、cutover unit、publisher 并发、expand–contract、runner/存储两轴、稳定身份、单域恢复、RPO/RTO、仓库治理和内容仓库状态的脱敏摘要。

### 第一轮

Codex 在独立审计 124 个直接 SQLite 连接、六个 `ATTACH` 文件、现有 publisher 和人工写路径后先形成修订草案，再请求 DeepSeek 只反驳数据丢失、双 writer、错误恢复和文档矛盾。返回内容偏离约束，发明了 Redis、DNS/load balancing、固定批量/周期等项目不存在的设施，并把实现细节当作架构门槛。

Codex 全部拒绝这些意见：它们没有来自 live 代码、节点事实或 RPO/RTO 的证据，会扩张本轮范围，也没有指出草案中真实的状态机冲突。

### 第二轮

Codex 进一步把已修订的十项架构边界压缩成结构化问题，并明确禁止发明节点、双写、Docker、主从和固定周期。DeepSeek 返回九项所谓缺口，但其中八项只是复述输入中已经明确存在的设计；例如再次要求 expected revision、expand–contract、RPO/RTO、2FA 和 `RESERVED-UNUSED` 定义。其余建议把 cutover unit 错定为 PostgreSQL schema、把 legacy mapping 强制成 UUID，并错误声称方案使用“SQLite 本地开发 + PostgreSQL 生产”。这些都与本轮明确边界冲突。

Codex拒绝：

- cutover unit 不能固定为 schema，它由完整事务和业务语义决定；
- 稳定身份不等于所有对象 UUID 化；
- 本地目标是独立 dev/test PostgreSQL，SQLite 只做迁移兼容；
- “短期 token”“必须 PITR”等实现选项应由权限审计和 RPO/RTO 决定，不应在架构稿无证据写死。

没有从第二轮接受新的实质架构意见。停止第三轮的原因是连续两轮都没有信息增量，继续调用只会重复已写入的门槛或扩张系统。

### 本轮文档发生的实质变化

- 用 S0–S4 状态明确 PostgreSQL 新写入前后的 SQLite 角色，区分 rollback、restore 和 forward fix；
- 用业务 `cutover unit`、权威后端矩阵和跨域事务图替代按文件/按 schema 的机械迁移；
- 恢复 publisher 与人工内容的 expected revision、幂等、stale conflict 和依赖簇原子性；
- 增加 expand–migrate/backfill–transition–contract 和 code-only rollback 前提；
- 分离数据后端与任务 runner 两条迁移轴；
- 强化稳定业务身份和 legacy mapping，但不强制 UUID；
- 增加 RPO/RTO 分类和单域旁路恢复；
- 把共置改为非 HA 的可接受 production 候选，并用触发条件决定是否拆分；
- 把个人仓库公司控制权设为 production gate；
- 把内容仓库固定为 `RESERVED-UNUSED`。

## 第三次架构审查（本轮追加）

> 日期：2026-08-03  
> 实际轮次：2 轮；未进行第三轮，因为第二轮后没有剩余的具体合同矛盾，继续调用只会重复或扩张实现。  
> 脱敏输入范围：cutover unit 唯一 ownership、S2→S3 水位、target/measured RPO/RTO、本地 runner 临时状态、环境事实、`ATTACH` 故障语义、备份注册表和阶段 1 权限。未发送 key、Cookie、凭据、数据库内容、论文原文、用户内容或未批准资料。

### 第一轮：状态机和恢复边界反驳

Codex 先基于本地代码、四库 journal mode、计划任务和运维文档形成第三轮修订草案，再要求 DeepSeek 只检查双 writer、双 runner、错误回退和不可证明状态。

DeepSeek 返回中，以下意见被拒绝：

- 凭空假设 target RPO/RTO 为 3 秒和 4 秒；本方案没有设定任何具体数值，目标仍需用户按数据类别批准。
- 假设存在 SQLite→PostgreSQL 异步复制、同步复制、CDC、备用 VM 和自动 failover；这些都不是当前项目事实或已批准设计。
- 建议分布式事务、集中配置服务和额外缓存失效系统；这是超出本轮的小范围合同修订。
- 要求把 SQLite 与 PostgreSQL 组成一套一致备份；S3/S4 的权威是 PostgreSQL，SQLite 仅保留为基线和修复材料，不应伪装成共同 live 恢复点。

部分接受的提醒是：切换前必须明确停写、源末水位、目标首个正式提交和 uncertain response；`ATTACH` 在 WAL 条件下不能被描述成无条件跨文件强原子。这些内容原已在草案方向中，本轮把证据字段和保守判定写得更明确。

### 第二轮：跨文件一致性检查

第二轮只发送 A—I 的合同摘要。DeepSeek 错误地把 S2 理解成 SQLite 与 PostgreSQL 都可能是 writer，并据此构造 A/B、B/E 冲突；也把阶段 1 Git 权限与 runner owner 混为同一 ownership。这些判断被拒绝，因为文档中的 ownership 分别属于数据切换、任务运行和代码仓库治理三个不同对象。

第二轮仍带来两项低成本表述改进：

- 接受：明确写成 S2 中 PostgreSQL 是唯一指定 writer，SQLite writer 已停止并冻结；验证写只通过 PostgreSQL，不能被解释成双后端。
- 部分接受：每个 cutover unit 必须列明包含或依赖的数据类别，逐类满足 target RPO/RTO；不能用宽松类别覆盖严格类别，也不能把当前 SQLite `backup/latest` 当成 PostgreSQL 目标达标证据。

关于 publisher stale conflict 与 S2 uncertain response“是否同一机制”的建议被拒绝为概念混淆：前者处理业务版本并发，后者处理提交结果不确定；它们都可使用稳定身份/幂等身份查账，但不能合并成一个状态。

### 本轮实质变化与停止原因

- cutover unit 增加唯一 owning unit、dependency、重叠检查、责任人和人工边界变更合同；
- S2 明确为 PostgreSQL 单 writer 的短时栅栏，并增加 epoch、双端水位、验证写和 uncertain-response 保守收口；
- target RPO/RTO 前置到阶段 3 末/阶段 4 前，measured RPO/RTO 后置到阶段 5 真实恢复验收；
- 本地 runner 连接 production PostgreSQL 被限定为有 owner、权限和退出条件的临时状态；
- 运维文档区分当前解释器/Interactive 任务事实与未来 lockfile/服务身份目标；
- 备份注册表区分 SQLite 历史恢复材料、迁移基线和 PostgreSQL 目标恢复合同。

第二轮后剩余意见要么已由现有合同覆盖，要么源自错误前提，没有新的未闭环矛盾，因此停止在两轮。
