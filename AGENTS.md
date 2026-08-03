# AGENTS.md - Codex 项目入口

项目根目录：`D:\quant\industry_demo`  
活动工作流：`research.workflow.v2`

本项目把 AI/半导体产业链的 PDF、网页、API 和数据库资料转成可追溯数据点、行业文档、公司透视、动态情报、情绪/供应链数据、研究员假说和 Opportunity Lens，并由 Flask viewer 展示。

权威顺序：

```text
用户最新要求
> live 代码 / DB / 前端
> config/research_workflow.yaml 与活动文档
> 当前 live 快照
> 历史设计、prompt、日志和 CLAUDE 时代文件
```

所有面向用户的回复、进度、报告、审计和验收默认使用中文。代码标识符、路径、API、URI 和专有名词可保留英文。严肃内容不使用 emoji；网页图标可以保留，但不得出现连续问号式损坏占位符。

## 1. Fresh Session

默认只读：

1. `AGENTS.md`
2. `codex_context/LIVE_STATE.md`
3. `config/research_workflow.yaml`
4. 与当前任务直接相关的活动文档和代码

研究任务加读 `docs/research/RESEARCH_WORKFLOW_V2.md`。C 轨再读 `opportunity_lens/MODULE_CONTEXT.md` 和 `opportunity_lens/HUMAN_READABILITY_STANDARD.md`；涉及开放检索、评分/指标槽、独立 DB/状态或 Viewer/输出时，分别按职责读取顶层 `C轨研究启动与开放探索输出标准_V0.9.1.md`、`C轨供需失衡评分流程与可解释计算体系_V0.8.1.md`、`C轨独立DB与开放研究深度补充修订说明_V1.0.md`、`C轨输出模板与前端可视化标准_V1.1.md`，不从旧 run 产物反推协议。需要完整系统边界时再读 `codex_context/PROJECT_COMPLETE_UNDERSTANDING.md`；需要路径/表/路由时读 `codex_context/FILE_DB_INDEX.md`。

不要默认读取 `PROGRESS_LOG.md`、`archive/project_history/`、全部旧 SOP、全部 skills、`opportunity_lens/design/**`、`plan/**`、补丁 prompt 或 run 历史。只有追溯具体设计原因时按需读取。活动/兼容/历史分层见 `docs/research/ACTIVE_FILE_AUTHORITY.md`；旧 `CLAUDE.md` 和清理前完整进度已集中保留在 `archive/project_history/retained_originals/root/`。

需要 agent 方法时先看 `skills/README.md` 的活动清单，只读取与当前 artifact/风险对应的 skill；旧 academic prototype 和固定 phase/persona skill 不进入 A/B/C 默认上下文。

执行任务前重新查询会变化的事实：数据库计数、当前 run、服务进程、端口和动态表。`codex_context/LIVE_STATE.md` 是快照，不是永久事实；架构变化后用只读命令 `python -m tools.maintenance.build_context_snapshot` 更新。

涉及 `sentiment.db` 的原文保留、窗口补漏、评分、聚合、迁移或瘦身时，必须加读 `codex_context/SENTIMENT_DB_RETENTION_TODO.md`。用户已确认的目标是：完整窗口在抓取、评分、永久聚合和校验通过后即可直接删除原文，不再默认保留 14 天；`partial/running/failed` 和未映射数据必须先查明并收口，不能粗暴删除或伪装成完整。该文档记录的是活动待办与方法，动态数量仍须重新查询 live 库。

## 2. 红线

- 先查代码、DB 或文件，再下结论；不得凭上下文记忆声称当前状态。
- 未经明确授权，不运行会写库或调用外部服务的抓取、回填、迁移、scheduler、Tushare/yfinance、DeepSeek、Xinghan、新闻、KOL、情绪和招聘任务。
- 不读取、复制、总结或外发 `tools/dynamic/secrets/*` 中的密钥、cookie 或 storage state。
- 不造数。找不到就写“客观不可得/待补充”，说明已查来源、不可得原因、可接受代理和结论影响。
- 不把 AI 摘要、文献综述、卖方结论、专家纪要、论坛或二级转述当一手事实。
- 不直接 INSERT `industry_data_point`；只走 `tools/pipeline/db_writer.py::write_data_point()` 或批量封装。
- `research.db`、`sentiment.db`、`opportunity_lens.db`、`financial.db` 不得混写；跨库只使用经定义的只读语义链接或显式事务封装。
- Smoke 默认只发只读 GET，不自动调用 POST/DELETE/refresh/export 等写入路由。
- 不用 `git reset --hard`、`git checkout --` 等破坏性命令；项目当前不保证存在 Git 元数据。
- 大规模删除、迁移或目录瘦身前必须先读取 `codex_context/BACKUP_REGISTRY.md`，在 `D:\quant` 下创建名称包含 `industry_demo` 的临时外部安全副本，并完成非活动文件清单与 SQLite 事务一致快照核验；不能把复制失败或仅有 WAL/SHM 的目录声称为有效备份。验收完成后必须运行 `python -m tools.maintenance.refresh_project_backup --version "<版本>" --reason "<原因>"`，原子刷新项目内唯一 `backup/latest`。确认归档与四库快照校验通过后，先 dry-run、再用 `tools.maintenance.prune_external_project_backups --apply` 受限删除临时和旧的项目外 backup/rollback；不得长期保留多个项目外备份目录。
- 项目文件清理必须先用 `tools/maintenance/project_artifacts.py` 生成显式 manifest，再由 `tools/maintenance/apply_project_cleanup.py` 逐批 dry-run/apply；不确定项保持 `pending_review`。历史信息统一进入 `archive/project_history/`，该目录不得成为 live 配置、脚本、DB、papers 或 cache 的新落点。

