# Skills 权威分层

## A/B/C 活动 skill

下列 `通用基础层/`、`研究层/`、`行研专用层/`、`工程层/`、`设计层/` 路径相对 `skills/`；`审核代理/` 路径相对项目根目录。

- `通用基础层/adaptive-research-workflow/SKILL.md`
- `通用基础层/fresh-session-bootstrap/SKILL.md`
- `通用基础层/verifier-protocol/SKILL.md`
- `通用基础层/continuous-execution/SKILL.md`
- `通用基础层/phase-handoff-protocol/SKILL.md`
- `通用基础层/progress-logging/SKILL.md`
- `工程层/parallel-subagent-orchestration/SKILL.md`
- `工程层/session-reporting/SKILL.md`
- `研究层/conducting-literature-review/SKILL.md`
- `研究层/citation-verification/SKILL.md`
- `研究层/adversarial-review/SKILL.md`
- `研究层/controlled-vocabulary/SKILL.md`
- `研究层/independent-threshold-judgment/SKILL.md`
- `研究层/company-financial-modeling/SKILL.md`
- `研究层/company-valuation-modeling/SKILL.md`
- `研究层/industry-supply-demand-modeling/SKILL.md`
- `研究层/probability-scenario-modeling/SKILL.md`
- `行研专用层/source-quality-tier/SKILL.md`
- `行研专用层/claim-extraction-from-source/SKILL.md`
- `行研专用层/industry-md-template/SKILL.md`
- `工程层/numerical-sanity-gate/SKILL.md`
- `工程层/outcome-based-verification/SKILL.md`
- `工程层/smoke-test-tiers/SKILL.md`
- `工程层/seed-isolation-audit/SKILL.md`
- `工程层/code-quality-standard/SKILL.md`
- `设计层/interface-contract/SKILL.md`
- `设计层/spec-code-reconciliation/SKILL.md`
- `通用基础层/verify-before-claim/SKILL.md`
- `审核代理/verifier-domain-research.md`

这些 skill 必须服从 `config/research_workflow.yaml`。同一要求只在机器契约中定义一次，skill 负责判断方法，不复制整套门槛。四个建模 Skill 由 `tools/research_core/model_routing.py` 按任务强制选择：公司财务与公司估值是硬复算合同，行业供需与概率情景是开放证据合同；没有命中时不加载全文。其余 skill 仍按 artifact 和风险选择：引用/证据用 citation 与 verify；模型、概率、财务和单位用 numerical sanity 与 independent threshold；冲突或关键反方用 adversarial；接口/schema/Viewer 接线用 interface contract 与 spec-code reconciliation；代码交付用 code quality、smoke 和 outcome verification；只有随机性或训练 seed 风险时才用 seed isolation。

## 兼容与历史 skill

其余 Claude Code 时代的 GOLD、academic prototype、固定 phase、固定 persona、固定七段报告和全量 skill 组合保留用于追溯或其他旧项目，不是本项目 A/B/C 默认 prompt。发生冲突时以 `AGENTS.md`、机器契约和上述活动 skill 为准。
