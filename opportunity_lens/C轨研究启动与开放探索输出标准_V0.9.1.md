# C 轨研究启动与开放探索输出标准 V0.9.1

> **V0.9.1 修订说明**：本版本接入 `C轨独立DB与开放研究深度补充修订说明_V1.0.md`。核心变化：C-Open 第一版是正式 pre-scoring research pack；C-Open 与 C-Paper 使用同等搜索深度；新增统一 taxonomy、search coverage stats、factor readiness stats、结构化 supplement request + `freeform_agent_note`；C 轨改为独立 DB，A/B `research.db` 只能只读参考。

> **现行开放检索补充（2026-07-20）**：对新近、证据稀疏、可能改变概率或财务判断的任务，搜索资源必须随新颖性、时效性、不确定性和决策重要性增加。执行“大胆搜索、小心求证”：弱媒体、公众号、论坛、社媒、招聘和展会材料可以用于发现可核验线索，但不得直接升级为核心事实；必须追溯最早出处、核对主体/产品/时间/数量、寻找跨链独立侧证并主动搜索冲突。多方反复提及但仍无法验证的重要线索应保留、降档、解释和监控，不静默删除，也不进入核心评分、概率事实更新或财务模型事实输入。


**目标读者**：架构设计师、工程师、Agent 开发者、策略师、行业研究员。  
**适用系统**：`industry_demo` 行研工作台中的 C 轨“供需失衡机会扫描”。  
**配套文档**：`C轨供需失衡评分流程与可解释计算体系_V0.8.md`。  
**本文定位**：定义 C 轨在进入 V0.8 评分系统之前的研究启动、开放探索、资料增强、全网 文献综述、候选发现、数据充足度判断、补充资料建议和评分交接标准。本文不重新定义 V0.8 的 14 个因子包、slot 评分、因子聚合和总分模型，只定义“如何把开放问题研究到足以进入 V0.8”。

---

## 0. 核心结论

C 轨不能被设计成“用户给一个标题，Agent 直接生成最终报告”。现实工作流更常见的是：

```text
开放研究问题
  ↓
全球多语言 文献综述
  ↓
候选环节 / 材料 / 公司发现
  ↓
证据和数据可得性判断
  ↓
补充资料建议
  ↓
满足条件后再进入 V0.8 可解释评分
```

因此，C 轨应拆成两个运行模式：

| 模式 | 适用情况 | 第一阶段目标 | 是否直接评分 |
|---|---|---|---|
| `C-Open` | 没有系统性研报 / 数据库资料，或问题很开放、候选范围不清楚 | 做高质量探索研究，找候选、找证据、判断数据充足度、提出补充资料建议 | 只有通过 Scoring Readiness Gate 后才进入评分 |
| `C-Paper` | 用户提供研究问题 + papers/研报/数据库材料 | 把 papers 当作 seed，先抽取 claims，再独立联网核验、更新、补充，并判断是否足够评分 | 可评分或暂缓评分，取决于覆盖率和审计结果 |

第一阶段输出不是草稿，也不是简单“方向性摘要”。它应按正式研究包标准输出：

```text
问题拆解
+ 全网独立搜索
+ 候选发现
+ 证据表
+ 数据充足度判断
+ 初步研究判断
+ 补充资料建议
+ 是否进入 V0.8 评分的交接结论
```

但它也不是 V0.8 正式评分报告。它的结论必须清楚标注：

```text
正式评分前研究 / pre-scoring research pack
```

---

## 1. 和 V0.8 的边界关系

### 1.1 V0.8 负责什么

V0.8 负责正式评分和可解释计算链路：

```text
industry_data_point
  ↓
metric_slot preprocessing
  ↓
slot_score
  ↓
factor_bundle aggregation
  ↓
segment_imbalance_score / company_capture_score
  ↓
market_reflection_state
  ↓
research_bias_label
```

V0.8 定义：

```text
1. 14 个一级评分因子包；
2. 4 个市场反应因子；
3. 5 个一票否决项；
4. slot 级预处理、归一化、离群值处理；
5. factor 聚合；
6. coverage / confidence / audit 调整；
7. final score、research priority 和 research bias label。
```

### 1.2 本文负责什么

本文负责评分前的研究启动和探索阶段：

```text
1. 用户问题如何进入系统；
2. 如何自动判定 C-Open / C-Paper；
3. 开放问题如何拆解；
4. 如何做全球多语言 文献综述；
5. 如何发现候选材料、环节、公司；
6. 如何把搜索结果转成可审计 claim / source / evidence；
7. 如何判断某个候选是否足够进入 V0.8；
8. 如何输出补充资料建议；
9. 如何把结果 handoff 给 V0.8。
```

### 1.3 接口原则

本文必须遵守以下接口约束：

```text
1. 不改变 V0.8 的评分因子、权重和计算逻辑；
2. 使用与 V0.8 一致的 run_id、entity_id、factor_code、source_id、data_point_id；
3. C-Open / C-Paper 只产生 readiness、candidate、claim、source map、supplement request 和 handoff package；
4. 只有进入 V0.8 后，才生成正式 slot_score、factor_score、composite_score；
5. pre-scoring 阶段可以给 preliminary_priority，但不能伪装成正式分数；
6. 所有关键 claim 必须能回到 source、URL、PDF、page 或 source_excerpt。
```

---

## 2. 模式判定

### 2.1 输入自动分类

系统接到任务后，第一步必须执行 `mode_classification`。不要直接写报告，也不要直接评分。

| 输入情况 | 运行模式 | 处理方式 |
|---|---|---|
| 只有一个开放问题，没有 papers | `C-Open` | 先做全球 文献综述 和候选发现 |
| 问题很大，候选范围不清楚 | `C-Open` | 先做 taxonomy 和子问题拆解 |
| 用户给了少量截图、链接或口头线索 | `C-Open with seed` | 把线索当 seed，但仍独立搜索 |
| 用户给了研究问题 + papers/研报文件夹 | `C-Paper` | papers 抽取 + 独立联网核验 |
| 用户给了完整候选集合 + 完整 papers | `C-Paper scoring-ready candidate` | 仍先审计，再判断是否可评分 |
| 用户只说“帮我写一份报告” | `needs_problem_rewrite` | 自动改写成研究问题；必要时提示用户补范围 |

### 2.2 自动判定输出

每次 run 开头必须输出：

```text
mode = C-Open / C-Paper / C-Open with seed / needs_problem_rewrite
mode_reason = 为什么这样判定
initial_scoring_allowed = yes / no / conditional
required_next_step = lit_review / paper_claim_extraction / scoring_readiness_gate / scope_narrowing
```

