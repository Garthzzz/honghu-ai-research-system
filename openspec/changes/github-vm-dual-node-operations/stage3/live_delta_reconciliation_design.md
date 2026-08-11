# 阶段 3：live 增量对账与迁移证据重绑定设计

## 1. 目的与边界

阶段 3 的工程试点完成后，活动目录又完成了 Opportunity Lens run19/run20 与“封装基板”B 轨重做。它们没有改变四库 schema，但增加了研究内容、一次性研究生产脚本、若干 SQLite 写路径，以及 Viewer、必要 cache 和清理审计的通用代码变化。因此，原阶段 3 inventory、cutover registry 和完成报告不能继续声称覆盖当前 live 状态。

本次工作只做阶段 3 证据收口：

- 保持 `D:\quant\industry_demo` 为当前生产事实与运行目录；
- 在 `D:\quant\industry_demo_stage1` 中逐功能合并可版本化的通用代码；
- 重建 deployable source inventory，并为不允许进入公开 Git 的 live-only 研究生产代码建立 Git 外补充审计；
- 重新验证 ownership、SQLite ratchet、PostgreSQL dev/test 试点和 live 四库不变；
- 更新阶段 3 报告，但不批准 target RPO/RTO，不勾选阶段 3 HALT，不进入阶段 4。

明确禁止修改 live SQLite、8080、计划任务、生产 writer、VM production 和 production PostgreSQL。

## 2. 审计事实

截至 2026-08-10 的只读审计得到：

- 阶段 3 分支为 `phase3/postgresql-devtest-pilot`，审计起点为 `6c69479752c41b9a7a423cf11c41826a26af4163`；PR #5 仍 open、clean、未合并，既有 required checks 为绿色。
- 四套 SQLite schema 未变化，现有 134 张受审业务表仍在；多张表的行数随新研究正常增加。
- live 新增或修改了 21 个符合 tracked path 形状的文件，但其中包含研究专属构建器、研究正文生成器和一次性写库脚本，不能因位于 `tools/` 就机械进入公开 Git。
- `tools/viewer/app.py` 的 live 版本含新的行业继承/关系投票与估值正文展示，但缺少阶段 2 已验证的 runtime layout、外置 content、只读候选和 health 身份代码，证明整文件覆盖不安全。
- 原 inventory 为 280 个依赖文件、956 条 writer operation、387 个事务边界。只读初扫显示 live 新增至少 13 条研究专属 SQLite writer operation；旧结果已经不是当前完整证据。
- `backup/latest` 创建于 2026-08-10 05:25:58，覆盖 run19/run20 和较早的封装基板状态，但不覆盖当天 13:40 之后的 Viewer、动态配置与必要 cache 修订。

## 3. 文件分类与同步合同

### 3.1 纳入应用 Git 的变化

只纳入具有持续应用价值、可由 clean clone 审核且不携带研究原文/用户输入的变化：

- Viewer 的行业分组推导与行业估值正文展示；
- 对应模板和确定性测试；
- `research_sectors` / `ai_chain_directions` 的继承与关系投票说明；
- required-cache 扫描对 screenshot 路径的精确排除；
- cleanup reference map 对通用 `manifest.json`、`brief.json` 等歧义 basename 的修正；
- 与上述通用行为直接对应的测试。

这些修改必须手工移植到阶段 3 分支，保留 Stage 2 的 runtime path、外置 content、只读候选、immutable release、health 与 release identity 合同。禁止用 live 文件整份覆盖。

### 3.2 保持 Git 外的研究资产

以下内容继续属于研究内容或运行证据边界，不提交公开应用仓库：

- `docs/industries/**`、`papers/**`、`opportunity_lens/intake_requests/**`、`opportunity_lens/research_outputs/**`；
- run19/run20 的 pack builder、source downloader 及其专属底稿/输出；
- 封装基板正文生成器、一次性准备/应用/终审脚本和生成图表；
- live 数据库、cache、浏览器审计结果和原始证据。

保持 Git 外不等于忽略其迁移影响。它们必须进入本地、Git 外的 live dependency addendum，至少记录文件路径、安全 SHA256、读写库、writer operation、事务边界、候选 cutover unit 和当前 `sqlite_transition/S0` 状态。公开报告只记录 addendum 的 schema、计数和整体 SHA256，不提交研究正文、URL、数据库行或原始文件。

### 3.3 冲突合并规则

每个修改文件分别比较：阶段 3 当前版本、live 版本及 Stage 2/3 已验证合同。合并顺序为：

1. 保留迁移分支的安全与 release 能力；
2. 移植 live 的独立通用功能；
3. 合并相应测试；
4. 对冲突行为增加回归测试；
5. 不以“live 更新时间更晚”为覆盖依据。

## 4. 备份与数据不变合同

本次不写库，但会同步和测试大量应用代码。执行前在 `D:\quant` 建立名称含 `industry_demo` 的临时外部安全副本，四套 SQLite 必须用 SQLite backup API 快照并通过 `integrity_check` / `foreign_key_check`。不得复制 `tools/dynamic/secrets`，不得只复制 `.db` 主文件。

