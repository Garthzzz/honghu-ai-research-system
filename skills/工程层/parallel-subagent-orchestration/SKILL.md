---
name: parallel-subagent-orchestration
description: 仅在任务可独立、写集不冲突且并行有收益时使用 subagent。不是研究 prompt 每个方向固定启动 agent 的要求。
---

# 并行编排 V2

使用 subagent 前先完成总体 brief 和依赖图。

适合并行：

- 不同地区或语言的独立来源检索；
- 不同公司、产品或数据源的独立核验；
- 写集互不重叠的代码模块；
- 主路径继续推进时可并行完成的验证。

不适合并行：

- 下一步立即依赖结果的阻塞任务；
- 多 worker 会重复读取同一完整 prompt；
- 分工边界不清或会编辑同一文件；
- 只是为了满足固定 agent 数量。

每个 worker 只接收对应 `ResearchBrief` slice、输入 artifact 和输出合同。结果按 source/requirement/artifact id 合并；不靠自由文本手工拼接。并行不是质量证据，最终仍走共同 gate 和综合审稿。

