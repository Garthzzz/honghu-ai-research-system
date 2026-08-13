# Stage 4 `user_content_notes` 生产切换与上线验收设计

## 1. 授权、目标与不可越线

用户于 2026-08-13 批准最终 identity mapping 处理、在本机 BitLocker `D:` 建立受限加密异机恢复域，并授权在恢复、S1 和生产门禁通过后执行首个 `user_content_notes` 单元的受控 S2/S3、8080 前端上线、写入、多端与压力测试。Codex 是本次 operator，用户是 approver；批准引用固定为本轮用户指令，不能扩展到其他 cutover unit、计划任务或 runner。

本轮只切换 `analyst_note` 这条 operation-level writer。A/B/C、财务、动态、情绪、Opportunity Lens 和七个计划任务继续使用现有 SQLite authority；不做通用双写、shadow write 或失败后 SQLite fallback。S3 后旧 `analyst_note` SQLite 只作为切换基线与审计材料，不能直接恢复为 writer。

## 2. 恢复域与两份验证集

唯一外部备份根为 `D:\quant\industry_demo_backup_package\postgresql_recovery`。该路径位于与 VM 不同的 Windows 主机和故障域，底层卷 BitLocker protection 必须为 On；SMB 只允许 VM 地址、要求加密、使用专用最小权限账户。secret 只在内存和 Windows Credential Manager/安全凭据边界中传递，不写 Git、命令行日志或 evidence。

每个验证集自包含：新 base backup、达到 sentinel/target watermark 所需 WAL、manifest、逐 artifact SHA256、源/目标 host 与 storage identity、目标恢复水位、实际 whole restore 和 sentinel 验证。验证通过后才标记 `validated`。轮换策略按验证时间保留最新两份；创建新集合时先完成新集合 restore，再删除第三旧集合。大更新必须生成新集合并执行同一验证，不允许只覆盖 manifest 或复用未验证 WAL。

## 3. Identity mapping 与 S1

在同一 query-only SQLite snapshot 中重新冻结 mapping，并把用户决定写入受审计 approval：

- `company_id=336 海光` 映射到 `company_id=330 海光信息` 的 `688041.SH` 主体；
- `company_id=58 Sumitomo`、`59 住友电气` 映射到 Sumitomo Electric `5802/Tokyo`；
- `company_id=21 Acacia` 保持被 Cisco 收购前的独立历史主体，以 `ACIA/us` 显式 override，不合并 Cisco；
- 保留已批准 COHU alias 与 TER override；
- 对整份 manifest 做 cutover-level 用户批准绑定，机器 crosscheck 不能替代该批准。

`user_content_notes` S1 必须在 production PostgreSQL 中真实登记 authority、mapping、空集/非空 backfill、source/target watermark 和 reconciliation。S1 结束时 SQLite 仍是唯一正式 authority/writer，PostgreSQL 数据可放弃，tracked route 仍为 S0/S1 SQLite。

## 4. 维护窗与 S2/S3

维护窗开始前冻结：应用 commit/release manifest、PG system/service/TLS/ACL、mapping approval、SQLite final watermark、恢复集 identity、8080 listener/process identity、route revision 和 operator/approver。

切换顺序：

1. 精确识别当前 8080 listener 及其进程族，停止对 `analyst_note` 的旧 SQLite writer；不按模糊进程名清理。fence 证据同时要求旧 listener/process identity 消失、SQLite final watermark 在停写后二次采样不变、新 route 的唯一 writer identity 与 PostgreSQL authority 一致；本轮不为 live SQLite 追加 token 字段。
2. 再次确认 SQLite final watermark 与 S1 target 一致，确认无未完成 mutation。
3. 以 controller 事务进入 S2：PostgreSQL 是唯一指定 writer，SQLite writer fenced，记录 epoch、approval、writer identity 和水位。
4. 生成 Git 外完整 runtime route、PostgreSQL connection、identity mapping 与 user-content security 配置，使用 exact immutable application release 启动 8080。
5. 执行一笔带稳定 note/operation identity 的正式测试 create；该 mutation、revision、audit、idempotency、first-formal watermark 与 S2→S3 必须同事务提交。响应不确定时按 S3，通过相同 identity 查询/重放，绝不恢复 SQLite writer。
6. S3 后验证 update/delete/list、并发冲突和前向修复；测试对象采用明确前缀并最终 soft-delete，revision/audit 保留。

