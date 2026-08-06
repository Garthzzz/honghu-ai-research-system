# 阶段 2 实施与验收报告

> 状态：实施修复已完成，VM 18080 人工验收尚未执行，阶段 2 不具备退出条件。PR #3 保持 open、未合并；阶段 2 HALT 未批准，阶段 3 未开始。

## 2026-08-06 VM content preflight 阻断与修复

第二次 VM 人工执行在候选启动前被 preflight 正确阻断，18080 没有 listener。实测 `C:\industry_demo\docs\industries` 与 `C:\industry_demo\papers` 存在，`docs\themes` 不存在；四库对象、列和只读探针全部通过，`research.db.theme` 有 5 条正常记录。代码审计确认主题详情页先读取数据库中的主题、行业和公司关系，主题 Markdown 由容错加载器作为增强内容读取；文件不存在时页面仍展示数据库内容，并明确显示“尚无主题分析 md”。本地旧目录中的 `docs/themes` 也是空目录，Git 不保存空目录，因此不存在尚未识别的主题文件权威。

根因是 deployment policy 和 preflight 把三个外置路径硬编码为同一强制等级，把数据库承载、Markdown 可选增强的主题页误定义成无条件依赖。修复把外置路径改成 manifest 驱动的逐路径合同：`docs/industries` 和 `papers` 为 required，缺失或类型错误仍 fail-closed；`docs/themes` 为 optional，缺失会明确写入 preflight/evidence，但不会伪装存在或阻止数据库主题页。原 `--allow-missing-content` 绕过参数已经删除，防止 required 路径被弱化。

合成 fixture 不再创建空 `docs/themes`，并新增数据库主题和关系；schema 合同新增主题必需列、关系表和只读探针；代表性 smoke 增加数据库-only 主题页检查，同时核对页面明确报告 Markdown 缺失。smoke 因而由 15 项增至 16 项。旧提交 `f6926410475cf5c646641f6d7056736abae1453d` 使用错误的强制内容合同，已经撤销 VM 验收资格。新的可部署 SHA 必须来自本次修复后的绿色 push artifact，并与绿色 PR artifact 的 `pull_request_head_sha` 一致。

## 2026-08-06 VM runtime verifier 阻断与修复

首次 VM 人工执行在 Python runtime verification 处按设计停止。74 个 hash-pinned distribution 已安装且 `pip check` 通过，但旧 verifier 仅执行小写转换并把下划线替换为连字符，没有按照 Python packaging 规范把点号、连字符和下划线统一处理。因此 lockfile 中的 `backports-tarfile`、`jaraco-classes`、`jaraco-context`、`jaraco-functools` 与 metadata 返回的点号或下划线名称被错误判为缺包。

修复统一使用 `packaging.utils.canonicalize_name` 处理 lockfile 和 installed metadata 两侧名称，不为具体包增加例外。回归测试覆盖点号/连字符/下划线和大小写等价、真实 jaraco/backports 命名、缺包、版本不一致、规范名冲突以及 `pip check` 失败；后三类仍 fail-closed。部署脚本和 exact-commit Actions evidence 现在都保存 verifier 的结构化结果，包括标准化算法、锁定包数量、mismatch 和 `pip check`。

修复提交 `05fd0ab04575188798a39cdaa8724c777e743090` 已在真实全新 Python 3.10 环境中按 lockfile 安装 74 个 hash-pinned distribution；verifier 返回 `ok=true`、`mismatches=[]`、`pip_check.ok=true`。完整本地结果为 550 passed、21 个受治理 artifact 测试分层跳过、53 subtests passed；push Actions run `31086840297` 和 PR Actions run `31086843575` 的两个 job 均真实绿色。下载后的 push artifact 绑定该分支提交且具备 VM 候选资格；PR artifact 绑定临时 merge commit，并记录 `pull_request_head_sha` 为同一分支提交。

