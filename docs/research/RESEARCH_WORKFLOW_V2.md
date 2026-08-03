# A/B/C 研究工作流 V2

版本：`research.workflow.v2`  
机器契约：`config/research_workflow.yaml`  
适用范围：A 轨纯研报行研、B 轨 prompt 驱动行研、C 轨 Opportunity Lens。

## 1. 为什么重构

旧流程通过不断追加 prompt 和 reviewer 角色，成功解决过造数、错引、模板化、漏 prompt、财务空表、理论问题误评分和页面不可读等问题。但规则分散在多份 SOP、补丁 prompt、skills、上下文和专题构建器中，导致三个后果：

1. 每次任务都重复读取历史补丁，输入上下文远大于当前问题；
2. 机械检查和高阶判断混在同一 agent loop，简单错误也消耗完整审稿 prompt；
3. “规范存在”“构建器自报通过”“独立 reviewer 已执行”三种事实容易混淆。

V2 不降低研究深度。它把防错要求收敛为机器门禁，把研究判断留给 agent，把审查改为按风险触发，并要求发布证据可追溯。

## 2. 三层活动契约

1. `config/research_workflow.yaml`：唯一机器可读门槛，代码直接读取。
2. 本文件：解释流程、目的、判断方法和兼容边界。
3. `AGENTS.md`：Fresh Session 入口、红线和任务路由。

其余旧 SOP、设计、补丁、完成报告和 `PROGRESS_LOG.md` 是历史证据。只有追溯某项设计原因时才读，不进入默认上下文。

## 3. 共同工作流

```text
Intake
  -> ResearchBrief
  -> Search / Source registration
  -> Extraction / Structured evidence
  -> Analysis / Calculation ledger
  -> Writing / Visualization
  -> Deterministic gates
  -> Risk-adaptive review
  -> Integrated final review
  -> Stage
  -> Publish gate
```

### 3.1 ResearchBrief

输入只解析一次，形成结构化 `ResearchBrief`：

- 主问题和决策用途；
- 必答问题；
- 地区、产品、公司、时间和口径范围；
- 必须包含、必须排除；
- 用户指定的最低数据与正文深度；
- 输出 artifact；
- 每项要求的来源是默认 coverage、用户 prompt，还是两者重合。

B 轨按“用户 prompt 全集 + A 轨默认 coverage”取并集。编译器只自动合并规范化后完全相同的要求；语义相近项可以在 requirement matrix 中建立关联，但不能由字符串或模型判断直接删除，以免漏掉 prompt 独有问题。

Brief 保存要求本身，execution manifest 保存逐项执行状态。每项 requirement 必须标为 `pending`、`completed`、`completed_with_limitation` 或 `blocked`，并关联产物和证据；`completed_with_limitation` 必须说明已查范围、客观缺口和结论影响。`pending/blocked` 会阻止发布，不能用总报告已生成替代逐项覆盖。

共享执行入口是 `tools/research_core/workflow.py::ResearchWorkflowRun`。它只负责 brief、artifact hash、gate、review plan 和 manifest，不包含行业标题、结论句式或固定研究模板。结构化 request JSON 可用以下命令初始化：

```powershell
python -m tools.research_core.workflow <request.json> --run-dir cache/research_runs/<run_key>
```

A/B 统一 ingest 已直接接入该接口。每次入库同时生成 brief/manifest、输入 hash、五项 gate 和 review plan。B 轨正式入库使用 `--workflow-request <request.json>`；为兼容旧命令，缺少 request 时仍可暂存数据，但 manifest 会把补录原始 prompt 标为 blocked 并把 contract gate 置为 RED，因此不能发布。相同 tag 重跑会先把旧 brief/manifest 复制到 `history/`。

### 3.2 搜索和缓存

