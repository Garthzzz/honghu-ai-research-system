# 阶段 2 实施与验收报告

> 状态：VM 已完成候选启动和 16 项 smoke，但生产不变性 evidence 被 cleanup 后采样覆盖；本轮代码修复已完成本地定向验证，仍须取得新的 push/PR 绿色 full SHA 和 exact-commit artifact 后重新执行 VM 18080 人工验收。阶段 2 不具备退出条件。PR #3 保持 open、未合并；阶段 2 HALT 未批准，阶段 3 未开始。

## 2026-08-07 production gate evidence 覆盖缺陷与稳定采样修复

真实 VM 使用提交 `67cc70ec93908db982d8f16f81c49f1ae3b9c90a` 时，18080 成功启动，commit/PID/数据库合同正确，16 项代表性 smoke 全部通过，写请求门禁返回 403。最终 production gate 抛出 `Production 8080/current evidence is not stable.`，随后候选清理成功、端口释放、candidate pointer 恢复，8080 正常。但最终 JSON 却显示 `observed.production_8080_and_pointer_unchanged.verified=true` 且 `reasons=[]`。

确定根因是同一个 evidence key 被两个时间点复用：正常路径先采集 gate-time `post_state` 和 production comparison，据此抛错；catch 在停止候选、恢复 pointer 后再次采集生产状态，并把 cleanup 后的 comparison 重新写回 `observed.production_8080_and_pointer_unchanged` 与 `post_state`。因此真正触发 gate 的原始 false/reasons 被销毁，只留下恢复后的正常状态；这不是门禁“误抛后又自行纠正”，而是证据生命周期设计错误。

evidence 升级为 `honghu.vm_readonly_candidate_evidence.v5`：

- `pre_state` 保存部署前任务、生产状态及完整采样窗口；
- `gate.post_state` 与 `gate.comparisons` 是原始门禁证据，一经 `evaluated=true` 即不可覆盖；顶层 `post_state` 和原 `observed.*_unchanged` 只作为指向该原始 gate 的兼容别名；
- `failure.primary` 永久保存主失败；`failure.cleanup`、`failure.pointer_recovery`、`failure.final_state_capture` 分别记录次级动作；
- cleanup/pointer recovery 后的新状态只进入 `recovery.post_cleanup_state` 和 `recovery.comparisons_to_pre`。即使 recovery comparison 为 true，也不能改写 gate 的 false/reasons。

生产稳定性门禁同时从单次请求改为三次有界采样，要求至少两个可用样本，且所有可用样本在实际支持的 health identity、listener PID、production `current` 和广播 manifest 上相互一致。一次孤立的不可达或不可解析样本会连同错误原样保留为 warning；可用样本不足、成功样本之间冲突、真实身份/pointer/manifest 变化仍 fail-closed。这个改动减少旧 8080 的瞬态访问噪声，但没有降低 production authority 门禁。

回归覆盖：原 gate=false 而 recovery=true 时原 false/reasons 不变；第二次写 gate 被拒绝；primary failure 不被 recovery 覆盖；一次瞬态失败加两个一致样本可以通过；真实 identity 变化、pointer 变化和 broadcast manifest 变化继续失败；PowerShell 三个脚本解析无错误。旧 SHA `67cc70ec93908db982d8f16f81c49f1ae3b9c90a` 已撤销 VM 验收资格，新的唯一可部署 SHA 只能在本修复提交的 push/PR required jobs 和 exact-commit artifact 均通过后确定。

## 2026-08-07 legacy production health 与 stale process record 修复

真实 VM 现场表明，旧 SHA `dd099faa6bcf7f1f120e8ce5166d6319812488ba` 的候选成功启动，commit、listener PID、只读合同和 16 项 smoke 全部通过；8080 listener PID 集合、production current 和广播 manifest 前后均未变化，手工访问 8080 health 也正常。自动门禁却把 pre/post health 都记为 `reachable=false`，随后清理又因 CIM 对象没有可读取的 `ExecutablePath` 而失败。候选最终已经退出，18080 无 listener、candidate current 恢复为 no-current；遗留记录 PID 5500 在 `Get-Process`、CIM 和端口三处均无对应对象，属于 stale record，不是未知运行进程。

根因有两层。第一，StrictMode 下直接访问 legacy health 不存在的 `viewer_mode` 会抛异常，外层 catch 把“HTTP 已返回但 schema 较旧”误写成“不可达”。第二，进程快照把 `Get-Process.Path`、CIM `ExecutablePath` 和 `CommandLine` 当作无条件属性；单个来源缺字段或权限不足会阻断所有观测。旧 stale 分支还在只看到 PID 不存在时直接删除活动记录，没有同时证明端口释放，也没有保存原 identity。

