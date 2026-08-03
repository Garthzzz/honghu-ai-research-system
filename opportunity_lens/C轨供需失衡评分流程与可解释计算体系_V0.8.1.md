# C 轨供需失衡机会扫描：评分流程与可解释计算体系 V0.8.1

> **V0.8.1 修订说明**：本版本在 V0.8 基础上接入 `C轨独立DB与开放研究深度补充修订说明_V1.0.md`。评分公式、14 个一级评分因子包、slot 预处理、覆盖率、置信度和事件处理原则不推翻；本次只补充工程前接口约束：C 轨独立 DB、A/B 只读参考、run manifest、版本回放、factor readiness 统计、event 去重、score_limited 输出和 C-Open handoff 接口。


**目标读者**：架构设计师、工程师、Agent 开发者、策略师、行业研究员。  
**上游文档**：`C轨供需失衡机会扫描体系_架构与数据设计_V0.6.md`、`C轨供需失衡评分流程与模型设计_V0.7.md`。  
**本文定位**：在 V0.6 的抓取/入库架构与 V0.7 的评分框架基础上，进一步标准化“每一个数据如何预处理、如何打分、如何进入因子、如何加权、如何处理覆盖率不足、如何处理非数字事件、如何展示完整计算链条”。

---

## 0. 本版核心修订

V0.8 对 V0.7 做了 8 个关键修订：

1. **信息源权重压缩**：可信媒体和最权威来源之间的分值差距不应过大。消息事实本身最重要，来源只影响置信度、是否触发人工复核、是否能支撑高影响事件。除明显低质、无法溯源、野鸡来源外，不应因为“不是公告”而大幅打低。
2. **每个因子都给出 slot 级预处理、归一化和计算原因**：不允许只写“因子 80 分”。参与评分的 slot 必须能看到原始数据、标准化数据、bucket、slot_score、factor_score、调整过程和文字 rationale；`context` slot 只保留事实、口径和不计分说明，不生成或序列化 bucket、slot_score、scoring_rule。
3. **覆盖率不足不再简单开方惩罚**：覆盖率 50%—60% 时仍可以出低置信临时分，但评级必须降级或标注；低于 50% 原则上不出强结论。
4. **预处理标准化**：统一货币、单位、时间、口径、币种、百分比、同比/环比、产能状态、价格品级、股价基准、估值口径。
5. **离群值处理显式化**：先做硬性 sanity check，再做 winsorization/robust z-score/IQR 检查；离群值不默认删除，必须保留 raw value 与处理 trace。
6. **多个数据支撑一个因子，但只产生一次父因子分**：supporting 数据只能确认方向或提高置信度，不能重复加分。
7. **非数字事件单独结构化**：事件先进入 event ledger，按来源、官方确认、方向、严重度、是否重复、是否映射因子处理；预测类和会计类事件不直接进入供需分。
8. **所有分数可解释入库**：每个 slot、factor、composite score 都需要保存 `calculation_trace_json` 和 `rationale_text`。

---

## 1. 评分系统总原则

### 1.1 基本目标

C 轨评分系统回答四个问题：

```text
1. 环节是否真的供需失衡？
2. 公司是否真正能承接这个失衡红利？
3. 市场是否已经充分反应甚至过度反应？
4. 证据质量是否足够支撑结论？
```

最终输出必须同时给出：

```text
segment_imbalance_score
company_capture_score
company_fundamental_score
market_reflection_state
research_priority_score
research_bias_label
coverage_summary
confidence_summary
audit_issue_summary
calculation_trace
```

不要只输出一个裸分。

### 1.2 重要定义

| 概念 | 定义 | 是否直接打分 |
|---|---|---:|
| `source` | 原始来源，如公告、研报、官网、媒体、数据库、纪要 | 否 |
| `industry_data_point` | 最小可信事实原子，有原文、单位、日期、source_id | 否 |
| `metric_slot` | 某个因子需要看的标准化数据槽位 | 评分槽生成 slot_score；context 槽不打分 |
| `factor_bundle` | 一级评分因子包，由多个 slot/event 生成一个父因子分 | 是 |
| `event_ledger` | 非数字文字事件账本 | 仅高可信映射事件影响因子 |
| `composite_score` | 因子加权后的环节分、公司分、总分 | 是 |
| `market_reaction` | 股价、估值、成交、热度构成的市场反应层 | 不改基本面分，只改研究优先级 |

### 1.3 不允许的做法

```text
1. 不允许从 LLM 文本直接跳到分数。
2. 不允许把 AI 摘要、DeepSeek 判断、研报摘要当一手来源。
3. 不允许把多个高度相关的数据重复加分。
4. 不允许用缺失数据当 0 分。
5. 不允许把预测数据当已发生事实。
6. 不允许把市场热度当基本面证据。
7. 不允许输出买入/卖出/仓位建议作为默认结果。
```

---

## 2. 端到端计算链路

### 2.1 完整链路

```text
raw_source
  ↓
source review
  ↓
industry_data_point
  ↓
metric_slot preprocessing
  ↓
score-bearing slot → slot_score
context slot → evidence only（不生成评分字段）
  ↓
factor_bundle aggregation
  ↓
factor_score_raw
  ↓
coverage/confidence/freshness/audit adjustment
  ↓
factor_score_adjusted
  ↓
segment_imbalance_score / company_capture_score
  ↓
company_fundamental_score
  ↓
veto cap / rating status
  ↓
market_reflection_state
  ↓
research_priority_score + research_bias_label
  ↓
viewer/report/API output
```

### 2.2 每一步必须可追溯

每个最终分数必须能展开为：

```text
final score
  ├── composite formula
  ├── factor score list
  │     ├── raw factor score
  │     ├── adjusted factor score
  │     ├── factor coverage
  │     ├── factor confidence
  │     └── factor rationale
  ├── metric slot list
  │     ├── raw value
  │     ├── raw unit
  │     ├── standardized value
  │     ├── standardized unit
  │     ├── bucket
  │     ├── slot_score
  │     ├── source_id
  │     ├── source_excerpt
  │     └── preprocessing trace
  ├── event ledger entries
  ├── veto status
  └── audit issues
```

---

## 3. 信息源权重与来源审阅

### 3.1 核心思想

可信来源之间的权重差距应压缩。只要来源属于可索引、可追溯、有编辑责任或专业口径的可信来源，权重不应差太多；真正需要谨慎的是无法追溯、明显野鸡、单一 KOL、小作文或商业软文。

换句话说：

```text
公告 > 权威数据库 > 可信产业媒体 > 券商研报/纪要 > KOL/自媒体
```

但在数值上：

```text
公告 1.00
权威数据库 0.97
可信产业媒体 0.93
券商研报/纪要 0.86
弱源不入分
```

而不是把可信媒体打成 0.5。消息就是消息，若 Reuters/The Elec/TrendForce/财联社报道一个事实，且无官方否认、无强冲突，就可以作为有效证据，只是对高影响结论需要标注官方确认状态或人工复核。

### 3.2 Source Tier 与权重

| tier | 来源类型 | source_weight | 用法 |
|---|---|---:|---|
| S | 公司公告、交易所文件、年报、季报、招股书、政府公告、监管文件、海关、公司官网正式公告 | 1.00 | 可支撑核心事实和高影响事件 |
| A | WSTS/SIA、SEMI、USGS、官方行业协会、权威数据库、交易所问询回复 | 0.97 | 可支撑行业/周期/原材料/市场数据 |
| B | Reuters、Nikkei、The Elec、TrendForce、Digitimes、财联社等可信媒体/产业数据库 | 0.93 | 可支撑及时事件和价格信号；高影响事件需官方确认状态 |
| C | 券商研报、进门财经纪要、专家访谈、Alpha Pi 摘要结果 | 0.86 | 可补充解释和半结构化数据；高影响结论需交叉验证 |
| D | KOL、微博、雪球、X、小作文、自媒体、无原文转述 | 0.00 或仅展示 | 不进入核心评分；仅作为线索/热度/待核验 |

