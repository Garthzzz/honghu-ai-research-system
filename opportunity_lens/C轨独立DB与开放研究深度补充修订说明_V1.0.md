# C 轨独立 DB 与开放研究深度补充修订说明 V1.0

**适用范围**：补充并修订 `C轨供需失衡评分流程与可解释计算体系_V0.8.md` 与 `C轨研究启动与开放探索输出标准_V0.9.md`。  
**本文定位**：不是重新设计评分模型，而是把 C 轨在工程启动前仍然模糊的部分写清楚：C-Open 的研究深度、统一 taxonomy、统计接口、补充资料建议、独立数据库边界、内部 promotion/maturation、版本回放和后续 Scientist/Architect/Engineer 交接方式。  
**硬边界**：C 轨是独立系统。A/B 行研轨和 `research.db` 可以作为只读参考来源，但 C 轨不得直接写入、修改、删除或污染 A/B 的数据库、文档和 viewer 主链路。

---

## 0. 本次修订的核心结论

本次修订确认以下设计原则：

1. **C-Open 第一版不是草稿**。它是正式的 pre-scoring research pack，必须按最终研究包标准输出，只是结论状态可能是 `research_only`、`score_limited` 或 `scoring_ready`。
2. **C-Open 和 C-Paper 的全网搜索深度应保持一致**。是否有研报不影响联网 文献综述 的强制性；研报只影响 seed 和参考，不降低搜索深度。
3. **C 轨使用独立数据库**。A/B 的 `research.db` 只能通过只读引用、快照或导入型 reference 使用。C 轨自己的 source、data point、entity、event、score、audit、output 都写入独立 C 轨 DB。
4. **taxonomy 必须机器化**。所有 Agent 必须用同一套 entity 层级、mapping 口径和地理/应用/流程字段，避免同一对象被不同 Agent 放在不同层级。
5. **必须增加统计接口**。每次 run 都要输出搜索深度、source 分布、语言覆盖、候选数量、factor readiness、缺失率、过期率、冲突率等统计，确保不同 Agent 处理口径一致。
6. **补充资料建议必须结构化**，但保留一个自由文本字段 `freeform_agent_note`，允许 Codex/Agent 在认为必要时补充非标准建议。
7. **promotion 只在 C 轨内部发生**。C 轨内部从发现、候选、核验、入槽、计分、审阅、发布逐级成熟；不自动 promotion 到 A/B 主库。
8. **所有 run 必须可回放**。搜索策略、taxonomy、source ladder、factor dictionary、preprocessing、scoring、event mapping、prompt 和 agent 版本都要写入 manifest。

---

## 1. C 轨和 A/B 轨的架构边界

### 1.1 独立性定义

C 轨不是 A/B 轨的一个行业页面扩展，而是独立的供需失衡机会扫描系统。它可以复用已有行研资产作为参考，但不能把 A/B 轨当作 C 轨事实库。

| 项目 | A/B 行研轨 | C 轨机会扫描 |
|---|---|---|
| 主要目标 | 行业知识底座、Q0-Q5、公司透视、估值、产业链 | 开放问题探索、供需失衡评分、公司承接、市场反应、审计和补充资料 |
| 输入 | papers、prompt、行业研报、平台已有数据 | 用户问题、全网搜索、全球多语言 文献综述、研报/DB 参考、事件和市场数据 |
| DB | `research.db` / `sentiment.db` | 独立 `opportunity.db`，或等价 C 轨 DB |
| 是否可写 A/B | 是，按 A/B SOP | 否；只读参考，不写、不改、不删 |
| 研报作用 | 主输入或重要输入 | seed / reference / background，不是唯一事实源 |
| 输出 | 行业文档、Q0-Q5、公司页、估值页 | pre-scoring research pack、评分卡、事件账本、审计、补充资料建议、viewer trace |

### 1.2 A/B 资产如何被 C 轨使用

C 轨可从 A/B 轨读取以下内容，但必须标明来源和时效：

```text
ab_source_reference
ab_industry_data_point_reference
ab_company_profile_reference
ab_industry_relation_reference
ab_markdown_reference
```

使用规则：

