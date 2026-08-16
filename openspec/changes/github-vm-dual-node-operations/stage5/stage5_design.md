# Stage 5 任务、恢复与监控设计

> 状态：2026-08-16 已获实施授权，工程和现场验收进行中；本文不构成 Stage 5 PASS。

## 1. 不变量与范围

- 九个 cutover unit 已是 durable S3，PostgreSQL 是唯一 production authority/writer。Stage 5 只迁移 runner host、checkpoint、恢复和监控，不重新切换数据后端。
- SQLite 只作 migration baseline/audit；PostgreSQL 不可达时任务必须失败、延期或停止，不得 fallback、dual write 或恢复 SQLite writer。
- 同一 `task_id` 在任一时刻只有一个 production runner。VM 任务必须先 disabled 安装，完成受控试跑与对账，并证明本地同名任务 Disabled 后才能启用。
- 本阶段只覆盖七个既有 `IndustryDemo_*` 任务，不引入 HA、replica、CDC、自动故障转移或无人审核 production deploy。

## 2. Canonical manifest 与 immutable runtime

`config/operations/production_tasks.json` 是七个任务的 canonical manifest；其 schema、任务数量、时区、schedule、logical window、writer unit、freshness 和 command 由 `tools/operations/task_manifest.py` fail-closed 校验。

VM runner 必须同时绑定：

- 人工批准且 CI 绿色的 exact commit；
- immutable release 与 `RELEASE_MANIFEST.json`；
- Python 3.10 的 hash-pinned lock 环境和绝对路径；
- 外置 PostgreSQL runtime catalog、cutover registry、runtime logs/checkpoints、data/content；
- 非交互、非管理员的最小权限服务身份；
- 只属于任务所需 unit 的 PostgreSQL role/credential。

安装器不得从 `PATH` 猜解释器，不得把 live checkout 当可变 production release，也不得把 secret 写进参数、evidence 或 Git。任务定义先以 Disabled 注册；manifest、release、principal 或 installed XML identity 不一致时阻止启用。

## 3. Runner、ledger 与 checkpoint

统一 runner 为每次执行计算稳定的 `(task_id, logical_window)` operation identity，并在 PostgreSQL operations ledger 中记录 manifest、commit、runner host/principal、attempt、开始/结束时间、退出状态和失败分类。PostgreSQL advisory lock 防止同一任务并发；业务 producer 自身的 domain lock、pagination checkpoint、segment heartbeat 和 provider rate-limit state 继续保留，两层锁职责不得混淆。

退出码 `0` 只表示 runner/producer 本次命令成功返回，不能单独证明数据新鲜。健康判定必须组合 task ledger、业务 checkpoint、source audit、last-success、logical window 和数据 freshness。超时、部分成功、资源锁延期、producer/reconciliation failure 与 contract failure 必须分开记录。

## 4. 七个任务的补漏边界

- `DynamicTick`：恢复后按数据库 `fetch_schedule` 计算当前到期 target；不逐个重放已错过的 15 分钟 tick。不可补抓或已越过来源窗口的缺口单独登记。
- `EventIngest`：按业务日期和未评分公告做受限追平；来源抓取失败必须非零退出，合法空结果不得与失败混淆。
- `RecruitWeekly`：以 ISO week 为逻辑窗口；同周成功记录防重，错过后只做一次受控补跑；任一 child failure 必须向 runner 传播。
- `Retail_Preopen/Morning/Afternoon`：以业务日期和 slot 为窗口，复用既有 segment/checkpoint、source completeness 与 auto-backfill 合同；不因 Windows trigger 补发而跳过业务时间边界。
- `SentimentRetention`：只在对应完整窗口永久聚合与复算验证后清理过期原文；与 retail producer 共享资源边界，不得在仍 running/partial/failed 或未封存窗口上误删。

## 5. 逐任务 host cutover

每个任务独立经历：

1. 从 exact release 以 service account 在 VM disabled 安装；
2. 核验 PostgreSQL authority、unit ACL、credential、manifest、checkpoint 与当前 freshness；
3. 使用受控 logical window 做真实试跑，验证 ledger、业务结果、幂等重试和失败分类；
4. 证明本地旧 runner Disabled，再启用 VM 唯一 runner；
5. 观察至少覆盖其业务窗口的 last-success、checkpoint 和 freshness；
6. 撤销不再需要的本地 production credential、role 和网络访问，但保留旧任务定义 Disabled 供审计。

VM 试跑失败时保持 VM Disabled。若临时恢复 runner host，只能从已验证 checkpoint 恢复唯一 runner，数据后端始终保持 PostgreSQL。

## 6. 启动、故障与恢复顺序

启动/恢复顺序固定为：PostgreSQL service 与 authority-control 验证 → schema/application compatibility → Viewer → task definitions/credentials → missed-window 计划 → 逐任务 runner。服务进程启动不等于 pipeline healthy；追平未完成时 health 必须报告 `catching_up` 或 `degraded`。

Stage 5 的全系统恢复必须使用 GitHub exact release、异机 base/WAL recovery set、Git 外 credential/config、外置 content/artifact 和 task manifest/checkpoint，在 clean/isolated 环境中重建 PostgreSQL、Viewer、9/9 authority 与七个任务。恢复后先验证 authority 和 task checkpoint，才能恢复 writer/runner。

Stage 4 的 `0.007s` 是固定 recovery-set target gap，`8.047s` 是该固定数据库 target 的 restore elapsed；两者都不是任意连续生产故障的全系统 measured RPO/RTO。Stage 5 必须以故障前已异机持久化的 base/WAL、实际 recoverable watermark、空机耗时、未恢复数据和补抓/选择性修复时间重新测量并与 approved target 对账。

## 7. 统一健康与告警

统一 health 至少覆盖 Viewer、PostgreSQL、9/9 authority、writer/runner uniqueness、七个 task ledger/checkpoint/freshness、backup freshness、WAL continuity、last verified restore、磁盘容量和 recovery-set retention。告警必须区分：

- process/service 不可用；
- process 存活但 checkpoint 停滞；
- logical window 缺失或 catch-up 超时；
- source 客观不可补抓；
- backup/WAL 缺口或 restore evidence 过期；
- authority/credential/manifest identity 不一致。

## 8. 临时 repository governance exception

治理门禁完全关闭前只允许 `CI green → 用户人工批准 exact SHA → immutable VM deploy`；禁止 `main merge → 无人审核自动 production deploy`。公司资产归属或例外、第二管理员/交接、2FA/恢复、reviewer gate 和公司控制的 deploy credential 仍是退出 exception 的人工事项，详见 `repository_production_governance_exception.md`。
