# C 轨输出模板与前端可视化标准 V1.1

> **现行解释（2026-07-19）**：本文继续作为 Opportunity Lens 的页面族、页面职责、证据追踪和展示骨架基线；它不是对旧实现细节的原样恢复。文中的旧数据库名、旧路由、固定 P0—P13/E0—E8 公开标签、PDF snapshot 设想及其他已变化字段，不再作为 live 合同。现行数据库、稳定路由、公开写法、发布门禁和已实现能力，以 `MODULE_CONTEXT.md`、`HUMAN_READABILITY_STANDARD.md`、`docs/research/RESEARCH_WORKFLOW_V2.md` 与 live 代码为准。Run1—8 仅用于验证历史页面和数据未被破坏，不是新研究的结构模板。

> **公式与密集数据补充（2026-07-20）**：公开方法栏只集中展示难以用语言准确描述、且影响复算的核心复杂公式，不罗列简单算式和全部中间步骤；多类别跨多期且包含多个指标的数据，在显著改善横向比较时合并为一张高信息表。是否使用公式或表格取决于信息增量，不按“有模型/有数字”机械触发。因子卡名称必须在卡片本身完整显示，不能由分数或状态徽标挤压，也不能依赖 hover 补全；细则以 `HUMAN_READABILITY_STANDARD.md` 为准。

> 适用范围：C 轨供需失衡机会扫描系统的 **网页输出、前端可视化、分析段落、PDF 导出、展示层入库结构**。  
> 配套文档：`V0.8.1 评分流程与可解释计算体系`、`V0.9.1 研究启动与开放探索输出标准`、`V1.0 独立 DB 与开放研究深度补充修订说明`。  
> 本文不重写 V0.8.1 的评分模型，也不重写 V0.9.1 的 文献综述 / readiness 流程；本文定义 **研究结果如何入库、如何展示、如何追溯、如何导出**。

---

## 0. 一句话定位

C 轨前端不是“把 Markdown 报告渲染出来”，而是一个 **可解释、可审计、可回放的机会扫描工作台**：

```text
C-Open / C-Paper research pack
        ↓
opportunity.db 结构化研究结果 + 证据 + 评分 trace
        ↓
Flask / industry_demo 前端新子页
        ↓
Run 总览 → 候选/评分/事件/审计/补资料 → Entity/Factor/Slot drill-down
        ↓
可导出完整 PDF snapshot
```

网页上的每一段分析、每一个分数、每一个图表，都必须能回到：

```text
source / data_point / metric_slot / factor_score / event / audit_issue
```

如果不能回到上述任一对象，就不能作为正式分析展示；只能作为 `unsupported_note`，并用红色明确标注。

---

## 1. 设计目标

### 1.1 用户目标

C 轨网页要让研究员和 PM 在一个页面上完成以下判断：

1. 这个开放问题是否已经研究到足够深度？
2. 哪些候选环节/材料/公司值得继续看？
3. 哪些结论是数据支持的，哪些只是推断或线索？
4. 每个分数是怎么从原始数据计算出来的？
5. 哪些字段缺失、过期、冲突或覆盖不足？
6. 市场是否已经反应，研究优先级是否仍然高？
7. 如果不能正式评分，还缺什么资料？
8. 最终能否把网页完整导出为 PDF 交给投研同事审阅？

### 1.2 架构目标

1. **独立 C 轨 DB**：C 轨数据写入独立 `opportunity.db`；A/B 轨 `research.db` 只读参考，不修改、不删除、不回写。
2. **合并到 industry_demo 前端**：前端平台新增 C 轨子 page，统一视觉系统、统一 source hover、统一 trace 展示。
3. **所有分析可追溯**：每段分析必须绑定 evidence links。
4. **所有数字可展开**：总分 → 因子分 → slot 分 → 原始数据 → source excerpt。
5. **所有低质量内容显式标红**：覆盖不足、AI 推断、弱来源、无证据、冲突未解决、过期数据必须明显标注。
6. **网页优先，PDF 是网页 snapshot**：PDF 不另写一套报告；PDF 是 print-mode HTML 的完整导出。

---

## 2. 和现有 industry_demo 前端的关系

### 2.1 复用现有前端范式

现有 demo 页面已经有几个对 C 轨非常有价值的设计范式：

| 现有元素 | C 轨复用方式 |
|---|---|
| 左侧导航 + 主内容区 | C 轨 run detail 页面按段落锚点导航 |
| KPI 卡片 | 展示总分、覆盖率、置信度、市场反应、审计问题数 |
| ECharts 图卡 | 展示排序、矩阵、热力图、时间线、瀑布图 |
| source hover / source index | 展示 source excerpt、source tier、source URL/PDF |
| 公式折叠 | 展示每个因子和总分公式 |
| 可信度描边/角标 | 区分事实、推导、推测、无证据 |
| brief / scard | 展示核心结论、研究员可读解释、风险提示 |
| print-friendly section | 支持 PDF snapshot |