1. 只能通过 read-only attach、快照导入或 link table 引用。
2. 不建立跨库硬外键，避免 C 轨运行影响 A/B 主库。
3. 引用 A/B 数据时必须记录：
   - `ab_db_name`
   - `ab_table_name`
   - `ab_row_id`
   - `ab_snapshot_at`
   - `ab_reference_freshness_days`
   - `ab_reference_usage = seed / supporting / rejected / stale_reference`
4. A/B 数据若过期，仍可用于产业链理解和候选 seed，但不得直接支撑当前供需失衡强结论。
5. C 轨重新抓到的外部数据不得回写 A/B，除非未来单独设计人工 review 后的 export workflow。

### 1.3 C 轨独立 DB 建议

建议 C 轨使用独立 SQLite：

```text
data/opportunity.db
```

如工程上使用其他命名，也必须保持以下逻辑边界：

```text
C 轨 own source
C 轨 own data point
C 轨 own entity
C 轨 own metric slot
C 轨 own factor score
C 轨 own event ledger
C 轨 own audit issue
C 轨 own output package
```

A/B 的 `research.db` 只是 reference，不是 C 轨权威状态库。

---

## 2. C-Open minimum research depth：正式研究深度标准

### 2.1 核心原则

C-Open 不因为没有 papers 而降低标准。相反，C-Open 更需要全网 文献综述 和 taxonomy 构建。

C-Open 第一版必须完成：

```text
问题拆解
+ 搜索计划
+ 全球多语言 source discovery
+ 候选 taxonomy
+ 候选长名单与短名单
+ claim/evidence 表
+ factor readiness matrix
+ 数据缺口和补充资料建议
+ 是否进入 V0.8 评分的 handoff 判断
```

不允许输出一个仅有观点、没有证据矩阵和缺口判断的“方向草稿”。

### 2.2 搜索深度与范围

无论 C-Open 还是 C-Paper，都必须覆盖同一组 search axes：

| search_axis | 目标 | 典型问题 |
|---|---|---|
| `taxonomy` | 找候选环节、材料、公司和产业链结构 | 这个问题应该拆成哪些细分环节？ |
| `demand` | 找需求触发 | 下游价格、产能、CapEx、出货、应用强度是否变化？ |
| `supply` | 找供给约束 | 产能、原料、政策、供应结构、替代难度是否形成约束？ |
| `signal` | 找当前失衡信号 | 价格、招投标、海关量价、调价、限供、停产是否出现？ |
| `company_capture` | 找公司承接 | 公司是否直接供货？收入敞口、产能、财务能否承接？ |
| `market_reaction` | 找市场是否反应 | 股价、估值、成交、新闻/KOL 热度是否已交易？ |
| `risk_contradiction` | 找反证和风险 | 是否有价格回落、扩产洪水、客户自研、澄清、否认？ |
| `reference_background` | 找研报/数据库/长期背景 | 静态格局、份额、CAGR、技术路线是否有权威支持？ |

### 2.3 多语言覆盖

默认语言集合：

```text
zh, en, ja, ko
```

按行业可扩展：

```text
de, fr, zh-Hant, local_language
```

规则：

1. 全球半导体、存储、材料、设备问题，至少覆盖 `zh + en`。
2. 涉及日本/韩国供应商或客户时，必须加入 `ja / ko` 查询。
3. 涉及欧洲化工、材料、设备时，加入 `de / fr` 查询。
4. 不要求每个候选都有每种语言 source，但 run 级统计必须披露各语言覆盖。

### 2.4 source ladder 覆盖

每次正式 C-Open 至少尝试覆盖以下 source groups：

| source_group | 作用 |
|---|---|
| `official_company` | 公司公告、官网、IR、年报、季报、招股书 |
| `official_government` | 政府、监管、交易所、海关、出口管制、协会 |
| `industry_database` | SEMI、WSTS/SIA、TrendForce、DRAMeXchange、Yole、Omdia、TechInsights 等 |
| `credible_media` | Reuters、Nikkei、The Elec、Digitimes、财联社等 |
| `sellside_database` | Alpha Pi、Wind、Choice、卖方研报、进门财经等 |
| `market_data` | 股价、估值、成交、情绪、新闻热度 |
| `weak_signal` | KOL、自媒体、小作文，仅作线索和热度，不进入核心评分 |

