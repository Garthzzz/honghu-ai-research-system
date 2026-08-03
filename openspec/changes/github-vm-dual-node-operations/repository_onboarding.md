# GitHub 仓库接入记录

首次记录时间：2026-08-03 17:02:07 +08:00  
写权限复核时间：2026-08-03 17:10:55 +08:00  
记录范围：确认仓库身份、本地认证、只读访问与临时 tag 写入/删除；不初始化项目根目录 Git，不建立项目 remote，不推送任何项目文件。

## 仓库映射

| 用途 | 逻辑名称 | 实际 HTTPS 地址 | 所有者 | 当前状态 |
| --- | --- | --- | --- | --- |
| 应用版本、配置、测试和部署工具 | `honghu-ai-research-system` | `https://github.com/Garthzzz/honghu-ai-research-system` | `Garthzzz` | 已创建；认证读写成功；临时 tag 已删除；当前该测试 ref 不存在 |
| 预留但不使用 | `honghu-ai-research-content` | `https://github.com/Garthzzz/-honghu-ai-research-content` | `Garthzzz` | **`RESERVED-UNUSED`**；保持空置、无生产凭据、不承载 live 内容/备份/发布权威；实际 slug 以 `-` 开头 |

## 验证证据

- 本机 Git：`git version 2.53.0.windows.2`。
- Git Credential Manager：`2.7.3`，Git for Windows 系统级 `credential.helper=manager` 已启用。
- 对两个实际 HTTPS 地址分别执行只读 `git ls-remote`，均返回退出码 `0`，没有返回 refs；这证明当前凭据可访问两个空仓库。
- 在独立临时仓库生成不含文件的空 commit `a3509a48684b7e303ee8b10a0c147c8b6c86b076`，仅推送临时 tag `codex-auth-smoke-20260803T1705`，没有推送项目源代码、数据库、cache、papers、凭据或其他项目内容。
- 两个仓库均明确返回 `[new tag]`，证明当前凭据具有 Git 写权限；随后均明确返回 `[deleted]`。按同一 tag 名称再次执行 `ls-remote --tags` 均返回退出码 `0` 且结果为空，证明远端测试 ref 已删除。
- 内容仓库第一次删除请求遇到 GitHub HTTP `503`；重试后删除成功并通过空结果复核。这是瞬时网络/服务响应，不是最终残留。
- 本地临时仓库已删除。项目根目录在验证前后均未初始化为 Git 仓库；没有生成项目 `.git`、没有配置项目 remote、没有创建项目 commit。
- 凭据通过 Git Credential Manager/浏览器流程处理；没有在聊天、命令参数、项目文件或日志中记录密码或 token。

## 尚未完成

- tag 级 Git 写权限已经验证，不应仅为重复认证再次登录或重跑同一测试。首次 bootstrap 的后续工作以 `tasks.md` 的“阶段 1：安全 Git bootstrap 与 CI”及其明确任务标题为准，不再引用已经失效的数字任务编号。
- 尚未核验 GitHub 网页设置中的 private 可见性、2FA、ruleset、secret scanning/push protection；应在阶段 1 的仓库治理与 production gate 中核验。
- 尚未为 VM 配置应用仓库只读 deploy key。新版设计不再默认给内容仓库配置实时写权限；只有用户和合规重新批准其明确用途后才评估。
- 第二个仓库本轮不删除、不重命名、不 archive；它的当前状态已明确，不再作为 production 设计的 open question。

## 生产代码仓库治理门槛

应用仓库当前归个人账号 `Garthzzz` 所有。这一事实不阻止经人工批准后的安全 bootstrap 和开发用途，但在以下条件关闭前，它不具备 production authority：

- 公司代码资产归属已明确；优先评估转入公司 GitHub Organization，暂不能转移时必须有书面批准的例外；
- 至少有第二位公司管理员或可执行的交接/恢复机制；
- 管理员强制 2FA，账号恢复和离职交接可验证；
- protected branch/ruleset、required checks 和最小权限生效；
- VM deploy credential 由公司控制，不依赖个人工作站凭据；
- 生产发布和紧急恢复不以单一个人账号持续可用为前提。

该门槛属于 production deployment gate，不是安全建立初始 Git 历史的前置条件。

## 新版架构下的定位

- 应用仓库仍是后续 Git bootstrap 的目标，但本轮没有重新连接或修改远端。
- 内容仓库不再用于 comment/thesis/hypothesis/Q6 的逐编辑 outbox、事件复制或空库回放。中央 PostgreSQL 的 revision、soft delete、audit 和数据库备份是长期方案。
- 内容仓库固定标记为 `RESERVED-UNUSED`，不配置生产 deploy credential。若未来需要客户端加密的低频灾备，应重新评估职责明确的独立 backup repository，并先通过资料与用户内容上云合规审批；不得默认复用当前异常命名仓库。