## 3. Live 架构

- A/B 行研、公司、来源、动态新闻、意见领袖、事件和假说：`data/research.db`。
- 三层情绪、关键词、招聘、K 线和 Funda 供应链镜像：`data/sentiment.db`；情绪模块只读 attach `research.db`。
- C 轨 Opportunity Lens：`data/opportunity_lens.db`；通过 evidence URI 只读引用 A/B。
- Wind、Tushare、yfinance 的结构化历史财务、市场估值、一致预期、公司指引、内部预测、市场隐含结果和模型计算账本：`data/financial.db`；公司页和研究模型按规范证券身份只读引用，不再把这些记录新增为普通 `industry_data_point`。
- Flask：`tools/viewer/app.py`；模板和静态资源在 `tools/viewer/templates/`、`tools/viewer/static/`。
- Windows 内网部署入口是根目录 `restart_viewer.bat`，只读预检为 `tools/viewer/preflight.py`，操作说明见 `docs/VIEWER_内网部署.md`。部署闭包必须包含 `data/`、`docs/`、`tools/`、`papers/`、`opportunity_lens/`、`config/` 六个目录，以及被配置或四套 live 数据库实际引用的必要 `cache/` 文件和活动财务模型目录；不得把整个临时 cache 无差别打包，也不得遗漏仍被引用的研究证据、模型和审计闭包。标准广播构建必须通过 `build_viewer_broadcast_bundle.py` 自动计算并写入必要 cache 清单，不能依赖人工另行补包。工作流 V2 后缺少 `config/research_workflow.yaml` 会在 Flask 导入阶段失败。

实时表数、行数、行业和 run 见 `codex_context/LIVE_STATE.md`。任何“已实现”“已审核”“已发布”“已在线”必须说明证据类型：代码门禁、DB 记录、独立 reviewer 记录、命令测试或浏览器实测。规范文件存在不等于工作流已执行。

## 4. A/B 行研

活动合同：`docs/research/RESEARCH_WORKFLOW_V2.md`。

### A 轨

输入是行业名和 `papers/<行业>/`。默认覆盖产品边界、价值链、历史、竞争、市场空间、公司壁垒、行业经济性、风险、监控和综合判断。

### B 轨

输入是用户 prompt、资料和独立公开搜索。必须把“prompt 全集 + A 轨默认 coverage”编译为 `ResearchBrief`；代码只合并完全相同项，语义近似项不得自动删除。每条要求的 origin、状态、产物和证据引用写入 execution manifest；限制完成必须说明客观缺口，未完成或阻塞项不能通过发布门禁。公司研报降权，不能把本地公司池当候选上限。

### 共同输出

现有 viewer 继续读取主文档、Q0-Q5、可选 Q6、公司透视、估值和产业链。页面集合是兼容层，不是固定分析模板。成熟行业包只用于校准深度、证据和表达质量，不得照抄标题、句式和段落节奏。

统一 claims 入库是 `tools/pipeline/ingest_research.py`；旧 A/B ingest 脚本是兼容 wrapper。该入口必须同时生成 `brief.json` 和 `manifest.json`、记录五项确定性 gate、按 artifact 配置 review plan，并把 claims 放入内容寻址缓存。B 轨正式任务应通过可选 `--workflow-request <request.json>` 传入原始 prompt requirement matrix；旧调用不传该参数时仍允许数据暂存，但 contract gate 必须为 RED、缺失 prompt requirement 必须标记 blocked，补齐前不得发布。默认严格模式遇到无效记录立即失败，不静默跳过。相同 tag 重跑时，旧 brief/manifest 必须先复制到 `history/`，不能静默覆盖丢失。

第一轮每个问题轴必须分别生成研报 `report` 与网络 `web` 搜索任务，两条链路分别抽取、去重、评级和登记 `source_channel`；一方命中不得减少另一方预算。分析后只有明确证据缺口或冲突才生成第二轮任务，并记录对应 `gap_trigger`。

