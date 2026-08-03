# 泓湖 AI 研究系统

本仓库保存应用代码、配置模板、测试、正式项目规则、活动 OpenSpec 和开发/部署工具。它不是 live 数据、研究资料或用户内容仓库。

## 仓库边界

- Git：应用源代码、测试、CI、依赖锁、正式规则与迁移脚本。
- live 结构化数据：当前仍由四套 SQLite 承载，长期目标为中央 PostgreSQL；本仓库不保存数据库文件或 dump。
- papers/evidence：由内部资料存储管理，不进入普通 Git 历史。
- runtime/backup/broadcast/cache/secrets：全部在 Git 外管理。
- `honghu-ai-research-content`：当前状态为 `RESERVED-UNUSED`，不是数据通道或备份权威。

详细分类、例外和提交前门禁见 [Git 仓库边界](docs/GIT_REPOSITORY_BOUNDARY.md)。当前迁移合同见 `openspec/changes/github-vm-dual-node-operations/`。

阶段 1 的解释器、依赖锁、CI 和测试分层见 [阶段 1 CI 与环境合同](docs/STAGE1_CI_AND_ENVIRONMENT.md)。

## 当前实施阶段

阶段 1 仅建立安全 Git bootstrap、测试基线、依赖锁和 CI。它不授权 PostgreSQL production、数据库切换、任务迁移或 VM 部署。