C 轨不建议另做一套完全不同的视觉语言，应复用现有“浅色面板 + 左侧导航 + 图卡 + 折叠公式 + source hover + 表格”的模式。

### 2.2 推荐路由

```text
/opportunity                         C 轨首页：run 列表 + 最近任务
/opportunity/run/<run_id>             单次 run 完整研究包
/opportunity/entity/<entity_id>       单个材料/环节/公司详情页
/opportunity/factor/<factor_score_id> 单个因子 trace 页
/opportunity/slot/<slot_id>           单个 metric slot 证据页
/opportunity/audit/<run_id>           审计问题页
/opportunity/supplement/<run_id>      补充资料请求页
/opportunity/export/<run_id>          PDF export job 状态页
```

API 建议：

```text
GET  /api/opportunity/runs
GET  /api/opportunity/run/<run_id>/summary
GET  /api/opportunity/run/<run_id>/sections
GET  /api/opportunity/run/<run_id>/entities
GET  /api/opportunity/run/<run_id>/rankings
GET  /api/opportunity/run/<run_id>/visuals
GET  /api/opportunity/entity/<entity_id>/score_trace
GET  /api/opportunity/factor/<factor_score_id>/trace
GET  /api/opportunity/slot/<slot_id>/trace
GET  /api/opportunity/run/<run_id>/audit
GET  /api/opportunity/run/<run_id>/supplement_requests
POST /api/opportunity/run/<run_id>/export_pdf
GET  /api/opportunity/export/<job_id>
```

`POST export_pdf` 是写 job 的动作，必须明确为用户触发；普通 smoke test 不调用。

---

## 3. 输出内容总模板

C 轨网页输出分为两类：

1. **Run 级页面**：回答整个研究问题。
2. **Entity 级页面**：回答某个材料/环节/公司的分数和证据。

### 3.1 Run 级页面固定结构

```text
P0 · 任务与结论总览
P1 · 研究问题拆解与边界
P2 · 搜索覆盖与资料完整度
P3 · 候选 taxonomy 与候选漏斗
P4 · 材料/环节失衡排序
P5 · 公司承接排序
P6 · 市场反应与拥挤度
P7 · 关键因子热力图与覆盖率矩阵
P8 · Top 实体深度卡片
P9 · 事件账本与 12 个月催化剂图谱
P10 · 一票否决与风险闸门
P11 · 审计问题与红色标注
P12 · 补充资料建议
P13 · 方法、公式、版本和 source index
```

### 3.2 Entity 级页面固定结构

```text
E0 · Entity header：对象、层级、应用、地理口径
E1 · 总分卡：基本面分、公司承接、市场反应、研究倾向
E2 · Score waterfall：原始分 → 质量调整 → veto/cap → market priority
E3 · Factor bundle trace：14 个因子包逐项展开
E4 · Metric slot evidence：每个 slot 的原始数据和计算方式
E5 · 事件账本：正负向事件、催化剂、澄清/反证
E6 · 相关 source / data point / excerpt
E7 · 审计问题和待人工复核
E8 · 补充资料建议
```

---

## 4. Run 页面各段落详细标准

### P0 · 任务与结论总览

#### 目的

让用户在 30 秒内知道：

- 这次任务是否能正式评分；
- 哪些方向最值得看；
- 结论证据质量如何；
- 市场是否已经反应；
- 是否有严重审计问题。

#### 必须展示数字

| 字段 | 来源 |
|---|---|
| `run_id` | `opportunity_run` |
| `run_mode` | C-Open / C-Paper |
| `readiness_status` | `opportunity_handoff_package` |
| `scoring_version` | `opportunity_run_manifest` |
| `data_cutoff_date` | `opportunity_run` |
| `entity_count_total` | `opportunity_run_stats` |
| `shortlist_count` | `opportunity_run_stats` |
| `scoring_ready_count` | `opportunity_run_stats` |
| `avg_coverage` | `opportunity_run_stats` |
| `avg_confidence` | `opportunity_run_stats` |
| `high_severity_audit_count` | `opportunity_run_stats` |
| `supplement_request_count` | `opportunity_run_stats` |

#### 必须展示分析

1. **一句话结论**：必须是 data-backed 或明确标注 derived。
2. **Top 3 机会方向**：每条必须链接到 entity detail。
3. **Top 3 风险/反证**：必须链接到 audit issue 或 event。
4. **本 run 能否进入正式评分**：必须说明原因。

#### 推荐可视化

