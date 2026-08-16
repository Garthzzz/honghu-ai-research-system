# Repository production governance evidence

> 最近只读核验：2026-08-16。本文件不包含凭据、deploy secret 或 GitHub 私有设置值；仓库可见性继续遵守用户当前要求。

## 已由 GitHub API 核实

- 仓库 owner 为个人账号 `Garthzzz`，owner type 为 `User`，默认分支为 `main`，当前按用户要求保持 public。
- `main` required checks 为 `boundary-and-contracts` 与 `python-clean-environment`，strict update 已启用。
- 管理员同样受保护规则约束，conversation resolution 已启用。
- GitHub 当前 `required_approving_review_count=0`；“人工批准 exact SHA”是现行运营合同，尚未由 GitHub 强制至少一名 reviewer。
- force push 与 branch deletion 已禁止。
- 当前只核实到一位直接管理员 `Garthzzz`；deploy key 数量为 0。
- 在治理门禁完全关闭前，生产发布模式保持：`CI green → 人工批准 exact SHA → VM immutable deploy`。不得启用 main merge 后无人审核自动上线。

## 仍需人工关闭

1. 公司资产归属，或批准个人账号暂时作为代码托管方的正式例外。
2. 第二位公司管理员及可执行的离职、失联和账号恢复交接。
3. owner 与第二管理员的 2FA、账号恢复和公司留存证据。
4. 是否把至少一名 approving reviewer 写入 GitHub protection/ruleset，而不只依赖流程约定。
5. 公司控制、最小权限、可轮换和可撤销的 VM deploy credential；当前不得把个人 GCM/SSH 凭据认定为长期 production authority。

这些事项不阻止已经人工批准 exact SHA 的现有发布模式，也不推翻九个数据单元已经形成的 PostgreSQL authority；但在启用无人审核自动部署或把仓库认定为完整 production authority 前必须关闭。
