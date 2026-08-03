# 动态情报自动化部署(E3)

> 当前状态：本文记录现有本地/SQLite 任务部署事实，不授权 GitHub—PostgreSQL—VM 迁移。未来迁移必须分别记录“数据权威后端”和“唯一任务 runner”；任务主机从本地切到 VM 不等于数据后端切换，反之亦然。正式边界见 `openspec/changes/github-vm-dual-node-operations/`。

scheduler 进程本身是短生命周期 tick，靠外部定时器每 15 分钟唤醒；核心业务调度状态主要在数据库，但运行正确性还依赖 runtime lock、checkpoint、segment heartbeat、API 限流状态、pagination offset 和部分可恢复 cache。因此不能把它描述成“全部状态都在数据库”的完全无状态任务。

## 当前任务事实与目标配置

2026-08-03 第三轮只读复核显示，当前七个 `IndustryDemo_*` 任务仍全部使用 `InteractiveToken`、运行用户为 `zhang`，并混用 base 与 `quant` 解释器。复核时状态均为 Ready；最近结果为 DynamicTick/EventIngest/RecruitWeekly=`0`，三个 Retail 任务=`2`，SentimentRetention=`0x40010004`。这些是会变化的审计快照，Ready 不等于执行成功，迁移前必须重新读取任务定义、checkpoint 和真实数据效果。

下文“勾选不管用户是否登录都运行”是新建任务时的目标安装配置，不是当前七个任务已经达到的事实。GitHub—PostgreSQL—VM 迁移后的 production 目标是经批准的非交互、最小权限服务身份、固定解释器/lockfile、canonical task manifest 和可审计 checkpoint；本轮没有修改任何任务。

## 1. Windows 任务计划程序挂 scheduler tick(每 15 分钟)
1. 任务计划程序 → 创建任务。
2. 触发器:周一至周五,重复间隔 **15 分钟**,持续到 20:00；周末不启动。
3. 操作:程序 `<python.exe 绝对路径>`,参数 `tools\dynamic\scheduler.py tick`,起始于 `D:\quant\industry_demo`。
4. 目标安装时勾选「不管用户是否登录都运行」；现有任务仍是 Interactive，不能用本条说明反向证明已经配置完成。
（或用 NSSM 把 `python scheduler.py`(循环版)包成 Windows 服务。)

每 tick 只跑到点的 target（所有意见领袖统一在北京时间 09:00—17:00 每 60 分钟检查一次；17:00 后不再启动 KOL 抓取；news/event 沿用各自节奏），并发锁防重入，失败指数退避。代码入口另有上海时区周末静默门禁：即使任务被误触发，也不请求外部服务、不写失败告警、不累计错误。
`status=active` 表示最近一次来源检查成功；首次失败立即为 `error`，连续第三次失败才 `paused`；`is_running=1` 才表示当前正在执行。

## 2. 看日志
- 抓取日志:`cache/dynamic_fetch_log/<date>.log`(每 tick 一行 + 各 target 结果)
- 状态:`python tools\dynamic\scheduler.py status`(freq_actual / error_count / paused 高亮)

## 3. 处理 error / paused 的 leader
- 查 `cache/dynamic_alerts/<date>.md` 与 `cache/dynamic_fetch_log/<date>.log`。
- 微博 KOL 不登录微博、不使用访客流或 cookie，只调用舆情 API 的微博媒体类型和重点账号范围，再按 `opinion_leader.account_handle` 的 UID 精确匹配本人发言。API 返回其他作者、转述或仅提到该作者的内容不会入库。
- 顾文军、王一平和大才子与其他意见领袖一致，仅在北京时间 09:00—17:00 每 60 分钟检查一次；三人共享 15 分钟缓存和供应商每 65 秒一次的账号级限流。共享令牌正被窗口抓取占用时返回延期码 22，scheduler 释放锁并在下一 tick 重试，不累计错误。
- 认证、接口或作者匹配链路异常会传播为 scheduler `error/paused`；不能配置微博 cookie 绕过。正文被更完整版本替换时会清空旧 AI 派生字段并重新富化。
- X/雪球仍按各自现行 fetcher 处理登录态。修复后可按审批流程解除 paused；下一次成功会自动清空 `last_error` 并恢复 `active`。

## 4. 扩展(零改代码)
- **新意见领袖**:`config.yaml opinion_leaders` 加一行 + 跑 `seed_3a.py`(建 source+leader+schedule)。
- **新新闻源**:`config.yaml news_publishers` 加一行(含 rss)+ `seed_3a.py`。
- **新行业(产业链一环)**:`G3_vocab_queue.jsonl` 候选 → user 批准 → `INSERT INTO industry`(+ 可在 config.industry_color_groups / industry_tag_keywords 配色/别名)。
- **新大会**:`config.yaml conferences` 加一行 + `conference_loader.py`。
- 平台/频率/时区/突发簇/相关性关键词全在 `config.yaml`。