示例：

```text
本任务判定为 C-Open。
原因：用户只提出开放研究问题，未提供系统性 papers/研报文件夹，候选材料和公司范围未定。
因此第一阶段输出为 pre-scoring research pack，不直接生成正式评分。
```

---

## 3. 标准输入结构

### 3.1 用户最小输入

系统必须能接受非常短的问题，例如：

```text
未来 12 个月，全球存储上游哪些材料可能出现供需失衡？
```

当输入很短时，Agent 应自动补全默认值：

| 字段 | 默认值 |
|---|---|
| `run_mode` | 自动判定 |
| `geo_scope` | global，多语言 |
| `core_window_months` | 12 |
| `long_term_context_window` | 2-3 年，只作为背景 |
| `source_policy` | 公开全网 + 平台 DB + papers/数据库若有 |
| `scoring_policy` | 通过 readiness gate 后才评分 |

### 3.2 推荐完整输入模板

```text
【任务模式】
C-Open / C-Paper / 由系统判断

【核心问题】
一句话说明要回答什么。

【研究对象】
行业 / 细分环节 / 材料品类 / 公司 / 股票。

【时间窗口】
核心判断窗口：未来 3/6/12 个月。
长期背景窗口：未来 2-3 年，仅作背景。

【地理范围】
全球 / 中国 / 美国 / 日本 / 韩国 / 欧洲 / 多语言全网。

【候选范围】
如已有候选则列出；如没有，允许系统自行发现。

【已有资料】
无 / 少量链接 / papers 文件夹 / 平台已有 DB / 指定数据库。

【输出目标】
方向判断 / 候选清单 / 可评分性判断 / 正式评分 / 公司排序 / 催化剂图谱 / 补充资料建议。

【约束】
必须做独立全网 文献综述；研报和数据库只作补充；关键结论必须有来源；覆盖不足不得强评分。
```

### 3.3 系统内部任务请求 JSON

```json
{
  "task_name": "global_storage_upstream_materials_copen",
  "user_question": "未来12个月全球存储上游哪些材料可能出现供需失衡？",
  "run_mode": "auto",
  "research_object_level": ["industry", "segment", "product", "company"],
  "geo_scope": ["global", "china", "japan", "korea", "us", "europe"],
  "language_scope": ["zh", "en", "ja", "ko"],
  "core_window_months": 12,
  "long_term_context_years": 3,
  "seed_materials": [],
  "candidate_entities": [],
  "required_output": [
    "problem_decomposition",
    "source_map",
    "candidate_taxonomy",
    "evidence_table",
    "factor_readiness_matrix",
    "supplement_request",
    "scoring_readiness_gate"
  ],
  "v08_scoring_allowed": "after_readiness_gate"
}
```

---

## 4. C-Open 工作流

### 4.1 总体架构

```text
User Question
  ↓
Mode Classifier
  ↓
Problem Decomposer
  ↓
Global 文献综述 Planner
  ↓
Source Discovery Executor
  ↓
Candidate Taxonomy Builder
  ↓
Claim & Evidence Extractor
  ↓
Factor Readiness Mapper
  ↓
Data Sufficiency Gate
  ↓
Supplement Request Generator
  ↓
C-Open Research Pack
  ↓
V0.8 Handoff Package, if ready
```

### 4.2 Step 1 — 问题拆解

目标：把开放问题拆成可搜索、可验证、可评分的子问题。

必须输出：

| 字段 | 说明 |
|---|---|
| `primary_question` | 原始核心问题 |
| `decision_use_case` | 用于方向探索、候选筛选、评分、动态跟踪还是专题研究 |
| `entity_scope` | 行业、环节、材料、公司、股票中的哪些层级 |
| `geography_scope` | 全球/地区口径 |
| `time_window` | 当前判断窗口和长期背景窗口 |
| `must_answer_questions` | 必须回答的问题 |
| `deferred_questions` | 不在第一阶段回答的问题 |

问题拆解模板：

```text
1. 需求触发是否存在？
2. 供给约束是否存在？
3. 是否出现价格、贸易流、产能、政策或事件信号？
4. 有哪些候选材料/环节？
5. 有哪些全球和中国相关公司？
6. 市场是否已经交易？
7. 数据是否足够进入正式评分？
8. 还缺哪些权威资料？
```

### 4.3 Step 2 — 全球多语言 文献综述 计划

C-Open 的 文献综述 不能只搜中文，也不能只搜研报标题。必须按“产业链问题 × 来源层级 × 语言地区”生成 search plan。

#### 4.3.1 Source Ladder

| 层级 | 来源类型 | 用途 |
|---|---|---|
| S | 公司公告、交易所文件、年报、季报、招股书、IR、公司官网、政府/海关/监管公告 | 核心事实、产能、财务、政策、正式事件 |
| A | WSTS/SIA、SEMI、USGS、行业协会、官方统计、权威数据库 | 行业周期、原材料、设备周期、需求代理 |
| B | Reuters、Nikkei、The Elec、Digitimes、TrendForce、DRAMeXchange、可信产业媒体 | 及时事件、价格、供需扰动、产业链变化 |
| C | 券商研报、Alpha Pi、进门财经、专家访谈 | 细分框架、解释、历史数据、候选补充 |
| D | KOL、自媒体、微博、雪球、X、小作文 | 只做线索、市场热度和待核验事件 |

Source Ladder 约束的是“证据能支持到哪里”，不是“搜索时能不能看”。D 级及其他非权威来源应在新近任务中主动进入 discovery：先提取专利号、文件名、产品规格、客户称谓、地点、日期、数量、图片文字和引用机构，再向原始专利、公告、展会主办方、公司/客户/供应商、政府项目、设备与财务链回溯。回溯成功后，正式证据登记原始来源；回溯失败时，D 级来源仍只保留为线索。

对于每条可能改变核心结论的新近主张，search plan 必须包含：

```text
1. origin_trace：寻找最早可见出处和后续转载链；
2. claim_identity_check：核对主体、产品、时间、数量与适用场景；
3. cross_chain_corroboration：从公司、客户、供应商、专利、招聘、设备、政府、展会中寻找独立侧证；
4. contradiction_search：寻找否认、官方沉默、口径冲突、替代解释和时间不一致；
5. decision_impact：判断若属实或不属实会改变哪个概率、财务或监控结论。
```

网页数量不得代替独立性。若多篇文章共享同一数字、同一措辞、同一图片、同一卖方报告或同一匿名产业链消息，它们只形成一个 `independence_key`。

#### 4.3.2 搜索维度

