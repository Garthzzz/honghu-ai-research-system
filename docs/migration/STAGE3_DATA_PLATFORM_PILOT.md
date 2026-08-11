# 阶段 3：数据依赖、切换单元与 PostgreSQL dev/test 试点

## 1. 边界与结论

本阶段不迁移生产数据。当前四套 SQLite 仍是唯一生产事实源，所有切换单元均为 `S0 / sqlite_transition`。阶段 3 建立的是可审计清单、边界和非生产试点，不是 production PostgreSQL。

机器清单分为两个互相绑定的层次：公开仓库中的 deployable inventory，以及 Git 外 live-only research producer addendum。前者覆盖 tracked Python 中的连接、`ATTACH`、`PRAGMA`、事务语义、普通 DML、函数级 writer operation、Viewer route、任务/ingest surface 和候选切换单元；后者记录仍在活动目录、但因研究内容和公开边界不能纳入 Git 的一次性 producer。aggregate manifest 固定两者的内容身份、合并计数和冲突检查。后续 production sequencing 缺少任一层都不完整。静态识别不能替代人工事务审计，所以所有写路径继续标记为需人工复核。

2026-08-11 最终复验后的合并视图为 287 个依赖文件、971 条 writer operation、392 个事务边界和 6 个 `ATTACH` 文件；deployable 子集为 281/958/388/5，Git 外 addendum 为 6/13/4/1。新增的一份依赖文件和一条 writer/事务边界来自 inventory 自身的测试 fixture，不是 production writer。134 个业务表的唯一 ownership 检查、operation/transaction 重复检查和未知 owner 检查均通过。

最终 registry 的硬约束是：

- 每个 live 可写表只有一个 owning cutover unit；
- 每条 writer operation 和完整事务边界只有一个 owner；
- 同一进程可以包含多个 unit 的 mutation path；
- dependency 不等于 ownership；边界变化必须人工复核；
- 任一时点每个对象只有一个 authoritative backend 和一个 writer；
- PostgreSQL 失败不得静默回落 SQLite；一个业务事务不得在两个后端分别提交后声称原子完成。

## 2. 依赖图和高风险边界

```text
shared_identity
├─ research_publication
│  ├─ investment_hypotheses
│  └─ opportunity_lens
├─ dynamic_intelligence
│  ├─ operations_governance
│  ├─ investment_hypotheses
│  └─ sentiment_analytics
├─ financial_data
│  └─ opportunity_lens
└─ user_content_notes   ← dev/test 首个试点
```

人工代码审计识别出三类不能按 SQLite 文件机械切换的边界：

1. `ensure_listed_company_profile` 同时维护研究库公司身份与财务证券身份，属于共享身份事务，不得拆成两个后端提交。
2. `refresh_company_financial_metrics` 同时写结构化财务观测和研究库 legacy 聚合，必须先消除 legacy bridge 或共同切换。
3. sentiment 写路径会只读关联研究身份；Viewer 一个进程内同时包含笔记、thesis、hypothesis、event 和 researcher 等不同 mutation operation，owner 必须按函数/事务而非进程划分。

`ATTACH` 只说明代码把操作组织在同一 SQLite transaction scope。它不被表述为跨文件、任意 journal/WAL 和崩溃点下的无条件强原子保证；迁移前仍须以业务事务边界重新验证。

## 3. 数据访问与 PostgreSQL 目标边界

目标优先采用一个主要业务 database、按逻辑 schema 和角色分域。`config/migration/postgresql_domain_model.json` 定义候选逻辑域和最小权限合同。只有容量、权限、故障域或独立扩容证据成立时才物理拆库。

`tools/data_platform/routing.py` 建立最小显式路由合同：调用者必须声明 cutover unit、backend、writer operation 和 transaction boundary；Stage 3 明确拒绝 production PostgreSQL，也不存在 fallback backend。这不是把 SQL 字符串机械替换为 PostgreSQL，而是先固定事务和权威边界。

