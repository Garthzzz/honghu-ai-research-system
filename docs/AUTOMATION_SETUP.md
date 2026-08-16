# 动态情报自动化部署(E3)

> 当前状态（2026-08-16）：Stage 4 已获人工批准退出，九个 cutover unit 均为 durable S3，PostgreSQL 是唯一 production authority/writer；SQLite 只作 migration baseline/audit，不是失败回退后端。Stage 5 已获授权并正在实施七个任务的 VM runner、checkpoint、恢复和监控迁移，但尚未宣布完成。数据权威后端与唯一任务 runner 是两个独立状态；任务主机迁到 VM 不改变 PostgreSQL authority。正式边界见 `openspec/changes/github-vm-dual-node-operations/`。

scheduler 进程本身是短生命周期 tick，靠外部定时器每 15 分钟唤醒；核心业务调度状态主要在数据库，但运行正确性还依赖 runtime lock、checkpoint、segment heartbeat、API 限流状态、pagination offset 和部分可恢复 cache。因此不能把它描述成“全部状态都在数据库”的完全无状态任务。

## 当前任务事实、Stage 5 合同与历史说明

2026-08-16 Stage 5 启动时的只读复核显示，本地七个 `IndustryDemo_*` 任务全部为 `Disabled`，仍属于用户 `zhang` 的 Interactive 配置；DynamicTick、EventIngest、RecruitWeekly 最近结果为 `0`，三个 Retail 任务为 `0x2`，SentimentRetention 为 `0x800710E0`。这些是会变化的现场快照，不表示 VM 任务已经安装，也不能用 `Disabled`、进程退出码或任务状态替代 checkpoint、业务结果和 freshness 验证。2026-08-03 的 Ready/旧退出码仅是历史快照，已不再代表当前状态。

Stage 5 的正式声明入口是 `config/operations/production_tasks.json`，受 `tools/operations/task_manifest.py` 严格校验；统一 runner 是 `tools/operations/task_runner.py`，VM 安装入口是 `tools/operations/Provision-ProductionTaskRunner.ps1` 与 `tools/operations/Install-ProductionTasks.ps1`。安装必须绑定经过 CI 和人工批准的 immutable release、固定 Python 3.10 lock 环境、外置 runtime/data/content、非交互最小权限服务身份和 PostgreSQL task ledger。任务先 disabled 安装，真实试跑和对账通过后才可逐项启用；不得从 `PATH` 猜解释器，不得使用 live 项目目录作为可变代码根，不得在 PostgreSQL 失败时写回 SQLite，也不得让本地与 VM 同名任务同时启用。

本文后续章节保留各 producer 的业务窗口、来源、补漏和历史入口说明。出现 `research.db`、`sentiment.db` 或本地 cache 的段落描述的是历史物理实现或仍需外置的可恢复运行状态；Stage 5 production 写入必须通过已经处于 S3 的 PostgreSQL unit adapter。若正文与 canonical manifest、authority matrix 或 OpenSpec 冲突，以后三者为准。

## 1. Windows 任务计划程序挂 scheduler tick(每 15 分钟)
1. 任务计划程序 → 创建任务。
2. 触发器:周一至周五,重复间隔 **15 分钟**,持续到 20:00；周末不启动。
3. 操作:程序 `<python.exe 绝对路径>`,参数 `tools\dynamic\scheduler.py tick`,起始于 `D:\quant\industry_demo`。
4. 历史本地安装曾使用 Interactive 配置。Stage 5 VM 只能使用批准的非交互服务身份和统一 installer；不得用手工勾选、NSSM 或个人登录会话绕过 canonical manifest 与 task ledger。

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
一般动态源：`工作日任务计划器 → scheduler tick → run_fetch(event/news/voice subprocess) → ingest 去重 → relevance_classifier → ai_tagger → PostgreSQL dynamic_intelligence → viewer`。旧 `research.db` 行只作迁移基线/audit，不再接收 production task 写入。

微博 KOL：`工作日 scheduler → voice_ingest → 舆情 API（微博重点账号）→ 作者 UID 精确匹配 → PostgreSQL dynamic_intelligence voice_post → viewer`。该链路与散户情绪完全分离；散户域不再抓取、保存或计算微博。
AI 标注/事件前瞻本期为 CC session 版(grounded);`ANTHROPIC_API_KEY` 到位后切 API 版(接口一致)。