- A/B/C 的 `report` 链可使用 `tools.research_sources.datayes_reports` 通过 Playwright 操作萝卜投研正常网页，不调用或逆向站点 API。账号密码只由本机遮罩输入框写入 Windows Credential Manager，并由 `keyring` 的 `WinVaultKeyring` 后端调用；不得经聊天、命令行、环境变量、项目文件或日志传递。浏览器 profile 只放在 `tools/dynamic/secrets/datayes_profile_v2`，不得进入 Git、广播包、cache 审计、DB 或研究产物。
- 萝卜投研统一使用标题检索：公司报告默认最近 183 天，行业报告默认最近 366 天且优先 20 页以上；正式研究应尝试取得 1—2 份外资卖方报告和 1—2 份国内推荐报告。站内推荐流没有相关国内报告时可下载标题检索命中的近期国内深度报告作为显式回退，但不得把回退计作平台推荐，严格配额仍记 shortfall；客观不足必须记录真实数量、关键词和影响。下载文件在验证 PDF、页数、SHA256 后按 Windows 安全路径写入 `papers/<行业>/`，并写 `_source_manifests/` 供 A/B ingest 和 C 轨 provenance 复用。萝卜投研只是聚合入口，独立性按底层券商、标题和发布日期计算；卖方研报是二手研究/冻结后外部对账材料，不能替代公告、监管披露或产业原始数据。

- 证据评级与原文语言、机构所在国家或是否需要翻译无关。英文研报、英文公司资料和英文产业资料与同类型中文资料同级评价；权重只由来源层级、是否为原始材料、时效、方法透明度、独立性、问题相关性和可复核性决定，不得因英文原文、翻译成本或本地资料更易获得而降权。涉及全球产业链、海外客户、海外竞争者或国际技术路线时，应主动同时检索中英文资料；中文译意是公开展示要求，不是证据降级因素。

### A/B 数据点

- 必填 metric、period/as_of、unit、value、source、source_excerpt、extraction_method。
- 新数据只允许 `pdf_direct`、`web_fetch`、`inferred`；`unknown` 和 `template_estimate` 仅限显式 legacy migration。
- `inferred` 必须在 note 写公式、输入或计算口径。
- 数值必须有限；industry/source/company 外键必须存在。
- 批量写入用 savepoint；任一记录或共识计算失败默认回滚整批。
- 同源同对象同口径序列在研究事实和证据计数层面合并为一个数据点，不能拆日期凑 coverage 或证据数。
- A/B 历史关系表可保留逐期观测行，但 coverage/证据计数必须使用统一 ingest 生成的 `parallel_research_fact_count`；C 轨 V2 则必须以一个数据点加 `observations` 数组入库。

### 公司和财务

