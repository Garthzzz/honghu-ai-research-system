# Stage 4 production-readiness candidate 设计

## 1. 目标与边界

本轮只关闭 `user_content_notes` 首个 production cutover unit 在进入 S2 前的工程与现场证据缺口。活动应用路由持续保持 `S0/sqlite_transition`；readiness candidate 只能处理合成数据，不得连接 production Viewer、替代 SQLite writer、修改 8080、计划任务或 live SQLite，也不得写入正式业务数据。

Public Git 只保存代码、schema、测试、脱敏摘要和证据 identity。数据库副本、恢复介质、凭据、私钥、原始 mapping 和现场 evidence 留在 Git 外。任何布尔声明或格式正确的 SHA256 都不能单独证明 readiness。

## 2. 一致 identity snapshot

mapping builder 必须在一个显式、只读 SQLite transaction 中完成所有 identity 表的 schema、行与水位读取。快照 identity 由该事务内读取的 canonical schema 和 row content 计算；数据库文件前后哈希仅作诊断，不能代表 WAL 模式下的事务快照，也不能作为 cutover approval identity。

同一 mapping manifest 必须固定：

- transaction snapshot identity；
- 每张 source table 的 schema/content/row-count watermark；
- 774 条 legacy-to-stable mapping；
- alias、override 和 fallback 分类；
- 生成工具版本与 approval 文件 identity。

全量原文留在 Git 外。人工包提供类别计数、市场分布、COHU alias、TER override、所有 fallback 的可审计附录 identity 和未批准状态；Codex 不代替用户给出 cutover-level approval。

## 3. Evidence verifier

readiness 输入改为 manifest + typed evidence envelopes。manifest 只列路径、内容 SHA256 和 evidence type；verifier 必须逐个打开文件并验证：

- 文件真实存在、哈希匹配、路径没有逃逸允许的 evidence root；
- cutover unit、environment、candidate、commit、config identity 一致；
- observed time、cutoff、有效期和相互引用一致；
- topology、版本来源、容量、服务生命周期、network/TLS、角色 ACL、credential rotation/revocation 均有现场 payload；
- backup/WAL、whole restore、side restore、authority recovery 的 source/restore identity 可对账；
- off-VM 只有在 storage host 与 PostgreSQL host 明确不同且存在真实介质 identity 时成立；同 VM 路径一律不能冒充；
- repository governance、mapping approval、operator/approver 和 maintenance window 仍是明确 human decisions，不能由机器 evidence 自授权。

结果区分 `engineering_blockers` 与 `human_decisions`。只有工程证据全部通过时才可返回 `ready_to_request_production_authorization`；该状态仍不等于 production cutover authorized。

## 4. 隔离 PostgreSQL candidate

候选使用固定、受支持的 PostgreSQL 来源和独立目录、端口、服务名、角色及凭据，不复用 production 数据或权限。现场 runner 必须先检查资源、端口与 reboot 要求；发现冲突或需整机重启即停止该子任务。

候选演练覆盖：

- start/stop/crash recovery；
- 受限 listener 与 protected transport；
- reader/writer/controller/backup 最小权限；
- Windows Credential Manager 中的候选凭据创建、轮换、旧凭据失效和撤销；
- synthetic database 的 base backup/WAL、whole restore、side restore 和 authority-control recovery；
- adapter forward repair 与 schema-compatible code rollback。

本地可先验证脚本和恢复合同，但不能把本地演练写成 VM 现场证据。没有独立 VM 外介质时，off-VM gate 保持 blocked。

## 5. 浏览器 uncertain mutation

一次逻辑 mutation 的 note/operation identity 必须跨刷新与标签页关闭持续存在，并绑定可信登录 principal。payload 变化或 principal 变化必须 fail-closed；uncertain response 只能用原 identity 精确重放。跨标签页建立 identity 时使用浏览器原生的跨上下文互斥能力；环境不支持安全互斥时禁止写入，而不是退化成可能重复的 check-then-set。

长期 pending 不自动过期或换 identity。没有服务端 reconciliation 证据前，删除本地 pending 会制造重复提交风险；本轮保留精确重放路径，并在 UI 明示待确认状态。

## 6. 退出条件

`READY TO REQUEST FIRST PRODUCTION CUTOVER` 只在下列条件同时成立时使用：一致 mapping 工程通过、现场 evidence verifier 通过、真实 VM candidate 与真实 off-VM recovery evidence 通过，且只剩 mapping approval、repository production authority/exception、operator/approver、maintenance window 和进入 S2 的用户批准。

任何现场 evidence 缺失、同 VM 伪装 off-VM、无法验证 TLS/ACL/credential/recovery 或 route 不再是 S0，都返回 `PRODUCTION READINESS BLOCKED`。