- 先按问题拆搜索方向，再判断哪些方向真正独立、适合并行；不机械地为每条提示启动 subagent。
- 每个第一轮问题轴必须同时生成相互独立的 `report` 与 `web` 任务：研报/本地 papers 与公司公告、IR、监管、协会、权威媒体等网络来源分别检索、抽取、去重和登记 `source_channel`，一边命中不得降低另一边预算。第一轮分析后只有明确 gap 才生成第二轮任务，且每个第二轮任务必须记录触发它的 `gap_trigger`。
- `report` 链可以使用已授权的萝卜投研网页库，但只能通过 Playwright 驱动正常网页界面，不调用、逆向或绕过站点 API。账号和密码通过本机遮罩输入框直接写入 Windows Credential Manager，由 `keyring` 的 `WinVaultKeyring` 后端调用；不得经聊天、命令行参数、环境变量或项目文件传递。浏览器登录态只保存在 `tools/dynamic/secrets/datayes_profile_v2`，不得进入 Git、广播包、日志、manifest 或研究正文。公司研报按标题检索并默认限定最近 183 天；行业研报限定最近 366 天，优先 20 页以上。每个正式公司或行业研究应尝试取得 1—2 份外资卖方报告和 1—2 份国内推荐报告；站内推荐流没有相关报告时可下载标题检索命中的国内深度报告作为显式回退，但不得把该回退计作平台推荐，严格配额仍记 shortfall。充分检索后不足时记录实际数量、已查关键词与影响，不能伪造达标。萝卜投研只是聚合入口，证据独立性按底层券商、报告标题和发布日期判断，同一底层报告的转载或重复下载只算一个证据组。
- 下载先进入临时目录，校验 PDF、页数与 SHA256 后再通过 Windows 安全文件名规则原子移动到 `papers/<行业>/`，同时在 `_source_manifests/` 保存来源标题、券商、发布日期、原始详情页、搜索关键词、国内/外资分类、页数、哈希和独立性键。A/B claims 引用该 PDF 时由统一 ingest 补齐这些来源字段；C 轨 producer 使用同一清单生成 source/provenance，但仍须遵守独立证据和原始来源门槛。卖方研报属于二手研究证据，只用于框架、预测和冻结后外部对账，不能替代公司公告、监管披露或产业原始数据。
- 每个方向只接收本方向所需的 brief slice，避免重复加载完整 prompt。
- 已接入生产入口的 claims JSON 和 C 轨 run pack 按内容 hash 缓存；同内容的不同来源 metadata 以不可变 provenance record 分开保存，不能相互覆盖。缓存版本、输入 hash、缓存命中和产物 hash进入审计记录。通用网页快照和 PDF 抽取仍需未来 crawler/renderer 显式调用同一缓存接口，不能因为缓存类存在就声称网络抓取已复用。
- 搜索停止依据是 coverage、边际新增和明确不可得，不是固定轮数或固定来源数量。
- 搜索预算随新颖性、时效性、不确定性和决策重要性上升。用户链接、本地 papers 和卖方资料是发现搜索词与候选的 seed，不是搜索边界；新近且可能改变概率、评分或财务结论的主张必须分配更多查询、来源类型、语言和反证搜索，不能因已经找到一份“看起来完整”的研报提前收口。
- 来源语言不是证据等级。英文研报、英文公司文件和英文产业资料与同类型中文资料按同一标准评级，不因原文语言、机构所在地、翻译工作量或本地可得性不同而调整权重；实际权重只看来源层级、原始性、时效、方法透明度、独立性、相关性和可复核性。全球产业链、海外公司/客户/供应商或国际技术路线相关问题必须在适用时同时建立中英文检索词和候选池；中文标题与译意仅服务公开可读性，不降低英文原始证据的等级。
- 非权威媒体、公众号、论坛、社媒、招聘与展会材料允许进入 discovery pool。研究者应先提取其中可核验的专利号、文件名、产品、客户、地点、日期、数量和引述，再向原始文件及公司、客户、供应商、政府、专利、认证或财务链路回溯；线索来源本身仍按弱源处理。
- 核心新近主张的验证不是“网页数量投票”。至少完成最早出处追踪、主体/产品/时间/数量核对、跨链独立侧证和反证/冲突搜索；转载、翻译、共同数字和共同匿名消息只算一个证据组。
- 多方反复提及但无法闭环的重要线索应保留为显式研究对象：写明说法、源头、支持与冲突、已查范围、未决证据和如果属实对结论的影响。它可以扩大不确定性、提高补证优先级或形成监控触发器，但不能直接成为核心事实、概率加点或财务模型输入。

### 3.3 证据单位

