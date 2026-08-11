# 阶段 4：执行准备计划

## Gate 0：入口复核与设计冻结

- [x] 只读复核 live 四库 schema、文件身份、deployable inventory、Git 外 addendum 和 aggregate manifest。
- [x] 区分普通数据增长与 migration-boundary drift。
- [x] 独立排序 production cutover units 并选择首个准备单元。
- [x] DeepSeek V4 Flash 对脱敏设计进行第一轮反驳；Codex 独立接受、部分接受或拒绝。
- [x] 冻结首单元配置、S0—S4、fencing、reconciliation、recovery 和 topology 前置合同。

**退出条件：** 设计不把 Stage 3 原型误称 production-ready；没有 production 操作。

## Gate 1：首单元兼容与控制面准备

- [x] 为 `user_content_notes` 增加 additive、可重复的 dev/test migration；不得改写 0001 identity。
- [x] 通过新增文本 `q_label` 而不是修改 live SQLite 修正 Q 标签；补齐 nullable title、legacy id/原始时间、stable note/entity identity、legacy mapping 和 API compatibility 合同。
- [x] 建立 authority state、epoch、watermark、verification/formal write 分类和审计合同。
- [x] 让 S2 首个合法 create/update/soft-delete formal mutation 与 S3 authority revision 原子提交，并要求 operator、approval reference、expected state/revision 和 writer identity；无效 delete 不得推进 authority。
- [x] 以数据库约束和 controller wrapper 双重固定 S0—S4 backend/state invariant；S3→S4 保留 authority identity、formal watermark，并要求不可复用的独立批准引用。
- [x] 明确 shared identity 仍由 SQLite authority 管理期间的 mapping bridge：S2 冻结；S1/S3/S4 仅允许带 expected authority revision、source evidence、批准和审计的增量登记；未映射实体 fail-closed。
- [ ] 建立显式 backend route 和 operation-level writer fence；默认保持 SQLite/S0，production PG 路由必须双重显式授权。
- [ ] 对 create/update/soft-delete/list 增加 repository-level dev/test adapter 与 fail-closed 测试；不接通 production endpoint。

**退出条件：** 代码具备演练能力，但 production backend 仍不可选，live SQLite/Viewer 不变。

## Gate 2：隔离 PostgreSQL 演练

- [x] 仅使用 loopback、非 production 名称和隔离凭据启动 dev/test PostgreSQL。
- [x] 对空源与非空合成源分别执行 expand、backfill、mapping、count/field/invariant reconciliation。
- [x] 演练 S1 放弃、S2 在零正式新写下撤回，以及 S2 uncertain response 按 S3 幂等收口。
- [ ] 在应用 adapter 完成后补演练 S3 前向修复和兼容代码回滚；旁路单域 restore 已完成。
- [x] 验证 least privilege、无 DDL 应用角色、无跨单元写权限和无 silent SQLite fallback。
- [x] 生成 Git 外 rehearsal evidence，记录 migration/config/source/target/restore identity；测试库和 listener 完成后销毁。
- [x] 演练前后验证四套 live SQLite 文件身份不变。
- [x] 真实覆盖 S3→S4 正常路径，以及 wrong backend、missing/reused approval、writer drift 和 unmapped identity 的 fail-closed 路径。

**退出条件：** 所有状态与失败路径可复算，测试没有连接 production。

## Gate 3：恢复、监控和 production readiness 差距

- [x] 形成 production topology decision record，列出共置候选的资源、监听、角色、服务启动和拆分触发条件。
- [x] 形成 backup/recovery readiness checklist；不创建 production PG、不刷新 live backup。
- [x] 定义首单元监控、告警、authority audit 和 S3 后恢复决策树。
- [x] 明确 repository production authority、人工写接口安全、VM 外备份/restore 等尚未关闭 gate。

**退出条件：** 文档能区分“已演练”“待现场验证”和“production 禁止”。

## Gate 4：复核与提交

- [x] 运行完整 compile/test、OpenSpec strict、tracked boundary、secret/path/large-file、SQLite ratchet。
- [x] DeepSeek 对实现和演练摘要进行第二轮脱敏复核；Codex 独立 revision。
- [x] 更新 `debate_summary.md`，不复制外部模型原文。
- [x] 生成 Stage 4 completion/readiness report 与 final identity；原始 live/rehearsal evidence 留在 Git 外。
- [x] authority-control 实现提交 `8c5c5e58d9efb65827b23a08fd15801d7bd11757` 已推送到仍为 open/未合并的 PR #7；push run `31495248015` 与 PR run `31495252243` 的两个 required jobs 均绿色。后续治理状态提交不得改写该实现或复用旧 SHA 作为新实现证据，其自身 required CI 在最终 HALT 报告中按 GitHub 实际状态核验。
- [ ] HALT，等待用户决定是否批准首单元实际 production 执行；不得进入 S2/S3。

**本轮不会勾选：** `tasks.md` 中任何要求实际切换 production writer、产生正式 PG 新写入、完成 S3/S4 或稳定观察期的项目。
