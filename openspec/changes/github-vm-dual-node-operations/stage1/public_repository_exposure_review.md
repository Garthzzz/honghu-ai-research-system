# 阶段 1 公开仓库暴露面复核

复核时间：2026-08-04（北京时间）

适用范围：`Garthzzz/honghu-ai-research-system` 当前 tracked 历史

状态：仓库临时公开仅用于本轮人工与外部 reviewer 检查；本文件不把公开状态批准为长期状态。

## 结论

确定性 Git gate 与完整历史路径扫描没有发现数据库及其旁路文件、backup、broadcast、papers、用户内容、浏览器状态、Cookie、token、私钥或密码进入 tracked 历史。当前公开仓库仍暴露了一些在 private 开发仓库中合理、但不适合长期公开的内部实现信息，因此本轮人工复核结束后应尽快恢复为 private。

## 公开暴露但未被 secret scanner 阻断的信息

| 风险 | 已发现的信息类型 | 判断与处置 |
|---|---|---|
| 较高 | 固定内网代理端点及其调用结构，分布在财务供应商适配器和能力审计文档 | 不是 credential，但会暴露内部网络接口形态；不在本阶段擅自删除正式代码，仓库应恢复 private。未来如需长期公开，必须另立变更将端点参数化并重新审计历史。 |
| 中等 | 本地与 VM 的 Windows 绝对路径、目录结构和恢复位置 | 其中相当一部分是正式 SOP、测试 fixture 或迁移事实，不能机械删改；公开状态会泄露内部部署习惯。 |
| 中等 | 任务时间窗、供应商类型、抓取与研究工作流、部署和恢复流程 | 不含凭据，但组合后可以推断内部运营方式；只适合受控 private 仓库。 |
| 较低 | `localhost`、测试端口和静态 vendor 代码中的模式命中 | 属于本地开发/测试信息；minified vendor 中的个别模式是误报，不构成内部端点。 |

## 确定性核验

- tracked gate：通过；禁止资产为 0。
- Git 全历史对象名检查：没有发现 DB、WAL、SHM、backup、broadcast、papers、Cookie 或 storage-state 路径。
- 高置信 secret/path/credential gate：通过；报告不输出任何 secret 值。
- GitHub 原生 secret scanning/push protection 当前未启用；本阶段的自有 gate 可以降低误提交风险，但不应被解释成等价替代。
- `config/pending_review_index.json` 只保存安全标识和分类，不公开 66 个未跟踪文件的原始路径或内容。

## 人工复核后的动作

1. 用户人工检查本轮 commit、Actions、main 保护和证据包。
2. 复核结束后把应用仓库恢复为 private。
3. private 恢复前不得新增内部端点、凭据、数据库、papers、用户内容或生产基础设施细节。
4. 是否启用 GitHub 原生 secret scanning/push protection、是否进一步参数化内网端点，作为仓库治理选择另行决定；本阶段不扩大权限或改写生产配置。
