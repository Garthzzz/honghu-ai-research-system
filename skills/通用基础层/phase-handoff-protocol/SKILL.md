---
name: phase-handoff-protocol
description: V2 stage 交接协议。用 artifact hash、gate 结果和依赖记录交接；不要求固定 PHASE completion report 或角色标签。
metadata:
  category: core
  version: 2.0.0
---

# Stage Handoff V2

进入下一 stage 前确认：

- 上一 stage 的输出 artifact 存在且 hash 已记录；
- 必需 gate 没有 RED；
- 下一 stage 只接收所需 brief slice 和 artifact，不重复加载全量历史 prompt；
- 未关闭 finding 有明确 owner、影响范围和 reconciliation 状态。

只有长任务、写库、发布或跨会话恢复需要持久化 handoff，写入 execution manifest 即可。普通连续编辑不创建 `PHASE_N_COMPLETION_REPORT.md`。需要独立判断时才启用 fresh reviewer；角色标签和 subagent 数量都不是有效交接证据。