C-Open 输出中必须有 `source_group_coverage`。如果某 source_group 未覆盖，要说明是不可得、权限不足、无相关结果，还是本问题不适用。

### 2.5 候选收敛规则

C-Open 可以先产生长名单，但必须收敛到可研究短名单。

建议状态：

```text
long_list
candidate
shortlist
scoring_ready
research_only
rejected
```

进入 `shortlist` 的最低要求：

1. 与核心问题高度相关；
2. 至少有 2 个 search_axis 出现有效证据；
3. 至少有 1 个 B 级及以上可信来源，或 2 个 C 级以上独立来源；
4. 不是纯主题映射；
5. 没有未解决的高严重度反证。

进入 `scoring_ready` 的最低要求：

1. 对环节/材料类实体：V0.8 的 demand/supply/signal 三类中至少 2 类具备可用证据；
2. 对公司类实体：必须证明 `company.exposure_directness` 不是纯主题映射，或明确标为低承接；
3. 最新动态证据必须满足 freshness 规则：高频信号 30 天内、月度数据 60 天内、季度数据 120 天内、结构性数据 12 个月内；
4. 无 unresolved high-severity audit issue；
5. factor readiness 低于 50% 时不得进入正式评分。

### 2.6 C-Open 输出深度口径

C-Open 第一版输出深度应接近正式报告，但结论状态不同。

必须输出：

```text
1. 任务判定和范围
2. 问题拆解
3. search plan 和 search coverage stats
4. source map
5. taxonomy 和候选 long list / shortlist
6. claim/evidence table
7. factor readiness matrix
8. 初步研究判断
9. 数据缺口
10. supplement request table
11. V0.8 handoff package
12. audit log
```

不允许缺失：

```text
search statistics
source distribution
candidate inclusion/exclusion reasons
readiness gate status
supplement request
```

---

## 3. 统一 taxonomy 与实体映射口径

### 3.1 Entity 层级

C 轨实体必须使用统一层级：

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

含义：

| entity_type | 说明 | 示例 |
|---|---|---|
| `theme` | 跨行业主题 | AI 算力、存储景气、国产替代 |
| `industry` | 行业 | 半导体材料、存储、先进封装 |
| `segment` | 细分环节 | 电子特气、光刻胶、CMP、封装材料 |
| `product_material` | 具体材料/产品 | WF6、ArF、HBM EMC、低 α 球硅 |
| `process_step` | 工艺步骤 | 光刻、刻蚀、沉积、CMP、封装 |
| `application` | 下游应用 | DRAM、3D NAND、HBM、先进逻辑 |
| `customer` | 下游客户或客户群 | YMTC、CXMT、Samsung、SK hynix |
| `company` | 公司法人 | 中船特气、关东电化 |
| `security` | 股票/证券 | 688146.SH、4045.T |
| `geography` | 地理口径 | global、China、Japan、Korea、US、Europe |

### 3.2 Candidate entity 必填字段

`opportunity_candidate_entity` 最低字段：

```text
entity_id
run_id
entity_type
entity_name
canonical_name
aliases_json
parent_entity_id
geo_scope
application_scope
process_step
candidate_status
candidate_source
inclusion_reason
exclusion_reason
created_at
updated_at
```

### 3.3 映射类型

公司到材料/环节映射必须显式记录：

```text
direct_mass_supply
direct_small_batch
qualified_testing
indirect_supply
upstream_raw_material
downstream_customer_link
global_peer
theme_mapping_only
unverified
```

规则：

1. 公司不得直接从 `theme` 获得高承接分，必须先映射到 `product_material` 或 `segment`。
2. `theme_mapping_only` 的公司承接评分设上限，不允许靠主题拿高分。
3. 全球同业对标必须标 `global_peer`，不能与直接供应混同。
4. 一家公司可映射多个材料/环节，但每个 mapping 都要有 source 和 evidence。

---

## 4. 统计接口与统一口径

### 4.1 为什么必须有统计接口

C-Open 和 C-Paper 的输出质量不能只靠自然语言判断。每个 run 必须产生一组可筛选、可比较、可回放的统计指标，用于回答：

```text
搜得够不够？
来源类型是否偏窄？
语言覆盖是否不足？
候选是否只是主题映射？
哪些因子真正具备评分条件？
缺失是因为没有查、查不到、来源弱，还是数据本身不披露？
```

