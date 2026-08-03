# 阶段 1 实施与验收报告

报告日期：2026-08-04（北京时间）

状态：工程门禁正在闭环；阶段 1 人工 HALT 未批准，不进入阶段 2。

## 1. 授权与隔离边界

- 用户已于 2026-08-03 21:12:55 +08:00 批准阶段 0 退出，授权范围仅为安全 Git 接入、版本边界、测试基线、依赖锁和 CI。
- 活动目录 `D:\quant\industry_demo` 没有被切换 branch、reset、clean、迁移或用于破坏性测试。代码修复与远端操作在 sibling clone `D:\quant\industry_demo_stage1` 完成。
- 未授权也未执行 PostgreSQL、live SQLite 写入或 schema 变更、计划任务变更、VM 部署、papers/数据库/备份/用户内容上传、内容仓库操作或阶段 2。

## 2. Git 历史与远端范围

- 应用仓库：`Garthzzz/honghu-ai-research-system`。
- bootstrap branch：`bootstrap/stage1-safe-history`。
- 当前仓库临时为 public，仅用于本轮审查；这不是长期批准状态，也不是 production authority。
- 初始安全 inventory 为 742 个文件。后续新增内容只包括 CI、依赖与测试合同、阶段审计证据、Windows 路径兼容修复、pending-review 安全索引和精确提交证据生成器；没有把 excluded 资产补进 Git。
- 本轮最终修订暂存后的 tracked 文件数为 760；相对首次增加 18 个，均落在上述获准类别。最终字节数、类型分布和逐文件身份不在这里手工冻结，以成功 main run 的 runtime artifact 为准。
- 最终逐文件数量、体积、类型分布、最大对象和 SHA256 由 required job 在精确 checkout 后生成 `stage1-evidence-{github.sha}` artifact。该机制避免让 tracked 报告伪造包含自身的 commit SHA。

## 3. tracked、excluded 与 pending-review

- tracked allowlist 权威：`config/git_tracked_policy.json`；`.gitignore` 只是误操作防线，不代替 allowlist、gate 或未来 deployment manifest。
- tracked 包含应用源代码、测试、CI、正式项目规则、活动 OpenSpec、审核实际依赖的 skills、正式 SOP、配置模板和必要静态资源。
- excluded 包含 SQLite/WAL/SHM/journal、PostgreSQL dump、backup、broadcast、runtime/log/cache、凭据和浏览器状态、papers/evidence、用户研究内容、个人 scratch 和历史归档。
- 原始全项目 inventory 中 66 个不确定文件继续保持 untracked。`config/pending_review_index.json` 长期保存每项的路径 SHA256、安全范围、后缀、大小、分类、暂不纳入原因和状态，但不公开原始路径或内容；完整路径映射只留在 ignored 本地 inventory。
- Git 全历史对象路径复核没有发现数据库、backup、broadcast、papers、Cookie 或 storage-state 被提交。

## 4. 远端 CI 根因与修复

原提交 `3db233b6c8a302f49740da40005d93a010c3f67a` 的远端 `python-clean-environment` 连续失败。真实日志显示五个测试都源于 GitHub Windows runner 把同一临时目录分别暴露为 8.3 短名和规范长名；直接使用 `Path.relative_to()` 做词法比较时，路径在文件系统上相同、字符串上却不属于同一根目录。

第一次修复只增加了公共路径 helper，仍有两个实际调用点绕过 helper，而且一个 API 把规范长路径返回给短路径调用者，因此远端仍失败。第二次修复：

- 内部安全比较统一使用 Windows 规范路径；
- 公共 API 边界保留调用者原有路径表示；
- `ingest_research`、paper path 校验/规范化和 DataYes 下载路径全部改走安全 helper；
- 回归测试不只测 helper，而是把真实 ingest 调用链绑定到实际 8.3 alias。

提交 `f0532d9846fddef7d25e359170d1335136206525` 的远端 run `30845719227` 已真实通过两个 job：`boundary-and-contracts` 与 `python-clean-environment`。远端 clean-clone 结果为 531 passed、21 skipped、53 subtests passed；加入精确提交证据回归后，本地同层结果为 532 passed、21 skipped、53 subtests passed。随后该绿色提交用于创建 `main`；main 同 SHA 的 run `30846637590` 也已完成且两个 job 均为 success，没有在失败 CI 上宣布完成。