### 3.3 Source Weight 的使用位置

来源权重**不直接改变事实方向**，只进入 `slot_confidence`。例如同样是“价格上涨 20%”：

```text
source_weight 高 → slot_confidence 高
source_weight 低 → slot_confidence 低，可能只展示
```

如果数据本身可验证、口径清晰、无冲突，S/A/B 的差异不应导致分数大幅不同。

### 3.4 单一可信媒体事件的处理

| 场景 | 处理 |
|---|---|
| 单一 B 级媒体报道价格/供给事件，且无冲突 | 可进入因子，但 event_delta cap = ±5，source_review_status = pass_with_note |
| 两个以上独立 B/A/S 来源一致 | 可正常进入因子，event_delta cap = ±10 |
| B 级媒体报道，但公司公告否认 | 不入分，进入 `official_vs_media_conflict` 审计 |
| C 级纪要提到高影响事件 | 默认展示，除非有 S/A/B 交叉验证 |
| D 级来源 | 不入分，只作为线索和市场热度 |

### 3.5 来源独立性

多来源不等于多独立来源。需要识别同源转载、新闻聚合、研报互相引用。

```text
independent_source_count = 去重后的独立来源数量
source_count = 所有来源数量
```

置信度使用 `independent_source_count`，不是 `source_count`。

---

## 4. 数据预处理标准

所有 slot_score 之前必须完成预处理。预处理输出写入 `preprocess_trace_json`。

### 4.1 单位标准化

| 类型 | 原始可能单位 | 标准单位 | 规则 |
|---|---|---|---|
| 价格 | 元/吨、万元/吨、美元/kg、日元/kg | 默认 `CNY/ton`，同时保留 `USD/kg` | 用 run 截止日或数据日期 FX；保留税前/税后标记 |
| 产能 | 吨/年、kg/月、片/月、万片/月 | 行业指定标准单位 | 必须记录 `capacity_basis`：nominal/effective/under_construction/planned |
| 收入 | 元、万元、亿元、美元、日元、韩元 | CNY million 和原币双存 | 用期间平均汇率或期末汇率，标记方法 |
| 估值 | PE、PB、PS、EV/EBITDA | 原单位 | PE 对亏损公司置空，不使用负 PE |
| 增速 | %、pct、倍数 | decimal 或 pct 统一 | 区分 `percent_change` 和 `percentage_point_change` |
| 市占率 | % | decimal/pct 统一 | 必须标明全球/中国/客户/产品口径 |
| 股价 | 本币 | 本币 + CNY/USD 辅助 | 计算收益率不需币种换算 |

### 4.2 货币换算

每条换算需要保存：

```text
raw_currency
standard_currency
fx_rate
fx_rate_date
fx_source_id
fx_method = spot / period_average / period_end
```

规则：

```text
1. 价格快照用 as_of_date 的 spot FX。
2. 财务期间数据用 period_average FX；若不可得，用 period_end 并标注。
3. 历史估值和股价收益率一般不需要跨币种换算。
4. 跨国家公司市值对比必须统一成 CNY 或 USD。
```

### 4.3 时间口径标准化

所有数据必须有：

```text
period          # 财务/区间数据，如 2026Q1、2026H1、LTM
as_of_date      # 事件/价格/市场数据日期
window          # 1D/20D/60D/120D/3M/YoY 等
```

规则：

```text
1. 价格、新闻、事件、股价用 as_of_date。
2. 财务、CapEx、收入、利润用 period。
3. 若一个数据只有发布日期但无数据期间，period = publication_period_unknown，必须低置信。
4. 不同期间不能直接比较；必须生成 normalized_period。
```

### 4.4 百分比与百分点

必须区分：

```text
margin_change_pct       # 相对变化，例如毛利率从 20% 到 24%，变化 +20%
margin_change_pp        # 百分点变化，例如 20% 到 24%，变化 +4pct
revenue_growth_pct      # 收入增长率
market_share_pp_change  # 市占率百分点变化
```

### 4.5 价格品级和产品规格

材料价格必须记录：

```text
product_grade
purity
package_type
region
quote_type = spot / contract / export_avg / tender / official_revision / media_quote
```

不同品级价格不可直接混合。例如 5N/6N WF6、不同 ArF/ArFi 光刻胶、不同低 α 填料必须分开。若无法确认品级：

```text
value_status = available_with_grade_unknown
score_cap = 70
confidence 降低
```

### 4.6 产能口径

产能必须拆口径：

```text
existing_effective_capacity
nominal_capacity
under_construction_capacity
trial_production_capacity
ramping_capacity
planned_capacity
rumored_capacity
```

进入 `capacity_event_12m` 的只包括：

```text
existing_effective
under_construction with confirmed commissioning date
trial_production
ramping
mass_production
```

不进入核心产能计算：

```text
planned_only
rumored
unclear_status
```

### 4.7 事实、预测和观点分离

| 类型 | 示例 | 能否进入核心分 |
|---|---|---:|
| actual_fact | 已披露产能、已公告合同、已发生价格 | 是 |
| management_guidance | 公司指引、业绩会展望 | 低权重或预测层 |
| analyst_forecast | 卖方预测、一致预期 | 不作事实，只作为 forecast_overlay |
| media_reported_event | 媒体报道事件 | 可信媒体可进入，但需 source review |
| rumor | 小作文、KOL 传闻 | 不进入核心分 |

---

## 5. 离群值与异常值处理

### 5.1 三层离群处理

#### 第一层：硬性 sanity range

每个 slot 定义合理区间。超出后不直接删除，先标记：

```text
sanity_status = pass / warning / fail
```

示例：

| 数据 | warning | fail |
|---|---|---|
| 月度价格涨幅 | >100% | >300% 且无事件支撑 |
| PE | >300x | >1000x 或净利润为负仍给 PE |
| 产能新增比例 | >100% | >500% 且无公告 |
| 毛利率 | >80% | >100% 或 < -50% |
| 经营现金流/净利润 | >300% | >1000% 且无一次性解释 |

#### 第二层：统计离群检测

当同类样本数足够时使用：

```text
robust_z = (x - median) / IQR
IQR rule: outside Q1 - 1.5*IQR or Q3 + 1.5*IQR = potential_outlier
outside Q1 - 3*IQR or Q3 + 3*IQR = probable_outlier
```

处理原则：

```text
1. 离群值不自动删除。
2. 若有高可信事件支撑，可保留并说明。
3. 若无事件支撑，winsorize 到规则上限，同时保留 raw_value。
4. 所有处理写入 preprocess_trace_json。
```

#### 第三层：来源冲突检测

如果同一指标不同来源差异过大：

```text
source_conflict_status = conflict_unresolved
slot_score = neutral 50 或 blocked
human_review_required = true
```

### 5.2 Winsorization 规则

当数据需要进入连续评分但存在极端值时，采用规则型 winsorization：

```text
winsorized_value = min(max(raw_value, lower_cap), upper_cap)
```

注意：

```text
raw_value 必须保留。
winsorized_value 只用于打分。
trace 中必须说明 cap 原因。
```

### 5.3 常见变量 caps

| 变量 | 下限 | 上限 | 说明 |
|---|---:|---:|---|
| 下游价格 3M 变化 | -50% | +100% | 极端涨跌需事件支撑 |
| 材料价格 3M 变化 | -50% | +150% | 资源/政策型材料可更宽 |
| 收入 YoY | -80% | +300% | 小基数公司需标注 |
| 净利润 YoY | -300% | +500% | 若基数接近 0，改用绝对利润和 margin |
| 毛利率 | -20% | +80% | 超出需人工复核 |
| 产能新增比例 | 0% | +200% | >50% 可能触发 veto candidate |
| PE | 0 | 300 | 亏损公司 PE 不适用 |
| PS | 0 | 100 | 高成长小市值需标注 |

---

## 6. 覆盖率不足的处理

### 6.1 覆盖率定义

覆盖率不是“找到几个数字”，而是按 slot 权重计算：

```text
factor_coverage = usable_slot_weight / applicable_slot_weight
```