## 6. 散户情绪市场窗口 V2

公司页散户情绪不再使用每小时桶。Windows 本地时区按周一至周五执行三个任务：

- 10:00 `preopen`：前一交易日 16:00-24:00，加本交易日 00:00-09:30；两个片段分别请求，周末不请求。
- 14:00 `morning`：本交易日 09:30-13:00。
- 17:00 `afternoon`：本交易日 13:00-16:00。

以下 installer 仅是 SQLite 时代的兼容/历史入口，不得用于 Stage 5 VM production 安装：

```powershell
powershell -ExecutionPolicy Bypass -File tools\sentiment\install_retail_window_tasks.ps1
powershell -ExecutionPolicy Bypass -File tools\sentiment\install_retail_window_tasks.ps1 -Apply
```

`-Apply` 的历史行为会直接注册本地任务，因此迁移期间禁止执行。Stage 5 的 VM 定义只能由统一 installer 从 exact-release manifest 生成；它必须先 disabled 安装、保存 definition identity，并在受控试跑、checkpoint/freshness 对账和本地 Disabled 复核后逐任务启用。

手工只读审计/迁移入口：

```powershell
python -m tools.sentiment.migrate_retail_windows_v2
# 正式写 live 必须同时显式给出两个开关；执行前仍应按 BACKUP_REGISTRY 完成一致快照
python -m tools.sentiment.migrate_retail_windows_v2 --apply --allow-live
```

窗口台账只有在 guba、星瀚和公平评分均成功时才为 `complete`；guba 整窗成功返回 0 条时，第一次只记为待复核，第二次独立成功仍为 0 才确认合法空窗，失败请求不计次数，后续出现真实帖子会清除空窗确认。K 线失败会令 tick 返回非零并保留 source audit，但不会把完整的散户情绪证据降成不可用。`yuqing_feed_raw` 在公司归因前保存非微博平台的完整正文、作者、URL、post_id、来源状态与内容哈希，不保存 token/cookie/raw JSON；周末记录和微博记录均不请求、不落表。

星瀚 `subject/infos` 保持每分钟最多一次请求，生产间隔设为 65 秒。散户窗口显式请求 API 文档列出的非微博媒体类型，不再发 `mediaType=[4]` 专项，也不把全媒体结果中的微博分类、保存或计分。窗口分页、一次性 dump 和 KOL `KuaiSearchClient` 共用同一个账号级跨进程 state/lock；KOL 任务遇到窗口补抓占用令牌时不等待、不发真实请求，有旧缓存也明确返回 `cached_stale`。正式窗口按 `request_variant=all` 保存检查点；每页记录、公司归因和下一页 offset 在同一事务提交，重启后复用相同时间戳和精确 offset。单个 30 页块只是进程内安全边界，单片段最多 240 页，仍未闭合时保留 `partial` 供下次续跑。DeepSeek 批量 JSON 无效时只重试未成功行，最终仍失败的行保持 NULL，不伪造中性。

东财股吧通过官方 WAP `WebArticleList` JSON 接口按原帖发布时间倒序读取，并在一个窗口内复用 HTTP session；不再依赖会落入“身份核实”页的浏览器列表。接口页长固定为 50（更大页长会产生跨页重叠），生产深度从 `sentiment_layers.guba.pages_per_stock` 读取（当前安全上限为 128 页，可覆盖极活跃股票约 6400 帖）；逐页读取原帖发布时间，只有整页越过窗口起点才算完整，接口异常、空首页和达到页数上限仍未越界都会明确记为失败/`truncated`。置顶帖和跨页重复按 `post_id` 去重；瞬时 HTTP/接口异常会换新 session 重试一次，失败公司会结构化写入 run 结果。

三个窗口虽然使用三个 Windows Task Scheduler 任务名，但 `retail_window_tick.py` 仍须共享同一业务资源锁，并由 Stage 5 task runner 另加 task-level PostgreSQL advisory lock。前一窗口尚未结束时，后一窗口等待或延期，避免不同任务名绕过 `MultipleInstances` 后并发抓取或竞争写入 PostgreSQL `sentiment_analytics`。若父 tick 被系统强制终止但 Xinghan 子进程仍在分页，下一次取得锁的 tick 会先识别仍在推进的 segment/checkpoint 心跳并等待其收口；心跳停止或必需请求闭合后，才把遗留 `running` 状态如实收敛为 `partial/failed` 并重算草稿聚合，再执行当前窗口。