- 新市场、估值、财务和 K 线允许 Wind、Tushare 与 yfinance；Akshare 继续全局禁止作为新来源。Wind 只使用项目根目录 `WindPy.py` 对接的固定内网 HTTP 代理，不使用正式桌面 SDK，也不得把代理地址改成外部未知服务。
- A 股以 Wind 为主源，Tushare 为逐字段补缺、逐机构预测明细和公告/重述审计补充；海外、台股、日股等继续以 yfinance `get_info()` 和财务表为主。A 股合并必须遵守“Wind 非空有效值优先，Wind 客观缺失时才采用 Tushare”，并为每个字段分别保存 provider、原始字段、证券代码、时点、单位和计算口径；不得把合并快照伪装成单一来源，也不得用 Tushare 静默覆盖同口径的 Wind 非空值。
- Wind 默认只允许单证券或少量证券、窄字段、受限日期范围的小型取数。单次超过 10 只证券、20 个字段或预计 5,000 个观测，或者同一任务/北京时间自然日累计预计超过 50 只证券或 50,000 个观测，必须先向用户说明证券范围、字段、日期区间、预计数据量和用途并取得明确 permission；全 A 股历史、全市场截面和分钟长历史天然属于大规模请求，即使估算低于阈值也必须先问。不得拆成多个小请求规避门禁。Wind provider 的单次硬门禁不能替代任务级累计审计。
- 两源同口径同时点数值冲突时保留双方观测并进入对账，不做算术平均；公司公告、交易所/监管披露仍是财务事实的最终权威。Wind、Tushare 收录同一卖方报告时不算两条独立证据。
- 结构化供应商财务写入 `financial.db`：actual、market、consensus、guidance、internal_estimate、implied 必须分层；同一观测身份的修订写 revision，不复制成新事实。刷新任务不得更新 `research.db.company` 的旧财务聚合列，也不得把 Wind/Tushare/yfinance 原始快照复制为 A/B/C 的 source、claim、data point 或标的数据点；研究包只保存冻结模型、对账结论和指向公司页/财务库的只读语义关系。旧聚合列和旧 `industry_data_point` 财务记录只读兼容。
- 涉及公司未来盈利、估值、行业供需或事件概率时，必须由 `ResearchBrief` 的确定性路由按需启用 `company_financial_modeling`、`company_valuation_modeling`、`industry_supply_demand_modeling`、`probability_scenario_modeling`；只核验新闻/专利/招聘时不得误加载。公司独立 FY1—FY3 模型必须先冻结输入输出哈希，再读取一致预期和研报对账；新 run 缺少被路由 Skill 的完成记录、财务冻结或外部对账时不得发布，历史包没有新合同标记时保持兼容。
- 公司财务建模中的卖方预测中位数、FY1—FY3差异和估值对账，只纳入研究截止日前最近两个季度发布的同一公司研报，并在正文写明机构、发布日期和预测口径。该筛选和后续权重对中英文研报完全一致；更早的公司研报可用于解释历史业务或预期变化，但不得混入当前财务预测中位数；停止覆盖等非活跃报告可以保留其截至报告日的最终模型，但必须标明状态。Wind等数据商一致预期单独列示，不与可能重复收录的底层卖方报告再次合并计权。
- A/B 行研或 Opportunity Lens 将上市公司列为龙头、重点公司或财务建模对象时，必须主动取得研究截止日前最新的当年年报/季报以及最近两个季度内可核验的中英文机构预测或公司研究，保存到对应 `papers/<行业>/` 并登记为来源；公司公告用于经营与会计事实，近期机构预测用于冻结后的外部对账，二者不得混为一类。充分搜索后客观不可得时说明已查范围、缺口及对公司页和估值置信度的影响，不得因本地资料不足直接留下空公司页。随时刷新的 Wind/Tushare/yfinance 结构化快照仍只进入 `financial.db`，不因下载了报告而复制成普通行研数据点。
- 新下载、复制或生成到 `papers/` 的研报必须先经过 `tools/pipeline/paper_paths.py` 的 Windows 安全文件名规范化：文件名最多 96 个字符、项目相对路径最多 180 个字符，保留可读前缀并追加稳定哈希消除冲突。下载器和统一 ingest 必须在形成数据库或研究包引用前完成规范化；已经被代码、文本、缓存或数据库引用的旧文件不得单独手工改名，必须使用 `python -m tools.maintenance.migrate_paper_paths` 同步迁移所有 live 引用。广播包构建遇到违规路径必须失败，不得继续生成在 Windows 上无法可靠解压的包。
- Opportunity Lens 涉及已解析 `company_id` 的上市公司且数据足以形成财务模型时，应生成 `company_financial_profile_export.v1`，通过独立工具 `python -m tools.financial.opportunity_profile_export <export.json>` 把 FY1—FY3 独立预测、适用的多方法估值和当前市场隐含结果同步到 `financial.db`；C 轨 loader 仍不得跨库写入。数据或方法门禁不足时不造数，导出中省略不适用方法并在研究结论说明具体缺口。
- 上市公司检查 PE/PB/PS、人民币市值/美元等值、毛利率、净利率、经营现金流、capex、至少三年序列和近期事件。
- 金额默认“亿元人民币（约 xx.xx 亿美元）”，倍数和比例保留两位小数。
- 亏损、退市、私营、子公司、接口不可得和待补抓分别说明；空表不得通过。
- 行研或 Opportunity Lens 涉及新的上市公司时，先以公司主体、ticker、市场和股份类别精确核验；已有画像复用规范 `company_id`，不存在时走 `tools/pipeline/ensure_listed_company_profile.py` 显式创建。模糊名称、母子公司、A/H/ADR 冲突时不得自动猜测。公司链接统一进入 `/company/<company_id>`，C 轨 loader 不得在自己的事务中越库隐式创建公司。

## 5. C 轨 Opportunity Lens

正式请求目录：`opportunity_lens/intake_requests/`。公开 canonical 字段是 `research_question`、`available_materials_choice`、`intake_material_type`、`materials_delivery_note` 和 `evidence_policy`；历史别名只在 legacy parser 边界归一。

### 稳定产品与执行合同

工作流精简前已经成立的 Opportunity Lens 产品合同继续有效，并在本节重新成为活动规则；协议来源是 `opportunity_lens/C轨输出模板与前端可视化标准_V1.1.md` 与精简前保存的通用规则，不是从 run1-run8 的产物外观反推模板。旧 run 只用于兼容验收，不能决定新研究正文写什么；新写作要求只叠加到既有产品合同，不替换它。

- 页面族保持独立职责：研究列表、研究请求、run 总览、研究对象列表、研究对象详情、标的详情、因子追踪、指标槽追踪、审计、补充研究和导出。稳定路由见 `opportunity_lens/MODULE_CONTEXT.md`；pack/schema 适配器可以不同，但不得把这些页面改成无信息重定向或另起一套公开信息架构。
- Run 页沿用同一工作台骨架：身份与状态/KPI 后，完整研究报告使用全宽阅读区；其后是研究对象，底部是“因子热力图与结构化总览”和在确有长周期价值时出现的“长期序列总览”。机会矩阵、评分、机会线索等组件按实体类型和数据是否适用条件显示，不适用可以省略，但不能借此删除对应独立页面或导航职责。
- `market_linked` 实体页继续承担评分、因子、证据、事件、标的与条件化建议；`theory_research` 实体页继续承担研究问题、方法、文献综述、研究指标、分析、回答与限制，且不评分、不挂标的。标的页、因子页和指标槽页必须能独立完成各自追踪任务，不能只跳回 run 页。
- 审计信息、补充资料和导出状态保留在各自页面或内部审计层，不挤进公开研究正文；公开正文不显示 P0-P13、E0-E8、内部情景代码、字段完成度或参数 owner 等生产标签。
- C 轨执行保持 producer-reviewer loop：来源/数据生产后做 evidence 核验；模型、概率、公式和财务生产后做 calculation/science/financial 复核；正文完成后做 writing 复核并在该 stage 内执行 citation verification；页面完成后做 browser 复核；最后只做一次综合 final review。失败只打回相关 producer，并用当前产物哈希重新复核。

