# 行研工具系统 — 通用化复用清单(REUSABILITY_CHECKLIST)

> 第三次修订任务 9 产出。下次启动新行业(锂电 / AI 算力 / 储能 / ...)时,对照本清单逐项检查。
> **?? 通用规则**:任何行业自动生效,无需改动
> **?? 行业特化**:启动新行业时需要调整或重新填充

---

## 1. db schema(全部通用)

| 表 / view | 用途 | 通用 / 特化 |
|---|---|---|
| `industry` | 行业一等公民 | ?? 通用,新行业 INSERT 一行即可 |
| `industry_relation` | 上下游关系 | ?? 通用,新行业按产业链结构填 |
| `industry_data_point` | 行业层数据点 | ?? 通用,所有字段(含 consensus_status / sentiment / as_of_date) |
| `data_point_peer_group` | 多源对照中间表 | ?? 通用,consensus_compute 自动维护 |
| `company` | 公司极简 tag | ?? 通用 |
| `company_industry` | 公司 × 行业 tag | ?? 通用 |
| `theme` | 主题 | ?? 通用,新行业新主题 INSERT |
| `theme_industry` / `theme_company` | 主题关联 | ?? 通用 |
| `source` | 信息来源 | ?? 通用(含 value_layer / source_url / key_arguments) |
| `source_entity` | source × 实体 | ?? 通用 |
| `source_snapshot` | 增量快照 | ?? 通用 |
| `md_section_version` | md 章节版本 | ?? 通用 |
| `thesis` / `thesis_kpi` | 投资观点 | ?? 通用 |
| `v_industry_overview` view | 首页 dashboard | ?? 通用 |
| `v_source_extraction_audit` view | 抽取审计 | ?? 通用,阈值表内置 |

---

## 2. 当前研究工作流硬规则（全部通用）

| 硬规则 | 适用 |
|---|---|
| `## 中文输出硬约束`(白名单 / 黑名单) | ?? 通用,所有行业 |
| `## Source 抽取最小产出量硬约束`(value_layer × 阈值表) | ?? 通用,所有行业 |
| `## 引用密度与多源对照硬约束`(md 引用密度 + 共识算法) | ?? 通用 |
| `## 抗 Slop 硬约束` 8 条 | ?? 通用 |
| `## Cache 使用协议` | ?? 通用 |
| `## Skill 针对行研的适配指示` | ?? 通用 |
| 三阶段执行框架 / GOLD 1-4 | ?? 通用 |

---

## 3. 工程脚本与函数(全部通用)

| 脚本 | 用途 | 复用 |
|---|---|---|
| `tools/pipeline/consensus_compute.py` | 多源对照算法 | ?? 通用,接口 `recompute_all/metric/after_insert` |
| `tools/pipeline/db_writer.py` | SCIENTIST 入库统一接口 | ?? 通用,`write_data_point` 自动触发 consensus |
| `tools/pipeline/zero_data_alert.py` | 零数据 source 告警 | ?? 通用,SCIENTIST session 启动必跑 |
| `tools/pipeline/incremental_update.py` | 增量更新机制 | ?? 通用,任意行业 |
| `tools/viewer/app.py` | Flask viewer | ?? 通用,所有路由 |
| `tools/viewer/static/styles.css` | 通用样式 | ?? 通用 |
| viewer 模板 base/dashboard/industry/q_horizontal 等 | ?? 通用 |
| viewer 模板 audit_extraction / metric_detail | ?? 通用 |

---

## 4. Viewer 路由(全部通用)

| 路由 | 用途 |
|---|---|
| `/` 首页 dashboard | ?? 通用 |
| `/industry/<id>` 行业详情 | ?? 通用 |
| `/q/<q>` Q0-Q5 横向页 | ?? 通用 |
| `/chain/<id>` 产业链全景 | ?? 通用 |
| `/source/<id>` source 详情 | ?? 通用 |
| `/company/<id>` 公司 tag | ?? 通用 |
| `/theme/<id>` 主题 | ?? 通用 |
| `/data_points` 数据点全览 | ?? 通用(含 consensus 列) |
| `/sources` source 库 | ?? 通用 |
| `/incremental` 增量批次 | ?? 通用 |
| `/refresh/<id>` 触发增量 | ?? 通用 |
| **`/audit/extraction` 抽取审计** | ?? 通用 |
| **`/metric/<id>/<m>/<as_of>/<fc>` metric 详情** | ?? 通用 |
| `/api/health` / `/api/source/<id>` / `/pdf/<id>` | ?? 通用 |

---

## 5. 模板系统(通用)