其中：

```text
usable_slot = available / calculated / stale_but_usable
not usable = not_found / not_disclosed / weak_source_only / conflict_unresolved
not_applicable = 经人工确认后从 denominator 中剔除
```

### 6.2 覆盖率分层

| factor_coverage | 状态 | 处理 |
|---:|---|---|
| >= 0.80 | high_coverage | 正常打分 |
| 0.65 - 0.80 | medium_coverage | 正常打分但标注 |
| 0.50 - 0.65 | low_coverage | 可出临时分，但向 50 收敛；评级 cap |
| < 0.50 | insufficient_coverage | 不出强分，factor_score_adjusted = 50，标证据不足 |

### 6.3 覆盖率对分数的影响

采用“向中性收敛”，不是扣分：

```text
coverage_multiplier =
  1.00 if coverage >= 0.80
  0.85 if 0.65 <= coverage < 0.80
  0.60 if 0.50 <= coverage < 0.65
  0.00 if coverage < 0.50
```

因子调整：

```text
factor_score_after_coverage = 50 + (factor_score_raw - 50) * coverage_multiplier
```

含义：

```text
raw 90, coverage 0.85 → adjusted 90
raw 90, coverage 0.70 → adjusted 84
raw 90, coverage 0.55 → adjusted 74
raw 90, coverage 0.45 → adjusted 50，证据不足
```

### 6.4 覆盖率不足对评级的限制

| 覆盖率状态 | 评级限制 |
|---|---|
| segment_coverage < 0.50 | 环节不评级，输出 `unrated_insufficient_evidence` |
| 0.50 <= segment_coverage < 0.60 | 环节评级最高 B，不得 S/A |
| company_coverage < 0.50 | 公司承接分不评级 |
| 0.50 <= company_coverage < 0.60 | 公司基本面机会最高 B，且 bias 不得高于 `neutral_watch` |
| overall_coverage < 0.60 | 最终必须标 `provisional` |
| overall_coverage < 0.50 | 最终输出 `unrated_insufficient_evidence` |

### 6.5 为什么这样处理

覆盖率不足时，系统不能假设未知项都是好，也不能假设未知项都是坏。最稳妥方式是：

```text
不确定性越高，越向中性 50 收敛。
```

这样可以避免“只抓到两个利好就给 S 分”的偏差。

---

## 7. 置信度计算

### 7.1 Slot Confidence

```text
slot_confidence =
  source_weight
  * freshness_weight
  * consistency_weight
  * extraction_quality_weight
  * preprocessing_quality_weight
```

每项范围 0-1。

| 项 | 说明 |
|---|---|
| `source_weight` | 来源可信度，S=1.00/A=0.97/B=0.93/C=0.86/D=0 |
| `freshness_weight` | 数据新鲜度 |
| `consistency_weight` | 多源一致性，无冲突为 1，有冲突降到 0.5 以下 |
| `extraction_quality_weight` | 是否从原文精确抽取，是否 OCR，是否转述 |
| `preprocessing_quality_weight` | 单位、口径、时间、币种是否明确 |

### 7.2 Freshness Weight

不同数据 TTL 不同：

| 数据类型 | TTL |
|---|---:|
| 价格、事件、股价、成交、新闻 | 30 天 |
| 月度行业数据、海关、WSTS/SIA、SEMI | 60 天 |
| 季度财务、CapEx、业绩会 | 120 天 |
| 年度/结构性数据，如扩产周期、供应商结构 | 365 天 |
| 预测数据 | 到下一次业绩/指引更新；标 forecast |

```text
freshness_ratio = freshness_days / ttl
freshness_weight =
  1.00 if ratio <= 1.0
  0.75 if 1.0 < ratio <= 1.5
  0.50 if 1.5 < ratio <= 2.0
  0.25 if ratio > 2.0
```

### 7.3 Factor Confidence

```text
factor_confidence = weighted_avg(slot_confidence, slot_weight)
```

若有 unresolved conflict：

```text
factor_confidence = min(factor_confidence, 0.55)
human_review_required = true
```

### 7.4 置信度对分数的影响

和覆盖率一样，置信度采用向 50 收敛：

```text
confidence_multiplier =
  1.00 if confidence >= 0.85
  0.90 if 0.75 <= confidence < 0.85
  0.75 if 0.60 <= confidence < 0.75
  0.50 if 0.45 <= confidence < 0.60
  0.00 if confidence < 0.45
```

最终因子调整：

```text
factor_reliability_multiplier = min(coverage_multiplier, confidence_multiplier, audit_multiplier)

factor_score_adjusted =
  50 + (factor_score_raw - 50) * factor_reliability_multiplier
```

用 `min` 而不是乘法，避免过度惩罚。低覆盖和中等置信已经标注，不应把所有分数都压成 50；但如果任一项极差，就不允许强结论。

---

## 8. Slot 到 Factor 的聚合原则

### 8.1 Slot Role

每个因子下面的 slot 分为：

| role | 作用 | 是否能决定方向 |
|---|---|---:|
| `primary` | 主信号 | 是 |
| `supporting` | 支撑信号 | 只能小幅修正和提高置信度 |
| `contradiction` | 反证信号 | 降低分数或置信度 |
| `context` | 背景信息 | 不打分 |

`context` 只用于解释背景事实及口径，不进入因子分数、覆盖率或置信度。活动 V2 pack 中此类槽不得出现 `bucket`、`slot_score` 或 `scoring_rule` 字段；必须用 `scoring_trace` 明确说明“不计分”，避免空值字段被误读为一次评分。

### 8.2 通用公式

```text
factor_score_raw =
  primary_component
  + support_adjustment
  + event_adjustment
  - contradiction_penalty
```

约束：

```text
support_adjustment ∈ [-8, +8]
event_adjustment ∈ [-10, +10]
contradiction_penalty ∈ [0, 20]
factor_score_raw ∈ [0, 100]
```

### 8.3 主信号缺失时

| 情况 | 处理 |
|---|---|
| 主信号缺失，但两个以上高质量 supporting 一致 | `factor_score_raw = min(avg_supporting_score, 65)`，不得给高分 |
| 主信号缺失，只有单一 supporting | `factor_score_raw = 50`，仅展示 |
| 主信号冲突未解决 | `factor_score_raw = 50`，触发 review |
| 主信号不适用且经人工确认 | 从 applicable weight 中剔除 |

### 8.4 防重复计分规则

如果事件已经映射到某个 slot，不得再额外加事件分：

```text
if event.maps_to_slot and slot_score_uses_event:
    event_adjustment = 0
    event.score_effect = mapped_only
```

例如：官方调价公告已经进入 `signal.material_price_momentum`，不能在事件账本再额外 +5。

---

## 9. 14 个一级评分因子包：slot、预处理、打分规则

> 说明：以下 `slot_weight` 是因子内部权重，不是最终总分权重。每个因子最终只生成一个父因子分。

---

### 9.1 `demand.downstream_price_momentum`

**问题**：下游产品价格是否已经上涨，从而证明需求强度或供需紧张？

| slot_code | role | weight | 数据内容 | 标准化 |
|---|---|---:|---|---|
| `downstream_price_3m_change` | primary | 0.45 | 下游产品 3M 价格变化 | pct |
| `downstream_price_1m_change` | supporting | 0.20 | 下游产品 1M 价格变化 | pct |
| `downstream_price_yoy_change` | supporting | 0.20 | 下游产品 YoY 价格变化 | pct |
| `price_source_quality` | context | 0.05 | 价格来源类型 | contract/spot/index |
| `price_reversal_signal` | contradiction | 0.10 | 价格回落或客户砍价 | event/bucket |

**预处理**：

```text
1. 统一为 percentage change。
2. 价格序列必须同品类、同口径；不能混现货和合约，除非明确标 quote_type。
3. 3M 变化优先；无 3M 用 1M + YoY 支撑，但因子 cap 70。
4. 对 3M change winsorize 到 [-50%, +100%]。
```

**3M 变化打分**：

