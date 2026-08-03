# 新行业接入 V2 Checklist

机器标准：`config/research_workflow.yaml`  
方法说明：`docs/research/RESEARCH_WORKFLOW_V2.md`

## 1. Intake

- [ ] 判断 A/B 轨，并记录依据。
- [ ] 编译 `ResearchBrief`；B 轨有 prompt requirement matrix。
- [ ] 明确行业边界、时间、地区、产品、公司、必须包含和必须排除。
- [ ] 记录输入文件 hash 和 workflow version。

## 2. Source 与数据

- [ ] 本地 PDF/网页/API 原文可定位，来源身份和日期明确。
- [ ] 公司研报、自媒体、专家纪要未被当成决定性一手事实。
- [ ] 同一底层事实的转载和转述归入同一独立证据组。
- [ ] 数据点有 metric、period/as_of、unit、value、source、excerpt 和 extraction method。
- [ ] 序列按同源同对象同口径形成一个研究事实组；A/B 观测行未被拿来凑数据点。
- [ ] 推算有公式、输入、单位、舍入和复算结果。
- [ ] 新市场/财务数据只来自 Tushare/yfinance。
- [ ] 严格模式没有静默跳过无效数据点。

## 3. 研究覆盖

- [ ] 定义、价值链、历史、竞争、空间、公司、行业经济性、风险和监控均有回答。
- [ ] B 轨 prompt 每一要求都有落点、证据和状态。
- [ ] 竞争格局说明全行业与高端细分口径，CR 配公司名和份额。
- [ ] 市场空间拆量价、应用、地区、情景和测算分歧。
- [ ] 公司壁垒写证据、同业比较、兑现路径和证伪条件。
- [ ] 反方、替代路线、供给扩张、价格回落和财务约束实际改变结论边界。

## 4. 公司与财务

- [ ] 所有上市公司有 ticker、市场状态和近期事件。
- [ ] PE/PB/PS、市值、毛利率、净利率、经营现金流、capex 和至少三年序列已检查。
- [ ] 金额以亿元人民币为主，括号写约 xx.xx 亿美元，保留两位小数。
- [ ] 亏损、退市、私营、子公司和接口不可得分别解释，空表不能通过。
- [ ] 未上市主体没有伪造 PE/PB/市值。

## 5. 文档与页面

- [ ] 主文档、Q0-Q5、必要 Q6、公司透视、估值和产业链均可访问。
- [ ] 正文独立回答页面问题，未用表格和来源清单代替分析。
- [ ] `^src` 紧跟事实，来源索引是最后一个二级章节，引用存在。
- [ ] 没有跨页长段落复制、替换公司名式模板和损坏占位符。
- [ ] 宽表局部滚动，移动端不造成全页横向溢出，图片非空且来源可见。

## 6. Gate 与发布

- [ ] `contract`、`evidence_integrity`、`provenance`、`duplication`、`scope_and_units` 五个 gate 已执行。
- [ ] 有计算时执行独立复算；有公司时执行财务完整性；有公开文档时执行写作/引用；有新页面时执行 Playwright。
- [ ] 所需 reviewer 为 GREEN，findings 已闭环，输入/输出 artifact hash 已记录；final 为 independent/human。
- [ ] execution manifest 记录输入 hash、gate、review 和发布结果。
- [ ] DB、文件、API、浏览器和 GET no-write 回归通过后才交付。
