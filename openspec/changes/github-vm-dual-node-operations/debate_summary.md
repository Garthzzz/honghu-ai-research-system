# DeepSeek V4 Flash 架构交叉审核摘要

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

发送给 DeepSeek 的只有公开仓库、公开 commit、上述脱敏控制流、测试名称和汇总结果，没有发送 key、Cookie、数据库内容、papers/evidence、用户内容、内网地址或 VM 原始 evidence。DeepSeek 返回 `needs_changes`，但四项 must-fix 均与公开实现直接冲突：

- 声称 gate 抛错后 catch 不执行 cleanup；实际 `catch` 先保存 `failure.primary`，再调用身份受控 cleanup 与 pointer recovery；
- 声称 final-state capture 不保证运行；实际 cleanup 后有独立 `try/catch`，成功或失败都写 `failure.final_state_capture`，最后重新抛出保存的 primary；
- 声称窗口没有验证 health/listener/current/manifest；实际 usable 条件要求 HTTP、payload、成功状态和 listener query，所有 usable 状态再通过 `Test-HonghuProductionUnchanged` 比较 identity、listener、current pointer 和 broadcast manifest。`current` 可以合法不存在，但其存在性和 hash 必须前后一致；
- 声称测试没有核对 gate 与 recovery；`test_gate_evidence_remains_immutable_when_cleanup_state_recovers` 明确断言 gate=false、兼容 post_state 仍为 gate、recovery=true、post-cleanup 状态独立、primary 不变、observed 仍指原 gate，并验证第二次 gate 写入被拒绝。

DeepSeek 在 `uncertainties` 中也承认没有完整看到具体代码路径，因此 Codex 拒绝上述无可复现依据的意见，没有据此放宽 production gate。确定性依据是 569 passed、21 skipped、55 subtests、PowerShell parser 0 error、tracked boundary、SQLite ratchet 和 OpenSpec strict；远端 push/PR Actions 与 exact-commit artifact 仍需按最终提交重新核验，外部 reviewer 不替代 VM 重验。