| 3M 价格变化 | slot_score |
|---:|---:|
| >= +30% | 100 |
| +15% ~ +30% | 85 |
| +5% ~ +15% | 70 |
| -5% ~ +5% | 50 |
| -15% ~ -5% | 35 |
| < -15% | 20 |

**反证处理**：若最近 1M 已经转负，且 3M 为正：

```text
contradiction_penalty = 5-15
factor rationale 必须写“3M 仍强但边际转弱”
```

---

### 9.2 `demand.customer_capex_capacity_signal`

**问题**：下游客户是否正在扩产或增加资本开支？

| slot_code | role | weight | 数据内容 | 标准化 |
|---|---|---:|---|---|
| `customer_capex_yoy_or_guidance` | primary | 0.35 | 下游客户 CapEx YoY 或指引变化 | pct/bucket |
| `confirmed_capacity_expansion_event` | primary | 0.30 | 新厂、扩线、封装厂、设备采购事件 | event/bucket |
| `equipment_order_or_billings_proxy` | supporting | 0.20 | SEMI billings、设备订单等代理 | pct |
| `customer_delay_or_cut_event` | contradiction | 0.15 | 推迟扩产、削减 CapEx | event/bucket |

**预处理**：

```text
1. CapEx 统一为 YoY 或 guidance change。
2. 多客户时按目标应用权重加权，例如 HBM/DRAM/NAND 对应客户权重不同。
3. 若只有行业设备 billings，无客户级数据，因子 cap 75。
```

**CapEx/扩产信号打分**：

| 信号 | slot_score |
|---|---:|
| 重大扩产确认，或 CapEx +25% 以上 | 90-100 |
| 扩产确认，或 CapEx +10% ~ +25% | 75-85 |
| 稳定扩产，CapEx -10% ~ +10% | 50-65 |
| 推迟扩产，CapEx -10% ~ -25% | 35-45 |
| 明确削减/取消扩产 | 10-30 |

---

### 9.3 `demand.output_consumption_proxy`

**问题**：下游实际产出或消耗是否增长？

| slot_code | role | weight | 数据内容 |
|---|---|---:|---|
| `output_or_shipment_growth_3m` | primary | 0.40 | wafer input、bit shipment、终端出货、产量 |
| `industry_sales_growth` | supporting | 0.25 | WSTS/SIA、行业销售 |
| `utilization_rate_signal` | supporting | 0.20 | 客户产能利用率、开工率 |
| `inventory_destocking_signal` | contradiction | 0.15 | 下游去库存或产出转弱 |

**打分**：

| 增长/消耗代理 | slot_score |
|---|---:|
| >= +25% | 90 |
| +10% ~ +25% | 75 |
| 0 ~ +10% | 60 |
| -10% ~ 0 | 45 |
| < -10% | 25 |

**特殊情况**：若行业销售增长来自 ASP 上升而非出货量增长，需降 `output_consumption_proxy` 置信度，避免与价格动量重复。

---

### 9.4 `demand.application_intensity_change`

**问题**：技术路线是否提高单位材料/工序消耗强度？

| slot_code | role | weight | 数据内容 |
|---|---|---:|---|
| `technology_generation_shift` | primary | 0.40 | HBM 堆叠、NAND 层数、先进封装、工艺节点 |
| `material_intensity_proxy` | primary | 0.30 | 单位用量、工序次数、关键材料消耗强度 |
| `customer_mix_shift` | supporting | 0.20 | 高端产品占比提升 |
| `process_reduction_or_substitution` | contradiction | 0.10 | 工艺简化、材料替代导致用量下降 |

**分档打分**：

| 强度变化 | slot_score |
|---|---:|
| 明确 step-change，单位用量/工序显著提升 | 90 |
| 结构性提升但缺少精确量化 | 75 |
| 温和提升 | 60 |
| 无明显变化 | 50 |
| 工艺替代导致用量下降 | 25-40 |

**不抓精确 BOM 占比**：精确 BOM 占比作为 `ref.bom_share_exact` 展示，不进入核心分。

---

### 9.5 `supply.capacity_event_12m`

**问题**：未来 12 个月供给是变紧、稳定、缓解，还是产能洪水？

| slot_code | role | weight | 数据内容 |
|---|---|---:|---|
| `capacity_addition_12m_pct` | primary | 0.35 | 未来 12M 有效新增产能 / 当前有效产能 |
| `current_effective_capacity` | supporting | 0.15 | 当前有效产能 |
| `confirmed_shutdown_or_disruption` | primary/supporting | 0.25 | 停产、限产、断供、事故、复产 |
| `ramp_delay_or_cancel_event` | supporting | 0.15 | 延期、取消、爬坡不及预期 |
| `planned_or_rumored_capacity` | context | 0.10 | 规划/传闻产能，仅展示 |

**预处理**：

```text
1. 只使用 effective/under_construction/trial/ramping/mass_production。
2. planned_only 和 rumored 不进入 capacity_addition_12m_pct。
3. 产能单位统一。
4. 若当前有效产能不明，新增比例不能计算，因子 cap 65。
```

**新增产能比例打分**：

| 12M 有效新增产能 / 当前有效产能 | slot_score | 说明 |
|---:|---:|---|
| <= 10% | 85 | 供给难缓解 |
| 10% ~ 25% | 70 | 轻微缓解 |
| 25% ~ 50% | 50 | 明显缓解 |
| > 50% | 20 | 产能洪水候选 |

**供给扰动加分**：

| 扰动事件 | adjustment |
|---|---:|
| 官方确认停产/限供，影响 >10% 有效供给 | +10 |
| 可信媒体多源报道限供，无官方否认 | +5 |
| 单一媒体报道 | +3 且标注 |
| 公司否认 | 不加，触发冲突审计 |

---

### 9.6 `supply.expansion_cycle_bucket`

**问题**：供给扩张需要多长时间？

| slot_code | role | weight | 数据内容 |
|---|---|---:|---|
| `expansion_cycle_months_or_bucket` | primary | 0.50 | 从立项到可用产能的周期 |
| `equipment_lead_time_bucket` | supporting | 0.20 | 关键设备交付周期 |
| `qualification_or_ramp_cycle_bucket` | supporting | 0.20 | 客户验证/爬坡周期 |
| `fast_modular_expansion_signal` | contradiction | 0.10 | 是否可快速复制扩产 |

**打分**：

| 扩产周期 | slot_score |
|---|---:|
| >36m | 95 |
| 24-36m | 85 |
| 12-24m | 65 |
| 6-12m | 45 |
| <6m | 25 |

**规则**：若只有研报泛称“扩产周期长”，无区间，默认 `value_status=available_text_only`，score cap 75。

---

### 9.7 `supply.raw_policy_constraint`

**问题**：原材料或政策是否形成真实供给约束？

| slot_code | role | weight | 数据内容 |
|---|---|---:|---|
| `raw_material_supply_concentration` | primary | 0.30 | 原料产地/供应集中度 |
| `export_import_control_event` | primary | 0.30 | 出口管制、许可、制裁 |
| `raw_material_price_momentum` | supporting | 0.20 | 原材料价格变化 |
| `policy_direction_for_entity` | supporting/contradiction | 0.20 | 对该公司/环节是正向还是负向 |

**打分**：

| 状态 | score |
|---|---:|
| 官方政策/原料约束显著限制竞争对手供给，且公司可受益 | 90 |
| 存在明确原料/政策约束，但方向需区分 | 70 |
| 有原料集中但暂无政策/价格压力 | 55 |
| 无明显约束 | 50 |
| 政策导致公司自身市场关闭或原料断供 | 20 或触发 veto |

**方向规则**：同一出口管制对不同公司方向可能相反，必须保存 `direction_for_entity`。

---

### 9.8 `supply.supplier_structure_bucket`

**问题**：供应格局是否集中、有效供应商是否少、切换是否难？