旧 VM 候选提交 `028572f7a1895636b6d8b46d3ff0d3019dd56309` 已失去验收资格，不得继续部署。新的 VM SHA 只能取自本次修复最终分支提交的绿色 push artifact，并须与绿色 PR artifact 的 `pull_request_head_sha` 一致。VM 尚未重新执行，因此本节不改变阶段 2 状态。

## 1. 隔离和禁止边界

- 实施分支：`phase2/repeatable-release`；隔离工作目录：`D:\quant\industry_demo_stage1`。
- 活动目录 `D:\quant\industry_demo` 未切换分支、未 reset/clean；四套 live SQLite、现有 Viewer、8080 和七个计划任务未修改。
- 未安装 PostgreSQL，未迁移数据库或任务，未配置 VM deploy credential，未向 Git 提交数据库、papers/evidence、备份、用户内容或 secret。
- 仓库按用户要求继续 public；这不构成 production authority。

## 2. 本轮重新审计发现的根因

1. 旧候选由 CLI 再启动 Flask 子进程，PID 文件可能只指向外层进程，停止和失败清理存在残留与 PID 复用风险。
2. VM evidence 中“任务未改、8080 未切换、数据库只读”等部分结论是静态声明，没有部署前后采集证据。
3. `-Python python` 依赖 VM PATH，不能证明使用受支持的 Python 3.10 和精确 lockfile 环境。
4. PDF/source 相对路径和锂计算器旧 cache 回退仍可能从 immutable release 根解析，外置 content/state 闭包不完整。
5. schema fingerprint 被计算但未用于兼容决策，而表存在检查又不足以支持强意义的 schema compatibility。
6. smoke 只覆盖 health、工具页和一个写 403，不能证明四库、外置 PDF、Opportunity Lens、公司财务与计算器链路。
7. 原 evidence 绑定旧分支头，不能代表当前 PR head。
8. 第一轮远端 SHA `b9ce946ea5b74497bdc00befa80e814efef43435` 的 clean test 还暴露了 Windows runner 8.3 短路径与规范长路径的测试误判；真实日志显示仅该断言失败，不是应用回归。
9. 将代表性 smoke 纳入 exact-commit evidence 后，合成 fixture 首次真实暴露首页、行业、估值和公司页缺少依赖表；这证明旧 smoke/fixture 确实过弱，而不是简单增加测试数量即可。

## 3. 已完成修复

- 候选 CLI 自身直接运行 Flask，记录进程即 listener owner；关闭 reloader，不再保留外层父进程。
- PID 身份扩展为 PID、启动时间、解释器、命令行 SHA256、launch id、commit、manifest 和端口；停止、重复部署和失败回收均先核验身份，拒绝误停复用 PID。
- 进程从解释器参数开始使用 `-B`；preflight 报告以 SHA256、commit、manifest、schema contract 和 data/content/state root 绑定给进程，避免启动后再次递归散列 release 和生成 `__pycache__`。
- VM 部署要求显式 Python 3.10 绝对路径，在候选根按 lockfile hash 创建隔离 venv，以 `--require-hashes` 安装并逐包核验；不碰生产任务环境。
- VM evidence 分为静态代码保证、部署前状态、部署后状态、实测结果和未验证事项；任务定义 XML hash、8080 health/listener、生产 current/broadcast identity 均前后采集比较。
- 数据库相对 source/PDF 路径从外置 content root 解析；正式计算器模型来自 release 内 tracked config，旧 cache 只允许从外置 state root 回退；路径逃逸和绝对外部路径被拒绝。
- schema 合同收窄为“阶段 2 代表性只读路由”，同时增强为 `mode=ro/query_only`、对象类型、必需列、版本范围和只读探针；完整 fingerprint 仅作诊断，不再声称证明全部列、索引、约束、视图和写路径兼容。
- 代表性 smoke 共 16 项，覆盖 health、首页、行业、行业估值、公司、缺少可选 Markdown 时的数据库主题页、情绪、Opportunity Lens 列表与 run、外置 PDF、工具首页、锂/铜/锂电池计算器、静态 CSS 和写方法 403。
- exact-commit CI evidence 现在会真实启动合成候选、核对 health PID、Windows listener PID、16 项 smoke、停止后端口释放、release 无 `__pycache__`，再执行 code-only rollback 和四库 hash 不变检查。
- Windows 路径测试改为已有文件身份比较，仍保留路径逃逸拒绝；没有 skip、xfail、删除测试或降低合同。

