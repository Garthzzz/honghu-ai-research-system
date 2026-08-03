---
name: verifier-protocol
description: 风险自适应审查协议。机械问题先由 gate 处理，reviewer 只审需要判断的 artifact；输出 findings、证据和 reconciliation，不写空泛 verdict。
---

# Verifier Protocol V2

## 选择 reviewer

- 所有任务：contract、evidence integrity、provenance、duplicate、scope/unit/time gate。
- 有派生计算：calculation reviewer。
- 有评分、指数、方法：science/logic reviewer。
- 有公司财务：financial reviewer。
- 有公开正文：writing/citation reviewer。
- 有新页面：browser reviewer。
- 有冲突、单一证据组或陈旧当前结论：evidence escalation。
- 发布前：一次 integrated final reviewer。

## 记录

每条 review record 必须有：

```json
{
  "stage": "science",
  "reviewer_role": "science_reviewer",
  "reviewer_id": "independent-science-01",
  "review_kind": "independent",
  "input_artifact_hash": "sha256:...",
  "output_artifact_hash": "sha256:...",
  "verdict": "GREEN | YELLOW | RED",
  "findings": [],
  "reconciliation_status": "pending | resolved | blocked | not_applicable"
}
```

公开页面的 browser 记录可以是可复现的 deterministic Playwright 审计；evidence/calculation/science/financial/writing/final 等发布必需判断不得用 deterministic 自报替代独立或人工 reviewer。

RED 打回对应 producer。修订后产生新 artifact hash 和新 review 记录；不得覆盖旧 findings。最多三轮定向修复，未闭环则 blocked。

GREEN 必须说明检查了什么和依据；“看起来没问题”不是审查。规范文件存在、静态 review contract 和 producer 自报都不是 independent review。

工作流重构还必须审查运行接线：生产入口是否真实生成 brief、五项 gate、review plan、requirement coverage 和缓存记录。只验证独立核心类、文档或测试夹具，不能判定端到端流程 GREEN。C 轨发布后共享 execution manifest 必须与 DB 最新 gate/reviewer 记录一致。