| slot_code | role | weight | 数据内容 |
|---|---|---:|---|
| `supplier_structure_bucket` | primary | 0.40 | fragmented/moderate/oligopoly/near_monopoly |
| `cr3_calculated` | supporting | 0.20 | Top3 复算 |
| `effective_supplier_count` | supporting | 0.20 | 全球/客户有效供应商数 |
| `qualification_bottleneck_text` | supporting | 0.10 | 认证、合格供应商、切换成本 |
| `cr3_gap_or_definition_conflict` | contradiction | 0.10 | CR3 加总或口径冲突 |

**结构 bucket 打分**：

| bucket | score |
|---|---:|
| near_monopoly | 95 |
| oligopoly | 80 |
| moderately_concentrated | 60 |
| fragmented | 35 |
| unknown | 50 |

**CR3 参考规则**：

| CR3 | 参考 bucket |
|---:|---|
| >= 85% | near_monopoly / oligopoly |
| 70% ~ 85% | oligopoly |
| 40% ~ 70% | moderately_concentrated |
| <40% | fragmented |

**强制审计**：如果 `cr3_claimed` 与 `cr3_calculated` 差异 >5pct：

```text
calculation_review_status = warning/fail
factor_confidence <= 0.65
rationale 必须说明使用分档而非裸 CR3
```

---

### 9.9 `supply.substitution_barrier`

**问题**：目标材料/环节是否容易被替代？

| slot_code | role | weight | 数据内容 |
|---|---|---:|---|
| `process_criticality_bucket` | primary | 0.35 | 必经/重要/普通 |
| `commercial_alternative_status` | primary | 0.35 | 无替代/有限/部分/成熟 |
| `switching_validation_burden` | supporting | 0.20 | 重新验证/流片/客户风险 |
| `substitution_event` | contradiction | 0.10 | 替代技术商业化事件 |

**打分**：

| 替代状态 | score |
|---|---:|
| 无商业替代，且是必经工艺 | 90 |
| 有有限替代但切换成本高 | 75 |
| 部分替代可行 | 55 |
| 商业替代成熟 | 30 |
| 替代已商业化且快速扩散 | 10 或 veto |

---

### 9.10 `signal.material_price_momentum`

**问题**：目标材料自身价格是否已经上涨？

| slot_code | role | weight | 数据内容 |
|---|---|---:|---|
| `material_price_3m_change` | primary | 0.40 | 材料 3M 价格变化 |
| `material_price_1m_change` | supporting | 0.15 | 材料 1M 价格变化 |
| `material_price_yoy_change` | supporting | 0.15 | 材料 YoY 价格变化 |
| `customs_or_trade_price_proxy` | supporting | 0.15 | 海关均价/进出口价格 |
| `official_price_revision_event` | supporting/event | 0.10 | 官方调价公告 |
| `price_denial_or_reversal` | contradiction | 0.05 | 公司否认涨价/价格回落 |

**预处理**：

```text
1. 不称为 ASP，统一称 price_proxy。
2. 必须标 product_grade/purity/quote_type。
3. 同一品级才能计算环比/同比。
4. 若品级不明，score cap 70。
5. winsorize 3M change 到 [-50%, +150%]，异常必须有事件解释。
```

**打分**：

| 3M 价格变化 | score |
|---:|---:|
| >= +50% | 100 |
| +25% ~ +50% | 90 |
| +10% ~ +25% | 75 |
| 0 ~ +10% | 60 |
| -10% ~ 0 | 45 |
| < -10% | 25 |

---

### 9.11 `company.exposure_directness`

**问题**：公司是否真的能承接该环节，而不是主题映射？

| slot_code | role | weight | 数据内容 |
|---|---|---:|---|
| `supply_relationship_status` | primary | 0.45 | 直接供货、小批量、验证、间接、主题 |
| `customer_named_or_unnamed` | supporting | 0.15 | 是否披露客户名称 |
| `product_customer_match` | supporting | 0.20 | 产品是否与目标环节一致 |
| `mass_production_status` | supporting | 0.15 | 是否量产/批量供货 |
| `relationship_denial_or_unclear` | contradiction | 0.05 | 公司否认/关系不清 |

**分档打分**：

| 状态 | score | company_score_cap |
|---|---:|---:|
| direct_mass_supply | 95 | 100 |
| direct_small_batch | 80 | 90 |
| qualified_testing | 65 | 80 |
| indirect_supply | 55 | 70 |
| upstream_beneficiary | 45 | 65 |
| theme_mapping_only | 25 | 45 |
| unverified | 20 | 40 |

**规则**：该因子同时生成 `company_score_cap`，防止主题映射公司因行业强而拿高分。

---

### 9.12 `company.revenue_exposure_proxy`

**问题**：相关产品/业务对公司收入或利润贡献有多大？

| slot_code | role | weight | 数据内容 |
|---|---|---:|---|
| `product_revenue_share` | primary | 0.40 | 产品级收入占比 |
| `segment_revenue_share` | primary/supporting | 0.30 | 业务分部收入占比 |
| `gross_profit_exposure_proxy` | supporting | 0.15 | 相关业务毛利贡献 |
| `textual_exposure_disclosure` | supporting | 0.10 | 文本披露的敞口 |
| `exposure_too_small_or_unclear` | contradiction | 0.05 | 敞口极小或不可证实 |

**打分**：

| 收入敞口 | score |
|---|---:|
| 产品级收入 >30% | 90 |
| 产品级收入 15%-30% | 75 |
| 产品级收入 5%-15% | 60 |
| 产品级收入 <5% | 40 |
| 只有分部收入，无法拆产品 | cap 75 |
| 只有文字披露 | cap 60 |
| 仅主题映射 | 20-30 |

---

### 9.13 `company.capacity_readiness_window`

**问题**：公司有没有产能在机会窗口内兑现？

| slot_code | role | weight | 数据内容 |
|---|---|---:|---|
| `current_available_capacity` | primary | 0.30 | 现有可用产能 |
| `capacity_available_within_12m` | primary | 0.35 | 12M 内可释放产能 |
| `ramp_status` | supporting | 0.15 | 试产、爬坡、达产 |
| `capacity_delay_event` | contradiction | 0.10 | 延期、取消、爬坡差 |
| `capacity_customer_match` | supporting | 0.10 | 产能是否对应目标产品/客户 |

**打分**：

| 状态 | score |
|---|---:|
| 现有产能充足且目标产品已量产 | 90 |
| 12M 内明确爬坡/达产 | 75 |
| 12M 内试产，量产不确定 | 60 |
| 只有规划，>12M | 40 |
| 无产能或产能不匹配 | 25 |

---

### 9.14 `company.financial_capture_quality`

**问题**：公司能否把行业景气转化为利润和现金流？

| slot_code | role | internal_weight | 数据内容 |
|---|---|---:|---|
| `relevant_margin_trend` | primary | 0.30 | 分部/公司毛利率及变化 |
| `revenue_profit_growth` | primary | 0.25 | 收入、利润、扣非增长 |
| `cash_conversion_quality` | primary | 0.20 | OCF/净利润、FCF proxy |
| `working_capital_risk` | contradiction | 0.15 | 应收、存货、预付异常 |
| `capex_depreciation_burden` | contradiction/context | 0.10 | CapEx、折旧、费用压力 |

**预处理**：

```text
1. 财务数据统一为季度/TTM。
2. 净利润 YoY 对小基数极敏感，若基数接近 0，改用利润率和绝对利润。
3. 亏损公司 PE 不使用，财务质量可用毛利率、现金流、亏损收窄。
4. 存货/应收需要行业相对分位，不同商业模式不可混比。
```

**子项打分建议**：

| 子项 | 高分 | 中性 | 低分 |
|---|---|---|---|
| 毛利率趋势 | 高于行业且上行 | 稳定 | 连续下滑 |
| 收入利润增长 | 收入和扣非同步强增长 | 温和增长 | 收入增长但利润/扣非弱 |
| 现金流 | OCF/净利 >80% | 30%-80% | OCF 长期显著低于利润 |
| 应收/存货 | 周转稳定 | 轻微恶化 | 明显恶化且无扩产解释 |
| CapEx/折旧 | 支撑成长 | 中性 | 折旧/费用压制盈利 |

