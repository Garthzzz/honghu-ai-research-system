---
name: session-reporting
description: V2 会话收尾。基于实际命令、manifest、DB 和测试结果给出简洁高信号说明，不生成固定 ASCII 大表。
metadata:
  category: engineering
  version: 2.0.0
---

# Session Reporting V2

收尾只说明：

1. 实际完成的行为和关键设计变化；
2. 改动的主要文件、数据库或公开接口；
3. 本轮实际执行的测试、迁移和页面验证结果；
4. 未执行项、兼容边界和真实残余风险。

事实优先读取 execution manifest、DB 查询和命令输出。报告长度随任务风险调整；不要求固定栏目、ASCII 边框、会话事件日志或耗时统计。