每个开放问题至少覆盖以下搜索维度：

| 维度 | 搜索目标 |
|---|---|
| Demand trigger | 下游价格、CapEx、扩产、产出、技术强度变化 |
| Supply constraint | 产能、原料、政策、供应商结构、替代性 |
| Timely signal | 材料价格、调价公告、海关量价、供应扰动、事故、限供 |
| Company capture | 公司敞口、客户验证、收入敞口、产能窗口、财务质量 |
| Market reaction | 股价、估值、热度、新闻/KOL 关注度 |
| Risk / veto | 替代、产能洪水、客户自研、政策反向、失衡不足 |

#### 4.3.3 多语言策略

| 语言 | 适用区域 | 典型用途 |
|---|---|---|
| 中文 | 中国大陆、台港 | A 股、国产替代、国内客户、公告、巨潮、交易所 |
| 英文 | 全球 | Reuters、SEMI、WSTS/SIA、USGS、国际公司、全球数据库 |
| 日文 | 日本 | 化学品、光刻胶、材料供应商、公司官网、IR |
| 韩文 | 韩国 | 存储、HBM、SK hynix、Samsung、The Elec、韩国供应链 |
| 德/法 | 欧洲 | Merck、Air Liquide、BASF 等材料/气体公司 |

C-Open 不要求每种语言都一定抓到数据，但必须记录搜索覆盖情况：

```text
language_attempted = yes / no
useful_sources_found = integer
coverage_gap_reason = not_searched / no_results / paywalled / stale / irrelevant
```

### 4.4 Step 3 — Source Discovery 执行

搜索结果不能直接变成结论。每个发现的来源先进入 source discovery list。

每条记录必须包含：

| 字段 | 说明 |
|---|---|
| `title` | 来源标题 |
| `url_or_file` | URL 或文件路径 |
| `publisher` | 发布方 |
| `language` | 语言 |
| `source_type` | announcement / database / media / research_report / transcript / official_statistics 等 |
| `prelim_source_tier` | S/A/B/C/D 初步分级 |
| `publish_date` | 发布时间 |
| `freshness_days` | 与数据截止日距离 |
| `relevance_reason` | 为什么相关 |
| `candidate_claims_count` | 可抽取 claim 数 |
| `source_ingest_status` | discovered / inserted_to_source / rejected / duplicate / paywalled |

只有通过初步 source review 的来源才进入平台 `source` 表或作为已有 `source_id` 复用。

### 4.5 Step 4 — 候选 taxonomy 构建

C-Open 必须避免一开始就被用户给的候选集合锁死。系统应先构建 taxonomy，再生成候选长名单。

Taxonomy 层级：

```text
macro_theme
  → industry
  → segment
  → product_or_material
  → process_step
  → application
  → company
  → security / ticker
```

候选实体字段：

| 字段 | 说明 |
|---|---|
| `entity_type` | industry / segment / product / company / security |
| `entity_name` | 候选名称 |
| `parent_entity_id` | 上级实体 |
| `geo_scope` | global / china / japan / korea / us / europe |
| `application` | 下游应用 |
| `why_included` | 纳入理由 |
| `evidence_count` | 已有证据数 |
| `source_tier_best` | 最高来源等级 |
| `discovery_path` | 从哪个搜索维度发现 |
| `inclusion_status` | included / watch / rejected / duplicate |

Candidate longlist 不等于 scoring universe。只有通过数据充足度判断后，才能进入 V0.8 scoring universe。

### 4.6 Step 5 — Claim & Evidence 抽取

C-Open 第一阶段必须输出 claim 表。Claim 是评分前研究的最小可审计判断单元。

Claim 类型：

```text
需求触发 claim
供给约束 claim
价格/事件 claim
公司承接 claim
市场反应 claim
风险/否决 claim
背景/解释 claim
预测/观点 claim
```

Claim 字段：

| 字段 | 说明 |
|---|---|
| `claim_text` | 原始或标准化后的 claim |
| `claim_type` | demand / supply / signal / company / market / risk / background / forecast |
| `entity_id` | 关联候选实体 |
| `factor_code_candidate` | 可能映射到 V0.8 哪个 factor |
| `polarity` | positive / negative / neutral / mixed |
| `fact_or_forecast` | fact / forecast / opinion / event / estimate |
| `source_id` | 来源 ID |
| `source_excerpt` | 原文证据 |
| `period_or_as_of_date` | 时间口径 |
| `evidence_status` | usable / weak / conflict / stale / not_enough_for_scoring |
| `next_action` | ingest_data_point / event_ledger / reference_only / reject / human_review |

关键规则：

```text
1. Claim 不等于 data point。
2. 数字 claim 通过审查后可以写入 industry_data_point。
3. 文字事件 claim 通过审查后进入 event_ledger。
4. 预测/观点 claim 只能进入 forecast_overlay 或 background。
5. 无原文或无法回链的 claim 不得进入评分。
```

### 4.7 Step 6 — Factor Readiness 映射

C-Open 不直接打 V0.8 分数，但必须判断每个候选是否具备 V0.8 评分条件。

对每个候选实体，按 V0.8 的 factor bundle 做 readiness，而不是打分。

Readiness 状态：

| readiness | 含义 |
|---|---|
| `ready` | 数据和来源足够进入 V0.8 正式评分 |
| `partial` | 可以生成低置信临时判断，但不宜强结论 |
| `insufficient` | 数据不足，不能评分 |
| `blocked_by_conflict` | 有高严重性冲突，必须人工核验 |
| `not_applicable` | 该因子对该实体不适用 |

Factor readiness 字段：

| 字段 | 说明 |
|---|---|
| `factor_code` | V0.8 factor code |
| `available_claim_count` | 可用 claim 数 |
| `available_data_point_count` | 可用数据点数 |
| `recent_evidence_count` | 近期证据数 |
| `best_source_tier` | 最高来源等级 |
| `independent_source_count` | 独立来源数量 |
| `freshness_status` | fresh / acceptable / stale / unknown |
| `estimated_coverage_pct` | 粗略覆盖率估计 |
| `readiness_status` | ready / partial / insufficient / blocked_by_conflict / not_applicable |
| `blocker_reason` | 阻断原因 |
| `handoff_allowed` | 是否允许进入 V0.8 |

注意：`estimated_coverage_pct` 不是 V0.8 的正式 factor_coverage。它只是 pre-scoring readiness 指标。

### 4.8 Step 7 — Scoring Readiness Gate

正式进入 V0.8 之前，必须通过 readiness gate。