`IndustryDemo_SentimentRetention` 每个工作日 21:00 只做本地数据库维护，不请求外部服务。窗口聚合先保存三类标签数量、三类加权总量、平台分布、计算版本和哈希；完整窗口通过复算封存后即可删除逐帖正文、归属副本和窗口映射，不再设置固定 14 天等待期。`running`、存在 checkpoint、未封存以及默认的 `partial/failed` 窗口全部受保护。维护入口 `python -m tools.maintenance.sentiment_retention` 默认仅输出计划；只有显式 `--apply` 才逻辑清理。物理收缩必须另行停写、完成外部一致备份后，带 `--compact --apply --backup-confirmation <路径>` 人工执行。

每次 tick 先执行本次到期窗口，再自动扫描 `sentiment_layers.schedule.auto_backfill_start` 之后、最近 `backfill_max_days` 天内已经到期但尚未 `complete`、聚合计数矛盾或零数据尚未完成二次复核的窗口，并按时间从早到晚最多补 `backfill_max_windows_per_tick` 个。如果当前 tick 执行期间下一个 10:00/14:00/17:00 窗口已经到期，则跳过本轮历史回补并释放全局锁，让新的当前窗口先执行，避免历史缺口反过来阻塞当天时点。补跑只重试缺失、失败或数据审计不闭环的来源；已完成的股吧、星瀚、评分和 K 线不会重复调用，已确认的合法空窗也不会无限重抓。最终状态统一从 `retail_window_source_run` 和当前公平样本未评分数重新推导，先写状态再聚合，避免“评分已经存在但 ledger/usable 没有收口”。当前 live 起点为 2026-07-15；更早由历史 raw 映射产生的兼容 `pending` 行不会触发自动外抓。K 线仍是辅助来源：失败会令 tick 非零并在后续同窗口执行时重试，但不会把三个情绪来源已经闭环的窗口降为未完成。

K 线负载按窗口分层：10:00 对动态上市公司全集做日线与 90 天 60m 回填；14:00 只取 5 天 60m 增量；17:00 取 10 天日线与 5 天 60m 增量。相同 ticker 只请求一次再分发到公司，`delisted/unlisted/private/pre_ipo` 等客观无当前行情实体不进入动态池。港股五位交易所代码会在 Yahoo provider 边界转为四位代码，例如 `09888.HK` 转为 `9888.HK`；历史 `3324.TW` 转为 Yahoo 正确代码 `3324.TWO`。A 股日线优先使用 Tushare；yfinance 无法提供的 A 股当日 60 分钟线由 Tushare 官方 `rt_min` 多代码批量接口补齐，并在 source audit 中保留 fallback 状态。yfinance 日线即使非空也会校验所在市场本地时间下应有的最近工作日；发现滞后会用明确日期范围和 yfinance `repair` 再取一次并记录 warning。股票日线缺少/为零成交量的平线不入库，避免拆股停牌期的 Yahoo 伪 bar 污染股价轴。

公司身份以 PostgreSQL `shared_identity` 为 production canonical。旧 SQLite `research.db.company` 及 research/sentiment redirect/alias 表只保留 migration/legacy/audit 映射；K 线、情绪 raw/aggregate 和页面跳转统一到 PostgreSQL stable identity。Yahoo 的 `.SS`、港股四位代码等只允许存在于 provider 请求边界，权威身份始终保存规范 ticker/venue。

## 7. 招聘周任务

`IndustryDemo_RecruitWeekly` 固定在北京时间每周一 11:00 执行 `tools.sentiment.recruit_weekly`，依次抓取招聘页并更新新增/下架变化，再进行职能、领域和城市分类；production 只写 PostgreSQL `sentiment_analytics`。Windows 任务使用周一触发器，脚本内部继续保留周末静默门禁，迟到启动也不得在周末请求外部服务；child failure 必须向统一 runner 返回非零结果。
