# Opportunity Lens 模块上下文 V2

活动工作流：`docs/research/RESEARCH_WORKFLOW_V2.md`  
机器契约：`config/research_workflow.yaml`  
展示契约：`opportunity_lens/HUMAN_READABILITY_STANDARD.md`  
旧版完整上下文：`archive/project_history/retained_originals/workflow_v1_20260712/opportunity_lens/MODULE_CONTEXT.md`

## 1. 模块边界

- DB：`data/opportunity_lens.db`
- 代码：`tools/opportunity_lens/**`
- Viewer/API：`/opportunity-lens`、`/api/opportunity-lens`
- Intake：`opportunity_lens/intake_requests/`
- V2 pack builder：`tools/opportunity_lens/run_pack_builder.py`
- V2 contract：`tools/opportunity_lens/run_pack_contract.py`
- 装载与发布：`tools/opportunity_lens/manual_run_loader.py`
- 发布门禁：`tools/opportunity_lens/publication.py`

C 轨只读引用 `research.db`、`sentiment.db` 和 `financial.db`，不得回写 A/B、情绪或财务库。`financial.db` 只承载规范证券身份下的结构化 actual/market/consensus/guidance/internal_estimate/implied 与模型账本；C 轨不得把这些数据复制成普通 Opportunity Lens 数据点。

同一 Opportunity Lens 产品的不同 run 默认共享既有 Viewer 展示骨架。内容生产和人类可读性规则不得自行改变导航、路由、页面分工或全局交互；结构改版必须有用户明确授权并验证历史 run 兼容。

## 2. 稳定页面、路由与阅读顺序

下面的产品合同恢复自工作流精简前的活动协议，并结合当前 live route 重新声明。它是新旧 pack 共同遵守的界面基线，不是从 run1-run8 的 DOM 或内容反推出来的模板；历史 run 只用于确认兼容性。

```text
/opportunity-lens
/opportunity-lens/request-generator
/opportunity-lens/run/<run_id>
/opportunity-lens/run/<run_id>/entities
/opportunity-lens/entity/<entity_id>
/opportunity-lens/target/<target_id>
/opportunity-lens/factor/<factor_score_id>
/opportunity-lens/metric-slot/<slot_id>
/opportunity-lens/run/<run_id>/audit
/opportunity-lens/run/<run_id>/supplement
/opportunity-lens/run/<run_id>/export
```

这些页面不是同一正文的别名：run 页回答整个研究问题；研究对象页展开单一公司、风险或理论专题；标的页承载标的自身数据和条件化建议；因子页解释分数、公式和证据上下文；指标槽页追踪选中、排除和缺失证据；审计、补充研究、导出分别承载质量问题、补证动作和导出状态。不得用跳回 run 总览的重定向代替独立页面职责。

Run 页公开阅读顺序固定为：

1. 紧凑的身份、状态和 KPI 区；必要时可有一屏研究概览，但不得变成营销式 hero；
2. 全宽“研究报告”，正文直接回答完整研究问题；
3. “研究对象”，链接到只出现一次的专题分析；
4. “因子热力图与结构化总览”；
5. 仅在存在有解释价值的长周期序列时显示“长期序列可视化总览”，桌面最多两列。

不同 schema 可以使用不同 read adapter 或模板处理数据形状，但公开导航、页面族、上述阅读顺序和各页面职责必须一致。可选组件按数据和实体类型条件显示；条件不适用不等于允许删掉产品路由或改写页面分工。

## 3. Canonical 接口

- 用户问题：`research_question`；DB `question` 仅兼容旧记录。
- 页面短标题：`display_title`，只承载可快速识别的主题；完整 `research_question` 保留在研究包和入口合同中，由正文 requirement matrix 逐项回答。`problem_statement` 可作为页头下的一句自然中文问题摘要，三者不得互相覆盖。
- 资料选择：`available_materials_choice`。
- 工作流资料类型：`intake_material_type`。
- 附件交付：`materials_delivery_note`；B 类不要求个人电脑路径。
- 证据策略：`freshness_first`、`balanced`、`accuracy_first`。
- 实体研究模式：`market_linked`、`theory_research`。
- 来源定位与独立性：原始 URL/本地原文路径、`independence_key` 和 `independence_rationale`；英文来源显式存 `title_zh`、`excerpt_zh`。

公开 API 不接受 `question`、`available_materials_state` 等历史别名；legacy parser 边界可归一后立即丢弃别名。