| 条件 | 要求 |
|---|---|
| 核心问题已拆解 | 必须 |
| 候选 taxonomy 已建立 | 必须 |
| 至少有一个 S/A/B/C 级可回链来源 | 必须 |
| 关键候选的 factor readiness ≥ 50% | 建议最低门槛 |
| 无 unresolved high-severity conflict | 必须 |
| 至少存在一个近期信号 | 价格、事件、公告、市场反应、政策等至少一种 |
| 公司承接任务中，公司与环节关系可证实 | 必须 |
| 市场反应数据可取 | 公司层评分时必须 |

Readiness Gate 输出：

| gate_status | 处理 |
|---|---|
| `score_ready` | 可进入 V0.8 正式评分 |
| `score_limited` | 可做临时评分，但必须标低覆盖/低置信，不给强结论 |
| `research_only` | 只输出研究判断和补充资料建议 |
| `blocked` | 需要人工核验或补资料后重跑 |

### 4.9 C-Open 研究深度与停止条件

C-Open 第一阶段必须按正式研究包标准执行，不允许只给“方向性草稿”。但它也不能无限搜索。系统应使用“最低覆盖要求 + 边际收益停止条件”。

搜索资源不是固定配额。对于发布日期很近、既有研报尚未覆盖、公开口径相互冲突或一旦属实会显著改变结论的主张，应增加来源类型、语言、时间切片和反向查询；已有 papers、用户 seed 或达到最低来源数不能作为停止理由。只有关键主张已完成 origin trace、跨链核验和反证搜索后，边际收益停止条件才可生效。

重要但仍未验证的线索必须进入内部 claim/evidence 表和公开研究中的自然语言说明，至少记录：具体说法、最早可见出处、独立来源组、支持/冲突、已查范围、缺失证据、当前降档角色、如果属实对结论的方向性影响。推荐状态为 `material_unverified_lead`，其用途只能是 `weak_signal`、`reference_only`、补证优先级或不确定性边界；不得进入核心评分、把专家概率直接加点或作为财务模型事实输入。

#### 4.9.1 最低覆盖要求

全球开放问题至少应尝试覆盖：

| 维度 | 最低要求 | 说明 |
|---|---|---|
| 语言 | 至少中文 + 英文；若产业链核心在日本/韩国，则必须尝试日文/韩文 | 例如存储、材料、化学品通常需要日/韩源 |
| 来源层级 | 至少覆盖 S/A/B 三类来源中的两类 | 不能只看研报或只看媒体 |
| 候选层级 | 至少形成 industry → segment → product/material → company 四层 taxonomy | 不直接从公司排序开始 |
| 近期证据 | 每个高优先候选至少尝试寻找 30/60/90 天内的价格、公告、事件或市场数据 | 如果找不到，必须说明缺口 |
| 反证搜索 | 对 Top 候选必须搜索替代、扩产、客户自研、价格回落、公司澄清等反向证据 | 防止只抓利好 |
| 市场反应 | 公司层候选必须检查股价、估值、成交/热度是否已经反应 | 市场反应不改变基本面，但影响研究优先级 |

#### 4.9.2 边际收益停止条件

C-Open 不要求无限搜索。满足以下任一条件，可以停止第一阶段搜索并输出：

```text
1. Top 候选的新增搜索不再产生新候选或新高可信证据；
2. 连续两轮 search_log 的 useful_result_count 明显下降；
3. 关键缺口已确认主要来自付费数据库、公司不披露或需要人工调研；
4. 已经能明确给出 score_ready / score_limited / research_only / blocked；
5. 搜索继续扩张会显著偏离原研究问题。
```

#### 4.9.3 第一阶段也必须有研究判断

即使暂不进入 V0.8 正式评分，C-Open 也必须输出尽可能深入的研究判断：

```text
- 哪些候选最值得继续研究；
- 为什么它们可能存在供需失衡；
- 哪些证据已经较强；
- 哪些证据仍弱；
- 哪些方向被排除；
- 需要补哪些资料才能进入评分。
```

禁止把 C-Open 写成只有“需要更多资料”的空泛总结。

---

## 5. C-Paper 工作流

C-Paper 用于用户提供 papers/研报文件夹的情况。Papers 是 seed，不是事实终点。

### 5.1 架构

```text
User Question + Papers Folder
  ↓
Paper Intake
  ↓
Claim Extraction from Papers
  ↓
Paper Source Review
  ↓
Independent Global 文献综述
  ↓
Claim Verification / Update / Conflict Detection
  ↓
Candidate Expansion
  ↓
Factor Readiness Mapping
  ↓
Scoring Readiness Gate
  ↓
V0.8 Handoff or Supplement Request
```

### 5.2 Papers 的用途

| 用途 | 是否允许 |
|---|---:|
| 提供产业链框架 | 是 |
| 提供候选材料/公司 | 是 |
| 提供历史数据和卖方观点 | 是 |
| 作为唯一事实来源 | 否 |
| 直接继承其评分结论 | 否 |
| 直接继承其配置建议/仓位建议 | 否 |
| 作为 claim seed 进入审计 | 是 |

### 5.3 Papers claim extraction 字段

| 字段 | 说明 |
|---|---|
| `paper_source_id` | 研报 source_id |
| `page_no` | 页码 |
| `claim_text` | 抽取 claim |
| `claim_type` | demand / supply / company / market / event / forecast |
| `metric_candidate` | 可能对应指标 |
| `value_num / value_text` | 数值或文本 |
| `period` | 口径时间 |
| `source_excerpt` | 原文片段 |
| `requires_external_verification` | 是否需外部核验 |
| `paper_claim_status` | usable_seed / stale / unsupported / conflict / reject |

### 5.4 C-Paper 输出差异

C-Paper 比 C-Open 多三张表：

```text
1. papers_claim_extraction 表；
2. papers_claim_verification 表；
3. papers_vs_external_conflict 表。
```

但最终仍输出同样的 readiness gate 和 handoff package。

---

## 6. C-Open / C-Paper 输出标准

### 6.1 输出不是草稿

第一阶段输出应按正式研究包标准写作，不能用“粗略看看”“初步随便排”这种方式。它应满足：

```text
1. 有清晰结论；
2. 有证据表；
3. 有候选 taxonomy；
4. 有数据充足度判断；
5. 有 source map；
6. 有 supplement request；
7. 有进入 V0.8 或暂缓评分的明确理由。
```

### 6.2 标准章节结构

