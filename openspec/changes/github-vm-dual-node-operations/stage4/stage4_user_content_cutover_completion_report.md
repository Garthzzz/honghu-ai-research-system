# Stage 4 首个切换单元生产执行报告

> 状态：`user_content_notes` 已进入不可直接退回 SQLite 的 S3。本报告只提交脱敏结论；数据库、恢复集、凭据、TLS 私钥、用户内容及 VM 原始 evidence 保持在 Git 外。

## 1. 执行范围与权威状态

本报告只验收 `user_content_notes`。正式 create/update/delete/list、revision、soft delete、audit 与 idempotency 已由 production PostgreSQL 承担；其余八个 cutover unit 在本报告形成时尚未切换。用户后续批量执行授权不追溯改变本报告的首单元 evidence，也不允许任何未通过自身门禁的单元进入 S2/S3。

- authority state：S3；authoritative backend：`postgresql_production`。
- authority epoch：由 Git 外 control-plane evidence 固定并审计。
- SQLite writer 已 fenced；旧 `IndustryViewer`、`IndustryViewer1` 服务已停止并禁用。
- PostgreSQL 已产生必须保留的正式写入，旧 SQLite 仅是迁移基线、审计档案和有限修复材料，不是 production rollback target。
- 没有 dual write、shadow write 或 PostgreSQL 失败后的 silent SQLite fallback。

## 2. PostgreSQL、恢复与身份

生产服务为 PostgreSQL 17.10 Windows service `HonghuPostgreSQL17`，使用固定端口、TLS、最小权限 reader/writer/controller/audit/backup 角色和 Windows Credential Manager 凭据。`user_content_notes` 的 migration、authority/control、revision/audit/idempotency、稳定身份映射与 writer identity separation 均已应用并记入 migration ledger。

进入 S2 前已完成 base backup、base 后 sentinel、目标 WAL、manifest/hash、另一故障域复制，以及仅使用该 recovery set 的 whole/authority/side restore。S3 产生正式业务写入后，又以恢复工具提交 `0971b9cc03466b7ffdaea7b98616d6f8b4423e47` 对真实 S3 authority snapshot 完成一次新的异机恢复：恢复过程完整保存并逐字段核对 state、backend、writer identity、cutover epoch、SQLite final watermark、PostgreSQL first-formal commit watermark、state revision 和 approval reference；S2 状态及 S3/S4 缺少任一关键字段均 fail-closed。

本次 S3 后 recovery set identity 为 `a69d45a25b80fe02410c0ffd7989b9cf4fe92bf4c513e8286c2a279d2326e99b`，脱敏 evidence SHA256 为 `edb9f9f1efe5ff9e3aa06b46da847f81bd6b85c15118eff1dc9bc96622530495`。恢复只使用异机加密集合，whole-database restore、authority-control restore 与 side restore 均通过；实测 RPO 为 0.02 秒、RTO 为 7.484 秒。恢复集保留合同为最多两份已验证集合；当前仅保留 `stage4-20260814T095155Z-98a23e3d` 和 `stage4-20260814T063843Z-b739e2f9`。同 VM 盘符不计作 off-VM，失败或未验证目录不计入配额。

774 条 company mapping 使用一致只读 SQLite transaction snapshot：399 条 ticker+venue 直接身份，278 条 fallback 经多库机器交叉核验，COHU alias 与 TER override 显式记录；最终四个例外已由用户批准并形成独立 approval identity。数据库文件 hash 只作诊断，不冒充事务快照身份。

## 3. S2→S3 与应用上线

writer fence 后，PostgreSQL 成为唯一指定 writer。首条必须保留的 formal mutation 与 S2→S3 authority revision、revision/audit/idempotency 和 first-formal watermark 在同一 PostgreSQL transaction 提交。之后 Viewer 重新加载 durable S3 route。

生产 Viewer 同时提供：

- 8080：兼容只读 HTTP；所有 mutation 在进入 payload/repository 前拒绝。
- 8443：TLS、认证、最小 ACL、CSRF、expected revision 和幂等 mutation。

应用 health 必须同时证明 exact commit、release manifest、S3、PostgreSQL backend、security ready、launch ID、health PID 与 listener PID。正式启动器使用受支持的 base Python 3.10 `-I -B -S`，只注入 hash-pinned site-packages；immutable release 显式包含 `AGENTS.md`，不再依赖 full repository，也不记录 Windows venv redirector 外层 PID。

## 4. 独立功能、浏览器与压力验收

