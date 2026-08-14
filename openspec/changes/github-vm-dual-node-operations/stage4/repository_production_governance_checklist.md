# Repository production governance evidence

> 只读核验时间：2026-08-14；本文件不包含凭据、deploy secret 或 GitHub 私有设置值。

## 已由 GitHub API 核实

- 仓库当前 owner 为个人账号 `Garthzzz`，owner type 为 `User`，默认分支为 `main`。
- `main` required checks 为 `boundary-and-contracts` 与 `python-clean-environment`，strict update 已启用。
- 管理员同样受保护规则约束；conversation resolution 已启用。
- force push 与 branch deletion 已禁止。
- 当前只核实到一位仓库管理员；未发现 deploy key。
- 在治理门禁完全关闭前，生产发布模式保持：`CI green → 人工批准 exact SHA → VM immutable deploy`。不得启用 main merge 后无人审核自动上线。

## 仍需人工关闭

1. 公司资产归属，或批准个人账号暂时作为代码托管方的正式例外。
2. 第二位公司管理员及可执行的离职/失联交接。
3. owner 与第二管理员的 2FA、账号恢复和公司留存证据。
4. 公司控制、最小权限、可轮换和可撤销的 VM deploy credential；当前不得把个人凭据认定为长期 production authority。

这些事项不阻止已人工批准 exact SHA 的现有发布模式，但在无人审核自动部署或仓库成为完整 production authority 前必须关闭。
