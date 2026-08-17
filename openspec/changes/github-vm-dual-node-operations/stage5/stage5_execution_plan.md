# Stage 5 执行计划

> 状态：OPERATIONAL CLOSEOUT COMPLETE / FORMAL HALT OPEN。所有完成状态必须由现场 evidence 支撑；被 owner 取消的项目不因本次收口而自动变成 PASS。

> Owner scope decision（2026-08-18）：用户取消独立/可销毁 Windows VM 空机演练、额外自然调度窗口观察、额外统一 Stage 5 验收重跑和广播包工作，并要求在 operational closeout 窗口内收口已知可复现缺陷与最终清理。被取消项只能标记为 `OUT OF SCOPE BY OWNER DECISION` 或 `WAIVED WITHOUT TEST CLAIM`，不得写成 PASS/verified；该决定不豁免 isolated whole/side/authority/checkpoint restore、continuous recovery、Viewer supervisor、已知缺陷修复、受限 cleanup 或最终人工 HALT。

> 规划前必读：开始或修订任何实施项前，必须读取并逐项对照 [`stage45_execution_pitfalls_and_evidence_contract.md`](stage45_execution_pitfalls_and_evidence_contract.md)，在计划中明确身份、authority/runner、恢复、证据、测试和禁止边界；该对照不构成完成勾选。

## 0. 已批准基线

- [x] 用户于 2026-08-16 批准 Stage 4 PASS/退出并授权 Stage 5。
- [x] 九个 cutover unit 为 durable S3，PostgreSQL 9/9 唯一 authority/writer；SQLite 只作 migration baseline/audit。
- [x] 修正 Stage 4 recovery-set target gap 与全系统 continuous production RPO/RTO 的口径。
- [x] 记录临时 repository production-governance exception；无人审核自动部署继续禁止。

## 1. 共用 runner 合同与测试

- [x] 固定七任务 canonical manifest、exact-release Python/runtime、service identity、unit role 和外置路径。
- [x] 建立 task definition/run/checkpoint/gap ledger、稳定 logical-window identity、single-instance lock、失败分类和 freshness 计算。
- [x] 修复会把 child/source 失败误报为成功的入口，保留合法空结果与失败的区别。
- [x] 通过 manifest、runner、installer、credential、catch-up、producer regression 和 fail-closed 测试。

**退出门槛**：测试证明重复 trigger 不重复业务效果；非零/partial/timeout 不被记为成功；PG/authority/credential/manifest 不匹配时不运行。

## 2. VM disabled 安装与身份验证

- [x] 从一个 CI 绿色且人工批准的 exact SHA 构建 immutable release 和 lock 环境。
- [x] 创建非交互、非管理员、最小权限 runner identity，并以 Git 外安全方式注入 task-scoped PostgreSQL credentials。
- [x] 在 VM 注册七个 Disabled 任务，核对 installed XML、principal、trigger、command、manifest 和 release identity。
- [x] 记录本地七任务 Disabled、VM 七任务 Disabled，证明此时没有 production runner 重叠。

**失败处理**：任一任务 identity/credential/probe 不通过时保持全部新任务 Disabled；不得启用部分未知定义。

## 3. 逐任务受控试跑与迁移

按真实依赖与外部窗口排序；每个任务都执行以下相同门禁：

- [x] 核验 authority、ACL、checkpoint、历史失败与受控试跑边界。
- [x] 选择不会伪造业务完成状态的真实 logical window 做试跑；核对 PostgreSQL ledger、业务表、source audit 与幂等重试。
- [x] 明确 missed-window 计划：可补抓、不可补抓、已完成和受时间窗口限制。
- [x] 再次证明本地同名任务 Disabled 后，只启用该 VM 任务。
- [ ] [OUT OF SCOPE BY OWNER DECISION] 追加自然调度窗口观察与 freshness 验收；未执行部分不得写成 PASS，既有 controlled trial/enable evidence 仍按各自窄合同记录。

建议风险顺序：`DynamicTick` → `RecruitWeekly` → `EventIngest` → 三个 Retail slot → `SentimentRetention`。实际顺序可因当天来源窗口调整，但不得跳过每个任务的独立 evidence。

## 4. 权限收口与自动恢复

- [x] 七个任务完成唯一 VM runner 后，撤销不再需要的本地 production role、credential 和网络访问，并保留可审计 evidence。
- [ ] 验证 PostgreSQL、Viewer 和 tasks 的依赖顺序；安全执行 service/process crash rehearsal。
- [ ] 若无安全 reboot 窗口，完成所有独立工作并把整机 reboot 保留为明确人工 gate，不得伪造完成。
- [ ] 验证停机缺口识别、bounded catch-up、checkpoint 不倒退和不重复消费。

## 5. Backup/WAL、隔离恢复与 measured RPO/RTO

- [x] 验证 production base backup、continuous WAL、freshness、retention、corruption/WAL-gap detection。
- [x] 完成 whole-database、side-domain、authority-control 和 task-checkpoint restore。
- [ ] [WAIVED WITHOUT TEST CLAIM / OUT OF SCOPE BY OWNER DECISION] 在独立/可销毁 Windows VM 从空机验证 exact release + backup/WAL + Git 外 config/credential + content/artifact + task manifest/checkpoint 的全主机闭包；用户已取消该演练，未产生 empty-machine PASS。上一项的 isolated whole/side/authority/checkpoint restore 仍是本轮必须项。
- [ ] [WAIVED WITHOUT TEST CLAIM / OUT OF SCOPE BY OWNER DECISION] 形成全系统 measured RPO/RTO 并逐类与 target 对账；已记录窄恢复目标与 `97.078s` resume 段，但不得冒充 full-system RPO/RTO。

## 6. 监控、CI 与最终 HALT

- [ ] [OUT OF SCOPE BY OWNER DECISION] 额外启用严格统一 health aggregator 与外发告警；现有 Viewer supervisor、task ledger 与 continuous recovery 保持各自合同，未声称统一告警 PASS。
- [ ] [OUT OF SCOPE BY OWNER DECISION] 在既有确定性证据之外再执行一轮额外统一 Stage 5 acceptance 重跑；该范围变更不把任何未执行检查改写成 PASS，也不改变最终人工 HALT。
- [x] 修复截至 owner decision 已知且可复现的缺陷；尚未出现的未来未知缺陷进入后续正常运维，不为假设性问题无限延长本轮。
- [ ] [PARTIAL / EXACT HANDOFF] VM 白名单 cleanup 与三个 Git linked worktree 清理完成；`backup/latest`、批准 recovery root、活动 worktree、live dev/test PostgreSQL 和 SQLite baseline 未触碰。本机 15 个 project-root-external standalone 临时目录因 Codex recursive-delete 执行策略拒绝而保留，exact-path 人工 handoff 后才可勾选。
- [ ] full core、Stage 5 targeted、compile、OpenSpec strict、tracked/secret/path boundary、SQLite ratchet 和 push/PR/main required CI 全绿。
- [x] 更新 completion report，绑定 exact commit、manifest、installed definitions、task evidence、recovery set 和 CI identity。
- [ ] [HALT] 提交 Stage 5 最终证据，等待用户人工验收；不得自动开始 HA/replica/CDC/自动故障转移等后续 change。