**总分**：

```text
financial_capture_quality_score =
  0.30 * margin_score
+ 0.25 * growth_score
+ 0.20 * cash_score
+ 0.15 * working_capital_score
+ 0.10 * capex_burden_score
```

---

## 10. Composite Score：因子权重与含义

### 10.1 环节失衡分

环节失衡分只使用需求、供给、材料前瞻信号，不使用公司财务。

```text
segment_imbalance_score_raw =
  0.30 * demand_component
+ 0.50 * supply_component
+ 0.20 * signal_component
```

#### 因子权重

| 因子 | 权重 | 设计原因 |
|---|---:|---|
| `demand.downstream_price_momentum` | 7 | 下游需求价格信号，更新快 |
| `demand.customer_capex_capacity_signal` | 8 | 客户扩产是需求触发核心 |
| `demand.output_consumption_proxy` | 7 | 验证真实消耗 |
| `demand.application_intensity_change` | 8 | 技术路线带来结构需求 |
| `supply.capacity_event_12m` | 12 | 直接决定未来 12M 供给变化 |
| `supply.expansion_cycle_bucket` | 8 | 决定供给响应速度 |
| `supply.raw_policy_constraint` | 10 | 原料/政策卡脖子通常是强约束 |
| `supply.supplier_structure_bucket` | 10 | 供应集中和切换壁垒 |
| `supply.substitution_barrier` | 10 | 决定紧缺能否持续 |
| `signal.material_price_momentum` | 20 | 目标材料自身价格是最直接前瞻信号 |
| **合计** | **100** |  |

### 10.2 公司承接分

```text
company_capture_score_raw =
  0.35 * exposure_directness
+ 0.25 * revenue_exposure_proxy
+ 0.20 * capacity_readiness_window
+ 0.20 * financial_capture_quality
```

| 因子 | 权重 | 含义 |
|---|---:|---|
| `company.exposure_directness` | 35 | 是否真实参与，而不是蹭主题 |
| `company.revenue_exposure_proxy` | 25 | 受益弹性大小 |
| `company.capacity_readiness_window` | 20 | 能否在窗口期兑现 |
| `company.financial_capture_quality` | 20 | 能否转为利润和现金流 |

### 10.3 公司基本面机会分

```text
company_fundamental_score_raw =
  0.65 * segment_imbalance_score_raw
+ 0.35 * company_capture_score_raw
```

然后应用敞口上限：

```text
company_fundamental_score_capped =
  min(company_fundamental_score_raw, company_score_cap)
```

最后质量调整：

```text
overall_multiplier = min(overall_coverage_multiplier, overall_confidence_multiplier, audit_multiplier)

company_fundamental_score_adjusted =
  50 + (company_fundamental_score_capped - 50) * overall_multiplier
```

### 10.4 为什么公司承接只占 35%

C 轨的核心是“供需失衡机会”。如果环节不失衡，公司再强也不是 C 轨要找的机会。公司承接占 35% 是为了判断“谁能吃到红利”，但不让普通好公司因为财务质量好而掩盖环节不紧缺。

### 10.5 权重上限检查

为了防止单一输入过度影响：

```text
1. 任一一级因子对 company_fundamental_score 的最大理论影响不得超过 20 分。
2. 任一 metric slot 不得直接影响最终分超过 12 分。
3. 任一事件 event_delta 不得直接影响最终分超过 5 分，除非进入 veto。
4. 市场反应不改变基本面分。
5. 财务质量最多影响 company_capture_score 的 20%，约等于最终分 7%。
```

---

## 11. Market Reaction：市场反应与研究优先级

市场反应不改变基本面分，只用于回答：

```text
这个机会是否已经被交易？现在研究优先级高不高？
```

### 11.1 因子

| 因子 | 数据 | 预处理 | 输出 |
|---|---|---|---|
| `market.excess_return_vector` | 20D/60D/120D 超额收益 | 相对行业/基准指数 | 是否已上涨 |
| `market.valuation_crowding` | PE/PB/PS/EV/EBITDA 分位 | 亏损公司不用 PE | 是否估值拥挤 |
| `market.attention_heat` | 成交、新闻、KOL、舆情热度 | robust z-score | 是否被关注 |
| `market.reflection_state` | 计算枚举 | 综合前三项 | 市场状态 |

### 11.2 状态规则

| reflection_state | 典型条件 | multiplier |
|---|---|---:|
| `unnoticed` | 基本面高，20/60D 超额低，热度低，估值不高 | 1.10 |
| `early_reaction` | 股价或热度刚启动，估值未极端 | 1.00 |
| `recognized` | 股价/估值/热度已有明显反应 | 0.80 |
| `crowded` | 超额收益、换手、新闻/KOL 热度均高 | 0.55 |
| `overheated` | 极端上涨且基本面新增证据不足 | 0.30 |
| `post_hype_reset` | 热度回落但基本面仍在 | 0.85 |

### 11.3 研究优先级

```text
research_priority_score =
  company_fundamental_score_adjusted
  * market_window_multiplier
  * audit_multiplier
```

市场反应层会改变排序，但不会把基本面分改高或改低。

---

## 12. 一票否决与 Rating Cap

### 12.1 五个否决项

| veto_code | 含义 |
|---|---|
| `veto.tech_substitution` | 颠覆性替代商业化 |
| `veto.capacity_flood` | 6-12M 内 >50% 有效新增产能且会压制价格 |
| `veto.imbalance_too_short` | 失衡持续不足、无法确认持续性 |
| `veto.customer_backup_selfdev` | 核心客户备份/自研替代 |
| `veto.policy_market_shutdown` | 政策/管制导致主要市场关闭 |

### 12.2 状态处理

| 状态 | 处理 |
|---|---|
| `safe` | 无影响 |
| `unknown` | 不扣分，但降低 `veto_confidence`，报告标注 |
| `warning` | 最终 rating cap = B，bias 最高 `neutral_watch` |
| `triggered` | final rating = F 或 score cap 49，需人工复核 |

### 12.3 触发来源要求

| 来源 | 可否触发 hard veto |
|---|---:|
| S/A 来源明确 | 可以 |
| 多个独立 B 来源一致 | 可以触发 `warning`，人工确认后可 triggered |
| 单一 B 来源 | 只能 warning |
| C 来源 | 展示/待核验 |
| D 来源 | 不触发 |

---

## 13. 非数字事件处理

### 13.1 事件分类

| event_type | 类别 | 默认处理 |
|---|---|---|
| `price_revision` | 调价公告 | 映射价格因子，不重复加分 |
| `capacity_change` | 投产、爬坡、延期、取消 | 映射产能因子 |
| `supply_disruption` | 限供、停产、事故、断供 | 映射供给/价格因子 |
| `policy_control` | 出口管制、制裁、许可 | 映射政策约束或 veto |
| `customer_validation` | 客户认证、批量供货 | 映射公司敞口 |
| `long_term_contract` | 长单、重大合同 | 公告级才影响，框架协议只展示 |
| `customer_substitution_or_cut` | 客户自研、砍单、备份供应 | 风险/veto 候选 |
| `guidance_or_analyst_revision` | 管理层指引、分析师上修下修 | forecast_overlay，不当事实 |
| `accounting_impairment` | 商誉、资产、存货、应收减值 | 不进供需分，影响财务质量/风险 |
| `clarification_denial` | 澄清、否认、问询回复 | 优先进入 source review |

### 13.2 Event Score Effect

| score_effect | 说明 | 分数影响 |
|---|---|---:|
| `none` | 只展示 | 0 |
| `mapped_only` | 作为某个 slot 的证据 | 0 |
| `factor_delta_small` | 小幅修正因子 | ±3 |
| `factor_delta_medium` | 中等修正 | ±5 |
| `factor_delta_large` | 高可信重大事件 | ±10，需 S/A 或多源 B |
| `veto_candidate` | 否决候选 | 不直接加减分 |
| `forecast_overlay` | 预测层 | 不进基本面，最多影响 rationale |

