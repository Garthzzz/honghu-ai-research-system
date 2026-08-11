# Stage 4 加速执行计划

## Milestone 0：冻结边界与独立复核

- [x] 读取活动 OpenSpec、live 快照和当前 Stage 4 实现。
- [x] 形成加速执行设计，明确 S1 与 S2/S3 禁线。
- [x] DeepSeek 对 recovery set、S1、批量 unit 推进和 bootstrap 边界做第一轮脱敏反驳；Codex 独立修订。

## Milestone 1：PR #9 收口与合并

- [x] 实现完整 off-VM recovery set、sentinel WAL replay、真实 measured RPO/RTO 和 storage identity。
- [x] 增加缺 WAL、WAL gap、manifest/hash 篡改、sentinel 缺失、same/fake host、copy mismatch 和 local-artifact 混用反例。
- [x] 重建 recovery/readiness evidence，修正最终 PR/governance identity binding。
- [ ] 完整本地/PG/边界/OpenSpec/CI 验收；合并 PR #9 并核验 main CI。

## Milestone 2：Production PostgreSQL 现场执行包

- [ ] 从 main 建立独立 execution branch。
- [ ] 建立单入口、幂等、fail-closed 的 Windows bootstrap 包及 deterministic tests。
- [ ] 建立 service/TLS/network/roles/credentials/health/backup/WAL/restore evidence 合同。
- [ ] 若有安全 VM 通道则执行；否则保留完整一次性现场包并继续后续独立工程。

## Milestone 3：各 unit migration-ready / S1

- [ ] `user_content_notes`：production S1 现场或完整可执行 S1 bundle。
- [ ] `shared_identity`
- [ ] `financial_data`
- [ ] `research_publication`
- [ ] `dynamic_intelligence`
- [ ] `operations_governance`
- [ ] `investment_hypotheses`
- [ ] `opportunity_lens`
- [ ] `sentiment_analytics`

每个 unit 都要冻结 owning objects/dependencies、migration SHA、ACL、source snapshot/watermark、stable mapping、backfill、delta catch-up、reconciliation、target watermark 和 evidence；依赖未关闭时标记 migration-ready，不伪称 production S1。

## Milestone 4：最终收口

- [ ] 压缩 mapping 人工异常清单并冻结 manifest/hash。
- [ ] 读取 GitHub 现场治理事实，区分机器确认与人类决定。
- [ ] 运行 final verifier、full core、targeted/browser、PG/recovery rehearsal、compile、OpenSpec strict、tracked/staged/secret/path、SQLite ratchet 和远端 CI。
- [ ] 提交一个 Stage 4 execution PR，完成 Codex + DeepSeek 最终复核。
- [ ] 输出 `READY FOR USER S2 DECISION` 或 `PRODUCTION READINESS BLOCKED` 后 HALT。