- 数据点是平行研究事实，不是数据库行数竞赛。
- 同一来源、同一对象、同一口径的一组时间序列只算一个数据点；底层观测保留在该数据点的结构化序列中。
- 研报一句话、一组数字、一次官方确认和一个长序列在“研究事实”层级平行，但用途和证据强度不同。
- 因子证据按 `independence_key` 计数。转载、翻译、卖方转述同一公告或媒体转述同一公司口径属于同一个独立证据组。
- 独立性未知时不自动算独立证据；应补 `independence_basis` 或降级。

A/B 的历史关系模型仍可把序列观测存为多行，统一 ingest 会另算 `parallel_research_fact_count`，检索、coverage 和证据门槛只能按同源/对象/指标/口径后的研究事实组计数；不能把存储行数当数据点数。C 轨 V2 必须直接把长期序列写成一个顶层数据点和一个 `observations` 数组，按日期拆行会被契约拒绝。

### 3.4 分析和写作

研究正文必须完成这条链：

```text
事实和数据
  -> 口径及冲突处理
  -> 对研究问题意味着什么
  -> 反方如何改变边界
  -> 结论和不确定性
  -> 证实/证伪及下一步动作
```

篇幅门槛是发现浅薄输出的兜底，不是写作模板。达到字符数但没有回答问题、没有解释计算、没有反方或多页复用同一段，仍然失败。

### 3.5 四个建模 Skill 与独立财务层

`ResearchBrief` 用确定性路由按问题只加载四个活动建模 Skill：

| 条件 | 必须加载 |
|---|---|
| 公司未来收入、利润、EPS、ROE、ROA或现金流 | `company_financial_modeling` |
| 目标价、合理价值、高估/低估、PE/PB/DCF/反向估值 | 财务建模 + `company_valuation_modeling` |
| 市场空间、量价、有效供给、产能或供需缺口 | `industry_supply_demand_modeling` |
| 竞争进入、技术替代、政策冲击、事件概率或经营情景 | `probability_scenario_modeling`；涉及公司价值时再接财务和估值 |
| 只做新闻、专利、招聘或事实核验 | 不加载上述建模 Skill |

AGENTS 和机器配置只保存触发条件和全局不变量；公式、最低数据要求和长方法说明留在对应 `SKILL.md` / reference 中按需读取。新工作流必须记录 Skill 输入/输出哈希和完成状态。公司财务模型先冻结 FY1—FY3 独立输入输出，再读取 Wind/Tushare 一致预期、公司指引、研报或市场隐含值对账；缺少冻结或对账时不能发布正式财务/估值结论。历史 V2 包没有 `research.modeling_skills.v1` 标记时维持只读兼容，不补造执行记录。

公司财务模型使用卖方预测做当前中位数、FY1—FY3差异或估值对账时，只纳入研究截止日前最近两个季度发布的同一公司报告，并在公开结果列明机构和发布日期。该时效筛选、适用性审查和计权规则对中文与英文研报完全相同；更早报告只用于解释历史预期变化；停止覆盖报告可保留截至当日的最终模型但必须标明状态。Wind等数据商聚合一致预期单独对账，不与可能重复收录的底层卖方报告混合计权。

当 A/B 行研或 Opportunity Lens 把上市公司列为龙头、重点公司或财务建模对象时，producer 必须主动取得研究截止日前最新的当年年报/季报以及最近两个季度内可核验的中英文机构预测或公司研究，保存到对应 `papers/<行业>/` 并完成来源登记。公司公告用于经营与会计事实，近期机构预测只在独立模型冻结后用于外部对账；充分搜索后仍不可得时，必须记录已查范围、缺口和对公司页及估值置信度的影响，不得因本地资料少而交付空公司页。Wind/Tushare/yfinance 的动态结构化快照继续只写 `financial.db`，不复制为普通行研数据点。

Wind、Tushare、yfinance 的结构化公司财务、行情估值、一致预期、内部预测和市场隐含结果统一进入 `data/financial.db`。`research.db` 只保留公司主体、行业关系和研究事实；旧结构化财务数据点只读兼容，新刷新不得继续写成普通 `industry_data_point`。公司页按规范证券身份直接读取财务库，供应商 actual、market、consensus、guidance、internal_estimate、implied 分层保存，同一观测修订保留 revision 账本。