```text
# C-Open / C-Paper Pre-Scoring Research Pack

## 1. 任务判定
## 2. 研究问题拆解
## 3. 研究范围与排除范围
## 4. 全球 文献综述 覆盖情况
## 5. Source Map
## 6. 候选 taxonomy 与长名单
## 7. 核心发现与证据
## 8. Factor Readiness Matrix
## 9. 初步研究优先级
## 10. 数据缺口和补充资料建议
## 11. Scoring Readiness Gate
## 12. V0.8 Handoff Package
## 13. 审计问题与人工核验项
## Appendix A. Search Log
## Appendix B. Claim & Evidence Table
## Appendix C. Source Review Notes
```

### 6.3 初步研究优先级

C-Open 允许输出“初步研究优先级”，但不能输出正式评分。

允许枚举：

```text
high_priority_for_scoring
medium_priority_for_followup
low_priority_watch
research_only_insufficient_data
reject_or_out_of_scope
```

禁止输出：

```text
S/A/B/C/D 正式评级
最终总分
买入/卖出
仓位比例
目标价
```

如确实通过 readiness gate 并进入 V0.8，正式评分应在 V0.8 输出区单独生成。

### 6.4 补充资料建议输出

Supplement Request 不是泛泛说“建议补资料”。每一条必须说明：

| 字段 | 说明 |
|---|---|
| `request_type` | research_report / database / company_filing / price_data / customs_data / transcript / expert_call / internal_note |
| `target_question` | 要解决哪个研究问题 |
| `target_factor_code` | 对应 V0.8 哪个因子 |
| `why_needed` | 为什么当前数据不足 |
| `suggested_sources` | 建议找哪些源 |
| `priority` | P0 / P1 / P2 |
| `required_for_scoring` | yes / no |
| `expected_impact` | 能显著改变排序 / 只提高置信度 / 只作背景 |
| `acceptable_alternative` | 没有该资料时可用什么替代 |

示例：

```text
request_type: price_data
目标问题: WF6 价格上涨是否仍在持续
target_factor_code: signal.material_price_momentum
why_needed: 当前只找到媒体报价和旧研报价格，缺少近 30-60 天可复核价格代理
suggested_sources: 海关出口均价、产业价格库、公司调价公告、TrendForce/DRAMeXchange
priority: P0
required_for_scoring: yes
expected_impact: 影响材料价格动量因子和 readiness gate
acceptable_alternative: 若无价格数据库，可用海关均价 + 官方调价事件 + 多源媒体报价交叉验证
```

---

## 7. 数据结构设计

本节定义 C-Open / C-Paper 的 pre-scoring 数据结构。它与 V0.8 的评分表互相衔接，但不替代 V0.8 的 scoring tables。

### 7.1 `opportunity_run`

如 V0.6/V0.8 已定义 `opportunity_run`，则本表为其字段扩展要求；如未实现，可按以下字段创建。

```sql
CREATE TABLE IF NOT EXISTS opportunity_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name TEXT NOT NULL,
    run_mode TEXT NOT NULL CHECK(run_mode IN (
        'C_OPEN',
        'C_OPEN_WITH_SEED',
        'C_PAPER',
        'C_PAPER_SCORING_READY',
        'NEEDS_PROBLEM_REWRITE'
    )),
    run_stage TEXT NOT NULL CHECK(run_stage IN (
        'intake',
        'lit_review',
        'candidate_discovery',
        'readiness_review',
        'handoff_ready',
        'scoring_started',
        'closed'
    )),
    user_question TEXT NOT NULL,
    normalized_question TEXT,
    mode_reason TEXT,
    geo_scope_json TEXT,
    language_scope_json TEXT,
    core_window_months INTEGER DEFAULT 12,
    long_term_context_years INTEGER DEFAULT 3,
    data_cutoff_date TEXT,
    scoring_policy TEXT DEFAULT 'after_readiness_gate',
    status TEXT NOT NULL DEFAULT 'active',
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);
```

### 7.2 `opportunity_search_log`

记录每轮 文献综述 的搜索行为，解决“Agent 说搜过但不可复查”的问题。

```sql
CREATE TABLE IF NOT EXISTS opportunity_search_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    search_round INTEGER NOT NULL,
    query_text TEXT NOT NULL,
    query_language TEXT,
    target_region TEXT,
    target_source_type TEXT,
    search_engine_or_tool TEXT,
    searched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    result_count INTEGER,
    useful_result_count INTEGER,
    top_domains_json TEXT,
    search_status TEXT CHECK(search_status IN (
        'completed', 'no_useful_result', 'paywalled', 'failed', 'skipped'
    )),
    notes TEXT,
    FOREIGN KEY(run_id) REFERENCES opportunity_run(id)
);
```

### 7.3 `opportunity_source_discovery`

记录发现但未必已经入库为 `source` 的外部来源。

```sql
CREATE TABLE IF NOT EXISTS opportunity_source_discovery (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    source_id INTEGER,
    title TEXT NOT NULL,
    url_or_file TEXT,
    publisher TEXT,
    publish_date TEXT,
    language TEXT,
    source_type TEXT,
    prelim_source_tier TEXT CHECK(prelim_source_tier IN ('S','A','B','C','D','unknown')),
    is_primary_source INTEGER,
    relevance_reason TEXT,
    candidate_claims_count INTEGER DEFAULT 0,
    source_ingest_status TEXT CHECK(source_ingest_status IN (
        'discovered', 'inserted_to_source', 'duplicate', 'rejected', 'paywalled', 'pending_review'
    )),
    rejection_reason TEXT,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES opportunity_run(id)
);
```

### 7.4 `opportunity_candidate_entity`

记录 C-Open / C-Paper 发现的候选行业、环节、产品、公司。

```sql
CREATE TABLE IF NOT EXISTS opportunity_candidate_entity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL CHECK(entity_type IN (
        'industry', 'segment', 'product', 'company', 'security'
    )),
    entity_name TEXT NOT NULL,
    parent_candidate_id INTEGER,
    mapped_industry_id INTEGER,
    mapped_company_id INTEGER,
    ticker TEXT,
    geo_scope TEXT,
    application TEXT,
    process_step TEXT,
    why_included TEXT,
    discovery_path TEXT,
    evidence_count INTEGER DEFAULT 0,
    best_source_tier TEXT,
    inclusion_status TEXT CHECK(inclusion_status IN (
        'included', 'watch', 'rejected', 'duplicate', 'out_of_scope'
    )),
    v08_handoff_status TEXT CHECK(v08_handoff_status IN (
        'not_ready', 'ready_as_entity', 'merged_into_existing_entity', 'rejected'
    )),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES opportunity_run(id),
    FOREIGN KEY(parent_candidate_id) REFERENCES opportunity_candidate_entity(id)
);
```