- KPI cards：总实体数、可评分实体数、平均覆盖率、平均置信度、高危审计数。
- Score distribution bar：S/A/B/C/D/未评级数量。
- Readiness gauge：`scoring_ready / score_limited / research_only / blocked`。

#### 红色标注规则

| 条件 | 标注 |
|---|---|
| `readiness_status = blocked` | 整个 P0 顶部红色 banner |
| `avg_coverage < 50%` | “证据不足，不允许强结论”红色 |
| `high_severity_audit_count > 0` | 红色审计 badge |
| 结论来自 AI 推断且无 data point/source | 红色 `unsupported` |

---

### P1 · 研究问题拆解与边界

#### 目的

防止 Agent 在大问题里直接跳到结论。必须展示：

```text
用户问题 → 拆解后的子问题 → 研究对象层级 → 时间窗口 → 地理口径 → 输出限制
```

#### 必须展示内容

| 内容 | 字段 |
|---|---|
| 原始问题 | `opportunity_run.user_question` |
| 系统判定模式 | `run_mode` |
| 拆解后的子问题 | `opportunity_report_section.section_type = question_decomposition` |
| 研究层级 | `theme / industry / segment / product_material / company / security` |
| 时间窗口 | `core_window`, `long_term_window`, `data_cutoff_date` |
| 地理范围 | `geo_scope` |
| 禁止项 | no target price / no position / no unsupported claim |

#### 分析写法

每个子问题应以 `Q1/Q2/Q3...` 写出，例如：

```text
Q1：需求端是否有真实触发？
Q2：供给端是否存在 12 个月内难以缓解的约束？
Q3：是否已有价格或事件信号？
Q4：哪些公司能承接？
Q5：市场是否已经反应？
```

---

### P2 · 搜索覆盖与资料完整度

#### 目的

证明 C-Open / C-Paper 不是“只读研报”，而是执行了全球多语言 文献综述 和 source discovery。

#### 必须展示数字

| 字段 | 来源 |
|---|---|
| 搜索任务数 | `opportunity_search_log` |
| 搜索语言 | `language_set` |
| source group 覆盖 | `opportunity_source_discovery.source_group` |
| accepted source 数 | `accepted_source_count` |
| rejected source 数 | `rejected_source_count` |
| latest source date | source max publish/as_of |
| source tier 分布 | S/A/B/C/D |
| AB reference 使用数 | `ab_reference_count` |
| stale reference 数 | `stale_reference_count` |

#### 推荐可视化

1. **Source coverage heatmap**：语言 × source group。
2. **Source ladder stacked bar**：S/A/B/C/D 数量。
3. **Freshness strip**：按时间显示 source 新鲜度。
4. **Search axis checklist**：taxonomy / demand / supply / signal / company / market / risk 是否完成。

#### 标准表格

| search_axis | languages | query_count | accepted_sources | latest_source_date | coverage_status | missing_notes |
|---|---:|---:|---:|---|---|---|

#### 红色标注规则

| 条件 | 标注 |
|---|---|
| 某核心 search_axis 无 accepted source | 红色 |
| 仅有研报，没有外部独立 source | 红色 |
| 仅有 C/D 级来源 | 红色或黄色，取决于是否进核心结论 |
| source 最新日期超过字段有效期 | stale 红/黄标注 |

---

### P3 · 候选 taxonomy 与候选漏斗

#### 目的

展示 Agent 如何从开放问题收敛到候选材料/环节/公司，避免候选选择黑箱。

#### 必须展示层级

```text
theme
industry
segment
product_material
process_step
application
customer
company
security
geography
```

#### 推荐可视化

1. **Taxonomy tree / sunburst**：从 theme 到 product_material。
2. **Candidate funnel**：discovered → source_candidate → evidence_supported → shortlist → scoring_ready。
3. **Segment-company bipartite graph**：材料/环节 ↔ 公司。
4. **Geo map / country chips**：如果有全球源，显示国家/区域分布。

#### 候选表字段

| 字段 | 说明 |
|---|---|
| `candidate_id` | 候选 ID |
| `entity_type` | product_material / company / security |
| `name` | 名称 |
| `parent_entity_id` | 上级环节 |
| `candidate_status` | discovered / shortlist / scoring_ready / rejected |
| `inclusion_reason` | 纳入原因 |
| `exclusion_reason` | 剔除原因 |
| `evidence_count` | 证据数 |
| `readiness_status` | ready / limited / missing / blocked |

#### 红色标注规则

- `inclusion_reason` 只有 AI 推断且无 source：红色。
- 公司无法映射到具体 `product_material` 或 `segment`：红色 `theme_mapping_only`。
- 只因为股价热度高进入候选：红色或黄色，不允许进公司承接高分。

---

### P4 · 材料/环节失衡排序

#### 目的