Opportunity Lens 的上市公司研究若已经完成可复算的 FY1—FY3 独立预测、估值门禁和反向估值，应额外生成 `company_financial_profile_export.v1`，由 `tools.financial.opportunity_profile_export` 在 C 轨事务之外校验原始产物哈希后写入 `financial.db`，使公司页同步显示多方法估值与当前市场隐含结果。该同步是证据充分时的默认动作，不是填满页面的硬凑数要求；数据不足或方法不适用时只同步可成立部分，并保留具体边界。

公司商业化或投资组合研究增加一项确定性内容门禁：进入公司排序、评分或权重讨论的主体，必须存在“付款人/客户—采购或部署阶段—客户经济价值—可复制市场—收入与自由现金流传导—当前估值与行动条件”的逐公司分析。合同、启动、上线、验收、收入和回款分别登记，不得合并成“已经落地”；客户侧效率若只来自供应商案例，正文必须注明未经过独立审计。成交价不可得时允许用明确假设计算客户侧盈亏平衡或回收期，但该结果不能倒推为公司收入事实。缺少这条链的公司只能进入经营对照池，不能获得精确权重；writing/final review 发现公司简介、方向标签或泛化展望替代这条链时必须判为 RED。

## 4. A 轨

### 4.1 输入

行业名和 `papers/<行业>/`。A 轨不是“只摘要研报”，而是基于研报建立可追溯数据底座，再形成独立行业判断。

### 4.2 默认 coverage

1. 产品定义、边界和价值链；
2. 历史、技术代际和周期切换；
3. 竞争、份额、集中度、区域和国产替代；
4. 市场规模、量价驱动、情景和测算分歧；
5. 公司壁垒、客户验证、经营兑现和证伪；
6. 行业经济性、议价、政策、地缘和路线替代；
7. 当前判断、主要风险、监控变量和结论边界。

### 4.3 输出兼容

Viewer 仍读取主文档、Q0-Q5、可选 Q6、公司透视、估值和产业链。这个页面集合是展示兼容层，不是限制研究只能按固定小标题思考。研究可以先按问题自适应组织，再映射到页面：

- Q0：历史与代际；
- Q1：竞争格局；
- Q2：市场空间；
- Q3：公司壁垒；
- Q4：行业经济性和商业模式；
- Q5：综合判断；
- Q6：无法自然归入前述页面的专项问题。

## 5. B 轨

B 轨继承 A 轨全部数据、文档、公司和页面要求，并增加：

1. 编译 prompt requirement matrix，逐项记录落点和状态；
2. 独立公开搜索，不能只依赖用户资料包或本地公司池；
3. 公司研报默认是支持证据，不是决定性证据；
4. prompt 提到的口径、表格、计算和排除项优先，但不得突破不造数和可追溯红线；
5. 客观不可得必须写已查来源、不可得原因和可接受代理，不能留空或填估计。

统一入库入口为 `tools/pipeline/ingest_research.py`。旧 `ingest_industry.py` 与 `ingest_b_track.py` 只保留 CLI 兼容。

```powershell
python tools/pipeline/ingest_research.py --track b --industry-id <id> --tag <tag> --papers-subdir <dir> --workflow-request <request.json>
```

## 6. C 轨

C 轨 V2 是对既有 Opportunity Lens 工作流的门禁升级，不是产品重写。以下四份顶层协议继续作为活动基础合同，并按 artifact 选择读取：开放检索与 intake 用 `C轨研究启动与开放探索输出标准_V0.9.1.md`，评分与指标槽用 `C轨供需失衡评分流程与可解释计算体系_V0.8.1.md`，独立 DB 与状态用 `C轨独立DB与开放研究深度补充修订说明_V1.0.md`，Viewer 页面族与输出职责用 `C轨输出模板与前端可视化标准_V1.1.md`。V2 pack、发布门禁和现行人类可读性合同覆盖其中已过期的字段、动态快照和公开机器标签，但不取消原有页面职责。

### 6.1 Intake

Canonical 字段：

- `research_question`
- `available_materials_choice`
- `intake_material_type`
- `materials_delivery_note`
- `evidence_policy`

资料状态 B 可以填共享路径，也可以只写资料包已交付及企业微信同步说明，不要求个人电脑路径。

### 6.2 实体类型

`market_linked`：直接或间接映射公司、证券、ETF、期货、价差或观察篮子；可评分、可生成 early signal、必须有条件化标的研究。