## 4. 实体分流

`market_linked`：允许评分、early signal、标的和条件化投资研究建议。每个实体至少有一个可点击公司、证券、ETF、期货、价差、篮子或官方观察入口；每个标的有结构化数据点和差异化证实/证伪动作。

`theory_research`：必须有 research profile、文献综述和至少 8 条计算/证据底稿；不得生成 factor score、composite score、early signal 或 target。通用评分函数已按 research profile 排除理论实体。

## 5. 数据和证据

- 真实研究至少 100 个平行数据点。
- 同源同对象同口径序列只算一个数据点和一个证据组；V2 pack 使用一个顶层数据点加 `observations` 数组。
- 普通因子至少 3 个独立证据组，重要因子至少 5 个；按 `independence_key`，不按 URI 数量。
- 弱证据只能进入 early signal/reference，不能抬高核心 14 因子。
- 2024 年或更早材料作当前判断时必须显示严重时效警告。
- 英文原文保留，并给中文译意。
- A/B 证据只通过 `ab://research.*` / `ab://sentiment.*` 或等价 resolver 引用，不建立跨库外键、不回写 A/B；用于 C 轨评分、正文或标的研究时，C 轨必须保存足以展示和复核的来源/数据快照、原文摘录、口径与复核元数据。
- 新近且重要的开放问题必须提高独立搜索权重，不能让用户链接、papers 或卖方资料成为候选与来源上限。弱媒体、论坛、社媒、招聘和展会材料可以主动用于发现线索，但只能在追到原始文件或形成独立跨链验证后升级；重复转载仍是一个证据组。
- 多方反复提及但无法闭环的重要主张保留为 `material_unverified_lead` 或等价内部状态，公开页面用自然中文说明其说法、源头、冲突、已查范围和若属实的结论影响。该状态只影响补证优先级、监控和不确定性，不直接进入核心评分、概率事实更新或财务事实输入。
- 第一轮每个问题轴的研报与网络检索必须分别登记 `source_channel=report/web`，分别完成抽取、去重和来源评级；一条链路命中不减少另一条链路的搜索。第二轮只围绕第一轮分析形成的明确 gap，并保存 `gap_trigger`。
- C 轨 `report` 链可复用 `tools.research_sources.datayes_reports` 在萝卜投研正常网页中完成标题检索和授权下载。账号密码只经 Windows Credential Manager 的 `WinVaultKeyring` 后端调用；公司报告默认最近 183 天、行业报告最近 366 天且优先 20 页以上，并尝试覆盖 1—2 份外资与 1—2 份国内推荐报告。站内推荐流没有相关国内报告时，标题检索的国内深度报告只作为显式回退，不满足平台推荐严格配额。下载后的 `_source_manifests` 是来源发现和 provenance 输入，不是已核验结论；`independence_key` 按底层券商、标题和发布日期生成，聚合站重复项不得抬高独立证据数。登录 profile 位于 secrets，任何 C 轨 pack、DB、cache 审计和导出都不得复制其内容。

## 5.1 建模 Skill 和公司身份

- 新 pack 声明 `modeling_contract_version=research.modeling_skills.v1`，并由共享 `ResearchBrief` 根据问题按需路由公司财务、公司估值、行业供需、概率情景四个 Skill；事实核验任务不误加载。
- 被路由 Skill 必须写 `modeling_records` 的输入/输出 SHA256。涉及公司财务时必须先写独立预测冻结记录，之后才允许写 Wind/Tushare/研报/市场隐含结果的外部对账；缺一项不得发布。没有新合同标记的历史 pack 维持兼容，不补造记录。
- 上市公司标的必须精确解析公司主体、证券代码、市场和股份类别。已有公司复用规范 `company_id`；不存在时先通过显式公司画像 provisioning 流程核验并建立 `research.db` 公司身份和 `financial.db` 证券链接。模糊名称、母子公司或 A/H/ADR 冲突时拒绝自动猜测。
- 公司标的链接统一落到 `/company/<company_id>`；公司页只读显示相关 Opportunity Lens run。C 轨装载事务不会隐式创建或修改 A/B 公司身份。
- 输出接口要求 `market_linked` 研究在身份解析后保存规范 `company_id`，正文每个独立段落首次提及该公司时使用上述公司路由。实体详情按公司分别承载自身短期/长期财务、上下游、估值和条件化投资分析；内部数据供应商错误与补缺过程不进入公开正文。
- 对已识别上市公司，模型证据足够时由 producer 生成 `company_financial_profile_export.v1`，在 C 轨装载事务之外调用 `tools.financial.opportunity_profile_export` 同步独立 FY1—FY3、适用估值方法和市场隐含结果；导出必须绑定真实模型文件 SHA256。C 轨 loader 只保存研究包和审计状态，不越库代写 `financial.db`。

