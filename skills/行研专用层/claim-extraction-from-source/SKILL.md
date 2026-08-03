---
name: claim-extraction-from-source
description: 从原始来源抽取可追溯 claim/data point，保持对象、口径、时期、单位、原文和独立证据组。
---

# Claim Extraction V2

每条结构化事实至少包含：

```text
subject / entity
metric or claim
value_num or value_text
unit
period or as_of_date
actual / forecast / opinion
source identity
source_excerpt
extraction_method
independence_key
```

原文摘录必须直接支持当前 metric。禁止把同一财务句复制到技术能力、客户验证、层数或市场份额等无关指标。

同源同对象同口径时间序列在研究事实层打包为一个数据点，完整 observations 放结构化 payload。C 轨 V2 直接按该结构入库；A/B 兼容关系表即使逐期存行，coverage 和证据计数仍只能算一个平行研究事实。派生值写公式和输入，不能伪装成原文事实。
