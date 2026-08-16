# Stage 4 全部数据单元生产迁移收口报告

> 状态：九个 cutover unit 均为 durable S3；本报告只提交脱敏结论和 evidence identity。数据库、恢复集、凭据、TLS 私钥、用户内容及 VM 原始 evidence 保持在 Git 外。用户已于 2026-08-16 批准 Stage 4 退出并授权 Stage 5；七个任务与 runner 的迁移仍须由 Stage 5 现场 evidence 验收。

## 1. 结论

Stage 4 的数据 authority 迁移已经完成工程验收。九个单元都由 PostgreSQL 承担唯一 authority/writer，authority revision 均为 4；所有 SQLite writer flag 为 false。旧 SQLite 文件只保留为 migration baseline、审计档案和有限修复材料，不是 production rollback target。PostgreSQL 失败时应用 fail-closed，不允许 silent fallback、dual writer 或 shadow write。

最终 production Viewer 运行 exact commit `076dc982b343a851ae1dbbf30f99cb8e10104bdb`，模式为 `production_hybrid`。这里的 hybrid 表示数据 authority 已全部进入 PostgreSQL，但 papers/evidence、外置 content、运行时 projection 以及尚未迁移的任务主机仍按各自合同存在；它不表示 SQLite 仍可作为任一单元的生产 writer。

## 2. 九个 cutover unit

| cutover unit | state | authority / writer | 已核验迁移基线行数 | 当前角色 |
| --- | --- | --- | ---: | --- |
| `user_content_notes` | S3 | PostgreSQL / `honghu_user_content_writer` | 空集 backfill；正式 revision/audit 另行保留 | 唯一正式读写与审计事实源 |
| `shared_identity` | S3 | PostgreSQL / `honghu_writer_shared_identity` | 3,539 | 公司、行业、主题稳定身份权威 |
| `financial_data` | S3 | PostgreSQL / `honghu_writer_financial_data` | 53,569 | 财务事实、revision 与 reconciliation 权威 |
| `research_publication` | S3 | PostgreSQL / `honghu_writer_research_publication` | 35,012 | 研究发布、来源和版本治理权威 |
| `dynamic_intelligence` | S3 | PostgreSQL / `honghu_writer_dynamic_intelligence` | 19,091 | 动态情报与 checkpoint 数据权威 |
| `operations_governance` | S3 | PostgreSQL / `honghu_writer_operations_governance` | 38 | 运维、发布和控制记录权威 |
| `investment_hypotheses` | S3 | PostgreSQL / `honghu_writer_investment_hypotheses` | 37 | 假说及其变更权威 |
| `opportunity_lens` | S3 | PostgreSQL / `honghu_writer_opportunity_lens` | 19,048 | Opportunity Lens 结构化数据权威 |
| `sentiment_analytics` | S3 | PostgreSQL / `honghu_writer_sentiment_analytics` | 2,113,951 | 情绪聚合、窗口和短期明细权威 |

上述结构化迁移基线合计 2,244,285 行（不把 `user_content_notes` 的 revision/audit 运行记录重复计入）。S1 时每个单元的 source/target count 与 canonical content SHA256 已一致；进入 S2 前又按最终 watermark 做 delta catch-up、stable identity/legacy mapping、依赖和事务边界复核。每个单元的 S2→S3 都记录 cutover epoch、唯一 writer、SQLite final watermark、PostgreSQL first-formal watermark、approval/actor、幂等 operation identity 和 authority ledger；uncertain commit 按 S3 保守对账。

## 3. 应用与发布证据

- exact release commit：`076dc982b343a851ae1dbbf30f99cb8e10104bdb`。
- immutable release manifest：`60e24aa2ee9fb4ff62a923d9983787aa1cf474bf1ce1b0325544e701d1c480d9`。
- deployment evidence SHA256：`4611ead22cd668b85c7baf7d8445e70a9ee47c2a18da6b9f04e7b5ab4ca4da68`。
- representative smoke evidence SHA256：`0ff1a0afafb05067d137eb2f0b60f83cd2e0d092b4840fad7b130935cc837f31`。
- 16 项 production read smoke 全部通过；额外复核 `/`、`/company/1`、`/dynamic/sentiment`、`/opportunity-lens` 和 `/opportunity-lens/run/20` 均为 HTTP 200。
- LAN `http://10.5.1.240:8080/api/health` 返回 exact commit、9/9 S3、0 个 SQLite writer。
- 部署没有 authority transition、没有 formal business mutation，也没有恢复 SQLite writer；它只把已经完成 S3 的数据面接入经过 CI 验证的 immutable application release。