启动归档前先按现有归档体积、旧 `backup/latest`、新 staging 和安全余量校验磁盘空间；空间不足则停止，不能用缩减 papers、cache 或数据库范围来伪装完整副本。外部副本使用现有 `tools.maintenance.create_external_safety_backup`，项目内最终版本使用 `tools.maintenance.refresh_project_backup`，两者职责不得互换。

执行前后分别记录四库文件/一致快照身份。代码测试、inventory 和 PostgreSQL dev/test 试点不得改变 live 四库。验收通过后使用现有原子工具刷新唯一 `backup/latest`，核验 ZIP SHA、CRC、成员清单和四库快照；再按注册表先 dry-run、后受限清理本次临时外部副本。任何备份或核验失败都停止提交。

## 5. inventory 与 ownership 重绑定

重绑定分成两层：

1. **deployable inventory**：扫描阶段 3 分支中实际可部署、可版本化的代码，生成 tracked `sqlite_dependency_inventory.json` 和 `cutover_unit_registry.json`。
2. **live-only addendum**：扫描被 Git 边界排除、但当前活动目录仍可能执行的研究专属 Python，生成 Git 外 evidence。它不能创建第二套 authority，只补足“当前 live 还有哪些写路径”的事实。

两层清单不是两个互相竞争的事实源。Stage 3 的完整迁移审计身份是一个 Git 外 aggregate manifest：它固定 deployable inventory SHA、live-only addendum SHA、扫描根、截止时间、包含/排除规则和合并后的表/writer/transaction 计数。只要 live-only 路径仍存在，任何 production sequencing 都必须同时提供这三个身份；只拿公开 Git inventory 不足以批准 cutover。研究专属路径正式退役后，才可通过单独人工审核的边界变更把它从 addendum 移除。

研究专属脚本留在 Git 外会降低公开仓库的单独可复现性，但这是用户内容/研究资产边界的有意选择，不通过上传敏感研究实现“可复现”。本次外部安全副本和更新后的 `backup/latest` 保存其 exact file、哈希与同时点数据库快照；未来若需要长期跨节点复现，应由经批准的内部 artifact authority 承担，而不是复用 public 应用 Git。

最终汇总校验必须回答：

- 134 张 live 表是否仍各有唯一 owner；
- deployable 与 live-only operation 是否均有一个且仅一个候选 owner；
- 是否新增 `ATTACH`、跨库事务、硬编码数据库路径或 SQLite 专属 DML；
- 研究专属 writer 是持续生产路径、可复现工具还是已完成的一次性路径；
- 一次性路径在正式退役前仍不得从审计中消失；
- Stage 3 低风险 `user_content_notes` 试点选择是否仍成立。

`config/sqlite_dependency_baseline.json` 继续作为新增技术债 ratchet。对确有必要的新依赖，只能以精确路径、域、原因、责任边界和未来 cutover unit 记录例外，不能扩大目录豁免。

## 6. 非生产 PostgreSQL 复验

代码合并和 inventory 重建后，在隔离 PostgreSQL dev/test 环境重跑既有 analyst-note 试点：

- 只监听 loopback 非标准端口，不注册生产服务；
- 重复 migration、create/update/soft-delete、幂等 retry、stale revision、NULL revision、audit 和 side restore 继续通过；
- 试点前后 live 四库身份不变；
- 完成后删除测试 database 并停止 listener；
- 原始 evidence 保持 Git 外，仅提交工具、测试、摘要和 SHA256。

新研究没有向 `analyst_note` 写入数据，也没有改变其 schema，因此试点不自动改选；若 inventory 发现它与新增事务发生实际耦合，才停止并重新设计。

## 7. 提交前最终验收

提交前而非提交后，统一执行：

- Python compile；
- clean/core 完整测试与受治理 artifact 分层；
- OpenSpec strict；
- tracked boundary、secret/path/large-file/Windows path gate；
- SQLite dependency ratchet；
- deployable inventory 与 live-only addendum 汇总校验；
- cutover ownership overlap、unknown owner、漏表、虚构表和事务冲突检查；
- PostgreSQL dev/test 试点及 side restore；
- public repository exposure review；
- `backup/latest` 安装后核验；
- `git diff --check` 和最终 staged inventory。

所有结果绑定同一个待提交工作树身份。随后才允许 commit、push PR #5 并等待远端 required checks。远端绿色仍不等于阶段 3 人工退出批准。

由于文件不能在自身内容中预先写入最终 commit SHA，提交前证据绑定使用 staged Git tree SHA、逐文件/registry/addendum hash 和工作树 clean gate；commit 后另在 Git 外 final identity 记录 `staged_tree_sha → commit_sha → push/PR checks` 映射。若 commit tree 与已验收 staged tree 不一致，提交作废并重新验收；不得用旧 evidence 绑定新 commit。

## 8. 失败与回退

- 合并失败：只恢复隔离 Git 工作树中的未提交变更，不动 live 根目录。
- 测试失败：保留失败 evidence，修复应用分支；不得修改 live DB 迎合测试。
- inventory 冲突：停止并人工调整 ownership，脚本不得自动漂移 unit 边界。
- PostgreSQL 试点失败：销毁隔离 test database/process；SQLite authority 不变。
- 备份失败：保留旧 `backup/latest`，停止提交。
- public exposure 发现敏感内容：从 staged/index 移除并停止 push，不打印敏感值。
