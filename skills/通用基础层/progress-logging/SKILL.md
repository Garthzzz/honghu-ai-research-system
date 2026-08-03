---
name: progress-logging
description: V2 低噪声记录协议。运行事实进入 execution manifest/live snapshot，PROGRESS_LOG 只记录重要架构里程碑，PENDING 只保留真实待用户决策。
metadata:
  category: core
  version: 2.0.0
---

# Progress Logging V2

- `cache/research_runs/<run>/manifest.json`：输入 hash、requirement coverage、stage、gate、review、修订和发布事实。
- C 轨：同类记录进入 `opportunity_quality_gate_result`、`opportunity_agent_review_log` 和 run manifest。
- `codex_context/LIVE_STATE.md`：由只读脚本生成的当前 DB/文件快照。
- `PROGRESS_LOG.md`：只追加架构迁移、正式发布、重大数据修复等人工需要追溯的里程碑，不按每个 phase/文件/论文追加。
- `PENDING_USER_REVIEW.md`：只记录确实需要用户裁决或外部状态改变的事项；一般 YELLOW 和可自行判断的方案不堆积。

聊天更新用于当前可见进度，不能替代 manifest；也不再维护强制 `session_current.log`、七段阶段报告或 ASCII 框汇报。