### 4.2 run 级统计

建议表：`opportunity_run_stats`

核心字段：

```text
run_id
total_search_queries
search_queries_by_language_json
search_queries_by_axis_json
source_count_total
source_count_by_tier_json
source_count_by_group_json
source_count_by_language_json
latest_source_date
median_source_freshness_days
candidate_count_longlist
candidate_count_shortlist
candidate_count_scoring_ready
claim_count_total
data_point_candidate_count
c_data_point_verified_count
event_count_total
audit_issue_count_total
audit_issue_count_high
supplement_request_count
ab_reference_count
stale_reference_ratio
run_readiness_status
created_at
```

`run_readiness_status` 枚举：

```text
scoring_ready
score_limited
research_only
blocked
```

### 4.3 candidate 级统计

建议表：`opportunity_candidate_stats`

字段：

```text
run_id
entity_id
source_count
source_tier_best
source_group_coverage_json
language_coverage_json
evidence_axis_coverage_json
factor_readiness_json
available_factor_count
missing_factor_count
weak_source_factor_count
conflict_factor_count
latest_evidence_date
freshness_status
confidence_summary
audit_issue_count
high_severity_audit_issue_count
readiness_status
```

### 4.4 factor readiness 统计

每个候选都要按 V0.8 的 14 个因子包输出 readiness：

```text
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

状态：

```text
ready
limited
reference_only
missing
conflict_blocked
not_applicable
```

---

## 5. 补充资料建议标准化

### 5.1 Supplement Request 表

建议表：`opportunity_supplement_request`

字段：

```text
supplement_id
run_id
entity_id
entity_type
target_factor_code
target_slot_code
missing_evidence_type
recommended_source_type
recommended_source_examples
priority
blocking_status
reason
expected_decision_impact
suggested_search_query
acceptable_alternatives
can_score_without_it
is_due_to_staleness
is_due_to_source_conflict
is_due_to_low_coverage
freeform_agent_note
created_by_agent
created_at
review_status
reviewer_note
```

### 5.2 字段含义

| 字段 | 说明 |
|---|---|
| `missing_evidence_type` | 缺少价格、产能、客户、供应商份额、公告、财务、市场反应等哪类证据 |
| `recommended_source_type` | 建议补充公告、数据库、研报、纪要、专家访谈、海关、交易所文件等 |
| `priority` | `P0_blocking / P1_high / P2_medium / P3_low` |
| `blocking_status` | 是否阻止正式评分：`blocks_scoring / limits_score / improves_confidence_only` |
| `expected_decision_impact` | 补充后会影响哪个判断：候选纳入、评分方向、公司承接、市场反应、否决项 |
| `can_score_without_it` | 是否可在缺失情况下低置信评分 |
| `freeform_agent_note` | Agent 对非标准补充资料的自然语言建议 |

### 5.3 自由文本字段规则

`freeform_agent_note` 用于记录标准字段无法表达的补充建议，例如：

```text
建议找某公司近两次业绩会录音，因为公开公告没有解释客户验证节奏。
建议向研究员确认该材料在 YMTC 232L NAND 中的实际工艺位置，因为公开资料只说明“相关耗材”。
建议补充日文/韩文产业媒体，因为英文源仅引用二手报道。
```

这个字段不能替代结构化字段。所有 supplement request 都必须先填结构化字段，再用 `freeform_agent_note` 补充。

---

## 6. C 轨内部 promotion / maturation 机制

### 6.1 设计目的

C 轨需要从开放搜索得到大量候选和线索。如果没有成熟度状态，系统会混淆：

```text
刚搜索到的网页
被抽取的 claim
可入库 data point
可进入 metric slot 的数据
可用于评分的证据
已人工审阅的结论
```

所以 promotion 不是“写回 A/B”，而是 C 轨内部证据成熟机制。

### 6.2 状态机

建议字段：`maturation_status`

```text
discovered
source_candidate
source_accepted
claim_extracted
data_point_candidate
data_point_verified
metric_slot_candidate
metric_slot_accepted
factor_used
score_generated
review_pending
reviewed
published
rejected
archived
```

规则：

1. `discovered`：搜索结果或用户 seed，未审。
2. `source_accepted`：source review 通过，可进入 C source。
3. `claim_extracted`：已抽取 claim，但未必可入 data point。
4. `data_point_verified`：数字/事实通过 source 和 calculation review，可进入 C data point。
5. `metric_slot_accepted`：映射到 V0.8 slot，口径合格。
6. `factor_used`：进入某个 factor bundle 的主/支撑/反证信号。
7. `score_generated`：参与评分计算。
8. `reviewed`：人工或审计 Agent 通过。
9. `published`：进入正式输出包。
10. `rejected`：拒绝使用，但保留审计痕迹。

### 6.3 外部导出候选

如果未来希望把 C 轨发现沉淀到 A/B 行研主库，只能生成建议，不自动写入：

```text
external_export_candidate
```

字段：

```text
export_target = ab_research_db / industry_doc / company_profile / relation / none
export_reason
required_human_approval
export_status = proposed / approved / rejected / executed_manually
```

默认 `export_status = proposed`。工程实现阶段不做自动执行。

---

## 7. 版本与可回放设计

### 7.1 Run manifest

每次 run 必须写入 `opportunity_run_manifest`。

字段：

```text
run_id
user_question
run_mode
created_at
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

