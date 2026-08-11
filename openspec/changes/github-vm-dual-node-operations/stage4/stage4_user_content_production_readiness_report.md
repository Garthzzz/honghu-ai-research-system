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
- 安全边界：签名 session、权限、CSRF、Git 外 Credential Manager；audit actor 只来自认证 principal，客户端 body actor 被忽略。
- stable identity：只读冻结 company、industry、industry_q、theme；legacy identity 唯一，允许经核验的历史 alias 汇聚到同一 stable identity。
- PostgreSQL runtime：reader/writer role 分离，production 仅允许受保护传输，凭据缺失即失败。
- readiness preflight：production topology、恢复、仓库治理、operator/approver/window 任一证据缺失均返回 BLOCKED，不会自授权。

## 3. Git 外证据 identity

原始映射、演练和 readiness JSON 保留在 Git 外，仅在本报告固定聚合事实与 SHA256：

| 证据 | 结果 | SHA256 |
|---|---|---|
| stable identity mapping | 774 条；681 company、44 industry、44 industry_q、5 theme；collision=0；alias group=1 | `f95259b764c71fc5adac7e7cb14694074f2598b2e262bc6ede6072738d3e4d6d` |
| mapping manifest | source/row/schema/content watermark 聚合身份 | `736584c1822957adbc663852f835ff6d6d7e6d35eba32d36ada37dc05fb8a294` |
| adapter PostgreSQL rehearsal | PASS；migration×2、ACL、CRUD/软删除、S2→S3、S4、alias、dump/side restore | `180883b288485c488e0a8727bd45efb4325922c0fac10d7894ad38c97b22ec2d` |
| readiness input | 未伪造 production 现场证据 | `941ceb537b65000551701c8d9b48a88a9b1fd7aebd99c0f8d2a5929225fc084f` |
| readiness result | `BLOCKED`、29 个细分 blocker、production authorization=false | `73639b275de2399a329fa32f2e4e1e3a479364c1761b157be78df37cb04f8ea1` |

identity mapping 尚无人工 approval reference，所以即使其机器校验通过，也仍不能进入 S2。

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

因此当前尚不具备向用户申请“立即执行首个 production cutover”的条件。下一轮若获授权，应先在不进入 S2 的前提下关闭上述现场 readiness gate；只有 preflight 变为 ready-to-request 后，才能再次申请独立的 production cutover 授权。

## 6. 验收

- core tests：621 passed、21 skipped、55 subtests passed；
- Stage 4 定向 tests：32 passed；
- compile：PASS；
- 隔离 PostgreSQL rehearsal：PASS；
- live SQLite unchanged：PASS；
- DeepSeek：2 轮，第二轮无有效增量后停止；
- production operations：未执行。

最终 commit、push/PR run 与 required-check identity 在分支推送后补入本轮 HALT 汇报；不把 PR 临时 merge SHA 当作实现 identity。
