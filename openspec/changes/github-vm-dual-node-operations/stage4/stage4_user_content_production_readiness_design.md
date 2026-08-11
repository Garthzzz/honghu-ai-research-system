# Stage 4：`user_content_notes` production-readiness 收口设计

## 1. 范围与结论

本轮只关闭首个 cutover unit 在应用接线、可信写入、稳定身份和恢复演练方面的代码与非生产证据缺口。当前 authority 保持 `S0/sqlite_transition`；live SQLite、production Viewer、计划任务和 production PostgreSQL 均不改变。

代码完成不等于 production-ready。以下现场门禁没有真实证据时继续标记为 blocker：production PostgreSQL 拓扑与服务生命周期、VM 外 backup/WAL/restore、HTTPS 或等价传输保护、公司控制的 repository authority、维护窗口与 operator/approver。

## 2. 应用路由与 writer fence

`analyst_note` 使用 operation-level repository，不把整个 Flask 进程视为 writer。路由包含 cutover unit、backend、authority state、reader/writer operation 和 transaction boundary。

- tracked 默认值固定为 `S0/sqlite_transition`，不能由 PostgreSQL 连接失败触发切换；
- production PostgreSQL 只能由 Git 外 runtime route 明确启用，且必须同时验证 `S2/S3/S4`、`postgresql_production`、批准的 writer identity 和 SQLite writer fence；
- external route、数据库 authority 或 writer fence 任一缺失/冲突，mutation fail-closed；
- PostgreSQL 失败不回写 SQLite，SQLite writer 被 fenced 后也不能因配置回滚自行恢复；
- reader 与 writer 分别登记，但同一 unit 的混合状态不得制造伪事务。

## 3. API 与 repository 合同

保留现有 analyst-note URL，响应增加稳定键、revision、deleted 和 backend 等兼容字段。PostgreSQL mutation 要求 stable note key、expected revision 和 idempotency key；delete 调用数据库 soft-delete。S0 的 legacy SQLite 结构只能如实提供当前 create/list 能力；新的 repository 不再暴露不可审计的硬删除，也不伪造 durable idempotency、revision 或 soft-delete。

浏览器客户端为一次逻辑 mutation 同时生成稳定 note identity 与 operation identity，并只保存 payload SHA256、不保存正文。网络异常、5xx 或响应无法解析时在 `sessionStorage` 保留同一 identity；重试必须复用，且 pending 期间 payload 改变即 fail-closed。成功或明确 4xx 失败后才释放。同一 scope 的并发同内容提交共享一个 in-flight Promise，只发送一次 HTTP 请求；并发改内容直接拒绝，避免双击竞态在 uncertain response 后释放 identity。当前页面的 create 使用该 coordinator，通用 coordinator 同时覆盖以后接入的 update/delete；测试必须执行真实 JavaScript 状态机，不能只断言 API header 存在。stale revision、idempotency conflict、mapping conflict 和 authority fence 分别返回稳定错误类别，不用笼统 500 掩盖。

## 4. 认证、授权与 CSRF

只保护本 cutover unit，不借机重写所有 Viewer 写接口。

- principal 来自经过认证的 server-side session；body/header 中自由填写的 actor 不进入 audit；
- principal 必须具备 `analyst_note:read` 或 `analyst_note:write` 权限；
- 浏览器 mutation 必须验证 session CSRF token；
- production credential、密码哈希和 Flask session secret 由 Git 外配置引用 Windows Credential Manager，不进入 Git、日志或 API；
- 缺少安全配置、credential、TLS/受批准传输边界或角色时，写接口关闭而不是匿名降级；
- 测试使用注入的 principal/credential provider，不读取本机 credential。

## 5. Stable identity mapping

只读工具从 `research.db` 冻结当前 company/industry/theme/industry_q 映射，并输出 Git 外 manifest：

- company 使用规范 ticker 与 venue 的组合身份；交易所后缀优先决定 venue，裸 ticker 使用可核验的 market/listing status。源表缺失 venue 时只能使用带批准引用和依据的显式 identity override；无 ticker 时使用规范名称与市场组成的 fallback，并标注稳定性限制；
- industry 使用经 cycle/parent 校验的完整层级路径；
- theme 使用现有文本主键；
- industry_q 引用 industry stable key，Q 标签仍是 note 字段，不复制 shared identity authority；
- 每条映射携带 source database/table/id、source watermark、basis、ticker/venue 组成和 evidence identity；同一 legacy identity 冲突、父级环和空关键字段均 fail-closed。多个经过核验的历史 legacy alias 可以汇聚到同一 stable identity，但必须由 tracked approval 精确列出 legacy ids、批准引用和依据；任何未获批准的 stable-key 重复直接失败，不能用 `collision_count=0` 推定 alias 合法。

映射原文不提交 public Git，只提交工具、聚合数量和 SHA256。shared identity 仍由 SQLite 管理；S2 禁止 mapping 变化，S1/S3/S4 的新增映射必须走已批准 controller/audit 合同。

## 6. PostgreSQL adapter rehearsal

隔离 PostgreSQL rehearsal 使用和 Viewer 相同的 repository 代码覆盖：

- create/update/delete/list；
- idempotent retry、stale revision、缺失 mapping、错误 writer/backend；
- 首笔 create/update/delete 与 S2→S3 同事务；
- adapter 故障后保持 PG authority、不回写 SQLite，并用修复后的 adapter 对同一 stable operation 继续前向处理；
- 当前 schema 仍满足旧只读 view 时的 code-only read rollback；不把它描述成数据库回滚；
- side restore 后按 stable key/revision/audit 对账。

## 7. Production 现场门禁

本轮提供 fail-closed preflight 与 evidence schema，但不安装或启用 production PostgreSQL。请求实际 cutover 前仍必须现场证明：

1. 固定 PostgreSQL 版本、资源、服务启动/关机/crash recovery、监听/防火墙和角色权限；
2. 凭据存放、轮换、撤销和 break-glass；
3. VM 外基础备份、满足 target RPO 的 WAL/增量链、整库与旁路单域 restore；
4. authority-control 恢复后先独立验证再开放 writer；
5. repository 公司控制权或明确批准例外、第二管理员/交接、2FA、恢复与公司 deploy credential；
6. 最新 live drift、维护窗口、operator、approver 和单 unit S2 授权。

下一轮必须把 readiness preflight 从“boolean/reference/SHA 形状检查”提升为逐项打开并验证现场 evidence 本体、其相互引用及时间/主体/环境身份；本轮仅登记该 production-readiness blocker，不据此伪造或搭建 production 设施。

## 8. Reviewer 取舍

DeepSeek 第一轮提醒应用层需要独立 SQLite writer fence，而不能只验证“PG 已启用”，该意见接受并纳入第 2 节。其要求修改 live SQLite、统一 UUID、Git 内容同步以及把已存在的 SQL revision/idempotency/mapping 控制视为缺失，与冻结架构和真实代码冲突，拒绝。后续 reviewer 仅复核本轮实际实现与证据，不扩张基础设施。