### 7.2 可回放等级

定义 `replay_level`：

```text
L0_not_replayable
L1_score_replayable
L2_data_replayable
L3_search_replayable
```

含义：

| 等级 | 含义 |
|---|---|
| `L1_score_replayable` | 固定 data point 和 slot，可重算评分 |
| `L2_data_replayable` | 固定 sources 和 claims，可重建 data point/slot |
| `L3_search_replayable` | 固定 search plan、query、result、source，可重放搜索过程 |

MVP 最低要求：`L1_score_replayable`。正式系统目标：`L2_data_replayable`，搜索平台支持时尽量达到 `L3_search_replayable`。

### 7.3 版本变更原则

1. 任何因子权重、bucket、预处理、source ladder 调整都必须产生新 version。
2. 历史 score 不覆盖，只追加新 score run。
3. 输出必须显示 `scoring_rule_version` 和 `data_cutoff_date`。
4. 如果同一实体分数变化，必须能区分数据变化和规则变化。

---

## 8. C-Open 搜索协议

### 8.1 Search Plan 对象

建议 `opportunity_search_plan` 字段：

```text
search_plan_id
run_id
question_decomposition_json
search_axes_json
language_set_json
source_groups_target_json
geo_scope_json
candidate_seed_json
negative_search_required
created_at
```

### 8.2 Search Task 对象

建议 `opportunity_search_task` 字段：

```text
search_task_id
run_id
search_axis
language
geo_scope
query_text
query_intent
source_group_target
status
result_count
accepted_source_count
rejected_source_count
created_at
completed_at
failure_reason
```

### 8.3 Source discovery 对象

建议 `opportunity_source_discovery` 字段：

```text
discovery_id
run_id
search_task_id
url_or_file_ref
title
publisher
publish_date
language
source_group
source_tier_candidate
is_primary_source_candidate
domain
snippet
accepted_as_source
rejection_reason
source_id
created_at
```

### 8.4 Stop condition

C-Open 搜索可以停止，必须满足以下之一：

1. 已覆盖全部 search axes，且 short list 候选的 factor readiness 足以判断 `scoring_ready / score_limited / research_only`；
2. 继续搜索主要返回重复来源，新增高可信 claim 接近于零；
3. 出现权限/付费壁垒，且已输出 supplement request；
4. 研究范围过大，系统已提出下一轮聚焦子问题。

不得因为“已有研报”而提前停止全网搜索。

---

## 9. Scoring Readiness Gate 修订

### 9.1 Gate 状态

```text
scoring_ready
score_limited
research_only
blocked
```

### 9.2 Segment / product_material ready 条件

`product_material` 或 `segment` 进入正式评分，最低要求：

```text
1. demand 侧 4 个因子中至少 2 个 ready/limited；
2. supply 侧 5 个因子中至少 3 个 ready/limited；
3. signal.material_price_momentum ready/limited，或明确说明该品类价格无公开代理并降级；
4. 最新证据满足时效规则；
5. 无 unresolved high severity audit issue；
6. 总 factor coverage >= 50%。
```

