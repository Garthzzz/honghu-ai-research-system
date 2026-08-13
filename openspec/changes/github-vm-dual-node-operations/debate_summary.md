# DeepSeek V4 Flash 架构交叉审核摘要

## Stage 4 production execution：部署闭包与 WinVault 会话复核（2026-08-12）

真实 exact-checkout VM 执行确认了两个独立问题。第一，bootstrap 动态调用的旧 helper 因文件名命中宽泛的 credential 路径忽略规则，只存在于本地工作树而不在 Git/deployment closure；本地测试因此误通过，VM clean checkout 在凭据阶段才失败。修订把它替换为中性命名、明确 tracked 的 `stage4_keyring_bridge.py`，bootstrap 在调用前验证文件存在，clean-clone 回归同时验证引用路径和实体文件。真实 credential 路径的忽略规则没有放宽。

第二，同一 VM 的 Windows OpenSSH 非交互登录实测对 WinVault 返回 WinError 1312，原生 `cmdkey` set 也失败。这是登录会话能力，不是 PostgreSQL、密码或包版本问题。bootstrap 现在在解压和锁定依赖安装前执行可逆的合成 Credential Manager capability probe；失败时明确要求在批准 principal 的 VM 交互桌面运行同一 exact package，不再消耗十余分钟后返回泛化错误。正式 bridge 强制 `WinVaultKeyring`、只从 stdin 接收 secret、不打印 secret，并把 1312 归一为不含敏感内容的诊断标签。

DeepSeek 只收到上述脱敏事实和测试汇总，返回 `approve`、无 must-fix。Codex接受其增加 WinError 1312 确定性单元测试及补清交互 principal/runbook 的建议。关于“自动扫描并删除所有遗留 probe”的建议未采用：probe target 只含非生产合成值，强行枚举本地化 Credential Manager 输出会引入误删并发/其他条目的新风险；现有调用在 `finally` 删除，本次现场 set 本身失败，没有残留条目。最终依据仍是 clean checkout、真实 VM 1312/`cmdkey` 探针、686 个 core tests、67 个 Stage 4/API/browser tests、OpenSpec、parser/compile、边界门禁和最终 required CI；外部 reviewer 不构成 interactive VM、off-VM、mapping、repository governance 或 S2 批准。

> 首次审查日期：2026-08-03  
> 首次审查轮次：2 轮；未进行第三轮，因为前两轮已显示同一前提偏差，继续扩张没有信息增量。  
> 数据边界：只发送脱敏架构摘要；未发送 key、Cookie、个人信息、数据库内容、论文原文或未批准材料。

## 第一次架构审查（保留原记录）

## 第一轮

DeepSeek 主张把系统定义为 local-first、多 VM 离线写架构，以每节点 SQLite 为事实源、Git 传输 change-set、PostgreSQL 作为汇聚查询库，并继续建设 outbox、CAS 和数据库文件/SQL 的 Git 回滚。

Codex 拒绝。项目事实是一个本地开发/研究工作站和一个生产 VM，本地不要求离线写入生产数据；Git 明确不得承载 live rows、SQLite、SQL 事件或数据库回滚。该建议会重新引入本次重构要删除的双事实源和自建复制系统。

## 第二轮

Codex 明确纠正节点、事实源和禁止事项后，DeepSeek 仍建议 SQLite dev 双轨、自动同步、通用方言适配以及未要求的 PostgreSQL 主从和 Docker 化。

Codex 再次拒绝。SQLite dev/PG prod 的长期双方言会让生产语义无法在开发期真实验证；自动同步违背唯一 writer 和不长期双写；主从、Docker 和固定周数没有来自当前代码、恢复目标或基础设施的证据，属于范围扩张。

## 第一次审查接受的意见

唯一接受的实质提醒是：如果 PostgreSQL 与 Viewer/任务 VM 共置，应用和数据库仍处于同一故障域，不能称为高可用。新版设计因此明确：

- 共置不能被描述为高可用；
- 共置切 production 前必须验证 VM 外备份、自动启动、正常关机、crash recovery 和空机 restore。

第二次人工架构审查进一步基于当前规模、可接受停机和运维经验修正了“必须长期独立”的倾向：共置可以是满足 RPO/RTO 后的 production 候选；只有恢复、隔离、维护、资源或多节点条件触发时才要求拆分。

## 相较第一稿的实质变化

- PostgreSQL 从“未来并发上升后的二期选项”改为明确长期目标；
- SQLite 从长期生产事实源改为迁移期状态；第三轮进一步纠正早期“只读回退候选”的宽泛措辞：S3/S4 只能作为迁移基线、审计档案和有限修复材料，不是默认 production rollback target；
- 删除长期四库 snapshot/change-set/CAS 和用户内容 Git 事件复制；
- 保留并强化研究 publisher、revision/audit、任务 checkpoint 和 restore test；
- 拆分 Git bootstrap、main、VM deployment、task cutover 和 database cutover 门槛；
- 增加本地独立 dev/test PostgreSQL 和 VM 停机补漏设计；
- 生产 PostgreSQL 共置/分离成为明确人工决策，而不是被默认隐藏。

最终方案由 Codex 基于 live 代码、schema、测试和任务配置独立负责，没有把 DeepSeek 输出直接复制到正式文档。

## 第二次架构审查（本轮追加）

> 日期：2026-08-03
> 实际轮次：2 轮；未进行第三轮，因为两轮都没有提供超出 Codex 草案的有效架构增量。  
> 发送范围：仅包括 SQLite 回退状态、cutover unit、publisher 并发、expand–contract、runner/存储两轴、稳定身份、单域恢复、RPO/RTO、仓库治理和内容仓库状态的脱敏摘要。

### 第一轮

Codex 在独立审计 124 个直接 SQLite 连接、六个 `ATTACH` 文件、现有 publisher 和人工写路径后先形成修订草案，再请求 DeepSeek 只反驳数据丢失、双 writer、错误恢复和文档矛盾。返回内容偏离约束，发明了 Redis、DNS/load balancing、固定批量/周期等项目不存在的设施，并把实现细节当作架构门槛。

Codex 全部拒绝这些意见：它们没有来自 live 代码、节点事实或 RPO/RTO 的证据，会扩张本轮范围，也没有指出草案中真实的状态机冲突。

### 第二轮

Codex 进一步把已修订的十项架构边界压缩成结构化问题，并明确禁止发明节点、双写、Docker、主从和固定周期。DeepSeek 返回九项所谓缺口，但其中八项只是复述输入中已经明确存在的设计；例如再次要求 expected revision、expand–contract、RPO/RTO、2FA 和 `RESERVED-UNUSED` 定义。其余建议把 cutover unit 错定为 PostgreSQL schema、把 legacy mapping 强制成 UUID，并错误声称方案使用“SQLite 本地开发 + PostgreSQL 生产”。这些都与本轮明确边界冲突。

Codex拒绝：

- cutover unit 不能固定为 schema，它由完整事务和业务语义决定；
- 稳定身份不等于所有对象 UUID 化；
- 本地目标是独立 dev/test PostgreSQL，SQLite 只做迁移兼容；
- “短期 token”“必须 PITR”等实现选项应由权限审计和 RPO/RTO 决定，不应在架构稿无证据写死。

没有从第二轮接受新的实质架构意见。停止第三轮的原因是连续两轮都没有信息增量，继续调用只会重复已写入的门槛或扩张系统。

### 本轮文档发生的实质变化

- 用 S0–S4 状态明确 PostgreSQL 新写入前后的 SQLite 角色，区分 rollback、restore 和 forward fix；
- 用业务 `cutover unit`、权威后端矩阵和跨域事务图替代按文件/按 schema 的机械迁移；
- 恢复 publisher 与人工内容的 expected revision、幂等、stale conflict 和依赖簇原子性；
- 增加 expand–migrate/backfill–transition–contract 和 code-only rollback 前提；
- 分离数据后端与任务 runner 两条迁移轴；
- 强化稳定业务身份和 legacy mapping，但不强制 UUID；
- 增加 RPO/RTO 分类和单域旁路恢复；
- 把共置改为非 HA 的可接受 production 候选，并用触发条件决定是否拆分；
- 把个人仓库公司控制权设为 production gate；
- 把内容仓库固定为 `RESERVED-UNUSED`。

## 第三次架构审查（本轮追加）

> 日期：2026-08-03  
> 实际轮次：2 轮；未进行第三轮，因为第二轮后没有剩余的具体合同矛盾，继续调用只会重复或扩张实现。  
> 脱敏输入范围：cutover unit 唯一 ownership、S2→S3 水位、target/measured RPO/RTO、本地 runner 临时状态、环境事实、`ATTACH` 故障语义、备份注册表和阶段 1 权限。未发送 key、Cookie、凭据、数据库内容、论文原文、用户内容或未批准资料。

### 第一轮：状态机和恢复边界反驳

Codex 先基于本地代码、四库 journal mode、计划任务和运维文档形成第三轮修订草案，再要求 DeepSeek 只检查双 writer、双 runner、错误回退和不可证明状态。

DeepSeek 返回中，以下意见被拒绝：

- 凭空假设 target RPO/RTO 为 3 秒和 4 秒；本方案没有设定任何具体数值，目标仍需用户按数据类别批准。
- 假设存在 SQLite→PostgreSQL 异步复制、同步复制、CDC、备用 VM 和自动 failover；这些都不是当前项目事实或已批准设计。
- 建议分布式事务、集中配置服务和额外缓存失效系统；这是超出本轮的小范围合同修订。
- 要求把 SQLite 与 PostgreSQL 组成一套一致备份；S3/S4 的权威是 PostgreSQL，SQLite 仅保留为基线和修复材料，不应伪装成共同 live 恢复点。

部分接受的提醒是：切换前必须明确停写、源末水位、目标首个正式提交和 uncertain response；`ATTACH` 在 WAL 条件下不能被描述成无条件跨文件强原子。这些内容原已在草案方向中，本轮把证据字段和保守判定写得更明确。

### 第二轮：跨文件一致性检查

第二轮只发送 A—I 的合同摘要。DeepSeek 错误地把 S2 理解成 SQLite 与 PostgreSQL 都可能是 writer，并据此构造 A/B、B/E 冲突；也把阶段 1 Git 权限与 runner owner 混为同一 ownership。这些判断被拒绝，因为文档中的 ownership 分别属于数据切换、任务运行和代码仓库治理三个不同对象。

第二轮仍带来两项低成本表述改进：

- 接受：明确写成 S2 中 PostgreSQL 是唯一指定 writer，SQLite writer 已停止并冻结；验证写只通过 PostgreSQL，不能被解释成双后端。
- 部分接受：每个 cutover unit 必须列明包含或依赖的数据类别，逐类满足 target RPO/RTO；不能用宽松类别覆盖严格类别，也不能把当前 SQLite `backup/latest` 当成 PostgreSQL 目标达标证据。

关于 publisher stale conflict 与 S2 uncertain response“是否同一机制”的建议被拒绝为概念混淆：前者处理业务版本并发，后者处理提交结果不确定；它们都可使用稳定身份/幂等身份查账，但不能合并成一个状态。

