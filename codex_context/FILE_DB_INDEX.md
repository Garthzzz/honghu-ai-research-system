# 文件、数据库与接口索引 V2

当前数量见 `codex_context/LIVE_STATE.md`。旧版逐文件索引在 `archive/project_history/retained_originals/workflow_v1_20260712/codex_context/FILE_DB_INDEX.md`。

## 活动契约

| 路径 | 用途 |
|---|---|
| `AGENTS.md` | 项目入口与红线 |
| `config/research_workflow.yaml` | A/B/C 机器工作流 |
| `docs/research/RESEARCH_WORKFLOW_V2.md` | 流程与审查方法 |
| `docs/research/ACTIVE_FILE_AUTHORITY.md` | 活动/兼容/历史分层 |
| `codex_context/LIVE_STATE.md` | 只读生成的 live 快照 |
| `codex_context/BACKUP_REGISTRY.md` | 项目内唯一 latest 备份、临时安全副本流程与恢复边界 |

## 数据库

| DB | 主要对象 | 标准写入口 |
|---|---|---|
| `data/research.db` | industry/source/data point/company/news/voice/event/hypothesis | A/B pipeline 和 dynamic 模块 |
| `data/sentiment.db` | 三层情绪、散户市场窗口、招聘、K-line、舆情原始 feed、Funda mirror | sentiment 模块；关键词情绪专属表已退役 |
| `codex_context/SENTIMENT_DB_RETENTION_TODO.md` | sentiment 原文即时清理的活动待办、边界、实施顺序与 2026-07-27 诊断快照 | 涉及 sentiment 保留、补漏、聚合或瘦身时必须读取；动态事实需重查 live 库 |
| `data/opportunity_lens.db` | C 轨 run/evidence/entity/score/target/report/review | `tools/opportunity_lens/**` |
| `data/financial.db` | 证券身份、来源快照、actual/market/consensus/guidance/internal/implied、模型输入输出、修订与外部对账 | `tools/financial/**` 和审核后的公司财务 manifest apply |

## A/B

| 路径 | 用途 |
|---|---|
| `tools/pipeline/db_writer.py` | 数据点 canonical writer、原子批量写入 |
| `tools/pipeline/ingest_research.py` | A/B 统一 claims ingest；接入 brief/manifest/gate/review plan/cache，B 轨支持 `--workflow-request` |
| `tools/pipeline/paper_source_manifest.py` | 校验 `papers/<行业>/_source_manifests`，为 A/B claims 补齐下载研报 provenance；经原文摘录、中文译意和 SHA256 门禁向 C 轨 producer 生成 pending source |
| `tools/pipeline/ingest_industry.py` | A 轨兼容 wrapper |
| `tools/pipeline/ingest_b_track.py` | B 轨兼容 wrapper |
| `tools/pipeline/consensus_compute.py` | numeric peer/consensus |
| `tools/pipeline/data_source_policy.py` | Wind/Tushare/yfinance 允许列表；Akshare 禁止 |
| `tools/maintenance/build_financial_field_catalog.py` | 从官方文档、小样本与只读元数据生成公司财务建模字段总目录；不调用Wind |
| `docs/公司财务建模可用字段总目录_20260722.md` | Wind/Tushare/yfinance/内网Ricequant共1,783行原始字段、期限、频率、建模相关性和有用性目录 |
| `WindPy.py` | 固定内网 Wind HTTP 代理客户端；显式绕过本机 VPN 代理 |
| `tools/pipeline/wind_http_provider.py` | Wind 单证券字段白名单、交易日和单位转换提供层 |
| `tools/pipeline/company_data_fetcher.py` | 公司数据获取编排 |
| `tools/pipeline/refresh_company_financial_metrics.py` | 全公司财务 fetch/apply manifest；A 股 Wind 主源、Tushare 逐字段补缺；动态供应商数据只写 `financial.db`，不再更新 `research.company` 兼容摘要或普通数据点 |
| `tools/financial/refresh_valuation_band_history.py` | 小型 Wind PE/PB Band 历史刷新；按少量证券、窄字段、月频受控取数，只写 `financial.db` |
| `tools/pipeline/ensure_listed_company_profile.py` | 经核验后显式建立上市公司主体、别名和 financial security 链接；拒绝同名、市场和股份类别猜测 |
| `tools/migrations/015_company_identity_consolidation.py` | research 重复公司合并、身份修正、旧 ID redirect/alias 与守恒审计 |
| `tools/pipeline/*research*.py` | 已有专题构建器 |
| `docs/industries/` | 行业主文档、Q 页和专题页 |
| `papers/` | 原始研报资料 |
| `papers/<行业>/_source_manifests/` | 萝卜投研等授权下载的标题、底层券商、日期、详情页、页数、SHA256 和独立性键；不是研究结论，也不含登录凭据 |

