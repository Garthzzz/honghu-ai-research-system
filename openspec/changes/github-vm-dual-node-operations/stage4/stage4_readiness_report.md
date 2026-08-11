# 阶段 4 设计、准备与隔离演练报告

## 1. 结论

本轮授权范围已完成：Stage 4 总体实施方案、cutover unit 顺序、首单元详细合同、additive migration/权限模板、隔离 PostgreSQL 演练、production topology/backup/monitoring 前置和两轮 DeepSeek 复核均已形成。

当前结论是：

> **非生产设计与演练 PASS；首个 production cutover 仍 BLOCKED。**

因此尚不具备申请 `user_content_notes` 实际进入 production S2 的条件。本轮 HALT 后应先关闭应用 adapter、稳定身份全量映射、写接口安全、production PostgreSQL 现场拓扑、VM 外备份/restore、仓库 production authority 和维护窗口批准等 gate。

## 2. Live 与 Stage 3 一致性

2026-08-11 的只读 final drift check 结果：

- 四套 SQLite schema 无新增、删除或变更；审计窗口前后文件 SHA256 不变。
- deployable inventory：281 个文件、958 条 writer operation、388 个 transaction boundary。
- Git 外 live-only addendum：6 个文件、13 条 writer operation、4 个 transaction boundary。
- aggregate：287 个文件、971 条 writer operation、392 个 transaction boundary；134 张业务表仍为唯一 ownership。
- deployable、live-only source path、writer operation、transaction boundary 均无 drift。
- research/dynamic/sentiment 的普通行增长未被误判为 migration-boundary drift。
- `research.db.analyst_note` 仍为 0 行。

最终输入 identity：deployable `a48fb886…1df4`、live-only `8d0b8fc4…c8dd`、aggregate `13529bd9…2151`。原始证据继续留在 Git 外。

## 3. Cutover 顺序

生产单元顺序冻结为：

1. `user_content_notes`
2. `shared_identity`
3. `financial_data`
4. `research_publication`
5. `dynamic_intelligence`
6. `operations_governance`
7. `investment_hypotheses`
8. `opportunity_lens`
9. `sentiment_analytics`

排序依据是 dependency、实际 transaction/writer 复杂度、不可重建性、持续 runner、数据量和恢复难度，不按 SQLite 文件机械迁移。bridge、fixture、legacy one-shot 和 reader transition 不成为独立 production authority。

## 4. 首单元选择与原型纠偏

选择 `user_content_notes` 的原因是 0 live row、2 条实际 mutation path、无 scheduler 且已有 revision/audit 基础。它只是风险最低的首选，不是零风险。

本轮人工审计纠正了 Stage 3 原型不能直接生产使用的事实：

- SQLite `q_number` 是文本而非整数；
- theme legacy id 是文本；
- title 可空；
- 当前 API create 无 expected revision/idempotency，delete 是硬删除；
- SQLite 自增 entity/note id 不是跨环境稳定身份。

新的 0002 不改 live SQLite、不改写 0001 migration，而是 additive 增加 `q_label`、文本 legacy entity id、stable entity key、legacy note/time、兼容 read view、authority/audit/mapping 和 v2 mutation contract。

## 5. 非生产演练结果

在 PostgreSQL 17 loopback、非 5432、测试库名前缀环境实际通过：

- 0001/0002 各重复应用两次；
- S1 放弃回到 S0；
- S2 verification 后在无 formal write 的证据下回到 S1；
- 首个 formal mutation 与 S2→S3 authority revision 同事务；
- uncertain-response 使用同一 idempotency identity 重放；
- stale revision 冲突、update、soft delete；
- Q6、文本 theme id、nullable title、legacy 原始时间兼容；
- writer 无 base INSERT，reader 只读 active view，controller 只有首单元 wrapper；
- writer identity 同时匹配 authority row 与 `session_user`；
- pg_dump 到旁路库 restore 后 authority=S3、2 条 note、1 条 soft delete、Q6 legacy 行和 4 条 authority revision 均可核验；
- 演练数据库、角色和 listener 已清除；四套 live SQLite 前后哈希不变。

Git 外 rehearsal evidence SHA256 为 `e0383fac…6e3d`。这只证明 dev/test 合同，不是 measured production RPO/RTO。

## 6. S0—S4 与恢复边界

- S0/S1：SQLite 保持唯一 authority；PG 候选可以放弃。
- S2：短时 fence；SQLite mutation 停止，PG 只允许 verification。只有水位、audit、停写和人工批准证明零 formal write 才能恢复 SQLite writer。
- S2 uncertain：无法证明未提交即按 S3，以稳定 operation identity 对账。
- S3：第一条必须保留的 PG 正式业务写与 authority revision 原子提交；旧 SQLite 不再是 production rollback target。
- S4：观察期通过后旧 mutation path 永久 fenced/移除；旧文件仅作迁移基线和审计档案。

S3 后故障只允许 PG 前向修复、schema-compatible code rollback 或旁路 restore 后选择性修复。单域逻辑错误不得原地回退整个 production database。

## 7. Production 前置与剩余风险

尚未关闭：

1. production PostgreSQL 版本/资源/服务/网络/凭据现场决策；
2. VM 外备份、满足目标的 WAL/增量路径、整库与旁路单域 restore；
3. authority control 零 acknowledged loss 的真实恢复证据；
4. Viewer repository/adapter 接线并保持 S0 默认、无 silent fallback；
5. company/industry/theme stable mapping 全量冻结与验证；
6. create/update/delete/list API 兼容及 authentication/authorization/CSRF；
7. 应用仓库成为 production authority 的公司治理 gate；
8. maintenance window、operator/approver 和首单元 S2 单独授权；
9. S3 前向修复和 schema-compatible application rollback 的 adapter 级演练。

首期可考虑 PostgreSQL 与 Viewer/任务 VM 共置，但不能称为 HA；若实测恢复目标、资源或隔离不能满足，再以证据触发物理拆分。

## 8. DeepSeek review

共 2 轮。第一轮唯一有效增量是确认 Q 字段类型冲突，Codex接受问题但拒绝修改 live SQLite，改为 additive compatibility。其“uncertain 时回滚 SQLite”和“无证据强制 HA”与已批准合同冲突，拒绝。第二轮无 must-fix，所列 10 项几乎全部是已实现控制的重复误判，并虚构 Docker/CDC；无信息增量后停止第三轮。详细判断已追加到 `debate_summary.md`。

## 9. 确定性验收

- clean-core：597 passed、21 skipped、55 subtests；618 tests collected。
- Stage 4 定向测试：5 passed；真实 PostgreSQL rehearsal PASS。
- compile：PASS。
- tracked boundary：809 files、29,020,166 bytes，PASS。
- SQLite ratchet：PASS，无新增 debt。
- OpenSpec strict：PASS。
- `git diff --check`：PASS。

## 10. 本轮明确未执行

没有安装或启动 production PostgreSQL，没有创建 production database，没有修改 live SQLite 数据/schema，没有切换 writer/backend，没有停止 SQLite writer，没有进入 production S2/S3，没有迁移计划任务，没有切换 Viewer/runner，没有刷新或清理 backup，没有上传数据库/papers/用户内容，也没有进入 Stage 5。