### 实体模式

- `market_linked`：可评分、可有 early signal、必须绑定可点击标的或交易/观察工具，并有结构化标的数据点和条件化建议。
- `theory_research`：必须有文献综述、research profile 和计算/证据底稿；不得评分、进入机会矩阵、生成 early signal 或挂标的。

### 证据门槛

- 真实研究至少 100 个平行数据点，不是 100 个序列观测。
- 普通因子至少 3 个独立证据组，重要因子至少 5 个；按 `independence_key`，不按 URI 数。
- 弱/灰源只能进入 early signal/reference，不能抬高核心 14 因子。
- 同一底层公告、转述、转载和翻译属于一个证据组。
- 标的研究必须主动搜索官方产品、IR/公告、ticker、客户/供应商和替代路线，不能只依赖本地研报。

### 开放检索与新近线索

- 搜索资源按问题的新颖性、时效性、不确定性和结论重要性增加；越新的产业变化、越可能改变概率或财务结论的主张，越不能因已有研报或达到最低来源数提前停止。用户给的链接、研报和本地资料只作为 seed，不决定候选上限、来源上限或搜索结论。
- 执行“大胆搜索、小心求证”：可以主动搜索产业媒体、公众号、论坛、社媒、招聘平台、展会照片和供应链转述来发现产品、客户、产线、专利与人员线索，但先登记为 `weak_signal/reference`，再追溯原始公告、专利全文、公司/客户/供应商、政府项目、产品规格、认证或财务记录。弱源本身不得直接进入核心评分、概率更新或财务输入。
- 每条可能改变核心结论的新近主张至少执行四类核验动作：追最早可见出处；核对主张中的主体、产品、时间和数量；从公司/客户/供应商/专利/招聘/设备/展会中寻找独立侧证；主动搜索否认、口径冲突和替代解释。某类公开资料客观不存在时记录已查范围，不伪造“多源确认”。
- 多篇文章说法一致不等于多方独立验证。必须识别共同措辞、共同数字、共同图片、共同研报或共同匿名消息源；同源转载只算一个 `independence_key`，来源数量不能抬升可信度。
- 对“多方反复提及、决策上重要、但仍无法用强证据验证”的线索不得静默删除。应以自然中文说明具体说法、最早可见出处、支持与冲突、已查范围、尚缺什么以及若属实会怎样改变结论，并明确标为“重要但尚未验证的线索”；它只能影响补证优先级或不确定性范围，不能伪装成已确认事实。
- 搜索停止需要同时满足问题轴覆盖、关键主张溯源、反证搜索和边际新增下降。正式 pack/manifest 应记录弱线索数、追溯到原始来源数、同源重复数、仍未验证的重要线索数及其处置。

### Run pack V2

- 构建器：`tools/opportunity_lens/run_pack_builder.py`。
- 契约：`tools/opportunity_lens/run_pack_contract.py`。
- `pack_schema_version=opportunity_lens.run_pack.v2`。
- `workflow_contract_version=research.workflow.v2`。
- source 必须有 `independence_key` 与 `independence_rationale`。
- source 必须有原始 URL/本地原文定位；英文 source 必须显式写 `title_zh`、`excerpt_zh`，英文 claim/数据点/底稿摘录也必须写对应中文译意。
- 静态 `workflow_review_contract` 不能替代 `review_records`。

装载器默认进入 `under_review/reviewable`：

```powershell
python -m tools.opportunity_lens.manual_run_loader <pack.json> --validate-only
python -m tools.opportunity_lens.manual_run_loader <pack.json> --validate-for-publish
python -m tools.opportunity_lens.manual_run_loader <pack.json>
python -m tools.opportunity_lens.manual_run_loader <pack.json> --publish
```

装载默认不覆盖相同 slug；确需替换既有 run 时显式加 `--replace`，替换逻辑会尽量复用原 run_id。普通暂存或发布命令不得隐式删除旧 run。

推荐正式流程是先暂存、补齐 reviewer/browser 记录，再运行 `python -m tools.opportunity_lens.publication <run_id>` 发布已有 run；不要为了追加审计记录反复替换整包。

V2 C 轨装载时必须把同一 pack 编译为共享 `ResearchBrief` 和 `ExecutionManifest`，分别以 `research_brief`、`research_execution_manifest` 写入 `opportunity_run_manifest`；原有 intake、quality gate、review log 和发布门禁仍是 C 轨 live 事实源。暂存后补 reviewer 再发布时，发布事务必须用 DB 最新 gate/reviewer 记录同步共享 manifest，不能形成两个不一致的审计状态。历史 run 没有这些 V2 记录时不补造、不追溯认证。