### 本轮实质变化与停止原因

- cutover unit 增加唯一 owning unit、dependency、重叠检查、责任人和人工边界变更合同；
- S2 明确为 PostgreSQL 单 writer 的短时栅栏，并增加 epoch、双端水位、验证写和 uncertain-response 保守收口；
- target RPO/RTO 前置到阶段 3 末/阶段 4 前，measured RPO/RTO 后置到阶段 5 真实恢复验收；
- 本地 runner 连接 production PostgreSQL 被限定为有 owner、权限和退出条件的临时状态；
- 运维文档区分当前解释器/Interactive 任务事实与未来 lockfile/服务身份目标；
- 备份注册表区分 SQLite 历史恢复材料、迁移基线和 PostgreSQL 目标恢复合同。

第二轮后剩余意见要么已由现有合同覆盖，要么源自错误前提，没有新的未闭环矛盾，因此停止在两轮。

## 阶段 1 实施审核

> 日期：2026-08-03
> DeepSeek 轮次：0。

Codex 先在隔离 clone 中完成 allowlist、staged gate、SQLite ratchet、测试修复、hash-pinned 环境和 CI，并通过远端 fresh clone 复验。本阶段没有调用 DeepSeek：门禁两次真实阻断分别发现 `.git/` 误伤 `.github/` 和受控 artifact 测试污染 clean-clone coverage，随后均由确定性回归测试关闭；继续向外部模型发送抽象摘要没有可识别的信息增量。该选择符合“可以使用、连续无增量即停止”，也避免无必要发送项目结构信息。

这不等于外部模型批准了阶段 1。阶段 1 的证据是 staged/tracked gate、SQLite ratchet、OpenSpec strict、clean environment 安装、compile、clean-clone tests 和远端 commit identity；main ruleset 与人工 HALT 仍由用户完成。

## 阶段 1 远端 CI 闭环审查（2026-08-04 追加）

### 第一轮：Windows 路径修复、证据绑定和仓库保护

Codex 先读取失败 run 的真实日志，确认五个失败都来自 GitHub Windows runner 对同一路径的 8.3 短名/规范长名表示差异；随后经过两次定向修复，把真实 ingest、paper path 和 DataYes 路径调用链纳入回归测试。提交 `f0532d9846fddef7d25e359170d1335136206525` 的两个远端 job 均真实绿色，clean-clone 为 531 passed、21 skipped、53 subtests passed。

发送给 DeepSeek V4 Flash 的内容只有上述脱敏根因、测试结果和四项待办：精确 commit 证据、pending-review 安全索引、main required checks/force-push 保护、公开暴露面审计。没有发送 key、Cookie、源代码、数据库、papers、用户内容或内部端点。前两次响应把推理预算耗尽而没有给出最终 reviewer 内容，不计作有效 review；缩短问题后取得一份完整结果。

DeepSeek 的三项意见及 Codex 判断：

- 接受：main 必须禁止 force push；它与已批准仓库治理合同一致。
- 拒绝：“66 个 pending-review 必须全部解决后才能合并”。这些文件的正确状态就是保持 untracked 并有可持续安全索引，强行纳入反而违反合规边界。
- 拒绝：“Windows runner 不适用”。同一 runner 上的最终修复已经通过两个实际 job；应保留 Windows 作为真实目标环境，而不是用换 runner 隐藏路径缺陷。

据此修订：增加 exact-checkout runtime evidence、长期 pending-review 哈希索引、公开仓库暴露面报告，并继续要求 main 的两个 required checks 和 force-push 禁令。没有接受任何 PostgreSQL、Docker、Redis、CDC、额外 VM 或阶段 2 范围扩张。

### 第二轮：精确提交证据与远端治理一致性

Codex 完成第一轮修订后先做本地全层复核，再推送 `8e83dfc6ddb85cde59c8777f5b1bc440e712324a`。远端 run `30847270449` 的两个 job 均为 success：553 项测试被收集，532 passed、21 skipped、53 subtests passed。Actions 上传的 `stage1-evidence-8e83dfc6ddb85cde59c8777f5b1bc440e712324a` 被重新下载检查，commit、run、760 个 tracked 文件、7 份 spec 和 66 条 pending-review 索引相互一致。GitHub API 同时回读确认 main 的两个 required checks、strict、PR gate、管理员约束、conversation resolution、force-push 禁令和删除禁令。

DeepSeek 只收到这些脱敏结果和公开仓库标识，返回 `pass`，没有提出阶段 1 内的 must-fix，也没有要求范围扩张。Codex 独立复核后同意“没有新增工程缺口”，但不把 reviewer 的 pass 解释为阶段 1 人工批准；最终仍需 protected main 的 PR/main Actions 和用户 HALT。由于第二轮没有信息增量或未闭环问题，停止第三轮。

## 阶段 2 release 实施审核（2026-08-04）

### 第一轮：初始实现审查

Codex 先在隔离 clone 中完成 exact-commit release、只读 candidate、schema compatibility、code-only rollback、本地 fixture 和测试，再向 DeepSeek发送公开 commit 与脱敏合同摘要。没有发送 key、Cookie、数据库、papers、用户内容、内网地址或源代码全文。

DeepSeek 把 reviewer 身份写成 `postgresql-docker-redis`，并提出以下与代码事实冲突的意见：声称 candidate 没有设置 `query_only`、health 没有验证 manifest、POST 路由仍会处理 body，又虚构 Docker/Redis 配置和 VM 资源结论。这些均被拒绝：candidate 连接同时使用 `mode=ro` 和 `query_only`；health 会调用 `verify_release` 复算 manifest 和逐文件 hash；非安全 HTTP 方法在路由处理前统一返回 403；项目没有阶段 2 Docker/Redis 实现。

这轮没有可采纳的工程增量。Codex独立审查反而发现并修正了两个真实问题：同 commit manifest 不应含构建时钟；rollback 必须用目标 release 的 schema contract，而不是当前 release contract。

### 第二轮：远端绿色证据审查

第二轮只发送远端 run `30856809650`、artifact identity、preflight、rollback 和禁止范围。DeepSeek 返回空的 `valid_must_fix`/`valid_should_fix`，但仍生成 `docker=true`、`redis=true`、`postgresql=true` 等不存在的断言，并在已明确“VM 尚未执行”时建议 `proceed`。

Codex拒绝这些虚构字段，也拒绝阶段 2 退出建议：VM 只读并行候选仍是明确退出 gate。两轮连续没有有效新增问题，因此停止第三轮。阶段 2 的有效证据来自本地/fresh-clone 测试、远端 Actions、下载后重算的 artifact、只读数据库哈希和待完成的 VM 实测，不来自 DeepSeek 的结论。

## 阶段 2 重点复审（2026-08-04 追加）

> 实际轮次：2 轮；未进行第三轮，因为第二轮没有提出能由公开代码或脱敏摘要支持的新缺口。发送内容仅包括公开仓库、公开 commit、测试状态，以及进程生命周期、Python 合同、路径闭包、schema 范围、smoke 和证据绑定的脱敏摘要；没有发送 key、Cookie、数据库内容、papers/evidence、用户内容或凭据。

### 第一轮：生命周期与 VM 证据合同

Codex 先修复候选进程 ownership、身份校验、失败清理、显式 Python 3.10、外置 content/state、只读 schema 合同和 15 项代表性 smoke，并在提交 `b9ce946ea5b74497bdc00befa80e814efef43435` 上完成真实本地生命周期实验。DeepSeek 返回 `pass`，没有 must-fix 或 should-fix。

Codex 没有把该结果当作退出依据。继续独立检查 CI evidence 后发现：原 evidence 虽验证了构建和 rollback，却没有在同一 exact-commit job 中真实启动候选；强化后又暴露合成 fixture 缺少首页、行业、估值和公司页依赖对象。由此新增了 CI 内的真实候选生命周期、listener PID、15 项 smoke、端口释放和无 `__pycache__` 证据，并扩充 fixture 与只读 schema 合同。

### 第二轮：公开提交与人工 VM 手册复核

Codex 在提交 `a6b19f2264a266a760688a46937d653f97e43c26` 的 push Actions 两个 job 真实绿色后，再向 DeepSeek发送上述实现摘要和 VM 手册边界。DeepSeek仍声称不存在 PID/launch id/commit/manifest evidence、Python 3.10 校验、data/content/state 检查、schema probe、exact-commit CI、403 smoke、rollback 和 Windows `samefile` 处理；这些陈述与公开提交中的实现和测试直接冲突，因此全部拒绝。其“增加 schema migration”和“建立 VM push/PR matrix”建议还越过阶段 2：本阶段禁止数据库 migration，push/PR Actions 是代码验证，不是替用户远程部署 VM。

第二轮没有给出新的可定位文件、失败路径或可复现反例。Codex据此停止第三轮，但仍保留 VM 18080 本机与内网客户端真实验收为人工 gate。外部 reviewer 的 `pass` 或 `revise` 均不替代确定性测试、Actions artifact、VM evidence 或用户 HALT。

第二轮后下载真实 Actions artifact 元数据时，Codex又独立发现 GitHub PR workflow 的 `GITHUB_SHA` 是临时 merge commit，而不是分支头。该问题不来自 DeepSeek意见。最终修订因此把 push artifact 定义为可部署分支提交的 exact-commit evidence，把 PR artifact 定义为与 base 的合并结果证据，并要求 PR artifact 中记录的 `pull_request_head_sha` 与 push SHA 一致；PR 临时 merge SHA 明确不得用于 VM 部署。

### 第三轮：push 分支身份与 PR merge 身份

由于第二轮后出现上述实质身份修订，Codex使用最后一轮配额，只请 DeepSeek检查临时 merge SHA、stale PR head 和无 event 的本地 evidence 是否可能被误认成 VM 候选。DeepSeek把“PR merge-result 在 Actions 中测试”错误理解成“PR artifact 必须被拿去部署 VM”，并据此声称 PR 被完全跳过；公开 workflow 实际对 `pull_request` 和 `push` 都运行同一套两个 job，PR merge commit 已经被测试，只是按设计不具备 VM 部署资格。该 must-fix 被拒绝。

DeepSeek关于“artifact 元数据应区分 push 与 PR”的方向已由本轮实现满足：`commit_role`、`event_name`、`pull_request_head_sha`、`pull_request_base_sha` 和 `eligible_as_vm_candidate_sha` 都进入 evidence。关于 PR 合并后 main push 的提醒也不构成缺口：若未来 main push 形成新的 branch commit，它必须重新通过该 SHA 自己的 push evidence；当前阶段仍禁止合并 PR 和 production deployment。第三轮未产生进一步修改，审核至此停止。

## 阶段 2 Python runtime 名称规范化复核（2026-08-06 追加）

> 实际有效轮次：2 轮；两轮均没有产生可复现的新缺口，因此停止第三轮。

### 第一轮：名称规范化修复后的合同检查

