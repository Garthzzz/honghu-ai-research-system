# 阶段 3 public repository 暴露复核

## 结论

本轮拟提交内容没有新增 secret、token、Cookie、浏览器状态、live SQLite/WAL/SHM、PostgreSQL dump、backup、broadcast、papers/evidence、用户内容或原始研究产物。仓库按用户明确要求继续保持 public，但仍不具备 production authority。

## 新增公开内容

- 通用 Viewer 行业分组、估值正文展示与回归测试；
- required-cache 与 cleanup 的通用边界修复；
- SQLite live-only addendum/aggregate manifest 的生成与验证工具，但不包含真实 Git 外研究清单；
- 阶段 3 design、plan、完成报告和本暴露复核；
- backup ZIP64 流式写入修复与测试；
- `phase3/**` 分支的 CI push trigger。

## 保持 Git 外的内容

- run19/run20 研究包、研究正文、source downloader 与一次性 builder；
- 封装基板 B 轨的 papers、文档、输出和一次性数据库 producer；
- 四套 live SQLite 及旁路文件；
- PostgreSQL dev/test dump 和原始试点 evidence；
- live-only addendum、aggregate manifest、schema audit、数据库行和备份；
- credentials、供应商 profile、内部用户内容与浏览器状态。

Git 外并不表示迁移审计忽略这些写路径。它们由文件哈希和去敏计数绑定到 addendum/aggregate evidence，真实路径和内容只在本地受控审计中保存。

## 既有公开风险

仓库仍公开暴露一部分内部目录结构、端口、迁移状态机、任务命名和运维合同。这些不是传统 secret，但会降低攻击者理解系统的成本，风险维持为中等。当前公开状态来自用户明确决定；本轮不擅自删除正式代码或改变功能。成为 production authority 前仍需完成公司控制权、最小权限、2FA、恢复和 deploy credential 治理。

## 提交前门禁

最终提交必须再次通过 tracked/staged inventory、secret/path/credential/large-file、Windows path、SQLite ratchet、OpenSpec strict、测试分层和 `git diff --check`。若出现疑似敏感项，应从 staged index 移除并 HALT，不能依赖本报告声明放行。
