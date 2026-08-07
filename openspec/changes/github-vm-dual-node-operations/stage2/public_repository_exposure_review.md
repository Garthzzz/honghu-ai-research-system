# 阶段 2 公开仓库暴露面复核

> 仓库在迁移、实施和人工审核期间继续保持 public，这是用户的明确指令；本复核不把 public 等同于 production authority，也不擅自删除正常业务代码。

## 1. 禁止资产检查

阶段 2 tracked/staged gate 未发现下列资产进入提交：

- secret、token、Cookie、Credential Manager 内容或浏览器 storage state；
- `research.db`、`sentiment.db`、`opportunity_lens.db`、`financial.db` 及 WAL/SHM/journal；
- PostgreSQL dump、backup、broadcast package、runtime log 或 PID；
- papers/evidence、用户 comment/thesis/hypothesis 或其他 live 用户内容；
- 未批准的大文件和个人工作记忆。

release manifest 另行声明并验证 `contains_live_data=false`、`contains_papers_or_evidence=false`、`contains_secrets=false`。这类声明不能代替文件级 gate；两者均执行。

## 2. 非传统敏感信息

公开代码仍包含正常运行所需、但可向外界暴露系统形态的信息：

- 精确私网 IPv4 共 5 处，位于 Wind 内网代理实现、既有数据源能力文档和本阶段生产未切换证明；
- Windows 绝对路径约 85 处、分布于约 41 个 tracked 文件，主要用于部署 SOP、历史兼容脚本、备份注册表和本机运行入口；未发现具名的个人用户目录；
- Wind、Tushare、DataYes、DeepSeek、星瀚等供应商结构和研究流程在正式代码/文档中可见；
- 计划任务窗口、SQLite 过渡结构、Viewer 路由和发布/恢复方法属于可推断的运维信息。
- 阶段 2 新增的候选部署与停止脚本、进程身份字段、18080 验收步骤和路径闭包合同，会进一步暴露 release 运作方式；脚本不含生产凭据、数据库内容或 papers，但公开审查者可以据此理解候选部署边界。

这些信息不是传统 secret，但公开后可帮助外部人员理解供应商依赖、内网拓扑和运维习惯，综合风险评为“中等”。本阶段没有擅自删除它们，因为 Wind 代理、部署说明和项目治理属于正常业务功能或正式项目规则。

## 3. 控制结论

- public 状态只服务当前迁移和审查，不授予个人仓库 production authority；
- VM deploy credential、生产数据库凭据和供应商密钥均不得进入该仓库；
- 候选部署只允许明确 full SHA、只读数据连接和独立端口；
- 每个后续阶段仍需重新运行 exposure review；
- 若未来 public 审查价值低于暴露风险，应由用户明确决定是否调整可见性，不由 Codex擅自修改。

当前没有发现需要立即从 Git 历史清除的 secret 或禁止资产；保留风险主要来自已知的业务拓扑和运维元数据公开。

## 4. 本轮复核结论

- tracked boundary gate、release manifest 禁止资产声明和 Git diff 继续作为三条独立检查，不用单一 secret scanner 代替；
- VM 人工手册中的私网地址沿用既有正式部署事实，未新增凭据或访问能力；
- evidence v5 新增的是 gate/recovery 状态分区、采样次数和比较理由，不包含 VM 原始 evidence、PID、数据库内容、用户内容或凭据；公开风险仍来自既有部署拓扑和运维合同，没有新增秘密材料；
- 仓库继续 public 是用户明确决定，风险接受不等于仓库获得 production authority；
- PR #3 未合并，VM deploy credential 未配置，内容仓库仍为 `RESERVED-UNUSED`。