Codex 先根据 VM 的真实安装日志定位根因：旧 verifier 只把下划线替换成连字符，没有按 Python packaging 规则把点号、连字符、下划线和大小写统一。修复后，lockfile 名称和 `importlib.metadata` 返回的 distribution 名称两侧统一调用 `packaging.utils.canonicalize_name`；缺包、版本不一致、冲突 pin 和 `pip check` 失败继续 fail-closed。发送给 DeepSeek 的只有公开仓库、公开提交、脱敏合同摘要和测试结果，没有发送 key、Cookie、数据库、papers、用户内容、内网地址或源代码全文。

DeepSeek 返回 `revise`，但声称 mismatch 和 `pip check` 不会使 verifier 失败、两侧没有统一规范化、evidence 未绑定提交，并建议为四个包建立硬编码映射。Codex 逐项对照公开实现和测试后拒绝：两类失败都会进入 `failures` 并使 `ok=false`；CLI 返回非零；两侧调用同一规范化函数；exact-commit evidence 在同一构建中记录提交身份与 runtime 结果；硬编码特例反而违反通用 packaging 规范。本轮没有据此改弱门禁。

### 第二轮：最终实现与远端绿色结果复核

第二轮只发送同一公开提交的脱敏事实：统一名称规范化、真实 Python 3.10 全新环境安装 74 个 hash pin 包、缺包/错版本/`pip check` 的反例测试、exact-commit evidence 和 push/PR Actions 绿色状态。DeepSeek再次返回 `revise`，但主要意见仍与事实冲突：把 `pip check` mismatch 说成需要解释的“可接受例外”，忽略现有 commit identity 和 CLI 退出码，并建议检查 `importlib.metadata` 是否安装（该模块属于受支持 Python 运行时的标准库）。这些意见被拒绝。

其关于“锁文件不存在时给出更友好的结构化错误”的建议不构成本轮部署缺口：release manifest、部署脚本和固定路径在调用 verifier 前已验证 lockfile 闭包；若文件仍然消失，当前调用会非零终止而不是误报通过。后续可以改善错误展示，但不能把它解释为 runtime verification 会 false-positive。两轮连续没有有效新增问题，故不调用第三轮；最终依据仍是确定性回归、真实隔离环境、远端 Actions 和待执行的 VM 18080 人工证据，不是外部模型结论。

## 阶段 2 外置主题内容合同复核（2026-08-06 追加）

> 实际轮次：2 轮；两轮均未提出确定性新增缺口，因此停止第三轮。发送内容只有公开仓库、公开提交、脱敏后的 required/optional 内容合同、Windows 进程合同和测试摘要；没有发送 key、Cookie、数据库内容、papers、用户内容、内网地址或其他敏感材料。

### 第一轮：required/optional content closure

Codex 根据 VM 实测先独立确认：`docs/industries` 和 `papers` 存在，`docs/themes` 不存在，四库 probe 通过，主题基础数据在 `research.db`；代码中的主题 Markdown 加载器本来就允许文件缺失。修复提交 `65d981ff612741ad7f6a2f07165559efe9f0cdbf` 将外置路径改成 manifest 驱动合同：前两者 required，主题 Markdown optional；删除 content bypass；合成 fixture 刻意不创建空主题目录，并新增数据库-only 主题 route smoke。

DeepSeek 返回 `pass`。它建议可选目录存在但类型错误时失败、runbook 明确 optional、检查其他环境配置。Codex 对照实现逐项确认：wrong-kind 对 required 和 optional 都进入失败；runbook 和 16 项 smoke 已覆盖缺失；全仓只有一份活动 deployment policy 声明此闭包。因此建议均已由当前实现满足，没有新增修改。

### 第二轮：Windows venv listener ownership

第一轮之后，Codex 使用严格 lockfile venv 生成 exact-commit evidence，16 个路由全部成功，但身份门禁发现 Windows venv redirector PID 并非实际 listener PID。该问题不是 DeepSeek 提出，而是确定性 lifecycle 测试继续 fail-closed 的结果。修复提交 `f01208a40b7fe597d9969bfa226eb4dd4cb1728c` 保留 venv 安装与逐包核验，但由 verifier 记录的 base Python 以 `-S` 直接启动，只加入已验证 venv site-packages；实测 process PID、health PID 和 listener PID 一致，停止后端口释放。

DeepSeek 第二轮再次返回 `pass`，仅建议文档说明 base Python/`-S` 合同并在 evidence 核对 listener owner；两项都已经进入 design、spec、runbook、结构化 evidence 和回归测试。连续两轮没有有效新增问题，故停止第三轮。Codex 不把外部 reviewer 的 `pass` 当作 VM 验收或阶段 2 退出依据。

## 阶段 2 immutable release bytecode 与 Windows UTF-8 复核（2026-08-06 追加）

> 实际有效轮次：1 轮。发送范围只有公开仓库、公开提交 `1580aa6b87ff5c3b89ffc434a65da5ab969281f0`、脱敏根因、隔离/重试合同和确定性测试摘要；没有发送 key、Cookie、数据库内容、papers、用户内容、内网地址或源代码全文。

Codex 先用临时 exact release 复现 VM 的四个额外 `.pyc`：旧调用 `python -m tools.release.readonly_smoke --help` 稳定生成与现场完全相同的模块 bytecode，随后 strict verifier 返回 `release file set mismatch`。修复将所有导入项目代码的 Python 子进程收口到白名单 bootstrap 和 `-I -B -S`，在 build、preflight、activate、launch、smoke、stop 后逐次核对相同 manifest；污染但未激活、未运行的同 SHA 目录只能整体原子 quarantine 并保留文件集合证据，`current`、运行引用和不可证明状态全部 fail-closed。

提交 `a612fe83065d51f9e87e807b25e6fccee8f7880e` 的本地 evidence 通过后，Codex读取真实失败 Actions 日志，发现 GitHub Windows runner 的标准输出为 `cp1252`。由于 `-I` 会忽略 `PYTHONUTF8/PYTHONIOENCODING`，中文 smoke JSON 在打印阶段触发 `UnicodeEncodeError`；这不是 release manifest 失败，也没有通过 ASCII 转义或跳过 smoke 隐藏。后续修复让 bootstrap 在导入项目入口前显式把 stdout/stderr 设为 UTF-8 strict，并增加遗留代码页与中文 JSON 的真实子进程回归测试。

DeepSeek 返回 `pass`，唯一 should-fix 是“在 direct candidate 中显式 reconfigure UTF-8”，但该能力正是待审公开提交中已经实现并由回归测试覆盖的内容；因此没有新增修改。Codex以本地 556 passed、21 skipped、55 subtests、六阶段 exact manifest 一致性，以及 push run `31113566860` 和 PR run `31113572490` 的真实绿色结果作为工程依据。因 reviewer 没有给出新的可复现路径，停止后续轮次；阶段 2 仍必须等待新最终 SHA 的 VM 18080 人工验收，外部模型 `pass` 不构成退出批准。

## 阶段 2 legacy health 与 stale candidate record 复核（2026-08-07 追加）

### 第一轮：公开分支实现反查

Codex 先根据 VM 现场独立定位并修复：legacy 8080 health 缺少 `viewer_mode` 时的 StrictMode false negative、CIM 可选属性缺失、stale record 直接删除、失败 evidence 被 cleanup 次级异常遮蔽。定向回归和完整 core test 均通过后，将实现提交到公开分支，再向 DeepSeek 发送公开仓库、分支、提交、四项脱敏合同和测试目标；没有发送 key、Cookie、数据库、papers、用户内容、VM 内部内容或凭据。

DeepSeek 返回 `fail`，但其五项判断均与公开提交直接冲突：声称没有 CIM 查询、没有端口过滤、没有 stale cleanup/pre-post comparison、没有 StrictMode，并要求“VM/papers 测试”。公开文件实际包含 `Get-CimInstance Win32_Process`、`Get-NetTCPConnection -LocalPort`、`stale-record-archived`、`Test-HonghuProductionUnchanged` 和文件首行 `Set-StrictMode -Version Latest`；papers 也不属于本轮进程兼容缺陷。因此这些意见全部拒绝，未据此降低门禁或扩张范围。

Codex 没有因外部审查失真而停止独立复核，随后主动补强两点：stale 自动归档还必须确认 candidate health 不可达；可管理的活动 record 至少要有启动时间以及 executable/command 二者之一，避免生成以后无法安全清理的弱身份。相应增加 reachable-health 冲突测试，并保留“任一未知即 fail-closed”。第一轮外部结果不构成通过或退出依据。

### 第二轮：指定 raw 文件的跨文件一致性复核

为排除第一轮可能没有正确读取分支的问题，Codex 提供了最终候选提交中三个公开 raw 文件的精确 URL，并把问题限制为 health 能力、stale 四条件、PID 复用、CIM 可选属性和 failure evidence 五项。DeepSeek 仍声称 health 调用了不存在的 `/health`、PowerShell 没有处理 `viewer_mode`、没有校验命令行和 listener、没有 CIM 空字段测试。这些说法再次与公开源码中的 `/api/health`、`present_identity_fields`、`command_line_sha256`、`listener_owner` 以及对应回归测试直接冲突，故全部拒绝。

两轮外部响应连续没有给出可定位到真实代码的新增问题。Codex 不为了凑满三轮继续调用；停止原因是 reviewer 没有信息增量，而不是把其结论当作通过。工程判断继续以完整本地测试、OpenSpec strict、最终 push/PR Actions、exact-commit artifact 和下一次 VM 现场 evidence 为准。

## 阶段 2 production gate evidence v5 复核（2026-08-07 追加）

### 第一轮：公开修复提交与脱敏控制流检查

Codex 先根据真实 VM evidence 独立确认确定性根因：正常路径已经写入并据此判失败的 production gate comparison，在 catch cleanup 后被同名字段的二次采样覆盖。因此最终 JSON 出现 primary failure 与 `verified=true` 同时存在。修复提交 `7ef641827649d67ee4d9e74268be3b95eca0fbda` 将 evidence 升级为 v5：原始 `gate.post_state/comparisons/reasons` 只允许写一次，顶层兼容字段永久指向原 gate；cleanup 后状态独立进入 `recovery.post_cleanup_state/comparisons_to_pre`；primary、cleanup、pointer recovery 和 final-state capture 分别保存。生产状态使用三次有界采样，至少两个样本可用，所有可用样本在实际身份、listener、`current` 和广播 manifest 上必须一致。

发送给 DeepSeek 的只有公开仓库、公开 commit、上述脱敏控制流、测试名称和汇总结果，没有发送 key、Cookie、数据库内容、papers/evidence、用户内容、内网地址或 VM 原始 evidence。DeepSeek 返回 `needs_changes`，但两项 must-fix 和两项 should-fix 均与公开实现直接冲突：

