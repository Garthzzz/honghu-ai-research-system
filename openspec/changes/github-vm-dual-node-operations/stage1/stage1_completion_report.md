# 阶段 1 实施与验收报告

报告时间：2026-08-03 22:13:21 +08:00
状态：实现工作完成；等待 GitHub UI 人工 gate 与阶段 1 HALT 审查，不进入阶段 2。

## 1. 批准、工作区与提交

- 阶段 0 批准已记录于 `tasks.md`：批准人是用户，时间为 2026-08-03 21:12:55 +08:00，范围仅限安全 Git bootstrap、边界、测试、依赖锁和 CI。
- 活动目录 `D:\quant\industry_demo` 只完成首个安全历史，没有切换 branch、reset、clean、迁移或环境变更。后续修复均在 sibling clone `D:\quant\industry_demo_stage1` 完成；最终复验使用第二个 fresh clone `D:\quant\industry_demo_stage1_verify_20260803`。
- remote：`https://github.com/Garthzzz/honghu-ai-research-system`；只推送 `bootstrap/stage1-safe-history`。
- commit：`2787c54`（安全初始历史）、`1f39dbf`（测试、lockfile 与 CI）、`ecb7640`（clean-clone artifact 分层修正）。报告与任务状态将在后续审计 commit 中固化。
- 未创建或推送 main，未修改远端历史，未使用内容仓库，未配置 VM credential。

## 2. Git 边界与首次 inventory

- 当前 tracked：751 个文件、26,949,970 bytes；最大对象 `tools/viewer/static/vendor/plotly.min.js` 为 4,847,499 bytes，属于 Viewer 明确依赖的冻结 vendor 资源，低于 10 MiB block 门槛。
- 主要类型：Python 484、Markdown 91、HTML 65、字体 60、JSON 13、JavaScript 8、CSS 7、YAML/YML 5、SQL 3、依赖 input 2、TXT 2。
- 首次 bootstrap inventory 是 742 个文件、26,848,959 bytes；分类为应用源代码 545、测试 93、正式治理/spec 93、部署/配置 11。完整逐文件清单、大小、SHA256 和扫描详情保存在本地 ignored `cache/git_bootstrap/`，可供人工复核但不上传排除资产路径。
- tracked allowlist 的机器权威是 `config/git_tracked_policy.json`；`.gitignore` 只提供误操作防线，不替代 allowlist、staged gate 或未来 deployment manifest。
- tracked：应用代码、测试、CI、正式规则、活动 OpenSpec、选定活动 skills、正式 SOP、配置模板和必要静态资源。
- excluded：四套 SQLite 及 WAL/SHM/journal、PostgreSQL dump、backup、broadcast、runtime/log/cache、secrets/Cookie/browser state、papers/evidence、Opportunity Lens intake/outputs、用户研究内容、个人上下文和 history/archive。
- 初次全项目审计有 66 个不确定文件保持 `pending_review`，主要是非活动 skills、历史 OpenSpec、旧 prompt/TODO 和诊断说明；均未跟踪。隔离 clone 中新增的虚拟环境被明确分类为 runtime，不再污染 pending-review 统计。

## 3. 安全扫描和 Git 属性

- 首次及后续 staged/tracked allowlist gate：通过。
- secret/path/credential 扫描：通过；没有输出或提交 secret 值。minified vendor 的低置信赋值误报仅对显式 vendor 例外，高置信 key/token/private-key 规则仍执行。
- DB/WAL/SHM/backup/broadcast：tracked 中为 0。
- Windows 保留名、不安全路径、超长相对路径、symlink/junction/reparse 和路径逃逸：通过。
- 大文件：无普通对象超过 10 MiB；未启用 Git LFS。
- `.gitattributes` 固定源文件换行，Windows 脚本使用 CRLF，二进制字体/图片不做文本转换；lockfile 与 requirements input 固定 LF。
- staged gate 曾按设计阻断两次：一是 `.git/` 前缀错误误伤 `.github/`，二是正式迁入的旧 reviewer 含 `BEGIN IMMEDIATE`。两者均增加回归测试并显式收口，没有绕过门禁。

## 4. SQLite dependency baseline 与 writer 定义

- legacy baseline：589 个静态规则命中、163 个 Python 文件；覆盖 `sqlite3.connect()`、`ATTACH`、`PRAGMA`、`BEGIN IMMEDIATE`、SQLite conflict DML 和硬编码 `data/*.db`。
- writer 按 domain mutation path、write endpoint、writer operation 或 transaction contract 审计，不等同于进程、Viewer 或整个 scheduler。
- `silicon_review_recorder.py` 是从 excluded cache 迁入正式源码的既有 review 事务，不是新增业务能力；已登记 domain、rule、reason、owner 和 future cutover-unit candidate。最终 ratchet 为 pass。
- 阶段 1 没有创建 cutover registry，也没有重构生产数据访问层。

## 5. 测试修复和分层

