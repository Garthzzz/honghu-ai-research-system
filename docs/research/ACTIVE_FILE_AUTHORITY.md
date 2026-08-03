# 活动文件与历史文件分层

## 活动入口

| 文件 | 用途 |
|---|---|
| `AGENTS.md` | Fresh Session 入口、红线、任务路由 |
| `config/research_workflow.yaml` | A/B/C 唯一机器工作流契约 |
| `docs/research/RESEARCH_WORKFLOW_V2.md` | 工作流、审查和发布语义 |
| `codex_context/LIVE_STATE.md` | 脚本生成的当前 DB/文件/运行快照 |
| `codex_context/PROJECT_COMPLETE_UNDERSTANDING.md` | 整体模块边界，按需读取 |
| `codex_context/FILE_DB_INDEX.md` | 路径、数据库和路由索引，按需读取 |
| `templates/数据呈现与重写标准.md` | A/B/C 共同写作和数据呈现合同 |
| `opportunity_lens/MODULE_CONTEXT.md` | C 轨活动模块、稳定页面族与路由职责 |
| `opportunity_lens/HUMAN_READABILITY_STANDARD.md` | C 轨特有展示契约 |
| `opportunity_lens/C轨研究启动与开放探索输出标准_V0.9.1.md` | C 轨 intake、搜索、候选发现和补证基础合同 |
| `opportunity_lens/C轨供需失衡评分流程与可解释计算体系_V0.8.1.md` | C 轨评分、因子、指标槽和可解释计算基础合同 |
| `opportunity_lens/C轨独立DB与开放研究深度补充修订说明_V1.0.md` | C 轨独立 DB、状态和 A/B 只读边界基础合同 |
| `opportunity_lens/C轨输出模板与前端可视化标准_V1.1.md` | C 轨页面族、页面职责、追踪和展示骨架基础合同；公开内容写法以现行人类可读性契约为准 |
| `skills/README.md` | A/B/C 活动 skill 清单与旧 skill 边界 |

## 兼容入口

以下文件名仍被历史记录或人工习惯引用，但内容只负责把旧入口导向 V2：

- `STANDARD_行研流程_20260609.md`
- `FRAMEWORK_双轨行研_20260628.md`
- `STANDARD_PROMPT驱动行研_20260628.md`
- `CHECKLIST_新行业接入_20260628.md`

## 历史证据

以下内容保留用于追溯，不是活动 prompt：

- `archive/project_history/retained_originals/root/CLAUDE.md` 和 Claude Code 时代 skills；
- `archive/project_history/retained_originals/root/PROGRESS_LOG.md`、历史 run log 和完成报告；
- `opportunity_lens/design/**`、`opportunity_lens/plan/**`、`opportunity_lens/reviews/**`；顶层四份 C 轨基础合同不属于这一历史目录规则；
- `archive/project_history/retained_originals/root_protocols/` 中的旧 Opportunity Lens prompt；
- 已发布 run 的专题构建器和 `research_outputs/**`。

只有在排查某个历史决策、兼容字段或旧 run 时才读取对应文件，不应整批加载。

统一历史入口是 `archive/project_history/README.md`。该目录只保存过去信息和清理审计，不承载当前配置、脚本、数据库、研究资料或待办，也不进入 Fresh Session 默认读取链。
