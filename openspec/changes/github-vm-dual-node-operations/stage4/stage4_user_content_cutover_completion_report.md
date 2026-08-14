# Stage 4 首个切换单元生产执行报告

> 状态：`user_content_notes` 已进入不可直接退回 SQLite 的 S3。本报告只提交脱敏结论；数据库、恢复集、凭据、TLS 私钥、用户内容及 VM 原始 evidence 保持在 Git 外。

## 1. 执行范围与权威状态

本轮只切换 `user_content_notes`。正式 create/update/delete/list、revision、soft delete、audit 与 idempotency 已由 production PostgreSQL 承担；其余八个 cutover unit 未获得 S2/S3 授权。

- authority state：S3；authoritative backend：`postgresql_production`。
- authority epoch：由 Git 外 control-plane evidence 固定并审计。
- SQLite writer 已 fenced；旧 `IndustryViewer`、`IndustryViewer1` 服务已停止并禁用。
- PostgreSQL 已产生必须保留的正式写入，旧 SQLite 仅是迁移基线、审计档案和有限修复材料，不是 production rollback target。
- 没有 dual write、shadow write 或 PostgreSQL 失败后的 silent SQLite fallback。

## 2. PostgreSQL、恢复与身份

生产服务为 PostgreSQL 17.10 Windows service `HonghuPostgreSQL17`，使用固定端口、TLS、最小权限 reader/writer/controller/audit/backup 角色和 Windows Credential Manager 凭据。`user_content_notes` 的 migration、authority/control、revision/audit/idempotency、稳定身份映射与 writer identity separation 均已应用并记入 migration ledger。

进入 S2 前已完成 base backup、base 后 sentinel、目标 WAL、manifest/hash、另一故障域复制，以及仅使用该 recovery set 的 whole/authority/side restore。恢复集保留合同为最多两份已验证集合；同 VM 盘符不计作 off-VM，失败或未验证目录不计入配额。

774 条 company mapping 使用一致只读 SQLite transaction snapshot：399 条 ticker+venue 直接身份，278 条 fallback 经多库机器交叉核验，COHU alias 与 TER override 显式记录；最终四个例外已由用户批准并形成独立 approval identity。数据库文件 hash 只作诊断，不冒充事务快照身份。

## 3. S2→S3 与应用上线

writer fence 后，PostgreSQL 成为唯一指定 writer。首条必须保留的 formal mutation 与 S2→S3 authority revision、revision/audit/idempotency 和 first-formal watermark 在同一 PostgreSQL transaction 提交。之后 Viewer 重新加载 durable S3 route。

生产 Viewer 同时提供：

- 8080：兼容只读 HTTP；所有 mutation 在进入 payload/repository 前拒绝。
- 8443：TLS、认证、最小 ACL、CSRF、expected revision 和幂等 mutation。

应用 health 必须同时证明 exact commit、release manifest、S3、PostgreSQL backend、security ready、launch ID、health PID 与 listener PID。正式启动器使用受支持的 base Python 3.10 `-I -B -S`，只注入 hash-pinned site-packages；immutable release 显式包含 `AGENTS.md`，不再依赖 full repository，也不记录 Windows venv redirector 外层 PID。

## 4. 独立功能、浏览器与压力验收

本地最终代码门禁：777 passed、21 skipped、55 subtests；compile、OpenSpec strict、tracked boundary 与 SQLite dependency ratchet 全部通过。

真实生产验收包括：

- VM-local exact release、TLS、四库只读闭包和 authority probes；
- LAN 浏览器在真实行业公司页完成登录、create、唯一 list、soft delete 和截图审计；
- 第一轮 16 并发、96 次创建及 96 次软删除全部成功；create p95 约 3.91 秒，delete p95 约 0.31 秒；
- 第二轮 8 并发、48 次创建及 48 次软删除全部成功；create p95 约 0.28 秒，delete p95 约 0.28 秒；
- 两轮均验证 idempotent replay、stale revision、未认证读取、缺 CSRF、只读角色写入和 HTTP 明文 mutation 的 fail-closed 行为。

16 并发时的约四秒 create p95 记录为当前容量/排队边界，不构成一致性错误；未发现重复 note、丢 revision、越权写入或 SQLite 回退。

## 5. 已关闭问题与保留风险

本轮真实关闭：逻辑 writer 与数据库 session role 混用、release 缺 `AGENTS.md`、full-repo launcher 依赖、venv redirector PID 记录错误、HTTP mutation 在安全门禁前解析 payload，以及正式 cutover migration ledger 重放缺口。

DeepSeek 在本轮 S3 实现复核中已有一轮有效脱敏 review，未提出新可复现缺口；最终启动器修订后的两次外部调用没有返回有效 reviewer 内容，因此明确记录为“不可用”，不伪装成 pass。最终判断由代码、真实 PostgreSQL rehearsal、浏览器/多端压力、VM health/process/listener、远端 required CI 和 exact release evidence负责。

仍需后续阶段处理：其余八个 cutover unit、任务 runner 迁移、全系统 measured RPO/RTO、repository production-authority 公司治理，以及 S3 稳定观察后是否进入 S4。上述事项不影响 `user_content_notes` 当前 S3，但不得被本报告自动批准。

## 6. 清理与保留

最终验收后只保留当前 immutable release、PostgreSQL data/WAL、authority/revision/audit、最新两份 verified recovery set 和脱敏治理报告。旧 exact execution root、incoming bundle、临时 task、测试对象及已确认无效的 failed package 按显式 manifest dry-run/apply 清理；不得删除当前 release、当前 recovery set、live 数据或原始审计证据。

## 7. 结论

`user_content_notes` 已完成首个生产 cutover 并处于 durable S3。该结论不等于整个 Stage 4 完成，也不授权其余单元进入 S2/S3。最终可部署 commit、release manifest、push/PR run 与 VM evidence 由本报告所在分支的 exact-commit CI 和 Git 外 evidence 共同绑定。