### 7.5 `opportunity_claim_evidence`

C-Open / C-Paper 的核心表。所有初步判断先进入 claim，不直接变成评分。

```sql
CREATE TABLE IF NOT EXISTS opportunity_claim_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    candidate_entity_id INTEGER,
    claim_text TEXT NOT NULL,
    claim_type TEXT NOT NULL CHECK(claim_type IN (
        'demand', 'supply', 'signal', 'company', 'market', 'risk', 'background', 'forecast', 'event'
    )),
    factor_code_candidate TEXT,
    polarity TEXT CHECK(polarity IN ('positive','negative','neutral','mixed','unknown')),
    fact_or_forecast TEXT CHECK(fact_or_forecast IN ('fact','forecast','opinion','event','estimate','unknown')),
    value_num REAL,
    value_text TEXT,
    unit TEXT,
    period_or_as_of_date TEXT,
    source_id INTEGER,
    source_discovery_id INTEGER,
    source_excerpt TEXT,
    evidence_status TEXT CHECK(evidence_status IN (
        'usable',
        'weak',
        'conflict',
        'stale',
        'unsupported',
        'not_enough_for_scoring',
        'rejected'
    )),
    next_action TEXT CHECK(next_action IN (
        'ingest_data_point',
        'event_ledger',
        'reference_only',
        'human_review',
        'reject'
    )),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES opportunity_run(id),
    FOREIGN KEY(candidate_entity_id) REFERENCES opportunity_candidate_entity(id)
);
```

### 7.6 `opportunity_factor_readiness`

对接 V0.8 的核心接口表。它不存分数，只存可评分性。

```sql
CREATE TABLE IF NOT EXISTS opportunity_factor_readiness (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    candidate_entity_id INTEGER NOT NULL,
    factor_code TEXT NOT NULL,
    available_claim_count INTEGER DEFAULT 0,
    available_data_point_count INTEGER DEFAULT 0,
    recent_evidence_count INTEGER DEFAULT 0,
    independent_source_count INTEGER DEFAULT 0,
    best_source_tier TEXT,
    freshness_status TEXT CHECK(freshness_status IN ('fresh','acceptable','stale','unknown')),
    estimated_coverage_pct REAL,
    readiness_status TEXT CHECK(readiness_status IN (
        'ready',
        'partial',
        'insufficient',
        'blocked_by_conflict',
        'not_applicable'
    )),
    blocker_reason TEXT,
    handoff_allowed INTEGER DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES opportunity_run(id),
    FOREIGN KEY(candidate_entity_id) REFERENCES opportunity_candidate_entity(id)
);
```

### 7.7 `opportunity_supplement_request`

补充资料建议必须结构化，便于研究员补材料后重跑。

```sql
CREATE TABLE IF NOT EXISTS opportunity_supplement_request (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    candidate_entity_id INTEGER,
    request_type TEXT NOT NULL CHECK(request_type IN (
        'research_report',
        'database',
        'company_filing',
        'price_data',
        'customs_data',
        'transcript',
        'expert_call',
        'internal_note',
        'market_data',
        'other'
    )),
    target_question TEXT NOT NULL,
    target_factor_code TEXT,
    why_needed TEXT NOT NULL,
    suggested_sources TEXT,
    priority TEXT CHECK(priority IN ('P0','P1','P2')),
    required_for_scoring INTEGER DEFAULT 0,
    expected_impact TEXT CHECK(expected_impact IN (
        'may_change_ranking',
        'improve_confidence',
        'background_only',
        'resolve_conflict'
    )),
    acceptable_alternative TEXT,
    status TEXT DEFAULT 'open' CHECK(status IN ('open','fulfilled','waived','obsolete')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES opportunity_run(id),
    FOREIGN KEY(candidate_entity_id) REFERENCES opportunity_candidate_entity(id)
);
```

### 7.8 `opportunity_handoff_package`

将 pre-scoring 研究交给 V0.8 scoring engine。

```sql
CREATE TABLE IF NOT EXISTS opportunity_handoff_package (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    handoff_status TEXT CHECK(handoff_status IN (
        'score_ready',
        'score_limited',
        'research_only',
        'blocked'
    )),
    scoring_version TEXT,
    ready_entity_count INTEGER DEFAULT 0,
    partial_entity_count INTEGER DEFAULT 0,
    blocked_entity_count INTEGER DEFAULT 0,
    ready_entities_json TEXT,
    blocked_reasons_json TEXT,
    supplement_request_ids_json TEXT,
    handoff_notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES opportunity_run(id)
);
```

### 7.9 `opportunity_agent_review_log`

记录审核 loop 的问题和修正。

```sql
CREATE TABLE IF NOT EXISTS opportunity_agent_review_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    review_round INTEGER NOT NULL,
    reviewer_role TEXT NOT NULL CHECK(reviewer_role IN (
        'strategist', 'architect', 'engineer', 'researcher', 'data_auditor', 'final_reviewer'
    )),
    question_or_issue TEXT NOT NULL,
    severity TEXT CHECK(severity IN ('high','medium','low')),
    resolution TEXT,
    status TEXT CHECK(status IN ('open','resolved','waived')) DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES opportunity_run(id)
);
```

---

## 8. 与现有平台数据层的关系

### 8.1 不绕开 `source + industry_data_point`

C-Open / C-Paper 发现的外部信息，不能直接写成最终结论。必须按以下路径处理：

```text
search result
  ↓
opportunity_source_discovery
  ↓
source review
  ↓
source 表或已有 source_id
  ↓
opportunity_claim_evidence
  ↓
可用数字 claim → write_data_point() → industry_data_point
可用事件 claim → event ledger
预测 / 观点 → forecast_overlay 或 reference only
  ↓
V0.8 metric_slot / factor_score, if ready
```

### 8.2 不重复 V0.8 数据结构

C-Open 只负责：

```text
1. 找候选；
2. 找证据；
3. 判断可评分性；
4. 输出补充资料建议；
5. 创建 handoff package。
```

V0.8 负责：

```text
1. 预处理数据；
2. slot 打分；
3. factor 聚合；
4. 覆盖率/置信度调整；
5. 总分输出；
6. 研究倾向标签。
```

### 8.3 Viewer 集成建议

新增页面建议：

```text
/c-open
/c-open/run/<run_id>
/c-open/run/<run_id>/sources
/c-open/run/<run_id>/candidates
/c-open/run/<run_id>/claims
/c-open/run/<run_id>/readiness
/c-open/run/<run_id>/supplement
/c-open/run/<run_id>/handoff
```

页面最重要的交互是：

