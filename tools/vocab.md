# 行研版受控词表 (vocab.md)

本词表是行研工具系统的 schema 字段取值约束集合。多个 skill / 数据入库前必须按本表 enforce。

**并行扩充机制**:阶段 2/3 处理 source 发现需要新词 → 写到 `vocab_queue.jsonl`(每行一个 JSON 候选) → 阶段结束后人工 review → 合入本文件 → 清空 queue。

---

## 1. source.source_type

```yaml
- 卖方深度       # 头部券商行业首席 50+ 页深度报告
- 卖方周报       # 周度/月度跟踪报告
- 公告           # 公司公告(年报/季报/临时公告)
- 业绩说明会     # 业绩说明会纪要(原始)
- 招股书         # 招股书/募集说明书/重大重组报告
- 协会数据       # 行业协会季度/年度数据
- 三方数据       # Wind内网HTTP/Tushare/yfinance/朝阳永续/iFinD/Bloomberg；A股Wind主、Tushare补缺
- 财经媒体       # 财新/第一财经/华尔街见闻
- 自媒体         # 雪球/微信公众号/知识星球
- claude_lit_review  # Claude 自主 web lit review 综合
- website_material   # 实习生准备的网站材料
- 其他           # 暂未分类,需后续 review 归入
```

db 表 `source.source_type` 的 CHECK 约束已与本词表同步。

### 1a. source.value_layer(研报价值分层 — 决定抽取强度)

```yaml
- 深度框架     # 行业概念 / 上下游结构 / 商业逻辑 / 分析框架 / 历史规律(慢变量,变化频率低)
- 最新数据     # 季度业绩 / 月度指标 / 价格 / 出货量 / CapEx 等高频数据(快变量)
- 双层         # 同时含深度和最新(头部券商行业首席半年/年度深度)
- 公司专项     # 单家公司深度,服务 company 维度,补壁垒细节
- 主题专项     # 单一技术路线 / 政策主题(CPO 专题 / 出海专题)
- 信息流       # 周报/点评/媒体/自媒体(默认 tier=3 + 默认不深读)
```

> SCIENTIST 入库新 source 时必填。抽取协议按 value_layer 分层(深度框架/双层走完整 5-step,最新数据/主题专项简化抽取,公司专项挂 company 维度,信息流仅扫标题摘要)。

## 2. industry.tier 与 industry.status

```yaml
tier:
  - 1   # 深度跟踪
  - 2   # 基础跟踪
  - 3   # 仅记录
status:
  - 深度跟踪
  - 基础跟踪
  - 仅记录
```

> tier 与 status 通常对齐,但允许暂时不一致(例:某 tier=1 行业临时降为「基础跟踪」)

## 3. industry_relation.relation_type

```yaml
- 供应   # 上游产品物理流向下游(光芯片 → 光模块)
- 配套   # 无物理流但下游需要(检测设备 → 光模块产线)
- 替代   # 上游可替代下游某环节(硅光 → 传统光器件)
- 互补   # 同时使用增强彼此价值(光模块 + 交换机)
- 衍生   # 行业演化派生(CPO 是光模块的衍生方向)
```

## 4. industry_relation.bargaining_power

```yaml
- upstream_strong       # db 值。前端显示:上游议价强势
- balanced              # db 值。前端显示:相对均衡
- downstream_strong     # db 值。前端显示:下游议价强势
```

> db 字段值保留英文 ID(向后兼容),前端 viewer 经 `LABEL_MAP` + `t()` 翻译为中文显示。

## 4b. industry_data_point.sentiment(数据点的多空倾向)

```yaml
- 看涨     # 此数据支持看多观点
- 看跌     # 此数据支持看空观点
- 中性     # 此数据无明确方向(纯描述)
- 不适用   # 不是观点性数据(如行业定义类数据点)
```

> SCIENTIST 抽 claim 入库时必填。前端表格用色点区分(绿/红/灰/—)。

### 4c. industry_data_point.as_of_date(数据指向时点 — 与 publish_date 区分)

```
格式:自由文本,但建议:
  - "YYYY-MM-DD"        日级精确
  - "YYYY-MM"           月度
  - "YYYYQ1/Q2/Q3/Q4"   季度
  - "YYYY"              年度
  - "YYYY-YYYYE"        多年预测
```

> 与 source.publish_date 严格区分。例:2026-04 发布的研报引用 2025Q4 数据,publish_date=2026-04-xx,as_of_date=2025Q4。

## 5. industry_data_point.metric(行业层关键数据 key)

**通用 metric**(所有行业适用):