回答：哪些材料/环节本身发生供需失衡。

#### 必须展示表格

| 排名 | 材料/环节 | 应用 | 基本面失衡分 | 调整后分 | 覆盖率 | 置信度 | 市场状态 | 评级状态 | 最大支撑 | 最大反证 | 链接 |
|---:|---|---|---:|---:|---:|---:|---|---|---|---|---|

#### 必须展示图表

1. **Segment ranking bar**：按 `segment_imbalance_score_adjusted` 排序。
2. **Factor contribution stacked bar**：需求 / 供给 / signal 的贡献。
3. **Coverage-confidence scatter**：x=coverage，y=score，size=confidence。
4. **Data freshness strip**：每个材料的关键数据最新日期。

#### 分析要求

每个 Top 材料必须有 3 段分析：

1. 需求触发为什么成立；
2. 供给约束为什么成立；
3. 前瞻信号是否已经出现。

每段必须链接到至少一个 factor 或 source。

---

### P5 · 公司承接排序

#### 目的

回答：哪些公司能真实承接材料/环节红利，哪些只是主题映射。

#### 必须展示表格

| 排名 | 公司 | 代码 | 对应材料/环节 | 敞口类型 | 环节分 | 公司承接分 | 基本面机会分 | 市场反应 | 研究倾向 | 覆盖率 | 置信度 | 链接 |
|---:|---|---|---|---|---:|---:|---:|---|---|---:|---:|---|

#### 必须展示图表

1. **Segment-company matrix**：材料/环节 × 公司，颜色为承接强度。
2. **Opportunity quadrant**：x=market crowding，y=fundamental score。
3. **Company capture waterfall**：敞口、收入、产能、财务质量贡献。
4. **Theme mapping warning table**：仅主题映射公司单独列出。

#### 分析要求

每家公司至少输出：

```text
1. 对应环节是什么；
2. 敞口证据是什么；
3. 收入/利润/产能是否能兑现；
4. 市场是否已经反应；
5. 研究倾向标签和原因。
```

已解析为上市公司且研究已完成可复算财务模型时，还应通过 `company_financial_profile_export.v1` 把 FY1—FY3 独立预测、适用的多方法估值和当前市场隐含结果同步到公司详情页。现金流、净资产或倍数依据不足时允许只输出诊断/参考方法，但必须标明限制；不得为填充页面生成目标价或伪精确结果。C 轨 loader 不直接写财务库，同步由独立导入工具完成。

禁止默认输出仓位、目标价、买入/卖出建议。

---

### P6 · 市场反应与拥挤度

#### 目的

区分：

```text
基本面强 ≠ 当前仍未被市场反应
```

#### 必须展示字段

| 字段 | 说明 |
|---|---|
| `excess_return_20d` | 20 日超额收益 |
| `excess_return_60d` | 60 日超额收益 |
| `excess_return_120d` | 120 日超额收益 |
| `valuation_crowding` | 估值拥挤度 |
| `attention_heat` | 成交/新闻/KOL/舆情热度 |
| `market_reflection_state` | unnoticed / early / recognized / crowded / overheated / post_hype_reset |

#### 推荐图表

1. **Market reaction quadrant**：fundamental score vs market crowding。
2. **Price/valuation strip**：20D/60D/120D 超额收益和估值分位。
3. **Attention heat timeline**：新闻、KOL、成交热度随时间。

#### 红色标注规则

- `overheated`：红色。
- `crowded` 且基本面分高：不降低基本面分，但研究优先级下降。
- 市场数据缺失：红色 `market_data_missing`，不能输出“未反应”。

---

### P7 · 关键因子热力图与覆盖率矩阵

#### 目的

让用户一眼看到每个候选的因子覆盖情况、分数质量和缺口。

#### 推荐图表

1. **Factor score heatmap**：entity × 14 factor bundles。
2. **Coverage heatmap**：entity × factor coverage。
3. **Confidence heatmap**：entity × factor confidence。
4. **Readiness matrix**：ready / limited / missing / conflict_blocked。

#### 因子行列

14 个基本面因子：

```text
demand.downstream_price_momentum
demand.customer_capex_capacity_signal
demand.output_consumption_proxy
demand.application_intensity_change
supply.capacity_event_12m
supply.expansion_cycle_bucket
supply.raw_policy_constraint
supply.supplier_structure_bucket
supply.substitution_barrier
signal.material_price_momentum
company.exposure_directness
company.revenue_exposure_proxy
company.capacity_readiness_window
company.financial_capture_quality
```

其中材料/环节页面只展示前 10 个；公司页面展示全部 14 个。

---

### P8 · Top 实体深度卡片

#### 目的

网页中最接近“报告正文”的部分。每个 Top entity 输出一张研究员可读卡片。

