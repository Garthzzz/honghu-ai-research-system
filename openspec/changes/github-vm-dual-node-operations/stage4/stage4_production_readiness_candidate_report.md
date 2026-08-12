# Stage 4 production-readiness candidate 收口报告

> 历史状态说明：本文记录的是当时尚无远程通道的候选审计事实。2026-08-12 用户已建立并人工验证 `ssh honghu-vm`；当前执行边界和状态以 `stage4_production_execution_runbook.md` 与 `stage4_production_execution_status.md` 为准。本说明不改写本文的历史证据。

## 结论

> **PRODUCTION READINESS BLOCKED**

本轮已经关闭可在本地与代码侧自主完成的工程缺口，但没有真实 VM candidate 和另一故障域 off-VM copy/restore evidence。因此尚不能向用户申请首个 production cutover，也不能进入 S2/S3。

应用 tracked route 始终是 `S0/sqlite_transition`。本轮未连接 production Viewer 到 PostgreSQL，未修改 live SQLite、8080、计划任务或 production runner，也未写入正式业务数据。

## 已关闭的工程项

1. Identity mapping 在一个显式 query-only SQLite transaction 内读取全部 identity 表。事务内 schema/content/row watermarks 构成 snapshot identity，数据库文件哈希只作诊断；WAL 并发回归证明快照建立后的写入不会混入。
2. 774 条 mapping 已重新生成：681 company、44 industry、44 industry_q、5 theme；company 中 399 条 ticker+venue 直接确定，282 条 name/market fallback。COHU alias 与 TER venue override 单列审计；整份 mapping 仍等待用户 cutover-level approval。
3. Readiness preflight 不再接受 boolean/reference/SHA 外形声明。v3 bundle 把 recovery-set manifest 作为独立 artifact，打开并复算 hash，校验 environment/candidate/commit/config、时效、交叉引用、S0 route、应用 rehearsal、PostgreSQL topology/TLS/ACL/credential、base backup/WAL/target sentinel/whole/side/authority recovery、repository governance 和 cutover decision。
4. 浏览器 uncertain mutation identity 使用 localStorage 跨 reload/tab 保留，绑定可信 principal 与 payload；navigator.locks 提供跨 tab 互斥。明确成功或失败前不换 identity；principal/payload 变化、缺少安全锁能力和长期 pending 均 fail-closed。
5. 本机隔离 PostgreSQL 17.10 候选已真实完成 TLS、四类最小权限角色、Credential Manager 创建/轮换/旧凭据拒绝/撤销、start/stop/immediate crash recovery、base backup+WAL、whole restore、logical side restore，以及真实 authority-control migration/ACL/adapter/side restore。base backup 后另写 post-backup sentinel；恢复前原始同机 backup/WAL 被移出恢复路径，恢复只使用 recovery set，sentinel 经 WAL replay 恢复。实测 RPO `0.025` 秒、RTO `0.748` 秒。live SQLite schema 与文件哈希前后不变，候选最终无 listener。

## 当前机器判定

本机 typed bundle verifier 的预期结果为 `blocked`。工程 blocker 只剩：

- off-VM recovery copy 未验证；
- endpoint probe 明确把当前 recovery set 识别为 source-host local filesystem，不能证明不同故障域。

Human decisions 被单独列出，不伪装成工程失败：mapping 最终批准、repository production authority/exception、第二管理员或交接、2FA/恢复、公司控制 deploy credential、operator、approver、maintenance window 和进入 S2 的单独批准。

## 现场边界

当前从本机到 VM 的 SSH、SMB、WinRM 端口均不可用；只有 8080 Viewer 可达。Codex因此没有安全远程执行通道，不能自主在 VM 建候选。项目已提供 `stage4_postgresql_readiness_candidate_runbook.md`；它固定 Python 3.10、PostgreSQL 17.10 archive identity、loopback 非生产端口、S0 route 和执行后清理检查。

没有获确认的 VM 外恢复位置。本机另一个盘符不构成 off-VM，不能用于关闭该 gate。

## DeepSeek 复核

本次加速设计的两次预审连续要求引入明令禁止的 shadow write/fallback 和 S2/S3，且没有恢复反例，均被拒绝。recovery-set 实现和真实恢复完成后再做一轮窄审，DeepSeek返回 `pass`、无 must-fix/should-fix。最终判断仍由 fail-closed 反例与真实 PostgreSQL 物理恢复负责，不由 reviewer verdict 代替。

## 提交前验证

- 最终正式 clean-clone core：643 passed、21 skipped、55 subtests。
- recovery-set/readiness 定向回归：19 passed；Stage 4 既有 migration/browser/data-platform 测试也包含在完整 core 中。
- compile、OpenSpec strict、tracked boundary 与 SQLite dependency ratchet 通过。
- 原始全仓 `pytest` 会进入 22 个明确登记的 governed-artifact integration 模块；在 clean clone 缺少 Git 外研究包、工作簿和 live 只读快照时产生 42 failed、41 errors。该结果保留为测试分层事实，不通过 skip、xfail、上传受限 artifact 或降低合同伪装成通过。
- 本机隔离 PostgreSQL/recovery rehearsal 已在实现提交后重新生成并绑定该提交；VM/off-VM gate 仍保持 blocked。

## 最终 evidence identity

本轮 recovery-set 实现提交为 `de3fd1ef3ad6d10ccef1f3dbdb2826530197d812`（tree `d0be7bcb...a762`），其 push run `31541123718` 与 pull_request run `31541126825` 两项 required checks 均为 success。最终本机 candidate topology identity 为 `3f258ee8...9502`，recovery identity 为 `02d71fde...cfab`，recovery-set identity 为 `9075bebb...5931`；typed readiness bundle 文件 identity 为 `40e2140d...cdff`，verifier 结果文件 identity 为 `3d91fc42...356d`。最终 governance commit 不能递归把自己的 SHA 写进自身，故由该提交自己的 GitHub runtime Stage-1/Stage-2 artifacts 绑定最终 PR head/tree/checks；旧 `315335...` 与 `315343...` 仅是历史。完整脱敏绑定见 `config/migration/stage4_readiness_evidence_identity.json`，原始数据库、恢复、凭据和现场 evidence 未进入 Git。

Verifier 只留下两项同一根因的工程 blocker：没有真实 VM 外恢复副本，且 endpoint probe 证明当前副本仍属于 source-host failure domain。mapping、repository/operator/approver/maintenance/S2 等仍是 human decisions，不能用工程证据替代。

## 下一步

要解除 `PRODUCTION READINESS BLOCKED`，最小外部输入是：

1. 用户在 VM 按固定最终 commit 执行隔离 candidate runbook；
2. 提供一个真正位于另一主机或批准对象存储的 off-VM 路径与 host identity；
3. 将 Git 外 VM/off-VM evidence 输入 typed verifier；
4. 工程 gate 通过后，再由用户分别决定 mapping、repository governance/exception、operator/approver、maintenance window 和进入 S2。

以上均不等于授权实际 cutover。