```yaml
- CR5                    # 头部 5 家份额合计(%)
- CR10                   # 头部 10 家份额合计(%)
- TAM_USD                # 总可触达市场(亿美元)
- TAM_CNY                # 总可触达市场(亿元人民币)
- TAM_unit               # 总可触达市场(实物单位,如万只/万吨)
- CAGR_5Y                # 5 年复合年增长率(%)
- CAGR_3Y                # 3 年复合年增长率(%)
- 国产化率               # 国产化率(%)
- 库存周期               # 库存周转天数(天)
- 产能利用率             # 产能利用率(%)
- 资本开支同比           # 行业资本开支同比(%)
- 渗透率                 # 某场景的渗透率(%)
```

**光模块特化 metric**(本 PoC 行业,阶段 3 提炼时考虑通用化):

```yaml
- 800G_出货量            # 800G 光模块出货量(万只)
- 1.6T_出货量            # 1.6T 光模块出货量(万只)
- 800G_ASP               # 800G 单价(美元/只)
- 1.6T_ASP               # 1.6T 单价(美元/只)
- EML_自给率             # EML 国产自给率(%)
- 单 GPU 配比            # 每 GPU 配光模块数(只)
- 北美云厂 CapEx_YoY     # 北美 4 家云厂 CapEx 同比(%)
```

> 阶段 3 review:把光模块特化 metric 提炼为「板块-子类」二级结构,便于扩展到第二个行业。

**大模型特化 metric**(industry_id=8,G3 并行真读 canonical — 并行 agent 必须引用,严禁自创变体名):

```yaml
# === 市场规模 ===
- TAM_USD                  # 大模型/细分市场 TAM(亿美元),note 标细分(大模型/Agent/AI应用/AI编程/AI Infra/一体机)
- TAM_CNY                  # (亿元),note 标细分
- 全行业CAGR(%)
- 推理市场规模(亿美元)
- 训练市场规模(亿美元)
- token调用量(万亿/日)      # 全行业或公司,company_id/note 标口径

# === 模型能力/规模(技术)===
- 参数量(B)                 # 十亿参数,note 标模型名
- 训练算力(FLOPs)           # note 标模型名
- 上下文长度(K)             # note 标模型名
- MoE激活参数比(%)          # note 标模型名
- benchmark得分             # note 标 benchmark 名(MMLU/GPQA/SWE-bench 等)+ 模型名

# === 成本/价格 ===
- API输入价格(USD/Mtok)     # note 标模型名
- API输出价格(USD/Mtok)     # note 标模型名
- 推理成本_每Mtok(USD)
- 训练成本(万美元)          # note 标模型名
- API价格年降幅(%)

# === 商业 ===
- ARR(亿美元)               # company_id 标公司
- 估值(亿美元)              # company_id
- 融资额(亿美元)            # company_id
- MAU(百万)                 # company_id
- DAU(百万)                 # company_id
- 付费用户数(万)            # company_id
- 营收_YoY(%)               # company_id
- 毛利率(%)                 # company_id

# === 格局 ===
- CR4(%)                    # 头部 4 家集中度
- 市占率(%)                 # company_id,note 标口径(美国/中国/全球,C端/B端)
- 开源占比(%)
- 模型调用量(亿次/日)        # company_id
- 模型数量                  # note 标范围(国产/全球)

# === 中美对比 ===
- 中美能力差距(月)
- 算力自给率(%)

# === 渗透/应用 ===
- 渗透率(%)                 # note 标场景(企业/C端/某垂直行业)
- 企业采用率(%)             # note 标行业
```

> **并行规则**:metric=纯概念(不含模型名/公司名/时间);公司→company_id;模型名/benchmark名/口径→note。本列表没有的新概念 → 写 `cache/G3_vocab_queue.jsonl` 候选(用最接近 canonical + note),**agent 不许自创新名直接入库**。

## 6. source_entity.entity_type / coverage

```yaml
entity_type:
  - industry
  - company
  - theme
coverage:
  - 主要覆盖   # source 主标的就是此实体
  - 部分覆盖   # source 一节或多节涉及
  - 提及       # 仅顺带提到
```

## 7. company_industry.role(公司在行业内的角色)

```yaml
- 头部玩家     # CR5 以内
- 二线         # CR10 内非头部
- 跟随者       # CR10 外但已商业化
- 潜在进入者   # 尚未商业化但有动作
- 上游供应     # 不是本行业玩家,但作为关键上游
- 下游客户     # 不是本行业玩家,但作为关键下游
- 已退出       # 历史曾参与已退出
```

## 8. theme.category

```yaml
- 政策   # 政策驱动主题(国产替代、出海管制等)
- 技术   # 技术驱动主题(AI 算力、硅光等)
- 需求   # 需求侧主题
- 供给   # 供给侧主题
- 宏观   # 宏观/利率/汇率/财政相关
```

