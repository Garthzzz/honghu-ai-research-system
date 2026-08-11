# 阶段 3 完成报告（人工批准退出）

## 状态与授权边界

阶段 3 的代码审计、迁移边界、隔离 PostgreSQL dev/test 试点和 live 增量对账已经完成。用户已于 2026-08-11 14:25:45 +08:00 批准 `target_rpo_rto_proposal.v2` 并批准阶段 3 退出。

当前四套 SQLite 仍是唯一生产事实源。未安装或启用 production PostgreSQL，未修改 live SQLite，未切换 production writer、Viewer、runner 或计划任务，也未进入阶段 4。

## 本轮 live 增量对账

阶段 3 开始后，活动目录又完成了 Opportunity Lens run19/run20、封装基板 B 轨重做和若干通用 Viewer/cache/cleanup 修复。为避免迁移证据停留在旧快照，本轮先冻结设计和执行计划，再完成三类处理：

1. 通用代码通过手工三方合并进入 Git：行业父级继承与关系投票、估值正文展示、required-cache screenshot 引用排除、cleanup 歧义 basename 处理，以及相应测试。
2. run 输出、研究正文、papers、数据库和一次性研究 producer 继续保持 Git 外；没有因迁移对账把用户研究内容上传到 public repository。
3. Git 外 producer 通过 live-only addendum 纳入迁移审计，并与可部署 inventory 合成为 aggregate manifest。任何后续 production sequencing 必须同时提供这两层清单，不能只看公开仓库。

## SQLite 依赖、ownership 与事务边界

可部署清单覆盖 281 个依赖文件，其中 234 个生产文件、181 个写文件、958 条 operation-level writer 和 388 个事务边界；`ATTACH` 文件为 5 个。

Git 外 live-only addendum 覆盖 6 个研究 producer，其中 3 个写文件、13 条 writer operation、4 个事务边界和 1 个 `ATTACH` 文件。合并后的完整审计视图为：

- 287 个依赖文件；
- 240 个生产文件；
- 184 个写文件；
- 971 条 writer operation；
- 392 个事务边界；
- 6 个 `ATTACH` 文件；
- writer、事务边界重复和未知 cutover owner 均为 0。

134 个当前业务表继续由 registry 唯一归属；共享身份、研究发布、财务桥接、Opportunity Lens、动态数据、情绪和用户内容之间的 dependency 不被误写为重复 ownership。`writer` 仍指可审计 mutation path/operation 或 transaction contract，不等于整个 Python 进程。

主要 Git 外证据身份：

- deployable inventory 文件 SHA256：`751598638b54d7ddb7eae9fa3d42a59fb51787bedd1241912b5109d635559686`；内容身份：`3c08fcf087678f04a4d6fd028733ca0307c0cb9a2cf1b12484637026a69f3f2d`；
- live-only addendum 文件 SHA256：`e2792166c653deaa286296edadae2a955d08bec0b4aa77d4a62555e4afbd10b4`；内容身份：`0a8f4ee59ba1aa97ed10c54e797dfd9aa8dba4fa3b650e4067d9c7aec2576999`；
- aggregate manifest 文件 SHA256：`17abcc2e945ebee4d1328398544aba389a5d12cc8d49dbcab3680d7c1ab3f1a3`；内容身份：`4434170746e77ac0899ace93d45c3c3d8b6003ae846c00b9224506f9c3dc9b34`；
- cutover registry 文件 SHA256：`cda06890d9a4be4d290587be00eb63be61d657c4aede1eeaf02b5bec3ccb0274`；
- live schema audit 文件 SHA256：`2a60e51a465594360f99966555a511b2440a496d74373c8a84d320816db85400`。

上述身份会在提交前重新生成；如最终值变化，以最终 Git 外 identity 记录和提交报告为准。

## PostgreSQL dev/test 试点

隔离 PostgreSQL 17 dev/test 监听 `127.0.0.1:55432`，使用测试角色和测试库，不注册服务、不连接 production。复验完成了：

- expand migration 连续应用两次；
- create、uncertain-response 幂等重试、update、stale revision 冲突和 soft delete；
- revision/audit 链及 payload-level 幂等冲突；
- `pg_dump` 后恢复到旁路测试库；
- 四套 live SQLite 演练前后哈希不变；
- 测试数据库清理、进程停止且 55432 listener 消失。

Git 外试点证据 SHA256 为 `ac9700d46af1b16af983d678c3ecf0ffbdd89409b2e51e48a7868dce78e5cf4d`；migration SHA256 为 `333d8d5bd266b6bb70afd2444b5deca44f8a908f0e9cb00736031ebecf121f47`，旁路 dump SHA256 为 `8cbf288560446793f2208014d217d75f0b0d34fb28605051f4b000a9290d5b50`。

## 测试与验收口径

标准 clean-environment 测试入口当前结果为 591 passed、21 skipped、55 subtests；收集到 612 个测试。compile、SQLite dependency ratchet、代表性只读 Viewer 路由、Stage 2 readonly/release 回归和 OpenSpec strict 均通过。

2026-08-11 的首次治理提交 CI 暴露出一个固定日期测试缺陷：财务刷新 fixture 使用 2026-07-15/07-10，但校验引用真实北京时间，跨日后旧值超过 31 天门槛而使测试失去原意。修复只在测试类内冻结时钟到 fixture 日期；production 的 apply-time freshness、31 天 fail-closed 门禁和测试断言均未放宽。修复后该模块 22 passed、3 subtests，完整 core 重新得到上述绿色结果。