本轮修复了两个真实只读兼容问题：SQLite projection 必须在 schema/data 装载完成后才能启用 `query_only`；同一进程内同 unit/version 的多个 `PostgresDomainReadCache` 必须使用独立 shared-memory URI，避免 schema collision。两项都有回归测试，最终 clean CI tier 为 909 passed、21 skipped、55 subtests；compile、OpenSpec strict、tracked boundary 与 SQLite dependency ratchet 均通过。PR #26 的 push/PR required checks 对 exact head 全绿。

## 4. 备份、WAL 与恢复

最终 post-S3 recovery 使用批准的另一故障域 SMB storage，恢复集包含 base backup、达到目标 LSN 所需 WAL、sentinel、manifest、逐文件 hash、source/storage identity 和目标水位。restore 只读取异机 recovery set；whole-database、authority-control 和 side-domain restore 必须同时通过，恢复后的九个 authority snapshot 必须逐字段等于 durable source。

最终 recovery evidence 在 Git 外，治理记录只冻结以下脱敏身份：

- recovery set identity：`5854c08a44b4b25d6a7ae6662f52ac89df263fd20d0110528d02482ee0072cc5`；
- recovery evidence 内容 identity：`06bea500760b96d4856e3f7bdc886a167c07f396f1ce18f227c45c3568a22ac2`；文件 SHA256：`b5148947baaa870917b64db8f266e526a6c63641797544a2281d3c3c089b9089`；
- 本次 recovery-set target gap：0.007 秒；该固定 target 的数据库 restore elapsed：8.047 秒。前者不等于持续生产 RPO，后者不等于包含空机、凭据、Viewer、task/checkpoint 和补抓的全系统 RTO；Stage 5 另行实测并与 target 对账；
- validated retention：保留 `stage4-20260815T231501Z-aedb9d2e` 与 `stage4-20260815T185455Z-6b56b3aa`；最旧有效集已由 retention 删除，唯一未验证失败目录也经独立审计清理，异机端最终只剩两份有效集。

同 VM 的本机 base backup 和 restore-test 目录不计作 off-VM 副本。最终清理 evidence SHA256 为 `fd119838b16cf2d75b29657d6ac89d45d0b42a4fb0a134a55209aeb0b094d622`：删除 4 个旧 execution 目录、21 个旧 immutable release、4 个本机 backup source、3 个 restore-test 和 4 个 legacy Stage 4 根目录，D 盘可用空间恢复至约 151.5 GB；只保留最终 `076dc982…`、上一稳定版 `61bb3bed…`、live PostgreSQL/WAL、最终 evidence 和仍有审计价值的 SQLite baseline。异机失败目录清理 evidence SHA256 为 `3b44c82353f63f9d77cecad97133945572d38a4875b408d14e1a408ccd33a700`。

## 5. Runner 与 Stage 5 边界

Stage 4 收口时本机七个 `IndustryDemo_*` 计划任务全部 Disabled，VM 上不存在同名生产任务；因此 Stage 4 没有迁移 runner，也没有双 runner。当前数据 authority 已在 PostgreSQL。用户后来于 2026-08-16 单独授权 Stage 5 实施任务自动启动、checkpoint 连续、漏窗补跑、服务账户和 VM runner 切换；这不改变本报告记录的 Stage 4 现场事实。

## 6. Repository governance

GitHub API 已核实 main 的两个 required checks、strict update、管理员约束、conversation resolution、禁止 force push/delete。仍需人工处理：公司资产归属或正式例外、第二管理员、2FA/账号恢复，以及公司控制的 deploy credential。在关闭这些事项前，生产发布继续使用 `CI green → 人工批准 exact SHA → VM immutable deploy`，不启用 main merge 后无人审核自动上线。

## 7. Stage 4 退出建议

九个 cutover unit 已满足 Stage 4 的 S3、唯一 writer、对账、应用兼容和恢复合同；用户已于 2026-08-16 接受该建议并批准 Stage 4 退出。该批准不等于推进 S4；Stage 5 虽已另行授权，仍禁止无人审核自动部署并须独立完成七任务、恢复和 measured RPO/RTO 验收。
