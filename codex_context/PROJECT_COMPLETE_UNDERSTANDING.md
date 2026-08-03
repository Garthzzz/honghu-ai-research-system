# industry_demo 完整架构理解 V2

本文件描述稳定边界，不保存易变化计数和逐 run 历史。当前数字由 `tools/maintenance/build_context_snapshot.py` 只读生成到 `codex_context/LIVE_STATE.md`。旧版完整上下文在 `archive/project_history/retained_originals/workflow_v1_20260712/codex_context/PROJECT_COMPLETE_UNDERSTANDING.md`。

## 1. 目标与信息架构

系统把产业研究的原始材料转为四类可复用资产：

1. 可追溯 source 和结构化数据点；
2. 行业文档、公司透视、估值和产业链；
3. 动态新闻、意见领袖、事件、情绪、招聘和供应链信号；
4. Opportunity Lens 问题驱动研究、评分、理论研究底稿和标的研究。

统一 Flask viewer 提供研究员阅读、检索、比较和证据回溯。它不是纯静态网站，也不是单一自动抓取服务。

## 2. 权威与上下文

权威顺序是用户最新要求、live 代码/DB/前端、V2 活动契约、当前 live 快照、历史设计/日志。

活动文件：

- `AGENTS.md`
- `config/research_workflow.yaml`
- `docs/research/RESEARCH_WORKFLOW_V2.md`
- `codex_context/LIVE_STATE.md`
- 本文件和 `FILE_DB_INDEX.md`

旧 SOP、CLAUDE 文件、Opportunity Lens `design/**`/`plan/**`/补丁和 `PROGRESS_LOG.md` 用于追溯，不是默认 prompt。顶层四份 C 轨基础协议、`MODULE_CONTEXT.md` 与 `HUMAN_READABILITY_STANDARD.md` 已重新确立为活动合同，按 artifact 职责读取。

## 3. 数据库边界

### research.db

承载：

- `industry`、`industry_relation`；
- `source`、`source_entity`；
- `industry_data_point` 和共识/peer 结构；
- `company`、`company_industry`、`company_profile`、细分份额；
- 新闻、KOL、事件和 opinion leader；
- 研究员、假说及版本/审计辅助表。

`data/schema.sql` 是历史参考，live `sqlite_master` 和 `PRAGMA table_info` 才是当前事实。

### sentiment.db

承载三层情绪、关键词、post/raw、K 线、招聘、事件项和 Funda 供应链镜像。相关模块只读 attach `research.db`，不得把情绪原始数据回写主行研表。

### opportunity_lens.db

承载 intake、run、search/source/cluster、claim/data point、entity/maturation/profile、research ledger、factor/slot/score、early signal、target、report/visual、audit/review、manifest、state transition 和 export job。

C 轨 evidence resolver 可只读解析 A/B URI；C 轨写入不能污染 `research.db`、`sentiment.db` 或 `financial.db`。

### financial.db

承载规范证券身份与公司链接、结构化来源快照、历史实际、市场行情与估值、一致预期、公司指引、内部预测、市场隐含结果、模型输入/输出、同一观测修订和外部对账。六类事实分别保存，不把供应商实际、卖方预期和内部判断混成一个数值。

Wind、Tushare、yfinance 的新结构化公司数据只写入该库；旧 `research.company` 财务列和 `company_profile` JSON 只读兼容、不再由刷新任务更新，旧结构化 `industry_data_point` 只读保留。公司页按 `financial_security_company_link` 直接读取财务库；Opportunity Lens 保存冻结模型和研究结论，但不复制供应商原始快照为 source/claim/data point。四库之间不建立破坏边界的写入外键。

## 4. A/B 行研

### 共同底座

`tools/pipeline/db_writer.py::write_data_point()` 是 A/B 数据点标准写入口。V2 对新数据强制：

- metric、period/as_of、unit、value、source 和 excerpt 完整；
- 数值有限；引用对象存在；
- extraction method 只用 `pdf_direct`、`web_fetch`、`inferred`；
- inferred 有公式/口径 note；
- 批量写入原子化；共识失败默认回滚。

该入口只处理行业研究事实，不再承载 Wind/Tushare/yfinance 结构化公司财务、市场和一致预期；这些数据进入 `financial.db`。

