# 阶段 3 工程完成报告（等待人工验收）

## 状态与授权边界

阶段 3 的代码审计、迁移边界、隔离 PostgreSQL dev/test 试点和 2026-08-10 live 增量对账已经完成；本报告不批准阶段 3 退出。`target RPO/RTO` 仍为 `pending_human_approval`，阶段 3 的人工 HALT 仍未批准。

当前四套 SQLite 仍是唯一生产事实源。未安装或启用 production PostgreSQL，未修改 live SQLite，未切换 production writer、Viewer、runner 或计划任务，也未进入阶段 4。

## 本轮 live 增量对账

阶段 3 开始后，活动目录又完成了 Opportunity Lens run19/run20、封装基板 B 轨重做和若干通用 Viewer/cache/cleanup 修复。为避免迁移证据停留在旧快照，本轮先冻结设计和执行计划，再完成三类处理：

1. 通用代码通过手工三方合并进入 Git：行业父级继承与关系投票、估值正文展示、required-cache screenshot 引用排除、cleanup 歧义 basename 处理，以及相应测试。
2. run 输出、研究正文、papers、数据库和一次性研究 producer 继续保持 Git 外；没有因迁移对账把用户研究内容上传到 public repository。
3. Git 外 producer 通过 live-only addendum 纳入迁移审计，并与可部署 inventory 合成为 aggregate manifest。任何后续 production sequencing 必须同时提供这两层清单，不能只看公开仓库。

## SQLite 依赖、ownership 与事务边界

可部署清单覆盖 280 个依赖文件，其中 234 个生产文件、180 个写文件、957 条 operation-level writer 和 387 个事务边界；`ATTACH` 文件为 5 个。

Git 外 live-only addendum 覆盖 6 个研究 producer，其中 3 个写文件、13 条 writer operation、4 个事务边界和 1 个 `ATTACH` 文件。合并后的完整审计视图为：

- 286 个依赖文件；
- 240 个生产文件；
- 183 个写文件；
- 970 条 writer operation；
- 391 个事务边界；
- 6 个 `ATTACH` 文件；
- writer、事务边界重复和未知 cutover owner 均为 0。

134 个当前业务表继续由 registry 唯一归属；共享身份、研究发布、财务桥接、Opportunity Lens、动态数据、情绪和用户内容之间的 dependency 不被误写为重复 ownership。`writer` 仍指可审计 mutation path/operation 或 transaction contract，不等于整个 Python 进程。

主要 Git 外证据身份：

- deployable inventory 文件 SHA256：`586492740bc9304c8f4108e6774f1eed520a880f246d3d3a0bff098e9724a281`；
- live-only addendum 文件 SHA256：`572147261dddd6bcefbac2eabbefe528ced425cee89e7376191b4cd4540490b2`；内容身份：`9c12e94ad04a1b4548c1728443c895f6b739cc4a7e5023c2ec433fbc19ae0ec4`；
- aggregate manifest 文件 SHA256：`a323110e0fa0826d2153213eccdb3a8e8bf2233c6f15ac2ec24a878f7d42044e`；内容身份：`43992d208be4eff8481b55541727c55e525c8f208c4324c2b1df4f97a6acb6fb`；
- cutover registry 文件 SHA256：`cb0590047f40e3b47fb4acf39e777114ba36c48e25c08c1145852c666937cfe2`；
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

## 尚待人工决定

1. 是否批准 `config/migration/target_rpo_rto_proposal.json`；
2. 是否接受两层 inventory 作为当前完整审计合同；
3. 是否批准阶段 3 退出；
4. PR #5 是否合并；
5. 即使阶段 3 退出，任何阶段 4 production cutover 仍需另行授权。

最终提交、CI 与 PR 身份将在提交前终验后补入 Git 外 identity 证据；在此之前不得把当前工作树描述为已远端验收。