#### 卡片结构

```text
标题：Entity name + score + rating + market state
一句话判断
关键支撑证据 3 条
关键反证/风险 3 条
分数构成图
覆盖率和置信度
事件/催化剂
待核验项
跳转：详情页 / 因子 trace / source index
```

#### 分析段落要求

每张卡片至少 4 段：

1. **需求端**：为什么需求成立。
2. **供给端**：为什么供给受限。
3. **信号端**：是否已有价格/事件信号。
4. **承接/市场端**：公司能否兑现，市场是否已反应。

每段都要绑定 evidence links。无 evidence 的段落不得进入 Top card。

---

### P9 · 事件账本与 12 个月催化剂图谱

#### 目的

展示文字利好/利空、催化剂、风险事件和待验证事件。

#### 必须展示事件类别

```text
price_revision
capacity_change
supply_disruption
policy_control
customer_validation
long_term_contract
customer_substitution_or_cut
guidance_or_analyst_revision
accounting_impairment
clarification_denial
```

#### 推荐图表

1. **Catalyst timeline / Gantt**：未来 12 个月事件。
2. **Event type stacked bar**：按事件类型统计。
3. **Positive/negative event lane**：正向、负向、混合事件分泳道展示。
4. **Event → factor mapping graph**：哪些事件映射到哪些 factor。

#### 事件表字段

| 事件日期 | 生效日期 | 类型 | 对象 | 方向 | 严重度 | 来源等级 | 官方确认 | 映射因子 | 是否入分 | 人工复核 | 链接 |
|---|---|---|---|---|---:|---|---|---|---|---|---|

#### 特别规则

- 调价公告映射 `signal.material_price_momentum` 后，事件账本不能重复加分。
- 商誉减值、存货跌价、应收坏账只影响 `company.financial_capture_quality` 或风险提示，不进入供需失衡分。
- 分析师上修/下修、管理层指引变化是 forecast overlay，不当事实。
- 澄清公告/公司否认/交易所问询回复优先级高，必须进入审计区。

---

### P10 · 一票否决与风险闸门

#### 目的

明确是否存在会推翻结论的硬风险。

#### 五个 veto

```text
veto.tech_substitution
veto.capacity_flood
veto.imbalance_too_short
veto.customer_backup_selfdev
veto.policy_market_shutdown
```

#### 推荐可视化

- **Veto matrix**：entity × veto，状态为 safe / warning / triggered / unknown。
- **Risk waterfall**：veto/cap 对最终 rating 的影响。

#### 标注规则

| 状态 | 展示 |
|---|---|
| safe | 正常 |
| unknown | 黄色，不扣分但降低置信度 |
| warning | 黄色/橙色，限制评级上限 |
| triggered | 红色，进入回避/否决 |

---

### P11 · 审计问题与红色标注

#### 目的

集中展示所有导致“不确定性上升”的问题。

#### 审计问题类型

```text
source_missing
source_rejected
source_conflict
official_vs_media_conflict
calculation_error
unit_conversion_error
period_conflict
geo_scope_conflict
capacity_definition_conflict
supplier_count_definition_conflict
duplicate_event_score
stale_data
low_coverage
ai_inference_only
unsupported_claim
```

#### 推荐图表

1. **Audit severity bar**：high/medium/low 数量。
2. **Audit table**：可筛选。
3. **Factor-blocking map**：哪些 audit issue 阻止哪些因子评分。

#### 红色标注统一规则

任何内容满足以下条件之一，必须红色：

```text
coverage < 50%
source_review_status = reject
calculation_review_status = fail
conflict_status = unresolved
support_status = unsupported
value_status = weak_source_only 且进入核心结论
ai_generated_flag = 1 且无 evidence links
freshness_status = stale_only 且用于当前失衡判断
```

黄色规则：

```text
coverage 50%-65%
single_source_only
forecast_overlay
source_tier = C 但非低质
freshness approaching expiry
unknown veto
```

---

### P12 · 补充资料建议

#### 目的

把“缺什么”变成可分配任务，而不是自然语言抱怨。

#### 表格字段

| 字段 | 说明 |
|---|---|
| `target_entity_id` | 缺口对应对象 |
| `target_factor_code` | 缺口对应因子 |
| `target_slot_code` | 缺口对应 slot |
| `missing_evidence_type` | price / capacity / customer / financial / market 等 |
| `recommended_source_type` | 推荐源类型 |
| `recommended_source_examples` | 推荐查哪些源 |
| `priority` | high / medium / low |
| `blocking_status` | blocks_scoring / limits_confidence / nice_to_have |
| `reason` | 为什么缺 |
| `expected_decision_impact` | 补上后会影响什么判断 |
| `suggested_search_query` | 建议搜索语句 |
| `acceptable_alternatives` | 可接受替代来源 |
| `can_score_without_it` | 是否可评分 |
| `freeform_agent_note` | Agent 自由补充 |