## 5. 精确提交证据

- `tools/maintenance/build_stage1_evidence.py` 只读取 `git ls-files` 中的 tracked 文件。
- 每次 required CI checkout 后生成：`final_inventory.json`、`capability_spec_identities.runtime.json`、`stage1_completion_report.runtime.md`。
- runtime evidence 记录 branch/ref、精确 commit SHA、UTC 生成时间、run id、逐文件大小与 SHA256、类型分布、七份 capability spec hashes 和 pending-review 索引 hash。
- `stage1/capability_spec_identities.json` 保存静态合同 hashes 和运行时绑定方法；人工验收应以成功 main run 上传的同名 SHA artifact 为最终证据。

## 6. 测试、解释器与 CI 合同

- 支持基线为 Python 3.10；`requirements.in` / `requirements-dev.in` 是直接依赖输入，`requirements.lock.txt` 是 Windows/Python 3.10 的 hash-pinned 权威，`requirements.txt` 仅为兼容入口。
- 没有升级或修改 live base/quant 环境，也没有把缺失的 `industry` 环境与它们视为等价。
- CI job：`boundary-and-contracts`、`python-clean-environment`。
- CI 覆盖 compile、clean collection/core tests、tracked/secret/path/large-file gate、SQLite dependency ratchet、OpenSpec strict、lockfile clean install 和精确提交证据。
- CI 只有 `contents: read`，checkout 不持久化 credential；不访问 live DB、内网、供应商生产 API、papers、用户内容或 VM。
- governed-artifact integration tests 仍由显式 manifest 分层，因为其必要 artifact 被禁止上传；没有把它们伪装成通过，也没有用永久 xfail、删除测试或降低合同门槛掩盖失败。

## 7. SQLite ratchet 与 writer 粒度

- 当前 legacy SQLite 命中按 baseline 保留；新 PR 不得静默增加 `sqlite3.connect()`、`ATTACH`、`PRAGMA`、`BEGIN IMMEDIATE`、SQLite 专属 conflict DML、硬编码 `data/*.db` 或跨库自增 ID 依赖。
- writer 按 domain mutation path、write endpoint、writer operation 或 transaction contract 审计，不等于整个 Python/Viewer/scheduler 进程。
- 阶段 1 没有构建 cutover registry，也没有重构生产数据访问层。

## 8. main、保护与仓库治理

- GitHub API 回读确认默认分支为 `main`；required checks 为 `boundary-and-contracts` 与 `python-clean-environment`，strict update、PR review gate、管理员约束和 conversation resolution 已启用，force push 与 branch deletion 已禁止。
- 最终阶段修订必须通过 PR 和 main Actions，不能用管理员身份直接绕过保护。
- 当前个人账号仓库可作为 bootstrap/development source，但未获得 production authority。公司资产归属或批准例外、第二管理员/交接、2FA、账号恢复、最小权限和公司控制的 VM deploy credential 仍是未来 production gate。
- 内容仓库保持 `RESERVED-UNUSED`，本阶段未连接或写入。

## 9. 临时公开风险

`public_repository_exposure_review.md` 记录了公开状态下的额外风险：tracked 历史没有发现禁止资产或凭据，但包含固定内网代理调用形态、Windows 内部路径、任务节奏和研究/运维流程。这些不一定是 secret，却不适合长期公开。人工复核结束后应及时恢复 private；本阶段没有擅自删除正式代码或改写生产配置。

## 10. 阶段结论

本报告只提交阶段 1 工程和审计证据，不自行批准阶段 1 退出。只有最终 main commit 的两个 required jobs 真实绿色、保护规则可读验证、运行时证据 artifact 与该 commit 一致、OpenSpec strict 通过后，才建议用户进行阶段 1 人工审批。即使用户批准阶段 1，也不等于批准 PostgreSQL、VM、数据库、runner、production deploy 或阶段 2。
