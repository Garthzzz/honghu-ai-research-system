# A/B 双轨行研兼容框架

状态：兼容文件。活动设计见 `docs/research/RESEARCH_WORKFLOW_V2.md`。旧版完整框架在 `archive/project_history/retained_originals/workflow_v1_20260712/FRAMEWORK_双轨行研_20260628.md`。

## 判轨

| 轨道 | 输入 | 研究要求 |
|---|---|---|
| A | 行业名 + papers | 执行默认行业 coverage |
| B | 用户 prompt + papers/资料 + 独立搜索 | 用户 prompt 全集与 A 轨默认 coverage 取并集；只自动合并完全相同项 |

两轨共享 `research.db`、`industry_data_point`、行业文档、公司透视、估值、产业链和 viewer，不建立第二套行业数据模型。

## 共同原则

- 输入只编译一次为 `ResearchBrief`；每个 worker 只接收当前方向需要的 slice。
- 数据、来源、计算、正文和页面分别产出 artifact；确定性 gate 先于 agent reviewer。
- 并行按独立问题和独立数据源决定，不按 prompt 行数机械拆 agent。
- 失败只打回相关 stage；三轮定向修复仍未闭环则 blocked，不强行通过。
- 篇幅是兜底验收，不是模板；证据、逻辑、反方和问题回答优先。

## B 轨增量

- requirement matrix 必须记录每条 prompt 要求的落点、证据和完成状态。
- 本地研报是 seed，不是候选池上限，也不是结论上限。
- 公司研报默认只能支持线索或公司自述，需独立核验隐患、竞争对手和反方。
- 资料少时主动扩展官方、监管、行业组织、海外本地语言、客户、供应商和替代路线。

机器差异由 `config/research_workflow.yaml::tracks` 定义，不在多份自然语言文档重复维护。