```text
1. 从结论展开到 claim；
2. 从 claim 展开到 source_excerpt；
3. 从候选实体展开到 factor readiness；
4. 从 readiness 展开到缺口和补充资料建议；
5. 点击 handoff 查看哪些实体进入 V0.8。
```

---

## 9. Max 5 轮执行审核 Loop

每次 C-Open / C-Paper run 最多执行 5 轮审核。若前面轮次已经通过，可提前结束；若第 5 轮仍未通过，则输出 blocked / research_only，不得强行评分。

### Loop 1 — 策略师视角：问题和范围审核

审核问题：

```text
1. 用户问题是否过大？
2. 是否需要拆分成多个子问题？
3. 时间窗口是否明确？
4. 研究对象层级是否清楚？
5. 是否错误地从公司开始，而应该先从环节/材料开始？
```

可能修正：

```text
- 调整为全球品类扫描；
- 将公司排序后置；
- 把长期判断降为背景；
- 标注不适合直接评分。
```

### Loop 2 — Source / 文献综述 视角：搜索覆盖审核

审核问题：

```text
1. 是否只搜了中文？
2. 是否只用了研报？
3. 是否漏掉官方公告、公司官网、交易所、政府、海关、行业协会？
4. 是否漏掉日文/韩文/英文重要来源？
5. 是否把媒体报道当官方确认？
```

可能修正：

```text
- 增加多语言搜索；
- 增加官方和行业数据库源；
- 标注官方确认状态；
- 把弱来源降为线索。
```

### Loop 3 — 研究员视角：候选完整性审核

审核问题：

```text
1. 候选 taxonomy 是否完整？
2. 是否只找了 A 股，漏掉全球龙头？
3. 是否只找了热门公司，漏掉上游原料或海外供应商？
4. 是否遗漏反向证据？
5. 是否把主题映射公司当成真实承接公司？
```

可能修正：

```text
- 新增全球供应商；
- 新增替代品和客户自研风险；
- 把公司分层为直接供货 / 间接供货 / 原料受益 / 主题映射。
```

### Loop 4 — 工程师 / 数据质量视角：可入库性审核

审核问题：

```text
1. 每条 claim 是否有 source_excerpt？
2. 数字是否有单位、时间、口径？
3. 能否写入 industry_data_point？
4. 是否有不应入库的 AI 摘要或二手总结？
5. 是否存在明显单位、口径、时间冲突？
```

可能修正：

```text
- 拆分数字和文字 claim；
- 标注 not_enough_for_scoring；
- 建 supplement_request；
- 阻止进入 V0.8。
```

### Loop 5 — 最终审计视角：交接和输出审核

审核问题：

```text
1. 是否明确给出 readiness gate？
2. 是否有补充资料建议？
3. 是否把 preliminary priority 误写成正式评分？
4. 是否和 V0.8 接口一致？
5. 是否有未解决 high severity conflict？
```

可能修正：

```text
- 输出 research_only / score_limited / score_ready；
- 创建 handoff package；
- 把冲突项放入人工核验清单；
- 禁止正式评分。
```

---

## 10. 文档级 Max 2 审核记录

本节是本文自身的设计审核结果。审核目标是保证本文能同时被 Agent、架构师、工程师、研究员理解和落地。

### Review Round 1 — 架构 / 工程 / 研究三方审查

| 角色 | 问题 | 处理 |
|---|---|---|
| 架构师 | C-Open 和 V0.8 的边界是否清楚？ | 增加第 1 章，明确 C-Open 只做 readiness 和 handoff，不做评分模型 |
| 工程师 | 是否有可落地表结构？ | 增加第 7 章 DDL，覆盖 run、search、source discovery、candidate、claim、readiness、supplement、handoff、review log |
| 研究员 | 第一阶段是否会被误解为草稿？ | 增加第 6 章，明确 pre-scoring research pack 按正式研究包标准输出 |
| Agent 开发者 | 执行顺序是否明确？ | 增加第 4、5 章架构流程和模式分支 |

### Review Round 2 — V0.8 接口一致性审查

| 问题 | 修正 |
|---|---|
| 是否重复定义 V0.8 因子和评分？ | 删除具体评分阈值，只保留 factor readiness 和 handoff |
| 是否能复用 V0.8 的 factor_code？ | `opportunity_factor_readiness.factor_code` 使用 V0.8 factor code |
| 是否能从 C-Open 进入 V0.8？ | 增加 `opportunity_handoff_package` 和 readiness gate |
| 是否能处理 C-Paper？ | 增加第 5 章 papers claim extraction 和 verification |
| 是否能避免只靠研报？ | Source Ladder 和 文献综述 workflow 中强制独立全网搜索 |

本文在 Round 2 后通过：可作为 C 轨 pre-scoring 标准文档，与 V0.8 配套使用。

---

## 11. 标准 Prompt 模板

### 11.1 C-Open 标准 Prompt

```text
请按 C 轨 V0.9 执行一次 C-Open 开放探索研究。

【核心问题】
<写清楚开放研究问题>

【任务目标】
不是直接生成最终评分报告，而是按正式研究包标准完成：问题拆解、全球多语言 文献综述、候选发现、证据表、数据充足度判断、补充资料建议，并判断是否进入 V0.8 评分。

【研究范围】
<行业/环节/材料/公司/股票范围；若不确定，允许系统扩展候选>

【时间窗口】
核心窗口：未来 12 个月。
长期背景：未来 2-3 年，仅作背景，不进入正式评分。

【数据源策略】
先做全球多语言公开源搜索；优先公司公告、官网、交易所、政府/海关、行业协会、权威数据库、可信产业媒体；研报和数据库只作补充；KOL/自媒体只作线索。

【输出】
1. 任务判定；
2. 问题拆解；
3. 全球 文献综述 覆盖；
4. Source Map；
5. 候选 taxonomy 和长名单；
6. Claim & Evidence 表；
7. Factor Readiness Matrix；
8. 初步研究优先级；
9. 数据缺口和补充资料建议；
10. Scoring Readiness Gate；
11. V0.8 Handoff Package 或 blocked reason。

【禁止】
不直接输出正式评级、仓位、目标价或买卖建议。覆盖不足不得强评分。预测不得当事实。研报不得当唯一事实源。
```

### 11.2 C-Paper 标准 Prompt