稳定身份分为三层：

- 可跨环境发布/审计的对象使用稳定业务键；
- PostgreSQL 内部可继续使用 surrogate key；
- 迁移期通过 `operations.legacy_identity_mapping` 保存 SQLite database/table/id 到稳定键和目标对象的可验证映射。

不要求所有对象统一 UUID，也不得让单个 SQLite 自增 ID 成为跨域永久身份。

## 4. migration 合同

首个 migration 只做 expand：增加 `user_content`、`operations`、`audit` schema，增加 analyst note、幂等 ledger、revision audit 和 legacy mapping。没有 `DROP`、破坏性 `ALTER` 或生产数据 backfill。

后续固定为四步：

1. expand：增加旧代码仍可兼容的新结构；
2. migrate/backfill：迁移并对账历史数据；
3. application transition：在明确兼容窗口切换 reader/writer；
4. contract：后续独立批准 release 才移除旧结构或收紧约束。

code-only rollback 只在 schema 仍兼容旧代码时成立。forward-only migration 必须显式标记，并分别说明 backup、verification 和 recovery；不能用应用回滚代替数据库恢复。

## 5. 低风险试点与真实结果

选择 `analyst_note` 是因为它有真实 Viewer mutation path，而当前生产表为空；这使试点可以验证业务合同而不导入或修改 live 数据。共享身份、财务桥接和 sentiment 均因事务/体量风险排除为首个试点。

隔离环境使用 PostgreSQL 17.10 Windows binaries，不注册服务，仅监听 loopback 非标准端口。测试数据库名称有固定 dev/test 前缀，工具拒绝 `0.0.0.0`、5432 和非测试库名。

真实演练完成：

- migration 连续应用两次且 identity 一致；
- create、uncertain-response 幂等重试、update、stale revision 拒绝、幂等键冲突拒绝、soft delete；
- 最终 revision 与 audit 链一致，禁止 silent last-write-wins；
- `pg_dump` 后恢复到旁路 test database 并复核记录、revision 和 deleted 状态；
- 四套 live SQLite 在演练前后整文件 SHA256 一致；
- 测试 database 已删除，PostgreSQL 进程与 loopback listener 已停止。

原始演练 evidence 保持 Git 外；Git 只保存可重复工具、migration、测试和非敏感结论。

## 6. 用户内容导出与 RPO/RTO

`config/migration/user_content_export.schema.json` 只定义低频受控导出：稳定键、revision、soft-delete、payload hash 和水位。它不是实时 Git 复制，不把用户内容写入应用仓库。

`config/migration/target_rpo_rto_proposal.json` 把 migration/cutover authority control、不可补抓的人工作品/发布 ledger、财务修订、动态任务状态、sentiment raw/aggregate 和 papers/evidence 分开提出目标。权威切换类覆盖 S0—S4、唯一 writer/backend、cutover epoch、水位、路由、验证写、uncertain commit 和审计 ledger；已确认状态要求零丢失，恢复并独立验证前必须继续阻断 production writes，不能并入普通 task/checkpoint 目标。用户已于 2026-08-11 批准 v2 target；该批准不代表 measured RPO/RTO 已达到，也不授权 production data cutover，阶段 5 的真实 restore 才能产生 measured 结果。

## 7. 下一切换单元建议

若本阶段获批，下一步仍不应先迁 sentiment。建议顺序是：

1. 完成 `user_content_notes` 的生产前设计审查、身份映射和备份合同；
2. 再处理 shared identity，使后续域不再复制公司/证券身份；
3. research publication 与 financial 依据 bridge 重构进度排序；
4. opportunity 在依赖稳定后；
5. dynamic/operations 根据 runner/checkpoint 合同；
6. sentiment 最后，除非后续 inventory 证明可拆出更小、独立的 ledger 单元。

这个排序是下一阶段建议，不是 Stage 4 授权。