`theory_research`：产品边界、价格体系、方法、理论和不适合直接映射标的的问题；必须有文献综述、研究 profile 和计算底稿，不评分、不进入机会矩阵、不挂标的。

### 6.3 Run pack V2

新研究包必须声明：

```text
pack_schema_version = opportunity_lens.run_pack.v2
workflow_contract_version = research.workflow.v2
```

每个 source 必须有原始 URL/本地原文定位、`independence_key` 和 `independence_rationale`；英文 source 还必须显式提供 `title_zh` 与 `excerpt_zh`，不能依赖自动占位说明。每个 reviewer 记录必须有 canonical stage、角色、reviewer id、类型、输入/输出 artifact hash、verdict、findings 和 reconciliation 状态。`workflow_review_contract` 只说明期望流程，不能替代执行记录。

评分的可用指标槽必须从明确数据点复算到标准化值、分档规则和槽分；`context` 槽只展示背景事实，不进入分数、覆盖率或置信度，并且不得序列化 `bucket`、`slot_score`、`scoring_rule` 等评分字段。缺失槽保持缺失，不用零分或来源关键词自动补值。

### 6.4 装载与发布

```powershell
# 只校验，不开 DB
python -m tools.opportunity_lens.manual_run_loader <pack.json> --validate-only

# 只读检查是否满足完整发布前 pack 契约
python -m tools.opportunity_lens.manual_run_loader <pack.json> --validate-for-publish

# 默认暂存为 under_review / reviewable
python -m tools.opportunity_lens.manual_run_loader <pack.json>

# 显式通过发布门禁
python -m tools.opportunity_lens.manual_run_loader <pack.json> --publish
```

相同 slug 默认拒绝重复装载，不隐式删除历史 run。只有明确确认替换时使用 `--replace`；该路径会在同一事务内删除旧 run，并尽量恢复原 run_id，失败则整体回滚。

正式执行优先先暂存、在 staged run 上完成浏览器与其他 reviewer 记录，再用 `python -m tools.opportunity_lens.publication <run_id>` 发布既有 run。这样无需为了补审计记录重载整包，也不会改变 run_id。

V2 loader 还会把 pack 编译为共享 `ResearchBrief` 和 `ExecutionManifest`，以 `research_brief` 与 `research_execution_manifest` 两类记录写入 `opportunity_run_manifest`。这两条记录与原有 intake contract、五项 quality gate 和 reviewer log 使用相同 pack hash；发布既有 staged run 时，发布事务会用 DB 最新 gate/reviewer 记录同步 execution manifest。legacy pack 和历史 run 不自动生成这些记录。

发布门禁要求：contract/evidence integrity/provenance/duplication/scope and units 五个 gate 均存在且无 RED、无未关闭 P0。基础 reviewer 为 evidence/science/writing/final；公开页面追加 browser，market-linked 追加 calculation，证券标的追加 financial。各 stage 最新记录须为 GREEN 且 findings 已闭环，输入/输出 SHA256 格式合法；browser 可以是确定性 Playwright 审计，其余发布必需 reviewer 和 final 必须是 independent 或 human。

无版本历史包被识别为 `opportunity_lens.run_pack.legacy`。既有 DB 记录和页面继续可读；历史 JSON 可审计，但触发现行 legacy 校验时必须先修复才能重新装载，且不能在没有升级和真实 reviewer 记录时自动发布。

### 6.5 公开研究的表达合同

本节规定研究内容如何表达，不是 Viewer 改版授权。界面依据是上面的活动基础协议与 `opportunity_lens/MODULE_CONTEXT.md`，不是从 run1-run8 产物反推模板。除非用户明确提出页面或交互改造，同一产品的不同 run 必须沿用稳定页面骨架、导航、路由、页面分工和交互，研究内容只在既有展示区域内自适应。pack schema、研究问题或写作规则变化不会自动授权新增、删除或重排页面、tab、路由及全局模板、CSS、JS；确需结构变更时，必须先说明现有骨架为何无法承载，并完成全部稳定路由的兼容审计。

稳定页面族包括列表、研究请求、run 总览、研究对象列表、实体详情、标的详情、因子追踪、指标槽追踪、审计、补充研究和导出。schema 专用模板可以适配数据形状，但不能把详情页重定向回 run 总览或改变公开页面职责。Run 页在紧凑身份/KPI 区之后，固定采用“研究报告全宽在前 → 研究对象 → 因子热力图与结构化总览 → 有长期趋势价值时再显示长期序列总览”的顺序；主报告不复制实体全文。内部 P0-P13/E0-E8 编码只用于追溯原始协议职责，不进入公开标题。