```text
请按 C 轨 V0.9 执行一次 C-Paper 资料增强研究。

【核心问题】
<写清楚研究问题>

【输入资料】
我会提供 papers/研报文件夹。请把这些材料作为 seed，而不是事实终点。

【任务目标】
1. 从 papers 中抽取 claims、数据点、候选材料和公司；
2. 独立联网做全球多语言 文献综述；
3. 对 papers claims 做 source review 和 calculation review；
4. 更新、补充、纠错；
5. 判断是否足够进入 V0.8 评分；
6. 若不足，输出补充资料建议。

【输出】
1. papers claim extraction；
2. 外部核验结果；
3. 冲突和过期数据；
4. 新增外部证据；
5. Factor Readiness Matrix；
6. Supplement Request；
7. Scoring Readiness Gate；
8. V0.8 Handoff Package。
```

---

## 12. 示例：开放问题如何进入系统

### 12.1 不推荐输入

```text
帮我做一份全球存储行业最紧缺原材料报告。
```

问题：像报告标题，容易导致 Agent 直接写作，忽略候选发现和证据审计。

### 12.2 推荐输入

```text
未来 12 个月，全球存储上游哪些材料可能出现供需失衡？
请按 C-Open 先做全球多语言 文献综述、候选发现、数据可得性评估和补充资料建议。
若证据足够，再判断哪些候选可以进入 V0.8 正式评分。
```

### 12.3 期望第一阶段输出

```text
1. 本任务判定为 C-Open；
2. 已拆成需求、供给、价格/事件、公司承接、市场反应五组问题；
3. 已覆盖中文、英文、日文、韩文搜索；
4. 已形成材料品类 taxonomy；
5. 已给出候选材料长名单；
6. 已列出关键证据和 source；
7. 已判断哪些候选 score_ready、score_limited、research_only；
8. 已输出需要补充的研报、数据库、价格数据、公司文件；
9. 若 score_ready，则生成 V0.8 handoff package。
```

---

## 13. 成功标准

一次合格的 C-Open / C-Paper 输出必须满足：

```text
1. 明确模式判定；
2. 问题拆解完整；
3. 搜索覆盖不局限于国内和研报；
4. 候选发现有 taxonomy，不是拍脑袋长名单；
5. 所有关键 claim 有 source 或明确缺口；
6. 资料不足时明确说明，不强行评分；
7. 补充资料建议具体、可执行；
8. 与 V0.8 scoring engine 的 handoff 清晰；
9. 输出能被 viewer 展开到 source、claim、candidate、readiness、supplement；
10. 不输出仓位、目标价、买卖建议。
```

不合格输出包括：

```text
1. 直接写成最终报告；
2. 没有搜索覆盖记录；
3. 没有候选 taxonomy；
4. 没有补充资料建议；
5. 把 papers 结论当事实；
6. 把 preliminary priority 当正式评分；
7. 没有 readiness gate；
8. 无法和 V0.8 表结构或 factor_code 对接。
```

---

## 14. 最终定位

C-Open / C-Paper 是 C 轨的“研究启动与评分前审计层”。它的价值不是快速写一份看起来完整的报告，而是把一个开放问题变成：

```text
可解释的问题拆解
+ 可复查的全球证据地图
+ 可扩展的候选集合
+ 可判断的数据充足度
+ 可执行的补充资料需求
+ 可交接给 V0.8 的评分输入包
```

它和 V0.8 合起来构成完整 C 轨：

```text
C-Open / C-Paper V0.9
  负责：问题 → 候选 → 证据 → readiness → handoff

V0.8 Scoring Engine
  负责：data point → metric slot → factor score → composite score → market reaction → research bias
```



---

# 附录 A：V0.9.1 研究启动与 Handoff 修订

## A1. C-Open 研究深度升级

C-Open 第一版不是草稿。它必须按正式 pre-scoring research pack 输出，至少覆盖：

```text
问题拆解
search plan
全球多语言 source discovery
taxonomy
候选 long list / shortlist
claim/evidence table
factor readiness matrix
run/candidate 统计
supplement request
V0.8.1 handoff 判断
```

C-Open 与 C-Paper 的搜索深度相同。是否有 papers 不影响联网 文献综述 的强制性。

## A2. Search Axes 固定

所有 C-Open / C-Paper run 都必须覆盖以下 search axes：

| search_axis | 目标 |
|---|---|
| `taxonomy` | 找产业链结构、候选环节、材料、公司 |
| `demand` | 找需求触发：价格、CapEx、出货、应用强度 |
| `supply` | 找供给约束：产能、原料、政策、供应结构、替代难度 |
| `signal` | 找当前失衡信号：价格、招投标、海关、调价、限供、停产 |
| `company_capture` | 找公司承接：供货、收入敞口、产能、财务 |
| `market_reaction` | 找市场是否已反应：股价、估值、成交、热度 |
| `risk_contradiction` | 找反证：价格回落、扩产洪水、客户自研、澄清、否认 |
| `reference_background` | 找静态框架：研报、数据库、长期格局、技术路线 |

如果某 axis 不适用，必须记录 `not_applicable_reason`。

## A3. 统一 Taxonomy

C 轨 candidate entity 必须使用以下层级：

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

最低字段：

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
```

公司映射类型：

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

公司不得只凭 `theme_mapping_only` 进入高承接评分。

## A4. Run 与 Candidate 统计接口

V0.9.1 必须输出 run 级统计：

```text
total_search_queries
search_queries_by_language_json
search_queries_by_axis_json
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
event_count_total
audit_issue_count_total
supplement_request_count
ab_reference_count
stale_reference_ratio
run_readiness_status
```

Candidate 级统计：

```text
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

## A5. Supplement Request 结构

补充资料建议必须结构化，并保留自由文本字段。

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

`freeform_agent_note` 用于记录标准字段无法表达的研究建议，但不能替代结构化字段。

## A6. 独立 C DB 边界

V0.9.1 的输出默认写入独立 C 轨 DB，例如：

```text
data/opportunity.db
```

A/B 的 `research.db` 只能通过只读 reference 使用。所有来自 A/B 的参考数据必须标注：

```text
ab_db_name
ab_table_name
ab_row_id
ab_snapshot_at
ab_reference_usage
ab_reference_freshness_days
```

C 轨不得自动修改 A/B DB、docs、company_profile 或 industry_relation。

## A7. Handoff Package

进入 V0.8.1 前必须生成 handoff package：

```text
run_id
run_manifest_id
entity_shortlist
factor_readiness_matrix
claim_evidence_table
event_ledger_candidates
supplement_request_table
run_stats
candidate_stats
audit_issues
readiness_status
why_ready_or_not
```

`readiness_status`：

```text
scoring_ready
score_limited
research_only
blocked
```

如果 `research_only` 或 `blocked`，不得强行进入 V0.8.1 评分。