修复将生产 health 分为 HTTP 可达性、状态码、payload 解析、实际存在/缺失的身份字段和身份值。比较逐字段核对双方实际能力：同一 legacy 字段前后都缺失不构成变化，字段出现/消失、值改变、真实断连、非成功状态、payload 不可解析、listener/current/manifest 变化仍 fail-closed。候选进程改为同时保存 Get-Process、CIM、listener 和 candidate health 四类观测；可选路径或命令行缺失只记为 unavailable，停止权限仍要求启动时间加“可取得的 executable/command”以及 command/listener/health 中至少一项运行权威，任一冲突或证据不足都拒绝杀进程。

stale record 现在只有在记录合同完整、Get-Process 与 CIM 都确定无 PID、端口查询成功且无 listener、candidate health 不可达时才自动收口。流程先把原 record、SHA256、完整身份、现场观测、原因和时间写入 `runtime/stale_process_records/`，确认归档存在后才移除活动记录；PID/端口存在、查询权限未知、health 可达或身份冲突均保留记录并停止。该合同覆盖 VM 当前 PID 5500 状态，无需用户手工删除记录或杀 PID。

失败 evidence 升级为 v4：主失败、cleanup 和 pointer recovery 分栏；无论门禁在哪一步失败，均在重新采集 post state 后保存 scheduled-task comparison、production comparison、逐项 reasons 和 release integrity，再重新抛出原始主失败，cleanup 的次级异常不再覆盖根因。回归测试覆盖 legacy health、部分字段、真实断连、身份变化、CIM 缺字段/拒绝访问、匹配进程真实回收、误杀拒绝、stale 归档、端口/health 冲突以及失败 evidence 字段顺序。旧 SHA 已撤销资格；最终可部署 SHA 以本轮最后绿色 push artifact 为准。

## 2026-08-06 VM immutable release bytecode 污染阻断与修复

第三次 VM 人工执行在 immutable release build 阶段被严格文件集合校验阻断，18080 尚未启动。现场报告的四个额外文件并非随机残留：在不设置 `PYTHONDONTWRITEBYTECODE` 的隔离复现实验中，从 release 目录执行旧命令 `python -m tools.release.readonly_smoke --help` 会稳定生成完全相同的四个文件：`tools/__pycache__/runtime_paths`、`tools/release/__pycache__/__init__`、`manager` 和 `readonly_smoke` 的 `.pyc`。随后 `verify_release()` 正确返回 `release file set mismatch`。因此根因不是 verifier 过严，而是旧部署仅给 listener 加了 `-B`；build/preflight/activate/rollback 和 smoke 仍以普通模块方式导入项目代码。前一次执行可在 smoke 或后续失败路径污染保留的 SHA，下一次同 SHA 重试在 build 复用检查时才暴露污染。

修复没有删除 `.pyc` 或放宽 exact-file verification。VM 脚本会清除子进程继承的 `PYTHONPATH/PYTHONHOME`，设置禁止用户 site 与 bytecode 的环境，并让所有项目模块通过白名单 bootstrap 以 `-I -B -S` 运行。build、preflight、activate、launch 和 smoke 后逐次执行精确 manifest 复核；CI lifecycle 在 stop 后再复核一次。代表性 smoke 也改为真实的隔离子进程调用，不再由已经导入仓库代码的 evidence 父进程代跑。

第一轮提交 `a612fe83065d51f9e87e807b25e6fccee8f7880e` 在本地完整生命周期通过，但真实 GitHub Windows runner 的 isolated smoke 暴露了第二个边界：`-I` 会忽略 `PYTHONUTF8/PYTHONIOENCODING`，runner 的标准输出仍为 `cp1252`，因此 smoke 已经写好的 UTF-8 JSON 在同步输出包含中文摘要时触发 `UnicodeEncodeError`。修复提交 `1580aa6b87ff5c3b89ffc434a65da5ab969281f0` 让白名单 bootstrap 在导入任何项目模块前显式把 stdout/stderr 设为 UTF-8 strict，并新增 `cp1252 + 中文 JSON` 回归测试；没有改成 ASCII 转义、丢弃字符或放宽 smoke。该提交的本地测试为 556 passed、21 skipped、55 subtests，push run `31113566860` 与 PR run `31113572490` 均为 success；本地 exact-commit evidence 的 build、preflight、activate、launch、smoke、stop 六个阶段保持同一 manifest、572 个文件且零 `.pyc`。后续文档提交仍须用自己的 push artifact 重新绑定最终 VM SHA。