## 共享工作流

| 路径 | 用途 |
|---|---|
| `tools/research_core/config.py` | 加载/校验 track profile |
| `tools/research_core/brief.py` | ResearchBrief 编译和去重 |
| `tools/research_core/model_routing.py` | 四个建模 Skill 的确定性按需路由与强制产物 |
| `tools/research_core/search_channels.py` | report/web 第一轮隔离与 gap 驱动第二轮任务 |
| `tools/research_sources/datayes_reports.py` | 萝卜投研 Playwright 标题检索、Windows Credential Manager 登录、配额选择、PDF 下载和来源清单；不调用站点 API |
| `tools/research_core/modeling_benchmark.py` | 对照全量加载代理，测量按需 Skill 上下文和 brief 编译开销 |
| `tools/research_core/content_cache.py` | 内容 hash 缓存 |
| `tools/research_core/manifest.py` | execution manifest、gate/review 记录 |
| `tools/research_core/quality.py` | 按 artifact/risk 选择 review plan |
| `tools/research_core/workflow.py` | 初始化 brief、记录 artifact/gate/review 并持久化 manifest |
| `tools/maintenance/audit_workflow_contract.py` | 审计静态契约、A/B/C 入口接线、缓存消费者和 C DB schema |
| `tools/maintenance/benchmark_research_workflow.py` | 复测配置、brief、workflow session 与内容缓存的控制层开销；不外推检索和模型耗时 |
| `cache/research_runs/` | A/B 执行 manifest |

## Opportunity Lens

| 路径 | 用途 |
|---|---|
| `opportunity_lens/intake_requests/` | 正式研究请求 |
| `opportunity_lens/intake_templates/` | 网页端 request 模板 |
| `opportunity_lens/research_outputs/` | 历史/当前研究包与执行底稿 |
| `opportunity_lens/MODULE_CONTEXT.md` | C 轨活动模块、稳定页面族、路由和页面职责 |
| `opportunity_lens/HUMAN_READABILITY_STANDARD.md` | C 轨公开内容与浏览器验收合同 |
| `opportunity_lens/C轨输出模板与前端可视化标准_V1.1.md` | C 轨既有 Viewer 页面族与追踪职责基础协议；公开措辞服从现行 HUMAN 合同 |
| `tools/opportunity_lens/intake_parser.py` | fenced/legacy intake parser |
| `tools/opportunity_lens/run_pack_builder.py` | V2 pack builder |
| `tools/opportunity_lens/run_pack_contract.py` | V2/legacy pack validator |
| `tools/opportunity_lens/manual_run_loader.py` | validate/stage/publish loader |
| `tools/opportunity_lens/workflow_bridge.py` | 把 V2 run pack 编译为共享 ResearchBrief/ExecutionManifest，并与 C 轨 DB 审计语义对齐 |
| `tools/opportunity_lens/publication.py` | 发布门禁 |
| `tools/opportunity_lens/workflow.py` | run 状态机 |
| `tools/opportunity_lens/scoring.py` | 通用评分，排除 theory entity |
| `tools/opportunity_lens/review_workflow.py` | quality gate 和 reviewer log |
| `tools/opportunity_lens/read_models.py` | viewer/API 只读模型 |
| `tools/opportunity_lens/schema.sql` | C 轨 schema |
| `tools/opportunity_lens/migrate.py` | 兼容 migration/verify |

## 财务与估值

| 路径 | 用途 |
|---|---|
| `tools/financial/schema.sql` | 独立财务库 schema、六类事实、模型账本、revision 与 reconciliation |
| `tools/financial/migrate.py` | 从旧公司字段、profile 序列和结构化财务数据点迁移到财务库；旧数据只读保留 |
| `tools/financial/modeling.py` | FY1—FY3 财务桥和外部事件条件冲击 |
| `tools/financial/valuation.py` | PE/同行/EV-EBITDA/PS/DCF/反向估值/PB-ROE/PB-ROA/残余收益与模型簇 |
| `tools/financial/read_models.py` | 公司页只读财务、预测、模型、隐含预期和资产回报配对点 |
| `tools/financial/opportunity_profile_export.py` | 校验并导入 `company_financial_profile_export.v1`；把 Opportunity Lens 已冻结的上市公司预测、估值与市场隐含结果同步到 `financial.db`，不由 C 轨 loader 跨库写入 |
| `skills/研究层/company-financial-modeling/` | 公司财务硬方法 Skill |
| `skills/研究层/company-valuation-modeling/` | 公司估值硬方法 Skill 与 PB 资产回报 reference |
| `skills/研究层/industry-supply-demand-modeling/` | 行业市场与供需开放 Skill |
| `skills/研究层/probability-scenario-modeling/` | 概率与情景开放 Skill |