## 4. 已取得的本地确定性证据

在实现提交 `3b3778f7c5deada4f4a6fbe849ca390c219467ee` 上：

- exact-commit manifest：571 个文件、24,549,498 bytes，SHA256 `b6e23e5d03d7655a3b8cdda7a6b11f189aa2bfe9843f79b9ecadb47ee170047d`；禁止资产三项均为 false；
- preflight、对象/列/只读探针 schema 合同通过；
- 候选进程 PID 44932、Windows listener PID 44932、health PID 44932 三者一致；
- 15 项代表性 smoke 全部通过；停止后端口释放；release 内 `__pycache__` 为 0；
- code-only rollback 实际执行，四个合成数据库 SHA256 前后不变；
- 完整 core：543 passed、21 个受治理 artifact 测试分层跳过、53 subtests passed；
- tracked boundary、SQLite ratchet、compile 和 OpenSpec strict 通过。

后续仅修复 Windows 文件身份断言的提交为 `a6b19f2264a266a760688a46937d653f97e43c26`；聚焦回归 4 项通过。该提交的 push Actions 两个 job 已真实绿色，PR Actions 在本文修订时仍在运行。最终可部署 SHA 必须取本分支最后一次 push 与 PR 的两个 Actions job 均绿色的完整 40 位 SHA，不能从本文中的缩写、分支名或 PR 号推断。

## 5. 统一 evidence 绑定合同

tracked 报告不能可靠地把“包含它自己的 Git commit SHA”硬编码进自身内容，因为修改 SHA 字段会再次改变 commit。为避免伪精确或永远落后一笔，最终身份采用以下同一提交闭包：

1. `push` workflow 的 `GITHUB_SHA` 才是可部署分支头；其两个 job 必须均为 success，且 `stage2_evidence.json` 的 `binding.commit_role=branch_commit`、`eligible_as_vm_candidate_sha=true`；
2. PR workflow 默认检出 GitHub 临时 merge commit；它用于证明分支头与 base 的合并结果通过 required checks，不得把该临时 merge SHA 当成 VM 部署 SHA；
3. PR artifact 另外记录 `pull_request_head_sha`，必须与上述 push 分支头一致；
4. push artifact 在 `binding.commit_sha` 和 `binding.github_run_id` 写入可部署 SHA/run，同一 artifact 内 release manifest、preflight、candidate lifecycle、rollback 和数据库 hash 均由该 checkout 生成；
5. VM 脚本的 `requested_commit_sha`、candidate health commit 和 release manifest 必须等于该 push exact SHA；
6. 内网客户端再次核对 18080 health 的 commit。

`release_identity.json` 记录此绑定合同和最近一次已验证实现，而不冒充尚未执行的 VM 证据。VM 验收后再补最终实测记录；在此之前 `vm_readonly_candidate_verified=false`、`phase2_halt_approved=false`。

## 6. VM 只读候选仍是阻塞项

Codex 没有替用户执行 VM PowerShell 命令。新的人工步骤见 `stage2/vm_readonly_candidate_runbook.md`，它要求：

- 先确认 VM 上真实 Python 3.10 绝对路径；没有则 HALT，不从 PATH 猜测；
- 只检出最终绿色 full SHA；
- 候选根为 `C:\honghu-ai-research-candidate`，生产根仍为 `C:\industry_demo`，端口只用 18080；
- VM 本机证据成功后，再从另一台内网客户端验证 18080 commit 和原 8080 可达；
- VM evidence 和客户端证据交回人工审查。

在上述证据完成前，不得宣称阶段 2 完成，不得勾选 VM gate 或 HALT，不得合并 PR #3，也不得进入阶段 3。