### 13.3 事件去重

所有事件必须有：

```text
duplicate_group_id
maps_to_factor
maps_to_slot
score_effect
```

若同一事件已进入某个 slot，则 event_score_effect 必须改为 `mapped_only`。

---

## 14. Rating 与研究倾向

### 14.1 基本面 Rating

| adjusted score | rating |
|---:|---|
| >= 90 | S |
| 80-89 | A |
| 70-79 | B |
| 60-69 | C |
| 50-59 | D |
| <50 | F |

### 14.2 质量状态

| 状态 | 条件 |
|---|---|
| `high_confidence` | coverage >= 0.75 且 confidence >= 0.80，无重大审计问题 |
| `medium_confidence` | coverage >= 0.60 且 confidence >= 0.65 |
| `provisional` | coverage 0.50-0.60 或 confidence 0.50-0.65 |
| `unrated_insufficient_evidence` | coverage <0.50 或核心冲突未解决 |
| `review_required` | 有 veto warning、冲突、重大事件或计算失败 |

### 14.3 研究倾向标签

| label | 中文 | 条件 |
|---|---|---|
| `strong_positive_research` | 强正向研究 | adjusted >=85，coverage >=70%，无 veto warning，市场未拥挤 |
| `positive_research` | 偏正向跟踪 | adjusted >=75，无 hard veto，证据中等以上 |
| `neutral_watch` | 中性观察 | adjusted 60-75，或市场 crowded，或证据不足 |
| `negative_watch` | 偏负向观察 | adjusted <60，或负向事件明显 |
| `avoid_or_reject` | 回避/否决 | hard veto triggered，或 adjusted <50 且负向证据确认 |
| `unrated_insufficient_evidence` | 证据不足，暂不评级 | coverage <50% 或关键冲突未解决 |

禁止默认输出：

```text
买入
卖出
仓位比例
目标价
收益率承诺
```

---

## 15. 入库结构补充

V0.6 已定义主表。本版建议对以下表补充 trace 字段。

### 15.1 `opportunity_metric_slot`

```sql
CREATE TABLE IF NOT EXISTS opportunity_metric_slot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    factor_code TEXT NOT NULL,
    slot_code TEXT NOT NULL,
    slot_role TEXT NOT NULL, -- primary/supporting/contradiction/context
    slot_weight REAL NOT NULL DEFAULT 1.0,

    raw_value_num REAL,
    raw_value_text TEXT,
    raw_unit TEXT,
    raw_currency TEXT,
    period TEXT,
    as_of_date TEXT,

    standardized_value_num REAL,
    standardized_value_text TEXT,
    standardized_unit TEXT,
    standardized_currency TEXT,
    normalization_method TEXT,
    bucket_label TEXT,
    slot_score REAL,

    value_status TEXT NOT NULL,
    source_count INTEGER DEFAULT 0,
    independent_source_count INTEGER DEFAULT 0,
    best_source_id INTEGER,
    best_source_tier TEXT,
    source_weight REAL,
    freshness_days INTEGER,
    freshness_weight REAL,
    slot_confidence REAL,

    source_review_status TEXT,
    calculation_review_status TEXT,
    human_review_status TEXT DEFAULT 'pending',

    preprocess_trace_json TEXT,
    scoring_trace_json TEXT,
    rationale_text TEXT,
    audit_issue_count INTEGER DEFAULT 0,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, entity_id, factor_code, slot_code)
);
```

### 15.2 `opportunity_factor_score`

```sql
CREATE TABLE IF NOT EXISTS opportunity_factor_score (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    factor_code TEXT NOT NULL,

    primary_score REAL,
    support_adjustment REAL DEFAULT 0,
    event_adjustment REAL DEFAULT 0,
    contradiction_penalty REAL DEFAULT 0,

    factor_score_raw REAL,
    factor_coverage REAL,
    factor_confidence REAL,
    coverage_multiplier REAL,
    confidence_multiplier REAL,
    audit_multiplier REAL,
    factor_score_adjusted REAL,

    factor_status TEXT,
    review_required INTEGER DEFAULT 0,
    aggregation_trace_json TEXT,
    adjustment_trace_json TEXT,
    rationale_text TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, entity_id, factor_code)
);
```

### 15.3 `opportunity_composite_score`

```sql
CREATE TABLE IF NOT EXISTS opportunity_composite_score (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,

    segment_imbalance_score_raw REAL,
    segment_imbalance_score_adjusted REAL,
    segment_coverage REAL,
    segment_confidence REAL,

    company_capture_score_raw REAL,
    company_capture_score_adjusted REAL,
    company_coverage REAL,
    company_confidence REAL,
    company_score_cap REAL,

    company_fundamental_score_raw REAL,
    company_fundamental_score_capped REAL,
    company_fundamental_score_adjusted REAL,
    overall_coverage REAL,
    overall_confidence REAL,

    market_reflection_state TEXT,
    market_window_multiplier REAL,
    research_priority_score REAL,

    rating TEXT,
    rating_status TEXT,
    research_bias_label TEXT,

    veto_triggered_count INTEGER DEFAULT 0,
    veto_warning_count INTEGER DEFAULT 0,
    audit_issue_count INTEGER DEFAULT 0,
    high_confidence_weight REAL,

    scoring_version TEXT NOT NULL,
    composite_trace_json TEXT,
    summary_rationale TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, entity_id, scoring_version)
);
```

### 15.4 Trace JSON 示例

```json
{
  "input": {
    "raw_value": 0.32,
    "raw_unit": "pct",
    "period": "3M",
    "source_ids": [101, 205]
  },
  "preprocessing": {
    "unit_conversion": "none",
    "winsorized": false,
    "standardized_value": 0.32
  },
  "scoring": {
    "rule": "3M price change >=30% => 100",
    "bucket": ">=30%",
    "slot_score": 100
  },
  "quality": {
    "source_weight": 0.93,
    "freshness_weight": 1.0,
    "slot_confidence": 0.91
  },
  "rationale": "目标材料 3M 价格上涨 32%，属于强正向价格动量。"
}
```

---

## 16. Max 5 轮自我审查记录

### Round 1：微观数据与预处理审查

**问题**：是否每个数据都定义了单位、时间、币种、口径和离群处理？  
**发现**：V0.7 对归一化有框架，但没有给出币种、产能、价格品级、百分比/百分点、预测/事实分离的完整规则。  
**修正**：新增第 4、5 节，覆盖单位、货币、时间、价格品级、产能状态、离群值和 winsorization。

### Round 2：来源权重审查

**问题**：是否过度惩罚可信媒体？  
**发现**：V0.7 S/A/B/C 差距过大，可能导致可信产业媒体无法有效参与及时事件判断。  
**修正**：压缩 source weight：S=1.00、A=0.97、B=0.93、C=0.86，D 不入分。对高影响事件增加官方确认状态，而不是简单大幅降权。

### Round 3：覆盖率不足审查

**问题**：覆盖率只有 50%-60% 时怎么办？是否会制造假高分？  
**发现**：简单乘法/开方可能过度惩罚，也可能规则不透明。  
**修正**：改成覆盖率分层与向 50 收敛；低于 50% 不出强结论，50%-60% 只能 provisional，最高 B 或 neutral_watch。

### Round 4：因子权重与隐性偏置审查

**问题**：是否给某些方向隐性过高权重？  
**发现**：若价格、调价事件、媒体涨价新闻同时计入，价格因素可能被重复放大；若 CR3、供应商数、认证周期都单独打分，供给结构也会重复放大。  
**修正**：明确“多个数据支撑一个因子但只产生一次父因子分”；事件若映射 slot，不能重复加分；任一 metric slot 对最终分影响不得超过 12 分，任一事件对最终分影响不得超过 5 分，除非进入 veto。

### Round 5：特殊情况和输出审查

