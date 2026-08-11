# 阶段 4：首单元 production readiness 与恢复前置

## 1. 当前判断

`user_content_notes` 已完成非生产 migration/state/permission/reconciliation/side-restore 演练，但尚不具备实际 production cutover 授权条件。缺口不是 SQL 原型能否运行，而是 production topology、authority durability、off-VM recovery、应用接线与写入口安全尚无现场证据。

## 2. Production topology 决策

首期候选为一个 PostgreSQL instance、一个主要业务 database、按 schema 与 role 分域；允许和 Viewer/任务 VM 共置。理由是当前体量、用户数和 VM 可接受停机事实尚不足以证明额外主机的收益超过运维复杂度。该选择不是高可用承诺。

实际安装前必须通过人工审查记录：

| 项目 | 必需证据 | 当前状态 |
|---|---|---|
| 版本与环境 | 受支持 PostgreSQL 版本、固定二进制来源、服务账户和升级边界 | 未验证 |
| 资源 | 数据/WAL/临时空间、内存、IO 和容量余量基线 | 未验证 |
| 服务生命周期 | 开机自动启动、正常关机、crash recovery 和健康探针 | 未验证 |
| 网络 | 监听范围、防火墙、远程连接必要性及传输保护 | 未验证 |
| 凭据 | 不进 Git/release/log；存放、轮换、撤销和 break-glass 流程 | 未验证 |
| 角色 | migration、unit writer、reader、controller、audit/backup 分离 | dev/test 已演练，production 未验证 |
| 仓库 authority | 公司控制权或已批准例外、管理员/恢复/2FA/deploy credential | gate 未关闭 |

以下条件任一出现时重新评估物理拆分：共置无法达到 target RPO/RTO；维护窗口相互冲突；资源争用影响数据库一致性或 Viewer/任务；需要独立故障域；权限/网络隔离无法在共置环境成立。

## 3. 角色与权限

| 角色 | 允许 | 禁止 |
|---|---|---|
| migration owner | 经批准窗口的 DDL/backfill、函数 owner | 日常应用登录 |
| user-content writer | 执行首单元专用 put/soft-delete | 基础表 DML、DDL、其他 unit transition |
| user-content reader | 只读 active-note 兼容视图 | 基础表、audit、mutation |
| cutover controller | 首单元专用 transition/verification wrapper | 通用或其他 unit transition、业务表 DML |
| audit/backup | 只读审计或备份所需权限 | 应用 mutation |

production 登录身份必须与 authority row 的 writer identity 绑定。不能把请求中的 writer 字符串当鉴权；dev/test 已验证业务函数同时要求 `session_user` 一致。迁移 owner 不得作为 Viewer 日常凭据。

## 4. Backup 与 recovery

### 4.1 切换前必须具备

- VM 外恢复副本；VM 本机目录不能是唯一备份。
- 可验证的基础备份与满足 target RPO 的增量/WAL 保留设计。
- authority/audit、user content 与密钥材料分开保护。
- 备份失败、WAL gap 或 restore 未验证时 writer fail-closed。
- 恢复环境不得覆盖 production；先旁路恢复、核验，再选择性修复。

### 4.2 必须演练的故障

1. 整个 production database/VM 不可用：恢复到隔离环境，测量 actual RPO/RTO。
2. 只损坏 `user_content` 逻辑数据：从旁路恢复结果按 stable key/revision/audit 选择性修复，不能原地回退整个 database。
3. authority state 不一致：先恢复 authority/audit 和 watermarks，writer 保持 fenced；无法证明时按 S3。
4. application release 故障：只有 schema 仍兼容旧代码时允许 code-only rollback；database authority 不变。
5. S3 后 PG 连接故障：前向修复或 restore；禁止启用旧 SQLite writer。

target 与 measured 必须分开。Stage 3 已批准的目标是 authority transition 零 acknowledged loss/1 小时验证，human-authored content RPO 不超过 5 分钟、RTO 不超过 4 小时；当前没有 measured production SLA。

## 5. 首单元 monitoring

| 监控对象 | 通过条件 | 失败动作 |
|---|---|---|
| authority | unit/state/backend/epoch/writer/revision 唯一且 audit 连续 | fence writer，人工对账 |
| first formal watermark | S3/S4 必有且能关联幂等 operation | 按 S3 保守处理，禁止 SQLite fallback |
| writer | 只有批准 session role 可执行首单元函数 | 撤销凭据并 fence |
| idempotency/revision | duplicate retry 同结果；stale update 显式冲突 | 停止发布新 writer release |
| mapping | legacy id 与 stable key 唯一、source watermark/evidence 可验证；S2 映射冻结，S1/S3/S4 增量登记有 expected authority revision、approval 和 audit | 拒绝 mutation |
| audit | 每次 create/update/delete 和 state transition 无 gap | fence writer并恢复 audit |
| backup/WAL | freshness 达到 target，最近 restore evidence 有效 | 不进入 S2或保持停写 |
| SQLite fence | S2 后 mutation path 不可达 | 任何双 writer 立即停止 cutover |

## 6. 实际授权前 go/no-go

只有全部为 GO 才能请求进入 production S1/S2：

- [ ] 最新 live drift 与两层 aggregate manifest 仍覆盖当前系统；
- [ ] 应用 repository/adapter 已接入显式 route，默认 S0，production 路由需双重开关；
- [ ] create/update/delete/list 兼容、authentication、authorization、CSRF 已通过浏览器/API 审核；
- [ ] stable entity mapping 对 company/industry/theme 全量验证，并有 SQLite authority 仍可能新增实体时的只读 resolver、受控增量登记和冲突处置现场证据；
- [ ] production PG topology、角色、凭据、服务和网络现场验收；
- [ ] 在进入首单元 S2 前完成该 unit 的 VM 外 backup、PITR/等价增量路径、整库和旁路单域 restore 现场演练；Stage 5 的系统级 measured RPO/RTO 不能替代此 gate；
- [ ] authority control 的零 acknowledged loss 机制有恢复证据；
- [ ] maintenance window、operator、approver、rollback/recovery decision tree 获批；
- [ ] 用户明确批准该 unit 进入 S2；
- [ ] 其他 unit、计划任务和 Viewer production runner 保持原 authority。

本轮不满足上述现场 gate，因此不能把 dev/test PASS 写成 production-ready。
