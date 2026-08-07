# 阶段 3 完成报告（待人工验收）

## 状态

工程实施与非生产试点已完成，当前等待人工审查。未自行批准阶段 3，未进入阶段 4。

`target RPO/RTO` 仍为提案状态；它必须由用户人工批准后才能满足阶段 3 的全部退出条件，任何 production data cutover 在此之前继续禁止。

## 已完成

- 生成 operation-level SQLite dependency inventory；普通 DML、SQLite 专属语义、函数、surface、route、数据库引用和候选 unit 均可复核。
- 建立 134 个 live 表的唯一 ownership、956 条 writer operation 和 387 个事务边界 registry；重叠、未知 owner、漏表和虚构表检查均通过。
- 人工复核跨库 `ATTACH`、共享身份、财务 bridge、sentiment 只读身份依赖和 Viewer 多 mutation path。
- 建立显式 backend/transaction routing 合同，禁止 production backend 与 silent fallback。
- 建立 PostgreSQL 逻辑 schema/role 候选模型、稳定业务身份和 legacy mapping 合同。
- 建立 expand-only migration 和受控用户内容导出 schema。
- 在隔离 PostgreSQL 17.10 dev/test 完成 analyst-note 低风险试点、幂等/revision/audit/soft-delete、冲突、dump/restore 和 live SQLite 哈希不变验证。
- 提出按数据可补抓性和业务重要性分层的 target RPO/RTO，等待人工批准。

## 固定身份与验证结果

- 公开 PR：`#5`，工程复核 head（写本报告时）：`e8701562f5fa815adb4c7d85ce6d1b52fffe053e`；最终治理提交和 CI 仍以 PR 实际最新 head 为准。
- inventory 绑定实现提交：`48dc94035b3907468f762e88208279755db29a6b`。
- inventory：134 个 live 表、956 条 operation-level writer、387 个事务边界；ownership overlap、unknown owner、漏表和虚构表均为 0。
- 本地 core：581 passed、21 skipped、55 subtests；compile、SQLite ratchet 和 OpenSpec strict 通过。
- Git-external PostgreSQL pilot evidence SHA256：`29a75f79ebcc69af4af58fb365800f4f408ce9d8ad9205ea4810fefcacba70fd`。
- Git-external只读 live schema audit SHA256：`3aaab5f5207bd70ea23e4dc9694713f2a192f505d31b1e61a4188b00b4138337`。
- PostgreSQL 17.10 官方指向 binary archive SHA256：`ef9b1e5e23d2e8a83914ba13d9dc536a72210fba53fd1808ff1f7e06bb22b106`。
- 最新试点 migration SHA256：`333d8d5bd266b6bb70afd2444b5deca44f8a908f0e9cb00736031ebecf121f47`；migration 两次应用、payload-level 幂等冲突、NULL revision、stale revision、soft delete、audit 和旁路 restore 均通过。

原始 evidence 未提交公开 Git；上述 hash 只用于把人工复核绑定到本地只读/合成证据。

## DeepSeek reviewer

实际两轮后停止。第一轮要求把 operation ledger/lease 写入 live SQLite，并错误声称脚本使用 5432；第二轮仍把函数放错文件、否认公开代码已有的 migration SHA、soft delete、NULL revision 和 test-target gate，同时虚构 Docker/Redis/CDC 改动。两轮均没有可复现的有效新增问题，因此拒绝并停止第三轮。Codex 独立发现并修复了 payload-level 幂等比较、NULL revision 绕过和 Windows `pg_ctl` capture-pipe 生命周期问题；外部 reviewer 不是通过依据。

## 明确未执行

- 未安装、启动或创建 production PostgreSQL；测试集群不是 Windows 服务且已停止。
- 未修改或迁移 live SQLite；未运行 production backfill。
- 未修改 Viewer production、8080、计划任务、runner 或 writer authority。
- 未双写、未配置 silent fallback、未进入 S1—S4 production 状态。
- 未提交数据库、dump、papers、用户内容、secret 或原始 live evidence。
- 未进入阶段 4。

## 人工审查重点

1. cutover registry 的 owner/dependency 和 Viewer operation-level overrides；
2. user-content pilot 是否适合作为首个 production 候选；
3. target RPO/RTO 是否接受或需要调整；
4. 下一单元排序是否接受；
5. 阶段 3 是否退出。即使退出，也不自动授权阶段 4 production cutover。