- 声称 gate 抛错后 catch 不执行 cleanup；实际 `catch` 先保存 `failure.primary`，再调用身份受控 cleanup 与 pointer recovery；
- 声称 final-state capture 不保证运行；实际 cleanup 后有独立 `try/catch`，成功或失败都写 `failure.final_state_capture`，最后重新抛出保存的 primary；
- 声称窗口没有验证 health/listener/current/manifest；实际 usable 条件要求 HTTP、payload、成功状态和 listener query，所有 usable 状态再通过 `Test-HonghuProductionUnchanged` 比较 identity、listener、current pointer 和 broadcast manifest。`current` 可以合法不存在，但其存在性和 hash 必须前后一致；
- 声称测试没有核对 gate 与 recovery；`test_gate_evidence_remains_immutable_when_cleanup_state_recovers` 明确断言 gate=false、兼容 post_state 仍为 gate、recovery=true、post-cleanup 状态独立、primary 不变、observed 仍指原 gate，并验证第二次 gate 写入被拒绝。

DeepSeek 在 `uncertainties` 中也承认没有完整看到具体代码路径，因此 Codex 拒绝上述无可复现依据的意见，没有据此放宽 production gate。确定性依据是 569 passed、21 skipped、55 subtests、PowerShell parser 0 error、tracked boundary、SQLite ratchet 和 OpenSpec strict；远端 push/PR Actions 与 exact-commit artifact 仍需按最终提交重新核验，外部 reviewer 不替代 VM 重验。

### 第二轮：当前分支头的可定位反例复核

Codex 将第一轮复核记录提交为 `b8af0d0f36192422e49944f04c1619151f61d9c3` 后，再次要求 DeepSeek 只在读取公开代码后给出“相对路径、真实函数名和可复现反例”，并把输出限制为紧凑 JSON。DeepSeek 仍返回四项与源码冲突的意见：它引用了不存在的 `Set-GateState` 和笼统的 `Deploy-ReadonlyCandidate` 函数，声称 catch 没有 cleanup/pointer recovery、gate setter 不保存 post-state、生产窗口不相对 pre-state 比较，以及测试没有核对 primary/reasons。公开实现实际使用 `Set-HonghuCandidateGateEvidence`、`Set-HonghuCandidateRecoveryEvidence`、`Get-HonghuProductionStateWindow` 和 `Test-HonghuProductionUnchanged`；部署脚本 catch 明确执行 cleanup、pointer recovery、独立 final-state capture 后重抛 primary；回归测试逐项断言原 gate、recovery、primary、reasons 和兼容别名。

这些意见没有提供能够在公开提交上复现的路径，而且响应再次在 `uncertainties` 中承认实现细节并未完整确认。Codex 因此拒绝全部四项，不产生新的运行时代码修订；在没有新确定性事实时不为凑轮数调用第三轮。随后最终审计记录提交的远端 CI 暴露了新的 Windows 测试事实，才据此进行下面的第三轮。最终工程依据仍是当前提交自己的完整 Actions、exact-commit artifact 和下一次 VM 现场 evidence；本记录提交只保存 reviewer 判断，不扩大阶段范围。

### 第三轮：GitHub Windows 测试取证通道复核

最终审计记录提交触发的 push/PR Actions 均在同一个回归测试失败：PowerShell 子进程返回 0，但测试只从 stdout 读取 JSON，两个 runner 的 stdout 都为空，因而在 Python 取最后一行时触发 `IndexError`；旧测试没有把 error stream 变成确定性失败，因此第一次日志尚不能证明底层命令是否报错。修复提交 `8b80e94a852f4da1d4834530d351e7f8eca39477` 先加固测试取证：PowerShell 使用 `$ErrorActionPreference='Stop'`，把完整 comparison 写入临时 JSON；Python 同时断言进程退出码、文件存在，并以 `utf-8-sig` 兼容 Windows PowerShell 5.1 的 BOM。原有 `verified=false`、pointer/manifest 均不稳定和对应 reasons 的断言全部保留，没有 skip、xfail 或门禁放宽。本地完整结果为 569 passed、21 skipped、55 subtests。

DeepSeek 第三轮仍返回 `needs_changes`，但理由自相矛盾：一方面确认 `utf-8-sig` 会正确移除 BOM、JSON 能正常解析，另一方面声称测试“只依赖退出码、没有直接验证 JSON”，而公开测试恰好同时验证退出码、文件存在、JSON 结构和六项 fail-closed 结果。它还把原始 `IndexError` 错说成 JSON 中的 reason，并假设 PowerShell 异常会被当作成功；当前脚本通过 `ErrorActionPreference=Stop`、非零退出断言和结果文件存在断言形成三层失败检测。Codex 因此拒绝两项意见，没有再修改实现。

第三轮之后的新 Actions 终于把原 error stream 确定化：GitHub 的 PowerShell 7 job 启动 Windows PowerShell 子进程时，继承的模块发现路径没有提供 `Get-FileHash`；它正是第一次空 stdout 的底层原因。Codex 因而没有把 reviewer 结论当作闭环，而是按真实 traceback 系统替换 release PowerShell 中四处模块依赖：pointer/manifest、旧 evidence、lockfile 和 preflight 均改用 .NET `SHA256.ComputeHash`，并新增与 Python `hashlib.sha256` 对账及“运行时代码无 `Get-FileHash`”回归。完整本地结果更新为 570 passed、21 skipped、55 subtests。该修订发生在第三轮 reviewer 之后；由于用户限定最多三轮，未违规调用第四轮，最终仍由新提交自己的远端 Actions 和 artifact 验证。

三轮 reviewer 均未给出可在公开代码上复现的新缺口，已达到本轮最多三轮限制。停止调用不代表外部模型批准；最终候选仍必须由其自身 push/PR Actions、exact-commit artifact 和新的 VM 现场 evidence 证明。

## 阶段 2 production authority quorum 与 PID drift 复核（2026-08-07 追加）

> 实际轮次：2 轮。两轮都只发送公开仓库、公开提交、脱敏 VM 采样事实、门禁合同和测试摘要；没有发送 key、Cookie、数据库、papers/evidence、用户内容、内网地址或 VM 原始文件。连续两轮没有可定位到真实代码的新增问题，按约束停止第三轮。

### 第一轮：authority 与 runtime topology 分层

Codex 先根据三次真实 pre-state sample 独立确认：health、release/app/manifest、production `current`、广播 manifest 和 listener 存在性全部稳定，唯一波动是 PID set；旧实现却固定以第一条 usable sample 为 reference，并把所有后续 PID set 的完全相等当作硬门禁。修复提交 `7fba217ea4791d664b78e0e324c7c38983ac40f1` 把 PID 排除出 authority hash，按硬身份聚类，保留逐样本 PID 与 warning；listener 消失、候选 PID 出现在 8080、pre/post identity/current/broadcast 变化仍失败。

DeepSeek 返回的 must-fix 同时要求“PID 必须与 `[5000,16332]` 或 `[4604,16332]` 匹配”和“candidate PID 应监听 8080”，并声称输入没有给出 health 状态、required sample 数和 evidence schema。前两项直接违背本轮合同，后三项已在脱敏输入明确提供，因此拒绝。它提出“cluster 有 hard outlier 时不应无条件通过”的方向，与用户要求的“真实 release/manifest/app/current/broadcast 变化仍失败”一致；Codex没有照抄其错误结论，而是重新审查安全边界后独立收紧：只有全部 usable 样本属于同一 hard-authority cluster 才通过，孤立 unusable 样本可 warning，任何 usable hard-authority 冲突仍 fail-closed。

### 第二轮：收紧后公开提交复核

收紧后的公开提交 `ada6fef2b91f17f822d164bfb1508fd06c452428` 通过 23 项定向测试与完整 573 passed、21 skipped、55 subtests，并保留 tracked boundary、SQLite ratchet 和 OpenSpec strict。第二轮明确提供真实函数名和 A—F 合同，要求只报告带相对路径、真实函数与可复现输入的缺陷。

DeepSeek仍没有返回约定的 verdict/must-fix 结构，而是把输入摘要重写成函数说明；它再次声称 candidate 运行在 8080，并建议“candidate PID 不应在 ForbiddenListenerPids”，与公开部署脚本“candidate 只监听 18080，若其 PID 出现在 production 8080 则失败”的合同相反。它还错误声称 authority identity 包含 PID，而公开实现明确只包含 listener query/presence 布尔，PID 仅在 runtime diagnostics。由于没有任何相对路径、真实触发输入或可复现错误，这些意见全部拒绝，不再据此修改代码。

两轮外部响应连续没有信息增量，故停止第三轮。有效工程证据来自 PowerShell 定向回归、完整本地测试、最终提交自己的 push/PR Actions、exact-commit artifact 与待执行的 VM 现场复验；DeepSeek 不构成阶段 2 退出批准。

## 阶段 3 数据依赖与 PostgreSQL dev/test 试点复核（2026-08-07 追加）

> 实际轮次：2 轮。只发送公开仓库、PR #5、公开提交和脱敏合同/测试摘要；未发送 key、Cookie、数据库内容或行数、papers/evidence、用户内容、内网地址、外部 evidence 或凭据。连续两轮没有可复现的信息增量，停止第三轮。

### 第一轮：初版公开试点

Codex 先独立完成 operation-level SQLite dependency inventory、唯一 cutover ownership registry、显式 backend route、expand-only migration 和隔离 PostgreSQL 17.10 用户笔记试点。DeepSeek 要求把 operation ledger 与 writer lease 写入 live SQLite、用 attached database 保证一致性，并提前增加 Stage 4、复制和监控；这些直接违反“Stage 3 不改 live SQLite、不进入生产”的授权。它还错误声称 dev/test 使用 5432，而公开 `validate_test_target` 明确拒绝 5432、非 loopback 和非测试库前缀。上述意见全部拒绝。

Codex没有因无效 reviewer 意见停止独立复核，随后发现两个真实 SQL 边界：NULL `expected_revision` 可能绕过 SQL 三值比较；只比较调用方声称的 request hash 不能证明 payload 相同。修订在数据库内保存并比较完整 canonical JSON payload，显式拒绝 NULL revision/key/hash，并增加“相同 hash 但 payload 改变”反例。Windows 真机复验还发现 `pg_ctl start` 的长生命周期 server 可继承 capture pipe；启动路径改用外部日志和无继承 pipe，并新增回归。

### 第二轮：收紧后的公开提交

第二轮要求 DeepSeek只报告带相对路径、真实函数/SQL对象和精确触发输入的问题。返回仍把 `validate_test_target` 错放进 `cutover_registry.py`，重复声称代码连接 5432、没有 migration ID/SHA、没有 soft delete/NULL 处理或 payload 校验，并虚构 PR 修改了 Docker、Redis 和 CDC。它还把“NULL revision 必须 fail-closed”倒置为缺陷。这些均与公开源码和测试直接冲突，全部拒绝。

两轮没有有效增量后按约束停止。Stage 3 的有效依据是本地完整测试、真实 PostgreSQL migration/冲突/dump/restore、live SQLite 前后文件 hash、registry 冲突检查、OpenSpec strict 和最终 PR Actions，不是外部 reviewer verdict。

## 阶段 3 live 增量对账设计复核（2026-08-10 追加）