`tools/pipeline/consensus_compute.py` 处理可比较 numeric peer；来源独立性和底层事实聚类不能只依赖共识函数，需在研究 brief/gate 中额外检查。

### A 轨

从 papers 建立来源和数据底座，再完成定义、历史、竞争、空间、公司、行业经济性和综合判断。它不是只摘要研报。

### B 轨

先把 prompt 编译为 `ResearchBrief`，与 A 默认 coverage 取并集；代码只合并完全相同项，语义近似项不自动删除。Brief 同时保存决策用途、必含/排除、范围、时间、产物和质量下限。B 轨必须独立搜索，不把本地资料或公司研报当候选和结论上限。

### 输出兼容

Viewer 固定识别行业主文档与 Q0-Q5 文件名，可选 Q6；公司透视、估值和产业链由 DB 与模板共同生成。研究内部结构可自适应，最终映射到兼容页面。

专题构建器仍是既有行业资产。新共性逻辑应进入 shared core，不再让专题构建器改写 AGENTS/context。

研报与网络搜索在第一轮按每个问题轴分别生成 `report` 和 `web` 任务、分别抽取和登记来源；任一渠道命中不降低另一渠道预算。第二轮只由明确 gap 触发，并保存 `gap_trigger`。`ResearchBrief` 同时按问题只路由公司财务、公司估值、行业供需、概率情景四个 Skill，纯证据核验不加载模型。

## 5. 公司、估值和市场数据

新增数据源政策由 `tools/pipeline/data_source_policy.py` 和 V2 config 共同约束：

- A 股：项目根目录 `WindPy.py` 对接的内网 Wind HTTP 代理为主源，Tushare 对 Wind 客观缺失字段逐项补齐，并提供逐机构预测明细和公告/重述审计；每字段保留真实 provider、symbol、时点、单位和方法。
- 海外、台股、日股等：yfinance；当前 Wind 代理的美股三表和远期预测覆盖不足，不作为海外主源。
- Akshare：禁止新抓取；Wind 已解除禁用，但旧 one-off 回填脚本继续退役，必须走统一 provider、fetch/apply manifest 和独立财务库 writer。
- Wind大规模取数仍需用户逐次明确授权：默认单次只允许不超过10只证券、20字段、预计5,000观测，任务日累计不超过50只证券或50,000观测；全市场或长历史天然视为大规模，不能拆单绕过。

公司透视必须区分上市、未上市、子公司、退市和观察篮子。上市公司检查估值、市值、利润率、现金流、capex、财务序列和近期事件；不可得有原因，不能留空后声称完成。

公司详情页和 `/companies` 使用规范 `company_id`。Opportunity Lens 或行研发现新的上市公司时，必须先核验主体、ticker、市场和股份类别，再通过显式 provisioning 建立 research 公司身份及 financial security 链接；装载器不在 C 轨事务中猜测或隐式创建公司。公司页展示 FY1—FY3 内部预测与一致预期、估值模型账本、市场隐含预期、PB-ROE/PB-ROA 历史关系和相关 Opportunity Lens。

公司型公开研究按规范 `company_id` 建立段落内公司链接，数据供应商错误和补缺过程留在审计层。不同公司的财务与风险传导分别分析；复杂模型同时公开关键数值输入和结果，实体页覆盖事件对公司自身的短期/长期财务、上下游与估值影响。PB-ROE/PB-ROA只在适用时解释资产回报和杠杆，表格与图表还必须通过语义列宽、经济观测去重和双视口可读性验收。

Opportunity Lens 对已识别上市公司完成可复算建模后，优先生成 `company_financial_profile_export.v1`，由独立导入工具校验冻结底稿哈希并同步 FY1—FY3、适用估值方法和市场隐含结果到 `financial.db`。C 轨 loader 不跨库写财务；证据不足时只同步可成立部分，不为公司页完整度造数。

财务建模先基于实际值形成 FY1—FY3 独立预测并冻结输入/输出 SHA256，之后才允许读取一致预期和研报对账。正式估值按方法门禁启用 PE、历史/同行、EV/EBITDA、PS、PB 资产回报、DCF/反向估值等；DCF 缺未来现金流闭环时关闭，多模型按依赖簇解释而不机械平均。事件概率只描述情景成为现实的可能性，条件财务冲击必须通过受影响业务、份额、价格、成本、费用和税率传导，不能直接把概率乘利润。