- 修复 `scheduler.py`、`seed_3a.py` import-time 重包 stdout/stderr 导致的 pytest capture 失效。
- 把受测试的硅片 reviewer 从 cache 移入 `tools/opportunity_lens/silicon_review_recorder.py`，测试不再导入 ignored runtime 文件。
- Run16 evidence catalog 改为 build-time fail-closed 加载，clean clone 可收集模块，但真实构建缺少 governed artifact 仍明确失败。
- 硅片 V2 builder 增加每个问题轴独立 `report`/`web` 第一轮任务、确定性 `source_channel` 和退役公开标题归一；新增不依赖研究产物的回归测试。
- 修复 `lithium_battery_research_content.py` 两处 Python 3.10 不允许的 f-string 反斜杠表达式，不改变公式和研究值。
- 修复前：pytest 在 import-time capture 处无法形成稳定根基线；解除该问题后，本地混合 artifact 全量曾为 626 passed、21 skipped、42 failed、41 errors，失败集中于缺失/不完整的被排除研究产物。
- 最终 clean clone：全量 compile 通过；clean core 为 526 passed、21 skipped、53 subtests passed。
- `config/ci_test_tiers.json` 显式列出 22 个 governed-artifact integration 模块。这些测试需要被禁止上传的研究 pack、evidence ledger、Excel、冻结模型、正式 intake 或 live 只读快照，不计作 CI coverage，也没有被声明为通过。
- 活动测试：clean core；兼容/受控集成：manifest 中的 22 个模块；正式退役：本阶段没有以删除或永久 xfail 方式退役测试。
- 没有运行会访问供应商 API、公司内网或 live DB 的测试。

## 6. Python 环境与 CI

- 支持基线：Python 3.10；fresh clone 实测 Python 3.10.20。
- `requirements.in` / `requirements-dev.in` 为直接依赖输入；`requirements.lock.txt` 是 Windows/Python 3.10 的 74 包 hash-pinned 权威；`requirements.txt` 仅为兼容入口。
- 使用隔离 `.venv-stage1` 与 fresh-clone `.venv-verify` 安装；未升级或修改活动 base/quant 环境，也未假定缺失的 `industry` 与它们等价。
- clean environment 同步 74 个锁定包成功；随后 gate、ratchet、OpenSpec、compile 和 core tests 全部通过。
- workflow：`.github/workflows/stage1-ci.yml`。
- required-check 候选：`boundary-and-contracts`、`python-clean-environment`。
- CI 只有 `contents: read`，checkout 不持久化 credential，不访问 live DB、内网、供应商 API、papers、用户内容或 VM，不部署任何系统。
- 私有 GitHub Actions 的实际远端运行状态未通过本机 CLI读取；不得用 GCM 导出 token 来绕过。需要用户在 GitHub UI 核验 workflow run。

## 7. main、仓库治理和人工事项

- 当前 remote 只有 `bootstrap/stage1-safe-history`，main 尚未创建/保护。
- 管理员需在 GitHub UI 审核 branch 与 Actions 后创建/确认 main，启用 branch protection/ruleset，并要求两个 check；禁止 force push 和直接绕过应由公司治理决定。
- 个人账号 private repository 目前只是 bootstrap/development source，不是 production authority。公司资产控制或批准例外、第二管理员/交接、2FA、账号恢复、最小权限和公司控制的 VM deploy credential 仍是生产 gate。
- 内容仓库保持 `RESERVED-UNUSED`，本阶段未连接或写入。

## 8. 正式规范、恢复文档与未执行事项

- 七份 capability specs 均进入 Git；`stage1/capability_spec_identities.json` 的 SHA256 全部复核匹配。本阶段只包含 bootstrap 前已经批准的 writer-operation 粒度澄清，没有静默修改架构合同。
- `codex_context/BACKUP_REGISTRY.md` 作为恢复事实/目标合同进入 Git，但未刷新、prune、复制或验证 PostgreSQL restore。
- `docs/VIEWER_内网部署.md` 与 `docs/AUTOMATION_SETUP.md` 保持第三轮已审查的当前事实/目标状态区分；本阶段未改环境、任务或 Viewer。
- 财务建模文档只保留已批准的顶部物理存储状态说明；未修改模型、公式、历史数据或 `financial.db`。
- DeepSeek 实际调用 0 轮；确定性 gate 与 fresh clone 已产生直接证据，没有必要外发更多项目摘要。
- OpenSpec strict 在 clean clone 通过。
- 明确未执行：PostgreSQL 安装/启动/schema、live SQLite 数据或 schema 写入、migration、任务变更、VM deploy、deploy key、production release、papers/evidence/数据库/backup/用户内容上传、backup refresh/prune、内容仓库操作和阶段 2。

## 9. 退出判断

阶段 1 的代码、边界、测试、lockfile、CI 和远端 bootstrap branch 已完成并可复验；但 `main` 的远端 Actions 结果和 branch protection/ruleset 需要管理员在 GitHub UI 完成，因此尚不能自行勾选阶段 1 HALT 或宣告 production authority。人工审查建议顺序：本报告 → bootstrap inventory → Git diff/commits → workflow 与 Actions → GitHub main/ruleset → capability hashes → `tasks.md` 的阶段 1 HALT。
