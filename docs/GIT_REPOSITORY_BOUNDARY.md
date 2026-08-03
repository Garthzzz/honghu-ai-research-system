# Git 仓库边界与阶段 1 门禁

## 1. 权威边界

应用仓库只保存可审核、可复现的源代码和正式规则。`config/git_tracked_policy.json` 是 tracked allowlist 的机器合同，`tools/maintenance/git_stage1_guard.py` 负责生成本地全项目分类、精确 allowlist、staged/tracked gate 和 SQLite 技术债 ratchet。

`.gitignore` 只是降低误操作概率，不能代替 allowlist、staged inventory 或扫描门禁。首次和后续提交必须由精确 pathspec 暂存，并对暂存区运行 gate。

## 2. 允许进入 Git

- `tools/` 的应用、Viewer、pipeline、financial、sentiment、Opportunity Lens、migration 和维护源代码；
- `tests/`、CI、依赖声明和 lockfile；
- `AGENTS.md`、活动 OpenSpec、活动 A/B/C skills、正式 context、SOP 和模板；
- 配置模板与已审查的小型冻结模型；
- Viewer 必需的静态源资产和显式允许的 vendor 文件。

`tools/` 不是机械整目录纳入：浏览器登录态、生成图表、checkpoint、备份和临时文件仍被更高优先级规则排除。`skills/`、`docs/`、`codex_context/` 与 `opportunity_lens/` 均按活动文件逐项选择。

## 3. 禁止进入 Git

- live SQLite、WAL/SHM/journal、PostgreSQL dump；
- `backup/`、`broadcast_packages/`、runtime、logs 和 cache；
- `tools/dynamic/secrets/`、Cookie、browser profile、storage state、token 和 credential；
- `papers/`、Funda 资料、Excel/PPT/PDF、未经批准的 evidence；
- Opportunity Lens intake、run outputs、研究员 workpaper 和行业正文等用户/研究内容；
- 个人 checkpoint、对话记忆、历史 archive 和一次性调试输出。

无法可靠判断的路径保持 `pending_review`，不会为完成首次提交而猜测纳入。

## 4. 扫描与报告

本地完整分类写入被忽略的 `cache/git_bootstrap/`，避免把排除资产的路径细节带进远端。公开扫描报告只记录路径、发现类型、行号和不可逆安全指纹，不打印匹配值。

门禁覆盖：

- allowlist 对账；
- secret、credential 与高风险 token 模式；
- DB/sidecar/backup/broadcast 禁止资产；
- Windows 保留名、不安全字符、超长相对路径；
- symlink、junction/reparse 与路径逃逸；
- 普通 Git 大对象；
- SQLite 专属依赖增量。

显式 vendor 资产可以通过单文件白名单保留，但不得用目录白名单绕过 secret 或数据库检查。

## 5. SQLite 增量 ratchet

`config/sqlite_dependency_baseline.json` 如实记录 bootstrap 时的 legacy 依赖。阶段 1 不重构全部旧代码，但新变更不得静默增加 `sqlite3.connect()`、`ATTACH`、`PRAGMA`、`BEGIN IMMEDIATE`、SQLite conflict DML、硬编码 `data/*.db` 等依赖。

这里的 writer 按 domain mutation path、write endpoint、writer operation 或 transaction contract 审计，不等同于整个进程。静态基线中的函数符号只是 operation 候选定位，不是阶段 3 的 cutover ownership 结论。

## 6. 生产治理限制

个人账号下的 private 仓库可用于 bootstrap 和开发，但在公司资产控制、共同管理/交接、2FA、账号恢复、branch protection、最小权限和公司控制的 VM deploy credential 完成前，不是 production authority。阶段 1 不配置 VM credential，也不部署 production。

## 7. CI 与环境

阶段 1 的 Python 3.10、hash-pinned lockfile、clean-clone 测试分层和 required-check 合同见 [阶段 1 CI、测试分层与 Python 环境合同](STAGE1_CI_AND_ENVIRONMENT.md)。CI 不使用被仓库边界排除的研究资料或 live 数据；受控 artifact 集成测试不会被伪装成 clean-clone coverage。