> 实际轮次：2 轮。Codex 先独立审计 live/Git 差异、四库 schema、备份时点和阶段 3 证据，再形成 design/plan；发送给 DeepSeek 的只有脱敏架构摘要、文件类别和聚合计数，没有发送 key、Cookie、源代码、数据库行、papers、用户请求、研究正文、内网地址或原始 evidence。两轮连续没有可复现的信息增量，因此停止第三轮。

### Codex 独立草案与修订

只读审计确认 live 新研究没有改变四库 schema 或 134 张受审业务表集合，但增加了研究专属 SQLite writer；同时 live `app.py` 的新行业分组功能与阶段 2 已验收的 runtime/只读候选能力发生整文件分叉。Codex 因此拒绝整树复制，设计逐功能三方合并，并把研究专属脚本保持在 public Git 外。为避免排除路径从迁移审计中消失，设计采用 deployable inventory、Git 外 live-only addendum 和固定二者 SHA/扫描根/截止时间的 aggregate manifest；production sequencing 不能只拿公开清单。Codex还补充磁盘峰值 gate、现有 external safety backup 工具、研究脚本退役的人工边界变更，以及 staged tree 到 commit/checks 的非自引用证据映射。

### 第一轮：事实被错误改写

DeepSeek 把 134 张表误写成 134 个 SQLite 文件，把“新增至少 13 条 writer operation”改写成 13 个 ownership conflict，并虚构 Git 是 live data authority、RPO/RTO 已批准和 PostgreSQL 用于 analytics。其 must-fix 只是要求实现设计中已经存在的 backup API、ownership 与 addendum，未给出新的触发路径。Codex拒绝这些与输入冲突的结论，但接受其问题方向中唯一合理的抽象提醒：双层清单必须有一个完整审计身份，提交证据必须明确绑定最终树；这两点由 Codex按真实边界独立补强。

### 第二轮：要求违反已批准边界

第二轮把问题严格限制为五个合同并禁止发明事实。DeepSeek仍建议把 live database data 版本化进 Git、把研究内容纳入 immutable application release，并虚构 papers 已经在 public Git 和 8080 是开发端口。这些建议直接违反已批准的 PostgreSQL/live data/artifact 边界和当前阶段禁止事项；它关于 immutable release、backup API 和 exact commit 的建议也都是阶段 2 或当前设计已有能力，没有新增缺口。Codex全部拒绝，不据此扩大范围或上传研究资产。

两轮连续没有有效增量，按用户约束停止第三轮。设计冻结依据是本地代码/DB/备份事实、已批准 capability specs 与确定性门禁；DeepSeek 不构成执行批准或通过证据。

## 阶段 3 最终 RPO/RTO 与 live drift Gate 复核（2026-08-11 追加）

> 实际轮次：2 轮。Codex 先独立补齐 migration/cutover authority-control recovery class，并以既有 Git 外 cutoff 对 live 根执行只读语义漂移检查；发送给 DeepSeek 的只有六类恢复目标、切换控制合同和聚合漂移结论，没有发送 key、Cookie、源码、数据库内容或具体行数、papers/evidence、用户内容、内网地址或原始 evidence。两轮连续没有事实增量，因此停止第三轮。

### Codex 独立修订

新增的 authority-control 类覆盖 cutover unit S0—S4、唯一 writer/backend、cutover epoch、SQLite/PG 水位、路由、验证写、uncertain commit 和审计 ledger。已确认的权威切换状态要求零丢失，只有状态与审计证据持久化后才允许 acknowledgement；目标在一小时内恢复并独立验证，但未验证时 production writes 必须继续保持栅栏，因此 RTO 不会授权不安全恢复。普通 dynamic/task 类明确排除此类状态，其余五类目标不变，全部仍是待人工批准的 target，不是 measured SLA。

只读 drift check 对比了表、列、`user_version`、deployable source/writer path、Git 外 producer/writer path、ownership 和 transaction boundary。上述迁移边界均无变化；已有 research/sentiment 表的普通行数增长不改变 writer、schema 或 ownership，故不被误判为 migration-boundary drift。

### 两轮 DeepSeek 复核与 Codex 判断

第一轮把摘要中明确存在的 S0—S4、唯一 writer、fencing、uncertain-commit reconciliation、audit ledger、ownership 和 Stage 4 gate 全部反写成“缺失”，并错误要求当前提供 measured SLA。Codex逐项以已批准 design/spec 和本轮 proposal 拒绝，没有据此扩大实现。

第二轮明确列出这些既有控制并要求只报告输入能够直接推出的问题；DeepSeek仍逐字重复“没有 ownership/backend matrix、没有 authority 记录、没有 target/measured 计划、没有 aggregate manifest”，与输入和确定性扫描结果直接冲突，也没有提供可复现反例。Codex拒绝全部意见。两轮连续无有效信息增量后停止；最终判断由 OpenSpec、机器清单、只读 drift 结果和远端 CI 负责，DeepSeek 不构成人工批准。

## 阶段 4 首单元设计与非生产演练复核（2026-08-11 追加）

> 实际轮次：2 轮。Codex 先独立复核 live drift、cutover registry、实际 Viewer mutation 函数和 SQLite/PG schema，再形成设计并执行 loopback/non-5432 PostgreSQL dev/test 演练。发送给 DeepSeek 的只有脱敏 unit 计数、状态机、权限与测试结论；没有发送 key、Cookie、源代码全文、数据库行、papers/evidence、用户内容、内网地址、生产凭据或 Git 外原始 evidence。

### 第一轮：设计反驳与有效修订

DeepSeek 返回 5 项 must-fix。`q_number` 类型不一致是成立的问题：live SQLite 是文本并允许 `Q0`—`Q6`，Stage 3 原型 PG 是 integer。Codex接受问题但拒绝其“修改 SQLite 为整数”建议，改为不改 live SQLite、不改写 0001 migration，以 additive 0002 增加文本 `q_label` 和兼容读视图。进一步人工审计还发现 theme legacy id 为文本、title 可空、旧 API 硬删除且没有 revision/idempotency，均纳入兼容和 production gate。

其余意见不是新缺口：首版设计已经有 entity mapping、operation-level fence、uncertain response 按 S3 幂等对账、off-VM restore rehearsal 和 authority zero-acknowledged-loss。DeepSeek建议 uncertain 时回滚 SQLite 会丢失可能已经提交的 PG 写入，明确拒绝；无 RPO/RTO 或规模证据却强制增加 HA 节点也超出已批准边界，拒绝。Codex部分接受“把 additive 步骤写具体”的方向，补充 0001 identity 不变、0002 expand、S0/S1 业务函数拒绝、S2 verification 与首次 formal write/S3 原子提交的步骤。

### 第二轮：真实 SQL、权限和恢复演练复核

Codex完成两次真实 dev/test 演练：migration 重复应用，S1 放弃、S2 零正式写撤回、首个正式 mutation 与 S3 authority revision 原子提交、uncertain-response 幂等 replay、stale conflict、软删除、文本 Q/主题身份/null title/原始时间兼容、最小权限 ACL、pg_dump 旁路 restore 均通过；四套 live SQLite 在演练窗口前后 schema 和文件 hash 不变。独立安全复核又把 writer identity 绑定到 `session_user`，controller 只获首单元 wrapper，writer 无基础表 DML，reader 只读 active view。

第二轮 DeepSeek verdict 为 approve、无 must-fix，但 10 项 should-fix 几乎全部重复声称已实现能力不存在：SQL 已为全部 SECURITY DEFINER 固定 search_path，PUBLIC/base ACL 已撤销，row lock+expected revision、idempotency、soft delete、dump/restore、authority transition、session identity 和合成 legacy backfill 均有真实测试；CSRF 被正确保留为 production 前 blocker。它还在 accepted controls 中虚构 Docker 和 CDC，而本轮明确没有这些系统，故拒绝。第二轮没有新的可复现信息，停止第三轮；外部 verdict 不构成 production 授权。

## 阶段 4 authority control-plane 收口复核（2026-08-11 追加）

> 实际轮次：2 轮。Codex 先独立修复状态/后端不变量、S3→S4 批准与参数保持、unit wrapper 权限和 shared-identity mapping 生命周期，并完成真实隔离 PostgreSQL 17 演练；发送给 DeepSeek 的只有脱敏状态机、权限边界和聚合测试结论，没有发送 key、源码全文、数据库内容、papers、用户内容、内网地址、凭据或 Git 外原始 evidence。

### 第一轮：批准引用复用的有效提醒

DeepSeek关于 backend、writer、epoch、SQLite watermark、mapping fail-closed 和 off-VM recovery 的大多数意见，都是输入中已经明确存在的控制或 production S2 前 blocker。Codex逐项对照 SQL 后确认：generic transition 对 authority row 使用 `FOR UPDATE` 与 expected state/revision，mapping registration 也锁定 authority row并校验 expected revision，controller 只有 unit wrapper 权限，故没有据此引入新锁系统。

其“批准应当正式授权”的抽象提醒揭示了一个仍可收紧的语义：文档要求 S4 使用新批准，但函数原先只要求非空，理论上可复用 S3 当前 approval reference。Codex接受这一点，把“新批准”提升为数据库级不变量：S3→S4 若复用当前批准引用即以 `22023` 失败，并在真实 PostgreSQL 演练加入反例。

### 第二轮：收紧后的真实数据库复核

第二轮输入明确给出了行锁、expected revision、唯一约束、错误 backend/缺失及复用批准/writer drift/未映射实体等真实失败结果，以及 S4 dump/旁路 restore。DeepSeek仍逐项声称这些控制不存在，并错误建议 S3→S4 时从备份恢复数据、把 measured production RPO/RTO 当作当前演练要求；这些建议混淆 authority transition 与 disaster restore，也违反“off-VM recovery 是进入 production S2 前 blocker、当前没有 measured production SLA”的合同，全部拒绝。

两轮后没有新的可复现信息增量，停止第三轮。最终依据是 SQL 约束、真实 PostgreSQL rehearsal、least-privilege ACL、旁路 restore、live SQLite 前后哈希和最终 CI；DeepSeek 不构成 production 授权。

## 阶段 4 首笔 soft-delete authority 语义复核（2026-08-11 追加）

> 实际轮次：2 轮。Codex 先独立确认 `soft_delete_analyst_note_v2` 排除 S2 的真实缺口，再以共享内部 authority helper 统一 create、update、soft-delete 的首笔正式 mutation 语义，并执行真实 loopback、非 5432 PostgreSQL 演练。发送给 DeepSeek 的只有脱敏状态、权限边界和聚合测试结论，没有发送 key、源码全文、数据库内容、papers、用户内容、内网地址、凭据或 Git 外原始 evidence。

第一轮把输入已经明确存在的 authority/object revision、固定 operation scope、least-privilege ACL、非空 backfill 和幂等记录反写为缺失，并建议实现本轮明确保留为 production blocker 的完整认证 adapter；还虚构了并不存在的业务 restore mutation。Codex逐项对照 SQL、角色 ACL 和真实演练后拒绝，没有扩大范围。

