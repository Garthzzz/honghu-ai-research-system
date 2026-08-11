# Stage 4 production-readiness candidate 执行计划

## Gate A：设计与隔离边界

- [x] 从 PR #8 已验收 head 合并并核验 main CI。
- [x] 建立独立 `feature/stage4-production-readiness` 分支；live 根保持不动。
- [x] 审计 mapping、preflight、browser mutation、PostgreSQL runtime 和 VM 网络可达性。
- [x] 完成 DeepSeek 第一轮脱敏设计复核并由 Codex 独立修订。

## Gate B：一致快照与 mapping approval bundle

- [x] 在一个显式只读 transaction 中读取全部 identity tables。
- [x] 用事务内 schema/content watermarks 生成 snapshot identity；文件哈希仅为 diagnostic。
- [x] 增加 WAL 并发写入回归测试，证明多个 SELECT 仍绑定同一 snapshot。
- [x] 重新生成 Git 外 mapping、脱敏摘要和可审计 approval bundle；保持最终人工批准为空。

## Gate C：真实 evidence verifier

- [x] 定义 typed evidence envelope/manifest 和共同 subject。
- [x] 实际打开、哈希并语义验证 topology、lifecycle、TLS/network、ACL、credential、backup/WAL、restore、authority recovery、repository 和 cutover decision evidence。
- [x] 验证环境、时点、commit/config、PostgreSQL system identity、backup/restore identity 与交叉引用。
- [x] 同 VM off-VM 声明、伪 hash/boolean、篡改、过期、环境错配均 fail-closed。
- [x] 结果明确区分工程 blocker 与 human decision，且永不自授权 production cutover。

## Gate D：浏览器 uncertain mutation 边界

- [x] identity 跨标签页关闭持续存在并绑定 principal。
- [x] 跨标签页建立/提交具备安全互斥；不支持时 fail-closed。
- [x] uncertain response 精确重放；明确结果后才释放；payload/principal 变化拒绝。
- [x] 回归覆盖标签页重建、重新登录、长期 pending 和并发标签页。

## Gate E：隔离 PostgreSQL/recovery rehearsal

- [x] 本地使用固定 PostgreSQL 17.10 candidate 运行 topology、ACL、credential、TLS、service/crash、backup/WAL、whole/side/authority recovery 合成演练。
- [x] 生成可在 VM 安全执行的只读前置检查和隔离 candidate runbook，不修改 production runner/8080/tasks/live SQLite。
- [ ] 真实 VM 执行通道与独立外部介质均未确认；准确保留 VM/off-VM blocker，不以本机其他盘符冒充。

## Gate F：最终验证与 PR

- [x] DeepSeek 已完成两轮脱敏复核；第二轮重复现有控制并混淆 stable mapping 与认证 identity，没有新的可复现缺口，按“无增量提前停止”结束。
- [x] 正式 clean-clone core（635 passed、21 skipped、55 subtests）、Stage 4/browser targeted（36 passed）、本机真实 PostgreSQL/recovery rehearsal、compile 与 OpenSpec strict 通过。原始全仓 `pytest` 另有 22 个受治理 artifact 模块缺少 Git 外输入，按既有 test-tier 合同不计入 clean-clone core，结果不被隐瞒或改写。
- [x] tracked boundary 通过；SQLite ratchet 对 identity freezer 的五个只读 metadata PRAGMA 采用有 owner、上限和退出条件的显式例外后通过。最终 staged boundary 在提交前再次执行。
- [ ] 生成最终 identity binding、readiness report，push readiness branch 并核验 push/PR CI。
- [ ] 只输出 `READY TO REQUEST FIRST PRODUCTION CUTOVER` 或 `PRODUCTION READINESS BLOCKED`，随后 HALT。
