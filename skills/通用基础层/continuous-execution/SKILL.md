---
name: continuous-execution
description: V2 连续执行协议。按依赖图推进到可验证完成，仅在真实授权、输入或安全阻塞时停止；不为每阶段生成固定报告。
metadata:
  category: core
  version: 2.0.0
---

# Continuous Execution V2

1. 把任务拆成依赖明确的 stage，前一 stage 的产物通过 gate 后立即推进。
2. 需要跨会话恢复、写库或发布的任务，把状态、输入 hash、产物 hash 和 blockers 写入 execution manifest。
3. 普通探索和小改动不创建阶段报告；中间进度通过简短用户更新说明。
4. 只有用户明确暂停、缺少不可推断的必要输入、需要额外授权或安全门禁失败时停止。
5. reviewer 按 artifact/风险触发；不得把“每阶段固定 reviewer/固定 persona/固定报告”当连续执行条件。
6. 失败只返回相关 producer stage，最多三轮定向修复；仍不闭环则记录 blocked，不伪造完成。

项目研究任务同时遵循 `config/research_workflow.yaml` 和 `docs/research/RESEARCH_WORKFLOW_V2.md`。