显式发布要求五个 canonical gate 均存在且无 RED、无未关闭 P0。基础 reviewer 为 evidence/science/writing/final；公开页面追加 browser，market-linked 追加 calculation，证券标的追加 financial。各 stage 最新记录须为 GREEN、findings 闭环且具备合法输入/输出 SHA256；browser 可由确定性 Playwright 审计完成，其余发布必需 reviewer 和 final 必须为 independent 或 human。旧 run 的历史 published 状态不得反向解释成已经有 V2 reviewer 记录。

C 轨仍没有通用真实 crawler 和真实 PDF renderer；不得把专题构建器或 HTML export 说成这些能力已经实现。

### 页面标题与展示兼容

- Opportunity Lens 页面使用独立、简短的 `display_title` 概括主题；完整 `research_question` 原样保留在研究包和入口合同中，正文必须逐项覆盖其 requirement matrix。页头可另显示一条自然中文 `problem_statement`，但不得直接把整段长请求作为列表标题或页头标题，也不得用机械截断代替人工概括。
- 摘要、章节问题链、表格取舍和文字改写要求只约束研究内容，不构成修改 Viewer 信息架构的授权。除非用户明确要求页面或交互改版，同一产品的不同 run 必须复用上面的稳定产品合同、页面骨架、导航、路由、页面分工和交互；内容可以在既有展示区域内自适应，但不得因 pack/schema 版本或写作规范变化自行新增、删除或重排页面、tab、路由及全局模板、CSS、JS。

## 6. 自适应 review

机器门禁始终先跑：contract、evidence integrity、provenance、duplicate/template、scope/unit/time。

按 artifact 触发：

- 计算、CAGR、CR、权重：独立复算；
- 因子、指数、评分：science/logic；
- 公司和估值：financial completeness；
- 公开 Markdown：writing（内含 citation verification）；
- 新页面或 UI：Playwright DOM/visual；
- 冲突、单一证据组、陈旧数据作当前判断：evidence escalation。

最终只做一次综合审稿，合并科学严谨性与基金经理决策效用。失败只打回相关 producer；最多三轮定向修复，仍未闭环则 blocked。每轮必须保留输入 artifact hash、findings、修订和复核记录，不能只写“已审查”。

## 7. 写作与展示

共同标准：`templates/数据呈现与重写标准.md`。C 轨特有标准：`opportunity_lens/HUMAN_READABILITY_STANDARD.md`。

核心要求：正文独立回答问题；指标说明设计、公式、权重和含义；证据链说明事实、关系、推论和边界；反方实际改变结论；标的字段逐标的差异化；正文不暴露裸 URL、磁盘路径、`opp://`、`source_ref:` 或原始 JSON。

面向用户的每个研究章节和实体专题必须显式分成四个可见部分：“问题”“研究方法与数据”“研究与分析”“总结”。不能只在写作顺序上暗含这四步，更不能把它们揉成一大段连续文字；每个部分使用简短小标题和独立段落，“研究与分析”可以按必要的论点继续分段，最后的“总结”直接写清主体、时间、事件和影响，并可用加粗突出核心判断。只有确实存在复杂模型时，才在“研究方法与数据”中补充关键公式、实际代入值和局限。不得用字段完成情况、审计状态、模型参数清单或表格堆叠替代分析。取消“如果想进一步研究，需要补充的信息”标准栏目；已经充分搜索仍客观不可得的数据，必须在当前问题分析中说明已查范围、采用的近似、结论影响和置信度，不能把本轮应回答的问题延期。结论不使用“决策含义”“专属边界”“破坏程度”等缺少主语的抽象标签；“一页执行摘要：概率、破坏度与投资含义”“联合情景树、概率更新与破坏程度”“决策验证债”“七字段事件监控 dashboard”等旧标题不得复用。

公开正文不得出现 `canonical`、`intake`、字段完成度、输出覆盖卡、参数 owner、内部变量名、D0/D1/D2、A—F、P/H/C、low/mode/high 等生产或模型内部术语；确有决策必要时必须先改成自然中文并当场解释。不得把没有直接证据写成“未知”：分别使用“目前没有直接证据”“公开资料不足以判断”或“无法根据现有资料推断”，并说明它会怎样影响结论；“未知”不得作为机械状态标签。公式必须正常渲染或写成可读算式，逐一定义输入、计算过程、结果和局限，不展示代码表达式。

当章节确有建模或计算时，先判断核心关系能否仅靠语言清楚复述。若模型包含多层乘积、加权汇总、情景递推、跨期传导或其他难以用一句话准确表达的关系，应在“建模方法”“计算方法”或自然等价栏目中集中展示最关键的一至三个完整公式，例如“有效产量＝运行时间×名义节拍×设备综合效率×良率”，并紧邻解释各输入、输出、口径和限制。简单四则运算、已经能用短句说清的关系或不改变理解的中间公式不单独展示；不得把所有底稿公式搬进正文。

