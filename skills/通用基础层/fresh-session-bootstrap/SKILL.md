---
name: fresh-session-bootstrap
description: V2 项目启动。读取最小活动上下文，再按任务路由补读；禁止整批加载历史 prompt、日志和 skills。
---

# Fresh Session Bootstrap V2

默认读取：

1. `AGENTS.md`
2. `codex_context/LIVE_STATE.md`
3. `config/research_workflow.yaml`
4. 当前任务直接相关的代码、DB、输入和活动文档

研究任务加读 `docs/research/RESEARCH_WORKFLOW_V2.md`。C 轨加读 `opportunity_lens/MODULE_CONTEXT.md` 和 `opportunity_lens/HUMAN_READABILITY_STANDARD.md`。只有需要完整模块边界时才读 `PROJECT_COMPLETE_UNDERSTANDING.md`。

不要默认读取 `PROGRESS_LOG.md` 最近 200 行、全部旧 SOP、所有 skills、全部 Opportunity Lens 设计/计划或 run 历史。精确计数和服务状态必须重新查询，不能引用快照当实时事实。