直接执行未分层的根目录 `pytest -q` 会进入 22 个由既有 manifest 治理、依赖 Git 外研究 artifact/Excel/live 数据的模块，因此产生 41 errors 和 42 failures；其余结果为 695 passed、21 skipped、57 subtests。这些失败没有通过删除、永久 xfail、放宽门禁或修改 live 数据掩盖。CI 与 clean clone 的权威入口继续是 `tools/ci/run_test_tier.py`，同时保留上述完整事实供人工判断。

## 备份与恢复事实

本轮先建立并验证项目外安全副本，完成对账后原子刷新 `backup/latest`，随后仅使用受限工具 dry-run/apply 清理本次临时外部副本。

当前 `backup/latest`：

- 创建时间：2026-08-10 19:57:06 +08:00；
- 版本：`阶段3-live增量对账-20260810`；
- archive：16,517,807,421 bytes；SHA256 `1c01e3653ba277a5c91fca5aa5ccd3a0b2f11b2595bc9649900769d1a5980fc7`；
- 32,150 个文件；源文件合计 19,163,559,754 bytes；
- ZIP CRC、成员清单和 embedded manifest 均通过；
- 四套 SQLite backup API 快照均 `integrity_check=ok`、foreign key issue=0。

该备份是当前 SQLite 时代恢复事实，不代表 PostgreSQL restore 已验证，也不批准 production 数据迁移。

## 设计复核

Codex 先独立形成 design/plan，再进行了两轮脱敏 DeepSeek V4 Flash 复核。两轮均没有形成可复现的信息增量：外部 reviewer 把 134 个业务表误写成 134 个 SQLite 文件，并建议把 live DB/研究内容纳入 Git，且虚构 RPO/RTO 已批准。Codex依据代码、inventory、公开边界和阶段授权拒绝这些意见；因连续两轮无有效增量，没有进行第三轮。

Codex在独立复核中补强了：外部安全副本与 `backup/latest` 的不同职责、峰值磁盘门禁、Git 外 aggregate manifest 的强制性、研究 producer 退役需人工调整边界，以及 staged tree 到 commit/checks 的身份绑定。

最终两项 Gate 又完成两轮脱敏 reviewer 复核。DeepSeek 两次都把输入中已明确存在的 authority registry、fencing、target/measured 分层和 aggregate manifest 反写成“缺失”，没有提供可复现的新问题；Codex据确定性合同与扫描结果拒绝，未扩大范围或进入 Stage 4。完整记录追加在 `debate_summary.md`。

## 人工批准与授权边界

- 批准人：用户；批准时间：2026-08-11 14:25:45 +08:00；
- 批准内容：`target_rpo_rto_proposal.v2`、两层 inventory/aggregate manifest 合同、阶段 3 退出和 PR #5 合并；批准状态写回后的 proposal 文件 SHA256 为 `32faaa7004842a97c8c66d6b18233c1a829c7c762f53ccfb6760c4115c25b73a`；
- 最终 evidence identity SHA256：`2b58252a84161996e3b9c81cf2e1cfe5f28bd30865be85d6d15acac14b5511c6`；final drift identity SHA256：`0f6c673c4cb5d6177681fafd25e5704d9a1985172c40c07efda7440d22cfc72c`；
- PR #5 验收 head：`736d7d3e4c535dff9dc465256dedd1deb2db7716`；merge commit：`c514a47b47aa2d44eb8bb57cff6d444f5080f217`；merge 后 main run `31464637909` 的两个 required jobs 均成功；
- 本次批准不授权 production PostgreSQL cutover、live SQLite migration、writer/backend、计划任务、production Viewer 或 runner 切换。任何阶段 4 操作仍需用户另行授权。

## 最终两项人工 Gate 收口

`target RPO/RTO` proposal 已增加独立的 migration/cutover authority-control 类。已确认的权威切换状态要求零丢失，目标在一小时内恢复并独立验证；该时限不构成不安全恢复写服务的理由，验证未完成时 production writes 必须继续保持栅栏。其余五类目标维持原等级；dynamic/task 类明确排除 backend routing、S0—S4 和 cutover authority，避免较宽松目标覆盖权威状态。

以 Git 外 `stage3_live_delta_identity.json` 为 cutoff 的最终只读 drift check 未发现四套 SQLite schema、deployable source/writer path、Git 外 producer/writer path、ownership 或事务边界变化。仅 `research.db` 与 `sentiment.db` 的普通业务表出现行数增长，不属于 migration-boundary drift。最终 drift evidence 继续保存在 Git 外，防止把 live 数据或内部路径带入 public repository。

## 工程提交与远端初验

提交前 staged tree `8fbdcba90e2abf39eae2ad9965c15b604f36e3ea` 与工程提交 `e18f8ee323b18a10feef38a17f7372603d6ec08b` 的 commit tree 完全一致。该提交已推送到 `phase3/postgresql-devtest-pilot`，PR #5 保持 open、clean、未合并。

- push run `31388506232`：两个 required jobs 均成功，artifact 名称绑定工程提交 SHA；
- pull_request run `31388509100`：两个 required jobs 均成功，PR head 为工程提交 SHA，workflow/artifact 使用 GitHub 临时 merge SHA `1c353b587feed53a25014f4c59b5c81f5f102f76`；该临时 SHA 不是部署或迁移身份。

最终治理提交与其远端 checks 继续通过 Git 外 `tree → commit → checks` identity 记录，避免在 tracked 文档内制造无法闭合的自引用哈希。
