# Stage 4 `user_content_notes` production-readiness 收口报告

## 1. 结论

PR #7 已按人工批准合并到 `main`，merge commit 为 `c5b20fbf99e63104f787521173dc8ec8cca70951`，对应 main required checks 全绿。本轮在其上完成首单元的应用、权限、身份与非生产恢复准备。

当前结论是：

> **应用与 dev/test readiness PASS；production cutover 仍 BLOCKED。**

阻塞来自尚未获准执行的 production 现场工作，而不是通过文档猜测即可关闭的代码项。tracked route 仍固定为 `S0/sqlite_transition`，`production_cutover_authorized=false`；没有安装或启用 production PostgreSQL，也没有切换 live reader/writer/backend。

## 2. 已关闭的代码与合同缺口

- 显式 backend routing：runtime override 必须是完整、可审计配置；无 merge、无失败后 SQLite fallback。
- operation-level repository：SQLite 与 PostgreSQL adapter 分离；PostgreSQL reader/writer 使用不同连接身份和最小权限。
- API compatibility：list/create/update/soft-delete 支持稳定 note key、expected revision、idempotency 和明确错误分类；S0 不伪造 revision/soft-delete，也不再暴露不可审计硬删除。
- 浏览器 mutation identity：create 的 note/operation identity 与 payload SHA256 在结果明确前持久化；uncertain response 重试复用同一 identity，内容变化被阻断，成功或明确失败后才释放。同一 scope 的并发双击共享一次请求，并发改内容 fail-closed；通用 coordinator 的 create/delete replay 与并发竞态由真实 JavaScript 执行测试覆盖。
- 安全边界：签名 session、权限、CSRF、Git 外 Credential Manager；audit actor 只来自认证 principal，客户端 body actor 被忽略。
- stable identity：只读冻结 company、industry、industry_q、theme；company stable key 同时包含 ticker 与 venue。COHU 多对一 alias 由显式用户批准清单约束；TER 因 research.db 缺 venue，使用现有 verified financial identity、US exchange 供应链身份与 yfinance 行情来源形成显式 venue override。任何未批准重复直接 fail-closed。
- PostgreSQL runtime：reader/writer role 分离，production 仅允许受保护传输，凭据缺失即失败。
- readiness preflight：production topology、恢复、仓库治理、operator/approver/window 任一证据缺失均返回 BLOCKED，不会自授权。

## 3. Git 外证据 identity

原始映射、演练和 readiness JSON 保留在 Git 外，仅在本报告固定聚合事实与 SHA256：

| 证据 | 结果 | SHA256 |
|---|---|---|
| stable identity mapping v2 | 774 条；681 company、44 industry、44 industry_q、5 theme；collision=0；unapproved alias=0；approved alias group=1；reviewed venue override=1 | `3dafbaacb89eca6a8a53bb1a374e2a948cb951accf20247964653a815fc8fe86` |
| mapping manifest | source/row/schema/content watermark、ticker/venue、alias approval 聚合身份 | `867b71f2737b817f12e6e4097a6dfbc83e91835efbcd49198832bd0824b2470c` |
| adapter PostgreSQL rehearsal | PASS；migration×2、ACL、CRUD/软删除、S2→S3、S4、alias、dump/side restore | `10f3a7fc661b6c0933dde07ad504d234c3521dda5cac6b9a4149237ef7ba278a` |
| readiness input | 未伪造 production 现场证据 | `de10aadf818e7e557a85f3f1bbc72bec49fa9115af53924023ce4f7d225e69be` |
| readiness result | BLOCKED；保留 topology/recovery/governance/window 与 evidence-body 验证门禁 | `fe5eeb5f4c923e014505e9f84f9c8894f0c71eacf18337a052195f89e9179766` |

COHU alias 与 TER venue override 已具有逐项批准引用，但整份 frozen mapping 尚无 cutover-level approval reference，所以即使机器校验通过，也仍不能进入 S2。

## 4. 真实 PostgreSQL dev/test 演练

隔离 PostgreSQL 17 仅监听 loopback 非标准端口，使用测试数据库和临时角色，完成后数据库、角色与 listener 均清除。演练包括：

- additive migration 重复应用；
- reader 无 base-table SELECT，writer 无 base-table DML，controller 无 generic transition 权限；
- create/update/delete/list、expected revision、stale conflict、幂等 replay、软删除；
- 首笔 formal create/update/delete 与 S2→S3 authority revision 同事务；
- S3→S4 backend/writer/epoch/watermark/approval 不变量；
- 错误 route、旧 authority、未映射实体和越权角色 fail-closed；
- 两个 legacy company alias 映射同一 stable security；
- schema-compatible read view、前向幂等修复和 pg_dump 旁路恢复；
- 四套 live SQLite 文件哈希与 schema 前后不变。

上述结果只证明 dev/test 合同，不等于 production backup、PITR、RPO/RTO 或服务生命周期已经验证。

## 5. 尚未关闭的 production blocker

1. identity mapping 的人工批准与 cutover evidence reference；
2. production PostgreSQL 版本来源、容量、服务生命周期、网络、受保护传输、角色 ACL 和凭据生命周期现场证据；
3. VM 外副本、基础备份、WAL/等价增量、整库 restore、旁路单域 restore、authority recovery 及 target RPO/RTO 演练；
4. 仓库公司控制权或批准例外、第二管理员/交接、2FA/账号恢复和公司控制 deploy credential；
5. operator、approver、维护窗口、writer fence 与 rollback/recovery decision tree 的单元级批准。
6. readiness preflight 逐项验证现场 evidence 本体、引用关系与环境/时点身份；当前 boolean/reference/SHA 形状检查不能单独证明 production 事实。

因此当前尚不具备向用户申请“立即执行首个 production cutover”的条件。下一轮若获授权，应先在不进入 S2 的前提下关闭上述现场 readiness gate；只有 preflight 变为 ready-to-request 后，才能再次申请独立的 production cutover 授权。

## 6. 验收

- core tests：625 passed、21 skipped、55 subtests passed；
- Stage 4/browser 定向 tests：37 passed；
- compile：PASS；
- 隔离 PostgreSQL rehearsal：PASS；
- live SQLite unchanged：PASS；
- DeepSeek：1 轮，无新的可复现 must-fix 后停止；
- production operations：未执行。

最终 commit、push/PR run 与 required-check identity 在分支推送后补入本轮 HALT 汇报；不把 PR 临时 merge SHA 当作实现 identity。
