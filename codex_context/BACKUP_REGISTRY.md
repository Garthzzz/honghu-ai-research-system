# 项目备份注册表

> 迁移边界：本文件同时保留 SQLite/广播包时代的历史恢复事实，并登记当前 PostgreSQL S3 的脱敏恢复合同。PostgreSQL 已产生有效新写入，`backup/latest` 内的旧 SQLite 不是无损 production rollback target；当前生产恢复以经验证的 PostgreSQL base backup、目标 WAL、异机 recovery set 和旁路恢复 evidence 为准。

## SQLite 时代项目内长期备份（历史兼容）

- 固定位置：`D:\quant\industry_demo\backup\latest`
- 归档文件：`industry_demo_latest.zip`
- 版本说明：`BACKUP_INFO.md`
- 机器可验清单：`backup_manifest.json`
- 刷新工具：`python -m tools.maintenance.refresh_project_backup --version "<版本>" --reason "<原因>"`
- 外部旧备份清理：先运行 `python -m tools.maintenance.prune_external_project_backups`，核对清单后再加 `--apply`

`backup/latest` 是当前 SQLite/广播包生产时代项目内唯一长期保留的完整版本备份。清单记录版本、北京时间、创建原因、归档 SHA256、文件数、原始字节数以及四套 live SQLite 的快照哈希、完整性、外键和表数。归档内部另含 `BACKUP_CONTENT_MANIFEST.json`，用于逐文件恢复核验。这里“唯一”只约束当前项目目录的版本备份保留策略，不表示它是未来 PostgreSQL 的唯一灾备、跨故障域副本或 production authority。

当前 latest 的实际安装版本、创建时间、刷新原因、文件数、归档哈希与四库快照统一以 `backup/latest/backup_manifest.json` 为准；本注册表不再复制某次刷新时的版本号，避免后续原子刷新后出现静态说明滞后。

## 创建与替换规则

1. 大规模删除、迁移、数据库变更或目录瘦身前，先临时停用可能写库的任务。
2. 在 `D:\quant` 下建立名称包含 `industry_demo` 的临时外部安全副本；live SQLite 必须使用 backup API，且执行 `integrity_check` 与 `foreign_key_check`。该副本只服务于本次变更，不是长期版本库。
3. 文件清理必须先由 `tools/maintenance/project_artifacts.py` 生成显式清单，再由 `tools/maintenance/apply_project_cleanup.py` 逐批 dry-run/apply。数据库或 manifest 显式引用的文件不得删除；判断不充分的项保持 `pending_review`。
4. 完成代码、数据库和 Viewer 验收后运行刷新工具。工具先在项目外构建和验证新归档，再原子替换 `backup/latest`；构建失败不会主动覆盖旧 latest。
5. 确认安装后的归档 SHA256、ZIP CRC、成员清单以及四套数据库校验均通过后，使用 `tools.maintenance.prune_external_project_backups` 先 dry-run 再 `--apply`。该工具只匹配 `D:\quant` 直属、以当前项目名开头且名称含 backup/rollback 的目录，不会碰其他项目。最终只保留项目目录及项目内 `backup/latest`。

## 备份范围与恢复边界

备份覆盖当前项目代码、配置、文档、论文、研究产物、Funda 镜像、有效缓存及四套 live 数据库。以下内容明确不进入归档：

- `tools/dynamic/secrets/`：不读取、不复制密钥、cookie 或 storage state；
- `backup/`：避免递归备份；
- SQLite WAL/SHM/journal：四套 live DB 改用 backup API 的事务一致快照；
- `__pycache__`、`.pytest_cache`、pyc/pyo、`cache/viewer_debug.log`：均可再生成。

恢复前必须停止 Viewer 和全部可能写库的计划任务。不得把旧 WAL/SHM 与快照拼接；恢复四库后应重新执行 `integrity_check`、`foreign_key_check`、相关测试及只读 Viewer smoke，再恢复计划任务。

### 当前已经验证的能力

- 刷新、清理和清单工具路径仍存在：`refresh_project_backup`、`prune_external_project_backups`、`project_artifacts.py` 和 `apply_project_cleanup.py`；本轮只读核验未执行这些工具。
- `backup_manifest.json` 与归档内清单可验证归档 SHA256、ZIP CRC、成员列表和四套 SQLite backup API 快照的完整性/外键检查结果。
- 上述证据证明的是当前 SQLite 时代归档与快照的一致性材料，不等同于已经做过完整空机恢复、PostgreSQL restore、单域旁路恢复或 RPO/RTO 测量。