Run 入口和页头使用独立的简短 `display_title`；完整 `research_question` 原样保留在研究包和入口合同中，正文通过 requirement matrix 逐项回答而不是重新粘贴整段请求。页头需要补充语境时使用自然中文 `problem_statement`。短标题是对主题的准确概括，不是对完整问题的机械截断。

C 轨公开正文必须让没有参与生产流程的投资研究读者直接读懂。每个章节和实体专题必须用可见小标题明确分成“问题—研究方法与数据—研究与分析—总结”，不能只把四步暗藏在连续长段里；“研究与分析”较长时继续按论点分段，最后的总结直接写清主体、时间、事件和影响。四个部分是阅读结构，不是字段完成清单：没有复杂计算时不硬加公式，也不得用来源堆叠代替分析。取消“如果想进一步研究，需要补充的信息”标准栏目；充分检索后仍不可得的关键数据，要在当前问题的研究与分析中说明已查范围、近似方法、结论影响和置信度，不能作为延后回答的出口。字段完成度、输出覆盖、参数归属、审计状态、内部情景代码和生产术语留在 run pack、manifest、DB 或内部 API，不进入公开正文。

每张公开表格只回答一个正文已经提出的问题；删除某列不影响事实理解、计算复核或决策时必须删除，两张表回答同一问题时必须合并。减少低信息表格不等于禁表：当模型结果需要横向比较多个主体、情景或期限，表格比连续正文更清楚时，应优先使用一张高信息结果表展示基准、变化幅度、期限及与问题直接相关的盈利、现金流或估值影响，再用正文解释原因和结论。概率章节不展示不能改变判断的分位数、模拟诊断和内部代码；敏感性只有在增加决策信息时才用至多一张表，否则使用量化正文，并写清估计方法、结果差异、口径边界和结论影响。主报告不得复制实体页、标的页或证据页的完整正文；来源索引不得用内部 source id、记录号或表名占据信息列。详细要求以 `opportunity_lens/HUMAN_READABILITY_STANDARD.md` 为准。

每个 topic 的图表数量按问题决定，不设“一节最多一张”的机械限制，通常不超过三张；相关财务时序、业务分部、情景和估值结果能合并清楚展示时优先整合，只有问题、量纲或视觉负担不同才拆开。

公司型研究还必须把规范证券身份贯穿输出：已解析 `company_id` 的公司在每个独立正文段落首次出现时链接到 `/company/<company_id>`，内部取数失败、代理重试和补缺过程留在审计层。不同公司的财务基数和传导路径分别分析；复杂模型除公式外必须披露关键数值输入、依据和结果，本地材料缺少未来盈利与估值对账时继续搜索可核验资料。实体页同时覆盖事件对公司自身的短期/长期财务、资本投入、上下游和估值影响；PB—ROE/PB—ROA仅在适用时用于解释资产回报与杠杆。表格语义列宽、经济观测去重和双视口标签可读性属于 browser gate，而非可选美化。

复杂模型若包含多层乘积、加权汇总、跨期递推或其他仅靠语言难以准确复述的关系，应在方法栏目集中展示一至三个核心可读公式，并说明输入、输出、量纲和边界；简单算式和不影响理解的中间公式不展示。多个类别同时跨多个期间和指标形成密集数据、连续文字难以横向对应时，使用一张高信息表；短序列、单指标或正文更清楚时不机械制表。因子卡等结构化组件的名称必须在卡片本身完整可见，不能被分数或状态徽标挤压，也不能依赖 hover 补全。

producer-reviewer loop 继续采用精简前的分工并接入 V2 记录：来源/数据后做 evidence，模型/评分/概率/公式后做 calculation/science，证券财务后做 financial，正文后做 writing 并在该 stage 内执行 citation verification，页面后做 browser，全部定向问题闭环后只做一次 final。writing reviewer 必须检查机器语言隔离、引用绑定、证据缺口的准确措辞、公式转译、低信息/重复表格和财务结果解释；browser reviewer 必须覆盖全部稳定路由，在桌面与移动端逐表检查最右列表头和单元格并保存逐表右端截图，不得用“存在横向滚动容器”代替可见性验收；全部唯一证据按钮也必须用键盘实际打开并检查 API、抽屉内容和溢出。整版重写后，旧 artifact hash 对应的 reviewer 记录全部失效。

