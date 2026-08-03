# 阶段 2 实施与验收报告

> 状态：实施中，阶段 2 尚未获人工批准退出。本文只记录已经取得的证据；VM 只读并行候选未完成前，不得勾选阶段 2 HALT，也不得进入阶段 3。

## 1. 授权与隔离

- 用户已批准阶段 1 退出，只授权阶段 2 的 immutable release、本地 dev/test 边界、health/preflight、代码回滚和不切换生产的 VM 只读候选。
- 实施分支为 `phase2/repeatable-release`，隔离工作目录为 `D:\quant\industry_demo_stage1`。
- 活动目录 `D:\quant\industry_demo` 未切换分支、未 reset/clean；四套 live SQLite、七个计划任务和现有 Viewer 均未改动。
- PostgreSQL、生产数据后端切换、任务迁移、VM production deploy 和 production authority 均不在本阶段。

## 2. 已实现结构

```text
<deploy-root>/
├─ releases/<full-commit-sha>/   精确 Git commit 的不可变代码与 manifest
├─ current                       通过同目录临时文件和 os.replace 更新的 JSON 指针
└─ runtime/                      deployment ledger、PID、日志和候选证据

外部运行闭包：
├─ data-root/                    四套迁移期 SQLite；候选只读
├─ content-root/                 docs/industries 与 papers；候选只读
└─ state-root/                   可恢复 cache 和 runtime；可写但不进入 release
```

核心实现包括：

- `config/deployment_policy.json`：部署 allowlist 与外部 artifact closure；
- `config/release_schema_compatibility.json`：当前 SQLite 过渡期的兼容合同；
- `tools/release/manager.py` 与 `tools/release/cli.py`：精确 commit 构建、逐文件 SHA256、verify、preflight、activate、health 和 code-only rollback；
- `tools/runtime_paths.py`：保持历史默认路径，同时允许候选显式外置 data/content/state；
- `tools/release/dev_fixture.py`：不含生产记录、无需 VM 在线的本地合成 fixture；
- `tools/release/Deploy-ReadonlyCandidate.ps1`：独立候选根、独立端口、只读 smoke 和 VM 证据；
- Viewer candidate 全局阻断 `POST/PUT/PATCH/DELETE`，research/sentiment 连接使用 SQLite `mode=ro` 与 `query_only`。

同一 commit 的 manifest 不含构建时钟，使用 commit 元数据，因此不同干净目录构建得到相同 manifest hash。回滚前按目标 release 的 schema compatibility 合同重新检查，不能拿当前 release 的合同替代。

## 3. 本地和 clean-clone 证据

- 隔离工作目录完整核心测试：560 项收集，539 passed、21 skipped、53 subtests passed；21 项是已登记、需要受控研究 artifact 的集成测试，不属于 clean-clone 核心层。
- fresh clone `D:\quant\industry_demo_phase2_verify_7c8eca4` 精确检出 `7c8eca4d2d24ecc25c3e7fbae47015483d36ec14`，再次得到 539 passed、21 skipped、53 subtests passed。
- 本地 exact-commit evidence 对 `0fc2562c5a4c4a3fc0739f0ec2181dd1274e1ceb` 完成 preflight 和一次真实 code-only rollback，四个合成数据库的 SHA256 前后完全一致。
- staged/tracked boundary、secret/path/credential/large-file gate、Windows path gate、SQLite ratchet 和 `openspec validate --strict` 均通过。

## 4. 远端 CI 诊断记录

第一次 run `30855688524` 在 stage2 evidence 的脚本路径入口失败，真实根因为 `ModuleNotFoundError: tools`；改为 package module 入口，没有跳过测试。

第二次 run `30856246310` 的 clean-environment 通过，boundary job 仍失败。真实根因为该静态边界 job 没有安装应用依赖，而合成正式 schema fixture 需要 PyYAML。release evidence 已移动到按 `requirements.lock.txt` 安装依赖并运行核心测试的 `python-clean-environment` job；静态边界 job 不重复安装整套应用环境。

最新实现提交为 `f6788eb21d7bae6ae749feb07f6b863cbd00d46f`。远端 run `30856809650` 的 `boundary-and-contracts` 与 `python-clean-environment` 均为 success；后者完成 539 passed、21 skipped、53 subtests 后生成并上传 stage2 artifact。

该 artifact 已重新下载核验：release 包含 567 个文件、24,483,608 bytes，manifest SHA256 为 `f4608e2e73eaa6c095d1b667697d06f9893b821e5b1431711a423786e98d002d`，本地重算一致；绑定的 commit、run id、preflight、rollback ledger 和数据库哈希不变证据相互一致。

## 5. VM 只读候选

当前生产 `http://10.5.1.240:8080/api/health` 仍返回成功，release version 仍为既有广播版本；端口 18080 未监听，说明没有偷偷启动候选或切换生产。

本机到 VM 的 SSH、SMB 和 WinRM 管理通道均不可用，现有 Viewer 又没有获批的远程部署写入口。因此 Codex 不能在不绕过权限边界的情况下自行把候选落到 VM。`Deploy-ReadonlyCandidate.ps1` 已准备好，但必须由 VM 上的人工命令执行，或由用户提供已批准的只读候选部署通道。该项不是“已完成”，阶段 2 当前不能退出。

VM 验收必须取得：独立候选根、18080 health、commit/manifest/schema identity、`GET /tools=200`、写请求 `403`、数据库只读、8080 未切换、计划任务未改，以及候选 runtime evidence。

## 6. 当前结论

代码层、本地开发边界、clean clone、preflight 和 rollback 已形成可验证实现；远端 CI 与 VM 只读候选仍是剩余 gate。阶段 2 HALT 保持未批准，阶段 3 未开始。