如果 signal 缺失但 demand/supply 强，可以 `score_limited`，但不得给强确定性结论。

### 9.3 Company ready 条件

公司进入正式承接评分，最低要求：

```text
1. 必须有明确 mapping 到 product_material 或 segment；
2. company.exposure_directness 不能是 unknown；
3. company.revenue_exposure_proxy 至少 available / not_disclosed_with_source / limited；
4. company.capacity_readiness_window 至少 limited；
5. company.financial_capture_quality available；
6. market reaction 至少有股价/估值/成交中的两类；
7. 无 unresolved high severity audit issue。
```

### 9.4 Blocked 条件

```text
1. 关键结论无 source；
2. 同一核心数据出现官方与非官方高冲突且无法解决；
3. 候选只是主题映射，无法证明实际产业链关系；
4. factor coverage < 50%；
5. 数据大量过期且无法通过最新公开源补足。
```

---

## 10. Event ledger 去重与映射规则

### 10.1 去重键

建议：

```text
same_event_key = event_type + canonical_entity_id + product_material + event_date/effective_date + normalized_event_subject
```

同一事件多源报道时：

1. 选一个 primary event；
2. 其他来源作为 supporting source；
3. source_count 和 confidence 可上升；
4. factor score 不重复加分。

### 10.2 默认映射

| event_type | 默认映射 | 说明 |
|---|---|---|
| `price_revision` | `signal.material_price_momentum` | 官方或权威价格源才可入分 |
| `capacity_change` | `supply.capacity_event_12m` / `company.capacity_readiness_window` | 需区分现有、在建、规划、传闻 |
| `supply_disruption` | `supply.capacity_event_12m` / `signal.material_price_momentum` | 需官方确认状态 |
| `policy_control` | `supply.raw_policy_constraint` / `veto.policy_market_shutdown` | 方向按公司和地理口径判断 |
| `customer_validation` | `company.exposure_directness` | 需验证/小批量/量产状态 |
| `long_term_contract` | `company.exposure_directness` / reference | 框架协议不等于长单 |
| `customer_substitution_or_cut` | `veto.customer_backup_selfdev` / risk event | 高可信才调整 |
| `guidance_or_analyst_revision` | forecast overlay | 不当事实 |
| `accounting_impairment` | `company.financial_capture_quality` | 不进供需分 |
| `clarification_denial` | source review / contradiction | 优先级高 |

---

## 11. Audit severity 标准

| severity | 定义 | 处理 |
|---|---|---|
| `high` | 会改变候选纳入、因子方向、评级、否决项或研究倾向 | 阻止正式评分或触发人工复核 |
| `medium` | 影响置信度、覆盖率、局部分数，但不必然改变方向 | 标黄、降低 confidence |
| `low` | 展示质量或口径注释问题 | 记录，不阻断 |

High severity 示例：

```text
核心数字没有 source
CR3 声称值与复算值差异大且用于评分
官方公告否认媒体关键事件
产能口径把规划产能当现有有效产能
预测数据被当作已发生事实
同一事件重复计分导致评级变化
```

Medium 示例：

```text
数据超过 freshness 窗口
source 单一但非核心
单位需要换算但可追溯
全球/中国口径需要标注
```

Low 示例：

```text
source excerpt 较短但可打开原文
文本表述不够清楚
source tier 需要人工微调
```

---

## 12. Human review workflow

### 12.1 Review 队列

建议表：`opportunity_review_queue`

字段：

```text
review_item_id
run_id
entity_id
object_type
object_id
review_reason
severity
assigned_to
review_status
review_decision
reviewer_note
created_at
reviewed_at
```

### 12.2 人工可覆盖项

可以人工覆盖：

```text
source_tier
official_confirmation_status
event_mapping
contradiction_status
candidate inclusion/exclusion
research_bias_label
```

不应直接覆盖：

```text
raw_value
source_excerpt
raw source content
original URL / file reference
```

如果需要修改原始数据，应创建修正 data point 或 correction record，而不是覆盖原值。

---

## 13. V0.8 修订点摘要

V0.8 的评分体系保持不变，但必须增加以下接口约束：