| 模板 / 资产 | 通用 / 特化 |
|---|---|
| `templates/industry.md.template`(9 节) | ?? 通用 |
| `templates/liang_q1.md.template`(Q1 等) | ?? 通用,Q0/Q4/Q5 模板可补 |
| `templates/theme.md.template` | ?? 通用 |
| `templates/source-litreview.md.template` | ?? 通用 |
| `tools/vocab.md` 受控词表(通用 metric / sentiment / consensus 等) | 大部分 ?? 通用,光模块特化 metric 段 ?? 需调整 |

---

## 6. Skill 集(通用)

| skill | 通用 / 特化 |
|---|---|
| `通用基础层/*`(verifier-protocol / chinese-output / halt-conditions 等) | ?? 通用 |
| `研究层/*`(行研适配版,5-step pipeline / reference-isolation 等) | ?? 通用 |
| `工程层/*` / `输出层/*` / `设计层/*` | ?? 通用 |
| `行研专用层/industry-md-template` | ?? 通用 |
| `行研专用层/liang-three-questions-md` | ?? 通用(可改名 Q1-Q3-md 去 Liang 字样) |
| `行研专用层/source-quality-tier` | ?? 通用(tier 三档定义) |
| `行研专用层/claim-extraction-from-source` | ?? 通用,4 类 hidden claim 探测 |
| `行研专用层/industry-relation-curation` | ?? 通用 |
| `行研专用层/claude-self-litreview` | ?? 通用(第三次修订强化:每 url=独立 source) |

---

## 7. 启动新行业的标准步骤