## 5. 数据流(全自动)
一般动态源：`工作日任务计划器 → scheduler tick → run_fetch(event/news/voice subprocess) → ingest 去重 → relevance_classifier → ai_tagger → research.db → viewer`。

微博 KOL：`工作日 scheduler → voice_ingest → 舆情 API（微博重点账号）→ 作者 UID 精确匹配 → research.db.voice_post → viewer`。该链路与散户情绪完全分离；散户库不再抓取、保存或计算微博。
AI 标注/事件前瞻本期为 CC session 版(grounded);`ANTHROPIC_API_KEY` 到位后切 API 版(接口一致)。

## 6. 散户情绪市场窗口 V2

公司页散户情绪不再使用每小时桶。Windows 本地时区按周一至周五执行三个任务：

- 10:00 `preopen`：前一交易日 16:00-24:00，加本交易日 00:00-09:30；两个片段分别请求，周末不请求。
- 14:00 `morning`：本交易日 09:30-13:00。
- 17:00 `afternoon`：本交易日 13:00-16:00。

安装器默认仅打印 dry-run，不会修改系统任务：

```powershell
powershell -ExecutionPolicy Bypass -File tools\sentiment\install_retail_window_tasks.ps1
powershell -ExecutionPolicy Bypass -File tools\sentiment\install_retail_window_tasks.ps1 -Apply
```

`-Apply` 会先注册周一至周五 10:30 执行的 `IndustryDemo_EventIngest`，再注册三个散户窗口任务。公告任务使用 `pythonw.exe` 后台运行，输出写入 `cache/sentiment/event_ingest.log`；它每次先抓取全量闭集公司的最新公告，再自动补判本轮和历史尚未评分的公告。公告任务不启用错过后补跑，避免电脑恢复时在错误时段执行；散户窗口仍启用 `StartWhenAvailable`。所有自动抓取周末静默，周一由各自既有补漏逻辑收口。全部任务注册成功后，安装器会删除任何残留的旧 `IndustryDemo_SentiTick`，避免旧入口被误启用。

手工只读审计/迁移入口：

```powershell
python -m tools.sentiment.migrate_retail_windows_v2
# 正式写 live 必须同时显式给出两个开关；执行前仍应按 BACKUP_REGISTRY 完成一致快照
python -m tools.sentiment.migrate_retail_windows_v2 --apply --allow-live
```

窗口台账只有在 guba、星瀚和公平评分均成功时才为 `complete`；guba 整窗成功返回 0 条时，第一次只记为待复核，第二次独立成功仍为 0 才确认合法空窗，失败请求不计次数，后续出现真实帖子会清除空窗确认。K 线失败会令 tick 返回非零并保留 source audit，但不会把完整的散户情绪证据降成不可用。`yuqing_feed_raw` 在公司归因前保存非微博平台的完整正文、作者、URL、post_id、来源状态与内容哈希，不保存 token/cookie/raw JSON；周末记录和微博记录均不请求、不落表。

星瀚 `subject/infos` 保持每分钟最多一次请求，生产间隔设为 65 秒。散户窗口显式请求 API 文档列出的非微博媒体类型，不再发 `mediaType=[4]` 专项，也不把全媒体结果中的微博分类、保存或计分。窗口分页、一次性 dump 和 KOL `KuaiSearchClient` 共用同一个账号级跨进程 state/lock；KOL 任务遇到窗口补抓占用令牌时不等待、不发真实请求，有旧缓存也明确返回 `cached_stale`。正式窗口按 `request_variant=all` 保存检查点；每页记录、公司归因和下一页 offset 在同一事务提交，重启后复用相同时间戳和精确 offset。单个 30 页块只是进程内安全边界，单片段最多 240 页，仍未闭合时保留 `partial` 供下次续跑。DeepSeek 批量 JSON 无效时只重试未成功行，最终仍失败的行保持 NULL，不伪造中性。

东财股吧通过官方 WAP `WebArticleList` JSON 接口按原帖发布时间倒序读取，并在一个窗口内复用 HTTP session；不再依赖会落入“身份核实”页的浏览器列表。接口页长固定为 50（更大页长会产生跨页重叠），生产深度从 `sentiment_layers.guba.pages_per_stock` 读取（当前安全上限为 128 页，可覆盖极活跃股票约 6400 帖）；逐页读取原帖发布时间，只有整页越过窗口起点才算完整，接口异常、空首页和达到页数上限仍未越界都会明确记为失败/`truncated`。置顶帖和跨页重复按 `post_id` 去重；瞬时 HTTP/接口异常会换新 session 重试一次，失败公司会结构化写入 run 结果。