第二轮已进一步明确 authority row 使用 `FOR UPDATE`、应用 writer 无 operations schema/helper 权限、legacy row 以 revision 1 接受首笔 delete、旁路 restore 只是灾备验证。DeepSeek仍声称 authority 没有行锁、writer 应直接取得内部 helper 权限，并再次混淆业务 restore 与旁路恢复；这些意见与真实实现和最小权限合同相反，也没有给出可复现触发输入，全部拒绝。连续两轮没有有效增量后停止第三轮。

最终依据是：失败的 missing delete 后 unit-specific S2 verification 仍成功；对非空 backfill 的首笔 soft-delete 与 audit、idempotency、first-formal watermark 和 S2→S3 revision 同事务；uncertain-response replay 不产生重复 revision；S4 与 pg_dump 旁路恢复均保留 delete-first watermark；live SQLite 前后 schema 和文件哈希不变。audit actor 必须来自可信认证 principal 仍是下一轮 adapter/auth production blocker，未被本轮演练冒充为已实现。

## 阶段 4 `user_content_notes` production-readiness 收口复核（2026-08-12 追加）

> 实际轮次：2 轮，其中第一轮在实现前审查有界设计，第二轮在实现与真实 PostgreSQL 演练后审查聚合事实。Codex没有向外部模型发送 key、Cookie、源码全文、数据库行、papers、用户内容、内网地址、凭据或 Git 外原始 evidence。

### Codex 独立实现与真实修订

Codex先审计 live Viewer 的 analyst-note 写路径，确认原实现直接使用 SQLite、请求 body 可提供 actor、没有认证/授权/CSRF、DELETE 为硬删除。修订建立显式 S0/SQLite 默认 route、无 fallback 的 operation-level repository、独立 PostgreSQL reader/writer role、可信 session principal、权限与 CSRF、Git 外 Credential Manager 配置，以及 fail-closed production readiness preflight。tracked 默认 route 仍为 S0，production route、凭据、拓扑和恢复证据缺一即关闭，未改变 live Viewer backend。

只读 stable-identity freeze 发现真实 legacy 别名：两个历史 company id 都指向 COHU。最初“一条 stable key 只能对应一个 legacy id”的假设因此被否定。Codex把合同修订为“legacy identity 唯一、stable identity 允许经核验的多对一 alias”，逐 alias 保存 watermark、evidence、批准和审计，并在真实 PostgreSQL 演练中验证两个 alias 可同时登记且旁路恢复后仍为两条。最终 mapping 共 774 条、collision 0、alias group 1；原始映射保留在 Git 外。

### DeepSeek意见与 Codex判断

第一轮中唯一有价值的抽象提醒是应用侧必须独立证明 SQLite writer fence，不能只依赖“PG enabled”；该要求已进入显式 route 和 repository factory。其余把既有 SQL revision/idempotency/mapping 当作缺失、要求修改 live SQLite、统一 UUID 或建立内容 Git 同步的意见，与冻结合同和代码事实冲突，拒绝。

第二轮在收到明确的实现与测试摘要后，仍建议 S0 双写、失败时 SQLite/PG 互相 fallback、按用户 hash 分片灰度、Redis/JWT、动态配置中心、固定 7 天观察期和新审批系统。这些建议不仅没有可复现的项目内触发路径，还直接违反“单一权威 writer、禁止双写和 silent fallback、不扩张基础设施”的已批准合同，全部拒绝。第二轮未产生有效信息增量，停止第三轮。

最终依据是 621 个 core pytest、55 个 subtest、32 个 Stage 4 定向测试、真实 PostgreSQL 17 migration/ACL/adapter/alias/dump/restore 演练、四套 live SQLite 前后哈希不变、OpenSpec strict 与远端 required CI，而不是外部 reviewer verdict。production topology、VM 外 backup/WAL/restore、repository 公司控制权和正式 cutover window 仍由 preflight 如实保持 BLOCKED。

## 阶段 4 PR #8 浏览器幂等与 stable identity 窄范围复核（2026-08-12 追加）

> 实际轮次：1 轮。Codex 先独立检查浏览器并发竞态、774 条只读 identity mapping 和 production-readiness 边界，再向 DeepSeek 发送不含源代码、数据库行、路径、凭据、papers、用户内容或 Git 外 evidence 的脱敏合同摘要。第一轮没有可复现信息增量，按约束停止，不为凑轮次继续调用。

### Codex 独立诊断与修订

原浏览器 create 虽然能在单次 uncertain response 后保存 identity，但两个同内容点击可能在异步 fingerprint 完成前分别创建 identity，或者并发请求先后结束时错误释放 pending identity。Codex增加 scope 级 in-flight 协调：同内容并发共享同一 Promise 且只发送一次 HTTP 请求，并发改内容 fail-closed；sessionStorage 继续只保存 note key、operation id 与 payload SHA256。真实 JavaScript 测试覆盖响应丢失、5xx、明确 4xx、响应解析失败、reload 式重放、双击竞态和并发内容变化。

只读审计确认 399 个有 ticker 的 company 中，348 个 ticker 带交易所后缀、51 个为裸 ticker；ticker 并非全局 qualified。stable key 因此改为 ticker+venue。唯一重复 ticker COHU 的两个 legacy id 按用户确认的显式 alias approval 合并；TER 的 venue 缺口依据既有 verified security、US exchange 与行情来源作 Codex 只读审计 override，但整个 mapping 仍缺 production cutover 人工批准引用，readiness 保持 BLOCKED。任何未批准 collision、未使用 approval/override 或 venue 冲突均 fail-closed。

### DeepSeek 意见与 Codex 判断

DeepSeek要求 stable identity 包含 ticker+venue、显式处理 alias、保留 ACL/idempotency，并在 production 前验证现场 evidence；这些均已实现或明确保留为下一轮 blocker，没有形成新修订。它同时建议 uncertain response 后不要复用 identity、强制 reload；这与已批准的“同一逻辑 mutation 使用同一 operation identity 查询/重放”合同冲突，而且 reload 并不能证明数据库未提交，因此拒绝。其对 Redis、监控或 production preflight 扩建的泛化建议不属于本轮窄范围，也未给出可复现触发输入，未采纳。

本轮外部 reviewer 没有发现新的可复现 must-fix。最终判断仍由真实 JavaScript 状态机测试、完整 core tests、隔离 PostgreSQL rehearsal、只读 live SQLite 哈希、OpenSpec strict 和最终远端 required CI 负责；DeepSeek 不构成 production 授权。

## Stage 4 production-readiness candidate 复核（2026-08-12）

> 实际轮次：2 轮。两轮均只发送脱敏合同、聚合结果和禁止边界；没有发送 key、Cookie、源代码全文、数据库行、papers、用户内容、内网地址、凭据或 Git 外原始 evidence。

第一轮在实现前审查一致 mapping snapshot、evidence verifier、VM/off-VM 恢复和浏览器 uncertain mutation。DeepSeek关于 silent fallback、off-VM 不得同故障域冒充、浏览器竞态需 fail-closed 的方向被接受并落实为确定性门禁。以下意见被拒绝：tab 关闭或 principal 变化时清除 pending identity 会使 uncertain commit 被新 identity 重复提交；把 SQLite snapshot 描述为全局 transaction ID 不符合 SQLite 事实；强制 VM reboot、HA/failover 或额外节点超出授权且没有恢复目标证据。

第二轮收到的脱敏事实已明确：S0 固定、事务内 schema/content watermark、typed artifact 本体校验、localStorage/principal/payload/locks、真实 PostgreSQL 17.10 TLS/ACL/credential/crash/backup/WAL/whole/side/authority recovery，以及 off-VM 缺失而保持 blocked。DeepSeek仍把上述每一项逐字列为“必须实现”，并混淆 774 条业务 stable mapping 与 authentication identity；还声称必须先具备远程 shell/SMB/WinRM 才可有 runbook。Codex对照实现与现场网络探针后拒绝：业务 stable key 不替代登录身份，后者已有可信 principal 合同；缺远程通道意味着 Codex不能自主执行 VM evidence，不意味着可以伪造通道或阻止生成安全人工手册。

第二轮没有新的可复现触发路径，按用户约束停止第三轮。最终依据是事务快照回归、typed evidence 反例测试、真实隔离 PostgreSQL/recovery rehearsal、浏览器执行测试、live SQLite 不变性、边界门禁与最终 CI；DeepSeek 不构成 mapping、repository governance、S2 或 production cutover 批准。

## Stage 4 加速执行：recovery-set 合同复核（2026-08-12）

> 实际有效轮次：1 轮实现后复核；此前两次设计询问连续要求引入本轮明令禁止的
> shadow write、SQLite/PG fallback 和 S2/S3，且没有给出代码路径或恢复反例，故拒绝并
> 按“连续无信息增量”停止。所有输入仅含脱敏合同和聚合测试结果，没有发送 key、凭据、
> 数据库行、papers、用户内容、内网地址或 Git 外原始 evidence。

Codex独立将 off-VM evidence 从“复制 base backup”重构为完整 recovery set：base
backup、达到 durable target 所需 WAL、target metadata、逐文件哈希、source/storage/
failure-domain identity 和 post-backup sentinel 共同进入内容身份；恢复前原始同机
base/WAL 被移出恢复路径，restore workspace 与 `restore_command` 只从 recovery set
取材。真实 PostgreSQL 17 演练恢复到 sentinel，RPO/RTO 由 durable/recovered watermark
与实际耗时计算；同机 recovery set 仍明确为 `engineering_partial`，没有伪装异机通过。

实现后 DeepSeek返回 `pass`，没有 must-fix 或 should-fix。Codex仍以 missing WAL、目标
WAL 不足、manifest/hash 篡改、缺 sentinel、同机盘符、伪 storage identity、copy identity
不符和 set 外恢复源等 fail-closed 测试，以及真实物理恢复结果作为依据；外部 verdict
不构成 off-VM、mapping、repository governance 或 S2 批准。

## Stage 4 production execution milestone review（2026-08-12 追加）

本轮先由 Codex 独立完成九单元只读 manifest、隔离 PostgreSQL
staging/catch-up、非空 user-content S1 和最小权限演练，再向 DeepSeek 发送不含
源码、数据库行、凭据、论文、用户内容、内网地址或 Git 外原始 evidence 的合同摘要。

DeepSeek 返回 `revise`，但其中六项把输入已经明确存在的 source ordinal、hash/count、
hash-bound mapping approval、revision/audit、sentinel/WAL manifest、exact launch identity
和完整 artifact verifier 反写为“缺失”；另有一项建议 dual-write 和自动 fallback，直接
违反已批准的单一 authority 合同，均被 Codex 拒绝。关于 NetworkService 读取 Credential
Manager 的判断也不成立：PostgreSQL Windows service 不读取应用数据库凭据，凭据属于执行
bootstrap 的 Windows principal。Codex 接受其背后的边界提醒，显式记录 credential owner，
并把未来 application service principal 的凭据配置保留为 S2 前 gate。