`freeform_agent_note` 必须保留，用于 Codex 说明标准字段无法表达的补充建议。

---

### P13 · 方法、公式、版本和 source index

#### 必须展示

1. 评分版本；
2. factor dictionary version；
3. preprocessing version；
4. source ladder version；
5. event mapping version；
6. model/prompt version；
7. PDF export snapshot version；
8. 全部 source index；
9. 全部公式；
10. 免责声明。

公式显示方式：

```text
plain language formula
+ expandable exact formula
+ factor weights
+ link to factor trace
```

---

## 5. Analysis Text 入库与展示标准

### 5.1 分析段落不能只存在 HTML 中

分析段落必须入库，否则无法追溯、review、导出 PDF 或复用。

新增表：`opportunity_report_section`

```sql
CREATE TABLE opportunity_report_section (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    entity_id INTEGER,
    section_type TEXT NOT NULL,
    section_order INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary_md TEXT,
    body_md TEXT,
    conclusion_direction TEXT,      -- positive / negative / mixed / neutral / uncertain
    confidence_level TEXT,          -- high / medium / low
    support_status TEXT NOT NULL,   -- supported / derived / forecast / weak / unsupported / conflict
    red_flag_level TEXT DEFAULT 'none', -- none / yellow / red
    ai_generated_flag INTEGER DEFAULT 1,
    reviewer_status TEXT DEFAULT 'pending', -- pending / confirmed / rejected / revised
    reviewer_note TEXT,
    print_include_flag INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);
```

### 5.2 段落证据链接表

```sql
CREATE TABLE opportunity_section_evidence_link (
    id INTEGER PRIMARY KEY,
    section_id INTEGER NOT NULL,
    evidence_type TEXT NOT NULL, -- source / data_point / metric_slot / factor_score / event / audit_issue / supplement_request
    evidence_id INTEGER NOT NULL,
    role TEXT NOT NULL,          -- primary / supporting / contradiction / method / caveat
    anchor_label TEXT,
    rationale TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### 5.3 分析段落类型

| `section_type` | 用途 | 是否可作为结论 |
|---|---|---|
| `executive_thesis` | 核心观点 | 是，必须 supported/derived |
| `demand_analysis` | 需求分析 | 是 |
| `supply_analysis` | 供给分析 | 是 |
| `signal_analysis` | 价格/事件信号分析 | 是 |
| `company_capture_analysis` | 公司承接分析 | 是 |
| `market_reaction_analysis` | 市场反应 | 是 |
| `risk_analysis` | 风险和反证 | 是 |
| `forecast_overlay` | 预测/分析师观点 | 只能标 forecast |
| `method_note` | 方法说明 | 否 |
| `unsupported_note` | 无证据备注 | 否，必须红色 |

### 5.4 支撑状态展示

| `support_status` | 展示 | 规则 |
|---|---|---|
| `supported` | 实线边框 | 有 source/data_point/factor 支撑 |
| `derived` | 虚线边框 | 基于多个数据推导，有 trace |
| `forecast` | 黄色/预测角标 | 管理层/分析师/模型预测 |
| `weak` | 黄色 | 单一弱来源或覆盖不足 |
| `unsupported` | 红色 | 无数据支撑，不得进入结论 |
| `conflict` | 红色 | 来源冲突未解决 |

---

## 6. 可视化组件清单

### 6.1 Run 总览组件

| 组件 | 目的 | 数据源 |
|---|---|---|
| KPI cards | 展示 run 状态 | run_stats/composite_score |
| Readiness gauge | 是否可正式评分 | handoff_package |
| Score distribution | 评级分布 | composite_score |
| Search coverage heatmap | 搜索覆盖 | source_discovery/search_log |
| Candidate funnel | 候选收敛 | candidate_entity |
| Taxonomy tree | 产业链结构 | candidate_entity |

### 6.2 Score 组件

| 组件 | 目的 | 数据源 |
|---|---|---|
| Factor heatmap | entity × factor 分数 | factor_score |
| Coverage heatmap | entity × factor 覆盖率 | factor_score |
| Score waterfall | raw → adjusted → cap → priority | composite_score |
| Factor contribution bar | 因子贡献 | factor_score |
| Formula fold | 解释计算公式 | scoring_rule_version |
| Factor trace tree | 因子 → slot → source | factor_score / metric_slot |

### 6.3 事件与风险组件

| 组件 | 目的 | 数据源 |
|---|---|---|
| Catalyst timeline | 12 个月事件 | event_ledger |
| Event lane | 正/负/混合事件 | event_ledger |
| Event-factor graph | 事件映射 | event_ledger |
| Veto matrix | 风险闸门 | veto_status |
| Audit table | 审计问题 | audit_issue |
| Supplement table | 补资料建议 | supplement_request |

### 6.4 市场组件

| 组件 | 目的 | 数据源 |
|---|---|---|
| Market quadrant | 基本面强度 vs 市场拥挤 | market_reaction/composite_score |
| Excess return strip | 20/60/120D 超额收益 | market_reaction |
| Valuation crowding chart | 估值分位 | market_reaction |
| Attention heat timeline | 新闻/KOL/成交热度 | market_reaction / sentiment refs |

---

## 7. 可解释分数展示标准

### 7.1 总分展示

任何总分必须显示完整链路：

```text
company_fundamental_score_raw
→ company_fundamental_score_capped
→ coverage/confidence adjustment
→ company_fundamental_score_adjusted
→ market_reflection_state
→ research_priority_score
→ research_bias_label
```

页面上用 waterfall 展示，点击每一步展开：

```text
公式
输入因子
权重
原始值
调整原因
审计问题
```

### 7.2 因子展示

每个因子必须展示：

```text
factor_score_raw
factor_coverage
factor_confidence
factor_reliability
factor_score_adjusted
primary_slot
supporting_slots
contradiction_slots
event_adjustment
audit_issues
```

### 7.3 Slot 展示

每个 slot 必须展示：

```text
raw_value
raw_unit
standardized_value
standardized_unit
preprocess_trace_json
bucket_label
slot_score
source_id
source_excerpt
source_tier
freshness_days
source_review_status
calculation_review_status
value_status
```

---

## 8. 红色、黄色、可信度和方向显示规范

### 8.1 方向颜色

| 方向 | 颜色 |
|---|---|
| 正向 | 绿色 |
| 负向 | 红色 |
| 中性 | 灰色 |
| 不确定 | 黄色/琥珀 |

### 8.2 可信度不使用颜色表达

可信度用边框和角标表达：

| 可信度 | 展示 |
|---|---|
| 有锚事实 | 实线边框 |
| 推导 | 虚线边框 + `~` |
| 推测/无数据 | 红色虚线 + 中文“待证实”占位 |

### 8.3 强制红色条件

```text
无 source/source_excerpt
AI inference only
coverage < 50%
source_review_status = reject
calculation_review_status = fail
conflict_unresolved
high severity audit issue
stale_only but used for current signal
unsupported narrative paragraph
```

### 8.4 强制黄色条件

```text
coverage 50%-65%
single_source_only
forecast_overlay
source_tier = C
unknown veto
medium severity audit issue
stale but used only as structural background
```

---

## 9. PDF 导出标准

### 9.1 原则

PDF 不是另一份报告，而是网页的完整 snapshot：

```text
run_id + data_cutoff + scoring_version + source snapshot + chart snapshot
```

### 9.2 推荐实现

使用 server-side Playwright / Chromium：

```text
POST /api/opportunity/run/<run_id>/export_pdf
        ↓