## Viewer

| 路径 | 用途 |
|---|---|
| `tools/viewer/app.py` | Flask 主应用和 A/B/动态/情绪路由 |
| `tools/viewer/opportunity_lens_blueprint.py` | C 轨页面/API |
| `tools/viewer/templates/` | Jinja 页面 |
| `tools/viewer/static/` | CSS/JS/图表资源 |
| `tools/viewer/preflight.py` | Windows 部署闭包、依赖、四库和 Flask import 只读预检 |
| `restart_viewer.bat` | 相对项目根启动、旧进程关闭、预检、内网监听和 HTTP 健康验证 |
| `docs/VIEWER_内网部署.md` | 六目录部署清单、环境变量、日志和数据库传输说明 |

主要只读页面族：

- `/research`
- `/companies`、`/api/companies/search`、`/company/<id>`
- `/industry/<id>`、`/industry/<id>/companies`、`/industry/<id>/valuation`
- `/q/<Q0-Q5>`
- `/opportunity-lens`、`/opportunity-lens/request-generator`、`/opportunity-lens/run/<id>`、`run/<id>/entities`、entity、target、factor、metric-slot、audit、supplement、export
- `/api/opportunity-lens/**`

主应用同时有写入路由；smoke 不能把所有 GET/POST 混跑。

Windows 完整 Viewer 部署必须同步 `data/`、`docs/`、`tools/`、`papers/`、`opportunity_lens/` 和 `config/`。旧五目录集合缺少工作流 V2 的机器契约，不能启动当前 Opportunity Lens blueprint。

## 动态与情绪

| 路径 | 用途 |
|---|---|
| `tools/dynamic/` | 新闻、KOL、事件、调度 |
| `tools/dynamic/config.yaml` | 动态任务配置 |
| `tools/sentiment/` | 三层情绪、散户市场窗口、招聘、K-line 和供应链情绪；关键词情绪页面/抓取链已退役 |
| `tools/sentiment/migrate_company_identity_consolidation.py` | 把 research canonical 身份同步到 sentiment raw、聚合、K线、别名和 redirect |
| `docs/AUTOMATION_SETUP.md` | 自动化历史与运维说明，执行前对照 live code |

`tools/dynamic/secrets/` 只可确认目录存在，不得读取内容。

## 测试与维护

| 路径 | 用途 |
|---|---|
| `tests/opportunity_lens/` | C 轨 schema/API/scoring/viewer/V2 workflow 测试 |
| `tests/research_workflow/` | shared core 和 A/B writer contract 测试 |
| `tools/maintenance/build_context_snapshot.py` | 只读生成 live state |
| `tools/maintenance/audit_workflow_contract.py` | 只读审计活动文件、版本、写入口和 live C schema 一致性 |
| `tools/maintenance/validate_sqlite_migration.py` | 只读比较迁移前后表、行数、列、完整性和外键 |
| `tools/maintenance/audit_legacy_run_packs.py` | 只读复核历史 C 轨研究包的 stage/publish 兼容边界 |
| `tools/maintenance/audit_viewer_workflow_v2.py` | Playwright 桌面/移动、证据抽屉、宽表和 GET no-write 验收 |
| `tools/maintenance/project_artifacts.py` | 只读全局文件盘点、生命周期分类、引用/重复/体积审计；可选接受显式用户授权的 exact-file 功能退役 spec，不支持 glob/目录，不读取 secrets 内容 |
| `tools/maintenance/apply_project_cleanup.py` | manifest 驱动的 dry-run/apply 清理器，校验根目录、外部备份、SHA256、保护路径和历史目标边界；功能退役还需 batch 二次授权、当前引用复扫与同路径备份 hash 一致 |
| `archive/project_history/README.md` | 历史信息边界、旧路径映射与恢复说明 |
| `archive/project_history/HISTORICAL_DECISIONS.md` | 旧 command、协议、设计和完成报告的耐久决策提要 |
| `archive/project_history/retained_originals/workflow_refactor_20260712/` | V2 重构关键设计、迁移、性能和浏览器验收原件 |
| `archive/project_history/cleanup_manifests/` | 2026-07-13 清理基线、批准动作、逐批结果、最终 inventory 与验收报告 |