金额主单位为亿元人民币，括号写约 xx.xx 亿美元，保留两位小数。汇率、原币和接口快照保留在底稿。

## 6. Opportunity Lens

### Intake

Canonical 字段为 `research_question`、`available_materials_choice`、`intake_material_type`、`materials_delivery_note`、`evidence_policy`。Markdown parser 支持正式 fenced template 和 legacy key-value 格式。

Run 另有简短人工概括字段 `display_title`，用于列表和页头；完整 `research_question` 继续保存在研究包和 intake 合同中，由正文 requirement matrix 逐项覆盖。页头可显示自然中文 `problem_statement`，短标题不得机械截断长问题。

### 证据策略

- `freshness_first`：弱信号可以进入 early signal，但不能进入核心分。
- `balanced`：默认证据纪律。
- `accuracy_first`：优先官方/一手，冲突未解时阻塞或降级。

### 实体

- `market_linked`：评分、early signal、标的、条件化建议。
- `theory_research`：文献综述、方法、分析、回答、限制和研究底稿；不评分、不进入矩阵、不挂标的。

研究模式存放在 `opportunity_entity_research_profile.entity_research_mode`，不是 taxonomy 的 `opportunity_entity.entity_type`。

### Run pack V2

`tools/opportunity_lens/run_pack_builder.py` 提供 canonical 构建入口；`run_pack_contract.py` 校验 schema、原始来源定位、显式英文译文、独立证据组、序列打包、数据点身份、理论/市场边界、底稿字段、因子证据、标的差异、正文和 review records。新 pack 还声明 `research.modeling_skills.v1` 并保存 Skill 执行、独立模型冻结和外部对账哈希；缺少被路由记录时不得发布。市场实体缺因子评分或标的会失败。

普通/重要因子最低独立证据组为 3/5。独立单位是 `independence_key`，不是 source URI 或文章数量。

### 状态和发布

装载默认进入 `under_review/reviewable`。纯理论 run 可跳过 scoring。`publication.py` 检查五个 canonical quality gate、P0、基础 reviewer，以及按公开页面、market-linked 和证券标的自适应追加的 browser/calculation/financial reviewer；记录 hash、闭环状态和 reviewer 类型通过后才设 `completed/published`。

`opportunity_quality_gate_result` 保存确定性 gate；`opportunity_agent_review_log` 保存 canonical stage、reviewer id/kind、输入/输出 artifact hash、findings 和 reconciliation。静态 workflow 描述不算执行记录。

旧 pack 缺版本时归为 legacy；既有 DB 页面可读，历史 JSON 可审计但不承诺无修改重载，且不能无升级重新自动发布。专题构建器和历史 run 是资产，不是通用 crawler。

### 展示

Opportunity Lens blueprint 位于 `tools/viewer/opportunity_lens_blueprint.py`，read models 位于 `tools/opportunity_lens/read_models.py`。页面使用 evidence drawer；公开正文不得泄露裸 URL、机器 URI、路径或 raw JSON。

公开章节采用“问题—证据/数据—方法（如有）—分析与结论”。“如果想进一步研究，需要补充的信息”不再是标准栏目；客观不可得必须写回当前问题的分析、近似和置信度，不能替代本轮 requirement 回答。

稳定页面族包括列表、研究请求、run、研究对象列表、实体、标的、因子、指标槽、审计、补充研究和导出。不同 pack schema 可以使用不同数据适配器/模板，但公开页面职责与导航一致；Run 阅读顺序为紧凑身份/KPI、全宽研究报告、研究对象、结构化可视化，以及确有长期趋势价值时的长期序列。

V2 页面审计覆盖桌面/移动、宽表顶部 mirror、KaTeX 排除、英文金额、source drawer、理论/市场实体和标的页。

### Deferred

当前没有通用真实 crawler、自动多语搜索生产编排和真实 PDF renderer。Export 可产生 HTML/manifest 时，不得称为真实 PDF 已完成。

## 7. 动态情报