**问题**：亏损公司、估值极端、预测数据、商誉减值、客户砍单、澄清公告怎么处理？  
**发现**：V0.7 对事件分类已有基础，但对特殊财务/预测/否认事件的 score_effect 仍不够严格。  
**修正**：将管理层指引和分析师预测放入 forecast_overlay；商誉/资产减值只影响财务质量或风险提示；澄清公告/否认传闻优先进入 source review；亏损公司不使用负 PE，估值用 PS/PB 或标不适用。

---

## 17. 最终输出要求

每个评分对象页面必须展示四块：

### 17.1 总分卡

```text
环节失衡分：xx / 100
公司承接分：xx / 100
公司基本面机会分：xx / 100
市场反应状态：recognized/crowded/...
研究优先级：xx / 100
研究倾向：positive_research / neutral_watch / ...
覆盖率：xx%
置信度：xx%
评级状态：high_confidence / provisional / review_required
```

### 17.2 因子拆解表

| factor | raw | adjusted | coverage | confidence | rationale |
|---|---:|---:|---:|---:|---|
| demand.downstream_price_momentum | 85 | 80 | 0.75 | 0.88 | 下游价格持续上涨，但 1M 边际放缓 |

### 17.3 数据与计算链条

用户点击任一因子后能看到：

```text
评分槽：slot → raw value → standardized value → bucket → slot_score → source → excerpt → preprocess trace

背景槽：slot → raw value → standardized value → source → excerpt → preprocess trace → 不计分说明
```

### 17.4 审计和事件表

必须展示：

```text
source conflicts
calculation issues
coverage gaps
stale data
weak source events
event ledger
veto status
```

---

## 18. 实施优先级

### Phase 1：落地可解释 score trace

```text
1. 扩展 opportunity_metric_slot / factor_score / composite_score trace 字段。
2. 实现 source_weight 压缩规则。
3. 实现覆盖率分层和向 50 收敛。
4. 实现 14 个 factor 的 slot 字典。
```

### Phase 2：实现预处理引擎

```text
1. 单位/货币/时间标准化。
2. 离群值检测和 winsorization trace。
3. 产品品级/产能状态/预测事实分离。
```

### Phase 3：评分引擎

```text
1. slot_score 生成。
2. factor 聚合。
3. composite score。
4. veto cap。
5. market reaction。
```

### Phase 4：viewer 展示

```text
1. 因子拆解页面。
2. 原始数据/标准化/分数链条页面。
3. 事件账本页面。
4. 审计问题页面。
```

### Phase 5：样例回放校准

先用：

```text
WF6
ArF/ArFi 光刻胶
HBM EMC
低 α 球硅/氧化铝
```

跑历史样例，检查：

```text
1. 是否因涨价新闻重复加分？
2. 是否因 CR3/供应商数/认证周期重复加分？
3. 是否因覆盖率 50%-60% 给出过强结论？
4. 是否因市场拥挤仍给强正向研究？
5. 是否所有分数都可追溯到原始数据？
```

---

## 19. 一句话总结

V0.8 的评分系统不是“打一个更复杂的分”，而是把每个分数都变成可解释计算链：

```text
可信来源 → 原子数据点 → 预处理 → slot_score → factor_score → composite_score → 市场反应 → 研究倾向
```

它的核心约束是：

```text
可信媒体不过度惩罚；弱源不入分。
覆盖率不足向中性收敛；低于 50% 不出强结论。
所有数字先标准化；所有离群值保留 raw trace。
多个数据证明一个因子；只打一次父因子分。
事件只映射，不重复加分。
市场反应不改基本面，只改研究优先级。
所有计算过程必须可展开、可审计、可复算。
```


---

# 附录 A：V0.8.1 工程前接口修订

## A1. C 轨独立 DB 约束

V0.8.1 的评分引擎默认从 C 轨独立数据库读取输入，不直接读取或写入 A/B 行研轨的业务表。A/B `research.db` 可以作为只读 reference，但不得作为评分权威库。

推荐 C 轨 DB：

```text
data/opportunity.db
```

评分相关对象均应属于 C 轨 DB：

```text
opportunity_run
opportunity_candidate_entity
opportunity_metric_slot
opportunity_slot_data_point
opportunity_factor_score
opportunity_composite_score
opportunity_event_ledger
opportunity_audit_issue
opportunity_market_reaction
opportunity_veto_status
```

A/B 数据进入评分前必须经过 C 轨 reference 导入或 link：

```text
ab_db_name
ab_table_name
ab_row_id
ab_snapshot_at
ab_reference_usage
ab_reference_freshness_days
```

A/B reference 默认只能作为 seed/supporting/stale_reference；如要成为评分证据，必须在 C 轨中形成新的 `metric_slot` 映射和审计记录。

## A2. Run Manifest 与版本回放

每次评分必须绑定 `opportunity_run_manifest`。最低字段：

```text
run_id
user_question
run_mode
data_cutoff_date
c_track_db_version
taxonomy_version
search_strategy_version
source_ladder_version
factor_dictionary_version
slot_dictionary_version
preprocessing_version
scoring_rule_version
event_mapping_version
audit_rule_version
prompt_version
agent_version
model_version
ab_reference_snapshot_at
input_files_hash_json
config_hash_json
run_manifest_json
```

评分结果必须至少达到 `L1_score_replayable`：固定 data point、slot 和 rule version 后可以重算相同分数。正式系统目标是 `L2_data_replayable`。

## A3. Factor Readiness 接口

进入 V0.8.1 打分前，V0.9.1 必须交付 `factor_readiness_matrix`。评分引擎不得在 readiness 缺失时自行猜测。

字段：

```text
run_id
entity_id
factor_code
slot_count_total
slot_count_available
slot_count_stale_only
slot_count_weak_source_only
slot_count_conflict
factor_coverage
factor_confidence
factor_readiness_status
blocking_reason
```

`factor_readiness_status` 枚举：

```text
ready
limited
reference_only
missing
conflict_blocked
not_applicable
```

如果 `factor_coverage < 50%` 或 `factor_readiness_status = conflict_blocked`，该因子不得产生强方向性分数，应向中性 50 收敛或触发 `score_limited / research_only`。

## A4. Event 去重和映射约束

事件账本进入评分前必须先去重。默认去重键：

```text
event_type + canonical_entity_id + product_material + event_date/effective_date + normalized_event_subject
```

同一事件多源报道只提高 source_count / confidence，不重复加分。

默认映射：

| event_type | 映射目标 | 评分约束 |
|---|---|---|
| `price_revision` | `signal.material_price_momentum` | 不得与同一价格 slot 重复计分 |
| `capacity_change` | `supply.capacity_event_12m` / `company.capacity_readiness_window` | 必须区分现有、在建、规划、传闻 |
| `supply_disruption` | `supply.capacity_event_12m` / `signal.material_price_momentum` | 需官方确认状态或多源验证 |
| `policy_control` | `supply.raw_policy_constraint` / `veto.policy_market_shutdown` | 按公司和地理口径判断方向 |
| `customer_validation` | `company.exposure_directness` | 需区分验证、小批量、量产 |
| `long_term_contract` | `company.exposure_directness` / reference | 框架协议不等于有约束长单 |
| `guidance_or_analyst_revision` | forecast overlay | 不当事实，不进供需分 |
| `accounting_impairment` | `company.financial_capture_quality` | 不进供需分 |
| `clarification_denial` | source review / contradiction | 高优先级审计事件 |

## A5. Score Limited 输出

当数据不足但仍有部分证据时，评分引擎必须输出 `rating_status`：

```text
full_score
score_limited
research_only
blocked
```

`score_limited` 的输出必须同时展示：

```text
missing_factor_count
weak_source_factor_count
conflict_factor_count
supplement_request_count
why_not_full_score
```

不得把 `score_limited` 包装成完整评级。

## A6. 与 V0.9.1 Handoff 的接口

V0.8.1 只接受 V0.9.1 生成的 handoff package：

```text
run_id
entity_shortlist
factor_readiness_matrix
claim_evidence_table
event_ledger_candidates
supplement_request_table
run_stats
candidate_stats
audit_issues
readiness_status
```

缺少 handoff package 时，V0.8.1 不应自动评分。
