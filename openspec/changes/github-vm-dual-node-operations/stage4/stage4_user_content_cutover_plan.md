# Stage 4 `user_content_notes` 生产切换执行计划

## Gate 0：设计冻结与 reviewer

- [ ] 复核 live 8080 listener/process family、PG、route、authority、mapping、backup 和 Git identity。
- [x] Codex 独立检查本设计；本轮 DeepSeek 对生产切换合同和“两份已验证恢复集”轮换各做一次脱敏复核，均返回 `pass`、无可复现 must-fix。Codex仍独立补上“新集合完整恢复通过后才删除第三旧集合”的确定性门禁和回归，不以外部 verdict 代替现场恢复。
- [ ] 运行 OpenSpec strict 和相关静态/单元测试；真实门禁失败不得进入下一 gate。

## Gate 1：异机恢复与 mapping

- [x] 在唯一 `industry_demo_backup_package` 根建立受限加密 recovery share；本机 `D:` BitLocker protection、加密 SMB、专用最小权限账户和仅允许 VM 地址的防火墙已现场验证。
- [ ] 生成新 base backup、sentinel WAL、manifest/hash；从 recovery set 独立 whole restore。
- [ ] 轮换到最多两份 validated set；第三份只在新份验证后删除。
- [x] 写入 Acacia、海光/海光信息、Sumitomo/住友电气以及既有 COHU、TER 的用户批准决定，重建 774 条 mapping/crosscheck/approval bundle；机器审计后人工待判项为 0。
- [x] 验证 mapping manifest 与 user approval、source snapshot、application commit 一致；原始 mapping 与批准 evidence 继续保持 Git 外，Git 仅保留规则和脱敏决定。

## Gate 2：S1 与生产切换前验收

- [ ] production PG 应用 domain S1 promotion，执行 backfill/reconciliation/ACL/adapter read。
- [ ] 建立两个最小权限 principal、session secret、runtime route/PG/security 配置，secret 仅进 Credential Manager。
- [ ] 构建 exact immutable 8080 release 和可回退 application package，不切换 authority。
- [ ] 复核 repository exception、operator=user-approved Codex、approver=user、maintenance window 和 S2 approval evidence。
- [ ] 冻结 SQLite final watermark、8080/PG/recovery identities，并做 Go/No-Go。

## Gate 3：受控 S2/S3 与 8080

- [ ] 精确停止旧 8080 analyst-note writer，证明无双 writer。
- [ ] S1→S2，记录 epoch/writer/approval/watermark；S2 只作短时栅栏。
- [ ] 启动 exact PostgreSQL-route Viewer；验证 health、TLS/auth/CSRF 与只读闭包。
- [ ] 首笔正式 mutation 与 S2→S3 原子提交；uncertain response 按 S3 幂等对账。
- [ ] 验证 SQLite 不再变化，PG authority/route/revision/audit 一致。

## Gate 4：上线、写入、多端和压力 loop

- [ ] VM 本机、开发主机和至少两个独立 session 的前端与 API 测试。
- [ ] create/update/delete/list、幂等、stale、CSRF、ACL、session/reload/tab 与错误分类。
- [ ] 有界并发、压力、连接池/资源/延迟监控与 PostgreSQL 不可用 fail-closed。
- [ ] 每轮修订后 Codex+DeepSeek review；最多三轮 DS，无增量提前停止。
- [ ] 完成修订后使用不同输入和交错顺序做独立终验；问题未闭环则循环，最多五轮。

## Gate 5：收口

- [ ] 稳定期后清理 obsolete failed packages、临时环境与测试对象，保留 audit 和最新两份恢复集。
- [ ] 刷新项目 `backup/latest`，验证四库快照与恢复登记。
- [ ] full core、targeted/browser、PG/recovery、compile、OpenSpec、boundary/secret/path、SQLite ratchet 全绿。
- [ ] push branch、PR required CI、合并和 main CI 全绿。
- [ ] 更新 tasks、debate summary、backup registry、runbook 与详细最终报告。