任何 route/authority/credential/mapping/PG 连接错误均 fail-closed。S2 只有在停写、水位和审计证明没有必须保留的新 PG 写入时才允许回到 S1/SQLite；第一笔必须保留的写入或 uncertain commit 后只允许 PostgreSQL 前向修复、兼容代码回滚或旁路恢复。

## 5. 8080 上线与身份安全

新 Viewer 使用 Python 3.10 lockfile 环境与 immutable release；data/content/state、route、mapping、security 和 secrets 全部外置。生产 PostgreSQL 连接继续强制 `sslmode=verify-full` 和冻结 CA root，证书/主机名校验失败必须有负向测试；应用 writer role 不能调用 generic authority transition，controller role 不进入 Viewer。

User-content security 至少配置两个测试 principal 以验证独立 session、权限与 stale conflict。密码哈希与 Flask session secret 写入 VM Credential Manager，audit actor 只来自认证 session；上线前执行一次 session secret/测试密码轮换并验证旧凭据失效。若当前内网 8080 没有 HTTPS 终止，本轮不得通过关闭传输保护来上线凭据；应先在同一 VM 建立受控 TLS 入口或把写接口保持关闭。GET 页面可继续提供，但生产 mutation 只有安全配置和传输门禁同时 ready 才开放。

## 6. 测试循环

### 首轮上线测试

- VM 本机与本地主机分别验证 health、release/route/authority、主要只读页面、静态资源和数据库读取；
- 两个独立浏览器/session 验证 login/logout、CSRF、read/write 权限、create/update/delete/list；
- 验证同 idempotency replay、lost-response replay、双击合并、stale revision 409、错误 CSRF 403、未认证 401、无权限 403、mapping 缺失 fail-closed；
- 有界并发/压力：逐步增加并发和总操作量，测 p50/p95/p99、错误率、连接数、锁等待和资源；阈值基于 baseline 与安全余量，不以把服务压垮为目标；
- 故障测试：PG 连接短暂不可用时写入失败且不触及 SQLite；恢复后复用同 operation identity 前向完成；8080 与其他只读模块保持可用或明确降级；
- 校验 SQLite `analyst_note` 文件水位不再变化、PG revision/audit/idempotency 完整、无 dual writer。

### 修订与独立终验

每轮按“Codex 诊断→修复→本机/VM/多端验证→DeepSeek 脱敏 reviewer→Codex复核”执行，DeepSeek 最多三轮；没有可复现增量则停止。功能/性能修订完成后，另行设计一套不复用首轮固定输入的独立终验，覆盖不同实体、操作顺序、并发交错、session 生命周期和故障点。若发现新问题，重复独立终验 loop，最多五轮；真实安全问题未关闭则不宣布完成。

## 7. 清理、版本与证据

上线稳定后才清理本地和 VM 的 obsolete failed execution、旧临时环境、测试输出和迁移包；任何 current/running release、PG data/WAL、最新两份 validated recovery set、authority/audit/revision、live data、backup/latest 或必要恢复材料不得删除。清理使用显式 inventory、dry-run、路径边界和前后健康检查。

最终提交绑定 application commit、tree、migration SHA、route/security template SHA、mapping/recovery/evidence identity、push/PR checks 和 VM deployment identity。公开 Git 只提交代码、测试、脱敏摘要与 evidence identity；原始数据库、backup、credentials、用户内容和私钥保持 Git 外。