## 6. Run pack 与发布

V2 pack 声明：

```text
pack_schema_version = opportunity_lens.run_pack.v2
workflow_contract_version = research.workflow.v2
modeling_contract_version = research.modeling_skills.v1  # 新构建器
```

命令语义：

- `--validate-only`：只读校验，不开 DB。
- 默认：装载到 `under_review/reviewable`。
- `--publish`：要求质量门禁、review records 和 P0 检查全部通过。
- `--replace`：仅在明确替换相同 slug 时使用，并尽量复用原 run_id；默认拒绝覆盖。
- `python -m tools.opportunity_lens.publication <run_id>`：对已完成 reviewer/browser 记录的 staged run 执行发布门禁。

`workflow_review_contract`、构建器 `audit_pack()` 和自然语言“已核验”都不是独立 reviewer 执行证据。真实记录写入 `opportunity_quality_gate_result` 和 `opportunity_agent_review_log`；五个确定性 gate 都必须存在，review record 包含 canonical stage、reviewer id/kind、输入/输出 artifact hash、findings 和 reconciliation。

旧 run pack 没有版本时标为 `opportunity_lens.run_pack.legacy`。既有 DB 页面继续可读；历史 JSON 只保证可识别和审计，不保证在发现旧证据/正文问题后仍能无修改重载，也不能无升级和 reviewer 记录自动发布。

## 7. 状态语义

- `run_status=completed`：流程执行完成。
- `run_readiness_status=reviewable`：可审查。
- `run_readiness_status=published`：发布门禁通过。
- 纯理论 run 可从 `mapping_entities` 直接进入 `report_drafting`，不经过 scoring。
- 相同 slug 默认拒绝覆盖；显式替换时尽量保留原 run_id，事务失败必须恢复旧 run。

## 8. 实现边界

- 当前没有通用真实 crawler、自动多语搜索调度和真实 PDF renderer。
- 专题构建器和历史 run pack 是既有研究资产，不等于通用生产编排器。
- 旧 run2-run8 的 published 状态早于 V2，不得反向宣称已有 V2 reviewer log。
- live 数量读取 `codex_context/LIVE_STATE.md` 或直接只读查询 DB，不写在本文件。
- 默认 smoke 只调用稳定页面和只读 GET API；POST run、刷新、删除、抓取、装载、迁移、发布和导出 job 都必须有任务范围内的明确授权。

## 9. 公开研究的生产与审查上下文

任何 Opportunity Lens producer、修复 agent、writing/browser/final reviewer 在执行前都必须读取 `opportunity_lens/HUMAN_READABILITY_STANDARD.md` 和本文件；Viewer/页面任务再读 `C轨输出模板与前端可视化标准_V1.1.md`，检索、评分和 DB 任务按职责读取另外三份顶层基础协议。任务合同必须显式检查：章节问题链、段落内规范公司链接、公司自身的短期/长期财务与上下游及估值影响、复杂模型实际输入、稳定页面职责、表格信息增量、机器字段隔离、概率/公式转译、主报告与子页面不重复、来源索引不暴露机器定位字段、逐表最右列视觉可见性与截图，以及全部唯一证据按钮的键盘/API/抽屉实测。审计完整性字段保留在 run pack、manifest、DB 和内部 API；公开正文只呈现研究问题、必要证据、可理解的方法、分析与结论。

新近或争议性任务的 producer 上下文还必须包含：按新颖性/时效性/不确定性/决策重要性扩展搜索预算；主动使用弱源发现可核验线索；对关键主张执行最早出处、主体口径、跨链侧证和反证搜索；识别共同源头；保留并降档说明重要未验证线索。evidence、writing 和 final reviewer 必须逐项检查这些记录，不能因核心结论谨慎就放过检索不完整。

报告重写会使旧 artifact hash 和旧 reviewer 记录失效。不得把旧版 GREEN、静态 `workflow_review_contract` 或 builder 自审当作新版通过证据；必须对新 artifact 重新执行对应 reviewer 和浏览器全页验收。
