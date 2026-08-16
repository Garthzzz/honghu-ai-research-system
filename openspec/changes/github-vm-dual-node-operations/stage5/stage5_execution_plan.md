# Stage 5 执行计划

> 状态：IN PROGRESS。所有完成状态必须由现场 evidence 支撑；本计划不因代码存在或任务注册成功而自动勾选。

## 0. 已批准基线

- [x] 用户于 2026-08-16 批准 Stage 4 PASS/退出并授权 Stage 5。
- [x] 九个 cutover unit 为 durable S3，PostgreSQL 9/9 唯一 authority/writer；SQLite 只作 migration baseline/audit。
- [x] 修正 Stage 4 recovery-set target gap 与全系统 continuous production RPO/RTO 的口径。
- [x] 记录临时 repository production-governance exception；无人审核自动部署继续禁止。

## 1. 共用 runner 合同与测试

- [ ] 固定七任务 canonical manifest、exact-release Python/runtime、service identity、unit role 和外置路径。
- [ ] 建立 task definition/run/checkpoint/gap ledger、稳定 logical-window identity、single-instance lock、失败分类和 freshness 计算。
- [ ] 修复会把 child/source 失败误报为成功的入口，保留合法空结果与失败的区别。
- [ ] 通过 manifest、runner、installer、credential、catch-up、producer regression 和 fail-closed 测试。

**退出门槛**：测试证明重复 trigger 不重复业务效果；非零/partial/timeout 不被记为成功；PG/authority/credential/manifest 不匹配时不运行。

## 2. VM disabled 安装与身份验证

- [ ] 从一个 CI 绿色且人工批准的 exact SHA 构建 immutable release 和 lock 环境。
- [ ] 创建非交互、非管理员、最小权限 runner identity，并以 Git 外安全方式注入 task-scoped PostgreSQL credentials。
- [ ] 在 VM 注册七个 Disabled 任务，核对 installed XML、principal、trigger、command、manifest 和 release identity。
- [ ] 记录本地七任务 Disabled、VM 七任务 Disabled，证明此时没有 production runner 重叠。

**失败处理**：任一任务 identity/credential/probe 不通过时保持全部新任务 Disabled；不得启用部分未知定义。

## 3. 逐任务受控试跑与迁移

按真实依赖与外部窗口排序；每个任务都执行以下相同门禁：

- [ ] 核验 authority、ACL、checkpoint、历史失败与当前 freshness。
- [ ] 选择不会伪造业务完成状态的真实 logical window 做试跑；核对 PostgreSQL ledger、业务表、source audit 与幂等重试。
- [ ] 明确 missed-window 计划：可补抓、不可补抓、已完成和受时间窗口限制。
- [ ] 再次证明本地同名任务 Disabled 后，只启用该 VM 任务。
- [ ] 观察业务窗口并核验 last-success、checkpoint 和 freshness，再继续下一任务。

建议风险顺序：`DynamicTick` → `RecruitWeekly` → `EventIngest` → 三个 Retail slot → `SentimentRetention`。实际顺序可因当天来源窗口调整，但不得跳过每个任务的独立 evidence。

## 4. 权限收口与自动恢复

- [ ] 七个任务完成唯一 VM runner 后，撤销不再需要的本地 production role、credential 和网络访问，并保留可审计 evidence。
- [ ] 验证 PostgreSQL、Viewer 和 tasks 的依赖顺序；安全执行 service/process crash rehearsal。
- [ ] 若无安全 reboot 窗口，完成所有独立工作并把整机 reboot 保留为明确人工 gate，不得伪造完成。
- [ ] 验证停机缺口识别、bounded catch-up、checkpoint 不倒退和不重复消费。

## 5. Backup/WAL、空机恢复与 measured RPO/RTO

- [ ] 验证 production base backup、continuous WAL、freshness、retention、corruption/WAL-gap detection。
- [ ] 完成 whole-database、side-domain、authority-control 和 task-checkpoint restore。
- [ ] 在 clean/isolated 环境验证 exact release + backup/WAL + Git 外 config/credential + content/artifact + task manifest/checkpoint 的恢复闭包。
- [ ] 记录实际 recoverable watermark、restore elapsed、未恢复数据、补抓与选择性修复耗时，形成全系统 measured RPO/RTO 并逐类与 target 对账。

## 6. 监控、CI 与最终 HALT

- [ ] 统一 Viewer/PG/authority/runner/checkpoint/freshness/backup/WAL/restore/disk/retention health 与告警。
- [ ] full core、Stage 5 targeted、compile、OpenSpec strict、tracked/secret/path boundary、SQLite ratchet 和 push/PR/main required CI 全绿。
- [ ] 更新 completion report，绑定 exact commit、manifest、installed definitions、task evidence、recovery set 和 CI identity。
- [ ] [HALT] 提交 Stage 5 最终证据，等待用户人工验收；不得自动开始 HA/replica/CDC/自动故障转移等后续 change。