本地最终代码门禁：781 passed、21 skipped、55 subtests；另有 61 项恢复/authority 定向回归通过，覆盖有效 S3 snapshot、S2 恢复拒绝、错误 backend、缺失 first-formal commit 和恢复前后 authority 一致性。compile、OpenSpec strict、tracked boundary 与 SQLite dependency ratchet 全部通过。恢复工具提交 `0971b9cc03466b7ffdaea7b98616d6f8b4423e47` 的 push run `31789483323` 与 PR run `31789486601` 两个 required jobs 均为绿色。

真实生产验收包括：

- VM-local exact release、TLS、四库只读闭包和 authority probes；
- LAN 浏览器在真实行业公司页完成登录、create、唯一 list、soft delete 和截图审计；
- 第一轮 16 并发、96 次创建及 96 次软删除全部成功；create p95 约 3.91 秒，delete p95 约 0.31 秒；
- 第二轮 8 并发、48 次创建及 48 次软删除全部成功；create p95 约 0.28 秒，delete p95 约 0.28 秒；
- 两轮均验证 idempotent replay、stale revision、未认证读取、缺 CSRF、只读角色写入和 HTTP 明文 mutation 的 fail-closed 行为。

16 并发时的约四秒 create p95 记录为当前容量/排队边界，不构成一致性错误；未发现重复 note、丢 revision、越权写入或 SQLite 回退。

## 5. 已关闭问题与保留风险

本轮真实关闭：逻辑 writer 与数据库 session role 混用、release 缺 `AGENTS.md`、full-repo launcher 依赖、venv redirector PID 记录错误、HTTP mutation 在安全门禁前解析 payload，以及正式 cutover migration ledger 重放缺口。

DeepSeek 在本轮 S3 实现复核中已有一轮有效脱敏 review，未提出新可复现缺口；最终启动器修订后的两次外部调用没有返回有效 reviewer 内容，因此明确记录为“不可用”，不伪装成 pass。S3 恢复修复后的最后一轮脱敏复核返回 `revise`，但意见把已经明确为“秒”的 RPO/RTO、测试项数量和恢复集保留说明误读为缺失，也没有给出可导致错误 PASS 的具体状态或可复现路径；Codex据真实状态机、61 项定向测试和异机恢复结果拒绝该意见。最终判断由代码、真实 PostgreSQL rehearsal、浏览器/多端压力、VM health/process/listener、远端 required CI、exact release 和 S3 后 restore evidence负责。

仍需后续处理：其余八个 cutover unit、repository production-authority 公司治理，以及 S3 稳定观察后是否进入 S4。任务 runner 迁移和全系统 measured RPO/RTO 收口属于阶段 5，不在当前批量授权内。上述事项不影响 `user_content_notes` 当前 S3，也不得复用本单元 evidence 绕过各单元门禁。

## 6. 清理与保留

最终验收后只保留当前 immutable release、PostgreSQL data/WAL、authority/revision/audit、最新两份 verified recovery set 和脱敏治理报告。已清理四份失败/无效异机恢复目录，释放 12,365,034,243 bytes；已清理 VM 23 个旧 backup/restore staging 目录，释放 53,486,137,846 bytes；`D:\honghu-stage4-execution` 旧 SHA 目录、临时 Scheduled Task、临时工具包和中间脚本均已收口，backup staging 与 restore staging 均为 0。所有删除均避开当前 release、两个有效 recovery set、live PostgreSQL、SQLite 和原始审计 evidence。

项目内唯一 `backup/latest` 已通过标准维护入口原子刷新为 `stage4-user-content-s3-20260814`。归档大小 16,351,801,201 bytes，SHA256 为 `d8a32ae32a6ffabeb48382dda9715f0bde43a2d86687f3e140bddc8f5e323d41`，32,170 个文件；四套 SQLite 的 integrity check 与 foreign-key check 均通过。该项目备份是当前项目恢复基线，不替代 PostgreSQL 异机 recovery set。

## 7. 结论

`user_content_notes` 已完成首个生产 cutover并处于 durable S3。生产 Viewer 继续运行已经完成功能验收的应用提交 `fb4301c2c8b22bfb95b6b50e394dc0b6fab71659`；恢复工具修复及 S3 后真实 restore 绑定提交 `0971b9cc03466b7ffdaea7b98616d6f8b4423e47`。PR #14 已合并为 main commit `7633921b25eb6302a137de534d8bd090c50cf706`，main required CI run `31815633323` 全绿。该治理身份只记录验收收口，不重新定义已验收 release 或恢复 evidence。

该结论在首单元验收时不等于整个 Stage 4 完成；当时 `user_content_notes` 进入 S3 observation、不推进 S4，其余单元仍须逐项通过 production gate，计划任务和 runner 当时也未获授权。该历史边界已被后续事实取代：九个单元现均为 durable S3，用户于 2026-08-16 批准 Stage 4 退出并另行授权 Stage 5；本报告不据此追认任何尚未完成的 Stage 5 现场 gate。
