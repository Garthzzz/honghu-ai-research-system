# 阶段 1 CI、测试分层与 Python 环境合同

## 1. 支持的解释器与依赖权威

阶段 1 的可重复开发和 CI 基线为 Python 3.10。`requirements.in` 与 `requirements-dev.in` 记录人工维护的直接依赖，`requirements.lock.txt` 是 Windows/Python 3.10 的带哈希完整依赖锁，也是 clean environment 安装的权威；`requirements.txt` 仅保留为阶段 1 前后的兼容安装入口。

当前活动环境仍可能使用 base、`quant` 或广播脚本声明的 `industry`。这些环境不被视为等价，本阶段不修改任何 live 环境、任务解释器或广播脚本。后续 production 环境只能采用显式、存在且与 lockfile 验证一致的解释器，不得在声明环境缺失时静默换用另一个 Python。

## 2. CI 数据与权限边界

CI 只使用 Git 中的代码、测试 fixture 和临时数据库。它不得连接公司内网、供应商 API、live SQLite、未来 production PostgreSQL 或 VM，不读取 papers/evidence、研究包、用户内容、browser profile、Cookie、credential、backup 或广播包，也不执行部署和写入操作。

两个 required-check 候选名称为：

- `boundary-and-contracts`
- `python-clean-environment`

第一个检查 tracked allowlist、禁止资产、凭据/路径风险、SQLite 技术债增量和 OpenSpec 合同；第二个从 hash-pinned lockfile 安装 Python 3.10 环境，执行 compile、测试收集和 clean-clone core tests。

## 3. 测试分层

`config/ci_test_tiers.json` 是测试分层合同。clean-clone core 只运行使用临时数据库和仓库内 fixture 的测试。依赖研究输出、evidence ledger、Excel、冻结模型或 live 只读快照的模块仍然保留在仓库，但归入 `governed_artifact_integration`，由具备受控输入的本地/人工环境运行。

这不是把失败测试改成成功，也不代表这些模块通过了 CI。禁止为了让 CI 变绿而把被 Git 边界排除的资料上传到应用仓库。测试分层变更必须修改 manifest 并接受代码审查，不能用临时命令静默扩大忽略范围。

## 4. Git 与生产治理边界

当前个人账号下的 private repository 可作为安全 bootstrap 和开发 source of truth，但不是 production authority。阶段 1 不配置 VM deploy credential，不部署 VM，也不更改数据库或计划任务。成为生产权威前仍需完成公司资产控制或获批例外、第二位公司管理员/交接、2FA、账号恢复、branch protection、最小权限和公司控制的部署凭据。

GitHub UI 中的 branch protection/ruleset 需要在 workflow 首次成功运行后，由有权限的管理员将上述两个 check 设为 main 的 required status checks。本阶段报告必须区分“workflow 已配置”“远端运行已通过”和“规则已由管理员启用”。
