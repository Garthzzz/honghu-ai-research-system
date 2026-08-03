# 阶段 1 首次 staged inventory 审查

审查时间：2026-08-03（北京时间）  
分支：`bootstrap/stage1-safe-history`  
范围：首次应用代码历史；不含数据库、papers/evidence、用户研究内容、backup、broadcast、runtime、cache 或 secrets。

## 1. 暂存区结果

- 文件数：`742`；总大小：`26,848,959 bytes`（约 `25.61 MiB`）。
- 分类：应用源代码 `545`、测试 `93`、正式治理/spec `93`、部署/配置模板 `11`。
- 最大普通对象：`tools/viewer/static/vendor/plotly.min.js`，`4,847,499 bytes`；第二大对象为 `mermaid.min.js`，`3,335,717 bytes`。两者是 Viewer 明确依赖的冻结 vendor 资源，低于 `10 MiB` block 阈值。
- 文件类型以 Python、Markdown、HTML 和 Viewer 静态资源为主；完整逐文件路径、大小、SHA256 和分类保存在本地忽略目录 `cache/git_bootstrap/staged_inventory_initial.json`。

## 2. 排除和待审查

- 全项目分类把 `data/`、`backup/`、`broadcast_packages/`、`cache/`、`papers/`、`funda/`、`tools/dynamic/secrets/`、Opportunity Lens intake/run outputs 和研究员 workpapers 作为不可暂存边界；这些子树不进入 staged inventory。
- `docs/industries/` 属于研究内容，不进入应用仓库；`codex_context/LIVE_STATE.md` 属于随 live DB 变化的运行快照，不进入 Git。
- 仍有 `66` 个文件保持 `pending_review`，主要是历史 OpenSpec、非活动 skills、旧 prompt/TODO、诊断说明与根目录研究请求；本次没有猜测纳入。
- `tools/vocab_queue.jsonl` 是待人工合并的运行队列，审查中从 staged index 移除并加入显式排除。

## 3. 安全门禁

- allowlist 对账：通过；暂存区所有文件均由 `config/git_tracked_policy.json` 显式选择。
- secret/credential 扫描：通过；报告不含匹配值。首次规则对 minified vendor 产生 6 个 generic false positive，复核后只对显式 vendor 关闭低置信通用赋值模式，高置信 private-key/token 模式继续执行。
- DB/WAL/SHM/backup/broadcast 检查：通过，暂存区为 0。
- Windows 保留名、不安全字符、相对路径长度、symlink/junction/reparse 与路径逃逸检查：通过。
- 大文件门禁：通过；无普通 Git 对象超过 block 阈值。
- SQLite legacy 基线：静态记录 `589` 个规则命中，分布于 `163` 个 tracked Python 文件；这是债务基线而非完成迁移的声明。后续 CI 只允许持平或下降，新增例外必须显式审计。

## 4. 已知基线债务

首次 commit 如实保留 import-time stdout 副作用和两个旧硅片 V2 builder 契约失败，不把它们标成通过。修复将在推送 bootstrap 后的隔离 clone 中完成，并以独立 commit 和测试证据提交。

## 5. 对 live 工作区的影响

本次只在活动根目录增加 `.git` 元数据和阶段 1 源文件，没有切换 branch、reset、clean、移动文件、修改 live SQLite、启动 migration、调整计划任务或改 Viewer/VM 配置。后续代码修复在 sibling clone 中进行。