## 9. theme_industry.impact / theme_company.impact

```yaml
- 主要受益
- 次要受益
- 中性
- 受损
```

## 10. thesis.direction / .confidence / .status

```yaml
direction:     # db 值 / 前端显示
  - bullish    # 看多
  - bearish    # 看空
  - neutral    # 中性
  - paired     # 配对(多 A 空 B)
confidence:    # db 值 / 前端显示
  - high       # 高
  - medium     # 中
  - low        # 低
status:        # db 值 / 前端显示
  - active     # 跟踪中
  - verified   # 已验证
  - falsified  # 已证伪
  - paused     # 暂停
```

> 前端 viewer 全部经 `t()` 翻译为中文显示。

## 11. thesis_kpi.expected_direction

```yaml
- up        # db 值。前端:上行(监控指标应当上行)
- down      # db 值。前端:下行(监控指标应当下行)
- range     # db 值。前端:区间(监控指标应当在某区间)
```

## 12. 抗 slop 标识词(出现在 md 或 claim note 中)

```yaml
- "孤证"              # 仅一个 source 支撑的 claim,前端提示
- "口径差异"          # 不同 source 因统计口径不同导致的数字差异
- "前瞻预测"          # 标注前瞻 claim(应用层 -1 tier)
- "AI 综合"           # Claude 综合产出(等价 ai_synthesized=true)
```

## 13. evidence_strength(claim 在 md 中引用时附加标签)

```yaml
- strong    # db 值。前端:高(一手数据 + 多源交叉)
- medium    # db 值。前端:中(单一头部卖方深度 或 一手数据但孤证)
- weak      # db 值。前端:低(卖方周报 / 媒体 / 自媒体)
```

> 应用层:strong 可作为 thesis 核心支撑;weak 仅可作为信息流。

## 14. 研究维度编号(Q0-Q5,无人名)

```yaml
- Q0  历史发展与代际规律   # 用历史推未来,不是百科
- Q1  竞争格局             # 玩家份额 / CR5 / 国产化率 / 并购出清
- Q2  市场空间             # TAM 拆分 / 渗透率 / 增长驱动
- Q3  公司壁垒             # 五维:客户认证 / 技术路线 / 良率 / 单价档位 / 一体化
- Q4  行业特征与商业模式   # 收入成本结构 / 周期属性 / 适用估值框架
- Q5  综述                 # ?? 给老板看的最终产出:大量引用 Q0-Q4 + 一句话核心判断 + 三大支撑/风险
```

> 旧产物含 `liang_question: Q1` frontmatter,可保留 ID(数据库 backward compat),viewer 显示时统一翻译为 "维度: Q1 竞争格局"。新产物不再使用 `liang_*` 命名。

---

## 词表治理

- **本文件是 single source of truth** — db CHECK / Flask viewer / skill protocol 全部 reference 此处
- 修改本词表 = schema change → 必须在 `PROGRESS_LOG.md` 记 `SCHEMA_CHANGE` 事件 + 理由
- 阶段 2/3 期间发现需新词 → **不直接改本文件**,先 append 到 `vocab_queue.jsonl` → 人工合入
- 删除词:必须确认 db 中无 row 使用该词后才允许


---

## 15-21. Stage 3 动态情报模块(合入自 docs/stage3_design/vocab_proposal_G3.md,2026-06-04)

### §15. voice_post.platform / opinion_leader.platform
```yaml
- xueqiu          # 雪球
- weibo           # 微博
- twitter         # X / Twitter(db 存 twitter,前端显示 X)
- wechat_official # 微信公众号
```

### §16. voice_post.post_type
```yaml
- 观点   # 默认展示(分析师判断)
- 数据   # 含数据/图表
- 转发   # 前端折叠
- 提问
- 闲聊   # 默认前端隐藏(?chat=1 显示)
```

### §17.（已取消)news_item 来源层级直接经 FK source 继承 source.quality_tier + source_credibility,不单列。

### §18. event.event_type
```yaml
- 财报 / 大会 / 产品发布 / 监管 / 并购 / 融资 / 论文 / 业内传言
```

### §19. event.importance / news_item.importance
```yaml
- 1   # L1 核心
- 2   # L2 重要
- 3   # L3 关注
```
> db 存整数,viewer 显示 "L1 核心" 等。

### §20. tag.industry / §21. tag.company
> 不新建词表,直接沿用现有 industry / company 表 id 池;AI tagger 只能取 db 现有 id,未知 → cache/G3_vocab_queue.jsonl,严禁凭空加。