calculation、financial 和 writing reviewer 共同检查字段单位到公开显示单位的数值换算，不能只改单位名称。至少用一项“数量 × 单价 = 金额”或等价量纲反算检查数量级；专题关键换算必须形成自动化回归测试。

science、calculation 和 writing reviewer 还必须检查近似命名指标是否实际使用不同输入、条件分母或阈值；存在两套合同时，公开正文必须分别解释，不能借同一标签暗示它们可互换。结构化专家判断要在模型输入 provenance 中标明非外部事实、残差方法和未校准边界；正文引用的本地模型输入/输出必须把实际文件 SHA256 写入 run pack source，确保 review hash 与发布冻结绑定真实底稿内容。

## 7. 自适应审查

### 7.1 始终执行

- contract；
- evidence integrity；
- provenance；
- duplicate/template text；
- scope/unit/time。

这些是确定性 gate，应由代码先检查，不应消耗完整 reviewer prompt。

### 7.2 按 artifact 触发

| Artifact / 风险 | Reviewer |
|---|---|
| 派生计算、CAGR、CR、份额、权重 | calculation recompute |
| 因子评分、指数、方法论 | science and logic |
| 上市公司、估值、财务 | financial completeness |
| 公开 Markdown | writing（内含 citation verification） |
| 新页面或 UI 改动 | Playwright DOM and visual |
| 冲突来源、单一证据组、陈旧数据作当前判断 | evidence escalation |

### 7.3 最终审稿

最终只做一次综合审稿，合并科学审稿与基金经理视角：

- 来源是否独立、方法是否可复算、反方和不确定性是否完整；
- 结论是否越过数据边界；
- 哪些信息改变风险收益、公司优先级或研究动作；
- 证实/证伪后如何调整；
- 页面是否让人直接读懂而不是暴露 JSON 和机器字段。

失败只打回相关 producer stage。最多三轮定向修复；仍未闭环则标记 blocked，不强行通过。

## 8. Execution manifest

活动任务在 `cache/research_runs/<run_key>/manifest.json` 或 C 轨 DB 中记录：

- request 和输入文件 hash；
- workflow/brief/pack 版本；
- stage 状态和缓存命中；
- gate findings；
- reviewer 输入、输出、findings 和修订；
- requirement 逐项状态、产物引用、证据引用和限制说明；
- 发布门禁结果。

只有这些记录能证明某个 gate/reviewer 实际执行。规范文件存在、prompt 声明或构建器自报不能替代。

`tools/maintenance/audit_workflow_contract.py` 必须同时检查静态契约和运行接线：A/B ingest、C loader、C workflow bridge、配置缓存，以及 A/B/C 对内容缓存的真实调用。独立核心类有单元测试但没有生产调用，视为未接线。

## 9. 不变红线

- 不造数；不可得就明确写不可得。
- A/B 新数据点必须走 `db_writer.write_data_point()` 或批量封装。
- `research.db`、`sentiment.db`、`opportunity_lens.db` 与 `financial.db` 保持四库边界；跨库读取和证券身份链接不能演变为相互混写。
- 新市场、估值、财务和 K 线允许 Wind、Tushare 与 yfinance；Akshare 不得作为新来源。A 股 Wind 只走项目根目录 `WindPy.py` 的内网 HTTP 代理并作为主源，Tushare 只补 Wind 缺失字段和提供逐机构/公告审计；字段级 provider、symbol、时点、单位与方法必须保留，冲突值不得静默平均或覆盖。其他市场以 yfinance 为主。Wind 未获用户明确授权时只做小型取数：单次上限为10只证券、20个字段、预计5,000个观测，同一任务/北京时间自然日累计上限为50只证券或50,000个观测；全A股历史、全市场截面、分钟长历史或任何超过上限的请求必须先报告范围与预计数据量并取得permission，不得拆单绕过。
- 不把 AI 摘要、卖方结论或论坛传闻当一手事实。
- 不读取或外发 secrets。
- 未授权不跑写库抓取、回填、迁移和 scheduler。
- Smoke 默认只读 GET。