当多个类别同时跨多个期间或指标形成密集数据，例如时序数据、公司历史与预测财务、业务分部或多情景结果，应优先把相关指标整合成一张高信息表格，再在“研究与分析”中解释趋势、差异和原因；不得把每个指标或每个年份拆成许多小表。是否制表以“能否显著提高横向比较、趋势识别或复算效率”为判断标准，不按数据条数机械触发；短序列、单指标或正文更清楚时不制表。公式和表格都必须服务于正文已经提出的问题，不能因为存在模型或一组数字就自动增加展示组件。

每个 topic 的图表数量按问题决定，不设“一节最多一张”的硬限制；通常控制在三张以内，零张、一张、两张或三张都可以。能够在同一坐标或同一高信息表中清楚比较的财务时序、业务分部、情景或估值结果应优先整合，只有量纲、问题或阅读负担确实不同才拆开；数量上限不能替代信息增量判断。

同一报告若存在名称相近但计算合同不同的概率、分类或损失指标，必须分别写清输入、分母、运算和用途，禁止用同一自然语言标签混写。专家判断权重必须在输入底稿标明“非外部事实”、残差计算和未校准边界；公开正文引用的模型输入与输出文件必须把实际内容 SHA256 写入 run pack，使 reviewer 和发布冻结绑定真实假设而不是可变路径。

单位转换必须先做数值换算，再改展示标签，禁止只把字段单位重命名。例如模型字段为“十亿美元”时，展示为“亿美元”必须把数值乘以 10；“百万个”改写为“万个/亿个”也必须同步换算。calculation、financial 与 writing reviewer 都要用至少一个量纲反算和数量级常识检查公开表格，并为专题关键单位写回归测试。

每张公开表格必须回答正文已经提出的一个问题。若删除某列不改变事实理解、计算复核或决策，就删除该列；若两张表回答同一问题，就合并。公开页不展示字段覆盖率、完成矩阵、参数归属或审计清单。减少低信息表格不等于取消表格：当模型结果需要比较多个主体、情景或期限，表格能更直观地呈现盈利、现金流或估值变化时，应优先保留一张高信息结果表，再用正文解释差异、原因和结论。财务专题原则上优先合并为一张核心历史财务表、一张未来情景结果表；敏感性只有在确实增加决策信息时才展示，既可用至多一张表，也可用更清楚的量化正文，不能为了满足版式惯例另造低信息表格。额外表格必须说明不可替代的信息增量。情景使用完整中文名称，不让读者记代码。

公司型研究长期遵守以下基础输出合同：

- 已解析为规范 `company_id` 的上市公司，在每个独立正文段落中第一次提及时链接到 `/company/<company_id>`；母子公司或不同股份类别必须先说明研究与财务归属，不能把近似名称链接到错误主体。数据供应商请求、代理错误、重试和逐字段补缺等执行过程只进入内部日志与审计；除非失败本身改变结论，公开正文只说明最终可得数据、客观缺口及其影响。
- 多家公司经营基数、口径或风险传导不同，必须分别建模和分析；不要为节省版面把主体挤进一张难读的历史财务表。核心公式之外还要公开实际代入的关键数值、来源或判断依据、计算结果和敏感性；本地材料缺少未来利润、市值、PE/PB、ROE/ROA等重要对账数据时，应继续检索可核验的最新外部资料，仍不可得才说明边界。
- 公司或研究实体页不仅判断外部事件是否发生，还要分析它对主体自身的短期与长期收入、利润、现金流、资本开支、上下游关系和估值影响；不同受影响公司分别给出情景结果、分析和条件化投资判断。PB—ROE/PB—ROA只在经济逻辑和数据适用时使用，并解释资产回报、杠杆和估值之间的关系，不能仅作装饰图。
- 涉及公司筛选和投资组合时，公开研究顺序固定为“产业/产品与客户兑现→逐公司收入、利润、现金流和估值验证→公司优选与组合”。候选表中进入排名、评分或组合讨论的每家公司，都必须至少核验产品、付款人或客户、合同/订单/量产/部署、财务传导和估值状态，不能只列名称。销售AI产品的公司逐家回答“谁付钱、买了什么、处于签约/启动/上线/验收/收入/回款哪一步、客户为什么续费、还可复制给多少同类客户”，并把合同额经收入确认、增量毛利、交付/推理成本、营运资金和资本开支传到自由现金流；使用AI提高经营效率的公司逐家核验实际采购或部署成本、产能/效率/服务改善、用工变化、回收期及其短期和长期财务影响。公司宣传的效率案例必须标明不是独立审计结果；价格客观不可得时只能做客户侧盈亏平衡敏感性，不得把案例数量乘成公司收入。证据不足的公司可以保留为经营对照，但不得获得伪精确权重；通用公司简介、方向稀缺或“未来继续观察”不能代替上述分析。
- 组合正文必须逐公司说明经营与估值评分怎样进入基础权重、主动调整、方向/单股/现金约束和最终权重；相关性、再平衡频率和风险统计只保留改变配置结论的要点，不得挤占公司质量、市场定价和财务模型分析。复杂核心公式在 Markdown 中使用独立展示块（`$$ ... $$`）并紧邻解释变量，不能把完整公式挤在行内。
- 表格按语义分配列宽，主体名称和关键结果不得因通用等宽规则被迫断行；可视化在渲染前按经济观测身份去重，同一报告期的兼容记录不得形成重叠标签。桌面和移动端都要实测标签、表头、最右列和局部滚动，不能用代码存在代替视觉验收。