同 SHA 重试现在分三类：严格有效目录原样复用；失效且既非 `current`、也未被当前执行开始时的候选进程记录引用的目录，整体原子移动到 `runtime/release_quarantine/`，保存原目录、失败原因、文件集合指纹和 bytecode 路径后重新构建；`current`、运行引用、引用记录不可读或符号链接目录一律停止，不自动覆盖、修补、删除或隔离。每次部署生成唯一 attempt evidence，原 latest evidence 进入 `runtime/evidence_history/`，失败重试不覆盖前次证据。

回归测试新增：preflight 失败后同 SHA 复用；任意 `.pyc` 与普通额外文件触发整目录隔离重建；current/运行记录引用的失效 release 禁止自动处理；调用环境存在恶意 `PYTHONPATH` 时仍从 release 导入白名单模块且不写 bytecode；遗留 Windows 输出编码不能破坏中文 evidence；完整生命周期各阶段的 commit、manifest hash、文件数与内容继续一致。旧 SHA `97d01708737368a9f963f0e9d321c7c596f53efc` 已撤销 VM 验收资格。最终可部署 SHA 仍须以后续最终修订的 push/PR Actions 和 exact-commit artifact 为准，本节不宣称 VM 已验收。

## 2026-08-06 VM content preflight 阻断与修复

第二次 VM 人工执行在候选启动前被 preflight 正确阻断，18080 没有 listener。实测 `C:\industry_demo\docs\industries` 与 `C:\industry_demo\papers` 存在，`docs\themes` 不存在；四库对象、列和只读探针全部通过，`research.db.theme` 有 5 条正常记录。代码审计确认主题详情页先读取数据库中的主题、行业和公司关系，主题 Markdown 由容错加载器作为增强内容读取；文件不存在时页面仍展示数据库内容，并明确显示“尚无主题分析 md”。本地旧目录中的 `docs/themes` 也是空目录，Git 不保存空目录，因此不存在尚未识别的主题文件权威。

根因是 deployment policy 和 preflight 把三个外置路径硬编码为同一强制等级，把数据库承载、Markdown 可选增强的主题页误定义成无条件依赖。修复把外置路径改成 manifest 驱动的逐路径合同：`docs/industries` 和 `papers` 为 required，缺失或类型错误仍 fail-closed；`docs/themes` 为 optional，缺失会明确写入 preflight/evidence，但不会伪装存在或阻止数据库主题页。原 `--allow-missing-content` 绕过参数已经删除，防止 required 路径被弱化。

合成 fixture 不再创建空 `docs/themes`，并新增数据库主题和关系；schema 合同新增主题必需列、关系表和只读探针；代表性 smoke 增加数据库-only 主题页检查，同时核对页面明确报告 Markdown 缺失。smoke 因而由 15 项增至 16 项。旧提交 `f6926410475cf5c646641f6d7056736abae1453d` 使用错误的强制内容合同，已经撤销 VM 验收资格。新的可部署 SHA 必须来自本次修复后的绿色 push artifact，并与绿色 PR artifact 的 `pull_request_head_sha` 一致。

在按 lockfile 新建的本地 Windows venv 中运行 exact-commit lifecycle 时，16 项路由 smoke 全部通过，但身份门禁发现 `Popen/Start-Process` 记录的是 venv redirector，实际 listener 由其 Python 子进程持有。这说明旧实现对 GitHub setup-python 解释器有效，却没有覆盖 VM 真实的 venv 启动形态。修复后仍用 venv 完成 lockfile 安装和逐包核验，但 listener 改由 verifier 记录的 base Python 以 `-S` 直接启动，只显式加入已验证 venv 的 site-packages；因此记录 PID、health PID 和 Windows listener PID 是同一进程，也不会泄漏 base/quant 的其他第三方包。该修复由 exact-commit lifecycle 实测，而不是放宽身份断言。

提交 `f01208a40b7fe597d9969bfa226eb4dd4cb1728c` 的本地严格环境 evidence 已验证：release 572 个文件、24,561,826 bytes、manifest SHA256 `03b0b3e324bbc5920cd8c91f99d580a0f8b90cd90c872b26d422c2346c5e77c8`；preflight 的 `required_missing=[]`、`optional_missing=[docs/themes]`、`invalid_paths=[]`；16 项 smoke 全部通过；process/listener PID 同为 17984；停止后端口释放；code-only rollback 已执行且四库哈希不变。该提交是实现证据，不替代后续最终分支头的 push/PR Actions artifact，也不冒充 VM 验收。

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
- 所有导入项目代码的进程从解释器参数开始使用 `-I -B -S`，并隔离 `PYTHONPATH/PYTHONHOME`；preflight 报告以 SHA256、commit、manifest、schema contract 和 data/content/state root 绑定给进程，release 在 build 到 stop 的各阶段继续接受精确文件校验。
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
