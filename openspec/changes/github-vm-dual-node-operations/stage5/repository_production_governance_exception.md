# 临时 production repository governance exception

> 生效依据：用户于 2026-08-16 批准 Stage 4 退出并授权 Stage 5。该记录只固化现行受控发布模式，不宣称个人仓库已经完成公司级治理。

## 当前允许

```text
required CI green
→ 用户人工批准 exact commit SHA
→ VM immutable deploy
→ preflight / smoke / evidence
```

- 仓库按用户当前要求保持 public；每阶段继续复核非传统敏感暴露与 secret/data boundary。
- `main` 继续要求 `boundary-and-contracts` 与 `python-clean-environment`，strict update、管理员 enforcement、conversation resolution、禁止 force push 和禁止 branch deletion 保持启用。
- production deploy 必须绑定人工批准的 exact SHA；PR 临时 merge SHA、旧 artifact 或未通过 required CI 的提交不可部署。

## 当前禁止

- `main merge → 无人审核自动 production deploy`；
- 把个人 GitHub/GCM/SSH credential 当作长期公司 deploy authority；
- 因 exception 绕过 required CI、人工 exact-SHA 批准、immutable release、secret/data boundary 或 recovery gate；
- 将 live DB、WAL、backup、credential、papers/evidence 或用户内容提交 public Git。

## Exception 退出条件

以下事项必须由用户/公司治理主体关闭并保留可审计证据：

1. 公司资产归属，或正式批准个人账号继续托管的例外；
2. 第二位公司管理员和可执行的离职、失联、账号恢复交接；
3. owner 与第二管理员的 2FA 和 recovery evidence；
4. 至少一名 approving reviewer 的规则与责任人；
5. 公司控制、最小权限、可轮换、可撤销的 VM deploy credential。

这些事项不阻止本 exception 下已经人工批准 exact SHA 的发布，但在启用无人审核自动部署或宣布 repository production governance 完整关闭前必须完成。最新只读 GitHub 事实见 `../stage4/repository_production_governance_checklist.md`。