1. **建 industry row** + 子行业(若有):`INSERT INTO industry ...`
2. **建 theme** + theme_industry 关联(如"国产替代"在新行业的影响)
3. **papers/<新行业>/** 放 PDF 研报
4. **fresh SCIENTIST session** 启动,先跑 `python tools/pipeline/zero_data_alert.py`(自动列零数据 source)
5. **按 P0→P3 顺序**精读 source,数据点走 `db_writer.write_data_point()`(自动 consensus 重算)
6. **抽取过程跑 `v_source_extraction_audit`** 自检每份 source 达标
7. **写 6 份 Q-md**（Q0-Q5）+ 主文档，并按当前发布门槛检查引用密度
8. **跑全自检 query**(per spec ## 10a)
9. **viewer 烟测**(`/audit/extraction` 看抽取达标;`/metric/<id>/<m>/<as>` 看共识)
10. **commit artifact**(`PHASE2_<行业>_COMPLETION.md`)

---

## 8. 需要新行业特化的内容(??)

| 项 | 工作量 | 备注 |
|---|---|---|
| 新 industry / 子行业 / theme 行 | 1-5 行 SQL | 5 分钟 |
| `tools/vocab.md` 加该行业特化 metric | 10-30 个 metric | 30 分钟(可在阶段 3 提炼为通用) |
| 6 份 Q-md(Q0-Q5) | 全新内容 | 4-6 个 SCIENTIST session |
| `templates/<行业>.md.template` 优化(可选) | 0-1 个 | 可选 |
| skill 适配指示(若该行业有特殊 quirk) | 0-2 段 | 可选 |

---

## 9. 复用 audit(本工具系统当前状态)

| 检查项 | 当前(光模块)| 新行业期望 |
|---|---|---|
| 通用 schema 覆盖 | 100% | 100% |
| 通用 viewer 路由覆盖 | 100% | 100% |
| 通用 skill 覆盖 | 100% | 100% |
| 通用 vocab.md | 80% 通用 + 20% 光模块特化 metric | 阶段 3 把光模块特化 metric 沉淀到「板块-子类」二级结构 |
| md 模板 | 通用 | 通用 |
| Hard rules / GOLD | 通用 | 通用 |

---

## 10. 第三次修订带来的复用红利

| 新规则 / 工具 | 新行业自动受益 |
|---|---|
| 抽取最小产出量硬约束 | ?? 新行业第一天就有阈值,杜绝"占字段"式入库 |
| 多源对照算法(consensus_compute) | ?? 新行业第一条数据点入库就自动算 peer_group |
| db_writer hook | ?? 新行业 SCIENTIST 不需要操心 INSERT,统一接口 |
| /audit/extraction 红绿可见 | ?? 新行业随时打开都能看缺口 |
| zero_data_alert.py | ?? 新行业 SCIENTIST session 启动必跑,自动列优先级 |
| /metric/<id>/<m>/<as>/<fc> | ?? 新行业任何 metric 都能看共识 / 离群 |

?? **这是真正的"做一次,所有行业受益"** — 通用化已固化在工具层,不靠手工迁移。

---

## 11. 第四次修订带来的复用红利(GOLD: extraction_method 透明化 + 防批量复制)

| 新规则 / 工具 | 通用性 | 新行业自动受益 |
|---|---|---|
| `industry_data_point.extraction_method` 字段 + 5 枚举 CHECK | ?? 通用 | 新行业第一天每条 dp 都强制标抽取方法 |
| `db_writer.write_data_point(..., extraction_method=...)` 必填 | ?? 通用 | 工具层就 enforce,不靠 SCIENTIST 记忆 |
| `tools/pipeline/duplicate_detection.py --industry <id>` | ?? 通用 | 任意行业可调,SCIENTIST session 结束必跑 |
| `tools/pipeline/scientist_session_audit.py --industry <id>` | ?? 通用 | 检查 em 分布 / dup / 不达标 / 不诚实标注 / 自动 fail |
| viewer `/data_points?em=pdf_direct` 等 filter | ?? 通用 | demo 时可主路径限定 "原文" 数据 |
| viewer industry 详情页 `data-quality-banner` | ?? 通用 | template_estimate > 30% 自动出 warning,tier=3 出红框 |
| viewer `/audit/extraction` 加 extraction_method 分布 | ?? 通用 | 一眼看全库各方法占比 + 按 industry 分布 |
| `extraction_method` 透明化要求 | 通用 | 当前 producer/reviewer workflow |
| skill `claim-extraction-from-source` / `claude-self-litreview` 升级 | ?? 通用 | skill 层 enforce 防批量复制 |

?? **真正的工程化抗 slop 防线**:不靠人记规则,db 层 CHECK + db_writer 必填 + audit 自动 fail。

---

## 12. viewer 交互改进(第五次:Q6 可编辑 + 筛选 + 链接 + hero)

| 改进 | 通用性 | 说明 |
|---|---|---|
| 数据点表多维筛选 pill(改动1)| ?? 通用 | 任意行业详情页;consensus/性质/倾向/抽取方法 4 维 toggle,AND 叠加,纯前端 JS |
| Q-md 链接渲染层修复(改动2)| ?? 通用 | `render_markdown` 把 `xxx_Qn_xxx.md` 重写为 `#tab-Qn`,所有行业 md 自动生效,md 文件保持干净相对链接 |
| Q5 核心判断 5 条结论 + hero 抽取(改动5)| ?? 通用 | `parse_q5_hero` 解析「核心判断」节的 `**结论X:...**` 标题;首页 hero 自动展示;去掉"暂未生成"placeholder |
| **Q6 用户可编辑补充栏(改动4)** | ?? 通用 | `<行业名>_Q6_补充.md` + `POST /industry/<id>/q6/save`(参数化 industry_id);查看/编辑模式;保存前 backup 到 `cache/q6_backup_<行业>_<ts>.md`;长期保存;渲染走现有管线(转义防 XSS)|
| Q5 CPO/LPO 替代逻辑(改动3)| 光模块特化内容 | 行业研究内容,非通用机制 |

?? Q6 机制对所有行业生效:存储 / 大模型只要建 `<行业名>_Q6_补充.md` 即自动有可编辑补充栏。


## 13. 三行业扩展验证(G4+G5+G6,2026-05-29)

光模块(首个 PoC,tier=1)的工具骨架 + 模板 + skill + viewer 已成功复用到第 2、3 个行业:

| 复用项 | 通用性 | 三行业验证结果 |
|---|---|---|
| 行业 md 9 节模板 + Q0-Q5 独立 md | ?? 通用 | 存储 7 份 / 大模型 7 份完整产出,frontmatter + research_dimension + 引用密度对齐光模块 |
| db 三层架构(industry/data_point/source)| ?? 通用 | 三行业共 1993 dp,同一 schema 零改动承载 |
| consensus_compute 多源对照 | ?? 通用 | 三行业 recompute 正常;存储如实 0 共识、大模型 28 统计共识,算法对不同数据密度自适应 |
| duplicate_detection 批量复制检测 | ?? 通用 | 三行业 0 批量复制,9 个真多源组全识别 |
| viewer 全部路由 + Q-tab 重写 + pill | ?? 通用 | /industry/7 /industry/8 全 200 渲染,改动1-5 自动生效 |
| tier 分级(status='深度跟踪'过滤)| ?? 通用 | 大模型 tier=3/基础跟踪 自动不进 /q 三问横向页,一手 vs 二手物理区分 |
| db dump → md 写作工作流 | ?? 通用 | cache/_g4_<行业>_dp.txt 按 metric 聚合,consensus 措辞回查 db,杜绝编造 |

?? **关键复用结论**:从光模块到存储/大模型,**db schema 0 改动、viewer 0 改动、模板 0 改动**,仅新增行业数据 + md。证明工具系统已通用化,新增行业的边际成本主要在"读 source + 写 md",系统骨架可直接复用。

?? **tier 分级的工程价值**:大模型作为 tier=3 二手研报整理,通过 status 过滤自动排除于 Liang 三问高级对比页,且 md 全程醒目标注"非一手投研",实现了"AI/二手数据不享受一手投研待遇"的抗 slop 原则在多行业的一致落地。