### 当前尚未证明的能力

- 现有记录没有证明 `backup/latest` 位于 Viewer/任务 VM 之外的独立故障域；`D:\quant` 下的临时副本也可能与源项目处于同一主机或存储故障域，只能作为变更前临时安全副本。
- 广播包是当前兼容部署与冷备材料，不是未来 live 数据权威，也不替代 PostgreSQL 备份、migration 版本和 papers/evidence 的独立恢复路径。
- “备份文件存在、哈希正确、SQLite integrity 通过”不能代替真实 restore test。恢复能力必须以隔离环境或空机恢复后的可运行、可对账结果为证据。

## PostgreSQL 目标恢复合同与迁移期角色

1. 在任何 production 数据切换前，按数据类别批准 target RPO/RTO，并据此选择 VM 外备份、备份频率、PITR 或部署拓扑；本注册表当前不写死这些参数。
2. 阶段 4 为每个 cutover unit 记录 migration baseline、cutover epoch、SQLite 最终业务水位、PostgreSQL 首条正式业务 commit 水位和恢复路径。S2 只有在停写、水位与审计共同证明没有必须保留的新写入并获人工批准时，旧 SQLite 才可能恢复 writer；uncertain response 无法证明未提交时按 S3。
3. S3/S4 中的旧 SQLite 只是迁移基线、审计档案和有限修复材料，不是无损回滚点；恢复优先使用 PostgreSQL 前向修复、schema 兼容的代码回滚、旁路恢复后选择性修复，或另行批准的显式反向迁移。
4. 最终生产迁移验收必须通过整库灾难恢复、单域旁路恢复和空机恢复取得 measured RPO/RTO，记录实际恢复点、耗时、未恢复数据、补抓及选择性修复耗时，并与目标对账。
5. 当前有效的 SQLite 恢复记录应原样保留为历史事实；未来 PostgreSQL 记录追加到本注册表时必须明确数据时代、验证范围和故障域，不能改写历史清单来伪装新能力已经存在。

## Stage 4 PostgreSQL 已验证恢复事实

> 本节记录脱敏后的恢复能力与 identity，不包含数据库、WAL、凭据、TLS 私钥、SMB credential 或原始 recovery evidence。

- 九个 cutover unit 已进入 S3，PostgreSQL 是唯一 authority/writer；旧 SQLite 仅为 migration baseline/audit，不能作为 production rollback target。
- 最终 post-S3 recovery set 位于批准的另一故障域，完整包含 base backup、目标 WAL、sentinel、manifest、逐文件 hash、source/storage identity 与恢复目标水位。
- restore 只使用异机 recovery set，whole-database、authority-control、side-domain restore 和九个 authority snapshot 对账均必须通过。
- 最终 recovery set identity：`5854c08a44b4b25d6a7ae6662f52ac89df263fd20d0110528d02482ee0072cc5`。
- 最终 recovery evidence 内容 identity：`06bea500760b96d4856e3f7bdc886a167c07f396f1ce18f227c45c3568a22ac2`；文件 SHA256：`b5148947baaa870917b64db8f266e526a6c63641797544a2281d3c3c089b9089`。
- Stage 4 单次恢复集结果：已验证 recovery-set target gap 为 0.007 秒、该目标的数据库 restore elapsed 为 8.047 秒；whole-database、authority-control、side-domain restore 均为 PASS，九个 formal unit authority snapshot 全部一致。0.007 秒不是任意生产故障时的持续 RPO，8.047 秒也不包含空机重建、凭据重新注入、应用/任务恢复和业务补抓。全系统 measured RPO/RTO 只能由 Stage 5 使用故障发生前已经异机持久化的 base/WAL 恢复链和空机演练测得。
- retention 最终只保留 `stage4-20260815T231501Z-aedb9d2e` 和 `stage4-20260815T185455Z-6b56b3aa` 两份完整验证集；最旧有效集及唯一未验证失败目录已分别按 retention 与独立 cleanup evidence 删除。
- 同 VM 的本机 backup/restore-test 目录只是构建和演练临时材料，不构成 off-VM 副本；最终验证完成后可按显式清单清理。
