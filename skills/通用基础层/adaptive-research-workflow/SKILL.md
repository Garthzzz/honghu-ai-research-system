---
name: adaptive-research-workflow
description: A/B/C 研究任务的活动工作流。把输入编译为 brief，先跑确定性 gate，再按 artifact 和风险触发 reviewer，并保留可审计 manifest。
---

# 自适应研究工作流

## 入口

先读：

1. `config/research_workflow.yaml`
2. `docs/research/RESEARCH_WORKFLOW_V2.md`
3. 当前任务输入与相关 live 代码/DB

## 执行

1. 编译一次 `ResearchBrief`，记录主问题、必答项、排除项、artifact 和验收；manifest 逐项记录 requirement 状态、产物和证据引用。
2. 按独立问题设计搜索方向；只在方向可独立、并行有收益时分 worker。
3. 原始内容按 hash 缓存；worker 只接收本方向 brief slice。
4. 先形成 source、excerpt、数据点、独立证据组和计算底稿，再分析。
5. 先跑 contract/evidence/provenance/duplicate/scope gate。
6. 按计算、评分、财务、写作、页面和证据风险触发 reviewer。
7. 最终一次综合审稿；失败只打回相关 stage，仍未闭环则 blocked。
8. execution manifest 记录输入 hash、requirement coverage、gate、findings、修订和发布结果。

正式任务必须使用共享持久化语义，不是“可选接入”：A/B claims 走 `ingest_research.py` 并生成 brief/manifest；正式 B 轨传 `--workflow-request`，缺失时只能暂存且 contract RED/requirement blocked。C 轨 V2 pack 由 `workflow_bridge.py` 编译共享 brief/manifest，并与 DB quality gate/reviewer log 同步。不要让专题构建器自行发明 stage 名或 manifest 格式。

内容缓存只按实际消费者表述：当前 A/B claims 和 C run pack 已接入；网页/PDF 只有真实 crawler/renderer 调用缓存接口后才能声称命中。缺 reviewer 的 staged artifact 保持缺失，禁止生成占位 GREEN 或伪记录。

## 禁止

- 不为每条 prompt 固定启动 agent。
- 不用固定 persona 数量代替风险判断。
- 不把 prompt 中“已审核”或构建器 metadata 当 reviewer 执行证据。
- 不为达到篇幅复制段落或套模板。