Codex 继续独立审计后发现一项 DeepSeek 未识别的真实问题：migration role 原先可以执行通用
`transition_user_content_notes()`，理论上能够请求 S2。实现已改为专用
`prepare_user_content_notes_authority_s1()`，只允许 `ABSENT→S0` 和 `S0→S1`，并撤销
migration role 对通用 transition 的权限。真实 PostgreSQL 17 最小权限演练确认合法 S0/S1
成功，两类 S2 请求均以 SQLSTATE 42501 拒绝，authority 最终仍为
`S1/sqlite_transition`，无 writer、epoch 或 formal commit。

同一轮独立恢复审计还修复了 PostgreSQL WAL 文件名跨 log/segment 边界的枚举：恢复工具现在
根据集群 `wal_segment_size` 计算连续 WAL ordinal，而不是把 16 位十六进制后缀机械加一。
外部 reviewer 没有对该真实问题提供信息增量。后续结论继续由真实 VM、恢复演练、边界门禁和
required CI 负责，DeepSeek 不构成 mapping、repository governance、S2 或 cutover 批准。

### Stage 4 production execution：隔离 Python runtime 复核（2026-08-12）

VM 只读预检确认，受信任的 Python 3.10 bootstrap 本身没有 `keyring`、
`cryptography` 和 `psycopg`。Codex没有修改既有 `quant` 环境，而是把正式执行合同
修订为：在 exact install root 下创建独立 venv，以 tracked
`requirements.lock.txt` 和 `pip --require-hashes` 安装，再用已有标准
canonicalization、Python 3.10、逐包版本和 `pip check` verifier 冻结 executable、
lock hash 与验证 evidence。fresh launch 在写入 exact launch/commit/config/archive
identity 前不占用 InstallRoot；completed retry 必须重新验证同一 isolated runtime，
foreign/incomplete/completed 三种安装状态继续 fail-closed 分流。

DeepSeek收到上述脱敏事实后仍把“必须给出 install root、hash lock、canonicalization、
pip check、executable/lock evidence、completed retry 和 incomplete 状态”逐项列为缺失，
并建议使用与 Windows 项目无关的 `/opt/quant/venv`。这些意见与输入及真实实现直接冲突，
没有提供可复现触发路径，因此拒绝。其背后的权限边界由 Codex独立复核：PostgreSQL
Windows service 不执行 Python；隔离 venv 与 Credential Manager 属于已记录的 Stage 4
operator principal，未来 application service principal 仍是 S2 前人工 gate。外部 verdict
不构成 production、mapping、off-VM 或 S2 批准。

### Stage 4 production execution：TLS 与 pre-install retry 复核（2026-08-12）

真实 VM 首次 bootstrap 在创建服务、数据目录和凭据之前失败，原因是官方 PostgreSQL
17.10 Windows ZIP 不含 `openssl.exe`，而旧入口错误把它列为 archive 必备二进制。Codex
独立修订为：其余六个 PostgreSQL 二进制和固定版本继续 fail-closed；只有 hash-pinned
Python 3.10 runtime 完成逐包与 `pip check` 验证后，才以 `cryptography` 生成 RSA-3072、
SHA256、localhost DNS/IP SAN、CA=false、serverAuth 的证书。生成器 exclusive-create 三个
TLS 文件，生成后重新加载验证私钥匹配、root 副本和自签名，evidence 只保存证书身份，
不保存私钥。Windows 私钥在递归服务授权后再次禁用继承，仅 SYSTEM/Administrators 完全
控制、NetworkService 只读。

pre-install 解压失败也不再留下语义不明的 staging：只有 InstallRoot 尚不存在、服务不
存在、55440 无 listener，且 staging 严格属于同父目录 `InstallRoot.staging.<32hex>` 时，
才允许将整目录原子隔离到本 launch 的 failed 路径，并记录主失败、原路径、文件数、总
字节和文件集 hash；foreign/current/completed/路径冲突或观测不足均拒绝。隔离目录不能
作为安装复用。

DeepSeek 共复核两轮。第一轮把 Unix `0600` 作为私钥权限要求；Codex接受其最小权限意图，
按 Windows 服务事实转化成上述 SID ACL，并增加生成后密码学自验。它同时要求继续把真实
不存在的 `openssl.exe` 列为必需文件，和确定性现场证据冲突，拒绝。第二轮基于公开提交
`8707a58111def28f682b2436291e07fe6da8f764` 返回 `pass`、无 must-fix/should-fix；其
accepted-controls 文本仍误写了一次“OpenSSL required binary”，Codex未把这一错误标签
当作实现事实。最终依据是 672 个 core tests、82 个 Stage 4/browser 定向测试、17 个
TLS/quarantine 测试、PowerShell parser、compile、OpenSpec strict、tracked/staged boundary
和 SQLite ratchet；外部 reviewer 不构成 S2/S3、mapping、off-VM 或 cutover 批准。

### Stage 4 production execution：Windows PowerShell CSPRNG 兼容复核（2026-08-12）

真实 VM 第二次 bootstrap 在服务、listener、database 和 credential 建立前失败：Windows
PowerShell 5.1 所在 .NET Framework 没有静态 `RandomNumberGenerator.Fill()`。失败目录按
launch identity 原子隔离；PostgreSQL service 不存在、55440 无 listener、8080 健康。
Codex 将通用 secret generator 改为 `RandomNumberGenerator.Create()` 实例，在 `try` 中调用
`GetBytes()`、在 `finally` 中 `Dispose()`；密码学随机源、字节长度和不记录 secret 的合同均
未降低。真实 `powershell.exe` 回归执行同一 API，验证输出缓冲区长度和非全零，但不打印随机值。

DeepSeek 仅收到上述脱敏故障、修订和测试摘要。它把已经完成的 `Create/GetBytes/Dispose`
修订再次列为 must-fix，并泛化要求验证之后才会建立的 listener/service；没有给出当前补丁的
新反例。Codex 接受其“不得降低密码学随机和资源释放”的方向，但这些要求已由实现与回归覆盖，
没有据此重复修改或提前宣称 VM bootstrap 通过。外部 verdict 不替代完整测试、最终 CI 和新的
exact-commit VM 现场执行。

### Stage 4 production execution：PG17 locale 初始化合同复核（2026-08-12）

真实 VM 第三次尝试在 service、listener 与数据库 authority 建立前因宿主中文 code-page locale
失败；PowerShell 还把 `initdb` 的本地化 stderr warning 升格为 terminating error。Codex 没有修改
系统 locale，而是把 PG17 cluster 固定为 builtin `C.UTF-8`、UTF8、`simple` text search 和 data
checksums；配置 validator 对任一 drift fail-closed。`initdb` stderr 被捕获且不写 evidence，成败只
由 native exit code 决定。最终 verifier 再从真实 server 与 `pg_database` 反查 encoding、text
search、checksum、locale provider 与 locale，不能靠配置自证。隔离的同版 `initdb` probe 已建立
`PG_VERSION=17` cluster；没有注册 service 或 listener，也没有触碰 8080。

DeepSeek把输入中已明确实现的 locale、checksum 与 catalog verifier 再次列为 must-fix，并虚构
“PostgreSQL 应监听 8080 且 24 秒内就绪”；8080 是现有 Viewer，PostgreSQL 固定端口是 55440，
因此该建议会制造真实冲突，明确拒绝。它关于不泄露 native output、保留非零退出失败的方向已由
捕获变量、`native_output_recorded=false` 与 exit-code gate 满足，没有新增可复现缺口。最终依据
仍是新提交自己的完整测试、required CI 和 exact-commit VM bootstrap，而不是外部 verdict。

### Stage 4 production execution：Windows service 崩溃恢复合同复核（2026-08-12）

真实 VM 第四次尝试已经通过固定 locale 的 cluster 初始化、TLS 与私钥 ACL，并完成正常的服务
启动、停止和重启；失败发生在受控 postmaster crash 后的“自动重启”假设。两次独立临时服务
探针确认：即使配置 SCM failure actions 和 failure flag，`pg_ctl runservice` 在 postmaster 退出后
仍把服务报告为 `Stopped`/成功状态，SCM 因而不会执行 failure recovery action。Codex据此删除不实
高可用承诺：通过 `postmaster.pid`、listener PID、`postgres.exe`、data-dir command line、
`Win32_Service` 父进程共同验证被终止进程；确认 crash 后服务停止且 listener 消失；再显式
`Start-Service`，要求新 postmaster PID、listener 和查询探针恢复。evidence 明确记录
`postmaster_crash_automatic_restart=false`、需要监控/操作者触发、恢复方式与耗时。真实合成探针
已通过，并完整清理临时 service、listener 和 data root，8080 保持健康。

DeepSeek 把“自动重启为 false”同时描述为事实和“违反 automatic_restart=false 的要求”，又称实现
没有识别 postmaster/PID/命令行、没有显式恢复触发；这些均与输入事实和实测直接冲突。它要求加入
cutover hook、高可用和 Viewer 生命周期展示，超出本轮 S0/S1 infrastructure readiness，且用户明确
禁止 S2/S3 与生产应用切换，故拒绝。其泛化的状态过渡提醒已由有界等待、Stopped/listener 双条件和
新 PID 验证覆盖，没有形成可复现新增缺口。本轮不因 reviewer 的矛盾结论降低门禁或扩张范围。

随后 exact-commit VM bootstrap 通过 service lifecycle 后在 credential probe 暴露出独立的
Windows resolver 缺陷：探针仍使用 `localhost`，宿主优先解析为 `::1`，而经审计的数据库监听
仅开放 `127.0.0.1`，连接因此被拒绝。通用管理连接本来已经固定 IPv4；Codex将 credential
探针和 runtime config 一并统一到确切的 `127.0.0.1`，保留 TLS IP SAN 验证，不通过扩大监听
范围解决。该问题由真实现场发现，DeepSeek本轮没有识别或提供信息增量。

下一次 exact-commit 运行的初始/新凭据正向探针已执行，但预期的“旧密码拒绝”触发
Windows PowerShell `NativeCommandError`：脚本级 `ErrorActionPreference=Stop` 在函数读取
`LASTEXITCODE` 前终止，因而把正确的拒绝结果误判成 bootstrap 失败。Codex把这一行为限定在
认证探针内部：暂时以 `Continue` 捕获且不输出 native 结果，保存 exit code 后恢复全局策略，
由调用者分别断言初始/新凭据必须成功、旧/撤销凭据必须失败。没有放宽任何认证合同，也没有
记录密码或 psql 错误原文；DeepSeek此前未识别该现场兼容缺口。

### Stage 4 production execution：隔离 CLI 参数合同复核（2026-08-12）

真实 VM bootstrap 在已完成隔离 Python runtime、TLS 生成和前置检查后，到 identity mapping
阶段因入口合同不一致失败：allowlisted dispatcher 始终向模块入口转发参数列表，而
`stage4_identity_mapping.main()` 仍是唯一的零参数入口。Codex只把该入口统一为
`main(argv=None)` 并将 `argv` 交给 `argparse`，未改变映射规则、SQLite 只读合同、PostgreSQL
状态或 authority。回归同时覆盖八个 allowlisted 入口的签名合同，以及通过真实 dispatcher
对临时 SQLite fixture 执行 identity mapping；另一个只读现场探针成功生成预期 774 条映射。

