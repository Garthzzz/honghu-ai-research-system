# 阶段 3：live 增量对账执行计划

## Gate 0：设计冻结

- [x] Codex 独立复核 live/Git/备份/SQLite 事实与本设计。
- [x] 把不含 secrets、数据库行、papers、用户内容的设计摘要交给 DeepSeek V4 Flash 独立反驳。
- [x] Codex 逐条接受、部分接受或拒绝，最多三轮；连续无信息增量时停止。
- [x] 将实际 review 与 revision 追加到 `debate_summary.md`。
- [x] 设计冻结前不复制代码、不刷新备份、不重建 migration evidence。

**退出条件：** 分类、三方合并、备份、双层 inventory、复验和失败回退合同没有未闭环冲突。

## Gate 1：变更前安全副本与基线

- [x] 记录 live 8080/18080、四库 schema/计数/哈希、Stage 3 branch/PR/checks 和 Git 状态。
- [x] 按旧/新归档与 staging 峰值检查磁盘空间；空间不足即 HALT。
- [x] 使用现有 backup API 工具在 `D:\quant` 创建本次临时外部安全副本并验证四库一致性。
- [x] 生成 live delta 分类清单；研究内容和不确定项保持 Git 外。

**退出条件：** 外部副本可验证、旧 `backup/latest` 未被覆盖、live 服务与数据库未受影响。

## Gate 2：选择性三方合并

- [x] 手工移植 Viewer 行业分组、估值正文和相应模板/测试。
- [x] 合并 required-cache screenshot 排除，同时保留 Stage 2 portable/Windows path 合同。
- [x] 合并 cleanup 歧义 basename 修复和测试。
- [x] 合并配置注释/合同，不复制研究正文、run 输出或一次性研究 producer。
- [x] 对每个修改文件执行针对性测试和 `git diff --check`。

**退出条件：** 新 live 通用功能存在，Stage 2 release/read-only/runtime 能力无回归，禁止资产未进入 Git。

## Gate 3：迁移证据重建

- [x] 重建 deployable SQLite dependency inventory。
- [x] 生成 Git 外 live-only research producer addendum，记录哈希、writer 和事务边界。
- [x] 生成 Git 外 aggregate manifest，固定两个清单的 SHA、扫描根/截止时间、合并计数和“production sequencing 必须同时提供”的合同。
- [x] 更新 ownership overrides/registry，检查表、writer 和事务边界唯一 ownership。
- [x] 更新依赖图、阶段 3报告中的计数、证据 SHA 和新增风险。
- [x] 复核 target RPO/RTO 提案是否因新数据类别而需要修订；状态仍保持 `pending_human_approval`。

**退出条件：** 当前 live 的可部署与排除写路径均可审计，旧 956/387 统计不再被错误当作当前事实。

## Gate 4：非生产复验

- [x] 运行完整本地 compile/test/contract。
- [x] 启动隔离 PostgreSQL dev/test，重跑 analyst-note migration、幂等/revision/audit、冲突和 side restore。
- [x] 证明复验前后四套 live SQLite 不变，并停止/清除隔离 test database 与 listener。
- [x] 运行 OpenSpec strict、Git boundary、secret/path/large-file、SQLite ratchet 和 public exposure review。

**退出条件：** 所有安全门禁通过；失败项不得以 skip、xfail、阈值放宽或 live 修改掩盖。

## Gate 5：备份刷新与提交前终验

- [x] 原子刷新 `backup/latest`，版本说明指向本次 live 增量与阶段 3 对账。
- [x] 核验 archive SHA、ZIP CRC、成员清单、四库 snapshot、integrity 和 foreign keys。
- [x] dry-run 后仅按受限工具清理本次临时外部副本。
- [x] 再运行一次最终 staged inventory、`git diff --check`、关键测试、inventory/ownership 和 OpenSpec strict。
- [x] 生成最终 completion report/public exposure review，并记录 staged Git tree SHA 与全部证据 hash。

**退出条件：** 提交前证据绑定同一工作树，live 服务/数据库/任务未变，备份可验证。

## Gate 6：提交与远端验证

- [x] 形成范围清楚的 commit，push 当前阶段 3 分支，保持 PR #5 open。
- [x] 验证 commit tree 等于已验收 staged tree，并在 Git 外记录 `tree → commit → checks` identity；不相等则作废并重验。
- [x] 核验 PR head、push/PR required checks 和 artifacts 绑定最终 SHA。
- [x] 更新状态为“阶段 3 工程证据已重绑定，等待 target RPO/RTO 与 HALT 人工批准”。
- [x] HALT；不合并 PR #5，不进入阶段 4。

**人工未决：** target RPO/RTO、阶段 3 退出、PR #5 是否合并及任何阶段 4 production 权限。