三个窗口虽然使用三个 Windows Task Scheduler 任务名，但 `retail_window_tick.py` 会持有同一个项目级跨进程锁。前一窗口尚未结束时，后一窗口排队等待并在获得锁后补跑，避免不同任务名绕过 `MultipleInstances` 后并发抓取或竞争写入 `sentiment.db`。若父 tick 被系统强制终止但 Xinghan 子进程仍在分页，下一次取得锁的 tick 会先识别最近 10 分钟仍在推进的 segment/checkpoint 心跳并等待其收口，避免第二个进程交错使用相同 snapshot/offset；心跳停止或必需请求闭合后，才把遗留 `running` 状态如实收敛为 `partial/failed` 并重算草稿聚合，再执行当前窗口，不会长期伪装成仍在运行。

`IndustryDemo_SentimentRetention` 每个工作日 21:00 只做本地数据库维护，不请求外部服务。窗口聚合先保存三类标签数量、三类加权总量、平台分布、计算版本和哈希；完整窗口通过复算封存后即可删除逐帖正文、归属副本和窗口映射，不再设置固定 14 天等待期。`running`、存在 checkpoint、未封存以及默认的 `partial/failed` 窗口全部受保护。维护入口 `python -m tools.maintenance.sentiment_retention` 默认仅输出计划；只有显式 `--apply` 才逻辑清理。物理收缩必须另行停写、完成外部一致备份后，带 `--compact --apply --backup-confirmation <路径>` 人工执行。

每次 tick 先执行本次到期窗口，再自动扫描 `sentiment_layers.schedule.auto_backfill_start` 之后、最近 `backfill_max_days` 天内已经到期但尚未 `complete`、聚合计数矛盾或零数据尚未完成二次复核的窗口，并按时间从早到晚最多补 `backfill_max_windows_per_tick` 个。如果当前 tick 执行期间下一个 10:00/14:00/17:00 窗口已经到期，则跳过本轮历史回补并释放全局锁，让新的当前窗口先执行，避免历史缺口反过来阻塞当天时点。补跑只重试缺失、失败或数据审计不闭环的来源；已完成的股吧、星瀚、评分和 K 线不会重复调用，已确认的合法空窗也不会无限重抓。最终状态统一从 `retail_window_source_run` 和当前公平样本未评分数重新推导，先写状态再聚合，避免“评分已经存在但 ledger/usable 没有收口”。当前 live 起点为 2026-07-15；更早由历史 raw 映射产生的兼容 `pending` 行不会触发自动外抓。K 线仍是辅助来源：失败会令 tick 非零并在后续同窗口执行时重试，但不会把三个情绪来源已经闭环的窗口降为未完成。

K 线负载按窗口分层：10:00 对动态上市公司全集做日线与 90 天 60m 回填；14:00 只取 5 天 60m 增量；17:00 取 10 天日线与 5 天 60m 增量。相同 ticker 只请求一次再分发到公司，`delisted/unlisted/private/pre_ipo` 等客观无当前行情实体不进入动态池。港股五位交易所代码会在 Yahoo provider 边界转为四位代码，例如 `09888.HK` 转为 `9888.HK`；历史 `3324.TW` 转为 Yahoo 正确代码 `3324.TWO`。A 股日线优先使用 Tushare；yfinance 无法提供的 A 股当日 60 分钟线由 Tushare 官方 `rt_min` 多代码批量接口补齐，并在 source audit 中保留 fallback 状态。yfinance 日线即使非空也会校验所在市场本地时间下应有的最近工作日；发现滞后会用明确日期范围和 yfinance `repair` 再取一次并记录 warning。股票日线缺少/为零成交量的平线不入库，避免拆股停牌期的 Yahoo 伪 bar 污染股价轴。

公司身份以 `research.db.company` 为 canonical。重复公司合并后，research 的 `company_identity_redirect/company_identity_alias` 和 sentiment 的 `company_id_redirect/company_alias` 保留旧 ID、旧名与旧 ticker；K 线、情绪 raw/aggregate 和页面跳转统一到 canonical ID。Yahoo 的 `.SS`、港股四位代码等只允许存在于 provider 请求边界，数据库始终保存 research canonical ticker。

## 7. 招聘周任务

`IndustryDemo_RecruitWeekly` 固定在北京时间每周一 11:00 执行 `tools/sentiment/recruit_weekly.py`，依次抓取招聘页并更新新增/下架变化，再进行职能、领域和城市分类；只写 `sentiment.db`。Windows 任务使用周一触发器，脚本内部继续保留周末静默门禁，迟到启动也不得在周末请求外部服务。