C 轨主报告不得再次完整复制实体页、标的页或证据页正文；主报告概括跨主体结论并提供可读链接，详细分析只在相应页面出现一次。公开来源索引以可读标题、发布方、日期和可点击引用为主，不把内部 source id、记录号、表名或其他机器定位字段单独列成信息列。

C 轨 run 首页由多个摘要 section 组成，而不是把全部实体研究压成一个长摘要；每个首页摘要 section 最多 700 字，详细行业、公司、模型和证据下沉到对应研究实体。摘要和“总结”优先给出研究员可直接使用的结论：明确写看多、谨慎或回避的方向/公司及原因，少写“继续观察、等待确认、以后补充”等不改变当前决策的车轱辘话；只有问题本身询问监控项，或证据缺口会实质改变结论时才保留验证条件。

浏览器验收必须逐张表检查桌面和移动端：正文不得整页横向溢出；最右列在滚动到右端后完整可见；长文本不重叠、不被裁切；表头与单元格在截图中可辨认；键盘可以到达局部滚动容器。不能只用 DOM 存在、路由返回 200 或“有横向滚动条”替代视觉检查。结构化 browser 审计必须绑定当前研究包和 Viewer 代码/模板/CSS/JS 组合哈希，并记录全路由、双 viewport、逐表几何、每张表滚到最右端后的局部截图与哈希。每个公开路由的全部唯一证据引用还必须用 Enter/Space 实际打开，核对证据 API 为 200、抽屉可见且无横向溢出、标题与来源级别/日期为人话、没有内部 URI、机器字段或原始 JSON，并保存代表性抽屉截图与哈希。其他必需 reviewer 输入哈希必须等于当前研究包哈希；任何产物或页面资源变化都使对应旧 GREEN 失效。writing、browser 和 final reviewer 发现低信息表格、机器字段、重复段落、公式未转译或最右列不可读时必须判失败。

因子热力图等卡片式组件还必须逐项检查完整标签：名称获得独立、足够的宽度，不被分数/状态徽标挤压，不以省略号、固定高度或容器裁切隐藏文字；桌面和移动端都要读取标签的可见几何并检查与徽标是否重叠。仅依靠 `title`、hover 或因子详情页显示全称不能替代卡片本身可读。

英文来源保留英文原文并给中文译意。2024 年或更早资料用于当前判断时显示严重时效警告。长期序列有趋势价值才画图；短序列不凑图。

## 8. 其他任务路由

- 公司透视/估值：加读 `CLAUDE_COMPANY_PROFILE.md` 和相关 live pipeline；A 股执行 Wind 内网 HTTP 主源、Tushare 逐字段补缺合同，以 `data_source_policy.py` 和 `config/research_workflow.yaml` 为准。
- 动态新闻/KOL/事件：读 `tools/dynamic/config.yaml`、`docs/AUTOMATION_SETUP.md` 和实际 fetcher；未授权不运行。
- 情绪/招聘/供应链：读 `tools/sentiment/**`、相关 run log 和专题文档；保持 sentiment/research DB 边界。
- Viewer：读实际 route、template、CSS 和 JS；不要从旧路由文档猜。涉及 Windows 内网部署时先运行 `python tools/viewer/preflight.py --root <部署目录>`，启动成功必须以 `/api/health` 返回 `ok=true` 和目标地址监听共同确认，不能只看端口存在。

## 9. 验收和交付

- 代码改动：compile + 相关 unit/integration tests。
- 工作流改动：契约审计除版本和活动文件外，必须检查 A/B、C 生产入口真实调用 `ResearchBrief`、execution manifest、五项 gate、review plan 和内容缓存；只测试独立类不算接线完成。
- DB 改动：先临时库迁移和 `foreign_key_check`，再经授权作用于 live 库。
- 页面改动：Flask test client + GET no-write；高风险/正式 UI 用 Playwright 检查桌面与移动。
- 文档改动：引用存在、来源索引位置、重复段落、机器字段、编码和页面渲染。
- 完成说明必须列实际执行的测试及未执行项，不把历史测试当本轮结果。

架构、契约或路径发生变化时同步：`AGENTS.md`、`docs/research/RESEARCH_WORKFLOW_V2.md`、相关代码接口和 `codex_context/`。不要把一次 run 的详细历史重新追加进活动入口；run 事实由 DB 和 `LIVE_STATE.md` 提供。

较大版本更新完成全部验收后，必须用 `tools/maintenance/refresh_project_backup.py` 自动替换 `backup/latest`。该工具会完整归档项目当前版本，以 SQLite backup API 冻结四套 live 数据库，排除 secrets、WAL/SHM 和可再生成临时文件，并在 ZIP CRC、成员清单、内嵌清单及安装后 SHA256 全部通过后才切换 latest；不得手工复制 live DB 或在 `D:\quant` 根目录累积版本备份。