create export job
        ↓
render /opportunity/run/<run_id>?print=1
        ↓
wait window.__REPORT_READY__ = true
        ↓
convert ECharts to SVG/PNG fallback
        ↓
print CSS expands all required sections
        ↓
save HTML snapshot + PDF + export manifest
```

### 9.3 PDF export job 表

```sql
CREATE TABLE opportunity_pdf_export_job (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    export_scope TEXT NOT NULL, -- full / executive / entity / audit
    status TEXT NOT NULL,       -- queued / running / success / failed
    requested_by TEXT,
    requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    html_snapshot_path TEXT,
    pdf_path TEXT,
    chart_asset_dir TEXT,
    export_manifest_json TEXT,
    error_message TEXT
);
```

### 9.4 Print mode 要求

1. 左侧导航变成目录。
2. 所有必要 details/fold 自动展开。
3. 所有 source hover 变成脚注/尾注。
4. 所有红色/黄色标注保留文本标签，避免黑白打印丢失。
5. ECharts 必须转为静态 SVG/PNG。
6. 每页页眉显示 run name、data cutoff、version。
7. 每页页脚显示 page number 和 disclaimer。
8. 最后附 source index、audit issue、supplement request。

---

## 10. 新增展示层表结构

### 10.1 `opportunity_visual_block`

```sql
CREATE TABLE opportunity_visual_block (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    entity_id INTEGER,
    section_id INTEGER,
    visual_type TEXT NOT NULL,
    title TEXT NOT NULL,
    subtitle TEXT,
    data_query_key TEXT,
    data_json TEXT,
    config_json TEXT,
    source_ids_json TEXT,
    factor_ids_json TEXT,
    event_ids_json TEXT,
    audit_issue_ids_json TEXT,
    print_fallback_type TEXT DEFAULT 'png',
    print_asset_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### 10.2 `opportunity_ui_annotation`

```sql
CREATE TABLE opportunity_ui_annotation (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    entity_id INTEGER,
    target_type TEXT NOT NULL, -- section / visual / factor / slot / event / audit
    target_id INTEGER NOT NULL,
    annotation_type TEXT NOT NULL, -- red_flag / yellow_flag / reviewer_note / tooltip / footnote
    severity TEXT,
    message TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### 10.3 `opportunity_navigation_index`

```sql
CREATE TABLE opportunity_navigation_index (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    entity_id INTEGER,
    anchor_id TEXT NOT NULL,
    title TEXT NOT NULL,
    nav_level INTEGER NOT NULL,
    section_id INTEGER,
    print_order INTEGER,
    include_in_pdf_toc INTEGER DEFAULT 1
);
```

---

## 11. 输出模板：最终报告页面结构示例

```text
[Header]
任务名 / run mode / data cutoff / scoring version / readiness

[Executive KPI]
Top opportunity / average coverage / confidence / audit issues / market state

[Core Answer]
本研究回答什么；结论是什么；结论边界是什么。

[Opportunity Ranking]
材料/环节排序 + 公司承接排序。

[Why]
需求端、供给端、前瞻信号、公司承接、市场反应五个解释块。

[Trace]
点击任意分数 → factor trace → slot trace → source excerpt。

[Events]
未来 12 个月催化剂图谱 + 负向事件 + 澄清事件。

[Audit]
红色问题、黄色问题、低覆盖、冲突、待人工核验。

[Supplement]
还缺什么资料；补了之后会改变什么判断。

[Method]
C 轨 v0.8.1 / v0.9.1 / v1.0 / source ladder / scoring formulas。

[Source Index]
完整来源索引。
```

---

## 12. 审核 Loop 结果

### Review 1：研究者视角

问题：网页是否只是漂亮 dashboard，而没有足够研究解释？  
修正：增加 `opportunity_report_section`，要求每个分析段落入库并绑定 evidence。P8 Top 卡片必须有需求、供给、信号、承接/市场四段解释。

### Review 2：工程师视角

问题：图表如果只在 JS 中临时生成，PDF 和回放无法复现。  
修正：增加 `opportunity_visual_block`，保存 data_json、config_json、print_asset_path；PDF export 保存 HTML snapshot 和 chart assets。

### Review 3：架构师视角

问题：C 轨独立 DB 和 industry_demo 前端合并可能混乱。  
修正：前端合并，DB 独立；A/B 只读参考；C 轨页面通过单独 blueprint / route family 接入。

### Review 4：数据质量视角

问题：没有数据支撑的分析可能被写进正文。  
修正：每个 section 必须有 `support_status` 和 evidence link；`unsupported`、`conflict`、`ai_inference_only` 强制红色，不允许进入 executive thesis。

### Review 5：PDF 输出视角

问题：交互网页导出 PDF 时会丢 hover/source/chart。  
修正：print mode 展开 details，将 source hover 转脚注，将 ECharts 转 PNG/SVG，保留 source index 和 audit appendix。

---

## 13. 最终建议的 MVP 实施顺序

### MVP 1：Run 总览 + Entity 详情

实现：

```text
/opportunity
/opportunity/run/<run_id>
/opportunity/entity/<entity_id>
```

展示：KPI、排序、因子热图、事件账本、审计表。

### MVP 2：Score Trace

实现：

```text
/opportunity/factor/<factor_score_id>
/opportunity/slot/<slot_id>
```

展示：公式、slot、原始数据、source excerpt、预处理、审计状态。

### MVP 3：PDF Export

实现：

```text
POST /api/opportunity/run/<run_id>/export_pdf
/opportunity/export/<job_id>
```

导出：完整 run PDF、source index、audit appendix。

### MVP 4：Review Workflow

实现：

```text
review status
reviewer note
red/yellow annotation
supplement request assignment
```

---

## 14. 结论

C 轨最终输出不应是传统 PDF 报告的网页化版本，而应是：

```text
可解释评分工作台
+ 研究员可读分析正文
+ 证据和计算 trace
+ 事件与审计账本
+ 补资料任务系统
+ 可导出 PDF snapshot
```

最重要的设计约束是：

1. 分析段落必须有 evidence links。
2. 分数必须能展开到 slot 和原始数据。
3. 图表必须可回放、可导出。
4. 覆盖不足、AI 推断、无数据支撑、冲突和过期必须红色显示。
5. 市场反应不修改基本面分，只改变研究优先级。
6. C 轨 DB 独立，A/B 轨只读参考。
7. 网页是主输出，PDF 是网页 snapshot。