代码位于 `tools/dynamic/`，配置以 `tools/dynamic/config.yaml` 和函数体为准。它处理新闻、意见领袖、事件和调度，写 `research.db`。旧注释可能落后于函数实现，判断能力必须读 live code。

真实 tick、fetch、ingest 会写库或访问外部服务，未经授权不得运行。凭据目录只可确认存在，不可读取内容。

## 8. 情绪、招聘、K 线和供应链

代码位于 `tools/sentiment/` 及关联脚本，写 `sentiment.db`。三层情绪、关键词、招聘、K 线和 Funda 镜像有各自表和任务，不得与行研 source/data point 混写。

历史 K 线中可存在 Wind provenance；Wind 已进入允许列表，但当前统一 K 线入口仍按其实际实现使用 Tushare/yfinance。若新增 Wind K 线，必须接入同一公司全集、状态传播和写库门禁，不能恢复旧脚本。

## 9. 研究员假说

假说和 researcher 数据在 `research.db`，viewer 路由位于 `tools/viewer/app.py` 和 `templates/hypothesis/`。假说是研究员工作台对象，不等同于经过 source gate 的行业事实。

## 10. Viewer 与副作用

Flask 单体同时注册主路由和 Opportunity Lens blueprint。GET 页面主要读取，但进程包含写入路由，连接也不都强制 mode=ro，因此不能笼统称 viewer 只读。

默认 smoke 只用 GET。需要测试写入 API 时，使用临时 DB/目录并由任务明确授权。

## 11. 自适应审查与 manifest

V2 把机械检查和判断分开：

- 确定性 gate 始终执行；
- 计算、评分、财务、写作、引用和页面按 artifact/risk 触发 reviewer；
- 最终一次综合审稿；
- 失败只重跑相关 stage；最多三轮，未闭环即 blocked。

`tools/research_core/workflow.py::ResearchWorkflowRun` 把 brief、artifact hash、gate、review plan 和 manifest 串成无主题模板的统一接口。A/B `ingest_research.py` 已直接调用该接口，正式 B 轨可用 `--workflow-request` 传 requirement matrix；缺失 request 时只允许暂存，contract RED 且 requirement blocked。A/B execution manifest 默认落 `cache/research_runs/<run_key>/manifest.json`，同 tag 重跑先归档旧记录；claims 输入进入内容寻址缓存。C 轨由 `workflow_bridge.py` 把 V2 pack 编译为共享 brief/manifest，并与原有 quality gate/review log 一同落 DB，发布时按 DB 最新记录同步。Manifest 读取会校验自身 hash；没有 reviewer id、输入/输出 hash 和 findings 不能证明 reviewer 执行。历史 run 不追溯补造 V2 记录。

## 12. 验收

- Python：compileall、相关 unittest。
- DB：临时库 migration、schema verify、foreign key check，再决定 live migration。
- API：Flask test client、契约字段、GET no-write。
- 页面：Playwright 桌面/移动、DOM、滚动、图片像素和证据抽屉。
- 文档：引用、原文语义、来源索引、重复、模板、编码和渲染。

测试输出必须是本轮实际结果。历史“曾通过”不能替代当前测试。

## 13. 备份与恢复

2026-07-12 工作流 V2 重构前完整备份：

`D:\quant\industry_demo_backup_20260712_231322_pre_agent_workflow_refactor`

源/备份文件数、总字节和三个数据库 SHA256 已一致校验。V1 活动上下文另存 `archive/project_history/retained_originals/workflow_v1_20260712/`，便于在项目内追溯。

2026-07-13 项目清理前恢复点：

`D:\quant\industry_demo_backup_20260713_104934_pre_cleanup`

非 live 文件按相对路径/大小核验，四库使用 SQLite backup API 生成事务一致快照。清理使用 `tools/maintenance/project_artifacts.py` 生成逐文件 manifest，并由 `tools/maintenance/apply_project_cleanup.py` 按哈希、保护路径和恢复位置逐批执行。历史信息集中在 `archive/project_history/`，该目录不进入 Fresh Session，也不承载 live 配置、代码、数据库、papers 或 cache。完整基线、批准动作、逐批结果和最终 inventory 在 `archive/project_history/cleanup_manifests/`。