DeepSeek收到脱敏后的 dispatcher/CLI 事实与测试摘要，结论为 `approve`、无 must-fix。它建议
对每个入口都增加完整 dispatcher 执行测试和补充开发规范；Codex部分接受“防止全体入口签名
漂移”的目标，当前全 allowlist 签名门禁已经覆盖，且出错入口已有端到端执行测试。逐一执行
所有重型 CLI 会引入环境依赖而不增加本缺陷的有效覆盖，因此不扩张；统一入口合同已由代码、
定向测试和只读现场探针共同证明。外部 reviewer 不构成 mapping、off-VM、S2/S3 或 cutover 批准。

下一次 VM bootstrap 进一步暴露了 dispatcher 参数命名空间冲突：外层和 recovery 子命令都使用
`--repo-root`，旧 `parse_known_args()` 会扫描整段命令并吞掉子命令同名参数。Codex改为强制
`--` 分隔 dispatcher 与子命令参数；外层只解析前缀，后缀逐 token 原样转发，缺少分隔符时
fail-closed。bootstrap 的八个隔离入口全部使用同一边界，回归验证重名参数保留、无分隔符拒绝、
PowerShell 语法以及 recovery help 的真实隔离调用。DeepSeek窄审查结论为 `pass`，无 must-fix
或 should-fix；未提出新的可复现缺口，因此在一轮后停止。
### Stage 4 production execution：Windows PowerShell UTF-8 BOM 合同复核（2026-08-13）

真实 VM bootstrap 在 identity mapping 与只读 cross-check 完成后，于 recovery runtime evidence 读取阶段失败。根因是 Windows PowerShell 5.1 的 `Set-Content -Encoding UTF8` 写入 UTF-8 BOM，而 Python 入口按无 BOM `utf-8` 解码；这属于跨运行时序列化合同不一致，不是 PostgreSQL、mapping 或 recovery 数据本身失败。失败后现场已只读确认：`HonghuPostgreSQL17` service 不存在、55440 无 listener、install root 不存在、8080 健康，因此没有形成 production authority 或半安装状态。

Codex 将 Stage 4 原子 JSON writer 固定为 .NET `UTF8Encoding(false)`，所有关键 Stage 4 文件型 JSON reader 统一通过共享 helper 以 `utf-8-sig` 接受有/无 BOM 的 UTF-8；UTF-16、损坏 JSON 和合同字段错误仍然 fail-closed。两个由 Python 输出、再由 PowerShell落盘的 runtime evidence 也改用同一无 BOM writer。回归覆盖有/无 BOM、中文内容、UTF-16 拒绝、真实 Windows PowerShell 无 BOM 字节以及 recovery reader 路径。最终本地证据为 695 个 core tests 通过、94 个 Stage 4/API/browser 定向测试通过、PowerShell parser、compile、OpenSpec strict 与 diff check 通过。

DeepSeek 只收到脱敏后的根因、编码合同、覆盖范围和测试摘要，结论为 `pass`，无 must-fix。其 should-fix 仅重复已经实现的共享 reader、无 BOM writer、验证门禁和合同记录，没有形成信息增量；Codex 逐项以代码和回归验证后不再开启第二轮。本次外部复核不构成 PostgreSQL 部署、mapping approval、off-VM recovery、S2/S3 或 cutover 批准。

### Stage 4 production execution：isolated bootstrap import 边界复核（2026-08-13）

精确提交 `0a4d0c1f7d08d605426589e00d6052371ab275bb` 的 VM 运行在 contract preflight 即失败：bootstrap 仍以 `python -I -B` 直接执行 contract 文件，而前一轮引入的共享 JSON helper 需要从 reviewed repo root 导入 `tools.migration`。隔离模式正确忽略了工作目录和 ambient `PYTHONPATH`，因此暴露了入口边界回归。现场随即确认 service、install root 和 55440 listener 均不存在，8080 健康；没有形成数据库或 authority 状态。

Codex 没有撤销隔离或依赖环境变量，而是把 bootstrap contract 纳入既有 allowlisted isolated dispatcher；fresh-install 与 completed-install resume 两条路径均通过显式 `--repo-root`、allowlisted module 和强制 `--` 参数边界执行。回归实际启动 `python -I -B` dispatcher 并导入 contract，同时复核全部 allowlisted invocation 的分隔符、入口签名和 PowerShell 语法。DeepSeek 只收到脱敏后的故障、修订、隔离合同与测试摘要，结论为 `pass`，无 must-fix/should-fix；其判断与真实代码和回归一致，没有信息增量，因此一轮后停止。该复核仍不构成 PostgreSQL 部署、mapping、off-VM recovery、S2/S3 或 cutover 批准。

### Stage 4 production execution：pg_basebackup TLS root 合同复核（2026-08-13）

真实 VM 已通过固定 PostgreSQL 17、TLS 生成与 ACL、service lifecycle/crash recovery、角色凭据 create/rotate/revoke 和 identity mapping；recovery 阶段留下的 run 目录为空，PostgreSQL 日志在同一时点记录 SSL connection EOF。代码审计确认所有 libpq subprocess 均强制 `PGSSLMODE=verify-full`，但 `pg_basebackup` 未继承 psycopg 路径已经显式使用的 runtime `sslrootcert`。Codex 将共享 subprocess helper 扩展为显式 TLS root 输入：解析并验证 root 文件存在，移除 ambient `PGSSLROOTCERT`，再把 exact reviewed root 注入 `pg_basebackup`；缺失 root 继续 fail-closed，密码只在子进程环境中存在且不进入 evidence。

DeepSeek 只收到上述脱敏现场、代码差异和回归摘要，结论为 `pass`、无 must-fix。其唯一 should-fix 是增加“root 路径不存在必须拒绝”的测试，而该测试已经与 exact `PGSSLMODE/PGSSLROOTCERT` 断言在同一 revision 中实现，因此没有信息增量，不再开启第二轮。外部复核不替代 exact-commit CI、真实 VM recovery、off-VM failure domain、mapping approval 或 S2/S3 授权。

### Stage 4 production execution：最小权限 verifier 控制面读取复核（2026-08-13）

真实 VM 已完成 PostgreSQL 17.10、TLS、service/crash recovery、角色凭据、identity mapping、
物理 recovery 和九个单元的 staging reconciliation，最终 verifier 使用
`honghu_migration` 读取 migration identity 时被 `operations.schema_migration` 的表级 ACL
拒绝。失败证据在 cleanup 前保存了原始 traceback，随后 service、listener 和 install root
按既有合同安全隔离，没有进入 S2/S3 或产生正式 PostgreSQL 业务 mutation。

Codex没有恢复全能管理员核验，也没有给 migration role 广泛的 `operations` schema 表权限；
只增加 verifier 实际需要的四张控制面表的 `SELECT`：migration identity、cutover authority、
dependency mapping 和 idempotency ledger。一次性 PostgreSQL 17.10 隔离集群按真实
0001/0002/0003 migration 与 role grants 建库后，以 `SET ROLE honghu_migration` 执行 verifier
全部控制面查询均通过，并确认没有 `GRANT SELECT ON ALL TABLES IN SCHEMA operations`。

DeepSeek只收到上述脱敏权限边界、失败类型和测试摘要，返回 `pass`、无 must-fix；其判断认为
四张命名表覆盖 verifier 的已声明读取合同且没有扩大写权。Codex仍以真实 PostgreSQL 角色执行
而非字符串断言作为主要证据，没有开启无信息增量的第二轮。外部复核不构成 mapping、
off-VM recovery、S2/S3 或 cutover 批准。
### Stage 4 production execution：持久化 S0/S1 装载复核（2026-08-13）

Codex 在真实 production PostgreSQL 中发现此前九单元“装载成功”报告并未留下持久记录。根因不是 PostgreSQL 或 VM，而是 psycopg 的 authority guard `SELECT` 先开启隐式外层事务，使每个 `load_snapshot()` 的事务块降为 savepoint；连接关闭时九个单元整体回滚。修订后 guard 连接使用 autocommit，每个 unit 拥有并提交一个顶层事务，连接关闭后再由全新会话逐单元验证 `reconciled`、`formal_business_data=false` 和行数。exact commit `af510bce455a59c47a0007cfc54928951303b48b` 的 push/PR required CI 全绿后，VM 实际装载 9/9 unit、2,244,285 行，source/target identity 全部一致，authority 前后均为空，路由保持 S0/SQLite，8080 正常。

第一轮外部复核在尚未获得 VM 持久化结果时错误要求 staging 记录标记 `formal_business_data=true`，并把 S0/S1 preparation 混同为 authority S1；这会违反“不产生正式 PostgreSQL 业务 mutation”和“不进入 S2/S3”的已批准边界，因此 Codex只接受其“顶层事务必须显式并可复核”的一般方向，拒绝具体状态建议。VM 成功后第二轮只发送脱敏行数、事务、authority 和剩余 gate 摘要；DeepSeek 返回 `pass`、无 findings。Codex核对后停止复核：该结果支持把现状表述为 durable S0/S1 staging，不构成 mapping、off-VM recovery、repository governance、S1 authority 或 S2 批准。

### Stage 4 `user_content_notes` 切换与两份恢复集轮换复核（2026-08-13）

Codex先独立实现首单元生产切换合同：经过批准的 mapping 与 off-VM recovery、S1 reconciliation、
SQLite writer fence 和最终水位共同约束 S2；首笔 create/update/soft-delete 与 revision、audit、
idempotency、first-formal watermark 和 S2→S3 在同一 PostgreSQL 事务提交；应用只允许同一 writer
和 epoch 的 S2→S3 单调观察，用于 uncertain response 的同 identity 重放，并拒绝 silent fallback、
dual writer、S4/回退和 epoch drift。生产写入口要求 TLS、可信认证 principal、CSRF 和最小 ACL，
HTTP 8080 写继续拒绝。定向 44 项与 core 735 项、21 skipped、55 subtests 在此实现上通过。

第一轮 DeepSeek 只收到上述脱敏合同、现场尚未执行的明确边界和测试汇总，返回 `pass`、无
must-fix/should-fix。Codex没有把该结果当作 VM、recovery、S1、S2/S3 或上线证据；独立复核后
发现设计中的“最多两份验证集”尚未成为代码门禁，因而继续修订。

第二轮只审查恢复集轮换：新集合必须先通过 exact manifest/hash、WAL 目标和 sentinel whole
restore；之后再次验证 current 及同一受控根下全部有效集合，确认 current 在最新两份窗口内才
整目录删除第三旧集合。无 manifest、篡改、symlink、根外路径或 current 无效均 fail-closed；
中断目录不计作有效恢复集，也不由 retention 逻辑自动删除。新增回归证明三份只保留最新两份，
且 current 无效时旧有效集合不会被删除；55 项 recovery/bootstrap tests 通过。DeepSeek再次
返回 `pass`、无可复现意见，因此停止后续轮次。失败目录的最终清理由独立 inventory/dry-run
负责，外部 reviewer 仍不替代真实 off-VM restore 和生产切换验收。
