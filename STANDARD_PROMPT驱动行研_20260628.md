# B 轨 prompt 驱动行研兼容入口

状态：兼容文件。活动契约见 `docs/research/RESEARCH_WORKFLOW_V2.md`。旧版在 `archive/project_history/retained_originals/workflow_v1_20260712/STANDARD_PROMPT驱动行研_20260628.md`。

## 核心合同

B 轨不是只回答 prompt，也不是把 prompt 填进固定模板。它执行：

```text
用户 prompt 全集
+ A 轨默认 coverage
- 规范化后完全相同项
= ResearchBrief
```

每条用户要求必须保留 origin、落点和验收状态。用户指定的口径、时间、地区、表格、计算和排除项优先；不造数、原文可追溯、来源独立和数据源政策不可被覆盖。

## 研究动作

1. 解析 prompt 的主问题、子问题、必须包含、必须排除、数据要求和输出要求。
2. 与 A 轨默认 coverage 合并；只自动合并完全相同项，语义近似项保留并在 requirement matrix 关联。
3. 把本地资料作为 seed，独立搜索官方、监管、行业组织、竞争对手、客户、供应商和反方。
4. 对公司研报和专家纪要做利益相关与时效降权。
5. 对不可得项记录已查来源、不可得原因、可接受代理和对结论影响。
6. 把适配 viewer 的主文档/Q0-Q6 看作输出映射，不让固定标题限制分析结构。
7. 发布前执行 `config/research_workflow.yaml` 规定的 gate 和 review plan。

统一入库：

```powershell
python tools/pipeline/ingest_research.py --track b --industry-id <id> --tag <tag> --papers-subdir <dir> --canon <aliases.json>
```

旧 `ingest_b_track.py` 只保留 CLI 兼容。