1. `metric_slot`、`factor_score`、`composite_score` 默认从 C 轨独立 DB 读取。
2. A/B `research.db` 仅作为 `ab_reference_link` 或导入型 reference，不是评分权威库。
3. 每个 score 必须绑定：
   - `scoring_rule_version`
   - `factor_dictionary_version`
   - `preprocessing_version`
   - `event_mapping_version`
   - `run_manifest_id`
4. `coverage` 要区分：
   - `slot_coverage`
   - `factor_coverage`
   - `entity_coverage`
   - `run_coverage`
5. `score_limited` 状态必须在输出中清楚标注，不能伪装成完整评分。
6. 事件映射必须先通过去重，防止重复计分。

---

## 14. V0.9 修订点摘要

V0.9 的 C-Open/C-Paper 流程保持不变，但必须补充：

1. C-Open 和 C-Paper 使用同等搜索深度；有 papers 不减少全网 文献综述。
2. C-Open 第一版是正式 pre-scoring research pack，不是草稿。
3. 必须输出 run-level 和 candidate-level 统计。
4. 必须使用统一 taxonomy。
5. supplement request 必须结构化，且保留 `freeform_agent_note`。
6. C 轨输出写入独立 DB。
7. C-Paper 的 papers 只能作为 seed/reference，仍需独立联网核验。
8. 不允许 C 轨自动写入 A/B 行研主库。

---

## 15. 后续 Codex 多 Agent 执行建议

### 15.1 角色分工

后续新项目建议按三角色执行：

```text
Scientist：基于 V0.8/V0.9/V1.0 进行全面 文献综述 和科学/策略审核。
Architect：在 Scientist 结论上写系统 design、DB schema、接口、state machine、viewer plan。
Engineer：在设计通过后写代码、脚本、DB migration、前端可视化、测试和验收。
```

### 15.2 推荐阶段

```text
P0 Fresh session bootstrap
P1 Scientist 独立 文献综述 + C 轨文档一致性审核
P2 Scientist 输出 RESEARCH_LITREVIEW_AND_ANALYSIS.md
P3 Architect 输出 SYSTEM_DESIGN.md
P4 Architect 输出 IMPLEMENTATION_PLAN.md
P5 HARD HALT：用户审核 design + plan
P6 Engineer 实施独立 C DB + search/pre-scoring MVP
P7 Engineer 实施 V0.8 scoring engine + viewer trace
P8 Scientist/Architect/Engineer 联合验收
```

### 15.3 给 Codex 的项目必读文档

建议新项目根目录包括：

```text
CLAUDE.md 或 AGENTS.md
C轨供需失衡评分流程与可解释计算体系_V0.8.1.md
C轨研究启动与开放探索输出标准_V0.9.1.md
C轨独立DB与开放研究深度补充修订说明_V1.0.md
研究设计实施组合项目说明.md
填写指南.md
```

其中 `研究设计实施组合项目说明.md` 的模板已经明确了 Scientist、Architect、Engineer 三类角色、continuous execution chain 和 T7 user review hard halt；这与本项目后续“先 Scientist 研究、再 Architect 设计、用户通过后 Engineer 实施”的计划一致。

---

## 16. 本文审核记录

### Round 1 — 研究者视角

**问题**：C-Open 是否还是太像草稿？  
**修正**：明确 C-Open 是正式 pre-scoring research pack，并把输出深度、search axes、source group、候选收敛和 readiness gate 固定化。

### Round 2 — 架构师视角

**问题**：C 轨和 A/B 是否边界不清？  
**修正**：定义独立 `opportunity.db`，A/B `research.db` 只读 reference，C 轨不写、不改、不删 A/B 数据。

### Round 3 — 工程师视角

**问题**：统计口径是否可执行？  
**修正**：增加 `opportunity_run_stats`、`opportunity_candidate_stats`、factor readiness 统计和 search task/source discovery 对象。

### Round 4 — 策略师/研究员视角

**问题**：补充资料建议是否可操作？  
**修正**：固定 supplement request 字段，并保留 `freeform_agent_note`，让 Agent 可以补充非标准建议。

### Round 5 — 审计视角

**问题**：promotion 与版本回放是否足够严谨？  
**修正**：将 promotion 改为 C 轨内部 maturation，增加 run manifest、version bundle 和 replay level。
